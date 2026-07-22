from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .models import CandidateExtractionResult, ChunkExtraction
from .prompts import candidate_recovery_prompt, context_enrichment_prompt


class GeminiExtractionError(RuntimeError):
    pass


class GeminiExtractor:
    """Thin adapter around the current Google GenAI Interactions API."""

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
        except ImportError as exc:  # pragma: no cover - installation failure path
            raise RuntimeError("Install the google-genai package before using Gemini") from exc

        self._api_key = api_key
        self._model = model
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._client = genai.Client(api_key=api_key)

    def extract(self, pdf_path: Path, prompt: str) -> ChunkExtraction:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                result = self._extract_once(pdf_path, prompt)
                if _needs_candidate_recovery(result):
                    recovered = self._recover_candidates(result)
                    result = result.model_copy(update={"candidates": recovered.candidates})
                if _needs_context_enrichment(result):
                    enriched = self._enrich_candidates(result)
                    result = result.model_copy(
                        update={
                            "candidates": _merge_enrichment(
                                result.candidates, enriched.candidates
                            )
                        }
                    )
                return result
            except Exception as exc:
                last_error = exc
                if attempt == self._max_attempts or not _is_retryable(exc):
                    break
                self._sleep(5 * (2 ** (attempt - 1)))

        assert last_error is not None
        message = str(last_error).replace(self._api_key, "[REDACTED]")
        raise GeminiExtractionError(f"Gemini extraction failed: {message}") from last_error

    def _extract_once(self, pdf_path: Path, prompt: str) -> ChunkExtraction:
        uploaded = None
        try:
            uploaded = self._client.files.upload(file=pdf_path)
            interaction = self._client.interactions.create(
                model=self._model,
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
                    "schema": ChunkExtraction.model_json_schema(),
                },
            )
            return ChunkExtraction.model_validate_json(interaction.output_text)
        finally:
            if uploaded is not None and getattr(uploaded, "name", None):
                try:
                    self._client.files.delete(name=uploaded.name)
                except Exception:
                    pass

    def _recover_candidates(self, result: ChunkExtraction) -> CandidateExtractionResult:
        interaction = self._client.interactions.create(
            model=self._model,
            input=candidate_recovery_prompt(result.pages),
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": CandidateExtractionResult.model_json_schema(),
            },
        )
        return CandidateExtractionResult.model_validate_json(interaction.output_text)

    def _enrich_candidates(self, result: ChunkExtraction) -> CandidateExtractionResult:
        interaction = self._client.interactions.create(
            model=self._model,
            input=context_enrichment_prompt(result.pages, result.candidates),
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": CandidateExtractionResult.model_json_schema(),
            },
        )
        return CandidateExtractionResult.model_validate_json(interaction.output_text)


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


def _needs_candidate_recovery(result: ChunkExtraction) -> bool:
    return not result.candidates and any(page.detected_labels for page in result.pages)


def _needs_context_enrichment(result: ChunkExtraction) -> bool:
    return bool(result.pages and result.candidates) and any(
        not candidate.prerequisites and not candidate.notation
        for candidate in result.candidates
    )


def _merge_enrichment(
    original: list, enriched: list
) -> list:
    enriched_by_id = {candidate.local_id: candidate for candidate in enriched}
    merged = []
    for candidate in original:
        update = enriched_by_id.get(candidate.local_id)
        if update is None:
            merged.append(candidate)
            continue
        merged.append(
            candidate.model_copy(
                update={
                    "notation": update.notation,
                    "prerequisites": update.prerequisites,
                    "surrounding_context": update.surrounding_context,
                    "proof_sketch": update.proof_sketch,
                    "ambiguities": update.ambiguities,
                    "confidence": min(candidate.confidence, update.confidence),
                }
            )
        )
    return merged
