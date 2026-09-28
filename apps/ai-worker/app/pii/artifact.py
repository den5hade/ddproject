"""PII artifact serialization (M5 Phase 10).

Builds the two surfaces a PII verdict is allowed to reach, from the one type
that already made it safe to serialize (:class:`~app.pii.models.PIIScanResult`):

- the versioned ``pii_result.json`` S3 artifact — the **only** place masked
  findings are persisted in full;
- the ``"pii"`` block of plan §4.7 — a counts/versions summary, no values, no
  masks, no fingerprints — reused verbatim for the frontmatter and for the
  event's ``data``.

Both mirror ``app/classification/artifact.py`` in placement and role. Neither
imports ``packages.canonical``: ``app/pii`` must stay a document-level
capability that never depends on the canonical models (ORDER §8), and M5 adds
the third import guard to prove it. ``PIIMeta`` is the canonical package's
*reader* of the block, not its producer — the block is built here as a plain
``dict`` and validated on the way into the frontmatter, which is why the
``"pii"`` shape has two homes (here and in
``canonical/metadata.py``) that this module's tests hold against
:data:`~app.pii.persistence.PII_META_REQUIRED_KEYS`.

Why the artifact has no provenance envelope
------------------------------------------

``build_classification_artifact`` wraps its verdict in a ``processing`` block
(``prompt_key``, ``schema_name``, ``model``, …) plus ``generated_at``. This
module deliberately does not, and the reason is that the fields have nothing
true to say: the classification verdict is produced *before* extraction, so the
prompt and model are the only record of the run it belongs to. The PII gate
runs on ``marker.md`` and never sees the LLM at all — stamping
``pii_result.json`` with the extraction's model and prompt version would record
provenance for a call the gate did not make, and ``PII_SCAN_RESULT_SCHEMA`` is
derived from ``PIIScanResult`` precisely so the artifact cannot grow keys no
schema covers. ``PIIScanResult`` already carries ``detector_version``,
``policy_version`` and ``processed_at``, and the S3 key already encodes tenant,
patient, document and version. So the artifact is exactly the scan result, and
it conforms to the schema by construction rather than by a filter.

Reading the versions off the result, not off the constants
-----------------------------------------------------------

``detector_version`` and ``policy_version`` are copied from the result rather
than read from ``DETECTOR_VERSION`` / ``PII_POLICY_VERSION`` here. The result
is the record of the scan that *actually ran*, and a stored verdict is only
interpretable if it names the policy that produced it (plan §4.8, risks R5/R6):
re-serializing an old result under today's constants would mislabel it. The end
to end claim — a fresh block carries the live constants — holds because the gate
stamps the result from them, and ``test_artifact.py`` asserts that wiring rather
than asserting a duplicated literal.

One result, one artifact
------------------------

This function takes a single ``PIIScanResult``. The pipeline produces two over
the life of a document — a ``stage=document`` verdict before extraction (Phase
11) and a ``stage=canonical`` verdict after ``build_canonical`` (Phase 14) — and
a two-result envelope is deliberately not built here: no schema covers it, and
composing two verdicts into one file is a decision for the phase that has both
of them in hand. Until that decision is taken, a function that accepts one result
cannot silently produce a document-shaped artifact.
"""

import json
from typing import Any

from app.pii.models import PIIScanResult

__all__ = ["build_pii_artifact", "build_pii_meta_block"]


def build_pii_artifact(*, result: PIIScanResult) -> str:
    """Serialize one gate verdict into the ``pii_result.json`` payload.

    Args:
        result: The gate's boundary-safe result. ``PIIFinding`` values are
            structurally absent from it (Phase 1's ``Field(exclude=True)`` and
            the value-free ``PIIFindingSummary``), so this is a projection of an
            already-safe type, not a place where safety is re-established.

    Returns:
        Pretty, UTF-8-preserving JSON whose top level is exactly
        ``PII_SCAN_RESULT_SCHEMA``'s property set.
    """
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)


def build_pii_meta_block(*, result: PIIScanResult) -> dict[str, Any]:
    """Project a scan result into the plan §4.7 ``"pii"`` block.

    The block summarises; the artifact holds detail. It carries counts,
    categories, the decision and both versions, and deliberately not
    ``masked_value``: a reviewer opening ``structured.md`` needs to know *what
    kind* of sensitive data the document carried, and the masks are already in
    ``pii_result.json`` (plan §4.7, ``app/pii/persistence.py``).

    The returned dict is the *same* object for the frontmatter and the event
    ``data``, so the two surfaces cannot disagree about a verdict — the one way
    this projection is consumed twice without a copy existing to drift.

    ``categories`` is derived from ``category_counts`` (the authoritative tally)
    and sorted, so two scans of the same document render byte-identical blocks;
    a consumer that had to recompute the tally to render the list would get the
    duplicate findings aggregation removes wrong.

    Args:
        result: The gate's boundary-safe result.

    Returns:
        A plain ``dict`` with exactly the eleven §4.7 keys, validated into
        ``canonical.PIIMeta`` by whatever receives it. It is a ``dict`` and not a
        ``PIIMeta`` because ``app/pii`` may not import ``packages.canonical``.
    """
    return {
        "decision": result.decision.value,
        "risk_level": result.risk_level.value,
        "stage": result.stage.value,
        "destination": result.destination.value,
        "findings_count": result.findings_count,
        "category_counts": dict(result.category_counts),
        "categories": sorted(result.category_counts),
        "detector_version": result.detector_version,
        "policy_version": result.policy_version,
        "reasons": list(result.reasons),
        "warnings": list(result.warnings),
    }
