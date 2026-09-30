"""Deterministic, offline evaluation CLI for the PII gate.

M6 (EVAL_IMPL_PLAN Phase 1). ``python -m app.pii.evaluate`` runs every fixture in
a dataset through the **production** gate chain —
``MarkdownNormalizer -> detectors -> aggregator -> policy -> decision`` — and
compares the outcome against the manifest ground truth. The detectors, the
aggregator and the policy engine are the pipeline's own objects, taken from
:func:`~app.pii.gate.build_document_gate` and
:func:`~app.pii.canonical_guard.build_canonical_guard`; only the *policy context*
is chosen here, because that is the one input the locked ``inspect`` signature
cannot carry and the one thing an evaluation is specifically about.

Two corpora, one evaluator
--------------------------

The dataset boundary is :class:`EvaluationDataset`, and it is at the **top of the
report**, not inside the metrics:

======================  =========================  ====================
dataset                 root                        role
======================  =========================  ====================
``synthetic_regression``  ``tests/fixtures/pii/``    committed, CI
``real_corpus``           ``$PII_FIXTURES_DIR``      local-only, calibration
======================  =========================  ====================

Both produce the same :class:`FixtureEvaluation` record, and
:func:`compute_metrics` / :func:`summarize` take a flat sequence of those records
and never read ``dataset`` — a metrics function that branched on provenance
would make "synthetic recall" and "real recall" the same number wearing two
labels, which is the failure the kickoff ruling was written against. The
provenance is carried *on the record* so a report can print it, and a test
(``test_dataset_isolation.py``) asserts by AST that nothing else looks at it.

Two boundaries, because ``expected_decision`` is destination-dependent
-------------------------------------------------------------------

M4's gap 1 is still open: one manifest cannot state one decision, because the
same findings are ``ALLOW`` at the production boundary, ``REVIEW`` at the
external boundary with no redactor, and ``ALLOW_WITH_WARNING`` for a canonical
payload heading to persistence. So every fixture is evaluated at the boundary its
manifest names **and** at the production one, and contour 2 is a separate pass:

* ``document`` / ``INTERNAL_LLM`` with :data:`~app.pii.gate.REDACTION_AVAILABLE`
  — the production default, and the context
  :func:`~app.pii.gate.build_document_gate` wires from ``Settings.llm_mode``;
* ``document`` / ``EXTERNAL_LLM`` with ``redaction_available=False`` — the
  fail-closed direction every committed ``expected_decision`` was written
  against;
* ``canonical`` / ``PERSISTENCE`` — contour 2, for payloads.

Three rows per document fixture, one per payload, because a report that printed a
single decision column would be wrong at two of the three boundaries and would
not know which one.

What Phase 1 measures, and what Phase 2 adds
--------------------------------------------

This module computes the **document-level** layer: per-boundary ground truth vs
prediction, exact-set match, subset recall (the number that matters — did we find
everything that is there), the spurious and missed category counts, the
per-category ``over_redacted`` set, detector attribution and a confidence band.
Phase 2 layers per-category precision/recall/F1 with macro/micro aggregates, the
four domain rates, per-detector tp/fp/fn and the confidence-reliability table on
top of the same records. The split is a phase boundary, not a design: the records
below carry everything Phase 2 needs and nothing Phase 2 has to recompute.

The one metric with no analogue in the M3 harness is ``over_redacted`` — a
category masked that no detector claimed. It is the tripwire for the R7 class of
bug, where a rule that was never asked about a field destroys it; it is computed
per category rather than per document because ``document_date`` being masked is
invisible at document granularity, which is precisely how that defect shipped.

Determinism and isolation, both structural
------------------------------------------

No LLM, no network, no S3/RabbitMQ/DB, no writes: output goes to stdout,
``--json`` or ``--report``. The fingerprint secret is a module constant, so two
runs over one corpus are byte-identical — and because no fingerprint is ever
*reported*, the secret cannot be a leak from this tool either. The loader reaches
nothing under ``.dev/`` unless ``PII_FIXTURES_DIR`` names it; with the variable
unset the real-corpus block is **absent from the JSON, not zero**, because a
synthesised empty block reads as a measurement of zero.

Prerequisite: run from the ai-worker project directory so ``app`` is on
``sys.path`` (``cd apps/ai-worker && uv run python -m app.pii.evaluate``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from app.classification.normalize import MarkdownNormalizer
from app.config.settings import Settings
from app.pii.canonical_guard import DefaultCanonicalPIIInspector, build_canonical_guard
from app.pii.detectors import DETECTOR_VERSION
from app.pii.fixtures import (
    CONTOUR_CANONICAL,
    CONTOUR_DOCUMENT,
    DATASET_REAL_CORPUS,
    DATASET_SYNTHETIC,
    SYNTHETIC_FIXTURES_DIR,
    PIIFixture,
    iter_canonical_fixtures,
    iter_local_real_corpus,
    iter_pii_fixtures,
    local_real_corpus_available,
    local_real_corpus_dir,
    local_real_corpus_manifest_version,
    local_real_corpus_unavailable_reason,
    synthetic_manifest_version,
)
from app.pii.gate import REDACTION_AVAILABLE, DefaultPIIGate, build_document_gate
from app.pii.models import PIIAction, PIIDecisionResult, PIIDestination, PIIFinding, PIIScanStage
from app.pii.policy import (
    PII_POLICY_VERSION,
    PIIPolicyContext,
    build_policy_context,
)

__all__ = [
    "BOUNDARY_CANONICAL_PERSISTENCE",
    "BOUNDARY_DOCUMENT_EXTERNAL",
    "BOUNDARY_DOCUMENT_INTERNAL",
    "CONFIDENCE_BANDS",
    "BoundaryEvaluation",
    "CountRate",
    "DatasetEvaluation",
    "EVALUATION_VERSION",
    "EvaluationDataset",
    "EvaluationReport",
    "FixtureEvaluation",
    "LocalRealCorpusDataset",
    "PIIMetrics",
    "SummaryMetrics",
    "SyntheticFixtureDataset",
    "compute_metrics",
    "confidence_band",
    "default_datasets",
    "evaluate_dataset",
    "evaluate_fixture",
    "main",
    "render_markdown",
    "render_text",
    "run_evaluation",
    "summarize",
]

EVALUATION_VERSION = "1.0.0"
"""Version of the harness, stamped into every report.

