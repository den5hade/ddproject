"""Behavioural tests for ``PlaceholderRedactor.redact`` (M5 Phase 12).

Phase 4 specified the algorithm and asserted that the implementation raised
``NotImplementedError``. Phase 12 wrote it, so these tests are behavioural
rather than contractual, and they concentrate on the two things that can go
wrong in a way no assertion about *format* would catch:

- **a wrong span replaced while the real value survives.** The findings the gate
  hands out index ``document.raw_text`` — case-folded, punctuation-mapped,
  whitespace-collapsed — while the text being redacted is the markdown. Every
  offset the gate returns for the consultation fixture is *in range* and
  *wrong*, so the naive reading of the locked algorithm corrupts the document and
  leaks the value it claims to have removed. ``test_wrong_offsets_are_never_
  trusted`` is the test that would have caught it.
- **a silent partial redaction.** Two overlapping spans, or an unresolvable
  finding, must not yield a partially redacted document that still looks
  successful.

The fixture test at the end is the phase's accept criterion: redact
``synthetic-consultation-01`` and assert every ``expected_categories`` value is
gone while every other character survives byte-for-byte.
"""

import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from app.classification.normalize import MarkdownNormalizer
from app.config.settings import Settings
from app.pii import (
    InvalidPIIInputError,
    PIICategory,
    PIIFinding,
    PIIRedactionError,
    PIISource,
    PlaceholderRedactor,
    build_document_gate,
    hash_pii_value,
    mask_pii_value,
    placeholder_for,
)
from pydantic import ValidationError

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "pii"
SECRET = "unit-test-fingerprint-secret-0123456789"


def _finding(
    value: str,
    *,
    category: PIICategory = PIICategory.PERSON_NAME,
    start: int | None = None,
    end: int | None = None,
    confidence: float = 0.9,
) -> PIIFinding:
    """A finding as a detector would build it, with optional offsets."""
    return PIIFinding(
        category=category,
        value=value,
        masked_value=mask_pii_value(category, value),
        value_fingerprint=hash_pii_value(value, secret=SECRET),
        confidence=confidence,
        source=PIISource.PATTERN,
        detector=f"pattern.{category.value}",
        detector_version="1.1.0",
        start=start,
        end=end,
    )


class _Context:
    """The three ids ``build_policy_context`` needs, and nothing else."""

    processing_id = uuid4()
    document_id = uuid4()
    document_version_id = uuid4()
    patient_id = uuid4()
    client_type = ""


# --- span replacement --------------------------------------------------------


def test_replaces_a_span_with_its_placeholder():
    markdown = "Пациент: Смирнова Ольга, договор подписан."
    finding = _finding("Смирнова Ольга")

    result = PlaceholderRedactor().redact(markdown, [finding])

    assert result == "Пациент: [PERSON_NAME], договор подписан."


def test_replacement_preserves_the_surrounding_characters_exactly():
    """Byte-identical outside the spans: no normalisation, no re-wrapping.

    A redactor that reflows whitespace would silently rewrite the document the
    LLM is about to extract from, making the artifact and the source disagree
    about what was said.
    """
    markdown = "  A\tB  \n\n  Смирнова Ольга  \n\n C  "
    result = PlaceholderRedactor().redact(markdown, [_finding("Смирнова Ольга")])
    assert result == "  A\tB  \n\n  [PERSON_NAME]  \n\n C  "


def test_redacts_every_finding_not_just_the_first():
    markdown = "Смирнова Ольга и Петров И. С. подписали документ."
    findings = [
        _finding("Смирнова Ольга", category=PIICategory.PERSON_NAME),
        _finding("Петров И. С.", category=PIICategory.DOCTOR_NAME),
    ]

    result = PlaceholderRedactor().redact(markdown, findings)

    assert "Смирнова" not in result
    assert "Петров" not in result
    assert result == "[PERSON_NAME] и [DOCTOR_NAME] подписали документ."


