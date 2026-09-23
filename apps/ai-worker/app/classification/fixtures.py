"""App-owned loader for the Classification 2.0 regression fixture manifest.

M3 (EVAL_IMPL_PLAN Phase 1): fixture loading moved out of the test-support
package and into the app so the evaluation CLI and the test suite read the
same manifest (single source of truth). ``tests/support/
classification_fixtures.py`` is now a thin delegate over this module.

The loader stays free of the pipeline (no scoring/service imports) and never
reaches back into ``tests.*`` — it is stdlib-only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# The regression dataset lives under the ai-worker test fixtures tree by
# design (EVAL_IMPL_PLAN §4): it is a dev/eval artifact, not pipeline input.
# ``CLASSIFICATION_FIXTURES_DIR`` allows pointing at a different dataset
# without code changes once the real-marker set grows beyond ~50.
_DEFAULT_FIXTURES_DIR = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "classification"
)

FIXTURES_DIR = Path(
    os.environ.get("CLASSIFICATION_FIXTURES_DIR", str(_DEFAULT_FIXTURES_DIR))
).resolve()
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"

__all__ = [
    "ClassificationFixture",
    "FIXTURES_DIR",
    "MANIFEST_PATH",
    "iter_classification_fixtures",
]


@dataclass(frozen=True)
class ClassificationFixture:
    """A single manifest entry with the resolved markdown path."""

    file: str
    path: Path
    source: str
    expected_type: str
    expected_subtype: str | None
    expected_decision: str


def iter_classification_fixtures() -> list[ClassificationFixture]:
    """Load the manifest and resolve each entry to an on-disk path."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fixtures: list[ClassificationFixture] = []
    for entry in manifest["fixtures"]:
        fixtures.append(
            ClassificationFixture(
                file=entry["file"],
                path=FIXTURES_DIR / entry["file"],
                source=entry.get("source", "synthetic"),
                expected_type=entry["expected_type"],
                expected_subtype=entry.get("expected_subtype"),
                expected_decision=entry["expected_decision"],
            )
        )
    return fixtures