"""Phase 2: the multi-label metric layer, against hand-built sets with exact fractions.

Phase 1's `test_evaluate.py` checks the harness against the committed corpus. That
is a canary — it proves nothing is *wrong*, but it cannot prove anything is
*right* about the arithmetic, because every fixture currently scores 1.0 on every
rate. The tests here are the other half: tiny synthetic corpora with counts chosen
so each expected number is a fraction you can check by hand.

**Why hand-built sets and not fixtures on disk.** A metric tested only against a
corpus that scores perfectly is a metric whose bugs are all zero-shaped: a
denominator dropped, a macro average that divides by the taxonomy size instead of
the observed count, a claim counted once per boundary instead of once per
fixture — each of those produces exactly the right answer here. The first two
bugs of that list were written and shipped inside this harness before these tests
existed. So the mini sets below are built to be *wrong* in the interesting ways,
and the expected values are written as fractions (``4/5``, ``8/15``) rather than
as decimals, so a reader can see the arithmetic rather than trust it.

**Category values are real.** `PIICategory` is an enum and `combination_trip`
raises on a value outside it — deliberately, since an unknown category means the
detector emitted something the taxonomy does not contain and a measurement layer
that shrugged at it would publish a number about it anyway. The builders
therefore name real categories and use corpus shape (which categories, how many
rows, which layer claimed them) as the only free variables.

**Corpus blindness is asserted here too, and not only in `test_dataset_isolation`.**
Each Phase 2 reduction is handed the *same* records under two different `dataset`
labels and required to return identical objects, because a corpus-aware
precision figure is the precise failure the M6 kickoff ruling rules out: it would
run only where `PII_FIXTURES_DIR` is set, so CI would never see it.
"""

from __future__ import annotations

import pytest
from app.pii import evaluate as ev
from app.pii.evaluate import (
    BOUNDARY_DOCUMENT_EXTERNAL,
    BOUNDARY_DOCUMENT_INTERNAL,
    ClaimDetail,
    CountRate,
    DatasetEvaluation,
    EvaluationReport,
    FixtureEvaluation,
    compute_category_metrics,
    compute_confidence_stats,
    compute_detector_attribution,
    compute_domain_rates,
    run_evaluation,
)
from app.pii.fixtures import (
    CONTOUR_DOCUMENT,
    DATASET_REAL_CORPUS,
    DATASET_SYNTHETIC,
    PIIFixture,
)
from app.pii.models import PIICategory

_REPORT = run_evaluation()
_SYNTHETIC = _REPORT.dataset(DATASET_SYNTHETIC)


# ---------------------------------------------------------------------------
# builders — enough shape to satisfy the models, nothing the metrics read
# ---------------------------------------------------------------------------


def _fixture(
    fixture_id: str,
    expected: tuple[str, ...],
    rows,
    *,
    detector_source: dict[str, tuple[str, ...]] | None = None,
    findings: tuple[ClaimDetail, ...] = (),
    dataset: str = DATASET_SYNTHETIC,
    contour: str = CONTOUR_DOCUMENT,
) -> FixtureEvaluation:
    return FixtureEvaluation(
        dataset=dataset,
        fixture=PIIFixture(
            id=fixture_id,
            file=f"{fixture_id}.md",
            path=ev.SYNTHETIC_FIXTURES_DIR / f"{fixture_id}.md",
            contour=contour,
            dataset=dataset,
            source="synthetic",
            expected_categories=expected,
            expected_decision="allow",
            expected_detector_source=detector_source or {},
        ),
        boundaries=tuple(rows),
        finding_details=findings,
    )


def _row(
    predicted: tuple[str, ...],
    *,
    boundary: str = BOUNDARY_DOCUMENT_EXTERNAL,
    over_redacted: tuple[str, ...] = (),
) -> ev.BoundaryEvaluation:
    """A row whose expected set is stamped on by :func:`_corpus` below.

    ``expected_categories`` is left empty here: ``evaluate_fixture`` copies the
    fixture's ground truth onto each of its rows in production, and repeating it in
    every builder call would let a test that forgot one pass for the wrong reason.
    """
    return ev.BoundaryEvaluation(
        boundary=boundary,
        stage="document",
        destination="external_llm",
        expected_categories=(),
        expected_decision="allow",
        predicted_categories=tuple(sorted(predicted)),
        decision="allow",
        risk_level="low",
        over_redacted=over_redacted,
    )


def _corpus(*fixtures: FixtureEvaluation) -> list[FixtureEvaluation]:
    """Stamp each fixture's ground truth onto its rows and return the corpus."""
    return [
        FixtureEvaluation(
            dataset=fixture.dataset,
            fixture=fixture.fixture,
            boundaries=tuple(
                ev.BoundaryEvaluation(
                    **{**row.__dict__, "expected_categories": fixture.fixture.expected_categories}
                )
                for row in fixture.boundaries
            ),
            finding_details=fixture.finding_details,
        )
        for fixture in fixtures
    ]


def _claim(category: str, detector: str, source: str, confidence: float) -> ClaimDetail:
    return ClaimDetail(
        category=category, detector=detector, source=source, confidence=confidence
    )


def _assert_rate(rate: CountRate, count: int, expected: float) -> None:
    """Compare a :class:`CountRate` field by field.

    The models are pydantic and validate on construction, so a
    ``CountRate(count=1, rate=pytest.approx(1/3))`` comparison is a
    ``ValidationError`` rather than a comparison — the fraction has to stay in the
    assertion, where a reader can check it.
    """
    assert rate.count == count
    assert rate.rate == pytest.approx(expected)


