from fastapi import Depends

from core.config import Settings, get_settings
from transcription.transcriber import ElevenLabsTranscriber, LocalWhisperTranscriber, Transcriber


def get_transcriber(settings: Settings = Depends(get_settings)) -> Transcriber:
    if settings.transcriber_backend == "elevenlabs":
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is required when TRANSCRIBER_BACKEND=elevenlabs")
        # Imported lazily so the SDK is only needed when this backend is selected.
        from elevenlabs.client import AsyncElevenLabs

        return ElevenLabsTranscriber(
            client=AsyncElevenLabs(api_key=settings.elevenlabs_api_key),
            model=settings.elevenlabs_model,
        )

    return LocalWhisperTranscriber(
        model_size=settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