A third constant beside ``DETECTOR_VERSION`` and ``PII_POLICY_VERSION``, and for
their reason: a report is an artifact, an artifact ages, and a reviewer who opens
one has to be able to tell whether it was produced by *this* measurement code or
by the code before it. Detector and policy versions answer "which gate produced
these numbers"; this one answers "which measurement compared them". It is stamped
separately from both, because a harness change moves no decision and would
therefore not license a policy bump.
"""

EVALUATION_FINGERPRINT_SECRET = "pii-eval-offline-fingerprint-secret"
"""Fixed HMAC key for the detector chain, so a run is reproducible.

Not a secret and deliberately not read from the environment: this tool is offline
and reports no fingerprint, so a per-machine key would add non-determinism to
every ``--json`` diff without protecting anything. A real deployment's key comes
from ``Settings.pii_fingerprint_secret`` via
:func:`~app.pii.gate.build_document_gate`, which is what production uses and what
the value here stands in for.
"""

BOUNDARY_DOCUMENT_INTERNAL = "document_internal_llm"
"""Contour 1 at the production boundary (``INTERNAL_LLM``, redactor available)."""

BOUNDARY_DOCUMENT_EXTERNAL = "document_external_llm"
"""Contour 1 at the fail-closed boundary the manifest's ``expected_decision`` names."""

BOUNDARY_CANONICAL_PERSISTENCE = "canonical_persistence"
"""Contour 2 — ``stage=canonical``, ``destination=persistence``."""

CONFIDENCE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("0.90-1.00", 0.90, 1.00),
    ("0.70-0.90", 0.70, 0.90),
    ("0.00-0.70", 0.00, 0.70),
)
"""The M3 three-band table, reused so the two harnesses are comparable.

Boundaries match ``scoring.py``'s decision-level confidence ladder rather than the
PII rules' own confidences: the point of the band is to group findings into
"trust this without reading it" / "read it" / "probably a mistake", and a second
set of numbers for the same question would be one more thing to keep in step.
"""

_BAND_NONE = "none"
"""Band for a boundary that found nothing — not a low score but an empty set."""


def confidence_band(confidences: Sequence[float]) -> str:
    """Return the band label for a set of finding confidences.

    Takes the **minimum**, and that is the load-bearing word. A band computed from
    the strongest claim would report ``0.90-1.00`` for a document where one 0.70
    rule invented a category — which is exactly the shape of both open calibration
    findings, where a high-confidence structured rule goes silent and a
    low-confidence pattern rule guesses instead. Banding by the maximum would
    report those documents as confident.

    An empty input returns ``"none"`` rather than the lowest band: zero findings
    is not low confidence, it is no evidence at all, and folding it into
    ``0.00-0.70`` would put every clean document in the bucket of documents whose
    detections were all unreliable.
    """
    if not confidences:
        return _BAND_NONE
    lowest = min(confidences)
    for label, low, high in CONFIDENCE_BANDS:
        if low <= lowest <= high:
            return label
    return CONFIDENCE_BANDS[-1][0]


@dataclass(frozen=True)
class BoundaryEvaluation:
    """Ground truth vs prediction for one fixture **at one boundary**.

    A row, not a document: ``expected_decision`` is destination-dependent (M4 gap
    1), so the same fixture legitimately yields two rows that disagree and a
    canonical payload a third. Keeping the boundary on the record is what stops a
    report from collapsing them and calling the disagreement a mismatch.

    ``expected_categories`` is repeated here rather than read off the owning
    fixture so a row is self-contained: the JSON report, the markdown table and
    the metrics all consume rows, and a row that had to reach back into its
    parent for its ground truth could be paired with the wrong parent.
    """

    boundary: str
    stage: str
    destination: str
    expected_categories: tuple[str, ...]
    expected_decision: str
    predicted_categories: tuple[str, ...]
    decision: str
    risk_level: str
    detector_attribution: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    actions: Mapping[str, str] = field(default_factory=dict)
    over_redacted: tuple[str, ...] = ()
    leaf_paths: tuple[str, ...] = ()
    confidence_band: str = _BAND_NONE
    findings_count: int = 0
    reasons: tuple[str, ...] = ()

    @property
    def spurious_categories(self) -> tuple[str, ...]:
        """Predicted but not expected — the false positives, per category."""
        expected = set(self.expected_categories)
        return tuple(sorted(set(self.predicted_categories) - expected))

    @property
    def missed_categories(self) -> tuple[str, ...]:
        """Expected but not predicted — the false negatives, per category."""
        predicted = set(self.predicted_categories)
        return tuple(sorted(set(self.expected_categories) - predicted))

    @property
    def exact_set_match(self) -> bool:
        """Every expected category found and nothing extra."""
        return not self.spurious_categories and not self.missed_categories

    @property
    def subset_recall(self) -> bool:
        """Everything expected was found (extra categories allowed).

        The number that matters for a gate: a document carrying a СНИЛС that the
        chain missed is a leak whether or not it also claimed a table number. The
        converse is not symmetric — an extra claim is a masking-fidelity bug, not
        a missed protection, which is why both are reported and only this one is
        named "recall".
        """
        return not self.missed_categories

    @property
    def over_fire(self) -> bool:
        """At least one category claimed that the ground truth does not name."""
        return bool(self.spurious_categories)

    @property
    def under_fire(self) -> bool:
        """At least one expected category was not claimed."""
        return bool(self.missed_categories)

    @property
    def decision_match(self) -> bool:
        return self.decision == self.expected_decision

    @property
    def halted(self) -> bool:
        """``REVIEW`` or ``BLOCK`` — the decisions that stop a document (R9/R15)."""
        return self.decision in {"review", "block"}


