"""PII detection contract, the three deterministic detectors and the chain (M5 Phases 8, 9, 13).

Locks the ``PIIDetector`` protocol every detector implements and wires the three
deterministic detectors in the order the plan fixes: labelled fields, then bare
patterns, then credentials. **No detector in this chain may return ``[]`` for
want of an implementation** — that is the fail-open default this milestone exists
to prevent, so a detector that cannot scan raises instead. The three that do scan
all sit in one module on purpose: they share one rule-row shape, one
masking/fingerprint construction site, and one chain constructor, so "which
categories exist" is answerable by reading one file.

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

Category assignment is **table-driven** as of M5 Phase 13. It was docstring-only
in M4 because the taxonomy was not yet assigned: the NER and LLM detectors are
deliberately deferred (§7), and a "every category is claimed" assertion would
have failed by construction. Both remaining tables —
:data:`_FIELDS` (:class:`StructuredFieldPIIDetector`) and :data:`_SECRET_RULES`
(:class:`SecretPIIDetector`) — now name a real ``PIICategory`` per row, and the
tests assert the tables and their class docstrings agree, so a rule can no longer
be added without saying which category it serves.

``DETECTOR_VERSION`` moves to ``1.2.0`` in this phase: ``date_of_birth.numeric``
is **removed** from :data:`_PATTERNS` and ``date_of_birth.after_patient_name``
is added to :data:`_FIELDS` (§4.11). A rule leaving is not an additive change, so
the minor is spent here rather than on Phase 16's NER; the reasoning, including
the recall the swap gives up, is on the constant.

The constant has not moved since. Phase 17 raised
:data:`~app.pii.policy.PII_POLICY_VERSION` to ``3.0.0`` — the combination
threshold is a *policy* change and adds no finding, so the detector half of §5's
smoke check is still ``1.2.0`` and the pair is now ``1.2.0 3.0.0``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.pii.exceptions import InvalidPIIInputError
from app.pii.masking import hash_pii_value, mask_pii_value
from app.pii.models import PIICategory, PIIFinding, PIISource

if TYPE_CHECKING:
    from app.classification.normalize import NormalizedDocument
    from app.config.settings import Settings

DETECTOR_VERSION = "1.2.0"
"""Contract version of the detector layer, stamped into every finding.

Independent of ``PII_POLICY_VERSION`` (mirroring ``classifier_version``): a
detector change and a policy change are separate events. The rule is §4.8's —
patch = docs/comments only; minor = **additive** (new optional fields, new
``PIICategory`` values); major = breaking (required-field changes, enum removals,
decision-rule changes). A stored ``PIIScanResult`` names the detector version that
produced it, so a historical verdict stays interpretable.

``1.1.0`` in M5 Phase 9, and the bump was exactly the contract change: the
detector protocol gained ``detect_text`` and a concrete pattern detector exists
where only a stub did. **M5 Phase 13 does not move it** — the two new detectors
populate the categories the locked table already declared, and §4.8 admits no
new ``PIICategory`` value, so the additive line is not spent.

**``1.2.0`` in M5 Phase 14**, and this one is the §4.8 rule being applied where it
is least comfortable. The phase removed ``date_of_birth.numeric`` and added
``date_of_birth.after_patient_name``: a rule leaves and a rule arrives, so neither
half of the rule is satisfied — *minor* is additive, and this is not; *major* is
for required-field changes, enum removals and decision-rule changes, and this is
none of those. What settles it is the test §4.8 actually cares about: a stored
``PIIScanResult`` names the detector version that produced it, so a historical
verdict stays interpretable. A ``1.1.0`` result that carries a date of birth
somebody can no longer reproduce is a historical verdict that has become a lie,
and the honest cost of that is a minor bump.

The minor is therefore *not* spent on Phase 16's NER as §7's roadmap assumed, and
the roadmap's ``1.1.0 → 1.2.0 (Phase 16)`` becomes ``1.2.0 → 1.3.0``. NER is still
additive; it simply earns the next number.
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
suite with the contour-1 gate silently blind.

An earlier revision of this note claimed ``re.IGNORECASE`` "does not cover
Cyrillic" and used it as the reason for the second class. That is **false**, and
Phase 13 measured it: on the worker's Python 3.12, ``re.IGNORECASE`` case-folds
Cyrillic (including ``ё``/``Ё``) through Unicode simple case folding. The
conclusion is unchanged — the folded text still needs a case-agnostic *character
class* — but the reason is that the text is folded, not that the flag is blind,
and the label rules below do compile with ``re.IGNORECASE`` so the canonical
contour's un-folded leaves are readable by the same table.
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


_LONG_DIGIT_RUN = r"(?<!\d)(?!\d{16}(?!\d))\d{12,}(?!\d)"
"""A bare digit run long enough to be a *талон*.

The threshold is the real marker's, not a guess: ``Номер талона`` in
``2b8fdd0d`` is 22 digits. Twelve is where a run stops looking like a card
number — the ``Номер карты: 0000001234`` in the real fixture is 10, and calling
that a ticket is the guess this rule exists not to make.

M5 Phase 13 added the leading ``(?!\\d{16}(?!\\d))``. The table's own docstring
already claimed "the 16-digit ``INSURANCE_NUMBER`` before the same run" owns that
span, and the claim was **false**: every row is an independent ``finditer``, so
table order cannot give one rule priority over another, and the real marker's
``Полис №: 8152510822001720`` was being reported as an insurance number *and* as
a ticket number. The guard makes the docstring true by excluding the more
specific form from the more general one — the same thing ordering does inside
:func:`_tolerant`'s alternatives, which is why it belongs here rather than in the
aggregator. It is not cross-category suppression: a 22-digit ticket is still
claimed, and the 28-digit API key is still misread as one (see the manifest's
notes on ``malicious/synthetic-injection-01.md``).
"""


