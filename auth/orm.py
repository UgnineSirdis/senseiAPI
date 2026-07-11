import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import EmailStr
from sqlalchemy import DateTime, Enum, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from auth.models import AuthType, UserRole
from core.database import Base


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_type]


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    auth_type: Mapped[AuthType] = mapped_column(
        Enum(
            AuthType,
            values_callable=_enum_values,
            native_enum=False,
            length=64,
        )
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            values_callable=_enum_values,
            native_enum=False,
            length=64,
        )
    )
    email: Mapped[EmailStr | None] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(512))
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
