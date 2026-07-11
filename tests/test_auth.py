import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import cast

import pytest
from fastapi import HTTPException
from pydantic import EmailStr, SecretStr

import auth.service as auth_service
from auth.dependencies import get_user_service
from auth.models import (
    AuthType,
    AuthUser,
    InvalidCredentialsError,
    UserAlreadyExistsError,
    UserRole,
)
from auth.repository import UserRepository
from auth.router import TokenClaims, decode_token
from auth.schemas import User
from auth.tokens import InvalidTokenError, create_access_token, verify_access_token
from core.config import Settings
from main import app
from tests.conftest import ClientFactory
from tests.database_helpers import get_database_url

USER_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")
CREATED_AT = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
TOKEN_SECRET = "a" * 64
AUTH_ROUTER_MODULE = import_module("auth.router")


def test_verify_access_token_rejects_expired_token() -> None:
    issued_at = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    token = create_access_token(
        AuthUser(
            user_id=USER_ID,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email="newuser@example.com",
            full_name="New User",
            created_at=CREATED_AT,
            token_version=0,
        ),
        secret_key=TOKEN_SECRET,
        ttl_seconds=60,
        now=issued_at,
    )

    with pytest.raises(InvalidTokenError):
        verify_access_token(
            token,
            secret_key=TOKEN_SECRET,
            now=issued_at + timedelta(seconds=61),
        )


def test_create_access_token_uses_user_id_as_subject() -> None:
    token = create_access_token(
        AuthUser(
            user_id=USER_ID,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email="newuser@example.com",
            full_name="New User",
            created_at=CREATED_AT,
            token_version=0,
        ),
        secret_key=TOKEN_SECRET,
        ttl_seconds=60,
    )

    payload = verify_access_token(token, secret_key=TOKEN_SECRET)

    assert payload["sub"] == str(USER_ID)


class _FakeUserService:
    def __init__(self) -> None:
        self._password = SecretStr("strong-password")
        self._token_version = 0

    async def register_user(
        self,
        *,
        password: SecretStr,
        auth_type: AuthType,
        role: UserRole,
        email: EmailStr,
        full_name: str | None = None,
    ) -> AuthUser:
        if email == "existing@example.com":
            raise UserAlreadyExistsError()
        assert password
        return AuthUser(
            user_id=USER_ID,
            auth_type=auth_type,
            role=role,
            email=email,
            full_name=full_name,
            created_at=CREATED_AT,
            token_version=self._token_version,
        )

    async def authenticate_user(self, *, email: EmailStr, password: SecretStr) -> AuthUser:
        if email != "newuser@example.com" or password != self._password:
            raise InvalidCredentialsError()
        return AuthUser(
            user_id=USER_ID,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email="newuser@example.com",
            full_name="New User",
            created_at=CREATED_AT,
            token_version=self._token_version,
        )

    async def get_user_by_id(self, user_id: uuid.UUID) -> AuthUser | None:
        if user_id != USER_ID:
            return None
        return AuthUser(
            user_id=USER_ID,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email="newuser@example.com",
            full_name="New User",
            created_at=CREATED_AT,
            token_version=self._token_version,
        )

    async def change_password(
        self,
        *,
        user_id: uuid.UUID,
        current_password: SecretStr,
        new_password: SecretStr,
    ) -> AuthUser:
        if user_id != USER_ID or current_password != self._password:
            raise InvalidCredentialsError()
        self._password = new_password
        self._token_version += 1
        user = await self.get_user_by_id(user_id)
        assert user is not None
        return user

    async def logout(self, *, user_id: uuid.UUID) -> None:
        if user_id != USER_ID:
            raise InvalidCredentialsError()
        self._token_version += 1


