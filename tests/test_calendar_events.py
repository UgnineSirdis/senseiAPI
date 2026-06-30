import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from calendar_events.dependencies import get_calendar_event_service
from calendar_events.models import CalendarEvent, CalendarEventNotFoundError
from calendar_events.router import list_date_range_to_utc, resolve_list_date_range
from main import app
from tests.conftest import ClientFactory
from tests.database_helpers import get_database_url

THERAPIST_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
EVENT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_EVENT_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
OTHER_EVENT_ID2 = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
PATIENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
CREATED_AT = datetime(2026, 6, 25, 9, 0, tzinfo=UTC)
START_AT = datetime(2026, 6, 25, 10, 0, tzinfo=UTC)
END_AT = datetime(2026, 6, 25, 11, 0, tzinfo=UTC)
OTHER_START_AT = datetime(2026, 6, 26, 10, 0, tzinfo=UTC)
OTHER_END_AT = datetime(2026, 6, 26, 11, 0, tzinfo=UTC)
OTHER_START_AT2 = datetime(2026, 5, 9, 3, 0, tzinfo=UTC)
OTHER_END_AT2 = datetime(2026, 5, 9, 4, 0, tzinfo=UTC)


class _FakeCalendarEventService:
    def __init__(self) -> None:
        self._event_ids = {EVENT_ID, OTHER_EVENT_ID}
        self._events = [
            CalendarEvent(
                id=EVENT_ID,
                title="Meeting",
                description="Initial session",
                start_at=START_AT,
                end_at=END_AT,
                created_at=CREATED_AT,
                therapist_id=THERAPIST_ID,
                patient_id=PATIENT_ID,
            ),
            CalendarEvent(
                id=OTHER_EVENT_ID,
                title="Other meeting",
                description=None,
                start_at=OTHER_START_AT,
                end_at=OTHER_END_AT,
                created_at=CREATED_AT,
                therapist_id=THERAPIST_ID,
                patient_id=None,
            ),
            CalendarEvent(
                id=OTHER_EVENT_ID2,
                title="Other meeting 2",
                description=None,
                start_at=OTHER_START_AT2,
                end_at=OTHER_END_AT2,
                created_at=CREATED_AT,
                therapist_id=THERAPIST_ID,
                patient_id=None,
            ),
        ]

    async def add_event(
        self,
        *,
        title: str,
        start_at: datetime,
        end_at: datetime,
        description: str | None = None,
        patient_id: uuid.UUID | None = None,
    ) -> CalendarEvent:
        return CalendarEvent(
            id=EVENT_ID,
            title=title,
            description=description,
            start_at=start_at,
            end_at=end_at,
            created_at=CREATED_AT,
            therapist_id=THERAPIST_ID,
            patient_id=patient_id,
        )

    async def list_events(
        self,
        *,
        from_at: datetime,
        to_at: datetime,
    ) -> list[CalendarEvent]:
        return [event for event in self._events if from_at <= event.start_at < to_at]

    async def get_event(self, event_id: uuid.UUID) -> CalendarEvent:
        for event in self._events:
            if event.id == event_id:
                return event
        raise CalendarEventNotFoundError(event_id)

    async def update_event(self, event_id: uuid.UUID, updates: dict[str, object]) -> CalendarEvent:
        for index, event in enumerate(self._events):
            if event.id != event_id:
                continue
            start_at = event.start_at
            start_at_value = updates.get("start_at")
            if isinstance(start_at_value, datetime):
                start_at = start_at_value
            end_at = event.end_at
            end_at_value = updates.get("end_at")
            if isinstance(end_at_value, datetime):
                end_at = end_at_value
            patient_id = event.patient_id
            if "patient_id" in updates:
                patient_id_value = updates["patient_id"]
                if patient_id_value is None or isinstance(patient_id_value, uuid.UUID):
                    patient_id = patient_id_value
            updated = CalendarEvent(
                id=event.id,
                title=str(updates.get("title", event.title)),
                description=None
                if updates.get("description", event.description) is None
                else str(updates.get("description", event.description)),
                start_at=start_at,
                end_at=end_at,
                created_at=event.created_at,
                therapist_id=event.therapist_id,
                patient_id=patient_id,
            )
            self._events[index] = updated
            return updated
        raise CalendarEventNotFoundError(event_id)

    async def delete_event(self, event_id: uuid.UUID) -> None:
        if event_id not in self._event_ids:
            raise CalendarEventNotFoundError(event_id)
        self._event_ids.remove(event_id)


