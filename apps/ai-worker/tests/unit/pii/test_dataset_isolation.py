"""Phase 1: the two corpora stay separate, and neither one bends the metrics.

The failure this module exists to prevent is quiet. A harness that grew a
"real corpus" branch would not announce itself: the real corpus is *local-only*
and absent in CI, so a branch that only ran when ``PII_FIXTURES_DIR`` was set
would execute on a developer's machine, change the numbers, and never be seen by
the gate that is supposed to be checking them. The tests below are therefore
written against the *shape* of the code — the reduction's source, the row
model's fields — rather than only against its output, because a corpus-blind
metric and a corpus-blind metric that happens not to differ yet are the same
code.

Three properties, one per section:

* **Seam shape** — both corpora are reached through one protocol, the committed
  one never consults the environment, and the local one is inert when unset.
* **Corpus blindness** — metrics, summaries and the per-row verdicts are pure
  functions of the rows; relabelling every evaluation changes nothing.
* **Absence is not zero** — an absent corpus publishes a reason and *no*
  metrics, in both renderings and in the JSON block.

Deliberately *not* here: any assertion about the real corpus's real contents. It
does not exist in CI, so such a test would either skip everywhere or pin numbers
nobody can reproduce. Phase 3 assembles that corpus locally; Phase 4 makes it a
non-gating local run.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

from app.pii import evaluate as ev
from app.pii.evaluate import (
    BOUNDARY_DOCUMENT_EXTERNAL,
    BOUNDARY_DOCUMENT_INTERNAL,
    DatasetEvaluation,
    FixtureEvaluation,
    compute_metrics,
    default_datasets,
    evaluate_dataset,
    render_markdown,
    render_text,
    run_evaluation,
    summarize,
)
from app.pii.fixtures import (
    CONTOUR_CANONICAL,
    CONTOUR_DOCUMENT,
    DATASET_REAL_CORPUS,
    DATASET_SYNTHETIC,
    DEFAULT_LOCAL_REAL_CORPUS_DIR,
    PII_FIXTURE_DIRECTORIES,
    SYNTHETIC_FIXTURES_DIR,
    iter_canonical_fixtures,
    iter_local_real_corpus,
    iter_pii_fixtures,
    iter_synthetic_fixtures,
    local_real_corpus_available,
    local_real_corpus_dir,
    local_real_corpus_unavailable_reason,
)

APP_ROOT = Path(__file__).resolve().parents[3]


def _synthetic_block() -> DatasetEvaluation:
    return run_evaluation().dataset(DATASET_SYNTHETIC)


def _synthetic_evaluations() -> list[FixtureEvaluation]:
    return list(_synthetic_block().evaluations)


def _real_block_json(monkeypatch) -> dict:
    monkeypatch.delenv("PII_FIXTURES_DIR", raising=False)
    return ev._to_json(run_evaluation())["datasets"][DATASET_REAL_CORPUS]


# ---------------------------------------------------------------------------
# the seam: one protocol, two corpora
# ---------------------------------------------------------------------------


def test_both_corpora_are_reached_through_the_same_protocol():
    datasets = default_datasets()
    assert [d.name for d in datasets] == [DATASET_SYNTHETIC, DATASET_REAL_CORPUS]
    for dataset in datasets:
        assert isinstance(dataset, ev._LoaderDataset)
        assert isinstance(dataset.available, bool)
        assert isinstance(dataset.unavailable_reason, (str, type(None)))
        assert dataset.root is not None


def test_the_two_datasets_differ_only_in_where_fixtures_come_from():
    """One evaluation routine, not two.

    ``_LoaderDataset.iter`` is the only place a ``FixtureEvaluation`` is built,
    so a per-corpus evaluation path could only exist by overriding it — and this
    pins the two concrete classes to *not* overriding anything but the loader.
    """
    for cls in (ev.SyntheticFixtureDataset, ev.LocalRealCorpusDataset):
        assert cls.iter is ev._LoaderDataset.iter
        assert cls.fixtures is not ev._LoaderDataset.fixtures
    assert not any(
        "iter" in vars(cls) and vars(cls)["iter"] is not ev._LoaderDataset.iter
        for cls in (ev.SyntheticFixtureDataset, ev.LocalRealCorpusDataset)
    )


def test_evaluate_dataset_accepts_anything_answering_the_protocol():
    """A hand-rolled dataset needs no inheritance to be evaluated."""

    class HandRolled:
        name = "hand_rolled"
        source = "committed"
        available = True
        unavailable_reason = None
        root = SYNTHETIC_FIXTURES_DIR
        manifest_version = "2.0.0"

        def iter(self):
            # The protocol's contract is that `iter()` *evaluates*; a dataset
            # that returned raw fixtures would not be conformant.
            return ev.SyntheticFixtureDataset().iter()[:1]

    block = evaluate_dataset(HandRolled())
    assert block.name == "hand_rolled"
    assert block.metrics.boundaries == 2  # one document, both boundaries
    assert block.metrics.documents == 1


def test_the_synthetic_corpus_is_the_committed_one_and_ignores_the_environment(monkeypatch):
    monkeypatch.setenv("PII_FIXTURES_DIR", "/nonexistent/corpus")
    assert all(f.dataset == DATASET_SYNTHETIC for f in iter_synthetic_fixtures())
    assert SYNTHETIC_FIXTURES_DIR.is_dir()
    assert ev.SyntheticFixtureDataset().available


def test_the_three_committed_iterators_are_nested_not_disjoint():
    """``iter_synthetic_fixtures`` is the whole committed corpus and the other
    two are its two contours, so the dataset composes the *narrow* pair rather
    than the wide one — otherwise the canonical payloads would be counted twice
    and every denominator in the report would be wrong."""
    committed = list(iter_synthetic_fixtures())
    documents = list(iter_pii_fixtures())
    canonical = list(iter_canonical_fixtures())
    assert {f.contour for f in committed} == {CONTOUR_DOCUMENT, CONTOUR_CANONICAL}
    assert {f.contour for f in documents} == {CONTOUR_DOCUMENT}
    assert {f.contour for f in canonical} == {CONTOUR_CANONICAL}
    assert {f.id for f in documents} | {f.id for f in canonical} == {f.id for f in committed}
    assert not {f.id for f in documents} & {f.id for f in canonical}

    # The dataset uses the two narrow iterators, and gets 6 — not 8.
    assert [f.id for f in ev.SyntheticFixtureDataset().fixtures()] == [f.id for f in committed]
    assert len(ev.SyntheticFixtureDataset().iter()) == 6


def test_the_local_corpus_is_inert_when_the_variable_is_unset(monkeypatch):
    monkeypatch.delenv("PII_FIXTURES_DIR", raising=False)
    assert not local_real_corpus_available()
    assert tuple(iter_local_real_corpus()) == ()
    # The conventional directory is still *named* — it is the documented
    # convention — but it is not read, and the reason says so.
    assert local_real_corpus_dir() == DEFAULT_LOCAL_REAL_CORPUS_DIR
    assert local_real_corpus_unavailable_reason() is not None


def test_the_local_dataset_reports_absence_rather_than_emptiness(monkeypatch):
    monkeypatch.delenv("PII_FIXTURES_DIR", raising=False)
    dataset = ev.LocalRealCorpusDataset()
    assert not dataset.available
    assert dataset.iter() == []
    assert dataset.unavailable_reason == local_real_corpus_unavailable_reason()


def test_the_committed_corpus_is_never_absent_and_never_explains_itself():
    # Its absence is a broken checkout, not a missing measurement, so it must
    # not be able to take the "explain yourself" path at all.
    dataset = ev.SyntheticFixtureDataset()
    assert dataset.available
    assert dataset.unavailable_reason is None
    assert dataset.manifest_version == "2.0.0"


def test_a_malformed_local_manifest_does_not_break_the_committed_report(tmp_path, monkeypatch):
    """One bad corpus must not take the other one down with it.

    The committed corpus is the regression gate; a half-written local manifest
    must not be able to make ``make eval-pii`` fail, because that failure would
    read as a detector regression and send someone to debug the wrong thing.
    """
    (tmp_path / "manifest.json").write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("PII_FIXTURES_DIR", str(tmp_path))
    report = run_evaluation()
    assert not report.dataset(DATASET_REAL_CORPUS).available
    assert report.dataset(DATASET_REAL_CORPUS).unavailable_reason
    synthetic = report.dataset(DATASET_SYNTHETIC)
    assert synthetic.available
    assert synthetic.metrics.boundaries == 10


def test_the_local_corpus_dir_cannot_be_inside_the_committed_tree(monkeypatch):
    """A local path pointing at the committed fixtures is refused, not read.

    Otherwise a local experiment could rewrite the regression ground truth and
    the resulting report would attribute its numbers to a corpus nobody audited.
    """
    monkeypatch.setenv("PII_FIXTURES_DIR", str(SYNTHETIC_FIXTURES_DIR))
    assert not local_real_corpus_available()
    reason = local_real_corpus_unavailable_reason()
    assert "overlaps the committed fixtures" in reason
    assert run_evaluation().dataset(DATASET_REAL_CORPUS).evaluations == ()
    assert run_evaluation().dataset(DATASET_SYNTHETIC).metrics.boundaries == 10


# ---------------------------------------------------------------------------
# corpus blindness: the reduction must not know which corpus it is reading
# ---------------------------------------------------------------------------


def _identifiers_used_in(func) -> set[str]:
    """Every attribute name a function body reads, via ``self``-free AST."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(func))):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


