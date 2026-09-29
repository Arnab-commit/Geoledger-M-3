"""Ownership models."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class Owner(Base):
    __tablename__ = "owners"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    name = Column(String(500), nullable=False)
    normalized_name = Column(String(500), nullable=True)
    father_husband_name = Column(String(500), nullable=True)
    is_current = Column(String(10), default="true")
    ownership_share = Column(String(100), nullable=True)
    source_document_id = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    parcel = relationship("Parcel", back_populates="owners")

    def __repr__(self):
        return f"<Owner {self.name}>"


class OwnershipEvent(Base):
    __tablename__ = "ownership_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    event_type = Column(String(50), nullable=False)
    event_date = Column(String(50), nullable=True)
    owner_before = Column(String(500), nullable=True)
    owner_after = Column(String(500), nullable=True)
    area_before = Column(Float, nullable=True)
    area_after = Column(Float, nullable=True)
    source_document_id = Column(String, nullable=True)
    reference_number = Column(String(255), nullable=True)
    confidence = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    parcel = relationship("Parcel", back_populates="ownership_events")

    def __repr__(self):
        return f"<OwnershipEvent {self.event_type} on {self.event_date}>"
