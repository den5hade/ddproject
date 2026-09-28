"""PII detection contract, detector stubs and the settings-driven chain (M5 Phase 8).

Locks the ``PIIDetector`` protocol every detector implements and the four
deterministic detector stubs M5 will implement. **No detection logic yet** — the
stubs declare a contract and raise. A stub that returned ``[]`` would be a
fail-open default: wired but unimplemented, it would report "no PII found" and
the gate would ``ALLOW``. Every stub therefore raises ``NotImplementedError``
until its implementation lands, and a raising detector is caught by
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

The fingerprint secret (M5 Phase 8)
----------------------------------

``PIIFinding.value_fingerprint`` is an HMAC over the raw value, and an HMAC
without its key is just a hash — which for СНИЛС, полис ОМС or a date of birth
means "the value wearing a disguise" (``masking.py``). So the secret is supplied
from configuration, is required, and has no usable default:

- :func:`build_detector_chain` is the only sanctioned way to assemble detectors,
  and it **raises** ``InvalidPIIInputError`` when ``settings.pii_fingerprint_secret``
  is missing, empty or whitespace-only. The check is at construction — worker
  start-up — so a misconfigured deployment fails closed before it can scan
  anything, rather than producing unkeyed fingerprints at 3am.
- :meth:`PIIDetectorBase.fingerprint` is the second, per-call choke point: a
  detector constructed directly (a test, a future tool) with no secret still
  cannot produce a finding, so "no raw value, no keyed fingerprint, no finding"
  holds on every path rather than only on the configured one.
- The secret is never logged, never serialized and never a public attribute.
  It is read once, at construction, and thereafter only its HMAC escapes.

``Settings`` is imported **type-only** for the same reason ``NormalizedDocument``
is: ``app.pii`` must stay importable with no configuration and no
infrastructure, so the security control never depends on the deployment
supplying an environment. The wiring happens at the edge — ``DocumentPipeline``
(Phase 11) — not here.

Category assignment is **docstring-only in M4** and becomes a machine-checked
mapping in M5. Reason: the taxonomy is not fully assigned yet — the NER and LLM
detectors are deliberately deferred (§7), so ``AGE``/``GENDER``/``NATIONALITY``
and free-text ``ADDRESS`` have no owner among these four stubs, and a
"every category is claimed" assertion would fail today by construction. The
docstrings below are the intent, not the lock.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.pii.exceptions import InvalidPIIInputError
from app.pii.masking import hash_pii_value, mask_pii_value
from app.pii.models import PIICategory, PIIFinding, PIISource

if TYPE_CHECKING:
    from app.classification.normalize import NormalizedDocument
    from app.config.settings import Settings

DETECTOR_VERSION = "1.1.0"
"""Contract version of the detector layer, stamped into every finding.

Independent of ``PII_POLICY_VERSION`` (mirroring ``classifier_version``): a
detector change and a policy change are separate events. Patch = docs/comments
only; minor = a new detector or a new category; major = a change that alters
which findings are produced. A stored ``PIIScanResult`` names the detector
version that produced it, so a historical verdict stays interpretable.

``1.1.0`` in M5 Phase 9, and the bump is exactly the contract change: the
detector protocol gained ``detect_text`` and a concrete pattern detector exists
where only a stub did. No category was added, removed, or re-labelled, and no
finding produced by the same text changed shape — the minor line, not the major
one. The `^0.95$` guard in the detector test suite is what keeps that honest.
"""

PII_FINGERPRINT_SECRET_ENV = "PII_FINGERPRINT_SECRET"
"""Env var backing ``Settings.pii_fingerprint_secret``, named in error messages.

