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
    """``[0, 5)`` and ``[5, 10)`` do not intersect; merging them would lie.

    One placeholder would assert that a single value was removed where two
    distinct ones were, and would hide which. Adjacency is not overlap.
    """
    markdown = "ababababab"
    first = _finding("ababa", start=0, end=5, category=PIICategory.PERSON_NAME)
    second = _finding("babab", start=5, end=10, category=PIICategory.SNILS)

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


def test_one_manifest_category_is_still_undetected_and_that_is_a_phase_13_gap():
    """The accept criterion is **not** fully met today, and this says so.

    The manifest declares seven ``expected_categories`` for the consultation
    fixture; the Phase 11 chain finds six. The missing one is ``doctor_name``:
    ``Петров И. С.`` is a surname plus two initials, and
    :class:`~app.pii.detectors.PatternPIIDetector` deliberately has no two-token
    ФИО rule because it would also match ``Уважаемые жильцы``-style prose and
    organisation names. Finding it is
    :class:`~app.pii.detectors.StructuredFieldPIIDetector`'s job — the fixture
    writes ``**Врач:** Петров И. С.``, a labelled form — and that detector is
    Phase 13.

    So the gap is a **detection** gap, not a redaction gap, and it will be
    closed by adding a detector, not by changing the redactor. This test exists
    so the gap cannot quietly widen: when Phase 13 lands, ``uncovered`` becomes
    empty, the assertion below fails, and the fix is to fold
    ``expected_categories`` straight into
    ``test_redacting_the_consultation_fixture_removes_every_detected_value``.
    Until then the accept criterion is met for six of seven categories, which is
    a partial pass and is reported as one.
    """
    markdown, _ = _consultation_fixture()
    expected = _expected_categories()

    detected = {finding.category.value for finding in _gate_findings(markdown)}
    uncovered = expected - detected

    assert uncovered == {"doctor_name"}
    # Nothing unexpected: the chain must not be inventing categories the
    # manifest does not declare for this fixture.
    assert detected <= expected


def _expected_redacted(markdown: str, findings: list[PIIFinding]) -> str:
    """Build the expected redaction independently, to compare the redactor against.

    Deliberately *not* the redactor's algorithm: one case-insensitive search per
    finding, spliced right-to-left, with no offset verification, no merging and
    no confidence logic. Two implementations that agree are evidence; a
    disagreement localises the bug to whichever one is simpler.
    """
    spans = []
    for finding in findings:
        match = re.search(re.escape(finding.value), markdown, re.IGNORECASE)
        assert match, f"fixture does not contain {finding.category.value}"
        spans.append((match.start(), match.end(), finding))
    spans.sort(key=lambda span: span[0])
    for (_, earlier_end, _), (later_start, _, _) in zip(spans, spans[1:], strict=False):
        assert earlier_end <= later_start, "this helper assumes non-overlapping spans"
    result = markdown
    for start, end, finding in reversed(spans):
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
