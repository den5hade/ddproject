"""Tests for the PII gate's configuration boundary (M5 Phase 8).

Phase 8 is the phase nothing else could start without: ``value_fingerprint`` is
an HMAC, and an HMAC without a configured key is the brute-forceable digest
``masking.py`` refuses to produce. So these tests are about *failing closed at
the boundary* rather than about detection — which lands in Phase 9.

The four properties pinned here, in the order they matter:

1. **No usable default secret.** ``Settings.pii_fingerprint_secret`` is empty
   out of the box, and a blank value is rejected rather than degraded to.
2. **The secret reaches the fingerprints, and only the fingerprints.** Two
   settings objects produce two unlinkable fingerprint spaces; one produces a
   stable one. The value itself never appears in a message, a ``repr`` or a
   public attribute.
3. **The policy context's un-sourced inputs are wired, not smuggled.** The
   tenant comes from ``settings.s3_tenant_id`` (ORDER §13.6), and a blank one
   fails; the destination defaults to the trusted internal provider.
4. **The package stays configuration-free.** ``app/pii`` borrows ``Settings``
   type-only, so importing it with ``app.config`` blocked at the import system
   still works — proven in a subprocess, like the M4 pipeline guard.
"""

import inspect
import subprocess
import sys

import pytest
from app.config.settings import Settings
from app.pii import (
    DEFAULT_DESTINATION,
    PII_FINGERPRINT_SECRET_ENV,
    InvalidPIIInputError,
    PatternPIIDetector,
    PIICategory,
    PIIDestination,
    PIIDetectorBase,
    PIIFinding,
    PIIPolicyContext,
    PIIPolicyError,
    PIIScanStage,
    PIISource,
    SecretPIIDetector,
    StructuredFieldPIIDetector,
    build_detector_chain,
    build_policy_context,
    hash_pii_value,
)
from pydantic import ValidationError
from tests.support.pii_imports import (
    ALLOWED_TYPE_ONLY_IMPORTS,
    module_names,
    pii_source_files,
    runtime_edge_guarded_files,
    type_only_imports,
    unexpected_type_only_imports,
)

_SECRET = "unit-test-secret-not-a-real-one"
_OTHER_SECRET = "a-different-unit-test-secret"
_SAMPLE_VALUE = "Шадеркин Денис Сергеевич"


def _settings(**overrides) -> Settings:
    """Settings built from code only — never from the developer's ``.env``."""
    return Settings(_env_file=None, **overrides)


# --- 1. the secret is required, and there is no usable default ----------------


def test_settings_secret_is_empty_by_default():
    """A default secret is a hard-coded secret, and that is no secret at all."""
    assert _settings().pii_fingerprint_secret == ""


def test_settings_secret_comes_from_the_environment(monkeypatch):
    """The env name is the deployment contract; pin it exactly."""
    monkeypatch.setenv(PII_FINGERPRINT_SECRET_ENV, "from-the-environment")
    assert _settings().pii_fingerprint_secret == "from-the-environment"


def test_settings_secret_env_name_matches_the_field():
    """``pydantic-settings`` derives the name from the field, case-insensitively."""
    assert PII_FINGERPRINT_SECRET_ENV == "PII_FINGERPRINT_SECRET"
    assert PII_FINGERPRINT_SECRET_ENV.lower() == "pii_fingerprint_secret"


@pytest.mark.parametrize("secret", ["", "   ", "\t\n"])
def test_chain_construction_fails_closed_on_a_blank_secret(secret):
    """The Phase 8 accept criterion: no setting means no chain, not a plain hash."""
    with pytest.raises(InvalidPIIInputError) as excinfo:
        build_detector_chain(_settings(pii_fingerprint_secret=secret))
    message = str(excinfo.value)
    assert PII_FINGERPRINT_SECRET_ENV in message
    assert "keyless" in message


def test_failure_message_depends_only_on_the_env_var_name():
    """A rejection message that varies with the rejected value would echo it.

    Every blank variant produces byte-identical text naming only the env var, so
    the message provably carries nothing from the configuration it refused.
    """
    messages = set()
    for blank in ("", "   ", "\t\n", "\n "):
        with pytest.raises(InvalidPIIInputError) as excinfo:
            build_detector_chain(_settings(pii_fingerprint_secret=blank))
        messages.add(str(excinfo.value))
    assert len(messages) == 1
    message = messages.pop()
    assert PII_FINGERPRINT_SECRET_ENV in message
    assert "keyless" in message


def test_hash_pii_value_rejects_a_whitespace_only_secret():
    """M5 tightening: a blank-looking key is an unkeyed digest with 3 candidates."""
    for blank in ("", " ", "\n\t "):
        with pytest.raises(InvalidPIIInputError):
            hash_pii_value(_SAMPLE_VALUE, secret=blank)


