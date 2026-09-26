"""PII detection contract and detector stubs (M4 Phase 3).

Locks the ``PIIDetector`` protocol every detector implements and the four
deterministic detector stubs M5 will implement. **No detection logic in M4** —
the stubs declare a contract and raise. A stub that returned ``[]`` would be a
fail-open default: wired but unimplemented, it would report "no PII found" and
the gate would ``ALLOW``. Every stub therefore raises ``NotImplementedError``
until its M5 implementation lands, and a raising detector is caught by
``PIIDetectorError`` handling in the gate rather than silently passing a
document through.

Contract points locked here:

- ``detect`` is **synchronous** (pure string/structure transform, like
  ``SignalDetector``); only the gate's ``inspect`` is async.
- The input is the shared ``NormalizedDocument`` — one normalizer feeds both
  classification and the PII gate, so PII never grows a second Marker parser
  (``PII GATE/IMPL_ARCH.md`` Phase 2). The type is imported **type-only**: PII is a
  document-level capability and must not require ``app.classification`` to be
  importable at runtime (ORDER §8; guarded in ``tests/support/pii_imports.py``).
- A detector returns **no risk and no action** (IMPL_ARCH §12, §17). Only the policy
  engine assigns those, which is what keeps jurisdiction-specific rules data
  rather than code.
- Every returned ``PIIFinding`` must already carry a ``masked_value`` and a
  salted ``value_fingerprint`` (Phase 1 fields, Phase 4 producers). A detector
  is the only component that sees raw text, so it is the only place those two
  derived values can be built.

Category assignment is **docstring-only in M4** and becomes a machine-checked
mapping in M5. Reason: the taxonomy is not fully assigned yet — the NER and LLM
detectors are deliberately deferred (§7), so ``AGE``/``GENDER``/``NATIONALITY``
and free-text ``ADDRESS`` have no owner among these four stubs, and a
"every category is claimed" assertion would fail today by construction. The
docstrings below are the intent, not the lock.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from app.pii.exceptions import InvalidPIIInputError
from app.pii.models import PIIFinding

if TYPE_CHECKING:
    from app.classification.normalize import NormalizedDocument

DETECTOR_VERSION = "1.0.0"
"""Contract version of the detector layer, stamped into every finding.

