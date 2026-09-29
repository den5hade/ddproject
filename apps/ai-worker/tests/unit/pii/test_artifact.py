"""Phase 10: the persistence surface — what a PII verdict is allowed to reach.

M4 locked the *shape* of the ``"pii"`` block as data
(:data:`~app.pii.persistence.PII_META_REQUIRED_KEYS`) and recorded a gap: with
``PIIMeta`` unbuilt, it could prove the intended shape but not that a written
block conforms to it. This module discharges that gap — every block here is
produced by the real :func:`build_pii_meta_block` and validated through the real
``canonical.PIIMeta``, so the two homes of the shape are pinned against each
other instead of against a literal.

The two acceptance claims of the phase:

1. :func:`build_pii_artifact` output conforms to ``PII_SCAN_RESULT_SCHEMA``
   structurally and carries no raw value;
2. ``build_frontmatter_meta(pii=...)`` round-trips through ``render_frontmatter``.

Both are driven from a **real** gate run over a real fixture, not from a
hand-built result. A hand-built result would pass a shape test while the
projection silently dropped a field the gate actually sets — which is the same
class of miss Phase 9 hit when a pattern rule matched the file on disk and
nothing in the document the pipeline hands the gate.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.canonical.rendering import build_frontmatter_meta
from app.classification.normalize import MarkdownNormalizer
from app.config.settings import Settings
from app.pii import (
    DETECTOR_VERSION,
    PII_ARTIFACT_FILENAME,
    PII_META_OPTIONAL_KEYS,
    PII_META_REQUIRED_KEYS,
    PII_POLICY_VERSION,
    CompositePIIDetector,
    DefaultPIIAggregator,
    DefaultPIIGate,
    DefaultPolicyEngine,
    PatternPIIDetector,
    PIICategory,
    PIIDecision,
    PIIDestination,
    PIIScanResult,
    PIIScanStage,
    PlaceholderRedactor,
    build_pii_artifact,
    build_pii_meta_block,
    build_policy_context,
)
from app.pii.fixtures import iter_pii_fixtures
from app.pii.schemas import PII_FINDING_SCHEMA, PII_SCAN_RESULT_SCHEMA
from canonical import PIIMeta, build_canonical, render_frontmatter

SECRET = "phase-10-persistence-surface-secret"

FIXTURE = next(f for f in iter_pii_fixtures() if f.file.endswith("synthetic-consultation-01.md"))
"""The Phase 9 acceptance fixture, reused so the two phases' claims agree."""

FORBIDDEN_PROPERTIES = ("value", "value_fingerprint")
"""Quoted key names, not substrings — ``masked_value`` is the one allowed hit.

Phase 2 recorded this trap: a naive ``"value" not in blob`` fails on
``"masked_value"``, so a leak scan that passes for the wrong reason is worse
than no scan. Every check below matches a *key*, not a fragment.
"""


# --- real gate output -------------------------------------------------------


def _gate(destination: PIIDestination = PIIDestination.INTERNAL_LLM) -> DefaultPIIGate:
    settings = Settings(pii_fingerprint_secret=SECRET)
    return DefaultPIIGate(
        detector=CompositePIIDetector([PatternPIIDetector(fingerprint_secret=SECRET)]),
        aggregator=DefaultPIIAggregator(),
        policy_engine=DefaultPolicyEngine(),
        policy_context_builder=lambda document, context: build_policy_context(
            settings, stage=PIIScanStage.DOCUMENT, destination=destination
        ),
        redactor=PlaceholderRedactor(),
    )


def _processing_context():
    return SimpleNamespace(
        document_id=FIXTURE.path.stem,
        document_version_id="v1",
        patient_id="p-1",
        client_type="web",
        processing_id="proc-1",
        attributes={},
    )


@pytest.fixture
async def scan_result() -> PIIScanResult:
    """``gate.inspect`` over the fixture's real markdown, at the locked default destination.

    ``INTERNAL_LLM``, not the fixture-manifest context: Phase 10 persists the
    verdict the *production* pipeline produces, and the default destination is
    the one the worker runs with. The manifest's own notes make ``expected_
    decision`` destination-dependent precisely so this stays a free choice.
    """
    markdown = FIXTURE.path.read_text(encoding="utf-8")
    document = MarkdownNormalizer().normalize(markdown)
    return await _gate().inspect(document, _processing_context())


