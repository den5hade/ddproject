"""Tests for the PII policy table and the gate contract (M4 Phase 5).

The value-for-value table assertions are written out longhand on purpose. A test
that compared :data:`CATEGORY_RISK` against a copy of itself would pass forever
and prove nothing; instead each risk level is asserted against the literal from
plan §4.4, so editing the table to weaken a category fails here.
"""

import inspect
import os
import subprocess
import sys
import typing
from pathlib import Path

import pytest
from app.pii import (
    CATEGORY_RISK,
    DECISION_OUTCOMES,
    DEFAULT_POLICY,
    PII_CATEGORY_GROUPS,
    PII_POLICY_VERSION,
    REDACT_ON_EXTERNAL,
    PIIAction,
    PIICategory,
    PIIDecision,
    PIIDestination,
    PIIFinding,
    PIIGate,
    PIIGateBase,
    PIIPolicy,
    PIIPolicyContext,
    PIIPolicyError,
    PIIRiskLevel,
    PIIRule,
    PIIScanStage,
    PIISource,
    PolicyEngine,
    PolicyEngineBase,
)
from pydantic import ValidationError
from tests.support.pii_imports import (
    ALLOWED_TYPE_ONLY_IMPORTS,
    PII_PACKAGE_DIR,
    imports_forbidden_domains,
    module_names,
    type_only_imports,
)

APP_ROOT = Path(__file__).resolve().parents[3]

_ORG = "org-42"

# Plan §4.4, transcribed independently of the implementation dict.
_LOCKED_RISK = {
    PIICategory.SECRET: PIIRiskLevel.CRITICAL,
    PIICategory.PASSPORT: PIIRiskLevel.HIGH,
    PIICategory.NATIONAL_ID: PIIRiskLevel.HIGH,
    PIICategory.INN: PIIRiskLevel.HIGH,
    PIICategory.SNILS: PIIRiskLevel.HIGH,
    PIICategory.INSURANCE_NUMBER: PIIRiskLevel.HIGH,
    PIICategory.PATIENT_ID: PIIRiskLevel.HIGH,
    PIICategory.MEDICAL_RECORD_NUMBER: PIIRiskLevel.HIGH,
    PIICategory.LAB_ORDER_ID: PIIRiskLevel.HIGH,
    PIICategory.ENCOUNTER_ID: PIIRiskLevel.HIGH,
    PIICategory.TICKET_NUMBER: PIIRiskLevel.HIGH,
    PIICategory.PERSON_NAME: PIIRiskLevel.MEDIUM,
    PIICategory.DOCTOR_NAME: PIIRiskLevel.MEDIUM,
    PIICategory.DATE_OF_BIRTH: PIIRiskLevel.MEDIUM,
    PIICategory.PHONE: PIIRiskLevel.MEDIUM,
    PIICategory.ADDRESS: PIIRiskLevel.MEDIUM,
    PIICategory.DOCTOR_LICENSE: PIIRiskLevel.MEDIUM,
    PIICategory.AGE: PIIRiskLevel.LOW,
    PIICategory.GENDER: PIIRiskLevel.LOW,
    PIICategory.NATIONALITY: PIIRiskLevel.LOW,
    PIICategory.EMAIL: PIIRiskLevel.LOW,
    PIICategory.ORGANIZATION_NAME: PIIRiskLevel.LOW,
    PIICategory.ORGANIZATION_ID: PIIRiskLevel.LOW,
}

_LOCKED_GROUPS = {
    "identity": {"person_name", "date_of_birth", "age", "gender", "nationality"},
    "contact": {"email", "phone", "address"},
    "government": {"passport", "national_id", "insurance_number", "snils", "inn"},
    "medical_id": {
        "patient_id",
        "medical_record_number",
        "lab_order_id",
        "encounter_id",
        "ticket_number",
    },
    "practitioner": {"doctor_name", "doctor_license", "organization_name", "organization_id"},
    "secret": {"secret"},
}


def _context(**overrides) -> PIIPolicyContext:
    base = {
        "destination": PIIDestination.INTERNAL_LLM,
        "stage": PIIScanStage.DOCUMENT,
        "organization_id": _ORG,
    }
    return PIIPolicyContext(**(base | overrides))


def _finding(category: PIICategory) -> PIIFinding:
    return PIIFinding(
        category=category,
        value="raw",
        masked_value="***",
        value_fingerprint="hmac-sha256:" + "0" * 64,
        confidence=0.9,
        source=PIISource.PATTERN,
        detector="pattern.test",
        detector_version="1.0.0",
    )


