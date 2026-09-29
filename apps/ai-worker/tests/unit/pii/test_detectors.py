"""Contract-level tests for the PII detector and aggregator contracts (M4 Phase 3).

Nothing detects yet, so these tests lock the *shape*: the protocol signature,
the fail-loud behaviour of the stubs, the composite's ordering guarantee, the
version constant, and the import boundary that keeps PII a document-level
capability independent of classification.
"""

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.pii import (
    DETECTOR_VERSION,
    CompositePIIDetector,
    InvalidPIIInputError,
    PatternPIIDetector,
    PIICategory,
    PIIDetector,
    PIIDetectorBase,
    PIIFinding,
    PIISource,
    SecretPIIDetector,
    StructuredFieldPIIDetector,
    aggregation,
)
from app.pii import detectors as detectors_module
from app.pii.aggregation import PIIAggregator, PIIAggregatorBase
from tests.support.pii_imports import (
    ALLOWED_TYPE_ONLY_IMPORTS,
    imports_forbidden_domains,
    imports_forbidden_infrastructure,
    module_names,
    runtime_imports,
    type_only_imports,
    unexpected_type_only_imports,
)

_DETECTORS_PATH = Path(__file__).resolve().parents[3] / "app" / "pii" / "detectors.py"
_AGGREGATION_PATH = Path(__file__).resolve().parents[3] / "app" / "pii" / "aggregation.py"
_SECRET = "phase-9-test-secret-not-a-real-key"
_ALL_STUBS = (
    PatternPIIDetector,
    StructuredFieldPIIDetector,
    SecretPIIDetector,
    CompositePIIDetector,
)


def _document():
    """A minimal stand-in; detectors only ever consume a ``NormalizedDocument``."""
    return object()


def _text_document(text: str):
    """A document stand-in exposing only ``raw_text``, which is all §7 reads."""
    return SimpleNamespace(raw_text=text)


# --- protocol contract ------------------------------------------------------


def test_detector_is_a_protocol():
    assert getattr(PIIDetector, "_is_protocol", False) is True


def test_detect_signature_is_sync_and_locked():
    """``detect(document) -> list[PIIFinding]``, synchronous (plan §4.6)."""
    signature = inspect.signature(PIIDetector.detect)
    parameters = list(signature.parameters.values())
    assert [p.name for p in parameters] == ["self", "document"]
    assert parameters[1].annotation == "NormalizedDocument"
    assert signature.return_annotation == "list[PIIFinding]"
    assert not inspect.iscoroutinefunction(PIIDetector.detect)
    assert not inspect.isasyncgenfunction(PIIDetector.detect)


def test_every_stub_satisfies_the_protocol():
    for stub in _ALL_STUBS:
        assert issubclass(stub, PIIDetectorBase)
        assert callable(stub.detect)


def test_stubs_detect_is_sync_with_the_protocol_signature():
    for stub in (*_ALL_STUBS, PIIDetectorBase):
        assert not inspect.iscoroutinefunction(stub.detect)
        assert list(inspect.signature(stub.detect).parameters) == ["self", "document"]


# --- fail-loud stubs --------------------------------------------------------


def test_only_the_base_class_still_raises_not_implemented():
    """An unimplemented detector must fail loudly, never report "no PII found".

    M5 Phase 13 implemented the last two stubs, so
    :class:`PIIDetectorBase` is the *only* thing left that must raise: it has no
    rule table to scan with, and inheriting it is a deliberate act, so a silent
    empty result there would hide a detector nobody finished.
    """
    with pytest.raises(NotImplementedError) as excinfo:
        PIIDetectorBase().detect(_document())
    assert type(excinfo.value) is NotImplementedError
    assert "M5" in str(excinfo.value)


def test_phase_13_detectors_no_longer_raise_not_implemented():
    """The structured and secret layers are live as of M5 Phase 13.

    Each is asserted on text it must find *and* text it must leave alone, so a
    later edit that guts a rule table fails here as an empty result rather than
    quietly as a passing test.
    """
    cases = (
        (StructuredFieldPIIDetector(fingerprint_secret=_SECRET), "**ФИО:** Иванов Пётр", "памятка"),
        (SecretPIIDetector(fingerprint_secret=_SECRET), "api_key: sk-live-abcd1234", "памятка"),
    )
    for detector, positive, negative in cases:
        assert detector.detect_text(positive), f"{type(detector).__name__} finds nothing"
        assert detector.detect_text(negative) == []
        assert detector.detect(_text_document(positive))
        assert detector.detect(_text_document(negative)) == []


