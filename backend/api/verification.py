"""Verification workflow API endpoints."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.database import get_db
from backend.api.auth import get_current_user
from backend.models.user import User, RoleEnum
from backend.models.verification import VerificationCase, VerificationAction, VerificationStatus
from backend.models.discrepancy import Discrepancy
from backend.models.parcel import Parcel, ParcelDocument
from backend.models.document import Document
from backend.models.feedback import FeedbackSample

from backend.security.permissions import (
    VERIFICATION_CREATE,
    VERIFICATION_READ_OWN,
    VERIFICATION_READ_SCOPED,
    VERIFICATION_READ_ALL,
    VERIFICATION_REVIEW,
    VERIFICATION_CORRECT,
    VERIFICATION_APPROVE,
    VERIFICATION_REJECT,
    VERIFICATION_RETURN,
    VERIFICATION_OVERRIDE,
    user_has_permission,
)
from backend.security.jurisdiction import filter_cases_by_scope, is_resource_in_jurisdiction
from backend.security.authorization import (
    require_permission,
    check_verification_conflict,
    validate_workflow_transition,
    log_security_event,
)
from backend.security.field_versioning import (
    record_officer_correction,
    record_final_verification,
)
from backend.models.extraction import ExtractedField
from backend.models.ownership import Owner
from backend.services.normalization_service import normalize_area, normalize_name

logger = logging.getLogger("geoldger.api.verification")

router = APIRouter(prefix="/api/verification", tags=["Verification"])


class CreateCaseRequest(BaseModel):
    parcel_id: Optional[str] = None
    document_id: Optional[str] = None
    discrepancy_id: Optional[str] = None
    case_type: str
    priority: str = "medium"
    summary: Optional[str] = None


class VerificationActionRequest(BaseModel):
    action: str  # "approve", "correct", "reject", "comment", "return", "override"
    field_name: Optional[str] = None
    original_value: Optional[str] = None
    corrected_value: Optional[str] = None
    comment: Optional[str] = None
    reason: Optional[str] = None


def _sync_verified_field_to_parcel(db: Session, case: VerificationCase, field: ExtractedField, user: User) -> None:
    """Keep the parcel's current owner/area projections aligned with verified field values."""
    if not case.parcel_id or not field.value:
        return
    parcel = db.query(Parcel).filter(Parcel.id == case.parcel_id).first()
    if not parcel:
        return

    if field.field_name in ("owner_name", "new_owner"):
        normalized_name, _ = normalize_name(field.value)
        field.normalized_value = normalized_name or field.value
        parcel.current_owner = field.value
        for owner in db.query(Owner).filter(Owner.parcel_id == parcel.id).all():
            owner.is_current = "true" if owner.name == field.value else "false"
        current_owner = db.query(Owner).filter(
            Owner.parcel_id == parcel.id, Owner.name == field.value
        ).first()
        if current_owner is None:
            db.add(Owner(
                parcel_id=parcel.id,
                name=field.value,
                normalized_name=normalized_name or field.value,
                is_current="true",
                ownership_share="1.0",
                source_document_id=case.document_id,
                confidence=field.confidence,
            ))
    elif field.field_name == "area":
        unit_field = db.query(ExtractedField).filter(
            ExtractedField.document_id == field.document_id,
            ExtractedField.field_name == "area_unit",
        ).first()
        area_acres, _, _ = normalize_area(field.value, unit_field.value if unit_field else None)
        if area_acres is not None:
            field.normalized_value = str(area_acres)
            parcel.current_area = area_acres
            parcel.area_unit = "acres"


