import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status

from summaries.dependencies import get_summary_reader
from summaries.repository import SummaryRepository
from summaries.schemas import SummaryResponse

router = APIRouter(prefix="/meetings", tags=["summaries"])


@router.get("/{meeting_id}/summary", response_model=SummaryResponse)
async def get_meeting_summary(
    meeting_id: uuid.UUID,
    response: Response,
    summaries: SummaryRepository = Depends(get_summary_reader),
) -> SummaryResponse:
    """Fetch the session summary.

    A failed summary is reported with 200 and an ``error``: the request succeeded, and
    it is the summary that failed. The therapist's client renders the reason.

    The summary is a drafting aid the therapist reviews. It is not a clinical record,
    and it must never be relied on to catch a risk disclosure.
    """
    summary = await summaries.get_by_meeting_id(meeting_id)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no summary for meeting {meeting_id}",
        )

    if summary.status in ("pending", "running"):
        response.status_code = status.HTTP_202_ACCEPTED

    return SummaryResponse.from_summary(summary)
