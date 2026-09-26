"""Persistence, provenance and versioning surface (M4 Phase 7).

Locks the three surfaces a PII verdict is allowed to reach — the frontmatter and
event block, the versioned artifact, and the audit event — and the version
constants that make an old verdict interpretable. Nothing here writes, uploads or
emits: the cross-package edits these shapes imply are **documented for M5, not
made** (plan §4.9), because M4 touches ``app/pii/**`` only.

Why the block shape is data, not a model
----------------------------------------

§4.7 fixes the ``"pii"`` block as a sibling of ``ClassificationMeta`` in
``packages/canonical/canonical/metadata.py:55-74``, with ``FrontmatterMeta.pii``
its optional field. That placement is not a preference — the block has to be a
field on ``FrontmatterMeta`` for the frontmatter to render, and that class lives
in ``packages/``. So M4 does **not** define a competing Pydantic model for the
block: two classes for one shape is two things to keep in sync, and the one M5
adds would be the one actually used. Instead the key set is data
(:data:`PII_META_REQUIRED_KEYS` / :data:`PII_META_OPTIONAL_KEYS`), asserted
against plan §4.7 by ``test_persistence_contract.py``. A JSON Schema was
rejected for the same reason plus one more: ``app/pii/schemas.py`` derives its
schemas from the contract models precisely so they cannot drift, and there is no
model here to derive from.

What may cross a boundary, restated
-----------------------------------

The block and the audit record are the *only* two PII surfaces that leave the
process, and both carry counts, categories, decisions and versions. Neither
carries a value, a mask, a fingerprint or a detector internal:

- ``PIIFindingSummary.masked_value`` never appears here. ``category_counts`` and
  ``categories`` say *what kind* of PII was present and how often, which is what
  a reviewer needs; the mask belongs only in ``pii_result.json``.
- ``PIIAuditRecord`` has no value, mask or fingerprint field, and the test asserts
  the exact field set so one cannot be appended later.

``pii.redacted`` is emitted *in addition to* the decision's own event, not instead
of it: a document that was redacted and allowed is both, and collapsing the two
into one event would make "how often do we redact" unanswerable without joining
against the stored result.

Versioning
----------

Two constants, both already stamped onto every result: ``DETECTOR_VERSION``
(:data:`app.pii.detectors.DETECTOR_VERSION`) and ``PII_POLICY_VERSION``
(:data:`app.pii.policy.PII_POLICY_VERSION`). The SemVer rules are Classification
2.0's, unchanged:

``patch``
    Docs and comments.
``minor``
    Additive — a new optional field, a new ``PIICategory`` value.
``major``
    Breaking — a required field changes, an enum member is removed, or a
    **decision rule changes**.

The rule with teeth: **any change that alters a decision bumps the policy
version.** A stored ``PIIScanResult`` is only interpretable if the policy that
produced it can be identified, so "tweak a threshold" is a major bump, not a
patch. And a new ``PIICategory`` requires a matching row in ``CATEGORY_RISK`` in
the same change, because ``PIIPolicy`` rejects an incomplete table at
construction — a new category with no policy row is a startup error, not a
category that quietly inherits no action.
"""

from app.pii.detectors import DETECTOR_VERSION
from app.pii.policy import PII_POLICY_VERSION

__all__ = [
    "DECISION_AUDIT_EVENTS",
    "DETECTOR_VERSION",
    "PII_ARTIFACT_FILENAME",
    "PII_AUDIT_EVENTS",
    "PII_META_BLOCK_KEY",
    "PII_META_OPTIONAL_KEYS",
    "PII_META_REQUIRED_KEYS",
    "PII_POLICY_VERSION",
    "PII_REDACTED_EVENT",
]

PII_META_BLOCK_KEY = "pii"
"""The frontmatter and event key: ``frontmatter["pii"]``, ``event.data["pii"]``.

One key for both surfaces, mirroring ``classification``. Deliberately **not** a
new event and **not** a new table (plan §4.7): the verdict rides along with
metadata that is already written, which is why account-api learns it with no
migration.
"""

PII_ARTIFACT_FILENAME = "pii_result.json"
"""The versioned artifact, mirroring ``classification_result.json``.

The only place masked findings are persisted in full. It is an artifact, not
inline metadata, precisely so the bulky per-finding detail stays out of
frontmatter and the event envelope.
"""

PII_META_REQUIRED_KEYS: tuple[str, ...] = (
    "decision",
    "risk_level",
    "stage",
    "destination",
    "findings_count",
    "category_counts",
    "categories",
    "detector_version",
    "policy_version",
)
"""The nine keys §4.7 marks as always present.

Ordered as in §4.7's example so a diff against the plan is readable.
``category_counts`` is authoritative and ``categories`` is the convenience list
derived from it for UI and metrics — both are required, because a consumer that
has to recompute the tally to render a list will get it subtly wrong for the
duplicate findings aggregation is designed to remove.
"""

PII_META_OPTIONAL_KEYS: tuple[str, ...] = (
    "reasons",
    "warnings",
)
"""Keys defaulting to empty lists, matching ``ClassificationMeta``.

Both are lists of strings, so "absent" and "empty" mean the same thing to a
consumer; making them required would force every writer to remember two empty
lists, and making the rest optional would let a block omit its decision.
"""

PII_REDACTED_EVENT = "pii.redacted"
"""Emitted in addition to the decision's event whenever redaction was applied."""

PII_AUDIT_EVENTS: tuple[str, ...] = (
    "pii.scan.completed",
    PII_REDACTED_EVENT,
    "pii.review.required",
    "pii.blocked",
)
"""The complete audit vocabulary of §4.7.

Audit must be written (IMPL_ARCH §22) and must never carry values (IMPL_ARCH §6, §22), so
these four names are the whole surface: there is no "allowed" event distinct from
``pii.scan.completed``, because a clean scan and an allowed-with-warnings scan
are the same operational event with different contents.
"""

DECISION_AUDIT_EVENTS: dict[str, str] = {
    "allow": "pii.scan.completed",
    "allow_with_warning": "pii.scan.completed",
    "review": "pii.review.required",
    "block": "pii.blocked",
}
"""Which audit event each decision emits, keyed by ``PIIDecision`` value.

``ALLOW`` and ``ALLOW_WITH_WARNING`` share ``pii.scan.completed`` on purpose:
they differ in the stored result, not in what happened operationally, and a
consumer asking "was this document scanned?" should not have to know the decision
vocabulary to get an answer. A test asserts the value set equals the enum's, so a
new decision cannot arrive without an event.
"""
