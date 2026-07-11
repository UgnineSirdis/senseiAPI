import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, EmailStr, Field, SecretStr

from auth.models import AuthType, AuthUser, UserRole


class User(BaseModel):
    user_id: uuid.UUID
    email: EmailStr | None
    full_name: str | None = None


class UserCreate(BaseModel):
    password: SecretStr = Field(min_length=8, max_length=1024)
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)


class PasswordChange(BaseModel):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=8, max_length=1024)


class UserOut(BaseModel):
    user_id: uuid.UUID
    auth_type: AuthType
    role: UserRole
    email: EmailStr | None
    full_name: str | None
    created_at: datetime

    @classmethod
    def from_user(cls, user: AuthUser) -> Self:
        return cls.model_construct(
            user_id=user.user_id,
            auth_type=user.auth_type,
            role=user.role,
            email=user.email,
            full_name=user.full_name,
            created_at=user.created_at,
        )


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
