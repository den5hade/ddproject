import pytest
from app.domain.account import IdentityKind
from app.domain.identity import Identity, is_email


@pytest.mark.parametrize(
    ("raw", "kind", "canonical"),
    [
        ("user@example.com", IdentityKind.EMAIL, "user@example.com"),
        ("User@Example.COM", IdentityKind.EMAIL, "user@example.com"),
        ("  user@example.com  ", IdentityKind.EMAIL, "user@example.com"),
        ("+15551234567", IdentityKind.PHONE, "+15551234567"),
        ("+12345678", IdentityKind.PHONE, "+12345678"),
        ("+123456789012345", IdentityKind.PHONE, "+123456789012345"),
    ],
)
def test_parse_valid_identities(raw, kind, canonical):
    parsed = Identity.parse(raw)
    assert parsed.kind is kind
    assert parsed.canonical == canonical
    assert Identity.parse(raw) == Identity(kind=kind, canonical=canonical)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not-an-email",
        "12345",
        "89123456789",
        "+0123456789",
        "+",
        "a@b",
        "@example.com",
        "a b@example.com",
        "a@b@c.com",
        "+1234567890123456",
    ],
)
def test_parse_rejects_invalid_identities(raw):
    with pytest.raises(ValueError):
        Identity.parse(raw)


def test_is_email_helper():
    assert is_email("user@example.com") is True
    assert is_email("+15551234567") is False
