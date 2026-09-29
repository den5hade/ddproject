"""Post-extraction canonical-output guard contract (M4 Phase 6).

This is the only contract in M4 that stops the leak that was **actually
observed**. A document-only gate would not have caught it: the PII did not
appear in ``marker.md`` as a field the gate declined to read, it appeared in
``canonical.json`` because the extraction model copied it into free prose. Real
runs of ``2b8fdd0d`` and ``fbbcb675`` in ``.dev/flow_upload_test/``::

    2b8fdd0d.../canonical.json → fields.note: "...для пациента Шадеркина Дениса
                                Сергеевича. Номер талона: 2026030709303211960141."
    fbbcb675.../canonical.json → fields.note: "...для пациента Шадеркина Дениса
                                Сергеевича (М, 39 лет)..."

and that content then persisted into ``document_extractions.data`` because
``DocumentAnalysisCompleted.data`` is dumped verbatim
(``apps/account-api/app/services/documents.py:536``). A prompt rule asking the
model not to do this is a request, not a control — which is precisely why
``canonical.yaml:100`` failed.

Why the walk is free-form
------------------------

``BaseCanonical.fields`` is typed ``Any`` (``packages/canonical/canonical/
schemas/__init__.py:67-89``) and ``GenericCanonical`` — the current default model
— accepts ``dict[str, Any]``. There is no field list to guard, and a guard
written against one would be a guard that misses the next schema. So the walk
enumerates **every string leaf in the serialized payload** and hands each one to
the detector, with a path so a violation can be traced back to
``fields.note`` and fixed at the source.

Traversal and judgement are deliberately separate. This module decides *where to
look* — completely, deterministically, with no allow-list of keys — and the
detector decides *what counts as PII*. A structural string like
``"appointment"`` is inspected like any other and simply will not match; the
alternative, skipping known-structural keys here, would put a second,
undocumented judgement inside the traversal and would need re-auditing every
time a schema gains a field.

Numeric leaves are the known blind spot
---------------------------------------

The walk yields ``str`` leaves only, because that is what the plan specifies and
because the observed leak is prose. A СНИЛС or phone number serialized as a
bare JSON *number* is therefore not inspected. This is recorded rather than
silently patched: scanning numbers means scanning every measurement value, every
date component and every internal id in every laboratory payload, and the
false-positive surface is a calibration problem for M5's detectors, not something
to decide inside a traversal. The fix, if M5 finds numeric identifiers leaking,
is a detector concern over an extended leaf set — not a change to the walk's
contract.

Remediation
-----------

Three actions, named in the contract and implemented in M5:

``WARN``
    Record and continue. The document persists as-is.
``SANITIZE``
    Replace the offending string with its mask and continue, so the value never
    reaches storage.
``RETRY_THEN_FAIL``
    Do not persist. Re-run extraction once with a stricter instruction, and fail
    the document if it still leaks. The retry exists because the defect is
    upstream in the prompt: failing immediately punishes the document for a
    problem one re-run may fix, and persisting punishes the patient.

:data:`DECISION_REMEDIATION` maps the Phase 5 decision vocabulary onto these, and
M5 Phase 14 confirmed that mapping — with one correction, recorded in its
docstring: ``REVIEW`` halts rather than sanitizes.

The M5 implementation
---------------------

:class:`DefaultCanonicalPIIInspector` runs the locked order **detect → aggregate
→ policy → decide** over a serialized payload, per leaf:

```text
walk_string_leaves(payload)
    │
    ▼  per leaf
detect_text(leaf)  →  aggregate(…)          ← per leaf, never across leaves (§7)
    │
    ▼
CanonicalPIIViolation(field_path, category, masked_value, confidence)
    │
    ▼  one evaluation over every leaf's findings
policy.evaluate(findings, ctx[stage=CANONICAL, destination=PERSISTENCE])
    │
    ▼
CanonicalPIIGuardResult  →  sanitize_canonical_payload(…)
```

Two shapes in that diagram are worth stating outright, because both are forced
and neither is obvious:

*Why violations cannot drive sanitization.* A
:class:`CanonicalPIIViolation` has no ``value`` and no offsets — M4 built it that
way, because the violation list is the audit projection and a copy of the leak
would be a second leak. But locating a span needs the value. So
:data:`CanonicalPIIGuardResult.findings_by_path` carries the in-process
:class:`~app.pii.models.PIIFinding` objects (which do have both) as an
``exclude=True`` field, and the sanitizer consumes that. Same string, same
process, no value crossing a boundary — which is exactly the argument §4.12
makes about ``PIIDecisionResult.actions``.

*Why the sanitizer mutates a copy instead of parsing paths.* Detection and
sanitization must agree on what a path *means*, and the cheapest way to guarantee
that is to traverse the payload the same way twice rather than to teach a second
piece of code how to parse ``fields.medications[0].doctor``. So
:func:`sanitize_canonical_payload` re-walks the copied payload and replaces a
leaf by looking its path up in a dict — no path parser, no per-schema setter
(§7 decision 7). :func:`walk_string_leaves` is deliberately *not* reused for the
write half: it is a generator that must not touch the caller's payload
(``test_walk_does_not_mutate_the_payload``), and the write half mutates a copy
it owns. The two traversals are asserted to agree on the same payload by
``test_the_sanitizer_and_the_walk_agree_on_paths``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator, Mapping, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.pii.aggregation import DefaultPIIAggregator, PIIAggregator
from app.pii.detectors import PIIDetector, build_detector_chain
from app.pii.exceptions import PIIDecisionError
from app.pii.gate import REDACTION_AVAILABLE
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
from app.pii.policy import (
    DEFAULT_POLICY,
    DefaultPolicyEngine,
    PIIPolicyContext,
    PolicyEngine,
    build_policy_context,
)
from app.pii.redaction import PIIRedactor, PlaceholderRedactor

if TYPE_CHECKING:
    from app.config.settings import Settings

__all__ = [
    "CANONICAL_POLICY_DESTINATION",
    "CANONICAL_POLICY_STAGE",
    "CanonicalPIIGuardResult",
    "CanonicalPIIInspector",
    "CanonicalPIIInspectorBase",
    "CanonicalPIIViolation",
    "DECISION_REMEDIATION",
    "DefaultCanonicalPIIInspector",
    "PIIRemediation",
    "build_canonical_guard",
    "sanitize_canonical_payload",
    "walk_string_leaves",
]

CANONICAL_POLICY_STAGE = PIIScanStage.CANONICAL
"""Stage the Phase 5 engine must evaluate this guard's findings under."""

