from enum import Enum

"""
Access / audit-domain enums.
"""


class GrantStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AccessReason(str, Enum):
    TREATMENT = "treatment"
    CONSULTATION = "consultation"
    DIAGNOSIS = "diagnosis"
    FOLLOW_UP = "follow_up"


class AuditAction(str, Enum):
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    VIEW_PATIENT = "VIEW_PATIENT"
    VIEW_MEDICAL_RECORD = "VIEW_MEDICAL_RECORD"
    VIEW_DOCUMENT = "VIEW_DOCUMENT"
    DOWNLOAD_DOCUMENT = "DOWNLOAD_DOCUMENT"
    UPLOAD_DOCUMENT = "UPLOAD_DOCUMENT"
    CREATE_ENCOUNTER = "CREATE_ENCOUNTER"
    UPDATE_ENCOUNTER = "UPDATE_ENCOUNTER"
    GRANT_ACCESS = "GRANT_ACCESS"
    REVOKE_ACCESS = "REVOKE_ACCESS"
    VIEW_ANALYTICS = "VIEW_ANALYTICS"


class PatientAccessGrantNotFoundError(Exception):
    """An access grant does not exist for the given patient and id."""


class PatientAccessDeniedError(Exception):
    """The account has no access right to the patient medical data."""