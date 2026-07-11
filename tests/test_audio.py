import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from calendar_events.models import CalendarEventNotFoundError
from main import app
from summaries.repository import SummaryRepository
from summaries.service import SummaryService
from tests.conftest import DEFAULT_TRANSCRIPT, ClientFactory
from transcripts.models import (
    StoredTranscript,
    TranscriptAlreadyExistsError,
)
from transcripts.service import TranscriptService


def test_upload_audio_returns_201_and_deletes_file_after_transcript(
    make_client: ClientFactory,
) -> None:
    client, settings = make_client()
    content = b"ID3 fake-audio-bytes"
    res = client.post(
        "/audio/upload",
        files={"file": ("song.mp3", content, "audio/mpeg")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["filename"] == "song.mp3"
    assert body["content_type"] == "audio/mpeg"
    assert body["size_bytes"] == len(content)
    assert body["id"].endswith(".mp3")
    assert body["text"] == DEFAULT_TRANSCRIPT

    stored = settings.upload_dir / body["id"]
    assert not stored.exists()


def test_upload_audio_returns_transcript(make_client: ClientFactory) -> None:
    client, _ = make_client()
    res = client.post(
        "/audio/upload",
        files={"file": ("song.mp3", b"fake-audio-bytes", "audio/mpeg")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["language"] == "he"
    assert body["text"] == DEFAULT_TRANSCRIPT
    assert body["meeting_id"] is None
    assert body["transcript_id"] is None


def test_upload_audio_accepts_m4a(make_client: ClientFactory) -> None:
    client, _ = make_client()
    res = client.post(
        "/audio/upload",
        files={"file": ("voice.m4a", b"fake-m4a", "audio/x-m4a")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["content_type"] == "audio/x-m4a"
    assert body["id"].endswith(".m4a")


def test_upload_audio_rejects_unsupported_type(make_client: ClientFactory) -> None:
    client, _ = make_client()
    res = client.post(
        "/audio/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 415


def test_upload_audio_rejects_empty_file(make_client: ClientFactory) -> None:
    client, _ = make_client()
    res = client.post(
        "/audio/upload",
        files={"file": ("empty.mp3", b"", "audio/mpeg")},
    )
    assert res.status_code == 400


def test_upload_audio_rejects_too_large(make_client: ClientFactory) -> None:
    client, _ = make_client(max_upload_bytes=4)
    res = client.post(
        "/audio/upload",
        files={"file": ("song.mp3", b"too-long-content", "audio/mpeg")},
    )
    assert res.status_code == 413


def test_upload_audio_requires_file(make_client: ClientFactory) -> None:
    client, _ = make_client()
    res = client.post("/audio/upload")
    assert res.status_code == 422


def test_list_audio_is_empty_initially(make_client: ClientFactory) -> None:
    client, _ = make_client()
    res = client.get("/audio")
    assert res.status_code == 200
    assert res.json() == []


def test_list_audio_returns_empty_after_upload_deletes_file(make_client: ClientFactory) -> None:
    client, _ = make_client()
    client.post(
        "/audio/upload",
        files={"file": ("song.mp3", b"abc", "audio/mpeg")},
    )
    res = client.get("/audio")
    assert res.status_code == 200
    assert res.json() == []


def test_download_audio_returns_content(make_client: ClientFactory) -> None:
    client, settings = make_client()
    content = b"fake-audio-content"
    audio_id = "seeded-song.mp3"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / audio_id).write_bytes(content)
    res = client.get(f"/audio/{audio_id}")
    assert res.status_code == 200
    assert res.content == content
    assert res.headers["content-type"].startswith("audio/mpeg")


def test_download_audio_missing_returns_404(make_client: ClientFactory) -> None:
    client, _ = make_client()
    res = client.get("/audio/does-not-exist.mp3")
    assert res.status_code == 404


def test_download_audio_rejects_path_traversal(make_client: ClientFactory) -> None:
    client, _ = make_client()
    res = client.get("/audio/..%2F..%2Fetc%2Fpasswd")
    assert res.status_code == 404


def test_delete_audio_returns_204_then_404(make_client: ClientFactory) -> None:
    client, settings = make_client()
    audio_id = "seeded-song.mp3"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / audio_id).write_bytes(b"abc")

    assert client.delete(f"/audio/{audio_id}").status_code == 204
    assert not (settings.upload_dir / audio_id).exists()
    assert client.get(f"/audio/{audio_id}").status_code == 404


def test_delete_audio_missing_returns_404(make_client: ClientFactory) -> None:
    client, _ = make_client()
    res = client.delete("/audio/does-not-exist.mp3")
    assert res.status_code == 404


def _override_db_session() -> None:
    from core.database import get_optional_db_session

    async def _fake_db():
        yield object()

    app.dependency_overrides[get_optional_db_session] = _fake_db


def _clear_db_override() -> None:
    from core.database import get_optional_db_session

    app.dependency_overrides.pop(get_optional_db_session, None)


def test_upload_without_meeting_id_returns_400_when_db_configured(
    make_client: ClientFactory,
) -> None:
    _override_db_session()
    try:
        client, _ = make_client()
        res = client.post(
            "/audio/upload",
            files={"file": ("song.mp3", b"fake-audio-bytes", "audio/mpeg")},
            data={"patient_id": str(uuid.uuid4())},
        )
    finally:
        _clear_db_override()
    assert res.status_code == 400
    assert "meeting_id" in res.json()["detail"]


def test_upload_with_meeting_persists_via_transcript_service(
    make_client: ClientFactory,
    monkeypatch,
) -> None:
    meeting_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    transcript_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    patient_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    saved = StoredTranscript(
        id=transcript_id,
        meeting_id=meeting_id,
        raw_text=DEFAULT_TRANSCRIPT,
        diarized_segments=[],
        language="he",
        created_at=datetime(2026, 7, 11, 12, 0, tzinfo=UTC),
    )
    mock_save = AsyncMock(return_value=saved)
    monkeypatch.setattr(TranscriptService, "save_for_upload", mock_save)
    monkeypatch.setattr(SummaryRepository, "create_pending", AsyncMock())
    monkeypatch.setattr(SummaryService, "generate", AsyncMock())

    _override_db_session()
    try:
        client, _ = make_client()
        res = client.post(
            "/audio/upload",
            files={"file": ("song.mp3", b"fake-audio-bytes", "audio/mpeg")},
            data={
                "patient_id": str(patient_id),
                "meeting_id": str(meeting_id),
            },
        )
    finally:
        _clear_db_override()

    assert res.status_code == 201
    body = res.json()
    assert body["meeting_id"] == str(meeting_id)
    assert body["transcript_id"] == str(transcript_id)
    mock_save.assert_awaited_once()
    kwargs = mock_save.await_args.kwargs
    assert kwargs["meeting_id"] == meeting_id
    assert kwargs["patient_id"] == patient_id
    assert kwargs["raw_text"] == DEFAULT_TRANSCRIPT


def test_upload_schedules_a_summary_and_marks_it_pending(
    make_client: ClientFactory,
    monkeypatch,
) -> None:
    """The pending row is written during the request, not by the background job: a client
    polling in the gap would otherwise get a 404 for a summary that is on its way."""
    meeting_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    saved = StoredTranscript(
        id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        meeting_id=meeting_id,
        raw_text=DEFAULT_TRANSCRIPT,
        diarized_segments=[],
        language="he",
        created_at=datetime(2026, 7, 11, 12, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(TranscriptService, "save_for_upload", AsyncMock(return_value=saved))

    mock_pending = AsyncMock()
    monkeypatch.setattr(SummaryRepository, "create_pending", mock_pending)
    mock_generate = AsyncMock()
    monkeypatch.setattr(SummaryService, "generate", mock_generate)

    _override_db_session()
    try:
        client, _ = make_client()
        res = client.post(
            "/audio/upload",
            files={"file": ("song.mp3", b"fake-audio-bytes", "audio/mpeg")},
            data={"meeting_id": str(meeting_id)},
        )
    finally:
        _clear_db_override()

    assert res.status_code == 201
    mock_pending.assert_awaited_once_with(meeting_id)
    mock_generate.assert_awaited_once_with(meeting_id)


def test_upload_unknown_meeting_returns_404(make_client: ClientFactory, monkeypatch) -> None:
    meeting_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    monkeypatch.setattr(
        TranscriptService,
        "save_for_upload",
        AsyncMock(side_effect=CalendarEventNotFoundError(meeting_id)),
    )
    _override_db_session()
    try:
        client, _ = make_client()
        res = client.post(
            "/audio/upload",
            files={"file": ("song.mp3", b"fake-audio-bytes", "audio/mpeg")},
            data={"meeting_id": str(meeting_id)},
        )
    finally:
        _clear_db_override()
    assert res.status_code == 404


def test_upload_duplicate_transcript_returns_409(make_client: ClientFactory, monkeypatch) -> None:
    meeting_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    monkeypatch.setattr(
        TranscriptService,
        "save_for_upload",
        AsyncMock(side_effect=TranscriptAlreadyExistsError(meeting_id)),
    )
    _override_db_session()
    try:
        client, _ = make_client()
        res = client.post(
            "/audio/upload",
            files={"file": ("song.mp3", b"fake-audio-bytes", "audio/mpeg")},
            data={"meeting_id": str(meeting_id)},
        )
    finally:
        _clear_db_override()
    assert res.status_code == 409
