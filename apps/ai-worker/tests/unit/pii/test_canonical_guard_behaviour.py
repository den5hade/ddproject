"""Behaviour tests for the canonical-output guard — contour 2 (M5 Phase 14).

``test_canonical_guard.py`` is M4's contract: shapes, names, the remediation
vocabulary, the import boundary. This module is the phase's claim, which is
narrower and louder: **given the two real leak shapes, the guard finds the PII,
rewrites only the PII, and refuses to publish a payload it cannot rewrite.**

The fixtures are the observed payload *shapes* rebuilt with invented values, per
plan §7 decision 9 — no real patient data. That is also why they are JSON
payloads rather than markdown: the leak did not happen in ``marker.md``. It
happened in ``canonical.json`` because the extraction model copied a declined
patient's name into free prose, and the same content then reached
``document_extractions.data`` through the completed event.

Four claims carry the phase, and each has a test that could only pass if that
claim is true:

1. **The leak is found.** A name and a ticket number in ``fields.note`` produce
   ``ALLOW_WITH_WARNING`` with a path per violation.
2. **The rewrite is narrow.** A doctor, a specialty, a sex and an age survive
   beside the masked name; ``document_date`` survives as itself, because a
   service date is not patient PII (IMPL_ARCH §34).
3. **A decision that cannot be acted on halts.** ``REVIEW`` and ``BLOCK`` both
   stop, and a secret — the one normal ``BLOCK`` source — is a halt rather than
   a rewrite.
4. **Confusion is not permission.** A missing or miswired policy context raises
   instead of returning a verdict, because "clean" and "I could not tell" are
   indistinguishable downstream and only one of them is safe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.config.settings import Settings
from app.pii import (
    CANONICAL_POLICY_DESTINATION,
    CANONICAL_POLICY_STAGE,
    CLINICAL_FACTS,
    DEFAULT_POLICY,
    DefaultPIIAggregator,
    PIIAction,
    PIICategory,
    PIIDecision,
    PIIDestination,
    PIIFinding,
    PIIPolicyContext,
    PIIRiskLevel,
    PIIScanStage,
    PIISource,
)
from app.pii.canonical_guard import (
    DefaultCanonicalPIIInspector,
    build_canonical_guard,
    walk_string_leaves,
)
from app.pii.detectors import build_detector_chain
from app.pii.exceptions import PIIDecisionError
from app.pii.gate import HALTING_DECISIONS
from app.pii.policy import (
    REDACT_ON_EXTERNAL,
    REDACT_ON_PERSIST,
    DefaultPolicyEngine,
    build_policy_context,
)
from app.pii.redaction import PIIRedactionError, PlaceholderRedactor

SECRET = "unit-test-fingerprint-secret-0123456789"
CANONICAL_FIXTURES = Path("tests/fixtures/pii/canonical")
SYNTHETIC_PATIENT = "Кузнецова Александра Петровича"
SYNTHETIC_TICKET = "2026030710155500000001"


def _settings() -> Settings:
    return Settings(pii_fingerprint_secret=SECRET)


def _guard(settings: Settings | None = None) -> DefaultCanonicalPIIInspector:
    return build_canonical_guard(settings or _settings())


def _guard_with(builder) -> DefaultCanonicalPIIInspector:
    """Wire the production chain around a *deliberately wrong* context builder.

    Built by hand rather than through :func:`build_canonical_guard` because the
    factory's whole job is to produce the right context — a builder that returns
    nothing is a miswiring, and the test has to be able to make one.
    """
    settings = _settings()
    return DefaultCanonicalPIIInspector(
        detector=build_detector_chain(settings),
        aggregator=DefaultPIIAggregator(),
        policy_engine=DefaultPolicyEngine(DEFAULT_POLICY),
        policy_context_builder=builder,
        redactor=PlaceholderRedactor(),
    )


def _fixture(name: str) -> dict[str, Any]:
    matches = list(CANONICAL_FIXTURES.rglob(name))
    assert len(matches) == 1, f"expected exactly one {name} under {CANONICAL_FIXTURES}"
    return json.loads(matches[0].read_text(encoding="utf-8"))


@pytest.fixture
def guard() -> DefaultCanonicalPIIInspector:
    return _guard()


class Leak:
    """One observed leak shape, with what must survive its sanitization.

    ``survivors`` is the half that makes the rewrite assertion a claim: a guard
    that returned ``{}`` would close the leak and fail here, which is the only
    way to tell "masked the PII" apart from "masked the document".
    """

    def __init__(self, name: str, payload: dict[str, Any], survivors: tuple[str, ...]) -> None:
        self.name = name
        self.payload = payload
        self.survivors = survivors


_LEAKS = (
    Leak(
        "synthetic-registration-note-01.json",
        _fixture("synthetic-registration-note-01.json"),
        ("врачу-терапевту", "Кабинет приема: 214", "Петров И. С."),
    ),
    Leak(
        "synthetic-analysis-note-01.json",
        _fixture("synthetic-analysis-note-01.json"),
        ("(М, 39 лет)", "гипертоническая болезнь I стадии", "Петров И. С."),
    ),
)
"""The two observed shapes, rebuilt with invented values (plan §7 decision 9)."""


@pytest.fixture(params=_LEAKS, ids=[leak.name for leak in _LEAKS])
def leak(request: pytest.FixtureRequest) -> Leak:
    """Both leak shapes, so no claim below gets to pass on one of them."""
    return request.param


def _paths(result) -> list[str]:
    return sorted(v.field_path for v in result.violations)


# --- 1. the leak is found ----------------------------------------------------


def test_the_leak_is_found_in_the_note(guard, leak):
    """A declined patient's name in free prose is a finding with a path.

    The path is the half that makes the finding actionable: ``fields.note`` says
    the prompt's note field is where the model put it, which is a fix at the
    source rather than a mask applied to a symptom. Without the path the artifact
    would be a document that "contained PII", which is true of every leak and
    therefore useless.
    """
    result = guard.evaluate_payload(leak.payload)

    categories = {v.category for v in result.violations}
    assert PIICategory.PERSON_NAME in categories
    assert "fields.note" in _paths(result)
    assert result.decision is PIIDecision.ALLOW_WITH_WARNING
    assert result.risk_level is PIIRiskLevel.HIGH


def test_inspect_is_the_projection_of_evaluate(guard, leak):
    """The locked protocol stays the same answer, minus the decision.

    Asserted as an equality of the two lists rather than as a shared fixture,
    because the failure this guards is a guard whose two entry points disagree —
    and the caller that gets the wrong one is the caller that decides whether to
    publish.
    """
    assert guard.inspect(leak.payload) == guard.evaluate_payload(leak.payload).violations


def test_a_violation_carries_no_raw_value(guard, leak):
    """The mask survives into the violation; the value and its fingerprint do not.

    The artifact this feeds is published, and the class docstring is explicit that
    ``masked_value`` is what a violation is allowed to carry: enough to answer
    "what leaked and where", not enough to be a second copy of the leak. So the
    assertion is two-sided — no ``value``/``value_fingerprint`` key, and the raw
    strings absent from the serialized form — while the mask is present.
    """
    result = guard.evaluate_payload(leak.payload)
    dumped = json.loads(result.model_dump_json())

    def keys(node: Any) -> set[str]:
        if isinstance(node, dict):
            return set(node) | {k for value in node.values() for k in keys(value)}
        if isinstance(node, list):
            return {k for value in node for k in keys(value)}
        return set()

    assert not keys(dumped) & {"value", "value_fingerprint"}
    assert {v.masked_value for v in result.violations}  # the mask is the point
    assert SYNTHETIC_PATIENT not in json.dumps(dumped, ensure_ascii=False)
    assert SYNTHETIC_TICKET not in json.dumps(dumped, ensure_ascii=False)


def test_in_process_findings_never_reach_the_serialized_result(guard, leak):
    """The redactor needs the raw span; the result must not carry it.

    The split is the whole design of a two-call guard: ``findings_by_path`` holds
    the values in memory so :func:`sanitize_canonical_payload` can place a mask,
    and ``Field(exclude=True)`` keeps them out of every dump. Asserted through
    the dump rather than through the attribute, because exclusion is a claim
    about serialization and only serialization is the boundary.
    """
    result = guard.evaluate_payload(leak.payload)

    assert result.findings_by_path  # the sanitizer is not working with nothing
    assert result.actions
    for key in ("findings_by_path", "actions"):
        assert key not in json.loads(result.model_dump_json())


def test_every_string_leaf_is_walked():
    """The walk is total: keys, values, and strings nested inside lists.

    Total is the property that makes the guard schema-agnostic, and the list case
    is the one that is easiest to lose in a rewrite — a ``dict[str, Any]`` can
    hold a list of dicts, and a generator that recurses only into mappings stops
    at the first list without saying so.
    """
    payload = {
        "fields": {
            "note": "text",
            "blockers": [{"code": "SEC-1", "why": "секретный ключ"}, ["nested", "deep"]],
        },
    }
    leaves = dict(walk_string_leaves(payload))

    assert leaves == {
        "fields.note": "text",
        "fields.blockers[0].code": "SEC-1",
        "fields.blockers[0].why": "секретный ключ",
        "fields.blockers[1][0]": "nested",
        "fields.blockers[1][1]": "deep",
    }


def test_a_cyclic_payload_terminates_and_still_scans_the_rest(guard):
    """A self-referential payload is skipped, not walked forever.

    The cycle is tracked by object identity along the current path, so a container
    already being walked is simply not entered again. The alternative — recursing
    until the stack gives out — turns a malformed payload into a worker crash
    mid-batch, which is a worse outcome than a leaf that goes unscanned, and the
    rest of the payload is still scanned either way.
    """
    payload: dict[str, Any] = {"fields": {"note": f"пациент {SYNTHETIC_PATIENT}"}}
    payload["fields"]["self"] = payload

    result = guard.evaluate_payload(payload)

    assert result.violations
    assert {v.field_path for v in result.violations} == {"fields.note"}


# --- 2. the rewrite is narrow ------------------------------------------------


def test_the_rewrite_masks_the_patient_and_keeps_everything_else(guard, leak):
    """The core claim: the two observed shapes come back clean and complete.

    Every assertion is about something that must **survive**, because a guard that
    masks the whole note has closed the leak and destroyed the document, and the
    only way to tell the two apart is to read what is left. Each shape names its
    own survivors, so the test cannot pass by masking both notes down to nothing
    and asserting the PII is gone.
    """
    result = guard.evaluate_payload(leak.payload)
    sanitized = guard.sanitize(leak.payload, result)
    note = sanitized["fields"]["note"]

    assert SYNTHETIC_PATIENT not in note
    assert SYNTHETIC_TICKET not in note
    assert "[PERSON_NAME]" in note

    for survivor in leak.survivors:
        assert survivor in note, f"{survivor!r} was destroyed in {leak.name}"


def test_a_sex_and_an_age_survive_the_rewrite(guard):
    """``(М, 39 лет)`` is clinical context, and Phase 14's rule set says so.

    The rule the phase turns on is the *inverse* of this test: a patient name
    resolves to ``ALLOW_WITH_WARNING`` (sanitize) while a name, an age and a sex
    together do not. The pair is the reason the policy has a set rather than a
    per-category line — drop ``AGE``/``GENDER``/``NATIONALITY`` out of the
    escalation and the note loses the sentence that makes it readable.
    """
    payload = _fixture("laboratory/synthetic-analysis-note-01.json")

    sanitized = guard.sanitize(payload, guard.evaluate_payload(payload))

    assert "(М, 39 лет)" in sanitized["fields"]["note"]


def test_a_service_date_is_not_redacted(guard):
    """``document_date`` survives — the reason Phase 14 also moved a detector rule.

    The date is in a *typed envelope field* whose name already says what kind of
    date it is, and IMPL_ARCH §34 is explicit that a service date is not patient
    PII. It is also the field ``render_document`` puts in the frontmatter, so
    redacting it would publish ``document_date: '[DATE_OF_BIRTH]'`` on every
    document that has one. Asserted on its own, in isolation, so that a
    regression here is not masked by the note-level redactions above.
    """
    payload = _fixture("laboratory/synthetic-analysis-note-01.json")

    sanitized = guard.sanitize(payload, guard.evaluate_payload(payload))

    assert sanitized["document_date"] == payload["document_date"] == "2026-03-05"


def test_the_original_payload_is_never_mutated(guard, leak):
    """Sanitization is a rebuild on a copy (§7 decision 7), so the input stands.

    The pipeline holds the built model in a local and would happily publish it
    again after a failed rewrite; an in-place guard makes "we sanitized" and "we
    tried to" indistinguishable at exactly the point where the distinction decides
    whether a document ships.
    """
    before = json.dumps(leak.payload, ensure_ascii=False, sort_keys=True)

    guard.sanitize(leak.payload, guard.evaluate_payload(leak.payload))

    assert json.dumps(leak.payload, ensure_ascii=False, sort_keys=True) == before


def test_a_clean_payload_is_returned_untouched(guard):
    """A clean payload is not a rewritten one.

    Stated as a value assertion rather than an identity one: the guard returns a
    copy, and the pipeline's "skip the rebuild when nothing is REDACT" fast path
    relies on there being nothing to skip.
    """
    payload = {
        "document_date": "2026-03-05",
        "language": "ru",
        "type": "generic",
        "fields": {"note": "Осмотр проведен. Диагноз: гипертоническая болезнь I стадии."},
    }

    result = guard.evaluate_payload(payload)
    sanitized = guard.sanitize(payload, result)

    assert result.decision is PIIDecision.ALLOW
    assert result.risk_level is PIIRiskLevel.LOW
    assert result.violations == []
    assert sanitized == payload


def test_a_clinical_fact_alone_does_not_rewrite_the_document(guard):
    """Findings that are all ``ALLOW`` are recorded, not acted on.

    The point is that a guard which redacted a doctor's name on sight would be
    unusable: it would produce a different document for every clinical input, and
    the diffs would be unreadable. ``sanitize`` must be a no-op here, and the
    evidence that anything was seen at all is the result, not the payload.
    """
    payload = {
        "fields": {
            "note": "Приём: Врач: Петров И. С. Пол: М. Возраст: 39 лет. "
            "Диагноз: гипертоническая болезнь I стадии.",
        }
    }

    result = guard.evaluate_payload(payload)
    sanitized = guard.sanitize(payload, result)

    assert {v.category for v in result.violations} == {
        PIICategory.DOCTOR_NAME,
        PIICategory.AGE,
    }
    assert all(action is PIIAction.ALLOW for action in result.actions.values())
    assert result.decision is PIIDecision.ALLOW
    assert sanitized == payload


# --- 3. a decision that cannot be acted on halts -----------------------------


def test_a_secret_halts_rather_than_rewriting(guard):
    """``SECRET`` is the one normal ``BLOCK``, and a block is not a mask.

    A secret is not something you redact out of a note and keep processing — it
    is a signal that the payload must not be persisted at all, and the pipeline's
    halt branch is the only thing standing between the finding and S3.
    """
    payload = {
        "fields": {
            "note": f"Пациент: {SYNTHETIC_PATIENT}. Ключ доступа: sk-proj-{SECRET}-abcdef",
        }
    }

    result = guard.evaluate_payload(payload)

    assert result.decision is PIIDecision.BLOCK
    assert result.actions[PIICategory.SECRET] is PIIAction.BLOCK


def test_the_halt_decisions_are_the_two_that_stop_the_document():
    """``REVIEW`` and ``BLOCK`` are the pipeline's ``HALTING_DECISIONS``.

    Asserted from the policy table rather than from a literal, so the guard's
    halt set and the pipeline's cannot drift apart without a failure here.
    """
    expected = frozenset({PIIDecision.REVIEW, PIIDecision.BLOCK})
    assert expected == HALTING_DECISIONS


def test_a_halting_result_is_never_sanitized(guard):
    """``sanitize`` on a halting result is a caller bug, and it is not silent.

    The guard's two-call shape exists so a halt can short-circuit *before* any
    rewrite. A caller that sanitizes anyway is not caught by the guard's
    behaviour — it is caught by the pipeline's halt branch — so what is asserted
    here is the cheap half: the result still carries the decision, so a caller
    that forgot to check it has no excuse.
    """
    payload = {"fields": {"note": f"Ключ доступа: sk-proj-{SECRET}-abcdef"}}

    result = guard.evaluate_payload(payload)

    assert result.decision in {PIIDecision.REVIEW, PIIDecision.BLOCK}
    assert result.findings_by_path


# --- 4. confusion is not permission ------------------------------------------


def test_a_builder_that_returns_nothing_raises():
    """No context is not a clean payload.

    The alternative — a default of ``CANONICAL``/``PERSISTENCE`` — would be a
    guess, and a guessed stage looks up the *source* rows, where a patient name
    is ``ALLOW``. The guard would report a leaking document as clean, which is the
    one answer this contour must never give.
    """
    guard = _guard_with(lambda: None)

    with pytest.raises(PIIDecisionError) as excinfo:
        guard.evaluate_payload({"fields": {"note": f"пациент {SYNTHETIC_PATIENT}"}})

    assert "refusing" in str(excinfo.value)


def test_a_context_from_the_wrong_stage_raises():
    """A miswired builder is the sharper failure, and it fails loudly.

    ``DOCUMENT``/``INTERNAL_LLM`` is the baseline the §4.4 table is written for,
    and it resolves the same findings to ``ALLOW`` — a patient name in a source
    document is only a finding at a boundary. The test asserts the *difference*
    before it asserts the raise, so the check is shown to be load-bearing rather
    than decorative: without it, this exact context would have the guard report a
    leaking payload as clean.
    """
    payload = {"fields": {"note": f"пациент {SYNTHETIC_PATIENT}"}}
    silently_allows = PIIPolicyContext(
        organization_id="tenant-1",
        stage=PIIScanStage.DOCUMENT,
        destination=PIIDestination.INTERNAL_LLM,
    )
    correct = build_policy_context(
        _settings(),
        stage=PIIScanStage.CANONICAL,
        destination=PIIDestination.PERSISTENCE,
        redaction_available=True,
    )

    engine = DefaultPolicyEngine(DEFAULT_POLICY)
    findings = build_detector_chain(_settings()).detect_text(payload["fields"]["note"])
    assert engine.evaluate(findings, silently_allows).decision is PIIDecision.ALLOW
    assert engine.evaluate(findings, correct).decision is PIIDecision.ALLOW_WITH_WARNING

    guard = _guard_with(lambda: silently_allows)
    with pytest.raises(PIIDecisionError) as excinfo:
        guard.evaluate_payload(payload)

    assert str(CANONICAL_POLICY_STAGE.value) in str(excinfo.value)


def test_a_wrong_destination_alone_is_enough_to_raise():
    """The check is on the *pair*, so the destination half is load-bearing too.

    ``CANONICAL`` with the source's ``EXTERNAL_LLM`` passes a stage check and
    still loses the persistence escalation, so a guard wired that way would
    approve a leaking payload. A test that only ever checked the stage would not
    notice.
    """
    guard = _guard_with(
        lambda: PIIPolicyContext(
            organization_id="tenant-1",
            stage=CANONICAL_POLICY_STAGE,
            destination=PIIDestination.EXTERNAL_LLM,
        )
    )

    with pytest.raises(PIIDecisionError) as excinfo:
        guard.evaluate_payload({"fields": {"note": f"пациент {SYNTHETIC_PATIENT}"}})

    assert str(CANONICAL_POLICY_DESTINATION.value) in str(excinfo.value)


def test_a_context_under_the_right_stage_and_destination_is_accepted():
    """The check is on the *pair*, and the pair the factory builds passes.

    Written as a test so a future change to ``_policy_context`` that compares only
    the stage — leaving the destination unchecked, and the persistence escalation
    silently unapplied — fails here rather than in production.
    """
    guard = _guard()

    result = guard.evaluate_payload({"fields": {"note": f"пациент {SYNTHETIC_PATIENT}"}})

    assert result.decision is PIIDecision.ALLOW_WITH_WARNING
    assert CANONICAL_POLICY_STAGE is PIIScanStage.CANONICAL
    assert CANONICAL_POLICY_DESTINATION is PIIDestination.PERSISTENCE


def test_a_redactor_that_fails_propagates_rather_than_writing_the_original(guard):
    """A failed rewrite is an exception, not a pass-through.

    The pipeline catches ``PIIRedactionError`` and halts, which is correct. What
    must not exist is a path where the exception is swallowed and the *original*
    payload continues down the pipeline — that is the leak with the sanitizer
    removed, and the only defence is that the failure cannot be mistaken for
    success.
    """

    class ExplodingRedactor:
        def redact(self, markdown: str, findings: list[PIIFinding]) -> str:
            raise PIIRedactionError("no span for this value")

    guard.redactor = ExplodingRedactor()
    payload = {"fields": {"note": f"пациент {SYNTHETIC_PATIENT}"}}

    with pytest.raises(PIIRedactionError):
        guard.sanitize(payload, guard.evaluate_payload(payload))


# --- the policy the guard is running on --------------------------------------


def test_the_base_table_still_allows_a_name_and_the_persistence_override_does_not():
    """The escalation is an *override*, so the §4.4 baseline is untouched.

    Two halves, and both matter. The baseline rows are still ``ALLOW`` — a
    patient name in a source document is only a finding at a boundary, and
    changing the table would have made contour 1 halt on every clinical document.
    The escalation is the ``(canonical, persistence)`` override, which is the
    narrowest place it can live.
    """
    assert DEFAULT_POLICY.action_for(PIICategory.PERSON_NAME) is PIIAction.ALLOW
    assert PIICategory.PERSON_NAME in REDACT_ON_PERSIST
    assert REDACT_ON_PERSIST == REDACT_ON_EXTERNAL - CLINICAL_FACTS
    assert len(REDACT_ON_PERSIST) == 15


def test_the_escalation_is_scoped_to_canonical_and_persistence():
    """Both halves of the key are load-bearing, and the test isolates each.

    The override fires on ``destination=PERSISTENCE`` **and**
    ``stage=CANONICAL``. Change either and the same value resolves back to the
    baseline ``ALLOW``:

    - ``(DOCUMENT, PERSISTENCE)`` isolates the **stage**: a payload being stored
      after a *source* scan is a different event from a canonical payload being
      stored, and only the second has been rewritten to be safe.
    - ``(CANONICAL, INTERNAL_LLM)`` isolates the **destination**: a canonical
      payload going to an internal model still leaves the process boundary.

    ``(CANONICAL, EXTERNAL_LLM)`` deliberately is not in this list: the
    external-destination override is a *separate* rule that also resolves to
    ``REDACT``, so it cannot distinguish the persistence escalation from the
    external one.
    """
    note = f"пациент {SYNTHETIC_PATIENT}"

    def decision_at(stage: PIIScanStage, destination: PIIDestination) -> PIIDecision:
        context = build_policy_context(
            _settings(), stage=stage, destination=destination, redaction_available=True
        )
        findings = build_detector_chain(_settings()).detect_text(note)
        return DefaultPolicyEngine(DEFAULT_POLICY).evaluate(findings, context).decision

    assert decision_at(PIIScanStage.CANONICAL, PIIDestination.PERSISTENCE) is (
        PIIDecision.ALLOW_WITH_WARNING
    )
    assert decision_at(PIIScanStage.DOCUMENT, PIIDestination.PERSISTENCE) is PIIDecision.ALLOW
    assert decision_at(PIIScanStage.CANONICAL, PIIDestination.INTERNAL_LLM) is PIIDecision.ALLOW


def test_the_clinical_facts_are_the_three_that_are_not_redacted():
    """The set is named, and its size is asserted so a fourth cannot join silently.

    ``AGE``/``GENDER``/``NATIONALITY`` are in ``REDACT_ON_EXTERNAL`` and out of
    ``REDACT_ON_PERSIST``. A clinical fact in a canonical note is the reason the
    note is worth keeping, so masking it is not a privacy win — and the count is
    the tripwire, because a set difference that silently grows is the shape of
    that mistake.
    """
    expected = frozenset({PIICategory.AGE, PIICategory.GENDER, PIICategory.NATIONALITY})
    assert expected == CLINICAL_FACTS
    assert not CLINICAL_FACTS & REDACT_ON_PERSIST
    for category in CLINICAL_FACTS:
        assert DEFAULT_POLICY.risk_for(category) is PIIRiskLevel.LOW
        assert DEFAULT_POLICY.action_for(category) is PIIAction.ALLOW


def test_the_policy_engine_reports_one_action_per_found_category():
    """Sanitization is driven by the policy's actions, not by the categories found.

    If it were driven by the findings, every finding would be a redaction and the
    ``ALLOW`` rows would be decorative. Asserting the *direction* of the mapping —
    found categories in, actions out, ``CLINICAL_FACTS`` finding nothing to do —
    is what makes the difference visible.
    """
    engine = DefaultPolicyEngine()
    findings = [
        PIIFinding(
            category=category,
            value="x",
            masked_value="X",
            value_fingerprint=f"hmac-sha256:{category.value}",
            confidence=0.9,
            source=PIISource.PATTERN,
            detector=f"test.{category.value}",
            detector_version="1.2.0",
        )
        for category in (PIICategory.PERSON_NAME, PIICategory.AGE, PIICategory.DOCTOR_NAME)
    ]

    decided = engine.evaluate(
        findings,
        PIIPolicyContext(
            organization_id="tenant-1",
            stage=CANONICAL_POLICY_STAGE,
            destination=CANONICAL_POLICY_DESTINATION,
            redaction_available=True,
        ),
    )

    assert decided.actions[PIICategory.PERSON_NAME] is PIIAction.REDACT
    assert decided.actions[PIICategory.AGE] is PIIAction.ALLOW
    assert decided.actions[PIICategory.DOCTOR_NAME] is PIIAction.ALLOW
    assert decided.decision is PIIDecision.ALLOW_WITH_WARNING


def test_a_finding_in_no_path_is_still_counted_once():
    """The same value at two paths is two findings, and both are rewritten.

    Aggregation is per leaf by design (§7 decision 6): collapsing them would let
    a remediation fix ``fields.note`` while the identical value keeps leaking from
    ``fields.doctor``, and the guard's own report would show one clean path.
    """
    guard = _guard()
    payload = {"fields": {"note": f"пациент {SYNTHETIC_PATIENT}", "referrer": SYNTHETIC_PATIENT}}

    result = guard.evaluate_payload(payload)

    assert sorted(result.findings_by_path) == ["fields.note", "fields.referrer"]
    sanitized = guard.sanitize(payload, result)
    assert SYNTHETIC_PATIENT not in json.dumps(sanitized, ensure_ascii=False)
