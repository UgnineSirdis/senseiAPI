from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Protocol

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from main import create_app
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
    with ExitStack() as stack:

        def _make(
            *,
            max_upload_bytes: int | None = None,
            transcriber: Transcriber | None = None,
            database_url: str | None = None,
        ) -> tuple[TestClient, Settings]:
            upload_dir = tmp_path / "uploads"
            settings = Settings(
                upload_dir=upload_dir,
                init_database_on_startup=database_url is not None,
            )
            if max_upload_bytes is not None:
                settings.max_upload_bytes = max_upload_bytes
            if database_url is not None:
                settings.database_url = database_url
            chosen = transcriber if transcriber is not None else _default_transcriber
            test_app = create_app(settings=settings)
            test_app.dependency_overrides[get_transcriber] = lambda: chosen
            client = stack.enter_context(TestClient(test_app))
            return client, settings

        yield _make
