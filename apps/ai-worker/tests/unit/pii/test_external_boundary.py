"""Tests for the untrusted-LLM boundary — ``llm_mode=external_llm`` (M5 Phase 15).

M5 ran to Phase 14 with the destination as a module constant, so everything
downstream of it was correct and unreachable: the redactor existed, was tested,
and was never called, because ``REDACT_ON_EXTERNAL`` only fires for
``EXTERNAL_LLM`` and nothing could select it. These tests are the first ones
that exercise that path, and they are grouped by the claim they defend:

1. **The destination is configuration, and a lying configuration is refused at
   start-up.** ``internal_llm`` + an unlisted ``ai_base_url`` is the pairing
   that sends documents unredacted to a boundary the operator believes is
   trusted, and it must never reach a document.
2. **The gate can now act on its own verdict.** It returns the projection
   *and* the values, and the values cannot be serialized out of that object.
3. **Redaction is per category.** A doctor's name and a clinic survive a
   patient's name being masked; the extraction needs them (R3).
4. **Presence still never blocks.** A medical record is expected to name a
   patient. Moving the boundary changes what is *removed*, never what is
   allowed through — with one exception, ``SECRET``, which is a security event
   rather than patient data.
5. **The canonical guard is not switched off by any of this.** It keeps its
   own constants and keeps running; it simply never sees the original text on
   this path, because the LLM never saw it either.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.classification.normalize import MarkdownNormalizer
from app.config.settings import Settings
from app.pii import (
    CANONICAL_POLICY_DESTINATION,
    CANONICAL_POLICY_STAGE,
    DETECTOR_VERSION,
    PII_POLICY_VERSION,
    DocumentPIIGateResult,
    InvalidPIIInputError,
    PIICategory,
    PIIDecision,
    PIIDestination,
    PIIScanStage,
    build_canonical_guard,
    build_document_gate,
)
from app.pii.policy import (
    CLINICAL_FACTS,
    REDACT_ON_EXTERNAL,
    TRUSTED_INTERNAL_URLS,
    resolve_destination,
)
from storage import MARKDOWN_KIND_REDACTED, markdown_artifact_filename

SECRET = "phase-15-external-boundary-secret-0123456789"
CONSULTATION = Path("tests/fixtures/pii/patient/synthetic-consultation-01.md")


class _Context:
    """The ids the policy-context builder wants; nothing else is read."""

    processing_id = uuid4()
    document_id = uuid4()
    document_version_id = uuid4()
    patient_id = uuid4()
    client_type = ""


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, pii_fingerprint_secret=SECRET, **overrides)


def _document(markdown: str):
    """A real normalized document — the gate's input, not a stand-in.

    ``raw_text`` is case-folded by the production normalizer, which is what the
    pattern rules actually face, so a name rule that cannot read folded text
    fails here rather than passing on capitalised prose.
    """
    return MarkdownNormalizer().normalize(markdown, metadata={})


# --- 1. the destination is configuration, and it is checked -------------------


def test_the_default_is_the_trusted_boundary():
    assert resolve_destination(_settings()) is PIIDestination.INTERNAL_LLM


def test_external_mode_selects_the_untrusted_boundary():
    settings = _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    assert resolve_destination(settings) is PIIDestination.EXTERNAL_LLM


def test_external_mode_never_inspects_the_url():
    """``external_llm`` is a claim of *distrust*, so there is nothing to check.

    The opposite pairing from the one that raises: an unrecognised provider
    under ``internal_llm`` is a misconfiguration, and the same unrecognised
    provider under ``external_llm`` is the entire point of the setting.
    """
    settings = _settings(llm_mode="external_llm", ai_base_url="https://unknown.example/v1")
    assert resolve_destination(settings) is PIIDestination.EXTERNAL_LLM


def test_internal_mode_with_an_untrusted_url_refuses_to_start():
    """The Phase 15 decision 3 control, and the reason it is not a comment.

    The pipeline believes the operator: ``INTERNAL_LLM`` issues ``ALLOW`` for
    every category but a credential, so this pairing would send every document
    unmasked to a host the configuration does not name, and the gate would
    report the result as clean.
    """
    settings = _settings(ai_base_url="https://elsewhere.example/v1")

    with pytest.raises(InvalidPIIInputError) as excinfo:
        resolve_destination(settings)

    message = str(excinfo.value)
    assert "https://elsewhere.example/v1" in message
    assert "internal_llm" in message
    assert "external_llm" in message


def test_the_refusal_names_the_trusted_list_so_the_fix_is_readable():
    settings = _settings(ai_base_url="https://elsewhere.example/v1")

    with pytest.raises(InvalidPIIInputError) as excinfo:
        resolve_destination(settings)

    for trusted in TRUSTED_INTERNAL_URLS:
        assert trusted in str(excinfo.value)


def test_one_trailing_slash_is_not_a_reason_to_refuse():
    """Cosmetic tolerance, without weakening the comparison.

    A provider configured with a trailing slash is the same provider, and an
    operator who hits a failure over a slash learns to disable the check. The
    slash is stripped on *both* sides, so it still cannot turn an untrusted host
    into a trusted one.
    """
    trusted = next(iter(TRUSTED_INTERNAL_URLS))
    assert resolve_destination(_settings(ai_base_url=f"{trusted}/")) is PIIDestination.INTERNAL_LLM


def test_a_trailing_slash_does_not_launder_an_untrusted_host():
    untrusted = "https://evil.example/v1"
    with pytest.raises(InvalidPIIInputError):
        resolve_destination(_settings(ai_base_url=f"{untrusted}/"))


def test_a_host_that_merely_looks_internal_is_not_trusted():
    """The check is name equality, not "looks private".

    A heuristic that accepts anything internal-looking passes for an
    exfiltration endpoint aimed at cloud metadata — which is the exact thing the
    check exists to stop, and a reason to keep the list explicit.
    """
    for url in (
        "http://169.254.169.254/latest/meta-data",
        "http://localhost:8000/v1",
        "https://10.0.0.5/v1",
        "https://foundation-models.api.cloud.ru.evil.example/v1",
    ):
        with pytest.raises(InvalidPIIInputError):
            resolve_destination(_settings(ai_base_url=url))


def test_the_production_base_url_is_the_one_named_as_trusted():
    """If this breaks, the default configuration fails to start the worker."""
    assert resolve_destination(_settings()) is PIIDestination.INTERNAL_LLM
    assert _settings().ai_base_url in {url.rstrip("/") for url in TRUSTED_INTERNAL_URLS}


def test_the_settable_modes_map_onto_real_destinations():
    """A setting value that names nothing would be a silent no-op.

    ``PIIDestination`` has four members and only two of them are states a
    deployment may be in: ``PERSISTENCE`` is the canonical guard's own constant
    and ``UNKNOWN`` is the fail-closed placeholder, so neither belongs on
    ``llm_mode``.
    """
    settable = {
        "internal_llm": PIIDestination.INTERNAL_LLM,
        "external_llm": PIIDestination.EXTERNAL_LLM,
    }
    for mode, destination in settable.items():
        assert resolve_destination(_settings(llm_mode=mode)) is destination
        assert destination is not PIIDestination.PERSISTENCE
        assert destination is not PIIDestination.UNKNOWN


def test_an_unknown_mode_is_a_construction_error_not_a_destination():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _settings(llm_mode="external")


def test_the_worker_refuses_to_start_on_the_lying_pairing():
    """The refusal belongs to the worker, not to a helper nobody calls."""
    with pytest.raises(InvalidPIIInputError):
        build_document_gate(_settings(ai_base_url="https://elsewhere.example/v1"))


def test_the_gate_honours_the_setting_for_both_modes():
    external = build_document_gate(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )
    internal = build_document_gate(_settings())

    def destination_of(gate) -> PIIDestination:
        return gate.policy_context_builder(_document("текст"), _Context()).destination

    assert destination_of(external) is PIIDestination.EXTERNAL_LLM
    assert destination_of(internal) is PIIDestination.INTERNAL_LLM


# --- 2. the gate can act on its own verdict ----------------------------------


@pytest.mark.asyncio
async def test_the_result_carries_the_values_the_projection_dropped():
    """Why this method exists at all: the summary model has no ``value``.

    Phase 1's structural rule means ``PIIScanResult.findings`` are summaries —
    there is nothing in the returned verdict a redactor could consume, which is
    why redaction was specified, tested, and unreachable for thirteen phases.
    """
    gate = build_document_gate(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )

    result = await gate.evaluate_document(_document("СНИЛС 123-067-082 21"), _Context())

    assert isinstance(result, DocumentPIIGateResult)
    assert [f.value for f in result.findings] == ["123-067-082 21"]
    assert not hasattr(result.scan_result.findings[0], "value")


def _keys_at_every_depth(node, path: tuple[str, ...] = ()) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(".".join((*path, str(key))))
            keys |= _keys_at_every_depth(value, (*path, str(key)))
    elif isinstance(node, list):
        for item in node:
            keys |= _keys_at_every_depth(item, path)
    return keys


@pytest.mark.asyncio
async def test_no_value_or_fingerprint_can_be_serialized_out_of_the_result():
    """The safety argument is ``exclude=True``, so it is asserted, not assumed.

    This is the same walk the suite already applies to ``PIIScanResult``. If the
    two value-bearing fields ever lose their ``exclude``, the first thing to
    break is this test rather than an artifact.
    """
    gate = build_document_gate(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )

    result = await gate.evaluate_document(
        _document("Пациент Смирнова Ольга Ивановна, СНИЛС 123-067-082 21"), _Context()
    )
    dumped = result.model_dump(mode="json")

    keys = _keys_at_every_depth(dumped)
    # `masked_value` is not `value`: it is the deliberate partial disclosure the
    # finding carries for a human, and it is inside the projection, not beside
    # it. Everything else that looks like a value is the leak this asserts away.
    assert not [key for key in keys if key.endswith(".value")], keys
    assert not [key for key in keys if key.endswith("value_fingerprint")], keys
    assert "123-067-082 21" not in json.dumps(dumped, ensure_ascii=False)


@pytest.mark.asyncio
async def test_inspect_is_the_projection_of_evaluate_document():
    """One implementation, so a verdict obtained by either path agrees.

    ORDER §8's signature is unchanged and still returns a value-free
    ``PIIScanResult``; ``evaluate_document`` is what it is a projection of.
    """
    settings = _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    gate = build_document_gate(settings)
    markdown = "СНИЛС 123-067-082 21"

    inspected = await gate.inspect(_document(markdown), _Context())
    evaluated = await gate.evaluate_document(_document(markdown), _Context())

    # Two evaluations, so `processed_at` legitimately differs; everything the
    # decision is made of must not.
    assert inspected.model_dump(mode="json", exclude={"processed_at"}) == (
        evaluated.scan_result.model_dump(mode="json", exclude={"processed_at"})
    )


@pytest.mark.asyncio
async def test_a_result_with_nothing_to_redact_comes_back_by_identity():
    """Identity, not equality: the pipeline uses it to skip the artifact."""
    gate = build_document_gate(_settings())
    markdown = "Пациент Смирнова Ольга Ивановна"

    result = await gate.evaluate_document(_document(markdown), _Context())

    assert gate.redact(markdown, result) is markdown


# --- 3. redaction is per category --------------------------------------------


@pytest.mark.asyncio
async def test_the_external_boundary_removes_identifiers_and_keeps_the_note_legible():
    """The phase's accept case, over the fixture the manifest declares."""
    gate = build_document_gate(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )
    markdown = CONSULTATION.read_text(encoding="utf-8")

    result = await gate.evaluate_document(_document(markdown), _Context())
    redacted = gate.redact(markdown, result)

    assert redacted is not markdown
    for finding in result.findings:
        assert result.actions[finding.category] is not None
        if result.actions[finding.category].value == "redact":
            assert finding.value not in redacted
    assert result.scan_result.decision is PIIDecision.ALLOW_WITH_WARNING


