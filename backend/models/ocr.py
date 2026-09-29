"""OCR result models."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Integer, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class OcrResult(Base):
    __tablename__ = "ocr_results"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    bbox_x1 = Column(Integer, nullable=True)
    bbox_y1 = Column(Integer, nullable=True)
    bbox_x2 = Column(Integer, nullable=True)
    bbox_y2 = Column(Integer, nullable=True)
    ocr_provider = Column(String(50), default="local")
    language = Column(String(20), nullable=True)
    block_type = Column(String(50), default="text")
    raw_output = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="ocr_results")

    @property
    def bbox(self):
        if all(v is not None for v in [self.bbox_x1, self.bbox_y1, self.bbox_x2, self.bbox_y2]):
            return [self.bbox_x1, self.bbox_y1, self.bbox_x2, self.bbox_y2]
        return None

    def __repr__(self):
        conf = f"{self.confidence:.2f}" if self.confidence else "N/A"
        return f"<OcrResult page={self.page_number} conf={conf}>"