Quoted verbatim in the failure raised by :func:`build_detector_chain` so the
operator who hits it is told the variable to set instead of only being told
that something is missing. The value is never part of any message.
"""


class PIIDetector(Protocol):
    """Protocol for any component that finds sensitive entities in a document."""

    def detect(self, document: NormalizedDocument) -> list[PIIFinding]:
        """Return every finding this detector can see in ``document``.

        A wrapper over :meth:`detect_text`, not the real entry point: the
        canonical-output guard (contour 2) works on string leaves of a payload
        and has no document to pass, so ``detect_text`` is the method every
        implementation actually provides (§7 decision 5).

        Implementations return all matches, including duplicates across
        detectors: deduplication is the aggregator's job (``aggregation.py``),
        not each detector's. Returns ``[]`` only when the document genuinely
        contains nothing this detector looks for.
        """
        ...

    def detect_text(self, text: str) -> list[PIIFinding]:
        """Return every finding this detector can see in ``text``.

        Pure and synchronous, so the same call serves both contours and both are
        testable with a string literal. Offsets are relative to ``text`` exactly
        as passed — see the offsets caveat in this module's docstring before
        using them to edit a *different* string.
        """
        ...


class PIIDetectorBase(PIIDetector):
    """Base marker for PII detector implementations, and the secret boundary.

    Deliberately instantiable — unlike ``ClassificationServiceBase``, which
    raises in ``__init__``. The gate needs to *construct* the whole detector
    chain (including the not-yet-implemented members) to assert that every
    declared detector is actually wired, and to prove that an unimplemented
    detector fails loudly instead of passing a document through. The failure
    therefore lives in ``detect``, where the work is.

    The fingerprint secret is optional **only** so the not-yet-implemented
    members stay constructible. It is not a usable default: an unconfigured
    detector cannot fingerprint, so it cannot produce a finding (see
    :meth:`fingerprint`), and :func:`build_detector_chain` refuses to build an
    unconfigured chain in the first place.
    """

    def __init__(self, *, fingerprint_secret: str = "") -> None:
        """Hold the HMAC key used to fingerprint this detector's findings."""
        self._fingerprint_secret = fingerprint_secret

    def detect(self, document: NormalizedDocument) -> list[PIIFinding]:
        """Not implemented until M5 Phase 9; always raises."""
        raise NotImplementedError(
            f"{type(self).__name__}.detect arrives with the M5 detector implementations."
        )

    def detect_text(self, text: str) -> list[PIIFinding]:
        """Return every finding this detector can see in one string.

        The real entry point. ``detect`` is a thin wrapper over it, added in M5
        Phase 9 (§7 decision 5) because the canonical-output guard walks *string
        leaves* of a payload and has no ``NormalizedDocument`` to hand over — a
        protocol whose only entry point takes a document is unusable by contour
        2. Additive, hence ``DETECTOR_VERSION`` 1.0.0 → 1.1.0.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.detect_text arrives with the M5 detector implementations."
        )

    def fingerprint(self, value: str) -> str:
        """Return the salted HMAC fingerprint of ``value`` under this detector's secret.

        The one place a detector turns raw text into a value that may be
        compared, correlated or persisted. Raises rather than falling back to a
        keyless digest: an unconfigured detector must not be able to produce a
        finding at all, because a fingerprint column that looks keyed and is
        not is the exact failure ``masking.py`` exists to prevent.

        Args:
            value: The raw value. Normalized inside
                :func:`~app.pii.masking.hash_pii_value`; never logged, never
                persisted.

        Returns:
            ``"hmac-sha256:"`` plus the lowercase hex digest.

        Raises:
            InvalidPIIInputError: If this detector has no usable secret.
        """
        if not self._fingerprint_secret.strip():
            raise InvalidPIIInputError(
                f"{type(self).__name__} has no usable fingerprint secret; build detectors "
                f"with build_detector_chain(settings) and set {PII_FINGERPRINT_SECRET_ENV}."
            )
        return hash_pii_value(value, secret=self._fingerprint_secret)


# --- pattern rules (M5 Phase 9) ------------------------------------------------

_CYRILLIC_TOKEN = r"[А-ЯЁ][а-яё]+"
_CYRILLIC_ANY_TOKEN = r"[А-Яа-яЁё]+"
"""Two Cyrillic letter classes: title-cased, and case-agnostic.

