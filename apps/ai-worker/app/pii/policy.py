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
* ``PERSISTENCE`` uses the base table, **except** under ``stage=CANONICAL``, where
  it escalates the same 18 categories to ``REDACT`` — see
  :data:`REDACT_ON_PERSIST` and the section below.

Why persistence is the exception to "presence never blocks"
----------------------------------------------------------

The base table is right for the *source* contour and wrong for *persistence*. At
the source the question is "is this document sensitive", and a medical record is
expected to name a patient — so ``ALLOW`` is correct and blocking would halt
every document the platform exists to process. At ``stage=CANONICAL`` the
question is different: the extraction model has *already* chosen what the
artifact needs to carry, and the observed leak (ORDER §13.1) is precisely that it
chose to carry the patient's full name and ticket number in free prose inside
``fields.note``. The M4 table would ``ALLOW`` both, and the document would
persist them.

So ``stage=CANONICAL`` + ``destination=PERSISTENCE`` escalates the four
patient-identifying groups to ``REDACT`` (:data:`REDACT_ON_PERSIST`). Three things
deliberately do **not** escalate:

* ``practitioner`` — a doctor and a clinic are not the patient (IMPL_ARCH §3.1),
  and :func:`~app.pii.detectors` writes ``Врач: …`` into the payload;
* ``AGE``/``GENDER``/``NATIONALITY`` — clinical facts that make the note legible
  (ORDER §13.7). Masking them destroys the artifact to protect nothing;
* ``secret`` — a credential is not made safer by redacting it, and ``REDACT``
  would replace a *security event* with a tidy string.

This is policy data, not a branch in the guard: one row set and one version
bump, reversible without touching a single line of detection code
(IMPL_ARCH §17). It is why the escalation costs a ``policy_version`` and not a
code change.

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

Where the context comes from
----------------------------
:meth:`PIIGate.inspect` receives a ``ProcessingContext`` and a
``NormalizedDocument``, and neither carries ``destination``,
``redaction_available`` or ``organization_id`` — the three inputs that select
an override. They are supplied by :func:`build_policy_context`, which reads
them from configuration at the edge of the package, so the gate's locked
signature stays exactly as ORDER §8 fixed it and the source of every policy
input is one auditable line. ``Settings`` is imported type-only for the same
reason the gate's other cross-package types are: ``app/pii`` must remain
importable with no configuration present.

``destination`` defaults to :data:`DEFAULT_DESTINATION` — ``INTERNAL_LLM``.
The worker does not read that default: it resolves the destination from
``Settings.llm_mode`` through :func:`resolve_destination`, so switching to
an untrusted provider is a configuration change rather than a code change.

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

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.pii.exceptions import InvalidPIIInputError, PIIPolicyError
from app.pii.models import (
    PIIAction,
    PIICategory,
    PIIDecision,
    PIIDecisionResult,
    PIIDestination,
    PIIFinding,
    PIIRiskLevel,
    PIIScanStage,
)

if TYPE_CHECKING:
    from app.config.settings import Settings

__all__ = [
    "CATEGORY_RISK",
    "CLINICAL_FACTS",
    "DEFAULT_DESTINATION",
    "DEFAULT_POLICY",
    "DEFAULT_POLICY_VERSION",
    "PII_CATEGORY_GROUPS",
    "PII_POLICY_VERSION",
    "REDACT_ON_EXTERNAL",
    "REDACT_ON_PERSIST",
    "RISK_ORDER",
    "TRUSTED_INTERNAL_URLS",
    "DefaultPolicyEngine",
    "PolicyEngine",
    "PolicyEngineBase",
    "PIICombinationRule",
    "PIIPolicy",
    "PIIPolicyContext",
    "PIIRule",
    "build_policy_context",
    "resolve_destination",
]

DEFAULT_POLICY_VERSION = "3.0.0"
"""Version of the locked baseline table, stamped onto every scan result.

``3.0.0`` is the combination threshold (M5 Phase 17). It is **major** because it
changes a decision: a document carrying two distinct government identifiers
(:data:`PII_CATEGORY_GROUPS`) resolves to ``REVIEW`` where the same document
resolved to ``ALLOW`` before, so an input that produced ``ALLOW`` now produces
``REVIEW``. §4.8 of the plan makes that the test — minor is additive *and*
backward-compatible, major is "any change that alters a decision for any input" —
and this rule fails the backward-compatible half of minor by the plan's own
definition. The roadmap's ``2.1.0`` was corrected with it.

The two prior majors are ``2.0.0``, the persistence escalation (Phase 14), and
``1.0.0``, the initial table. The reasoning is the same in every case, and it is
the reason the constant exists at all: a stored ``policy_version`` has to be
able to say which of those worlds produced it.

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

CLINICAL_FACTS: frozenset[PIICategory] = frozenset(
    {PIICategory.AGE, PIICategory.GENDER, PIICategory.NATIONALITY}
)
"""Demographics that are the *content* of a medical document, not identifiers.

