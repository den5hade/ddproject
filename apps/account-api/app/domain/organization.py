from enum import Enum

"""
Organization / integration-domain enums and legal-number helpers.

Legal-number helpers implement the official Russian control-digit schemes:

- INN: 10 digits (organizations) or 12 digits (individual entrepreneurs),
  with one or two weighted control digits respectively.
- OGRN: 13 digits; the 13th digit is the first 12 as an integer mod 11,
  mapped mod 10.
"""


class OrganizationVerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class BranchStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class OrganizationLicenseStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    PENDING = "pending"


class OrganizationApiKeyStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class OrganizationApiKeyScope(str, Enum):
    DOCUMENTS_UPLOAD = "organization.documents.upload"
    DOCUMENTS_BULK_UPLOAD = "organization.documents.bulk_upload"
    DOCUMENTS_READ = "organization.documents.read"
    JOBS_READ = "organization.jobs.read"


class BatchStatus(str, Enum):
    ACCEPTED = "accepted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class BatchItemStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class OrganizationDocumentSchemaStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class NotificationType(str, Enum):
    DOCUMENT_RECEIVED = "document_received"
    DOCUMENT_PROCESSED = "document_processed"
    DOCUMENT_PROCESSING_FAILED = "document_processing_failed"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    READ = "read"


class NotificationChannel(str, Enum):
    EMAIL = "email"


_INN_10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN_12_WEIGHTS_FIRST = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN_12_WEIGHTS_SECOND = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def normalize_inn(raw: str | None) -> str | None:
    """Strip surrounding whitespace from a raw INN."""
    if raw is None:
        return None
    return raw.strip()


def inn_checksum_valid(inn: str) -> bool:
    """Validate an INN string against the official control-digit scheme."""
    if not inn.isdigit():
        return False
    digits = [int(ch) for ch in inn]
    if len(digits) == 10:
        control = (
            sum(d * w for d, w in zip(digits[:9], _INN_10_WEIGHTS, strict=True))
            % 11
            % 10
        )
        return control == digits[9]
    if len(digits) == 12:
        first = (
            sum(
                d * w
                for d, w in zip(digits[:10], _INN_12_WEIGHTS_FIRST, strict=True)
            )
            % 11
            % 10
        )
        if first != digits[10]:
            return False
        second = (
            sum(
                d * w
                for d, w in zip(digits[:11], _INN_12_WEIGHTS_SECOND, strict=True)
            )
            % 11
            % 10
        )
        return second == digits[11]
    return False


def normalize_ogrn(raw: str | None) -> str | None:
    """Strip surrounding whitespace from a raw OGRN."""
    if raw is None:
        return None
    return raw.strip()


def ogrn_checksum_valid(ogrn: str) -> bool:
    """Validate an OGRN string against the official control-digit scheme."""
    if len(ogrn) != 13 or not ogrn.isdigit():
        return False
    control = int(ogrn[:12]) % 11 % 10
    return control == int(ogrn[12])


class OrganizationNotFoundError(Exception):
    """An organization does not exist for the given id."""


class OrganizationLegalDataConflictError(Exception):
    """An organization with the same INN or OGRN already exists."""


class OrganizationBranchNotFoundError(Exception):
    """A branch does not exist for the given organization and id."""


class OrganizationBranchConflictError(Exception):
    """A branch with the same code already exists in the organization."""