import pytest
from canonical import (
    CANONICAL_MODELS,
    DEFAULT_CANONICAL_MODEL,
    FrontmatterMeta,
    GenericCanonical,
    LaboratoryCanonical,
    PrescriptionCanonical,
    build_canonical,
    render_document,
    render_frontmatter,
    render_markdown,
)
from pydantic import ValidationError


def test_registry_contains_all_schemas():
    assert set(CANONICAL_MODELS) == {"generic", "laboratory", "prescription"}
    assert CANONICAL_MODELS["generic"] is GenericCanonical
    assert CANONICAL_MODELS["laboratory"] is LaboratoryCanonical
    assert CANONICAL_MODELS["prescription"] is PrescriptionCanonical
    assert DEFAULT_CANONICAL_MODEL is GenericCanonical


def test_build_canonical_laboratory_valid():
    raw = {
        "document_date": "2024-01-01",
        "type": "laboratory",
        "subtype": "laboratory",
        "fields": {
            "results": [
                {
                    "name": "Гемоглобин",
                    "value": 145,
                    "unit": "g/l",
                    "reference_min": 120,
                    "reference_max": 160,
                }
            ]
        },
    }
    canonical = build_canonical("laboratory", raw)
    assert canonical.schema_name == "laboratory"
    assert canonical.fields.results[0].name == "Гемоглобин"
    assert canonical.fields.results[0].flagged is False


def test_build_canonical_prescription_valid():
    raw = {
        "type": "prescription",
        "subtype": "prescription",
        "fields": {
            "medications": [{"name": "Амоксициллин", "dosage": "500 мг"}],
            "doctor": "Иванов",
        },
    }
    canonical = build_canonical("prescription", raw)
    assert canonical.schema_name == "prescription"
    assert canonical.fields.medications[0].name == "Амоксициллин"
    assert canonical.fields.doctor == "Иванов"


def test_build_canonical_generic_for_unknown_type():
    raw = {"type": "unknown", "subtype": "", "fields": {"note": "текст"}}
    canonical = build_canonical("whatever", raw)
    assert isinstance(canonical, GenericCanonical)
    assert canonical.schema_name == "generic"
    assert canonical.fields["note"] == "текст"


def test_build_canonical_rejects_extra_fields():
    raw = {
        "type": "laboratory",
        "subtype": "laboratory",
        "fields": {"results": []},
        "unexpected": True,
    }
    with pytest.raises(ValidationError):
        build_canonical("laboratory", raw)


def test_render_frontmatter_uses_python_built_metadata():
    meta = FrontmatterMeta(
        doc_id="doc-1",
        type="laboratory",
        subtype="laboratory",
        source={"filename": "report.pdf", "mime_type": "application/pdf"},
        processing={"extraction": {"model": "qwen", "prompt_version": "1", "schema": "laboratory"}},
    )
    text = render_frontmatter(meta)
    assert text.startswith("---")
    assert text.endswith("---")
    assert "doc_id" in text and "doc-1" in text
    assert "report.pdf" in text


def test_render_markdown_laboratory():
    raw = {
        "type": "laboratory",
        "subtype": "laboratory",
        "fields": {
            "results": [{"name": "Гемоглобин", "value": 145, "unit": "g/l", "flagged": True}]
        },
    }
    canonical = build_canonical("laboratory", raw)
    body = render_markdown(canonical)
    assert "Гемоглобин" in body
    assert "⚠" in body


def test_render_document_combines_frontmatter_and_body():
    raw = {
        "type": "prescription",
        "subtype": "prescription",
        "fields": {"medications": [{"name": "Ибупрофен"}]},
    }
    canonical = build_canonical("prescription", raw)
    meta = FrontmatterMeta(doc_id="doc-1", type="prescription", subtype="prescription")
    doc = render_document(canonical, meta)
    assert doc.startswith("---")
    assert "Ибупрофен" in doc
    assert "---" in doc
