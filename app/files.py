from __future__ import annotations

import base64
import mimetypes
import uuid
from pathlib import Path

# Register HEIC/HEIF since Python's mimetypes db omits them
mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")
mimetypes.add_type("image/heic", ".HEIC")
mimetypes.add_type("image/heif", ".HEIF")

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "text/css",
    "text/javascript",
    "application/json",
    "application/x-yaml",
    "text/yaml",
    "text/x-python",
    "text/x-csrc",
    "text/x-c++src",
    "text/x-java-source",
    "text/x-sh",
}

IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
}


def is_image(content_type: str) -> bool:
    return content_type in IMAGE_CONTENT_TYPES


def is_pdf(content_type: str) -> bool:
    return content_type == "application/pdf"


def is_allowed(content_type: str) -> bool:
    if content_type in ALLOWED_CONTENT_TYPES:
        return True
    # Allow all text/* subtypes
    return content_type.startswith("text/")


def save_upload(data: bytes, original_filename: str, upload_dir: Path) -> tuple[str, str]:
    """Save raw bytes to upload_dir with a unique name.
    Returns (saved_filename, file_path_str).
    """
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_filename).suffix or ""
    unique_name = f"{uuid.uuid4().hex}{suffix}"
    dest = upload_dir / unique_name
    dest.write_bytes(data)
    return unique_name, str(dest)


def encode_image_base64(file_path: str) -> str:
    return base64.b64encode(Path(file_path).read_bytes()).decode()


def extract_text(content_type: str, file_path: str) -> str | None:
    """Return text content for injection into the model context, or None on failure."""
    path = Path(file_path)
    if not path.exists():
        return None

    if is_pdf(content_type):
        return _extract_pdf_text(path)

    # text/* and other text-based types
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _extract_pdf_text(path: Path) -> str | None:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        return "\n\n".join(pages) if pages else None
    except Exception:
        return None


def guess_content_type(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"
