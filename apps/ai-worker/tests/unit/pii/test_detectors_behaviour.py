"""Behaviour tests for the pattern detector (M5 Phase 9).

M4's ``test_detectors.py`` asserts the *shape* of the contract. This module
asserts what the contract now produces: which patterns fire, on which text, with
which mask, fingerprint, offsets and confidence.

Two things here are security-relevant rather than merely behavioural, and both
have a named test:

- **Gotcha G1** — the live leak is a *declined* Cyrillic name
  (``"для пациента Шадеркина Дениса Сергеевича"``). A nominative
  ``Фамилия Имя Отчество`` pattern misses it, and so does any
  "capitalised word at the start of the string" heuristic. The regression test
  uses the exact string from the leak.
- **Case-folding** — ``NormalizedDocument.raw_text`` is case-folded, so contour 1
  scans text in which every name is lower-case. A title-case-only rule would
  match the canonical guard's payload leaves and nothing else, leaving the
  contour-1 gate silently blind behind a green suite. There is a test that feeds
  the gate a *real* normalized document, not just literals.
"""

from __future__ import annotations

import pytest
from app.pii import (
    DETECTOR_VERSION,
    CompositePIIDetector,
    DefaultPIIAggregator,
    InvalidPIIInputError,
    PatternPIIDetector,
    PIICategory,
    PIISource,
)
from app.pii.detectors import _PATTERNS
from app.pii.masking import FINGERPRINT_PREFIX, FIXED_MASKS

SECRET = "phase-9-behaviour-test-secret"

G1_LEAK_TEXT = "Осмотр проведён для пациента Шадеркина Дениса Сергеевича."
"""The live leak's own sentence (plan §7 gotcha G1), minus the identifying prefix.

Named explicitly because this is the single most likely way a green Phase 9
still leaves the leak open: a nominative-only name pattern matches every
synthetic fixture in the dataset and none of the real one.
"""


@pytest.fixture
def detector() -> PatternPIIDetector:
    return PatternPIIDetector(fingerprint_secret=SECRET)


def _categories(detector: PatternPIIDetector, text: str) -> set[PIICategory]:
    return {finding.category for finding in detector.detect_text(text)}


# --- per-category patterns -------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Пациент: Смирнова Ольга Ивановна, 1974-03-12", PIICategory.PERSON_NAME),
        ("СНИЛС 123-067-082 21", PIICategory.SNILS),
        ("Полис ОМС: 2203945854001234", PIICategory.INSURANCE_NUMBER),
        ("+7 (495) 000-11-22", PIICategory.PHONE),
        ("o.smirnova@example.invalid", PIICategory.EMAIL),
        ("Дата рождения: 1974-03-12", PIICategory.DATE_OF_BIRTH),
        ("Номер талона: 2026030709303211960141", PIICategory.TICKET_NUMBER),
    ],
)
def test_each_phase_9_category_fires_on_its_own_shape(detector, text, expected):
    """The seven categories Phase 9 names, one real shape each.

    The examples are the real marker's label/value structure and the real note's
    values, with no real patient data (plan §7 decision 9).
    """
    assert expected in _categories(detector, text)


def test_all_seven_named_patterns_have_a_rule_row():
    """Prose in a docstring is not a rule; assert the table itself."""
    covered = {row.category for row in _PATTERNS}
    assert {
        PIICategory.PERSON_NAME,
        PIICategory.SNILS,
        PIICategory.INSURANCE_NUMBER,
        PIICategory.PHONE,
        PIICategory.EMAIL,
        PIICategory.DATE_OF_BIRTH,
        PIICategory.TICKET_NUMBER,
    } <= covered


def test_clean_prose_yields_nothing(detector):
    """A maintenance notice must find zero entities — a gate that always fires
    trains its readers to ignore it, which is the failure mode that outlives a
    missed leak."""
    text = (
        "Уважаемые жильцы! Напоминаем, что 12 июня с 09:00 до 17:00 будет прекращена "
        "подача горячей воды в здании. Администрация."
    )
    assert detector.detect_text(text) == []


# --- gotcha G1: the declined name -----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        G1_LEAK_TEXT,
        "для пациента Шадеркина Дениса Сергеевича",
        "Направить к врачу: Смирновой Ольге Ивановне",
    ],
)
def test_declined_cyrillic_name_is_detected(detector, text):
    findings = [
        finding
        for finding in detector.detect_text(text)
        if finding.category is PIICategory.PERSON_NAME
    ]
    assert findings, f"declined name missed in {text!r}"
    assert all(finding.source is PIISource.PATTERN for finding in findings)