# --- the locked table, value-for-value --------------------------------------


@pytest.mark.parametrize(("category", "risk"), sorted(_LOCKED_RISK.items(), key=str))
def test_category_risk_matches_the_locked_table(category, risk):
    assert CATEGORY_RISK[category] is risk


def test_category_risk_covers_every_category_exactly_once():
    assert set(CATEGORY_RISK) == set(PIICategory)
    assert len(CATEGORY_RISK) == 23


def test_risk_level_counts_match_the_locked_ladder():
    counts: dict[PIIRiskLevel, int] = {}
    for risk in CATEGORY_RISK.values():
        counts[risk] = counts.get(risk, 0) + 1
    assert counts == {
        PIIRiskLevel.CRITICAL: 1,
        PIIRiskLevel.HIGH: 10,
        PIIRiskLevel.MEDIUM: 6,
        PIIRiskLevel.LOW: 6,
    }


def test_only_secret_blocks_in_the_default_policy():
    """PII presence alone never blocks; only a credential does (IMPL_ARCH §13)."""
    blocking = [c for c, r in DEFAULT_POLICY.rules.items() if r.action is PIIAction.BLOCK]
    allowing = [c for c, r in DEFAULT_POLICY.rules.items() if r.action is PIIAction.ALLOW]
    assert blocking == [PIICategory.SECRET]
    assert len(allowing) == 22


def test_default_policy_risk_agrees_with_the_risk_table():
    for category, risk in CATEGORY_RISK.items():
        assert DEFAULT_POLICY.risk_for(category) is risk


def test_default_policy_accessors_agree_with_the_rules():
    for category, rule in DEFAULT_POLICY.rules.items():
        assert DEFAULT_POLICY.action_for(category) is rule.action
        assert DEFAULT_POLICY.risk_for(category) is rule.risk_level


def test_policy_version_is_stamped_from_a_single_source():
    assert PII_POLICY_VERSION == "1.0.0"
    assert DEFAULT_POLICY.version == PII_POLICY_VERSION


def test_default_policy_is_complete():
    assert set(DEFAULT_POLICY.rules) == set(PIICategory)
    assert len(DEFAULT_POLICY.rules) == 23


# --- groups and the external override ---------------------------------------


@pytest.mark.parametrize("group", sorted(_LOCKED_GROUPS))
def test_category_groups_match_the_taxonomy(group):
    assert {c.value for c in PII_CATEGORY_GROUPS[group]} == _LOCKED_GROUPS[group]


def test_groups_partition_the_taxonomy():
    union = set().union(*PII_CATEGORY_GROUPS.values())
    total = sum(len(g) for g in PII_CATEGORY_GROUPS.values())
    assert union == set(PIICategory)
    assert total == 23, "groups must be disjoint"


def test_redact_on_external_is_exactly_the_four_patient_groups():
    expected = (
        _LOCKED_GROUPS["identity"]
        | _LOCKED_GROUPS["contact"]
        | _LOCKED_GROUPS["government"]
        | _LOCKED_GROUPS["medical_id"]
    )
    assert {c.value for c in REDACT_ON_EXTERNAL} == expected
    assert len(REDACT_ON_EXTERNAL) == 18
    assert PIICategory.SECRET not in REDACT_ON_EXTERNAL
    assert PIICategory.ORGANIZATION_NAME not in REDACT_ON_EXTERNAL
    assert PIICategory.DOCTOR_NAME not in REDACT_ON_EXTERNAL


# --- PIIPolicy invariants ---------------------------------------------------


def test_policy_rejects_a_partial_table():
    """A category with no rule has no action, and every fallback leaks."""
    partial = {k: v for k, v in DEFAULT_POLICY.rules.items() if k is not PIICategory.SECRET}
    with pytest.raises(PIIPolicyError) as excinfo:
        PIIPolicy(version="1.0.0", rules=partial)
    assert "secret" in str(excinfo.value).lower()


def test_policy_rejects_an_empty_table():
    with pytest.raises(PIIPolicyError):
        PIIPolicy(version="1.0.0", rules={})


def test_policy_and_rule_are_frozen():
    with pytest.raises(ValidationError):
        DEFAULT_POLICY.version = "2.0.0"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        DEFAULT_POLICY.rules[PIICategory.SECRET].action = PIIAction.ALLOW  # type: ignore[misc]


def test_policy_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PIIPolicy(version="1.0.0", rules=DEFAULT_POLICY.rules, surprise=1)  # type: ignore[call-arg]


