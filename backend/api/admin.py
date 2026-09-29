"""GeoLedger — Administrative Governance and User RBAC Management API."""

import logging
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.user import User, RoleEnum, Jurisdiction, UserJurisdiction
from backend.api.auth import get_current_user, hash_password
from backend.security.permissions import (
    USERS_READ,
    USERS_CREATE,
    USERS_UPDATE,
    USERS_DEACTIVATE,
    USERS_ASSIGN_ROLE,
    JURISDICTIONS_MANAGE,
    ROLES_READ,
    ROLE_PERMISSIONS_MAP,
)
from backend.security.authorization import require_permission, log_security_event

logger = logging.getLogger("geoldger.api.admin")
router = APIRouter(prefix="/api/admin", tags=["Administration"])


# Pydantic Schemas
class AdminUserCreateRequest(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    role: str  # "citizen", "revenue_officer", "admin", "auditor"
    jurisdiction_id: Optional[str] = None
    jurisdiction_scope: Optional[str] = "SCOPED"


class RoleUpdateRequest(BaseModel):
    role: str
    reason: Optional[str] = None


class StatusUpdateRequest(BaseModel):
    is_active: bool
    reason: Optional[str] = None


class JurisdictionAssignRequest(BaseModel):
    jurisdiction_id: str
    is_primary: Optional[bool] = True
    reason: Optional[str] = None


class JurisdictionCreateRequest(BaseModel):
    code: str
    name: str
    state: str
    district: Optional[str] = None
    tehsil: Optional[str] = None
    block: Optional[str] = None
    village: Optional[str] = None


@router.get("/users")
async def list_users(
    role: Optional[str] = Query(None),
    is_active: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(USERS_READ)),
):
    """List all users in the system with their role and assigned jurisdictions."""
    query = db.query(User)

    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()

    result = []
    for u in users:
        # Load user jurisdictions
        jurisdictions = []
        for uj in u.jurisdictions:
            if uj.jurisdiction:
                jurisdictions.append({
                    "id": uj.jurisdiction.id,
                    "code": uj.jurisdiction.code,
                    "name": uj.jurisdiction.name,
                    "district": uj.jurisdiction.district,
                    "tehsil": uj.jurisdiction.tehsil,
                    "is_primary": uj.is_primary == "true",
                })

        result.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.canonical_role,
            "raw_role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "is_active": u.is_active == "true" or u.is_active is True,
            "jurisdiction_scope": u.jurisdiction_scope,
            "jurisdictions": jurisdictions,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        })

    return {"total": total, "users": result}


@router.post("/users", status_code=201)
async def create_user(
    data: AdminUserCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(USERS_CREATE)),
):
    """Administrative user provisioning with explicit role and jurisdiction."""
    existing = db.query(User).filter(
        (User.username == data.username) | (User.email == data.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already registered")

    try:
        role_enum = RoleEnum(data.role.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {data.role}. Allowed: citizen, revenue_officer, admin, auditor, super_admin")
    if role_enum == RoleEnum.SUPER_ADMIN and current_user.canonical_role != RoleEnum.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail="Only a super administrator can provision a super administrator")

    new_user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=role_enum,
        jurisdiction_scope=data.jurisdiction_scope or "SCOPED",
        is_active="true",
    )
    db.add(new_user)
    db.flush()

    # Assign initial jurisdiction if provided
    if data.jurisdiction_id:
        jur = db.query(Jurisdiction).filter(Jurisdiction.id == data.jurisdiction_id).first()
        if not jur:
            db.rollback()
            raise HTTPException(status_code=404, detail="Jurisdiction not found")
        uj = UserJurisdiction(
            user_id=new_user.id,
            jurisdiction_id=jur.id,
            is_primary="true",
            assigned_by=current_user.id,
        )
        db.add(uj)

    db.commit()
    db.refresh(new_user)

    log_security_event(
        db=db,
        user=current_user,
        action="USER_CREATED",
        resource_type="user",
        resource_id=new_user.id,
        details=f"Created user {new_user.username} with role {new_user.role.value}",
    )

    return {
        "id": new_user.id,
        "username": new_user.username,
        "email": new_user.email,
        "role": new_user.canonical_role,
        "status": "created",
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    data: RoleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(USERS_ASSIGN_ROLE)),
):
    """Reassign role for a user with mandatory audit tracking."""
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        new_role = RoleEnum(data.role.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {data.role}")

    is_super_admin_operation = (
        new_role == RoleEnum.SUPER_ADMIN or target_user.canonical_role == RoleEnum.SUPER_ADMIN.value
    )
    if is_super_admin_operation and current_user.canonical_role != RoleEnum.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail="Only a super administrator can manage super administrator accounts")

    # Prevent demoting the last active admin
    if target_user.is_admin and new_role != RoleEnum.ADMIN:
        admin_count = db.query(User).filter(
            User.role.in_([RoleEnum.ADMIN, RoleEnum.SUPER_ADMIN]),
            User.is_active == "true"
        ).count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the only remaining active administrator")

    old_role_val = target_user.role.value if hasattr(target_user.role, "value") else str(target_user.role)
    target_user.role = new_role
    db.commit()

    log_security_event(
        db=db,
        user=current_user,
        action="ROLE_REASSIGNED",
        resource_type="user",
        resource_id=target_user.id,
        reason=data.reason or "Administrative role update",
        details=f"Role changed from {old_role_val} to {new_role.value}",
    )

    return {
        "id": target_user.id,
        "username": target_user.username,
        "old_role": old_role_val,
        "new_role": target_user.canonical_role,
    }


