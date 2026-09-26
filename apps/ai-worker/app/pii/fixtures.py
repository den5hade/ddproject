"""App-owned loader for the PII gate regression fixture manifest.

Mirrors ``app/classification/fixtures.py`` — the loader lives in the app so the
M5 detection CLI and the test suite read the same manifest (single source of
truth), and ``tests/support/`` stays a thin delegate if one is ever needed.

The manifest shape is fixed by plan §4.10: top-level ``version`` + ``notes`` +
``fixtures[]``, each entry carrying ``file``, ``source``, ``expected_categories``,
``expected_decision`` and ``expected_risk_level``, with ``contains_secret``
optional. M4 seeds ``clean/``, ``patient/`` and ``malicious/`` synthetically to
prove the shape; the real-marker sweep (copies of ``.dev/flow_upload_test/``)
belongs to M5, which also has a detector to check expectations against — until
then ``expected_*`` are declared ground truth that no test can verify.

The loader stays free of the pipeline and is stdlib-only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# The dataset lives under the ai-worker test fixtures tree by design, matching
# the classification fixtures: a dev/eval artifact, not pipeline input.
# ``PII_FIXTURES_DIR`` allows pointing at a different dataset once the
# real-marker set grows.
_DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pii"

FIXTURES_DIR = Path(os.environ.get("PII_FIXTURES_DIR", str(_DEFAULT_FIXTURES_DIR))).resolve()
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"

PII_FIXTURE_DIRECTORIES: tuple[str, ...] = (
    "clean",
    "patient",
    "laboratory",
    "appointment",
    "prescription",
    "mixed",
    "malicious",
)
"""The per-IMPL_ARCH-Phase-10 category directories the manifest may reference.

Fixed up front so M5's real-marker sweep has somewhere to land and so a
mis-pathed file fails a test instead of silently extending the dataset. Only
``clean``, ``patient`` and ``malicious`` are seeded here; the other four wait for
M5, which can populate them with real markers.
"""

__all__ = [
    "MANIFEST_PATH",
    "PII_FIXTURE_DIRECTORIES",
    "PIIFixture",
    "FIXTURES_DIR",
    "iter_pii_fixtures",
]


@dataclass(frozen=True)
class PIIFixture:
    """A single manifest entry with the resolved markdown path."""

    file: str
    path: Path
    source: str
    expected_categories: tuple[str, ...]
    expected_decision: str
    expected_risk_level: str
    contains_secret: bool = False


def iter_pii_fixtures() -> list[PIIFixture]:
    """Load the manifest and resolve each entry to an on-disk path."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fixtures: list[PIIFixture] = []
    for entry in manifest["fixtures"]:
        fixtures.append(
            PIIFixture(
                file=entry["file"],
                path=FIXTURES_DIR / entry["file"],
                source=entry["source"],
                expected_categories=tuple(entry["expected_categories"]),
                expected_decision=entry["expected_decision"],
                expected_risk_level=entry["expected_risk_level"],
                contains_secret=entry.get("contains_secret", False),
            )
        )
    return fixtures
