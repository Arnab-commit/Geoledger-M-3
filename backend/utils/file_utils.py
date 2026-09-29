"""File handling utilities."""

import hashlib
import uuid
import mimetypes
from pathlib import Path

from backend.config import settings

# Allowed MIME types mapped from extensions
ALLOWED_MIMES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

# File signatures (magic bytes) for validation
FILE_SIGNATURES = {
    b"%PDF": "application/pdf",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
}


def compute_file_hash(file_content: bytes) -> str:
    """Compute SHA-256 hash of file content."""
    return hashlib.sha256(file_content).hexdigest()


def generate_safe_filename(original_filename: str) -> str:
    """Generate a UUID-based filename preserving the extension."""
    ext = Path(original_filename).suffix.lower()
    return f"{uuid.uuid4()}{ext}"


def validate_file_extension(filename: str) -> bool:
    """Check if file extension is allowed."""
    ext = Path(filename).suffix.lower()
    return ext in settings.ALLOWED_EXTENSIONS


def validate_file_size(file_size: int) -> bool:
    """Check if file size is within limits."""
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    return file_size <= max_bytes


def validate_mime_type(file_content: bytes, claimed_filename: str) -> str | None:
    """Validate file content against magic bytes and return detected MIME type."""
    # Check magic bytes
    for signature, mime in FILE_SIGNATURES.items():
        if file_content[:len(signature)] == signature:
            return mime

    # Fallback to extension-based detection
    ext = Path(claimed_filename).suffix.lower()
    return ALLOWED_MIMES.get(ext)


def get_mime_type(filename: str) -> str:
    """Get MIME type from filename."""
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or "application/octet-stream"