@router.post("/cases")
async def create_verification_case(
    data: CreateCaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(VERIFICATION_CREATE)),
):
    """Create a new verification case for adjudication workflow."""
    parcel = None
    if data.parcel_id:
        parcel = db.query(Parcel).filter(Parcel.id == data.parcel_id).first()
        if not parcel:
            raise HTTPException(status_code=404, detail="Parcel not found")
        from backend.security.authorization import authorize_parcel_access
        authorize_parcel_access(parcel, current_user, "read", db)

    doc = None
    if data.document_id:
        doc = db.query(Document).filter(Document.id == data.document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        from backend.security.authorization import authorize_document_access
        authorize_document_access(doc, current_user, "read", db)
        if not parcel:
            from backend.models.parcel import ParcelDocument
            pl = db.query(ParcelDocument).filter(ParcelDocument.document_id == doc.id).first()
            if pl:
                parcel = db.query(Parcel).filter(Parcel.id == pl.parcel_id).first()
        elif parcel:
            from backend.models.parcel import ParcelDocument
            pl = db.query(ParcelDocument).filter(
                ParcelDocument.document_id == doc.id,
                ParcelDocument.parcel_id == parcel.id,
            ).first()
            if not pl:
                raise HTTPException(status_code=400, detail="Selected document is not linked to the selected parcel")

    if data.discrepancy_id:
        discrepancy = db.query(Discrepancy).filter(Discrepancy.id == data.discrepancy_id).first()
        if not discrepancy:
            raise HTTPException(status_code=404, detail="Discrepancy not found")
        if discrepancy.parcel_id:
            discrepancy_parcel = db.query(Parcel).filter(Parcel.id == discrepancy.parcel_id).first()
            if discrepancy_parcel:
                from backend.security.authorization import authorize_parcel_access
                authorize_parcel_access(discrepancy_parcel, current_user, "read", db)
            if parcel and discrepancy.parcel_id != parcel.id:
                raise HTTPException(status_code=400, detail="Discrepancy does not belong to the selected parcel")
            if not parcel:
                parcel = discrepancy_parcel
        linked_doc_ids = {value for value in (discrepancy.document_a_id, discrepancy.document_b_id) if value}
        if doc and linked_doc_ids and doc.id not in linked_doc_ids:
            raise HTTPException(status_code=400, detail="Discrepancy does not reference the selected document")
        if not parcel and not doc and not linked_doc_ids:
            raise HTTPException(status_code=400, detail="Discrepancy is not linked to an accessible record")
        for linked_doc_id in linked_doc_ids:
            linked_doc = db.query(Document).filter(Document.id == linked_doc_id).first()
            if not linked_doc:
                raise HTTPException(status_code=404, detail="A document linked to the discrepancy was not found")
            from backend.security.authorization import authorize_document_access
            authorize_document_access(linked_doc, current_user, "read", db)

    if not parcel and not doc and not data.discrepancy_id:
        raise HTTPException(status_code=400, detail="A parcel, document, or discrepancy is required")

    resolved_parcel_id = parcel.id if parcel else data.parcel_id
    district = parcel.district if parcel else (doc.district if doc else None)
    tehsil = parcel.tehsil if parcel else (doc.tehsil if doc else None)
    village = parcel.village if parcel else (doc.village if doc else None)
    parcel_code = parcel.parcel_code if parcel else "UNBOUND"

    case = VerificationCase(
        parcel_id=resolved_parcel_id,
        document_id=data.document_id,
        discrepancy_id=data.discrepancy_id,
        case_type=data.case_type,
        priority=data.priority,
        status=VerificationStatus.PENDING,
        summary=data.summary or f"{data.case_type} verification required",
        submitted_by=current_user.id,
        district=district,
        tehsil=tehsil,
        village=village,
        assigned_to=None,
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    log_security_event(
        db=db,
        user=current_user,
        action="VERIFICATION_CASE_CREATED",
        resource_type="verification_case",
        resource_id=case.id,
        details=f"Created case {case.case_type} for parcel {parcel_code}",
    )

    logger.info(f"Created verification case {case.id[:8]} for parcel {parcel_code} by {current_user.username}")

    return {
        "id": case.id,
        "parcel_id": case.parcel_id,
        "document_id": case.document_id,
        "case_type": case.case_type,
        "status": case.status.value,
        "priority": case.priority,
        "summary": case.summary,
        "district": case.district,
        "tehsil": case.tehsil,
    }


@router.get("/cases")
async def list_verification_cases(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    assigned_to_me: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List verification cases with strict role and jurisdiction scoping."""
    query = db.query(VerificationCase)

    if status:
        try:
            status_enum = VerificationStatus(status)
            query = query.filter(VerificationCase.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if priority:
        query = query.filter(VerificationCase.priority == priority)

    if assigned_to_me:
        query = query.filter(VerificationCase.assigned_to == current_user.id)

    # Scoping filter
    scoped_query = filter_cases_by_scope(query, current_user, db)
    cases = scoped_query.order_by(VerificationCase.created_at.desc()).offset(offset).limit(limit).all()

    return [
        {
            "id": c.id,
            "parcel_id": c.parcel_id,
            "case_type": c.case_type,
            "priority": c.priority,
            "status": c.status.value,
            "summary": c.summary,
            "assigned_to": c.assigned_to,
            "district": c.district,
            "tehsil": c.tehsil,
            "submitted_by": c.submitted_by,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in cases
    ]


@router.get("/cases/{case_id}")
async def get_verification_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed verification case with related data and access validation."""
    case = db.query(VerificationCase).filter(VerificationCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Access authorization check
    if current_user.is_citizen:
        # Citizen can only view cases they submitted
        if case.submitted_by not in (current_user.id, current_user.username):
            raise HTTPException(status_code=403, detail="Access denied: You can only view verification cases submitted by your account.")
    elif current_user.is_revenue_officer:
        # Officer must be within jurisdiction or assigned
        in_scope = is_resource_in_jurisdiction(
            user=current_user,
            district=case.district,
            tehsil=case.tehsil,
            village=case.village,
            db=db,
        )
        if not in_scope and case.assigned_to != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied: Verification case belongs to another jurisdiction.")

    # Get related discrepancy if exists
    discrepancy = None
    if case.discrepancy_id:
        disc = db.query(Discrepancy).filter(Discrepancy.id == case.discrepancy_id).first()
        if disc:
            discrepancy = {
                "id": disc.id,
                "type": disc.discrepancy_type.value if hasattr(disc.discrepancy_type, "value") else str(disc.discrepancy_type),
                "severity": disc.severity.value if hasattr(disc.severity, "value") else str(disc.severity),
                "field_name": disc.field_name,
                "value_a": disc.value_a,
                "value_b": disc.value_b,
                "reason": disc.reason,
            }

    # Get actions history
    actions = db.query(VerificationAction).filter(VerificationAction.case_id == case_id).order_by(VerificationAction.created_at.desc()).all()

    return {
        "id": case.id,
        "parcel_id": case.parcel_id,
        "document_id": case.document_id,
        "case_type": case.case_type,
        "priority": case.priority,
        "status": case.status.value,
        "summary": case.summary,
        "assigned_to": case.assigned_to,
        "district": case.district,
        "tehsil": case.tehsil,
        "submitted_by": case.submitted_by,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "discrepancy": discrepancy,
        "actions": [
            {
                "id": a.id,
                "action": a.action,
                "field_name": a.field_name,
                "original_value": a.original_value,
                "corrected_value": a.corrected_value,
                "comment": a.comment,
                "reason": a.reason,
                "user_id": a.user_id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in actions
        ],
    }


@router.post("/cases/{case_id}/actions")
async def add_verification_action(
    case_id: str,
    data: VerificationActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Execute a verification workflow action: approve, correct, reject, return, comment, override.
    Enforces:
    - Citizen prevention (403)
    - Conflict of interest (Uploader != Verifier)
    - Jurisdiction scoping
    - State machine lifecycle transition
    - Field versioning (RAW OCR -> AI EXTRACTION -> OFFICER CORRECTION -> FINAL VERIFIED VALUE)
    - Complete immutable audit trail
    """
    case = db.query(VerificationCase).filter(VerificationCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    action_name = data.action.strip().lower()

    action_permissions = {
        "approve": VERIFICATION_APPROVE, "verified": VERIFICATION_APPROVE,
        "correct": VERIFICATION_CORRECT, "corrected": VERIFICATION_CORRECT,
        "reject": VERIFICATION_REJECT, "rejected": VERIFICATION_REJECT,
        "return": VERIFICATION_RETURN, "needs_more_evidence": VERIFICATION_RETURN,
        "comment": VERIFICATION_REVIEW, "review": VERIFICATION_REVIEW, "claim": VERIFICATION_REVIEW,
        "override": VERIFICATION_OVERRIDE,
    }
    required_permission = action_permissions.get(action_name)
    if not required_permission:
        raise HTTPException(status_code=400, detail="Unsupported verification action.")
    if not user_has_permission(current_user, required_permission):
        log_security_event(
            db=db,
            user=current_user,
            action="VERIFICATION_PERMISSION_DENIED",
            resource_type="verification_case",
            resource_id=case_id,
            result="DENIED",
            reason=f"Missing required permission: {required_permission}",
        )
        raise HTTPException(status_code=403, detail="Your role is not authorized to perform this verification action.")

    # 1. Citizen cannot adjudicate
    if current_user.is_citizen:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: Citizens are strictly prohibited from adjudicating or altering official verification decisions.",
        )

    # 2. Conflict of interest enforcement (Section 11: Uploader != Verifier)
    check_verification_conflict(case, current_user, db)

    # 3. Jurisdiction enforcement for Revenue Officers
    if current_user.is_revenue_officer:
        in_scope = is_resource_in_jurisdiction(
            user=current_user,
            district=case.district,
            tehsil=case.tehsil,
            village=case.village,
            db=db,
        )
        if not in_scope and case.assigned_to != current_user.id:
            log_security_event(
                db=db,
                user=current_user,
                action="JURISDICTION_VIOLATION_BLOCKED",
                resource_type="verification_case",
                resource_id=case_id,
                result="DENIED",
                reason=f"Officer {current_user.username} tried to adjudicate case outside jurisdiction ({case.district}/{case.tehsil})",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Case is situated in {case.district or 'another jurisdiction'}, outside your authorized operational area.",
            )

    association_target = None
    if case.case_type == "parcel_association_review":
        if action_name in ("approve", "verified", "override"):
            raise HTTPException(status_code=400, detail="A parcel association must be explicitly corrected or rejected; it cannot be approved without a target parcel.")
        if action_name in ("correct", "corrected"):
            if data.field_name != "parcel_id" or not data.corrected_value or not case.document_id:
                raise HTTPException(status_code=400, detail="Select a target parcel ID or parcel code to confirm this association.")
            association_target = db.query(Parcel).filter(
                (Parcel.id == data.corrected_value.strip()) | (Parcel.parcel_code == data.corrected_value.strip())
            ).first()
            if not association_target:
                raise HTTPException(status_code=404, detail="Target parcel was not found.")
            document = db.query(Document).filter(Document.id == case.document_id).first()
            if not document:
                raise HTTPException(status_code=404, detail="Source document was not found.")
            from backend.security.authorization import authorize_document_access, authorize_parcel_access
            authorize_document_access(document, current_user, "read", db)
            authorize_parcel_access(association_target, current_user, "read", db)

    # 4. Workflow State Transition Validation
    validate_workflow_transition(case, action_name, current_user, reason=data.reason or data.comment)

    # 5. Create action record
    action = VerificationAction(
        case_id=case_id,
        user_id=current_user.id,
        action=action_name,
        field_name=data.field_name,
        original_value=data.original_value,
        corrected_value=data.corrected_value,
        comment=data.comment,
        reason=data.reason,
    )
    db.add(action)

    # 6. Apply state transition & Field-level versioning
    if action_name in ("approve", "verified"):
        case.status = VerificationStatus.VERIFIED
        # If field specified, finalize verification
        if data.field_name and case.document_id:
            field = db.query(ExtractedField).filter(
                ExtractedField.document_id == case.document_id,
                ExtractedField.field_name == data.field_name,
            ).first()
            if field:
                final_field = record_final_verification(db, field, field.value, current_user, reason=data.comment)
                _sync_verified_field_to_parcel(db, case, final_field, current_user)

    elif action_name in ("correct", "corrected"):
        case.status = VerificationStatus.CORRECTED
        if case.case_type == "parcel_association_review" and association_target:
            existing_link = db.query(ParcelDocument).filter(
                ParcelDocument.parcel_id == association_target.id,
                ParcelDocument.document_id == case.document_id,
            ).first()
            if not existing_link:
                db.add(ParcelDocument(
                    parcel_id=association_target.id,
                    document_id=case.document_id,
                    relationship_type="primary",
                    linked_by=current_user.id,
                ))
            case.parcel_id = association_target.id
        # Complete Data Versioning: Preserve RAW OCR and record correction
        if data.field_name and data.field_name != "parcel_id" and case.document_id and data.corrected_value:
            field = db.query(ExtractedField).filter(
                ExtractedField.document_id == case.document_id,
                ExtractedField.field_name == data.field_name,
            ).first()
            if field:
                corrected_field = record_officer_correction(
                    db=db,
                    field=field,
                    new_value=data.corrected_value,
                    officer=current_user,
                    reason=data.comment or data.reason,
                )
                _sync_verified_field_to_parcel(db, case, corrected_field, current_user)

        # Also store FeedbackSample for AI model alignment
        if data.field_name and data.field_name != "parcel_id" and data.original_value and data.corrected_value:
            feedback = FeedbackSample(
                document_id=case.document_id,
                field_name=data.field_name,
                ai_extracted_value=data.original_value,
                human_corrected_value=data.corrected_value,
                reviewer_id=current_user.id,
                is_used_for_training="false",
            )
            db.add(feedback)

    elif action_name in ("reject", "rejected"):
        case.status = VerificationStatus.REJECTED
    elif action_name in ("return", "needs_more_evidence"):
        case.status = VerificationStatus.NEEDS_MORE_EVIDENCE
    elif action_name in ("comment", "review", "claim"):
        case.status = VerificationStatus.IN_REVIEW
        case.assigned_to = current_user.id
    elif action_name == "override":
        # Admin override
        case.status = VerificationStatus.VERIFIED

    db.commit()

    # 7. Comprehensive Audit Log
    log_security_event(
        db=db,
        user=current_user,
        action=f"VERIFICATION_{action_name.upper()}",
        resource_type="verification_case",
        resource_id=case.id,
        reason=data.reason or data.comment,
        details=f"Officer {current_user.username} executed {action_name} -> status: {case.status.value}",
    )

    logger.info(f"User {current_user.username} performed '{action_name}' on case {case_id[:8]} (Status: {case.status.value})")

    return {
        "status": "success",
        "case_id": case.id,
        "action": action_name,
        "new_case_status": case.status.value,
    }


@router.get("/feedback/samples")
async def list_feedback_samples(
    field_name: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List human correction feedback samples for AI improvement."""
    if current_user.role != RoleEnum.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")

    query = db.query(FeedbackSample)

    if field_name:
        query = query.filter(FeedbackSample.field_name == field_name)

    samples = query.order_by(FeedbackSample.created_at.desc()).offset(offset).limit(limit).all()

    return [
        {
            "id": s.id,
            "field_name": s.field_name,
            "ai_extracted": s.ai_extracted_value,
            "human_corrected": s.human_corrected_value,
            "document_id": s.document_id,
            "reviewer_id": s.reviewer_id,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in samples
    ]