CANONICAL_POLICY_DESTINATION = PIIDestination.PERSISTENCE
"""Destination for the same evaluation.

Named as constants because they are the two inputs that make the guard's
findings *evaluate differently* from the document-stage findings on the same
values: a name in a canonical payload heading for PostgreSQL is a persistence
problem, not a source-document problem, and evaluating it as
``stage=DOCUMENT`` would look up the wrong policy rows.
"""


class PIIRemediation(str, Enum):
    """What to do about a canonical payload that contains PII.

    Declared here rather than in :mod:`app.pii.models` on purpose: the models
    module's enum set was closed in Phase 1 and is asserted by the Phase 2 schema
    parity tests, and remediation is a guard concern rather than an attribute of
    a finding.
    """

    WARN = "warn"
    SANITIZE = "sanitize"
    RETRY_THEN_FAIL = "retry_then_fail"


class CanonicalPIIViolation(BaseModel):
    """One PII value found in a canonical payload, at a traceable path.

    The second leak boundary, so it obeys the Phase 1 rule structurally: there
    is no ``value`` field and ``extra="forbid"`` keeps one from being added. What
    survives into the violation is the *mask*, which is enough to answer "what
    leaked and where" without the artifact becoming a second copy of the leak.

    ``PIISource.CANONICAL`` is implied by the type rather than stored: M5 stamps
    it when converting violations into :class:`~app.pii.models.PIIFinding`s, and
    a redundant field on a model that can only ever come from this one place
    would be a field that can disagree with its own type.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_path: str
    """Dotted path to the offending string, e.g. ``fields.note``.

    Shape matches the observed leak exactly, so a violation can be traced to the
    line in the artifact that produced it. Built by
    :func:`walk_string_leaves`: dict keys join with ``.``, list indices append
    ``[i]``.
    """

    category: PIICategory
    """What the detector believes the value is."""

    masked_value: str
    """The mask, never the value. See the class docstring."""

    confidence: float
    """Detector confidence, 0–1. Carried so M5 can threshold; the document-stage
    ``PIIFinding.confidence`` deliberately has no validator, and this mirrors
    that rather than tightening one side of the boundary."""


def walk_string_leaves(payload: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Yield ``(field_path, value)`` for every string leaf in ``payload``.

    The free-form walk rule, and the one part of this module that is
    implemented rather than specified: traversal is fully determined, so
    specifying it in prose would only invite an M5 reimplementation that walks
    something slightly different.

    Args:
        payload: A serialized canonical payload, as produced by
            ``BaseCanonical.model_dump()``. Not mutated.

    Yields:
        ``(field_path, value)`` pairs. Paths are dotted for dict keys
        (``fields.note``) and indexed for lists (``fields.medications[0].doctor``),
        which is the format the observed leak already uses.

    Notes:
        Only ``str`` leaves are yielded; see the module docstring for why
        numeric leaves are a known blind spot rather than an oversight. Containers
        are tracked along the current recursion path so a self-referential
        structure terminates instead of hanging the pipeline, while a payload
        that merely shares a sub-object between two keys still visits both.
    """
    yield from _walk(payload, "")


