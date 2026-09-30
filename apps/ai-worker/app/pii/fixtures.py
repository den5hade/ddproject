"""App-owned loaders for the two PII evaluation corpora.

M4 built one loader for one committed manifest; M6 (EVAL_IMPL_PLAN Phase 1) widens
it to **two corpora behind one seam**, because the gate can only be calibrated
against data it is allowed to hold:

* :data:`SYNTHETIC_FIXTURES_DIR` — ``tests/fixtures/pii/``. Committed, committed-only
  by ORDER §13.3, every identity value invented. Derived from real documents'
  **structure** (table/label layout, field ordering, realistic PII placement),
  never from their contents. This is the CI corpus and the only one a regression
  gate may assert on.
* the **local real corpus** — named by ``PII_FIXTURES_DIR``, conventionally
  ``.dev/pii-fixtures/``. Never committed, never required by CI, and the only
  corpus whose precision/recall figures mean anything about real documents.

Why the seam is env-gated rather than defaulted
-----------------------------------------------

``PII_FIXTURES_DIR`` was already the documented override (M4 put it there and
nothing has used it since). Its meaning changes here from *"use this instead of
the committed dataset"* to *"here is the local real corpus"*, because the two
corpora are now simultaneous rather than alternatives: CI needs the committed
one regardless of what a developer has on disk, and a calibration run needs both.

Consequently ``.dev/pii-fixtures/`` is **not** read when the variable is unset,
even when it exists. M6's own invariant requires that nothing under ``.dev/`` be
reachable from the loader by default, and a silent fallback would breach it the
moment a developer assembled a corpus: the same command would then produce a
different report depending on local state, which is how a real-corpus dependency
reaches CI one env var at a time. The default directory survives as a *documented
convention* — :func:`local_real_corpus_unavailable_reason` names it and says how
to opt in, so the fallback is discoverable instead of invisible.

Manifest shape (2.0.0)
----------------------

Two sections, one entry vocabulary:

``fixtures``
    Document-contour ``marker.md`` files. ``expected_risk_level`` is required,
    because §4.10 fixed it and M5 Phase 13 made it a measured value.

``canonical_fixtures``
    Serialized canonical payloads scanned by contour 2. These used to live outside
    the manifest entirely, which made them unmeasurable *and* made an unlabelled
    payload indistinguishable from a negative one — an evaluation that treats a
    payload built to contain a leaked name as a clean document would report a
    false-positive rate of 100% on two fixtures, which is the false precision
    M6 exists to eliminate.

Both sections gain ``id``, ``contour`` and ``expected_detector_source`` (the
machine-checkable form of the finding that the structured layer goes silent on
real layouts), plus optional ``derived_from`` and ``provenance``. The local
manifest carries the same keys with ``provenance`` required and
``expected_risk_level`` optional, and — the rule that matters most here — **no raw
PII values**: the ground truth is *which category is present*, never what it is.

The loader stays free of the pipeline and is stdlib-only.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

# The committed dataset lives under the ai-worker test fixtures tree by design:
# a dev/eval artifact, not pipeline input. Resolved from the module's own
# location so the loader is cwd-independent — it works from the repo root, from
# ``apps/ai-worker`` and in CI, with no environment set at all.
_APP_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _APP_ROOT.parents[1]

SYNTHETIC_FIXTURES_DIR = (_APP_ROOT / "tests" / "fixtures" / "pii").resolve()
SYNTHETIC_MANIFEST_PATH = SYNTHETIC_FIXTURES_DIR / "manifest.json"

LOCAL_REAL_CORPUS_DIR_ENV = "PII_FIXTURES_DIR"
"""The seam between the two corpora, and the only way to enable the real one."""

DEFAULT_LOCAL_REAL_CORPUS_DIR = (_REPO_ROOT / ".dev" / "pii-fixtures").resolve()
"""Where the local real corpus conventionally lives. Documented, never implicit."""

DATASET_SYNTHETIC = "synthetic_regression"
"""Report key and :attr:`PIIFixture.dataset` value for the committed corpus."""

DATASET_REAL_CORPUS = "real_corpus"
"""Report key and :attr:`PIIFixture.dataset` value for the local corpus."""

CONTOUR_DOCUMENT = "document"
"""Contour 1 — ``stage=document``, the source-document scan."""

CONTOUR_CANONICAL = "canonical"
"""Contour 2 — ``stage=canonical``, the post-extraction payload guard."""

MANIFEST_FILENAME = "manifest.json"

PII_FIXTURE_DIRECTORIES: tuple[str, ...] = (
    "clean",
    "patient",
    "laboratory",
    "appointment",
    "prescription",
    "mixed",
    "malicious",
)
"""The per-IMPL_ARCH-Phase-10 category directories a *document* entry may reference.

