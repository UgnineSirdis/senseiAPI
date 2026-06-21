import logging
from typing import Annotated

from fastapi import Depends, FastAPI, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from audio import router as audio_router
from core.config import Settings, get_settings
from core.database import ping_database

logger = logging.getLogger(__name__)

SettingsDep = Annotated[Settings, Depends(get_settings)]


class RootResponse(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database: str


app = FastAPI(title="SenseiAPI", version="0.1.0")

app.include_router(audio_router)


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