Distinct from their absence in the risk table — these are real, low-risk PII
categories that a detector deliberately finds (a bare ``39`` is an age as often
as a lab value, which is exactly why §34 warns about false positives). What
separates them is what *removing* them costs: mask the age in
``"(М, 39 лет)"`` and the note stops saying how old the patient is, which is the
clinical fact the document exists to carry (ORDER §13.7).

So they are found, recorded, and kept. §7 decision 13 states the intended
behaviour as one sentence, and the tension in it is worth quoting rather than
paraphrasing: the age "must survive sanitization", and masking the ``GENDER``/
``AGE`` *tokens* is "the intended behaviour". Those hold together only if the
token is a finding and the fact is the sentence — and the resolution this phase
takes is the conservative one, because a test can only assert what survives.
``(М, 39 лет)`` survives whole.
"""

REDACT_ON_PERSIST: frozenset[PIICategory] = REDACT_ON_EXTERNAL - CLINICAL_FACTS
"""The 15 categories redacted for a **canonical payload heading to storage** (§4.11).

Identity + contact + government + medical-id (:data:`REDACT_ON_EXTERNAL`) **minus**
:data:`CLINICAL_FACTS`. It is derived from the external set rather than restated
as a fourth literal, because the two overrides answer the same question — "may
this identifier leave the process?" — and a copied literal would be a second
place to forget a category, with the failure mode being a category redacted in
one destination and not the other.

The subtraction is the whole difference, and it is a decision, not an oversight:

* ``AGE``/``GENDER``/``NATIONALITY`` stay legible, because masking them destroys
  the note (ORDER §13.7) and Phase 14's accept criterion is literally
  ``(М, 39 лет)`` surviving;
* ``practitioner`` is absent from both sets — a doctor and a clinic are not the
  patient (IMPL_ARCH §3.1), and ``Врач: …`` is in the payload on purpose;
* ``SECRET`` is absent and stays ``BLOCK``, because a credential is not made
  safer by being replaced with a tidy ``[SECRET]``.

What differs from the external override is the surrounding condition, and that
is the point: ``REDACT_ON_EXTERNAL`` fires on ``destination=EXTERNAL_LLM`` at any
stage, while this one fires on ``destination=PERSISTENCE`` **and**
``stage=CANONICAL``. The source contour still ``ALLOW``s, because presence at the
source must never block.
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


RISK_ORDER: tuple[PIIRiskLevel, ...] = (
    PIIRiskLevel.LOW,
    PIIRiskLevel.MEDIUM,
    PIIRiskLevel.HIGH,
    PIIRiskLevel.CRITICAL,
)
"""The risk ladder in *declared* order — the only order ``risk_level`` means.

This module exists because the ladder is not the order the enum's values sort
in. ``PIIRiskLevel`` is a ``str`` enum, so ``max(low, high)`` compares ``"low"``
with ``"high"`` as strings and returns ``"low"`` — alphabetically
``critical < high < low < medium``. Without this rank map a document carrying a
passport and a date of birth is reported at ``LOW``, which is the kind of bug
that only ever appears as an artifact nobody reads.

Declared here rather than as a method on the enum because the ladder is a
*policy* statement (this module's subject); ``models.py`` only names the values.
"""

_RISK_RANK: dict[PIIRiskLevel, int] = {level: rank for rank, level in enumerate(RISK_ORDER)}


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


