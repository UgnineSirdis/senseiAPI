import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from calendar_events.models import CalendarEvent, CalendarEventNotFoundError
from calendar_events.orm import CalendarEventRecord

# TODO: refactor when we have an authorization
FAKE_THERAPIST_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _to_event(record: CalendarEventRecord) -> CalendarEvent:
    return CalendarEvent(
        id=record.id,
        title=record.title,
        description=record.description,
        start_at=record.start_at,
        end_at=record.end_at,
        created_at=record.created_at,
        therapist_id=FAKE_THERAPIST_ID,
        patient_id=record.patient_id,
    )


class CalendarEventRepository:
    """Persists calendar events in PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        title: str,
        start_at: datetime,
        end_at: datetime,
        description: str | None = None,
        patient_id: uuid.UUID | None = None,
    ) -> CalendarEvent:
        record = CalendarEventRecord(
            title=title,
            description=description,
            start_at=start_at,
            end_at=end_at,
            therapist_id=FAKE_THERAPIST_ID,
            patient_id=patient_id,
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return _to_event(record)

    async def list_all(
        self,
        *,
        from_at: datetime,
        to_at: datetime,
    ) -> list[CalendarEvent]:
        statement = select(CalendarEventRecord).where(
            CalendarEventRecord.therapist_id == FAKE_THERAPIST_ID,
            or_(
                and_(
                    CalendarEventRecord.start_at >= from_at,
                    CalendarEventRecord.start_at < to_at,
                ),
                and_(
                    CalendarEventRecord.end_at > from_at,
                    CalendarEventRecord.end_at <= to_at,
                ),
                and_(
                    from_at >= CalendarEventRecord.start_at,
                    from_at < CalendarEventRecord.end_at,
                ),
                and_(
                    to_at > CalendarEventRecord.start_at,
                    to_at <= CalendarEventRecord.end_at,
                ),
            ),
        )
        result = await self._session.execute(statement.order_by(CalendarEventRecord.start_at.asc()))
        return [_to_event(record) for record in result.scalars().all()]

    async def get(self, event_id: uuid.UUID) -> CalendarEvent:
        result = await self._session.execute(
            select(CalendarEventRecord).where(
                CalendarEventRecord.id == event_id,
                CalendarEventRecord.therapist_id == FAKE_THERAPIST_ID,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise CalendarEventNotFoundError(event_id)
        return _to_event(record)

    async def update(self, event_id: uuid.UUID, updates: dict[str, object]) -> CalendarEvent:
        record = await self._session.get(CalendarEventRecord, event_id)
        if record is None:
            raise CalendarEventNotFoundError(event_id)
        if "title" in updates:
            record.title = str(updates["title"])
        if "description" in updates:
            description_value = updates["description"]
            record.description = None if description_value is None else str(description_value)
        if "start_at" in updates:
            start_at_value = updates["start_at"]
            if isinstance(start_at_value, datetime):
                record.start_at = start_at_value
        if "end_at" in updates:
            end_at_value = updates["end_at"]
            if isinstance(end_at_value, datetime):
                record.end_at = end_at_value
        if "patient_id" in updates:
            patient_id_value = updates["patient_id"]
            if patient_id_value is None or isinstance(patient_id_value, uuid.UUID):
                record.patient_id = patient_id_value
        await self._session.commit()
        await self._session.refresh(record)
        return _to_event(record)

    async def delete(self, event_id: uuid.UUID) -> None:
        record = await self._session.get(CalendarEventRecord, event_id)
        if record is None:
            raise CalendarEventNotFoundError(event_id)
        await self._session.delete(record)
        await self._session.commit()
