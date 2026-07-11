import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


class TranscriptAlreadyExistsError(Exception):
    """Raised when a transcript already exists for the given meeting (1:1)."""

    def __init__(self, meeting_id: uuid.UUID) -> None:
        super().__init__(f"transcript already exists for meeting {meeting_id!r}")
        self.meeting_id = meeting_id


class TranscriptPatientMismatchError(Exception):
    """Raised when form patient_id does not match the calendar event's patient."""

    def __init__(self, meeting_id: uuid.UUID, patient_id: uuid.UUID) -> None:
        super().__init__(f"patient {patient_id!r} does not match calendar event {meeting_id!r}")
        self.meeting_id = meeting_id
        self.patient_id = patient_id


@dataclass(frozen=True)
class StoredTranscript:
    id: uuid.UUID
    meeting_id: uuid.UUID
    raw_text: str
    diarized_segments: list[dict[str, Any]]
    language: str
    created_at: datetime
