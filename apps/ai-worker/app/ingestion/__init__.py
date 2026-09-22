"""Document ingestion: unpack source files and OCR them to markdown."""

from app.ingestion.loader import (
    _IMAGE_EXTENSIONS,
    _PDF_EXTENSION,
    convert_pdf_to_images,
    get_pdf_page_count,
    load_images,
)
from app.ingestion.ocr import OcrEngine, count_pages

__all__ = [
    "OcrEngine",
    "_IMAGE_EXTENSIONS",
    "_PDF_EXTENSION",
    "convert_pdf_to_images",
    "count_pages",
    "get_pdf_page_count",
    "load_images",
]