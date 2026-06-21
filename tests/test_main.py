import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from main import app

client = TestClient(app)


def test_root_returns_welcome() -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert res.json() == {"message": "Welcome to SenseiAPI"}


def test_health_returns_ok() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_readiness_returns_ready_when_database_ping_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ping_database_succeeds(settings: Settings) -> bool:
        return True

    monkeypatch.setattr("main.ping_database", ping_database_succeeds)

    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready", "database": "ok"}


def test_readiness_returns_503_when_database_ping_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ping_database_fails(settings: Settings) -> bool:
        raise OSError("database unavailable")

    monkeypatch.setattr("main.ping_database", ping_database_fails)

    res = client.get("/ready")
    assert res.status_code == 503
    assert res.json() == {"status": "not_ready", "database": "unavailable"}


def test_settings_reads_database_url_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "postgresql+asyncpg://user:password@localhost:5432/testdb"
    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = Settings()

    assert settings.database_url == database_url


def test_unknown_route_returns_404() -> None:
    res = client.get("/does-not-exist")
    assert res.status_code == 404
