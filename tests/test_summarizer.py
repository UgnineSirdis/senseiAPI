from typing import Any

import pytest

from summaries.models import Summary, SummaryFailedError
from summaries.summarizer import OllamaSummarizer

HEBREW_TRANSCRIPT = "מטפל: איך עבר עליך השבוע? מטופל: היה קשה, הרבה חרדה."
HEBREW_SUMMARY = "## נושאים מרכזיים\nחרדה במהלך השבוע."


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeOllamaClient:
    """Stands in for ``ollama.AsyncClient``."""

    def __init__(self, content: str = HEBREW_SUMMARY, error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def chat(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"message": {"content": self._content}}


@pytest.mark.anyio
async def test_summarize_returns_the_models_summary() -> None:
    client = _FakeOllamaClient()
    summarizer = OllamaSummarizer(client=client, model="qwen2.5:7b-instruct", num_ctx=32768)

    summary = await summarizer.summarize(text=HEBREW_TRANSCRIPT, language="he")

    assert summary == Summary(text=HEBREW_SUMMARY, model="qwen2.5:7b-instruct")


@pytest.mark.anyio
async def test_summarize_passes_num_ctx_to_ollama() -> None:
    """Ollama defaults num_ctx to 2048 and silently truncates past it, which would
    summarise the first few minutes of a session and never say so."""
    client = _FakeOllamaClient()
    summarizer = OllamaSummarizer(client=client, model="qwen2.5:7b-instruct", num_ctx=32768)

    await summarizer.summarize(text=HEBREW_TRANSCRIPT, language="he")

    assert client.calls[0]["options"]["num_ctx"] == 32768


@pytest.mark.anyio
async def test_summarize_sends_the_transcript_and_system_prompt() -> None:
    client = _FakeOllamaClient()
    summarizer = OllamaSummarizer(client=client, model="qwen2.5:7b-instruct", num_ctx=32768)

    await summarizer.summarize(text=HEBREW_TRANSCRIPT, language="he")

    messages = client.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "לא נאמרו אמירות מפורשות של סיכון" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": HEBREW_TRANSCRIPT}


@pytest.mark.anyio
async def test_summarize_wraps_ollama_errors() -> None:
    client = _FakeOllamaClient(error=ConnectionError("connection refused"))
    summarizer = OllamaSummarizer(client=client, model="qwen2.5:7b-instruct", num_ctx=32768)

    with pytest.raises(SummaryFailedError):
        await summarizer.summarize(text=HEBREW_TRANSCRIPT, language="he")


@pytest.mark.anyio
async def test_summarize_rejects_an_empty_response() -> None:
    """An empty summary is a failure, not a session with nothing in it."""
    client = _FakeOllamaClient(content="   ")
    summarizer = OllamaSummarizer(client=client, model="qwen2.5:7b-instruct", num_ctx=32768)

    with pytest.raises(SummaryFailedError):
        await summarizer.summarize(text=HEBREW_TRANSCRIPT, language="he")