# ---------------------------------------------------------------------------
# per-category precision / recall / F1
# ---------------------------------------------------------------------------

# Three rows, chosen so every category lands in a different corner of the
# confusion matrix: `email` is always right, `phone` is half-missed, `inn` is
# always missed, `snils` is right once, and `passport` is invented once.
_MIXED = _corpus(
    _fixture("mixed-1", ("email", "phone"), [_row(("email", "phone"))]),
    _fixture("mixed-2", ("email", "inn", "phone"), [_row(("email",))]),
    _fixture("mixed-3", ("snils",), [_row(("passport", "snils"))]),
)


def test_per_category_counts_are_multi_label_and_stay_per_category():
    metrics = compute_category_metrics(_MIXED).per_category
    # email: expected and claimed on two rows.
    assert (metrics["email"].tp, metrics["email"].fp, metrics["email"].fn) == (2, 0, 0)
    assert metrics["email"].support == 2
    assert metrics["email"].precision == 1.0
    assert metrics["email"].recall == 1.0
    assert metrics["email"].f1 == 1.0
    # phone: expected on two rows, claimed on one -> recall 1/2.
    assert (metrics["phone"].tp, metrics["phone"].fp, metrics["phone"].fn) == (1, 0, 1)
    assert metrics["phone"].support == 2
    assert metrics["phone"].precision == 1.0
    assert metrics["phone"].recall == pytest.approx(1 / 2)
    assert metrics["phone"].f1 == pytest.approx(2 / 3)
    # inn: expected once, never claimed -> precision 0.0 with a *real* denominator.
    assert (metrics["inn"].tp, metrics["inn"].fp, metrics["inn"].fn) == (0, 0, 1)
    assert (metrics["inn"].precision, metrics["inn"].recall, metrics["inn"].f1) == (0.0, 0.0, 0.0)
    # passport: claimed once, expected nowhere -> support 0, which is why it averages alone.
    assert (metrics["passport"].tp, metrics["passport"].fp, metrics["passport"].fn) == (0, 1, 0)
    assert metrics["passport"].support == 0


def test_a_multi_label_row_contributes_one_tp_to_each_category_and_nothing_else():
    """The denominators are the reason single-label accuracy is unusable here.

    One row, two categories expected, two claimed. Neither category is
    ``predicted / |expected|`` of anything, and the row adds one tp to two
    categories rather than one prediction to one label — a corpus of such rows
    scored as single-label would report 50% while missing nothing.
    """
    metrics = compute_category_metrics(
        _corpus(_fixture("one-row", ("email", "phone"), [_row(("email", "phone"))]))
    )
    assert metrics.per_category["email"].support == 1
    assert metrics.per_category["phone"].support == 1
    assert sum(m.tp + m.fp for m in metrics.per_category.values()) == 2
    assert sum(m.fn for m in metrics.per_category.values()) == 0
    assert metrics.micro.precision == 1.0


def test_micro_pools_every_claim_and_macro_weights_every_category_equally():
    metrics = compute_category_metrics(_MIXED)
    # Σtp = 4, Σfp = 1, Σfn = 2, so micro P = 4/5 and micro R = 4/6.
    assert (metrics.micro.precision, metrics.micro.recall) == pytest.approx((4 / 5, 4 / 6))
    assert metrics.micro.f1 == pytest.approx(8 / 11)
    # macro over five observed categories: P = 3/5, R = 1/2, F1 = (1 + 2/3 + 0 + 1 + 0)/5.
    assert (metrics.macro.precision, metrics.macro.recall) == pytest.approx((3 / 5, 1 / 2))
    assert metrics.macro.f1 == pytest.approx(8 / 15)
    assert metrics.categories == 5
    assert metrics.boundaries == 3


def test_micro_and_macro_disagree_and_that_is_the_point():
    """The single most common way to read a P/I/F1 table wrongly.

    Micro precision here is 4/5 against macro's 3/5: ``email`` was right twice and
    carries the average, while two of five categories are worse than it. A report
    quoting micro alone would describe a detector that is uniformly good.
    """
    metrics = compute_category_metrics(_MIXED)
    assert metrics.micro.precision > metrics.macro.precision


def test_a_category_nobody_exercised_is_absent_rather_than_a_zero():
    """Taxonomy size must not dilute the average.

    ``PIICategory`` has 23 members and this corpus touches five. If a silent
    category entered the table, macro would divide by 23 and a rule that never
    fires anywhere would read as a badly-scoring one — the opposite of what a
    coverage gap is.
    """
    metrics = compute_category_metrics(_MIXED)
    exercised = {category.value for category in PIICategory}
    assert len(exercised) == 23
    assert exercised - set(metrics.per_category)
    assert set(metrics.per_category) <= exercised
    assert metrics.categories == len(metrics.per_category) == 5


def test_category_metrics_of_an_empty_corpus_are_zeros_not_an_error():
    metrics = compute_category_metrics(())
    assert (metrics.boundaries, metrics.categories, metrics.per_category) == (0, 0, {})
    assert (metrics.macro.precision, metrics.macro.recall, metrics.macro.f1) == (0.0, 0.0, 0.0)
    assert (metrics.micro.precision, metrics.micro.recall, metrics.micro.f1) == (0.0, 0.0, 0.0)


