import time
import uuid
from datetime import datetime
from typing import Any

import httpx
import jwt

from auth.models import AuthConfigurationError
from auth.schemas import User
from core.config import Settings

ALLOWED_SUPABASE_JWT_ALGORITHMS = {"RS256", "ES256"}
REQUIRED_CLAIMS = ["exp", "iat", "iss", "sub"]

_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class InvalidTokenError(Exception):
    """Raised when a Supabase access token is missing, malformed, or invalid."""


def _auth_base_url(settings: Settings) -> str:
    if not settings.supabase_url:
        raise AuthConfigurationError("SUPABASE_URL is not configured")
    return settings.supabase_url.rstrip("/") + "/auth/v1"


def _jwks_url(settings: Settings) -> str:
    return _auth_base_url(settings) + "/.well-known/jwks.json"


async def _fetch_jwks(settings: Settings) -> dict[str, Any]:
    url = _jwks_url(settings)
    cached = _jwks_cache.get(url)
    now = time.monotonic()
    if cached is not None and cached[0] > now:
        return cached[1]

    async with httpx.AsyncClient(timeout=settings.supabase_auth_timeout_seconds) as client:
        response = await client.get(url)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise InvalidTokenError("invalid jwks response")
    _jwks_cache[url] = (now + settings.supabase_jwks_ttl_seconds, data)
    return data


def clear_jwks_cache() -> None:
    _jwks_cache.clear()


def _metadata_full_name(metadata: object) -> str | None:
    if not isinstance(metadata, dict):
        return None
    full_name = metadata.get("full_name") or metadata.get("name")
    return full_name if isinstance(full_name, str) else None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _user_from_claims(claims: dict[str, Any]) -> User:
    subject = claims.get("sub")
    if not isinstance(subject, str):
        raise InvalidTokenError("missing subject")
    email = claims.get("email")
    metadata = claims.get("user_metadata")
    return User(
        user_id=uuid.UUID(subject),
        email=email if isinstance(email, str) else None,
        full_name=_metadata_full_name(metadata),
        email_confirmed_at=_parse_datetime(claims.get("email_confirmed_at")),
    )


async def verify_supabase_access_token(token: str, *, settings: Settings) -> User:
    if not token.strip():
        raise InvalidTokenError("empty token")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("invalid token header") from exc

    algorithm = header.get("alg")
    key_id = header.get("kid")
    if not isinstance(algorithm, str) or algorithm not in ALLOWED_SUPABASE_JWT_ALGORITHMS:
        raise InvalidTokenError("unsupported token algorithm")
    if not isinstance(key_id, str):
        raise InvalidTokenError("missing token key id")

    try:
        jwks = await _fetch_jwks(settings)
        jwk_set = jwt.PyJWKSet.from_dict(jwks)
        signing_key = next(key for key in jwk_set.keys if key.key_id == key_id)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[algorithm],
            audience=settings.supabase_jwt_audience,
            issuer=_auth_base_url(settings),
            options={"require": REQUIRED_CLAIMS},
        )
    except (StopIteration, httpx.HTTPError, jwt.InvalidTokenError, ValueError) as exc:
        raise InvalidTokenError("invalid token") from exc

    if claims.get("role") != "authenticated":
        raise InvalidTokenError("invalid token role")
    return _user_from_claims(claims)
