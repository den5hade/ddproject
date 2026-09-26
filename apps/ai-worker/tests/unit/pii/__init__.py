"""Unit tests for the PII gate contract (M4).

This package marker exists because ``tests/unit/classification/`` already owns
``test_models.py``, ``test_schemas.py`` and ``test_fixture_manifest.py``; with
no package marker pytest's default prepend import mode gives same-named files
in sibling directories the same module name and collection fails with
"import file mismatch". See ``PII GATE/IMPL_PLAN.md`` — Phase 1 Implementation
Status, Deviation: test-dir ``__init__.py``.
"""