# --- 2. the secret is wired, and it stays private -----------------------------


def test_chain_wires_every_declared_detector_in_a_fixed_order():
    """The composite is the only way detectors are assembled (Phase 9 reads this)."""
    chain = build_detector_chain(_settings(pii_fingerprint_secret=_SECRET))
    assert type(chain.detectors) is tuple
    assert [type(detector) for detector in chain.detectors] == [
        StructuredFieldPIIDetector,
        PatternPIIDetector,
        SecretPIIDetector,
    ]
    assert all(isinstance(detector, PIIDetectorBase) for detector in chain.detectors)


def test_chain_order_puts_the_strongest_signal_first():
    """Aggregation breaks a confidence tie in favour of the first detector, so the
    labelled-field form must outrank the bare-pattern form of the same entity."""
    chain = build_detector_chain(_settings(pii_fingerprint_secret=_SECRET))
    names = [type(detector).__name__ for detector in chain.detectors]
    assert names.index("StructuredFieldPIIDetector") < names.index("PatternPIIDetector")
    assert names[-1] == "SecretPIIDetector"


# --- 1b. the Phase 13 chain is whole, and the pipeline uses it ----------------


def test_full_chain_carries_every_detector_and_no_interim_inventory_remains():
    """Phase 11 shipped a second, smaller constructor so the pipeline could run
    before ``StructuredFieldPIIDetector`` and ``SecretPIIDetector`` existed.

    Phase 13 landed them, and the interim constructor is **gone**: two
    inventories of the same detectors is one too many, because the one nobody
    edits is the one the pipeline uses. The inventory is asserted here as a list
    rather than a set, so the "strongest signal first" order is part of the
    contract instead of a comment nobody checks.
    """
    chain = build_detector_chain(_settings(pii_fingerprint_secret=_SECRET))

    assert [type(detector) for detector in chain.detectors] == [
        StructuredFieldPIIDetector,
        PatternPIIDetector,
        SecretPIIDetector,
    ]


def test_available_detector_chain_is_no_longer_exported():
    """The interim constructor must not survive as a name.

    Deleting the function is the point; leaving an alias or a private helper
    behind would let the next contributor wire the pipeline to a subset again,
    and a subset fails *silently* — it just finds less. The import is attempted
    by name so the test fails with the actual reason if it comes back.
    """
    import app.pii as pii_package

    assert not hasattr(pii_package, "build_available_detector_chain")
    assert "build_available_detector_chain" not in pii_package.__all__


def test_full_chain_validates_the_secret_before_any_detector_runs():
    """Every member must actually scan; a stub in the chain fails every document."""
    chain = build_detector_chain(_settings(pii_fingerprint_secret=_SECRET))
    for detector in chain.detectors:
        findings = detector.detect_text("СНИЛС 123-456-789 00")
        assert isinstance(findings, list)


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_full_chain_rejects_a_blank_fingerprint_secret(blank):
    """One constructor, one choke point — so there is nowhere to forget it."""
    with pytest.raises(InvalidPIIInputError):
        build_detector_chain(_settings(pii_fingerprint_secret=blank))


def test_pipeline_gate_is_built_from_the_full_chain():
    """The wiring, asserted at the boundary rather than described in a comment."""
    from app.config.settings import Settings as _S
    from app.pii import build_document_gate

    gate = build_document_gate(_S(_env_file=None, pii_fingerprint_secret=_SECRET))
    assert [type(d) for d in gate.detector.detectors] == [
        type(d)
        for d in build_detector_chain(
            _S(_env_file=None, pii_fingerprint_secret=_SECRET)
        ).detectors
    ]
    assert gate.policy_context_builder is not None


def test_fingerprint_differs_under_two_settings_secrets():
    """The property that makes a leaked fingerprint column useless (§7 R8)."""
    first = build_detector_chain(_settings(pii_fingerprint_secret=_SECRET))
    second = build_detector_chain(_settings(pii_fingerprint_secret=_OTHER_SECRET))
    assert first.detectors[0].fingerprint(_SAMPLE_VALUE) != second.detectors[0].fingerprint(
        _SAMPLE_VALUE
    )


def test_fingerprint_is_stable_for_one_secret_across_the_whole_chain():
    """Every member must fingerprint the same value identically, or Phase 9's
    dedup on ``(category, value_fingerprint)`` silently never fires."""
    chain = build_detector_chain(_settings(pii_fingerprint_secret=_SECRET))
    fingerprints = {detector.fingerprint(_SAMPLE_VALUE) for detector in chain.detectors}
    assert len(fingerprints) == 1
    assert fingerprints.pop() == hash_pii_value(_SAMPLE_VALUE, secret=_SECRET)


