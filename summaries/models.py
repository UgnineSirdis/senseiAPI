import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SummaryStatus = Literal["pending", "running", "ready", "failed"]


class SummaryFailedError(Exception):
    """Raised when a summary could not be generated."""


class SummaryNotFoundError(Exception):
    """Raised when no summary has been requested for the given meeting."""

    def __init__(self, meeting_id: uuid.UUID) -> None:
        super().__init__(f"no summary for meeting {meeting_id!r}")
        self.meeting_id = meeting_id


@dataclass(frozen=True)
class Summary:
    """A generated session summary and the model that wrote it."""

    text: str
    model: str


@dataclass(frozen=True)
class StoredSummary:
    """A summary row: the only place a background failure can be recorded."""

    id: uuid.UUID
    meeting_id: uuid.UUID
    status: SummaryStatus
    text: str | None
    model: str
    error: str | None
    created_at: datetime
    updated_at: datetime