The second exists because of a property of the *input*, not of Russian grammar:
``MarkdownNormalizer.raw_text`` is case-folded (``normalize.py:82``), so
contour 1 scans text in which every name is lower-case. A title-case-only rule
would match the canonical guard's payload leaves and nothing else — a green test
suite with the contour-1 gate silently blind. ``re.IGNORECASE`` is not the answer:
its Unicode-aware case folding does not cover Cyrillic.
"""


@dataclass(frozen=True)
class _Pattern:
    """One compiled rule row: what it finds, how it is named, how sure it is."""

    category: PIICategory
    name: str
    regex: re.Pattern[str]
    confidence: float
    group: int = 0
    """Capture group holding the *value*; 0 means the whole match.

    Needed by rules whose match is wider than the entity — the name-after-label
    rule includes the introducing word so the label can be required, and a
    ``masked_value`` of ``"Пациент Смирнова Ольга"`` would be a fabricated field
    value. Offsets come from the same group, so a wider match never shifts them.
    """


_LONG_DIGIT_RUN = r"(?<!\d)\d{12,}(?!\d)"
"""A bare digit run long enough to be a *талон*.

The threshold is the real marker's, not a guess: ``Номер талона`` in
``2b8fdd0d`` is 22 digits. Twelve is where a run stops looking like a card
number — the ``Номер карты: 0000001234`` in the real fixture is 10, and calling
that a ticket is the guess this rule exists not to make.
"""
_NAME_LABELS = r"пациент\w*|фио|врач\w*|доктор\w*|д-р|больн\w*"
"""Words that introduce a name in the document genre this platform receives.

Used *only* by :data:`_PATTERNS`' label rule — the case-folded contour's name
rule. The word list is Cyrillic and case-agnostic on purpose: in folded text the
label is as lower-case as the name.
"""

_MD_DECOR = r"[\s:*_~>#—–-]*"
"""Markdown decoration between a label and its value.

Not cosmetic: ``raw_text`` keeps emphasis markers, so the real text is
``"**пациент:** смирнова ольга ивановна"``. A rule that allows only a colon and
a space after the label matches the fixture on disk and **not** the document the
pipeline actually hands the gate — the same class of blind spot as the
case-folding, and the reason this is a named constant rather than an inline
character class somebody tightens later.
"""


def _tolerant(alternatives: Sequence[str]) -> re.Pattern[str]:
    """Compile an alternation whose alternatives are joined in the order given.

    The order *is* the precedence: ``re`` matches the first alternative that
    succeeds at a position, so a rule listed before a broader one is the rule
    that wins on overlapping text. A tolerant form (separated by ``-``, spaces,
    and no separator at all) is listed before a strict one for exactly that
    reason — ``123-067-082 21`` must not be read as a bare 9+ digit run first.
    """
    return re.compile("|".join(f"(?:{alternative})" for alternative in alternatives))


_PATTERNS: tuple[_Pattern, ...] = (
    _Pattern(
        category=PIICategory.PERSON_NAME,
        name="person_name.three_token",
        regex=_tolerant([rf"{_CYRILLIC_TOKEN}(?:\s+{_CYRILLIC_TOKEN}){{2}}"]),
        confidence=0.8,
    ),
    _Pattern(
        category=PIICategory.PERSON_NAME,
        name="person_name.after_label",
        regex=re.compile(
            rf"(?<![\w-])(?:{_NAME_LABELS}){_MD_DECOR}"
            rf"({_CYRILLIC_ANY_TOKEN}(?:\s+{_CYRILLIC_ANY_TOKEN}){{2}})"
            rf"(?![{_CYRILLIC_ANY_TOKEN[1:-1]}])"
        ),
        confidence=0.7,
        group=1,
    ),
    _Pattern(
        category=PIICategory.SNILS,
        name="snils.check_summed",
        regex=_tolerant([r"\d{3}-\d{3}-\d{3}\s*\d{2}", r"\d{9}\s*\d{2}"]),
        confidence=0.95,
    ),
    _Pattern(
        category=PIICategory.INSURANCE_NUMBER,
        name="insurance_number.sixteen_digits",
        regex=re.compile(r"(?<![\d-])\d{16}(?![\d-])"),
        confidence=0.95,
    ),
    _Pattern(
        category=PIICategory.PASSPORT,
        name="passport.series_number",
        regex=_tolerant([r"\d{2}[ -]\d{2}[ -]\d{6}"]),
        confidence=0.9,
    ),
    _Pattern(
        category=PIICategory.EMAIL,
        name="email.address",
        regex=re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
        confidence=0.95,
    ),
    _Pattern(
        category=PIICategory.PHONE,
        name="phone.e164",
        regex=re.compile(r"(?<![\d+])\+\d[\d\s()-]{9,17}\d"),
        confidence=0.9,
    ),
    _Pattern(
        category=PIICategory.DATE_OF_BIRTH,
        name="date_of_birth.numeric",
        regex=re.compile(r"(?<![\d-])\d{4}-\d{2}-\d{2}(?![\d-])"),
        confidence=0.8,
    ),
    _Pattern(
        category=PIICategory.TICKET_NUMBER,
        name="ticket_number.long_digits",
        regex=re.compile(_LONG_DIGIT_RUN),
        confidence=0.6,
    ),
    _Pattern(
        category=PIICategory.MEDICAL_RECORD_NUMBER,
        name="medical_record_number.labelled_card",
        regex=re.compile(
            rf"(?<![\w-])(?:амбулаторн\w*|стационарн\w*)?\s*карт\w*{_MD_DECOR}(\d{{6,12}})"
            rf"(?!\d)",
            re.IGNORECASE,
        ),
        confidence=0.95,
        group=1,
    ),
    _Pattern(
        category=PIICategory.LAB_ORDER_ID,
        name="lab_order_id.digits_and_letters",
        regex=re.compile(r"(?<![\w-])0*\d{4,}[A-Za-zА-Яа-я]{1,4}(?![\w-])"),
        confidence=0.6,
    ),
    _Pattern(
        category=PIICategory.ADDRESS,
        name="address.locality",
        regex=re.compile(r"(?:г\.|город)\s+[А-Яа-яЁё]+"),
        confidence=0.6,
    ),
)
"""The ``PatternPIIDetector`` rule table, in precedence order.

