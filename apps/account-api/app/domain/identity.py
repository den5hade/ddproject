import re
from dataclasses import dataclass

from app.domain.account import IdentityKind

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


@dataclass(frozen=True)
class Identity:
    kind: IdentityKind
    canonical: str

    @classmethod
    def parse(cls, raw: str) -> "Identity":
        value = raw.strip()
        if EMAIL_PATTERN.fullmatch(value):
            return cls(kind=IdentityKind.EMAIL, canonical=value.lower())
        if PHONE_E164_PATTERN.fullmatch(value):
            return cls(kind=IdentityKind.PHONE, canonical=value)
        raise ValueError(
            "identity must be a valid email address or an E.164 phone number"
        )


def is_email(value: str) -> bool:
    return Identity.parse(value).kind is IdentityKind.EMAIL
