import logging
import mimetypes
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from audio.dependencies import get_audio_service
from audio.errors import raise_for_loader_error
from audio.models import (
    AudioNotFoundError,
    AudioTooLargeError,
    EmptyAudioError,
    UnsupportedAudioTypeError,
)
from audio.schemas import AudioFileInfo, AudioUploadResponse, diarized_segments_from_transcript
from audio.service import AudioService
from calendar_events.models import CalendarEventNotFoundError
from core.database import OptionalSessionDep, SettingsDep
from patients.models import PatientNotFoundError
from summaries.dependencies import build_summary_service
from transcription.errors import raise_for_transcription_error
from transcription.models import TranscriptionFailedError
from transcription.schemas import TranscriptionResponse
from transcripts.models import TranscriptAlreadyExistsError, TranscriptPatientMismatchError
from transcripts.service import TranscriptService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["audio"])


@router.post("/upload", response_model=AudioUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_audio(
    db: OptionalSessionDep,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    service: AudioService = Depends(get_audio_service),
    file: UploadFile = File(...),
    patient_id: uuid.UUID | None = Form(None),
    meeting_id: uuid.UUID | None = Form(None),
) -> AudioUploadResponse:
    try:
        saved, transcript = await service.upload_and_transcribe(file)
    except (
        UnsupportedAudioTypeError,
        EmptyAudioError,
        AudioTooLargeError,
    ) as exc:
        raise_for_loader_error(exc)
    except TranscriptionFailedError as exc:
        raise_for_transcription_error(exc)

    stored_meeting_id: str | None = None
    transcript_id: str | None = None

    # Persist to DB only when Postgres is configured. App clients must send meeting_id.
    if db is not None:
        if meeting_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="meeting_id is required to save a transcript",
            )
        try:
            stored = await TranscriptService(db).save_for_upload(
                meeting_id=meeting_id,
                patient_id=patient_id,
                raw_text=transcript.text,
                language=transcript.language or "he",
                diarized_segments=diarized_segments_from_transcript(transcript),
            )
        except PatientNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except CalendarEventNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except TranscriptPatientMismatchError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except TranscriptAlreadyExistsError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            logger.error("failed to persist transcript", exc_info=exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="failed to persist transcript",
            ) from exc
        stored_meeting_id = str(stored.meeting_id)
        transcript_id = str(stored.id)

        if settings.summary_enabled:
            summary_service = build_summary_service(db, settings)
            # The pending row is written here, inside the request, rather than by the
            # background job: a client polling in the gap between this response and the
            # job starting would otherwise get a 404 for a summary that is on its way.
            await summary_service.create_pending(stored.meeting_id)
            background_tasks.add_task(summary_service.generate, stored.meeting_id)

    return AudioUploadResponse.from_upload(
        saved,
        transcript,
        meeting_id=stored_meeting_id,
        transcript_id=transcript_id,
    )


@router.get("", response_model=list[AudioFileInfo])
async def list_audio_files(
    service: AudioService = Depends(get_audio_service),
) -> list[AudioFileInfo]:
    files = await service.list_files()
    return [AudioFileInfo.from_stored(file) for file in files]


@router.get("/{audio_id}", response_class=FileResponse)
async def download_audio(
    audio_id: str,
    service: AudioService = Depends(get_audio_service),
) -> FileResponse:
    try:
        path = await service.get_path(audio_id)
    except AudioNotFoundError as exc:
        raise_for_loader_error(exc)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.delete("/{audio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_audio(
    audio_id: str,
    service: AudioService = Depends(get_audio_service),
) -> None:
    try:
        await service.delete(audio_id)
    except AudioNotFoundError as exc:
        raise_for_loader_error(exc)


@router.post("/{audio_id}/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    audio_id: str,
    service: AudioService = Depends(get_audio_service),
) -> TranscriptionResponse:
    try:
        transcript = await service.transcribe(audio_id)
    except AudioNotFoundError as exc:
        raise_for_loader_error(exc)
    except TranscriptionFailedError as exc:
        raise_for_transcription_error(exc)
    return TranscriptionResponse.from_transcript(audio_id, transcript)
