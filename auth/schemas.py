import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field, SecretStr

from auth.models import AuthSession, AuthUser


class User(BaseModel):
    user_id: uuid.UUID
    email: EmailStr | None
    full_name: str | None = None
    email_confirmed_at: datetime | None = None

    @classmethod
    def from_auth_user(cls, user: AuthUser) -> Self:
        return cls(
            user_id=user.user_id,
            email=user.email,
            full_name=user.full_name,
            email_confirmed_at=user.email_confirmed_at,
        )


class UserCreate(BaseModel):
    password: SecretStr = Field(min_length=8, max_length=1024)
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)


class PasswordChange(BaseModel):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=8, max_length=1024)


class PasswordResetRequest(BaseModel):
    email: EmailStr
    redirect_to: AnyHttpUrl | None = None


class OAuthStartRequest(BaseModel):
    provider: Literal["google"] = "google"
    redirect_to: AnyHttpUrl | None = None


class UserOut(BaseModel):
    user_id: uuid.UUID
    email: EmailStr | None
    full_name: str | None
    email_confirmed_at: datetime | None
    created_at: datetime | None

    @classmethod
    def from_auth_user(cls, user: AuthUser) -> Self:
        return cls(
            user_id=user.user_id,
            email=user.email,
            full_name=user.full_name,
            email_confirmed_at=user.email_confirmed_at,
            created_at=user.created_at,
        )


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None

    @classmethod
    def from_session(cls, session: AuthSession) -> Self:
        return cls(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            token_type=session.token_type,
            expires_in=session.expires_in,
        )


class OAuthUrlOut(BaseModel):
    url: str
