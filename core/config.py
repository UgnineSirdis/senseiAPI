from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from the environment.

    Override any field via env vars (e.g. ``UPLOAD_DIR``) or a local ``.env``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    upload_dir: Path = Path("uploads")
    max_upload_bytes: int = 25 * 1024 * 1024  # 25 MiB
    database_url: str = "postgresql+asyncpg://sensei:sensei@localhost:5432/senseiapi"

    # Whisper transcription (local, via faster-whisper; no API key needed).
    whisper_model: str = "small"  # tiny|base|small|medium|large-v3 (or a local path)
    whisper_device: str = "cpu"  # "cpu", "cuda", or "auto"
    whisper_compute_type: str = "int8"  # e.g. int8, int8_float16, float16, float32
    transcribe_language: str = "he"  # ISO-639-1; Hebrew by default
    allowed_audio_types: tuple[str, ...] = (
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/mp4",
        "audio/x-m4a",
        "audio/m4a",
        "audio/aac",
        "audio/ogg",
        "audio/flac",
        "audio/x-flac",
        "audio/webm",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