def test_rule_rejects_extra_fields():
    with pytest.raises(ValidationError):
        PIIRule(action=PIIAction.ALLOW, risk_level=PIIRiskLevel.LOW, why="x")  # type: ignore[call-arg]


def test_policy_context_is_frozen():
    context = _context()
    with pytest.raises(ValidationError):
        context.destination = PIIDestination.EXTERNAL_LLM  # type: ignore[misc]


def test_policy_context_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PIIPolicyContext(
            destination=PIIDestination.INTERNAL_LLM,
            stage=PIIScanStage.DOCUMENT,
            organization_id=_ORG,
            surprise="nope",  # type: ignore[call-arg]
        )


def test_redaction_available_defaults_to_false():
    """Fail-closed default: a policy may not assume a redactor exists."""
    assert _context().redaction_available is False
    assert _context(redaction_available=True).redaction_available is True


def test_document_type_is_optional():
    assert _context().document_type is None
    assert _context(document_type="appointment").document_type == "appointment"


def test_organization_id_is_required():
    """Explicitly not optional in §4.4, unlike ``document_type``."""
    with pytest.raises(ValidationError):
        PIIPolicyContext(  # type: ignore[call-arg]
            destination=PIIDestination.INTERNAL_LLM,
            stage=PIIScanStage.DOCUMENT,
        )


# --- the documented algorithm ------------------------------------------------


def test_policy_documents_the_precedence_order():
    from app.pii import policy

    doc = inspect.getdoc(policy) or ""
    assert "BLOCK > REVIEW > ALLOW_WITH_WARNING > ALLOW" in doc
    assert "low < medium < high < critical" in doc
    assert "No findings means ``LOW``" in doc


def test_policy_documents_the_fail_closed_redaction_escalation():
    from app.pii import policy

    doc = inspect.getdoc(policy) or ""
    assert "redaction_available" in doc
    assert "never to downgrade it to ``ALLOW``" in doc


def test_policy_documents_every_destination():
    from app.pii import policy

    doc = inspect.getdoc(policy) or ""
    for destination in PIIDestination:
        assert destination.name in doc, f"the {destination.name} override must be documented"


def test_policy_documents_the_pipeline_order():
    from app.pii import policy

    assert "detect → aggregate → policy → decide" in (inspect.getdoc(policy) or "")


# --- engine protocol ---------------------------------------------------------


def test_policy_engine_protocol_shape():
    assert getattr(PolicyEngine, "_is_protocol", False) is True
    assert not inspect.iscoroutinefunction(PolicyEngine.evaluate)
    parameters = list(inspect.signature(PolicyEngine.evaluate).parameters)
    assert parameters == ["self", "findings", "context"]


def test_policy_engine_stub_raises():
    with pytest.raises(NotImplementedError) as excinfo:
        PolicyEngineBase().evaluate([_finding(PIICategory.SECRET)], _context())
    assert "M5" in str(excinfo.value)


def test_policy_engine_base_implements_the_protocol():
    # Not ``issubclass`` against the Protocol: the protocols are deliberately not
    # ``@runtime_checkable`` (matching Phase 3's ``PIIDetector``), so a nominal
    # MRO check is the assertion that means something here.
    assert PolicyEngine in PolicyEngineBase.__mro__


# --- gate protocol -----------------------------------------------------------


def test_gate_is_a_protocol_with_the_order_section_8_signature():
    assert getattr(PIIGate, "_is_protocol", False) is True
    assert inspect.iscoroutinefunction(PIIGate.inspect)
    assert list(inspect.signature(PIIGate.inspect).parameters) == ["self", "document", "context"]


def test_gate_signature_annotations_name_the_order_types():
    """Read the annotations off the signature rather than ``get_type_hints``.

    The two types are imported under ``TYPE_CHECKING``, so they are not in the
    module namespace at runtime and ``get_type_hints`` raises ``NameError`` on
    them. That failure is itself the proof that the borrow is type-only; the
    annotations are therefore compared as the strings they are.
    """
    signature = inspect.signature(PIIGate.inspect)
    assert signature.parameters["document"].annotation == "NormalizedDocument"
    assert signature.parameters["context"].annotation == "ProcessingContext"
    assert signature.return_annotation == "PIIScanResult"


def test_gate_annotations_are_unresolvable_at_runtime():
    """The type-only borrow must not become a runtime dependency."""
    with pytest.raises(NameError):
        typing.get_type_hints(PIIGate.inspect)


def test_gate_is_document_level_not_schema_level():
    """ORDER §8's actual claim: one gate, never ``AppointmentPIIGate``."""
    from app.pii import gate

    assert not hasattr(gate, "AppointmentPIIGate")
    doc = inspect.getdoc(gate) or ""
    assert "AppointmentPIIGate" in doc
    assert "document-level capability" in doc


