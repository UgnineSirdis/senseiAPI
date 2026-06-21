import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from patients.models import Patient, PatientNotFoundError
from patients.orm import PatientRecord


def _to_patient(record: PatientRecord) -> Patient:
    return Patient(
        id=record.id,
        name=record.name,
        phone=record.phone,
        created_at=record.created_at,
        therapist_id=record.therapist_id,
    )


class PatientRepository:
    """Persists patients in PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, name: str, phone: str, therapist_id: uuid.UUID) -> Patient:
        record = PatientRecord(name=name, phone=phone, therapist_id=therapist_id)
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return _to_patient(record)

    async def list_by_therapist(self, therapist_id: uuid.UUID) -> list[Patient]:
        result = await self._session.execute(
            select(PatientRecord)
            .where(PatientRecord.therapist_id == therapist_id)
            .order_by(PatientRecord.created_at.desc())
        )
        return [_to_patient(record) for record in result.scalars().all()]

    async def delete(self, patient_id: uuid.UUID) -> None:
        record = await self._session.get(PatientRecord, patient_id)
        if record is None:
            raise PatientNotFoundError(patient_id)
        await self._session.delete(record)
        await self._session.commit()