@pytest.mark.asyncio
async def test_a_doctor_and_a_clinic_survive_a_patient_name_being_masked():
    """R3, and the reason §4.12 is per category rather than all-or-nothing.

    ``render_document`` and the appointment model need the practitioner: a note
    with ``[DOCTOR_NAME]`` where the doctor was is not a redacted note, it is a
    broken one.
    """
    gate = build_document_gate(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )
    markdown = (
        "Пациент: Смирнова Ольга Ивановна\nВрач: Петров И. С.\nКлиника: ООО «Медцентр на Пресне»\n"
    )

    result = await gate.evaluate_document(_document(markdown), _Context())
    redacted = gate.redact(markdown, result)

    assert "Смирнова Ольга Ивановна" not in redacted
    assert "Петров И. С." in redacted
    assert "ООО «Медцентр на Пресне»" in redacted
    assert result.actions[PIICategory.PERSON_NAME].value == "redact"
    assert result.actions[PIICategory.DOCTOR_NAME].value == "allow"


@pytest.mark.asyncio
async def test_the_trusted_boundary_removes_nothing():
    """The default must stay a no-op, or every document grows an artifact."""
    gate = build_document_gate(_settings())
    markdown = "Пациент: Смирнова Ольга Ивановна\nВрач: Петров И. С.\n"

    result = await gate.evaluate_document(_document(markdown), _Context())
    redacted = gate.redact(markdown, result)

    assert redacted is markdown
    assert "Смирнова Ольга Ивановна" in redacted
    assert result.scan_result.decision is PIIDecision.ALLOW


