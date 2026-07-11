from types import SimpleNamespace
from typing import Any

import pytest

from core.config import Settings
from transcription.dependencies import get_transcriber
from transcription.models import Transcript, TranscriptionFailedError, Word
from transcription.transcriber import ElevenLabsTranscriber, LocalWhisperTranscriber

AUDIO = b"fake-audio-bytes"
HEBREW_TEXT = "שלום עולם"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeSpeechToText:
    """Stands in for ``AsyncElevenLabs().speech_to_text``."""

    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def convert(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _FakeClient:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.speech_to_text = _FakeSpeechToText(response=response, error=error)


def _word(text: str, start: float, end: float, type_: str = "word") -> SimpleNamespace:
    return SimpleNamespace(text=text, start=start, end=end, type=type_)


@pytest.mark.anyio
async def test_transcribe_returns_text_language_and_words() -> None:
    client = _FakeClient(
        response=SimpleNamespace(
            # Scribe answers in ISO-639-3 ("heb") even when asked in ISO-639-1 ("he").
            text=HEBREW_TEXT,
            language_code="heb",
            words=[_word("שלום", 0.0, 0.4), _word("עולם", 0.5, 0.9)],
        )
    )
    transcriber = ElevenLabsTranscriber(client=client, model="scribe_v2")

    transcript = await transcriber.transcribe(data=AUDIO, filename="voice.m4a", language="he")

    assert transcript == Transcript(
        text=HEBREW_TEXT,
        language="he",
        words=(Word(text="שלום", start=0.0, end=0.4), Word(text="עולם", start=0.5, end=0.9)),
    )


@pytest.mark.anyio
async def test_transcribe_keeps_only_word_entries() -> None:
    """The API also emits ``spacing`` and ``audio_event`` entries, which carry no words."""
    client = _FakeClient(
        response=SimpleNamespace(
            text=HEBREW_TEXT,
            language_code="he",
            words=[
                _word("שלום", 0.0, 0.4),
                _word(" ", 0.4, 0.5, type_="spacing"),
                _word("(laughter)", 0.5, 0.7, type_="audio_event"),
                _word("עולם", 0.7, 1.1),
            ],
        )
    )
    transcriber = ElevenLabsTranscriber(client=client, model="scribe_v2")

    transcript = await transcriber.transcribe(data=AUDIO, filename="voice.m4a", language="he")

    assert transcript.words == (
        Word(text="שלום", start=0.0, end=0.4),
        Word(text="עולם", start=0.7, end=1.1),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("returned", ["heb", "he", None])
async def test_transcribe_reports_the_requested_iso_639_1_language(returned: str | None) -> None:
    """Both backends must speak ISO-639-1, whatever dialect of language code the API answers in."""
    client = _FakeClient(
        response=SimpleNamespace(text=HEBREW_TEXT, language_code=returned, words=[]),
    )
    transcriber = ElevenLabsTranscriber(client=client, model="scribe_v2")

    transcript = await transcriber.transcribe(data=AUDIO, filename="voice.m4a", language="he")

    assert transcript.language == "he"


@pytest.mark.anyio
async def test_transcribe_wraps_provider_errors() -> None:
    client = _FakeClient(error=RuntimeError("401 unauthorized"))
    transcriber = ElevenLabsTranscriber(client=client, model="scribe_v2")

    with pytest.raises(TranscriptionFailedError):
        await transcriber.transcribe(data=AUDIO, filename="voice.m4a", language="he")


class _FakeWhisperModel:
    def __init__(self, segments: list[SimpleNamespace], language: str) -> None:
        self._segments = segments
        self._language = language
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, _audio: Any, **kwargs: Any) -> tuple[list[SimpleNamespace], Any]:
        self.calls.append(kwargs)
        return self._segments, SimpleNamespace(language=self._language)


@pytest.mark.anyio
async def test_whisper_transcribe_returns_word_timestamps() -> None:
    model = _FakeWhisperModel(
        segments=[
            SimpleNamespace(
                text="שלום עולם",
                words=[
                    SimpleNamespace(word="שלום", start=0.0, end=0.4),
                    SimpleNamespace(word="עולם", start=0.5, end=0.9),
                ],
            )
        ],
        language="he",
    )
    transcriber = LocalWhisperTranscriber(
        model_size="small",
        device="cpu",
        compute_type="int8",
        load_model=lambda *_: model,
    )

    transcript = await transcriber.transcribe(data=AUDIO, filename="voice.m4a", language="he")

    assert transcript.text == HEBREW_TEXT
    assert transcript.words == (
        Word(text="שלום", start=0.0, end=0.4),
        Word(text="עולם", start=0.5, end=0.9),
    )
    assert model.calls[0]["word_timestamps"] is True


def _settings(**overrides: Any) -> Settings:
    # ``_env_file=None`` keeps a developer's local .env out of these assertions.
    return Settings(_env_file=None, **overrides)


def test_get_transcriber_defaults_to_elevenlabs() -> None:
    transcriber = get_transcriber(_settings(elevenlabs_api_key="secret"))

    assert isinstance(transcriber, ElevenLabsTranscriber)


def test_get_transcriber_returns_whisper_when_configured() -> None:
    transcriber = get_transcriber(_settings(transcriber_backend="whisper"))

    assert isinstance(transcriber, LocalWhisperTranscriber)


def test_get_transcriber_requires_api_key_for_elevenlabs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        get_transcriber(_settings(elevenlabs_api_key=None))