def test_compute_metrics_never_names_the_dataset_field():
    assert "dataset" not in _identifiers_used_in(compute_metrics)


def test_summarize_never_names_the_dataset_field():
    assert "dataset" not in _identifiers_used_in(summarize)


def test_the_shared_row_reduction_never_names_the_dataset_field():
    assert "dataset" not in _identifiers_used_in(ev._rows)


def test_the_row_model_carries_no_corpus_field():
    """A row that grew a `corpus` field would let a per-corpus threshold creep
    back in at the row level, which is where the plan forbids it."""
    row = _synthetic_evaluations()[0].boundaries[0]
    assert "dataset" not in {f.name for f in fields(row)}
    assert "corpus" not in {f.name for f in fields(row)}
    assert not hasattr(row, "dataset")


def test_only_the_evaluation_record_knows_its_corpus():
    assert "dataset" in {f.name for f in fields(FixtureEvaluation)}


def test_a_corpus_of_the_same_rows_scores_the_same_under_any_name():
    synthetic = _synthetic_evaluations()
    relabelled = [
        FixtureEvaluation(dataset=DATASET_REAL_CORPUS, fixture=e.fixture, boundaries=e.boundaries)
        for e in synthetic
    ]
    assert compute_metrics(relabelled) == compute_metrics(synthetic)
    assert summarize(relabelled) == summarize(synthetic)
    assert len(relabelled) == len(synthetic)


