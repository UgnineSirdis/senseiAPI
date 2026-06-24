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
        email=record.email,
        created_at=record.created_at,
    )


class PatientRepository:
    """Persists patients in PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        name: str,
        phone: str,
        email: str | None = None,
    ) -> Patient:
        record = PatientRecord(name=name, phone=phone, email=email)
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return _to_patient(record)

    async def list_all(self) -> list[Patient]:
        result = await self._session.execute(
            select(PatientRecord).order_by(PatientRecord.created_at.desc())
        )
        return [_to_patient(record) for record in result.scalars().all()]

    async def update(self, patient_id: uuid.UUID, updates: dict[str, object]) -> Patient:
        record = await self._session.get(PatientRecord, patient_id)
        if record is None:
            raise PatientNotFoundError(patient_id)
        if "phone" in updates:
            record.phone = str(updates["phone"])
        if "email" in updates:
            email_value = updates["email"]
            record.email = None if email_value is None else str(email_value)
        await self._session.commit()
        await self._session.refresh(record)
        return _to_patient(record)

    async def delete(self, patient_id: uuid.UUID) -> None:
        record = await self._session.get(PatientRecord, patient_id)
        if record is None:
            raise PatientNotFoundError(patient_id)
        await self._session.delete(record)
        await self._session.commit()
