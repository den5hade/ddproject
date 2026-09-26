"""Contract-level tests for the PII detector and aggregator contracts (M4 Phase 3).

Nothing detects yet, so these tests lock the *shape*: the protocol signature,
the fail-loud behaviour of the stubs, the composite's ordering guarantee, the
version constant, and the import boundary that keeps PII a document-level
capability independent of classification.
"""

import inspect
from pathlib import Path

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
from app.pii.aggregation import PIIAggregator, PIIAggregatorBase
from tests.support.pii_imports import (
    imports_forbidden_domains,
    imports_forbidden_infrastructure,
    runtime_imports,
    type_only_imports,
    unexpected_type_only_imports,
)

_DETECTORS_PATH = Path(__file__).resolve().parents[3] / "app" / "pii" / "detectors.py"
_AGGREGATION_PATH = Path(__file__).resolve().parents[3] / "app" / "pii" / "aggregation.py"
_ALL_STUBS = (
    PatternPIIDetector,
    StructuredFieldPIIDetector,
    SecretPIIDetector,
    CompositePIIDetector,
)


def _document():
    """A minimal stand-in; detectors only ever consume a ``NormalizedDocument``."""
    return object()


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


def test_base_and_stubs_raise_not_implemented():
    """An unimplemented detector must fail loudly, never report "no PII found"."""
    instances = (
        PIIDetectorBase(),
        PatternPIIDetector(),
        StructuredFieldPIIDetector(),
        SecretPIIDetector(),
        CompositePIIDetector([PatternPIIDetector()]),
    )
    for instance in instances:
        with pytest.raises(NotImplementedError) as excinfo:
            instance.detect(_document())
        assert type(excinfo.value) is NotImplementedError
        assert "M5" in str(excinfo.value)


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
    assert DETECTOR_VERSION == "1.0.0"


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


def test_detectors_module_borrows_only_normalized_document_type_only():
    borrowed = type_only_imports(_DETECTORS_PATH)
    assert borrowed == {("app.classification.normalize", "NormalizedDocument")}
    assert not unexpected_type_only_imports(_DETECTORS_PATH)
    for module, name in borrowed:
        assert module == "app.classification.normalize"
        assert name == "NormalizedDocument"


def test_aggregation_module_imports_nothing_from_other_packages():
    assert not imports_forbidden_infrastructure(_AGGREGATION_PATH)
    assert not imports_forbidden_domains(_AGGREGATION_PATH)
    assert not unexpected_type_only_imports(_AGGREGATION_PATH)
    # The dedup key is (category, value_fingerprint) — the aggregator needs both
    # models, and nothing else from anywhere (stdlib excepted).
    project_imports = {m for m, _ in runtime_imports(_AGGREGATION_PATH) if m.startswith("app.")}
    assert project_imports == {"app.pii.models"}


def test_detector_documentation_names_its_intended_categories():
    """Category assignment is docstring-only in M4 but must not be vague."""
    for stub in _ALL_STUBS:
        doc = inspect.getdoc(stub) or ""
        assert doc, f"{stub.__name__} needs a docstring"
        if stub is CompositePIIDetector:
            continue
        named = {c.value for c in PIICategory if f"``{c.name}``" in doc}
        assert named, f"{stub.__name__} must name its intended categories"
        for category in named:
            assert category in PIICategory.__members__.values()


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
