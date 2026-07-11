import uuid
from collections.abc import Callable

from pydantic import EmailStr, SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.models import (
    AuthType,
    AuthUser,
    UserAlreadyExistsError,
    UserCredentials,
    UserRole,
)
from auth.orm import UserRecord


def _to_user(record: UserRecord) -> AuthUser:
    return AuthUser(
        user_id=record.id,
        auth_type=record.auth_type,
        role=record.role,
        email=record.email,
        full_name=record.full_name,
        created_at=record.created_at,
        token_version=record.token_version,
    )


def _to_credentials(record: UserRecord) -> UserCredentials | None:
    if record.password_hash is None:
        return None
    return UserCredentials(
        user=_to_user(record),
        password_hash=record.password_hash,
    )


class UserRepository:
    """Persists application users in PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _email_exists(self, email: str) -> bool:
        result = await self._session.execute(
            select(UserRecord.id).where(UserRecord.email == email).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_credentials_by_email(self, email: EmailStr) -> UserCredentials | None:
        result = await self._session.execute(
            select(UserRecord).where(UserRecord.email == email).limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return _to_credentials(record)

    async def get_by_user_id(self, user_id: uuid.UUID) -> AuthUser | None:
        result = await self._session.execute(
            select(UserRecord).where(UserRecord.id == user_id).limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return _to_user(record)

    async def update_password(
        self,
        *,
        user_id: uuid.UUID,
        current_password: SecretStr,
        new_password_hash: str,
        password_matches: Callable[[SecretStr, str], bool],
    ) -> AuthUser | None:
        async with self._session.begin():
            result = await self._session.execute(
                select(UserRecord).where(UserRecord.id == user_id).with_for_update()
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            if record.password_hash is None:
                return None
            if not password_matches(current_password, record.password_hash):
                return None
            record.password_hash = new_password_hash
            record.token_version += 1
            await self._session.flush()
            await self._session.refresh(record)
            return _to_user(record)

    async def increment_token_version(self, user_id: uuid.UUID) -> AuthUser | None:
        async with self._session.begin():
            result = await self._session.execute(
                update(UserRecord)
                .where(UserRecord.id == user_id)
                .values(token_version=UserRecord.token_version + 1)
                .returning(UserRecord)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            return _to_user(record)

    async def create(
        self,
        *,
        password_hash: str,
        auth_type: AuthType,
        role: UserRole,
        email: EmailStr,
        full_name: str | None = None,
    ) -> AuthUser:
        record = UserRecord(
            auth_type=auth_type,
            role=role,
            email=email,
            full_name=full_name,
            password_hash=password_hash,
        )
        try:
            async with self._session.begin():
                if await self._email_exists(email):
                    raise UserAlreadyExistsError()
                self._session.add(record)
                await self._session.flush()
                await self._session.refresh(record)
        except IntegrityError as exc:
            raise UserAlreadyExistsError() from exc
        return _to_user(record)
