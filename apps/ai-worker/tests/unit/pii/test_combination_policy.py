"""Tests for the cross-category combination threshold (M5 Phase 17).

Every other rule in the policy table is per category, so before this phase the
engine had no way to say that one finding is fine and two together are not.
:mod:`app.pii.policy` closes that with a ``PIIPolicy.combinations`` table and one
narrow rule: two distinct government identifiers in a document is ``REVIEW``.

The tests here are shaped by which way this rule can fail. It cannot fail by
*under*-firing in any way the existing fixtures can detect — they carry no
government identifiers at all — so the assertions that carry the value are the
**negative** ones: ``PERSON_NAME + SNILS`` must stay ``ALLOW``, a single
government identifier must stay ``ALLOW``, and no existing fixture may change
decision. A threshold that halts routine care is the failure mode, so the
narrowness is asserted as carefully as the escalation.
"""

from __future__ import annotations

import pytest
from app.pii import (
    CATEGORY_RISK,
    DEFAULT_POLICY,
    PII_POLICY_VERSION,
    PIIAction,
    PIICategory,
    PIIDecision,
    PIIDestination,
    PIIFinding,
    PIIPolicy,
    PIIPolicyContext,
    PIIPolicyError,
    PIIRiskLevel,
    PIIScanStage,
    PIISource,
)
from app.pii.policy import DefaultPolicyEngine, PIICombinationRule

ORGANIZATION = "tenant-1"


def _finding(category: PIICategory) -> PIIFinding:
    return PIIFinding(
        category=category,
        value="x",
        masked_value="X",
        value_fingerprint=f"hmac-sha256:{category.value}",
        confidence=0.95,
        source=PIISource.PATTERN,
        detector="test.finding",
        detector_version="1.2.0",
    )


def _context(
    destination: PIIDestination = PIIDestination.INTERNAL_LLM,
    *,
    redaction_available: bool = True,
    stage: PIIScanStage = PIIScanStage.DOCUMENT,
) -> PIIPolicyContext:
    return PIIPolicyContext(
        destination=destination,
        stage=stage,
        organization_id=ORGANIZATION,
        redaction_available=redaction_available,
    )


def _evaluate(*categories: PIICategory, context: PIIPolicyContext | None = None):
    return DefaultPolicyEngine().evaluate(
        [_finding(category) for category in categories],
        context or _context(),
    )


# --- the shipped table -------------------------------------------------------


def test_the_shipped_rule_is_two_government_identifiers():
    """The one row, asserted field by field rather than against a copy of itself.

    A test comparing ``DEFAULT_POLICY.combinations`` to a reconstructed object
    would pass a weakened table unchanged, which is the mistake ``test_policy_gate``
    already documents for the risk table. These are the literals from plan §4.13.
    """
    assert len(DEFAULT_POLICY.combinations) == 1
    rule = DEFAULT_POLICY.combinations[0]
    assert rule.requires_groups == frozenset({"government"})
    assert rule.min_count == 2
    assert rule.decision is PIIDecision.REVIEW


def test_the_rule_is_reachable_through_the_stamped_policy_version():
    """Acceptance criterion 9: the version names the table that produced a verdict.

    The rule lives on :class:`PIIPolicy` rather than in a module constant
    precisely so that this holds — ``PII_POLICY_VERSION`` *is*
    ``DEFAULT_POLICY.version``, so a stored ``PIIScanResult`` naming ``3.0.0``
    names a policy that carries the combination table. A module constant would
    leave the version pointing at a table the version cannot describe.
    """
    assert PII_POLICY_VERSION == "3.0.0"
    assert DEFAULT_POLICY.version == PII_POLICY_VERSION
    assert DEFAULT_POLICY.combinations


# --- both sides of the threshold ---------------------------------------------


def test_person_name_and_snils_stay_allow():
    """The narrowness assertion, and the ``IDENTIFIER_MARKER`` regression.

    ФИО + СНИЛС is the most ordinary pair in a Russian medical document and the
    pipeline's ``IDENTIFIER_MARKER`` test asserts it is *allowed*. This is the
    single test that would have failed had Phase 17 shipped ORDER §13.1's
    "identity + government ID" example instead of the narrow rule.
    """
    result = _evaluate(PIICategory.PERSON_NAME, PIICategory.SNILS)

    assert result.decision is PIIDecision.ALLOW
    assert not any("combination" in reason for reason in result.reasons)


def test_person_name_and_snils_and_insurance_number_is_review():
    """The §45.19 accept case, with the two government identifiers present."""
    result = _evaluate(
        PIICategory.PERSON_NAME,
        PIICategory.SNILS,
        PIICategory.INSURANCE_NUMBER,
    )

    assert result.decision is PIIDecision.REVIEW


