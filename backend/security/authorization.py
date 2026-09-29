"""GeoLedger — Resource-Level Authorization and Workflow Security Engine.

Enforces:
1. Identity & Role Verification
2. Granular Permission Checks
3. Resource Ownership Checks (IDOR / BOLA Prevention)
4. Geographic Jurisdiction Scoping
5. Conflict of Interest Prevention (Uploader != Verifier)
6. State Machine Workflow Transitions
7. Immutable Security Auditing
"""

import logging
from typing import Optional, Callable
from fastapi import HTTPException, status, Depends
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.database import get_db
from backend.api.auth import get_current_user
from backend.models.user import User, RoleEnum
from backend.models.document import Document
from backend.models.parcel import Parcel, ParcelDocument
from backend.models.verification import VerificationCase, VerificationStatus
from backend.models.audit import AuditLog
from backend.security.permissions import (
    user_has_permission,
    DOCUMENTS_READ_ALL,
    DOCUMENTS_READ_SCOPED,
    DOCUMENTS_READ_OWN,
    PARCELS_READ_ALL,
    PARCELS_READ_SCOPED,
    PARCELS_READ_OWN,
    VERIFICATION_APPROVE,
    VERIFICATION_REJECT,
    VERIFICATION_CORRECT,
    VERIFICATION_OVERRIDE,
)
from backend.security.jurisdiction import is_resource_in_jurisdiction

logger = logging.getLogger("geoldger.security.authorization")


