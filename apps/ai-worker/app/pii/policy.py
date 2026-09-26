"""PII policy configuration and the decision contract (M4 Phase 5).

This module separates *what* was found from *what to do about it*. Detection and
policy are distinct contracts on purpose (``STRUCTURE.md`` §5, ``PII GATE/IMPL_ARCH.md``
§2/§17): a detector can be replaced without touching a rule, and a rule can be
tightened without touching a detector. The gate pipeline is therefore
``detect → aggregate → policy → decide``, and this module owns the third step and
the precedence that turns it into a verdict.

The locked decision algorithm
-----------------------------

Given the findings and a :class:`PIIPolicyContext`, an engine must:

1. **Resolve an action per category** from the policy's :class:`PIIRule`, then
   apply the destination override (below).
2. **Compute ``risk_level`` as the maximum** category risk across the findings
   (``low < medium < high < critical``). No findings means ``LOW`` — an empty
   scan is not a risky scan, and defaulting upward would make every empty
   document look suspicious.
3. **Reduce the actions to one decision by precedence**::

       BLOCK > REVIEW > ALLOW_WITH_WARNING > ALLOW

   The *highest-precedence* action wins, so one secret in a thousand findings
   blocks the document. ``ALLOW_WITH_WARNING`` is not an action but a *residue*:
   it is produced when at least one ``WARN`` or ``REDACT`` action applied and
   nothing stronger did. Otherwise a redacted document would be reported as a
   plain ``ALLOW``, and the record of what was removed would be lost — which is
   the one thing the artifact exists to preserve.

Destination overrides
---------------------

* ``INTERNAL_LLM`` (the default, and the only destination wired today) uses the
  base table unchanged.
* ``EXTERNAL_LLM`` escalates every identity, contact, government and
  medical-id category to ``REDACT`` — see :data:`REDACT_ON_EXTERNAL`. The
  practitioner and secret groups are deliberately excluded: a clinic's name is
  not patient PII (IMPL_ARCH §3), and a secret is not made safer by redacting it.
* ``UNKNOWN`` forces ``REVIEW`` for every category. Failing closed is the whole
  point of the enum: a destination nobody can reason about is not a destination
  that may receive a document.
* ``PERSISTENCE`` uses the base table; the Phase 6 guard evaluates with
  ``stage=CANONICAL`` and this destination.

The redact-unavailable escalation
---------------------------------

An override can demand ``REDACT`` while ``context.redaction_available`` is
``False`` — which is the state of the world today, since no redactor is
implemented (plan §0). That combination is a contradiction, and the resolution
is to escalate the category to ``REVIEW``, never to downgrade it to ``ALLOW``:
a document that *must* be redacted and cannot be is a document a human has to
look at. Silently allowing it would be the worst outcome available, because the
caller would send unredacted PII to an external provider while the artifact
claimed the document was merely reviewed.

Why no working engine
---------------------

:class:`PolicyEngineBase` raises; the algorithm above is prose plus a
documentation test. Same deferral as Phase 3's aggregator and for the same
reason: M4 is a contract milestone (§5, "no detection-logic tests"), and the one
rule with no locked threshold — how many identifiers make a document
*suspicious* — cannot be written down without real findings to calibrate it
against. See the Phase 5 implementation status for the gap that exposes.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from app.pii.exceptions import PIIPolicyError
from app.pii.models import (
    PIIAction,
    PIICategory,
    PIIDecisionResult,
    PIIDestination,
    PIIFinding,
    PIIRiskLevel,
    PIIScanStage,
)

__all__ = [
    "CATEGORY_RISK",
    "DEFAULT_POLICY",
    "DEFAULT_POLICY_VERSION",
    "PII_CATEGORY_GROUPS",
    "PII_POLICY_VERSION",
    "REDACT_ON_EXTERNAL",
    "PolicyEngine",
    "PolicyEngineBase",
    "PIIPolicy",
    "PIIPolicyContext",
    "PIIRule",
]

DEFAULT_POLICY_VERSION = "1.0.0"
"""Version of the locked baseline table, stamped onto every scan result.