@pytest.mark.parametrize(
    "single",
    [
        PIICategory.SNILS,
        PIICategory.INSURANCE_NUMBER,
        PIICategory.PASSPORT,
        PIICategory.NATIONAL_ID,
        PIICategory.INN,
    ],
)
def test_a_single_government_identifier_does_not_escalate(single):
    """Every government category alone, on its own, stays ``ALLOW``.

    Parametrised over the group so a category added to ``government`` cannot
    arrive already tripping: the rule counts members of the group, and only the
    count of two is an escalation.
    """
    result = _evaluate(single)

    assert result.decision is PIIDecision.ALLOW


def test_one_identifier_repeated_in_the_document_does_not_escalate():
    """``min_count`` is distinct *categories*, not findings.

    A document repeating one identifier is not a combination. The aggregator
    already collapses an identical value to one finding, so this is reached
    through two different values of the same category rather than a repeated
    finding — which is the case a naive ``len(findings)`` threshold would trip.
    """
    engine = DefaultPolicyEngine()
    findings = [
        _finding(PIICategory.SNILS),
        PIIFinding(
            category=PIICategory.SNILS,
            value="y",
            masked_value="Y",
            value_fingerprint="hmac-sha256:snils-2",
            confidence=0.95,
            source=PIISource.PATTERN,
            detector="test.finding",
            detector_version="1.2.0",
        ),
    ]

    assert engine.evaluate(findings, _context()).decision is PIIDecision.ALLOW


def test_a_government_identifier_outside_the_threshold_still_uses_the_normal_algorithm():
    """Adding the rule did not disturb per-category resolution.

    The two identifiers resolve to ``ALLOW`` in ``actions`` exactly as before; the
    combination is a *separate* signal that joins the decision, not a replacement
    for the table.
    """
    result = _evaluate(PIICategory.SNILS, PIICategory.PASSPORT)

    assert result.actions == {
        PIICategory.SNILS: PIIAction.ALLOW,
        PIICategory.PASSPORT: PIIAction.ALLOW,
    }


# --- the escalation reaches the decision and nothing else ---------------------


def test_review_never_adds_a_redact_action():
    """Acceptance criterion 3: the escalation is decision-only.

    §4.12 makes ``actions`` the remediation channel and the canonical sanitizer
    masks a leaf iff its action is ``REDACT``, so writing ``REVIEW`` into the
    participating categories would stop those leaves being masked in any future
    where ``REVIEW`` does not halt, and would make the per-category table lie.
    Compared against the same findings evaluated by a policy with no
    combinations at all, which is the strongest form of the claim: the escalation
    changes the decision and nothing else about the result.
    """
    categories = (PIICategory.PERSON_NAME, PIICategory.SNILS, PIICategory.INSURANCE_NUMBER)
    with_rule = _evaluate(*categories)
    without_rule = DefaultPolicyEngine(_policy_without_combinations()).evaluate(
        [_finding(category) for category in categories], _context()
    )

    assert with_rule.actions == without_rule.actions
    assert all(action is not PIIAction.REDACT for action in with_rule.actions.values())
    assert with_rule.decision is PIIDecision.REVIEW
    assert without_rule.decision is PIIDecision.ALLOW


def test_the_escalation_does_not_weaken_the_persistence_redaction():
    """The §4.11 contour still redacts, and the combination still halts.

    At ``stage=canonical, destination=persistence`` the participating categories
    are ``REDACT``. The combination escalates the decision to ``REVIEW``, so the
    document halts *before* any dump rather than being written — which is the
    Phase 14 decision-16 ordering, reached now through a second route. The
    important half is that the ``REDACT`` in ``actions`` is untouched: a
    combination must not be able to downgrade a redaction.
    """
    result = _evaluate(
        PIICategory.PERSON_NAME,
        PIICategory.SNILS,
        PIICategory.INSURANCE_NUMBER,
        context=_context(PIIDestination.PERSISTENCE, stage=PIIScanStage.CANONICAL),
    )

    assert result.actions == {
        PIICategory.PERSON_NAME: PIIAction.REDACT,
        PIICategory.SNILS: PIIAction.REDACT,
        PIICategory.INSURANCE_NUMBER: PIIAction.REDACT,
    }
    assert result.decision is PIIDecision.REVIEW


