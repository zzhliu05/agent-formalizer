from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from .models import TheoremExtractionBatch
from .prompts import SYSTEM_PROMPT, extraction_prompt


DEFAULT_ENDPOINT = "https://genaiapi.shanghaitech.edu.cn/api/v1/start"


class GPT55ExtractionError(RuntimeError):
    """A secret-safe error raised by the ShanghaiTech GPT-5.5 adapter."""


@dataclass(frozen=True)
class ProviderMetadata:
    request_id: str
    requested_model: str
    resolved_model: str
    deployment: str
    finish_reason: str
    usage: dict[str, Any]


@dataclass(frozen=True)
class ExtractionResponse:
    batch: TheoremExtractionBatch
    metadata: ProviderMetadata


class GPT55Client:
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
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("GPT-5.5 endpoint must use HTTPS")
        if max_completion_tokens < 256:
            raise ValueError("max_completion_tokens must be at least 256")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")

        self._api_key = api_key
        self.endpoint = endpoint
        self.model_name = model
        self.deployment_label = deployment
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

    def __enter__(self) -> "GPT55Client":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request_body(
        self,
        *,
        document_id: str,
        chunk_name: str,
        markdown: str,
    ) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": extraction_prompt(
                        document_id=document_id,
                        chunk_name=chunk_name,
                        markdown=markdown,
                    ),
                },
            ],
            "stream": False,
            "reasoning_effort": self.reasoning_effort,
            "max_completion_tokens": self.max_completion_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "theorem_extraction_batch",
                    "strict": True,
                    "schema": TheoremExtractionBatch.model_json_schema(),
                },
            },
        }

    def extract(
        self,
        *,
        document_id: str,
        chunk_name: str,
        markdown: str,
    ) -> ExtractionResponse:
        body = self._request_body(
            document_id=document_id,
            chunk_name=chunk_name,
            markdown=markdown,
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
                    raise GPT55ExtractionError(
                        f"transient provider HTTP status {response.status_code}"
                    )
                response.raise_for_status()
                payload = response.json()
                if payload.get("success") is False:
                    code = payload.get("code", "unknown")
                    message = str(payload.get("message", "provider rejected the request"))
                    raise GPT55ExtractionError(f"provider error {code}: {message}")

                choice = payload["choices"][0]
                finish_reason = str(choice.get("finish_reason", ""))
                if finish_reason != "stop":
                    raise GPT55ExtractionError(
                        f"incomplete provider response: finish_reason={finish_reason or 'missing'}"
                    )
                message = choice["message"]
                refusal = message.get("refusal")
                if refusal:
                    raise GPT55ExtractionError("provider refused the extraction request")
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise GPT55ExtractionError("provider returned empty structured content")

                batch = TheoremExtractionBatch.model_validate_json(content)
                return ExtractionResponse(
                    batch=batch,
                    metadata=ProviderMetadata(
                        request_id=str(payload.get("id", "")),
                        requested_model=self.model_name,
                        resolved_model=str(payload.get("model", "")),
                        deployment=self.deployment_label,
                        finish_reason=finish_reason,
                        usage=payload.get("usage", {}),
                    ),
                )
            except (
                httpx.TimeoutException,
                httpx.TransportError,
                httpx.HTTPStatusError,
                KeyError,
                IndexError,
                json.JSONDecodeError,
                ValidationError,
                GPT55ExtractionError,
            ) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        message = str(last_error or "unknown provider failure").replace(self._api_key, "[REDACTED]")
        raise GPT55ExtractionError(
            f"GPT-5.5 extraction failed after {self.max_attempts} attempt(s): {message}"
        ) from last_error