def override_token_user_loader(
    monkeypatch: pytest.MonkeyPatch,
    service: _FakeUserService,
) -> None:
    async def fake_loader(_settings: Settings, claims: TokenClaims) -> User:
        user = await service.get_user_by_id(claims.user_id)
        if user is None or user.token_version != claims.token_version:
            raise HTTPException(
                status_code=401,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return User(
            user_id=user.user_id,
            email=user.email,
            full_name=user.full_name,
        )

    monkeypatch.setattr(AUTH_ROUTER_MODULE, "_load_user_from_token_claims", fake_loader)


class _MissingUserRepository:
    async def get_credentials_by_email(self, email: str) -> None:
        return None


def test_register_user_returns_201(make_client: ClientFactory) -> None:
    client, _ = make_client()
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()

    res = client.post(
        "/auth/register",
        json={
            "password": "strong-password",
            "email": "NewUser@Example.COM",
            "full_name": "New User",
        },
    )

    assert res.status_code == 201
    assert res.json() == {
        "user_id": str(USER_ID),
        "auth_type": "password",
        "role": "therapist",
        "email": "newuser@example.com",
        "full_name": "New User",
        "created_at": "2026-07-08T12:00:00Z",
    }


def test_register_user_does_not_return_password_fields(make_client: ClientFactory) -> None:
    client, _ = make_client()
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()

    res = client.post(
        "/auth/register",
        json={
            "password": "strong-password",
            "email": "newuser@example.com",
        },
    )

    assert res.status_code == 201
    body = res.json()
    assert "password" not in body
    assert "password_hash" not in body


def test_register_user_normalizes_email(make_client: ClientFactory) -> None:
    client, _ = make_client()
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()

    res = client.post(
        "/auth/register",
        json={
            "password": "strong-password",
            "email": "NewUser@Example.COM",
        },
    )

    assert res.status_code == 201
    assert res.json()["email"] == "newuser@example.com"


def test_register_user_rejects_duplicate_user(make_client: ClientFactory) -> None:
    client, _ = make_client()
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()

    res = client.post(
        "/auth/register",
        json={
            "password": "strong-password",
            "email": "existing@example.com",
        },
    )

    assert res.status_code == 409
    assert res.json() == {"detail": "user already exists"}


def test_register_user_rejects_short_password(make_client: ClientFactory) -> None:
    client, _ = make_client()
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()

    res = client.post(
        "/auth/register",
        json={
            "password": "short",
            "email": "newuser@example.com",
        },
    )

    assert res.status_code == 422


def test_register_user_requires_email(make_client: ClientFactory) -> None:
    client, _ = make_client()
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()

    res = client.post(
        "/auth/register",
        json={"password": "strong-password"},
    )

    assert res.status_code == 422


def test_register_user_rejects_invalid_email(make_client: ClientFactory) -> None:
    client, _ = make_client()
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()

    res = client.post(
        "/auth/register",
        json={
            "password": "strong-password",
            "email": "not-an-email",
        },
    )

    assert res.status_code == 422


def test_auth_whoami_uses_test_user_when_security_disabled(make_client: ClientFactory) -> None:
    client, _ = make_client(enable_security=False)

    res = client.get("/auth/whoami")

    assert res.status_code == 200
    assert res.json() == {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "testuser@example.com",
        "full_name": "Test User",
    }


def test_protected_route_allows_missing_token_when_security_disabled(
    make_client: ClientFactory,
) -> None:
    client, _ = make_client(enable_security=False)

    res = client.get("/audio")

    assert res.status_code == 200
    assert res.json() == []


def test_protected_route_requires_token_when_security_enabled(make_client: ClientFactory) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)

    res = client.get("/audio")

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}
    assert res.headers["www-authenticate"] == "Bearer"


