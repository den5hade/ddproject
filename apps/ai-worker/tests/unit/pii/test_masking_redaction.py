"""Tests for PII masking, fingerprinting and the redaction contract (M4 Phase 4).

Unlike Phases 1–3 this phase implements pure functions, so the tests are
behavioral as well as contractual. The two that carry the security weight:

- a **leak test** that walks every category × a set of adversarial values and
  asserts the mask reveals no more than the locked rule allows (no 3-character
  run of the original survives, except the 4-digit phone tail);
- a **brute-force test** showing the fingerprint is not a plain digest and does
  not transfer across secrets, which is the property that stops a leaked
  fingerprint column from re-identifying a СНИЛС.
"""

import hashlib
import sys
import unicodedata

import pytest
from app.pii import (
    FINGERPRINT_PREFIX,
    FIXED_MASKS,
    MASK_RULES,
    InvalidPIIInputError,
    PIICategory,
    PIIFinding,
    PIIRedactor,
    PIISource,
    PlaceholderRedactor,
    RedactorBase,
    hash_pii_value,
    mask_pii_value,
    placeholder_for,
)

_SECRET = "unit-test-secret-not-a-real-one"

# Values chosen to stress every branch: empty, single char, at/below the
# keep-length thresholds, separators, mixed case, and the real leaked strings.
_SAMPLE_VALUES = (
    "",
    " ",
    "   \t\n ",
    "A",
    "ab",
    "39",
    "М",
    "Иванов",
    "  иванов  ",
    "ИВАНОВ",
    "Иванов Иван Иванович",
    "Шадеркин Денис Сергеевич",
    "+79991234567",
    "+7 (999) 123-45-67",
    "89991234567",
    "12345",
    "1234",
    "123",
    "ivanov@example.com",
    "ivanov@",
    "@example.com",
    "no-at-sign",
    "27.07.1984",
    "123-067-082 21",
    "8152510822001720",
    "45 12 345678",
    "770708389623",
    "2026030709303211960141",
    "Москва, ул. Тверская, д. 1",
    "ООО Клиника Здоровье",
    "AKIAIOSFODNN7EXAMPLE",
    "Ångström Straße",
    "﻿Шадеркин",
)

# Contiguous characters a rule may reveal, keyed by rule name. Derived from the
# locked table so a rule change cannot silently widen a mask. ``None`` marks a
# rule the generic walk cannot express and that is pinned exactly instead.
_MAX_REVEAL_BY_RULE = {
    "none": None,  # not patient PII: exempt by decision (IMPL_ARCH §3)
    "fixed": None,  # constant output: cannot depend on the input at all
    "token": 1,
    "keep2": 2,
    "email": None,  # the TLD is revealed by design: pinned exactly instead
    "phone": 4,
}

# Rules the generic run check skips, and the exact-output test that pins each.
# An exemption without a pinning test is a hole in the suite, so one is required.
_PINNED_BY = {
    "none": None,  # covered by test_organization_categories_pass_through_unchanged
    "fixed": "test_fixed_masks_ignore_the_value_entirely",
    "email": "test_email_mask_keeps_the_tld_but_masks_the_first_domain_label",
}

_PASSTHROUGH = {PIICategory.ORGANIZATION_NAME, PIICategory.ORGANIZATION_ID}


def _rule(category: PIICategory) -> str:
    return MASK_RULES[category]