@dataclass(frozen=True)
class FixtureEvaluation:
    """One fixture evaluated at every boundary its contour has.

    ``dataset`` is provenance and nothing else. It is carried so a report can say
    which corpus a number came from, and it is deliberately not read by
    :func:`compute_metrics` or :func:`summarize` — a metrics function that
    branched on it would publish synthetic recall under a real-corpus heading,
    which is the one thing the M6 kickoff ruling rules out.
    """

    dataset: str
    fixture: PIIFixture
    boundaries: tuple[BoundaryEvaluation, ...]
    detector_version: str = DETECTOR_VERSION
    policy_version: str = PII_POLICY_VERSION

    @property
    def id(self) -> str:
        """The manifest id — the report's row key, and unique per dataset."""
        return self.fixture.id

    @property
    def contour(self) -> str:
        return self.fixture.contour

    @property
    def boundary_map(self) -> dict[str, BoundaryEvaluation]:
        """Rows keyed by boundary, for callers that want one specific one."""
        return {row.boundary: row for row in self.boundaries}


@dataclass(frozen=True)
class DatasetEvaluation:
    """One corpus' evaluation — present whether or not it was available.

    ``evaluations`` is empty and ``unavailable_reason`` set when the corpus is
    absent, rather than the reverse. The two states are not
    interchangeable: "evaluated and found nothing" and "not evaluated" print the
    same rows and mean opposite things, and only one of them is a measurement.
    """

    name: str
    source: str
    available: bool
    root: Path
    evaluations: tuple[FixtureEvaluation, ...] = ()
    manifest_version: str | None = None
    unavailable_reason: str | None = None

    @property
    def documents(self) -> int:
        return sum(1 for row in self.evaluations if row.contour == CONTOUR_DOCUMENT)

    @property
    def canonical_payloads(self) -> int:
        return sum(1 for row in self.evaluations if row.contour == CONTOUR_CANONICAL)

    @property
    def metrics(self) -> PIIMetrics:
        """The document-level reduction of this block's rows.

        A property rather than a stored field so there is exactly one reduction
        in the module: the three renderers and the tests all reach the numbers
        through here, and a cached copy on a frozen dataclass would be a second
        thing that can disagree with the rows it claims to describe.
        """
        return compute_metrics(self.evaluations)

    @property
    def summary(self) -> SummaryMetrics:
        return summarize(self.evaluations)


@dataclass(frozen=True)
class EvaluationReport:
    """The whole run: versions, then one block per dataset, in report order."""

    datasets: tuple[DatasetEvaluation, ...]
    detector_version: str = DETECTOR_VERSION
    policy_version: str = PII_POLICY_VERSION
    evaluation_version: str = EVALUATION_VERSION
    generated: str = field(default_factory=lambda: date.today().isoformat())

    def dataset(self, name: str) -> DatasetEvaluation:
        """The one block with this name.

        A report always carries every block — including the absent one — so a
        caller reaching for a corpus by name should get a lookup failure rather
        than ``KeyError`` on a tuple, and should not have to spell out that
        absence is a block like any other.
        """
        for block in self.datasets:
            if block.name == name:
                return block
        raise KeyError(f"no dataset {name!r} in report (have {[b.name for b in self.datasets]})")


class CountRate(BaseModel):
    """An absolute count with its rate over the applicable denominator.

    Carries a count beside every rate because both corpora are small: the committed
    one has 6 fixtures and the real one 6 unique documents, where one document is
    17% and a percentage is a statement about two data points. Mirrors
    ``app.classification.evaluate.CountRate``; the denominator is whichever
    population the metric names (boundaries, or boundaries with a declared
    expectation), and each metric's docstring says which.
    """

    model_config = ConfigDict(extra="forbid")

    count: int
    rate: float


class PIIMetrics(BaseModel):
    """The document-level layer, computed over boundary rows.

    Every rate's denominator is the row count unless the field name says otherwise,
    and the two ``*_categories`` counts are plain integers over
    ``Σ |predicted △ expected|`` rather than rates: a rate over rows would
    silently change meaning when a fixture carries one category versus seven.
    """

    model_config = ConfigDict(extra="forbid")

    documents: int
    canonical_payloads: int
    boundaries: int
    exact_set_match: CountRate
    subset_recall: CountRate
    decision_match: CountRate
    over_fire: CountRate
    under_fire: CountRate
    risk_declared_boundaries: int
    risk_match: CountRate
    halted: CountRate
    decisions: dict[str, int]
    spurious_categories: int
    missed_categories: int
    over_redacted_categories: int


class SummaryMetrics(BaseModel):
    """Rendering-facing counts, kept separate from :class:`PIIMetrics`.

    Same reduction, different surface: the CLI summary wants a handful of integers
    per corpus, and building them out of :class:`PIIMetrics` would mean every
    renderer re-deriving what the table already knows.
    """

    model_config = ConfigDict(extra="forbid")

    documents: int
    canonical_payloads: int
    boundaries: int
    exact_set_match: int
    missed_categories: int
    spurious_categories: int
    over_redacted_categories: int
    decisions: dict[str, int]


def _rows(evaluations: Sequence[FixtureEvaluation]) -> list[BoundaryEvaluation]:
    """Flatten fixture records to boundary rows — the metrics' only input.

    Reading ``fixture`` and ``boundaries`` only: this is where a dataset branch
    would have to live if the metrics were allowed one, and ``test_dataset_
    isolation.py`` asserts by AST that no ``.dataset`` read happens outside the
    renderers.
    """
    return [row for evaluation in evaluations for row in evaluation.boundaries]


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _count_rate(count: int, total: int) -> CountRate:
    return CountRate(count=count, rate=_safe_div(count, total))