class PIICombinationRule(BaseModel):
    """What to do when several categories appear *together* (M5 Phase 17).

    Every other rule in this module is per category, so the table has no way to
    say that one finding is fine and two together are not. That gap is ORDER
    §13.1's "unknown limitation", and this is its narrow resolution: a document
    carrying two distinct government identifiers is ``REVIEW`` even though each
    one on its own is ``ALLOW``.

    The two thresholds ORDER §13.1 offers as examples — "≥2 distinct HIGH
    categories" and "identity + government ID" — were measured against the whole
    fixture dataset and **both rejected**: a Russian medical record carrying
    СНИЛС + ОМС + № карты is three HIGH categories and would halt routine care,
    while ФИО + СНИЛС is the single most normal pair in the domain and is
    deliberately allowed today by ``IDENTIFIER_MARKER``. The narrower rule fires
    on the §45.19 accept case exactly and is silent on all six existing fixtures.
    Plan §4.13 records the measurement.

    The escalation is applied to the **document decision** and never to
    :attr:`~app.pii.models.PIIDecisionResult.actions`: §4.12 makes ``actions``
    the remediation channel, and the canonical sanitizer masks a leaf iff that
    action is ``REDACT``. Writing ``REVIEW`` into the participating categories
    would stop the sanitizer masking those leaves in any future where ``REVIEW``
    does not halt, and would make the per-category table lie about what it
    decided. This is decision 14 holding structurally — ``REVIEW`` adds no
    ``REDACT``, so a review still cannot rewrite the document it asks about.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    requires_groups: frozenset[str]
    """Names from :data:`PII_CATEGORY_GROUPS`. A category satisfies the rule if
    it belongs to any one of them."""

    min_count: int
    """How many **distinct** categories, counted across the union of
    :attr:`requires_groups`, fire the rule. Distinct, not total findings: a
    document repeating one identifier is not a combination."""

    decision: PIIDecision
    """Escalation target. Constrained to ``REVIEW`` — see
    :meth:`_require_review_only`."""

    @model_validator(mode="after")
    def _require_review_only(self) -> PIICombinationRule:
        """Reject a rule that could ``BLOCK``.

        A combination that blocks would make itself the second ``BLOCK`` source
        and contradict the invariant in :func:`_default_rules`: ``SECRET`` is the
        only thing that blocks, because a credential in a document is a
        vulnerability rather than a fact about the document's subject. The
        alternative — letting a combination block — is exactly the kind of change
        that halts a clinic's morning on an untested hypothesis, and it is
        rejected at construction rather than at decision time.
        """
        if self.decision is not PIIDecision.REVIEW:
            raise PIIPolicyError(
                f"Combination rule {sorted(self.requires_groups)}/x{self.min_count} escalates to "
                f"{self.decision.value}; only '{PIIDecision.REVIEW.value}' is permitted. "
                "BLOCK is reserved for SECRET (see _default_rules)."
            )
        return self

    @model_validator(mode="after")
    def _require_a_reachable_threshold(self) -> PIICombinationRule:
        """Reject a rule that can never mean anything.

        ``min_count < 2`` is not a stricter rule, it is a rule that fires on a
        single finding — that is a per-category rule wearing a combination's
        syntax, and it would silently duplicate (or contradict) ``rules``. An
        empty group set can never fire at all. Both are configuration bugs, and
        the plan's convention is that a policy which cannot decide is a
        construction-time error, not a runtime surprise.
        """
        if self.min_count < 2:
            raise PIIPolicyError(
                f"Combination rule {sorted(self.requires_groups)} has "
                f"min_count={self.min_count}; a combination needs at least 2 distinct "
                "categories. A threshold below 2 is a per-category rule and belongs in "
                "PIIPolicy.rules."
            )
        if not self.requires_groups:
            raise PIIPolicyError(
                "Combination rule has an empty requires_groups; it can never fire."
            )
        return self

    def matches(self, present: frozenset[PIICategory]) -> bool:
        """Whether ``present`` — the document's distinct categories — trips this rule.

        Counting is over categories, not findings, so a document that repeats one
        identifier does not reach ``min_count`` on repetition alone.
        """
        members: set[PIICategory] = set()
        for group in self.requires_groups:
            members |= PII_CATEGORY_GROUPS[group]
        return len(present & members) >= self.min_count

    def reason(self) -> str:
        """The line recorded in :attr:`~app.pii.models.PIIDecisionResult.reasons`.

        ``reasons`` is the only account of a review a human will ever see, and
        this rule fires on documents that are otherwise unremarkable — a bare
        ``ALLOW`` that is now a ``REVIEW`` is a halt someone has to explain, so
        the reason names the groups and the threshold rather than saying
        "combination".
        """
        groups = ", ".join(sorted(self.requires_groups))
        return f"combination: >={self.min_count} distinct categories from [{groups}] -> review"


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

    combinations: tuple[PIICombinationRule, ...] = ()
    """Cross-category thresholds (Phase 17). Empty by default, which makes this
    field additive: every policy built before it is still a valid policy.

    Owned here rather than declared as a module constant because
    :data:`PII_POLICY_VERSION` is ``DEFAULT_POLICY.version`` and the entire
    reason that constant exists is that a stored scan result must be
    re-derivable from the version it names. A threshold table the version does
    not name is a table a stored verdict cannot be reproduced from."""

    @model_validator(mode="after")
    def _require_known_groups(self) -> PIIPolicy:
        """Reject a combination rule naming a group that does not exist.

        ``PIICombinationRule.matches`` indexes :data:`PII_CATEGORY_GROUPS`
        directly, so a typo like ``"goverment"`` would not fail here — it would
        raise a bare ``KeyError`` on the first document that reached the rule,
        naming neither the group nor the policy version. A group name is a string
        precisely because a misspelling is possible; this is what pays for that
        choice.
        """
        for rule in self.combinations:
            unknown = rule.requires_groups - set(PII_CATEGORY_GROUPS)
            if unknown:
                raise PIIPolicyError(
                    f"Policy v{self.version} combination rule names unknown "
                    f"{PII_CATEGORY_GROUPS} group(s) {sorted(unknown)}; "
                    f"known groups are {sorted(PII_CATEGORY_GROUPS)}"
                )
        return self

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


def _default_combinations() -> tuple[PIICombinationRule, ...]:
    """Build the §4.13 baseline: one narrow rule, and only one.

    Two distinct *government* identifiers in one document is a combination worth
    a human: it is the shape of a document assembled to carry someone else's
    identifiers, and each identifier alone is exactly what a medical record is
    expected to contain. The rule is deliberately narrower than ORDER §13.1's two
    worked examples, because both of those were measured against the fixture
    dataset and either would halt routine care (see :class:`PIICombinationRule`).

    Written as a tuple of one so the *shape* is visible. The tempting alternative
    is to add a row per pair (``SNILS`` + ``INSURANCE_NUMBER``,
    ``SNILS`` + ``PASSPORT``, …), which is a table of ten near-identical rules
    that has to be edited every time a category is added and would have to be
    re-validated for consistency the model cannot check. Naming the group and the
    count says the same thing in one row that cannot drift from
    :data:`PII_CATEGORY_GROUPS`.
    """
    return (
        PIICombinationRule(
            requires_groups=frozenset({"government"}),
            min_count=2,
            decision=PIIDecision.REVIEW,
        ),
    )


DEFAULT_POLICY = PIIPolicy(
    version=DEFAULT_POLICY_VERSION,
    rules=_default_rules(),
    combinations=_default_combinations(),
)
"""The locked baseline of §4.4 plus the §4.13 combination table."""

PII_POLICY_VERSION: str = DEFAULT_POLICY.version
"""Stamped onto :class:`~app.pii.models.PIIScanResult.policy_version` (Phase 1).