Single source of truth: :data:`PII_POLICY_VERSION` reads from
``DEFAULT_POLICY.version`` rather than repeating the literal, because two
constants that must agree will eventually disagree.
"""

PII_CATEGORY_GROUPS: dict[str, frozenset[PIICategory]] = {
    "identity": frozenset(
        {
            PIICategory.PERSON_NAME,
            PIICategory.DATE_OF_BIRTH,
            PIICategory.AGE,
            PIICategory.GENDER,
            PIICategory.NATIONALITY,
        }
    ),
    "contact": frozenset(
        {
            PIICategory.EMAIL,
            PIICategory.PHONE,
            PIICategory.ADDRESS,
        }
    ),
    "government": frozenset(
        {
            PIICategory.PASSPORT,
            PIICategory.NATIONAL_ID,
            PIICategory.INSURANCE_NUMBER,
            PIICategory.SNILS,
            PIICategory.INN,
        }
    ),
    "medical_id": frozenset(
        {
            PIICategory.PATIENT_ID,
            PIICategory.MEDICAL_RECORD_NUMBER,
            PIICategory.LAB_ORDER_ID,
            PIICategory.ENCOUNTER_ID,
            PIICategory.TICKET_NUMBER,
        }
    ),
    "practitioner": frozenset(
        {
            PIICategory.DOCTOR_NAME,
            PIICategory.DOCTOR_LICENSE,
            PIICategory.ORGANIZATION_NAME,
            PIICategory.ORGANIZATION_ID,
        }
    ),
    "secret": frozenset({PIICategory.SECRET}),
}
"""The six taxonomy groups of §4.1, as data.

Declared here rather than left implicit in the risk table because the
destination override needs *group* membership, not risk level: "everything a
patient is identified by" spans four groups and three risk levels, and a rule
that tried to express the override through risk would sweep in the practitioner
group at ``medium``.
"""

REDACT_ON_EXTERNAL: frozenset[PIICategory] = frozenset(
    PII_CATEGORY_GROUPS["identity"]
    | PII_CATEGORY_GROUPS["contact"]
    | PII_CATEGORY_GROUPS["government"]
    | PII_CATEGORY_GROUPS["medical_id"]
)
"""The 18 categories redacted for ``EXTERNAL_LLM`` (§4.4).

Identity + contact + government + medical-id. ``practitioner`` is excluded
because a doctor and a clinic are not the patient (IMPL_ARCH §3), and ``secret`` is
excluded because redaction is the wrong tool for a leaked credential — it stays
``BLOCK``.
"""

CATEGORY_RISK: dict[PIICategory, PIIRiskLevel] = {
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
"""Plan §4.4, transcribed value-for-value. All 23 categories, no more.

Asserted category-by-category by ``test_default_policy_table_matches_the_locked_plan``
rather than compared against a copy of itself, so editing this dict to weaken a
risk level fails the suite.
"""


class PIIRule(BaseModel):
    """What to do about one category, and how bad it is.

    Deliberately does not carry the category: the category is the key in
    :attr:`PIIPolicy.rules`, and repeating it inside the value would give the
    table two sources of truth for the same fact.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: PIIAction
    """Base action for the category, before any destination override."""

    risk_level: PIIRiskLevel
    """Inherent sensitivity of the category; independent of destination."""