@pytest.mark.asyncio
async def test_the_external_boundary_masks_the_age_and_the_persistence_one_does_not():
    """A named cost of the shipped table, pinned rather than discovered later.

    ``AGE``/``GENDER``/``NATIONALITY`` are in ``REDACT_ON_EXTERNAL`` — they are
    demographics, and demographics identify — so an external provider sees
    ``(Ж, [AGE])`` where the internal one saw ``(Ж, 39 лет)``. Phase 14 derived
    ``REDACT_ON_PERSIST`` as ``REDACT_ON_EXTERNAL - CLINICAL_FACTS`` precisely so
    the *note* would keep them; that carve-out belongs to the guard, and the
    text sent across the boundary is not a note anybody reads.

    Asserted as it is, because the alternative is a reader assuming the
    ``(М, 39 лет)`` survival the persistence contour guarantees also holds here.
    Whether masking an age is the right trade on an external boundary is M6
    calibration with real findings, and this test is where that argument will
    start.
    """
    external = build_document_gate(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )
    markdown = "Пациент: Смирнова Ольга Ивановна (Ж, 39 лет), СНИЛС 123-067-082 21"

    result = await external.evaluate_document(_document(markdown), _Context())
    redacted = external.redact(markdown, result)

    assert result.actions[PIICategory.AGE].value == "redact"
    assert "39 лет" not in redacted
    assert "Смирнова Ольга Ивановна" not in redacted
    assert CLINICAL_FACTS <= REDACT_ON_EXTERNAL

    guard = build_canonical_guard(_settings())
    guard_result = guard.evaluate_payload({"fields": {"note": "пациент, (М, 39 лет)"}})
    assert guard_result.actions[PIICategory.AGE].value == "allow"


