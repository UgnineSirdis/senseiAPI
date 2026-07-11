from typing import Any, Self

from pydantic import BaseModel

from audio.models import SavedAudio, StoredAudioFile
from transcription.models import Transcript


def diarized_segments_from_transcript(transcript: Transcript) -> list[dict[str, Any]]:
    """Map word timings into the transcripts.diarized_segments shape (no real speakers yet)."""
    return [
        {
            "speaker": "unknown",
            "start_time": word.start,
            "end_time": word.end,
            "text": word.text,
        }
        for word in transcript.words
    ]


class AudioUploadResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    language: str
    text: str
    meeting_id: str | None = None
    transcript_id: str | None = None

    @classmethod
    def from_upload(
        cls,
        saved: SavedAudio,
        transcript: Transcript,
        *,
        meeting_id: str | None = None,
        transcript_id: str | None = None,
    ) -> Self:
        return cls(
            id=saved.id,
            filename=saved.filename,
            content_type=saved.content_type,
            size_bytes=saved.size_bytes,
            language=transcript.language,
            text=transcript.text,
            meeting_id=meeting_id,
            transcript_id=transcript_id,
        )


class AudioFileInfo(BaseModel):
    id: str
    size_bytes: int

    @classmethod
    def from_stored(cls, stored: StoredAudioFile) -> Self:
        return cls(id=stored.id, size_bytes=stored.size_bytes)
