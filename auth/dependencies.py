import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from auth.models import AuthConfigurationError
from auth.schemas import User
from auth.service import SupabaseAuthService
from auth.tokens import InvalidTokenError, verify_supabase_access_token
from core.config import Settings, get_settings

TEST_USER = User(
    user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    email="testuser@example.com",
    full_name="Test User",
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def not_authenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def auth_misconfigured() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Supabase Auth is not configured",
    )


def get_auth_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SupabaseAuthService:
    try:
        return SupabaseAuthService(settings)
    except AuthConfigurationError as exc:
        raise auth_misconfigured() from exc


async def get_current_access_token(
    settings: Annotated[Settings, Depends(get_settings)],
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> str:
    if not settings.enable_security:
        return ""
    if token is None:
        raise not_authenticated()
    return token


async def get_current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    if not settings.enable_security:
        return TEST_USER
    if token is None:
        raise not_authenticated()
    try:
        return await verify_supabase_access_token(token, settings=settings)
    except (AuthConfigurationError, InvalidTokenError):
        raise not_authenticated() from None
