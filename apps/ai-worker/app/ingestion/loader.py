"""Document ingestion: download, unpack, and render documents to images.

The pipeline consumes either a PDF (rendered page-by-page) or a raster image
as its input source when converting to unstructured markdown.
"""

import asyncio
import logging
import os
from typing import Literal

import pymupdf

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}
_PDF_EXTENSION = ".pdf"


def convert_pdf_to_images(
    pdf_bytes: bytes,
    dpi: int = 300,
    format: Literal["png", "jpeg"] = "png",
) -> list[bytes]:
    """Render each PDF page to an image.

    Args:
        pdf_bytes: PDF file content as bytes.
        dpi: Render resolution in dots per inch.
        format: Output image format ("png" or "jpeg").

    Returns:
        One image blob per page, in page order.
    """
    if format not in ("png", "jpeg"):
        raise ValueError(f"unsupported image format: {format}")

    zoom = dpi / 72  # PyMuPDF zoom is relative to the 72 DPI default
    matrix = pymupdf.Matrix(zoom, zoom)

    images: list[bytes] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        for page_num in range(len(document)):
            page = document.load_page(page_num)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            images.append(pixmap.tobytes(format))
    return images


def get_pdf_page_count(pdf_bytes: bytes) -> int:
    """Return the number of pages in a PDF."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        return len(document)


async def load_images(s3, storage_key: str, dpi: int = 300, format: str = "png") -> list[bytes]:
    """Download the input from S3 and return a list of image blobs.

    For a PDF the pages are rendered to images; for an image upload the
    original blob is returned directly.
    """
    file_bytes = await asyncio.to_thread(s3.download_bytes, storage_key)
    extension = os.path.splitext(storage_key)[1].lower()

    if extension == _PDF_EXTENSION:
        return await asyncio.to_thread(
            convert_pdf_to_images,
            file_bytes,
            dpi,
            format,
        )
    if extension in _IMAGE_EXTENSIONS:
        return [file_bytes]
    raise ValueError(f"unsupported document extension: {extension}")