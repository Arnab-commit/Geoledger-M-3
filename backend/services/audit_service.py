"""Audit logging service."""

import logging
from sqlalchemy.orm import Session
from backend.models.audit import AuditLog

logger = logging.getLogger("geoldger.audit")


def log_action(
    db: Session,
    action: str,
    entity_type: str = None,
    entity_id: str = None,
    user_id: str = None,
    old_value: str = None,
    new_value: str = None,
    details: str = None,
    ip_address: str = None,
):
    """Create an audit log entry."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        details=details,
        ip_address=ip_address,
    )
    db.add(entry)
    db.commit()
    logger.info(f"AUDIT: {action} | {entity_type}:{entity_id} | user:{user_id}")
    return entry