def _walk(node: Any, path: str, active: frozenset[int] = frozenset()) -> Iterator[tuple[str, str]]:
    """Recurse over containers, yielding string leaves with their paths."""
    if isinstance(node, str):
        if path:
            yield path, node
        return
    if not isinstance(node, dict | list):
        return

    identity = id(node)
    if identity in active:
        return  # cycle: this container is already on the path
    nested = active | {identity}

    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            yield from _walk(value, child, nested)
    else:
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]", nested)


class CanonicalPIIInspector(Protocol):
    """Protocol for inspecting a serialized canonical payload for PII."""

    def inspect(self, payload: dict[str, Any]) -> list[CanonicalPIIViolation]:
        """Return every PII violation found in ``payload``.

        The result is the *only* thing this component hands onward, and it
        carries masks rather than values, so a caller cannot accidentally persist
        what it found. An empty list means the payload is clean and may be
        persisted; a non-empty list is a decision input, not an error.

        Does not raise for a payload containing PII — that is a finding. Raises
        :class:`~app.pii.exceptions.PIIDecisionError` only if no decision can be
        produced at all, matching the document-stage gate.
        """
        ...


class CanonicalPIIInspectorBase(CanonicalPIIInspector):
    """Base marker for guard implementations; raises until M5.

    Consistent with ``PIIDetectorBase``, ``PolicyEngineBase`` and
    ``PIIGateBase``: the stub raises from the method so M5 can assemble the whole
    chain and prove each link fails loudly. A guard that returned an empty list
    would be indistinguishable from a clean payload, which is the one answer this
    component must never give by accident.
    """

    def inspect(self, payload: dict[str, Any]) -> list[CanonicalPIIViolation]:
        """Not implemented until M5; always raises."""
        raise NotImplementedError(
            "The canonical guard is wired after build_canonical in M5; the walk rule is "
            "walk_string_leaves() in this module."
        )


