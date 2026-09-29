from uuid import uuid4

from storage import ALLOWED_MIME_TYPES, MARKDOWN_KIND_PII, MARKDOWN_KIND_REDACTED
from storage.keys import (
    MARKDOWN_ARTIFACTS,
    build_key,
    markdown_artifact_filename,
    markdown_key,
    original_filename_for,
)

# The filename the ai-worker's PII gate writes. Duplicated as a literal on
# purpose: ``app/pii/persistence.py`` cannot be imported from this package (it
# depends on the worker app), so this is the only place the two can be pinned
# against each other, and a plain constant comparison beats asserting the
# package's own dict against itself.
PII_ARTIFACT_NAME = "pii_result.json"


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
    assert markdown_artifact_filename("classification") == "classification_result.json"
    assert markdown_artifact_filename("pii") == "pii_result.json"
    assert markdown_artifact_filename("redacted") == "redacted.md"


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


def test_markdown_key_classification_builds_full_immutable_path():
    tenant = "acme"
    patient_id, document_id, version_id = uuid4(), uuid4(), uuid4()
    key = markdown_key(
        tenant_id=tenant,
        patient_id=patient_id,
        document_id=document_id,
        version_id=version_id,
        kind="classification",
    )
    expected = (
        f"tenants/{tenant}/patients/{patient_id}"
        f"/documents/{document_id}/versions/{version_id}/classification_result.json"
    )
    assert key == expected


def test_markdown_key_pii_builds_full_immutable_path():
    tenant = "acme"
    patient_id, document_id, version_id = uuid4(), uuid4(), uuid4()
    key = markdown_key(
        tenant_id=tenant,
        patient_id=patient_id,
        document_id=document_id,
        version_id=version_id,
        kind="pii",
    )
    expected = (
        f"tenants/{tenant}/patients/{patient_id}"
        f"/documents/{document_id}/versions/{version_id}/pii_result.json"
    )
    assert key == expected


def test_pii_kind_constant_is_in_sync_with_the_filename_table():
    # The two live in the same package but in different modules, and a kind
    # constant that disagrees with the dict it indexes is a KeyError at the first
    # upload of a document — a production-time failure for a data-layer typo.
    assert MARKDOWN_KIND_PII in MARKDOWN_ARTIFACTS
    assert markdown_artifact_filename(MARKDOWN_KIND_PII) == PII_ARTIFACT_NAME


def test_redacted_kind_constant_is_in_sync_with_the_filename_table():
    # Same reason as the PII kind constant: two modules, one table, and a
    # disagreement is a KeyError on the first *external* upload — i.e. only in
    # the configuration this artifact exists for.
    assert MARKDOWN_KIND_REDACTED in MARKDOWN_ARTIFACTS
    assert markdown_artifact_filename(MARKDOWN_KIND_REDACTED) == "redacted.md"


def test_every_markdown_artifact_filename_is_unique():
    # Two kinds mapping to one filename would make the second upload silently
    # overwrite the first, and the loser is whichever wrote last.
    assert len(set(MARKDOWN_ARTIFACTS.values())) == len(MARKDOWN_ARTIFACTS)