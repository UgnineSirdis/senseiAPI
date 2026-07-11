# Meeting Summary via Local Ollama (Qwen)

**Date:** 2026-07-11
**Status:** Approved
**Branch:** `transcriptsdb`

## Goal

After a transcript is persisted for a therapy meeting, generate a Hebrew session
summary from it using a local Qwen model served by Ollama. Generation runs in the
background so uploads stay fast, and the therapist fetches the summary when it is
ready.

## Motivation

Therapists re-read a full transcript to recall what happened in a session. A
structured summary — themes, interventions, follow-ups, and explicitly-stated risk
content — turns a 50-minute transcript into notes they can scan.

The model runs locally via Ollama. Therapy transcripts are protected health
information, and keeping them on the therapist's own machine avoids sending them to
a third-party API.

## Non-goals

- **Safety screening.** The summary is a drafting aid the therapist reviews. It is
  not a clinical record and must never be relied on to catch a risk disclosure.
- Chunked map-reduce summarization of over-long transcripts. v1 fails loudly
  instead (see "Context window" below).
- Regenerating or versioning summaries. The schema allows it later; no endpoint
  exposes it now.
- Summarizing anything other than Hebrew sessions.
- Streaming partial summaries to the client.

## Architecture

Mirrors the existing transcription boundary: an ABC at the seam, one concrete
implementation, collaborators injected, wiring in `dependencies.py`. New
`summaries/` package, sibling to `transcripts/`.

```
POST /audio/upload                            (existing)
  -> transcribe -> StoredTranscript committed
  -> background_tasks.add_task(...)           (new; fire-and-forget)
  -> responds immediately                     (upload latency unchanged)

background: SummaryService.generate(meeting_id)
  -> read StoredTranscript by meeting_id
  -> status = running
  -> Summarizer.summarize(text) -> OllamaSummarizer -> local Qwen
  -> status = ready (+ text)  |  status = failed (+ error)

GET /meetings/{meeting_id}/summary            (new)
  -> 200 { status: "ready",  text: ... }
  -> 202 { status: "pending" | "running" }
  -> 200 { status: "failed", error: ... }
  -> 404 unknown meeting
```

The transcript is committed *before* the job is queued, so a summary failure can
never cost the therapist their transcript.

## Components

### 1. Data model — `meeting_summaries`

One row per meeting, 1:1 with `calendar_events`, mirroring `transcripts`.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | primary key |
| `meeting_id` | uuid | FK -> `calendar_events.id`, unique, `ondelete=CASCADE` |
| `status` | str(16) | `pending` \| `running` \| `ready` \| `failed` |
| `text` | text \| null | The Hebrew summary. Null until `ready`. |
| `model` | str(64) | Model that produced this text, e.g. `qwen2.5:7b-instruct` |
| `error` | text \| null | Failure reason. Null unless `failed`. |
| `created_at` | timestamptz | server default `now()` |
| `updated_at` | timestamptz | updated on each status transition |

`model` is recorded because the model will be swapped, and a summary is only
interpretable if you know what produced it.

Domain model:

```python
@dataclass(frozen=True)
class StoredSummary:
    id: uuid.UUID
    meeting_id: uuid.UUID
    status: SummaryStatus          # Literal["pending", "running", "ready", "failed"]
    text: str | None
    model: str
    error: str | None
    created_at: datetime
    updated_at: datetime
```

### 2. Summarizer seam (`summaries/summarizer.py`)

```python
@dataclass(frozen=True)
class Summary:
    text: str
    model: str


class Summarizer(ABC):
    """Turns a transcript into a session summary."""

    @abstractmethod
    async def summarize(self, *, text: str, language: str) -> Summary: ...


class OllamaSummarizer(Summarizer):
    def __init__(self, *, client: "AsyncClient", model: str, num_ctx: int) -> None: ...
```

The Ollama client is injected, exactly as the ElevenLabs SDK client is injected into
`ElevenLabsTranscriber`. Tests construct the summarizer with a fake client and never
reach the network.