# --- offsets: right-to-left stability and the trust question -----------------


def test_correct_offsets_are_used_as_given():
    """The canonical-guard contour: the caller scanned this exact string."""
    markdown = "Пациент: Смирнова Ольга"
    start = markdown.index("Смирнова")
    finding = _finding("Смирнова Ольга", start=start, end=start + len("Смирнова Ольга"))

    assert PlaceholderRedactor().redact(markdown, [finding]) == "Пациент: [PERSON_NAME]"


def test_offsets_stay_valid_across_several_replacements():
    """Right-to-left is what makes this pass; a forward loop cannot.

    The second span is replaced first, and it is *shorter* than the text it
    replaces, so every offset to its left shifts. Working backwards means no
    earlier offset is ever consulted after the edit.
    """
    markdown = "aaaaaaaaaa BBBBBBBBBB cccccccccc"
    first = _finding("BBBBBBBBBB", start=10, end=20)
    second = _finding("cccccccccc", start=21, end=31)

    result = PlaceholderRedactor().redact(markdown, [first, second])

    assert result == f"aaaaaaaaaa [PERSON_NAME] {placeholder_for(PIICategory.PERSON_NAME)}"

    # And the same two findings supplied in the opposite order give the same
    # output: input order must not reach the artifact.
    reversed_result = PlaceholderRedactor().redact(markdown, [second, first])
    assert result == reversed_result


def test_replacement_is_longer_than_the_span_it_replaces():
    """``[MEDICAL_RECORD_NUMBER]`` is longer than a 10-digit number.

    The mirror of the previous test: a longer replacement shifts *later* offsets,
    which is harmless right-to-left and corrupting left-to-right.
    """
    markdown = "номер 0000001234 и СНИЛС 123-456-789 00"
    record = _finding("0000001234", category=PIICategory.MEDICAL_RECORD_NUMBER, start=6, end=16)
    snils = _finding("123-456-789 00", category=PIICategory.SNILS, start=20, end=33)

    result = PlaceholderRedactor().redact(markdown, [snils, record])

    assert "0000001234" not in result
    assert "123-456-789 00" not in result
    assert result.startswith("номер [MEDICAL_RECORD_NUMBER] и СНИЛС [SNILS]")


def test_out_of_range_offsets_fall_back_to_the_value():
    """An offset past the end of the text is not a span, whatever it selects."""
    markdown = "Пациент: Смирнова Ольга"
    finding = _finding("Смирнова Ольга", start=900, end=920)

    assert PlaceholderRedactor().redact(markdown, [finding]) == "Пациент: [PERSON_NAME]"


def test_wrong_offsets_are_never_trusted():
    """The leak this phase exists to prevent.

    The offsets are comfortably *in range* — they pass the locked algorithm's
    literal "lie within the markdown" test — and they point at unrelated text
    ("Пациент: "). Honouring them would replace the wrong characters and leave
    the value in place, while the artifact claimed the value had been removed.
    """
    markdown = "Пациент: Смирнова Ольга, договор подписан."
    wrong = _finding("Смирнова Ольга", start=0, end=9)  # selects "Пациент: "

    result = PlaceholderRedactor().redact(markdown, [wrong])

    assert result == "Пациент: [PERSON_NAME], договор подписан."
    assert "Смирнова" not in result
    assert "Пациент: " not in result.split("[PERSON_NAME]")[0][8:], "the wrong span was replaced"


def test_value_is_located_case_insensitively():
    """The canonicaliser case-folds, so the value rarely matches byte-for-byte."""
    markdown = "**Пациент:** Смирнова Ольга Ивановна"
    finding = _finding("смирнова ольга ивановна")  # what the detector actually saw

    result = PlaceholderRedactor().redact(markdown, [finding])

    assert "Смирнова" not in result
    assert result == "**Пациент:** [PERSON_NAME]"


