"""Feedback/learning loop models."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text
from backend.database import Base


class FeedbackSample(Base):
    __tablename__ = "feedback_samples"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, nullable=True)
    document_type = Column(String(50), nullable=True)
    field_name = Column(String(100), nullable=False)
    original_ocr_text = Column(Text, nullable=True)
    ai_extracted_value = Column(Text, nullable=True)
    human_corrected_value = Column(Text, nullable=True)
    language = Column(String(20), nullable=True)
    reviewer_id = Column(String, nullable=True)
    is_used_for_training = Column(String(10), default="false")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<FeedbackSample {self.field_name}: {self.ai_extracted_value} → {self.human_corrected_value}>"