def test_the_metrics_block_carries_no_corpus_name_of_its_own():
    """Corpus identity is carried by the block, not by the numbers inside it."""
    metrics = _synthetic_block().metrics
    assert set(metrics.model_dump()) == {
        "documents",
        "canonical_payloads",
        "boundaries",
        "exact_set_match",
        "subset_recall",
        "decision_match",
        "over_fire",
        "under_fire",
        "risk_declared_boundaries",
        "risk_match",
        "halted",
        "decisions",
        "spurious_categories",
        "missed_categories",
        "over_redacted_categories",
    }


# ---------------------------------------------------------------------------
# absence is not zero
# ---------------------------------------------------------------------------


def test_an_absent_corpus_carries_a_reason_and_no_rows(monkeypatch):
    monkeypatch.delenv("PII_FIXTURES_DIR", raising=False)
    real = run_evaluation().dataset(DATASET_REAL_CORPUS)
    assert not real.available
    assert real.evaluations == ()
    assert "PII_FIXTURES_DIR" in real.unavailable_reason
    assert real.manifest_version is None


def test_an_absent_corpus_publishes_no_metrics_in_json(monkeypatch):
    block = _real_block_json(monkeypatch)
    assert block["available"] is False
    for absent in ("metrics", "summary", "evaluations"):
        assert absent not in block, f"{absent} must not be synthesised for an absent corpus"
    assert "reason" in block


def test_a_present_corpus_publishes_metrics_in_json():
    block = ev._to_json(run_evaluation())["datasets"][DATASET_SYNTHETIC]
    assert block["available"] is True
    assert block["metrics"]["boundaries"] == 10
    assert block["summary"]["boundaries"] == 10
    assert len(block["evaluations"]) == 6


def test_the_text_renderer_says_not_evaluated_rather_than_printing_zeros(monkeypatch):
    monkeypatch.delenv("PII_FIXTURES_DIR", raising=False)
    out = render_text(run_evaluation())
    assert f"{DATASET_REAL_CORPUS}: NOT EVALUATED" in out
    assert "No metrics" in out
    # No rate line may appear in the absent corpus's own section.
    section = out.split(f"{DATASET_REAL_CORPUS}: NOT EVALUATED", 1)[1]
    assert "Exact set match" not in section.split("\n\n", 1)[0]


def test_the_markdown_renderer_says_not_evaluated(monkeypatch):
    monkeypatch.delenv("PII_FIXTURES_DIR", raising=False)
    markdown = render_markdown(run_evaluation())
    assert "**Not evaluated.**" in markdown
    assert "No metrics are published for this corpus" in markdown