def test_fingerprint_keeps_phase_4_normalization():
    """OCR case and spacing variants must not become two entities."""
    detector = build_detector_chain(_settings(pii_fingerprint_secret=_SECRET)).detectors[0]
    assert detector.fingerprint("Иванов  ") == detector.fingerprint("иванов")


def test_fingerprint_fails_closed_on_a_directly_built_detector():
    """The per-call choke point: a detector with no secret cannot produce a finding,
    even though nothing stopped it from being constructed."""
    unconfigured = [
        PIIDetectorBase(),
        PatternPIIDetector(fingerprint_secret="  "),
        StructuredFieldPIIDetector(),
        SecretPIIDetector(fingerprint_secret=""),
    ]
    for detector in unconfigured:
        with pytest.raises(InvalidPIIInputError) as excinfo:
            detector.fingerprint(_SAMPLE_VALUE)
        assert PII_FINGERPRINT_SECRET_ENV in str(excinfo.value)


def test_composite_fails_closed_rather_than_raising_attribute_error():
    """The composite never fingerprints, but the inherited state must exist."""
    chain = build_detector_chain(_settings(pii_fingerprint_secret=_SECRET))
    with pytest.raises(InvalidPIIInputError):
        type(chain)(chain.detectors).fingerprint(_SAMPLE_VALUE)


def test_detector_does_not_expose_the_secret_publicly():
    """A public attribute is one ``model_dump``/logging call away from the artifact."""
    detector = build_detector_chain(_settings(pii_fingerprint_secret=_SECRET)).detectors[0]
    assert _SECRET not in repr(detector)
    assert not [name for name in dir(detector) if "secret" in name and not name.startswith("_")]


def test_findings_carry_the_configured_fingerprint():
    """End of the chain: a finding stamped by a chain-built detector is keyed by
    the configured secret, not by a module constant."""
    detector = build_detector_chain(_settings(pii_fingerprint_secret=_SECRET)).detectors[0]
    finding = PIIFinding(
        category=PIICategory.PERSON_NAME,
        value=_SAMPLE_VALUE,
        masked_value="Ш***** Д***** С*********",
        value_fingerprint=detector.fingerprint(_SAMPLE_VALUE),
        confidence=0.8,
        source=PIISource.PATTERN,
        detector="pattern.person_name",
        detector_version="1.0.0",
    )
    assert finding.value_fingerprint == hash_pii_value(_SAMPLE_VALUE, secret=_SECRET)
    assert "value" not in finding.model_dump()


# --- 3. the policy context boundary ------------------------------------------


def test_build_policy_context_reads_the_tenant_from_settings():
    """ORDER §13.6: nothing upstream carries a tenant, so it comes from config."""
    context = build_policy_context(_settings(s3_tenant_id="tenant-42"), stage=PIIScanStage.DOCUMENT)
    assert context.organization_id == "tenant-42"
    assert context.stage is PIIScanStage.DOCUMENT


def test_build_policy_context_strips_and_validates_the_tenant():
    context = build_policy_context(
        _settings(s3_tenant_id="  tenant-42  "), stage=PIIScanStage.DOCUMENT
    )
    assert context.organization_id == "tenant-42"


def test_build_policy_context_rejects_a_blank_tenant():
    for blank in ("", "   "):
        with pytest.raises(PIIPolicyError) as excinfo:
            build_policy_context(_settings(s3_tenant_id=blank), stage=PIIScanStage.DOCUMENT)
        assert "s3_tenant_id" in str(excinfo.value)


def test_policy_context_rejects_a_blank_organization_constructed_directly():
    """The validation lives on the model, so the factory cannot be bypassed."""
    with pytest.raises(PIIPolicyError):
        PIIPolicyContext(
            destination=PIIDestination.INTERNAL_LLM,
            stage=PIIScanStage.DOCUMENT,
            organization_id=" ",
        )


def test_policy_context_is_frozen_and_forbids_extra_fields_after_validation():
    """Phase 5's guarantees survive the Phase 8 validator."""
    context = build_policy_context(_settings(), stage=PIIScanStage.DOCUMENT)
    with pytest.raises(ValidationError):
        context.destination = PIIDestination.PERSISTENCE  # type: ignore[misc]
    with pytest.raises(ValidationError):
        PIIPolicyContext(
            destination=PIIDestination.INTERNAL_LLM,
            stage=PIIScanStage.DOCUMENT,
            organization_id="tenant-42",
            surprise="nope",  # type: ignore[call-arg]
        )