class PIIPolicy(BaseModel):
    """A versioned, complete category→rule table.

    Completeness is enforced rather than assumed. A policy that omits a category
    has no action for it, and the two plausible fallbacks — skip the finding, or
    default it to ``ALLOW`` — both leak. So :meth:`model_post_init` rejects a
    partial table outright, which turns "someone forgot a category" from a
    production incident into a construction-time ``PIIPolicyError``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    rules: dict[PIICategory, PIIRule]
    """Every category, exactly once — see the completeness check below."""

    @model_validator(mode="after")
    def _require_full_coverage(self) -> PIIPolicy:
        """Reject a table that does not cover every category.

        Raises:
            PIIPolicyError: If any category is missing or any unknown key is
                present. Raised at construction because a policy that cannot
                decide is a configuration bug, not a runtime condition.
        """
        missing = set(PIICategory) - set(self.rules)
        unknown = set(self.rules) - set(PIICategory)
        if missing or unknown:
            raise PIIPolicyError(
                f"Policy v{self.version} must cover every PIICategory; "
                f"missing={[c.value for c in sorted(missing, key=str)]}, "
                f"unknown={[c.value for c in sorted(unknown, key=str)]}"
            )
        return self

    def action_for(self, category: PIICategory) -> PIIAction:
        """Base action for ``category``, before destination overrides."""
        return self.rules[category].action

    def risk_for(self, category: PIICategory) -> PIIRiskLevel:
        """Inherent risk of ``category``."""
        return self.rules[category].risk_level


def _default_rules() -> dict[PIICategory, PIIRule]:
    """Build the §4.4 baseline: every category allows except ``SECRET``, which blocks.

    PII presence alone never blocks. A medical record is *expected* to carry a
    patient's name, date of birth and medical record number, so treating those as
    a violation would halt every document the platform exists to process. Only
    ``SECRET`` blocks, because a credential in a document is not a fact about
    the document's subject — it is a vulnerability (IMPL_ARCH §13).
    """
    return {
        category: PIIRule(
            action=PIIAction.BLOCK if category is PIICategory.SECRET else PIIAction.ALLOW,
            risk_level=risk,
        )
        for category, risk in CATEGORY_RISK.items()
    }


DEFAULT_POLICY = PIIPolicy(version=DEFAULT_POLICY_VERSION, rules=_default_rules())
"""The locked baseline of §4.4, for ``destination=INTERNAL_LLM``."""

PII_POLICY_VERSION: str = DEFAULT_POLICY.version
"""Stamped onto :class:`~app.pii.models.PIIScanResult.policy_version` (Phase 1).

Declared after :data:`DEFAULT_POLICY` so it cannot drift from the table it names.
"""


class PIIPolicyContext(BaseModel):
    """The inputs policy needs that are not on the findings themselves.

    Frozen and ``extra="forbid"``: policy inputs are recorded in the audit
    trail, so a context that could be mutated between evaluation and recording
    could produce a result nobody can reproduce.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    destination: PIIDestination
    """Where the document is going. Selects the override; see the module docstring."""

    stage: PIIScanStage
    """``DOCUMENT`` for the source scan, ``CANONICAL`` for the Phase 6 guard."""

    document_type: str | None = None
    """Optional classification hint. Unused by the baseline policy; carried so a
    type-specific policy can be added without changing this model's shape."""

    organization_id: str
    """Owning organization. Carried for the same reason — a per-tenant policy is
    a foreseeable M5/M6 extension, and adding the field later would change a
    locked contract."""

    redaction_available: bool = False
    """Whether a working redactor exists. Defaults to ``False``, the fail-closed
    direction and the state of the world today: a ``REDACT`` action with nothing
    to redact with escalates to ``REVIEW``."""


class PolicyEngine(Protocol):
    """Protocol for turning findings plus context into a decision."""

    def evaluate(self, findings: list[PIIFinding], context: PIIPolicyContext) -> PIIDecisionResult:
        """Evaluate ``findings`` under ``context`` and return the decision.

        Returns a :class:`~app.pii.models.PIIDecisionResult`, not a bare
        :class:`~app.pii.models.PIIDecision`: the caller needs the per-category
        action map to know *what* to redact, and re-deriving it from the decision
        would duplicate the precedence logic in a second place.

        Raises:
            PIIPolicyError: If the policy cannot decide — a category with no
                rule, which the completeness check makes unreachable for a
                constructed :class:`PIIPolicy`, so in practice this signals a
                corrupted or hand-built rules dict.
        """
        ...


class PolicyEngineBase(PolicyEngine):
    """Base marker for policy engine implementations; raises until M5.

    Mirrors ``PIIDetectorBase`` (Phase 3) rather than the classification
    services, which raise from ``__init__``. The difference matters here: the M5
    gate must be able to construct its entire collaborator chain in one place
    and prove that an unimplemented component fails loudly at the moment it is
    called. A policy engine that silently returned ``ALLOW`` would be the single
    worst failure in this package — it would report every document as clean.
    """

    def evaluate(self, findings: list[PIIFinding], context: PIIPolicyContext) -> PIIDecisionResult:
        """Not implemented until M5; always raises."""
        raise NotImplementedError(
            "PII policy evaluation arrives with the M5 gate wiring; the locked algorithm is "
            "in this module's docstring."
        )
