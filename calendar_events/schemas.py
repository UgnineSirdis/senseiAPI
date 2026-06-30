import uuid
from datetime import UTC, datetime
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from calendar_events.models import CalendarEvent


class CalendarEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    start_at: datetime
    end_at: datetime
    patient_id: uuid.UUID | None = None


class CalendarEventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    start_at: datetime | None = None
    end_at: datetime | None = None
    patient_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one event field must be provided")
        return self


class CalendarEventOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    start_at: datetime
    end_at: datetime
    created_at: datetime
    therapist_id: uuid.UUID
    patient_id: uuid.UUID | None = None

    @classmethod
    def from_event(cls, event: CalendarEvent, *, time_zone: ZoneInfo) -> Self:
        def in_time_zone(value: datetime) -> datetime:
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(time_zone)

        return cls(
            id=event.id,
            title=event.title,
            description=event.description,
            start_at=in_time_zone(event.start_at),
            end_at=in_time_zone(event.end_at),
            created_at=in_time_zone(event.created_at),
            therapist_id=event.therapist_id,
            patient_id=event.patient_id,
        )
