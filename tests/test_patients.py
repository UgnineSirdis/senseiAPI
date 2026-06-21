import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from core.database import close_database
from main import app
from patients.dependencies import get_patient_service
from patients.models import Patient, PatientNotFoundError
from tests.conftest import ClientFactory

THERAPIST_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_THERAPIST_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
PATIENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_PATIENT_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
CREATED_AT = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
OTHER_CREATED_AT = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


class _FakePatientService:
    def __init__(self) -> None:
        self._patient_ids = {PATIENT_ID}
        self._patients = [
            Patient(
                id=PATIENT_ID,
                name="Jane Doe",
                phone="050-1234567",
                created_at=CREATED_AT,
                therapist_id=THERAPIST_ID,
            ),
            Patient(
                id=OTHER_PATIENT_ID,
                name="John Smith",
                phone="052-9876543",
                created_at=OTHER_CREATED_AT,
                therapist_id=OTHER_THERAPIST_ID,
            ),
        ]

    async def add_patient(self, *, name: str, phone: str, therapist_id: uuid.UUID) -> Patient:
        return Patient(
            id=PATIENT_ID,
            name=name,
            phone=phone,
            created_at=CREATED_AT,
            therapist_id=therapist_id,
        )

    async def list_patients_by_therapist(self, therapist_id: uuid.UUID) -> list[Patient]:
        return [patient for patient in self._patients if patient.therapist_id == therapist_id]

    async def delete_patient(self, patient_id: uuid.UUID) -> None:
        if patient_id not in self._patient_ids:
            raise PatientNotFoundError(patient_id)
        self._patient_ids.remove(patient_id)


@pytest.fixture
def patient_client(make_client: ClientFactory) -> TestClient:
    client, _ = make_client()
    app.dependency_overrides[get_patient_service] = lambda: _FakePatientService()
    return client


def test_add_patient_returns_201(patient_client: TestClient) -> None:
    res = patient_client.post(
        "/patients",
        json={
            "name": "Jane Doe",
            "phone": "050-1234567",
            "therapist_id": str(THERAPIST_ID),
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["id"] == "22222222-2222-2222-2222-222222222222"
    assert body["name"] == "Jane Doe"
    assert body["phone"] == "050-1234567"
    assert body["therapist_id"] == str(THERAPIST_ID)
    assert body["created_at"] is not None


def test_add_patient_rejects_empty_name(patient_client: TestClient) -> None:
    res = patient_client.post(
        "/patients",
        json={"name": "", "phone": "050-1234567", "therapist_id": str(THERAPIST_ID)},
    )
    assert res.status_code == 422


def test_add_patient_rejects_invalid_therapist_id(patient_client: TestClient) -> None:
    res = patient_client.post(
        "/patients",
        json={"name": "Jane Doe", "phone": "050-1234567", "therapist_id": "not-a-uuid"},
    )
    assert res.status_code == 422


def test_delete_patient_returns_204(patient_client: TestClient) -> None:
    res = patient_client.delete(f"/patients/{PATIENT_ID}")
    assert res.status_code == 204
    assert res.content == b""


def test_delete_patient_missing_returns_404(patient_client: TestClient) -> None:
    missing_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    res = patient_client.delete(f"/patients/{missing_id}")
    assert res.status_code == 404


def test_delete_patient_rejects_invalid_id(patient_client: TestClient) -> None:
    res = patient_client.delete("/patients/not-a-uuid")
    assert res.status_code == 422


def test_list_patients_returns_matching_patients(patient_client: TestClient) -> None:
    res = patient_client.get("/patients", params={"therapist_id": str(THERAPIST_ID)})
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["id"] == str(PATIENT_ID)
    assert body[0]["name"] == "Jane Doe"
    assert body[0]["therapist_id"] == str(THERAPIST_ID)


def test_list_patients_returns_empty_for_unknown_therapist(patient_client: TestClient) -> None:
    unknown_id = uuid.UUID("99999999-9999-9999-9999-999999999999")
    res = patient_client.get("/patients", params={"therapist_id": str(unknown_id)})
    assert res.status_code == 200
    assert res.json() == []


def test_list_patients_rejects_invalid_therapist_id(patient_client: TestClient) -> None:
    res = patient_client.get("/patients", params={"therapist_id": "not-a-uuid"})
    assert res.status_code == 422


@pytest.mark.integration
def test_list_patients_persists_in_database(make_client: ClientFactory) -> None:
    from tests.database_helpers import get_database_url, prepare_database

    with get_database_url() as database_url:
        prepare_database(database_url)
        try:
            client, _ = make_client(database_url=database_url)
            other_therapist_id = uuid.UUID("66666666-6666-6666-6666-666666666666")

            for name, therapist_id in [
                ("Alice", THERAPIST_ID),
                ("Bob", THERAPIST_ID),
                ("Charlie", other_therapist_id),
            ]:
                res = client.post(
                    "/patients",
                    json={
                        "name": name,
                        "phone": "050-0000000",
                        "therapist_id": str(therapist_id),
                    },
                )
                assert res.status_code == 201

            list_res = client.get("/patients", params={"therapist_id": str(THERAPIST_ID)})
            assert list_res.status_code == 200
            names = {patient["name"] for patient in list_res.json()}
            assert names == {"Alice", "Bob"}
        finally:
            asyncio.run(close_database(database_url))


@pytest.mark.integration
def test_delete_patient_persists_in_database(make_client: ClientFactory) -> None:
    from tests.database_helpers import get_database_url, prepare_database

    with get_database_url() as database_url:
        prepare_database(database_url)
        try:
            client, _ = make_client(database_url=database_url)
            create_res = client.post(
                "/patients",
                json={
                    "name": "John Smith",
                    "phone": "052-9876543",
                    "therapist_id": str(THERAPIST_ID),
                },
            )
            assert create_res.status_code == 201
            patient_id = create_res.json()["id"]

            delete_res = client.delete(f"/patients/{patient_id}")
            assert delete_res.status_code == 204

            delete_again_res = client.delete(f"/patients/{patient_id}")
            assert delete_again_res.status_code == 404
        finally:
            asyncio.run(close_database(database_url))


@pytest.mark.integration
def test_add_patient_persists_in_database(make_client: ClientFactory) -> None:
    from tests.database_helpers import get_database_url, prepare_database

    with get_database_url() as database_url:
        prepare_database(database_url)
        try:
            client, _ = make_client(database_url=database_url)
            res = client.post(
                "/patients",
                json={
                    "name": "John Smith",
                    "phone": "052-9876543",
                    "therapist_id": str(THERAPIST_ID),
                },
            )
            assert res.status_code == 201
            body = res.json()
            assert body["name"] == "John Smith"
            assert body["phone"] == "052-9876543"
            assert body["therapist_id"] == str(THERAPIST_ID)
            assert uuid.UUID(body["id"])
        finally:
            asyncio.run(close_database(database_url))