def test_wrong_offsets_survive_a_case_folded_value():
    """Both guards apply at once: wrong offsets *and* a case-folded value."""
    markdown = "**Пациент:** Смирнова Ольга Ивановна"
    finding = _finding("смирнова ольга ивановна", start=3, end=11)  # selects "Пациент"

    result = PlaceholderRedactor().redact(markdown, [finding])

    assert "Ивановна" not in result
    assert result == "**Пациент:** [PERSON_NAME]"


# --- overlap, adjacency, merging ---------------------------------------------


def test_adjacent_spans_are_two_placeholders_not_one():
    """``[0, 2)`` and ``[2, 4)`` do not intersect; merging them would lie.

    One placeholder would assert that a single value was removed where two
    distinct ones were, and would hide which. Adjacency is not overlap.

    Each value occurs exactly **once** here, so the test measures adjacency and
    nothing else. The original fixture was ``"ababababab"`` split at 5 — where
    ``"ababa"`` and ``"babab"`` each occur several times over. H-1 makes the
    redactor remove every occurrence, those extra sightings do overlap, and they
    correctly merge into one span, so the old data no longer said which of the
    two invariants it was pinning.
    """
    markdown = "ab" + "cd"
    first = _finding("ab", start=0, end=2, category=PIICategory.PERSON_NAME)
    second = _finding("cd", start=2, end=4, category=PIICategory.SNILS)

    result = PlaceholderRedactor().redact(markdown, [first, second])

    assert result == "[PERSON_NAME][SNILS]"


def test_overlapping_spans_merge_into_one_placeholder():
    """Neither corrupting the text nor leaving a fragment of a value behind."""
    markdown = "Пациент: Смирнова Ольга Ивановна"
    first = _finding("Смирнова Ольга", start=9, end=23)
    second = _finding("Ольга Ивановна", start=16, end=31)

    result = PlaceholderRedactor().redact(markdown, [first, second])

    assert result == "Пациент: [PERSON_NAME]"
    assert "Ивановна" not in result


def test_merged_span_keeps_the_highest_confidence_placeholder():
    markdown = "Пациент: Смирнова Ольга"
    certain = _finding("Смирнова Ольга", start=9, end=23, confidence=0.99)
    unsure = _finding("Смирнова Ольга", start=9, end=23, confidence=0.4)
    # Same span, same confidence, different category: the tie must not be broken
    # by which finding the caller happened to pass first.
    snils = _finding("Смирнова Ольга", start=9, end=23, category=PIICategory.SNILS, confidence=0.99)

    assert PlaceholderRedactor().redact(markdown, [unsure, certain]) == "Пациент: [PERSON_NAME]"
    assert PlaceholderRedactor().redact(markdown, [certain, unsure]) == "Пациент: [PERSON_NAME]"
    assert PlaceholderRedactor().redact(markdown, [snils, certain]) == "Пациент: [PERSON_NAME]"
    assert PlaceholderRedactor().redact(markdown, [certain, snils]) == "Пациент: [PERSON_NAME]"


def test_merge_tie_resolves_deterministically_not_by_input_order():
    """Two findings, one span, one confidence: the artifact must not depend on
    the order the caller happened to supply them in.

    Resolved on the placeholder token, which is intrinsic to the finding, so
    redacting the same document twice produces byte-identical output.
    """
    markdown = "Смирнова Ольга"
    left = _finding("Смирнова Ольга", start=0, end=15, category=PIICategory.PERSON_NAME)
    right = _finding("Смирнова Ольга", start=0, end=15, category=PIICategory.SNILS)

    forward = PlaceholderRedactor().redact(markdown, [left, right])
    backward = PlaceholderRedactor().redact(markdown, [right, left])

    assert forward == backward
    # "[PERSON_NAME]" sorts before "[SNILS]", so the token decides, not arrival.
    assert forward == "[PERSON_NAME]"


