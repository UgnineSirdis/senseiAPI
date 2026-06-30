import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from audio import router as audio_router
from calendar_events import router as calendar_router
from core.config import Settings, get_settings
from core.database import close_database, init_database, ping_database
from patients import router as patients_router

logger = logging.getLogger(__name__)

SettingsDep = Annotated[Settings, Depends(get_settings)]


class RootResponse(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings_factory = app.dependency_overrides.get(get_settings, get_settings)
    settings = settings_factory()
    await init_database(settings)
    yield
    await close_database(settings.database_url)


app = FastAPI(title="SenseiAPI", version="0.1.0", lifespan=lifespan)

app.include_router(audio_router)
app.include_router(calendar_router)
app.include_router(patients_router)


@app.get("/", response_model=RootResponse)
async def root() -> RootResponse:
    return RootResponse(message="Welcome to SenseiAPI")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/ready", response_model=ReadinessResponse)
async def readiness(settings: SettingsDep, response: Response) -> ReadinessResponse:
    try:
        await ping_database(settings)
    except (OSError, SQLAlchemyError) as exc:
        logger.warning("Database readiness check failed: %s", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="not_ready", database="unavailable")

    return ReadinessResponse(status="ready", database="ok")
