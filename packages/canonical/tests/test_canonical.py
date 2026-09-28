import pytest
from canonical import (
    CANONICAL_MODELS,
    DEFAULT_CANONICAL_MODEL,
    FrontmatterMeta,
    GenericCanonical,
    LaboratoryCanonical,
    PIIMeta,
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


def test_build_canonical_laboratory_rich_fields():
    raw = {
        "document_date": "2026-02-28",
        "language": "ru",
        "type": "laboratory",
        "subtype": "laboratory",
        "institution": {
            "name": "Клиника № 2",
            "address": "г. Сургут",
            "ogrn": "1028600607441",
        },
        "material": "Кровь венозная",
        "equipment": "Анализатор X",
        "conclusion": "В пределах нормы",
        "performed_by": ["Иванов - врач", "Петров - техник"],
        "fields": {
            "results": [
                {
                    "name": "СОЭ",
                    "value": "4",
                    "unit": "мм/ч",
                    "interpretation": "норма",
                    "comment": "повторить",
                }
            ]
        },
    }
    canonical = build_canonical("laboratory", raw)
    assert canonical.schema_name == "laboratory"
    assert canonical.institution.name == "Клиника № 2"
    assert canonical.material == "Кровь венозная"
    assert canonical.equipment == "Анализатор X"
    assert canonical.conclusion == "В пределах нормы"
    assert canonical.performed_by == ["Иванов - врач", "Петров - техник"]
    item = canonical.fields.results[0]
    assert item.interpretation == "норма"
    assert item.comment == "повторить"


def test_render_markdown_laboratory_rich_fields():
    raw = {
        "type": "laboratory",
        "subtype": "laboratory",
        "material": "Кровь венозная",
        "conclusion": "В пределах нормы",
        "performed_by": ["Иванов - врач"],
        "fields": {
            "results": [
                {
                    "name": "СОЭ",
                    "value": "4",
                    "unit": "мм/ч",
                    "interpretation": "норма",
                    "comment": "повторить",
                }
            ]
        },
    }
    canonical = build_canonical("laboratory", raw)
    body = render_markdown(canonical)
    assert "Кровь венозная" in body
    assert "В пределах нормы" in body
    assert "Иванов - врач" in body
    assert "норма" in body
    assert "повторить" in body


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


# --- PIIMeta (PII GATE plan §4.7) -----------------------------------------
#
# The block is written by ``app/pii`` and rendered here, so the contract that
# matters is the one at the seam: the model accepts exactly the gate's block and
# rejects anything else. A widened model is a second, silently-diverging
# definition of the same shape; a missing one is a frontmatter that renders with
# no verdict on a document that was scanned.

PII_BLOCK = {
    "decision": "allow",
    "risk_level": "medium",
    "stage": "document",
    "destination": "internal_llm",
    "findings_count": 7,
    "category_counts": {"person_name": 1, "date_of_birth": 1, "address": 2},
    "categories": ["person_name", "date_of_birth", "address"],
    "detector_version": "1.1.0",
    "policy_version": "1.0.0",
    "reasons": ["expected_medical_identity"],
    "warnings": [],
}


def test_pii_meta_accepts_the_gate_block_verbatim():
    assert PIIMeta(**PII_BLOCK).model_dump(mode="json") == PII_BLOCK


def test_pii_meta_rejects_unknown_keys():
    # extra="forbid", mirroring ClassificationMeta: a block key the renderer
    # does not know about is a gate/model drift, and silently dropping it would
    # render a verdict missing the field that drifted.
    with pytest.raises(ValidationError):
        PIIMeta(**{**PII_BLOCK, "raw_value": "пациент"})


def test_pii_meta_rejects_a_block_missing_a_required_key():
    for key in PII_BLOCK:
        if key in {"reasons", "warnings"}:
            continue
        with pytest.raises(ValidationError):
            PIIMeta(**{k: v for k, v in PII_BLOCK.items() if k != key})


def test_pii_meta_reasons_and_warnings_default_empty():
    block = {k: v for k, v in PII_BLOCK.items() if k not in {"reasons", "warnings"}}
    dumped = PIIMeta(**block).model_dump(mode="json")
    assert dumped["reasons"] == []
    assert dumped["warnings"] == []


def test_pii_meta_has_no_field_for_a_value_or_a_fingerprint():
    fields = set(PIIMeta.model_fields)
    assert fields & {"value", "masked_value", "value_fingerprint", "findings"} == set()
    assert set(PIIMeta(**PII_BLOCK).model_dump(mode="json")) == set(PII_BLOCK)


def test_frontmatter_omits_the_pii_block_when_absent():
    # to_dict() is exclude_none=True, so a document scanned before the gate was
    # wired keeps the pre-M5 frontmatter byte-for-byte rather than growing a
    # "pii: null" that a consumer would have to special-case.
    meta = FrontmatterMeta(doc_id="doc-1", type="generic", subtype="generic")
    assert "pii" not in meta.to_dict()
    assert "pii" not in render_frontmatter(meta)


def test_frontmatter_renders_the_pii_block_and_round_trips():
    meta = FrontmatterMeta(
        doc_id="doc-1",
        type="generic",
        subtype="generic",
        pii=PII_BLOCK,
    )
    block = meta.to_dict()["pii"]
    assert block == PII_BLOCK

    text = render_frontmatter(meta)
    assert "pii:" in text
    assert "person_name" in text
    assert "1.1.0" in text
    # ...and a parsed copy validates back into the same model, so a renderer
    # change (a renamed key, a stringified mapping) cannot pass unnoticed.
    import yaml

    body = text.removeprefix("---\n").removesuffix("---")
    assert PIIMeta(**yaml.safe_load(body)["pii"]).model_dump(mode="json") == PII_BLOCK


def test_pii_block_sits_beside_classification_not_inside_it():
    # Two sibling blocks, mirroring §4.7. Nesting the verdict under
    # ``classification`` would make a document with a classification and no PII
    # indistinguishable from one that was never scanned.
    meta = FrontmatterMeta(doc_id="doc-1", type="generic", subtype="generic", pii=PII_BLOCK)
    dumped = meta.to_dict()
    assert "classification" not in dumped
    assert dumped["pii"]["decision"] == "allow"
