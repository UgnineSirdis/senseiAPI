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

PATIENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_PATIENT_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
CREATED_AT = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
OTHER_CREATED_AT = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


class _FakePatientService:
    def __init__(self) -> None:
        self._patient_ids = {PATIENT_ID, OTHER_PATIENT_ID}
        self._patients = [
            Patient(
                id=PATIENT_ID,
                name="Jane Doe",
                phone="050-1234567",
                email="jane@example.com",
                created_at=CREATED_AT,
            ),
            Patient(
                id=OTHER_PATIENT_ID,
                name="John Smith",
                phone="052-9876543",
                email=None,
                created_at=OTHER_CREATED_AT,
            ),
        ]

    async def add_patient(
        self,
        *,
        name: str,
        phone: str,
        email: str | None = None,
    ) -> Patient:
        return Patient(
            id=PATIENT_ID,
            name=name,
            phone=phone,
            email=email,
            created_at=CREATED_AT,
        )

    async def list_patients(self) -> list[Patient]:
        return list(self._patients)

    async def update_patient(self, patient_id: uuid.UUID, updates: dict[str, object]) -> Patient:
        for index, patient in enumerate(self._patients):
            if patient.id != patient_id:
                continue
            phone = str(updates["phone"]) if "phone" in updates else patient.phone
            email_value = updates.get("email", patient.email)
            email = None if email_value is None else str(email_value)
            updated = Patient(
                id=patient.id,
                name=patient.name,
                phone=phone,
                email=email,
                created_at=patient.created_at,
            )
            self._patients[index] = updated
            return updated
        raise PatientNotFoundError(patient_id)

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
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["id"] == "22222222-2222-2222-2222-222222222222"
    assert body["name"] == "Jane Doe"
    assert body["phone"] == "050-1234567"
    assert body["created_at"] is not None
    assert body["email"] is None


def test_add_patient_with_email_returns_email(patient_client: TestClient) -> None:
    res = patient_client.post(
        "/patients",
        json={
            "name": "Jane Doe",
            "phone": "050-1234567",
            "email": "jane@example.com",
        },
    )
    assert res.status_code == 201
    assert res.json()["email"] == "jane@example.com"


def test_add_patient_without_email_returns_null(patient_client: TestClient) -> None:
    res = patient_client.post(
        "/patients",
        json={
            "name": "Jane Doe",
            "phone": "050-1234567",
        },
    )
    assert res.status_code == 201
    assert res.json()["email"] is None


def test_add_patient_rejects_invalid_email(patient_client: TestClient) -> None:
    res = patient_client.post(
        "/patients",
        json={
            "name": "Jane Doe",
            "phone": "050-1234567",
            "email": "not-an-email",
        },
    )
    assert res.status_code == 422


def test_add_patient_rejects_empty_name(patient_client: TestClient) -> None:
    res = patient_client.post(
        "/patients",
        json={"name": "", "phone": "050-1234567"},
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


def test_list_patients_returns_all_patients(patient_client: TestClient) -> None:
    res = patient_client.get("/patients")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 2
    assert body[0]["id"] == str(PATIENT_ID)
    assert body[0]["name"] == "Jane Doe"
    assert body[0]["email"] == "jane@example.com"
    assert body[1]["id"] == str(OTHER_PATIENT_ID)


def test_update_patient_phone_returns_200(patient_client: TestClient) -> None:
    res = patient_client.patch(
        f"/patients/{PATIENT_ID}",
        json={"phone": "050-9999999"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["phone"] == "050-9999999"
    assert body["email"] == "jane@example.com"


def test_update_patient_email_returns_200(patient_client: TestClient) -> None:
    res = patient_client.patch(
        f"/patients/{OTHER_PATIENT_ID}",
        json={"email": "john@example.com"},
    )
    assert res.status_code == 200
    assert res.json()["email"] == "john@example.com"


def test_update_patient_clears_email(patient_client: TestClient) -> None:
    res = patient_client.patch(
        f"/patients/{PATIENT_ID}",
        json={"email": None},
    )
    assert res.status_code == 200
    assert res.json()["email"] is None


def test_update_patient_missing_returns_404(patient_client: TestClient) -> None:
    missing_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    res = patient_client.patch(
        f"/patients/{missing_id}",
        json={"phone": "050-9999999"},
    )
    assert res.status_code == 404


def test_update_patient_rejects_empty_body(patient_client: TestClient) -> None:
    res = patient_client.patch(f"/patients/{PATIENT_ID}", json={})
    assert res.status_code == 422


def test_update_patient_rejects_invalid_email(patient_client: TestClient) -> None:
    res = patient_client.patch(
        f"/patients/{PATIENT_ID}",
        json={"email": "not-an-email"},
    )
    assert res.status_code == 422


@pytest.mark.integration
def test_update_patient_persists_in_database(make_client: ClientFactory) -> None:
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
                    "email": "john@example.com",
                },
            )
            assert create_res.status_code == 201
            patient_id = create_res.json()["id"]

            update_res = client.patch(
                f"/patients/{patient_id}",
                json={"phone": "050-1111111", "email": "updated@example.com"},
            )
            assert update_res.status_code == 200
            body = update_res.json()
            assert body["phone"] == "050-1111111"
            assert body["email"] == "updated@example.com"
        finally:
            asyncio.run(close_database(database_url))


@pytest.mark.integration
def test_list_patients_persists_in_database(make_client: ClientFactory) -> None:
    from tests.database_helpers import get_database_url, prepare_database

    with get_database_url() as database_url:
        prepare_database(database_url)
        try:
            client, _ = make_client(database_url=database_url)

            for name in ["Alice", "Bob", "Charlie"]:
                res = client.post(
                    "/patients",
                    json={
                        "name": name,
                        "phone": "050-0000000",
                    },
                )
                assert res.status_code == 201

            list_res = client.get("/patients")
            assert list_res.status_code == 200
            names = {patient["name"] for patient in list_res.json()}
            assert names == {"Alice", "Bob", "Charlie"}
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
                },
            )
            assert res.status_code == 201
            body = res.json()
            assert body["name"] == "John Smith"
            assert body["phone"] == "052-9876543"
            assert body["email"] is None
            assert uuid.UUID(body["id"])
        finally:
            asyncio.run(close_database(database_url))
