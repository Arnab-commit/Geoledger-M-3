"""GeoLedger — Administrative Jurisdiction Evaluation Engine.

Enforces real-world land revenue hierarchy:
State -> District -> Tehsil / Taluk -> Block -> Revenue Circle -> Village / Mouza.
Ensures Revenue Officers cannot access, adjudicate, or modify records
outside their authorized geographic domain.
"""

import logging
from typing import List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from backend.models.user import User, Jurisdiction, UserJurisdiction, RoleEnum
from backend.models.document import Document
from backend.models.parcel import Parcel
from backend.models.verification import VerificationCase

logger = logging.getLogger("geoldger.security.jurisdiction")


def get_user_jurisdictions(user: User, db: Session) -> List[Jurisdiction]:
    """Retrieve all assigned jurisdictions for a given user."""
    if not user:
        return []
    assignments = db.query(UserJurisdiction).filter(UserJurisdiction.user_id == user.id).all()
    jurisdictions = []
    for a in assignments:
        if a.jurisdiction:
            jurisdictions.append(a.jurisdiction)
    return jurisdictions


def is_resource_in_jurisdiction(
    user: User,
    state: Optional[str] = None,
    district: Optional[str] = None,
    tehsil: Optional[str] = None,
    village: Optional[str] = None,
    db: Session = None,
) -> bool:
    """
    Check if a resource's location falls within the user's authorized jurisdiction scope.
    
    Admins and SuperAdmins have global scope.
    Officers must match state, district, and tehsil/village according to their assigned scope.
    """
    if not user:
        return False

    # Admins, SuperAdmins, and Auditors have statewide/nationwide scope
    if user.is_admin or user.canonical_role == RoleEnum.AUDITOR.value:
        return True

    # If user has explicit "GLOBAL" scope set
    if getattr(user, "jurisdiction_scope", None) == "GLOBAL":
        return True

    user_jurisdictions = get_user_jurisdictions(user, db) if db else []

    # If officer has no assigned jurisdictions and is not global, access is denied
    if not user_jurisdictions:
        logger.warning(f"User {user.username} has no jurisdictions assigned")
        return False

    # Normalize resource coordinates
    res_state = (state or "").strip().lower()
    res_district = (district or "").strip().lower()
    res_tehsil = (tehsil or "").strip().lower()
    res_village = (village or "").strip().lower()

    # Missing location data cannot establish that a resource falls inside an
    # officer's jurisdiction. Owners and global roles were handled above.
    if not any((res_state, res_district, res_tehsil, res_village)):
        return False

    for j in user_jurisdictions:
        j_state = (j.state or "").strip().lower()
        j_district = (j.district or "").strip().lower()
        j_tehsil = (j.tehsil or "").strip().lower()
        j_village = (j.village or "").strip().lower()

        # Check State
        if j_state and j_state != "*" and (not res_state or j_state != res_state):
            continue

        # Check District (null or '*' means all districts in the state)
        if j_district and j_district != "*" and (not res_district or j_district != res_district):
            continue

        # Check Tehsil (null or '*' means all tehsils in the district)
        if j_tehsil and j_tehsil != "*" and (not res_tehsil or j_tehsil != res_tehsil):
            continue

        # Check Village
        if j_village and j_village != "*" and (not res_village or j_village != res_village):
            continue

        # Match satisfied
        return True

    return False


def filter_documents_by_scope(query, user: User, db: Session):
    """
    Apply database query filters to documents based on user role and jurisdiction scope.
    - CITIZEN: Only documents uploaded by the user.
    - OFFICER: Documents in officer's jurisdiction, or documents linked to parcels in jurisdiction, or own uploads.
    - ADMIN/AUDITOR: All documents.
    """
    if user.is_admin or user.canonical_role == RoleEnum.AUDITOR.value or getattr(user, "jurisdiction_scope", None) == "GLOBAL":
        return query

    if user.is_citizen:
        # Citizens only see their own uploaded documents
        return query.filter(
            or_(
                Document.uploader_id == user.id,
                Document.uploaded_by == user.username,
            )
        )

    # REVENUE OFFICER: Scope to officer's assigned districts / tehsils or own uploads
    jurisdictions = get_user_jurisdictions(user, db)
    if not jurisdictions:
        # If no jurisdiction assigned, restrict to own uploads to prevent unauthorized data leaks
        return query.filter(
            or_(
                Document.uploader_id == user.id,
                Document.uploaded_by == user.username,
            )
        )

    # Build OR clauses for each assigned jurisdiction
    scope_clauses = [
        Document.uploader_id == user.id,
        Document.uploaded_by == user.username,
    ]

    for j in jurisdictions:
        conditions = []
        if j.state and j.state != "*":
            conditions.append(Document.state.ilike(f"%{j.state}%"))
        if j.district and j.district != "*":
            conditions.append(Document.district.ilike(f"%{j.district}%"))
        if j.tehsil and j.tehsil != "*":
            conditions.append(Document.tehsil.ilike(f"%{j.tehsil}%"))
        if conditions:
            scope_clauses.append(and_(*conditions))

    return query.filter(or_(*scope_clauses))


