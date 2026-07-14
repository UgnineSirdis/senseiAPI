import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import EmailStr, SecretStr

import auth.dependencies as auth_dependencies
from auth.dependencies import get_auth_service
from auth.models import AuthProviderError, AuthSession, AuthUser, InvalidCredentialsError
from auth.schemas import User
from auth.service import SupabaseAuthService
from auth.tokens import InvalidTokenError
from core.config import Settings
from main import app
from tests.conftest import ClientFactory

USER_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")
CREATED_AT = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
CONFIRMED_AT = datetime(2026, 7, 8, 12, 5, tzinfo=UTC)


def _auth_user(*, email: EmailStr | None = "newuser@example.com") -> AuthUser:
    return AuthUser(
        user_id=USER_ID,
        email=email,
        full_name="New User",
        email_confirmed_at=CONFIRMED_AT,
        created_at=CREATED_AT,
    )


def _session() -> AuthSession:
    return AuthSession(
        access_token="supabase-access-token",
        refresh_token="supabase-refresh-token",
        token_type="bearer",
        expires_in=3600,
        user=_auth_user(),
    )


class _FakeSupabaseAuthService:
    def __init__(self) -> None:
        self.logged_out_token: str | None = None
        self.password_reset_email: EmailStr | None = None
        self.changed_password_for: EmailStr | None = None

    async def register_user(
        self,
        *,
        email: EmailStr,
        password: SecretStr,
        full_name: str | None = None,
    ) -> AuthUser:
        if email == "existing@example.com":
            raise AuthProviderError("user already exists", status_code=409)
        assert password.get_secret_value()
        return AuthUser(
            user_id=USER_ID,
            email=email,
            full_name=full_name,
            email_confirmed_at=None,
            created_at=CREATED_AT,
        )

    async def authenticate_user(self, *, email: EmailStr, password: SecretStr) -> AuthSession:
        if email != "newuser@example.com" or password != SecretStr("strong-password"):
            raise InvalidCredentialsError()
        return _session()

    async def logout(self, *, access_token: str) -> None:
        self.logged_out_token = access_token

    async def change_password(
        self,
        *,
        email: EmailStr,
        current_password: SecretStr,
        new_password: SecretStr,
    ) -> None:
        if current_password != SecretStr("strong-password"):
            raise InvalidCredentialsError()
        assert new_password.get_secret_value()
        self.changed_password_for = email

    async def send_password_reset_email(
        self,
        *,
        email: EmailStr,
        redirect_to: str | None = None,
    ) -> None:
        assert redirect_to is None or redirect_to.startswith("https://")
        self.password_reset_email = email

    def oauth_authorize_url(self, *, provider: str, redirect_to: str | None = None) -> str:
        assert provider == "google"
        assert redirect_to is None or redirect_to.startswith("https://")
        return "https://example.supabase.co/auth/v1/authorize?provider=google"


def override_auth_service(service: _FakeSupabaseAuthService) -> None:
    app.dependency_overrides[get_auth_service] = lambda: service


def test_register_user_returns_201(make_client: ClientFactory) -> None:
    client, _ = make_client()
    override_auth_service(_FakeSupabaseAuthService())

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
        "email": "newuser@example.com",
        "full_name": "New User",
        "email_confirmed_at": None,
        "created_at": "2026-07-08T12:00:00Z",
    }


def test_register_user_does_not_return_password_fields(make_client: ClientFactory) -> None:
    client, _ = make_client()
    override_auth_service(_FakeSupabaseAuthService())

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


def test_register_user_rejects_duplicate_user(make_client: ClientFactory) -> None:
    client, _ = make_client()
    override_auth_service(_FakeSupabaseAuthService())

    res = client.post(
        "/auth/register",
        json={
            "password": "strong-password",
            "email": "existing@example.com",
        },
    )

    assert res.status_code == 409
    assert res.json() == {"detail": "user already exists"}


@pytest.mark.parametrize(
    "payload",
    [
        {"password": "short", "email": "newuser@example.com"},
        {"password": "strong-password"},
        {"password": "strong-password", "email": "not-an-email"},
    ],
)
def test_register_user_validates_payload(
    make_client: ClientFactory,
    payload: dict[str, str],
) -> None:
    client, _ = make_client()
    override_auth_service(_FakeSupabaseAuthService())

    res = client.post("/auth/register", json=payload)

    assert res.status_code == 422


