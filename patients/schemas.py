import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, EmailStr, Field, model_validator

from patients.models import Patient


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=3, max_length=32)
    email: EmailStr | None = None


class PatientUpdate(BaseModel):
    phone: str | None = Field(default=None, min_length=3, max_length=32)
    email: EmailStr | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one of phone or email must be provided")
        return self


class PatientOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str
    email: str | None
    created_at: datetime

    @classmethod
    def from_patient(cls, patient: Patient) -> Self:
        return cls(
            id=patient.id,
            name=patient.name,
            phone=patient.phone,
            email=patient.email,
            created_at=patient.created_at,
        )