def test_the_escalation_is_recorded_in_reasons():
    """A ``REVIEW`` that does not say why is a halt nobody can triage (R9, R15).

    The reason names the group and the threshold, so an operator reading the log
    line that Phase 11 writes can tell this apart from the redaction-unavailable
    review it shares an ``error_code`` with.
    """
    result = _evaluate(PIICategory.SNILS, PIICategory.INSURANCE_NUMBER)

    combination = [reason for reason in result.reasons if reason.startswith("combination:")]
    assert len(combination) == 1
    assert "government" in combination[0]
    assert ">=2" in combination[0]


def test_risk_level_is_unchanged_by_the_combination():
    """Risk answers "how sensitive", escalation answers "how to handle".

    §4.4 computes risk as the maximum category risk independently of any
    handling decision. A combination must not inflate it, or a document would
    start reporting a risk level its categories do not support.
    """
    result = _evaluate(PIICategory.SNILS, PIICategory.INSURANCE_NUMBER)

    assert result.risk_level is DEFAULT_POLICY.risk_for(PIICategory.SNILS)


# --- precedence ---------------------------------------------------------------


def test_a_combination_never_displaces_a_block():
    """A secret plus two government identifiers is a ``BLOCK``.

    ``SECRET`` is the only ``BLOCK`` source and this asserts a combination cannot
    become a second one. A document degraded from ``BLOCK`` to ``REVIEW`` would be
    sent to a human queue that does not exist, which is the specific harm R15
    already records.
    """
    result = _evaluate(
        PIICategory.SECRET,
        PIICategory.SNILS,
        PIICategory.INSURANCE_NUMBER,
    )

    assert result.decision is PIIDecision.BLOCK
    assert result.actions[PIICategory.SECRET] is PIIAction.BLOCK


def test_a_combination_joins_precedence_at_review_not_above_warning():
    """Two identifiers plus a redaction is ``REVIEW``, not ``ALLOW_WITH_WARNING``.

    ``REVIEW`` sits above ``ALLOW_WITH_WARNING`` in §4.4's precedence, so the
    combination outranks an applied redaction. Asserted at the external boundary,
    where every identity category is redacted and the residue would otherwise be
    ``ALLOW_WITH_WARNING``.
    """
    result = _evaluate(
        PIICategory.SNILS,
        PIICategory.INSURANCE_NUMBER,
        context=_context(PIIDestination.EXTERNAL_LLM),
    )

    assert result.decision is PIIDecision.REVIEW
    assert result.actions[PIICategory.SNILS] is PIIAction.REDACT


def test_a_combination_applies_at_every_destination():
    """Document-scoped, not leaf-scoped: the destination cannot suppress it.

    This is the deviation from ORDER §13.1's "in one free-text leaf" wording made
    visible. The rule is evaluated once over the document's distinct categories,
    so it fires identically at every boundary — including the unknown
    destination, where per-category actions are already ``REVIEW`` and the
    combination's contribution is idempotent.
    """
    for destination in PIIDestination:
        result = _evaluate(
            PIICategory.SNILS,
            PIICategory.INSURANCE_NUMBER,
            context=_context(destination),
        )
        assert result.decision is PIIDecision.REVIEW, destination


# --- construction-time guards -------------------------------------------------


def test_a_combination_rule_may_not_block():
    """A ``BLOCK`` combination is rejected when the policy is built.

    Blocking is reserved for ``SECRET``; a rule that could block would let a
    threshold halt a clinic's morning on an untested hypothesis. Rejecting it at
    construction keeps it a configuration bug rather than a runtime surprise.
    """
    with pytest.raises(PIIPolicyError) as excinfo:
        PIICombinationRule(
            requires_groups=frozenset({"government"}),
            min_count=2,
            decision=PIIDecision.BLOCK,
        )

    assert "only 'review' is permitted" in str(excinfo.value)


def test_a_combination_threshold_below_two_is_rejected():
    """``min_count < 2`` is a per-category rule wearing a combination's syntax.

    It would silently duplicate or contradict ``PIIPolicy.rules`` while appearing
    to be a cross-category threshold, which is the kind of ambiguity that survives
    review because the field names look right.
    """
    with pytest.raises(PIIPolicyError) as excinfo:
        PIICombinationRule(
            requires_groups=frozenset({"government"}),
            min_count=1,
            decision=PIIDecision.REVIEW,
        )

    assert "at least 2 distinct categories" in str(excinfo.value)


def test_a_combination_with_no_groups_is_rejected():
    """An empty group set can never fire — a rule that cannot decide."""
    with pytest.raises(PIIPolicyError) as excinfo:
        PIICombinationRule(
            requires_groups=frozenset(),
            min_count=2,
            decision=PIIDecision.REVIEW,
        )

    assert "can never fire" in str(excinfo.value)