DECISION_REMEDIATION: dict[str, PIIRemediation] = {
    "allow": PIIRemediation.WARN,
    "allow_with_warning": PIIRemediation.SANITIZE,
    "review": PIIRemediation.RETRY_THEN_FAIL,
    "block": PIIRemediation.RETRY_THEN_FAIL,
}
"""Decision → remediation, confirmed by M5 Phase 14 (was M4's proposal).

Keyed by :class:`~app.pii.models.PIIDecision` values, matching
``gate.DECISION_OUTCOMES``, and asserted against the enum's values so a new
decision cannot arrive without a remediation.

The reasoning, since the mapping is a judgement call:

- ``ALLOW`` maps to ``WARN`` rather than to "nothing", because reaching the
  guard's remediation step at all means violations were found, and a decision of
  ``ALLOW`` on a payload that *did* leak is the phase that introduced the
  escalation — it should leave a trace rather than pass silently.
- ``ALLOW_WITH_WARNING`` sanitizes. This is the main path now: the persistence
  escalation (§4.11) turns a name in ``fields.note`` into ``REDACT``, the
  redactor resolves it to ``ALLOW_WITH_WARNING``, and this maps to the one
  action that makes the leak impossible.
- **Both halting decisions retry-then-fail, and M4's proposal was wrong about
  ``REVIEW``.** M4 mapped ``review`` to ``SANITIZE`` on the argument that writing
  the patient's name to storage *on the way to* a review queue is worse than not
  writing it. The argument is sound and the answer it reached is not: ``REVIEW``
  means *this document needs a human*, and a human who never receives the
  document cannot review it. Halting before persistence is what
  ``gate.HALTING_DECISIONS`` already does for the source contour, and a second
  contour with a weaker rule would make the weaker rule the one that applies to
  the leak.

What the retry is, and is not, in this phase: ``RETRY_THEN_FAIL`` names the
correct outcome, and **no retry is implemented**. Re-running extraction needs a
second LLM call, a prompt override and a budget, none of which exist, and
faking it with a re-walk of the same payload would produce a second identical
artifact. So ``RETRY_THEN_FAIL`` currently means "halt, and a future phase can
decide whether one re-run is worth it" — ``DECISION_OUTCOMES`` still describes
it as a halt, and the pipeline's halt branch is what runs.
"""


class CanonicalPIIGuardResult(BaseModel):
    """One guard pass: what was found, what was decided, what to do about it.

    The third leak boundary this package defines, and the only one that is not a
    *summary* — it deliberately carries the in-process :class:`PIIFinding`
    objects, because the sanitizer needs a value to locate and a value may not
    leave the process. So the fields that may hold one are ``exclude=True``,
    which is a **serialization** property and not a secrecy one: the exclusion
    is structural (``model_dump()`` cannot emit them), asserted by
    ``test_guard_result_dumps_without_any_raw_value``, and the object stays
    in-process by contract.

    Two fields, two audiences:

    * :attr:`violations` — the audit view. Paths, categories and masks, which is
      what a human triaging a leak needs and all a log may carry.
    * :attr:`findings_by_path` — the remediation view. Grouped by the path
      :func:`walk_string_leaves` produced, because that is the key the sanitizer
      walks with, and carrying the grouping here is what makes a second mapping
      in the pipeline unnecessary.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    violations: list[CanonicalPIIViolation] = Field(default_factory=list)
    """Safe projection of every finding, in walk order."""

    decision: PIIDecision
    """The document-level verdict. The pipeline's only branch."""

    risk_level: PIIRiskLevel
    """Maximum category risk over the findings, straight from the policy engine."""

    reasons: list[str] = Field(default_factory=list)
    """Why the decision went the way it did, in category names only."""

    actions: dict[PIICategory, PIIAction] = Field(default_factory=dict, exclude=True)
    """Per-category action, post-override and post-escalation (§4.12).

    In-process for the same reason ``PIIDecisionResult`` keeps it: it says what
    to mask, and a mask table is not a diagnostic worth persisting.
    """

    findings_by_path: dict[str, list[PIIFinding]] = Field(default_factory=dict, exclude=True)
    """``field_path`` → the leaf's aggregated findings, values included."""