def compute_metrics(evaluations: Sequence[FixtureEvaluation]) -> PIIMetrics:
    """Ground-truth-vs-prediction counts over every boundary row.

    Multi-label by construction: ``expected_categories`` is a set of up to seven,
    so a document is never "right or wrong" — it is right about some categories,
    wrong about others, and the interesting question is which. The three per-row
    verdicts answer it from three angles:

    * ``exact_set_match`` — every category matched, nothing extra. The strictest
      reading, and the one ``test_manifest_verification.py`` asserts per fixture
      at the manifest's own boundary.
    * ``subset_recall`` — everything expected was found, extras tolerated.
    * ``over_fire`` / ``under_fire`` — the two error directions counted
      separately, because they have opposite fixes: one needs a wider rule, the
      other a narrower one.

    ``risk_match`` is the only rate whose denominator is not every row: the local
    corpus omits ``expected_risk_level``, so its denominator is the rows that
    declare one. That is the honest denominator — dividing by all rows would report
    a corpus as disagreeing about risk on the documents it never claimed to know
    the risk of. ``risk_declared_boundaries`` publishes that denominator next to the
    rate so a corpus that declares none reads as ``0 of 0`` rather than as a 0%
    agreement.
    """
    rows = _rows(evaluations)
    total = len(rows)

    decisions: dict[str, int] = {}
    for row in rows:
        decisions[row.decision] = decisions.get(row.decision, 0) + 1

    risk_declared = [
        evaluation
        for evaluation in evaluations
        if evaluation.fixture.expected_risk_level is not None
    ]
    risk_total = len(_rows(risk_declared))

    return PIIMetrics(
        documents=sum(1 for e in evaluations if e.contour == CONTOUR_DOCUMENT),
        canonical_payloads=sum(1 for e in evaluations if e.contour == CONTOUR_CANONICAL),
        boundaries=total,
        exact_set_match=_count_rate(sum(1 for row in rows if row.exact_set_match), total),
        subset_recall=_count_rate(sum(1 for row in rows if row.subset_recall), total),
        decision_match=_count_rate(sum(1 for row in rows if row.decision_match), total),
        over_fire=_count_rate(sum(1 for row in rows if row.over_fire), total),
        under_fire=_count_rate(sum(1 for row in rows if row.under_fire), total),
        risk_declared_boundaries=risk_total,
        risk_match=_count_rate(
            sum(
                1
                for evaluation in risk_declared
                for row in evaluation.boundaries
                if row.risk_level == evaluation.fixture.expected_risk_level
            ),
            risk_total,
        ),
        halted=_count_rate(sum(1 for row in rows if row.halted), total),
        decisions=dict(sorted(decisions.items())),
        spurious_categories=sum(len(row.spurious_categories) for row in rows),
        missed_categories=sum(len(row.missed_categories) for row in rows),
        over_redacted_categories=sum(len(row.over_redacted) for row in rows),
    )


def summarize(evaluations: Sequence[FixtureEvaluation]) -> SummaryMetrics:
    """Reduce the same rows to the counts the CLI summary prints."""
    rows = _rows(evaluations)
    decisions: dict[str, int] = {}
    for row in rows:
        decisions[row.decision] = decisions.get(row.decision, 0) + 1
    return SummaryMetrics(
        documents=sum(1 for e in evaluations if e.contour == CONTOUR_DOCUMENT),
        canonical_payloads=sum(1 for e in evaluations if e.contour == CONTOUR_CANONICAL),
        boundaries=len(rows),
        exact_set_match=sum(1 for row in rows if row.exact_set_match),
        missed_categories=sum(len(row.missed_categories) for row in rows),
        spurious_categories=sum(len(row.spurious_categories) for row in rows),
        over_redacted_categories=sum(len(row.over_redacted) for row in rows),
        decisions=dict(sorted(decisions.items())),
    )


# --- evaluation ----------------------------------------------------------


def _blank_settings() -> Settings:
    """Settings for an offline run: no ``.env``, a fixed fingerprint secret.

    ``_env_file=None`` because this tool must behave the same on a developer
    machine and in CI; a local ``.env`` that flipped ``llm_mode`` would move every
    decision in the report for reasons that have nothing to do with the gate.
    """
    return Settings(_env_file=None, pii_fingerprint_secret=EVALUATION_FINGERPRINT_SECRET)


def _document_context(settings: Settings, boundary: str) -> PIIPolicyContext:
    """Build the policy context one document boundary is evaluated under.

    Two named contexts, both explicit, neither derived from a default. The
    internal one is the production wiring (``build_document_gate`` resolves the same
    pair from ``Settings.llm_mode``), and the external one is the fail-closed
    direction every committed ``expected_decision`` was written against. Naming
    them keeps a reader of a report row from having to reconstruct which
    redaction assumption produced a ``REVIEW``.
    """
    if boundary == BOUNDARY_DOCUMENT_INTERNAL:
        return build_policy_context(
            settings,
            stage=PIIScanStage.DOCUMENT,
            destination=PIIDestination.INTERNAL_LLM,
            redaction_available=REDACTION_AVAILABLE,
        )
    if boundary == BOUNDARY_DOCUMENT_EXTERNAL:
        return build_policy_context(
            settings,
            stage=PIIScanStage.DOCUMENT,
            destination=PIIDestination.EXTERNAL_LLM,
            redaction_available=False,
        )
    raise ValueError(f"{boundary!r} is not a document boundary")


def _attribution(findings: Sequence[PIIFinding]) -> dict[str, tuple[str, ...]]:
    """``{detector_name: [categories]}`` for a set of findings.

    Detector names, not source enums: the question this answers is *which rule
    fired*, and that is what has to change when a detector is recalibrated. Two
    rules from the same layer claiming the same category stay distinguishable here
    and collapse to one at source granularity.
    """
    collected: dict[str, set[str]] = {}
    for finding in findings:
        collected.setdefault(finding.detector, set()).add(finding.category.value)
    return {detector: tuple(sorted(cats)) for detector, cats in sorted(collected.items())}


