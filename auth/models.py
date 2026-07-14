import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import EmailStr


class AuthConfigurationError(Exception):
    """Raised when Supabase Auth settings are incomplete."""


class AuthProviderError(Exception):
    """Raised when Supabase Auth rejects or cannot complete an operation."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class InvalidCredentialsError(AuthProviderError):
    """Raised when login credentials or access tokens are invalid."""

    def __init__(self) -> None:
        super().__init__("invalid credentials", status_code=401)


class UserAlreadyExistsError(AuthProviderError):
    """Raised when Supabase reports a duplicate email signup."""

    def __init__(self) -> None:
        super().__init__("user already exists", status_code=409)


@dataclass(frozen=True)
class AuthUser:
    user_id: uuid.UUID
    email: EmailStr | None
    full_name: str | None
    email_confirmed_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    refresh_token: str | None
    token_type: str
    expires_in: int | None
    user: AuthUser