CanonicalPolicyContextBuilder = Callable[[], "PIIPolicyContext"]
"""How the guard obtains the policy inputs the canonical contour has no context for.

The source contour borrows :data:`app.pii.gate.PolicyContextBuilder`, which takes
``(NormalizedDocument, ProcessingContext)``; the guard has neither, because a
canonical payload is not a source document and the pipeline is not a
``NormalizedDocument``. What is left is a *constant* — one stage, one destination,
one redaction flag, one tenant — so a zero-argument builder over settings is both
the only honest shape and the most auditable: there is no call site that could
pass a different stage to the guard than the constants name.
"""


class DefaultCanonicalPIIInspector(CanonicalPIIInspectorBase):
    """``detect → aggregate → policy → decide`` over a serialized payload — M5 Phase 14.

    The second contour, and the one that closes the observed leak. Every design
    choice below exists because the payload is free-form (``BaseCanonical.fields``
    is ``Any``) and therefore *unfamiliar* to the detector: there is no schema to
    lean on, so the guard has to decide where to look, and the only defensible
    answer is "everywhere" — hence :func:`walk_string_leaves` rather than a field
    list (IMPL_ARCH §14.1).

    Collaborators are injected rather than constructed, exactly as in
    :class:`~app.pii.gate.DefaultPIIGate`, for the same reason: ``app/pii`` must
    stay importable with no configuration present, and the policy inputs must
    arrive through one auditable line instead of through a call site.

    The order is the locked one, and the two places it could go wrong are both
    handled:

    * **Aggregate per leaf, never across leaves.** A name at ``fields.note`` and
      the same name at ``fields.doctor`` are two findings, because collapsing
      them lets a remediation fix one path while the second keeps leaking
      (§7 decision 6). The cost is a duplicated row in the artifact, which
      ``category_counts`` makes visible and which under-counting a leak is not
      worth.
    * **Evaluate once, over every leaf's findings.** Per-leaf aggregation does
      *not* mean per-leaf policy: a decision is a document-level property, and
      :class:`~app.pii.gate.PIIIGate` returns one verdict per document. Splitting
      the evaluation would produce per-leaf verdicts with no defined precedence.

    Fail-closed, twice over: a context builder that returns nothing raises, and a
    context that is not ``(CANONICAL, PERSISTENCE)`` raises too. The second check
    is the sharper one — a miswired builder would otherwise evaluate the same
    values under the *source* table, where a patient name is ``ALLOW``, and the
    guard would report a clean payload for a leaking one. That is the exact
    failure this contour exists to prevent, reached by a plausible mistake.
    """

    def __init__(
        self,
        *,
        detector: PIIDetector,
        aggregator: PIIAggregator,
        policy_engine: PolicyEngine,
        policy_context_builder: CanonicalPolicyContextBuilder,
        redactor: PIIRedactor,
    ) -> None:
        """Wire the collaborators.

        Args:
            detector: The composite chain. ``build_detector_chain(settings)``
                produces the configured one, and it is the *same* chain the source
                contour uses — one set of detectors, two contours, so a rule fixed
                on one contour is fixed on both.
            aggregator: Deduplicator, applied per leaf.
            policy_engine: Decision step; carries the persistence escalation.
            policy_context_builder: Produces the :class:`PIIPolicyContext`.
                Required, with no default: a guard that could scan without one
                would have to invent a stage, and the invented stage would be
                ``DOCUMENT`` — which is a silent allow.
            redactor: Performs the string surgery. Injected rather than imported
                so a test can assert on a sanitizer that fails, and so the
                ``REDACT`` action has a real mechanism behind it (which is what
                stops the policy escalating to ``REVIEW``).
        """
        self.detector = detector
        self.aggregator = aggregator
        self.policy_engine = policy_engine
        self.policy_context_builder = policy_context_builder
        self.redactor = redactor

    def inspect(self, payload: dict[str, Any]) -> list[CanonicalPIIViolation]:
        """Return every violation in ``payload`` — the locked protocol method.

        A projection of :meth:`evaluate_payload`, kept because the protocol is
        M4's locked contract and a caller that only wants "is this payload
        clean" should not have to know about decisions. A non-empty list is not
        an error; it is the answer.
        """
        return self.evaluate_payload(payload).violations

    def evaluate_payload(self, payload: dict[str, Any]) -> CanonicalPIIGuardResult:
        """Inspect ``payload`` and return the guard result.

        Args:
            payload: A serialized canonical payload, as produced by
                ``BaseCanonical.model_dump(mode="json", by_alias=True)``. Not
                mutated — sanitization is a separate call on a copy, so that a
                caller who wants the findings without the rewrite has it.

        Returns:
            A :class:`CanonicalPIIGuardResult`. A payload with nothing to find
            yields ``ALLOW`` at ``LOW`` with empty violations — the same "an empty
            scan is a clean scan" rule the source contour follows, and for the
            same reason: a guard that escalated silence would halt every
            document the platform processes.

        Raises:
            PIIDecisionError: If the context builder returns ``None``, or
                returns a context that is not
                ``(CANONICAL, PERSISTENCE)``, or the policy engine cannot decide.
                Never a default verdict — a guard that answers "clean" when it is
                confused is worse than no guard, because it is indistinguishable
                from a guard that worked.
        """
        policy_context = self._policy_context()
        findings_by_path = self._scan(payload)
        if not findings_by_path:
            return CanonicalPIIGuardResult(
                violations=[],
                decision=PIIDecision.ALLOW,
                risk_level=PIIRiskLevel.LOW,
                reasons=["no pii detected in canonical payload"],
            )

        decision: PIIDecisionResult = self.policy_engine.evaluate(
            [finding for found in findings_by_path.values() for finding in found],
            policy_context,
        )
        return CanonicalPIIGuardResult(
            violations=[
                violation
                for path, found in findings_by_path.items()
                for violation in _violations_for(path, found)
            ],
            decision=decision.decision,
            risk_level=decision.risk_level,
            reasons=list(decision.reasons),
            actions=dict(decision.actions),
            findings_by_path=findings_by_path,
        )

    def sanitize(self, payload: dict[str, Any], result: CanonicalPIIGuardResult) -> dict[str, Any]:
        """Return a copy of ``payload`` with every ``REDACT`` leaf replaced.

        The two-call shape (``evaluate_payload`` then ``sanitize``) is what lets
        the pipeline branch on the decision *before* rewriting anything: a
        halting result is never passed here, so a blocked document is not
        sanitized on its way to being discarded.
        """
        return sanitize_canonical_payload(
            payload,
            findings_by_path=result.findings_by_path,
            actions=result.actions,
            redactor=self.redactor,
        )

    def _policy_context(self) -> PIIPolicyContext:
        """Build and verify the context, failing closed on anything surprising."""
        context = self.policy_context_builder()
        if context is None:
            raise PIIDecisionError(
                f"{type(self).__name__} got no PIIPolicyContext from its builder; refusing to "
                f"assume {CANONICAL_POLICY_STAGE.value}/{CANONICAL_POLICY_DESTINATION.value}, "
                "because a guessed stage looks up the wrong policy rows and ALLOWs a name."
            )
        if (
            context.stage is not CANONICAL_POLICY_STAGE
            or context.destination is not CANONICAL_POLICY_DESTINATION
        ):
            raise PIIDecisionError(
                f"{type(self).__name__} must evaluate under "
                f"{CANONICAL_POLICY_STAGE.value}/{CANONICAL_POLICY_DESTINATION.value}; its "
                f"builder returned {context.stage.value}/{context.destination.value}. The "
                "persistence escalation does not apply there, so the same values would resolve "
                "to ALLOW and the guard would report a leaking payload as clean."
            )
        return context

    def _scan(self, payload: dict[str, Any]) -> dict[str, list[PIIFinding]]:
        """Detect and aggregate every string leaf, keyed by the leaf's path."""
        findings_by_path: dict[str, list[PIIFinding]] = {}
        for path, leaf in walk_string_leaves(payload):
            found = self.aggregator.aggregate(self.detector.detect_text(leaf))
            if found:
                findings_by_path[path] = found
        return findings_by_path


