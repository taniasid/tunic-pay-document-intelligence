"""
Ingest layer: validate, read, and normalise uploaded files into a
FilePayload that downstream stages can consume without knowing the
original file type.

Images are resized to a maximum dimension before base64 encoding to
stay within API payload limits (~5MB base64 per image).
"""

from __future__ import annotations
import base64
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# Optional PDF-to-image dependency
try:
    from pdf2image import convert_from_bytes
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

SUPPORTED_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

MAX_FILE_SIZE_MB = 20
CONFIDENCE_THRESHOLD = 0.60   # Below this → route to 'other' for human review

# Resize images so the longest edge is at most this many pixels.
# Keeps base64 payload well under API limits while preserving readability.
MAX_IMAGE_DIMENSION = 1568
JPEG_QUALITY = 85


@dataclass
class FilePayload:
    file_id: str
    original_filename: str
    images_b64: list[str]          # One entry per page; always base64 JPEG
    mime_type: str = "image/jpeg"


class IngestError(ValueError):
    """Raised for user-facing file problems (bad type, too large, corrupt)."""


def ingest_file(file_bytes: bytes, filename: str) -> FilePayload:
    """
    Validate and normalise an uploaded file.

    Returns a FilePayload with base64-encoded, resized JPEG pages.
    Raises IngestError for anything the user should fix.
    """
    suffix = Path(filename).suffix.lower()

    if suffix not in SUPPORTED_MIME_TYPES:
        raise IngestError(
            f"Unsupported file type '{suffix}'. "
            f"Accepted: {', '.join(SUPPORTED_MIME_TYPES)}"
        )

    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise IngestError(
            f"File is {size_mb:.1f} MB — maximum allowed is {MAX_FILE_SIZE_MB} MB."
        )

    if len(file_bytes) < 16:
        raise IngestError("File appears to be empty or corrupt.")

    file_id = _make_file_id(filename)

    if suffix == ".pdf":
        pages_b64 = _pdf_to_images_b64(file_bytes)
    else:
        pages_b64 = [_image_bytes_to_b64(file_bytes)]

    return FilePayload(
        file_id=file_id,
        original_filename=filename,
        images_b64=pages_b64,
        mime_type="image/jpeg",
    )


def _image_bytes_to_b64(file_bytes: bytes) -> str:
    """
    Open an image, resize it so the longest edge <= MAX_IMAGE_DIMENSION,
    re-encode as JPEG, and return as a base64 string.
    """
    img = Image.open(io.BytesIO(file_bytes))

    # Convert palette/RGBA modes so JPEG save works
    if img.mode in ("P", "RGBA", "LA"):
        img = img.convert("RGB")

    # Resize if needed, preserving aspect ratio
    w, h = img.size
    if max(w, h) > MAX_IMAGE_DIMENSION:
        scale = MAX_IMAGE_DIMENSION / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def _pdf_to_images_b64(file_bytes: bytes) -> list[str]:
    """Convert each PDF page to a resized base64 JPEG string."""
    if not PDF_SUPPORT:
        raise IngestError(
            "PDF support requires pdf2image + poppler. "
            "Install with: pip install pdf2image"
        )
    try:
        pages = convert_from_bytes(file_bytes, dpi=150)
    except Exception as exc:
        raise IngestError(f"Could not parse PDF: {exc}") from exc

    result = []
    for page in pages:
        buf = io.BytesIO()
        page.save(buf, format="PNG")
        result.append(_image_bytes_to_b64(buf.getvalue()))
    return result


def _make_file_id(filename: str) -> str:
    """Deterministic, filesystem-safe ID from filename."""
    stem = Path(filename).stem
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    return safe[:40]