def test_category_metrics_count_one_row_per_boundary_not_one_per_fixture():
    """The denominator is stated, so a reader is never left to guess it.

    A document evaluated at two boundaries contributes two rows, and each row is a
    separate observation of the same category set. Collapsing the rows would hide a
    boundary-specific recall difference; counting the document twice per category
    would inflate every support figure in a document corpus relative to a payload
    corpus of the same findings, which is not a fact about either.
    """
    metrics = compute_category_metrics(
        _corpus(
            _fixture(
                "two-boundaries",
                ("snils",),
                [_row(("snils",), boundary=BOUNDARY_DOCUMENT_INTERNAL), _row(("snils",))],
            )
        )
    )
    assert metrics.boundaries == 2
    assert metrics.per_category["snils"].tp == 2
    assert metrics.per_category["snils"].support == 2


# ---------------------------------------------------------------------------
# domain rates
# ---------------------------------------------------------------------------


def test_domain_rates_publish_each_denominator_next_to_its_rate():
    corpus = _corpus(
        _fixture(
            "over-fires",
            ("email",),
            [_row(("email", "phone"), boundary=BOUNDARY_DOCUMENT_INTERNAL), _row(("email",))],
        ),
        _fixture("misses", ("inn",), [_row(())]),
        _fixture("clean", ("snils",), [_row(("snils",))]),
    )
    domain = compute_domain_rates(corpus)
    assert (domain.fixtures, domain.boundaries) == (3, 4)
    assert domain.category_observations == 3
    _assert_rate(domain.false_positive_document, 1, 1 / 3)
    _assert_rate(domain.missed_category_document, 1, 1 / 3)
    _assert_rate(domain.combination_trip, 0, 0.0)
    _assert_rate(domain.over_redacted, 0, 0.0)


def test_a_boundary_local_over_fire_counts_once_per_fixture_not_once_per_row():
    """The halt rate is quoted per document, so it has to be counted per document.

    One fixture over-fires at its internal boundary only. Counting rows would
    publish 1-of-4 for the same three documents, and the two numbers would
    disagree about the same corpus.
    """
    domain = compute_domain_rates(
        _corpus(
            _fixture(
                "over-fires-at-one-boundary",
                ("email",),
                [_row(("email", "phone"), boundary=BOUNDARY_DOCUMENT_INTERNAL), _row(("email",))],
            )
        )
    )
    _assert_rate(domain.false_positive_document, 1, 1.0)
    assert domain.boundaries == 2


def test_over_redaction_is_counted_per_category_never_per_document_or_row():
    """The R7 metric, and the unit that makes it visible.

    ``passport`` is masked although no detector claimed it — a field destroyed
    without evidence. Counted per document that is one document out of three and
    shares a rate with two documents that were fine; counted per row it is 2 of 4
    and would read as a boundary difference. Counted per category over the
    ground truth's 6 category observations, it is the 1/6 it is: one field the
    corpus was supposed to carry, and a rule threw it away.
    """
    corpus = _corpus(
        _fixture(
            "masked-at-one-boundary",
            ("email", "phone"),
            [
                _row(("email", "phone"), over_redacted=("passport",)),
                _row(("email", "phone"), boundary=BOUNDARY_DOCUMENT_INTERNAL),
            ],
        ),
        _fixture(
            "masked-at-both",
            ("inn", "snils"),
            [
                _row(("inn", "snils"), over_redacted=("passport",)),
                _row(
                    ("inn", "snils"),
                    boundary=BOUNDARY_DOCUMENT_INTERNAL,
                    over_redacted=("passport",),
                ),
            ],
        ),
    )
    domain = compute_domain_rates(corpus)
    assert domain.category_observations == 4
    _assert_rate(domain.over_redacted, 2, 1 / 2)
    # A category masked at one boundary and one masked at both are one masked
    # category each, not one and two.
    assert domain.false_positive_document.count == 0
    assert domain.missed_category_document.count == 0


def test_a_clean_corpus_reports_no_over_redaction_at_all():
    """Today this is structurally zero, and publishing it is the point.

    The policy engine only issues an action for a category a detector found, so a
    non-zero figure means an override reached a category nothing detected. A test
    that would only notice such a rule *removing* the masking would not be a test
    of this metric, and the committed corpus cannot supply one.
    """
    domain = compute_domain_rates(_MIXED)
    assert domain.over_redacted.count == 0
    assert domain.category_observations == 6


def test_combination_trip_asks_the_locked_rule_table_not_a_reason_string():
    """One fixture carrying the §4.13 pair trips; one identifier alone does not.

    The measurement goes through ``PIICombinationRule.matches`` — the engine's own
    predicate over the engine's own table. Keying a metric on the prose the engine
    writes into ``reasons`` would break the day that sentence is reworded, and it
    would break silently, on a rate whose whole purpose is to be quoted.
    """
    corpus = _corpus(
        _fixture(
            "government-pair",
            ("insurance_number", "snils"),
            [
                _row(("insurance_number", "snils"), boundary=BOUNDARY_DOCUMENT_INTERNAL),
                _row(("insurance_number", "snils")),
            ],
        ),
        _fixture(
            "government-singleton",
            ("snils",),
            [
                _row(("snils",), boundary=BOUNDARY_DOCUMENT_INTERNAL),
                _row(("snils",)),
            ],
        ),
    )
    _assert_rate(compute_domain_rates(corpus).combination_trip, 1, 1 / 2)