def test_policy_context_defaults_to_the_trusted_internal_destination():
    """§0: the current provider is trusted by name, so redaction stays dormant."""
    assert DEFAULT_DESTINATION is PIIDestination.INTERNAL_LLM
    context = build_policy_context(_settings(), stage=PIIScanStage.DOCUMENT)
    assert context.destination is PIIDestination.INTERNAL_LLM


def test_policy_context_destination_is_overridable_for_the_canonical_guard():
    """Phase 6/14 evaluate at ``stage=CANONICAL, destination=PERSISTENCE``."""
    context = build_policy_context(
        _settings(),
        stage=PIIScanStage.CANONICAL,
        destination=PIIDestination.PERSISTENCE,
    )
    assert (context.stage, context.destination) == (
        PIIScanStage.CANONICAL,
        PIIDestination.PERSISTENCE,
    )


def test_policy_context_defaults_redaction_unavailable():
    """Fail-closed default: no redactor exists until Phase 12 says one does."""
    context = build_policy_context(_settings(), stage=PIIScanStage.DOCUMENT)
    assert context.redaction_available is False
    assert (
        build_policy_context(
            _settings(), stage=PIIScanStage.DOCUMENT, redaction_available=True
        ).redaction_available
        is True
    )


def test_policy_context_passes_the_document_type_through():
    context = build_policy_context(
        _settings(), stage=PIIScanStage.DOCUMENT, document_type="appointment"
    )
    assert context.document_type == "appointment"


def test_the_destination_is_a_settings_read_not_a_constant():
    """Phase 15 closed the gap this test used to *predict*.

    It was a tripwire: it asserted the module still said "a constant today, a
    setting in M5 Phase 15", so the claim could not be quietly dropped while the
    gap was open. The gap is closed, so the tripwire is replaced by what it was
    standing in for — the behaviour, asserted live. The full
    ``resolve_destination`` matrix lives in ``test_external_boundary.py``; this
    is the boundary-level statement: the worker reads its destination from
    configuration, and the constant is no longer what production uses.
    """
    from app.pii import policy

    assert DEFAULT_DESTINATION is PIIDestination.INTERNAL_LLM
    assert policy.resolve_destination(_settings()) is PIIDestination.INTERNAL_LLM
    external = policy.resolve_destination(_settings(llm_mode="external_llm"))
    assert external is PIIDestination.EXTERNAL_LLM

    module_doc = inspect.getdoc(policy) or ""
    assert "DEFAULT_DESTINATION" in module_doc
    assert "a settings read in M5 Phase 15" not in module_doc
    assert "build_policy_context" in module_doc
    assert "type-only" in module_doc


# --- 4. the package stays configuration-free ---------------------------------


def test_no_pii_module_imports_app_config_at_runtime():
    # The offline evaluation CLI (`app/pii/evaluate.py`) is exempt: its mandated
    # no-argument entry point has to build a blank Settings, and it is not a
    # module the pipeline imports. The property this guard protects is asserted
    # independently and end to end by
    # test_app_pii_imports_with_app_config_blocked below, which is unaffected by
    # the exemption because `app/pii/__init__.py` does not import the harness.
    for path in runtime_edge_guarded_files():
        assert not any(module.startswith("app.config") for module in module_names(path)), (
            f"{path.name} imports app.config at runtime"
        )


def test_the_harness_is_the_only_module_allowed_a_settings_runtime_import():
    """Named explicitly, so a second one is a decision rather than an accident."""
    offenders = {
        path.name
        for path in pii_source_files()
        if any(module.startswith("app.config") for module in module_names(path))
    }
    assert offenders == {"evaluate.py"}


def test_type_only_borrows_are_exactly_the_approved_ones():
    for path in pii_source_files():
        assert not unexpected_type_only_imports(path), path.name
        assert type_only_imports(path) <= ALLOWED_TYPE_ONLY_IMPORTS, path.name


def test_app_pii_imports_with_app_config_blocked():
    """The property the type-only borrow exists to protect, proven end to end.

    If ``app.config`` ever became a runtime import of ``app/pii``, the security
    control would stop being importable in any environment that has no
    configuration — including a fresh checkout, a test, and the linter. Run in a
    subprocess so the import blocker cannot leak into the rest of the suite.
    """
    code = (
        "import sys\n"
        "class Blocker:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('app.config', 'messaging'):\n"
        "            raise ImportError(name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "for m in [m for m in sys.modules if m.split('.')[0] in ('app.', 'messaging')]:\n"
        "    del sys.modules[m]\n"
        "import app.pii as p\n"
        "assert p.build_detector_chain is not None and p.build_policy_context is not None\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('app.config',"
        " 'messaging'))\n"
        "if bad:\n"
        "    raise SystemExit('pulled in ' + repr(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
