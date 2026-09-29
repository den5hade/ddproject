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

from app.pii.aggregation import DefaultPIIAggregator, PIIAggregator
from app.pii.detectors import (
    DETECTOR_VERSION,
    PIIDetector,
    build_detector_chain,
)
from app.pii.exceptions import PIIDecisionError
from app.pii.models import (
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
)

if TYPE_CHECKING:
    from app.classification.normalize import NormalizedDocument
    from app.config.settings import Settings
    from app.pipeline.context import ProcessingContext


__all__ = [
    "DECISION_OUTCOMES",
    "HALTING_DECISIONS",
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
    ) -> None:
        """Wire the four collaborators.

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
        """
        self.detector = detector
        self.aggregator = aggregator
        self.policy_engine = policy_engine
        self.policy_context_builder = policy_context_builder

    async def inspect(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> PIIScanResult:
        """Scan ``document`` and return the boundary-safe result.

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
        policy_context = self.policy_context_builder(document, context)
        if policy_context is None:
            raise PIIDecisionError(
                f"{type(self).__name__}.inspect got no PIIPolicyContext from its builder; "
                "refusing to assume a destination, because assuming INTERNAL_LLM is a "
                "silent allow."
            )

        findings = self.aggregator.aggregate(self.detector.detect(document))
        decision = self.policy_engine.evaluate(findings, policy_context)
        return self._project(decision, findings, policy_context)

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
    * ``redaction_available=True`` (Phase 12): a ``REDACT`` action now has a
      working redactor behind it, so the policy stops escalating to ``REVIEW``
      and starts reporting ``ALLOW_WITH_WARNING`` with "value must be redacted
      before leaving the boundary". Note that this changes nothing observable at
      today's destination — the default policy issues ``ALLOW`` for every
      category except ``SECRET``, and the ``REDACT`` override only fires for
      ``EXTERNAL_LLM`` — so the redactor stays dormant until Phase 15 makes
      ``destination`` a settings read. Setting the flag now means the policy is
      already honest about the redactor's existence when that switch is flipped,
      instead of needing a code change at the same moment the boundary moves.
    * ``destination`` is left at :data:`~app.pii.policy.DEFAULT_DESTINATION`
      rather than named here, so Phase 15 changes one default instead of this
      call.

    ``document_type`` is read from the *normalized* document's metadata, which
    is what :data:`PolicyContextBuilder` documents. Today the pipeline
    normalizes with ``{"client_type": ...}``, so this is ``None`` in practice —
    honest, because the baseline policy ignores it. A type-specific policy
    would need the *classification* verdict plumbed in, and
    :data:`PolicyContextBuilder`'s locked signature does not carry it; that is
    a Phase 12+ change to the builder's inputs, not something to smuggle through
    ``attributes``.

    Args:
        settings: Application settings. ``pii_fingerprint_secret`` is read by
            the chain constructor; nothing else is consulted.

    Returns:
        A wired :class:`DefaultPIIGate` for the document stage.

    Raises:
        InvalidPIIInputError: If the fingerprint secret is missing or blank.
    """

    def build_context(document: NormalizedDocument, context: ProcessingContext) -> PIIPolicyContext:
        """Close over settings to supply the inputs the locked signature omits."""
        return build_policy_context(
            settings,
            stage=PIIScanStage.DOCUMENT,
            document_type=document.metadata.get("document_type"),
            redaction_available=REDACTION_AVAILABLE,
        )

    return DefaultPIIGate(
        detector=build_detector_chain(settings),
        aggregator=DefaultPIIAggregator(),
        policy_engine=DefaultPolicyEngine(DEFAULT_POLICY),
        policy_context_builder=build_context,
    )