def test_a_span_fully_containing_another_collapses_to_the_outer_one():
    markdown = "Пациент: Смирнова Ольга"
    outer = _finding("Смирнова Ольга", start=9, end=23)
    inner = _finding("Смирнова", start=9, end=17)

    result = PlaceholderRedactor().redact(markdown, [outer, inner])

    assert result == "Пациент: [PERSON_NAME]"


# --- the fail-closed paths ---------------------------------------------------


def test_no_findings_is_a_no_op():
    markdown = "Ничего персонального нет."
    assert PlaceholderRedactor().redact(markdown, []) == markdown


def test_an_unresolvable_finding_raises_rather_than_skipping():
    """A silently skipped redaction is a leak the artifact would attest to."""
    finding = _finding("Смирнова Ольга", start=0, end=5)  # not in the text, wrong offsets

    with pytest.raises(PIIRedactionError) as excinfo:
        PlaceholderRedactor().redact("Совершенно другой документ.", [finding])

    message = str(excinfo.value)
    assert "person_name" in message
    assert "refuses to guess" in message


def test_one_unresolvable_finding_fails_the_whole_call():
    """Partial redaction is not a lesser outcome; it is the same leak."""
    good = _finding("Смирнова Ольга")
    bad = _finding("Отсутствующее значение", start=0, end=3)

    with pytest.raises(PIIRedactionError):
        PlaceholderRedactor().redact("Пациент: Смирнова Ольга", [good, bad])


def test_an_empty_value_with_unverifiable_offsets_raises():
    """Nothing to match against, so nothing may be replaced on a guess."""
    with pytest.raises(PIIRedactionError):
        PlaceholderRedactor().redact("Пациент: Смирнова Ольга", [_finding("", start=9, end=23)])


# --- inputs are not mutated --------------------------------------------------


def test_the_findings_list_is_not_mutated():
    markdown = "Смирнова Ольга и Петров И. С."
    findings = [
        _finding("Петров И. С.", category=PIICategory.DOCTOR_NAME),
        _finding("Смирнова Ольга", category=PIICategory.PERSON_NAME),
    ]
    before = [(f.category, f.start, f.end) for f in findings]

    PlaceholderRedactor().redact(markdown, findings)

    assert [(f.category, f.start, f.end) for f in findings] == before


def test_the_finding_objects_are_frozen():
    """Step 4: a redactor cannot "helpfully" annotate a finding either.

    ``PIIFinding`` is ``frozen=True``, so the non-mutation guarantee is a
    property of the type rather than of reviewer vigilance — and the finding
    list the gate will project into the audit artifact is the same object.
    """
    finding = _finding("Смирнова Ольга")
    with pytest.raises(ValidationError):
        finding.start = 5


def test_the_input_string_is_unchanged():
    markdown = "Пациент: Смирнова Ольга"
    PlaceholderRedactor().redact(markdown, [_finding("Смирнова Ольга")])
    assert markdown == "Пациент: Смирнова Ольга"


# --- SECRET and idempotence --------------------------------------------------


def test_secret_placeholder_reveals_nothing():
    """``[SECRET]`` is a marker, not an encoding: nothing maps back to a value."""
    credential = "sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    markdown = f"config: api_key={credential} end"
    finding = _finding(credential, category=PIICategory.SECRET)

    result = PlaceholderRedactor().redact(markdown, [finding])

    assert result == "config: api_key=[SECRET] end"
    for fragment in (credential, "sk-live", "ABCDEFGH", "0123456789"):
        assert fragment not in result


