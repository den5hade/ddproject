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

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.pii.exceptions import PIIRedactionError
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
    """Replaces each span with its ``[CATEGORY_UPPER]`` token — M5 Phase 12.

    Named and specified now because the token format is a contract that
    reviewers and M6 calibration read: a redacted artifact should be
    recognizable at a glance, and a stable token per category is what makes
    "how much was removed, and of what kind" answerable without the values.

    ``detect``-style fallbacks are not its concern — it receives findings, and
    :class:`PIIDetector` implementations are the only component that reads raw
    text to decide what a span is.

    **The offset is verified before it is trusted, and this is the one place
    Phase 12 deviates from the module docstring's wording.** The docstring says
    to prefer ``start``/``end`` "when both are present and lie within the
    markdown". That test is not sufficient, and on the real caller it is
    actively wrong. Findings produced by :meth:`app.pii.gate.PIIGate.inspect`
    index ``document.raw_text``, which is *canonicalised* — case-folded,
    punctuation-mapped, whitespace-collapsed — while the markdown is none of
    those things. Measured on the ``synthetic-consultation-01`` fixture, all six
    findings return offsets that are comfortably **in range** and point at
    unrelated text:

    .. code-block:: text

        person_name  (117, 140) -> "* Смирнова Ольга Иванов"   (value: "смирнова ольга ивановна")
        date_of_birth (142, 152) -> ", 1974-03-"               (value: "1974-03-12")
        phone        (166, 184) -> "* +7 (495) 000-11-"        (value: "+7 (495) 000-11-22")

    Honouring those offsets would replace the wrong characters *and* leave the
    real value in the document: corruption and leak in one step, and the
    artifact would attest to having removed a value it never touched. So this
    implementation treats the offset as a **hint** and accepts it only when the
    text it selects actually matches the finding's value; otherwise it locates
    the value in the markdown. Both halves of the deviation tighten the locked
    algorithm — they only change behaviour for offsets that were wrong, and for
    well-formed findings (the canonical-guard contour, where the caller walks
    the exact string it scanned) the hint still wins and the fast path is kept.
    The docstring's intent — "never skip a finding, because a silently skipped
    redaction is a leak" — is served better by this than by the literal reading,
    which leaks while appearing to succeed.

    Case-insensitive location is required, not a convenience: the canonicaliser
    case-folds, so a value the detector saw as ``смирнова ольга ивановна``
    appears in the markdown as ``Смирнова Ольга Ивановна``. Matching is done
    with a case-insensitive regex over the *original* string rather than
    ``str.casefold()`` on both sides, because ``casefold`` can change a string's
    length (``"ß".casefold() == "ss"``) and a length-changing search returns
    offsets into the wrong string.
    """

    def redact(self, markdown: str, findings: list[PIIFinding]) -> str:
        """Return a new string with every finding's span replaced.

        Steps 1–4 of the module docstring, in order: resolve, merge, replace
        right-to-left, mutate nothing.

        Args:
            markdown: The text to redact. Never modified — ``str`` is immutable
                and the returned string is built by slicing.
            findings: The findings to remove. Read-only; no
                :class:`~app.pii.models.PIIFinding` is annotated or sorted in
                place, because the finding list is the caller's and the same
                list is what the gate will project into the audit artifact.

        Returns:
            A new string with each finding's span replaced by
            :func:`placeholder_for`. With no findings, ``markdown`` unchanged —
            a no-op is the correct answer, not a missed replacement.

        Raises:
            PIIRedactionError: If a finding resolves to no span at all. The
                failure is deliberate and total: a partially redacted document
                is a leak wearing the costume of a success, so this redactor
                would rather produce nothing than produce a lie.
        """
        if not findings:
            return markdown

        spans = sorted(
            (self._resolve(markdown, finding) for finding in findings),
            key=lambda span: (span.start, span.end, -span.confidence, span.placeholder),
        )
        merged = _merge_overlapping(spans)

        redacted = markdown
        for span in reversed(merged):  # right-to-left: earlier offsets stay valid
            redacted = redacted[: span.start] + span.placeholder + redacted[span.end :]
        return redacted

    def _resolve(self, markdown: str, finding: PIIFinding) -> _Span:
        """Locate one finding in ``markdown`` — the offset hint, then the value.

        Raises:
            PIIRedactionError: If neither the hint nor the value locates.
        """
        from_offset = self._span_from_offset(markdown, finding)
        if from_offset is not None:
            return from_offset

        value = finding.value
        if value:
            located = _locate(markdown, value)
            if located is not None:
                return _Span(
                    start=located[0],
                    end=located[1],
                    placeholder=placeholder_for(finding.category),
                    confidence=finding.confidence,
                )

        raise PIIRedactionError(
            f"cannot redact a {finding.category.value} finding from the text: neither its "
            f"({finding.start}, {finding.end}) offsets nor its value select it. The finding's "
            f"offsets index a different string than the one being redacted, and redaction "
            f"refuses to guess: a value left in place and an artifact claiming it was removed "
            f"is the failure this gate exists to prevent."
        )

    @staticmethod
    def _span_from_offset(markdown: str, finding: PIIFinding) -> _Span | None:
        """Accept the offset hint only if the text it selects *is* the finding's value.

        Returns ``None`` — meaning "use the value instead" — for an absent,
        inverted, out-of-range or merely *wrong* offset. An unverified offset is
        never used: see the class docstring for the measured case.
        """
        start, end = finding.start, finding.end
        if start is None or end is None or not 0 <= start < end <= len(markdown):
            return None
        if not finding.value or not _same_text(markdown[start:end], finding.value):
            return None
        return _Span(
            start=start,
            end=end,
            placeholder=placeholder_for(finding.category),
            confidence=finding.confidence,
        )


