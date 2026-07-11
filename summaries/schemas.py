from typing import Self

from pydantic import BaseModel

from summaries.models import StoredSummary, SummaryStatus


class SummaryResponse(BaseModel):
    meeting_id: str
    status: SummaryStatus
    text: str | None = None
    model: str | None = None
    error: str | None = None

    @classmethod
    def from_summary(cls, summary: StoredSummary) -> Self:
        return cls(
            meeting_id=str(summary.meeting_id),
            status=summary.status,
            text=summary.text,
            model=summary.model or None,
            error=summary.error,
        )