def test_declined_name_masks_every_token(detector):
    """The mask must cover the name, not just its first letter.

    §4.5's token rule keeps one character per token: a mask that kept more would
    narrow identity, and one that kept fewer would make the artifact useless for
    debugging which field was hit.
    """
    finding = next(
        finding
        for finding in detector.detect_text(G1_LEAK_TEXT)
        if finding.category is PIICategory.PERSON_NAME
    )
    assert finding.masked_value == "Ш******** Д***** С*********"
    assert "ен" not in finding.masked_value


def test_two_token_name_does_not_fire_as_a_patient_name(detector):
    """``Петров И. С.`` is a doctor; Phase 13's labelled detector claims it.

    A two-token rule would also claim ``Уважаемые жильцы`` and any organisation
    name, which is how a practitioner-group name ends up redacted as patient PII
    — the exact mistake the medical/practitioner split exists to prevent.
    """
    assert PIICategory.PERSON_NAME not in _categories(detector, "Врач: Петров И. С.")
    assert PIICategory.PERSON_NAME not in _categories(detector, "Уважаемые жильцы!")


# --- case-folding (the contour-1 trap) -------------------------------------


def test_patterns_survive_the_case_folded_raw_text(detector):
    """The gate scans ``raw_text``, which is case-folded — not prose.

    Feeding a title-cased literal would pass while the real pipeline path found
    nothing at all. Note which rule answers: the capitalised
    ``person_name.three_token`` cannot match folded text, so the leak on the
    contour the pipeline actually uses is covered by
    ``person_name.after_label`` alone.
    """
    folded = G1_LEAK_TEXT.casefold()
    assert folded != G1_LEAK_TEXT
    found = [
        finding
        for finding in detector.detect_text(folded)
        if finding.category is PIICategory.PERSON_NAME
    ]
    assert found, "the case-folded leak must still be detected"
    assert {finding.detector for finding in found} == {"pattern.person_name.after_label"}


def test_both_name_rules_agree_on_one_span_when_the_label_is_present(detector):
    """Two rules, one entity, one fingerprint — so aggregation can collapse them.

    The real pair behind the dedup rule: both rows match exactly the same span of
    the same sentence, so the values are equal and the fingerprints are equal.
    This is the only test in M5 where two rules collide on identical text, and it
    is why the dedup key is ``(category, value_fingerprint)`` rather than offsets.
    """
    found = [
        finding
        for finding in detector.detect_text(G1_LEAK_TEXT)
        if finding.category is PIICategory.PERSON_NAME
    ]
    assert len(found) == 2
    assert {finding.value_fingerprint for finding in found} == {found[0].value_fingerprint}
    assert len({(finding.start, finding.end) for finding in found}) == 1
    assert len(DefaultPIIAggregator().aggregate(found)) == 1


def test_the_label_rule_keeps_its_offsets_on_the_name_not_the_label(detector):
    """The value is the name; the introducing word is context, not a field value."""
    text = "пациент: смирнова ольга ивановна"
    finding = next(f for f in detector.detect_text(text) if f.detector.endswith("after_label"))
    assert text[finding.start : finding.end] == "смирнова ольга ивановна"
    assert "пациент" not in finding.masked_value


@pytest.mark.parametrize(
    "text",
    [
        "**пациент:** смирнова ольга ивановна",
        "Пациент - смирнова ольга ивановна",
        "### Пациент: смирнова ольга ивановна",
    ],
)
def test_the_label_rule_survives_markdown_decoration(detector, text):
    """``raw_text`` keeps emphasis markers, so ``**пациент:** …`` is the real input.

    A rule that allowed only a colon and a space would match the fixture on disk
    and find nothing in the document the pipeline hands the gate.
    """
    found = [
        finding
        for finding in detector.detect_text(text.casefold())
        if finding.category is PIICategory.PERSON_NAME
    ]
    assert found, f"markdown-decorated label missed in {text!r}"
    assert found[0].value == "смирнова ольга ивановна"


def test_a_labelled_card_number_is_claimed_and_an_unlabelled_one_is_not(detector):
    """The label is the evidence; the length alone is a guess.

    Phase 13's structured detector supersedes this rule, but the manifest's
    ``expected_risk_level`` of ``high`` for this fixture depends on it — a
    10-digit run is only a medical record number when the document says so.
    """
    labelled = detector.detect_text("**номер карты:** 0000001234")
    assert [f.category for f in labelled] == [PIICategory.MEDICAL_RECORD_NUMBER]
    assert labelled[0].value == "0000001234"
    assert labelled[0].masked_value == "00********"

    unlabelled = detector.detect_text("Идентификатор 0000001234 выдан")
    assert {f.category for f in unlabelled} == set()


