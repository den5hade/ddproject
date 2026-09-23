"""Delegate over the app-owned Classification 2.0 fixture loader.

M3 (EVAL_IMPL_PLAN Phase 1): fixture loading moved into
``app.classification.fixtures`` so the evaluation CLI and the test suite read
one manifest (single source of truth). This module re-exports the app loader
for backward-compatible test imports.
"""

from app.classification.fixtures import (
    FIXTURES_DIR,
    MANIFEST_PATH,
    ClassificationFixture,
    iter_classification_fixtures,
)

__all__ = [
    "ClassificationFixture",
    "FIXTURES_DIR",
    "MANIFEST_PATH",
    "iter_classification_fixtures",
]