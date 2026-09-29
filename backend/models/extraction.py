"""Extracted field models."""

import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Integer, Float, Text, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship
from backend.database import Base


class FieldStatus(str, enum.Enum):
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"
    MISSING = "missing"


class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    field_name = Column(String(100), nullable=False)
    value = Column(Text, nullable=True)
    normalized_value = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    page_number = Column(Integer, nullable=True)
    bbox_x1 = Column(Integer, nullable=True)
    bbox_y1 = Column(Integer, nullable=True)
    bbox_x2 = Column(Integer, nullable=True)
    bbox_y2 = Column(Integer, nullable=True)
    extraction_method = Column(String(50), default="rule_based")
    status = Column(SAEnum(FieldStatus), default=FieldStatus.UNCERTAIN)
    raw_text = Column(Text, nullable=True)
    english_value = Column(Text, nullable=True)
    language = Column(String(50), nullable=True)
    # Complete Data Versioning Lifecycle (RAW OCR -> AI EXTRACTION -> OFFICER CORRECTION -> FINAL VERIFIED VALUE)
    ai_extracted_value = Column(Text, nullable=True)
    officer_corrected_value = Column(Text, nullable=True)
    corrected_by = Column(String, nullable=True)
    corrected_at = Column(DateTime, nullable=True)
    correction_reason = Column(Text, nullable=True)
    final_verified_value = Column(Text, nullable=True)
    verified_by = Column(String, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="extracted_fields")
    history = relationship("FieldAuditHistory", back_populates="field", cascade="all, delete-orphan")

    @property
    def bbox(self):
        if all(v is not None for v in [self.bbox_x1, self.bbox_y1, self.bbox_x2, self.bbox_y2]):
            return [self.bbox_x1, self.bbox_y1, self.bbox_x2, self.bbox_y2]
        return None

    def __repr__(self):
        return f"<ExtractedField {self.field_name}={self.value} ({self.status})>"


class FieldAuditHistory(Base):
    """Immutable audit trail for field values across the verification lifecycle."""
    __tablename__ = "field_audit_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    field_id = Column(String, ForeignKey("extracted_fields.id"), nullable=False)
    document_id = Column(String, nullable=False)
    field_name = Column(String(100), nullable=False)
    stage = Column(String(50), nullable=False)  # "RAW_OCR", "AI_EXTRACTED", "OFFICER_CORRECTION", "FINAL_VERIFIED"
    value = Column(Text, nullable=True)
    changed_by = Column(String, nullable=True)  # User ID or "SYSTEM"
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    field = relationship("ExtractedField", back_populates="history")

    def __repr__(self):
        return f"<FieldAuditHistory {self.field_name} [{self.stage}]={self.value}>"
