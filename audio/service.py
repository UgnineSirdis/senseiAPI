from collections.abc import Sequence
from pathlib import Path

from fastapi import UploadFile

from audio.loader import AudioLoader
from audio.models import SavedAudio, StoredAudioFile
from transcription.models import Transcript
from transcription.transcriber import Transcriber


class AudioService:
    """Orchestrates audio storage and transcription."""

    def __init__(self, loader: AudioLoader, transcriber: Transcriber, *, language: str) -> None:
        self._loader = loader
        self._transcriber = transcriber
        self._language = language

    async def upload_and_transcribe(self, file: UploadFile) -> tuple[SavedAudio, Transcript]:
        saved = await self._loader.save(file)
        try:
            transcript = await self._transcriber.transcribe(
                data=saved.data,
                filename=saved.filename,
                language=self._language,
            )
        except Exception:
            # Keep the file on transcription failure so the client can retry.
            raise
        await self._loader.delete(saved.id)
        return saved, transcript

    async def transcribe(self, audio_id: str) -> Transcript:
        filename, data = await self._loader.read(audio_id)
        try:
            transcript = await self._transcriber.transcribe(
                data=data,
                filename=filename,
                language=self._language,
            )
        except Exception:
            # Keep the file on transcription failure so the client can retry.
            raise
        await self._loader.delete(audio_id)
        return transcript

    async def list_files(self) -> Sequence[StoredAudioFile]:
        return await self._loader.list_files()

    async def get_path(self, audio_id: str) -> Path:
        return await self._loader.get_path(audio_id)

    async def delete(self, audio_id: str) -> None:
        await self._loader.delete(audio_id)
