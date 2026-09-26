"""PII masking and value fingerprinting (M4 Phase 4).

Two pure functions with opposite jobs, both on the in-process path only:

- :func:`mask_pii_value` turns a raw value into a string that is safe to log,
  audit, publish and persist. This is the **only** representation of PII that
  may cross a boundary (``PII GATE/IMPL_ARCH.md`` §6, §19, §22).
- :func:`hash_pii_value` produces the salted fingerprint that lets aggregation
  recognise "the same value seen twice" without ever comparing raw text.

Why the fingerprint is HMAC and not a hash
------------------------------------------

A plain ``sha256`` here would be the value wearing a disguise. The
low-entropy identifiers this gate exists to catch are brute-forceable in
seconds: СНИЛС is 9 digits plus a checksum, полис ОМС is 16 digits, a date of
birth is ~36k candidates, and a Russian phone number is ~10^10 with a known
prefix. An attacker holding a fingerprint column could enumerate the entire
candidate space and re-identify every row. HMAC with a caller-supplied secret
makes the digest useless without that secret, so a leaked fingerprint column
cannot be reversed even by someone who knows the exact value format.

Three rules the callers must honour, all enforced here:

1. **The secret is a required keyword argument.** There is no module constant
   and no default, because a default is a hard-coded secret and a hard-coded
   secret is no secret at all. An empty secret is rejected: HMAC with an empty
   key is an unkeyed digest wearing the same disguise as ``sha256``.
2. **The fingerprint is never logged and never persisted** (plan §7). It rides
   ``PIIFinding.value_fingerprint`` in-process only; ``document_id`` +
   ``category`` + offset is the sanctioned join key if cross-scan correlation is
   ever needed.
3. **Fingerprinting normalizes, masking does not.** These are different
   purposes and must not share a normalizer (see below).

Normalization is for fingerprints, not for masks
------------------------------------------------

:func:`hash_pii_value` NFC-normalizes, case-folds and collapses whitespace
before hashing, because Phase 3 locked aggregation dedup on
``(category, value_fingerprint)``: without normalization ``Иванов`` and
``ИВАНОВ  `` — one name, two OCR variants, the normal case in Marker output —
would fingerprint differently and the dedup would silently never fire.

:func:`mask_pii_value` deliberately does **not** normalize. A mask exists so a
human can recognize an entity in a log line, which means it must reflect the
characters actually present in the document. Normalizing a mask would make it
describe a value the document never contained.

An empty or whitespace-only value still yields a well-formed fingerprint (the
HMAC of the empty string). The "empty fingerprint bypasses dedup" rule in
``aggregation.py`` therefore stays reserved for a detector that genuinely
failed to fingerprint, and is never triggered as a normalization side effect.

The mask table
--------------

``MASK_RULES`` maps every :class:`~app.pii.models.PIICategory` to the rule
that masks it, and is the machine-checkable form of plan §4.5: the Phase 4
acceptance criterion is that no category is missing, so a new category without
a rule is a failing test rather than an unmasked value in production. Rules:

``none``
    Return the value unchanged. Reserved for ``ORGANIZATION_NAME`` /
    ``ORGANIZATION_ID``: a clinic's name is not a patient identifier
    (``PII GATE/IMPL_ARCH.md`` §3), and redacting the issuing organization along
    with the patient is precisely the mistake the medical/practitioner split
    exists to prevent.
``fixed``
    A constant string, independent of the value. Used where revealing even the
    shape narrows identity: a date of birth is one of ~36k dates, so
    ``**.**.****`` keeps the format and nothing else.
``token``
    Per whitespace-separated token, keep the first character and star the
    rest (``Шадеркин Денис Сергеевич`` → ``Ш******* Д***** С********``). The
    token count and lengths leak, which is accepted for name debugging (IMPL_ARCH §6).
``keep2``
    Keep the first two characters, star the remainder — opaque internal
    identifiers, where a year or type prefix is the useful debugging signal.
``email`` / ``phone``
    Structure-aware: per-label first character for the local part and each
    domain label; leading ``+`` plus country digit and the last four digits for
    a phone.
"""

import hashlib
import hmac
import unicodedata

from app.pii.exceptions import InvalidPIIInputError, PIIPolicyError
from app.pii.models import PIICategory

__all__ = [
    "FIXED_MASKS",
    "FINGERPRINT_PREFIX",
    "MASK_RULES",
    "hash_pii_value",
    "mask_pii_value",
]

RULE_NONE = "none"
"""Pass the value through unchanged — non-patient identifiers only."""

RULE_FIXED = "fixed"
"""Constant output, independent of the value."""

RULE_TOKEN = "token"
"""Per whitespace token: first character kept, remainder starred."""

RULE_KEEP_PREFIX = "keep2"
"""Keep the first two characters, star the remainder."""

RULE_EMAIL = "email"
"""Per-label first character for local part and every domain label."""

RULE_PHONE = "phone"
"""Leading ``+`` + country digit and the last four digits."""