def test_a_second_pass_over_redacted_text_is_a_no_op():
    """Idempotence, stated the way the pipeline would actually reach it.

    Re-running :meth:`redact` with the *same* findings cannot succeed — the
    values are gone, so the spans are unresolvable and the redactor raises,
    which is correct. The real property is that a second *pipeline pass* is a
    fixed point: detection re-runs on the redacted markdown, finds nothing it can
    act on, and the empty finding list makes redaction a no-op. Asserted
    end-to-end through the real gate rather than by hand-feeding findings.
    """
    settings = Settings(_env_file=None, pii_fingerprint_secret=SECRET)
    gate = build_document_gate(settings)
    scan = lambda text: gate.aggregator.aggregate(  # noqa: E731
        gate.detector.detect(MarkdownNormalizer().normalize(text, metadata={}))
    )

    markdown, _ = _consultation_fixture()
    first_findings = scan(markdown)
    assert first_findings

    redacted = PlaceholderRedactor().redact(markdown, first_findings)
    second_findings = scan(redacted)

    assert second_findings == []
    assert PlaceholderRedactor().redact(redacted, second_findings) == redacted


def test_re_redacting_with_the_original_findings_raises_rather_than_double_replacing():
    """The fail-closed half of idempotence.

    A second pass with the same findings must not produce ``[[SNILS]]`` or
    silently succeed having done nothing; it has nothing left to remove, and the
    only honest answer is that it cannot.
    """
    markdown = "Пациент: Смирнова Ольга, СНИЛС 123-456-789 00"
    findings = [
        _finding("Смирнова Ольга"),
        _finding("123-456-789 00", category=PIICategory.SNILS),
    ]
    redacted = PlaceholderRedactor().redact(markdown, findings)

    with pytest.raises(PIIRedactionError):
        PlaceholderRedactor().redact(redacted, findings)

    assert "[PERSON_NAME]" in redacted
    assert "[[" not in redacted, "a placeholder must never be re-wrapped"


# --- accept: the real fixture, scanned by the real gate ----------------------


def _consultation_fixture() -> tuple[str, str]:
    path = FIXTURES / "patient" / "synthetic-consultation-01.md"
    return path.read_text(encoding="utf-8"), str(path)


def _expected_categories() -> set[str]:
    """The manifest's ground truth for the consultation fixture."""
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    entry = next(
        item
        for item in manifest["fixtures"]
        if item["file"].endswith("synthetic-consultation-01.md")
    )
    return set(entry["expected_categories"])


def _gate_findings(markdown: str) -> list[PIIFinding]:
    """Scan the fixture through the real gate, as the pipeline would."""
    settings = Settings(_env_file=None, pii_fingerprint_secret=SECRET)
    gate = build_document_gate(settings)
    normalized = MarkdownNormalizer().normalize(markdown, metadata={})
    chain = gate.detector
    findings = chain.detect(normalized)
    return gate.aggregator.aggregate(findings)


def test_redacting_the_consultation_fixture_removes_every_detected_value():
    """**Phase 12 accept criterion**, over the values the gate actually finds.

    Every value the manifest declares *and the chain detects* must be gone from
    the output, and every other character must survive byte-for-byte. The second
    half is the one that matters: a redactor that removed the right values by
    also reflowing the document would pass the first assertion and destroy the
    artifact's fidelity.
    """
    markdown, _ = _consultation_fixture()
    findings = _gate_findings(markdown)
    assert findings

    redacted = PlaceholderRedactor().redact(markdown, findings)

    for finding in findings:
        assert finding.value.casefold() not in redacted.casefold(), finding.category.value
        assert placeholder_for(finding.category) in redacted

    # The strong half: the redacted output is *exactly* what splicing those
    # values out would produce, so every untouched character is accounted for.
    assert redacted == _expected_redacted(markdown, findings)


