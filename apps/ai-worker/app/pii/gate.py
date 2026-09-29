"""PII gate: blocks or redacts documents containing detected PII (M4 Phase 5).

The gate is a **document-level capability**, not a schema-level one. Its
signature is ORDER §8's, verbatim, and the shape of that signature is the whole
architectural claim::

    async def inspect(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> PIIScanResult

not ``AppointmentPIIGate``. One gate serves every document type, which is what
keeps PII from becoming a per-schema tax and what lets a new document type be
covered the day it is added instead of the day someone remembers.

The order inside ``inspect`` is fixed: **detect → aggregate → policy → decide**.
Detection first because policy has nothing to reason about without findings;
aggregation before policy because the dedup key is
``(category, value_fingerprint)`` and a policy that counted pre-dedup findings
would inflate its own risk assessment with one value seen twice.

The decision → outcome mapping
------------------------------

============================  ==========================================
``PIIDecision``               Outcome
============================  ==========================================
``ALLOW``                     continue
``ALLOW_WITH_WARNING``        continue, and record that redaction happened
``REVIEW``                    halt, ``needs_review`` (no human UI yet)
``BLOCK``                     halt, processing failure
============================  ==========================================

Both halting decisions stop the pipeline, and they stop it for different
reasons. ``REVIEW`` means *this document needs a human*; ``BLOCK`` means *this
document is a security event*. Collapsing them would either page an operator for
every medical record or let a leaked credential through as routine review.

``ALLOW_WITH_WARNING`` is deliberately not a halt. A redacted document is
already safe to process, and halting it would make redaction pointless — the
whole point of redacting is to continue with the document intact minus its
identifiers. What must survive is the *record* that redaction occurred, which is
why it is a decision rather than a log line: it is stamped into
``PIIScanResult`` and from there into the audit record.

Fail closed
-----------

If the gate cannot produce a decision at all — a detector crashed, a policy is
inconsistent, the collector returns something unrecognizable — it raises
:class:`~app.pii.exceptions.PIIDecisionError` and the pipeline must not proceed
to extraction. An exception, not a default decision, because the tempting
default here is ``ALLOW``, and a gate that answers "clean" whenever it is
confused is worse than no gate at all. M4 locks the exception; M5 wires the halt.

A gap the signature leaves for M5
--------------------------------

``inspect`` receives a ``ProcessingContext``, which carries ``document_id``,
``document_version_id``, ``patient_id``, ``client_type``, ``processing_id`` and
``attributes`` — but **not** ``destination`` or ``redaction_available``, the two
inputs that select a policy override. M5 must supply them from gate
configuration; they are not smuggled in through ``attributes``, because a policy
input that arrives in a free-form dict cannot be validated or defaulted. The
signature is left exactly as ORDER §8 fixed it rather than widened to accept
them, and the construction-time wiring is M5's problem to solve.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.pii.aggregation import DefaultPIIAggregator, PIIAggregator
from app.pii.detectors import (
    DETECTOR_VERSION,
    PIIDetector,
    build_detector_chain,
)
from app.pii.exceptions import PIIDecisionError
from app.pii.models import (
    PIIAction,
    PIICategory,
    PIIDecision,
    PIIDecisionResult,
    PIIFinding,
    PIIFindingSummary,
    PIIScanResult,
    PIIScanStage,
)
from app.pii.policy import (
    DEFAULT_POLICY,
    PII_POLICY_VERSION,
    DefaultPolicyEngine,
    PIIPolicyContext,
    PolicyEngine,
    build_policy_context,
    resolve_destination,
)
from app.pii.redaction import PIIRedactor, PlaceholderRedactor

if TYPE_CHECKING:
    from app.classification.normalize import NormalizedDocument
    from app.config.settings import Settings
    from app.pipeline.context import ProcessingContext


__all__ = [
    "DECISION_OUTCOMES",
    "HALTING_DECISIONS",
    "DocumentPIIGateResult",
    "PolicyContextBuilder",
    "DefaultPIIGate",
    "PIIGate",
    "PIIGateBase",
    "build_document_gate",
]


class PIIGate(Protocol):
    """Protocol for any service that inspects a document for PII."""

    async def inspect(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> PIIScanResult:
        """Inspect ``document`` within ``context`` and return the scan result.

        Never raises for a document that merely *contains* PII — that is what
        the decision field is for. Raises
        :class:`~app.pii.exceptions.PIIDecisionError` only when no decision can
        be produced at all.
        """
        ...


class PIIGateBase(PIIGate):
    """Base marker for PII gate implementations; raises until M5.

    Raises from ``inspect`` rather than ``__init__``, consistent with
    ``PIIDetectorBase`` and ``PolicyEngineBase`` (Phases 3 and 5), so the M5
    pipeline can construct its whole chain and prove that an unimplemented gate
    fails loudly. A gate that returned an empty ``ALLOW`` result would be the
    most dangerous stub in the repository: the pipeline would look healthy and
    every document would pass.
    """

    async def inspect(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> PIIScanResult:
        """Not implemented until M5; always raises."""
        raise NotImplementedError(
            "The PII gate is wired into the pipeline in M5; the decision→outcome mapping and "
            "the detect→aggregate→policy→decide order are in this module's docstring."
        )


PolicyContextBuilder = Callable[
    ["NormalizedDocument", "ProcessingContext"],
    "PIIPolicyContext",
]
"""How the gate obtains the three inputs ``ProcessingContext`` cannot carry.

