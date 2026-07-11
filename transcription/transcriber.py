import io
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi.concurrency import run_in_threadpool

from transcription.models import Transcript, TranscriptionFailedError, Word

if TYPE_CHECKING:
    from elevenlabs.client import AsyncElevenLabs
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# (model_size, device, compute_type) -> a loaded Whisper model.
ModelLoader = Callable[[str, str, str], "WhisperModel"]


class Transcriber(ABC):
    """Transcribes raw audio bytes into a ``Transcript``."""

    @abstractmethod
    async def transcribe(self, *, data: bytes, filename: str, language: str) -> Transcript: ...


@lru_cache(maxsize=4)
def _load_model(model_size: str, device: str, compute_type: str) -> "WhisperModel":
    # Imported lazily so the (heavy) dependency and model load only happen on first use.
    from faster_whisper import WhisperModel

    logger.info(
        "loading whisper model",
        extra={"model": model_size, "device": device, "compute_type": compute_type},
    )
    return WhisperModel(model_size, device=device, compute_type=compute_type)


class LocalWhisperTranscriber(Transcriber):
    """Whisper transcription running locally via faster-whisper (no API key)."""

    def __init__(
        self,
        *,
        model_size: str,
        device: str,
        compute_type: str,
        load_model: ModelLoader = _load_model,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._load_model = load_model

    def _transcribe_sync(self, data: bytes, language: str) -> Transcript:
        model = self._load_model(self._model_size, self._device, self._compute_type)
        segments, info = model.transcribe(io.BytesIO(data), language=language, word_timestamps=True)
        text = ""
        words: list[Word] = []
        for segment in segments:
            text += segment.text
            words.extend(
                Word(text=word.word.strip(), start=word.start, end=word.end)
                for word in segment.words or ()
            )
        detected = getattr(info, "language", None) or language
        return Transcript(text=text.strip(), language=detected, words=tuple(words))

    async def transcribe(self, *, data: bytes, filename: str, language: str) -> Transcript:
        try:
            return await run_in_threadpool(self._transcribe_sync, data, language)
        except Exception as exc:
            logger.error("whisper transcription failed", exc_info=exc)
            raise TranscriptionFailedError("transcription failed") from exc


class ElevenLabsTranscriber(Transcriber):
    """Transcription via the ElevenLabs Speech-to-Text API (Scribe)."""

    def __init__(self, *, client: "AsyncElevenLabs", model: str) -> None:
        self._client = client
        self._model = model

    async def transcribe(self, *, data: bytes, filename: str, language: str) -> Transcript:
        try:
            response = await self._client.speech_to_text.convert(
                file=(filename, data),
                model_id=self._model,
                language_code=language,
                timestamps_granularity="word",
            )
        except Exception as exc:
            logger.error("elevenlabs transcription failed", exc_info=exc)
            raise TranscriptionFailedError("transcription failed") from exc
        words = tuple(
            Word(text=word.text, start=word.start, end=word.end)
            for word in response.words
            if word.type == "word"
        )
        # Scribe answers in ISO-639-3 ("heb") even though we ask in ISO-639-1 ("he"). Since the
        # language is always ours to specify, report it back rather than translating between
        # code sets — that keeps this backend's output identical to the Whisper one's.
        return Transcript(text=response.text, language=language, words=words)
