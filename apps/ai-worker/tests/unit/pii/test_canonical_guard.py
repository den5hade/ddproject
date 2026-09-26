"""Tests for the canonical-output guard contract (M4 Phase 6).

Two things are under test and they are not the same kind of thing:

- :func:`walk_string_leaves` is *implemented*, so it is tested behaviorally —
  including against the two real leaks from ``2b8fdd0d`` and ``fbbcb675``, which
  is the whole reason this contract exists.
- the violation shape, the protocol and the remediation vocabulary are
  *specified*, so they are pinned structurally, the way Phases 1–5 pinned theirs.
"""

import ast
import inspect
import pathlib

import pytest
from app.pii import (
    CANONICAL_POLICY_DESTINATION,
    CANONICAL_POLICY_STAGE,
    DECISION_REMEDIATION,
    CanonicalPIIInspector,
    CanonicalPIIInspectorBase,
    CanonicalPIIViolation,
    PIICategory,
    PIIDecision,
    PIIDestination,
    PIIRemediation,
    PIIScanStage,
    walk_string_leaves,
)
from pydantic import ValidationError

# The two observed leaks, verbatim in shape from .dev/flow_upload_test/.
# The plan's accept criterion is that the contract covers exactly these.
LEAK_2B8FDD0D = {
    "schema_name": "generic",
    "type": "generic",
    "fields": {
        "note": (
            "Осмотр проведен для пациента Шадеркина Дениса Сергеевича. "
            "Номер талона: 2026030709303211960141."
        )
    },
}
LEAK_FBBCB675 = {
    "schema_name": "generic",
    "type": "generic",
    "fields": {"note": "Осмотр для пациента Шадеркина Дениса Сергеевича (М, 39 лет)"},
}

_NAME = "Шадеркин"
_TICKET = "2026030709303211960141"


def _constant_docstring(module, name: str) -> str:
    """The string literal written directly below a module-level assignment.

    ``inspect.getdoc`` cannot be used for this: a docstring under an assignment
    is not attached to the object, so ``getdoc`` on a dict returns ``dict``'s own
    docstring and the assertion would silently pass against the wrong text.
    """
    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    for index, node in enumerate(tree.body):
        targets = (
            [node.target]
            if isinstance(node, ast.AnnAssign)
            else getattr(node, "targets", [])
            if isinstance(node, ast.Assign)
            else []
        )
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        following = tree.body[index + 1] if index + 1 < len(tree.body) else None
        if isinstance(following, ast.Expr) and isinstance(following.value, ast.Constant):
            return following.value.value or ""
    return ""


# --- the free-form walk ------------------------------------------------------


def test_walk_finds_the_observed_leak_path_exactly():
    """The path format must match the real artifact, or a violation is untraceable."""
    paths = dict(walk_string_leaves(LEAK_2B8FDD0D))
    assert "fields.note" in paths
    assert _TICKET in paths["fields.note"]
    assert _NAME in paths["fields.note"]


def test_walk_finds_both_real_leaks():
    for payload in (LEAK_2B8FDD0D, LEAK_FBBCB675):
        paths = dict(walk_string_leaves(payload))
        assert "fields.note" in paths
        assert _NAME in paths["fields.note"]


def test_walk_yields_every_string_leaf():
    payload = {
        "conclusion": "рекомендовано наблюдение",
        "institution": {"name": "ООО Клиника", "address": "Москва"},
        "fields": {"note": "текст", "nested": {"deep": "значение"}},
    }
    assert {path for path, _ in walk_string_leaves(payload)} == {
        "conclusion",
        "institution.name",
        "institution.address",
        "fields.note",
        "fields.nested.deep",
    }


def test_walk_indexes_lists():
    payload = {"fields": {"medications": [{"doctor": "Иванов"}, {"doctor": "Петров"}]}}
    assert list(walk_string_leaves(payload)) == [
        ("fields.medications[0].doctor", "Иванов"),
        ("fields.medications[1].doctor", "Петров"),
    ]