def test_protected_route_rejects_invalid_token_when_security_enabled(
    make_client: ClientFactory,
) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)

    res = client.get("/audio", headers={"Authorization": "Bearer real-token"})

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_decode_token_hides_invalid_token_cause() -> None:
    with pytest.raises(HTTPException) as exc_info:
        decode_token("not-a-token", secret_key=TOKEN_SECRET)

    assert exc_info.value.status_code == 401
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_protected_route_accepts_signed_token_when_security_enabled(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)
    service = _FakeUserService()
    override_token_user_loader(monkeypatch, service)
    token = create_access_token(
        AuthUser(
            user_id=USER_ID,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email="newuser@example.com",
            full_name="New User",
            created_at=CREATED_AT,
            token_version=0,
        ),
        secret_key=TOKEN_SECRET,
        ttl_seconds=3600,
    )

    res = client.get("/audio", headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 200
    assert res.json() == []


def test_auth_whoami_accepts_bearer_token_when_security_enabled(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)
    service = _FakeUserService()
    override_token_user_loader(monkeypatch, service)
    token = create_access_token(
        AuthUser(
            user_id=USER_ID,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email="newuser@example.com",
            full_name="New User",
            created_at=CREATED_AT,
            token_version=0,
        ),
        secret_key=TOKEN_SECRET,
        ttl_seconds=3600,
    )

    res = client.get("/auth/whoami", headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 200
    assert res.json() == {
        "user_id": str(USER_ID),
        "email": "newuser@example.com",
        "full_name": "New User",
    }


def test_logout_requires_token(make_client: ClientFactory) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)

    res = client.post("/auth/logout")

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_logout_invalidates_current_token(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)
    service = _FakeUserService()
    app.dependency_overrides[get_user_service] = lambda: service
    override_token_user_loader(monkeypatch, service)
    token = create_access_token(
        AuthUser(
            user_id=USER_ID,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email="newuser@example.com",
            full_name="New User",
            created_at=CREATED_AT,
            token_version=0,
        ),
        secret_key=TOKEN_SECRET,
        ttl_seconds=3600,
    )

    logged_out = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    old_token_whoami = client.get("/auth/whoami", headers={"Authorization": f"Bearer {token}"})

    assert logged_out.status_code == 204
    assert logged_out.content == b""
    assert old_token_whoami.status_code == 401
    assert old_token_whoami.json() == {"detail": "Not authenticated"}


def test_change_password_requires_token(make_client: ClientFactory) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)

    res = client.post(
        "/auth/password/change",
        json={
            "current_password": "strong-password",
            "new_password": "new-strong-password",
        },
    )

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_change_password_rejects_wrong_current_password(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)
    service = _FakeUserService()
    app.dependency_overrides[get_user_service] = lambda: service
    override_token_user_loader(monkeypatch, service)
    token = create_access_token(
        AuthUser(
            user_id=USER_ID,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email="newuser@example.com",
            full_name="New User",
            created_at=CREATED_AT,
            token_version=0,
        ),
        secret_key=TOKEN_SECRET,
        ttl_seconds=3600,
    )

    res = client.post(
        "/auth/password/change",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "bad-password",
            "new_password": "new-strong-password",
        },
    )

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_change_password_invalidates_old_token_and_password(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)
    service = _FakeUserService()
    app.dependency_overrides[get_user_service] = lambda: service
    override_token_user_loader(monkeypatch, service)
    token = create_access_token(
        AuthUser(
            user_id=USER_ID,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email="newuser@example.com",
            full_name="New User",
            created_at=CREATED_AT,
            token_version=0,
        ),
        secret_key=TOKEN_SECRET,
        ttl_seconds=3600,
    )

    changed = client.post(
        "/auth/password/change",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "strong-password",
            "new_password": "new-strong-password",
        },
    )
    old_token_whoami = client.get("/auth/whoami", headers={"Authorization": f"Bearer {token}"})
    old_password_login = client.post(
        "/auth/token",
        data={"username": "newuser@example.com", "password": "strong-password"},
    )
    new_password_login = client.post(
        "/auth/token",
        data={"username": "newuser@example.com", "password": "new-strong-password"},
    )

    assert changed.status_code == 204
    assert changed.content == b""
    assert old_token_whoami.status_code == 401
    assert old_password_login.status_code == 401
    assert new_password_login.status_code == 200