def filter_parcels_by_scope(query, user: User, db: Session):
    """
    Apply database query filters to parcels based on user role and jurisdiction scope.
    - CITIZEN: Only parcels owned by the citizen or linked to citizen's uploaded documents.
    - OFFICER: Parcels within authorized jurisdiction.
    - ADMIN/AUDITOR: All parcels.
    """
    if user.is_admin or user.canonical_role == RoleEnum.AUDITOR.value or getattr(user, "jurisdiction_scope", None) == "GLOBAL":
        return query

    if user.is_citizen:
        from backend.models.parcel import ParcelDocument
        # Find parcels linked to citizen's documents
        user_doc_ids = db.query(Document.id).filter(
            or_(
                Document.uploader_id == user.id,
                Document.uploaded_by == user.username,
            )
        ).subquery()
        linked_parcel_ids = db.query(ParcelDocument.parcel_id).filter(
            ParcelDocument.document_id.in_(user_doc_ids)
        ).subquery()

        return query.filter(
            or_(
                Parcel.current_owner.ilike(f"%{user.full_name}%"),
                Parcel.current_owner.ilike(f"%{user.username}%"),
                Parcel.id.in_(linked_parcel_ids),
            )
        )

    # REVENUE OFFICER: Scope to officer's assigned districts / tehsils
    jurisdictions = get_user_jurisdictions(user, db)
    if not jurisdictions:
        return query.filter(Parcel.id == "__NO_ACCESS__")

    scope_clauses = []
    for j in jurisdictions:
        conditions = []
        if j.state and j.state != "*":
            conditions.append(Parcel.state.ilike(f"%{j.state}%"))
        if j.district and j.district != "*":
            conditions.append(Parcel.district.ilike(f"%{j.district}%"))
        if j.tehsil and j.tehsil != "*":
            conditions.append(Parcel.tehsil.ilike(f"%{j.tehsil}%"))
        if conditions:
            scope_clauses.append(and_(*conditions))

    if scope_clauses:
        return query.filter(or_(*scope_clauses))
    return query


def filter_cases_by_scope(query, user: User, db: Session):
    """
    Apply database query filters to verification cases based on user role and jurisdiction scope.
    - CITIZEN: Cases submitted by user or linked to user's documents/parcels.
    - OFFICER: Cases within officer's jurisdiction or assigned to the officer.
    - ADMIN/AUDITOR: All cases.
    """
    if user.is_admin or user.canonical_role == RoleEnum.AUDITOR.value or getattr(user, "jurisdiction_scope", None) == "GLOBAL":
        return query

    if user.is_citizen:
        # Own submissions
        return query.filter(
            or_(
                VerificationCase.submitted_by == user.id,
                VerificationCase.submitted_by == user.username,
            )
        )

    # OFFICER: Assigned to this officer OR within their jurisdiction
    jurisdictions = get_user_jurisdictions(user, db)
    scope_clauses = [
        VerificationCase.assigned_to == user.id,
    ]

    for j in jurisdictions:
        conditions = []
        if j.district and j.district != "*":
            conditions.append(VerificationCase.district.ilike(f"%{j.district}%"))
        if j.tehsil and j.tehsil != "*":
            conditions.append(VerificationCase.tehsil.ilike(f"%{j.tehsil}%"))
        if conditions:
            scope_clauses.append(and_(*conditions))

    return query.filter(or_(*scope_clauses))
