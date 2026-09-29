"""Mutation record models."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class Mutation(Base):
    __tablename__ = "mutations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    mutation_number = Column(String(100), nullable=True)
    mutation_date = Column(String(50), nullable=True)
    mutation_type = Column(String(100), nullable=True)
    previous_owner = Column(String(500), nullable=True)
    new_owner = Column(String(500), nullable=True)
    area = Column(Float, nullable=True)
    area_unit = Column(String(50), nullable=True)
    source_document_id = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    parcel = relationship("Parcel", back_populates="mutations")

    def __repr__(self):
        return f"<Mutation {self.mutation_number}>"
