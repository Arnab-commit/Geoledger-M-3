"""Reconciliation and Multi-Document Comparison API endpoints."""

import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.api.auth import get_current_user
from backend.models.user import User
from backend.services.document_service import save_uploaded_file, create_document, read_uploaded_content
from backend.services.reconciliation_service import compare_multiple_documents

logger = logging.getLogger("geoldger.api.reconciliation")

router = APIRouter(prefix="/api/reconciliation", tags=["Reconciliation"])


class DocumentCompareRequest(BaseModel):
    document_ids: List[str] = Field(..., min_length=2, description="List of at least two document IDs to compare")


@router.post("/compare-documents")
async def compare_documents_endpoint(
    req: DocumentCompareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Execute structured field-by-field multi-document comparison.
    Enforces authorization on each document being compared (IDOR protection).
    """
    from backend.models.document import Document
    from backend.security.authorization import authorize_document_access

    for doc_id in req.document_ids:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
        authorize_document_access(doc, current_user, "compare", db)

    try:
        comparison_res = compare_multiple_documents(db, req.document_ids)
        return comparison_res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Document comparison failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Document comparison execution failed")


@router.post("/upload-and-compare")
async def upload_and_compare_endpoint(
    file1: UploadFile = File(...),
    file2: UploadFile = File(...),
    language1: str = Form("all"),
    language2: str = Form("all"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload two land record documents simultaneously, execute OCR, 23-field structured extraction,
    and immediately return side-by-side extracted data and a complete comparison matrix.
    """
    from backend.api.process import process_document

    created_doc_ids = []
    try:
        # Ingest Document 1
        content1 = await read_uploaded_content(file1)
        content2 = await read_uploaded_content(file2)
        file_path1, safe_filename1, file_hash1, mime_type1 = await save_uploaded_file(
            content1, file1.filename, uploaded_by=current_user.username
        )
        doc1 = create_document(
            db=db,
            original_filename=file1.filename,
            safe_filename=safe_filename1,
            file_path=file_path1,
            file_hash=file_hash1,
            file_size=len(content1),
            mime_type=mime_type1,
            uploaded_by=current_user.username,
            language=language1,
        )
        doc1.uploader_id = current_user.id
        db.commit()
        created_doc_ids.append(doc1.id)

        # Ingest Document 2
        file_path2, safe_filename2, file_hash2, mime_type2 = await save_uploaded_file(
            content2, file2.filename, uploaded_by=current_user.username
        )
        doc2 = create_document(
            db=db,
            original_filename=file2.filename,
            safe_filename=safe_filename2,
            file_path=file_path2,
            file_hash=file_hash2,
            file_size=len(content2),
            mime_type=mime_type2,
            uploaded_by=current_user.username,
            language=language2,
        )
        doc2.uploader_id = current_user.id
        db.commit()
        created_doc_ids.append(doc2.id)

        # Process Document 1
        await process_document(document_id=doc1.id, current_user=current_user, db=db)

        # Process Document 2
        await process_document(document_id=doc2.id, current_user=current_user, db=db)

        # Execute Comparison Matrix
        comparison_res = compare_multiple_documents(db, created_doc_ids)
        return comparison_res

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Upload and compare failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Comparison pipeline failed. Check document statuses and retry.")
