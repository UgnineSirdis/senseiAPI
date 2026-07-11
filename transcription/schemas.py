from typing import Self

from pydantic import BaseModel

from transcription.models import Transcript, Word


class WordOut(BaseModel):
    text: str
    start: float
    end: float

    @classmethod
    def from_word(cls, word: Word) -> Self:
        return cls(text=word.text, start=word.start, end=word.end)


class TranscriptionResponse(BaseModel):
    id: str
    language: str
    text: str
    words: list[WordOut] = []

    @classmethod
    def from_transcript(cls, audio_id: str, transcript: Transcript) -> Self:
        return cls(
            id=audio_id,
            language=transcript.language,
            text=transcript.text,
            words=[WordOut.from_word(word) for word in transcript.words],
        )