def _standalone_digits(pattern: str) -> str:
    """Wrap ``pattern`` in boundaries that keep it from matching inside a token.

    Both sides are written here, once, because a rule that guards only the left
    is worse than an unguarded one: it does not fail loudly, it *truncates*.
    ``\\d{9}\\s*\\d{2}`` with a left guard alone claims the first eleven digits
    of the real marker's 22-digit ``Номер талона`` and of the 16-digit
    ``Полис №`` as СНИЛС at 0.95 — values that are neither, and that read as
    more authoritative than the real ticket they were cut from.

    A digit boundary is not enough on either side. In the real corpus every
    clinician certificate is a 32-character hex hash, and hex digits are
    ``[0-9a-f]``, so ``fbf92603229241aa4f2c47c135c61e8e`` contributes
    ``92603229241``: a clean 9+2 run flanked by ``f`` and ``a``. ``\\w`` is what
    says "standalone token" instead of "adjacent digits".
    """
    return rf"(?<![\d\w])(?:{pattern})(?![\d\w])"


_NAME_BOUND_WORDS = (
    r"в|на|и|с|со|к|ко|о|об|от|до|у|из|за|для|по|при|без|над|под|про"
    r"|не|ни|а|но|или|же|ли|бы|да"
)
"""Russian prepositions and particles — a **closed** class, not a stop-word list.

This is the one vocabulary rule the name pattern needs, and it is worth being
explicit about why a closed class is acceptable where a stop-list is not: Russian
prepositions and conjunctions are a finite, grammatically defined set, so
enumerating them terminates. A "common words seen after *пациент*" list would
not terminate — it is a snapshot of the corpus, and the next document adds to
it. The first token of a ФИО is never a preposition, so refusing them costs no
recall and removes an entire class of prose: ``у пациента с повышенным
давлением`` stops at ``с``, ``для пациента не сохранён`` stops at ``не``.

The word boundary matters as much as the class: ``с`` also prefixes real surnames
(``Соколова``) and ``не`` also prefixes real given names, so without ``\\b`` this
would refuse a ФИО. Written into the pattern rather than kept as a Python-side
check, because a check the regex cannot express is a check the next editor
cannot see.
"""