def test_a_blocking_secret_does_not_hide_the_combination_trip():
    """The rule fired; the ``BLOCK`` outranked it.

    ``_decide`` puts ``BLOCK`` above the combination escalation, so a document with
    a credential *and* two government identifiers is blocked rather than reviewed.
    The trip still happened and still has to be counted — otherwise a document
    that trips two rules at once would report one.
    """
    corpus = _corpus(
        _fixture(
            "secret-and-government",
            ("insurance_number", "secret", "snils"),
            [_row(("insurance_number", "secret", "snils"))],
        )
    )
    assert compute_domain_rates(corpus).combination_trip.count == 1


def test_combination_trip_raises_on_a_category_outside_the_taxonomy():
    """A measurement layer that shrugged at an unknown category would lie about it.

    ``PIICategory`` is an enum, so a value outside it means a detector emitted
    something the taxonomy does not contain. Every other layer here either reports
    the string verbatim or counts it; this one asks the engine's own rule table
    whether the pair is a combination, and the honest answer to a category it
    cannot name is to fail rather than to report 0.0 trips.
    """
    row = ev.BoundaryEvaluation(
        boundary=BOUNDARY_DOCUMENT_EXTERNAL,
        stage="document",
        destination="external_llm",
        expected_categories=(),
        expected_decision="allow",
        predicted_categories=("not_a_category",),
        decision="allow",
        risk_level="low",
    )
    with pytest.raises(ValueError, match="not_a_category"):
        assert row.combination_trip is False


def test_domain_rates_of_an_empty_corpus_are_zeros():
    domain = compute_domain_rates(())
    assert (domain.fixtures, domain.boundaries, domain.category_observations) == (0, 0, 0)
    _assert_rate(domain.false_positive_document, 0, 0.0)
    _assert_rate(domain.over_redacted, 0, 0.0)


# ---------------------------------------------------------------------------
# detector attribution
# ---------------------------------------------------------------------------


def _attribution_corpus() -> list[FixtureEvaluation]:
    return _corpus(
        _fixture(
            "address-two-layers",
            ("address",),
            [_row(("address",)), _row(("address",), boundary=BOUNDARY_DOCUMENT_INTERNAL)],
            detector_source={"address": ("pattern", "structured_field")},
            findings=(
                _claim("address", "structured.address.labelled", "structured_field", 0.90),
                _claim("address", "pattern.address.locality", "pattern", 0.60),
            ),
        ),
        _fixture(
            "organization-id-mistaken-for-a-ticket",
            ("organization_id",),
            [_row(("organization_id", "ticket_number"))],
            detector_source={"organization_id": ("structured_field",)},
            findings=(
                _claim(
                    "organization_id",
                    "structured.organization_id.labelled",
                    "structured_field",
                    0.95,
                ),
                _claim("ticket_number", "pattern.ticket_number.long_digits", "pattern", 0.60),
            ),
        ),
        _fixture(
            "silent-structured-layer",
            ("snils",),
            [_row(("snils",)), _row(("snils",), boundary=BOUNDARY_DOCUMENT_INTERNAL)],
            detector_source={"snils": ("structured_field",)},
            findings=(_claim("snils", "pattern.snils.digits", "pattern", 0.70),),
        ),
    )


def test_detector_attribution_splits_claims_into_tp_and_fp_per_rule():
    attribution = compute_detector_attribution(_attribution_corpus())
    assert attribution.per_detector["structured.address.labelled"].tp == 1
    assert attribution.per_detector["pattern.address.locality"].tp == 1
    # 5 claims, one of them wrong.
    assert attribution.false_positive_claims == 1
    assert sum(m.claimed for m in attribution.per_detector.values()) == 5
    ticket = attribution.per_detector["pattern.ticket_number.long_digits"]
    assert (ticket.tp, ticket.fp, ticket.claimed, ticket.precision) == (0, 1, 1, 0.0)
    assert attribution.per_detector["structured.address.labelled"].precision == 1.0


def test_claims_are_counted_once_per_fixture_not_once_per_boundary_row():
    """The regression pin for a bug this layer shipped with.

    A document is detected once and decided at both of its boundaries. Counting
    claims inside the per-row loop reported this corpus's 5 claims as 8, and the
    committed corpus's 20 as 33 — so ``false_positive_claims``, the number Finding
    B has to move, scaled with how many boundaries a contour happened to have
    rather than with how many claims were wrong. The committed corpus hid it
    completely, because every claim there is correct and ``2 * 0 == 0``.
    """
    attribution = compute_detector_attribution(_attribution_corpus())
    assert sum(m.claimed for m in attribution.per_detector.values()) == 5
    assert sum(m.claimed for m in attribution.per_source.values()) == 5
    single = _corpus(
        _fixture(
            "one-boundary",
            ("address",),
            [_row(("address",))],
            findings=(_claim("address", "pattern.address.locality", "pattern", 0.60),),
        )
    )
    two = _corpus(
        _fixture(
            "two-boundaries",
            ("address",),
            [_row(("address",)), _row(("address",), boundary=BOUNDARY_DOCUMENT_INTERNAL)],
            findings=(_claim("address", "pattern.address.locality", "pattern", 0.60),),
        )
    )
    assert compute_detector_attribution(single) == compute_detector_attribution(two)


def test_per_source_collapses_the_two_address_rules_into_one_layer():
    """Layer granularity is the question the manifest declares and the findings ask.

    ``address`` is claimed twice on one fixture, by two rules in two different
    layers. At rule granularity that is two rows; at layer granularity it is two
    correct claims split across ``pattern`` and ``structured_field``, and the only
    false positive in the corpus belongs to ``pattern`` — which is the shape
    Finding A has to be able to see and per-rule counts alone would hide.
    """
    per_source = compute_detector_attribution(_attribution_corpus()).per_source
    structured = per_source["structured_field"]
    assert (structured.tp, structured.fp, structured.claimed) == (2, 0, 2)
    assert structured.precision == 1.0
    pattern = per_source["pattern"]
    assert (pattern.tp, pattern.fp, pattern.claimed) == (2, 1, 3)
    assert pattern.precision == pytest.approx(2 / 3)


