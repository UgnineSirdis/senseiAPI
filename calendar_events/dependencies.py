from calendar_events.repository import CalendarEventRepository
from calendar_events.service import CalendarEventService
from core.database import SessionDep


def get_calendar_event_service(session: SessionDep) -> CalendarEventService:
    return CalendarEventService(CalendarEventRepository(session))
