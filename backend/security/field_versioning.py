"""GeoLedger — Field-Level Data Versioning and Extraction Audit Service.

Guarantees that officer corrections NEVER destroy or silently overwrite raw OCR.
Maintains full documentary lineage:
RAW OCR -> AI EXTRACTION -> OFFICER CORRECTION -> FINAL VERIFIED VALUE
along with timestamps, actor IDs, and justification reasons.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.models.extraction import ExtractedField, FieldAuditHistory, FieldStatus
from backend.models.user import User

logger = logging.getLogger("geoldger.security.field_versioning")


def record_field_extraction(
    db: Session,
    field: ExtractedField,
    raw_ocr: Optional[str] = None,
    ai_extracted: Optional[str] = None,
):
    """Record initial extraction stage in history."""
    field.ai_extracted_value = ai_extracted or field.value
    if raw_ocr:
        field.raw_text = raw_ocr

    # Create history entry
    hist = FieldAuditHistory(
        field_id=field.id,
        document_id=field.document_id,
        field_name=field.field_name,
        stage="AI_EXTRACTED",
        value=field.ai_extracted_value,
        changed_by="SYSTEM_AI",
        reason="Automated layout & neural extraction",
    )
    db.add(hist)
    db.commit()


def record_officer_correction(
    db: Session,
    field: ExtractedField,
    new_value: str,
    officer: User,
    reason: Optional[str] = None,
) -> ExtractedField:
    """
    Apply officer correction while preserving AI extraction and raw OCR.
    Updates working value and appends to immutable version history.
    """
    old_value = field.value
    now = datetime.now(timezone.utc)

    # Preserve prior value in officer_corrected_value
    field.officer_corrected_value = new_value
    field.corrected_by = officer.id
    field.corrected_at = now
    field.correction_reason = reason or "Revenue officer manual adjudication"
    field.value = new_value
    field.status = FieldStatus.CONFIRMED

    # Append to history
    hist = FieldAuditHistory(
        field_id=field.id,
        document_id=field.document_id,
        field_name=field.field_name,
        stage="OFFICER_CORRECTION",
        value=new_value,
        changed_by=officer.id,
        reason=field.correction_reason,
    )
    db.add(hist)
    db.commit()
    db.refresh(field)

    logger.info(f"Field {field.field_name} in doc {field.document_id[:8]} corrected by {officer.username}: '{old_value}' -> '{new_value}'")
    return field


def record_final_verification(
    db: Session,
    field: ExtractedField,
    verified_value: str,
    officer: User,
    reason: Optional[str] = None,
) -> ExtractedField:
    """Record final statutory verified value."""
    now = datetime.now(timezone.utc)
    field.final_verified_value = verified_value
    field.verified_by = officer.id
    field.verified_at = now
    field.value = verified_value
    field.status = FieldStatus.CONFIRMED

    hist = FieldAuditHistory(
        field_id=field.id,
        document_id=field.document_id,
        field_name=field.field_name,
        stage="FINAL_VERIFIED",
        value=verified_value,
        changed_by=officer.id,
        reason=reason or "Statutory deed verification finalized",
    )
    db.add(hist)
    db.commit()
    db.refresh(field)

    return field


def get_field_audit_lineage(db: Session, field_id: str) -> List[Dict[str, Any]]:
    """Retrieve full chronological evolution of a field value."""
    histories = db.query(FieldAuditHistory).filter(
        FieldAuditHistory.field_id == field_id
    ).order_by(FieldAuditHistory.created_at.asc()).all()

    return [
        {
            "id": h.id,
            "stage": h.stage,
            "value": h.value,
            "changed_by": h.changed_by,
            "reason": h.reason,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in histories
    ]
