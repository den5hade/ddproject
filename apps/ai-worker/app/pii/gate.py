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

from typing import TYPE_CHECKING, Protocol

from app.pii.models import PIIScanResult

if TYPE_CHECKING:
    from app.classification.normalize import NormalizedDocument
    from app.pipeline.context import ProcessingContext

__all__ = [
    "DECISION_OUTCOMES",
    "PIIGate",
    "PIIGateBase",
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
