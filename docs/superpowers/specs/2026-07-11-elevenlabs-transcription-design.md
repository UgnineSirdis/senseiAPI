# ElevenLabs Transcription Backend

**Date:** 2026-07-11
**Status:** Approved

## Goal

Replace local Whisper as the default speech-to-text engine with the ElevenLabs
Speech-to-Text API (Scribe), keeping the local Whisper backend selectable via
configuration. Add word-level timestamps to the transcription result.

## Motivation

Transcription currently runs `faster-whisper` in-process. The model is heavy to
load, slow on CPU, and Hebrew accuracy at the `small` size is mediocre.
ElevenLabs Scribe transcribes Hebrew well, returns word-level timings, and
removes the local model from the request path.

Whisper stays available because ElevenLabs requires an API key, network access,
and is billed per minute of audio. Developers need an offline path.

## Non-goals

- Speaker diarization. ElevenLabs supports it (`diarize`, `speaker_id`), and this
  is a therapy-session product where therapist/patient separation is valuable,
  but it changes the API contract and belongs in its own spec.
- Persisting transcripts to the database.
- Streaming / real-time transcription.
- Removing `faster-whisper`.

## Architecture

The existing `Transcriber` ABC in `transcription/transcriber.py` and the
`get_transcriber` FastAPI dependency already isolate the engine from the router.
No structural change is needed — one new implementation and a config switch.

```
audio/router.py
  -> Depends(get_transcriber)          # transcription/dependencies.py
       -> ElevenLabsTranscriber        # default
       -> LocalWhisperTranscriber      # TRANSCRIBER_BACKEND=whisper
  -> Transcriber.transcribe(...) -> Transcript
  -> TranscriptionResponse.from_transcript(...)
```

## Components

### 1. Configuration (`core/config.py`)

Add to `Settings`:

| Field | Env var | Default | Notes |
|---|---|---|---|
| `transcriber_backend` | `TRANSCRIBER_BACKEND` | `elevenlabs` | `elevenlabs` \| `whisper` |
| `elevenlabs_api_key` | `ELEVENLABS_API_KEY` | `None` | Required when backend is `elevenlabs` |
| `elevenlabs_model` | `ELEVENLABS_MODEL` | `scribe_v2` | ElevenLabs STT `model_id` |

`transcriber_backend` is typed `Literal["elevenlabs", "whisper"]` so an invalid
value fails at settings load.

All existing `whisper_*` fields stay. `transcribe_language` (default `he`) is
shared: it maps to Whisper's `language` and ElevenLabs' `language_code`.

### 2. Domain model (`transcription/models.py`)

Additive — `Transcript` gains a defaulted field, so existing construction sites
(including test stubs) remain valid.

```python
@dataclass(frozen=True)
class Word:
    """A single transcribed word and its position in the audio."""

    text: str
    start: float  # seconds from start of audio
    end: float


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    words: tuple[Word, ...] = ()
```

### 3. `ElevenLabsTranscriber` (`transcription/transcriber.py`)

Uses the official `elevenlabs` SDK's `AsyncElevenLabs` client, so no threadpool
hop is needed.

```python
response = await client.speech_to_text.convert(
    file=(filename, data),
    model_id=self._model,
    language_code=language,
    timestamps_granularity="word",
)
```

Response mapping:

- `response.text` -> `Transcript.text`
- `response.language_code` -> `Transcript.language`, falling back to the
  requested `language` when absent
- `response.words` -> `Transcript.words`, keeping only entries with
  `type == "word"`. The API also emits `spacing` and `audio_event` entries,
  which carry no lexical content.

Any exception from the SDK (network, auth, rate limit, 4xx/5xx) is logged and
re-raised as `TranscriptionFailedError`, which `transcription/errors.py` already
maps to HTTP 502. Error handling is therefore identical to the Whisper backend.

The client is constructed once per `ElevenLabsTranscriber` instance from the
API key.

### 4. `LocalWhisperTranscriber` (`transcription/transcriber.py`)

Pass `word_timestamps=True` to `model.transcribe(...)` and map each
`segment.words` entry to a `Word`. Both backends therefore return the same
`Transcript` shape — the config switch never changes the API contract.

### 5. Dependency wiring (`transcription/dependencies.py`)

```python
def get_transcriber(settings: Settings = Depends(get_settings)) -> Transcriber:
    if settings.transcriber_backend == "elevenlabs":
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is required when TRANSCRIBER_BACKEND=elevenlabs")
        return ElevenLabsTranscriber(
            api_key=settings.elevenlabs_api_key,
            model=settings.elevenlabs_model,
        )
    return LocalWhisperTranscriber(...)
```

A missing API key fails loudly rather than falling back silently to Whisper: a
silent fallback would mean a production deployment quietly downgrading its
transcription quality.

### 6. API schema (`transcription/schemas.py`)

`TranscriptionResponse` gains a `words` list. Additive: `id`, `language`, and
`text` are unchanged, so existing clients keep working.

```python
class WordOut(BaseModel):
    text: str
    start: float
    end: float


class TranscriptionResponse(BaseModel):
    id: str
    language: str
    text: str
    words: list[WordOut] = []
```

### 7. Dependencies

Add `elevenlabs>=2.0.0` to `requirements.txt`. `faster-whisper` stays.

## Data flow

1. `POST /audio/{id}/transcribe` loads the stored bytes.
2. `get_transcriber` resolves the configured backend.
3. The backend returns a `Transcript` with text, language, and words.
4. `TranscriptionResponse.from_transcript` serialises it.

Failures at step 3 raise `TranscriptionFailedError` -> 502. A missing audio file
still yields 404 via the existing audio-loader path.

## Testing

- Existing router tests (`tests/test_transcribe.py`) keep passing unchanged —
  the stub transcribers return `Transcript` without `words`, which defaults to
  `()`.
- New: `ElevenLabsTranscriber` unit tests against a fake SDK client (no
  network). Cover the happy path, filtering of non-`word` entries, language
  fallback, and SDK exception -> `TranscriptionFailedError`.
- New: `get_transcriber` returns `ElevenLabsTranscriber` by default,
  `LocalWhisperTranscriber` when `TRANSCRIBER_BACKEND=whisper`, and raises when
  the API key is missing.
- New: the transcribe endpoint response includes word timestamps.

No test may make a real ElevenLabs call.

## Documentation

Update `.env.example`, `README.md`, and `AGENTS.md` with the new variables and
the backend switch.