def test_the_consultation_fixtures_declared_categories_are_all_detected():
    """The Phase 12 criterion, now complete — and asserted in both directions.

    This was a tripwire: through M5 Phase 12 the chain found six of the seven
    categories the manifest declared, the missing one being ``doctor_name``,
    because ``Петров И. С.`` is a surname plus two initials and only
    :class:`~app.pii.detectors.StructuredFieldPIIDetector` claims a labelled
    two-part ФИО. Phase 13 closed the gap, so the assertion inverts from
    ``uncovered == {"doctor_name"}`` to equality, and the *reverse* containment
    is now part of it: a chain that invented a category the manifest does not
    declare for this fixture would be inventing ground truth.
    """
    markdown, _ = _consultation_fixture()
    expected = _expected_categories()
    detected = {finding.category.value for finding in _gate_findings(markdown)}

    assert detected == expected
    # The gap this replaced, kept as an explicit statement of what Phase 13 added.
    assert "doctor_name" in detected


def test_no_phase_13_detector_reads_a_redaction_placeholder_as_a_value():
    """A second pass must stay a fixed point for the *new* rules too.

    ``**Адрес:** [address]`` is what a redacted document looks like, and
    ``address.labelled`` is a free-text rule: without a guard it takes
    ``[address]`` as the address, reports it, and the pipeline's second pass
    finds PII in its own output. The same document then has to be redacted
    again, to a document that is again detected, and nothing converges.

    Asserted over the whole chain rather than per rule because the placeholder
    is the *output* of Phase 12 meeting the *input* of Phase 13; the bug lives
    in the seam, and a per-rule test would only ever cover the rules its author
    remembered.
    """
    markdown, _ = _consultation_fixture()
    settings = Settings(_env_file=None, pii_fingerprint_secret=SECRET)
    gate = build_document_gate(settings)
    scan = lambda text: gate.aggregator.aggregate(  # noqa: E731
        gate.detector.detect(MarkdownNormalizer().normalize(text, metadata={}))
    )

    first = scan(markdown)
    assert first
    redacted = PlaceholderRedactor().redact(markdown, first)

    assert scan(redacted) == []


def _expected_redacted(markdown: str, findings: list[PIIFinding]) -> str:
    """Build the expected redaction independently, to compare the redactor against.

    Deliberately *not* the redactor's algorithm: one case-insensitive search per
    finding, spans resolved by value alone, merged by intersection with the
    highest-confidence finding naming the placeholder, then spliced
    right-to-left. No offset verification, no confidence logic beyond picking a
    winner, no shared code. Two implementations that agree are evidence; a
    disagreement localises the bug to whichever one is simpler.

    The merge is not optional bookkeeping. M5 Phase 13 added
    ``structured.address.labelled``, so the consultation fixture now yields two
    ``ADDRESS`` findings that overlap — ``address.locality`` claims ``г. москва``
    inside the full value the labelled rule claims — and the redactor's contract
    is that intersecting spans become one span carrying one placeholder. A helper
    that asserted the spans were disjoint would have kept passing right up to the
    day a real overlap arrived, which is exactly the day it stops being useful.
    """
    spans: list[list] = []
    for finding in findings:
        match = re.search(re.escape(finding.value), markdown, re.IGNORECASE)
        assert match, f"fixture does not contain {finding.category.value}"
        spans.append([match.start(), match.end(), finding])

    spans.sort(key=lambda span: (span[0], span[1], -span[2].confidence, span[2].category.value))

    merged: list[list] = []
    for span in spans:
        if merged and span[0] < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], span[1])
            if span[2].confidence > merged[-1][2].confidence:
                merged[-1][2] = span[2]
        else:
            merged.append(span)

    result = markdown
    for start, end, finding in reversed(merged):
        result = result[:start] + placeholder_for(finding.category) + result[end:]
    return result


def test_redacting_the_fixture_leaves_no_raw_identifier_anywhere():
    """The leak test, on the fixture, through the real gate.

    Nothing that the detector identified may survive in any form — not the raw
    value, not the case-folded form, not a fingerprint.
    """
    markdown, _ = _consultation_fixture()
    findings = _gate_findings(markdown)

    redacted = PlaceholderRedactor().redact(markdown, findings)

    for finding in findings:
        assert finding.value not in redacted
        assert finding.value.casefold() not in redacted.casefold()
        assert finding.value_fingerprint not in redacted
    assert "value_fingerprint" not in redacted


