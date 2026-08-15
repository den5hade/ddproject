from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AuthOtpRequested(BaseModel):
    """Published by account-api when a user requests a one-time login code."""

    request_id: UUID
    identity: str
    channel: Literal["email", "phone"]
    code: str
    expires_at: datetime = Field(
        description="UTC timestamp after which the code is no longer valid"
    )