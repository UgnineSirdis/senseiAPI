import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class SummaryRecord(Base):
    """Persisted session summary for a therapy meeting (calendar event)."""

    __tablename__ = "meeting_summaries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("calendar_events.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="", server_default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