def test_issue_token_returns_supabase_session(make_client: ClientFactory) -> None:
    client, _ = make_client(enable_security=True)
    override_auth_service(_FakeSupabaseAuthService())

    res = client.post(
        "/auth/token",
        data={"username": "NewUser@Example.COM", "password": "strong-password"},
    )

    assert res.status_code == 200
    assert res.json() == {
        "access_token": "supabase-access-token",
        "refresh_token": "supabase-refresh-token",
        "token_type": "bearer",
        "expires_in": 3600,
    }


def test_issue_token_rejects_bad_credentials(make_client: ClientFactory) -> None:
    client, _ = make_client(enable_security=True)
    override_auth_service(_FakeSupabaseAuthService())

    res = client.post(
        "/auth/token",
        data={"username": "newuser@example.com", "password": "bad-password"},
    )

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_issue_token_returns_email_not_confirmed(make_client: ClientFactory) -> None:
    class _EmailNotConfirmedService(_FakeSupabaseAuthService):
        async def authenticate_user(
            self,
            *,
            email: EmailStr,
            password: SecretStr,
        ) -> AuthSession:
            raise AuthProviderError("email not confirmed", status_code=403)

    client, _ = make_client(enable_security=True)
    override_auth_service(_EmailNotConfirmedService())

    res = client.post(
        "/auth/token",
        data={"username": "newuser@example.com", "password": "strong-password"},
    )

    assert res.status_code == 403
    assert res.json() == {"detail": "email not confirmed"}


def test_auth_whoami_uses_test_user_when_security_disabled(make_client: ClientFactory) -> None:
    client, _ = make_client(enable_security=False)

    res = client.get("/auth/whoami")

    assert res.status_code == 200
    assert res.json() == {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "testuser@example.com",
        "full_name": "Test User",
        "email_confirmed_at": None,
    }


def test_protected_route_allows_missing_token_when_security_disabled(
    make_client: ClientFactory,
) -> None:
    client, _ = make_client(enable_security=False)

    res = client.get("/audio")

    assert res.status_code == 200
    assert res.json() == []


def test_protected_route_requires_token_when_security_enabled(make_client: ClientFactory) -> None:
    client, _ = make_client(enable_security=True)

    res = client.get("/audio")

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}
    assert res.headers["www-authenticate"] == "Bearer"


