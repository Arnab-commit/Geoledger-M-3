"""Document upload and management API endpoints."""

import logging
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.user import User
from backend.models.document import Document, ProcessingStatus
from backend.schemas.document import DocumentResponse, DocumentListResponse
from backend.api.auth import get_current_user, get_optional_user
from backend.services.document_service import (
    save_uploaded_file,
    read_uploaded_content,
    create_document,
    get_document,
    list_documents,
)
from backend.services.audit_service import log_action

from backend.security.permissions import (
    DOCUMENTS_UPLOAD,
    DOCUMENTS_READ_OWN,
    DOCUMENTS_READ_SCOPED,
    DOCUMENTS_READ_ALL,
)
from backend.security.jurisdiction import filter_documents_by_scope
from backend.security.authorization import require_permission, authorize_document_access, log_security_event

logger = logging.getLogger("geoldger.upload")
router = APIRouter(prefix="/api/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    source: str = Form(None),
    language: str = Form("eng"),
    current_user: User = Depends(require_permission(DOCUMENTS_UPLOAD)),
    db: Session = Depends(get_db),
):
    """
    Upload a single document (PDF, JPG, PNG).
    Validates file type, computes SHA-256 hash, and saves to storage.
    Enforces uploader ownership binding.
    """
    try:
        # Read file content
        content = await read_uploaded_content(file)

        # Save file to storage
        file_path, safe_filename, file_hash, mime_type = await save_uploaded_file(
            content,
            file.filename,
            uploaded_by=current_user.username
        )

        # Create database record
        document = create_document(
            db=db,
            original_filename=file.filename,
            safe_filename=safe_filename,
            file_path=file_path,
            file_hash=file_hash,
            file_size=len(content),
            mime_type=mime_type,
            uploaded_by=current_user.username,
        )

        # Bind explicit uploader_id and metadata
        document.uploader_id = current_user.id
        if source:
            document.source = source
        if language:
            document.language = language
        db.commit()

        # Log action with security tracking
        log_security_event(
            db=db,
            user=current_user,
            action="DOCUMENT_UPLOADED",
            resource_type="document",
            resource_id=document.id,
            details=f"Uploaded {file.filename} ({len(content)} bytes, hash: {file_hash[:8]}...)",
        )

        logger.info(f"Document uploaded: {document.id} - {file.filename} by {current_user.username}")
        return document

    except ValueError as e:
        logger.warning(f"Upload validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Document upload failed")


@router.get("", response_model=DocumentListResponse)
def get_documents(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    search: str = Query(None, min_length=1, max_length=255),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List documents with pagination scoped by user role & jurisdiction."""
    query = db.query(Document)

    if status:
        try:
            status_enum = ProcessingStatus(status)
            query = query.filter(Document.processing_status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if search:
        term = search.strip()
        if term:
            query = query.filter(
                Document.original_filename.ilike(f"%{term}%") |
                Document.file_hash.ilike(f"{term}%") |
                Document.document_type.ilike(f"%{term}%")
            )

    # Enforce role & jurisdiction scoping
    scoped_query = filter_documents_by_scope(query, current_user, db)
    total = scoped_query.count()
    docs = scoped_query.order_by(Document.upload_timestamp.desc()).offset(skip).limit(limit).all()

    return DocumentListResponse(documents=docs, total=total)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document_details(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get document details by ID with strict ownership/jurisdiction IDOR protection."""
    try:
        doc = get_document(db, document_id)
        # IDOR and Jurisdiction verification
        authorize_document_access(doc, current_user, "read", db)
        return doc
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
