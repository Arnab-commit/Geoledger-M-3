"""Audit trail models."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    actor_role = Column(String(50), nullable=True)  # Role of the acting user
    action = Column(String(100), nullable=False)
    entity_type = Column(String(100), nullable=True)
    entity_id = Column(String, nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    details = Column(Text, nullable=True)
    result = Column(String(20), default="SUCCESS")  # "SUCCESS", "DENIED", "CONFLICT_BLOCKED", "ERROR"
    reason = Column(Text, nullable=True)  # Administrative or authorization justification
    ip_address = Column(String(50), nullable=True)
    model_version = Column(String(50), nullable=True)
    correlation_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="audit_logs")

    def __repr__(self):
        return f"<AuditLog {self.action} on {self.entity_type}>"