def log_security_event(
    db: Session,
    user: Optional[User],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    result: str = "SUCCESS",
    reason: Optional[str] = None,
    details: Optional[str] = None,
    ip_address: Optional[str] = None,
):
    """Log security-relevant access decisions and violations."""
    try:
        entry = AuditLog(
            user_id=user.id if user else None,
            actor_role=user.canonical_role if user else "ANONYMOUS",
            action=action,
            entity_type=resource_type,
            entity_id=resource_id,
            result=result,
            reason=reason,
            details=details,
            ip_address=ip_address,
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to record security audit log: {e}")
        db.rollback()


def require_permission(permission: str) -> Callable:
    """FastAPI dependency factory: require a specific granular permission."""
    def permission_checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not user_has_permission(current_user, permission):
            log_security_event(
                db=db,
                user=current_user,
                action="PERMISSION_DENIED",
                result="DENIED",
                reason=f"Missing required permission: '{permission}'",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: You do not possess the required permission '{permission}'.",
            )
        return current_user
    return permission_checker


def authorize_document_access(
    document: Document,
    user: User,
    action: str = "read",
    db: Session = None,
) -> Document:
    """
    Validate that the authenticated user is authorized to access or modify this specific document.
    Prevents IDOR: Citizens can only access documents they uploaded.
    Officers can only access documents within their jurisdiction.
    """
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Admins and Auditors have global read/access
    if user.is_admin or user.canonical_role == RoleEnum.AUDITOR.value:
        return document

    # Ownership check: If citizen or officer uploaded this document, they have ownership access
    is_owner = (
        (document.uploader_id and document.uploader_id == user.id) or
        (document.uploaded_by and document.uploaded_by == user.username)
    )

    if is_owner:
        return document

    # Non-owner Citizen: STRICT DENIAL (IDOR prevention)
    if user.is_citizen:
        log_security_event(
            db=db,
            user=user,
            action="IDOR_ATTEMPT_BLOCKED",
            resource_type="document",
            resource_id=document.id,
            result="DENIED",
            reason="Citizen attempted to access document belonging to another user",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to view or access this document.",
        )

    # Revenue Officer: Jurisdiction scope check
    if user.is_revenue_officer:
        # Check document's own jurisdiction fields
        doc_state = document.state
        doc_district = document.district
        doc_tehsil = document.tehsil
        doc_village = document.village

        # If document has no explicit jurisdiction metadata, check linked parcels
        if not (doc_state or doc_district) and db:
            linked_parcel_doc = db.query(ParcelDocument).filter(ParcelDocument.document_id == document.id).first()
            if linked_parcel_doc and linked_parcel_doc.parcel:
                doc_state = linked_parcel_doc.parcel.state
                doc_district = linked_parcel_doc.parcel.district
                doc_tehsil = linked_parcel_doc.parcel.tehsil
                doc_village = linked_parcel_doc.parcel.village

        # Check against officer's scope
        in_scope = is_resource_in_jurisdiction(
            user=user,
            state=doc_state,
            district=doc_district,
            tehsil=doc_tehsil,
            village=doc_village,
            db=db,
        )

        if in_scope:
            return document

        log_security_event(
            db=db,
            user=user,
            action="JURISDICTION_VIOLATION_BLOCKED",
            resource_type="document",
            resource_id=document.id,
            result="DENIED",
            reason=f"Officer {user.username} tried to access document outside authorized jurisdiction ({doc_district}/{doc_tehsil})",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: This document belongs to a jurisdiction outside your authorized operational area.",
        )

    raise HTTPException(status_code=403, detail="Access denied")


def authorize_parcel_access(
    parcel: Parcel,
    user: User,
    action: str = "read",
    db: Session = None,
) -> Parcel:
    """
    Validate that the authenticated user is authorized to access or modify this parcel.
    Citizens: Only parcels they own or that are linked to their uploaded deeds.
    Officers: Only parcels in their jurisdiction.
    """
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")

    if user.is_admin or user.canonical_role == RoleEnum.AUDITOR.value:
        return parcel

    if user.is_citizen:
        # Check ownership or linked documents
        is_owner = False
        if parcel.current_owner:
            owner_lower = parcel.current_owner.lower()
            if user.full_name.lower() in owner_lower or user.username.lower() in owner_lower:
                is_owner = True

        if not is_owner and db:
            # Check if any document uploaded by user is linked to this parcel
            linked = db.query(ParcelDocument).join(Document, ParcelDocument.document_id == Document.id).filter(
                ParcelDocument.parcel_id == parcel.id,
                or_(
                    Document.uploader_id == user.id,
                    Document.uploaded_by == user.username,
                )
            ).first()
            if linked:
                is_owner = True

        if is_owner:
            return parcel

        log_security_event(
            db=db,
            user=user,
            action="UNAUTHORIZED_PARCEL_ACCESS",
            resource_type="parcel",
            resource_id=parcel.id,
            result="DENIED",
            reason="Citizen attempted to access parcel without verified ownership or linked deed",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have ownership or statutory authorization for this land parcel.",
        )

    if user.is_revenue_officer:
        in_scope = is_resource_in_jurisdiction(
            user=user,
            state=parcel.state,
            district=parcel.district,
            tehsil=parcel.tehsil,
            village=parcel.village,
            db=db,
        )
        if in_scope:
            return parcel

        log_security_event(
            db=db,
            user=user,
            action="JURISDICTION_VIOLATION_BLOCKED",
            resource_type="parcel",
            resource_id=parcel.id,
            result="DENIED",
            reason=f"Officer {user.username} tried to access parcel outside jurisdiction ({parcel.district}/{parcel.tehsil})",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Parcel '{parcel.parcel_code}' is situated outside your authorized jurisdiction ({parcel.district or 'Unknown District'}).",
        )

    raise HTTPException(status_code=403, detail="Access denied")


def check_verification_conflict(
    case: VerificationCase,
    user: User,
    db: Session,
):
    """
    CRITICAL SECTION 11: Verification Conflict of Interest Prevention.
    At minimum: Uploader != Verifier.
    A user can never verify, approve, reject, or alter adjudication for their own record,
    unless an explicitly authorized administrative exception exists.
    """
    # Section 11 & 21: Controlled administrative exception for administrators
    if user.is_admin:
        log_security_event(
            db=db,
            user=user,
            action="ADMIN_VERIFICATION_EXCEPTION",
            resource_type="verification_case",
            resource_id=case.id,
            details="Administrative supervisory adjudication permitted under controlled exception",
        )
        return

    # 1. Check if user is the case submitter
    if case.submitted_by and (case.submitted_by == user.id or case.submitted_by == user.username):
        log_security_event(
            db=db,
            user=user,
            action="VERIFICATION_CONFLICT_BLOCKED",
            resource_type="verification_case",
            resource_id=case.id,
            result="CONFLICT_BLOCKED",
            reason="User attempted to adjudicate verification case submitted by themselves",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conflict of Interest: You cannot adjudicate, approve, or verify a case submitted by your own account.",
        )

    # 2. Check linked document uploaders
    if case.document_id:
        doc = db.query(Document).filter(Document.id == case.document_id).first()
        if doc and ((doc.uploader_id and doc.uploader_id == user.id) or (doc.uploaded_by and doc.uploaded_by == user.username)):
            log_security_event(
                db=db,
                user=user,
                action="VERIFICATION_CONFLICT_BLOCKED",
                resource_type="verification_case",
                resource_id=case.id,
                result="CONFLICT_BLOCKED",
                reason=f"User {user.username} attempted to verify case linked to deed they uploaded (doc {doc.id[:8]})",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Conflict of Interest: You cannot verify or adjudicate land records for documents uploaded by your own account.",
            )

    # 3. Check parcel documents uploaders
    if case.parcel_id:
        parcel_docs = db.query(Document).join(ParcelDocument, Document.id == ParcelDocument.document_id).filter(
            ParcelDocument.parcel_id == case.parcel_id,
            or_(
                Document.uploader_id == user.id,
                Document.uploaded_by == user.username,
            )
        ).all()
        if parcel_docs:
            log_security_event(
                db=db,
                user=user,
                action="VERIFICATION_CONFLICT_BLOCKED",
                resource_type="verification_case",
                resource_id=case.id,
                result="CONFLICT_BLOCKED",
                reason=f"User {user.username} uploaded deeds linked to parcel {case.parcel_id}",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Conflict of Interest: You have uploaded deeds linked to this parcel and cannot act as adjudicating officer.",
            )


def validate_workflow_transition(
    case: VerificationCase,
    action: str,
    user: User,
    reason: Optional[str] = None,
):
    """
    CRITICAL SECTION 5: State Machine Enforcement for Verification Workflow.
    Allowed transitions:
    - CITIZEN: CANNOT perform verification actions.
    - OFFICER:
        - PENDING -> IN_REVIEW (claim / comment)
        - IN_REVIEW / PENDING -> VERIFIED (approve)
        - IN_REVIEW / PENDING -> CORRECTED (correct)
        - IN_REVIEW / PENDING -> REJECTED (reject)
        - IN_REVIEW / PENDING -> NEEDS_MORE_EVIDENCE (return)
    - ADMIN:
        - Can perform standard transitions or OVERRIDE finalized states with mandatory reason.
    """
    act = action.strip().lower()

    # Citizens strictly prohibited from operational verification actions
    if user.is_citizen:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: Citizens are not permitted to adjudicate, approve, reject, or modify verification cases.",
        )

    # If case is already finalized (VERIFIED or REJECTED)
    is_finalized = case.status in (VerificationStatus.VERIFIED, VerificationStatus.REJECTED)

    if is_finalized:
        # Only ADMIN or SUPER_ADMIN can override finalized status, and ONLY with mandatory justification
        if not user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Case {case.id[:8]} has already been finalized ({case.status.value.upper()}). Only administrative personnel may override finalized adjudication decisions.",
            )
        if not reason or len(reason.strip()) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrative override requires a mandatory justification reason (minimum 10 characters).",
            )