Every rule is a plain ``(category, regex, confidence)`` row rather than a method
per category, so the table can be asserted against the categories the phase is
supposed to cover — a rule that silently stops matching is a test failure, not
something a reader has to notice. Order matters twice over: within
:func:`_tolerant` alternatives, and between rows when two patterns overlap on
the same span (``SNILS`` before the ``TICKET_NUMBER`` long run, the 16-digit
``INSURANCE_NUMBER`` before the same run).

What is deliberately **not** here, and why. The absence is calibrated against
real text, not against the category list: the table was trimmed to the rules that
do not mis-claim a value the manifest already attributes to a *labelled* field.

- ``NATIONAL_ID``/``INN`` and ``PASSPORT`` as *bare* lengths — an 8/10/12-digit run.
  The ``synthetic-consultation-01`` fixture's own ``Номер карты: 0000001234`` is
  a 10-digit run the manifest calls a ``medical_record_number``; before the trim
  this table claimed that one number as a ``national_id``, as a ``ticket_number``
  and as a ``medical_record_number`` at once. Two of those three guesses were
  wrong, which is the whole argument: a pattern cannot tell six identifiers
  apart by length. What survives is the *labelled* form
  (``medical_record_number.labelled_card``) — a label is the one piece of
  evidence that turns a length into an identity, and it is the minimum the
  Phase 9 accept criterion needs to see a ``HIGH`` finding on this fixture.
  Phase 13's ``StructuredFieldPIIDetector`` supersedes it with the same evidence
  and more of it. ``PASSPORT`` survives in a different shape, because requiring
  real separators (``45 12 123456``) makes it a form rather than a length.
- ``TICKET_NUMBER`` at every length *except* the long one. The real marker's
  ``Номер талона`` is 22 digits, so :data:`_LONG_DIGIT_RUN` starts at 12 — which
  is also what keeps the rule off the 10-digit card above. A 9- or 10-digit run
  is the honest limit of "which identifier is this", and the cost of guessing it
  is a ``ticket_number`` mask applied to a patient's medical record.