def test_offsets_index_the_text_that_was_passed(detector):
    text = f"Заключение. {G1_LEAK_TEXT}"
    finding = next(
        finding
        for finding in detector.detect_text(text)
        if finding.category is PIICategory.PERSON_NAME
    )
    assert text[finding.start : finding.end] == finding.value


def test_no_offsets_are_invented_for_empty_input(detector):
    assert detector.detect_text("") == []
    assert detector.detect_text("   ") == []


# --- finding shape ---------------------------------------------------------


def test_every_finding_is_masked_fingerprinted_and_versioned(detector):
    finding = next(
        finding
        for finding in detector.detect_text("СНИЛС 123-067-082 21")
        if finding.category is PIICategory.SNILS
    )
    assert finding.masked_value == "***-***-*** **"
    assert finding.value_fingerprint.startswith(FINGERPRINT_PREFIX)
    assert finding.detector_version == DETECTOR_VERSION
    assert finding.detector.startswith("pattern.")
    assert 0.0 < finding.confidence <= 1.0
    assert finding.source is PIISource.PATTERN


def test_the_raw_value_stays_in_memory_only(detector):
    """A detector is the last component that sees the value; it must not hand it on."""
    finding = detector.detect_text("СНИЛС 123-067-082 21")[0]
    assert "value" not in finding.model_dump()
    assert "value_fingerprint" not in finding.model_dump()
    assert finding.value == "123-067-082 21"


def test_fingerprint_changes_with_the_secret():
    """A per-deployment key is what makes the fingerprint unlinkable across tenants."""
    a = PatternPIIDetector(fingerprint_secret="secret-a").detect_text("СНИЛС 123-067-082 21")
    b = PatternPIIDetector(fingerprint_secret="secret-b").detect_text("СНИЛС 123-067-082 21")
    assert a[0].value_fingerprint != b[0].value_fingerprint


def test_an_unconfigured_detector_fails_closed():
    with pytest.raises(InvalidPIIInputError):
        PatternPIIDetector().detect_text("СНИЛС 123-067-082 21")


# --- overlapping rules -----------------------------------------------------


def test_a_specific_rule_wins_over_the_long_digit_run(detector):
    """СНИЛС is 9 digits plus a checksum; the medical-record rule is 9 digits.

    Both match the same span, and which one survives is decided by table order
    (aggregation keeps *both* — a different category is not a duplicate). So the
    finding list must contain the specific category, and the generic one is an
    accepted, separately-masked duplicate rather than a replacement.
    """
    found = detector.detect_text("Полис: 2203945854001234")
    categories = {finding.category for finding in found}
    assert PIICategory.INSURANCE_NUMBER in categories
    assert PIICategory.TICKET_NUMBER in categories, "the long-run rule must not be suppressed"
    insurance = next(f for f in found if f.category is PIICategory.INSURANCE_NUMBER)
    assert insurance.masked_value == FIXED_MASKS[PIICategory.INSURANCE_NUMBER]


def test_a_short_number_is_not_a_ticket(detector):
    """An order id or a dosage is not a 9-digit medical record number.

    The rule exists to catch the real marker's ``Номер талона`` (22 digits). A
    bare ``39`` is an age as often as a measurement, and ``№ 5`` is an order.
    """
    found = _categories(detector, "Назначение: таблетки 2 раза в день, курс 14 дней")
    assert PIICategory.TICKET_NUMBER not in found
    assert PIICategory.MEDICAL_RECORD_NUMBER not in found


# --- composite -------------------------------------------------------------


def test_composite_fans_out_over_the_chain():
    """Two detectors, one text: findings from both, in configured order.

    Order matters because aggregation breaks ties by earliest position, so the
    chain order is what makes a winner deterministic.
    """
    first = PatternPIIDetector(fingerprint_secret=SECRET)
    second = PatternPIIDetector(fingerprint_secret=SECRET)
    composite = CompositePIIDetector([first, second])
    text = "Пациент: Смирнова Ольга Ивановна"
    found = composite.detect_text(text)
    assert len(found) == 2
    assert all(finding.detector_version == DETECTOR_VERSION for finding in found)


def test_composite_detect_reads_raw_text_and_returns_everything():
    from types import SimpleNamespace

    composite = CompositePIIDetector([PatternPIIDetector(fingerprint_secret=SECRET)])
    document = SimpleNamespace(raw_text="Пациент: Смирнова Ольга Ивановна")
    found = composite.detect(document)
    assert [finding.category for finding in found] == [PIICategory.PERSON_NAME]
