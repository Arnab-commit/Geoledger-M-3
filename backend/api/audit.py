"""Audit trail and analytics API endpoints."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import get_db
from backend.api.auth import get_current_user
from backend.models.user import User, RoleEnum
from backend.models.audit import AuditLog
from backend.models.document import Document
from backend.models.parcel import Parcel
from backend.models.verification import VerificationCase, VerificationStatus
from backend.models.discrepancy import Discrepancy, Severity
from backend.models.extraction import ExtractedField
from backend.models.ocr import OcrResult
from backend.security.jurisdiction import filter_documents_by_scope, filter_parcels_by_scope, filter_cases_by_scope

logger = logging.getLogger("geoldger.api.audit")

router = APIRouter(prefix="/api/audit", tags=["Audit"])


@router.get("/logs")
async def get_audit_logs(
    entity_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve audit trail logs with strict role and jurisdiction scoping."""
    query = db.query(AuditLog)

    # Scoping enforcement
    if current_user.is_citizen:
        # Citizens strictly restricted to their own audit events
        query = query.filter(AuditLog.user_id == current_user.id)
        if user_id and user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied: Citizens can only inspect their own audit events.")
    elif current_user.is_revenue_officer:
        # Officer: Can see own actions or actions within their scoped jurisdiction
        from backend.security.jurisdiction import get_user_jurisdictions
        jurisdictions = get_user_jurisdictions(current_user, db)
        jurisdiction_names = [j.district for j in jurisdictions if j.district] + [j.tehsil for j in jurisdictions if j.tehsil]

        # Scope by user_id or jurisdiction keywords in details
        scope_conditions = [AuditLog.user_id == current_user.id]
        for j_name in jurisdiction_names:
            scope_conditions.append(AuditLog.details.ilike(f"%{j_name}%"))

        from sqlalchemy import or_
        query = query.filter(or_(*scope_conditions))
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
    else:
        # Admin or Auditor: Global access
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)

    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))

    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "logs": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "user_name": log.user.username if log.user else "System",
                "actor_role": log.actor_role or (log.user.canonical_role if log.user else "SYSTEM"),
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "result": log.result or "SUCCESS",
                "reason": log.reason,
                "details": log.details,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }


@router.get("/stats")
async def get_system_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get system-wide metrics for dashboard."""
    scoped_documents = filter_documents_by_scope(db.query(Document), current_user, db)
    scoped_parcels = filter_parcels_by_scope(db.query(Parcel), current_user, db)
    scoped_cases = filter_cases_by_scope(db.query(VerificationCase), current_user, db)
    doc_count = scoped_documents.count()
    parcel_count = scoped_parcels.count()

    pending_cases = scoped_cases.filter(
        VerificationCase.status.in_([VerificationStatus.PENDING, VerificationStatus.IN_REVIEW])
    ).count()

    verified_cases = scoped_cases.filter(
        VerificationCase.status == VerificationStatus.VERIFIED
    ).count()

    scoped_parcel_ids = scoped_parcels.with_entities(Parcel.id).subquery()
    scoped_discrepancies = db.query(Discrepancy).filter(Discrepancy.parcel_id.in_(scoped_parcel_ids))
    discrepancy_count = scoped_discrepancies.count()
    high_risk_discrepancies = scoped_discrepancies.filter(
        Discrepancy.severity.in_([Severity.HIGH, Severity.CRITICAL])
    ).count()

    # Average OCR Confidence (measured confidence score across OCR blocks)
    scoped_document_ids = scoped_documents.with_entities(Document.id).subquery()
    avg_ocr = db.query(func.avg(OcrResult.confidence)).filter(OcrResult.document_id.in_(scoped_document_ids)).scalar()
    avg_ocr_val = round(float(avg_ocr) * 100, 1) if avg_ocr is not None else 0.0

    # Average Extraction Confidence (measured confidence score across extracted fields)
    avg_extract = db.query(func.avg(ExtractedField.confidence)).filter(ExtractedField.document_id.in_(scoped_document_ids)).scalar()
    avg_extract_val = round(float(avg_extract) * 100, 1) if avg_extract is not None else 0.0

    return {
        "documents_count": doc_count,
        "parcels_count": parcel_count,
        "pending_verifications": pending_cases,
        "verified_records": verified_cases,
        "total_discrepancies": discrepancy_count,
        "high_risk_discrepancies": high_risk_discrepancies,
        "avg_ocr_confidence": avg_ocr_val,
        "avg_extraction_confidence": avg_extract_val,
        "avg_processing_time": _average_processing_time(scoped_documents),
    }


def _average_processing_time(document_query):
    """Compute a real average duration from completed documents with timestamps."""
    durations = []
    for uploaded_at, processed_at in document_query.with_entities(
        Document.upload_timestamp, Document.processed_at
    ).filter(Document.processed_at.is_not(None)).all():
        if uploaded_at and processed_at:
            durations.append(max(0.0, (processed_at - uploaded_at).total_seconds()))
    if not durations:
        return None
    return f"{sum(durations) / len(durations):.1f}s"
