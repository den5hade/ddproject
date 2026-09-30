"""Phase 2: the manifest audit is a gate, not a report.

`MANIFEST_AUDIT.md` is only worth writing if applying one of its findings changes
something. A findings list that sits next to the code and asserts nothing is a
document, and the natural way for it to go stale is for the finding to be applied
*quietly* — someone corrects a label because the audit told them to, the numbers
improve, and the reasoning that made the correction conditional on a ruling is
gone. Each test below therefore pins a *pair* of facts: the finding is recorded
**and** the thing it objects to is still the current state of the repository. Both
halves are load-bearing. If the finding is deleted while the label stays, the
audit has lost the reasoning. If the label is flipped while the finding stays,
someone has taken a decision this phase was not authorised to take.

The committed corpus is also, by construction, incapable of producing a false
positive (F1), and that fact is asserted directly rather than left as prose — a
report quoting `false_positive_claims: 0` as a precision figure is quoting a
tautology, and the test that pins the tautology is what makes the distinction
auditable.

Deliberately *not* here: any assertion about the local real corpus, which does not
exist in CI. The audit records the obligation for Phase 3 in prose; a test against
a corpus that only exists on one machine would either skip everywhere or pin
numbers nobody can reproduce.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.pii import evaluate as ev
from app.pii.fixtures import (
    CONTOUR_CANONICAL,
    DATASET_SYNTHETIC,
    iter_synthetic_fixtures,
)
from app.pii.models import PIICategory

AUDIT = Path(__file__).resolve().parents[3] / "app" / "pii" / "MANIFEST_AUDIT.md"
INJECTION_FIXTURE_ID = "malicious-synthetic-injection-01"

_SYNTHETIC = ev.run_evaluation().dataset(DATASET_SYNTHETIC)
_TEXT = AUDIT.read_text(encoding="utf-8")
# Prose is asserted against a whitespace-flattened copy: the document is hard
# wrapped, so a phrase that crosses a line break is the same sentence to a reader
# and a different string to `in`.
_FLAT = re.sub(r"\s+", " ", _TEXT)


def _evaluation(fixture_id: str) -> ev.FixtureEvaluation:
    for evaluation in _SYNTHETIC.evaluations:
        if evaluation.id == fixture_id:
            return evaluation
    raise AssertionError(f"no committed fixture {fixture_id!r}")


# ---------------------------------------------------------------------------
# F1 — filed, not applied
# ---------------------------------------------------------------------------


def test_the_audit_records_f1_as_pending_and_keeps_the_flip_unapplied():
    """Both halves, in one test, because either half alone is a bug.

    Deleting the finding would let the corpus be described as measuring precision.
    Applying the flip would change the manifest's ground truth, which the Phase 2
    review ruled is neither an evaluation decision nor a detector one — it is a
    product ruling handed off to Phase 5.
    """
    assert "### F1 —" in _TEXT
    assert "`PENDING_GROUND_TRUTH_RULING`. Not applied — ruled in Phase 2 review." in _TEXT
    assert "F1" in _TEXT.split("## Findings index")[1], "F1 must appear in the findings index"
    assert "ticket_number" in _evaluation(INJECTION_FIXTURE_ID).fixture.expected_categories


def test_f1_is_routed_to_the_phase_five_hand_off_as_a_ground_truth_decision():
    """The routing is part of the ruling, and the two decision classes stay separate.

    The plan's Phase 5 acceptance counts **two** `PENDING_PRODUCT_DECISION` items
    — Finding C and the `AGE`/`EXTERNAL_LLM` trade — and both are policy questions.
    F1 is filed under its own disposition so a third item cannot quietly appear
    under a token that means "a rule is in or out": it means "this corpus's ground
    truth is wrong", which only the corpus's owner can rule on.
    """
    body = _FLAT.split("## Findings index")[0]
    f1 = body.split("### F1 —", 1)[1].split("### F2 —", 1)[0]
    assert "handed off as a product ruling in **Phase 5**" in f1
    assert "not an evaluation decision and not a detector decision" in f1
    assert "rather than as a third `PENDING_PRODUCT_DECISION`" in f1
    # The policy token must not be attached to F1 itself.
    assert "`PENDING_PRODUCT_DECISION`" not in f1.split("rather than as a third")[0]
    index = _TEXT.split("## Findings index")[1]
    assert "`PENDING_GROUND_TRUTH_RULING`" in index
    assert "Phase 5" in index


def test_the_injection_fixture_still_declares_the_known_ticket_claim():
    """The exact shape F1 objects to, named in the manifest's own vocabulary.

    A credential, a prompt-injection attempt, no ticket number — and
    `ticket_number` in `expected_categories` anyway, because
    `test_manifest_verification.py` asserts set equality between the chain's
    output and this list. If the label ever leaves, this test fails and the
    failure says why: a ruling was required first.
    """
    fixture = _evaluation(INJECTION_FIXTURE_ID).fixture
    assert "secret" in fixture.expected_categories
    assert "ticket_number" in fixture.expected_categories
    assert fixture.expected_detector_source["ticket_number"] == ("pattern",)


def test_the_committed_corpus_reports_no_false_positive_claim():
    """The tautology, pinned so it cannot be quoted as a precision figure.

    Every finding the chain produces is in the manifest by construction, so this
    number is 0 whatever the detector does — and stays 0 if the detector's only
    error is *missing* something, because a miss is not a claim. The audit's rule
    is therefore explicit: no number in a PII report may be described as a
    precision figure for the committed corpus while F1 is pending.
    """
    attribution = _SYNTHETIC.detector_attribution
    assert attribution.false_positive_claims == 0
    assert all(metrics.fp == 0 for metrics in attribution.per_detector.values())
    assert all(metrics.precision == 1.0 for metrics in attribution.per_source.values())
    assert "not** a precision measurement" in _TEXT or "is not** a precision" in _TEXT


def test_the_corrected_numbers_f1_publishes_are_the_ones_the_manifest_would_produce():
    """The audit states what the corrected metrics *would* be; this checks the arithmetic.

    A projection in an audit is a claim about the future, and a wrong projection
    is worse than none: it is the number a reviewer would expect to see after the
    flip and would then spend a phase hunting for the discrepancy. Two units are
    in play and conflating them is the mistake the table is written to prevent —
    the category metric counts **rows** (the injection fixture's two boundaries
    both go spurious) while the attribution counts **claims** (one false positive,
    because a finding is detected once).
    """
    attribution = _SYNTHETIC.detector_attribution
    category = _SYNTHETIC.category_metrics.per_category["ticket_number"]
    structured = attribution.per_detector["structured.ticket_number.labelled"]
    pattern = attribution.per_detector["pattern.ticket_number.long_digits"]
    # Current state: the two labelled claims plus the one pattern claim, all counted.
    assert (category.tp, category.fp, category.support) == (5, 0, 5)
    assert (structured.tp, structured.fp) == (2, 0)
    assert (pattern.tp, pattern.fp) == (1, 0)

    # The projection, quoted from the document rather than recomputed.
    assert "| `ticket_number` category tp / fp (per boundary row) | 5 / 0 | **3 / 2** |" in _FLAT
    assert (
        "| `pattern.ticket_number.long_digits` tp / fp (per claim) | 1 / 0 | **0 / 1** |" in _FLAT
    )
    assert "| `false_positive_claims` | 0 | **1** |" in _FLAT
    assert "| `exact_set_match` | 10/10 | **8/10** |" in _FLAT
    assert "| band `0.00-0.70` | 3/3 | **2/3** |" in _FLAT
    # The two figures the flip must not disturb, stated so their absence is noticed.
    assert "| `subset_recall` | 10/10 | 10/10 |" in _FLAT
    assert "2 / 0 | unaffected" in _FLAT


# ---------------------------------------------------------------------------
# the audit covers every committed entry
# ---------------------------------------------------------------------------


def test_every_entry_cites_its_provenance():
    """Three entries invented outright, three derived — and the audit says which.

    A derived fixture must name the layout it was shaped from, and an invented one
    must *not* claim a derivation it never had. Both directions are provenance
    claims, and a false one is the failure this audit exists to prevent.
    """
    derived = {
        fixture.id: fixture.derived_from
        for fixture in iter_synthetic_fixtures()
        if fixture.derived_from
    }
    assert set(derived) == {
        "appointment-synthetic-registration-01",
        "appointment-synthetic-registration-note-01",
        "laboratory-synthetic-analysis-note-01",
    }
    for fixture_id, source in derived.items():
        assert source, f"{fixture_id} derives from a layout and must say which"
        assert f"`{fixture_id}`" in _TEXT, f"{fixture_id} is missing from the audit table"
    invented = {f.id for f in iter_synthetic_fixtures()} - set(derived)
    assert invented == {
        "clean-generic-notice-01",
        "patient-synthetic-consultation-01",
        INJECTION_FIXTURE_ID,
    }
    assert "carry no `derived_from`" in _TEXT


def test_the_audit_table_has_a_verdict_for_every_committed_entry():
    """6 entries, 6 rows, and every row's verdict cell is a real disposition.

    `CONFIRM` and `PENDING_GROUND_TRUTH_RULING` are the only dispositions the audit
    grammar allows, so a free-text verdict would let a row quietly stop being a
    verdict. The check is per row rather than a count, because a count of six
    would also be satisfied by six rows for five fixtures and one duplicate.
    """
    rows = {
        line.split("|")[1].strip().strip("`"): line
        for line in _TEXT.splitlines()
        if line.startswith("| `") and line.count("|") >= 7
    }
    for fixture in iter_synthetic_fixtures():
        row = rows.get(fixture.id)
        assert row is not None, f"{fixture.id} has no row in the audit table"
        assert fixture.file in row
        verdict = row.split("|")[5]
        assert "CONFIRM" in verdict or "PENDING_GROUND_TRUTH_RULING" in verdict, verdict
    # The row that is not a plain CONFIRM says so in the same cell.
    assert "PENDING" in rows[INJECTION_FIXTURE_ID].split("|")[5] or "see F1" in rows[
        INJECTION_FIXTURE_ID
    ].split("|")[5]


def test_the_audit_states_the_measurement_baseline_it_was_written_against():
    """Versions and counts, so a future reader knows when the numbers are stale.

    The audit quotes measured figures (20 findings, 11 categories, 6 fixtures, 10
    boundary rows) and pins the three versions they came from. A detector bump
    invalidates the confidence table in F4, and the version line is what makes
    that visible instead of assumed.
    """
    assert "`DETECTOR_VERSION` `1.2.0`" in _TEXT
    assert "`PII_POLICY_VERSION` `3.0.0`" in _TEXT
    assert "`EVALUATION_VERSION` `1.1.0`" in _TEXT
    assert "6 fixtures / 10 boundary rows / 20 findings / 11 observed categories" in _FLAT
    assert (ev.EVALUATION_VERSION, ev.DETECTOR_VERSION, ev.PII_POLICY_VERSION) == (
        "1.1.0",
        "1.2.0",
        "3.0.0",
    )


# ---------------------------------------------------------------------------
# F8 — a taxonomy gap is recorded, not closed
# ---------------------------------------------------------------------------


def test_no_diagnosis_category_was_added_to_escape_f8():
    """The audit says a diagnosis is the most sensitive unmasked field; adding a
    member inside M6 would contradict that without a policy row and a mask row.

    `PIICategory` has 23 members and none of them names a clinical finding. The
    assertion is a count plus a name check rather than a full snapshot, so a later
    member added *with* its policy and mask rows does not break this test — only
    one added to quiet a finding does.
    """
    assert len(PIICategory) == 23
    values = {category.value for category in PIICategory}
    assert not values & {"diagnosis", "clinical_finding", "interpretation", "complaint"}
    assert "F8" in _TEXT
    assert "Out of M6's scope" in _TEXT


# ---------------------------------------------------------------------------
# the document's own internal consistency
# ---------------------------------------------------------------------------


def test_every_indexed_finding_has_a_section():
    """The index is derived from the body, not maintained beside it.

    A finding that exists only in the index is invisible to a reader of the body,
    and Phase 3 cites findings by number — so a number with no section would send a
    calibration change after a heading that does not exist.
    """
    body = _TEXT.split("## Findings index")[0]
    index = _TEXT.split("## Findings index")[1]
    indexed = set(re.findall(r"\*\*(F\d+)\*\*", index))
    headed = set(re.findall(r"^### (F\d+) —", body, flags=re.MULTILINE))
    assert indexed == headed
    assert indexed == {f"F{number}" for number in range(1, len(indexed) + 1)}


def test_every_measurement_decision_names_the_count_it_changes():
    """D1–D4 exist because a unit choice is invisible until it is wrong.

    A decision recorded without the number it moved is a decision nobody can
    check, and D1's whole content is that a number *was* moved — 20 claims read as
    33 — so it has to be the number in the document, not a summary of one.
    """
    decisions = re.findall(r"\*\*(D\d+) — ([^*]+)\*\*", _TEXT)
    assert [number for number, _ in decisions] == ["D1", "D2", "D3", "D4"]
    assert "**20 claims as 33**" in _TEXT
    assert "18" in _TEXT
    assert "5** of 6" in _TEXT
    assert "no `fn`" in _TEXT


def test_d4_records_the_ruling_and_where_a_miss_is_actually_counted():
    """The divergence is settled, and settled with its reasoning attached.

    A reader who finds "per-detector attribution has no `fn`" six months from now
    has to be able to see that it was a decision rather than an omission, and that
    the miss is published rather than dropped. The distinction the ruling rests on
    is the one the table spells out: `CategoryMetrics.fn` is the **count**,
    `missed_category_document` is the **document rate**, and neither is a per-rule
    figure — "covered by `missed_category_document`" is true of the document-level
    view and not of the count.
    """
    d4 = _TEXT.split("**D4 — ", 1)[1].split("## Findings", 1)[0]
    assert "Ruled in Phase 2 review: the divergence is accepted as delivered." in _FLAT
    assert "a miss has no claimant" in d4
    assert "| `CategoryMetrics.fn` | the count, per category |" in _FLAT
    assert "| `DomainRates.missed_category_document` | the rate, per document |" in _FLAT
    # And the model really does carry no per-detector false-negative field.
    attribution = _SYNTHETIC.detector_attribution
    assert not any(
        hasattr(metrics, "fn")
        for metrics in (*attribution.per_detector.values(), *attribution.per_source.values())
    )
    assert set(attribution.per_detector["pattern.ticket_number.long_digits"].model_dump()) == {
        "detector",
        "tp",
        "fp",
        "claimed",
        "precision",
    }


def test_the_audit_records_why_the_local_manifest_is_not_here_yet():
    """Phase 3 owns the local corpus; the obligation is recorded before it exists.

    The plan audits both manifests, and the local one does not exist in this
    phase. Recording the obligation — no raw values, provenance required,
    `expected_decision` documented and not asserted — is what keeps "we will do it
    later" from becoming "we forgot".
    """
    section = _TEXT.split("## The local real corpus manifest")[1].split("## Findings index")[0]
    assert "Phase 3" in section
    assert "no raw PII values anywhere" in section
    assert "`provenance` **required**" in section
    assert "**documented, not asserted**" in section


def test_the_audit_names_the_two_contours_and_their_two_boundary_counts():
    """The corpus is not one shape: 4 markdown documents at 2 boundaries each and
    2 canonical payloads at 1, which is 10 rows — and why every rate in the report
    publishes its denominator beside itself rather than as a bare percentage."""
    documents = [e for e in _SYNTHETIC.evaluations if e.contour != CONTOUR_CANONICAL]
    payloads = [e for e in _SYNTHETIC.evaluations if e.contour == CONTOUR_CANONICAL]
    assert (len(documents), len(payloads)) == (4, 2)
    assert sum(len(e.boundaries) for e in documents) == 8
    assert sum(len(e.boundaries) for e in payloads) == 2
    assert _SYNTHETIC.domain_rates.boundaries == 10
    assert "4 `marker.md`, 2 `canonical.json`" in _TEXT
    assert all(evaluation.dataset == DATASET_SYNTHETIC for evaluation in _SYNTHETIC.evaluations)
