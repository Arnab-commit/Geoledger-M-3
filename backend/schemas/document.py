"""Document schemas."""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class DocumentResponse(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_hash: str
    file_size: int
    mime_type: str
    page_count: int
    document_type: str
    classification_confidence: Optional[float] = None
    language: str
    processing_status: str
    processing_error: Optional[str] = None
    uploaded_by: Optional[str] = None
    upload_timestamp: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int
