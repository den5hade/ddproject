from uuid import uuid4

from storage import ALLOWED_MIME_TYPES
from storage.keys import build_key, original_filename_for


def test_build_key_uses_immutable_ids():
    tenant = "acme"
    patient_id, document_id, version_id = uuid4(), uuid4(), uuid4()
    key = build_key(tenant, patient_id, document_id, version_id, "original.pdf")
    expected = (
        f"tenants/{tenant}/patients/{patient_id}"
        f"/documents/{document_id}/versions/{version_id}/original.pdf"
    )
    assert key == expected
    assert str(key).count("tenants/") == 1
    assert str(key).endswith("original.pdf")


def test_build_key_is_deterministic():
    args = ("t", uuid4(), uuid4(), uuid4(), "original.pdf")
    assert build_key(*args) == build_key(*args)


def test_original_filename_for_known_mime():
    assert original_filename_for("application/pdf") == "original.pdf"
    assert original_filename_for("image/png") == "original.png"


def test_original_filename_for_unknown_mime_falls_back_to_bin():
    assert original_filename_for("application/octet-stream") == "original.bin"


def test_allowed_mime_types_match_extension_map():
    assert "application/pdf" in ALLOWED_MIME_TYPES
    for mime in ALLOWED_MIME_TYPES:
        ext = original_filename_for(mime).split(".")[-1]
        assert ext != "bin"