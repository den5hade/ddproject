from typing import Literal

import pymupdf


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