FINGERPRINT_PREFIX = "hmac-sha256:"
"""Self-describing prefix on every fingerprint.

A bare hex digest invites being mistaken for — or replaced by — a plain hash,
and the entire point of the invariant is that this is *not* one. The prefix
also makes a leaked plain-hash column greppable.
"""

_PHONE_VISIBLE_TAIL = 4
"""Digits kept from the end of a phone number (plan §4.5: "2–4 characters")."""

_KEEP_PREFIX_LENGTH = 2
"""Characters kept by ``RULE_KEEP_PREFIX`` (plan §4.5: "first 2 chars")."""

_MIN_REVEAL = 1
"""Characters a derived rule may keep; a shorter value is masked completely."""

_EMPTY_MASK = "**"
"""Output for an empty or whitespace-only value under a derived rule."""


def _mask_token(token: str) -> str:
    """Keep the first character of ``token`` and star the rest."""
    if len(token) <= _MIN_REVEAL:
        return "*" * len(token)
    return token[0] + "*" * (len(token) - _MIN_REVEAL)


def _mask_tokens(value: str) -> str:
    """Mask every whitespace-separated token, preserving the token count."""
    return " ".join(_mask_token(token) for token in value.split())


def _mask_keep_prefix(value: str, keep: int) -> str:
    """Keep ``keep`` leading characters; mask entirely if the value is shorter."""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)


def _mask_email(value: str) -> str:
    """Mask an address: ``ivanov@example.com`` → ``i*****@e******.com``.

    The local part and the **first** domain label are masked per label; the
    rest of the domain is kept verbatim. The first label is where the identity
    lives (``ivanov.ru``, ``ivanov`` in ``ivanov.mail.example.com``), while
    everything after it is routing infrastructure that identifies nobody —
    which is also why plan §4.5's ``i****@d****.ru`` shows the TLD intact.

    A value with no ``@`` is not an address, so it is masked as a single opaque
    token rather than trusted to have a sensible structure.
    """
    local, separator, domain = value.partition("@")
    if not separator:
        return _mask_keep_prefix(value, _MIN_REVEAL)
    masked_local = _mask_token(local) if local else _EMPTY_MASK
    first_label, dot, remainder = domain.partition(".")
    masked_domain = _mask_token(first_label) if first_label else _EMPTY_MASK
    if dot:
        masked_domain = f"{masked_domain}.{remainder}"
    return f"{masked_local}@{masked_domain}"


def _mask_phone(value: str) -> str:
    """Keep the leading ``+`` + country digit and the last four digits.

    Everything else — middle digits *and* separators — becomes ``*``, so the
    output is a fixed-ish shape rather than a partially valid phone number that
    could be mistaken for a real one. Derived from the digits actually present,
    so separators and spacing variants (``+7 (999) 123-45-67``) mask
    identically instead of shifting the visible tail.
    """
    digit_indexes = [index for index, char in enumerate(value) if char.isdigit()]
    if len(digit_indexes) <= _PHONE_VISIBLE_TAIL:
        return "*" * len(value)

    keep: set[int] = set()
    if value.startswith("+") and len(value) > 1 and value[1].isdigit():
        keep.add(0)
        keep.add(1)
    keep.update(digit_indexes[-_PHONE_VISIBLE_TAIL:])

    return "".join(char if index in keep else "*" for index, char in enumerate(value))


FIXED_MASKS: dict[PIICategory, str] = {
    PIICategory.SECRET: "****",
    PIICategory.DATE_OF_BIRTH: "**.**.****",
    PIICategory.SNILS: "***-***-*** **",
    PIICategory.INSURANCE_NUMBER: "******************",
    PIICategory.PASSPORT: "**** ******",
    PIICategory.NATIONAL_ID: "***********",
    PIICategory.INN: "***********",
    PIICategory.ADDRESS: "г. *******, ул. *******, д. **",
    PIICategory.AGE: "**",
    PIICategory.GENDER: "**",
    PIICategory.NATIONALITY: "**",
}
"""Constant masks, copied verbatim from plan §4.5 (plus the §7 additions).

Four categories are absent from §4.5's table and are closed here rather than
left to a future reader; the two ``*_ID``-style gaps are the substantive ones:

- ``AGE`` / ``GENDER`` → ``**``, extending §7's explicit "kept … masked to
  ``**``" to its sibling in the same identity group.
- ``NATIONALITY`` → ``**``, same low-risk single-token treatment. §4.5 does not
  name it; a first-character rule would reveal the leading letter of a
  citizenship for no debugging benefit.
- ``DOCTOR_LICENSE`` → ``keep2``. A license number is an opaque identifier, so
  it joins the ``TICKET_NUMBER``/``*_ID`` family rather than being unmasked
  like ``ORGANIZATION_ID``. The distinction is deliberate: an *organization's*
  registration is not patient PII, but a license is held by a named individual.
- ``MEDICAL_RECORD_NUMBER`` → ``keep2``. It does not match §4.5's ``*_ID``
  glob, but it is the identifier that actually leaked in the real document, so
  it must not be the one high-risk identifier with no mask.
"""

