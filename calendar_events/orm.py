import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class CalendarEventRecord(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        Index("ix_calendar_events_therapist_start_at", "therapist_id", "start_at"),
        Index("ix_calendar_events_therapist_end_at", "therapist_id", "end_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # [start_at, end_at) - half-interval
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    therapist_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