def test_issue_token_returns_signed_bearer_token(make_client: ClientFactory) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()

    res = client.post(
        "/auth/token",
        data={"username": "NewUser@Example.COM", "password": "strong-password"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str)
    assert body["access_token"].count(".") == 2


def test_issue_token_rejects_bad_credentials(make_client: ClientFactory) -> None:
    client, _ = make_client(auth_token_secret_key=TOKEN_SECRET)
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()

    res = client.post(
        "/auth/token",
        data={"username": "newuser@example.com", "password": "bad-password"},
    )

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_password_hash_uses_secret_value() -> None:
    password_hash = auth_service.hash_password(SecretStr("strong-password"))

    assert auth_service.verify_password(SecretStr("strong-password"), password_hash)
    assert not auth_service.verify_password(SecretStr("wrong-password"), password_hash)


def test_authenticate_unknown_user_hashes_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[SecretStr] = []

    def fake_hash_password(password: SecretStr) -> str:
        calls.append(password)
        return "irrelevant"

    monkeypatch.setattr(auth_service, "hash_password", fake_hash_password)
    service = auth_service.UserService(cast(UserRepository, _MissingUserRepository()))

    with pytest.raises(InvalidCredentialsError):
        asyncio.run(
            service.authenticate_user(
                email="missing@example.com", password=SecretStr("bad-password")
            )
        )

    assert calls == [SecretStr("bad-password")]


def test_issue_token_requires_secret_key(make_client: ClientFactory) -> None:
    client, _ = make_client()
    app.dependency_overrides[get_user_service] = lambda: _FakeUserService()

    res = client.post(
        "/auth/token",
        data={"username": "newuser@example.com", "password": "strong-password"},
    )

    assert res.status_code == 500
    assert res.json() == {"detail": "auth token secret key is not configured"}


@pytest.mark.integration
def test_register_user_persists_in_database(make_client: ClientFactory) -> None:
    with get_database_url() as database_url:
        client, _ = make_client(
            auth_token_secret_key=TOKEN_SECRET,
            database_url=database_url,
        )
        with client:
            created = client.post(
                "/auth/register",
                json={
                    "password": "strong-password",
                    "email": "DBUser@Example.COM",
                    "full_name": "DB User",
                },
            )
            assert created.status_code == 201
            body = created.json()
            assert body["auth_type"] == "password"
            assert body["role"] == "therapist"
            assert body["email"] == "dbuser@example.com"
            assert uuid.UUID(body["user_id"])
            assert "username" not in body
            assert "password" not in body
            assert "password_hash" not in body

            duplicate = client.post(
                "/auth/register",
                json={
                    "password": "strong-password",
                    "email": "DBUSER@example.com",
                },
            )
            assert duplicate.status_code == 409

            token_res = client.post(
                "/auth/token",
                data={"username": "DBUSER@Example.COM", "password": "strong-password"},
            )
            assert token_res.status_code == 200
            token = token_res.json()["access_token"]

            whoami = client.get("/auth/whoami", headers={"Authorization": f"Bearer {token}"})
            assert whoami.status_code == 200
            assert whoami.json() == {
                "user_id": body["user_id"],
                "email": "dbuser@example.com",
                "full_name": "DB User",
            }

            changed = client.post(
                "/auth/password/change",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "current_password": "strong-password",
                    "new_password": "new-strong-password",
                },
            )
            assert changed.status_code == 204

            old_token_whoami = client.get(
                "/auth/whoami",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert old_token_whoami.status_code == 401

            old_password_login = client.post(
                "/auth/token",
                data={"username": "dbuser@example.com", "password": "strong-password"},
            )
            assert old_password_login.status_code == 401

            new_password_login = client.post(
                "/auth/token",
                data={"username": "dbuser@example.com", "password": "new-strong-password"},
            )
            assert new_password_login.status_code == 200


@pytest.mark.integration
def test_signed_token_requires_existing_user_in_database(
    make_client: ClientFactory,
) -> None:
    missing_user_id = uuid.UUID("88888888-8888-8888-8888-888888888888")

    def token_user(user_id: uuid.UUID) -> AuthUser:
        return AuthUser(
            user_id=user_id,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email="tokenuser@example.com",
            full_name="Token User",
            created_at=CREATED_AT,
            token_version=0,
        )

    with get_database_url() as database_url:
        client, _ = make_client(
            auth_token_secret_key=TOKEN_SECRET,
            database_url=database_url,
        )
        with client:
            created = client.post(
                "/auth/register",
                json={
                    "password": "strong-password",
                    "email": "TokenUser@Example.COM",
                    "full_name": "Token User",
                },
            )
            assert created.status_code == 201
            created_body = created.json()
            existing_user_id = uuid.UUID(created_body["user_id"])

            existing_user_token = create_access_token(
                token_user(existing_user_id),
                secret_key=TOKEN_SECRET,
                ttl_seconds=3600,
            )

            allowed = client.get(
                "/auth/whoami",
                headers={"Authorization": f"Bearer {existing_user_token}"},
            )
            assert allowed.status_code == 200
            assert allowed.json() == {
                "user_id": created_body["user_id"],
                "email": "tokenuser@example.com",
                "full_name": "Token User",
            }

            missing_user_token = create_access_token(
                token_user(missing_user_id),
                secret_key=TOKEN_SECRET,
                ttl_seconds=3600,
            )

            denied = client.get(
                "/auth/whoami",
                headers={"Authorization": f"Bearer {missing_user_token}"},
            )
            assert denied.status_code == 401
            assert denied.json() == {"detail": "Not authenticated"}
            assert denied.headers["www-authenticate"] == "Bearer"


@pytest.mark.integration
def test_logout_invalidates_token_in_database(make_client: ClientFactory) -> None:
    with get_database_url() as database_url:
        client, _ = make_client(
            auth_token_secret_key=TOKEN_SECRET,
            database_url=database_url,
        )
        with client:
            created = client.post(
                "/auth/register",
                json={
                    "password": "strong-password",
                    "email": "LogoutUser@Example.COM",
                    "full_name": "Logout User",
                },
            )
            assert created.status_code == 201
            created_body = created.json()

            token_res = client.post(
                "/auth/token",
                data={"username": "logoutuser@example.com", "password": "strong-password"},
            )
            assert token_res.status_code == 200
            token = token_res.json()["access_token"]

            allowed = client.get("/auth/whoami", headers={"Authorization": f"Bearer {token}"})
            assert allowed.status_code == 200
            assert allowed.json() == {
                "user_id": created_body["user_id"],
                "email": "logoutuser@example.com",
                "full_name": "Logout User",
            }

            logged_out = client.post(
                "/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert logged_out.status_code == 204
            assert logged_out.content == b""

            old_token_whoami = client.get(
                "/auth/whoami",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert old_token_whoami.status_code == 401
            assert old_token_whoami.json() == {"detail": "Not authenticated"}

            new_token_res = client.post(
                "/auth/token",
                data={"username": "logoutuser@example.com", "password": "strong-password"},
            )
            assert new_token_res.status_code == 200
            new_token = new_token_res.json()["access_token"]

            new_token_whoami = client.get(
                "/auth/whoami",
                headers={"Authorization": f"Bearer {new_token}"},
            )
            assert new_token_whoami.status_code == 200
