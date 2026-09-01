from uuid import uuid4

from storage import ALLOWED_MIME_TYPES
from storage.keys import (
    build_key,
    markdown_artifact_filename,
    markdown_key,
    original_filename_for,
)


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


def test_markdown_artifact_filename_known_kinds():
    assert markdown_artifact_filename("unstructured") == "marker.md"
    assert markdown_artifact_filename("structured") == "structured.md"
    assert markdown_artifact_filename("canonical") == "canonical.json"


def test_markdown_artifact_filename_unknown_kind_raises():
    try:
        markdown_artifact_filename("nope")
    except ValueError as exc:
        assert "unknown markdown artifact" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_markdown_key_builds_full_immutable_path():
    tenant = "acme"
    patient_id, document_id, version_id = uuid4(), uuid4(), uuid4()
    key = markdown_key(
        tenant_id=tenant,
        patient_id=patient_id,
        document_id=document_id,
        version_id=version_id,
        kind="unstructured",
    )
    expected = (
        f"tenants/{tenant}/patients/{patient_id}"
        f"/documents/{document_id}/versions/{version_id}/marker.md"
    )
    assert key == expected


def test_markdown_key_canonical_builds_full_immutable_path():
    tenant = "acme"
    patient_id, document_id, version_id = uuid4(), uuid4(), uuid4()
    key = markdown_key(
        tenant_id=tenant,
        patient_id=patient_id,
        document_id=document_id,
        version_id=version_id,
        kind="canonical",
    )
    expected = (
        f"tenants/{tenant}/patients/{patient_id}"
        f"/documents/{document_id}/versions/{version_id}/canonical.json"
    )
    assert key == expected