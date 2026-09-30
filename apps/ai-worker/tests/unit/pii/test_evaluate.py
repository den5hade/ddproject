"""Phase 1: the offline PII evaluation CLI and its document-level metrics.

Four kinds of test live here, and the split is deliberate:

* **The hand-audited fixtures** — the three rows the plan names, asserted
  against the numbers a human read off the source text. These are the tests that
  would catch a detector regression, and they are written as literals rather
  than read back from the manifest, because a test that compares the evaluator
  to the manifest the evaluator was pointed at proves only that the file parses.
* **The JSON contract** — both dataset blocks present, and the absent corpus
  carrying *no* ``metrics`` key at all. A synthesised empty block would read as a
  measurement of zero, which is the false precision the plan rules out.
* **Determinism** — two runs byte-identical, which is the property that makes
  the report reviewable.
* **The loader seam** — the subprocess checks that ``app.pii.evaluate`` imports
  no ``tests.*`` package and that nothing under ``.dev/`` is read when
  ``PII_FIXTURES_DIR`` is unset.

Per-category precision/recall and per-detector attribution are Phase 2. What is
here is the document-level view Phase 1 promises, and the tests below hold that
line rather than reaching for a metric that does not exist yet.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.pii.evaluate import (
    BOUNDARY_CANONICAL_PERSISTENCE,
    BOUNDARY_DOCUMENT_EXTERNAL,
    BOUNDARY_DOCUMENT_INTERNAL,
    EVALUATION_VERSION,
    CountRate,
    DatasetEvaluation,
    EvaluationReport,
    FixtureEvaluation,
    PIIMetrics,
    compute_metrics,
    evaluate_fixture,
    main,
    render_markdown,
    render_text,
    run_evaluation,
    summarize,
)
from app.pii.fixtures import (
    CONTOUR_DOCUMENT,
    DATASET_SYNTHETIC,
    iter_canonical_fixtures,
    iter_pii_fixtures,
)
from app.pii.models import PIICategory, PIIDecision, PIIRiskLevel

APP_ROOT = Path(__file__).resolve().parents[3]

_REPORT = run_evaluation()
_SYNTHETIC = _REPORT.dataset(DATASET_SYNTHETIC)
_BY_ID = {evaluation.id: evaluation for evaluation in _SYNTHETIC.evaluations}


def _row(fixture_id: str, boundary: str):
    """The one row of one fixture, by id and boundary, failing loudly if absent."""
    evaluation = _BY_ID[fixture_id]
    matches = [row for row in evaluation.boundaries if row.boundary == boundary]
    assert len(matches) == 1, (fixture_id, boundary, [r.boundary for r in evaluation.boundaries])
    return matches[0]


# ---------------------------------------------------------------------------
# the three hand-audited fixtures
# ---------------------------------------------------------------------------


def test_patient_fixture_finds_seven_categories_and_reviews_at_the_external_boundary():
    # The plan's own worked example, written out rather than derived: seven
    # categories, and `review` — not `allow` — once the destination is external
    # and no redactor is available.
    row = _row("patient-synthetic-consultation-01", BOUNDARY_DOCUMENT_EXTERNAL)
    assert len(row.expected_categories) == 7
    assert row.predicted_categories == tuple(
        sorted(
            {
                PIICategory.ADDRESS,
                PIICategory.DATE_OF_BIRTH,
                PIICategory.DOCTOR_NAME,
                PIICategory.EMAIL,
                PIICategory.MEDICAL_RECORD_NUMBER,
                PIICategory.PERSON_NAME,
                PIICategory.PHONE,
            },
            key=lambda c: c.value,
        )
    )
    assert row.exact_set_match
    assert row.decision == PIIDecision.REVIEW.value
    assert row.risk_level == PIIRiskLevel.HIGH.value


def test_patient_fixture_allows_at_the_internal_boundary():
    # The same bytes, the same eight findings, a different decision — which is
    # the entire reason this harness scores boundaries rather than fixtures.
    row = _row("patient-synthetic-consultation-01", BOUNDARY_DOCUMENT_INTERNAL)
    assert (
        row.predicted_categories
        == _row(
            "patient-synthetic-consultation-01", BOUNDARY_DOCUMENT_EXTERNAL
        ).predicted_categories
    )
    assert row.decision == PIIDecision.ALLOW.value


def test_appointment_fixture_finds_the_name_and_the_ticket_and_nothing_else():
    # The locked acceptance pair, and the constraint is on the fixture: a
    # declined booking collected nothing, so the rows that would add a category
    # (СНИЛС, Полис, дата рождения, адрес, ФИО врача) are absent by design.
    row = _row("appointment-synthetic-registration-01", BOUNDARY_DOCUMENT_EXTERNAL)
    assert row.predicted_categories == (
        PIICategory.PERSON_NAME.value,
        PIICategory.TICKET_NUMBER.value,
    )
    assert row.exact_set_match
    assert not row.spurious_categories


def test_malicious_fixture_blocks_on_the_secret_and_still_reports_the_ticket():
    # `ticket_number` is a known false positive: the 28-digit API key is one
    # unbroken digit run and `pattern.ticket_number.long_digits` claims any run
    # of twelve or more. It is recorded rather than hidden, so the row has to
    # carry both the spurious category and the blocking decision.
    row = _row("malicious-synthetic-injection-01", BOUNDARY_DOCUMENT_EXTERNAL)
    assert row.predicted_categories == (
        PIICategory.SECRET.value,
        PIICategory.TICKET_NUMBER.value,
    )
    assert row.exact_set_match
    assert row.decision == PIIDecision.BLOCK.value
    assert row.risk_level == PIIRiskLevel.CRITICAL.value
    assert row.halted


def test_clean_fixture_finds_nothing_and_allows_at_every_boundary():
    for boundary in (BOUNDARY_DOCUMENT_INTERNAL, BOUNDARY_DOCUMENT_EXTERNAL):
        row = _row("clean-generic-notice-01", boundary)
        assert row.predicted_categories == ()
        assert row.decision == PIIDecision.ALLOW.value
        assert row.findings_count == 0


def test_a_service_date_is_not_pii():
    # Worth its own line because it is the fixture's reason for existing: the
    # maintenance date must not be claimed as a date of birth. There is no
    # service-date category at all, so the assertion that matters is that the
    # only date category in the taxonomy stays unfound.
    row = _row("clean-generic-notice-01", BOUNDARY_DOCUMENT_EXTERNAL)
    assert PIICategory.DATE_OF_BIRTH.value not in row.predicted_categories
    assert {c.value for c in PIICategory if "date" in c.value} == {"date_of_birth"}


def test_the_ticket_false_positive_is_attributed_to_the_digit_pattern():
    # The manifest expects the structured layer for `ticket_number` on the
    # appointment fixture; on the malicious one the only evidence is the digit
    # run, so the attribution is where the R7-shaped mistake shows up.
    row = _row("malicious-synthetic-injection-01", BOUNDARY_DOCUMENT_EXTERNAL)
    claimants = {d for d, cats in row.detector_attribution.items() if "ticket_number" in cats}
    assert claimants == {"pattern.ticket_number.long_digits"}


def test_canonical_fixtures_are_scored_at_the_persistence_boundary():
    # Contour 2 is a different boundary with a different redaction story, so a
    # canonical row must never be confused for a document row.
    for evaluation in _SYNTHETIC.evaluations:
        if evaluation.contour == CONTOUR_DOCUMENT:
            continue
        assert len(evaluation.boundaries) == 1
        row = evaluation.boundaries[0]
        assert row.boundary == BOUNDARY_CANONICAL_PERSISTENCE
        assert row.destination == "persistence"
        assert row.decision == PIIDecision.ALLOW_WITH_WARNING.value
        assert row.leaf_paths, "a canonical finding must name the leaf it was found on"


def test_canonical_doctor_name_is_detected_but_not_masked():
    # §4.12: practitioner and organization names stay ALLOW-actioned at every
    # destination, because blanking them would destroy the note. A row that
    # reported `doctor_name` as masked would mean the remediation table changed.
    row = _row("appointment-synthetic-registration-note-01", BOUNDARY_CANONICAL_PERSISTENCE)
    assert PIICategory.DOCTOR_NAME.value in row.predicted_categories
    assert row.actions[PIICategory.DOCTOR_NAME.value] == "allow"
    assert PIICategory.DOCTOR_NAME.value not in row.over_redacted


def test_every_committed_fixture_is_evaluated_at_every_boundary_it_has():
    for evaluation in _SYNTHETIC.evaluations:
        expected = 2 if evaluation.contour == CONTOUR_DOCUMENT else 1
        assert len(evaluation.boundaries) == expected, evaluation.id
        assert len({row.boundary for row in evaluation.boundaries}) == expected, evaluation.id


def test_the_synthetic_corpus_scores_perfectly_on_categories():
    # Not a regression gate (Phase 4 owns those) but a canary: a non-perfect
    # number here means a detector moved without the manifest being re-audited.
    metrics = _SYNTHETIC.metrics
    assert metrics.exact_set_match == CountRate(count=metrics.boundaries, rate=1.0)
    assert metrics.spurious_categories == 0
    assert metrics.missed_categories == 0
    assert metrics.over_redacted_categories == 0


def test_the_two_internal_rows_carry_the_documented_decision_mismatch():
    # `expected_decision` in the manifest is written against the external
    # boundary, so the two document rows evaluated at the internal boundary
    # cannot match it. Asserted as a fact about the data rather than tolerated
    # as a fudge, because the moment it stops being 2 the manifest's stated
    # context has drifted from the harness.
    mismatched = [
        (evaluation.id, row.boundary)
        for evaluation in _SYNTHETIC.evaluations
        for row in evaluation.boundaries
        if not row.decision_match
    ]
    assert sorted(mismatched) == [
        ("appointment-synthetic-registration-01", BOUNDARY_DOCUMENT_INTERNAL),
        ("patient-synthetic-consultation-01", BOUNDARY_DOCUMENT_INTERNAL),
    ]


# ---------------------------------------------------------------------------
# metrics over hand-built sets (exact fractions, M3 Phase 2 pattern)
# ---------------------------------------------------------------------------


def _metrics_of(evaluations) -> PIIMetrics:
    return compute_metrics(evaluations)


def test_count_rate_carries_the_count_beside_the_rate():
    # Both corpora are small enough that a bare percentage is a statement about
    # two data points, so the count is part of the metric rather than decoration.
    assert _SYNTHETIC.metrics.exact_set_match.count == 10
    assert _SYNTHETIC.metrics.exact_set_match.rate == 1.0


def test_rendered_rates_are_counts_over_rows_never_percentages_alone(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "10/10" in out
    assert "Exact set match : 10/10" in out


def test_metrics_counts_every_boundary_row():
    assert _SYNTHETIC.metrics.boundaries == sum(len(e.boundaries) for e in _SYNTHETIC.evaluations)
    assert _SYNTHETIC.metrics.documents == 4
    assert _SYNTHETIC.metrics.canonical_payloads == 2


def test_metrics_is_pure_in_its_input():
    first = compute_metrics(_SYNTHETIC.evaluations)
    second = compute_metrics(_SYNTHETIC.evaluations)
    assert first == second


def test_metrics_of_no_evaluations_is_all_zeros_not_an_error():
    # An empty corpus is a real state (a local manifest that lists nothing), and
    # it must not divide by zero or raise.
    empty = compute_metrics(())
    assert empty.boundaries == 0
    assert empty.exact_set_match == CountRate(count=0, rate=0.0)
    assert empty.decisions == {}


def test_summarize_is_also_dataset_blind():
    # The plan's hard rule, and the reason it is worth its own test: the same
    # evaluation set must summarize identically no matter which corpus it is
    # labelled as, or the real corpus could acquire its own denominator.
    relabelled = tuple(
        FixtureEvaluation(dataset="real_corpus", fixture=e.fixture, boundaries=e.boundaries)
        for e in _SYNTHETIC.evaluations
    )
    assert summarize(relabelled) == summarize(_SYNTHETIC.evaluations)
    assert compute_metrics(relabelled) == compute_metrics(_SYNTHETIC.evaluations)


def test_summarize_matches_the_metrics_it_summarizes():
    summary = summarize(_SYNTHETIC.evaluations)
    metrics = _SYNTHETIC.metrics
    assert summary.boundaries == metrics.boundaries
    assert summary.exact_set_match == metrics.exact_set_match.count
    assert summary.spurious_categories == metrics.spurious_categories


# ---------------------------------------------------------------------------
# the JSON contract
# ---------------------------------------------------------------------------


def test_cli_json_carries_both_dataset_blocks(capsys):
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["datasets"]) == {DATASET_SYNTHETIC, "real_corpus"}
    assert payload["evaluation_version"] == EVALUATION_VERSION
    assert payload["detector_version"] == "1.2.0"
    assert payload["policy_version"] == "3.0.0"


def test_cli_json_marks_the_absent_corpus_without_a_metrics_key(capsys, monkeypatch):
    monkeypatch.delenv("PII_FIXTURES_DIR", raising=False)
    assert main(["--json"]) == 0
    real = json.loads(capsys.readouterr().out)["datasets"]["real_corpus"]
    assert real["available"] is False
    assert "metrics" not in real, "an absent corpus must not carry a synthesised zero block"
    assert "reason" in real
    assert real["reason"]


def test_cli_json_reports_every_committed_fixture(capsys):
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    ids = {e["id"] for e in payload["datasets"][DATASET_SYNTHETIC]["evaluations"]}
    expected = {f.id for f in iter_pii_fixtures()} | {f.id for f in iter_canonical_fixtures()}
    assert ids == expected
    assert len(ids) == 6


def test_cli_json_rows_carry_expected_and_predicted_side_by_side(capsys):
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    row = payload["datasets"][DATASET_SYNTHETIC]["evaluations"][0]["boundaries"][0]
    assert set(row["expected"]) == {"categories", "decision", "detector_source"}
    assert set(row["predicted"]) == {"categories", "decision", "risk_level"}


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def test_render_text_names_the_versions_and_both_corpora(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert f"detector {EVALUATION_VERSION}" not in out  # versions are listed separately
    assert "detector 1.2.0" in out
    assert "policy 3.0.0" in out
    assert "synthetic_regression" in out
    assert "real_corpus" in out


def test_render_text_says_no_metrics_for_the_absent_corpus(capsys, monkeypatch):
    monkeypatch.delenv("PII_FIXTURES_DIR", raising=False)
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "NOT EVALUATED" in out
    assert "No metrics" in out


def test_render_markdown_states_availability_in_its_header():
    markdown = render_markdown(_REPORT)
    assert markdown.startswith("# PII")
    assert "synthetic_regression" in markdown
    assert "**Not evaluated.**" in markdown
    assert "No metrics are published for this corpus" in markdown


def test_render_markdown_has_a_row_per_boundary():
    markdown = render_markdown(_REPORT)
    for evaluation in _SYNTHETIC.evaluations:
        for row in evaluation.boundaries:
            assert row.boundary in markdown
            assert evaluation.id in markdown


def test_render_text_and_markdown_do_not_crash_on_an_empty_dataset():
    # A local manifest that lists nothing is a real state, and the renderers
    # must not divide by zero or index into an empty block while saying so.
    empty = DatasetEvaluation(
        name="empty", source="local-only", available=True, root=APP_ROOT, evaluations=()
    )
    report = EvaluationReport(datasets=(empty,))
    assert empty.metrics.boundaries == 0
    assert "empty" in render_text(report)
    assert "empty" in render_markdown(report)


def test_cli_report_writes_markdown(tmp_path):
    report_path = tmp_path / "eval.md"
    assert main(["--report", str(report_path)]) == 0
    assert report_path.is_file()
    assert report_path.read_text(encoding="utf-8").startswith("# PII")


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_two_runs_are_byte_identical(capsys):
    assert main(["--json"]) == 0
    first = capsys.readouterr().out
    assert main(["--json"]) == 0
    second = capsys.readouterr().out
    assert first == second


def test_evaluation_is_reproducible_across_fresh_harnesses():
    # A fresh `run_evaluation` rebuilds the detector chain and the guard, so
    # this catches state that survives between runs — a cached fingerprint, a
    # module-level accumulator, a detector holding per-instance state. Compared
    # as rendered JSON because that is the artifact the determinism claim is
    # about; a structural comparison would need to deepcopy the frozen
    # `expected_detector_source` mappings, which `asdict` cannot do.
    first = _json_of(run_evaluation())
    second = _json_of(run_evaluation())
    assert first == second


def _json_of(report: EvaluationReport) -> str:
    return render_markdown(report)


def test_detector_and_policy_versions_are_the_locked_baseline():
    assert _REPORT.detector_version == "1.2.0"
    assert _REPORT.policy_version == "3.0.0"
    assert EVALUATION_VERSION == "1.0.0"


# ---------------------------------------------------------------------------
# the loader seam (subprocess: these are import-time and env-time properties)
# ---------------------------------------------------------------------------


def _subprocess(code: str, **env_overrides) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(APP_ROOT), **env_overrides}
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=str(APP_ROOT),
    )


def test_evaluate_module_imports_no_tests_package():
    result = _subprocess(
        "import sys\n"
        "import app.pii.evaluate\n"
        "bad = sorted(m for m in sys.modules if m == 'tests' or m.startswith('tests.'))\n"
        "if bad:\n"
        "    raise SystemExit('evaluate pulled in tests.*: ' + repr(bad))\n"
    )
    assert result.returncode == 0, result.stderr


def test_the_loader_reads_nothing_under_dot_dev_when_the_env_var_is_unset():
    # The real corpus is local-only. A default path that resolved to `.dev/`
    # would make a clean checkout's report depend on whether the developer
    # happens to have a corpus lying around — and would read a real patient's
    # document without asking.
    result = _subprocess(
        "from app.pii.fixtures import (\n"
        "    DEFAULT_LOCAL_REAL_CORPUS_DIR,\n"
        "    iter_local_real_corpus,\n"
        "    local_real_corpus_available,\n"
        ")\n"
        "assert not local_real_corpus_available()\n"
        "assert tuple(iter_local_real_corpus()) == ()\n"
        "assert '.dev' in str(DEFAULT_LOCAL_REAL_CORPUS_DIR), DEFAULT_LOCAL_REAL_CORPUS_DIR\n"
        "print('ok')\n",
        PII_FIXTURES_DIR="",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_the_json_block_for_an_absent_corpus_needs_no_corpus_on_disk():
    # Belt and braces for the same property, through the CLI's own output.
    result = _subprocess(
        "import json, sys\nfrom app.pii.evaluate import main\nmain(['--json'])\n",
        PII_FIXTURES_DIR="",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["datasets"]["real_corpus"]["available"] is False
    assert "metrics" not in payload["datasets"]["real_corpus"]


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [[], ["--json"], ["--report", "unused.md"]])
def test_main_always_returns_zero(argv, tmp_path, monkeypatch, capsys):
    # Thresholds live in pytest, as in M3: a corpus that scores badly is a
    # finding to read, not a non-zero exit that hides the rest of the report.
    monkeypatch.chdir(tmp_path)
    assert main(argv) == 0
    capsys.readouterr()


def test_evaluate_fixture_rejects_an_unknown_contour():
    fixture = next(iter(iter_pii_fixtures()))
    object.__setattr__(fixture, "contour", "not-a-contour")
    with pytest.raises(ValueError, match="unknown fixture contour"):
        evaluate_fixture(fixture, gate=None, guard=None)  # type: ignore[arg-type]


def test_evaluate_fixture_rejects_an_unknown_document_boundary():
    from app.pii.evaluate import _document_context

    with pytest.raises(ValueError, match="not a document boundary"):
        _document_context(None, "document/wherever")  # type: ignore[arg-type]
