import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from audio import router as audio_router
from core.config import Settings, get_settings
from core.database import init_database, ping_database

logger = logging.getLogger(__name__)

SettingsDep = Annotated[Settings, Depends(get_settings)]


class RootResponse(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database: str


router = APIRouter()


@router.get("/", response_model=RootResponse)
async def root() -> RootResponse:
    return RootResponse(message="Welcome to SenseiAPI")


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(settings: SettingsDep, response: Response) -> ReadinessResponse:
    try:
        await ping_database(settings)
    except (OSError, SQLAlchemyError) as exc:
        logger.warning("Database readiness check failed: %s", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="not_ready", database="unavailable")

    return ReadinessResponse(status="ready", database="ok")


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        app_settings = settings or get_settings()
        if app_settings.init_database_on_startup:
            try:
                await init_database(app_settings)
            except (OSError, SQLAlchemyError) as exc:
                logger.exception("Database initialization failed")
                raise RuntimeError("Database initialization failed") from exc
        yield

    created_app = FastAPI(title="SenseiAPI", version="0.1.0", lifespan=lifespan)
    if settings is not None:
        created_app.dependency_overrides[get_settings] = lambda: settings
    created_app.include_router(router)
    created_app.include_router(audio_router)
    return created_app


app = create_app()