MASK_RULES: dict[PIICategory, str] = {
    PIICategory.PERSON_NAME: RULE_TOKEN,
    PIICategory.DATE_OF_BIRTH: RULE_FIXED,
    PIICategory.AGE: RULE_FIXED,
    PIICategory.GENDER: RULE_FIXED,
    PIICategory.NATIONALITY: RULE_FIXED,
    PIICategory.EMAIL: RULE_EMAIL,
    PIICategory.PHONE: RULE_PHONE,
    PIICategory.ADDRESS: RULE_FIXED,
    PIICategory.PASSPORT: RULE_FIXED,
    PIICategory.NATIONAL_ID: RULE_FIXED,
    PIICategory.INSURANCE_NUMBER: RULE_FIXED,
    PIICategory.SNILS: RULE_FIXED,
    PIICategory.INN: RULE_FIXED,
    PIICategory.PATIENT_ID: RULE_KEEP_PREFIX,
    PIICategory.MEDICAL_RECORD_NUMBER: RULE_KEEP_PREFIX,
    PIICategory.LAB_ORDER_ID: RULE_KEEP_PREFIX,
    PIICategory.ENCOUNTER_ID: RULE_KEEP_PREFIX,
    PIICategory.TICKET_NUMBER: RULE_KEEP_PREFIX,
    PIICategory.DOCTOR_NAME: RULE_TOKEN,
    PIICategory.DOCTOR_LICENSE: RULE_KEEP_PREFIX,
    PIICategory.ORGANIZATION_NAME: RULE_NONE,
    PIICategory.ORGANIZATION_ID: RULE_NONE,
    PIICategory.SECRET: RULE_FIXED,
}
"""Every category mapped to its masking rule — plan §4.5 in machine-checkable form."""


def mask_pii_value(category: PIICategory, value: str) -> str:
    """Return the loggable form of ``value`` for ``category``.

    Never raises for a well-formed category and never returns ``value``
    unchanged except for the two ``ORGANIZATION_*`` categories, which are not
    patient PII. Callers on the in-process path use this to fill
    ``PIIFinding.masked_value``; nothing else may build a masked value, so the
    leak surface is one function.

    Args:
        category: The finding's category, which selects the rule.
        value: The raw value. May be empty; a degenerate value still produces a
            recognizable mask rather than an empty string, because an empty
            ``masked_value`` in an artifact reads as "nothing found".

    Returns:
        The masked representation. For ``RULE_NONE`` categories, ``value`` itself.
    """
    rule = MASK_RULES[category]
    if rule == RULE_NONE:
        return value
    if not value.strip():
        return FIXED_MASKS.get(category, _EMPTY_MASK)
    if rule == RULE_FIXED:
        return FIXED_MASKS[category]
    if rule == RULE_TOKEN:
        return _mask_tokens(value)
    if rule == RULE_KEEP_PREFIX:
        return _mask_keep_prefix(value, _KEEP_PREFIX_LENGTH)
    if rule == RULE_EMAIL:
        return _mask_email(value)
    if rule == RULE_PHONE:
        return _mask_phone(value)
    # A rule name that is not implemented must fail loudly: returning the raw
    # value here would be the single worst bug this module could have.
    raise PIIPolicyError(f"No masking rule named {rule!r} for {category.value}.")


def _normalize_for_fingerprint(value: str) -> str:
    """NFC-normalize, case-fold and collapse whitespace.

    Required for aggregation dedup to work across OCR case and spacing variants
    (Phase 3). Applied to fingerprints only — never to masks.
    """
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def hash_pii_value(value: str, *, secret: str) -> str:
    """Return the salted HMAC-SHA256 fingerprint of ``value``.

    Deterministic for a given ``(normalized value, secret)`` pair, and
    unlinkable across secrets. Never reversible without ``secret``, which is
    what makes it safe to keep for correlation while still being useless to an
    attacker who obtains it.

    Args:
        value: The raw value. Normalized before hashing (see
            :func:`_normalize_for_fingerprint`); never logged, never persisted.
        secret: High-entropy secret supplied by the caller. Keyword-only and
            required: there is deliberately no module constant and no default.
            M5 sources it from settings; it must never fall back to a
            hard-coded value.

    Returns:
        ``"hmac-sha256:"`` followed by the lowercase hex digest.

    Raises:
        InvalidPIIInputError: If ``secret`` is empty. HMAC with an empty key is
            an unkeyed digest, which is the exact disguise this function exists
            to avoid.
    """
    if not secret:
        raise InvalidPIIInputError(
            "hash_pii_value requires a non-empty secret; an empty key makes the "
            "fingerprint an unkeyed digest."
        )
    message = _normalize_for_fingerprint(value).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{FINGERPRINT_PREFIX}{digest}"