def _document_row(
    fixture: PIIFixture,
    boundary: str,
    findings: Sequence[PIIFinding],
    result: PIIDecisionResult,
    context: PIIPolicyContext,
) -> BoundaryEvaluation:
    """Assemble one contour-1 row from an already-decided evaluation.

    ``over_redacted`` is ``REDACT``-actioned categories that no detector claimed.
    The policy engine only ever issues an action for a category that is present in
    the findings, so this is structurally zero on today's table — which is exactly
    why it is worth publishing: a non-zero value means an override reached a
    category nothing detected, and every such value is a field being masked
    without evidence. The R7-shaped failure (a rule claiming the *wrong* field,
    with a finding behind it) is a spurious category instead, and shows up in
    ``spurious_categories`` and in the per-detector attribution beside it.
    """
    detected = tuple(sorted({finding.category.value for finding in findings}))
    redacted = sorted(
        category.value
        for category, action in result.actions.items()
        if action is PIIAction.REDACT and category.value not in set(detected)
    )
    return BoundaryEvaluation(
        boundary=boundary,
        stage=context.stage.value,
        destination=context.destination.value,
        expected_categories=fixture.expected_categories,
        expected_decision=fixture.expected_decision,
        predicted_categories=detected,
        decision=result.decision.value,
        risk_level=result.risk_level.value,
        detector_attribution=_attribution(findings),
        actions={
            category.value: action.value
            for category, action in sorted(result.actions.items(), key=lambda kv: kv[0].value)
        },
        over_redacted=tuple(redacted),
        confidence_band=confidence_band([finding.confidence for finding in findings]),
        findings_count=len(findings),
        reasons=tuple(result.reasons),
    )


def evaluate_fixture(
    fixture: PIIFixture,
    *,
    gate: DefaultPIIGate,
    guard: DefaultCanonicalPIIInspector,
    settings: Settings | None = None,
    normalizer: MarkdownNormalizer | None = None,
) -> FixtureEvaluation:
    """Evaluate one fixture at every boundary its contour has.

    Detection happens **once** and the decision is taken twice, which is both
    faster and more correct than scanning twice: two scans of the same text would
    be two chances for a stateful detector to disagree with itself, and the rows
    would differ for a reason that has nothing to do with the boundary.

    Args:
        fixture: The manifest entry, resolved by :mod:`app.pii.fixtures`.
        gate: Contour 1's chain. Take it from
            :func:`~app.pii.gate.build_document_gate` so the fixtures are scored by
            the pipeline's own detectors rather than a private helper that could
            drift from the wiring.
        guard: Contour 2's chain, from
            :func:`~app.pii.canonical_guard.build_canonical_guard`.
        settings: Optional pre-built settings, for callers evaluating many
            fixtures. Built from a fixed offline configuration when omitted.
        normalizer: Optional shared normalizer; one is built per call otherwise.

    Returns:
        A :class:`FixtureEvaluation` with two rows for a document fixture and one
        for a canonical payload.
    """
    settings = settings or _blank_settings()
    normalizer = normalizer or MarkdownNormalizer()

    if fixture.contour == CONTOUR_CANONICAL:
        return FixtureEvaluation(
            dataset=fixture.dataset,
            fixture=fixture,
            boundaries=(_canonical_row(fixture, guard),),
        )
    if fixture.contour != CONTOUR_DOCUMENT:
        raise ValueError(f"unknown fixture contour {fixture.contour!r} on {fixture.file!r}")

    document = normalizer.normalize(fixture.path.read_text(encoding="utf-8"), metadata={})
    findings = gate.aggregator.aggregate(gate.detector.detect(document))
    rows = []
    for boundary in (BOUNDARY_DOCUMENT_INTERNAL, BOUNDARY_DOCUMENT_EXTERNAL):
        context = _document_context(settings, boundary)
        rows.append(
            _document_row(
                fixture, boundary, findings, gate.policy_engine.evaluate(findings, context), context
            )
        )
    return FixtureEvaluation(dataset=fixture.dataset, fixture=fixture, boundaries=tuple(rows))


def _canonical_row(fixture: PIIFixture, guard: DefaultCanonicalPIIInspector) -> BoundaryEvaluation:
    """Contour 2 row: the payload guard's own verdict, at its own stage/destination.

    The stage and destination are read off the guard's policy context rather than
    restated, because they are the two inputs that make the same value evaluate
    differently here than on the source contour; a row that hard-coded them would
    keep reporting ``persistence`` if the guard's wiring ever moved.

    Findings come from ``findings_by_path`` rather than ``violations`` because the
    attribution map needs the detector that produced each claim, and the violation
    projection deliberately does not carry one. It is also the guard's own
    per-leaf grouping, so the leaf paths reported alongside the categories are the
    same keys the sanitizer would walk — a report that named different paths would
    be describing a remediation nobody can apply.
    """
    payload = json.loads(fixture.path.read_text(encoding="utf-8"))
    result = guard.evaluate_payload(payload)
    context = guard.policy_context_builder()
    findings = [finding for leaf in result.findings_by_path.values() for finding in leaf]
    detected = tuple(sorted({finding.category.value for finding in findings}))
    redacted = sorted(
        category.value
        for category, action in result.actions.items()
        if action is PIIAction.REDACT and category.value not in set(detected)
    )
    return BoundaryEvaluation(
        boundary=BOUNDARY_CANONICAL_PERSISTENCE,
        stage=context.stage.value,
        destination=context.destination.value,
        expected_categories=fixture.expected_categories,
        expected_decision=fixture.expected_decision,
        predicted_categories=detected,
        decision=result.decision.value,
        risk_level=result.risk_level.value,
        detector_attribution=_attribution(findings),
        actions={
            category.value: action.value
            for category, action in sorted(result.actions.items(), key=lambda kv: kv[0].value)
        },
        over_redacted=tuple(redacted),
        leaf_paths=tuple(sorted(result.findings_by_path)),
        confidence_band=confidence_band([finding.confidence for finding in findings]),
        findings_count=len(findings),
        reasons=tuple(result.reasons),
    )