Any exception from Ollama (connection refused, model not pulled, timeout) is logged
and re-raised as `SummaryFailedError`, which the service records as `status=failed`.

### 3. Context window — the silent-truncation trap

**Ollama defaults `num_ctx` to 2048 tokens.** A 50-minute session is far longer.
Left at the default, Ollama silently truncates the input and returns a fluent,
confident summary *of the first few minutes*, with no error and no warning. Hebrew
makes this worse: it tokenizes less efficiently than English, so a Hebrew transcript
consumes more tokens per word.

A silently-truncated clinical note is worse than no note. Therefore:

- `num_ctx` is set explicitly (default `32768`, configurable).
- The transcript is length-checked **before** the model is called. If it exceeds the
  budget, the job fails with
  `status=failed, error="transcript exceeds context window (N tokens > M)"`.
  We do not summarize a fragment.

Budget check uses a conservative character-per-token estimate for Hebrew rather than
a real tokenizer; the estimate errs toward failing early. Chunked map-reduce for long
sessions is a follow-up spec.

### 4. System prompt

Sent as the `system` message; the transcript is the `user` message. Written in
Hebrew, because the model follows instructions most reliably in the language it is
asked to answer in.

```
אתה עוזר תיעוד למטפל/ת בבריאות הנפש. קיבלת תמליל גולמי של פגישת טיפול אחת.
המשימה שלך היא להפיק טיוטת סיכום פגישה בעברית, שהמטפל/ת יקרא ויערוך.

כללי יסוד — הפרתם פוסלת את הסיכום:
- הסתמך אך ורק על מה שנאמר בתמליל. אל תסיק, אל תשלים פערים, ואל תמציא פרטים.
- אל תאבחן, אל תציע אבחנה, ואל תמליץ על טיפול.
- אם נושא כלשהו לא עלה בפגישה, כתוב "לא עלה בפגישה". אל תמלא סעיף ריק בניחושים.
- אם התמליל אינו ברור או קטוע, אמור זאת במפורש במקום לנחש.

כתוב את הסיכום תחת ארבע הכותרות הבאות, בדיוק בסדר הזה:

## נושאים מרכזיים
מה הביא/ה המטופל/ת לפגישה, והנושאים המרכזיים שנדונו.

## התערבויות המטפל/ת
מה עשה/תה המטפל/ת בפועל — טכניקות, שיקופים, משימות שניתנו — וכיצד הגיב/ה המטופל/ת.

## סימני סיכון
כאן חלים כללים מחמירים במיוחד:
- כלול רק אמירות מפורשות של פגיעה עצמית, אובדנות, פגיעה באחר, התעללות או משבר חריף.
- צטט את הדברים מילה במילה מהתמליל, בתוך מרכאות.
- אל תסיק סיכון מרמזים, מטון, או מהקשר. אל תרכך ואל תפרש.
- אם לא נאמרו דברים מפורשים כאלה, כתוב בדיוק: "לא נאמרו אמירות מפורשות של סיכון".

## המשך ומעקב
משימות, הסכמות, ונושאים שסוכם לחזור אליהם בפגישה הבאה.

הסיכום הוא טיוטה לעזר בלבד. הוא אינו רשומה רפואית ואינו כלי לאיתור סיכון.
```

The risk section is deliberately the most constrained. An LLM that *invents* a risk
disclosure sends a therapist chasing something that never happened; one that *misses*
a real disclosure is far worse. Quote-only, explicit-only, with a fixed sentence for
"nothing found," keeps the model from doing either quietly. It does not make the
feature a safety net, and the spec says so plainly.

### 5. Service (`summaries/service.py`)

```python
class SummaryService:
    async def generate(self, meeting_id: uuid.UUID) -> None:
        """Runs in the background. Never raises into the request."""
```

Flow:

1. Load the `StoredTranscript` for `meeting_id`. Missing -> record `failed`.
2. Move the summary row to `status=running`.
3. Pre-flight the length budget. Over budget -> `failed`, model never called.
4. `Summarizer.summarize(...)` -> on success `status=ready, text=...`;
   on `SummaryFailedError` -> `status=failed, error=str(exc)`.

The `pending` row itself is created **synchronously in the upload request**, before
the background job is queued — not by the job. Otherwise a client polling in the gap
between the upload responding and the job starting would get a 404 for a summary that
is in fact on its way. The row exists from the moment the work is promised.

Every terminal state is written to the database. A background job has no HTTP
response to carry an error home on, so the row is the only place a failure can live.

### 6. Trigger (`audio/router.py`)

After the transcript commits, and only when a summary is not already present:

```python
await SummaryService(db).create_pending(meeting_id)   # committed before we respond
background_tasks.add_task(run_summary_job, meeting_id)
```

Gated by `SUMMARY_ENABLED`. The upload response is unchanged.

### 7. Orphan sweep (`main.py` lifespan)

`BackgroundTasks` runs in-process. If the server restarts mid-generation, the row is
stranded in `running` forever and the client spins indefinitely. On startup, any row
left in `running` is marked:

`status=failed, error="interrupted by server restart"`

This is the known cost of choosing `BackgroundTasks` over a durable queue, and the
sweep is what makes that cost survivable.

### 8. API (`summaries/router.py`)

`GET /meetings/{meeting_id}/summary`

| Case | Status | Body |
| --- | --- | --- |
| Ready | 200 | `{status: "ready", text, model}` |
| Pending / running | 202 | `{status: "running"}` |
| Failed | 200 | `{status: "failed", error}` |
| No such meeting | 404 | error detail |
| Meeting exists, but no summary was ever requested | 404 | error detail |

A failure returns 200, not 5xx: the request succeeded, and the *summary* is what
failed. The client renders the error to the therapist.

### 9. Configuration (`core/config.py`)

| Field | Env var | Default |
| --- | --- | --- |
| `summary_enabled` | `SUMMARY_ENABLED` | `true` |
| `ollama_host` | `OLLAMA_HOST` | `http://localhost:11434` |
| `ollama_model` | `OLLAMA_MODEL` | `qwen2.5:7b-instruct` |
| `ollama_num_ctx` | `OLLAMA_NUM_CTX` | `32768` |
| `ollama_timeout_seconds` | `OLLAMA_TIMEOUT_SECONDS` | `600` |

### 10. Dependencies

Add `ollama>=0.4.0` to `requirements.txt`.

## Testing

Seams under test, one vertical slice at a time:

| Seam | Cases |
| --- | --- |
| `OllamaSummarizer.summarize()` | Happy path; `num_ctx` is actually passed through; connection error -> `SummaryFailedError`; empty response -> `SummaryFailedError` |
| `SummaryService.generate()` | pending -> running -> ready; summarizer failure writes `error` and `status=failed`; over-length transcript fails **without calling the model**; missing transcript -> failed |
| `GET /meetings/{id}/summary` | 202 while running; 200 + text when ready; 200 + error when failed; 404 unknown meeting |
| Startup sweep | Orphaned `running` row becomes `failed` |
| `POST /audio/upload` | Still returns immediately; writes a `pending` row before responding; schedules the job; upload succeeds even when summarization is disabled |

No test may reach a real Ollama; the client is injected and faked.

## Verification

Ollama is **not installed** on this machine. The unit tests above run against a fake
client, but they cannot tell us whether Qwen writes a *good* Hebrew summary — the
architecture is the easy part, the output quality is not.

Before this is trusted:

```bash
brew install ollama
ollama pull qwen2.5:7b-instruct
```

then generate a summary from one real Hebrew session and read it. Qwen's Hebrew is
the largest open risk in this design, and only a real transcript will settle it.

## Documentation

Update `.env.example`, `README.md`, and `AGENTS.md` with the new variables, the
Ollama prerequisite, and the "drafting aid, not a safety net" caveat.
