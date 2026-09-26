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

:data:`DECISION_REMEDIATION` maps the Phase 5 decision vocabulary onto these. That
mapping is **M4's proposal, not a locked decision** — the actions are named
here because the plan requires it, but which action belongs to which decision is
an M5 call, and it is recorded as such in the plan.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from app.pii.models import PIICategory, PIIDestination, PIIScanStage

__all__ = [
    "CANONICAL_POLICY_DESTINATION",
    "CANONICAL_POLICY_STAGE",
    "CanonicalPIIInspector",
    "CanonicalPIIInspectorBase",
    "CanonicalPIIViolation",
    "DECISION_REMEDIATION",
    "PIIRemediation",
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
    "review": PIIRemediation.SANITIZE,
    "block": PIIRemediation.RETRY_THEN_FAIL,
}
"""Proposed decision → remediation mapping. **Not locked** — M5 confirms it.

Keyed by :class:`~app.pii.models.PIIDecision` values, matching
``gate.DECISION_OUTCOMES``, and asserted against the enum's values so a new
decision cannot arrive without a remediation.

The reasoning, since the mapping is a judgement call: ``ALLOW`` still maps to
``WARN`` rather than to "nothing", because reaching the guard's remediation step
at all means violations were found, and a decision of ``ALLOW`` on a payload
that *did* leak is the Phase 5 gap already recorded in the plan — it should leave
a trace rather than pass silently. ``REVIEW`` sanitizes because the guard's
entire purpose is that the observed leak reached ``canonical.json``; halting a
document for human review is not a reason to also write the patient's name to
storage on the way to the review queue. ``BLOCK`` is the only retry: a secret in
a payload is an upstream prompt defect, and one re-run is worth attempting before
failing the document outright.
"""
