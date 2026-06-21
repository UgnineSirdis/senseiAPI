import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from patients.models import Patient


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=3, max_length=32)
    therapist_id: uuid.UUID


class PatientOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str
    created_at: datetime
    therapist_id: uuid.UUID

    @classmethod
    def from_patient(cls, patient: Patient) -> Self:
        return cls(
            id=patient.id,
            name=patient.name,
            phone=patient.phone,
            created_at=patient.created_at,
            therapist_id=patient.therapist_id,
        )