``destination``, ``redaction_available`` and ``organization_id`` decide the
outcome and none of them is on the locked ``inspect`` signature, so the gate is
*constructed* with a way to build one instead of being handed a policy input at
call time. That is the shape this module's docstring asks for ("M5 must supply
them from gate configuration; they are not smuggled in through ``attributes``"),
and it is the opposite of the alternative: a caller that stashed a context in a
free-form dict would have smuggled a security-relevant input past the validation
that makes it auditable.

The production implementation is a closure over settings::

    def builder(document: NormalizedDocument, context: ProcessingContext) -> PIIPolicyContext:
        return build_policy_context(
            settings,
            stage=PIIScanStage.DOCUMENT,
            document_type=document.metadata.get("document_type"),
        )

It receives the document because the classification hint is a per-document input,
and the processing context so a future per-tenant policy can read the ids from
one auditable place instead of from five.
"""


class DocumentPIIGateResult(BaseModel):
    """A verdict plus the values behind it — M5 Phase 15.

    Two audiences, one evaluation. ``scan_result`` is the artifact: the Phase 1
    projection with no ``value`` and no ``value_fingerprint`` at any depth, and
    the only part of this object the pipeline persists or publishes. ``findings``
    and ``actions`` are the remediation view: the raw
    :class:`~app.pii.models.PIIFinding` objects a redactor needs, and the
    per-category map that says which of them are ``REDACT``-actioned.

    This is the shape :class:`~app.pii.canonical_guard.CanonicalPIIGuardResult`
    already uses for contour 2, for the same reason: a scan that can decide but
    cannot say *what to remove* forces the caller to re-derive the values, and a
    caller that re-derives is a second detector.

    ``Field(exclude=True)`` on both value-bearing fields is the boundary, and it
    is the whole safety argument — ``model_dump()`` cannot produce a payload
    containing a raw PII value, so neither the ``pii_result.json`` upload, nor
    the event, nor a stray ``logger.info(..., result=...)`` can leak one by
    accident. A test walks every key of the dumped model at every depth and
    asserts the absence, and the tests that already prove it for
    ``PIIScanResult`` are re-applied here.

    Frozen: the decision and the remediation must describe the same evaluation.
    A result that could be edited between the two would let a caller redact
    against actions the verdict was not based on.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scan_result: PIIScanResult
    """The boundary-safe verdict. Persisted, published, and the only part that
    ever leaves the process."""

    findings: list[PIIFinding] = Field(default_factory=list, exclude=True)
    """Raw findings, in process only. Never serialized."""

    actions: dict[PIICategory, PIIAction] = Field(default_factory=dict, exclude=True)
    """Per-category action from the same evaluation, in process only.

    Carried rather than recomputed so :meth:`DefaultPIIGate.redact` cannot
    disagree with :meth:`DefaultPIIGate.inspect` about the same document.
    """