def _digits(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def _identifying_runs(token: str) -> list[str]:
    """Split a token into maximal alphanumeric runs.

    The leak check looks at these rather than at raw characters, because
    punctuation is format, not identity: a ``**.**.****`` date-of-birth mask is
    *supposed* to reveal the dots, and a pass/fail that turned on them would be
    testing typography instead of disclosure.
    """
    runs: list[str] = []
    current = ""
    for char in token:
        if char.isalnum():
            current += char
        elif current:
            runs.append(current)
            current = ""
    if current:
        runs.append(current)
    return runs


# --- mask table completeness ------------------------------------------------


def test_every_category_has_a_mask_rule():
    """The Phase 4 acceptance criterion, as an executable statement."""
    assert set(MASK_RULES) == set(PIICategory)


def test_every_mask_rule_is_implemented():
    assert set(MASK_RULES.values()) <= set(_MAX_REVEAL_BY_RULE)


def test_fixed_masks_only_back_fixed_rules():
    for category in FIXED_MASKS:
        assert _rule(category) == "fixed", f"{category.value} has a fixed mask but no fixed rule"


def test_mask_table_matches_the_locked_plan():
    """Spot-check the plan §4.5 table, copied verbatim."""
    assert FIXED_MASKS[PIICategory.SECRET] == "****"
    assert FIXED_MASKS[PIICategory.DATE_OF_BIRTH] == "**.**.****"
    assert FIXED_MASKS[PIICategory.SNILS] == "***-***-*** **"
    assert FIXED_MASKS[PIICategory.INSURANCE_NUMBER] == "*" * 18
    assert FIXED_MASKS[PIICategory.PASSPORT] == "**** ******"
    assert FIXED_MASKS[PIICategory.NATIONAL_ID] == "*" * 11
    assert FIXED_MASKS[PIICategory.INN] == "*" * 11
    assert FIXED_MASKS[PIICategory.ADDRESS] == "г. *******, ул. *******, д. **"
    assert FIXED_MASKS[PIICategory.AGE] == "**"
    assert FIXED_MASKS[PIICategory.GENDER] == "**"
    assert _rule(PIICategory.PERSON_NAME) == "token"
    assert _rule(PIICategory.DOCTOR_NAME) == "token"
    assert _rule(PIICategory.ORGANIZATION_NAME) == "none"
    assert _rule(PIICategory.ORGANIZATION_ID) == "none"


# --- masking behavior -------------------------------------------------------


def test_name_mask_keeps_one_character_per_token():
    assert (
        mask_pii_value(PIICategory.PERSON_NAME, "Шадеркин Денис Сергеевич")
        == "Ш******* Д**** С********"
    )
    assert mask_pii_value(PIICategory.PERSON_NAME, "Иванов") == "И*****"
    assert mask_pii_value(PIICategory.DOCTOR_NAME, "Иванов Иван Иванович") == "И***** И*** И*******"


def test_phone_mask_keeps_country_prefix_and_last_four():
    """Reproduces plan §4.5's ``+7******4567`` exactly."""
    assert mask_pii_value(PIICategory.PHONE, "+79991234567") == "+7******4567"


def test_phone_mask_reveals_the_same_digits_across_separator_variants():
    """The visible digits must be the country digit plus the last four, wherever the separators are.

    Comparing the revealed digits rather than the exact mask is the point: a
    separator inside the tail must not shift which digits are visible, or the
    same number would redact differently depending on how OCR spaced it.
    """
    compact = mask_pii_value(PIICategory.PHONE, "+79991234567")
    spaced = mask_pii_value(PIICategory.PHONE, "+7 (999) 123-45-67")
    assert _digits(spaced) == _digits(compact) == "74567"
    assert spaced.startswith("+7")
    assert "+7" not in spaced[2:]  # the prefix is revealed exactly once


def test_phone_mask_hides_everything_when_too_short_to_show_a_tail():
    assert mask_pii_value(PIICategory.PHONE, "1234") == "****"
    assert mask_pii_value(PIICategory.PHONE, "123") == "***"


def test_email_mask_keeps_the_tld_but_masks_the_first_domain_label():
    assert mask_pii_value(PIICategory.EMAIL, "ivanov@example.com") == "i*****@e******.com"
    assert mask_pii_value(PIICategory.EMAIL, "ivanov@mail.example.ru") == "i*****@m***.example.ru"


def test_email_mask_degrades_safely_without_an_at_sign():
    assert "@" not in mask_pii_value(PIICategory.EMAIL, "no-at-sign")


def test_fixed_masks_ignore_the_value_entirely():
    """Same output for every value — the strongest anti-leak property there is."""
    for category in FIXED_MASKS:
        masks = {mask_pii_value(category, value) for value in _SAMPLE_VALUES}
        assert masks == {FIXED_MASKS[category]}, f"{category.value} varies with the value"


def test_keep_prefix_masks_short_values_entirely():
    """A 2-character value must not survive a "keep 2" rule verbatim."""
    assert mask_pii_value(PIICategory.TICKET_NUMBER, "ab") == "**"
    assert mask_pii_value(PIICategory.MEDICAL_RECORD_NUMBER, "MRN-000123") == "MR********"


def test_single_character_values_are_fully_masked():
    for category in PIICategory:
        if category in _PASSTHROUGH:
            continue  # a one-character organization name is not patient PII
        assert mask_pii_value(category, "A") != "A"


def test_organization_categories_pass_through_unchanged():
    """A clinic's name is not a patient identifier (IMPL_ARCH §3)."""
    for category in _PASSTHROUGH:
        assert _rule(category) == "none"
        assert mask_pii_value(category, "ООО Клиника Здоровье") == "ООО Клиника Здоровье"


def test_masking_never_raises_across_the_whole_matrix():
    for category in PIICategory:
        for value in _SAMPLE_VALUES:
            assert isinstance(mask_pii_value(category, value), str)


def test_mask_output_is_never_empty():
    """An empty ``masked_value`` in an artifact reads as "nothing found"."""
    for category in PIICategory:
        for value in _SAMPLE_VALUES:
            if category not in _PASSTHROUGH or value:
                assert mask_pii_value(category, value) != ""


# --- the leak test ----------------------------------------------------------


def test_mask_never_reveals_more_than_the_rule_allows():
    """No run of ``max_reveal + 1`` identifying characters may survive the mask.

    Walked per token, over alphanumeric runs only, because punctuation and the
    token separators are format rather than identity (see
    :func:`_identifying_runs`). ``fixed`` rules are exempt because a constant
    output cannot depend on its input — a match there is a coincidental letter
    in format text, such as the ``д.`` of an address mask — and they are pinned
    by exact output instead.
    """
    for category in PIICategory:
        limit = _MAX_REVEAL_BY_RULE[_rule(category)]
        if limit is None:
            continue
        run = limit + 1
        for value in _SAMPLE_VALUES:
            mask = mask_pii_value(category, value)
            for token in value.split():
                for identifying in _identifying_runs(token):
                    for start in range(len(identifying) - run + 1):
                        fragment = identifying[start : start + run]
                        if fragment in mask:
                            pytest.fail(
                                f"{category.value} leaked {fragment!r} from {value!r} as "
                                f"{mask!r} (rule {_rule(category)!r} allows {limit})"
                            )


def test_every_generic_walk_exemption_is_pinned_exactly():
    """An exemption must not become a hole: each one is pinned by a named test."""
    module = sys.modules[__name__]
    for rule, pinning_test in _PINNED_BY.items():
        assert _MAX_REVEAL_BY_RULE[rule] is None
        if pinning_test is not None:
            assert hasattr(module, pinning_test), f"{rule} is exempt but {pinning_test} is gone"
    assert {c for c in PIICategory if _rule(c) == "none"} == _PASSTHROUGH
    assert set(_PINNED_BY) == {r for r, v in _MAX_REVEAL_BY_RULE.items() if v is None}


def test_mask_never_equals_the_value_for_patient_categories():
    for category in PIICategory:
        if category in _PASSTHROUGH:
            continue
        for value in _SAMPLE_VALUES:
            assert mask_pii_value(category, value) != value


def test_masked_value_carries_no_raw_text_end_to_end():
    """The combination used on a real finding, as a detector would build it."""
    finding = PIIFinding(
        category=PIICategory.PERSON_NAME,
        value="Шадеркин Денис Сергеевич",
        masked_value=mask_pii_value(PIICategory.PERSON_NAME, "Шадеркин Денис Сергеевич"),
        value_fingerprint=hash_pii_value("Шадеркин Денис Сергеевич", secret=_SECRET),
        confidence=0.97,
        source=PIISource.PATTERN,
        detector="pattern.person_name",
        detector_version="1.0.0",
    )
    assert "Шадеркин" not in finding.masked_value
    assert "Шадеркин" not in str(finding.model_dump())
    assert "Шадеркин" not in finding.model_dump_json()


# --- fingerprinting ---------------------------------------------------------


def test_fingerprint_is_deterministic():
    first = hash_pii_value("Шадеркин", secret=_SECRET)
    assert first == hash_pii_value("Шадеркин", secret=_SECRET)


def test_fingerprint_depends_on_the_secret():
    """The property that makes a leaked column useless without the secret."""
    assert hash_pii_value("123-067-082 21", secret="alpha") != hash_pii_value(
        "123-067-082 21", secret="beta"
    )


def test_fingerprint_is_not_a_plain_digest():
    """A plain sha256 would be the value wearing a disguise (plan §0)."""
    value = "8152510822001720"
    fingerprint = hash_pii_value(value, secret=_SECRET)
    plain = hashlib.sha256(value.encode("utf-8")).hexdigest()
    assert plain not in fingerprint
    assert fingerprint != plain
    assert fingerprint.startswith(FINGERPRINT_PREFIX)
    assert fingerprint.removeprefix(FINGERPRINT_PREFIX) != plain


def test_fingerprint_is_hex_and_carries_no_value():
    fingerprint = hash_pii_value("Шадеркин Денис", secret=_SECRET)
    digest = fingerprint.removeprefix(FINGERPRINT_PREFIX)
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")
    assert "Шадеркин" not in fingerprint


def test_fingerprint_normalizes_case_and_whitespace():
    """Required for Phase 3 dedup across OCR variants."""
    canonical = hash_pii_value("Иванов", secret=_SECRET)
    for variant in ("  иванов ", "ИВАНОВ", "Иванов\n", "\tиванов  "):
        assert hash_pii_value(variant, secret=_SECRET) == canonical


def test_fingerprint_normalizes_unicode_forms():
    composed = "Ångström"
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    assert hash_pii_value(composed, secret=_SECRET) == hash_pii_value(decomposed, secret=_SECRET)


def test_fingerprint_still_distinguishes_different_values():
    base = hash_pii_value("Иванов", secret=_SECRET)
    assert hash_pii_value("Ивановa", secret=_SECRET) != base
    assert hash_pii_value("Иванов Иван", secret=_SECRET) != base


def test_fingerprint_of_empty_value_is_well_formed():
    """Must not collide with the "failed to fingerprint" empty-string escape."""
    fingerprint = hash_pii_value("", secret=_SECRET)
    assert fingerprint.startswith(FINGERPRINT_PREFIX)
    assert fingerprint == hash_pii_value("   \n ", secret=_SECRET)
    assert fingerprint != ""


def test_secret_is_keyword_only_and_required():
    with pytest.raises(TypeError):
        hash_pii_value("value", _SECRET)  # type: ignore[misc]


def test_empty_secret_is_rejected():
    with pytest.raises(InvalidPIIInputError) as excinfo:
        hash_pii_value("value", secret="")
    assert "secret" in str(excinfo.value).lower()


def test_fingerprint_rejects_the_plain_digest_of_the_same_input():
    """Guards the invariant directly: two different digests of one value."""
    value = "123-067-082 21"
    salted = hash_pii_value(value, secret=_SECRET).removeprefix(FINGERPRINT_PREFIX)
    unsalted = hashlib.sha256(unicodedata.normalize("NFC", value).casefold().encode()).hexdigest()
    assert salted != unsalted


# --- redaction contract -----------------------------------------------------


def test_redactor_is_a_protocol_with_the_locked_signature():
    import inspect

    assert getattr(PIIRedactor, "_is_protocol", False) is True
    assert not inspect.iscoroutinefunction(PIIRedactor.redact)
    parameters = list(inspect.signature(PIIRedactor.redact).parameters)
    assert parameters == ["self", "markdown", "findings"]


def test_redactor_stubs_raise_not_implemented():
    for stub in (RedactorBase, PlaceholderRedactor):
        with pytest.raises(NotImplementedError) as excinfo:
            stub().redact("markdown", [])
        assert "M5" in str(excinfo.value)


def test_placeholder_token_format():
    assert placeholder_for(PIICategory.PERSON_NAME) == "[PERSON_NAME]"
    assert placeholder_for(PIICategory.MEDICAL_RECORD_NUMBER) == "[MEDICAL_RECORD_NUMBER]"
    assert placeholder_for(PIICategory.SECRET) == "[SECRET]"


def test_placeholder_token_exists_for_every_category():
    for category in PIICategory:
        token = placeholder_for(category)
        assert token == f"[{category.name}]"
        assert token.strip("[]") == category.name


def test_redaction_documentation_locks_the_algorithm():
    import inspect

    from app.pii import redaction

    doc = inspect.getdoc(redaction) or ""
    for required in (
        "right-to-left",
        "overlapping",
        "PIIRedactionError",
        "not mutate",
        "immutable",
        "never rewrites",
    ):
        assert required.lower() in doc.lower(), f"redaction contract must state {required!r}"


# --- import boundary --------------------------------------------------------


def test_phase_four_modules_import_only_stdlib_and_the_pii_package():
    """``masking``/``redaction`` reach nothing outside the package.

    The package-wide guards in ``test_models.py`` already enforce this, but
    asserting it here too means an edit that makes Phase 4 the first place a
    forbidden import appears fails in the file that introduced it.
    """
    from tests.support.pii_imports import PII_PACKAGE_DIR, module_names

    allowed_stdlib = {"hashlib", "hmac", "unicodedata", "typing", "__future__"}
    for name in ("masking.py", "redaction.py"):
        outside = {
            module
            for module in module_names(PII_PACKAGE_DIR / name)
            if not module.startswith("app.pii") and module.split(".")[0] not in allowed_stdlib
        }
        assert outside == set(), f"{name} imports outside the boundary: {outside}"