# --- the dataset boundary -------------------------------------------------


class EvaluationDataset(Protocol):
    """A corpus the evaluator can run over, or an explanation of why it cannot.

    ``available``/``unavailable_reason`` are the whole point of the abstraction:
    the report must be able to say "the real corpus was not evaluated" without
    that statement depending on whether a directory happens to exist. An
    implementation that returned an empty list for both cases would make the two
    indistinguishable, and the report would have to guess which one it is
    describing.

    ``iter()`` evaluates rather than merely enumerating, so both implementations
    produce the identical :class:`FixtureEvaluation` record and the caller cannot
    accidentally score one corpus differently from the other. The name is M6's
    plan-locked surface; the metrics read the returned records, never the dataset.
    """

    name: str
    source: str
    available: bool
    unavailable_reason: str | None
    root: Path
    manifest_version: str | None

    def iter(self) -> list[FixtureEvaluation]:
        """Evaluate every fixture in this corpus, in manifest order."""
        ...


class _LoaderDataset:
    """Shared machinery for the two corpora: load fixtures, then evaluate them.

    Both implementations differ only in *where* the fixtures come from and *how
    they label themselves*. Everything after the loader call is identical, which
    is what makes the two records comparable — a per-corpus evaluation routine
    would be a second implementation to keep in step.
    """

    name = ""
    source = ""

    def __init__(self, root: Path, manifest_version: str | None) -> None:
        self.root = root
        self.manifest_version = manifest_version
        self.available = manifest_version is not None
        self.unavailable_reason = None if self.available else self._reason()

    def _reason(self) -> str:
        raise NotImplementedError

    def fixtures(self) -> list[PIIFixture]:
        raise NotImplementedError

    def iter(self) -> list[FixtureEvaluation]:
        if not self.available:
            return []
        settings = _blank_settings()
        gate = build_document_gate(settings)
        guard = build_canonical_guard(settings)
        normalizer = MarkdownNormalizer()
        return [
            evaluate_fixture(
                fixture,
                gate=gate,
                guard=guard,
                settings=settings,
                normalizer=normalizer,
            )
            for fixture in self.fixtures()
        ]


class SyntheticFixtureDataset(_LoaderDataset):
    """The committed corpus — ``tests/fixtures/pii/``.

    Always available: it is in version control, so "the synthetic block is absent"
    is a broken checkout, not a missing measurement. That asymmetry with
    :class:`LocalRealCorpusDataset` is deliberate — CI asserts on this corpus, so
    its absence has to fail loudly rather than be reported as an empty result.
    """

    name = DATASET_SYNTHETIC
    source = "committed"

    def __init__(self) -> None:
        super().__init__(SYNTHETIC_FIXTURES_DIR, synthetic_manifest_version())

    def _reason(self) -> str:  # pragma: no cover - the committed manifest is in git
        return f"the committed manifest is missing at {self.root / 'manifest.json'}"

    def fixtures(self) -> list[PIIFixture]:
        return iter_pii_fixtures() + iter_canonical_fixtures()


class LocalRealCorpusDataset(_LoaderDataset):
    """The local real corpus — ``$PII_FIXTURES_DIR``, conventionally ``.dev/pii-fixtures/``.

    Never committed and never required. ``available`` is decided from the
    environment *before* the file system is touched, so with ``PII_FIXTURES_DIR``
    unset this object reads nothing at all and nothing under ``.dev/`` is reachable
    — see :mod:`app.pii.fixtures` for why the conventional default directory is
    deliberately not picked up automatically.
    """

    name = DATASET_REAL_CORPUS
    source = "local-only"

    def __init__(self) -> None:
        super().__init__(
            local_real_corpus_dir(),
            local_real_corpus_manifest_version() if local_real_corpus_available() else None,
        )

    def _reason(self) -> str:
        return local_real_corpus_unavailable_reason() or "the real corpus is unavailable"

    def fixtures(self) -> list[PIIFixture]:
        return iter_local_real_corpus()


def default_datasets() -> tuple[EvaluationDataset, ...]:
    """The two corpora, in report order: synthetic first, real second.

    Order is a contract, not cosmetics — the JSON keys and the markdown sections
    follow it, and the synthetic corpus leads so a reader who stops after the
    first block has seen the numbers CI actually gates on.
    """
    return (SyntheticFixtureDataset(), LocalRealCorpusDataset())


def evaluate_dataset(dataset: EvaluationDataset) -> DatasetEvaluation:
    """Run one corpus and wrap the result with its availability metadata."""
    evaluations = tuple(dataset.iter())
    return DatasetEvaluation(
        name=dataset.name,
        source=dataset.source,
        available=dataset.available,
        root=dataset.root,
        evaluations=evaluations,
        manifest_version=dataset.manifest_version,
        unavailable_reason=dataset.unavailable_reason,
    )


def run_evaluation(datasets: Sequence[EvaluationDataset] | None = None) -> EvaluationReport:
    """Evaluate every dataset and return the report.

    Unlike M3's ``run_evaluation``, which returns a bare list because it has one
    corpus, this returns the whole report — the dataset blocks *are* the result,
    and a list of records would have already thrown away the one fact a reader of
    an absent corpus most needs.
    """
    targets = list(datasets) if datasets is not None else list(default_datasets())
    return EvaluationReport(datasets=tuple(evaluate_dataset(dataset) for dataset in targets))


# --- rendering ------------------------------------------------------------


def _dataset_line(dataset: DatasetEvaluation) -> str:
    if not dataset.available:
        return f"{dataset.name}: NOT EVALUATED - {dataset.unavailable_reason}"
    version = dataset.manifest_version or "?"
    return (
        f"{dataset.name}: {dataset.documents} document(s), "
        f"{dataset.canonical_payloads} canonical payload(s), manifest {version}"
    )