def test_a_silent_declared_layer_is_a_reported_mismatch_not_a_miss_on_some_rule():
    """The machine-checkable form of the finding the plan records as Finding A.

    ``snils`` was expected from ``structured_field`` and was found by ``pattern``
    instead. The category is present, the category metrics are happy, and the
    0.95-confidence layer went silent without a single rate moving. This is the
    only place in the harness where that shows up — and it is the reason
    ``expected_detector_source`` exists.
    """
    attribution = compute_detector_attribution(_attribution_corpus())
    assert attribution.declared_fixtures == 3
    _assert_rate(attribution.source_expectation_mismatches, 1, 1 / 3)
    (miss,) = attribution.source_expectation_details
    assert miss.fixture_id == "silent-structured-layer"
    assert miss.category == "snils"
    assert miss.declared_sources == ("structured_field",)
    assert miss.claiming_sources == ("pattern",)


def test_a_violated_declaration_is_one_miss_per_fixture_not_one_per_boundary():
    """A declaration is made once, by a manifest, about a fixture.

    The silent-layer fixture above has two boundary rows, and the earlier
    implementation emitted a miss for each — so the count was a function of the
    contour rather than of the manifests, and a document corpus would report twice
    the misses of a payload corpus with identical ground truth.
    """
    single = _corpus(
        _fixture(
            "silent",
            ("snils",),
            [_row(("snils",))],
            detector_source={"snils": ("structured_field",)},
            findings=(_claim("snils", "pattern.snils.digits", "pattern", 0.70),),
        )
    )
    two = _corpus(
        _fixture(
            "silent",
            ("snils",),
            [_row(("snils",)), _row(("snils",), boundary=BOUNDARY_DOCUMENT_INTERNAL)],
            detector_source={"snils": ("structured_field",)},
            findings=(_claim("snils", "pattern.snils.digits", "pattern", 0.70),),
        )
    )
    assert compute_detector_attribution(single) == compute_detector_attribution(two)
    assert compute_detector_attribution(two).source_expectation_mismatches.count == 1


def test_a_corpus_that_declares_nothing_has_no_denominator_rather_than_a_zero_rate():
    """Nothing to check is not "checked and passed".

    A rate of 0/0 would print as 0.0%, and a reader would take away that every
    layer fired where the manifest asked — from a manifest that never asked.
    """
    attribution = compute_detector_attribution(
        _corpus(
            _fixture(
                "undeclared",
                ("snils",),
                [_row(("snils",))],
                findings=(_claim("snils", "pattern.snils.digits", "pattern", 0.70),),
            )
        )
    )
    assert attribution.declared_fixtures == 0
    assert attribution.source_expectation_mismatches.count == 0
    assert attribution.source_expectation_mismatches.rate == 0.0
    assert attribution.source_expectation_details == ()


def test_a_category_found_by_nobody_reports_an_empty_claiming_set():
    """The two mismatch shapes are distinguishable from the record alone.

    An empty ``claiming_sources`` is a recall defect — nothing found the category.
    A non-empty set disjoint from ``declared_sources`` is a calibration defect —
    something found it that the manifest did not allow. A reader who cannot tell
    them apart has to go and re-run the corpus to find out.
    """
    corpus = _corpus(
        _fixture(
            "missed-entirely",
            ("inn",),
            [_row(())],
            detector_source={"inn": ("structured_field",)},
        )
    )
    (miss,) = compute_detector_attribution(corpus).source_expectation_details
    assert miss.declared_sources == ("structured_field",)
    assert miss.claiming_sources == ()


def test_a_declaration_satisfied_by_an_extra_layer_is_still_a_miss():
    """The declaration pins the load-bearing layer; it is not a whitelist.

    ``expected_detector_source: {address: [pattern, structured_field]}`` on a
    real layout records that both layers were written for it. If the structured
    layer goes quiet and only the 0.60 pattern rule answers, the category is still
    found and every recall metric is still 1.0 — which is precisely the regression
    this check exists to catch, so it has to fire on the partial answer.
    """
    corpus = _corpus(
        _fixture(
            "one-layer-of-two",
            ("address",),
            [_row(("address",))],
            detector_source={"address": ("pattern", "structured_field")},
            findings=(_claim("address", "pattern.address.locality", "pattern", 0.60),),
        )
    )
    (miss,) = compute_detector_attribution(corpus).source_expectation_details
    assert (miss.declared_sources, miss.claiming_sources) == (
        ("pattern", "structured_field"),
        ("pattern",),
    )


def test_a_satisfied_declaration_reports_no_mismatch():
    corpus = _corpus(
        _fixture(
            "as-declared",
            ("snils",),
            [_row(("snils",))],
            detector_source={"snils": ("structured_field",)},
            findings=(_claim("snils", "structured.snils.labelled", "structured_field", 0.95),),
        )
    )
    attribution = compute_detector_attribution(corpus)
    assert attribution.source_expectation_details == ()
    _assert_rate(attribution.source_expectation_mismatches, 0, 0.0)


