import uuid
from dataclasses import dataclass
from datetime import datetime


class CalendarEventNotFoundError(Exception):
    """Raised when a requested calendar event does not exist."""

    def __init__(self, event_id: uuid.UUID) -> None:
        super().__init__(f"calendar event {event_id!r} not found")
        self.event_id = event_id


@dataclass(frozen=True)
class CalendarEvent:
    id: uuid.UUID
    title: str
    description: str | None
    start_at: datetime
    end_at: datetime
    created_at: datetime
    therapist_id: uuid.UUID
    patient_id: uuid.UUID | None = None
