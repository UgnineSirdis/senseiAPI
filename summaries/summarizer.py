import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from summaries.models import Summary, SummaryFailedError
from summaries.prompt import THERAPIST_SUMMARY_SYSTEM_PROMPT

if TYPE_CHECKING:
    from ollama import AsyncClient

logger = logging.getLogger(__name__)


class Summarizer(ABC):
    """Turns a transcript into a session summary."""

    @abstractmethod
    async def summarize(self, *, text: str, language: str) -> Summary: ...


class OllamaSummarizer(Summarizer):
    """Summarization by a local model served by Ollama (Qwen by default)."""

    def __init__(self, *, client: "AsyncClient", model: str, num_ctx: int) -> None:
        self._client = client
        self._model = model
        self._num_ctx = num_ctx

    async def summarize(self, *, text: str, language: str) -> Summary:
        try:
            response = await self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": THERAPIST_SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                # Ollama defaults num_ctx to 2048 and silently truncates anything longer,
                # which would summarise the opening minutes of a session and say nothing.
                options={"num_ctx": self._num_ctx},
            )
        except Exception as exc:
            logger.error("ollama summarization failed", exc_info=exc)
            raise SummaryFailedError(f"summarization failed: {exc}") from exc

        summary_text = response["message"]["content"].strip()
        if not summary_text:
            raise SummaryFailedError("the model returned an empty summary")
        return Summary(text=summary_text, model=self._model)