Declared after :data:`DEFAULT_POLICY` so it cannot drift from the table it names.
"""


DEFAULT_DESTINATION = PIIDestination.INTERNAL_LLM
"""The destination used when no context says otherwise.

Not a deployment decision: :func:`build_policy_context` takes ``destination``
from :func:`resolve_destination` as of Phase 15, so the worker resolves it from
``Settings.llm_mode`` and this constant only serves contexts constructed
directly in tests. The current provider is trusted and named in §0
(``ai_base_url``), so pre-extraction redaction stays dormant: nothing must leave
the trusted boundary unmasked while that is true.
"""


TRUSTED_INTERNAL_URLS: frozenset[str] = frozenset({"https://foundation-models.api.cloud.ru/v1"})
"""The providers ``llm_mode="internal_llm"`` is allowed to name (§0).

Explicit and by name, not "anything that looks internal": a check that accepts
any private-looking host is a check that passes for an exfiltration URL pointed
at a cloud metadata service, which is the opposite of what it is for. Add a
provider here deliberately, with the same weight as adding a row to the policy
table.
"""


def resolve_destination(settings: Settings) -> PIIDestination:
    """Map :attr:`Settings.llm_mode` onto a :class:`PIIDestination`.

    The single sanctioned way to learn where the document is going. Called from
    ``build_document_gate`` so the refusal below happens at worker start-up
    (Phase 15 decision 3), which is the only point at which a misconfiguration
    can be reported before a document is in flight.

    Args:
        settings: The worker settings. ``llm_mode`` selects the boundary;
            ``ai_base_url`` is only read to check the ``internal_llm`` claim.

    Returns:
        ``EXTERNAL_LLM`` for ``llm_mode="external_llm"``, ``INTERNAL_LLM``
        otherwise.

    Raises:
        InvalidPIIInputError: If ``llm_mode`` is ``internal_llm`` and
            ``ai_base_url`` is not in :data:`TRUSTED_INTERNAL_URLS`. The pair
            means "I am only sending documents I would send to myself" while
            the configuration sends them somewhere else, and the pipeline
            believes the operator: PII is neither redacted nor blocked. A
            comment claiming the provider is trusted (plan §0) is an
            intention, not a control, and this is the control.

    Note:
        A single trailing ``/`` is ignored on both sides. Without it a correct
        configuration fails for a cosmetic reason, which is how operators learn
        to distrust the check; with it, a trailing slash still cannot turn an
        untrusted host into a trusted one, because the comparison is otherwise
        exact.
    """
    if settings.llm_mode == "external_llm":
        return PIIDestination.EXTERNAL_LLM

    base_url = _normalise_url(settings.ai_base_url)
    trusted = {_normalise_url(url) for url in TRUSTED_INTERNAL_URLS}
    if base_url not in trusted:
        raise InvalidPIIInputError(
            f"llm_mode={settings.llm_mode!r} declares the provider trusted, but "
            f"ai_base_url={settings.ai_base_url!r} is not in TRUSTED_INTERNAL_URLS "
            f"({', '.join(sorted(TRUSTED_INTERNAL_URLS))}). The worker refuses to start: "
            f"this pairing sends documents unredacted to a boundary the configuration "
            f"does not name, and nothing downstream would notice. Either point "
            f"ai_base_url at a trusted provider, or set llm_mode=external_llm so the "
            f"gate redacts what leaves."
        )
    return PIIDestination.INTERNAL_LLM


def _normalise_url(url: str) -> str:
    """Return ``url`` without one trailing slash; nothing else is normalised."""
    return url.rstrip("/") if url.rstrip("/") else url


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
    locked contract.

    Validated as a non-empty, stripped identifier, because the two degenerate
    values are both silent: an empty string satisfies ``str`` and would scope
    every future per-tenant rule to a tenant named "", and whitespace is an id
    nobody can match. Sourced from ``settings.s3_tenant_id`` by
    :func:`build_policy_context`; see §7 decision 4 for why that placeholder is
    the honest answer today."""

    redaction_available: bool = False
    """Whether a working redactor exists. Defaults to ``False``, the fail-closed
    direction and the state of the world today: a ``REDACT`` action with nothing
    to redact with escalates to ``REVIEW``."""

    @field_validator("organization_id")
    @classmethod
    def _require_organization(cls, value: str) -> str:
        """Reject a blank organization and normalize surrounding whitespace.

        Raises:
            PIIPolicyError: If ``value`` is empty or whitespace-only. Raised
                rather than left to a ``min_length`` constraint so the failure is
                a domain error a caller can handle, and so the message can name
                the setting the value came from.
        """
        organization = value.strip()
        if not organization:
            raise PIIPolicyError(
                "PIIPolicyContext.organization_id must be a non-empty identifier "
                "(sourced from settings.s3_tenant_id); a blank tenant would scope "
                "every per-tenant rule to a tenant named ''."
            )
        return organization