_LABEL_SEP = r"(?:\s*[:：]|\s+[-\u2013\u2014])"
_NAME_LABELS = (
    rf"пациент\w*{_LABEL_SEP}"
    rf"|(?:для|у|от)\s+пациент(?:а|у|ом|е)?"
    rf"|(?:ф\.?\s*и\.?\s*о\.?|больн\w*){_LABEL_SEP}"
    rf"|\*\*\s*пациент\w*\s*\*\*"
)
"""Constructions that introduce a *patient's* name in this document genre.

Used *only* by :data:`_PATTERNS`' label rule — the case-folded contour's name
rule, and the *declined* contour that exists because the leak it has to catch
(§7 gotcha G1) is genitive, mid-sentence and lower-case: ``для пациента
Шадеркина Дениса Сергеевича``. There is no colon to require there, so the
precision has to come from the *construction* — a preposition binding the
genitive, ``для``/``у``/``от`` + ``пациента`` — and from
:data:`_NAME_BOUND_WORDS` refusing a preposition as the name's first token.

The remaining two forms are the counterpart. M5 Phase 9's version of this rule
accepted ``пациент`` with no punctuation at all, and on folded text — where
capitalisation is already gone, so a colon or a pair of ``**`` is the only
punctuation left to read — that claims prose: ``Пациент отказался от приёма.``
came back as the person name ``отказался от приёма``, at 0.7, in the synthetic
appointment fixture. Two signals replace that blank slate, and both are
punctuation the normaliser leaves intact:

- a **colon**, as in ``Пациент: Имя Фамилия``;
- a **bold label**, as in the real marker ``**Пациент**`` on its own line with
  the name on the next — after folding that is ``**пациент** шадеркин денис
  сергеевич``, and the name is the *only* thing after the label, which is what
  makes the missing colon safe. It is a deliberate asymmetry: prose after a
  bold ``**Пациент**`` is possible and would be over-masked, while dropping the
  form would lose a real patient's name from a real document. A missed name is a
  leak; an over-masked clause is a fidelity problem, and the plan's failure mode
  is the leak.

The colon forms for ``фио``/``больн`` are the same three-way choice resolved the
other way — a ФИО in prose is rare enough that a colon is required, and a doctor
or a ward label is not a patient name at all. M5 Phase 13 **removed**
``врач\\w*|доктор\\w*|д-р`` from this list: on the real marker's ``ФИО врача: …``
they made the patient rule claim a clinician as ``PERSON_NAME``, and removing
them is what lets the two categories mean what they say. A clinician's name is
``DOCTOR_NAME`` at :class:`StructuredFieldPIIDetector`.
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
            rf"(?!(?:{_NAME_BOUND_WORDS})\b)"
            rf"({_CYRILLIC_ANY_TOKEN}(?:\s+{_CYRILLIC_ANY_TOKEN}){{2}})"
            rf"(?![{_CYRILLIC_ANY_TOKEN[1:-1]}])",
            re.IGNORECASE,
        ),
        confidence=0.7,
        group=1,
    ),
    _Pattern(
        category=PIICategory.SNILS,
        name="snils.check_summed",
        regex=_tolerant(
            [
                _standalone_digits(r"\d{3}-\d{3}-\d{3}\s*\d{2}"),
                _standalone_digits(r"\d{9}\s*\d{2}"),
            ]
        ),
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
something a reader has to notice. Order matters **within** :func:`_tolerant`'s
alternatives, where a specific form is listed before a general one. It does *not*
matter *between* rows — each row is an independent ``finditer`` — which is why
the two precedence claims this table used to make between rows are now expressed
as guards inside the rows themselves (see the Phase 13 note below).

What is deliberately **not** here, and why. The absence is calibrated against
real text, not against the category list: the table was trimmed to the rules that
do not mis-claim a value the manifest already attributes to a *labelled* field.

M5 Phase 13 ran this table over the real markers for the first time and fixed two
defects it found there. Both were *claims the module already made* and the
implementation did not honour, which is the best kind of bug to find because the
fix is the docstring, not a new idea:

- ``snils.check_summed`` had no digit boundary, so ``\\d{9}\\s*\\d{2}`` matched inside
  a 22-digit ticket number and produced **two** СНИЛС findings from one value
  (``20260307093`` and ``03211960141``), and a third from the 16-digit полис.
  The rule now requires a standalone run.
- ``ticket_number.long_digits`` claimed the 16-digit полис, contradicting the
  ordering note below; see :data:`_LONG_DIGIT_RUN`.

The remaining is calibrated against real text, not against the category list:

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
  ``ООО Ромашка``, so it stayed out of this table — and Phase 13 puts it in
  :data:`_FIELDS` instead, where a ``Врач:`` / ``ФИО врача:`` label is what
  makes the same three-token run safe.
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
labelled detector (:data:`_FIELDS`) is the real fix and supersedes the second row
wherever a label is present.

Where both rows match the *same* span they produce the same value, hence the
same fingerprint, hence one finding after aggregation — which is the dedup rule
doing exactly its job on a real pair rather than a synthetic one. The same holds
between :data:`_FIELDS` and this table: ``ФИО:`` is claimed by both, with the
labelled row's higher confidence surviving aggregation. Where they claim
*different* spans of one entity — the labelled ``Адрес приема:`` cell and the
pattern's ``address.locality`` — both survive, by design: see
``aggregation.py`` for why a different value is not a duplicate, and Phase 12's
redactor for the merge that keeps one placeholder on the page.
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
        return _findings_for_rule(
            text,
            row.regex,
            category=row.category,
            group=row.group,
            confidence=row.confidence,
            source=PIISource.PATTERN,
            detector_name=f"pattern.{row.name}",
            fingerprint=self.fingerprint,
        )


def _findings_for_rule(
    text: str,
    regex: re.Pattern[str],
    *,
    category: PIICategory,
    group: int,
    confidence: float,
    source: PIISource,
    detector_name: str,
    fingerprint: Callable[[str], str],
) -> list[PIIFinding]:
    """Turn every match of ``regex`` in ``text`` into an already-masked finding.

    The single place a detector builds a :class:`~app.pii.models.PIIFinding`, so
    the three detectors cannot drift on the fields Phase 1 makes mandatory: a
    finding that reached a caller without a ``masked_value`` or a keyed
    ``value_fingerprint`` would be the raw value with extra steps. ``masking.py``
    is the other half of that argument — it is the only function allowed to
    build a masked value — and this is the only caller allowed to build either.

    Args:
        text: The string being scanned. Offsets index *this* string exactly as
            passed, which is why no detector may apply them to the original
            markdown (see this module's offsets caveat).
        regex: The compiled rule. Its ``group`` is the value-bearing group.
        category: The category every match of this rule belongs to.
        group: Capture group holding the *value*; ``0`` means the whole match.
        confidence: Rule confidence, stamped on the finding and used by
            aggregation to pick the winner among duplicate values.
        source: Which mechanism found it (``PIISource``).
        detector_name: Dotted rule name, e.g. ``pattern.snils.check_summed``.
        fingerprint: The owning detector's :meth:`PIIDetectorBase.fingerprint`,
            passed in so the finding is built with a bound method rather than a
            detector reference this module would have to keep alive.

    Returns:
        One finding per match whose value group is not blank. A rule that matches
        only decoration (``| :--- | :--- |`` under a label row) contributes
        nothing rather than a finding with an empty value — which reads in an
        artifact as "found, but nothing to redact".
    """
    found: list[PIIFinding] = []
    for match in regex.finditer(text):
        value = match.group(group)
        if not value or not value.strip():
            continue
        start, end = match.span(group)
        found.append(
            PIIFinding(
                category=category,
                value=value,
                masked_value=mask_pii_value(category, value),
                value_fingerprint=fingerprint(value),
                confidence=confidence,
                source=source,
                detector=detector_name,
                detector_version=DETECTOR_VERSION,
                start=start,
                end=end,
            )
        )
    return found


# --- structured field rules (M5 Phase 13) -------------------------------------

_FIELD_GAP = r"[\s:*_~>|#\-–—]*[:：][\s|*]*"
"""Markdown decoration, a **mandatory** colon, then the cell gap: label to value.

The colon is the precision lever, and it is not cosmetic. Every shape the real
marker writes puts a colon in the gap — ``ФИО:``, ``| полис №: |``,
``**пациент:**`` — so requiring one costs no recall on the data this detector
exists for, and it buys the thing that matters: a label can no longer be found
where it is merely a *prefix* of a phrase. ``фио врача:`` is the case in point.
Without the requirement, the label ``фио`` plus optional decoration would reach
across `` врача:`` and claim a clinician as the patient; with it, the rule stops
at ``фио`` and :class:`StructuredFieldPIIDetector`'s doctor row owns the value.

Markdown decoration is kept because ``raw_text`` keeps emphasis markers: the real
text is ``**пациент:** смирнова ольга ивановна``, not ``пациент: …`` (the same
reason as :data:`_MD_DECOR`).
"""

_NO_GAP = r""
"""The gap for a rule whose prefix is already self-contained.

Only the two ``*.shape`` rows pass it. Their prefix is a *delimiter*, not a
label — a parenthesised demographic, or ``Пол/возр.: М / `` — so the value
starts where that prefix ends, and demanding a second colon would make the rule
unsatisfiable. The mandatory colon therefore stays on every word label, which is
where the precision it buys actually is.
"""

_CELL_END = r"(?=\s*\*\*(?:[^*\n]{0,40}:|\s*(?:\||$))|\s*\||$)"
"""Where a free-text field value stops: the next bold label, a cell edge, or end.

Not a nicety — a correctness requirement, and one that comes straight from how
``MarkdownNormalizer`` builds ``raw_text``: it collapses **all** whitespace,
newlines included, so a contour-1 scan sees the whole document as *one line*
(measured: the 53-line real marker normalizes to a single string). A
"to end of line" value pattern would therefore swallow the rest of the document,
and the finding's ``value`` would be a paragraph.

Two terminators carry the dataset: a ``**``-wrapped next label and a ``|`` cell
edge, which is how both the marker's table rows and the synthetic fixtures write
their fields. The first branch is the one that has to be written carefully,
because the shape that fails is the *intersection* of the two — a value that is
itself bold and sits in a cell, ``| **Адрес:** **ул. Примерная, д. 1** |``.
Neither terminator matches there on its own: after the closing ``**`` the text
is `` |``, which is neither a label nor a bare cell edge, so the lazy value class
walks straight past the markers it should have stopped at and returns the cell
plus the pipe plus the following label. Hence the inner group accepts *either* a
label colon *or* an optional space and then a cell edge or end of text — the
last two terms also cover a bold value that ends the document, which is what the
final fixture row looks like.

Known limit, stated rather than hidden: a value that is *plain prose* with no
bold label, no cell edge and no end of document after it runs to the end of the
text. No fixture in the dataset is shaped that way, and the categories exposed
to it (``ADDRESS``, ``ORGANIZATION_NAME``) carry ``RULE_NONE`` masks, so the cost
is a long value in one artifact row rather than a wrong redaction.
"""

_CYR_WORD = r"[А-Яа-яЁё][А-Яа-яЁё\-]*\.?"
_NAME_VALUE = rf"{_CYR_WORD}(?:(?:[ ,]+|(?<=\.)){_CYR_WORD}){{1,3}}"
"""A ФИО: two to four words, where a word may carry one trailing dot.

Two details are the whole trick, and both come from real shapes in the marker:

- the word class may carry **one trailing dot**, because otherwise it consumes
  the initial's letter, leaves the dot behind, and the match stops a character
  early — a value of ``Петров И`` that reads as a truncation, not a name;
- the separator is a space/comma **or the fixed-width ``(?<=\\.)`` lookbehind**,
  because ``КУРМАМБАЕВА Ю.М.`` writes its second initial with no space at all.

Two words are the floor and four the ceiling: the ceiling is what stops
``Силина А.Н. (ВРАЧ …)`` before the parenthesis, and the floor is what keeps a
single-word value from being claimed. The floor does **not** stop
``Врач: врач-терапевт участковый`` — two words, so it matches, and the finding
names a specialty as a doctor. That error is accepted on purpose: it lands in
``DOCTOR_NAME``, the one category that is explicitly not patient PII
(IMPL_ARCH §3.1) and is ``ALLOW`` at every destination, so the cost is one
over-labelled artifact row rather than a wrong redaction or a wrong halt.
"""

_TICKET_VALUE = r"(?<!\d)\d{6,}(?!\d)"
_POLICY_VALUE = r"(?<![\d-])\d{16}(?![\d-])"
_SNILS_VALUE = r"(?<!\d)\d{3}-\d{3}-\d{3}\s*\d{2}"
_DOB_VALUE = r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(?!\d)"
_ISO_DATE_VALUE = r"(?<![\d-])\d{4}-\d{2}-\d{2}(?![\d-])"
"""An ISO ``YYYY-MM-DD`` date — the *shape*, with nothing said about whose date it is.

The shape on its own is not evidence of a birth date, and Phase 14 learned that
the expensive way: this was once a :data:`_PATTERNS` row (``date_of_birth.numeric``,
0.8) that claimed **every** bare ISO date, and once ``DATE_OF_BIRTH`` became
``REDACT`` at ``canonical``+``persistence`` that turned the claim into data loss —
``canonical.document_date`` is a *service* date by construction of
``BaseCanonical``, and the structured-markdown frontmatter is rendered from it, so
every document with an ISO date would have been published with
``document_date: '[DATE_OF_BIRTH]'``. A PII control must not corrupt a field that
was never PII.

So the shape stays and the *claim* moves to two rules that have to earn it, both
in :data:`_FIELDS` and both anchored on evidence the shape does not carry:
``date_of_birth.labelled`` (a label, accepting either spelling) and
``date_of_birth.after_patient_name`` (the patient's ФИО immediately in front of
the date). The digit guards are the ones the removed pattern row used, so a
labelled ISO birth date and the old rule produce the same ``value`` and
aggregation collapses them instead of double-counting.

The recall this trades away is stated rather than hidden: a date of birth in the
**declined** construction (``для пациента Смирнова Ольга Ивановна, 1974-03-12``)
is no longer a finding, because there is no field label to anchor to and the
label is the entire mechanism. Its ФИО still is — :data:`_NAME_LABELS` owns that
construction — and a declined booking is the shape that carries the least
demographic weight. The alternative was keeping a rule that claims every date on
the page, which is the one that corrupts real output.
"""
"""An ISO ``YYYY-MM-DD`` date — the *shape*, with nothing said about whose date it is.

The shape on its own is not evidence of a birth date, and Phase 14 learned that
the expensive way: this was once a :data:`_PATTERNS` row (``date_of_birth.numeric``,
0.8) that claimed **every** bare ISO date, and once ``DATE_OF_BIRTH`` became
``REDACT`` at ``canonical``+``persistence`` that turned the claim into data loss —
``canonical.document_date`` is a *service* date by construction of
``BaseCanonical``, and the structured-markdown frontmatter is rendered from it, so
every document with an ISO date would have been published with
``document_date: '[DATE_OF_BIRTH]'``. A PII control must not corrupt a field that
was never PII.

So the shape stays and the *claim* moves to a rule that has to earn it:
:data:`_FIELDS`' ``date_of_birth.after_patient_name``, which only matches when a
patient's ФИО is right there in front of the date. The digit guards are the ones
the removed pattern row used, kept so the two rules produce the same ``value``
and aggregation collapses them instead of double-counting.

The recall this trades away is stated rather than hidden: a date of birth in the
**declined** construction (``для пациента Смирнова Ольга Ивановна, 1974-03-12``)
is no longer a finding, because there is no field label to anchor to and the
label is the entire mechanism. Its ФИО still is — :data:`_NAME_LABELS` owns that
construction — and a declined booking is the shape that carries the least
demographic weight. The alternative was keeping a rule that claims every date on
the page, which is the one that corrupts real output.
"""
_PHONE_VALUE = r"(?<![\d+])\+\d[\d\s()\-]{9,17}\d"
_EMAIL_VALUE = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
_AGE_VALUE = r"(?<!\d)\d{1,3}(?!\d)\s*(?:лет|года|год|г\.)"
_GENDER_VALUE = r"(?<![А-Яа-яЁё])[МЖFf](?![А-Яа-яЁё])"
_RECORD_VALUE = r"(?<!\d)\d{4,12}(?!\d)"
_PATIENT_ID_VALUE = r"(?<!\d)\d{5,12}(?!\d)"
_LICENSE_VALUE = r"(?<![A-Za-zА-Яа-яЁё0-9])[A-Za-zА-Яа-яЁё0-9/-]{5,}"
_ORG_ID_VALUE = r"(?<!\d)\d{9,15}(?!\d)"
_FREE_TEXT_VALUE = rf"[^|*\n]+?{_CELL_END}"
_ONE_OR_TWO_WORDS = rf"{_CYR_WORD}(?:[ ]+{_CYR_WORD}){{0,1}}"
"""The value shapes, each **bounded**.

A label says *this* is the value; a bounded shape says how long it may be, and
the bounding is what keeps a label from claiming the rest of the document. The
digit shapes are deliberately the same ones :data:`_PATTERNS` uses, so the two
detectors agree on what a value of that category looks like and produce the same
``value`` — which is what makes aggregation's ``(category, fingerprint)`` dedup
collapse them into one finding instead of two.

``_FREE_TEXT_VALUE`` is the one unbounded shape, and it is bounded by
:data:`_CELL_END` instead (address, organization name, nationality).
"""


@dataclass(frozen=True)
class _Field:
    """One labelled-field rule row: what it finds, how it is named, how sure it is.

    ``regex`` is label + gap + value already joined, with the value in group 1 —
    a single scan with a single span, so a field's offsets are its value's
    offsets rather than a diff of two lookups.
    """

    category: PIICategory
    name: str
    regex: re.Pattern[str]
    confidence: float


def _field(
    category: PIICategory,
    name: str,
    label: str,
    value: str,
    confidence: float,
    gap: str = _FIELD_GAP,
) -> _Field:
    """Compile one ``label`` + ``gap`` + ``value`` row, case-insensitively.

    ``gap`` is :data:`_FIELD_GAP` — the mandatory colon — for every row whose
    label is a word. The two shape rows pass :data:`_NO_GAP` instead, because a
    shape's prefix is a delimiter (``(``, ``Пол/возр.: М / ``) and it has already
    said where the value starts; demanding a second colon there would make the
    rule unsatisfiable. Keeping the colon *per row* rather than global is what
    lets the precision lever stay on the labelled rows without disabling it.

    ``re.IGNORECASE`` is what lets one table serve both contours: contour 1 scans
    the case-folded ``raw_text`` and contour 2 (Phase 14's canonical guard) scans
    un-folded payload leaves, so a table pinned to one case would be blind on
    exactly one of them.

    The two-character guard in the compiled form — *not* whitespace, *not* an
    opening bracket — is Phase 13's idempotence check, and it is here rather
    than in each value shape because it is a property of *every* row: a value
    neither starts with whitespace (the gap already ate it) nor with a bracket,
    and a bracket is exactly what :func:`~app.pii.masking.placeholder_for`
    writes. Without it the redaction output feeds straight back into the gate —
    the second pipeline pass sees ``**Адрес:** [address]``, and
    ``address.labelled`` reports the placeholder as a fresh address, which is
    the one thing Phase 12's second-pass-is-a-no-op property exists to prevent.

    Whitespace belongs in that guard for a reason that looks pedantic until it
    bites: the guard is only as strong as its least popular branch, and the
    gap's own trailing class is greedy *and backtrackable*. With a bare
    bracket guard the engine still finds a match — it hands the leading space to
    the value class and starts the value at the space rather than the bracket,
    which :data:`_FREE_TEXT_VALUE` allows. Both characters have to be refused at
    once, or the backtracking finds exactly the gap the guard was written to
    close.
    """
    return _Field(
        category=category,
        name=name,
        regex=re.compile(
            rf"(?<![\w-])(?:{label}){gap}(?![\s\[])({value})",
            re.IGNORECASE,
        ),
        confidence=confidence,
    )


_DEMOGRAPHIC_LABEL = r"пол\s*/\s*возр(?:аст)?\.?"
"""``Пол/возр.:`` — the laboratory marker's combined sex-and-age cell (real
``fbbcb675``). It is a label *and* a container: the sex and the date of birth sit
inside it, which is why three rows carry this prefix instead of a plain
``пол:``/``дата рождения:``.
"""

_DEMOGRAPHIC_PREFIX = _DEMOGRAPHIC_LABEL + _FIELD_GAP
"""``Пол/возр.:`` through its colon and cell gap — the start of that cell's value.

Named once because three rows need it and they must not drift: the sex, the
date of birth and the age are three readings of one cell, and a change to the
cell's spelling is a change to all three or to none.
"""

_PATIENT_FIELD_LABEL = r"ф\.\s*и\.\s*о\.|фамилия[,\s]+имя|пациент\w*|больн\w*|фио"
"""Labels that introduce **the patient's** ФИО as a field value, colon required.

Named once for the same reason as :data:`_DEMOGRAPHIC_PREFIX`, and for a reason
that has since grown: two rows need it — ``person_name.labelled``, which claims
the ФИО itself, and ``date_of_birth.after_patient_name``, which claims the ISO
date that follows it. Those two are one reading of one cell, and a ФИО whose
date of birth is not found is a patient left half-identified in the output.

The label carries a colon, unlike :data:`_NAME_LABELS`: this table reads
*fields*, and a field has a label with a colon. The declined-construction forms
(``для пациента``, no colon) are deliberately not here — they belong to
:data:`_PATTERNS`, which is the case-folded contour and scans whole prose.
"""


_FIELDS: tuple[_Field, ...] = (
    _field(
        PIICategory.DOCTOR_NAME,
        "doctor_name.labelled",
        r"ф\.\s*и\.\s*о\.\s*(?:врача|доктора)|фио\s+врача|фамилия\s+врача"
        r"|(?<!специальность\s)(?:врач|доктор|д-р)\w*|лечащий\s+врач",
        _NAME_VALUE,
        0.95,
    ),
    _field(
        PIICategory.PERSON_NAME,
        "person_name.labelled",
        _PATIENT_FIELD_LABEL,
        _NAME_VALUE,
        0.95,
    ),
    _field(
        PIICategory.DATE_OF_BIRTH,
        "date_of_birth.after_patient_name",
        rf"(?:{_PATIENT_FIELD_LABEL}){_FIELD_GAP}{_NAME_VALUE},\s*",
        _ISO_DATE_VALUE,
        0.85,
        gap=_NO_GAP,
    ),
    _field(
        PIICategory.DATE_OF_BIRTH,
        "date_of_birth.labelled",
        r"дата\s+рождения|д\.\s*р\.|рождени\w*",
        rf"(?:{_DOB_VALUE}|{_ISO_DATE_VALUE})",
        0.95,
    ),
    _field(
        PIICategory.DATE_OF_BIRTH,
        "date_of_birth.dr_abbrev",
        r"д\.\s*р\.[\s*]*",
        rf"(?:{_DOB_VALUE}|{_ISO_DATE_VALUE})",
        0.9,
        gap=_NO_GAP,
    ),
    _field(
        PIICategory.DATE_OF_BIRTH,
        "date_of_birth.demographic_shape",
        _DEMOGRAPHIC_PREFIX + r"[МЖFf][,\s/]*",
        _DOB_VALUE,
        0.9,
        gap=_NO_GAP,
    ),
    _field(
        PIICategory.AGE,
        "age.labelled",
        r"возраст|возр\.",
        _AGE_VALUE,
        0.85,
    ),
    _field(
        PIICategory.AGE,
        "age.demographic_paren.shape",
        r"\(\s*[МЖFf]?\s*[,\-/]?\s*",
        _AGE_VALUE,
        0.8,
        gap=_NO_GAP,
    ),
    _field(
        PIICategory.GENDER,
        "gender.demographic_label",
        _DEMOGRAPHIC_LABEL,
        _GENDER_VALUE,
        0.85,
    ),
    _field(
        PIICategory.NATIONALITY,
        "nationality.labelled",
        r"гражданство",
        _ONE_OR_TWO_WORDS,
        0.7,
    ),
    _field(
        PIICategory.PHONE,
        "phone.labelled",
        r"номер\s+телефона|телефон|мобильн\w+|тел\.?",
        _PHONE_VALUE,
        0.9,
    ),
    _field(
        PIICategory.EMAIL,
        "email.labelled",
        r"электронная\s+почта|эл\.\s*почта|e-mail|email|почта",
        _EMAIL_VALUE,
        0.95,
    ),
    _field(
        PIICategory.ADDRESS,
        "address.labelled",
        r"адрес(?:\s+(?:при[её]ма|регистрации|рег\.?))*|место\s+жительства",
        _FREE_TEXT_VALUE,
        0.9,
    ),
    _field(
        PIICategory.SNILS,
        "snils.labelled",
        r"снилс|страховой\s+номер",
        _SNILS_VALUE,
        0.95,
    ),
    _field(
        PIICategory.INSURANCE_NUMBER,
        "insurance_number.labelled",
        r"полис(?:а)?(?:\s+омс)?|номер\s+полиса",
        _POLICY_VALUE,
        0.95,
    ),
    _field(
        PIICategory.TICKET_NUMBER,
        "ticket_number.labelled",
        r"номер\s+талона|талон",
        _TICKET_VALUE,
        0.95,
    ),
    _field(
        PIICategory.PATIENT_ID,
        "patient_id.labelled",
        r"идентификатор\s+пациента|id\s*пациента|номер\s+пациента",
        _PATIENT_ID_VALUE,
        0.9,
    ),
    _field(
        PIICategory.MEDICAL_RECORD_NUMBER,
        "medical_record_number.labelled",
        r"номер\s+карты|амбулаторная\s+карта|карта\s+пациента|карта",
        _RECORD_VALUE,
        0.95,
    ),
    _field(
        PIICategory.DOCTOR_LICENSE,
        "doctor_license.labelled",
        r"сертификат(?:а)?|№\s*сертификата",
        _LICENSE_VALUE,
        0.85,
    ),
    _field(
        PIICategory.ORGANIZATION_NAME,
        "organization_name.labelled",
        r"медицинская\s+организация|медучреждение|лечебное\s+учреждение"
        r"|филиал|отделение",
        _FREE_TEXT_VALUE,
        0.6,
    ),
    _field(
        PIICategory.ORGANIZATION_ID,
        "organization_id.labelled",
        r"инн|огрн|код\s+учреждения",
        _ORG_ID_VALUE,
        0.85,
    ),
)
"""The ``StructuredFieldPIIDetector`` rule table, in precedence order.

Every row is a **label** plus a **bounded value**, which is the whole thesis of
this detector: a value behind a known label is labelled data, not a guess. The
real ``2b8fdd0d`` marker carries the taxonomy in exactly this form, and Phase 13
adds the file that reproduces it synthetically
(``tests/fixtures/pii/appointment/synthetic-registration-01.md``).

Order is documentation, not behaviour: each row is an independent
``finditer`` scan, so a row cannot shadow another the way :data:`_PATTERNS`' rows
can. ``DOCTOR_NAME`` is nevertheless listed first, because a reader checking
``фио врача:`` should meet the doctor row before the patient one, and because the
mandatory colon — not the table order — is what actually keeps
``person_name.labelled`` off a clinician.

Why each row's confidence is what it is. A label plus a shape is strong evidence
(``0.9``–``0.95``), which is what makes the labelled row win aggregation's
confidence tie against :data:`_PATTERNS`' unlabelled form of the same value.
``nationality.labelled`` sits at ``0.7`` and ``organization_name.labelled`` at
``0.6`` because their value shapes are the loosest in the table — a nationality
and a clinic name are both "a word" — and a guess about a person's citizenship
should be visibly weaker in the artifact than a parsed СНИЛС.

What is deliberately **not** here, and why:

- ``LAB_ORDER_ID`` and ``ENCOUNTER_ID`` are absent because the two markers
  disagree about what a ``Лаб. номер`` is — a 7-digit run on the real
  ``fbbcb675`` would be a lab order on one document and an encounter on another —
  and a category this table cannot fill with evidence is a category it should
  not claim. The taxonomy keeps them for the NER detector.
- ``DOCTOR_LICENSE`` is included even though it is not patient PII
  (IMPL_ARCH §3.1), for the reason ``ORGANIZATION_*`` is: the categories exist
  so a policy can redact the patient *without* redacting the issuing clinic or
  the signing physician. The real marker's ``Сертификат: 00ED1…`` is the shape.
- ``NATIONAL_ID``/``INN`` as *bare* lengths stays out, exactly as in
  :data:`_PATTERNS`. A label is what turns a digit run into an identity.
- A dotted date of birth inside ``Пол/возр.:`` is reachable
  (``date_of_birth.demographic_shape``), but a *free-prose* ``27.07.1984`` with no
  label and no demographic cell is not. ``PIICategory`` has no bare-date rule and
  this is not one: a service date is not PII, which is why
  ``clean/generic-notice-01.md``'s ``12 июня`` must stay undetected.
"""


class StructuredFieldPIIDetector(PIIDetectorBase):
    """Labelled-field detector (IMPL_ARCH §9) — implemented in M5 Phase 13.

    The strongest signal available without an LLM: a value behind a known label
    (``ФИО:``, ``Дата рождения:``, ``Полис №:``, ``СНИЛС:``, ``Номер талона:``)
    is labelled data, not a guess. The real marker carries almost the whole
    taxonomy in this form, and ``"(М, 39 лет)"`` is why ``AGE``/``GENDER`` are
    PII categories at all (§7) rather than ignored.

    Categories: ``PERSON_NAME``, ``DOCTOR_NAME``, ``DATE_OF_BIRTH``, ``AGE``,
    ``GENDER``, ``NATIONALITY``, ``PHONE``, ``EMAIL``, ``ADDRESS``, ``SNILS``,
    ``INSURANCE_NUMBER``, ``TICKET_NUMBER``, ``PATIENT_ID``,
    ``MEDICAL_RECORD_NUMBER``, ``DOCTOR_LICENSE``, ``ORGANIZATION_NAME``,
    ``ORGANIZATION_ID``.

    ``ORGANIZATION_*``/``DOCTOR_*`` are included on purpose: they are not
    patient PII (IMPL_ARCH §3) and must stay separable so a policy can redact the
    patient without redacting the issuing clinic.

    Runs :data:`_FIELDS` over the text and stamps every hit with the mask and the
    fingerprint it computed itself, because a detector is the only component that
    sees raw text and the only place those two derived values can be built (Phase
    1's field requirements). Two properties carry over from
    :class:`PatternPIIDetector` and are deliberate: **no suppression of
    overlapping hits** (aggregation dedups only on
    ``(category, value_fingerprint)``, and collapsing a patient's name into a
    passport finding would delete one of them) and **every row is used**
    (:meth:`detect_text` iterates the table, not a hand-written dispatch).

    Source: ``PIISource.STRUCTURED_FIELD``.
    """

    def detect(self, document: NormalizedDocument) -> list[PIIFinding]:
        """Scan ``document.raw_text`` — the §7 decision 5 wrapper.

        Same caveat as :meth:`PatternPIIDetector.detect` and for the same
        reasons: ``raw_text`` is case-folded with whitespace collapsed, so a
        ``masked_value`` here is the folded form of the entity and the offsets
        index ``raw_text`` rather than the original markdown.
        """
        return self.detect_text(document.raw_text)

    def detect_text(self, text: str) -> list[PIIFinding]:
        """Return every labelled field in ``text``, in rule order then position order.

        Args:
            text: Any string. Empty input yields ``[]``: an empty document is a
                legitimate input, and a detector that cannot be asked about
                nothing cannot be trusted on what it finds.

        Returns:
            One :class:`~app.pii.models.PIIFinding` per matched field, already
            masked and fingerprinted. Values that duplicate a
            :class:`PatternPIIDetector` finding are left in place — same
            category and same value means same fingerprint, so the aggregator
            collapses them.
        """
        if not text:
            return []
        found: list[PIIFinding] = []
        for row in _FIELDS:
            found.extend(
                _findings_for_rule(
                    text,
                    row.regex,
                    category=row.category,
                    group=1,
                    confidence=row.confidence,
                    source=PIISource.STRUCTURED_FIELD,
                    detector_name=f"structured.{row.name}",
                    fingerprint=self.fingerprint,
                )
            )
        return found


_SECRET_LABELS = (
    r"api[\s_-]?key|api[\s_-]?secret|apikey|secret[\s_-]?key|client[\s_-]?secret"
    r"|access[\s_-]?key|access[\s_-]?token|auth[\s_-]?token|private[\s_-]?key"
    r"|passphrase|credentials"
    r"|секретн\w*\s+ключ|секрет|ключ\s+доступа|ключ\s+api|токен"
    r"|парольн\w*\s+фраз\w*|пароль|passwd|password|уч[её]тные\s+данные|учетные\s+данные"
)
_SECRET_GAP = r"[\s:*_~>|#\-–—]*[:=][\s|*]*"
_SECRET_VALUE = (
    r"(?=[^\s|*\"'`,;:{}\[\]<>]{8,}[^\s|*\"'`,;:{}\[\]<>]*[A-Za-zА-Яа-яЁё])"
    r"[^\s|*\"'`,;:{}\[\]<>]{8,}"
)
"""Credential words, the ``key = value`` gap, and a value shape for :data:`_SECRET_RULES`.

The value shape requires eight characters **and** a letter. Both halves are
load-bearing for a detector whose only category is ``BLOCK``: the length floor
keeps ``token: 42`` and ``pin: 1234`` out, and the letter requirement keeps a
bare number — an order id, a room number, a phone fragment — from being called a
credential on the strength of the word before it. ``log:`` and ``login=`` are
absent for the same reason a username is not a secret: it is the half of a
credential that is meant to be read.

The separator allows ``=`` as well as ``:`` because that is how the credentials
in the real world are written (``password=…``, ``api_key: …``), and it stops at
a trailing ``.`` or ``,`` so prose punctuation is not swallowed into the value.
"""


@dataclass(frozen=True)
class _Secret:
    """One credential rule row. ``SECRET`` is the only category, so there is no
    category column — a second one would be an invitation to claim something else.
    """

    name: str
    regex: re.Pattern[str]
    confidence: float
    group: int = 0
    """Capture group holding the value; ``0`` means the whole match.

    The prefixed forms are the value. The labelled form's match is wider than its
    value by construction — the word ``api_key`` is the evidence, not the secret —
    so it takes group 1, and a ``masked_value`` of ``api_key: sk-live-…`` would be
    a fabricated credential.
    """


_SECRET_RULES: tuple[_Secret, ...] = (
    _Secret(
        name="private_key_block",
        regex=re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
        confidence=0.95,
    ),
    _Secret(
        name="connection_string",
        regex=re.compile(
            r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@/]+:[^\s@/]+@"
        ),
        confidence=0.9,
    ),
    _Secret(
        name="aws_access_key_id",
        regex=re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        confidence=0.95,
    ),
    _Secret(
        name="github_token",
        regex=re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        confidence=0.95,
    ),
    _Secret(
        name="slack_token",
        regex=re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
        confidence=0.95,
    ),
    _Secret(
        name="google_api_key",
        regex=re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
        confidence=0.95,
    ),
    _Secret(
        name="jwt",
        regex=re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"),
        confidence=0.9,
    ),
    _Secret(
        name="bearer_token",
        regex=re.compile(r"(?<![A-Za-z])[Bb]earer\s+[A-Za-z0-9._~+/=-]{16,}"),
        confidence=0.85,
    ),
    _Secret(
        name="vendor_key",
        regex=re.compile(r"\bsk-(?:live|test)-[A-Za-z0-9]{16,}\b"),
        confidence=0.9,
    ),
    _Secret(
        name="labelled_credential",
        regex=re.compile(
            rf"(?<![\w-])(?:{_SECRET_LABELS}){_SECRET_GAP}({_SECRET_VALUE})",
            re.IGNORECASE,
        ),
        confidence=0.8,
        group=1,
    ),
)
"""The ``SecretPIIDetector`` rule table, in precedence order.

The most self-contained table in the module, and the one with the least room for
error: ``SECRET`` is the **only** category the default policy ``BLOCK``s (plan
§4.4), so every row here is a control that can stop a document, and a false
positive here stops a document that was fine. The asymmetry is priced the other
way from :class:`PatternPIIDetector`'s name rule, and deliberately so: recall
means "a credential in an uploaded document reaches the extraction prompt", which
is a security incident (IMPL_ARCH §2), while precision means "a legitimate
document is halted for a human to clear", which is an inconvenience.

Two families, and the split is the design:

- **Prefixed formats** (``vendor_key``, ``aws_access_key_id``, ``github_token``,
  ``private_key_block``, ``connection_string``, ``jwt``, ``bearer_token``) need
  no label because the format *is* the evidence. They are high-confidence by
  construction and cannot be reached by ordinary prose.
- **The one labelled row** (``labelled_credential``) is the fallback for
  credentials with no recognizable format — a corporate password manager's
  ``password=…`` — and it is deliberately the *lowest* confidence in the table.
  It is also the only row that can be made to misfire, which is why
  :data:`_SECRET_LABELS` carries a letter requirement and no usernames.

Overlap between the two families is the point, not a bug: ``sk-live-…`` behind an
``api_key:`` label is found by both, produces the same value, and so produces
one finding after aggregation's ``(category, value_fingerprint)`` dedup.

What is deliberately **not** here: entropy heuristics, ``BEGIN OPENSSH PRIVATE
KEY``-adjacent public keys, and any rule over *masked* values. Each was
considered and rejected — an entropy threshold is a false-positive machine
against clinical prose, and a credential is a *kind*, not a statistical property.
A secret with no recognizable format and no labelling word is not detectable
without a dictionary, and this table is not a dictionary.
"""


class SecretPIIDetector(PIIDetectorBase):
    """Credential/secret detector (IMPL_ARCH §13) — implemented in M5 Phase 13.

    Categories: ``SECRET`` only — API keys, passwords, private keys, connection
    strings, bearer tokens. This is the *only* category the default policy
    ``BLOCK``s (plan §4.4), because a secret in an uploaded document is a
    security incident, not expected medical identity (IMPL_ARCH §2: PII presence
    alone never blocks).

    Kept as its own detector, not a pattern rule inside
    :class:`PatternPIIDetector`, so that "block on secret" is a separable,
    independently testable control and so a false positive in medical pattern
    matching can never block a document. That separation is why
    :data:`_SECRET_RULES` is calibrated to *recall* and :data:`_PATTERNS` to
    precision: they are not allowed to be the same detector, so they must not
    have the same error profile.

    Source: ``PIISource.PATTERN``. Detection must never be the sole control
    for a ``BLOCK``: the gate fails closed via ``PIIDecisionError`` if the
    detector cannot run at all.
    """

    def detect(self, document: NormalizedDocument) -> list[PIIFinding]:
        """Scan ``document.raw_text`` — the §7 decision 5 wrapper."""
        return self.detect_text(document.raw_text)

    def detect_text(self, text: str) -> list[PIIFinding]:
        """Return every credential in ``text``, in rule order then position order.

        Args:
            text: Any string. Empty input yields ``[]`` for the same reason every
                detector here does: nothing to find is a finding-shaped answer,
                not an error.

        Returns:
            One :class:`~app.pii.models.PIIFinding` per matched credential,
            already masked and fingerprinted. ``mask_pii_value`` gives ``SECRET``
            a fixed mask, so no row here can emit any part of the value.
        """
        if not text:
            return []
        found: list[PIIFinding] = []
        for row in _SECRET_RULES:
            found.extend(
                _findings_for_rule(
                    text,
                    row.regex,
                    category=PIICategory.SECRET,
                    group=row.group,
                    confidence=row.confidence,
                    source=PIISource.PATTERN,
                    detector_name=f"secret.{row.name}",
                    fingerprint=self.fingerprint,
                )
            )
        return found


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


__all__ = [
    "DETECTOR_VERSION",
    "PII_FINGERPRINT_SECRET_ENV",
    "CompositePIIDetector",
    "PatternPIIDetector",
    "PIIDetector",
    "PIIDetectorBase",
    "SecretPIIDetector",
    "StructuredFieldPIIDetector",
    "build_detector_chain",
]
