from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


TheoremKind = Literal[
    "theorem",
    "lemma",
    "proposition",
    "corollary",
    "axiom",
    "claim",
    "exercise-claim",
]
EvidenceStatus = Literal["quoted", "inferred", "unresolved"]


class SourceAnchor(BaseModel):
    """Pages are one-based within the PDF chunk returned to Gemini."""

    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    section: str | None = None
    heading: str | None = None

    @model_validator(mode="after")
    def page_order(self) -> "SourceAnchor":
        if self.page_end < self.page_start:
            raise ValueError("page_end must not precede page_start")
        return self


class NotationItem(BaseModel):
    symbol: str
    meaning: str
    source_page: int | None = Field(default=None, ge=1)
    source_status: EvidenceStatus = "quoted"


class Prerequisite(BaseModel):
    label: str
    kind: str
    statement: str
    relation: str = Field(description="Why this item is needed for the theorem")
    source_page: int | None = Field(default=None, ge=1)
    source_status: EvidenceStatus
    confidence: float = Field(ge=0, le=1)


class Ambiguity(BaseModel):
    text: str
    reason: str
    source_page: int | None = Field(default=None, ge=1)


class PageObservation(BaseModel):
    page_number: int = Field(ge=1)
    transcription: str = Field(
        description="Layout-aware OCR of theorem-bearing text and prerequisite context"
    )
    detected_labels: list[str] = Field(
        default_factory=list,
        description="Printed labels such as Definition 1.2, Proposition 0.6, or Theorem 0.8",
    )
    formulas_latex: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class TheoremCandidate(BaseModel):
    local_id: str = Field(description="Identifier unique only within this model response")
    kind: TheoremKind
    title: str | None = None
    original_text: str = Field(description="Faithful transcription of the source statement")
    normalized_statement: str = Field(description="Notation-preserving readable normalization")
    variables: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    conclusion: str
    source_anchor: SourceAnchor
    notation: list[NotationItem] = Field(default_factory=list)
    prerequisites: list[Prerequisite] = Field(default_factory=list)
    surrounding_context: str = ""
    proof_sketch: str | None = None
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ChunkExtraction(BaseModel):
    document_title: str | None = None
    chunk_summary: str
    pages: list[PageObservation] = Field(default_factory=list)
    candidates: list[TheoremCandidate] = Field(default_factory=list)


class CandidateExtractionResult(BaseModel):
    candidates: list[TheoremCandidate]
