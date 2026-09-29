"""Registration record models."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class Registration(Base):
    __tablename__ = "registrations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    registration_number = Column(String(100), nullable=True)
    registration_date = Column(String(50), nullable=True)
    registration_type = Column(String(100), nullable=True)
    parties = Column(Text, nullable=True)
    consideration_amount = Column(Float, nullable=True)
    source_document_id = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    parcel = relationship("Parcel", back_populates="registrations")

    def __repr__(self):
        return f"<Registration {self.registration_number}>"
