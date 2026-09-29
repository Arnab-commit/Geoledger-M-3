"""Document and processing models."""

import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Integer, Float, Text, ForeignKey, TypeDecorator
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship
from backend.database import Base


class SafeEnumType(TypeDecorator):
    """A resilient Enum type decorator that safely resolves case variations, aliases, or unmapped values without throwing 500 LookupErrors."""
    impl = String(100)
    cache_ok = True

    def __init__(self, enum_cls, default_val=None, **kw):
        super().__init__(**kw)
        self.enum_cls = enum_cls
        self.default_val = default_val or list(enum_cls)[-1]

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return self.default_val
        val_str = str(value).strip().lower()
        # Direct value match
        for member in self.enum_cls:
            if member.value.lower() == val_str or member.name.lower() == val_str:
                return member
        # Common alias mappings
        if "mutation" in val_str:
            return DocumentType.MUTATION
        if "sale" in val_str or "deed" in val_str:
            return DocumentType.SALE_DEED
        if "ror" in val_str or "khatian" in val_str:
            return DocumentType.ROR
        return self.default_val


class ProcessingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PREPROCESSING = "preprocessing"
    OCR_PROCESSING = "ocr_processing"
    EXTRACTION = "extraction"
    VALIDATION = "validation"
    COMPLETED = "completed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    FAILED = "failed"


class DocumentType(str, enum.Enum):
    ROR = "ror"
    KHATIAN = "khatian"
    KHASRA = "khasra"
    MUTATION = "mutation"
    MUTATION_DEED = "mutation_deed"
    SALE_DEED = "sale_deed"
    PARTITION = "partition"
    INHERITANCE = "inheritance"
    REGISTRATION = "registration"
    TAX_RECORD = "tax_record"
    COURT_ORDER = "court_order"
    CADASTRAL_MAP = "cadastral_map"
    HISTORICAL = "historical"
    DEED = "deed"
    SALE = "sale"
    UNKNOWN = "unknown"


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(500), nullable=False)
    original_filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_hash = Column(String(64), nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=False)
    page_count = Column(Integer, default=1)
    document_type = Column(SafeEnumType(DocumentType, default_val=DocumentType.UNKNOWN), default=DocumentType.UNKNOWN)
    classification_confidence = Column(Float, nullable=True)
    language = Column(String(50), default="eng")
    source = Column(String(255), nullable=True)
    processing_status = Column(SafeEnumType(ProcessingStatus, default_val=ProcessingStatus.UPLOADED), default=ProcessingStatus.UPLOADED)
    processing_error = Column(Text, nullable=True)
    uploaded_by = Column(String, nullable=True)
    uploader_id = Column(String, ForeignKey("users.id"), nullable=True)
    state = Column(String(100), nullable=True)
    district = Column(String(100), nullable=True)
    tehsil = Column(String(100), nullable=True)
    village = Column(String(100), nullable=True)
    upload_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime, nullable=True)

    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan")
    ocr_results = relationship("OcrResult", back_populates="document", cascade="all, delete-orphan")
    extracted_fields = relationship("ExtractedField", back_populates="document", cascade="all, delete-orphan")
    parcel_documents = relationship("ParcelDocument", back_populates="document")
    evidence_items = relationship("Evidence", back_populates="document")

    def __repr__(self):
        return f"<Document {self.id[:8]} ({self.document_type})>"


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    original_image_path = Column(String(1000), nullable=True)
    processed_image_path = Column(String(1000), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="pages")

    def __repr__(self):
        return f"<DocumentPage doc={self.document_id[:8]} page={self.page_number}>"


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    job_type = Column(String(50), nullable=False)
    status = Column(String(50), default="pending")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    result_summary = Column(Text, nullable=True)

    def __repr__(self):
        return f"<ProcessingJob {self.job_type} ({self.status})>"