class DefaultPIIGate(PIIGateBase):
    """``detect → aggregate → policy → project``, wired — M5 Phase 9.

    The first vertical slice: the four steps M4 defined separately, composed in
    the one order the architecture allows. The order is not incidental.
    Aggregation precedes evaluation so ``findings_count`` and ``risk_level``
    describe *distinct entities* rather than sightings, and the projection comes
    last because it is the only step that drops ``value`` and
    ``value_fingerprint``.

    Collaborators are injected rather than constructed, so a caller that wants a
    different policy, detector set or redactor state says so at the call site.
    Nothing here reads settings or environment: the policy inputs arrive through
    :data:`PolicyContextBuilder`, which keeps ``app/pii`` importable with no
    configuration present and keeps the decision free of globals.

    Text source: :meth:`inspect` scans ``document.raw_text``, which is
    **canonicalised** — case-folded, punctuation mapped, whitespace collapsed
    (``normalize.py:74-89``). That is the honest consequence of the locked
    signature, and it has one sharp edge: the offsets in a finding index
    ``raw_text``, which is *not* the markdown the pipeline sends to the model, so
    Phase 12 must re-locate a value in the source text rather than trust an
    offset across that boundary. The pattern rules are written to survive
    case-folding for the same reason (``detectors.py``).
    """

    def __init__(
        self,
        detector: PIIDetector,
        aggregator: PIIAggregator,
        policy_engine: PolicyEngine,
        policy_context_builder: PolicyContextBuilder,
        redactor: PIIRedactor,
    ) -> None:
        """Wire the collaborators.

        Args:
            detector: The composite chain. ``build_detector_chain(settings)``
                produces the configured one; injecting it keeps the gate
                constructible without configuration, which is what preserves
                ``app/pii``'s import isolation.
            aggregator: Deduplicator. ``DefaultPIIAggregator`` is stateless.
            policy_engine: Decision step. ``DefaultPolicyEngine`` is stateless
                apart from its bound policy table.
            policy_context_builder: Produces the :class:`PIIPolicyContext` for a
                call — see :data:`PolicyContextBuilder`. Required, with no
                default: a gate that could scan without one would have to invent
                a destination, and the invented value would be ``INTERNAL_LLM``,
                which is a silent allow.
            redactor: Performs the replacement for :meth:`redact`. Injected
                rather than imported, exactly as ``build_canonical_guard``
                injects one, so a test can supply a redactor that fails and
                assert the failure propagates instead of falling back to the
                unredacted text. Required, not defaulted to
                :class:`~app.pii.redaction.PlaceholderRedactor`: a silent
                no-redactor default is the one default that turns this gate into
                a pass-through.
        """
        self.detector = detector
        self.aggregator = aggregator
        self.policy_engine = policy_engine
        self.policy_context_builder = policy_context_builder
        self.redactor = redactor

    async def inspect(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> PIIScanResult:
        """Scan ``document`` and return the boundary-safe result.

        The projection of :meth:`evaluate_document`, kept because ORDER §8's
        signature is a locked contract and because a caller that only persists a
        verdict should not be handed raw values to be careful with. Both paths
        run the same code, so a verdict obtained by one cannot disagree with the
        other.

        Args:
            document: The normalized document to scan. Only ``raw_text`` is read;
                the other normalized fields (table inventory, frontmatter,
                paragraphs) are classification's business, and the canonical
                payload contour (Phase 14, VS#2) covers the structured side.
            context: The processing context, handed to the policy-context
                builder. The baseline policy does not read it — a per-tenant
                policy is the foreseeable extension, and the ids that policy
                needs are all here.

        Returns:
            A :class:`~app.pii.models.PIIScanResult`: a projection carrying no
            ``value`` and no ``value_fingerprint``. Never raises for a document
            that merely contains PII — that is what ``decision`` is for.

        Raises:
            PIIDecisionError: If the policy-context builder returns ``None``. A
                scan that cannot decide fails loudly rather than defaulting to
                ``ALLOW``, which is the one outcome that would let a document
                through with nobody having looked at it ("Fail closed" above).
        """
        result = await self.evaluate_document(document, context)
        return result.scan_result

    async def evaluate_document(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> DocumentPIIGateResult:
        """Scan ``document`` and return the verdict *and* what to remove for it.

        Phase 15. The gate physically could not redact before this: it returned
        a :class:`~app.pii.models.PIIScanResult`, whose findings are
        :class:`~app.pii.models.PIIFindingSummary` — a model with no ``value``
        field at all, by the Phase 1 structural rule. The pipeline was therefore
        holding nothing a redactor could consume, and the only correct statement
        about redaction was that it was not wired.

        So this returns the safe projection *and* the values beside it, in
        process, in the same shape
        :meth:`~app.pii.canonical_guard.DefaultCanonicalPIIInspector.evaluate_payload`
        already established for contour 2: a safe artifact plus
        :class:`~app.pii.models.PIIFinding` objects that must never be
        serialized. The two value-bearing fields are ``Field(exclude=True)``, and
        the existing walk-every-key tests are re-applied to this type at any
        depth.

        Raises:
            PIIDecisionError: If the policy-context builder returns ``None``.
        """
        policy_context = self.policy_context_builder(document, context)
        if policy_context is None:
            raise PIIDecisionError(
                f"{type(self).__name__}.evaluate_document got no PIIPolicyContext from its "
                "builder; refusing to assume a destination, because assuming INTERNAL_LLM is a "
                "silent allow."
            )

        findings = self.aggregator.aggregate(self.detector.detect(document))
        decision = self.policy_engine.evaluate(findings, policy_context)
        return DocumentPIIGateResult(
            scan_result=self._project(decision, findings, policy_context),
            findings=findings,
            actions=dict(decision.actions),
        )

    def redact(self, markdown: str, result: DocumentPIIGateResult) -> str:
        """Return the text to send, with every ``REDACT``-actioned value removed.

        The rule is §4.12 verbatim: mask iff ``actions[category] is REDACT``.
        ``DOCTOR_NAME`` and ``ORGANIZATION_NAME`` are ``ALLOW``-actioned at every
        destination, and blanking them would destroy the note
        (``render_document`` and the appointment model need them, R3), so the
        filter is per category and not "redact everything found".

        The decision is **not** re-evaluated here. It was made once, in
        :meth:`evaluate_document`, and re-deriving it in a second place is how
        the two would come to disagree about what a document is allowed to
        contain. This method consumes ``result.actions``; it does not read
        settings, the destination, or the findings' categories on its own.

        Args:
            markdown: The text as it would be sent. Never modified.
            result: The evaluation this redaction belongs to. Using a result
                from a different document raises rather than redacting the wrong
                text — a stale result is indistinguishable from a leak at the
                call site.

        Returns:
            A new string with each ``REDACT``-actioned value replaced by
            ``[CATEGORY]``. **Returns ``markdown`` unchanged, by identity, when
            nothing is ``REDACT``-actioned** — the caller uses that to decide
            whether a ``redacted.md`` artifact is warranted at all, so a
            "nothing was removed" answer has to be observable from outside.

        Raises:
            PIIRedactionError: From the redactor, if a finding resolves to no
                span. Propagated rather than caught: a value left in place while
                the pipeline records that redaction happened is the failure this
                gate exists to prevent.
        """
        actionable = [
            finding
            for finding in result.findings
            if result.actions.get(finding.category) is PIIAction.REDACT
        ]
        if not actionable:
            return markdown
        return self.redactor.redact(markdown, actionable)

    def _project(
        self,
        decision: PIIDecisionResult,
        findings: list[PIIFinding],
        policy_context: PIIPolicyContext,
    ) -> PIIScanResult:
        """Project the decision and findings into the persisted shape.

        The drop of ``value`` and ``value_fingerprint`` happens here and nowhere
        else, which is why this is a separate step: it is the boundary, and a
        reviewer should be able to find it by searching for where a
        ``PIIFinding`` stops being a ``PIIFindingSummary``.

        ``processed_at`` is stamped with an aware UTC timestamp, never a naive
        ``now()`` — an audit record whose time is ambiguous cannot settle a
        question of ordering, which is most of what an audit record is for.
        """
        summaries = [
            PIIFindingSummary(
                category=finding.category,
                masked_value=finding.masked_value,
                confidence=finding.confidence,
                source=finding.source,
                detector=finding.detector,
                start=finding.start,
                end=finding.end,
            )
            for finding in findings
        ]
        return PIIScanResult(
            decision=decision.decision,
            risk_level=decision.risk_level,
            stage=policy_context.stage,
            destination=policy_context.destination,
            findings=summaries,
            findings_count=len(summaries),
            detector_version=DETECTOR_VERSION,
            policy_version=PII_POLICY_VERSION,
            processed_at=datetime.now(UTC),
            category_counts=dict(Counter(summary.category.value for summary in summaries)),
            reasons=list(decision.reasons),
            warnings=list(decision.warnings),
        )


DECISION_OUTCOMES: dict[str, str] = {
    "allow": "continue",
    "allow_with_warning": "continue, and record that redaction happened",
    "review": "halt, needs_review (no human UI yet)",
    "block": "halt, processing failure",
}
"""The §0 decision table, as data, for M5's pipeline to switch on.

Keyed by the :class:`~app.pii.models.PIIDecision` *values* rather than the enum
members, because the pipeline compares against a string and because a test can
assert this table covers the enum without importing the enum into the assertion's
failure path. A test asserts the key set equals the set of ``PIIDecision``
values, so adding a decision without an outcome fails the suite rather than
reaching production as an unhandled case.
"""

REDACTION_AVAILABLE: bool = True
"""Whether a working redactor exists — M5 Phase 12.

A module constant rather than a settings read because it is not an operational
choice: it is a fact about *this codebase* (``PlaceholderRedactor.redact`` is
implemented and tested), and it is the one input to
:class:`~app.pii.policy.PIIPolicyContext` that configuration cannot honestly
change. A deployment cannot acquire a redactor by setting an environment
variable, so exposing one as config would be an operator's way to declare
"redaction is available" and have the platform believe it while no redactor
exists — the exact fail-open the flag's ``False`` default was chosen to prevent.

The consequence of ``True`` today is nil, and deliberately so: the default policy
issues ``ALLOW`` for every category but ``SECRET``, and the ``REDACT`` override
fires only for ``EXTERNAL_LLM``, so no action is escalated to ``REVIEW`` for
lack of a redactor. Phase 15 makes ``destination`` configurable; when it does,
this flag is already telling the truth.
"""

HALTING_DECISIONS: frozenset[PIIDecision] = frozenset({PIIDecision.REVIEW, PIIDecision.BLOCK})
"""The decisions that stop a document — the pipeline's only branch on the verdict.

``DECISION_OUTCOMES`` above is *prose*; a caller cannot switch on prose, so
anything branching on halt-vs-continue had to re-type the set, and a second copy
of a security-relevant set is a second copy to forget when a decision is added.

Deriving it here keeps one source of truth in the module that owns the decision
vocabulary, and ``test_policy_gate.py`` asserts it is exactly the decisions
whose :data:`DECISION_OUTCOMES` entry says "halt" — so the two cannot drift, and
adding a halting decision fails the suite rather than letting the pipeline fall
through to the extraction call with it.

``REVIEW`` and ``BLOCK`` both halt, but they are not the same event downstream;
the pipeline maps them to distinct ``error_code`` values because ``REVIEW`` is a
document that needs a person and ``BLOCK`` is a document that must not be
written down at all.
"""


def build_document_gate(settings: Settings) -> DefaultPIIGate:
    """Construct the contour-1 gate — the pipeline's one call, M5 Phase 11.

    Everything M4 left as a collaborator is resolved here, from ``settings``,
    in one place: the detector chain, the aggregator, the policy engine and the
    policy-context closure. The pipeline's ``__init__`` is then a single line
    with no ``app.pii`` vocabulary in it, which means the security-relevant
    choices (which detectors run, which stage, which destination) are all
    auditable in this file rather than scattered across a call site.

    Fail-closed properties, all inherited and none re-decided here:

    * A missing ``pii_fingerprint_secret`` raises out of the chain constructor,
      so a misconfigured deployment refuses to start rather than scanning
      anything with a brute-forceable digest.
    * ``llm_mode="internal_llm"`` with an ``ai_base_url`` that
      :data:`~app.pii.policy.TRUSTED_INTERNAL_URLS` does not name raises here
      (Phase 15 decision 3). Resolved once, at construction, so the refusal
      happens at worker start-up rather than on the first document.
    * ``redaction_available=True`` (Phase 12): a ``REDACT`` action now has a
      working redactor behind it, so the policy stops escalating to ``REVIEW``
      and starts reporting ``ALLOW_WITH_WARNING`` with "value must be redacted
      before leaving the boundary".
    * ``destination`` is :func:`~app.pii.policy.resolve_destination`'s answer,
      resolved **once** here rather than per call: a destination that could
      change between two documents of the same batch would mean the same
      document is judged under two different rules depending on when it arrived.

    ``document_type`` is read from the *normalized* document's metadata, which
    is what :data:`PolicyContextBuilder` documents. Today the pipeline
    normalizes with ``{"client_type": ...}``, so this is ``None`` in practice —
    honest, because the baseline policy ignores it. A type-specific policy
    would need the *classification* verdict plumbed in, and
    :data:`PolicyContextBuilder`'s locked signature does not carry it; that is
    a Phase 12+ change to the builder's inputs, not something to smuggle through
    ``attributes``.

    Args:
        settings: Application settings. ``pii_fingerprint_secret`` and
            ``llm_mode`` are read here, plus ``ai_base_url`` and ``s3_tenant_id``
            downstream.

    Returns:
        A wired :class:`DefaultPIIGate` for the document stage.

    Raises:
        InvalidPIIInputError: If the fingerprint secret is missing or blank, or
            if the ``internal_llm`` + untrusted-URL pairing is configured.
    """
    destination = resolve_destination(settings)

    def build_context(document: NormalizedDocument, context: ProcessingContext) -> PIIPolicyContext:
        """Close over settings to supply the inputs the locked signature omits."""
        return build_policy_context(
            settings,
            stage=PIIScanStage.DOCUMENT,
            destination=destination,
            document_type=document.metadata.get("document_type"),
            redaction_available=REDACTION_AVAILABLE,
        )

    return DefaultPIIGate(
        detector=build_detector_chain(settings),
        aggregator=DefaultPIIAggregator(),
        policy_engine=DefaultPolicyEngine(DEFAULT_POLICY),
        policy_context_builder=build_context,
        redactor=PlaceholderRedactor(),
    )
