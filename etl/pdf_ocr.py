"""
PDF text extraction for archival UAP documents.

Tries PyMuPDF (fitz) first — fastest and handles both native text and
embedded OCR layers. Falls back to pdfplumber for complex layouts.

Usage:
    from etl.pdf_ocr import extract_text
    text = extract_text("/path/to/file.pdf")
"""

from __future__ import annotations
import os


def extract_text(path: str, max_pages: int = 50) -> str:
    """
    Extracts text from a PDF file.
    Returns a single string with pages separated by form-feed characters.
    Raises FileNotFoundError if the path does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF not found: {path}")

    text = _try_pymupdf(path, max_pages)
    if text and len(text.strip()) > 100:
        return text

    # fallback
    text = _try_pdfplumber(path, max_pages)
    if text and len(text.strip()) > 100:
        return text

    raise RuntimeError(
        f"Could not extract readable text from {path}. "
        "The file may be a scanned image PDF — run it through an OCR tool (e.g. ocrmypdf) first."
    )


def _try_pymupdf(path: str, max_pages: int) -> str | None:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    try:
        doc = fitz.open(path)
        pages = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pages.append(page.get_text())
        doc.close()
        return "\f".join(pages)
    except Exception:
        return None


def _try_pdfplumber(path: str, max_pages: int) -> str | None:
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        pages = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                pages.append(page.extract_text() or "")
        return "\f".join(pages)
    except Exception:
        return None
