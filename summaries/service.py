import logging
import uuid
from typing import TYPE_CHECKING

from core.database import get_sessionmaker
from summaries.models import StoredSummary, SummaryFailedError
from summaries.repository import SummaryRepository
from summaries.summarizer import Summarizer
from transcripts.repository import TranscriptRepository

if TYPE_CHECKING:
    from core.config import Settings

logger = logging.getLogger(__name__)


async def sweep_interrupted_summaries(settings: "Settings") -> None:
    """Startup hook: rescue rows stranded in ``running`` by a restart."""
    if not settings.database_url or not settings.summary_enabled:
        return

    sessionmaker = get_sessionmaker(settings.database_url)
    async with sessionmaker() as session:
        await fail_interrupted_summaries(SummaryRepository(session))


async def fail_interrupted_summaries(summaries: SummaryRepository) -> int:
    """Mark summaries stranded mid-generation by a server restart as failed.

    ``BackgroundTasks`` run in-process and die with it. Without this sweep a killed job
    leaves its row in ``running`` forever, and the therapist's client spins on a summary
    that nothing is generating. Run once at startup.
    """
    stranded = await summaries.list_running()
    for summary in stranded:
        await summaries.mark_failed(
            summary.meeting_id,
            error="generation was interrupted by a server restart",
        )
    if stranded:
        logger.warning("failed %d summaries interrupted by restart", len(stranded))
    return len(stranded)


class SummaryService:
    """Generates a session summary from a stored transcript.

    ``generate`` runs as a background task, so it has no HTTP response to carry a
    failure home on. Every terminal state is written to the summary row instead.
    """

    def __init__(
        self,
        *,
        summaries: SummaryRepository,
        transcripts: TranscriptRepository,
        summarizer: Summarizer,
        max_transcript_chars: int,
    ) -> None:
        self._summaries = summaries
        self._transcripts = transcripts
        self._summarizer = summarizer
        self._max_transcript_chars = max_transcript_chars

    async def create_pending(self, meeting_id: uuid.UUID) -> StoredSummary:
        return await self._summaries.create_pending(meeting_id)

    async def generate(self, meeting_id: uuid.UUID) -> None:
        transcript = await self._transcripts.get_by_meeting_id(meeting_id)
        if transcript is None:
            await self._summaries.mark_failed(meeting_id, error="no transcript for this meeting")
            return

        # Ollama truncates silently past its context window, so an over-long transcript
        # would come back as a fluent summary of the opening minutes with no error at
        # all. Fail where the therapist can see it instead of summarising a fragment.
        if len(transcript.raw_text) > self._max_transcript_chars:
            await self._summaries.mark_failed(
                meeting_id,
                error=(
                    f"transcript exceeds the context window "
                    f"({len(transcript.raw_text)} chars > {self._max_transcript_chars})"
                ),
            )
            return

        await self._summaries.mark_running(meeting_id)

        try:
            summary = await self._summarizer.summarize(
                text=transcript.raw_text,
                language=transcript.language,
            )
        except SummaryFailedError as exc:
            await self._summaries.mark_failed(meeting_id, error=str(exc))
            return
        except Exception as exc:
            # Nothing is awaiting this task, so an escaping error would disappear into the
            # event loop and strand the row in "running" forever.
            logger.error("summary generation failed", exc_info=exc)
            await self._summaries.mark_failed(meeting_id, error=str(exc))
            return

        await self._summaries.mark_ready(meeting_id, text=summary.text, model=summary.model)