# --- 4. presence still never blocks ------------------------------------------


@pytest.mark.asyncio
async def test_a_medical_record_is_not_a_security_event():
    """A patient identifier on the untrusted boundary is redacted, not halted.

    This is the invariant Phase 15 could most easily have broken by making the
    untrusted destination stricter: a platform that refuses to send a medical
    record anywhere has not solved PII, it has stopped working.
    """
    gate = build_document_gate(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )

    result = await gate.evaluate_document(
        _document("Пациент: Смирнова Ольга Ивановна, СНИЛС 123-067-082 21"), _Context()
    )

    assert result.findings
    assert result.scan_result.decision is PIIDecision.ALLOW_WITH_WARNING


@pytest.mark.asyncio
async def test_a_credential_still_blocks_at_the_external_boundary():
    """``SECRET`` is excluded from the redaction set on purpose.

    A leaked key is not made safer by replacing it with ``[SECRET]`` — it is a
    security event that must not travel at all, and masking it would convert a
    block into a quiet success.
    """
    gate = build_document_gate(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )

    result = await gate.evaluate_document(
        _document("api_key = sk-live-4eC39HqLyjWDarjtT1zdp7dcABCDEF"), _Context()
    )

    assert result.scan_result.decision is PIIDecision.BLOCK
    assert PIICategory.SECRET not in REDACT_ON_EXTERNAL