@dataclass(frozen=True)
class _Span:
    """One located replacement: where, with what, and whose confidence won."""

    start: int
    end: int
    placeholder: str
    confidence: float


def _same_text(left: str, right: str) -> bool:
    """Compare two strings ignoring case and whitespace runs.

    The canonicaliser case-folds and collapses whitespace before detection, so
    the text at a *correct* offset differs from the finding's ``value`` in
    exactly those two ways. Anything else differing means the offset is wrong.
    """
    normalise = lambda text: " ".join(text.split()).casefold()  # noqa: E731
    return normalise(left) == normalise(right)


def _locate(markdown: str, value: str) -> tuple[int, int] | None:
    """Leftmost case-insensitive occurrence of ``value``, or ``None``.

    A case-insensitive *regex* rather than ``casefold()`` on both strings
    because ``casefold`` is not length-preserving (``"ß"`` → ``"ss"``); searching
    a transformed copy would return offsets into the wrong string and splice it
    at the wrong place.
    """
    match = re.search(re.escape(value), markdown, re.IGNORECASE)
    return (match.start(), match.end()) if match else None


def _merge_overlapping(spans: list[_Span]) -> list[_Span]:
    """Union intersecting spans so no character is replaced twice.

    Two overlapping spans applied right-to-left would corrupt the text, and
    dropping the second would leave part of a value in place — a partial leak.
    Merging makes both outcomes unrepresentable.

    Touching spans are **not** merged: ``[0, 5)`` and ``[5, 10)`` do not
    intersect, they are two adjacent values, and collapsing them into one
    placeholder would destroy the fact that two different things were removed.

    The merged span's placeholder comes from the highest-confidence finding in
    the group. Confidence alone is not enough to make the output deterministic:
    two findings can share a confidence *and* a span, and then "first one seen"
    would put the caller's ordering into the artifact — the same document
    redacted twice could produce two different files. So the sort key carries
    ``(start, end, confidence, placeholder)``: position dominates (so a tie is
    always the leftmost span), and the placeholder is the final tiebreaker, which
    is intrinsic to the finding rather than to when it arrived.
    """
    merged: list[_Span] = []
    for span in spans:
        if merged and span.start < merged[-1].end:
            previous = merged[-1]
            winner = span if span.confidence > previous.confidence else previous
            merged[-1] = _Span(
                start=previous.start,
                end=max(previous.end, span.end),
                placeholder=winner.placeholder,
                confidence=winner.confidence,
            )
        else:
            merged.append(span)
    return merged
