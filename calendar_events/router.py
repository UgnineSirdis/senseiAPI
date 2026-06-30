import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from calendar_events.dependencies import get_calendar_event_service
from calendar_events.models import CalendarEventNotFoundError
from calendar_events.schemas import CalendarEventCreate, CalendarEventOut, CalendarEventUpdate
from calendar_events.service import CalendarEventService

logger = logging.getLogger(__name__)
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
WEEK = timedelta(days=6)
YEAR = timedelta(days=365)

router = APIRouter(prefix="/calendar", tags=["calendar"])


def get_time_zone(time_zone: str) -> ZoneInfo:
    try:
        return ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid time_zone",
        ) from exc


def in_utc(value: datetime, time_zone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=time_zone)
    return value.astimezone(UTC)


def list_date_range_to_utc(
    from_date: date,
    to_date: date,
    time_zone: ZoneInfo,
) -> tuple[datetime, datetime]:
    from_at = datetime.combine(from_date, datetime.min.time(), tzinfo=time_zone)
    to_exclusive = datetime.combine(
        to_date + timedelta(days=1),
        datetime.min.time(),
        tzinfo=time_zone,
    )
    return from_at.astimezone(UTC), to_exclusive.astimezone(UTC)


def resolve_list_date_range(
    from_date: date | None,
    to_date: date | None,
    *,
    time_zone: ZoneInfo = ISRAEL_TZ,
    today: date | None = None,
) -> tuple[date, date]:
    if from_date is None and to_date is None:
        current_date = today or datetime.now(time_zone).date()
        sunday = current_date - timedelta(days=(current_date.weekday() + 1) % 7)
        return sunday, sunday + WEEK
    if from_date is None:
        assert to_date is not None
        from_date = to_date - WEEK
        return from_date, to_date
    if to_date is None:
        to_date = from_date + WEEK
        return from_date, to_date
    if from_date > to_date:
        raise ValueError("'from' must be on or before 'to'")
    if to_date - from_date > YEAR:
        to_date = from_date + YEAR
    return from_date, to_date


@router.post("", response_model=CalendarEventOut, status_code=status.HTTP_201_CREATED)
async def add_event(
    payload: CalendarEventCreate,
    time_zone: Annotated[str, Query()] = ISRAEL_TZ.key,
    service: CalendarEventService = Depends(get_calendar_event_service),
) -> CalendarEventOut:
    zone_info = get_time_zone(time_zone)
    try:
        event = await service.add_event(
            title=payload.title,
            description=payload.description,
            start_at=in_utc(payload.start_at, zone_info),
            end_at=in_utc(payload.end_at, zone_info),
            patient_id=payload.patient_id,
        )
    except SQLAlchemyError as exc:
        logger.error("failed to create calendar event", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to create calendar event",
        ) from exc
    return CalendarEventOut.from_event(event, time_zone=zone_info)


@router.get("", response_model=list[CalendarEventOut])
async def list_events(
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    time_zone: Annotated[str, Query()] = ISRAEL_TZ.key,
    service: CalendarEventService = Depends(get_calendar_event_service),
) -> list[CalendarEventOut]:
    zone_info = get_time_zone(time_zone)
    try:
        resolved_from, resolved_to = resolve_list_date_range(
            from_date,
            to_date,
            time_zone=zone_info,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    from_at, to_at = list_date_range_to_utc(resolved_from, resolved_to, zone_info)
    try:
        events = await service.list_events(
            from_at=from_at,
            to_at=to_at,
        )
    except SQLAlchemyError as exc:
        logger.error("failed to list calendar events", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to list calendar events",
        ) from exc
    return [CalendarEventOut.from_event(event, time_zone=zone_info) for event in events]


@router.get("/{event_id}", response_model=CalendarEventOut)
async def get_event(
    event_id: uuid.UUID,
    time_zone: Annotated[str, Query()] = ISRAEL_TZ.key,
    service: CalendarEventService = Depends(get_calendar_event_service),
) -> CalendarEventOut:
    zone_info = get_time_zone(time_zone)
    try:
        event = await service.get_event(event_id)
    except CalendarEventNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        logger.error("failed to get calendar event", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to get calendar event",
        ) from exc
    return CalendarEventOut.from_event(event, time_zone=zone_info)


@router.patch("/{event_id}", response_model=CalendarEventOut)
async def update_event(
    event_id: uuid.UUID,
    payload: CalendarEventUpdate,
    time_zone: Annotated[str, Query()] = ISRAEL_TZ.key,
    service: CalendarEventService = Depends(get_calendar_event_service),
) -> CalendarEventOut:
    zone_info = get_time_zone(time_zone)
    updates = payload.model_dump(exclude_unset=True)
    if payload.start_at is not None:
        updates["start_at"] = in_utc(payload.start_at, zone_info)
    if payload.end_at is not None:
        updates["end_at"] = in_utc(payload.end_at, zone_info)
    try:
        event = await service.update_event(
            event_id,
            updates,
        )
    except CalendarEventNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        logger.error("failed to update calendar event", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to update calendar event",
        ) from exc
    return CalendarEventOut.from_event(event, time_zone=zone_info)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    service: CalendarEventService = Depends(get_calendar_event_service),
) -> None:
    try:
        await service.delete_event(event_id)
    except CalendarEventNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        logger.error("failed to delete calendar event", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to delete calendar event",
        ) from exc