def _violations_for(path: str, findings: Sequence[PIIFinding]) -> Iterator[CanonicalPIIViolation]:
    """Project one leaf's findings onto the safe violation shape.

    ``PIISource.CANONICAL`` is implied by the type and not stored (M4): a
    violation can only come from this contour, so a field recording it could only
    ever disagree with its own type. ``masked_value`` comes from the finding,
    which already built it — the violation does not get a second masking rule.
    """
    for finding in findings:
        yield CanonicalPIIViolation(
            field_path=path,
            category=finding.category,
            masked_value=finding.masked_value,
            confidence=finding.confidence,
        )


def sanitize_canonical_payload(
    payload: dict[str, Any],
    *,
    findings_by_path: Mapping[str, Sequence[PIIFinding]],
    actions: Mapping[PIICategory, PIIAction],
    redactor: PIIRedactor,
) -> dict[str, Any]:
    """Return a sanitized **copy** of ``payload``; mask iff the action says ``REDACT``.

    The per-category rule is the whole of §4.12 and the reason this is a
    separate step from the document decision: a run that redacted one name must
    not blank every finding in it. ``actions[category] is REDACT`` is consulted
    per violation, so ``DOCTOR_NAME`` and ``ORGANIZATION_NAME`` survive a
    ``PERSON_NAME`` redaction and ``render_document`` keeps working — which is
    also why a category that is merely ``ALLOW``-but-recorded stays legible to
    the human reading the artifact.

    The plan's signature for this function took ``violations`` as an argument; it
    does not, because a violation cannot locate a span (no value, no offsets) and
    passing it alongside ``findings_by_path`` would be two sources of truth for
    one question. The violations stay on :class:`CanonicalPIIGuardResult` for the
    audit view.

    The replacement is :func:`~app.pii.redaction.placeholder_for` — ``[PERSON_NAME]`` —
    not :func:`~app.pii.masking.mask_pii_value`. The mask table's partial
    disclosure is documented "for human debugging", and ``canonical.json`` is
    heading for PostgreSQL, not for a debugger: ``Ш***** Д***** С*********`` still
    publishes the first letter of every name token. The partial mask is still
    available where it belongs, on the finding the log line reports.

    Args:
        payload: The serialized payload. **Not mutated** — the copy is what
            comes back, which is why the pipeline re-validates into a new model
            rather than assigning into the old one.
        findings_by_path: Path → the leaf's findings, from
            :meth:`DefaultCanonicalPIIInspector.evaluate_payload`.
        actions: Per-category action from the same result.
        redactor: Performs the replacement. :class:`PlaceholderRedactor` verifies
            a finding's offsets before trusting them, which matters here even
            though the guard scanned the exact string it is rewriting: a leaf
            that was redacted twice in one payload would otherwise be rewritten
            from stale offsets.

    Returns:
        A new payload. Equal to the input when nothing is ``REDACT``-actioned —
        an empty copy, not the same object, so a caller cannot tell whether it
        was rewritten and the pipeline does not have to check.

    Raises:
        PIIRedactionError: From the redactor, if a finding resolves to no span.
            Propagated rather than caught: a value left in place while the
            artifact claims it was removed is the failure this guard exists to
            prevent, and the pipeline turns the raise into a fail-closed halt.
    """
    sanitized = copy.deepcopy(payload)
    replacements: dict[str, str] = {}
    for path, leaf in walk_string_leaves(payload):
        redacted = [
            finding
            for finding in findings_by_path.get(path, ())
            if actions.get(finding.category) is PIIAction.REDACT
        ]
        if redacted:
            replacements[path] = redactor.redact(leaf, redacted)
    if replacements:
        _replace_leaves(sanitized, "", frozenset(), replacements)
    return sanitized