def test_gate_findings_carry_offsets_that_index_a_different_string():
    """The premise of the whole offset-verification design, asserted.

    If a future normaliser change makes the gate's offsets index the markdown
    directly, this fails — and the reviewer learns the verification is now
    redundant rather than that a leak was closed by accident. It also keeps the
    concrete numbers in ``PlaceholderRedactor``'s docstring honest.
    """
    markdown, _ = _consultation_fixture()
    findings = _gate_findings(markdown)
    assert findings, "the fixture must produce findings"

    wrong = [
        finding
        for finding in findings
        if finding.start is not None
        and 0 <= finding.start < finding.end <= len(markdown)
        and markdown[finding.start : finding.end].casefold() != finding.value.casefold()
    ]
    assert len(wrong) == len(findings), "every offset should currently point at the wrong text"


# --- the flag the phase was really about ------------------------------------


def test_the_document_gate_reports_a_working_redactor():
    """Phase 12's other half: the policy must know redaction is available."""
    settings = Settings(_env_file=None, pii_fingerprint_secret=SECRET)
    gate = build_document_gate(settings)

    context = gate.policy_context_builder(
        MarkdownNormalizer().normalize("текст", metadata={}), _Context()
    )
    assert context.redaction_available is True


def test_the_flag_still_fails_closed_without_a_secret():
    """Setting the redaction flag must not soften the secret requirement."""
    with pytest.raises(InvalidPIIInputError):
        build_document_gate(Settings(_env_file=None, pii_fingerprint_secret="  "))


# --- one finding, every occurrence (H-1) --------------------------------------


def test_a_value_repeated_in_the_text_is_removed_at_every_occurrence():
    """Three occurrences, no offsets: all three go, and nothing else moves.

    H-1. A single ``REDACT`` action is a claim about the *value*, and the caller
    cannot make it per-occurrence: aggregation deduplicates on
    ``(category, value_fingerprint)``, so a value written twice yields one
    finding that says which value and nothing about how often it appears. The
    redactor is therefore the only component that can know, and removing one
    occurrence of three is a document that looks redacted and is not.
    """
    markdown = "СНИЛС 123-067-082 21 вновь; СНИЛС 123-067-082 21 подтверждён; СНИЛС 123-067-082 21."
    finding = _finding("123-067-082 21", category=PIICategory.SNILS)

    result = PlaceholderRedactor().redact(markdown, [finding])

    assert "123-067-082 21" not in result
    assert result.count("[SNILS]") == 3
    assert result == "СНИЛС [SNILS] вновь; СНИЛС [SNILS] подтверждён; СНИЛС [SNILS]."


def test_a_repeated_value_is_removed_in_a_different_case():
    """The canonicaliser case-folds, so occurrences need not be byte-identical.

    The second sighting is lower-case, which is how a real document carries a
    repeated surname. Matching is case-insensitive per occurrence, not only on
    the one that happened to be found first.
    """
    markdown = "Пациент Кузнецова Александра. Пациент кузнецова александра."
    finding = _finding("Кузнецова Александра", start=8, end=26)

    result = PlaceholderRedactor().redact(markdown, [finding])

    assert "Кузнецова" not in result
    assert "кузнецова" not in result
    assert result == "Пациент [PERSON_NAME]. Пациент [PERSON_NAME]."


def test_a_verified_offset_hint_does_not_suppress_the_other_occurrences():
    """The hint path was the second half of the leak, and it is covered too.

    A verified hint pins **one** span. When the caller walks exactly the string
    it scanned — the canonical-guard contour — the hint is always verified, so
    returning it and skipping the search would have left contour 2 leaking just
    as it did before. Both are collected.
    """
    markdown = "СНИЛС 123-067-082 21. Повторно СНИЛС 123-067-082 21 продублирован в карте."
    hint = _finding("123-067-082 21", category=PIICategory.SNILS, start=6, end=21)

    result = PlaceholderRedactor().redact(markdown, [hint])

    assert "123-067-082 21" not in result
    assert result == "СНИЛС [SNILS]. Повторно СНИЛС [SNILS] продублирован в карте."