Fixed up front so a mis-pathed file fails a test instead of silently extending
the dataset. ``laboratory/`` and ``mixed/`` are reserved and still empty: M6
Phase 4 lands the derived real-layout corpus there, which is why the tuple has
never had to grow.
"""

PII_CANONICAL_FIXTURE_DIRECTORIES: tuple[str, ...] = ("canonical",)
"""Top-level directory a *canonical* entry may reference."""

__all__ = [
    "CONTOUR_CANONICAL",
    "CONTOUR_DOCUMENT",
    "DATASET_REAL_CORPUS",
    "DATASET_SYNTHETIC",
    "DEFAULT_LOCAL_REAL_CORPUS_DIR",
    "LOCAL_REAL_CORPUS_DIR_ENV",
    "MANIFEST_FILENAME",
    "PII_CANONICAL_FIXTURE_DIRECTORIES",
    "PII_FIXTURE_DIRECTORIES",
    "PIIFixture",
    "SYNTHETIC_FIXTURES_DIR",
    "SYNTHETIC_MANIFEST_PATH",
    "iter_canonical_fixtures",
    "iter_local_real_corpus",
    "iter_pii_fixtures",
    "iter_synthetic_fixtures",
    "local_real_corpus_available",
    "local_real_corpus_dir",
    "local_real_corpus_manifest_path",
    "local_real_corpus_manifest_version",
    "local_real_corpus_unavailable_reason",
    "synthetic_manifest_version",
]

_DOCUMENT_REQUIRED_KEYS = frozenset(
    {
        "id",
        "file",
        "contour",
        "source",
        "expected_categories",
        "expected_detector_source",
        "expected_decision",
        "expected_risk_level",
    }
)
_CANONICAL_REQUIRED_KEYS = _DOCUMENT_REQUIRED_KEYS
_LOCAL_REQUIRED_KEYS = frozenset(
    {
        "id",
        "file",
        "contour",
        "source",
        "provenance",
        "expected_categories",
        "expected_detector_source",
        "expected_decision",
    }
)
_OPTIONAL_KEYS = frozenset({"derived_from", "provenance", "contains_secret", "expected_risk_level"})


@dataclass(frozen=True)
class PIIFixture:
    """A single manifest entry with its resolved on-disk path.

    One record for both corpora and both contours. The four fields that
    distinguish a corpus (``dataset``) or a contour (``contour``) are read
    nowhere in the metrics: they exist so a report can say *which* corpus a
    number came from, and so a loader can refuse a manifest that puts a canonical
    payload in the document section.

    ``expected_detector_source`` maps a category to the detector **source**
    (:class:`~app.pii.models.PIISource` values) allowed to claim it, as a set
    because two rules may legitimately claim the same category — the patient
    fixture's address is found by both the pattern and the structured layer, and
    a single-value field would have had to lie about one of them. It is the
    machine-checkable form of the finding that the structured detector cannot
    read the colonless real-world layouts: pinning *which layer* must fire turns
    "the structured detector went silent" from a quiet degradation into a failed
    test.

    ``expected_decision`` is the ground-truth decision **for the boundary the
    manifest's notes name**, which differs by contour (§4.10 fixes no destination
    field). On the committed corpus it is asserted at ``test=document`` /
    ``EXTERNAL_LLM``; on the local corpus it is *documented, not asserted* — it
    is the output M6 measures, and a gate that asserted it would be agreeing with
    itself.
    """

    id: str
    file: str
    path: Path
    contour: str
    dataset: str
    source: str
    expected_categories: tuple[str, ...]
    expected_decision: str
    expected_risk_level: str | None = None
    expected_detector_source: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    derived_from: str | None = None
    provenance: str | None = None
    contains_secret: bool = False

    def __post_init__(self) -> None:
        """Freeze ``expected_detector_source`` so the record is genuinely immutable.

        ``frozen=True`` stops attribute rebinding but says nothing about a ``dict``
        reachable from an instance, and these records are ground truth: a test
        that edited one in place to make an assertion pass would be invisible in
        the diff. Same reasoning as :class:`~app.pii.models.PIIFinding.metadata`,
        except this one can be closed because nothing needs to mutate it.
        """
        object.__setattr__(
            self,
            "expected_detector_source",
            MappingProxyType(dict(self.expected_detector_source)),
        )

    @property
    def is_canonical(self) -> bool:
        return self.contour == CONTOUR_CANONICAL


def synthetic_manifest_version() -> str:
    """Return the committed manifest's ``version`` string."""
    return _read_manifest(SYNTHETIC_MANIFEST_PATH)["version"]