def test_an_undeclared_category_does_not_create_a_declaration_to_violate():
    """Only declared categories are checked.

    A manifest that names the sources for seven categories still has others to
    discover; a spurious eighth must not read as a violation of a declaration
    nobody made — and it is already counted as a false positive claim beside this.
    """
    corpus = _corpus(
        _fixture(
            "undeclared-extra",
            ("snils",),
            [_row(("snils", "ticket_number"))],
            detector_source={"snils": ("structured_field",)},
            findings=(
                _claim("snils", "structured.snils.labelled", "structured_field", 0.95),
                _claim("ticket_number", "pattern.ticket_number.long_digits", "pattern", 0.60),
            ),
        )
    )
    attribution = compute_detector_attribution(corpus)
    assert attribution.source_expectation_details == ()
    assert attribution.false_positive_claims == 1


def test_detector_attribution_of_an_empty_corpus_is_empty_not_an_error():
    attribution = compute_detector_attribution(())
    assert (attribution.per_detector, attribution.per_source) == ({}, {})
    assert (attribution.false_positive_claims, attribution.declared_fixtures) == (0, 0)
    assert attribution.source_expectation_details == ()


# ---------------------------------------------------------------------------
# confidence reliability
# ---------------------------------------------------------------------------


def _confidence_corpus() -> list[FixtureEvaluation]:
    """Seven claims placed on and around all three band edges."""
    return _corpus(
        _fixture(
            "bands",
            ("email", "inn", "phone", "snils"),
            [_row(("email", "inn", "phone", "snils"))],
            findings=(
                _claim("email", "rule.email", "structured_field", 1.00),  # top band, inclusive
                _claim("inn", "rule.inn", "structured_field", 0.90),  # 0.90 is in the top band
                _claim("phone", "rule.phone", "structured_field", 0.70),  # 0.70 is in the middle
                _claim("snils", "rule.snils", "pattern", 0.60),  # bottom band
                _claim("secret", "rule.secret", "pattern", 0.95),  # top band, and wrong
                _claim("ticket_number", "rule.ticket", "pattern", 0.69),  # bottom, and wrong
                _claim("age", "rule.age", "pattern", 0.00),  # bottom, and wrong
            ),
        )
    )


def test_band_edges_are_a_partition_and_the_distribution_sums_to_the_findings():
    """The double-count a min-based band would cause is exactly the bug this pins.

    ``confidence_band`` is a row-level *summary* — the band of the lowest claim.
    A distribution needs each claim in one bucket, and the shared edges (0.70,
    0.90) are where a partition and an inclusive range part company.
    """
    stats = compute_confidence_stats(_confidence_corpus())
    assert stats.findings == 7
    assert sum(stats.distribution.values()) == stats.findings
    assert stats.distribution == {"0.90-1.00": 3, "0.70-0.90": 1, "0.00-0.70": 3}


def test_the_partitioner_agrees_with_the_row_level_minimum_band():
    """Two different questions, one answer.

    ``confidence_band([...])`` reports the band of the *weakest* claim in a row;
    ``_band_of`` buckets a single claim. A finding in the top band while its row
    summarises to the bottom one is the normal case, and both readings have to
    place a given confidence in the same bucket or the report contradicts itself.
    """
    assert (ev._band_of(1.0), ev._band_of(0.90), ev._band_of(0.8999)) == (
        "0.90-1.00",
        "0.90-1.00",
        "0.70-0.90",
    )
    assert (ev._band_of(0.70), ev._band_of(0.6999), ev._band_of(0.0)) == (
        "0.70-0.90",
        "0.00-0.70",
        "0.00-0.70",
    )
    for confidence in (0.0, 0.6, 0.7, 0.85, 0.9, 0.95, 1.0):
        assert ev.confidence_band([confidence]) == ev._band_of(confidence)


def test_reliability_is_precision_over_the_bands_claims_with_no_recall_column():
    """The reviewer's question: when the gate says 0.60, how often is it wrong?

    There is no recall per band and there cannot be: a miss has no confidence to
    band. Attributing one would mean picking a band the detector never produced,
    which would make the accuracy column a function of the guess. The top band
    holds two right claims and the 0.95 ``secret`` claim; the bottom holds one
    right claim and two wrong ones — which is the calibration gap the whole table
    exists to show.
    """
    top, middle, bottom = compute_confidence_stats(_confidence_corpus()).reliability
    assert (top.findings, top.correct, top.incorrect) == (3, 2, 1)
    assert top.accuracy == pytest.approx(2 / 3)
    assert (middle.findings, middle.correct, middle.incorrect) == (1, 1, 0)
    assert middle.accuracy == 1.0
    assert (bottom.findings, bottom.correct, bottom.incorrect) == (3, 1, 2)
    assert bottom.accuracy == pytest.approx(1 / 3)
    assert not any(hasattr(band, "recall") for band in (top, middle, bottom))


def test_findings_are_counted_once_even_when_the_document_has_two_boundaries():
    """Detection happens once and the decision is taken twice.

    Counting per row would report every document claim twice, making the
    distribution a function of the boundary count — a document corpus would look
    1.5× more confident than a payload corpus of the same findings, which is not
    a fact about either.
    """
    stats = compute_confidence_stats(
        _corpus(
            _fixture(
                "two-boundaries",
                ("snils",),
                [_row(("snils",)), _row(("snils",), boundary=BOUNDARY_DOCUMENT_INTERNAL)],
                findings=(_claim("snils", "rule.snils", "structured_field", 0.95),),
            )
        )
    )
    assert stats.findings == 1
    assert stats.distribution["0.90-1.00"] == 1
    assert stats.maximum == 0.95