def _replace_leaves(
    node: Any,
    path: str,
    active: frozenset[int],
    replacements: Mapping[str, str],
) -> Any:
    """Rebuild ``node`` with every string leaf named in ``replacements`` swapped.

    The write twin of :func:`_walk`, and deliberately a separate function: the
    walk is a generator that must not touch the caller's payload, while this
    mutates the deep copy :func:`sanitize_canonical_payload` owns. The two
    traversals are the same rule and are asserted to agree, path for path, by
    ``test_the_sanitizer_and_the_walk_agree_on_paths`` — which is why neither
    parses a path string. Detection and remediation cannot disagree about what
    ``fields.medications[0].doctor`` means, because neither of them ever
    interprets it.
    """
    if isinstance(node, str):
        return replacements.get(path, node)
    if not isinstance(node, dict | list):
        return node

    identity = id(node)
    if identity in active:
        return node  # cycle: this container is already on the path
    nested = active | {identity}

    if isinstance(node, dict):
        for key, value in list(node.items()):
            child = f"{path}.{key}" if path else str(key)
            node[key] = _replace_leaves(value, child, nested, replacements)
    else:
        for index, value in enumerate(node):
            node[index] = _replace_leaves(value, f"{path}[{index}]", nested, replacements)
    return node


def build_canonical_guard(settings: Settings) -> DefaultCanonicalPIIInspector:
    """Construct the contour-2 guard — the pipeline's second call, M5 Phase 14.

    The mirror of :func:`~app.pii.gate.build_document_gate`, and deliberately
    symmetrical: the same detector chain, the same aggregator, the same policy
    engine over the same table, and the same redaction flag. One difference, and
    it is the point of the phase — the two are built with the *same* chain on
    purpose, so a rule fixed on either contour is fixed on both, and a guard that
    silently ran a subset would be the contour-1 defect (risk R13) all over again
    in the place the leak actually is.

    Fail-closed properties, all inherited: a missing ``pii_fingerprint_secret``
    raises out of the chain constructor, and a misconfigured tenant raises out of
    :func:`~app.pii.policy.build_policy_context`.

    Args:
        settings: Application settings. The chain constructor reads
            ``pii_fingerprint_secret``; :func:`build_policy_context` reads
            ``s3_tenant_id`` (§7 decision 4).

    Returns:
        A wired :class:`DefaultCanonicalPIIInspector`.

    Raises:
        InvalidPIIInputError: If the fingerprint secret is missing or blank.
        PIIPolicyError: If ``settings.s3_tenant_id`` is blank.
    """

    def build_context() -> PIIPolicyContext:
        """Close over settings to supply the stage/destination pair.

        ``document_type`` stays ``None`` rather than the canonical ``type``: the
        baseline policy ignores the field, and inventing a per-type rule would
        need the classification verdict threaded in — the same "do not smuggle a
        policy input past validation" argument :data:`PolicyContextBuilder`
        documents.
        """
        return build_policy_context(
            settings,
            stage=CANONICAL_POLICY_STAGE,
            destination=CANONICAL_POLICY_DESTINATION,
            redaction_available=REDACTION_AVAILABLE,
        )

    return DefaultCanonicalPIIInspector(
        detector=build_detector_chain(settings),
        aggregator=DefaultPIIAggregator(),
        policy_engine=DefaultPolicyEngine(DEFAULT_POLICY),
        policy_context_builder=build_context,
        redactor=PlaceholderRedactor(),
    )