def test_walk_handles_a_list_of_scalars():
    assert list(walk_string_leaves({"fields": ["a", "b"]})) == [
        ("fields[0]", "a"),
        ("fields[1]", "b"),
    ]


def test_walk_visits_a_shared_subobject_under_both_keys():
    """Cycle tracking is path-scoped, so a repeated sub-object is not swallowed."""
    shared = {"name": _NAME}
    assert list(walk_string_leaves({"primary": shared, "secondary": shared})) == [
        ("primary.name", _NAME),
        ("secondary.name", _NAME),
    ]


def test_walk_terminates_on_a_self_referential_payload():
    payload: dict = {"a": "x"}
    payload["self"] = payload
    assert list(walk_string_leaves(payload)) == [("a", "x")]


def test_walk_skips_non_string_leaves():
    """Numbers, booleans and nulls are the documented blind spot, not a crash."""
    payload = {"n": 42, "f": 1.5, "flag": True, "none": None, "s": "kept"}
    assert list(walk_string_leaves(payload)) == [("s", "kept")]


def test_walk_on_empty_containers():
    assert list(walk_string_leaves({})) == []
    assert list(walk_string_leaves({"fields": {}})) == []
    assert list(walk_string_leaves({"fields": []})) == []
    assert list(walk_string_leaves({"fields": None})) == []


def test_walk_yields_nothing_for_a_bare_string_root():
    """A root scalar has no field name, so it has no reportable path."""
    assert list(walk_string_leaves("bare")) == []


def test_walk_stringifies_non_string_keys():
    assert list(walk_string_leaves({1: "one"})) == [("1", "one")]


def test_walk_does_not_mutate_the_payload():
    payload = LEAK_2B8FDD0D
    before = repr(payload)
    list(walk_string_leaves(payload))
    assert repr(payload) == before


def test_walk_yields_empty_strings_rather_than_skipping_them():
    """An empty string is a value the detector may still need to see."""
    assert list(walk_string_leaves({"fields": {"note": ""}})) == [("fields.note", "")]


def test_walk_is_deterministic():
    first = list(walk_string_leaves(LEAK_2B8FDD0D))
    second = list(walk_string_leaves(LEAK_2B8FDD0D))
    assert first == second


# --- violation shape ---------------------------------------------------------


def test_violation_carries_no_raw_value_field():
    """The second leak boundary obeys the Phase 1 rule structurally."""
    assert "value" not in CanonicalPIIViolation.model_fields
    assert "raw" not in CanonicalPIIViolation.model_fields
    assert set(CanonicalPIIViolation.model_fields) == {
        "field_path",
        "category",
        "masked_value",
        "confidence",
    }


def test_violation_forbids_extra_fields():
    with pytest.raises(ValidationError):
        CanonicalPIIViolation(
            field_path="fields.note",
            category=PIICategory.PERSON_NAME,
            masked_value="Ш*******",
            confidence=0.9,
            value="Шадеркин Денис Сергеевич",  # type: ignore[call-arg]
        )


def test_violation_is_frozen():
    violation = CanonicalPIIViolation(
        field_path="fields.note",
        category=PIICategory.PERSON_NAME,
        masked_value="Ш*******",
        confidence=0.9,
    )
    with pytest.raises(ValidationError):
        violation.field_path = "fields.other"  # type: ignore[misc]


def test_violation_serializes_without_a_raw_value():
    violation = CanonicalPIIViolation(
        field_path="fields.note",
        category=PIICategory.TICKET_NUMBER,
        masked_value="20********************",
        confidence=0.97,
    )
    assert _TICKET not in violation.model_dump_json()


# --- policy inputs -----------------------------------------------------------


def test_canonical_policy_inputs_are_the_locked_pair():
    assert CANONICAL_POLICY_STAGE is PIIScanStage.CANONICAL
    assert CANONICAL_POLICY_DESTINATION is PIIDestination.PERSISTENCE


def test_canonical_guard_findings_would_evaluate_under_persistence():
    """Persisting is a different policy question from reading the source document."""
    assert CANONICAL_POLICY_DESTINATION is not PIIDestination.INTERNAL_LLM
    assert CANONICAL_POLICY_STAGE is not PIIScanStage.DOCUMENT