Independent of ``PII_POLICY_VERSION`` (mirroring ``classifier_version``): a
detector change and a policy change are separate events. Patch = docs/comments
only; minor = a new detector or a new category; major = a change that alters
which findings are produced. A stored ``PIIScanResult`` names the detector
version that produced it, so a historical verdict stays interpretable.
"""


class PIIDetector(Protocol):
    """Protocol for any component that finds sensitive entities in a document."""

    def detect(self, document: NormalizedDocument) -> list[PIIFinding]:
        """Return every finding this detector can see in ``document``.

        Implementations return all matches, including duplicates across
        detectors: deduplication is the aggregator's job (``aggregation.py``),
        not each detector's. Returns ``[]`` only when the document genuinely
        contains nothing this detector looks for.
        """
        ...


class PIIDetectorBase(PIIDetector):
    """Base marker for PII detector implementations.

    Deliberately instantiable — unlike ``ClassificationServiceBase``, which
    raises in ``__init__``. M5 needs to *construct* the whole detector chain
    (including the not-yet-implemented members) to assert that every declared
    detector is actually wired, and to prove that an unimplemented detector
    fails loudly instead of passing a document through. The failure therefore
    lives in ``detect``, where the work is.
    """

    def detect(self, document: NormalizedDocument) -> list[PIIFinding]:
        """Not implemented until M5; always raises."""
        raise NotImplementedError(
            f"{type(self).__name__}.detect arrives with the M5 detector implementations."
        )


class PatternPIIDetector(PIIDetectorBase):
    """Deterministic regex/format detector (IMPL_ARCH §8) — implements in M5.

    Intended categories: ``EMAIL``, ``PHONE``, ``SNILS``, ``INN``,
    ``INSURANCE_NUMBER``, ``NATIONAL_ID``, ``PASSPORT``, ``DATE_OF_BIRTH``,
    ``MEDICAL_RECORD_NUMBER``, ``LAB_ORDER_ID``, ``TICKET_NUMBER``,
    ``PATIENT_ID``, ``ENCOUNTER_ID``.

    Fast, cheap, deterministic and unit-testable — the reason this family comes
    first. All three identifiers observed in the real leak are format-shaped:
    полис ОМС (16 digits), СНИЛС (9 digits + checksum) and
    ``Номер талона: 2026030709303211960141`` (``2b8fdd0d`` marker).

    ``PERSON_NAME``/``DOCTOR_NAME`` are *partly* in scope here (Cyrillic
    three-token capitalised names match a pattern) but overlap deliberately with
    ``StructuredFieldPIIDetector`` — the same entity found two ways is exactly
    what aggregation dedup is for. The pattern form is the weaker signal and
    must not raise confidence above the labelled-field form.

    Source: ``PIISource.PATTERN``.
    """


class StructuredFieldPIIDetector(PIIDetectorBase):
    """Labelled-field detector (IMPL_ARCH §9) — implements in M5.

    Intended categories: ``PERSON_NAME``, ``DOCTOR_NAME``, ``DATE_OF_BIRTH``,
    ``AGE``, ``GENDER``, ``NATIONALITY``, ``PHONE``, ``EMAIL``, ``ADDRESS``,
    ``SNILS``, ``INSURANCE_NUMBER``, ``TICKET_NUMBER``, ``PATIENT_ID``,
    ``MEDICAL_RECORD_NUMBER``, ``DOCTOR_LICENSE``, ``ORGANIZATION_NAME``,
    ``ORGANIZATION_ID``.

    The strongest signal available without an LLM: a value behind a known label
    (``ФИО:``, ``Дата рождения:``, ``Полис №:``, ``СНИЛС:``, ``Номер талона:``)
    is labelled data, not a guess. The real marker carries almost the whole
    taxonomy in this form, and ``"(М, 39 лет)"`` is why ``AGE``/``GENDER`` are
    PII categories at all (§7) rather than ignored.

    ``ORGANIZATION_*``/``DOCTOR_*`` are included on purpose: they are not
    patient PII (IMPL_ARCH §3) and must stay separable so a policy can redact the
    patient without redacting the issuing clinic.

    Source: ``PIISource.STRUCTURED_FIELD``.
    """


class SecretPIIDetector(PIIDetectorBase):
    """Credential/secret detector (IMPL_ARCH §13) — implements in M5.

    Intended categories: ``SECRET`` only — API keys, passwords, private keys,
    connection strings, bearer tokens. This is the *only* category the default
    policy ``BLOCK``s (plan §4.4), because a secret in an uploaded document is
    a security incident, not expected medical identity (IMPL_ARCH §2: PII presence
    alone never blocks).

    Kept as its own detector, not a pattern rule inside
    ``PatternPIIDetector``, so that "block on secret" is a separable,
    independently testable control and so a false positive in medical pattern
    matching can never block a document.

    Source: ``PIISource.PATTERN``. Detection must never be the sole control
    for a ``BLOCK``: the gate fails closed via ``PIIDecisionError`` if the
    detector cannot run at all.
    """


class CompositePIIDetector(PIIDetectorBase):
    """Runs an ordered chain of detectors — implements in M5.

    Contributes no category of its own. It holds its children in the order
    given, so "deterministic detector order" is a property of the
    configuration, not of dictionary or set iteration order somewhere deeper.

    The chain is order-bearing for a reason: aggregation's "highest confidence
    wins, first detector breaks ties" rule (see ``aggregation.py``) means the
    configured order decides which of two equally-confident findings survives.
    Order changes are therefore a policy-visible change, not a refactor.

    An empty chain is rejected at construction rather than detected at scan
    time: a composite with no detectors reports "no PII found", which is the
    one configuration that disables the gate while still looking healthy in
    the pipeline.
    """

    def __init__(self, detectors: Sequence[PIIDetector]) -> None:
        """Store ``detectors`` as an immutable, order-preserving tuple."""
        chain = tuple(detectors)
        if not chain:
            raise InvalidPIIInputError(
                "CompositePIIDetector requires at least one detector; "
                "an empty chain would silently allow every document."
            )
        self.detectors: tuple[PIIDetector, ...] = chain


__all__ = [
    "DETECTOR_VERSION",
    "CompositePIIDetector",
    "PatternPIIDetector",
    "PIIDetector",
    "PIIDetectorBase",
    "SecretPIIDetector",
    "StructuredFieldPIIDetector",
]
