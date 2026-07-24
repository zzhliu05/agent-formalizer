from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TheoremKind = Literal[
    "theorem",
    "lemma",
    "proposition",
    "corollary",
    "axiom",
    "definition",
    "claim",
    "identity",
    "criterion",
    "other",
]
ProofStatus = Literal[
    "complete",
    "partial",
    "omitted",
    "by_reference",
    "left_to_reader",
    "not_applicable",
    "uncertain",
]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProofStep(StrictModel):
    order: int = Field(ge=1)
    role: str = Field(min_length=1)
    text_verbatim: str = Field(min_length=1)
    source_pages: list[int] = Field(min_length=1)

    @field_validator("source_pages")
    @classmethod
    def validate_pages(cls, pages: list[int]) -> list[int]:
        if any(page < 1 for page in pages):
            raise ValueError("source page numbers must be positive")
        return pages


class ProofOmission(StrictModel):
    is_omitted: bool
    reason: str | None
    marker_verbatim: str | None
    note: str | None


class ContextItem(StrictModel):
    relation: str = Field(min_length=1)
    label_verbatim: str | None
    text_verbatim: str = Field(min_length=1)
    source_pages: list[int] = Field(min_length=1)
    relevance: str = Field(min_length=1)

    @field_validator("source_pages")
    @classmethod
    def validate_pages(cls, pages: list[int]) -> list[int]:
        if any(page < 1 for page in pages):
            raise ValueError("context page numbers must be positive")
        return pages


class ExtractedResult(StrictModel):
    source_pages: list[int] = Field(min_length=1)
    kind: TheoremKind
    label_verbatim: str | None
    title_verbatim: str | None
    statement_verbatim: str = Field(min_length=1)
    proof_status: ProofStatus
    proof_verbatim: str | None
    proof_steps: list[ProofStep]
    omission: ProofOmission
    context_items: list[ContextItem]
    uncertainties: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    record_complete_in_chunk: bool
    boundary_note: str | None

    @field_validator("source_pages")
    @classmethod
    def validate_pages(cls, pages: list[int]) -> list[int]:
        if any(page < 1 for page in pages):
            raise ValueError("source page numbers must be positive")
        if len(set(pages)) != len(pages):
            raise ValueError("source page numbers must be unique")
        return pages

    @model_validator(mode="after")
    def validate_proof_consistency(self) -> "ExtractedResult":
        if self.proof_status == "complete" and not self.proof_verbatim:
            raise ValueError("complete proof status requires proof_verbatim")
        if self.omission.is_omitted and self.proof_status == "complete":
            raise ValueError("a complete proof cannot also be marked omitted")
        if self.omission.is_omitted and not self.omission.reason:
            raise ValueError("omitted proof requires an omission reason")
        return self


class SourceReference(StrictModel):
    markdown_file: str = Field(min_length=1)
    markdown_sha256: str
    pdf_pages: list[int] = Field(min_length=1)
    overlap_variant: bool

    @field_validator("markdown_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("markdown_sha256 must be a lowercase SHA-256 digest")
        return value


class ProviderMetadata(StrictModel):
    request_id: str | None
    requested_model: str | None
    resolved_model: str | None
    deployment: str | None
    finish_reason: str | None
    usage: dict[str, Any] | None


class TheoremPackage(StrictModel):
    schema_version: Literal["1.0"]
    theorem_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    extraction_run_id: str = Field(min_length=1)
    source: SourceReference
    result: ExtractedResult
    provider: ProviderMetadata

    @field_validator("theorem_id")
    @classmethod
    def validate_theorem_id(cls, value: str) -> str:
        if not _SAFE_ID_RE.fullmatch(value):
            raise ValueError(
                "theorem_id must contain only ASCII letters, digits, '.', '_' or '-'"
            )
        return value

    @model_validator(mode="after")
    def validate_page_consistency(self) -> "TheoremPackage":
        if self.source.pdf_pages != self.result.source_pages:
            raise ValueError("source.pdf_pages must exactly match result.source_pages")
        return self


class LatestExtractionPointer(StrictModel):
    theorem_id: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    path: str = Field(min_length=1)
    theorem_json_sha256: str

    @field_validator("theorem_json_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError(
                "latest pointer theorem_json_sha256 must be a lowercase SHA-256 digest"
            )
        return value
