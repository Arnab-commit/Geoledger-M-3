"""GeoLedger — Granular Permission System and Role Mappings.

Separates role identity from authorization rights.
Allows role -> permissions mapping and fine-grained authorization.
"""

from typing import Set, Dict
from backend.models.user import RoleEnum, User

# ---------------------------------------------------------------------------
# Granular Permission Constants
# ---------------------------------------------------------------------------

# Document Permissions
DOCUMENTS_UPLOAD = "documents.upload"
DOCUMENTS_READ_OWN = "documents.read_own"
DOCUMENTS_READ_SCOPED = "documents.read_scoped"
DOCUMENTS_READ_ALL = "documents.read_all"
DOCUMENTS_EDIT_EXTRACTION = "documents.edit_extraction"
DOCUMENTS_DELETE_OWN = "documents.delete_own"
DOCUMENTS_DELETE_ALL = "documents.delete_all"
DOCUMENTS_VERIFY = "documents.verify"

# Parcel Permissions
PARCELS_READ_OWN = "parcels.read_own"
PARCELS_READ_SCOPED = "parcels.read_scoped"
PARCELS_READ_ALL = "parcels.read_all"
PARCELS_EDIT = "parcels.edit"

# Verification Case Permissions
VERIFICATION_CREATE = "verification.create"
VERIFICATION_READ_OWN = "verification.read_own"
VERIFICATION_READ_SCOPED = "verification.read_scoped"
VERIFICATION_READ_ALL = "verification.read_all"
VERIFICATION_REVIEW = "verification.review"
VERIFICATION_CORRECT = "verification.correct"
VERIFICATION_APPROVE = "verification.approve"
VERIFICATION_REJECT = "verification.reject"
VERIFICATION_RETURN = "verification.return"
VERIFICATION_OVERRIDE = "verification.override"

# GIS Permissions
GIS_READ_OWN = "gis.read_own"
GIS_READ_SCOPED = "gis.read_scoped"
GIS_READ_ALL = "gis.read_all"
GIS_EDIT = "gis.edit"
GIS_APPROVE_GEOMETRY = "gis.approve_geometry"

# User Management Permissions
USERS_READ = "users.read"
USERS_CREATE = "users.create"
USERS_UPDATE = "users.update"
USERS_DEACTIVATE = "users.deactivate"
USERS_ASSIGN_ROLE = "users.assign_role"

# Jurisdiction & Role Management Permissions
JURISDICTIONS_MANAGE = "jurisdictions.manage"
ROLES_READ = "roles.read"
ROLES_MANAGE = "roles.manage"

# Audit Permissions
AUDIT_READ_OWN = "audit.read_own"
AUDIT_READ_SCOPED = "audit.read_scoped"
AUDIT_READ_ALL = "audit.read_all"
AUDIT_EXPORT = "audit.export"

# System Configuration Permissions
SYSTEM_CONFIGURE = "system.configure"


