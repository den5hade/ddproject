"""Deterministic, offline evaluation CLI for the rule-based classifier.

M3 (EVAL_IMPL_PLAN Phase 1–2): ``python -m app.classification.evaluate`` runs
every regression fixture through the single prediction path
``MarkdownNormalizer -> detectors -> RuleScoringEngine -> decision tuple`` and
compares the outcome against the manifest ground truth.

Phase 2 metrics (pure functions over evaluation results, Pydantic-typed):

* per-type TP/FP/FN → precision/recall/F1 (+ macro/micro aggregates);
* overall accuracy (type **and** decision must match the ground truth);
* design-spec §29 domain rates — ``wrong_schema_rate`` / ``generic_rate`` /
  ``ambiguous_rate`` / ``false_laboratory_rate`` — each with the absolute
  count alongside it;
* confidence distribution (the three decision-level bands), saturation-at-1.00
  count and correctness-by-band reliability.

Domain-rate taxonomy (design-spec §29, counts at N=11):

* wrong schema — a typed document routed to a *different* typed schema
  (e.g. laboratory → appointment); fallback-to-other and other→typed false
  positives are *not* wrong schema;
* generic — expected non-other routed to ``other`` (unexpected fallback);
* ambiguous — predicted decision ``ambiguous``;
* false laboratory — predicted ``laboratory`` when ground truth is not.

Per-type P/R/F1 are computed on ``document_type`` alone (single-label
multi-class); only types appearing in expected or predicted labels enter the
averages. Subtype mismatches are reported per fixture but not gated here.

Dev-only tool. Output is local (stdout / ``--json`` / ``--report <path>``):
no S3, RabbitMQ or storage writes, no LLM, no network — the run is fully
reproducible on the fixed fixtures.

Prerequisite: run from the ai-worker project directory so ``app`` is on
``sys.path`` (e.g. ``cd apps/ai-worker && uv run python -m
app.classification.evaluate``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from app.classification.fixtures import (
    MANIFEST_PATH,
    ClassificationFixture,
    iter_classification_fixtures,
)
from app.classification.models import (
    ClassificationConfidenceLevel,
    ClassificationDecision,
    ClassificationSignal,
    DocumentType,
)
from app.classification.normalize import MarkdownNormalizer
from app.classification.scoring import RuleScoringEngine
from app.classification.service import RuleBasedClassificationService
from app.pipeline.context import ProcessingContext

__all__ = [
    "ClassificationMetrics",
    "ConfidenceStats",
    "CountRate",
    "DomainRates",
    "FixtureEvaluation",
    "ReliabilityBand",
    "SummaryMetrics",
    "TypeMetrics",
    "compute_confidence_stats",
    "compute_domain_rates",
    "compute_metrics",
    "evaluate_fixture",
    "main",
    "render_markdown",
    "render_text",
    "run_evaluation",
    "summarize",
]


@dataclass(frozen=True)
class RankingDetail:
    """Scoring ranking detail not carried on the contract result."""

    top_type: DocumentType
    top: float
    second: float
    margin: float
    totals: dict[str, float]


@dataclass(frozen=True)
class FixtureEvaluation:
    """Ground truth vs prediction for a single fixture."""

    fixture: ClassificationFixture
    document_type: DocumentType
    document_subtype: str | None
    decision: ClassificationDecision
    confidence: float
    confidence_level: ClassificationConfidenceLevel
    margin: float
    top: float
    second: float
    per_type: dict[str, float]
    signals: list[ClassificationSignal]
    classifier_version: str
    reasons: list[str] = field(default_factory=list)

    @property
    def type_expected(self) -> str:
        return self.fixture.expected_type

    @property
    def type_predicted(self) -> str:
        return self.document_type.value

    @property
    def subtype_expected(self) -> str | None:
        return self.fixture.expected_subtype

    @property
    def subtype_predicted(self) -> str | None:
        return self.document_subtype

    @property
    def decision_expected(self) -> str:
        return self.fixture.expected_decision

    @property
    def decision_predicted(self) -> str:
        return self.decision.value

    @property
    def type_match(self) -> bool:
        return self.type_expected == self.type_predicted

    @property
    def subtype_match(self) -> bool:
        return self.subtype_expected == self.subtype_predicted

    @property
    def decision_match(self) -> bool:
        return self.decision_expected == self.decision_predicted

    @property
    def is_correct(self) -> bool:
        """Correct = type and decision both match the ground truth."""
        return self.type_match and self.decision_match

    @property
    def misfit(self) -> bool:
        return not (self.type_match and self.subtype_match and self.decision_match)


class SummaryMetrics(BaseModel):
    """Counts + rates produced for the evaluation summary.

    N=11 makes percentages ~9% per document, so every rate carries the
    absolute count alongside it (EVAL_IMPL_PLAN §4: counts over percentages
    until the real-marker set grows past ~50).
    """

    documents: int
    correct: int
    accuracy: float
    recall: dict[str, tuple[int, int]]  # expected type -> (correct, total)
    wrong_schema: int
    generic_fallback: int
    ambiguous: int
    false_laboratory: int


class TypeMetrics(BaseModel):
    """Per-type confusion counts and derived precision/recall/F1."""

    type: str
    tp: int
    fp: int
    fn: int
    support: int
    precision: float
    recall: float
    f1: float


class Aggregates(BaseModel):
    """Macro/micro averages over per-type metrics."""

    precision: float
    recall: float
    f1: float


class ClassificationMetrics(BaseModel):
    """Per-type P/R/F1 with macro/micro aggregates and overall accuracy."""

    documents: int
    accuracy: float
    per_type: dict[str, TypeMetrics]
    macro: Aggregates
    micro: Aggregates


class CountRate(BaseModel):
    """An absolute count with its rate over the evaluation set."""

    count: int
    rate: float


class DomainRates(BaseModel):
    """design-spec §29 domain rates (each with the absolute count alongside)."""

    wrong_schema: CountRate
    generic: CountRate
    ambiguous: CountRate
    false_laboratory: CountRate

    @property
    def wrong_schema_rate(self) -> float:
        return self.wrong_schema.rate

    @property
    def generic_rate(self) -> float:
        return self.generic.rate

    @property
    def ambiguous_rate(self) -> float:
        return self.ambiguous.rate

    @property
    def false_laboratory_rate(self) -> float:
        return self.false_laboratory.rate


class ReliabilityBand(BaseModel):
    """Correctness within one confidence band (decision-level boundaries)."""

    band: str
    total: int
    correct: int
    accuracy: float


class ConfidenceStats(BaseModel):
    """Confidence distribution, saturation count and band reliability."""

    minimum: float
    maximum: float
    mean: float
    saturated_at_one: int
    distribution: dict[str, int]
    reliability: list[ReliabilityBand]


# Confidence bands mirror the decision-level boundaries in scoring.py:
# HIGH >= 0.90, MEDIUM >= 0.70, LOW < 0.70. Label = "lo-hi".
_CONFIDENCE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("0.90-1.00", 0.90, 1.00),
    ("0.70-0.90", 0.70, 0.90),
    ("0.00-0.70", 0.00, 0.70),
)


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return _safe_div(2 * precision * recall, precision + recall)


def _count_rate(count: int, total: int) -> CountRate:
    return CountRate(count=count, rate=_safe_div(count, total))


def compute_metrics(evaluations: Sequence[FixtureEvaluation]) -> ClassificationMetrics:
    """Per-type TP/FP/FN → P/R/F1 (+ macro/micro) and overall accuracy.

    Single-label multi-class over ``document_type``. Only types with any
    support (expected or predicted) enter the macro average; zero-denominator
    precision/recall are reported as 0.0. Accuracy additionally requires the
    decision to match (``FixtureEvaluation.is_correct``).
    """
    evaluations = list(evaluations)
    total = len(evaluations)
    present_types = sorted(
        {evaluation.type_expected for evaluation in evaluations}
        | {evaluation.type_predicted for evaluation in evaluations}
    )

    per_type: dict[str, TypeMetrics] = {}
    sum_tp = sum_fp = sum_fn = 0
    for document_type in present_types:
        tp = sum(
            1
            for evaluation in evaluations
            if evaluation.type_expected == document_type
            and evaluation.type_predicted == document_type
        )
        fp = sum(
            1
            for evaluation in evaluations
            if evaluation.type_expected != document_type
            and evaluation.type_predicted == document_type
        )
        fn = sum(
            1
            for evaluation in evaluations
            if evaluation.type_expected == document_type
            and evaluation.type_predicted != document_type
        )
        support = tp + fn
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        per_type[document_type] = TypeMetrics(
            type=document_type,
            tp=tp,
            fp=fp,
            fn=fn,
            support=support,
            precision=precision,
            recall=recall,
            f1=_f1(precision, recall),
        )
        sum_tp += tp
        sum_fp += fp
        sum_fn += fn

    if per_type:
        macro = Aggregates(
            precision=sum(m.precision for m in per_type.values()) / len(per_type),
            recall=sum(m.recall for m in per_type.values()) / len(per_type),
            f1=sum(m.f1 for m in per_type.values()) / len(per_type),
        )
    else:
        macro = Aggregates(precision=0.0, recall=0.0, f1=0.0)
    micro_precision = _safe_div(sum_tp, sum_tp + sum_fp)
    micro_recall = _safe_div(sum_tp, sum_tp + sum_fn)
    micro = Aggregates(
        precision=micro_precision,
        recall=micro_recall,
        f1=_f1(micro_precision, micro_recall),
    )
    correct = sum(1 for evaluation in evaluations if evaluation.is_correct)
    return ClassificationMetrics(
        documents=total,
        accuracy=_safe_div(correct, total),
        per_type=per_type,
        macro=macro,
        micro=micro,
    )


def compute_domain_rates(
    evaluations: Sequence[FixtureEvaluation],
) -> DomainRates:
    """design-spec §29 domain rates, each with its absolute count."""
    evaluations = list(evaluations)
    total = len(evaluations)
    wrong_schema = sum(
        1
        for evaluation in evaluations
        if evaluation.type_expected != evaluation.type_predicted
        and evaluation.type_expected != "other"
        and evaluation.type_predicted != "other"
    )
    generic = sum(
        1
        for evaluation in evaluations
        if evaluation.type_expected != "other" and evaluation.type_predicted == "other"
    )
    ambiguous = sum(
        1 for evaluation in evaluations if evaluation.decision_predicted == "ambiguous"
    )
    false_laboratory = sum(
        1
        for evaluation in evaluations
        if evaluation.type_expected != "laboratory"
        and evaluation.type_predicted == "laboratory"
    )
    return DomainRates(
        wrong_schema=_count_rate(wrong_schema, total),
        generic=_count_rate(generic, total),
        ambiguous=_count_rate(ambiguous, total),
        false_laboratory=_count_rate(false_laboratory, total),
    )


def compute_confidence_stats(
    evaluations: Sequence[FixtureEvaluation],
) -> ConfidenceStats:
    """Confidence distribution, saturation-at-1.00 count and band reliability."""
    evaluations = list(evaluations)
    values = [evaluation.confidence for evaluation in evaluations]
    if not values:
        return ConfidenceStats(
            minimum=0.0,
            maximum=0.0,
            mean=0.0,
            saturated_at_one=0,
            distribution={label: 0 for label, _, _ in _CONFIDENCE_BANDS},
            reliability=[
                ReliabilityBand(band=label, total=0, correct=0, accuracy=0.0)
                for label, _, _ in _CONFIDENCE_BANDS
            ],
        )

    distribution: dict[str, int] = {label: 0 for label, _, _ in _CONFIDENCE_BANDS}
    reliability: list[ReliabilityBand] = []
    for label, low, high in _CONFIDENCE_BANDS:
        if high >= 1.0:
            band_values = [
                evaluation
                for evaluation in evaluations
                if low <= evaluation.confidence <= high
            ]
        else:
            band_values = [
                evaluation
                for evaluation in evaluations
                if low <= evaluation.confidence < high
            ]
        correct = sum(1 for evaluation in band_values if evaluation.is_correct)
        distribution[label] = len(band_values)
        reliability.append(
            ReliabilityBand(
                band=label,
                total=len(band_values),
                correct=correct,
                accuracy=_safe_div(correct, len(band_values)),
            )
        )

    return ConfidenceStats(
        minimum=min(values),
        maximum=max(values),
        mean=sum(values) / len(values),
        saturated_at_one=sum(1 for value in values if value == 1.0),
        distribution=distribution,
        reliability=reliability,
    )


def summarize(evaluations: Sequence[FixtureEvaluation]) -> SummaryMetrics:
    """Reduce evaluations to summary counts (Phase 9 block of the CLI)."""
    evaluations = list(evaluations)
    total = len(evaluations)
    correct = sum(1 for evaluation in evaluations if evaluation.is_correct)

    recall: dict[str, tuple[int, int]] = {}
    for evaluation in evaluations:
        expected = evaluation.type_expected
        recall.setdefault(expected, (0, 0))
        count, total_expected = recall[expected]
        recall[expected] = (count + evaluation.type_match, total_expected + 1)

    domain = compute_domain_rates(evaluations)
    return SummaryMetrics(
        documents=total,
        correct=correct,
        accuracy=_safe_div(correct, total),
        recall=recall,
        wrong_schema=domain.wrong_schema.count,
        generic_fallback=domain.generic.count,
        ambiguous=domain.ambiguous.count,
        false_laboratory=domain.false_laboratory.count,
    )


def _blank_context() -> ProcessingContext:
    return ProcessingContext(
        document_id=uuid4(),
        document_version_id=uuid4(),
        patient_id=uuid4(),
    )


def _ranking(signals: Sequence[ClassificationSignal]) -> RankingDetail:
    """Recompute the engine's ranking detail from scored signals.

    Uses the ``RuleScoringEngine`` implementation as-is (no modifications in
    Phase 1); the ranking helpers are pure functions of the signal set.
    """
    totals = RuleScoringEngine._type_totals(list(signals))
    top_type, top, second, margin = RuleScoringEngine._ranked(totals)
    return RankingDetail(
        top_type=top_type,
        top=top,
        second=second,
        margin=margin,
        totals={document_type.value: totals[document_type] for document_type in DocumentType},
    )


async def _evaluate_one(
    fixture: ClassificationFixture,
    *,
    normalizer: MarkdownNormalizer,
    service: RuleBasedClassificationService,
) -> FixtureEvaluation:
    text = fixture.path.read_text(encoding="utf-8")
    document = normalizer.normalize(text)
    result = await service.classify(document, _blank_context())
    ranking = _ranking(result.signals)
    return FixtureEvaluation(
        fixture=fixture,
        document_type=result.document_type,
        document_subtype=result.document_subtype,
        decision=result.decision,
        confidence=result.confidence,
        confidence_level=result.confidence_level,
        margin=ranking.margin,
        top=ranking.top,
        second=ranking.second,
        per_type=ranking.totals,
        signals=result.signals,
        classifier_version=result.classifier_version,
        reasons=result.reasons,
    )


async def evaluate_fixture(
    fixture: ClassificationFixture,
    *,
    normalizer: MarkdownNormalizer | None = None,
    service: RuleBasedClassificationService | None = None,
) -> FixtureEvaluation:
    """Evaluate a single fixture on the fixed prediction path."""
    return await _evaluate_one(
        fixture,
        normalizer=normalizer or MarkdownNormalizer(),
        service=service or RuleBasedClassificationService(),
    )


def run_evaluation(
    fixtures: Sequence[ClassificationFixture] | None = None,
) -> list[FixtureEvaluation]:
    """Evaluate ``fixtures`` (or the whole manifest) synchronously."""
    targets = list(fixtures) if fixtures is not None else iter_classification_fixtures()
    return asyncio.run(
        _evaluate_all(targets, MarkdownNormalizer(), RuleBasedClassificationService())
    )


async def _evaluate_all(
    fixtures: Sequence[ClassificationFixture],
    normalizer: MarkdownNormalizer,
    service: RuleBasedClassificationService,
) -> list[FixtureEvaluation]:
    return [
        await _evaluate_one(fixture, normalizer=normalizer, service=service)
        for fixture in fixtures
    ]


def _signals_line(signals: Sequence[ClassificationSignal]) -> str:
    parts = []
    for signal in signals:
        parts.append(f"{signal.name} x{signal.matches} ({signal.score:.1f})")
    return ", ".join(parts) if parts else "(none)"


def _per_type_line(totals: dict[str, float]) -> str:
    parts = [f"{name} {score:.1f}" for name, score in totals.items() if score > 0]
    return ", ".join(parts) if parts else "(none)"


def _detail_lines(evaluation: FixtureEvaluation) -> list[str]:
    mark = "MATCH" if not evaluation.misfit else "MISMATCH"
    return [
        f"  expected : {evaluation.type_expected}/{evaluation.subtype_expected or '-'}"
        f"/{evaluation.decision_expected}",
        f"  predicted: {evaluation.type_predicted}/{evaluation.subtype_predicted or '-'}"
        f"/{evaluation.decision_predicted}  [{mark}]",
        f"  confidence: {evaluation.confidence:.2f} ({evaluation.confidence_level.value})"
        f"  margin {evaluation.margin:.1f}"
        f" (top {evaluation.top:.1f}, second {evaluation.second:.1f})",
        f"  per-type : {_per_type_line(evaluation.per_type)}",
        f"  signals  : {_signals_line(evaluation.signals)}",
    ]


def _rate_line(label: str, count: int, denom: int) -> str:
    if not label.endswith(":"):
        label = label + ":"
    rate = count / denom if denom else 0.0
    return f"{label:<21} {count}/{denom} ({rate:.1%})"


def _metrics_lines(metrics: ClassificationMetrics) -> list[str]:
    lines = ["Per-type metrics:"]
    for document_type, type_metrics in metrics.per_type.items():
        lines.append(
            f"  {document_type:<14} P {type_metrics.precision:.3f}"
            f"  R {type_metrics.recall:.3f}"
            f"  F1 {type_metrics.f1:.3f}"
            f"  (support {type_metrics.support})"
        )
    lines.append(
        f"  {'macro':<14} P {metrics.macro.precision:.3f}"
        f"  R {metrics.macro.recall:.3f}"
        f"  F1 {metrics.macro.f1:.3f}"
    )
    lines.append(
        f"  {'micro':<14} P {metrics.micro.precision:.3f}"
        f"  R {metrics.micro.recall:.3f}"
        f"  F1 {metrics.micro.f1:.3f}"
    )
    return lines


def _confidence_lines(
    stats: ConfidenceStats,
    summary: SummaryMetrics,
) -> list[str]:
    lines = [
        f"Confidence:     min {stats.minimum:.2f}  mean {stats.mean:.2f}"
        f"  max {stats.maximum:.2f}"
        f"  saturated@1.00: {stats.saturated_at_one}/{summary.documents}",
        "Distribution:   "
        + "  ".join(
            f"{label}: {count}" for label, count in stats.distribution.items()
        ),
        "Reliability by band:",
    ]
    for band in stats.reliability:
        lines.append(
            f"  {band.band:<12} {band.correct}/{band.total}"
            f" ({band.accuracy:.1%})"
        )
    return lines


def render_text(
    summary: SummaryMetrics,
    evaluations: Sequence[FixtureEvaluation],
) -> str:
    """Render the design-spec Phase 9 shape (with counts alongside)."""
    order = ("laboratory", "appointment", "prescription", "other")
    lines = [
        f"Documents: {summary.documents}",
        "",
        f"Accuracy:          {summary.accuracy:.1%} ({summary.correct}/{summary.documents})",
    ]
    for expected_type in order:
        if expected_type in summary.recall:
            correct, total = summary.recall[expected_type]
            rate = correct / total if total else 0.0
            lines.append(
                f"{expected_type.capitalize()} recall: {rate:.1%} ({correct}/{total})"
            )
    lines.append(_rate_line("Wrong schema", summary.wrong_schema, summary.documents))
    lines.append(_rate_line("Generic fallback", summary.generic_fallback, summary.documents))
    lines.append(_rate_line("Ambiguous", summary.ambiguous, summary.documents))
    lines.append(
        _rate_line("False laboratory", summary.false_laboratory, summary.documents)
    )
    lines.append("")
    lines.extend(_metrics_lines(compute_metrics(evaluations)))
    lines.append("")
    lines.extend(_confidence_lines(compute_confidence_stats(evaluations), summary))
    lines.append("")

    for evaluation in evaluations:
        lines.append(f"== {evaluation.fixture.file} ({evaluation.fixture.source})")
        lines.extend(_detail_lines(evaluation))
        lines.append("")
    return "\n".join(lines).rstrip()


def render_markdown(
    summary: SummaryMetrics,
    evaluations: Sequence[FixtureEvaluation],
    *,
    classifier_version: str,
    manifest_path: Path,
) -> str:
    """Render a human-readable Markdown evaluation report."""
    lines = ["# Classification 2.0 — Evaluation report", ""]
    lines.append(f"- generated: {date.today().isoformat()}")
    lines.append(f"- manifest: `{manifest_path}` (version 1.0.0)")
    lines.append(f"- classifier: `{classifier_version}`")
    lines.append(f"- Documents: {summary.documents}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Accuracy | {summary.accuracy:.1%} ({summary.correct}/{summary.documents}) |")
    for expected_type, (correct, total) in sorted(summary.recall.items()):
        rate = correct / total if total else 0.0
        lines.append(f"| {expected_type.capitalize()} recall | {rate:.1%} ({correct}/{total}) |")
    lines.append(f"| Wrong schema | {summary.wrong_schema} |")
    lines.append(f"| Generic fallback | {summary.generic_fallback} |")
    lines.append(f"| Ambiguous | {summary.ambiguous} |")
    lines.append(f"| False laboratory | {summary.false_laboratory} |")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    metrics = compute_metrics(evaluations)
    lines.append("| Type | TP | FP | FN | Precision | Recall | F1 | Support |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for document_type, type_metrics in metrics.per_type.items():
        lines.append(
            f"| {document_type} | {type_metrics.tp} | {type_metrics.fp}"
            f" | {type_metrics.fn} | {type_metrics.precision:.3f}"
            f" | {type_metrics.recall:.3f} | {type_metrics.f1:.3f}"
            f" | {type_metrics.support} |"
        )
    lines.append(
        f"| **macro** |  |  |  | {metrics.macro.precision:.3f}"
        f" | {metrics.macro.recall:.3f} | {metrics.macro.f1:.3f} |  |"
    )
    lines.append(
        f"| **micro** |  |  |  | {metrics.micro.precision:.3f}"
        f" | {metrics.micro.recall:.3f} | {metrics.micro.f1:.3f} |  |"
    )
    lines.append("")
    lines.append("## Confidence")
    lines.append("")
    stats = compute_confidence_stats(evaluations)
    lines.append(
        f"- min `{stats.minimum:.2f}` / mean `{stats.mean:.2f}`"
        f" / max `{stats.maximum:.2f}`"
        f" — saturated at 1.00: {stats.saturated_at_one}/{summary.documents}"
    )
    lines.append(
        "- distribution: "
        + ", ".join(f"`{label}` {count}" for label, count in stats.distribution.items())
    )
    lines.append("")
    lines.append("| Band | Correct | Total | Accuracy |")
    lines.append("|---|---|---|---|")
    for band in stats.reliability:
        lines.append(
            f"| {band.band} | {band.correct} | {band.total} | {band.accuracy:.1%} |"
        )
    lines.append("")
    lines.append("## Per-fixture")
    lines.append("")
    for evaluation in evaluations:
        mark = "MATCH" if not evaluation.misfit else "MISMATCH"
        lines.append(f"### `{evaluation.fixture.file}` ({evaluation.fixture.source}) — {mark}")
        lines.append("")
        lines.append(f"- expected: `{evaluation.type_expected}/"
                     f"{evaluation.subtype_expected or '-'}/{evaluation.decision_expected}`")
        lines.append(f"- predicted: `{evaluation.type_predicted}/"
                     f"{evaluation.subtype_predicted or '-'}/{evaluation.decision_predicted}`")
        lines.append(f"- confidence: `{evaluation.confidence:.2f}` "
                     f"({evaluation.confidence_level.value})")
        lines.append(f"- margin: `{evaluation.margin:.1f}` "
                     f"(top `{evaluation.top:.1f}`, second `{evaluation.second:.1f}`)")
        lines.append(f"- per-type: `{_per_type_line(evaluation.per_type)}`")
        lines.append(f"- signals: {_signals_line(evaluation.signals)}")
        lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Counts are shown alongside rates; at N=11 percentages are coarse "
                 "(1 document ≈ 9%) and gates resume percentage-based targets when the "
                 "real-marker set grows past ~50.")
    lines.append("")
    return "\n".join(lines)


def _to_json(
    summary: SummaryMetrics,
    evaluations: Sequence[FixtureEvaluation],
    *,
    classifier_version: str,
    manifest_path: Path,
) -> dict[str, Any]:
    return {
        "classifier_version": classifier_version,
        "manifest_version": "1.0.0",
        "manifest_path": str(manifest_path),
        "generated": date.today().isoformat(),
        "summary": {
            "documents": summary.documents,
            "correct": summary.correct,
            "accuracy": summary.accuracy,
            "recall": {
                expected: {"correct": correct, "total": total}
                for expected, (correct, total) in sorted(summary.recall.items())
            },
            "wrong_schema": summary.wrong_schema,
            "generic_fallback": summary.generic_fallback,
            "ambiguous": summary.ambiguous,
            "false_laboratory": summary.false_laboratory,
        },
        "metrics": compute_metrics(evaluations).model_dump(),
        "domain": compute_domain_rates(evaluations).model_dump(),
        "confidence": compute_confidence_stats(evaluations).model_dump(),
        "evaluations": [
            {
                "file": evaluation.fixture.file,
                "source": evaluation.fixture.source,
                "expected": {
                    "type": evaluation.type_expected,
                    "subtype": evaluation.subtype_expected,
                    "decision": evaluation.decision_expected,
                },
                "predicted": {
                    "type": evaluation.type_predicted,
                    "subtype": evaluation.subtype_predicted,
                    "decision": evaluation.decision_predicted,
                },
                "confidence": evaluation.confidence,
                "confidence_level": evaluation.confidence_level.value,
                "margin": evaluation.margin,
                "top": evaluation.top,
                "second": evaluation.second,
                "per_type": evaluation.per_type,
                "signals": [
                    {
                        "name": signal.name,
                        "weight": signal.weight,
                        "matched": signal.matched,
                        "matches": signal.matches,
                        "score": signal.score,
                    }
                    for signal in evaluation.signals
                ],
                "reasons": evaluation.reasons,
                "correct": evaluation.is_correct,
            }
            for evaluation in evaluations
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="app.classification.evaluate",
        description="Evaluate the rule-based classifier on the regression fixtures.",
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

    evaluations = run_evaluation()
    summary = summarize(evaluations)
    version = evaluations[0].classifier_version if evaluations else "unknown"

    if args.json:
        payload = _to_json(
            summary,
            evaluations,
            classifier_version=version,
            manifest_path=MANIFEST_PATH,
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False))
    else:
        print(render_text(summary, evaluations))

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_markdown(
                summary,
                evaluations,
                classifier_version=version,
                manifest_path=MANIFEST_PATH,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())