def test_the_absent_corpus_does_not_change_the_present_one(monkeypatch, tmp_path):
    monkeypatch.delenv("PII_FIXTURES_DIR", raising=False)
    without = run_evaluation().dataset(DATASET_SYNTHETIC).metrics
    root = tmp_path / "empty"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps({"version": "1.0.0", "notes": "t", "fixtures": [], "canonical_fixtures": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PII_FIXTURES_DIR", str(root))
    assert run_evaluation().dataset(DATASET_SYNTHETIC).metrics == without


# ---------------------------------------------------------------------------
# a populated local corpus, end to end (built here, never committed)
# ---------------------------------------------------------------------------

_LOCAL_ENTRY = {
    "id": "note-probe-01",
    "file": "note/probe-01.md",
    "contour": "document",
    "source": "real",
    "provenance": "layout-only probe, invented values",
    "expected_categories": ["person_name", "phone"],
    "expected_detector_source": {
        "person_name": ["structured_field"],
        "phone": ["structured_field"],
    },
    "expected_decision": "review",
}


def _write_local_corpus(root: Path, entries: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "notes": "probe",
                "fixtures": entries,
                "canonical_fixtures": [],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_a_populated_local_corpus_gets_its_own_block(tmp_path, monkeypatch):
    """The positive case: present, evaluated, reported separately, and its
    presence changes nothing about the committed block.

    Invented values only — nothing resembling a patient exists in the
    repository even transiently.
    """
    root = _write_local_corpus(tmp_path / "pii-fixtures", [_LOCAL_ENTRY])
    (root / "note").mkdir()
    (root / "note" / "probe-01.md").write_text(
        "Пациент: Иванов Иван Иванович\nТелефон: +7 900 000-00-00\n", encoding="utf-8"
    )
    monkeypatch.setenv("PII_FIXTURES_DIR", str(root))

    fixtures = tuple(iter_local_real_corpus())
    assert [f.id for f in fixtures] == ["note-probe-01"]
    assert all(f.dataset == DATASET_REAL_CORPUS for f in fixtures)

    report = run_evaluation()
    real = report.dataset(DATASET_REAL_CORPUS)
    assert real.available
    assert real.metrics.boundaries == 2, "a document is scored at both boundaries"
    assert real.metrics.exact_set_match.count == 2
    assert report.dataset(DATASET_SYNTHETIC).metrics.boundaries == 10


def test_a_local_corpus_may_omit_expected_risk_level(tmp_path, monkeypatch):
    """Documented as optional, and the omission must not read as disagreement.

    ``expected_risk_level`` is absent here, so the risk rate has no rows in its
    denominator. Publishing ``0`` alone would say "the corpus disagreed about
    risk everywhere"; the declared-boundary count beside it is what makes the
    absence legible.
    """
    root = _write_local_corpus(tmp_path / "corpus", [_LOCAL_ENTRY])
    (root / "note").mkdir()
    (root / "note" / "probe-01.md").write_text("Пациент: Иванов Иван Иванович\n", encoding="utf-8")
    monkeypatch.setenv("PII_FIXTURES_DIR", str(root))

    metrics = run_evaluation().dataset(DATASET_REAL_CORPUS).metrics
    assert metrics.risk_declared_boundaries == 0
    assert metrics.risk_match.count == 0
    assert metrics.risk_match.rate == 0.0
    assert metrics.boundaries == 2, "the risk rate must not shrink the row denominator"


def test_the_committed_manifest_declares_risk_and_the_local_one_need_not():
    assert _synthetic_block().metrics.risk_declared_boundaries == 10


def test_both_blocks_render_together_when_both_are_present(tmp_path, monkeypatch):
    root = _write_local_corpus(tmp_path / "empty", [])
    monkeypatch.setenv("PII_FIXTURES_DIR", str(root))
    report = run_evaluation()
    out = render_text(report)
    assert f"{DATASET_SYNTHETIC}:" in out
    assert f"{DATASET_REAL_CORPUS}:" in out
    assert "NOT EVALUATED" not in out
    assert "**Not evaluated.**" not in render_markdown(report)


def test_a_local_manifest_may_declare_canonical_payloads(tmp_path, monkeypatch):
    """Both sections exist in the local manifest too — the two corpora share a
    schema, which is what makes their rows comparable at all."""
    root = _write_local_corpus(tmp_path / "corpus", [])
    payload = {"fields": {"note": "Врач: Петров Пётр Петрович"}}
    (root / "canonical").mkdir()
    (root / "canonical" / "probe.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["canonical_fixtures"] = [
        {
            "id": "canonical-probe-01",
            "file": "canonical/probe.json",
            "contour": "canonical",
            "source": "real",
            "provenance": "layout-only probe, invented values",
            "expected_categories": ["doctor_name"],
            "expected_detector_source": {"doctor_name": ["structured_field"]},
            "expected_decision": "allow_with_warning",
        }
    ]
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("PII_FIXTURES_DIR", str(root))

    real = run_evaluation().dataset(DATASET_REAL_CORPUS)
    assert real.available
    assert real.metrics.canonical_payloads == 1
    assert real.metrics.boundaries == 1


# ---------------------------------------------------------------------------
# the committed corpus is the only one CI may gate on
# ---------------------------------------------------------------------------


def test_every_committed_fixture_is_labelled_synthetic():
    assert all(f.dataset == DATASET_SYNTHETIC for f in iter_synthetic_fixtures())
    assert all(f.source == "synthetic" for f in iter_synthetic_fixtures())


def test_the_committed_corpus_resolves_inside_its_own_directory():
    for fixture in iter_synthetic_fixtures():
        assert fixture.path.resolve().is_relative_to(SYNTHETIC_FIXTURES_DIR.resolve())


def test_no_committed_fixture_lives_under_dot_dev():
    for fixture in iter_synthetic_fixtures():
        assert ".dev" not in fixture.path.parts


def test_the_committed_corpus_keeps_both_contours():
    documents = list(iter_pii_fixtures())
    canonical = list(iter_canonical_fixtures())
    assert all(f.path.suffix == ".md" for f in documents)
    assert all(f.path.suffix == ".json" for f in canonical)
    assert all(f.contour == CONTOUR_DOCUMENT for f in documents)
    assert all(f.contour == CONTOUR_CANONICAL for f in canonical)


def test_the_reserved_directories_are_still_the_declared_vocabulary():
    # `laboratory/` and `mixed/` are reserved and hold no document fixture yet;
    # the reservation is what makes a mis-pathed file fail loudly instead of
    # silently extending the dataset.
    assert PII_FIXTURE_DIRECTORIES == (
        "clean",
        "patient",
        "laboratory",
        "appointment",
        "prescription",
        "mixed",
        "malicious",
    )


def test_a_document_fixture_is_scored_at_both_boundaries():
    for evaluation in _synthetic_evaluations():
        if evaluation.contour != CONTOUR_DOCUMENT:
            continue
        assert {row.boundary for row in evaluation.boundaries} == {
            BOUNDARY_DOCUMENT_INTERNAL,
            BOUNDARY_DOCUMENT_EXTERNAL,
        }


# ---------------------------------------------------------------------------
# subprocess: the loader must not reach outside the package when unset
# ---------------------------------------------------------------------------


def _run(code: str, **env_overrides) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(APP_ROOT), "PII_FIXTURES_DIR": "", **env_overrides}
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(APP_ROOT),
        check=False,
    )


def test_no_dot_dev_path_is_opened_when_the_variable_is_unset():
    """The load-bearing isolation test: instrument every open and run the real
    CLI, then assert nothing local was touched.

    Asserting ``local_real_corpus_available() is False`` would only prove the
    guard function; this proves the whole run, renderers included, never reaches
    for a real document.
    """
    code = (
        "import builtins, pathlib\n"
        "opened = []\n"
        "real_open = builtins.open\n"
        "real_popen = pathlib.Path.open\n"
        "def t_open(file, *a, **k):\n"
        "    opened.append(str(file)); return real_open(file, *a, **k)\n"
        "def t_popen(self, *a, **k):\n"
        "    opened.append(str(self)); return real_popen(self, *a, **k)\n"
        "builtins.open = t_open\n"
        "pathlib.Path.open = t_popen\n"
        "import app.pii.evaluate as e\n"
        "e.main(['--json'])\n"
        "builtins.open = real_open\n"
        "bad = sorted({p for p in opened if '.dev' in p or 'pii-fixtures' in p})\n"
        "if bad:\n"
        "    raise SystemExit('read a local corpus path: ' + repr(bad))\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr
    # The run really did evaluate the committed corpus while touching nothing local.
    assert '"boundaries": 10' in result.stdout


def test_the_committed_corpus_files_really_are_read():
    """The mirror image of the test above.

    Without it, a harness that read no fixtures at all would pass every
    isolation test in this file.
    """
    result = _run(
        "import app.pii.evaluate as e\n"
        "r = e.run_evaluation()\n"
        "print(r.dataset('synthetic_regression').metrics.boundaries)\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("10")