# ---------------------------------------------------------------------------
# Default Role Permissions Matrix
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS_MAP: Dict[str, Set[str]] = {
    # 1. CITIZEN / USER: Own document uploads, views, case submissions, own audit
    RoleEnum.CITIZEN.value: {
        DOCUMENTS_UPLOAD,
        DOCUMENTS_READ_OWN,
        DOCUMENTS_DELETE_OWN,
        PARCELS_READ_OWN,
        VERIFICATION_CREATE,
        VERIFICATION_READ_OWN,
        GIS_READ_OWN,
        AUDIT_READ_OWN,
    },
    # Legacy VIEWER maps to CITIZEN
    RoleEnum.VIEWER.value: {
        DOCUMENTS_UPLOAD,
        DOCUMENTS_READ_OWN,
        DOCUMENTS_DELETE_OWN,
        PARCELS_READ_OWN,
        VERIFICATION_CREATE,
        VERIFICATION_READ_OWN,
        GIS_READ_OWN,
        AUDIT_READ_OWN,
    },

    # 2. REVENUE OFFICER: Jurisdictional scoped access, evidence inspection, field correction, adjudication
    RoleEnum.REVENUE_OFFICER.value: {
        DOCUMENTS_UPLOAD,
        DOCUMENTS_READ_OWN,
        DOCUMENTS_READ_SCOPED,
        DOCUMENTS_EDIT_EXTRACTION,
        PARCELS_READ_SCOPED,
        VERIFICATION_CREATE,
        VERIFICATION_READ_SCOPED,
        VERIFICATION_REVIEW,
        VERIFICATION_CORRECT,
        VERIFICATION_APPROVE,
        VERIFICATION_REJECT,
        VERIFICATION_RETURN,
        GIS_READ_SCOPED,
        GIS_EDIT,
        AUDIT_READ_SCOPED,
    },
    # Legacy VERIFIER maps to REVENUE_OFFICER
    RoleEnum.VERIFIER.value: {
        DOCUMENTS_UPLOAD,
        DOCUMENTS_READ_OWN,
        DOCUMENTS_READ_SCOPED,
        DOCUMENTS_EDIT_EXTRACTION,
        PARCELS_READ_SCOPED,
        VERIFICATION_CREATE,
        VERIFICATION_READ_SCOPED,
        VERIFICATION_REVIEW,
        VERIFICATION_CORRECT,
        VERIFICATION_APPROVE,
        VERIFICATION_REJECT,
        VERIFICATION_RETURN,
        GIS_READ_SCOPED,
        GIS_EDIT,
        AUDIT_READ_SCOPED,
    },

    # 3. AUDITOR: Global read-only observation and audit trail export
    RoleEnum.AUDITOR.value: {
        DOCUMENTS_READ_ALL,
        PARCELS_READ_ALL,
        VERIFICATION_READ_ALL,
        GIS_READ_ALL,
        USERS_READ,
        ROLES_READ,
        AUDIT_READ_ALL,
        AUDIT_EXPORT,
    },

    # 4. ADMIN: System management, user governance, jurisdiction administration, audit observation
    RoleEnum.ADMIN.value: {
        DOCUMENTS_UPLOAD,
        DOCUMENTS_READ_OWN,
        DOCUMENTS_READ_SCOPED,
        DOCUMENTS_READ_ALL,
        DOCUMENTS_EDIT_EXTRACTION,
        DOCUMENTS_DELETE_ALL,
        DOCUMENTS_VERIFY,
        PARCELS_READ_SCOPED,
        PARCELS_READ_ALL,
        PARCELS_EDIT,
        VERIFICATION_CREATE,
        VERIFICATION_READ_SCOPED,
        VERIFICATION_READ_ALL,
        VERIFICATION_REVIEW,
        VERIFICATION_CORRECT,
        VERIFICATION_APPROVE,
        VERIFICATION_REJECT,
        VERIFICATION_RETURN,
        VERIFICATION_OVERRIDE,
        GIS_READ_SCOPED,
        GIS_READ_ALL,
        GIS_EDIT,
        GIS_APPROVE_GEOMETRY,
        USERS_READ,
        USERS_CREATE,
        USERS_UPDATE,
        USERS_DEACTIVATE,
        USERS_ASSIGN_ROLE,
        JURISDICTIONS_MANAGE,
        ROLES_READ,
        ROLES_MANAGE,
        AUDIT_READ_SCOPED,
        AUDIT_READ_ALL,
        AUDIT_EXPORT,
        SYSTEM_CONFIGURE,
    },

    # 5. SUPER_ADMIN: Full emergency overrides (all audited)
    RoleEnum.SUPER_ADMIN.value: {
        DOCUMENTS_UPLOAD, DOCUMENTS_READ_OWN, DOCUMENTS_READ_SCOPED, DOCUMENTS_READ_ALL,
        DOCUMENTS_EDIT_EXTRACTION, DOCUMENTS_DELETE_OWN, DOCUMENTS_DELETE_ALL, DOCUMENTS_VERIFY,
        PARCELS_READ_OWN, PARCELS_READ_SCOPED, PARCELS_READ_ALL, PARCELS_EDIT,
        VERIFICATION_CREATE, VERIFICATION_READ_OWN, VERIFICATION_READ_SCOPED, VERIFICATION_READ_ALL,
        VERIFICATION_REVIEW, VERIFICATION_CORRECT, VERIFICATION_APPROVE, VERIFICATION_REJECT,
        VERIFICATION_RETURN, VERIFICATION_OVERRIDE,
        GIS_READ_OWN, GIS_READ_SCOPED, GIS_READ_ALL, GIS_EDIT, GIS_APPROVE_GEOMETRY,
        USERS_READ, USERS_CREATE, USERS_UPDATE, USERS_DEACTIVATE, USERS_ASSIGN_ROLE,
        JURISDICTIONS_MANAGE, ROLES_READ, ROLES_MANAGE,
        AUDIT_READ_OWN, AUDIT_READ_SCOPED, AUDIT_READ_ALL, AUDIT_EXPORT,
        SYSTEM_CONFIGURE,
    },
}


def get_user_permissions(user: User) -> Set[str]:
    """Retrieve all effective permissions for a user based on their canonical role."""
    if not user or not user.is_active:
        return set()
    role_key = user.canonical_role
    return ROLE_PERMISSIONS_MAP.get(role_key, set())


def user_has_permission(user: User, permission: str) -> bool:
    """Check if the user holds a specific granular permission."""
    perms = get_user_permissions(user)
    return permission in perms
