import uuid

from patients.models import Patient
from patients.repository import PatientRepository


class PatientService:
    """Business logic for patient management."""

    def __init__(self, repository: PatientRepository) -> None:
        self._repository = repository

    async def add_patient(
        self,
        *,
        name: str,
        phone: str,
        email: str | None = None,
    ) -> Patient:
        return await self._repository.create(
            name=name,
            phone=phone,
            email=email,
        )

    async def list_patients(self) -> list[Patient]:
        return await self._repository.list_all()

    async def update_patient(self, patient_id: uuid.UUID, updates: dict[str, object]) -> Patient:
        return await self._repository.update(patient_id, updates)

    async def delete_patient(self, patient_id: uuid.UUID) -> None:
        await self._repository.delete(patient_id)