def _row_line(row: BoundaryEvaluation) -> str:
    expected = ",".join(row.expected_categories) or "-"
    predicted = ",".join(row.predicted_categories) or "-"
    mark = "MATCH" if row.exact_set_match and row.decision_match else "MISMATCH"
    detail = []
    if row.spurious_categories:
        detail.append(f"extra: {','.join(row.spurious_categories)}")
    if row.missed_categories:
        detail.append(f"missed: {','.join(row.missed_categories)}")
    if row.over_redacted:
        detail.append(f"over-redacted: {','.join(row.over_redacted)}")
    if not row.decision_match:
        detail.append(f"decision: expected {row.expected_decision}")
    suffix = f"  [{'; '.join(detail)}]" if detail else ""
    return (
        f"  {row.boundary:<24} {row.stage}/{row.destination}\n"
        f"    expected : {expected}\n"
        f"    predicted: {predicted}  [{mark}]\n"
        f"    decision : {row.decision} ({row.risk_level})"
        f" band {row.confidence_band} findings {row.findings_count}{suffix}"
    )


def _dataset_block_lines(dataset: DatasetEvaluation) -> list[str]:
    lines = [_dataset_line(dataset), ""]
    if not dataset.available:
        lines.append("  No metrics: the corpus was not evaluated, so there is nothing to report.")
        lines.append("")
        return lines
    metrics = dataset.metrics
    summary = dataset.summary
    lines.append(f"  root: {dataset.root}")
    lines.append("")
    lines.append(
        f"  Fixtures: {summary.documents} document(s) + "
        f"{summary.canonical_payloads} canonical payload(s) = {summary.boundaries} boundary rows"
    )
    lines.append(
        f"  Exact set match : {metrics.exact_set_match.count}/{metrics.boundaries}"
        f" ({metrics.exact_set_match.rate:.1%})"
    )
    lines.append(
        f"  Subset recall   : {metrics.subset_recall.count}/{metrics.boundaries}"
        f" ({metrics.subset_recall.rate:.1%})"
    )
    lines.append(
        f"  Decision match  : {metrics.decision_match.count}/{metrics.boundaries}"
        f" ({metrics.decision_match.rate:.1%})"
    )
    lines.append(
        f"  Over-fire rows  : {metrics.over_fire.count}  "
        f"({metrics.spurious_categories} category/categories claimed spuriously)"
    )
    lines.append(
        f"  Under-fire rows : {metrics.under_fire.count}  "
        f"({metrics.missed_categories} category/categories missed)"
    )
    lines.append(
        f"  Over-redacted   : {metrics.over_redacted_categories}"
        " (categories masked that no detector claimed)"
    )
    lines.append(
        f"  Halted rows     : {metrics.halted.count}/{metrics.boundaries}"
        f" ({metrics.halted.rate:.1%})  decisions: {metrics.decisions}"
    )
    lines.append("")
    for evaluation in dataset.evaluations:
        lines.append(f"  == {evaluation.id} ({evaluation.fixture.file}, {evaluation.contour})")
        if evaluation.fixture.derived_from:
            lines.append(f"     derived from: {evaluation.fixture.derived_from}")
        for row in evaluation.boundaries:
            lines.append(_row_line(row))
            for detector, categories in row.detector_attribution.items():
                lines.append(f"       {detector}: {','.join(categories)}")
            if row.leaf_paths:
                lines.append(f"       leaves: {', '.join(row.leaf_paths)}")
        lines.append("")
    return lines


def render_text(report: EvaluationReport) -> str:
    """Render the stdout report: one block per corpus, availability stated first."""
    lines = [
        f"PII gate evaluation - detector {report.detector_version}, "
        f"policy {report.policy_version}, evaluation {report.evaluation_version}",
        f"generated {report.generated}",
        "",
    ]
    for dataset in report.datasets:
        lines.extend(_dataset_block_lines(dataset))
    lines.append(
        "Counts, not percentages, decide: the committed corpus is small and the real "
        "corpus is 6 unique documents, so every rate here is report-grade."
    )
    return "\n".join(lines).rstrip()


