from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .models import ChunkMarkdown


class GeminiTranscriptionError(RuntimeError):
    pass


class GeminiMarkdownExtractor:
    """Gemini adapter limited to PDF-to-Markdown transcription."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("A non-empty Gemini API key is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install the google-genai package before using Gemini") from exc

        self._api_key = api_key
        self.model_name = model
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._client = genai.Client(api_key=api_key)

    def extract(self, pdf_path: Path, prompt: str) -> ChunkMarkdown:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return self._extract_once(pdf_path, prompt)
            except Exception as exc:
                last_error = exc
                if attempt == self._max_attempts or not _is_retryable(exc):
                    break
                self._sleep(5 * (2 ** (attempt - 1)))

        assert last_error is not None
        message = str(last_error).replace(self._api_key, "[REDACTED]")
        raise GeminiTranscriptionError(f"Gemini transcription failed: {message}") from last_error

    def _extract_once(self, pdf_path: Path, prompt: str) -> ChunkMarkdown:
        uploaded = None
        try:
            uploaded = self._client.files.upload(file=pdf_path)
            interaction = self._client.interactions.create(
                model=self.model_name,
                input=[
                    {
                        "type": "document",
                        "uri": uploaded.uri,
                        "mime_type": uploaded.mime_type or "application/pdf",
                    },
                    {"type": "text", "text": prompt},
                ],
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": ChunkMarkdown.model_json_schema(),
                },
            )
            return ChunkMarkdown.model_validate_json(interaction.output_text)
        finally:
            if uploaded is not None and getattr(uploaded, "name", None):
                try:
                    self._client.files.delete(name=uploaded.name)
                except Exception:
                    pass


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in {429, 500, 502, 503, 504}:
        return True
    text = str(exc).casefold()
    return any(
        marker in text
        for marker in (
            "high demand",
            "temporar",
            "rate limit",
            "resource exhausted",
            "service unavailable",
            "internal server error",
        )
    )