@pytest.fixture
def calendar_client(make_client: ClientFactory) -> TestClient:
    client, _ = make_client()
    app.dependency_overrides[get_calendar_event_service] = lambda: _FakeCalendarEventService()
    return client


def test_add_calendar_event_returns_201(calendar_client: TestClient) -> None:
    res = calendar_client.post(
        "/calendar",
        json={
            "title": "Session",
            "description": "Initial session",
            "start_at": START_AT.isoformat(),
            "end_at": END_AT.isoformat(),
            "patient_id": str(PATIENT_ID),
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["id"] == str(EVENT_ID)
    assert body["title"] == "Session"
    assert body["description"] == "Initial session"
    assert body["patient_id"] == str(PATIENT_ID)


def test_allow_add_calendar_event_without_patient(calendar_client: TestClient) -> None:
    res = calendar_client.post(
        "/calendar",
        json={
            "title": "Admin",
            "start_at": START_AT.isoformat(),
            "end_at": END_AT.isoformat(),
        },
    )
    assert res.status_code == 201
    assert res.json()["patient_id"] is None


def test_add_calendar_event_uses_time_zone_for_naive_datetimes(
    calendar_client: TestClient,
) -> None:
    res = calendar_client.post(
        "/calendar?time_zone=Europe/Paris",
        json={
            "title": "Session",
            "start_at": "2026-05-09T05:00:00",
            "end_at": "2026-05-09T06:00:00",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["start_at"] == "2026-05-09T05:00:00+02:00"
    assert body["end_at"] == "2026-05-09T06:00:00+02:00"


def test_add_calendar_event_rejects_empty_title(calendar_client: TestClient) -> None:
    res = calendar_client.post(
        "/calendar",
        json={
            "title": "",
            "start_at": START_AT.isoformat(),
            "end_at": END_AT.isoformat(),
        },
    )
    assert res.status_code == 422


def test_list_calendar_events_returns_all_events(calendar_client: TestClient) -> None:
    res = calendar_client.get("/calendar?from=2026-06-25&to=2026-06-26")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 2
    assert body[0]["id"] == str(EVENT_ID)
    assert body[1]["patient_id"] is None


def test_list_calendar_events_filters_by_date_range(calendar_client: TestClient) -> None:
    res = calendar_client.get("/calendar?from=2026-06-26&to=2026-06-26")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["id"] == str(OTHER_EVENT_ID)


def test_list_calendar_events_filters_and_prints_in_time_zone(
    calendar_client: TestClient,
) -> None:
    res = calendar_client.get("/calendar?from=2026-05-08&to=2026-05-08&time_zone=America/New_York")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["id"] == str(OTHER_EVENT_ID2)
    assert body[0]["start_at"] == "2026-05-08T23:00:00-04:00"


def test_list_calendar_events_rejects_invalid_date_range(calendar_client: TestClient) -> None:
    res = calendar_client.get("/calendar?from=2026-06-27&to=2026-06-26")
    assert res.status_code == 400
    assert res.json()["detail"] == "'from' must be on or before 'to'"


def test_list_calendar_events_rejects_invalid_time_zone(calendar_client: TestClient) -> None:
    res = calendar_client.get("/calendar?time_zone=bad-zone")
    assert res.status_code == 400
    assert res.json()["detail"] == "invalid time_zone"


@pytest.mark.parametrize(
    ("from_date", "to_date", "today", "expected"),
    [
        (None, None, date(2026, 6, 24), (date(2026, 6, 21), date(2026, 6, 27))),
        (date(2026, 6, 25), None, None, (date(2026, 6, 25), date(2026, 7, 1))),
        (None, date(2026, 6, 25), None, (date(2026, 6, 19), date(2026, 6, 25))),
        (date(2026, 1, 1), date(2027, 2, 1), None, (date(2026, 1, 1), date(2027, 1, 1))),
    ],
)
def test_resolve_list_date_range_defaults(
    from_date: date | None,
    to_date: date | None,
    today: date | None,
    expected: tuple[date, date],
) -> None:
    assert resolve_list_date_range(from_date, to_date, today=today) == expected


def test_list_date_range_to_utc_uses_time_zone_boundaries() -> None:
    assert list_date_range_to_utc(
        date(2026, 5, 8),
        date(2026, 5, 8),
        ZoneInfo("America/New_York"),
    ) == (
        datetime(2026, 5, 8, 4, 0, tzinfo=UTC),
        datetime(2026, 5, 9, 4, 0, tzinfo=UTC),
    )


def test_get_calendar_event_returns_200(calendar_client: TestClient) -> None:
    res = calendar_client.get(f"/calendar/{EVENT_ID}")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == str(EVENT_ID)
    assert body["title"] == "Meeting"


def test_get_calendar_event_prints_in_time_zone(calendar_client: TestClient) -> None:
    res = calendar_client.get(f"/calendar/{OTHER_EVENT_ID2}?time_zone=America/New_York")
    assert res.status_code == 200
    assert res.json()["start_at"] == "2026-05-08T23:00:00-04:00"


def test_get_calendar_event_missing_returns_404(calendar_client: TestClient) -> None:
    missing_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    res = calendar_client.get(f"/calendar/{missing_id}")
    assert res.status_code == 404


def test_update_calendar_event_returns_200(calendar_client: TestClient) -> None:
    res = calendar_client.patch(
        f"/calendar/{EVENT_ID}",
        json={"title": "Updated session", "description": None},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Updated session"
    assert body["description"] is None


def test_update_calendar_event_uses_time_zone_for_naive_datetimes(
    calendar_client: TestClient,
) -> None:
    res = calendar_client.patch(
        f"/calendar/{EVENT_ID}?time_zone=America/New_York",
        json={
            "start_at": "2026-05-08T23:00:00",
            "end_at": "2026-05-09T00:00:00",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["start_at"] == "2026-05-08T23:00:00-04:00"
    assert body["end_at"] == "2026-05-09T00:00:00-04:00"


def test_update_calendar_event_missing_returns_404(calendar_client: TestClient) -> None:
    missing_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    res = calendar_client.patch(
        f"/calendar/{missing_id}",
        json={"title": "Updated session"},
    )
    assert res.status_code == 404


def test_update_calendar_event_rejects_empty_body(calendar_client: TestClient) -> None:
    res = calendar_client.patch(f"/calendar/{EVENT_ID}", json={})
    assert res.status_code == 422


def test_delete_calendar_event_returns_204(calendar_client: TestClient) -> None:
    res = calendar_client.delete(f"/calendar/{EVENT_ID}")
    assert res.status_code == 204
    assert res.content == b""


def test_delete_calendar_event_missing_returns_404(calendar_client: TestClient) -> None:
    missing_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    res = calendar_client.delete(f"/calendar/{missing_id}")
    assert res.status_code == 404


@pytest.mark.integration
def test_calendar_database(make_client: ClientFactory) -> None:
    with get_database_url() as database_url:
        client, _ = make_client(database_url=database_url)
        with client:
            initial_empty_list = client.get("/calendar")
            assert initial_empty_list.status_code == 200
            assert initial_empty_list.json() == []

            created = client.post(
                "/calendar",
                json={
                    "title": "Meeting",
                    "description": "Initial notes",
                    "start_at": START_AT.isoformat(),
                    "end_at": END_AT.isoformat(),
                    "patient_id": str(PATIENT_ID),
                },
            )
            assert created.status_code == 201
            created_body = created.json()
            event_id = created_body["id"]

            listed = client.get("/calendar?from=2026-06-25&to=2026-06-25")
            assert listed.status_code == 200
            listed_body = listed.json()
            assert len(listed_body) == 1
            assert listed_body[0]["id"] == event_id
            assert listed_body[0]["title"] == "Meeting"

            updated = client.patch(
                f"/calendar/{event_id}",
                json={
                    "title": "Updated meeting",
                    "description": None,
                    "start_at": OTHER_START_AT.isoformat(),
                    "end_at": OTHER_END_AT.isoformat(),
                    "patient_id": None,
                },
            )
            assert updated.status_code == 200

            fetched = client.get(f"/calendar/{event_id}")
            assert fetched.status_code == 200
            fetched_body = fetched.json()
            assert fetched_body["id"] == event_id
            assert fetched_body["title"] == "Updated meeting"
            assert fetched_body["description"] is None
            assert fetched_body["start_at"] == "2026-06-26T13:00:00+03:00"
            assert fetched_body["end_at"] == "2026-06-26T14:00:00+03:00"
            assert fetched_body["patient_id"] is None

            deleted = client.delete(f"/calendar/{event_id}")
            assert deleted.status_code == 204
            assert deleted.content == b""

            final_empty_list = client.get("/calendar?from=2026-06-26&to=2026-06-26")
            assert final_empty_list.status_code == 200
            assert final_empty_list.json() == []


@pytest.mark.integration
def test_calendar_database_lists_event_by_requested_time_zone(
    make_client: ClientFactory,
) -> None:
    with get_database_url() as database_url:
        client, _ = make_client(database_url=database_url)
        with client:
            created = client.post(
                "/calendar?time_zone=Asia/Jerusalem",
                json={
                    "title": "Meeting",
                    "start_at": "2026-06-25T04:00:00",
                    "end_at": "2026-06-25T05:00:00",
                },
            )
            assert created.status_code == 201
            event_id = created.json()["id"]

            listed = client.get(
                "/calendar?from=2026-06-24&to=2026-06-24&time_zone=America/New_York"
            )
            assert listed.status_code == 200
            body = listed.json()
            assert len(body) == 1
            assert body[0]["id"] == event_id
            assert body[0]["start_at"] == "2026-06-24T21:00:00-04:00"


@pytest.mark.integration
def test_calendar_database_intervals_intersection(
    make_client: ClientFactory,
) -> None:
    with get_database_url() as database_url:
        client, _ = make_client(database_url=database_url)
        with client:
            created = client.post(
                "/calendar",
                json={
                    "title": "Conference",
                    "start_at": "2026-06-22T09:00:00+03:00",
                    "end_at": "2026-06-29T09:00:00+03:00",
                },
            )
            assert created.status_code == 201
            event_id = created.json()["id"]

            one_day = client.get("/calendar?from=2026-06-25&to=2026-06-25")
            assert one_day.status_code == 200
            one_day_body = one_day.json()
            assert len(one_day_body) == 1
            assert one_day_body[0]["id"] == event_id

            partial_overlap = client.get("/calendar?from=2026-06-27&to=2026-07-01")
            assert partial_overlap.status_code == 200
            partial_overlap_body = partial_overlap.json()
            assert len(partial_overlap_body) == 1
            assert partial_overlap_body[0]["id"] == event_id

            earlier_partial_overlap = client.get("/calendar?from=2026-06-20&to=2026-06-22")
            assert earlier_partial_overlap.status_code == 200
            earlier_partial_overlap_body = earlier_partial_overlap.json()
            assert len(earlier_partial_overlap_body) == 1
            assert earlier_partial_overlap_body[0]["id"] == event_id

            interval_includes_all_meeting = client.get("/calendar?from=2026-06-20&to=2026-06-22")
            assert interval_includes_all_meeting.status_code == 200
            interval_includes_all_meeting_body = interval_includes_all_meeting.json()
            assert len(interval_includes_all_meeting_body) == 1
            assert interval_includes_all_meeting_body[0]["id"] == event_id


@pytest.mark.integration
def test_calendar_database_intervals_intersection_boundaries(
    make_client: ClientFactory,
) -> None:
    with get_database_url() as database_url:
        client, _ = make_client(database_url=database_url)
        with client:
            event_ids = []
            for event in [
                {
                    "title": "Meeting 1",
                    "start_at": "2026-01-01T22:00:00+02:00",
                    "end_at": "2026-01-02T00:00:00+02:00",
                },
                {
                    "title": "Meeting 2",
                    "start_at": "2026-01-02T00:00:00+02:00",
                    "end_at": "2026-01-02T02:00:00+02:00",
                },
                {
                    "title": "Meeting 3",
                    "start_at": "2026-01-03T00:00:00+02:00",
                    "end_at": "2026-01-03T02:00:00+02:00",
                },
            ]:
                created = client.post("/calendar", json=event)
                assert created.status_code == 201
                event_ids.append(created.json()["id"])

            listed = client.get("/calendar?from=2026-01-02&to=2026-01-02")
            assert listed.status_code == 200
            body = listed.json()
            assert len(body) == 1
            assert body[0]["id"] == event_ids[1]
            assert body[0]["title"] == "Meeting 2"
            assert body[0]["start_at"] == "2026-01-02T00:00:00+02:00"
            assert body[0]["end_at"] == "2026-01-02T02:00:00+02:00"