def render_markdown(report: EvaluationReport) -> str:
    """Render the ``--report`` artifact.

    The header states which corpora produced the numbers *and* whether the real one
    was available, because an artifact read weeks later cannot infer it: a report
    with one corpus in it is not obviously a report with one corpus missing.
    """
    lines = [
        "# PII Gate — Evaluation report",
        "",
        f"- generated: {report.generated}",
        f"- detector: `{report.detector_version}`",
        f"- policy: `{report.policy_version}`",
        f"- evaluation harness: `{report.evaluation_version}`",
        "",
        "## Corpora",
        "",
        "| dataset | available | source | root | manifest |",
        "|---|---|---|---|---|",
    ]
    for dataset in report.datasets:
        lines.append(
            f"| `{dataset.name}` | {'yes' if dataset.available else '**no**'} "
            f"| {dataset.source} | `{dataset.root}` "
            f"| {dataset.manifest_version or '-'} |"
        )
    lines.append("")
    for dataset in report.datasets:
        lines.append(f"## `{dataset.name}`")
        lines.append("")
        if not dataset.available:
            lines.append(f"> **Not evaluated.** {dataset.unavailable_reason}")
            lines.append("")
            lines.append(
                "No metrics are published for this corpus. An absent measurement is not a "
                "measurement of zero, and a synthetic figure under this heading would be "
                "the one failure this report exists to avoid."
            )
            lines.append("")
            continue
        metrics = dataset.metrics
        lines.append(
            f"- fixtures: {metrics.documents} document(s), "
            f"{metrics.canonical_payloads} canonical payload(s)"
        )
        lines.append(f"- boundary rows: {metrics.boundaries}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(
            f"| Exact set match | {metrics.exact_set_match.count}/{metrics.boundaries} "
            f"({metrics.exact_set_match.rate:.1%}) |"
        )
        lines.append(
            f"| Subset recall | {metrics.subset_recall.count}/{metrics.boundaries} "
            f"({metrics.subset_recall.rate:.1%}) |"
        )
        lines.append(
            f"| Decision match | {metrics.decision_match.count}/{metrics.boundaries} "
            f"({metrics.decision_match.rate:.1%}) |"
        )
        lines.append(f"| Over-fire rows | {metrics.over_fire.count} |")
        lines.append(f"| Under-fire rows | {metrics.under_fire.count} |")
        lines.append(f"| Spurious categories | {metrics.spurious_categories} |")
        lines.append(f"| Missed categories | {metrics.missed_categories} |")
        lines.append(f"| Over-redacted categories | {metrics.over_redacted_categories} |")
        lines.append(
            f"| Halted rows | {metrics.halted.count}/{metrics.boundaries} "
            f"({metrics.halted.rate:.1%}) |"
        )
        lines.append(f"| Decisions | `{metrics.decisions}` |")
        lines.append("")
        lines.append("### Per-fixture")
        lines.append("")
        lines.append(
            "| id | file | boundary | stage/destination | expected | predicted | decision | match |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for evaluation in dataset.evaluations:
            for row in evaluation.boundaries:
                mark = "MATCH" if row.exact_set_match and row.decision_match else "MISMATCH"
                lines.append(
                    f"| `{evaluation.id}` | `{evaluation.fixture.file}` | `{row.boundary}` "
                    f"| {row.stage}/{row.destination} "
                    f"| {', '.join(row.expected_categories) or '-'} "
                    f"| {', '.join(row.predicted_categories) or '-'} "
                    f"| {row.decision} | {mark} |"
                )
        lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Every fixture is evaluated at more than one boundary: `expected_decision` is "
        "destination-dependent, so a single decision column would be wrong at two of "
        "the three boundaries without saying which."
    )
    lines.append(
        "- Counts are reported alongside rates. Both corpora are small, so a percentage "
        "is a statement about a handful of documents."
    )
    lines.append("")
    return "\n".join(lines)


def _evaluation_to_dict(evaluation: FixtureEvaluation) -> dict[str, Any]:
    return {
        "id": evaluation.id,
        "file": evaluation.fixture.file,
        "contour": evaluation.contour,
        "source": evaluation.fixture.source,
        "derived_from": evaluation.fixture.derived_from,
        "provenance": evaluation.fixture.provenance,
        "boundaries": [
            {
                "boundary": row.boundary,
                "stage": row.stage,
                "destination": row.destination,
                "expected": {
                    "categories": list(row.expected_categories),
                    "decision": row.expected_decision,
                    "detector_source": {
                        category: list(sources)
                        for category, sources in evaluation.fixture.expected_detector_source.items()
                    },
                },
                "predicted": {
                    "categories": list(row.predicted_categories),
                    "decision": row.decision,
                    "risk_level": row.risk_level,
                },
                "spurious_categories": list(row.spurious_categories),
                "missed_categories": list(row.missed_categories),
                "over_redacted": list(row.over_redacted),
                "leaf_paths": list(row.leaf_paths),
                "detector_attribution": {
                    detector: list(categories)
                    for detector, categories in row.detector_attribution.items()
                },
                "actions": dict(row.actions),
                "confidence_band": row.confidence_band,
                "findings_count": row.findings_count,
                "reasons": list(row.reasons),
                "exact_set_match": row.exact_set_match,
                "subset_recall": row.subset_recall,
                "decision_match": row.decision_match,
            }
            for row in evaluation.boundaries
        ],
    }


def _dataset_to_dict(dataset: DatasetEvaluation) -> dict[str, Any]:
    """Build one dataset block.

    Hand-built rather than ``model_dump`` because the **absence** of ``metrics`` is
    the contract: an unavailable corpus emits ``available: false``, its reason, and
    no ``metrics`` key at all. A synthesised empty block — ``"metrics": {}`` or
    zeroes — reads as a measurement of zero rather than an absent measurement, and
    that is the false precision the M6 ruling rules out. Key presence is therefore
    the load-bearing part of this function.
    """
    block: dict[str, Any] = {
        "available": dataset.available,
        "source": dataset.source,
        "root": str(dataset.root),
    }
    if not dataset.available:
        block["reason"] = dataset.unavailable_reason
        return block
    block["manifest_version"] = dataset.manifest_version
    block["metrics"] = dataset.metrics.model_dump()
    block["summary"] = dataset.summary.model_dump()
    block["evaluations"] = [_evaluation_to_dict(item) for item in dataset.evaluations]
    return block


def _to_json(report: EvaluationReport) -> dict[str, Any]:
    return {
        "evaluation_version": report.evaluation_version,
        "detector_version": report.detector_version,
        "policy_version": report.policy_version,
        "generated": report.generated,
        "datasets": {dataset.name: _dataset_to_dict(dataset) for dataset in report.datasets},
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Always returns ``0``. The thresholds live in pytest, exactly as in M3: an
    evaluation tool that exited non-zero would be a gate wearing a dev-tool's
    clothes, and the exit code would then encode a threshold nobody could see in
    the report. Every dataset in the report is therefore reachable from a command
    that succeeds and a report that says what it measured.
    """
    parser = argparse.ArgumentParser(
        prog="app.pii.evaluate",
        description="Evaluate the PII gate on the committed and local corpora.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON to stdout",
    )
    parser.add_argument(
        "--report",
        metavar="PATH",
        help="write a Markdown evaluation report to PATH",
    )
    args = parser.parse_args(argv)

    report = run_evaluation()

    if args.json:
        print(json.dumps(_to_json(report), indent=2, ensure_ascii=False, sort_keys=False))
    else:
        print(render_text(report))

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
