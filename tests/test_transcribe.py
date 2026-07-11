from fastapi.testclient import TestClient

from tests.conftest import ClientFactory
from transcription.models import Transcript, TranscriptionFailedError, Word
from transcription.transcriber import Transcriber

HEBREW_TEXT = "שלום, זאת הקלטת בדיקה."


def _upload(client: TestClient) -> str:
    res = client.post(
        "/audio/upload",
        files={"file": ("voice.m4a", b"fake-audio-bytes", "audio/x-m4a")},
    )
    assert res.status_code == 201
    audio_id: str = res.json()["id"]
    return audio_id


class _StubTranscriber(Transcriber):
    async def transcribe(self, *, data: bytes, filename: str, language: str) -> Transcript:
        assert language == "he"
        assert data
        return Transcript(text=HEBREW_TEXT, language=language)


class _FailingTranscriber(Transcriber):
    async def transcribe(self, *, data: bytes, filename: str, language: str) -> Transcript:
        raise TranscriptionFailedError("boom")


def test_transcribe_returns_hebrew_text(make_client: ClientFactory) -> None:
    client, _ = make_client(transcriber=_StubTranscriber())
    audio_id = _upload(client)

    res = client.post(f"/audio/{audio_id}/transcribe")
    assert res.status_code == 200
    body = res.json()
    assert body == {"id": audio_id, "language": "he", "text": HEBREW_TEXT, "words": []}


class _WordTimestampTranscriber(Transcriber):
    async def transcribe(self, *, data: bytes, filename: str, language: str) -> Transcript:
        return Transcript(
            text=HEBREW_TEXT,
            language=language,
            words=(Word(text="שלום", start=0.0, end=0.4),),
        )


def test_transcribe_returns_word_timestamps(make_client: ClientFactory) -> None:
    client, _ = make_client(transcriber=_WordTimestampTranscriber())
    audio_id = _upload(client)

    res = client.post(f"/audio/{audio_id}/transcribe")

    assert res.status_code == 200
    assert res.json()["words"] == [{"text": "שלום", "start": 0.0, "end": 0.4}]


def test_transcribe_missing_audio_returns_404(make_client: ClientFactory) -> None:
    client, _ = make_client(transcriber=_StubTranscriber())
    res = client.post("/audio/does-not-exist.m4a/transcribe")
    assert res.status_code == 404


def test_transcribe_provider_failure_returns_502(make_client: ClientFactory) -> None:
    upload_client, _ = make_client(transcriber=_StubTranscriber())
    audio_id = _upload(upload_client)

    failing_client, _ = make_client(transcriber=_FailingTranscriber())
    res = failing_client.post(f"/audio/{audio_id}/transcribe")
    assert res.status_code == 502
