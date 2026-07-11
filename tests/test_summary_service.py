import uuid
from datetime import UTC, datetime

import pytest

from summaries.models import StoredSummary, Summary, SummaryFailedError
from summaries.service import SummaryService, fail_interrupted_summaries
from summaries.summarizer import Summarizer
from transcripts.models import StoredTranscript

MEETING_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
HEBREW_SUMMARY = "## נושאים מרכזיים\nחרדה במהלך השבוע."


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeSummarizer(Summarizer):
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    async def summarize(self, *, text: str, language: str) -> Summary:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return Summary(text=HEBREW_SUMMARY, model="qwen2.5:7b-instruct")


class _FakeSummaryRepository:
    """In-memory stand-in for the persistence boundary."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, StoredSummary] = {}
        self.transitions: list[str] = []

    def _row(self, meeting_id: uuid.UUID, **changes: object) -> StoredSummary:
        now = datetime.now(UTC)
        current = self.rows.get(meeting_id)
        base = {
            "id": current.id if current else uuid.uuid4(),
            "meeting_id": meeting_id,
            "status": "pending",
            "text": None,
            "model": "qwen2.5:7b-instruct",
            "error": None,
            "created_at": current.created_at if current else now,
            "updated_at": now,
        }
        base.update(changes)
        row = StoredSummary(**base)  # type: ignore[arg-type]
        self.rows[meeting_id] = row
        self.transitions.append(row.status)
        return row

    async def create_pending(self, meeting_id: uuid.UUID) -> StoredSummary:
        return self._row(meeting_id, status="pending")

    async def mark_running(self, meeting_id: uuid.UUID) -> StoredSummary:
        return self._row(meeting_id, status="running")

    async def mark_ready(self, meeting_id: uuid.UUID, *, text: str, model: str) -> StoredSummary:
        return self._row(meeting_id, status="ready", text=text, model=model)

    async def mark_failed(self, meeting_id: uuid.UUID, *, error: str) -> StoredSummary:
        return self._row(meeting_id, status="failed", error=error)

    async def get_by_meeting_id(self, meeting_id: uuid.UUID) -> StoredSummary | None:
        return self.rows.get(meeting_id)

    async def list_running(self) -> list[StoredSummary]:
        return [row for row in self.rows.values() if row.status == "running"]


class _FakeTranscriptRepository:
    def __init__(self, transcript: StoredTranscript | None) -> None:
        self._transcript = transcript

    async def get_by_meeting_id(self, meeting_id: uuid.UUID) -> StoredTranscript | None:
        return self._transcript


def _transcript(raw_text: str) -> StoredTranscript:
    return StoredTranscript(
        id=uuid.uuid4(),
        meeting_id=MEETING_ID,
        raw_text=raw_text,
        diarized_segments=[],
        language="he",
        created_at=datetime.now(UTC),
    )


def _service(
    *,
    transcript: StoredTranscript | None,
    summarizer: Summarizer,
    summaries: _FakeSummaryRepository | None = None,
    max_transcript_chars: int = 100_000,
) -> tuple[SummaryService, _FakeSummaryRepository]:
    repo = summaries or _FakeSummaryRepository()
    service = SummaryService(
        summaries=repo,  # type: ignore[arg-type]
        transcripts=_FakeTranscriptRepository(transcript),  # type: ignore[arg-type]
        summarizer=summarizer,
        max_transcript_chars=max_transcript_chars,
    )
    return service, repo


@pytest.mark.anyio
async def test_generate_marks_the_summary_ready_with_the_models_text() -> None:
    service, repo = _service(transcript=_transcript("מטפל: שלום."), summarizer=_FakeSummarizer())
    await repo.create_pending(MEETING_ID)

    await service.generate(MEETING_ID)

    row = repo.rows[MEETING_ID]
    assert row.status == "ready"
    assert row.text == HEBREW_SUMMARY
    assert row.model == "qwen2.5:7b-instruct"
    assert repo.transitions == ["pending", "running", "ready"]


@pytest.mark.anyio
async def test_generate_fails_an_over_long_transcript_without_calling_the_model() -> None:
    """Better a visible failure than a confident summary of the opening minutes."""
    summarizer = _FakeSummarizer()
    service, repo = _service(
        transcript=_transcript("א" * 501),
        summarizer=summarizer,
        max_transcript_chars=500,
    )

    await service.generate(MEETING_ID)

    assert summarizer.calls == []
    row = repo.rows[MEETING_ID]
    assert row.status == "failed"
    assert "exceeds" in (row.error or "")
    assert row.text is None


@pytest.mark.anyio
async def test_generate_records_a_model_failure_on_the_row() -> None:
    service, repo = _service(
        transcript=_transcript("מטפל: שלום."),
        summarizer=_FakeSummarizer(error=SummaryFailedError("connection refused")),
    )

    await service.generate(MEETING_ID)

    row = repo.rows[MEETING_ID]
    assert row.status == "failed"
    assert "connection refused" in (row.error or "")


@pytest.mark.anyio
async def test_generate_fails_when_there_is_no_transcript() -> None:
    service, repo = _service(transcript=None, summarizer=_FakeSummarizer())

    await service.generate(MEETING_ID)

    assert repo.rows[MEETING_ID].status == "failed"


@pytest.mark.anyio
async def test_generate_never_raises_into_the_background_task() -> None:
    """A background job has no caller to catch it, so an unexpected error must still land
    on the row rather than vanishing into the event loop."""
    service, repo = _service(
        transcript=_transcript("מטפל: שלום."),
        summarizer=_FakeSummarizer(error=RuntimeError("something unexpected")),
    )

    await service.generate(MEETING_ID)

    row = repo.rows[MEETING_ID]
    assert row.status == "failed"
    assert "something unexpected" in (row.error or "")


@pytest.mark.anyio
async def test_startup_sweep_fails_rows_stranded_by_a_restart() -> None:
    """BackgroundTasks die with the process. Without this, the therapist's client spins
    on a 'running' summary that nothing is generating."""
    repo = _FakeSummaryRepository()
    await repo.mark_running(MEETING_ID)

    await fail_interrupted_summaries(repo)  # type: ignore[arg-type]

    row = repo.rows[MEETING_ID]
    assert row.status == "failed"
    assert "restart" in (row.error or "")
