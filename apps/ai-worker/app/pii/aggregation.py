"""PII finding aggregation contract (M4 Phase 3).

Locks what happens when several detectors see the same entity — the inevitable
case, because ``PERSON_NAME`` is deliberately reachable from both the pattern
and the structured-field detector (see ``detectors.py``). The implementation
lands in M5; the rule is fixed here so the persisted ``findings[]`` order and
count are reproducible across runs and across detector additions.

Dedup key
---------

``(category, value_fingerprint)``. Both halves are load-bearing:

- ``category`` — the same text is two different findings when it is two
  different things (``39`` as an age vs. a lab value is not a PII collision;
  ``Шадеркин`` as ``PERSON_NAME`` vs. ``DOCTOR_NAME`` is a genuine
  misclassification that must not be silently collapsed).
- ``value_fingerprint`` — the salted HMAC of the value, not the value itself.
  Aggregation therefore never holds, compares or orders raw PII, and a
  duplicate can be recognised without a second copy of the text existing in
  two findings.

A finding whose ``value_fingerprint`` is empty **bypasses dedup entirely** and
keeps its own slot in the output. This is the one rule that is a safety
property rather than a nicety: if two different values both hash to ``""``,
keying on ``(category, "")`` would merge a patient's name into a passport
finding and delete one of them from the result. Reporting a duplicate is
recoverable; a merged finding is not.

Survivor selection
------------------

Within one key group the survivor is the finding with the highest
``confidence``; ties are broken by **earliest position in the input list**.
Because the composite preserves configured detector order (see
``detectors.py``), "earliest position" is a stable, explainable rule — first
configured detector wins — and it never depends on set or dict iteration
order. This is why a pattern-form and a labelled-form match of the same name
resolve the same way on every run.

Output order
------------

Order of **first appearance** of each key in the input list. Deliberately not
sorted by category or confidence: the persisted ``findings[]`` should read in
scan order so a reviewer can follow the document, and ``category_counts`` is
the authoritative per-category tally regardless of ordering. A future
requirement to sort must arrive as an explicit contract change, not as an
accident of implementation.

Consequences for the phases that consume this rule
--------------------------------------------------

- **Phase 4 (masking) must normalize before hashing.** ``hash_pii_value`` has
  to NFC-normalize, case-fold and collapse whitespace on its input, otherwise
  ``Иванов`` and ``ИВАНОВ  `` (OCR case and spacing variants of one name, the
  normal case in Marker output) produce different fingerprints and the dedup
  this module exists to perform silently never happens. Aggregate correctness
  depends on it, so it is a contract requirement, not a nicety.
- **Phase 5 (policy) counts groups, not raw findings.** ``risk_level`` is
  ``max(category_risk)`` over the *aggregated* list and
  ``findings_count`` is its length, so dedup-then-evaluate and
  evaluate-then-dedup cannot disagree about a document's severity.
"""

from typing import Protocol

from app.pii.models import PIIFinding


class PIIAggregator(Protocol):
    """Protocol for collapsing duplicate findings from multiple detectors."""

    def aggregate(self, findings: list[PIIFinding]) -> list[PIIFinding]:
        """Return deduplicated findings, preserving first-appearance order.

        Implementations must not mutate ``findings``; ``PIIFinding`` is frozen
        and the input list is the caller's. Findings keep their
        ``value``/``value_fingerprint`` in-process — aggregation happens before
        the boundary projection (``PIIScanResult``), never after.
        """
        ...


class PIIAggregatorBase(PIIAggregator):
    """Base marker for PII aggregator implementations.

    Raises ``NotImplementedError`` until the M5 implementation lands, for the
    same fail-loud reason as ``PIIDetectorBase``: an aggregator that returned
    its input unchanged would not be wrong, but it would be *quietly* wrong —
    duplicate findings would inflate ``findings_count`` and make a
    seven-entity document look like a thirty-entity one, which is precisely the
    signal M6 calibration reads.
    """

    def aggregate(self, findings: list[PIIFinding]) -> list[PIIFinding]:
        """Not implemented until M5; always raises."""
        raise NotImplementedError(
            "PII aggregation arrives with the M5 detector implementations; "
            "see the dedup rule in this module's docstring."
        )


__all__ = ["PIIAggregator", "PIIAggregatorBase"]