def test_a_combination_naming_an_unknown_group_is_rejected():
    """A misspelled group would otherwise raise a bare ``KeyError`` on first use.

    ``matches`` indexes ``PII_CATEGORY_GROUPS`` directly, so ``"goverment"``
    would fail on the first document reaching the rule, naming neither the group
    nor the policy version. Group names are strings precisely because a typo is
    possible; the policy validator is what pays for that choice.
    """
    with pytest.raises(PIIPolicyError) as excinfo:
        PIIPolicy(
            version="test",
            rules=dict(DEFAULT_POLICY.rules),
            combinations=(
                PIICombinationRule(
                    requires_groups=frozenset({"goverment"}),
                    min_count=2,
                    decision=PIIDecision.REVIEW,
                ),
            ),
        )

    assert "goverment" in str(excinfo.value)


def test_a_policy_with_no_combinations_is_unchanged():
    """``combinations=()`` is the rollback switch, and it is the default.

    Every policy constructed before this phase is still valid — the field
    defaults to empty — and reverting the rule is a one-line change to
    ``DEFAULT_POLICY`` with no other call site touched. Asserted on behaviour, not
    just on the default, so a stray non-empty default would fail.
    """
    result = DefaultPolicyEngine(_policy_without_combinations()).evaluate(
        [
            _finding(PIICategory.PERSON_NAME),
            _finding(PIICategory.SNILS),
            _finding(PIICategory.INSURANCE_NUMBER),
        ],
        _context(),
    )

    assert result.decision is PIIDecision.ALLOW


def _policy_without_combinations() -> PIIPolicy:
    return PIIPolicy(
        version="no-combinations",
        rules=dict(DEFAULT_POLICY.rules),
    )


# --- availability guard: no existing fixture changes --------------------------


def test_no_existing_category_reaches_the_threshold_alone():
    """The guard's cheap form: no single category satisfies ``min_count=2``.

    If this ever fails, the rule has started firing on documents the platform
    processes routinely, and every fixture decision downstream is in question.
    Asserted on the *reason* rather than the decision, because ``SECRET`` alone is
    ``BLOCK`` by design and would make a decision-shaped assertion say nothing
    about the combination.
    """
    engine = DefaultPolicyEngine()
    for category in PIICategory:
        result = engine.evaluate([_finding(category)], _context())
        assert not any(reason.startswith("combination:") for reason in result.reasons), category


def test_the_two_ordinary_patient_documents_stay_allow():
    """The two real-case categories that most resemble the rule, side by side.

    ``PERSON_NAME`` + a medical-record number is the patient fixture's shape and
    ``PERSON_NAME`` + ``SNILS`` is the marker's. Both must stay ``ALLOW``: §0's
    invariant is that a medical record is *expected* to carry patient identity,
    and a rule that halts those two shapes halts routine care.
    """
    assert (
        _evaluate(PIICategory.PERSON_NAME, PIICategory.MEDICAL_RECORD_NUMBER).decision
        is PIIDecision.ALLOW
    )
    assert _evaluate(PIICategory.PERSON_NAME, PIICategory.SNILS).decision is PIIDecision.ALLOW


def test_two_high_categories_that_are_not_government_still_allow():
    """The rejected "≥2 HIGH" rule, asserted as not-the-behaviour.

    Two ``HIGH`` categories that are not both government identifiers is the shape
    ORDER §13.1's first example would have halted, and it is the common shape of a
    real record (a medical record number plus a ticket number). It stays
    ``ALLOW``, which is the assertion recording that the risk-based rule was
    measured and rejected rather than overlooked — and it fails the day someone
    re-adds a threshold keyed on risk instead of on the identifier group.
    """
    result = _evaluate(
        PIICategory.MEDICAL_RECORD_NUMBER,
        PIICategory.TICKET_NUMBER,
    )

    assert CATEGORY_RISK[PIICategory.MEDICAL_RECORD_NUMBER] is PIIRiskLevel.HIGH
    assert CATEGORY_RISK[PIICategory.TICKET_NUMBER] is PIIRiskLevel.HIGH
    assert result.decision is PIIDecision.ALLOW


def test_identity_plus_a_government_identifier_still_allows():
    """The rejected "identity + government ID" rule, asserted as not-the-behaviour.

    §0's invariant and Phase 13's ``IDENTIFIER_MARKER`` both say a document
    carrying a name and one identifier is ordinary. This is the test that would
    have failed had Phase 17 shipped that example, and it is why the rule names
    the ``government`` group rather than a set including ``identity``.
    """
    result = _evaluate(
        PIICategory.PERSON_NAME,
        PIICategory.SNILS,
        PIICategory.DATE_OF_BIRTH,
    )

    assert result.decision is PIIDecision.ALLOW