# --- remediation -------------------------------------------------------------


def test_remediation_vocabulary_is_exactly_the_three_named_actions():
    assert {r.value for r in PIIRemediation} == {"warn", "sanitize", "retry_then_fail"}


def test_remediation_covers_every_decision():
    assert set(DECISION_REMEDIATION) == {d.value for d in PIIDecision}


def test_remediation_mapping_matches_the_proposal():
    assert DECISION_REMEDIATION["allow"] is PIIRemediation.WARN
    assert DECISION_REMEDIATION["allow_with_warning"] is PIIRemediation.SANITIZE
    assert DECISION_REMEDIATION["review"] is PIIRemediation.SANITIZE
    assert DECISION_REMEDIATION["block"] is PIIRemediation.RETRY_THEN_FAIL


def test_only_block_retries_and_fails():
    retrying = {d for d, r in DECISION_REMEDIATION.items() if r is PIIRemediation.RETRY_THEN_FAIL}
    assert retrying == {PIIDecision.BLOCK.value}


def test_remediation_mapping_is_marked_unlocked():
    """M4 names the actions; M5 owns the mapping. The module must not imply otherwise."""
    from app.pii import canonical_guard

    doc = inspect.getdoc(canonical_guard) or ""
    mapping_doc = _constant_docstring(canonical_guard, "DECISION_REMEDIATION")
    assert "Not locked" in mapping_doc
    assert "M5" in mapping_doc
    assert "retry" in doc


# --- protocol ----------------------------------------------------------------


def test_inspector_protocol_shape():
    assert getattr(CanonicalPIIInspector, "_is_protocol", False) is True
    assert not inspect.iscoroutinefunction(CanonicalPIIInspector.inspect)
    assert list(inspect.signature(CanonicalPIIInspector.inspect).parameters) == [
        "self",
        "payload",
    ]


def test_inspector_protocol_takes_no_context():
    """Documented consequence: policy inputs must be constructor state in M5."""
    assert "context" not in inspect.signature(CanonicalPIIInspector.inspect).parameters


def test_inspector_stub_raises():
    with pytest.raises(NotImplementedError) as excinfo:
        CanonicalPIIInspectorBase().inspect({})
    assert "M5" in str(excinfo.value)


def test_inspector_base_implements_the_protocol():
    assert CanonicalPIIInspector in CanonicalPIIInspectorBase.__mro__


# --- documented limits -------------------------------------------------------


def test_module_documents_the_walk_rule():
    from app.pii import canonical_guard

    doc = inspect.getdoc(canonical_guard) or ""
    assert "every string leaf" in doc
    assert "BaseCanonical.fields" in doc
    assert "2b8fdd0d" in doc and "fbbcb675" in doc


def test_module_documents_the_numeric_blind_spot():
    from app.pii import canonical_guard

    doc = inspect.getdoc(canonical_guard) or ""
    assert "Numeric leaves are the known blind spot" in doc
    assert "recorded rather than" in doc


# --- import boundary ---------------------------------------------------------


def test_guard_imports_nothing_outside_the_package():
    from tests.support.pii_imports import PII_PACKAGE_DIR, module_names

    allowed = {"__future__", "collections", "enum", "typing", "pydantic"}
    outside = {
        module
        for module in module_names(PII_PACKAGE_DIR / "canonical_guard.py")
        if not module.startswith("app.pii") and module.split(".")[0] not in allowed
    }
    assert outside == set(), f"canonical_guard.py imports outside the boundary: {outside}"


def test_guard_does_not_import_canonical_models():
    """The guard reads a serialized payload; it must not bind to a schema class."""
    from tests.support.pii_imports import PII_PACKAGE_DIR, imports_forbidden_domains

    assert imports_forbidden_domains(PII_PACKAGE_DIR / "canonical_guard.py") == set()
    assert "packages.canonical" not in repr(
        imports_forbidden_domains(PII_PACKAGE_DIR / "canonical_guard.py")
    )