def _walk_keys(node: Any) -> set[str]:
    """Every mapping key anywhere in a serialized structure, at any depth."""
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            keys |= _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _walk_keys(item)
    return keys


def _canonical():
    return build_canonical(
        "generic",
        {
            "type": "generic",
            "subtype": "generic",
            "language": "ru",
            "document_date": None,
            "fields": {"note": "текст"},
        },
    )


# --- acceptance 1: the artifact conforms and carries no value ---------------


async def test_artifact_top_level_is_exactly_the_schema_property_set(scan_result):
    payload = json.loads(build_pii_artifact(result=scan_result))

    assert set(payload) == set(PII_SCAN_RESULT_SCHEMA["properties"])
    assert set(PII_SCAN_RESULT_SCHEMA["required"]) <= set(payload)
    assert PII_SCAN_RESULT_SCHEMA["additionalProperties"] is False


async def test_artifact_carries_no_envelope_the_schema_does_not_declare(scan_result):
    """The load-bearing consequence of the no-provenance-envelope decision.

    ``build_classification_artifact`` adds ``processing`` and ``generated_at``.
    If a future contributor mirrors that habit here, the artifact stops being
    ``PII_SCAN_RESULT_SCHEMA``-conformant and the plan's structural validation
    claim becomes false — so the absence of an envelope is asserted, not left
    to the module docstring.
    """
    payload = json.loads(build_pii_artifact(result=scan_result))

    assert "processing" not in payload
    assert "generated_at" not in payload
    assert "findings" in payload, "the artifact's whole purpose is the full masked list"


async def test_artifact_findings_match_the_finding_schema(scan_result):
    payload = json.loads(build_pii_artifact(result=scan_result))

    assert payload["findings"], "the fixture yields findings; an empty list proves nothing"
    for item in payload["findings"]:
        assert set(item) == set(PII_FINDING_SCHEMA["properties"])
        assert item["category"] in {m.value for m in PIICategory}
        assert "masked_value" in item


async def test_artifact_enum_fields_are_real_members(scan_result):
    payload = json.loads(build_pii_artifact(result=scan_result))

    assert payload["decision"] in {m.value for m in PIIDecision}
    assert payload["stage"] == PIIScanStage.DOCUMENT.value
    assert payload["destination"] == PIIDestination.INTERNAL_LLM.value


async def test_artifact_revalidates_into_a_scan_result(scan_result):
    """Round-trip through the model, so a future field cannot be dropped silently."""
    payload = json.loads(build_pii_artifact(result=scan_result))

    assert PIIScanResult.model_validate(payload) == scan_result


async def test_artifact_has_no_value_or_fingerprint_key_at_any_depth(scan_result):
    """Acceptance claim 1's security half, over the bytes that reach S3."""
    payload = json.loads(build_pii_artifact(result=scan_result))

    assert _walk_keys(payload) & set(FORBIDDEN_PROPERTIES) == set()


async def test_artifact_reaches_no_token_of_the_source_document(scan_result):
    """Not a key check: the actual characters the gate must never re-emit.

    The key assertions above are true by construction, so they would survive a
    detector that wrote a patient's name into ``masked_value``. This one would
    not — it reads the artifact the way an operator would, and looks for the
    document's own text in it.
    """
    body = build_pii_artifact(result=scan_result)

    for token in ("Смирнова", "Ольга", "Ивановна", "smirnova", "1974-03-12", "000-11-22"):
        assert token not in body, f"{token!r} reached pii_result.json"


async def test_artifact_does_not_contain_a_fingerprint_prefix(scan_result):
    """The fingerprint is in-process only (plan §7 decision 11, risk R5/R8)."""
    body = build_pii_artifact(result=scan_result)

    assert "hmac-sha256:" not in body
    assert re.search(r'"value_fingerprint"\s*:', body) is None