@pytest.mark.asyncio
async def test_a_blocked_document_has_nothing_to_redact_into():
    """Halting comes first: a refused document is not sent in masked form."""
    from app.pii import HALTING_DECISIONS

    gate = build_document_gate(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )

    result = await gate.evaluate_document(
        _document("api_key = sk-live-4eC39HqLyjWDarjtT1zdp7dcABCDEF, СНИЛС 123-067-082 21"),
        _Context(),
    )

    assert result.scan_result.decision in HALTING_DECISIONS
    assert result.actions[PIICategory.SECRET] is not None


# --- 5. the guard is unaffected, and never saw the original ------------------


def test_the_canonical_guard_ignores_the_setting_entirely():
    """Its ``(canonical, persistence)`` constants are not configurable.

    The guard's job is the output of the extraction, and the extraction runs at
    a destination that no longer matters to it: whatever the LLM was sent, what
    comes back is what gets checked. Wiring ``llm_mode`` in here would be a
    second, independent way for the guard to be switched off.
    """
    external = build_canonical_guard(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )
    internal = build_canonical_guard(_settings())

    for guard in (external, internal):
        context = guard.policy_context_builder()
        assert context.stage is CANONICAL_POLICY_STAGE
        assert context.destination is CANONICAL_POLICY_DESTINATION
    assert CANONICAL_POLICY_DESTINATION is PIIDestination.PERSISTENCE


def test_the_canonical_guard_is_not_silently_a_no_op_on_the_external_path():
    """Switching providers must not disarm the *other* contour.

    A redaction-only pipeline would leave the Phase 14 leak — the model copying
    a patient name into free prose — untouched, because that leak is created
    after the text the model was given.
    """
    guard = build_canonical_guard(
        _settings(llm_mode="external_llm", ai_base_url="https://provider.example/v1")
    )
    payload = {"fields": {"note": "для пациента Смирнова Ольга Ивановна"}}

    result = guard.evaluate_payload(payload)
    sanitized = guard.sanitize(payload, result)

    assert "Смирнова Ольга Ивановна" not in json.dumps(sanitized, ensure_ascii=False)
    assert result.decision is PIIDecision.ALLOW_WITH_WARNING


# --- the artifacts and versions this phase adds ------------------------------


def test_the_redacted_artifact_is_its_own_storage_kind():
    assert MARKDOWN_KIND_REDACTED == "redacted"
    assert markdown_artifact_filename(MARKDOWN_KIND_REDACTED) == "redacted.md"


def test_the_redacted_artifact_is_not_a_second_name_for_marker():
    """Two kinds on one filename means the second upload overwrites the first."""
    from storage.keys import MARKDOWN_ARTIFACTS

    filenames = list(MARKDOWN_ARTIFACTS.values())
    assert len(set(filenames)) == len(filenames)
    assert MARKDOWN_ARTIFACTS[MARKDOWN_KIND_REDACTED] != MARKDOWN_ARTIFACTS["unstructured"]


def test_the_versions_did_not_move():
    """Neither constant describes what this phase changed.

    The ``EXTERNAL_LLM`` override already existed in the table; Phase 15 changes
    which destination is *supplied*, not any decision rule, so §4.8's "any
    change that alters a decision" does not fire. A stored ``pii_result.json``
    records ``destination: external_llm``, which is what makes such a verdict
    interpretable without a bump.
    """
    assert DETECTOR_VERSION == "1.2.0"
    assert PII_POLICY_VERSION == "2.0.0"


def test_the_document_gate_wire_produces_a_document_stage_context():
    gate = build_document_gate(_settings())

    context = gate.policy_context_builder(_document("текст"), _Context())

    assert context.stage is PIIScanStage.DOCUMENT
    assert context.redaction_available is True
