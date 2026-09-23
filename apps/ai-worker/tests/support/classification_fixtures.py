"""Loader for the Classification 2.0 regression fixture manifest.

Phase 5: every fixture loads and the manifest iterates cleanly. Phase 6
regressions consume this loader to evaluate each fixture against the rule-based
classifier.
"""

import json
from dataclasses import dataclass
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "classification"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"

__all__ = ["ClassificationFixture", "iter_classification_fixtures"]


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
        path = FIXTURES_DIR / entry["file"]
        fixtures.append(
            ClassificationFixture(
                file=entry["file"],
                path=path,
                source=entry.get("source", "synthetic"),
                expected_type=entry["expected_type"],
                expected_subtype=entry.get("expected_subtype"),
                expected_decision=entry["expected_decision"],
            )
        )
    return fixtures