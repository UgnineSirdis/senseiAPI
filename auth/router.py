from typing import Annotated

from email_validator import EmailNotValidError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import SecretStr

from auth.dependencies import (
    get_auth_service,
    get_current_access_token,
    get_current_user,
    not_authenticated,
)
from auth.models import AuthConfigurationError, AuthProviderError, InvalidCredentialsError
from auth.schemas import (
    OAuthStartRequest,
    OAuthUrlOut,
    PasswordChange,
    PasswordResetRequest,
    TokenOut,
    User,
    UserCreate,
    UserOut,
)
from auth.service import SupabaseAuthService, normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])


def _provider_error(exc: AuthProviderError) -> HTTPException:
    if isinstance(exc, InvalidCredentialsError):
        return not_authenticated()
    return HTTPException(
        status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
        detail=str(exc),
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    service: SupabaseAuthService = Depends(get_auth_service),
) -> UserOut:
    email = normalize_email(str(payload.email))
    try:
        user = await service.register_user(
            password=payload.password,
            email=email,
            full_name=payload.full_name,
        )
    except AuthProviderError as exc:
        raise _provider_error(exc) from exc
    return UserOut.from_auth_user(user)


@router.post("/token", response_model=TokenOut)
async def issue_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    service: SupabaseAuthService = Depends(get_auth_service),
) -> TokenOut:
    try:
        email = normalize_email(form.username)
        session = await service.authenticate_user(
            email=email,
            password=SecretStr(form.password),
        )
    except EmailNotValidError:
        raise not_authenticated() from None
    except AuthProviderError as exc:
        raise _provider_error(exc) from exc
    return TokenOut.from_session(session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    access_token: Annotated[str, Depends(get_current_access_token)],
    service: SupabaseAuthService = Depends(get_auth_service),
) -> None:
    if not access_token:
        return
    try:
        await service.logout(access_token=access_token)
    except AuthProviderError as exc:
        raise _provider_error(exc) from exc


@router.get("/whoami", response_model=User)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChange,
    current_user: Annotated[User, Depends(get_current_user)],
    service: SupabaseAuthService = Depends(get_auth_service),
) -> None:
    if current_user.email is None:
        raise not_authenticated()
    try:
        await service.change_password(
            email=current_user.email,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except AuthProviderError as exc:
        raise _provider_error(exc) from exc


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def request_password_reset(
    payload: PasswordResetRequest,
    service: SupabaseAuthService = Depends(get_auth_service),
) -> None:
    try:
        await service.send_password_reset_email(
            email=normalize_email(str(payload.email)),
            redirect_to=str(payload.redirect_to) if payload.redirect_to else None,
        )
    except AuthProviderError as exc:
        raise _provider_error(exc) from exc


@router.post("/oauth/url", response_model=OAuthUrlOut)
async def create_oauth_url(
    payload: OAuthStartRequest,
    service: SupabaseAuthService = Depends(get_auth_service),
) -> OAuthUrlOut:
    try:
        url = service.oauth_authorize_url(
            provider=payload.provider,
            redirect_to=str(payload.redirect_to) if payload.redirect_to else None,
        )
    except AuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase Auth is not configured",
        ) from exc
    return OAuthUrlOut(url=url)
