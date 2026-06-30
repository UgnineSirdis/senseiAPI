import uuid
from datetime import datetime

from calendar_events.models import CalendarEvent
from calendar_events.repository import CalendarEventRepository


class CalendarEventService:
    """Business logic for calendar event management."""

    def __init__(self, repository: CalendarEventRepository) -> None:
        self._repository = repository

    async def add_event(
        self,
        *,
        title: str,
        start_at: datetime,
        end_at: datetime,
        description: str | None = None,
        patient_id: uuid.UUID | None = None,
    ) -> CalendarEvent:
        return await self._repository.create(
            title=title,
            description=description,
            start_at=start_at,
            end_at=end_at,
            patient_id=patient_id,
        )

    async def list_events(
        self,
        *,
        from_at: datetime,
        to_at: datetime,
    ) -> list[CalendarEvent]:
        return await self._repository.list_all(
            from_at=from_at,
            to_at=to_at,
        )

    async def get_event(self, event_id: uuid.UUID) -> CalendarEvent:
        return await self._repository.get(event_id)

    async def update_event(self, event_id: uuid.UUID, updates: dict[str, object]) -> CalendarEvent:
        return await self._repository.update(event_id, updates)

    async def delete_event(self, event_id: uuid.UUID) -> None:
        await self._repository.delete(event_id)