def test_protected_route_rejects_invalid_token_when_security_enabled(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_token(_token: str, *, settings: Settings) -> None:
        raise InvalidTokenError("invalid token")

    monkeypatch.setattr(auth_dependencies, "verify_supabase_access_token", reject_token)
    client, _ = make_client(enable_security=True)

    res = client.get("/audio", headers={"Authorization": "Bearer real-token"})

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_auth_whoami_accepts_supabase_bearer_token(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def accept_token(_token: str, *, settings: Settings) -> User:
        return User(
            user_id=USER_ID,
            email="newuser@example.com",
            full_name="New User",
            email_confirmed_at=CONFIRMED_AT,
        )

    monkeypatch.setattr(auth_dependencies, "verify_supabase_access_token", accept_token)
    client, _ = make_client(enable_security=True)

    res = client.get("/auth/whoami", headers={"Authorization": "Bearer supabase-token"})

    assert res.status_code == 200
    assert res.json() == {
        "user_id": str(USER_ID),
        "email": "newuser@example.com",
        "full_name": "New User",
        "email_confirmed_at": "2026-07-08T12:05:00Z",
    }


def test_logout_requires_token(make_client: ClientFactory) -> None:
    client, _ = make_client(enable_security=True)

    res = client.post("/auth/logout")

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_logout_calls_supabase(make_client: ClientFactory) -> None:
    service = _FakeSupabaseAuthService()
    client, _ = make_client(enable_security=True)
    override_auth_service(service)

    res = client.post("/auth/logout", headers={"Authorization": "Bearer supabase-token"})

    assert res.status_code == 204
    assert res.content == b""
    assert service.logged_out_token == "supabase-token"


def test_change_password_requires_token(make_client: ClientFactory) -> None:
    client, _ = make_client(enable_security=True)

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
    async def accept_token(_token: str, *, settings: Settings) -> User:
        return User(
            user_id=USER_ID,
            email="newuser@example.com",
            full_name="New User",
        )

    monkeypatch.setattr(auth_dependencies, "verify_supabase_access_token", accept_token)
    client, _ = make_client(enable_security=True)
    override_auth_service(_FakeSupabaseAuthService())

    res = client.post(
        "/auth/password/change",
        headers={"Authorization": "Bearer supabase-token"},
        json={
            "current_password": "bad-password",
            "new_password": "new-strong-password",
        },
    )

    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_change_password_calls_supabase(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def accept_token(_token: str, *, settings: Settings) -> User:
        return User(
            user_id=USER_ID,
            email="newuser@example.com",
            full_name="New User",
        )

    service = _FakeSupabaseAuthService()
    monkeypatch.setattr(auth_dependencies, "verify_supabase_access_token", accept_token)
    client, _ = make_client(enable_security=True)
    override_auth_service(service)

    res = client.post(
        "/auth/password/change",
        headers={"Authorization": "Bearer supabase-token"},
        json={
            "current_password": "strong-password",
            "new_password": "new-strong-password",
        },
    )

    assert res.status_code == 204
    assert res.content == b""
    assert service.changed_password_for == "newuser@example.com"


def test_password_reset_sends_recovery_email(make_client: ClientFactory) -> None:
    service = _FakeSupabaseAuthService()
    client, _ = make_client()
    override_auth_service(service)

    res = client.post(
        "/auth/password/reset",
        json={
            "email": "NewUser@Example.COM",
            "redirect_to": "https://app.example.com/auth/reset",
        },
    )

    assert res.status_code == 204
    assert res.content == b""
    assert service.password_reset_email == "newuser@example.com"


def test_oauth_url_returns_google_authorize_url(make_client: ClientFactory) -> None:
    client, _ = make_client()
    override_auth_service(_FakeSupabaseAuthService())

    res = client.post(
        "/auth/oauth/url",
        json={
            "provider": "google",
            "redirect_to": "https://app.example.com/auth/callback",
        },
    )

    assert res.status_code == 200
    assert res.json() == {"url": "https://example.supabase.co/auth/v1/authorize?provider=google"}


def test_oauth_url_rejects_unsupported_provider(make_client: ClientFactory) -> None:
    client, _ = make_client()
    override_auth_service(_FakeSupabaseAuthService())

    res = client.post("/auth/oauth/url", json={"provider": "github"})

    assert res.status_code == 422


def test_supabase_service_accepts_signup_user_as_top_level_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SupabaseAuthService(
        Settings(
            supabase_url="https://example.supabase.co",
            supabase_anon_key="anon",
        )
    )

    async def fake_request(
        method: str,
        path: str,
        *,
        access_token: str | None = None,
        json: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        assert method == "POST"
        assert path == "/signup"
        assert access_token is None
        assert json == {
            "email": "newuser@example.com",
            "password": "strong-password",
            "data": {"full_name": "New User"},
        }
        assert params is None or set(params) == {"redirect_to"}
        return {
            "id": str(USER_ID),
            "email": "newuser@example.com",
            "user_metadata": {"full_name": "New User"},
            "email_confirmed_at": None,
            "created_at": "2026-07-08T12:00:00Z",
        }

    monkeypatch.setattr(service, "_request", fake_request)

    user = asyncio.run(
        service.register_user(
            email="newuser@example.com",
            password=SecretStr("strong-password"),
            full_name="New User",
        )
    )

    assert user == AuthUser(
        user_id=USER_ID,
        email="newuser@example.com",
        full_name="New User",
        email_confirmed_at=None,
        created_at=CREATED_AT,
    )


def test_supabase_service_preserves_email_not_confirmed_error() -> None:
    service = SupabaseAuthService(
        Settings(
            supabase_url="https://example.supabase.co",
            supabase_anon_key="anon",
        )
    )

    error = service._error_from_response(
        response=httpx.Response(
            status_code=400,
            json={"msg": "Email not confirmed"},
        )
    )

    assert isinstance(error, AuthProviderError)
    assert not isinstance(error, InvalidCredentialsError)
    assert str(error) == "email not confirmed"
    assert error.status_code == 403


def test_supabase_service_builds_google_oauth_url() -> None:
    service = SupabaseAuthService(
        Settings(
            supabase_url="https://example.supabase.co",
            supabase_anon_key="anon",
            supabase_oauth_redirect_to="https://app.example.com/auth/callback",
        )
    )

    assert service.oauth_authorize_url(provider="google") == (
        "https://example.supabase.co/auth/v1/authorize?"
        "provider=google&redirect_to=https%3A%2F%2Fapp.example.com%2Fauth%2Fcallback"
    )
