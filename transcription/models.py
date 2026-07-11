from dataclasses import dataclass


class TranscriptionFailedError(Exception):
    """Raised when transcription fails."""


@dataclass(frozen=True)
class Word:
    """A single transcribed word and where it falls in the audio."""

    text: str
    start: float  # seconds from the start of the audio
    end: float


@dataclass(frozen=True)
class Transcript:
    """The result of transcribing an audio file."""

    text: str
    language: str
    words: tuple[Word, ...] = ()
