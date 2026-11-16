"""Text extraction: native PDF text, OCR for images and scanned PDFs (on-device Tesseract, heb+eng).

Nothing in this module talks to the network: OCR runs locally so document contents never leave
the server for extraction.
"""
from __future__ import annotations

import io
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SUPPORTED_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/tiff": ".tiff",
    "text/plain": ".txt",
}


@dataclass
class Extraction:
    text: str
    ocr_used: bool
    pages: int
    language: str | None


def sniff_mime(data: bytes, filename: str) -> str | None:
    """Detect type from magic bytes; never trust the client-supplied content type."""
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypheim"):
        return "image/heic"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if filename.lower().endswith(".txt"):
        try:
            data[:4096].decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            return None
    return None


def detect_language(text: str) -> str | None:
    heb = len(re.findall(r"[֐-׿]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    if heb + lat < 5:
        return None
    if heb and lat and min(heb, lat) / max(heb, lat) > 0.35:
        return "mixed"
    return "he" if heb > lat else "en"


def _ocr_image(img, langs: str) -> str:
    import pytesseract
    from PIL import ImageOps
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    # Upscale small photos: Tesseract is far more accurate at ~300dpi-equivalent sizes.
    w, h = img.size
    if max(w, h) < 1600:
        f = 1600 / max(w, h)
        img = img.resize((int(w * f), int(h * f)))
    gray = ImageOps.grayscale(img)
    text = pytesseract.image_to_string(gray, lang=langs, config="--psm 3")
    # Rotated phone photos: retry with orientation detection if we got almost nothing.
    if len(text.strip()) < 15:
        try:
            osd = pytesseract.image_to_osd(gray)
            angle = int(re.search(r"Rotate: (\d+)", osd).group(1))
            if angle:
                text = pytesseract.image_to_string(gray.rotate(-angle, expand=True), lang=langs)
        except Exception:
            pass
    return text


def extract_text(data: bytes, mime: str, langs: str = "heb+eng", max_pdf_pages: int = 6) -> Extraction:
    if mime == "text/plain":
        t = data.decode("utf-8", errors="replace")
        return Extraction(t, False, 1, detect_language(t))
    if mime.startswith("image/"):
        from PIL import Image
        if mime == "image/heic":
            raise ValueError("heic_not_supported_yet")
        with Image.open(io.BytesIO(data)) as img:
            text = _ocr_image(img, langs)
        return Extraction(_clean(text), True, 1, detect_language(text))
    if mime == "application/pdf":
        return _extract_pdf(data, langs, max_pdf_pages)
    raise ValueError(f"unsupported type {mime}")


def _extract_pdf(data: bytes, langs: str, max_pages: int) -> Extraction:
    import pdfplumber
    texts, pages = [], 0
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages[:max_pages * 3]:
                texts.append(page.extract_text() or "")
    except Exception as e:  # malformed PDFs still get an OCR attempt
        log.warning("pdfplumber failed: %s", e)
    native = _clean("\n".join(texts))
    if native and _fix_reversed_hebrew(native) != native:
        native = _fix_reversed_hebrew(native)
    if len(re.sub(r"\s", "", native)) >= 40:
        return Extraction(native, False, pages, detect_language(native))
    # Scanned PDF: rasterise the first pages and OCR them locally.
    from PIL import Image
    ocr_texts = []
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(data)
        subprocess.run(["pdftoppm", "-r", "200", "-l", str(max_pages), "-png", str(src), str(Path(tmp) / "p")],
                       check=False, capture_output=True, timeout=120)
        for png in sorted(Path(tmp).glob("p*.png")):
            with Image.open(png) as img:
                ocr_texts.append(_ocr_image(img, langs))
    text = _clean("\n".join(ocr_texts)) or native
    return Extraction(text, True, pages or len(ocr_texts), detect_language(text))


def _fix_reversed_hebrew(text: str) -> str:
    """Some PDF generators store Hebrew in visual order; pdfplumber then yields reversed words.
    Heuristic: if common Hebrew words appear reversed more often than forward, flip Hebrew runs."""
    common = ["של", "את", "על", "אישור", "מספר", "תאריך", "שם", "חשבון", "לימודים", "זהות"]
    fwd = sum(text.count(w) for w in common)
    rev = sum(text.count(w[::-1]) for w in common)
    if rev > fwd and rev >= 2:
        return "\n".join(" ".join(reversed([w[::-1] if re.search(r"[֐-׿]", w) else w
                                             for w in line.split()]))
                         for line in text.splitlines())
    return text


def _clean(text: str) -> str:
    text = text.replace("\x0c", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def make_thumbnail(data: bytes, mime: str) -> bytes | None:
    """Small JPEG preview (first page for PDFs)."""
    from PIL import Image, ImageOps
    try:
        if mime.startswith("image/") and mime != "image/heic":
            img = Image.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img)
        elif mime == "application/pdf":
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "in.pdf"
                src.write_bytes(data)
                subprocess.run(["pdftoppm", "-r", "50", "-l", "1", "-jpeg", str(src), str(Path(tmp) / "t")],
                               check=False, capture_output=True, timeout=60)
                files = sorted(Path(tmp).glob("t*.jpg"))
                if not files:
                    return None
                img = Image.open(files[0])
                img.load()
        else:
            return None
        img = img.convert("RGB")
        img.thumbnail((360, 360))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=72)
        return out.getvalue()
    except Exception as e:
        log.info("thumbnail failed: %s", e)
        return None
