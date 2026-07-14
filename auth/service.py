import logging
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from email_validator import validate_email
from pydantic import EmailStr, SecretStr

from auth.models import (
    AuthConfigurationError,
    AuthProviderError,
    AuthSession,
    AuthUser,
    InvalidCredentialsError,
    UserAlreadyExistsError,
)
from core.config import Settings

logger = logging.getLogger(__name__)

INVALID_LOGIN_MESSAGES = {
    "invalid login credentials",
    "invalid credentials",
}


def _auth_base_url(settings: Settings) -> str:
    if not settings.supabase_url:
        raise AuthConfigurationError("SUPABASE_URL is not configured")
    return settings.supabase_url.rstrip("/") + "/auth/v1"


def _anon_key(settings: Settings) -> str:
    if not settings.supabase_anon_key:
        raise AuthConfigurationError("SUPABASE_ANON_KEY is not configured")
    return settings.supabase_anon_key


def normalize_email(email: str) -> EmailStr:
    normalized = validate_email(email, check_deliverability=False).normalized.lower()
    return normalized


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _metadata_full_name(metadata: object) -> str | None:
    if not isinstance(metadata, dict):
        return None
    full_name = metadata.get("full_name") or metadata.get("name")
    return full_name if isinstance(full_name, str) else None


def _user_from_payload(payload: dict[str, Any]) -> AuthUser:
    user_id = uuid.UUID(str(payload["id"]))
    email = payload.get("email")
    metadata = payload.get("user_metadata")
    return AuthUser(
        user_id=user_id,
        email=email if isinstance(email, str) else None,
        full_name=_metadata_full_name(metadata),
        email_confirmed_at=_parse_datetime(payload.get("email_confirmed_at")),
        created_at=_parse_datetime(payload.get("created_at")),
    )


def _session_from_payload(payload: dict[str, Any]) -> AuthSession:
    user_payload = payload.get("user")
    if not isinstance(user_payload, dict):
        raise AuthProviderError("Supabase response did not include a user")
    access_token = payload.get("access_token")
    if not isinstance(access_token, str):
        raise AuthProviderError("Supabase response did not include an access token")
    refresh_token = payload.get("refresh_token")
    token_type = payload.get("token_type")
    expires_in = payload.get("expires_in")
    return AuthSession(
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        token_type=token_type if isinstance(token_type, str) else "bearer",
        expires_in=expires_in if isinstance(expires_in, int) else None,
        user=_user_from_payload(user_payload),
    )


def _signup_user_payload(payload: dict[str, Any]) -> dict[str, Any]:
    user_payload = payload.get("user")
    if isinstance(user_payload, dict):
        return user_payload
    if isinstance(payload.get("id"), str):
        return payload
    raise AuthProviderError("Supabase response did not include a user")


class SupabaseAuthService:
    """Thin async client for Supabase Auth REST endpoints."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = _auth_base_url(settings)
        self._anon_key = _anon_key(settings)
        self._timeout = settings.supabase_auth_timeout_seconds

    def _headers(self, *, access_token: str | None = None) -> dict[str, str]:
        authorization = f"Bearer {access_token or self._anon_key}"
        return {
            "apikey": self._anon_key,
            "Authorization": authorization,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        access_token: str | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=self._headers(access_token=access_token),
                    json=json,
                    params=params,
                )
        except httpx.HTTPError as exc:
            logger.warning("Supabase Auth request failed: %s %s", method, path)
            raise AuthProviderError("auth provider unavailable") from exc

        if response.is_error:
            raise self._error_from_response(response)
        if not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _error_from_response(self, response: httpx.Response) -> AuthProviderError:
        message = "auth provider rejected the request"
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            description = body.get("msg") or body.get("message") or body.get("error_description")
            if isinstance(description, str):
                message = description

        lowered_message = message.lower()
        if response.status_code in {400, 401} and lowered_message in INVALID_LOGIN_MESSAGES:
            return InvalidCredentialsError()
        if "email not confirmed" in lowered_message:
            return AuthProviderError("email not confirmed", status_code=403)
        if response.status_code == 422 and "already" in message.lower():
            return UserAlreadyExistsError()
        return AuthProviderError(message, status_code=response.status_code)

    def _redirect_params(self, redirect_to: str | None) -> dict[str, str] | None:
        chosen = redirect_to or self._settings.supabase_email_redirect_to
        if not chosen:
            return None
        return {"redirect_to": chosen}

    async def register_user(
        self,
        *,
        email: EmailStr,
        password: SecretStr,
        full_name: str | None = None,
    ) -> AuthUser:
        payload: dict[str, Any] = {
            "email": str(email),
            "password": password.get_secret_value(),
        }
        if full_name:
            payload["data"] = {"full_name": full_name}
        data = await self._request(
            "POST",
            "/signup",
            json=payload,
            params=self._redirect_params(None),
        )
        return _user_from_payload(_signup_user_payload(data))

    async def authenticate_user(
        self,
        *,
        email: EmailStr,
        password: SecretStr,
    ) -> AuthSession:
        data = await self._request(
            "POST",
            "/token",
            json={"email": str(email), "password": password.get_secret_value()},
            params={"grant_type": "password"},
        )
        return _session_from_payload(data)

    async def logout(self, *, access_token: str) -> None:
        await self._request("POST", "/logout", access_token=access_token)

    async def change_password(
        self,
        *,
        email: EmailStr,
        current_password: SecretStr,
        new_password: SecretStr,
    ) -> None:
        session = await self.authenticate_user(email=email, password=current_password)
        await self._request(
            "PUT",
            "/user",
            access_token=session.access_token,
            json={"password": new_password.get_secret_value()},
        )

    async def send_password_reset_email(
        self,
        *,
        email: EmailStr,
        redirect_to: str | None = None,
    ) -> None:
        await self._request(
            "POST",
            "/recover",
            json={"email": str(email)},
            params=self._redirect_params(redirect_to),
        )

    def oauth_authorize_url(self, *, provider: str, redirect_to: str | None = None) -> str:
        chosen_redirect = redirect_to or self._settings.supabase_oauth_redirect_to
        query = {"provider": provider}
        if chosen_redirect:
            query["redirect_to"] = chosen_redirect
        return f"{self._base_url}/authorize?{urlencode(query)}"
