import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from calendar_events.orm import CalendarEventRecord
from tests.conftest import DEFAULT_TRANSCRIPT, ClientFactory
from tests.database_helpers import get_database_url
from transcripts.orm import TranscriptRecord


@pytest.mark.integration
def test_upload_persists_transcript_for_calendar_event(make_client: ClientFactory) -> None:
    with get_database_url() as database_url:
        client, _ = make_client(database_url=database_url)
        with client:
            patient_res = client.post(
                "/patients",
                json={"name": "Test Patient", "phone": "050-0000000"},
            )
            assert patient_res.status_code == 201
            patient_id = patient_res.json()["id"]

            start = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
            event_res = client.post(
                "/calendar",
                json={
                    "title": "Test Patient",
                    "start_at": start.isoformat(),
                    "end_at": (start + timedelta(minutes=50)).isoformat(),
                    "patient_id": patient_id,
                },
            )
            assert event_res.status_code == 201
            meeting_id = event_res.json()["id"]

            res = client.post(
                "/audio/upload",
                files={"file": ("song.mp3", b"fake-audio-bytes", "audio/mpeg")},
                data={
                    "patient_id": patient_id,
                    "meeting_id": meeting_id,
                },
            )
            assert res.status_code == 201
            body = res.json()
            assert body["text"] == DEFAULT_TRANSCRIPT
            assert body["meeting_id"] == meeting_id
            assert body["transcript_id"]
            transcript_id = uuid.UUID(body["transcript_id"])

            # Second upload for same meeting must conflict (1:1).
            dup = client.post(
                "/audio/upload",
                files={"file": ("song2.mp3", b"fake-audio-bytes-2", "audio/mpeg")},
                data={
                    "patient_id": patient_id,
                    "meeting_id": meeting_id,
                },
            )
            assert dup.status_code == 409

        async def _assert_rows() -> None:
            engine = create_async_engine(database_url)
            sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
            async with sessionmaker() as session:
                meeting = await session.get(CalendarEventRecord, uuid.UUID(meeting_id))
                assert meeting is not None
                assert meeting.patient_id == uuid.UUID(patient_id)

                result = await session.execute(
                    select(TranscriptRecord).where(TranscriptRecord.id == transcript_id)
                )
                transcript = result.scalar_one()
                assert transcript.meeting_id == uuid.UUID(meeting_id)
                assert transcript.raw_text == DEFAULT_TRANSCRIPT
                assert transcript.language == "he"
            await engine.dispose()

        asyncio.run(_assert_rows())


@pytest.mark.integration
def test_upload_unknown_meeting_returns_404(make_client: ClientFactory) -> None:
    with get_database_url() as database_url:
        client, _ = make_client(database_url=database_url)
        with client:
            res = client.post(
                "/audio/upload",
                files={"file": ("song.mp3", b"fake-audio-bytes", "audio/mpeg")},
                data={"meeting_id": str(uuid.uuid4())},
            )
            assert res.status_code == 404