- ``NATIONALITY`` — an -ский/-ческий adjective. On the real fixture it fired on
  ``синтетический``, a word that describes the dataset rather than a person. The
  category stays in the taxonomy; a label (``Гражданство: …``) is how it is found.
- ``AGE``/``GENDER`` — a bare ``39`` is a lab value as often as an age, and
  §7 decision 13 keeps them because they appear in the real note
  (``"(М, 39 лет)"``). They get a *labelled* detector in Phase 13. Detecting them
  by pattern would report every measurement in every laboratory payload.
- ``DOCTOR_NAME`` — the one FIO-shaped run the patient name will not claim is a
  two-token run, because ``Петров И. С.`` is a surname plus two initials. A
  2-token rule matches ``Уважаемые жильцы``-style prose and any org name
  ``ООО Ромашка``, so it is Phase 13's problem with a label in hand.
- ``ENCOUNTER_ID``/``PATIENT_ID``/``DOCTOR_LICENSE``/``ORGANIZATION_*`` — no
  self-identifying format at all. Claiming them from a digit run would be
  guessing, and would make a patient id a ``medical_record_number`` that Phase
  14's redaction then keeps.

Two contours, two name rules
----------------------------

``PERSON_NAME`` is the only category with **two** rows, because it is the only
one whose text differs between the two contours that scan text:

- ``person_name.three_token`` matches three title-cased Cyrillic tokens anywhere
  in the string. This is the gotcha-G1 rule: ``"...для пациента Шадеркина
  Дениса Сергеевича"`` is genitive, mid-sentence, and matches no nominative
  pattern — and it is the *canonical* contour (Phase 14) that sees the real,
  un-folded payload leaf.
- ``person_name.after_label`` is the case-folded contour's rule. On
  ``document.raw_text`` the same sentence reads ``"для пациента шадеркина
  дениса сергеевича"``, and a three-token run of lower-case Cyrillic words is
  indistinguishable from ``"сдан анализ крови"``. So the rule additionally
  requires a name-introducing label immediately before the run and a
  non-Cyrillic-token boundary immediately after it, which keeps the recall
  exactly where the leak is and pays for it in precision.

That trade is deliberate and priced. A false positive here costs one
``MEDIUM``-risk entry in an artifact and — at the internal destination, the
policy's base action for ``PERSON_NAME`` — no halt at all. A false negative
costs the leak §7 calls "the single most likely way a green Phase 9 still leaves
the leak open". For a security control the asymmetry is not close. Phase 13's
labelled detector is the real fix and supersedes the second row wherever a label
is present.