def build_policy_context(
    settings: Settings,
    *,
    stage: PIIScanStage,
    destination: PIIDestination = DEFAULT_DESTINATION,
    document_type: str | None = None,
    redaction_available: bool = False,
) -> PIIPolicyContext:
    """Build the policy context from configuration — the only sanctioned constructor.

    Exists because :class:`PIIPolicyContext` requires an ``organization_id``
    that nothing upstream carries: neither ``ProcessingContext`` nor any event
    contract has a tenant, and threading one through ``packages/contracts`` is a
    schema-versioned change that is explicitly out of M5 (ORDER §13.6, §7
    decision 4). ``settings.s3_tenant_id`` is the honest placeholder — it has a
    non-empty default, so the field is real and auditable today, and it is not
    claimed to be authoritative.

    Keeping the wiring here rather than in the pipeline means the *source* of
    every policy input is one auditable line in one place, and Phase 15's
    settings-backed ``destination`` changes one argument default instead of a
    call site.

    Args:
        settings: Application settings. Only ``s3_tenant_id`` is read.
        stage: Which contour is asking — ``DOCUMENT`` for the source scan,
            ``CANONICAL`` for the canonical-output guard.
        destination: Where the document is going. Defaults to
            :data:`DEFAULT_DESTINATION` (``INTERNAL_LLM``) and becomes a
            settings read in Phase 15.
        document_type: Optional classification hint, passed through as-is.
        redaction_available: Whether a working redactor exists. Defaults to
            ``False`` — the fail-closed direction — and Phase 12 flips it to
            ``True`` once ``PIIRedactor.redact`` is implemented.

    Returns:
        A frozen, validated :class:`PIIPolicyContext`.

    Raises:
        PIIPolicyError: If ``settings.s3_tenant_id`` is blank.
    """
    return PIIPolicyContext(
        destination=destination,
        stage=stage,
        document_type=document_type,
        organization_id=settings.s3_tenant_id,
        redaction_available=redaction_available,
    )


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