async def test_artifact_is_pretty_and_unicode_preserving(scan_result):
    """Mirrors ``build_classification_artifact``'s encoding so the diff is legible.

    ``ensure_ascii=False`` matters for a Russian medical document: the escaped
    form is unreadable in an artifact whose whole purpose is human review after
    an incident.
    """
    body = build_pii_artifact(result=scan_result)

    assert body.startswith("{\n")
    assert "person_name" in body
    assert "\\u04" not in body
    assert json.loads(body)["findings_count"] == scan_result.findings_count


async def test_artifact_serializes_the_stable_decision_and_counts(scan_result):
    payload = json.loads(build_pii_artifact(result=scan_result))

    assert payload["findings_count"] == len(payload["findings"])
    assert sum(payload["category_counts"].values()) == len(payload["findings"])
    assert payload["detector_version"] == DETECTOR_VERSION
    assert payload["policy_version"] == PII_POLICY_VERSION


# --- the "pii" block --------------------------------------------------------


async def test_block_keys_are_exactly_the_declared_ones(scan_result):
    """Discharges M4 Phase 7's recorded gap: the key set is now *enforced*.

    The assertion is made against ``PII_META_REQUIRED_KEYS`` /
    ``PII_META_OPTIONAL_KEYS`` — the M4 contract — and not against a second copy
    of it written here, so the two can only agree by both being right.
    """
    block = build_pii_meta_block(result=scan_result)

    assert set(block) == set(PII_META_REQUIRED_KEYS) | set(PII_META_OPTIONAL_KEYS)
    assert len(block) == 11


async def test_block_validates_through_the_real_pii_meta(scan_result):
    """The transcription becomes enforcement: ``PIIMeta`` is ``extra="forbid"``."""
    block = build_pii_meta_block(result=scan_result)

    assert PIIMeta(**block).model_dump(mode="json") == block


async def test_pii_meta_field_set_is_the_contract_key_set(scan_result):
    """The other direction, so the two homes cannot drift apart silently."""
    block = build_pii_meta_block(result=scan_result)
    fields = set(PIIMeta.model_fields)

    assert fields == set(block)


async def test_block_is_plain_json_ready_data(scan_result):
    """The block also rides in ``DocumentAnalysisCompleted.data``, unvalidated.

    That second consumer is why the block is a ``dict`` and not a ``PIIMeta``:
    the event path has no model to check it against, so the projection has to
    emit something ``json.dumps`` accepts and this test is the only guard.
    """
    block = build_pii_meta_block(result=scan_result)

    assert type(block) is dict
    assert json.loads(json.dumps(block, ensure_ascii=False)) == block


async def test_block_carries_no_finding_detail(scan_result):
    """§4.7: full findings live only in the artifact."""
    block = build_pii_meta_block(result=scan_result)
    assert "findings" not in block
    assert "processed_at" not in block, "the artifact is the timestamped record"
    assert "masked_value" not in json.dumps(block)
    assert not [key for key in _walk_keys(block) if key in FORBIDDEN_PROPERTIES]


async def test_block_categories_are_derived_from_the_authoritative_tally(scan_result):
    block = build_pii_meta_block(result=scan_result)

    assert block["categories"] == sorted(block["category_counts"])
    assert set(block["categories"]) == set(block["category_counts"])
    assert len(block["categories"]) == len(set(block["categories"]))


async def test_block_is_deterministic_for_one_result(scan_result):
    """Two calls, two equal blocks — ``categories`` is sorted for exactly this."""
    assert build_pii_meta_block(result=scan_result) == build_pii_meta_block(result=scan_result)


async def test_block_versions_come_from_the_result_not_from_the_constants(scan_result):
    """A stored verdict names the scan that produced it (plan §4.8, risk R6).

    The constants happen to agree here, which is the end-to-end wiring claim.
    What the test protects is the *source*: stamping a re-serialized old result
    with today's constants would mislabel it, so a result carrying stale
    versions must keep them.
    """
    stale = scan_result.model_copy(update={"policy_version": "0.9.0"})
    block = build_pii_meta_block(result=stale)

    assert block["policy_version"] == "0.9.0"
    assert build_pii_meta_block(result=scan_result)["policy_version"] == PII_POLICY_VERSION


