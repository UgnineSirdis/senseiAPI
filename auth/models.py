import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import EmailStr


class AuthType(StrEnum):
    PASSWORD = "password"


class UserRole(StrEnum):
    THERAPIST = "therapist"


class UserAlreadyExistsError(Exception):
    """Raised when email is already registered."""

    def __init__(self) -> None:
        super().__init__("user already exists")


class InvalidCredentialsError(Exception):
    """Raised when login credentials do not match any user."""

    def __init__(self) -> None:
        super().__init__("invalid credentials")


@dataclass(frozen=True)
class AuthUser:
    user_id: uuid.UUID
    auth_type: AuthType
    role: UserRole
    email: EmailStr | None
    full_name: str | None
    created_at: datetime
    token_version: int


@dataclass(frozen=True)
class UserCredentials:
    user: AuthUser
    password_hash: str