def test_phase_9_detectors_no_longer_raise_not_implemented():
    """The pattern layer and the composite are live as of M5 Phase 9."""
    pattern = PatternPIIDetector(fingerprint_secret=_SECRET)
    composite = CompositePIIDetector([pattern])
    for detector in (pattern, composite):
        assert detector.detect_text("плановая проверка сети") == []
        assert detector.detect(_text_document("плановая проверка сети")) == []


def test_aggregator_base_raises_not_implemented():
    assert getattr(PIIAggregator, "_is_protocol", False) is True
    assert not inspect.iscoroutinefunction(PIIAggregator.aggregate)
    assert list(inspect.signature(PIIAggregator.aggregate).parameters) == ["self", "findings"]
    with pytest.raises(NotImplementedError):
        PIIAggregatorBase().aggregate([])


def test_detector_contract_does_not_return_verdicts():
    """``detect`` returns findings only — no risk, no action, no decision (IMPL_ARCH §12)."""
    annotation = inspect.signature(PIIDetector.detect).return_annotation
    assert annotation == "list[PIIFinding]"
    for forbidden in ("decision", "risk", "action"):
        assert forbidden not in annotation.lower()


# --- composite ordering -----------------------------------------------------


def test_composite_preserves_configured_order_immutably():
    first, second = PatternPIIDetector(), SecretPIIDetector()
    composite = CompositePIIDetector([first, second])
    assert composite.detectors == (first, second)
    assert isinstance(composite.detectors, tuple)
    with pytest.raises((AttributeError, TypeError)):
        composite.detectors[0] = second  # type: ignore[index]


def test_composite_rejects_an_empty_chain():
    """An empty chain would allow every document while looking healthy."""
    with pytest.raises(InvalidPIIInputError) as excinfo:
        CompositePIIDetector([])
    assert "detector" in str(excinfo.value).lower()


def test_composite_accepts_any_detector_count():
    for count in (1, 4):
        chain = CompositePIIDetector([PatternPIIDetector() for _ in range(count)])
        assert len(chain.detectors) == count


# --- version constant -------------------------------------------------------


def test_detector_version_is_the_locked_baseline():
    """``1.1.0`` from M5 Phase 9 — the minor line, for a contract addition.

    The bump added ``detect_text`` to the protocol and gave the pattern layer an
    implementation. It did not add, remove or re-label a category, so the major
    line — "which findings are produced changed" — does not apply, and asserting
    ``1.0.0`` here again would only re-freeze the constant.
    """
    assert DETECTOR_VERSION == "1.1.0"


def test_finding_carries_the_detector_version_it_was_stamped_with():
    finding = PIIFinding(
        category=PIICategory.SECRET,
        value="AKIAIOSFODNN7EXAMPLE",
        masked_value="****",
        value_fingerprint="hmac-sha256:beef",
        confidence=1.0,
        source=PIISource.PATTERN,
        detector="secret.aws_key",
        detector_version=DETECTOR_VERSION,
    )
    assert finding.detector_version == DETECTOR_VERSION
    assert finding.source is PIISource.PATTERN


# --- import boundary (plan §0, §3 accept) ------------------------------------


def test_detectors_module_imports_no_infrastructure():
    assert not imports_forbidden_infrastructure(_DETECTORS_PATH)


def test_detectors_module_has_no_runtime_classification_import():
    """PII must be usable without ``app.classification`` importable at runtime."""
    assert not imports_forbidden_domains(_DETECTORS_PATH)
    classification_modules = {m for m, _ in runtime_imports(_DETECTORS_PATH)}
    assert not any(m.startswith("app.classification") for m in classification_modules)


def test_detectors_module_borrows_only_approved_types_type_only():
    """Widened in M5 Phase 8: the chain factory takes ``Settings``, type-only.

    The property under test is unchanged — every cross-package borrow is
    type-only and drawn from the allowlist — but the allowlist itself grew by
    one symbol, so an exact-equality assertion against the M4 pair would now be
    asserting the wrong thing. What must stay true is that ``app.config`` is
    *never* a runtime import: a runtime one would make ``app.pii`` unimportable
    without an environment, and would drag ``messaging.topology`` in with it.
    """
    borrowed = type_only_imports(_DETECTORS_PATH)
    assert borrowed <= ALLOWED_TYPE_ONLY_IMPORTS
    assert ("app.config.settings", "Settings") in borrowed
    assert not unexpected_type_only_imports(_DETECTORS_PATH)
    assert "app.config.settings" not in module_names(_DETECTORS_PATH)
    assert not any(m.startswith("app.config") for m in module_names(_DETECTORS_PATH))