async def test_block_for_a_clean_document_is_empty_not_absent(scan_result):
    """A scan that found nothing still records that it happened."""
    clean = next(f for f in iter_pii_fixtures() if f.file.startswith("clean/"))
    document = MarkdownNormalizer().normalize(clean.path.read_text(encoding="utf-8"))
    result = await _gate().inspect(document, _processing_context())
    block = build_pii_meta_block(result=result)

    assert block["decision"] == PIIDecision.ALLOW.value
    assert block["findings_count"] == 0
    assert block["category_counts"] == {}
    assert block["categories"] == []


async def test_block_does_not_alias_the_result(scan_result):
    """Mutating the block must not reach back into the result it was cut from."""
    block = build_pii_meta_block(result=scan_result)
    block["category_counts"]["person_name"] = 999
    block["categories"].append("injected")

    assert scan_result.category_counts.get("person_name") != 999
    assert "injected" not in scan_result.category_counts


# --- acceptance 2: the block round-trips through the frontmatter -----------


def _frontmatter(pii: Any | None):
    return build_frontmatter_meta(
        document_id=uuid4(),
        canonical=_canonical(),
        source={"filename": "report.pdf"},
        page_count=1,
        model="test-model",
        prompt_version="1.0.0",
        tokens={"total": 0},
        validation={"status": "valid"},
        pii=pii,
    )


async def test_frontmatter_renders_the_block_and_round_trips(scan_result):
    import yaml

    block = build_pii_meta_block(result=scan_result)
    text = render_frontmatter(_frontmatter(block))

    assert "pii:" in text
    assert "person_name" in text
    assert DETECTOR_VERSION in text

    body = text.removeprefix("---\n").removesuffix("---")
    assert PIIMeta(**yaml.safe_load(body)["pii"]).model_dump(mode="json") == block


async def test_frontmatter_omits_the_block_when_the_gate_did_not_run(scan_result):
    """Pre-M5 documents keep the frontmatter they had.

    ``to_dict()`` is ``exclude_none=True``, so no ``pii: null`` reaches a
    consumer that would otherwise have to distinguish "not scanned" from
    "scanned, found nothing" by checking for null.
    """
    assert "pii" not in _frontmatter(None).to_dict()
    assert "pii" not in render_frontmatter(_frontmatter(None))


async def test_frontmatter_rejects_a_block_the_gate_would_never_produce(scan_result):
    """``extra="forbid"`` reaches the caller: drift fails loudly, not quietly.

    This is the reason the block is built here and *validated* by
    ``FrontmatterMeta`` rather than constructed as a ``PIIMeta``: a block that
    drifted from §4.7 becomes a processing failure the pipeline already handles,
    instead of a rendered verdict carrying a field no consumer reads.
    """
    from pydantic import ValidationError

    block = {**build_pii_meta_block(result=scan_result), "raw_value": "пациент"}
    with pytest.raises(ValidationError):
        _frontmatter(block)


async def test_frontmatter_keeps_classification_and_pii_as_siblings(scan_result):
    block = build_pii_meta_block(result=scan_result)
    dumped = _frontmatter(block).to_dict()

    assert "pii" in dumped
    assert "classification" not in dumped
    assert set(dumped) >= {"doc_id", "type", "document", "source", "processing", "pii"}


# --- storage wiring ---------------------------------------------------------


def test_pii_kind_is_reachable_from_the_worker_artifact_package():
    """``pipeline.py`` imports kinds from ``storage``; ``app.artifacts`` is the
    documented home. Both must carry the constant or the key gets built twice."""
    import app.artifacts
    from app.artifacts.models import MARKDOWN_KIND_PII as from_models
    from storage import MARKDOWN_KIND_PII as from_storage

    assert app.artifacts.MARKDOWN_KIND_PII == from_models == from_storage == "pii"
    assert "MARKDOWN_KIND_PII" in app.artifacts.__all__
    assert "MARKDOWN_KIND_PII" in app.artifacts.models.__all__


