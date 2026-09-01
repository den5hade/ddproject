from app.pdf_converter import convert_pdf_to_images, get_pdf_page_count


def test_get_pdf_page_count(sample_pdf):
    count = get_pdf_page_count(sample_pdf)
    assert count > 0


def test_convert_pdf_to_images(sample_pdf):
    images = convert_pdf_to_images(sample_pdf, dpi=150)
    assert len(images) > 0
    assert all(isinstance(img, bytes) for img in images)


def test_convert_pdf_to_png_magic(sample_pdf):
    images = convert_pdf_to_images(sample_pdf, format="png")
    assert all(img.startswith(b"\x89PNG\r\n\x1a\n") for img in images)


def test_convert_pdf_to_jpeg_magic(sample_pdf):
    images = convert_pdf_to_images(sample_pdf, format="jpeg")
    assert all(img.startswith(b"\xff\xd8\xff") for img in images)


def test_convert_pdf_to_images_empty_pdf():
    empty = b""
    try:
        convert_pdf_to_images(empty)
    except Exception:
        # PyMuPDF raises on empty/invalid PDF; that is acceptable behavior.
        return
    raise AssertionError("expected an exception for empty PDF")
