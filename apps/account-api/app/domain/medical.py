from enum import Enum

"""
Medical-domain enums: persons, organizations, encounters, documents,
processing jobs and extractions.
"""


class Sex(str, Enum):
    MALE = "male"
    FEMALE = "female"
    UNSPECIFIED = "unspecified"


class OrganizationType(str, Enum):
    CLINIC = "clinic"
    HOSPITAL = "hospital"
    PRIVATE_PRACTICE = "private_practice"
    LABORATORY = "laboratory"


class OrganizationStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class MembershipStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    LEFT = "left"


class PatientStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class SpecialistStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class EncounterType(str, Enum):
    CONSULTATION = "consultation"
    FOLLOW_UP = "follow_up"
    PROCEDURE = "procedure"
    ADMISSION = "admission"
    TELEMEDICINE = "telemedicine"
    OTHER = "other"


class EncounterStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class DocumentType(str, Enum):
    LAB_RESULT = "lab_result"
    DOCTOR_REPORT = "doctor_report"
    PRESCRIPTION = "prescription"
    DISCHARGE_SUMMARY = "discharge_summary"
    IMAGING_REPORT = "imaging_report"
    REFERRAL = "referral"
    MEDICAL_CERTIFICATE = "medical_certificate"
    OTHER = "other"


class DocumentStatus(str, Enum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class ProcessingJobType(str, Enum):
    PDF_CONVERSION = "pdf_conversion"
    AI_EXTRACTION = "ai_extraction"
    EMBEDDING = "embedding"


class ProcessingJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYING = "retrying"
    FAILED = "failed"


class ExtractionStatus(str, Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PersonNotFoundError(Exception):
    """A person does not exist for the given id."""


class PatientAlreadyExistsError(Exception):
    """An account already has a patient bound to it."""


class DocumentNotFoundError(Exception):
    """A document (or its owning patient) does not exist for the given id."""


class DocumentAccessDeniedError(Exception):
    """The account has no access right to view/upload the document."""


class DocumentQuotaExceededError(Exception):
    """The medical record reached its free-plan document limit."""


class FileTooLargeError(Exception):
    """The uploaded binary exceeds the configured size limit."""


class UnsupportedFileTypeError(Exception):
    """The uploaded file is neither a supported PDF nor an image."""


class JobNotFoundError(Exception):
    """A processing job does not exist for the given id."""