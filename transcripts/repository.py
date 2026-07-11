import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from transcripts.models import StoredTranscript
from transcripts.orm import TranscriptRecord


def to_transcript(record: TranscriptRecord) -> StoredTranscript:
    return StoredTranscript(
        id=record.id,
        meeting_id=record.meeting_id,
        raw_text=record.raw_text,
        diarized_segments=list(record.diarized_segments or []),
        language=record.language,
        created_at=record.created_at,
    )


class TranscriptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        meeting_id: uuid.UUID,
        raw_text: str,
        language: str = "he",
        diarized_segments: list[dict[str, Any]] | None = None,
    ) -> StoredTranscript:
        record = TranscriptRecord(
            meeting_id=meeting_id,
            raw_text=raw_text,
            language=language or "he",
            diarized_segments=diarized_segments or [],
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return to_transcript(record)

    async def get_by_meeting_id(self, meeting_id: uuid.UUID) -> StoredTranscript | None:
        result = await self._session.execute(
            select(TranscriptRecord).where(TranscriptRecord.meeting_id == meeting_id)
        )
        record = result.scalar_one_or_none()
        return to_transcript(record) if record else None

    async def get_by_id(self, transcript_id: uuid.UUID) -> StoredTranscript | None:
        record = await self._session.get(TranscriptRecord, transcript_id)
        return to_transcript(record) if record else None