@router.put("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    data: StatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(USERS_DEACTIVATE)),
):
    """Activate or deactivate a user account with audit trail."""
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if target_user.id == current_user.id and not data.is_active:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own administrator account")

    old_status = target_user.is_active
    target_user.is_active = "true" if data.is_active else "false"
    db.commit()

    log_security_event(
        db=db,
        user=current_user,
        action="ACCOUNT_STATUS_CHANGED",
        resource_type="user",
        resource_id=target_user.id,
        reason=data.reason or f"Account active status set to {data.is_active}",
        details=f"Status changed from {old_status} to {target_user.is_active}",
    )

    return {
        "id": target_user.id,
        "username": target_user.username,
        "is_active": data.is_active,
    }


@router.put("/users/{user_id}/jurisdiction")
async def assign_user_jurisdiction(
    user_id: str,
    data: JurisdictionAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(JURISDICTIONS_MANAGE)),
):
    """Assign or reassign an administrative jurisdiction to an officer."""
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    jur = db.query(Jurisdiction).filter(Jurisdiction.id == data.jurisdiction_id).first()
    if not jur:
        raise HTTPException(status_code=404, detail="Jurisdiction not found")

    # Check if already assigned
    existing = db.query(UserJurisdiction).filter(
        UserJurisdiction.user_id == user_id,
        UserJurisdiction.jurisdiction_id == data.jurisdiction_id,
    ).first()

    if not existing:
        uj = UserJurisdiction(
            user_id=user_id,
            jurisdiction_id=data.jurisdiction_id,
            is_primary="true" if data.is_primary else "false",
            assigned_by=current_user.id,
        )
        db.add(uj)
    else:
        existing.is_primary = "true" if data.is_primary else "false"

    db.commit()

    log_security_event(
        db=db,
        user=current_user,
        action="JURISDICTION_ASSIGNED",
        resource_type="user",
        resource_id=user_id,
        reason=data.reason or "Administrative jurisdiction assignment",
        details=f"Assigned jurisdiction {jur.code} ({jur.name}) to {target_user.username}",
    )

    return {
        "user_id": user_id,
        "jurisdiction_id": jur.id,
        "jurisdiction_code": jur.code,
        "jurisdiction_name": jur.name,
    }


@router.get("/jurisdictions")
async def list_jurisdictions(
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List administrative jurisdictions."""
    query = db.query(Jurisdiction)
    if state:
        query = query.filter(Jurisdiction.state.ilike(f"%{state}%"))
    if district:
        query = query.filter(Jurisdiction.district.ilike(f"%{district}%"))

    jurisdictions = query.order_by(Jurisdiction.state, Jurisdiction.district, Jurisdiction.tehsil).all()
    return [
        {
            "id": j.id,
            "code": j.code,
            "name": j.name,
            "state": j.state,
            "district": j.district,
            "tehsil": j.tehsil,
            "block": j.block,
            "village": j.village,
        }
        for j in jurisdictions
    ]


@router.post("/jurisdictions", status_code=201)
async def create_jurisdiction(
    data: JurisdictionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(JURISDICTIONS_MANAGE)),
):
    """Create a new administrative jurisdiction boundary."""
    existing = db.query(Jurisdiction).filter(Jurisdiction.code == data.code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Jurisdiction with code '{data.code}' already exists")

    jur = Jurisdiction(
        code=data.code,
        name=data.name,
        state=data.state,
        district=data.district,
        tehsil=data.tehsil,
        block=data.block,
        village=data.village,
    )
    db.add(jur)
    db.commit()
    db.refresh(jur)

    log_security_event(
        db=db,
        user=current_user,
        action="JURISDICTION_CREATED",
        resource_type="jurisdiction",
        resource_id=jur.id,
        details=f"Created jurisdiction {jur.code}: {jur.name}",
    )

    return {
        "id": jur.id,
        "code": jur.code,
        "name": jur.name,
        "state": jur.state,
        "district": jur.district,
        "tehsil": jur.tehsil,
    }


@router.get("/roles")
async def list_roles_and_permissions(
    current_user: User = Depends(require_permission(ROLES_READ)),
):
    """List system roles and their assigned permission matrices."""
    roles = []
    for role_name, perms in ROLE_PERMISSIONS_MAP.items():
        roles.append({
            "role": role_name,
            "permissions_count": len(perms),
            "permissions": sorted(list(perms)),
        })
    return roles