def test_the_two_all_lists_stay_alphabetical():
    """Ruff's ``I`` rule enforces import sorting; ``__all__`` order is convention.

    Phase 10 adds an entry to both lists, and a misplaced one is the kind of
    thing that is only noticed by the next contributor who greps for it.
    """
    import app.artifacts
    import app.artifacts.models
    import storage

    for module in (app.artifacts, app.artifacts.models, storage):
        assert module.__all__ == sorted(module.__all__), module.__name__


def test_the_artifact_kind_resolves_to_the_declared_filename():
    from storage import markdown_artifact_filename

    assert markdown_artifact_filename("pii") == PII_ARTIFACT_FILENAME
    assert PII_ARTIFACT_FILENAME == "pii_result.json"


# --- the boundary this module had to respect -------------------------------


def test_artifact_module_imports_no_canonical_model():
    """M5's third import guard, applied to the new module specifically.

    ``build_pii_meta_block`` returns a ``dict`` *because* of this. Reaching for
    ``PIIMeta`` here would be a small convenience that silently makes
    ``app/pii`` depend on ``packages.canonical`` — the exact inversion ORDER §8
    rules out, and the reason the block is validated by its consumer instead.
    """
    from tests.support.pii_imports import pii_source_files, runtime_imports

    artifact = next(p for p in pii_source_files() if p.name == "artifact.py")
    modules = {module for module, _ in runtime_imports(artifact)}

    assert not any(m.startswith("canonical") for m in modules)
    assert modules <= {"json", "typing", "app.pii.models"}


def test_artifact_module_is_covered_by_the_package_guards():
    """The guards glob ``app/pii/*.py``, so a new file inherits them for free.

    Asserted explicitly because "inherited for free" is exactly the kind of
    assumption that breaks when someone switches the guard to an explicit list.
    """
    from tests.support.pii_imports import (
        imports_forbidden_domains,
        imports_forbidden_infrastructure,
        pii_source_files,
    )

    artifact = next(p for p in pii_source_files() if p.name == "artifact.py")
    assert imports_forbidden_domains(artifact) == set()
    assert imports_forbidden_infrastructure(artifact) == set()


def test_both_builders_are_exported_from_the_package():
    import app.pii

    assert "build_pii_artifact" in app.pii.__all__
    assert "build_pii_meta_block" in app.pii.__all__


# --- the Phase 1 invariant, one level out -----------------------------------


def test_a_constructed_finding_cannot_become_a_summary_carrying_its_value():
    """Phase 1's exclusion, re-asserted through this phase's projection.

    The artifact is safe because its *input* is safe. If that ever stops being
    true — a field added to ``PIIFindingSummary`` without thought — this is the
    test that notices. The narrowing is done with the gate's own field
    intersection rather than a hand-written dict, so a new summary field breaks
    this test loudly instead of being quietly dropped by the fixture.
    """
    from app.pii import PIIFinding, PIIFindingSummary

    finding = PIIFinding(
        category=PIICategory.PERSON_NAME,
        value="Смирнова Ольга Ивановна",
        masked_value="С***** О***** И*********",
        value_fingerprint="hmac-sha256:" + "b" * 64,
        confidence=0.9,
        source="pattern",
        detector="pattern.person_name",
        detector_version=DETECTOR_VERSION,
    )
    # Exactly what ``PIIFinding.value`` being Field(exclude=True) achieves:
    # a dump with no value to forward, and no fingerprint either.
    forwarded = {
        key: value
        for key, value in finding.model_dump().items()
        if key in PIIFindingSummary.model_fields
    }
    assert set(forwarded) == {
        "category",
        "masked_value",
        "confidence",
        "source",
        "detector",
        "start",
        "end",
    }

    summary = PIIFindingSummary(**forwarded)
    assert "value" not in summary.model_dump(mode="json")
    assert "Смирнова" not in json.dumps(summary.model_dump(mode="json"), ensure_ascii=False)


def test_the_module_docstring_states_the_one_result_decision():
    """Prose the code cannot enforce, so it is pinned like the other version rules."""
    from app.pii import artifact

    doc = artifact.__doc__ or ""
    assert "one result" in doc.lower()
    assert "phase 14" in doc.lower()
