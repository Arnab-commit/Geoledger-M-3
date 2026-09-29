"""SQLAlchemy models for GeoLedger."""

# Import all models so Base.metadata knows about them
from backend.models.user import User, Role, Jurisdiction, UserJurisdiction, Permission
from backend.models.document import Document, DocumentPage, ProcessingJob
from backend.models.ocr import OcrResult
from backend.models.extraction import ExtractedField, FieldAuditHistory
from backend.models.parcel import Parcel, ParcelIdentifier, ParcelDocument
from backend.models.ownership import Owner, OwnershipEvent
from backend.models.mutation import Mutation
from backend.models.registration import Registration
from backend.models.discrepancy import Discrepancy
from backend.models.evidence import Evidence
from backend.models.verification import VerificationCase, VerificationAction
from backend.models.feedback import FeedbackSample
from backend.models.audit import AuditLog
from backend.models.gis import GisGeometry, GisGeometryVersion
from sqlalchemy import Index

all_models = [
    User, Role, Jurisdiction, UserJurisdiction, Permission,
    Document, DocumentPage, ProcessingJob,
    OcrResult, ExtractedField, FieldAuditHistory,
    Parcel, ParcelIdentifier, ParcelDocument,
    Owner, OwnershipEvent, Mutation, Registration,
    Discrepancy, Evidence,
    VerificationCase, VerificationAction,
    FeedbackSample, AuditLog, GisGeometry, GisGeometryVersion,
]

# Index declared foreign-key columns used repeatedly by the document, parcel,
# verification and audit joins. These are additive and keep both SQL backends
# efficient. Existing single-column indexes are left alone.
for model in all_models:
    table = model.__table__
    indexed_columns = {
        column.name
        for index in table.indexes
        for column in index.columns
        if len(index.columns) == 1
    }
    for column in table.columns:
        if column.foreign_keys and not column.primary_key and column.name not in indexed_columns:
            Index(f"ix_{table.name}_{column.name}", column)

# Frequent chronological audit scans and review queue ordering.
Index("ix_audit_logs_created_at", AuditLog.created_at)
Index("ix_verification_cases_status_created_at", VerificationCase.status, VerificationCase.created_at)
