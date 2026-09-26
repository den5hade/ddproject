"""PII redaction contract (M4 Phase 4).

Redaction produces a **new** artifact string; it never rewrites the original
(``PII GATE/IMPL_ARCH.md`` §14, plan §0). ``marker.md`` and the upload stay
immutable, and the redacted form is what a future
``destination=EXTERNAL_LLM`` configuration would send — which is why ``REDACT``
is fully specified here even though it is unreachable while the only provider
is trusted by name (plan §0, §7).

The locked algorithm
--------------------

1. **Resolve every finding to a span.** Prefer ``start``/``end`` when both are
   present and lie within the markdown. Otherwise fall back to locating
   ``value`` in the markdown. A finding that resolves to neither must raise
   ``PIIRedactionError`` — never be skipped, because a silently skipped
   redaction is a leak that the artifact will happily attest to. The fallback
   is not optional: structured-field and canonical-guard findings legitimately
   arrive without offsets, and a redactor that only understood offsets would
   fail open on exactly the findings it cannot see.
2. **Merge overlapping spans** (union of intersecting ranges) before replacing.
   Applying two overlapping spans right-to-left corrupts the text, and skipping
   the second leaves part of it unredacted — a partial leak. Merging makes both
   outcomes impossible. The placeholder for a merged span comes from the
   highest-confidence finding in the group; ties resolve to the leftmost span,
   so the output is deterministic.
3. **Replace right-to-left.** Each replacement is a different length from the
   text it replaces, so offsets computed before the first edit would be invalid
   afterwards. Working from the end of the string backwards keeps every earlier
   offset valid. This is the reason the rule is "right-to-left" and not
   "sort-then-loop-forward".
4. **Do not mutate the inputs.** ``markdown`` is an immutable ``str`` and
   ``findings`` is the caller's list; neither is modified in place, and the
   returned string is a new object. ``PIIFinding`` is frozen, so a redactor
   cannot "helpfully" annotate a finding either.

Placeholder tokens
------------------

``[CATEGORY_UPPER]`` — ``[PERSON_NAME]``, ``[SNILS]``, ``[SECRET]``. The token
is built from the enum *member name*, not the value, so it stays stable if a
value is ever renamed; the two coincide for all 23 categories today. The token
is a marker for a reviewer, not a reversible encoding: nothing maps
``[PERSON_NAME]`` back to a value, which is the point.

What redaction does **not** do
-------------------------------

It does not decide whether to run. ``PIIAction.REDACT`` is a policy verdict
(Phase 5); the redactor is a mechanism that policy invokes. It does not mutate
``PIIFinding`` objects, does not re-run detection, and does not guarantee the
result is PII-free — only that the spans it was given are gone.
"""

from typing import Protocol

from app.pii.models import PIICategory, PIIFinding

__all__ = [
    "PlaceholderRedactor",
    "PIIRedactor",
    "RedactorBase",
    "placeholder_for",
]


def placeholder_for(category: PIICategory) -> str:
    """Return the redaction placeholder token for ``category``.

    ``PIICategory.PERSON_NAME`` → ``"[PERSON_NAME]"``. Built from the member
    name so it is stable under a value rename; the public helper exists so no
    caller hand-builds the token format.
    """
    return f"[{category.name}]"


class PIIRedactor(Protocol):
    """Protocol for replacing detected PII spans in a document."""

    def redact(self, markdown: str, findings: list[PIIFinding]) -> str:
        """Return a new string with every finding's span replaced.

        Implementations follow the algorithm in this module's docstring:
        resolve spans, merge overlaps, replace right-to-left, mutate nothing,
        and raise ``PIIRedactionError`` rather than skip an unresolvable
        finding.
        """
        ...


class RedactorBase(PIIRedactor):
    """Base marker for PII redactor implementations.

    Raises in ``redact`` rather than ``__init__``, consistent with
    ``PIIDetectorBase`` (Phase 3): the M5 gate must be able to construct its
    whole collaborator chain and prove that an unimplemented redactor fails
    loudly instead of quietly returning the input unchanged — which is the
    worst possible outcome for this component, since the caller would persist
    the *unredacted* text believing it had been redacted.
    """

    def redact(self, markdown: str, findings: list[PIIFinding]) -> str:
        """Not implemented until M5; always raises."""
        raise NotImplementedError(
            "PII redaction arrives with the M5 policy wiring; see the algorithm in "
            "this module's docstring."
        )


class PlaceholderRedactor(RedactorBase):
    """Replaces each span with its ``[CATEGORY_UPPER]`` token — implements in M5.

    Named and specified now because the token format is a contract that
    reviewers and M6 calibration read: a redacted artifact should be
    recognizable at a glance, and a stable token per category is what makes
    "how much was removed, and of what kind" answerable without the values.

    ``detect``-style fallbacks are not its concern — it receives findings, and
    :class:`PIIDetector` implementations are the only component that reads raw
    text to decide what a span is.
    """