def test_aggregation_module_imports_nothing_from_other_packages():
    assert not imports_forbidden_infrastructure(_AGGREGATION_PATH)
    assert not imports_forbidden_domains(_AGGREGATION_PATH)
    assert not unexpected_type_only_imports(_AGGREGATION_PATH)
    # The dedup key is (category, value_fingerprint) — the aggregator needs both
    # models, and nothing else from anywhere (stdlib excepted).
    project_imports = {m for m, _ in runtime_imports(_AGGREGATION_PATH) if m.startswith("app.")}
    assert project_imports == {"app.pii.models"}


def test_stub_documentation_names_its_intended_categories():
    """Category assignment for an *unimplemented* detector must not be vague.

    The M4 rule survives for the two detectors that are still stubs. It is
    retired for ``PatternPIIDetector``, because a prose list of "intended
    categories" is a worse artifact than the rule table it would describe, and
    drifts from it silently. The replacement check is stronger: every row of the
    table must name a real category, so a typo in a rule is a test failure
    rather than a category nobody will ever see.
    """
    for stub in (StructuredFieldPIIDetector, SecretPIIDetector):
        doc = inspect.getdoc(stub) or ""
        assert doc, f"{stub.__name__} needs a docstring"
        named = {c.value for c in PIICategory if f"``{c.name}``" in doc}
        assert named, f"{stub.__name__} must name its intended categories"
        for category in named:
            assert category in PIICategory.__members__.values()

    rows = detectors_module._PATTERNS
    assert rows
    for row in rows:
        assert row.category in set(PIICategory)
        assert 0.0 < row.confidence <= 1.0
        assert row.name == f"{row.category.value}.{row.name.split('.', 1)[1]}"
        assert row.regex.search("") is None


def test_aggregation_documentation_locks_the_dedup_rule():
    """The dedup rule is prose in M4, so the prose is the tested artifact."""
    doc = inspect.getdoc(aggregation) or ""
    for required in ("value_fingerprint", "highest", "earliest position", "first appearance"):
        assert required in doc, f"dedup rule must state {required!r}"
    # The empty-fingerprint escape hatch is a safety property, not a nicety.
    assert "bypasses dedup" in doc


# --- the guard's own teeth --------------------------------------------------


def test_import_guard_helper_discriminates_runtime_from_type_only(tmp_path):
    """A guard that cannot fail is not a guard: prove the classifier works.

    Every guard above is satisfied by *empty* results, which is also what a
    broken AST walk would return. This exercises the classifier against a
    synthetic module containing all three cases it must tell apart.
    """
    probe = tmp_path / "probe_module.py"
    probe.write_text(
        "from typing import TYPE_CHECKING\n"
        "\n"
        "from app.classification.normalize import NormalizedDocument  # runtime\n"
        "from pdf_storage import S3Client  # runtime, infrastructure\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from app.classification.models import DocumentType  # type-only, forbidden\n"
        "    from app.classification.normalize import NormalizedDocument as ND\n",
        encoding="utf-8",
    )

    assert {m for m, _ in runtime_imports(probe)} == {
        "typing",
        "app.classification.normalize",
        "pdf_storage",
    }
    assert type_only_imports(probe) == {
        ("app.classification.models", "DocumentType"),
        ("app.classification.normalize", "NormalizedDocument"),
    }
    assert imports_forbidden_infrastructure(probe) == {"pdf_storage"}
    # ``pdf_storage`` trips both guards — the two sets overlap on purpose, so a
    # persistence import is caught whichever guard a future module is checked
    # against.
    assert imports_forbidden_domains(probe) == {"app.classification.normalize", "pdf_storage"}
    # The guard keys on the imported *symbol*, not the local alias, so a
    # legitimate ``as ND`` rename stays approved while a different symbol
    # (``DocumentType``) does not.
    assert unexpected_type_only_imports(probe) == {
        ("app.classification.models", "DocumentType"),
    }


def test_import_guard_helper_flags_a_runtime_classification_import(tmp_path):
    """The exact regression Phase 3 had to avoid: a real runtime borrow."""
    probe = tmp_path / "runtime_borrow.py"
    probe.write_text(
        "from app.classification.models import DocumentType\n",
        encoding="utf-8",
    )
    assert imports_forbidden_domains(probe) == {"app.classification.models"}
    assert not type_only_imports(probe)
