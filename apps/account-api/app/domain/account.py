from enum import Enum

"""
Account / identity-domain enums.
"""


class AccountStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DELETED = "deleted"


class IdentityKind(str, Enum):
    EMAIL = "email"
    PHONE = "phone"


class RoleCode(str, Enum):
    CLIENT = "client"
    SPECIALIST = "specialist"
    ORGANIZATION_ADMIN = "organization_admin"
    SYSTEM_ADMIN = "system_admin"
    SUPPORT = "support"


class PermissionCode(str, Enum):
    MEDICAL_RECORD_READ = "medical_record.read"
    MEDICAL_RECORD_WRITE = "medical_record.write"

    DOCUMENT_READ = "document.read"
    DOCUMENT_UPLOAD = "document.upload"
    DOCUMENT_DOWNLOAD = "document.download"

    ENCOUNTER_READ = "encounter.read"
    ENCOUNTER_CREATE = "encounter.create"
    ENCOUNTER_UPDATE = "encounter.update"

    ANALYTICS_READ = "analytics.read"

    USER_MANAGE = "user.manage"
    ORGANIZATION_MANAGE = "organization.manage"


class RoleNotFoundError(Exception):
    """A role code does not exist in the roles table."""


class PermissionNotFoundError(Exception):
    """A permission code does not exist in the permissions table."""