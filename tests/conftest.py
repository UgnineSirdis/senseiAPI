from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import pytest
from fastapi.testclient import TestClient

from core.config import Settings, get_settings
from main import app
from transcription.dependencies import get_transcriber
from transcription.models import Transcript
from transcription.transcriber import Transcriber

DEFAULT_TRANSCRIPT = "תמלול לדוגמה"


class _DefaultTranscriber(Transcriber):
    async def transcribe(self, *, data: bytes, filename: str, language: str) -> Transcript:
        return Transcript(text=DEFAULT_TRANSCRIPT, language=language)


_default_transcriber = _DefaultTranscriber()


class ClientFactory(Protocol):
    def __call__(
        self,
        *,
        max_upload_bytes: int | None = None,
        transcriber: Transcriber | None = None,
        database_url: str | None = None,
    ) -> tuple[TestClient, Settings]: ...


@pytest.fixture
def make_client(tmp_path: Path) -> Iterator[ClientFactory]:
    """Build a TestClient with settings pointed at an isolated upload dir.

    A fake ``transcriber`` is injected by default so tests never load the real
    Whisper model; pass ``transcriber=`` to customise the behaviour.
    """

    def _make(
        *,
        max_upload_bytes: int | None = None,
        transcriber: Transcriber | None = None,
        database_url: str | None = None,
    ) -> tuple[TestClient, Settings]:
        upload_dir = tmp_path / "uploads"
        settings = Settings(upload_dir=upload_dir)
        if max_upload_bytes is not None:
            settings.max_upload_bytes = max_upload_bytes
        settings.database_url = database_url
        chosen = transcriber if transcriber is not None else _default_transcriber
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_transcriber] = lambda: chosen
        return TestClient(app), settings

    yield _make
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _skip_database_lifecycle_for_unit_tests(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit tests should not require Postgres during app lifespan startup."""
    if request.node.get_closest_marker("integration"):
        return

    async def noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("main.init_database", noop)
    monkeypatch.setattr("main.close_database", noop)