def test_gate_stub_raises():
    import asyncio

    with pytest.raises(NotImplementedError) as excinfo:
        asyncio.run(PIIGateBase().inspect(None, None))  # type: ignore[arg-type]
    assert "M5" in str(excinfo.value)


def test_gate_base_implements_the_protocol():
    assert PIIGate in PIIGateBase.__mro__


def test_gate_does_not_actually_take_a_schema_specific_gate():
    """The base is generic: no appointment/laboratory specialisation leaks in."""
    from app.pii import gate

    assert not [n for n in dir(gate) if n.endswith("PIIGate") and n != "PIIGate"]


# --- import boundary ---------------------------------------------------------


def test_gate_borrows_exactly_the_two_allowed_types():
    borrowed = type_only_imports(PII_PACKAGE_DIR / "gate.py")
    assert borrowed <= ALLOWED_TYPE_ONLY_IMPORTS
    assert ("app.pipeline.context", "ProcessingContext") in borrowed
    assert ("app.classification.normalize", "NormalizedDocument") in borrowed


def test_gate_has_no_runtime_classification_or_pipeline_dependency():
    """The boundary that keeps ``app/pii`` importable without the pipeline."""
    assert imports_forbidden_domains(PII_PACKAGE_DIR / "gate.py") == set()
    assert "app.pipeline.context" not in module_names(PII_PACKAGE_DIR / "gate.py")
    assert "app.classification.normalize" not in module_names(PII_PACKAGE_DIR / "gate.py")


def test_policy_and_gate_import_nothing_outside_the_package():
    allowed = {"__future__", "typing", "pydantic"}
    for name in ("policy.py", "gate.py"):
        outside = {
            module
            for module in module_names(PII_PACKAGE_DIR / name)
            if not module.startswith("app.pii") and module.split(".")[0] not in allowed
        }
        assert outside == set(), f"{name} imports outside the boundary: {outside}"


def test_processing_context_borrow_is_narrowed_to_the_one_symbol():
    """Guards the Phase 3 guard itself against being widened wholesale."""
    assert {
        ("app.classification.normalize", "NormalizedDocument"),
        ("app.pipeline.context", "ProcessingContext"),
    } == ALLOWED_TYPE_ONLY_IMPORTS


def test_pii_package_imports_with_no_pipeline_and_no_classification():
    """The boundary the type-only borrows exist to protect, proven end to end.

    ``PIIGate.inspect`` names ``ProcessingContext`` and ``NormalizedDocument``,
    and both are imported under ``TYPE_CHECKING``. If either became a runtime
    import, ``app.pii`` would stop being importable on its own — and with it any
    test, tool or service that wants the PII contract without the pipeline. Run
    in a subprocess so the import blocker cannot leak into the rest of the suite.
    """
    code = (
        "import sys\n"
        "class Blocker:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('app.pipeline', 'app.classification'):\n"
        "            raise ImportError(name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "for m in [m for m in sys.modules if m.startswith('app.')]:\n"
        "    del sys.modules[m]\n"
        "import app.pii as p\n"
        "assert p.PIIGate is not None and p.DEFAULT_POLICY is not None\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('app.pipeline',"
        " 'app.classification'))\n"
        "if bad:\n"
        "    raise SystemExit('pulled in ' + repr(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(APP_ROOT)},
        check=False,
    )
    assert result.returncode == 0, result.stderr


# --- decision → outcome mapping ----------------------------------------------


def test_decision_outcomes_cover_every_decision():
    assert set(DECISION_OUTCOMES) == {d.value for d in PIIDecision}


def test_decision_outcomes_match_the_plan_table():
    assert DECISION_OUTCOMES["allow"] == "continue"
    assert DECISION_OUTCOMES["allow_with_warning"].startswith("continue")
    assert "needs_review" in DECISION_OUTCOMES["review"]
    assert "halt" in DECISION_OUTCOMES["review"]
    assert "processing failure" in DECISION_OUTCOMES["block"]
    assert "halt" in DECISION_OUTCOMES["block"]


def test_halting_decisions_are_exactly_review_and_block():
    halting = {d for d, outcome in DECISION_OUTCOMES.items() if "halt" in outcome}
    assert halting == {PIIDecision.REVIEW.value, PIIDecision.BLOCK.value}


def test_only_redaction_records_that_something_happened():
    """A redacted document continues; the record is what survives."""
    assert "record" in DECISION_OUTCOMES["allow_with_warning"]
