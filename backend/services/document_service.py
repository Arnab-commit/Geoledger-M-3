"""Document management service."""

import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.document import Document, DocumentPage, ProcessingStatus, DocumentType
from backend.utils.file_utils import (
    compute_file_hash,
    generate_safe_filename,
    validate_file_extension,
    validate_file_size,
    validate_mime_type,
    get_mime_type,
)

logger = logging.getLogger("geoldger.document")


async def read_uploaded_content(upload_file) -> bytes:
    """Read an upload in bounded chunks and stop before oversized bodies fill memory."""
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    chunks = []
    total = 0
    while True:
        chunk = await upload_file.read(min(1024 * 1024, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"File exceeds maximum size of {settings.MAX_FILE_SIZE_MB}MB")
        chunks.append(chunk)
    return b"".join(chunks)


async def save_uploaded_file(
    file_content: bytes,
    original_filename: str,
    uploaded_by: str = None
) -> tuple[Path, str, str, str]:
    """
    Save uploaded file to storage.
    Returns: (file_path, safe_filename, file_hash, mime_type)
    """
    # Validate extension
    if not validate_file_extension(original_filename):
        raise ValueError(f"File type not allowed: {original_filename}")

    # Validate size
    if not validate_file_size(len(file_content)):
        max_mb = settings.MAX_FILE_SIZE_MB
        raise ValueError(f"File exceeds maximum size of {max_mb}MB")

    # Validate MIME type via magic bytes
    mime_type = validate_mime_type(file_content, original_filename)
    if mime_type is None:
        raise ValueError("Invalid file content or unsupported file type")

    # Compute hash
    file_hash = compute_file_hash(file_content)

    # Generate safe filename
    safe_filename = generate_safe_filename(original_filename)

    # Save to original directory
    original_dir = Path(settings.ORIGINAL_DIR)
    original_dir.mkdir(parents=True, exist_ok=True)

    file_path = original_dir / safe_filename

    # Write file
    with open(file_path, "wb") as f:
        f.write(file_content)

    logger.info(f"File saved: {safe_filename} ({len(file_content)} bytes)")

    return file_path, safe_filename, file_hash, mime_type


def create_document(
    db: Session,
    original_filename: str,
    safe_filename: str,
    file_path: Path,
    file_hash: str,
    file_size: int,
    mime_type: str,
    uploaded_by: str = None,
    language: str = "eng",
) -> Document:
    """Create document record in database."""
    document = Document(
        filename=safe_filename,
        original_filename=original_filename,
        file_path=str(file_path),
        file_hash=file_hash,
        file_size=file_size,
        mime_type=mime_type,
        uploaded_by=uploaded_by,
        language=language,
        processing_status=ProcessingStatus.UPLOADED,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    logger.info(f"Document created: {document.id} - {original_filename}")
    return document


def get_document(db: Session, document_id: str) -> Document:
    """Get document by ID."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise ValueError(f"Document not found: {document_id}")
    return doc


def list_documents(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: ProcessingStatus = None
) -> tuple[list[Document], int]:
    """List documents with pagination."""
    query = db.query(Document)

    if status:
        query = query.filter(Document.processing_status == status)

    total = query.count()
    documents = query.order_by(Document.upload_timestamp.desc()).offset(skip).limit(limit).all()

    return documents, total


def update_document_status(
    db: Session,
    document_id: str,
    status: ProcessingStatus,
    error: str = None
):
    """Update document processing status."""
    doc = get_document(db, document_id)
    doc.processing_status = status
    if error:
        doc.processing_error = error
    if status == ProcessingStatus.COMPLETED:
        doc.processed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(f"Document {document_id} status: {status}")
