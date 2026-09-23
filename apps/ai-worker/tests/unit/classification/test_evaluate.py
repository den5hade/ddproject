"""Phase 1: evaluation core (CLI + app-owned loader) tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.classification.evaluate import (
    FixtureEvaluation,
    compute_confidence_stats,
    compute_domain_rates,
    compute_metrics,
    evaluate_fixture,
    main,
    render_markdown,
    render_text,
    run_evaluation,
    summarize,
)
from app.classification.fixtures import (
    ClassificationFixture,
    iter_classification_fixtures,
)
from app.classification.models import (
    ClassificationConfidenceLevel,
    ClassificationDecision,
    DocumentType,
)

APP_ROOT = Path(__file__).resolve().parents[3]


def _fixture(name: str) -> ClassificationFixture:
    for fixture in iter_classification_fixtures():
        if fixture.file == name:
            return fixture
    raise AssertionError(f"no fixture named {name!r}")


def test_known_fixture_hematology_accept():
    evaluation = run_evaluation([_fixture("laboratory/fbbcb675.md")])[0]
    assert evaluation.type_predicted == "laboratory"
    assert evaluation.subtype_predicted == "hematology"
    assert evaluation.decision_predicted == "accept"
    assert evaluation.type_match and evaluation.subtype_match and evaluation.decision_match
    assert evaluation.is_correct


def test_known_fixture_appointment_accept():
    evaluation = run_evaluation([_fixture("appointment/2b8fdd0d.md")])[0]
    assert evaluation.type_predicted == "appointment"
    assert evaluation.decision_predicted == "accept"
    assert evaluation.is_correct


def test_known_fixture_other_fallback():
    evaluation = run_evaluation([_fixture("other/generic_001.md")])[0]
    assert evaluation.type_predicted == "other"
    assert evaluation.decision_predicted == "fallback"
    assert evaluation.is_correct


def test_known_fixture_via_async_api():
    async def evaluate_one():
        return await evaluate_fixture(_fixture("laboratory/b8f07559.md"))

    import asyncio

    evaluation = asyncio.run(evaluate_one())
    assert evaluation.type_predicted == "laboratory"
    assert evaluation.subtype_predicted == "biochemistry"
    assert evaluation.is_correct


def test_known_fixture_helix_microbiology_subtype():
    """M3 (2.1.0, finding F2): Helix culture result subtypes as microbiology."""
    evaluation = run_evaluation([_fixture("laboratory/datalab-output-helix_3_photo.jpeg.md")])[0]
    assert evaluation.type_predicted == "laboratory"
    assert evaluation.subtype_predicted == "microbiology"
    assert evaluation.decision_predicted == "accept"
    assert evaluation.is_correct


def test_all_eleven_fixtures_evaluate():
    evaluations = run_evaluation()
    assert len(evaluations) == 11
    assert all(0.0 <= evaluation.confidence <= 1.0 for evaluation in evaluations)
    summary = summarize(evaluations)
    assert summary.accuracy >= 0.95


def test_manifest_is_ground_truth_for_baseline():
    evaluations = run_evaluation()
    summary = summarize(evaluations)
    assert summary.wrong_schema == 0
    assert summary.ambiguous == 0
    assert summary.false_laboratory == 0
    assert summary.generic_fallback == 0
    assert summary.recall["laboratory"] == (6, 6)
    assert summary.recall["appointment"] == (2, 2)
    # Synthetic false-generic probe stays a fallback by design.
    assert summary.recall["other"] == (2, 2)


def test_render_text_phase9_shape():
    evaluations = run_evaluation()
    summary = summarize(evaluations)
    text = render_text(summary, evaluations)
    assert "Documents: 11" in text
    assert "Accuracy:" in text
    assert "Laboratory recall:" in text
    assert "Appointment recall:" in text
    assert "Wrong schema:" in text
    assert "Generic fallback:" in text
    assert "Ambiguous:" in text
    assert "False laboratory:" in text
    assert "== laboratory/fbbcb675.md (real)" in text


def test_render_markdown_report():
    evaluations = run_evaluation()
    summary = summarize(evaluations)
    report = render_markdown(
        summary,
        evaluations,
        classifier_version="2.0.0",
        manifest_path=_fixture("laboratory/fbbcb675.md").path,
    )
    assert report.startswith("# Classification")
    assert "## Summary" in report
    assert "## Metrics" in report
    assert "## Confidence" in report
    assert "## Per-fixture" in report
    assert "fbbcb675.md" in report
    assert "Laboratory recall" in report


def test_cli_json(capsys):
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["classifier_version"] == "2.1.0"
    assert payload["summary"]["documents"] == 11
    assert payload["evaluations"][0]["file"] == "laboratory/fbbcb675.md"


def test_cli_stdout_summary(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "Documents: 11" in out
    assert "fbbcb675.md" in out


def test_cli_report_writes_markdown(tmp_path):
    report_path = tmp_path / "eval.md"
    assert main(["--report", str(report_path)]) == 0
    assert report_path.is_file()
    content = report_path.read_text(encoding="utf-8")
    assert content.startswith("# Classification")
    assert "Documents: 11" in content


def test_evaluate_module_imports_no_tests_package():
    """The app-owned eval tool must not depend on anything under ``tests.*``."""
    code = (
        "import sys\n"
        "import app.classification.evaluate\n"
        "bad = sorted(m for m in sys.modules if m == 'tests' or m.startswith('tests.'))\n"
        "if bad:\n"
        "    raise SystemExit('evaluate pulled in tests.*: ' + repr(bad))\n"
    )
    env = {**os.environ, "PYTHONPATH": APP_ROOT}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "name",
    [fixture.file for fixture in iter_classification_fixtures()],
    ids=lambda name: name,
)
def test_fixture_has_resolved_path(name):
    fixture = _fixture(name)
    assert fixture.path.is_file()
    assert fixture.path.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Phase 2 — metrics (pure functions over hand-built evaluation sets)
# ---------------------------------------------------------------------------


def _ev(
    expected_type: str,
    predicted_type: str,
    *,
    confidence: float = 1.0,
    expected_decision: str = "accept",
    predicted_decision: str = "accept",
) -> FixtureEvaluation:
    """A hand-built evaluation record for metrics unit tests."""
    fixture = ClassificationFixture(
        file=f"{expected_type}/hand_built.md",
        path=Path("hand_built.md"),
        source="synthetic",
        expected_type=expected_type,
        expected_subtype=None,
        expected_decision=expected_decision,
    )
    if confidence >= 0.9:
        level = ClassificationConfidenceLevel.HIGH
    elif confidence >= 0.7:
        level = ClassificationConfidenceLevel.MEDIUM
    else:
        level = ClassificationConfidenceLevel.LOW
    return FixtureEvaluation(
        fixture=fixture,
        document_type=DocumentType(predicted_type),
        document_subtype=None,
        decision=ClassificationDecision(predicted_decision),
        confidence=confidence,
        confidence_level=level,
        margin=10.0,
        top=20.0,
        second=10.0,
        per_type={},
        signals=[],
        classifier_version="2.0.0",
    )


def _hand_built() -> list[FixtureEvaluation]:
    return [
        _ev("laboratory", "laboratory", confidence=1.0),  # a correct
        _ev("laboratory", "laboratory", confidence=0.95),  # b correct
        _ev("laboratory", "appointment", confidence=0.9),  # c wrong schema
        _ev("appointment", "appointment", confidence=0.8),  # d correct
        _ev(
            "other", "other", confidence=0.0,
            expected_decision="fallback", predicted_decision="fallback",
        ),  # e correct
        _ev("other", "laboratory", confidence=0.75),  # f false laboratory
        _ev(
            "prescription", "other", confidence=0.0,
            predicted_decision="fallback",
        ),  # g unexpected generic
        _ev(
            "laboratory", "laboratory", confidence=0.75,
            predicted_decision="ambiguous",
        ),  # h type-correct, decision mismatch
    ]


def test_per_type_metrics_hand_built():
    metrics = compute_metrics(_hand_built())
    assert metrics.documents == 8
    assert metrics.accuracy == 0.5  # a,b,d,e correct only
    assert set(metrics.per_type) == {"laboratory", "appointment", "other", "prescription"}

    lab = metrics.per_type["laboratory"]
    assert (lab.tp, lab.fp, lab.fn, lab.support) == (3, 1, 1, 4)
    assert lab.precision == 0.75
    assert lab.recall == 0.75
    assert lab.f1 == pytest.approx(0.75)

    appt = metrics.per_type["appointment"]
    assert (appt.tp, appt.fp, appt.fn, appt.support) == (1, 1, 0, 1)
    assert appt.precision == 0.5
    assert appt.recall == 1.0
    assert appt.f1 == pytest.approx(2 / 3)

    other = metrics.per_type["other"]
    assert (other.tp, other.fp, other.fn) == (1, 1, 1)
    assert other.precision == 0.5 and other.recall == 0.5 and other.f1 == 0.5

    presc = metrics.per_type["prescription"]  # never predicted
    assert (presc.tp, presc.fp, presc.fn, presc.support) == (0, 0, 1, 1)
    assert presc.precision == 0.0 and presc.recall == 0.0 and presc.f1 == 0.0

    assert metrics.macro.precision == pytest.approx(1.75 / 4)
    assert metrics.macro.recall == pytest.approx(2.25 / 4)
    assert metrics.micro.precision == pytest.approx(5 / 8)
    assert metrics.micro.recall == pytest.approx(5 / 8)
    assert metrics.micro.f1 == pytest.approx(5 / 8)


def test_domain_rates_hand_built():
    domain = compute_domain_rates(_hand_built())
    assert domain.wrong_schema.count == 1  # laboratory → appointment only
    assert domain.generic.count == 1  # prescription → other
    assert domain.ambiguous.count == 1  # predicted decision ambiguous
    assert domain.false_laboratory.count == 1  # other → laboratory
    assert domain.wrong_schema.rate == pytest.approx(0.125)
    assert domain.generic_rate == pytest.approx(0.125)
    assert domain.ambiguous_rate == pytest.approx(0.125)
    assert domain.false_laboratory_rate == pytest.approx(0.125)


def test_confidence_stats_hand_built():
    stats = compute_confidence_stats(_hand_built())
    assert stats.minimum == 0.0
    assert stats.maximum == 1.0
    assert stats.mean == pytest.approx(5.15 / 8)
    assert stats.saturated_at_one == 1
    assert stats.distribution == {"0.90-1.00": 3, "0.70-0.90": 3, "0.00-0.70": 2}

    high, medium, low = stats.reliability
    assert (high.band, high.correct, high.total) == ("0.90-1.00", 2, 3)
    assert high.accuracy == pytest.approx(2 / 3)
    assert (medium.band, medium.correct, medium.total) == ("0.70-0.90", 1, 3)
    assert (low.band, low.correct, low.total) == ("0.00-0.70", 1, 2)


def test_metrics_on_real_dataset():
    evaluations = run_evaluation()
    metrics = compute_metrics(evaluations)
    assert metrics.documents == 11
    assert metrics.accuracy == 1.0
    assert metrics.macro.f1 == 1.0
    assert metrics.micro.f1 == 1.0
    assert sorted(type_metrics.support for type_metrics in metrics.per_type.values()) == [
        1,
        2,
        2,
        6,
    ]

    domain = compute_domain_rates(evaluations)
    for count_rate in (
        domain.wrong_schema,
        domain.generic,
        domain.ambiguous,
        domain.false_laboratory,
    ):
        assert count_rate.count == 0

    confidence = compute_confidence_stats(evaluations)
    assert confidence.minimum == 0.0
    assert confidence.maximum == 1.0
    assert confidence.saturated_at_one == 6
    assert confidence.distribution["0.00-0.70"] == 2  # the two fallbacks
    assert all(band.accuracy == 1.0 for band in confidence.reliability if band.total)


def test_cli_json_phase2_sections(capsys):
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["metrics"]["accuracy"] == 1.0
    assert payload["metrics"]["per_type"]["laboratory"]["support"] == 6
    assert payload["domain"]["wrong_schema"] == {"count": 0, "rate": 0.0}
    assert payload["confidence"]["saturated_at_one"] == 6


def test_cli_json_metrics_match_ground_truth_counts(capsys):
    """Phase 4: run the CLI module and assert metrics equal ground-truth counts."""
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    expected_support = {"laboratory": 6, "appointment": 2, "prescription": 1, "other": 2}
    per_type = payload["metrics"]["per_type"]
    assert {name: metrics["support"] for name, metrics in per_type.items()} == expected_support
    for name, metrics in per_type.items():
        assert metrics["tp"] == metrics["support"], name
        assert (metrics["fp"], metrics["fn"]) == (0, 0)

    assert payload["domain"] == {
        key: {"count": 0, "rate": 0.0}
        for key in ("wrong_schema", "generic", "ambiguous", "false_laboratory")
    }
    assert payload["confidence"]["distribution"] == {
        "0.90-1.00": 9,
        "0.70-0.90": 0,
        "0.00-0.70": 2,
    }


def test_render_text_includes_metrics_and_confidence():
    evaluations = run_evaluation()
    text = render_text(summarize(evaluations), evaluations)
    assert "Per-type metrics:" in text
    assert "macro" in text and "micro" in text
    assert "Confidence:" in text
    assert "saturated@1.00:" in text
    assert "Reliability by band:" in text