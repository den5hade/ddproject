from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.domain.medical import Sex


class PersonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    date_of_birth: date | None
    sex: Sex | None
    city: str | None
    profession: str | None
    height: float | None
    weight: float | None

    @computed_field
    @property
    def age(self) -> int | None:
        if self.date_of_birth is None:
            return None
        today = date.today()
        return (
            today.year
            - self.date_of_birth.year
            - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        )


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    date_of_birth: date | None = None
    sex: Sex | None = None
    city: str | None = Field(default=None, max_length=255)
    profession: str | None = Field(default=None, max_length=255)
    height: float | None = Field(default=None, ge=0, le=300)
    weight: float | None = Field(default=None, ge=0, le=500)

    @model_validator(mode="after")
    def _date_of_birth_not_in_future(self) -> "PersonUpdate":
        if self.date_of_birth and self.date_of_birth > date.today():
            raise ValueError("date_of_birth cannot be in the future")
        return self