class DefaultPolicyEngine(PolicyEngineBase):
    """The §4.4 algorithm, implemented — M5 Phase 9.

    Stateless and side-effect free: it reads the policy table and the context and
    returns a value. Every other component in the package is either stateful
    (detectors hold the fingerprint secret) or I/O-bound (the gate is ``async``),
    and keeping the decision step pure is what lets the *precedence* rules be
    tested one at a time instead of through a whole document.
    """

    def __init__(self, policy: PIIPolicy = DEFAULT_POLICY) -> None:
        """Bind to a complete policy table, defaulting to the locked baseline.

        Args:
            policy: The table to evaluate against. Any
                :class:`PIIPolicy` is acceptable — completeness is already
                guaranteed by that model's validator, so this cannot receive a
                table that would force a ``PIIPolicyError`` at decision time.
                Injectable so a per-tenant or per-stage table can be tested
                without touching the baseline.
        """
        self.policy = policy

    def evaluate(self, findings: list[PIIFinding], context: PIIPolicyContext) -> PIIDecisionResult:
        """Resolve an action per category, then reduce to one decision.

        Implements the module docstring's algorithm in order, because the order
        is the specification: actions first (so ``ALLOW_WITH_WARNING`` can be
        derived from what *would* have been withheld), risk second (as the
        maximum category risk, independent of escalation — escalation is a
        decision about *handling*, not a statement of how sensitive the data is),
        and the verdict last.

        Args:
            findings: Already aggregated. An empty list is a valid input and
                yields ``ALLOW`` at ``LOW`` — an empty scan is a clean scan, and
                a gate that escalated silence would halt every empty document in
                the platform.
            context: The policy inputs. ``destination`` selects the override;
                ``redaction_available`` decides what happens when an override
                demands ``REDACT``.

        Returns:
            A :class:`~app.pii.models.PIIDecisionResult` whose ``actions`` map
            is post-override and post-escalation, so a caller acting on
            ``REDACT`` sees the same values the decision was derived from.

        Raises:
            PIIPolicyError: If a finding carries a category the bound policy has
            no rule for. Unreachable through a constructed
            :class:`PIIPolicy`; present because a hand-mutated ``rules`` dict
            would otherwise raise a bare ``KeyError`` from deep inside the
            loop, naming neither the category nor the policy version.
        """
        if not findings:
            return PIIDecisionResult(
                decision=PIIDecision.ALLOW,
                risk_level=PIIRiskLevel.LOW,
                actions={},
                reasons=["no pii detected"],
            )

        actions: dict[PIICategory, PIIAction] = {}
        reasons: list[str] = []
        warnings: list[str] = []
        risk_level = PIIRiskLevel.LOW
        present: set[PIICategory] = set()

        for finding in findings:
            category = finding.category
            if category not in self.policy.rules:
                raise PIIPolicyError(
                    f"Policy v{self.policy.version} has no rule for {category.value}; "
                    "the table was mutated after construction."
                )
            risk_level = max(risk_level, self.policy.risk_for(category), key=_RISK_RANK.__getitem__)
            action = self._action_for(finding, context, reasons, warnings)
            actions[category] = action
            present.add(category)

        escalation = self._combination(present, reasons)

        return PIIDecisionResult(
            decision=self._decide(actions, escalation),
            risk_level=risk_level,
            actions=actions,
            reasons=reasons,
            warnings=warnings,
        )

    def _combination(self, present: set[PIICategory], reasons: list[str]) -> PIIDecision | None:
        """Return the cross-category escalation for this document, if any.

        Deliberately returns a decision rather than mutating ``actions``: §4.12
        makes ``actions`` the remediation channel, and the sanitizer masks a leaf
        iff its action is ``REDACT``, so a combination that wrote ``REVIEW`` into
        the participating categories would stop those leaves being masked in any
        future where ``REVIEW`` does not halt, and would make the per-category
        table misreport what it decided.

        First match wins, in declared order — the table is short and ordered, and
        a rule that could fire alongside another is a rule set whose interaction
        nobody has reasoned about. A ``BLOCK`` is never returned: the combination
        decision is constrained to ``REVIEW`` at construction, so ``BLOCK``
        precedence stays where §4.4 put it.
        """
        for rule in self.policy.combinations:
            if rule.matches(frozenset(present)):
                reasons.append(rule.reason())
                return rule.decision
        return None

    def _action_for(
        self,
        finding: PIIFinding,
        context: PIIPolicyContext,
        reasons: list[str],
        warnings: list[str],
    ) -> PIIAction:
        """Resolve one finding's action: base rule, then override, then escalation.

        ``stage`` participates only in the persistence override, and that is
        deliberate asymmetry: ``destination`` alone cannot express the leak, since
        a canonical payload and a source document can be headed for the same
        place and must not resolve to the same action. Both overrides are
        mutually exclusive on ``destination``, so their order relative to each
        other is not load-bearing — a category that matched both would be the one
        case this table cannot describe, and there is no such destination.

        Records why the action changed in ``reasons``, because the artifact is
        the only account of a review a human will ever see: a ``REVIEW`` that
        does not say "external destination, redaction unavailable" is a review
        nobody can triage.
        """
        category = finding.category
        action = self.policy.action_for(category)

        if context.destination is PIIDestination.UNKNOWN:
            if action is not PIIAction.BLOCK:
                action = PIIAction.REVIEW
            reasons.append(f"{category.value}: destination unknown, forced review")
            return action

        if (
            context.destination is PIIDestination.EXTERNAL_LLM
            and category in REDACT_ON_EXTERNAL
            and action is not PIIAction.BLOCK
        ):
            action = PIIAction.REDACT
            reasons.append(f"{category.value}: external destination, redact before sending")

        if (
            context.destination is PIIDestination.PERSISTENCE
            and context.stage is PIIScanStage.CANONICAL
            and category in REDACT_ON_PERSIST
            and action is not PIIAction.BLOCK
        ):
            action = PIIAction.REDACT
            reasons.append(
                f"{category.value}: canonical payload heading to persistence, redact before storing"
            )

        if action is PIIAction.REDACT and not context.redaction_available:
            action = PIIAction.REVIEW
            reasons.append(
                f"{category.value}: redaction required but no redactor is available, "
                "escalated to review"
            )
        elif action is PIIAction.REDACT:
            warnings.append(f"{category.value}: value must be redacted before leaving the boundary")

        return action

    def _decide(
        self,
        actions: dict[PIICategory, PIIAction],
        escalation: PIIDecision | None = None,
    ) -> PIIDecision:
        """Reduce per-category actions to one decision by strict precedence.

        ``ALLOW_WITH_WARNING`` is the residue of an applied ``WARN`` or
        ``REDACT`` (module docstring): it is what distinguishes "nothing to do"
        from "something was withheld", which is the fact the persisted artifact
        exists to record. Actions are resolved per category, so a category that
        was redacted anywhere in a document keeps that action for the whole
        document regardless of what a later sighting of the same category
        resolved to.

        ``escalation`` is the Phase 17 combination verdict, which joins the
        precedence at ``REVIEW`` — not at the top. A document carrying a secret
        and two government identifiers is a ``BLOCK``: the credential is a
        vulnerability and outranks everything, and a combination rule must never
        become the reason a ``BLOCK`` degrades into a review.
        """
        applied = set(actions.values())
        if PIIAction.BLOCK in applied:
            return PIIDecision.BLOCK
        if PIIAction.REVIEW in applied or escalation is PIIDecision.REVIEW:
            return PIIDecision.REVIEW
        if applied & {PIIAction.WARN, PIIAction.REDACT}:
            return PIIDecision.ALLOW_WITH_WARNING
        return PIIDecision.ALLOW