Where both rows match the *same* span they produce the same value, hence the
same fingerprint, hence one finding after aggregation — which is the dedup rule
doing exactly its job on a real pair rather than a synthetic one.
"""

_PATTERNS_BY_CATEGORY: dict[PIICategory, _Pattern] = {}
for _row in _PATTERNS:
    _PATTERNS_BY_CATEGORY.setdefault(_row.category, _row)


class PatternPIIDetector(PIIDetectorBase):
    """Deterministic regex/format detector (IMPL_ARCH §8) — implemented in M5 Phase 9.

    Runs :data:`_PATTERNS` over the text and stamps every hit with the mask and
    the fingerprint it computed itself, because a detector is the only component
    that sees raw text and the only place those two derived values can be built
    (Phase 1's field requirements).

    Two properties are load-bearing:

    - **No suppression of overlapping hits.** Two rules that match different
      spans of the same entity are two findings, and aggregation dedups only on
      ``(category, value_fingerprint)`` — a different category is *not* a
      duplicate by contract (``aggregation.py``), because collapsing a patient's
      name into a passport finding would delete one of them.
    - **Every row is used.** :meth:`detect_text` iterates the table itself rather
      than the declared categories, so a rule cannot exist in the table and be
      silently skipped by a hand-written dispatch.

    Source: ``PIISource.PATTERN``.
    """

    def detect(self, document: NormalizedDocument) -> list[PIIFinding]:
        """Scan ``document.raw_text`` — the §7 decision 5 wrapper.

        Deliberately thin, and deliberately *not* the scanner contour 1's
        pipeline will use: the pipeline already holds the original
        ``unstructured_markdown``, while ``raw_text`` is case-folded, with
        punctuation mapped and whitespace collapsed (``normalize.py:74-89``).
        Two consequences, both benign, and both reasons to call
        :meth:`detect_text` from the gate instead:

        - a case-folded source yields a lower-case ``masked_value`` — the mask
          still describes the entity, so this is fidelity, not a leak;
        - the offsets are into ``raw_text``, which is **not** the string the
          extraction prompt is built from, so they must never be applied to the
          original markdown. See the offsets caveat above.
        """
        return self.detect_text(document.raw_text)

    def detect_text(self, text: str) -> list[PIIFinding]:
        """Return every finding in ``text``, in rule order then position order.

        Args:
            text: Any string. Empty or ``None``-ish input yields ``[]`` rather
                than raising: an empty document is a legitimate input, and a
                detector that cannot be asked about nothing cannot be trusted on
                what it finds.

        Returns:
            One :class:`~app.pii.models.PIIFinding` per match, already masked
            and fingerprinted. Duplicates across rules and across detectors are
            left in place for the aggregator.
        """
        if not text:
            return []
        findings: list[PIIFinding] = []
        for row in _PATTERNS:
            findings.extend(self._find_all(row, text))
        return findings

    def _find_all(self, row: _Pattern, text: str) -> list[PIIFinding]:
        """Build one finding per match of ``row`` in ``text``."""
        found = []
        for match in row.regex.finditer(text):
            value = match.group(row.group)
            if not value.strip():
                continue
            start, end = match.span(row.group)
            found.append(
                PIIFinding(
                    category=row.category,
                    value=value,
                    masked_value=mask_pii_value(row.category, value),
                    value_fingerprint=self.fingerprint(value),
                    confidence=row.confidence,
                    source=PIISource.PATTERN,
                    detector=f"pattern.{row.name}",
                    detector_version=DETECTOR_VERSION,
                    start=start,
                    end=end,
                )
            )
        return found


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

    def __init__(self, detectors: Sequence[PIIDetector], *, fingerprint_secret: str = "") -> None:
        """Store ``detectors`` as an immutable, order-preserving tuple.

        ``fingerprint_secret`` is accepted and ignored: a composite contributes
        no category of its own and fingerprints nothing, so requiring a secret
        here would assert a guarantee the container cannot keep. The members
        built by :func:`build_detector_chain` each hold their own. It is still
        passed to the base so that a composite's inherited state is initialized
        rather than missing — an unconfigured composite must fail closed with
        :class:`~app.pii.exceptions.InvalidPIIInputError`, never ``AttributeError``.
        """
        super().__init__(fingerprint_secret=fingerprint_secret)
        chain = tuple(detectors)
        if not chain:
            raise InvalidPIIInputError(
                "CompositePIIDetector requires at least one detector; "
                "an empty chain would silently allow every document."
            )
        self.detectors: tuple[PIIDetector, ...] = chain

    def detect(self, document: NormalizedDocument) -> list[PIIFinding]:
        """Scan ``document`` with every member and concatenate their findings."""
        return self.detect_text(document.raw_text)

    def detect_text(self, text: str) -> list[PIIFinding]:
        """Fan ``text`` out over the chain, in configured order.

        Concatenation preserves the chain order, which is what makes
        aggregation's "ties broken by earliest position" rule resolve to the
        strongest configured detector on every run.
        """
        found: list[PIIFinding] = []
        for detector in self.detectors:
            found.extend(detector.detect_text(text))
        return found


def _require_fingerprint_secret(settings: Settings) -> str:
    """Resolve the HMAC key every detector is constructed with, or refuse.

    Shared by both chain constructors so the start-up choke point is one
    function: a second copy of this check is a second place for the
    fail-closed behaviour to be quietly dropped from.

    Raises:
        InvalidPIIInputError: If the secret is missing, empty or whitespace-only.
    """
    secret = settings.pii_fingerprint_secret
    if not secret.strip():
        raise InvalidPIIInputError(
            "PII detectors require a fingerprint secret; set "
            f"{PII_FINGERPRINT_SECRET_ENV} to a high-entropy value. Refusing to fall back "
            "to a keyless digest, which would be brute-forceable for low-entropy "
            "identifiers such as СНИЛС or дата рождения."
        )
    return secret


def build_detector_chain(settings: Settings) -> CompositePIIDetector:
    """Assemble the detector chain from configuration — the only sanctioned constructor.

    Resolves the fingerprint secret out of ``settings``, refuses to proceed
    without a usable one, and wires every declared detector in a fixed order.
    Called once, by the pipeline, at worker start-up (Phase 11), so a
    misconfigured deployment fails closed before it scans anything.

    Args:
        settings: Application settings carrying
            ``pii_fingerprint_secret`` (env ``PII_FINGERPRINT_SECRET``). Read
            once, here; the detectors never see ``Settings`` itself.

    Returns:
        A :class:`CompositePIIDetector` over every declared detector, in the
        order below.

    Raises:
        InvalidPIIInputError: If the secret is missing, empty or whitespace-only.
            Never degraded to a default and never downgraded to a plain digest:
            the identifiers this gate exists to catch (СНИЛС, полис ОМС, дата
            рождения) are enumerable, so an unkeyed fingerprint is a disclosure.
    """
    secret = _require_fingerprint_secret(settings)
    return CompositePIIDetector(
        (
            # Strongest signal first: aggregation breaks a confidence tie in
            # favour of the first detector in the chain, so a labelled field
            # (``ФИО:``) must outrank the same entity found by a bare pattern.
            StructuredFieldPIIDetector(fingerprint_secret=secret),
            PatternPIIDetector(fingerprint_secret=secret),
            # Last, and the only BLOCK source. Order cannot soften it, but
            # keeping it terminal makes the "separable control" property of
            # this detector visible in the wiring rather than in a comment.
            SecretPIIDetector(fingerprint_secret=secret),
        )
    )


def build_available_detector_chain(settings: Settings) -> CompositePIIDetector:
    """The chain of detectors that are actually implemented — M5 Phase 11 wiring.

    :func:`build_detector_chain` is the complete inventory and the right
    target, but two of its three members raise ``NotImplementedError`` in
    ``detect_text`` until Phase 13 writes them. A pipeline that used it today
    would not degrade to a weaker control, it would fail *every* document with
    an exception — the fail-closed posture taken past the point of being
    useful, which in practice gets "fixed" by commenting the call out.

    So the pipeline gets the implemented subset instead, and the missing
    coverage is loud rather than silent:

    * ``build_detector_chain`` is left exactly as M4/Phase 8 pinned it. Nothing
      about the full inventory is softened, reordered or defaulted.
    * The chain returned here is a *strict subset* in the same relative order,
      and ``test_detector_chain.py`` asserts that subset relation — so when
      Phase 13 lands, the failing test says "delete this function and call
      :func:`build_detector_chain`" instead of leaving two inventories to drift.
    * The one consequence that matters is a *narrower* gate, not a laxer one:
      ``SecretPIIDetector`` is the only ``BLOCK`` source, so nothing reaches
      ``BLOCK`` until Phase 13, and a document carrying a credential gets
      ``ALLOW`` rather than being stopped. That is a real gap, it is the gap
      Phase 13 exists to close, and it is not papered over here.

    Args:
        settings: Application settings carrying ``pii_fingerprint_secret``,
            validated exactly as :func:`build_detector_chain` validates it.

    Returns:
        A :class:`CompositePIIDetector` over the implemented detectors.

    Raises:
        InvalidPIIInputError: If the secret is missing, empty or whitespace-only.
    """
    secret = _require_fingerprint_secret(settings)
    return CompositePIIDetector((PatternPIIDetector(fingerprint_secret=secret),))


__all__ = [
    "DETECTOR_VERSION",
    "PII_FINGERPRINT_SECRET_ENV",
    "CompositePIIDetector",
    "PatternPIIDetector",
    "PIIDetector",
    "PIIDetectorBase",
    "SecretPIIDetector",
    "StructuredFieldPIIDetector",
    "build_available_detector_chain",
    "build_detector_chain",
]
