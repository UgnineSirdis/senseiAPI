import uuid
from dataclasses import dataclass
from typing import Annotated

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import EmailStr, SecretStr
from sqlalchemy.exc import SQLAlchemyError

from auth.dependencies import get_user_service
from auth.models import AuthType, InvalidCredentialsError, UserAlreadyExistsError, UserRole
from auth.repository import UserRepository
from auth.schemas import PasswordChange, TokenOut, User, UserCreate, UserOut
from auth.service import UserService
from auth.tokens import InvalidTokenError, create_access_token, verify_access_token
from core.config import Settings, get_settings
from core.database import get_sessionmaker

router = APIRouter(prefix="/auth", tags=["auth"])

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_USER = User(
    user_id=TEST_USER_ID,
    email="testuser@example.com",
    full_name="Test User",
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    email: EmailStr
    full_name: str | None
    token_version: int


def _not_authenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _server_misconfigured() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="auth token secret key is not configured",
    )


def _token_secret(settings: Settings) -> str:
    assert settings.auth_token_secret_key
    return settings.auth_token_secret_key


def decode_token(token: str, *, secret_key: str) -> TokenClaims:
    if not token.strip():
        raise _not_authenticated()
    try:
        payload = verify_access_token(token, secret_key=secret_key)
    except InvalidTokenError:
        raise _not_authenticated() from None
    subject = payload.get("sub")
    email = payload.get("email")
    full_name = payload.get("full_name")
    token_version = payload.get("token_version")
    if not isinstance(subject, str) or not isinstance(email, str):
        raise _not_authenticated()
    if not isinstance(token_version, int):
        raise _not_authenticated()
    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise _not_authenticated() from None
    return TokenClaims(
        user_id=user_id,
        email=email,
        full_name=full_name if isinstance(full_name, str) else None,
        token_version=token_version,
    )


async def get_current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    if not settings.enable_security:
        return TEST_USER
    if token is None:
        raise _not_authenticated()
    claims = decode_token(token, secret_key=_token_secret(settings))
    return await _load_user_from_token_claims(settings, claims)


async def _load_user_from_token_claims(settings: Settings, claims: TokenClaims) -> User:
    if not settings.database_url:
        raise _not_authenticated()
    try:
        sessionmaker = get_sessionmaker(settings.database_url)
        async with sessionmaker() as session, session.begin():
            service = UserService(UserRepository(session))
            user = await service.get_user_by_id(claims.user_id)
    except SQLAlchemyError:
        raise _not_authenticated() from None
    if user is None or user.token_version != claims.token_version:
        raise _not_authenticated()
    return User(
        user_id=user.user_id,
        email=user.email,
        full_name=user.full_name,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    service: UserService = Depends(get_user_service),
) -> UserOut:
    email = validate_email(str(payload.email), check_deliverability=False).normalized.lower()
    try:
        user = await service.register_user(
            password=payload.password,
            auth_type=AuthType.PASSWORD,
            role=UserRole.THERAPIST,
            email=email,
            full_name=payload.full_name,
        )
    except UserAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="user already exists",
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to register user",
        ) from exc
    return UserOut.from_user(user)


@router.post("/token", response_model=TokenOut)
async def issue_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    settings: Annotated[Settings, Depends(get_settings)],
    service: UserService = Depends(get_user_service),
) -> TokenOut:
    if not settings.enable_security:
        raise _server_misconfigured()
    try:
        email = validate_email(form.username, check_deliverability=False).normalized.lower()
        user = await service.authenticate_user(
            email=email,
            password=SecretStr(form.password),
        )
    except EmailNotValidError:
        raise _not_authenticated() from None
    except InvalidCredentialsError:
        raise _not_authenticated() from None
    except SQLAlchemyError:
        raise _not_authenticated() from None
    access_token = create_access_token(
        user,
        secret_key=_token_secret(settings),
        ttl_seconds=settings.auth_token_ttl_seconds,
    )
    return TokenOut(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
    service: UserService = Depends(get_user_service),
) -> None:
    if not settings.enable_security:
        return
    try:
        await service.logout(user_id=current_user.user_id)
    except InvalidCredentialsError:
        raise _not_authenticated() from None
    except SQLAlchemyError:
        raise _not_authenticated() from None


@router.get("/whoami", response_model=User)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChange,
    current_user: Annotated[User, Depends(get_current_user)],
    service: UserService = Depends(get_user_service),
) -> None:
    try:
        await service.change_password(
            user_id=current_user.user_id,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except InvalidCredentialsError:
        raise _not_authenticated() from None
    except SQLAlchemyError:
        raise _not_authenticated() from None