def test_a_hint_and_the_search_yield_one_placeholder_per_occurrence():
    """N occurrences produce N placeholders, not N+1.

    Collecting the hint *and* the search is only safe if the span they agree on
    is counted once. Without this, the first occurrence would be replaced by two
    overlapping spans that merge into a single ``[SNILS][SNILS]`` — a corrupted
    document produced by a fix for a leak, which is the failure mode worth
    spending a test on.
    """
    markdown = "СНИЛС 123-067-082 21 и снова 123-067-082 21."
    hint = _finding("123-067-082 21", category=PIICategory.SNILS, start=6, end=20)

    result = PlaceholderRedactor().redact(markdown, [hint])

    assert result == "СНИЛС [SNILS] и снова [SNILS]."


def test_a_back_to_back_repetition_is_two_placeholders():
    """Adjacent repetitions are not one run of text, so they are two tokens.

    The merge rule stays "intersecting, not touching" — ``"ABAB"`` with value
    ``"AB"`` is two values that happen to share a boundary, and collapsing them
    would assert that one thing was removed where two were.
    """
    markdown = "номерABABдубль"
    finding = _finding("AB", category=PIICategory.SNILS)

    result = PlaceholderRedactor().redact(markdown, [finding])

    assert result == "номер[SNILS][SNILS]дубль"


def test_a_repeated_value_in_the_document_fixture_leaves_no_trace():
    """The gate's own data path, not a hand-built finding.

    Detection and aggregation are the shipped ones, so this is the contour-1
    property Phase 15 will rely on: scan, aggregate to one finding, redact — and
    the value the manifest's detector found is absent from every occurrence of
    the text it was scanned in.
    """
    markdown = "СНИЛС 123-067-082 21. Повторно СНИЛС 123-067-082 21 продублирован в карте."
    findings = _gate_findings(markdown)
    assert [f.category for f in findings] == [PIICategory.SNILS]

    result = PlaceholderRedactor().redact(markdown, findings)

    assert "123-067-082 21" not in result
    assert result == "СНИЛС [SNILS]. Повторно СНИЛС [SNILS] продублирован в карте."


def test_a_value_only_reachable_by_its_offsets_still_raises():
    """Widening the search must not have softened the fail-closed branch.

    A finding with neither a usable hint nor a searchable value still has to
    raise, and an unsearchable value — one whose whitespace the canonicaliser
    collapsed — must not be reported as "found nowhere" when the hint already
    proved it is there.
    """
    markdown = "Пациент: Смирнова   Ольга"
    hint = _finding("смирнова ольга", start=9, end=25)  # selects the triple-spaced run

    assert PlaceholderRedactor().redact(markdown, [hint]) == "Пациент: [PERSON_NAME]"

    with pytest.raises(PIIRedactionError):
        PlaceholderRedactor().redact("совсем другой текст", [hint])


def test_the_module_still_states_the_every_occurrence_deviation():
    """A deviation nobody can find is a deviation nobody can review.

    The M4 algorithm said "resolve every finding to a span", and H-1 changed it
    to "to every span it occupies". A refactor that restores the singular
    wording would otherwise leave the code correct-looking and the reason gone,
    and the next person to dedup an entity per occurrence would ship the leak
    again believing the docstring described what happens.
    """
    from app.pii import redaction

    doc = redaction.__doc__ or ""

    assert "Deviation 2" in doc
    assert "every occurrence" in doc
    assert "123-067-082 21" in doc  # the reproduced leak is quoted, not paraphrased
