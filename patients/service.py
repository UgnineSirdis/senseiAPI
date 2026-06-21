import uuid

from patients.models import Patient
from patients.repository import PatientRepository


class PatientService:
    """Business logic for patient management."""

    def __init__(self, repository: PatientRepository) -> None:
        self._repository = repository

    async def add_patient(self, *, name: str, phone: str, therapist_id: uuid.UUID) -> Patient:
        return await self._repository.create(
            name=name,
            phone=phone,
            therapist_id=therapist_id,
        )

    async def list_patients_by_therapist(self, therapist_id: uuid.UUID) -> list[Patient]:
        return await self._repository.list_by_therapist(therapist_id)

    async def delete_patient(self, patient_id: uuid.UUID) -> None:
        await self._repository.delete(patient_id)
