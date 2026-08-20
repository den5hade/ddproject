from fastapi import HTTPException, status

from app.domain.access import PatientAccessGrantNotFoundError
from app.domain.account import RoleNotFoundError
from app.domain.medical import (
    DocumentNotFoundError,
    DocumentQuotaExceededError,
    EncounterNotFoundError,
    FileTooLargeError,
    JobNotFoundError,
    PatientAlreadyExistsError,
    PersonNotFoundError,
    UnsupportedFileTypeError,
)
from app.services.auth import OtpVerificationError, RateLimitError, RefreshTokenError
from app.services.storage import StorageUnavailableError

_EXCEPTION_STATUS: dict[type[Exception], int] = {
    # Auth
    RateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,
    OtpVerificationError: status.HTTP_400_BAD_REQUEST,
    RefreshTokenError: status.HTTP_401_UNAUTHORIZED,
    # Patients
    PersonNotFoundError: status.HTTP_404_NOT_FOUND,
    PatientAlreadyExistsError: status.HTTP_409_CONFLICT,
    # Documents
    DocumentNotFoundError: status.HTTP_404_NOT_FOUND,
    DocumentQuotaExceededError: status.HTTP_429_TOO_MANY_REQUESTS,
    FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    UnsupportedFileTypeError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    StorageUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    # Jobs
    JobNotFoundError: status.HTTP_404_NOT_FOUND,
    # Encounters
    EncounterNotFoundError: status.HTTP_404_NOT_FOUND,
    # Access
    PatientAccessGrantNotFoundError: status.HTTP_404_NOT_FOUND,
    # Admin
    RoleNotFoundError: status.HTTP_404_NOT_FOUND,
}

_DEFAULT_STATUS = status.HTTP_400_BAD_REQUEST


def raise_for(exc: Exception) -> None:
    """Raise an :class:`HTTPException` whose status code matches *exc*."""
    code = _EXCEPTION_STATUS.get(type(exc), _DEFAULT_STATUS)
    raise HTTPException(status_code=code, detail=str(exc)) from exc
