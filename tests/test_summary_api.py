import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from core.config import Settings, get_settings
from main import app
from summaries.dependencies import get_summary_reader
from summaries.models import StoredSummary, SummaryStatus

MEETING_ID = uuid.uuid4()
HEBREW_SUMMARY = "## נושאים מרכזיים\nחרדה במהלך השבוע."


def _stored(status: SummaryStatus, **changes: object) -> StoredSummary:
    now = datetime.now(UTC)
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "meeting_id": MEETING_ID,
        "status": status,
        "text": None,
        "model": "qwen2.5:7b-instruct",
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    base.update(changes)
    return StoredSummary(**base)  # type: ignore[arg-type]


class _FakeReader:
    def __init__(self, summary: StoredSummary | None) -> None:
        self._summary = summary

    async def get_by_meeting_id(self, meeting_id: uuid.UUID) -> StoredSummary | None:
        return self._summary


def _client(summary: StoredSummary | None) -> TestClient:
    app.dependency_overrides[get_settings] = lambda: Settings(enable_security=False)
    app.dependency_overrides[get_summary_reader] = lambda: _FakeReader(summary)
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_ready_summary_returns_200_with_the_text() -> None:
    client = _client(_stored("ready", text=HEBREW_SUMMARY))

    res = client.get(f"/meetings/{MEETING_ID}/summary")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ready"
    assert body["text"] == HEBREW_SUMMARY
    assert body["model"] == "qwen2.5:7b-instruct"


def test_running_summary_returns_202() -> None:
    client = _client(_stored("running"))

    res = client.get(f"/meetings/{MEETING_ID}/summary")

    assert res.status_code == 202
    assert res.json()["status"] == "running"


def test_failed_summary_returns_200_with_the_error() -> None:
    """The request succeeded; it is the summary that failed, and the therapist must see why."""
    client = _client(_stored("failed", error="model qwen2.5 not found"))

    res = client.get(f"/meetings/{MEETING_ID}/summary")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "failed"
    assert body["error"] == "model qwen2.5 not found"


def test_missing_summary_returns_404() -> None:
    client = _client(None)

    res = client.get(f"/meetings/{MEETING_ID}/summary")

    assert res.status_code == 404
