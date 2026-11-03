"""File storage. Files live outside any public/static path and are only served
through an authorised route. Stored names are random, never the patient's filename."""
import hashlib
import mimetypes
import secrets
from pathlib import Path

from .config import settings

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".txt", ".docx"}


class UploadError(ValueError):
    pass


def save_bytes(patient_code: str, original_name: str, data: bytes) -> dict:
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError(f"{original_name}: file type {ext or '(none)'} is not supported. "
                          f"Use PDF, image (JPG/PNG), DOCX or TXT.")
    if not data:
        raise UploadError(f"{original_name}: file is empty.")
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise UploadError(f"{original_name}: file is larger than {settings.MAX_UPLOAD_MB} MB.")
    folder = settings.files_dir / _safe(patient_code)
    folder.mkdir(parents=True, exist_ok=True)
    stored = f"{secrets.token_hex(16)}{ext}"
    (folder / stored).write_bytes(data)
    mime = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    return {
        "stored_name": f"{_safe(patient_code)}/{stored}",
        "mime_type": mime,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def path_for(stored_name: str) -> Path:
    p = (settings.files_dir / stored_name).resolve()
    if settings.files_dir.resolve() not in p.parents:
        raise UploadError("Invalid file path")
    return p


def delete(stored_name: str) -> None:
    try:
        path_for(stored_name).unlink(missing_ok=True)
    except UploadError:
        pass


def _safe(s: str) -> str:
    return "".join(c for c in s if c.isalnum() or c in "-_") or "unknown"
