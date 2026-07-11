from pathlib import Path

from tests.conftest import ClientFactory
from transcription.models import Transcript, TranscriptionFailedError, Word
from transcription.transcriber import Transcriber

HEBREW_TEXT = "שלום, זאת הקלטת בדיקה."


def _seed_audio(
    upload_dir: Path, *, name: str = "voice.m4a", content: bytes = b"fake-audio-bytes"
) -> str:
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / name).write_bytes(content)
    return name


class _StubTranscriber(Transcriber):
    async def transcribe(self, *, data: bytes, filename: str, language: str) -> Transcript:
        assert language == "he"
        assert data
        return Transcript(text=HEBREW_TEXT, language=language)


class _FailingTranscriber(Transcriber):
    async def transcribe(self, *, data: bytes, filename: str, language: str) -> Transcript:
        raise TranscriptionFailedError("boom")


def test_transcribe_returns_hebrew_text(make_client: ClientFactory) -> None:
    client, settings = make_client(transcriber=_StubTranscriber())
    audio_id = _seed_audio(settings.upload_dir)

    res = client.post(f"/audio/{audio_id}/transcribe")
    assert res.status_code == 200
    body = res.json()
    assert body == {"id": audio_id, "language": "he", "text": HEBREW_TEXT, "words": []}
    assert not (settings.upload_dir / audio_id).exists()


class _WordTimestampTranscriber(Transcriber):
    async def transcribe(self, *, data: bytes, filename: str, language: str) -> Transcript:
        return Transcript(
            text=HEBREW_TEXT,
            language=language,
            words=(Word(text="שלום", start=0.0, end=0.4),),
        )


def test_transcribe_returns_word_timestamps(make_client: ClientFactory) -> None:
    client, settings = make_client(transcriber=_WordTimestampTranscriber())
    audio_id = _seed_audio(settings.upload_dir)

    res = client.post(f"/audio/{audio_id}/transcribe")

    assert res.status_code == 200
    assert res.json()["words"] == [{"text": "שלום", "start": 0.0, "end": 0.4}]
    assert not (settings.upload_dir / audio_id).exists()


def test_transcribe_missing_audio_returns_404(make_client: ClientFactory) -> None:
    client, _ = make_client(transcriber=_StubTranscriber())
    res = client.post("/audio/does-not-exist.m4a/transcribe")
    assert res.status_code == 404


def test_transcribe_provider_failure_keeps_file(make_client: ClientFactory) -> None:
    client, settings = make_client(transcriber=_FailingTranscriber())
    audio_id = _seed_audio(settings.upload_dir)

    res = client.post(f"/audio/{audio_id}/transcribe")
    assert res.status_code == 502
    assert (settings.upload_dir / audio_id).exists()
