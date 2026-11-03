"""Turn uploaded files into text: PDF text layer, OCR for scans/images, DOCX, TXT."""
import io
import logging
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40  # below this a PDF page set is treated as scanned


def extract_text(path: Path, mime_type: str = "") -> str:
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return _pdf(path)
        if ext in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
            return _ocr_image_path(path)
        if ext == ".docx":
            return _docx(path)
        if ext == ".txt":
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # never let one bad file break the pipeline
        log.warning("Text extraction failed for %s: %s", path.name, exc)
    return ""


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    text = "\n".join(parts).strip()
    if len(text) >= MIN_TEXT_CHARS:
        return text
    ocr = _ocr_pdf(path)
    return ocr if len(ocr) > len(text) else text


def _ocr_pdf(path: Path, max_pages: int = 15) -> str:
    if not settings.OCR_ENABLED:
        return ""
    try:
        from pdf2image import convert_from_path
        import pytesseract

        pages = convert_from_path(str(path), dpi=200, first_page=1, last_page=max_pages)
        return "\n".join(pytesseract.image_to_string(p) for p in pages).strip()
    except Exception as exc:
        log.warning("PDF OCR unavailable/failed for %s: %s", path.name, exc)
        return ""


def _ocr_image_path(path: Path) -> str:
    if not settings.OCR_ENABLED:
        return ""
    try:
        import pytesseract
        from PIL import Image, ImageOps

        img = Image.open(path)
        img = ImageOps.exif_transpose(img).convert("L")
        if img.width < 1200:  # small photos OCR better when upscaled
            scale = 1200 / img.width
            img = img.resize((int(img.width * scale), int(img.height * scale)))
        return pytesseract.image_to_string(img).strip()
    except Exception as exc:
        log.warning("Image OCR unavailable/failed for %s: %s", path.name, exc)
        return ""


def _docx(path: Path) -> str:
    import docx

    d = docx.Document(str(path))
    lines = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            lines.append(" | ".join(c.text for c in row.cells))
    return "\n".join(lines).strip()


def extract_from_bytes(data: bytes, filename: str) -> str:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        return extract_text(Path(tmp.name))