def test_a_finding_with_no_confidence_band_at_all_is_its_own_answer():
    """Zero findings is not low confidence.

    A clean document is reported as band ``none`` rather than folded into
    ``0.00-0.70``, so a corpus of clean documents does not fill its lowest band
    with documents that produced no evidence.
    """
    stats = compute_confidence_stats(_corpus(_fixture("clean", (), [_row(())])))
    assert stats.findings == 0
    assert sum(stats.distribution.values()) == 0
    assert ev.confidence_band([]) == "none"
    assert all(band.findings == 0 for band in stats.reliability)


def test_confidence_stats_of_an_empty_corpus_are_zeros():
    stats = compute_confidence_stats(())
    assert (stats.findings, stats.minimum, stats.maximum, stats.mean) == (0, 0.0, 0.0, 0.0)
    assert set(stats.distribution) == {"0.90-1.00", "0.70-0.90", "0.00-0.70"}
    assert len(stats.reliability) == 3


# ---------------------------------------------------------------------------
# corpus blindness
# ---------------------------------------------------------------------------


def test_every_phase_two_reduction_ignores_the_dataset_label():
    """The M6 hard rule, asserted against the four new reductions.

    ``test_dataset_isolation.py`` guards Phase 1's two by AST. These four are
    asserted behaviourally as well, because the AST guard cannot see a branch
    hidden behind a helper, and because a behavioural test says what the property
    is *for*.
    """
    relabelled = [
        FixtureEvaluation(
            dataset=DATASET_REAL_CORPUS,
            fixture=evaluation.fixture,
            boundaries=evaluation.boundaries,
            finding_details=evaluation.finding_details,
        )
        for evaluation in _SYNTHETIC.evaluations
    ]
    for reduce in (
        compute_category_metrics,
        compute_domain_rates,
        compute_detector_attribution,
        compute_confidence_stats,
    ):
        assert reduce(relabelled) == reduce(_SYNTHETIC.evaluations), reduce.__name__


# ---------------------------------------------------------------------------
# the committed corpus, as measured
# ---------------------------------------------------------------------------


def test_the_committed_corpus_scores_perfectly_on_every_phase_two_metric():
    """The audit's baseline, pinned so a change has to be deliberate.

    All eleven observed categories at F1 1.0, no false-positive claim, no declared
    layer silent. This is the *starting point* Phase 3 calibrates away from — and
    `MANIFEST_AUDIT.md` F1 explains why "perfect" here means the labels were
    measured from the detector rather than that the detector is flawless.
    """
    categories = _SYNTHETIC.category_metrics
    assert categories.categories == 11
    assert (categories.micro.precision, categories.micro.recall) == (1.0, 1.0)
    assert categories.macro.f1 == 1.0
    assert all(m.precision == 1.0 and m.recall == 1.0 for m in categories.per_category.values())

    attribution = _SYNTHETIC.detector_attribution
    assert attribution.false_positive_claims == 0
    assert attribution.source_expectation_details == ()
    assert attribution.declared_fixtures == 5

    domain = _SYNTHETIC.domain_rates
    assert (domain.fixtures, domain.boundaries, domain.category_observations) == (6, 10, 18)
    _assert_rate(domain.combination_trip, 0, 0.0)
    _assert_rate(domain.over_redacted, 0, 0.0)


def test_the_claim_count_equals_the_finding_count_on_the_committed_corpus():
    """20 claims from 20 findings, not 33.

    Four of the six fixtures are two-boundary documents, so the earlier per-row
    accounting inflated the corpus by its document rows. This is the assertion
    that would have caught it, written on the real numbers rather than on a
    synthetic two: it is a one-line invariant — every claim is counted once, and
    claims are findings — and it now guards every fixture added later.
    """
    attribution = _SYNTHETIC.detector_attribution
    assert sum(m.claimed for m in attribution.per_detector.values()) == 20
    assert sum(m.claimed for m in attribution.per_source.values()) == 20
    assert sum(m.claimed for m in attribution.per_detector.values()) == sum(
        m.claimed for m in attribution.per_source.values()
    )
    assert _SYNTHETIC.confidence_stats.findings == 20


def test_the_confidence_bands_over_the_committed_corpus():
    # The numbers `MANIFEST_AUDIT.md` F4 quotes. 20 findings across 6 fixtures:
    # a document's findings are detected once, so this is not 10 rows' worth.
    stats = _SYNTHETIC.confidence_stats
    assert stats.findings == 20
    assert stats.distribution == {"0.90-1.00": 12, "0.70-0.90": 5, "0.00-0.70": 3}
    assert stats.minimum == pytest.approx(0.60)
    assert stats.maximum == pytest.approx(0.95)
    assert all(band.accuracy == 1.0 for band in stats.reliability)


def test_the_structured_layer_is_the_only_layer_without_a_false_positive_claim():
    """The prior Phase 3 is handed, as a measurement rather than an argument.

    Every ``structured_field`` claim on this corpus is correct; the only 0.60
    ``pattern`` claim in the corpus is the ``ОГРН`` read as a ``ticket_number``.
    `MANIFEST_AUDIT.md` F1 records that this claim is *known* wrong but is
    labelled expected (F1) — so ``false_positive_claims == 0`` here is not
    evidence that the pattern layer is clean, and F2 is where that gets fixed.
    """
    per_source = _SYNTHETIC.detector_attribution.per_source
    assert per_source["structured_field"].fp == 0
    assert per_source["structured_field"].claimed == 13
    assert per_source["pattern"].tp == 7
    assert per_source["pattern"].fp == 0


