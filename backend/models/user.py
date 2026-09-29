"""User and Role models."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship
from backend.database import Base
import enum


class RoleEnum(str, enum.Enum):
    CITIZEN = "citizen"
    REVENUE_OFFICER = "revenue_officer"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"
    AUDITOR = "auditor"
    # Legacy aliases for database compatibility
    VERIFIER = "verifier"
    VIEWER = "viewer"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(SAEnum(RoleEnum), nullable=False, default=RoleEnum.CITIZEN)
    is_active = Column(String(10), default="true")
    jurisdiction_scope = Column(String(50), default="SCOPED")  # "GLOBAL", "SCOPED", "SELF"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime, nullable=True)

    # Relationships
    audit_logs = relationship("AuditLog", back_populates="user")
    verification_actions = relationship("VerificationAction", back_populates="user")
    jurisdictions = relationship("UserJurisdiction", back_populates="user", cascade="all, delete-orphan")

    @property
    def canonical_role(self) -> str:
        """Returns standard normalized role: citizen, revenue_officer, admin, super_admin, auditor."""
        r = self.role.value.lower() if hasattr(self.role, "value") else str(self.role).lower()
        if r in ("verifier", "revenue_officer"):
            return RoleEnum.REVENUE_OFFICER.value
        if r in ("viewer", "citizen", "user"):
            return RoleEnum.CITIZEN.value
        if r in ("super_admin", "superadmin"):
            return RoleEnum.SUPER_ADMIN.value
        if r in ("auditor",):
            return RoleEnum.AUDITOR.value
        return RoleEnum.ADMIN.value

    @property
    def is_admin(self) -> bool:
        return self.canonical_role in (RoleEnum.ADMIN.value, RoleEnum.SUPER_ADMIN.value)

    @property
    def is_revenue_officer(self) -> bool:
        return self.canonical_role == RoleEnum.REVENUE_OFFICER.value

    @property
    def is_citizen(self) -> bool:
        return self.canonical_role == RoleEnum.CITIZEN.value

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class Jurisdiction(Base):
    __tablename__ = "jurisdictions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(50), unique=True, nullable=False)  # e.g., "WB_N24P_BARASAT"
    name = Column(String(255), nullable=False)  # "Barasat Sub-Division / Tehsil"
    state = Column(String(100), nullable=False)  # "West Bengal"
    district = Column(String(100), nullable=True)  # "North 24 Parganas" (null/* = all in state)
    tehsil = Column(String(100), nullable=True)  # "Barasat" (null/* = all in district)
    block = Column(String(100), nullable=True)
    village = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user_assignments = relationship("UserJurisdiction", back_populates="jurisdiction", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Jurisdiction {self.code}: {self.name}>"


class UserJurisdiction(Base):
    __tablename__ = "user_jurisdictions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    jurisdiction_id = Column(String, ForeignKey("jurisdictions.id"), nullable=False)
    is_primary = Column(String(10), default="true")
    assigned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    assigned_by = Column(String, nullable=True)

    user = relationship("User", back_populates="jurisdictions")
    jurisdiction = relationship("Jurisdiction", back_populates="user_assignments")

    def __repr__(self):
        return f"<UserJurisdiction user={self.user_id[:8]} jurisdiction={self.jurisdiction_id[:8]}>"


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(100), unique=True, nullable=False)  # e.g., "documents.read_scoped"
    module = Column(String(50), nullable=False)  # "documents", "parcels", "verification", etc.
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)

    def __repr__(self):
        return f"<Permission {self.code}>"


class Role(Base):
    __tablename__ = "roles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(SAEnum(RoleEnum), unique=True, nullable=False)
    description = Column(String(500))
    permissions = Column(String(2000))  # JSON string of permissions

    def __repr__(self):
        return f"<Role {self.name}>"