def local_real_corpus_dir() -> Path:
    """Return the local real corpus root, resolved from the environment.

    Read at call time rather than imported as a constant so a test (or a
    developer with two shells) can point the loader somewhere else without
    reloading the module — and so an unset variable and a changed variable are
    the same code path.
    """
    configured = os.environ.get(LOCAL_REAL_CORPUS_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_LOCAL_REAL_CORPUS_DIR


def local_real_corpus_manifest_path() -> Path:
    """Return the local manifest path — present or not; absence is the answer."""
    return local_real_corpus_dir() / MANIFEST_FILENAME


def local_real_corpus_available() -> bool:
    """Whether the local real corpus can be evaluated right now."""
    return local_real_corpus_unavailable_reason() is None


def local_real_corpus_unavailable_reason() -> str | None:
    """Why the real corpus is not being evaluated, or ``None`` when it is.

    Five states, five different sentences, because the caller has to be able to
    tell "you did not ask for it" from "you asked and it is not there" from
    "what you asked for cannot be used":

    * unset and the conventional directory absent → the default state, and the
      sentence the plan's report shape shows verbatim;
    * unset and the conventional directory **present** → a deliberate refusal,
      naming the directory and how to enable it. Reading it silently is exactly
      the ``.dev/`` reachability the milestone rules out;
    * set but holding no manifest → a misconfiguration, reported as such;
    * set inside the committed fixtures tree → **refused**, because a local
      experiment pointed there would be editing the regression ground truth
      rather than measuring against it, and the resulting report would attribute
      its numbers to a corpus nobody audited;
    * set but holding a manifest that cannot be read → reported as a broken
      local corpus rather than raised, so one bad file cannot take the committed
      corpus's report down with it.

    The string lands in the report verbatim, so it is phrased for a human reading
    an artifact and never as an empty measurement.
    """
    configured = os.environ.get(LOCAL_REAL_CORPUS_DIR_ENV, "").strip()
    if configured:
        root = local_real_corpus_dir()
        if root.is_relative_to(SYNTHETIC_FIXTURES_DIR) or SYNTHETIC_FIXTURES_DIR.is_relative_to(
            root
        ):
            return (
                f"{LOCAL_REAL_CORPUS_DIR_ENV}={root} overlaps the committed fixtures at "
                f"{SYNTHETIC_FIXTURES_DIR}; the real corpus was not evaluated. A local corpus "
                "must live outside the tree CI asserts on."
            )
        if not local_real_corpus_manifest_path().is_file():
            return (
                f"{LOCAL_REAL_CORPUS_DIR_ENV}={local_real_corpus_dir()} holds no "
                f"{MANIFEST_FILENAME}; the real corpus was not evaluated."
            )
        try:
            _read_manifest(local_real_corpus_manifest_path())
        except (OSError, ValueError) as exc:
            return (
                f"{LOCAL_REAL_CORPUS_DIR_ENV}={root} holds a {MANIFEST_FILENAME} that could "
                f"not be read ({exc}); the real corpus was not evaluated."
            )
        return None
    if DEFAULT_LOCAL_REAL_CORPUS_DIR.is_dir():
        return (
            f"{LOCAL_REAL_CORPUS_DIR_ENV} is unset and a corpus exists at "
            f"{DEFAULT_LOCAL_REAL_CORPUS_DIR}, which is not read implicitly. Set "
            f"{LOCAL_REAL_CORPUS_DIR_ENV} to evaluate it."
        )
    return (
        f"{LOCAL_REAL_CORPUS_DIR_ENV} unset and no default corpus found at "
        f"{DEFAULT_LOCAL_REAL_CORPUS_DIR}"
    )


def local_real_corpus_manifest_version() -> str | None:
    """Return the local manifest's version, or ``None`` when there is no usable one."""
    if not local_real_corpus_available():
        return None
    return _read_manifest(local_real_corpus_manifest_path())["version"]



def iter_pii_fixtures() -> list[PIIFixture]:
    """Load the committed **document-contour** fixtures, in manifest order.

    Kept as the narrow entry point because three existing suites and the on-disk
    ``*.md`` parity check are about the document contour specifically; the
    canonical payloads were deliberately outside the manifest until M6 and are
    reached through :func:`iter_canonical_fixtures`.
    """
    return _load_entries(
        SYNTHETIC_MANIFEST_PATH,
        DATASET_SYNTHETIC,
        "fixtures",
        CONTOUR_DOCUMENT,
        required=_DOCUMENT_REQUIRED_KEYS,
    )


def iter_canonical_fixtures() -> list[PIIFixture]:
    """Load the committed **canonical-payload** fixtures, in manifest order."""
    return _load_entries(
        SYNTHETIC_MANIFEST_PATH,
        DATASET_SYNTHETIC,
        "canonical_fixtures",
        CONTOUR_CANONICAL,
        required=_CANONICAL_REQUIRED_KEYS,
    )


def iter_synthetic_fixtures() -> list[PIIFixture]:
    """Every committed fixture, documents first, in manifest order."""
    return iter_pii_fixtures() + iter_canonical_fixtures()


def iter_local_real_corpus() -> list[PIIFixture]:
    """Load the local real corpus — empty when it is unavailable.

    Returning an empty list rather than raising is what lets one caller drive
    both corpora, and it is safe only because availability is decided *before*
    the file system is touched: with ``PII_FIXTURES_DIR`` unset this function
    performs no read at all, so nothing under ``.dev/`` is reachable.
    """
    if not local_real_corpus_available():
        return []
    manifest_path = local_real_corpus_manifest_path()
    return _load_entries(
        manifest_path,
        DATASET_REAL_CORPUS,
        "fixtures",
        CONTOUR_DOCUMENT,
        required=_LOCAL_REQUIRED_KEYS,
    ) + _load_entries(
        manifest_path,
        DATASET_REAL_CORPUS,
        "canonical_fixtures",
        CONTOUR_CANONICAL,
        required=_LOCAL_REQUIRED_KEYS,
    )


def _read_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _load_entries(
    manifest_path: Path,
    dataset: str,
    section: str,
    contour: str,
    *,
    required: frozenset[str],
) -> list[PIIFixture]:
    """Build fixtures from one manifest section, validating as it goes.

    The validation is here rather than in a test because the loader is the only
    thing standing between a hand-edited JSON file and a report that quietly
    measures the wrong thing. Three classes of mistake are refused outright: a
    missing key (``KeyError`` names it), an entry whose ``contour`` contradicts
    the section it sits in, and a duplicate ``id`` — which matters because the
    report keys rows by it and two fixtures sharing one would silently collapse.
    """
    manifest = _read_manifest(manifest_path)
    root = manifest_path.parent
    fixtures: list[PIIFixture] = []
    seen: set[str] = set()
    for entry in manifest.get(section, []):
        missing = sorted(required - set(entry))
        if missing:
            raise ValueError(
                f"{manifest_path}: {section} entry "
                f"{entry.get('file', '<unnamed>')!r} is missing {missing}; "
                "ground truth cannot be inferred from what is absent."
            )
        unknown = sorted(set(entry) - required - _OPTIONAL_KEYS)
        if unknown:
            raise ValueError(
                f"{manifest_path}: {section} entry {entry['file']!r} carries unknown "
                f"keys {unknown}; a manifest that grows a second contract stops "
                "being read as ground truth."
            )
        if entry["contour"] != contour:
            raise ValueError(
                f"{manifest_path}: {section} entry {entry['file']!r} declares "
                f"contour={entry['contour']!r} but sits in the {contour} section."
            )
        if entry["id"] in seen:
            raise ValueError(
                f"{manifest_path}: duplicate fixture id {entry['id']!r}; report rows "
                "are keyed by it and two fixtures sharing one would collapse."
            )
        seen.add(entry["id"])
        fixtures.append(
            PIIFixture(
                id=entry["id"],
                file=entry["file"],
                path=root / entry["file"],
                contour=contour,
                dataset=dataset,
                source=entry["source"],
                expected_categories=tuple(entry["expected_categories"]),
                expected_decision=entry["expected_decision"],
                expected_risk_level=entry.get("expected_risk_level"),
                expected_detector_source={
                    category: tuple(sources)
                    for category, sources in entry["expected_detector_source"].items()
                },
                derived_from=entry.get("derived_from"),
                provenance=entry.get("provenance"),
                contains_secret=entry.get("contains_secret", False),
            )
        )
    return fixtures