# ---------------------------------------------------------------------------
# rendering and JSON
# ---------------------------------------------------------------------------


def test_the_text_report_prints_the_category_layer():
    text = ev.render_text(_REPORT)
    assert "Per-category metrics (11 categories observed):" in text
    assert "macro" in text and "micro" in text
    assert "Detector attribution (0 false positive claim(s)):" in text
    assert "expected_detector_source mismatches: 0/5 fixture(s) declaring a source" in text
    assert "over-redacted categories 0/18" in text
    assert "Confidence: 20 finding(s)" in text
    assert "0.90-1.00  12/12 correct" in text


def test_the_text_report_names_the_layer_that_missed_a_declaration():
    corpus = _corpus(
        _fixture(
            "silent-structured-layer",
            ("snils",),
            [_row(("snils",))],
            detector_source={"snils": ("structured_field",)},
            findings=(_claim("snils", "pattern.snils.digits", "pattern", 0.70),),
        )
    )
    report = DatasetEvaluation(
        name=DATASET_SYNTHETIC,
        source="local-only",
        available=True,
        root=_SYNTHETIC.root,
        evaluations=tuple(corpus),
    )
    text = ev.render_text(EvaluationReport(datasets=(report,)))
    assert "expected_detector_source mismatches: 1/1 fixture(s) declaring a source" in text
    assert "silent-structured-layer: snils declared [structured_field] claimed [pattern]" in text


def test_the_text_report_says_so_when_nothing_was_a_false_positive():
    empty = DatasetEvaluation(
        name="empty", source="local-only", available=True, root=_SYNTHETIC.root, evaluations=()
    )
    block = "\n".join(ev._dataset_block_lines(empty))
    assert "(none: every detector claim was correct)" in block
    assert "(no category was expected or predicted)" in block


def test_the_markdown_report_carries_all_three_phase_two_tables():
    markdown = ev.render_markdown(_REPORT)
    assert "### Domain rates" in markdown
    assert "| False-positive document | 0 | 6 |" in markdown
    assert "| Combination-rule trip | 0 | 6 |" in markdown
    assert "| Over-redacted category | 0 | 18 |" in markdown
    assert "### Per-category metrics" in markdown
    assert "| **macro** |" in markdown
    assert "### Detector attribution" in markdown
    assert "### Confidence reliability" in markdown
    assert "`0.00-0.70` | 3 | 3 | 0 |" in markdown
    assert "`expected_detector_source` mismatches: 0/5 fixture(s) declaring a source." in markdown


def test_the_markdown_report_states_that_categories_are_multi_label():
    """A reader of an artifact weeks later cannot infer it from the numbers.

    The notes block says the macro/micro averages are not accuracy, so a single
    averaged number in the table cannot be read as one.
    """
    markdown = ev.render_markdown(_REPORT)
    assert "Categories are multi-label" in markdown
    assert "never charged with a false negative against a detector" in markdown


def test_the_json_block_publishes_four_phase_two_keys_and_absent_ones_for_a_missing_corpus(
    monkeypatch,
):
    present = ev._to_json(_REPORT)["datasets"][DATASET_SYNTHETIC]
    for key in (
        "category_metrics",
        "domain_rates",
        "detector_attribution",
        "confidence_stats",
    ):
        assert key in present, key
    assert present["category_metrics"]["categories"] == 11
    assert present["domain_rates"]["combination_trip"]["count"] == 0
    assert present["domain_rates"]["category_observations"] == 18
    assert present["detector_attribution"]["false_positive_claims"] == 0
    assert present["detector_attribution"]["declared_fixtures"] == 5
    assert present["confidence_stats"]["findings"] == 20

    monkeypatch.delenv("PII_FIXTURES_DIR", raising=False)
    absent = ev._to_json(run_evaluation())["datasets"][DATASET_REAL_CORPUS]
    for key in (
        "metrics",
        "summary",
        "category_metrics",
        "domain_rates",
        "detector_attribution",
        "confidence_stats",
    ):
        assert key not in absent, key


def test_the_json_report_carries_each_finding_without_its_value():
    """``finding_details`` is the report's view of a finding, so it must be valueless.

    Not a restatement of `PIIFindingSummary`'s contract — a different consumer, on
    a different path, with a different reason to forget the rule. A ``value`` key
    here would put raw PII in an artifact that is not a boundary-safe type.
    """
    present = ev._to_json(_REPORT)["datasets"][DATASET_SYNTHETIC]
    claims = [
        claim for evaluation in present["evaluations"] for claim in evaluation["finding_details"]
    ]
    assert len(claims) == 20
    for claim in claims:
        assert set(claim) == {"category", "detector", "source", "confidence"}
        assert "value" not in claim
        assert "masked_value" not in claim
        assert "value_fingerprint" not in claim


def test_the_dataset_block_exposes_the_phase_two_layers_as_properties():
    """One reduction per layer, reached the same way by every caller.

    The renderers, the JSON block and the tests all read
    ``dataset.category_metrics`` rather than calling ``compute_*`` themselves, so
    there is no second implementation that could disagree with the table.
    """
    assert _SYNTHETIC.category_metrics == compute_category_metrics(_SYNTHETIC.evaluations)
    assert _SYNTHETIC.domain_rates == compute_domain_rates(_SYNTHETIC.evaluations)
    assert _SYNTHETIC.detector_attribution == compute_detector_attribution(
        _SYNTHETIC.evaluations
    )
    assert _SYNTHETIC.confidence_stats == compute_confidence_stats(_SYNTHETIC.evaluations)
