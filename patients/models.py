import uuid
from dataclasses import dataclass
from datetime import datetime


class PatientNotFoundError(Exception):
    """Raised when a requested patient does not exist."""

    def __init__(self, patient_id: uuid.UUID) -> None:
        super().__init__(f"patient {patient_id!r} not found")
        self.patient_id = patient_id


@dataclass(frozen=True)
class Patient:
    id: uuid.UUID
    name: str
    phone: str
    email: str | None
    created_at: datetime
