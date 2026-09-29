"""Evidence models."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Integer, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    discrepancy_id = Column(String, ForeignKey("discrepancies.id"), nullable=True)
    field_name = Column(String(100), nullable=True)
    value = Column(Text, nullable=True)
    page_number = Column(Integer, nullable=True)
    bbox_x1 = Column(Integer, nullable=True)
    bbox_y1 = Column(Integer, nullable=True)
    bbox_x2 = Column(Integer, nullable=True)
    bbox_y2 = Column(Integer, nullable=True)
    ocr_confidence = Column(Float, nullable=True)
    extraction_confidence = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="evidence_items")
    discrepancy = relationship("Discrepancy", back_populates="evidence_items")

    @property
    def bbox(self):
        if all(v is not None for v in [self.bbox_x1, self.bbox_y1, self.bbox_x2, self.bbox_y2]):
            return [self.bbox_x1, self.bbox_y1, self.bbox_x2, self.bbox_y2]
        return None

    def __repr__(self):
        return f"<Evidence {self.field_name} from doc={self.document_id[:8]}>"
