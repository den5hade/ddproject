from enum import Enum

"""
Organization / integration-domain enums and legal-number helpers.

Phase 4a (admin onboarding) introduces `OrganizationMembershipRole`,
`organizations.created_by_account_id` and the `organization_memberships.role`
column; a `system_admin` provisions an organization and connects the
representative by email. The organization-scoped role authorizes
`/organizations/me/*` (migration of that check happens in Phase 4b).

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


class OrganizationMembershipRole(str, Enum):
    """Organization-scoped role (Phase 4a, ``organization_memberships.role``).

    Authorization for ``/organizations/me/*`` migrates from the legacy global
    ``RoleCode.ORGANIZATION_ADMIN`` check to this column in Phase 4b; admin
    onboarding never grants a global role.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


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


class OrganizationLicenseNotFoundError(Exception):
    """A license does not exist for the given organization and id."""


class OrganizationLicenseConflictError(Exception):
    """A license with the same license number already exists in the organization."""


class OrganizationApiKeyNotFoundError(Exception):
    """An API key does not exist for the given organization and id."""


class OrganizationMembershipNotFoundError(Exception):
    """A membership does not exist for the given organization and account."""


class OrganizationMembershipConflictError(Exception):
    """The account is already a member (or the organization is not ACTIVE)."""


class OrganizationApiKeyAuthenticationError(Exception):
    """Missing, unknown, revoked or expired API key (Phase 4c auth)."""


class OrganizationInactiveError(Exception):
    """The key's organization is not ACTIVE, so integration access is denied."""


class OrganizationVerificationRejectedError(Exception):
    """The organization's verification was REJECTED; integration is blocked.

    ``Organization.status = ACTIVE`` is necessary but NOT sufficient: the
    locked verification gate requires ``verification_status != REJECTED``
    (PENDING verification never grants unrestricted production access).
    """


class OrganizationApiKeyPermissionDeniedError(Exception):
    """The key does not carry the scope required by the endpoint."""


class InvalidPatientIdentityError(Exception):
    """The integration payload references a patient identity that cannot be resolved.

    The integration API only accepts an email identity (``patient_email``);
    other identity kinds or a missing identity fail with this error (422).
    """


class OrganizationDocumentIdempotencyConflictError(Exception):
    """An idempotency key / external_id maps to a different document (409).

    Raised when the caller resubmits with the same idempotency key or
    ``external_id`` but a payload that differs from the original submission.
    """