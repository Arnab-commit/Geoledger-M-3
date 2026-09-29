"""Parcel and identity models."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class Parcel(Base):
    __tablename__ = "parcels"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_code = Column(String(50), unique=True, nullable=False)
    ulpin = Column(String(100), nullable=True)
    village = Column(String(255), nullable=True)
    mouza = Column(String(255), nullable=True)
    tehsil = Column(String(255), nullable=True)
    district = Column(String(255), nullable=True)
    state = Column(String(255), nullable=True)
    current_area = Column(Float, nullable=True)
    area_unit = Column(String(50), default="acres")
    land_classification = Column(String(255), nullable=True)
    current_owner = Column(String(500), nullable=True)
    consistency_score = Column(Float, nullable=True)
    verification_status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    identifiers = relationship("ParcelIdentifier", back_populates="parcel", cascade="all, delete-orphan")
    parcel_documents = relationship("ParcelDocument", back_populates="parcel", cascade="all, delete-orphan")
    owners = relationship("Owner", back_populates="parcel")
    ownership_events = relationship("OwnershipEvent", back_populates="parcel")
    mutations = relationship("Mutation", back_populates="parcel")
    registrations = relationship("Registration", back_populates="parcel")
    discrepancies = relationship("Discrepancy", back_populates="parcel")
    gis_geometries = relationship("GisGeometry", back_populates="parcel")
    verification_cases = relationship("VerificationCase", back_populates="parcel")

    def __repr__(self):
        return f"<Parcel {self.parcel_code}>"


class ParcelIdentifier(Base):
    __tablename__ = "parcel_identifiers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    identifier_type = Column(String(50), nullable=False)
    identifier_value = Column(String(255), nullable=False)
    source_document_id = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    parcel = relationship("Parcel", back_populates="identifiers")

    def __repr__(self):
        return f"<ParcelIdentifier {self.identifier_type}={self.identifier_value}>"


class ParcelDocument(Base):
    __tablename__ = "parcel_documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    relationship_type = Column(String(50), default="linked")
    linked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    linked_by = Column(String, nullable=True)

    parcel = relationship("Parcel", back_populates="parcel_documents")
    document = relationship("Document", back_populates="parcel_documents")

    def __repr__(self):
        return f"<ParcelDocument parcel={self.parcel_id[:8]} doc={self.document_id[:8]}>"
