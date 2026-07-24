from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from .models import BlindBacktranslation, SemanticComparison
from .prompts import (
    BLIND_SYSTEM_PROMPT,
    COMPARISON_SYSTEM_PROMPT,
    blind_translation_prompt,
    comparison_prompt,
)

DEFAULT_ENDPOINT = "https://genaiapi.shanghaitech.edu.cn/api/v1/start"
ModelT = TypeVar("ModelT", bound=BaseModel)


class ReviewProviderError(RuntimeError):
    """Secret-safe structured review provider failure."""


@dataclass(frozen=True)
class ProviderResult:
    value: BaseModel
    metadata: dict[str, Any]


class ReviewProvider(Protocol):
    def backtranslate(
        self,
        *,
        lean_sources: dict[str, str],
        declaration_names: list[str],
        axiom_output: str,
    ) -> ProviderResult: ...

    def compare(
        self,
        backtranslation: BlindBacktranslation,
        *,
        source_statement: str,
        source_proof: str,
        source_proof_status: str,
        source_proof_steps: list[str],
        source_context: list[str],
        source_uncertainties: list[str],
    ) -> ProviderResult: ...


class GPT55ReviewClient:
    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = "GPT-5.5",
        deployment: str = "east-US-2-gpt-5.5",
        reasoning_effort: str = "medium",
        max_completion_tokens: int = 32768,
        max_attempts: int = 3,
        timeout_seconds: float = 600,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
        }:
            raise ValueError("review endpoint must use HTTPS")
        self._api_key = api_key
        self.endpoint = endpoint
        self.model_name = model
        self.deployment = deployment
        self.reasoning_effort = reasoning_effort
        self.max_completion_tokens = max_completion_tokens
        self.max_attempts = max_attempts
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GPT55ReviewClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request_body(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: type[BaseModel],
    ) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "reasoning_effort": self.reasoning_effort,
            "max_completion_tokens": self.max_completion_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
        }

    def _call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: type[ModelT],
    ) -> ProviderResult:
        body = self._request_body(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_name=schema_name,
            schema=schema,
        )
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                if response.status_code in {408, 409, 429} or response.status_code >= 500:
                    raise ReviewProviderError(
                        f"transient provider HTTP status {response.status_code}"
                    )
                response.raise_for_status()
                payload = response.json()
                if payload.get("success") is False:
                    raise ReviewProviderError(
                        f"provider error {payload.get('code', 'unknown')}: "
                        f"{payload.get('message', 'request rejected')}"
                    )
                choice = payload["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise ReviewProviderError("provider returned an incomplete response")
                content = choice["message"].get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ReviewProviderError("provider returned empty structured content")
                value = schema.model_validate_json(content)
                return ProviderResult(
                    value=value,
                    metadata={
                        "request_id": str(payload.get("id", "")),
                        "requested_model": self.model_name,
                        "resolved_model": str(payload.get("model", "")),
                        "deployment": self.deployment,
                        "finish_reason": "stop",
                        "usage": payload.get("usage", {}),
                    },
                )
            except (
                httpx.TimeoutException,
                httpx.TransportError,
                httpx.HTTPStatusError,
                KeyError,
                IndexError,
                json.JSONDecodeError,
                ValidationError,
                ReviewProviderError,
            ) as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 8))
        message = str(last_error or "unknown provider failure").replace(
            self._api_key, "[REDACTED]"
        )
        raise ReviewProviderError(
            f"review provider failed after {self.max_attempts} attempt(s): {message}"
        ) from last_error

    def backtranslate(
        self,
        *,
        lean_sources: dict[str, str],
        declaration_names: list[str],
        axiom_output: str,
    ) -> ProviderResult:
        return self._call(
            system_prompt=BLIND_SYSTEM_PROMPT,
            user_prompt=blind_translation_prompt(
                lean_sources, declaration_names, axiom_output
            ),
            schema_name="lean_blind_backtranslation",
            schema=BlindBacktranslation,
        )

    def compare(
        self,
        backtranslation: BlindBacktranslation,
        *,
        source_statement: str,
        source_proof: str,
        source_proof_status: str,
        source_proof_steps: list[str],
        source_context: list[str],
        source_uncertainties: list[str],
    ) -> ProviderResult:
        return self._call(
            system_prompt=COMPARISON_SYSTEM_PROMPT,
            user_prompt=comparison_prompt(
                backtranslation,
                source_statement=source_statement,
                source_proof=source_proof,
                source_proof_status=source_proof_status,
                source_proof_steps=source_proof_steps,
                source_context=source_context,
                source_uncertainties=source_uncertainties,
            ),
            schema_name="source_lean_semantic_comparison",
            schema=SemanticComparison,
        )
