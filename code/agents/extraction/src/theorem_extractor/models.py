from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResultKind(StrEnum):
    THEOREM = "theorem"
    LEMMA = "lemma"
    PROPOSITION = "proposition"
    COROLLARY = "corollary"
    AXIOM = "axiom"
    DEFINITION = "definition"
    CLAIM = "claim"
    IDENTITY = "identity"
    CRITERION = "criterion"
    OTHER = "other"


class ProofStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    OMITTED = "omitted"
    BY_REFERENCE = "by_reference"
    LEFT_TO_READER = "left_to_reader"
    NOT_APPLICABLE = "not_applicable"
    UNCERTAIN = "uncertain"


class OmissionReason(StrEnum):
    NONE = "none"
    NO_PROOF_PRESENT = "no_proof_present"
    EXPLICITLY_OMITTED = "explicitly_omitted"
    BY_REFERENCE = "by_reference"
    LEFT_TO_READER = "left_to_reader"
    CHUNK_BOUNDARY = "chunk_boundary"
    OCR_UNCERTAINTY = "ocr_uncertainty"
    OTHER = "other"


class ProofStepRole(StrEnum):
    SETUP = "setup"
    REDUCTION = "reduction"
    INFERENCE = "inference"
    CALCULATION = "calculation"
    CONSTRUCTION = "construction"
    CASE = "case"
    CITATION = "citation"
    CONCLUSION = "conclusion"
    OTHER = "other"


class ContextRelation(StrEnum):
    LOCAL_DEFINITION = "local_definition"
    NOTATION = "notation"
    STANDING_ASSUMPTION = "standing_assumption"
    EXPLICIT_DEPENDENCY = "explicit_dependency"
    IMPLICIT_DEPENDENCY = "implicit_dependency"
    SECTION_SCOPE = "section_scope"
    OTHER = "other"


class ProofOmission(StrictModel):
    is_omitted: bool
    reason: OmissionReason
    marker_verbatim: str = Field(
        description="Exact source phrase marking omission/reference, or an empty string"
    )
    note: str = Field(
        description="Short extractor note explaining what the source does not provide"
    )


class ProofStep(StrictModel):
    order: int = Field(ge=1)
    role: ProofStepRole
    text_verbatim: str = Field(
        min_length=1,
        description="An exact, exhaustive consecutive segment of proof_verbatim",
    )
    source_pages: list[int] = Field(min_length=1)


class ContextItem(StrictModel):
    relation: ContextRelation
    label_verbatim: str
    text_verbatim: str = Field(
        min_length=1,
        description="Exact source text that supplies prerequisite context",
    )
    source_pages: list[int] = Field(min_length=1)
    relevance: str = Field(
        min_length=1,
        description="Why this exact source text is needed to understand or formalize the result",
    )


class TheoremCandidate(StrictModel):
    source_pages: list[int] = Field(min_length=1)
    kind: ResultKind
    label_verbatim: str = Field(
        min_length=1,
        description="Printed result label, including its number when present",
    )
    title_verbatim: str = Field(
        description="Printed result title/name, or an empty string"
    )
    statement_verbatim: str = Field(
        min_length=1,
        description="Complete printed label and statement, copied exactly from the Markdown",
    )
    proof_status: ProofStatus
    proof_verbatim: str = Field(
        description="Complete printed proof block copied exactly, or an empty string"
    )
    proof_steps: list[ProofStep] = Field(
        description="Ordered exhaustive partition of proof_verbatim"
    )
    omission: ProofOmission
    context_items: list[ContextItem]
    uncertainties: list[str]
    confidence: float = Field(ge=0, le=1)
    record_complete_in_chunk: bool
    boundary_note: str = Field(
        description="Chunk-boundary limitation, or an empty string"
    )

    @model_validator(mode="after")
    def validate_proof_state(self) -> "TheoremCandidate":
        omitted_statuses = {
            ProofStatus.OMITTED,
            ProofStatus.BY_REFERENCE,
            ProofStatus.LEFT_TO_READER,
            ProofStatus.PARTIAL,
            ProofStatus.UNCERTAIN,
        }
        if self.proof_status == ProofStatus.COMPLETE:
            if not self.proof_verbatim or not self.proof_steps:
                raise ValueError("a complete proof requires proof_verbatim and proof_steps")
            if self.omission.is_omitted or self.omission.reason != OmissionReason.NONE:
                raise ValueError("a complete proof cannot be marked omitted")
        if self.proof_status == ProofStatus.OMITTED:
            if self.proof_verbatim or self.proof_steps:
                raise ValueError("an omitted proof cannot contain proof text or steps")
        if self.proof_status == ProofStatus.NOT_APPLICABLE:
            if self.proof_verbatim or self.proof_steps or self.omission.is_omitted:
                raise ValueError("not_applicable is not a proof omission")
        if self.proof_status in omitted_statuses and not self.omission.is_omitted:
            raise ValueError(f"{self.proof_status.value} must carry an omission marker")
        if self.omission.is_omitted and self.omission.reason == OmissionReason.NONE:
            raise ValueError("an omitted proof requires a non-none reason")
        if self.omission.is_omitted and not self.omission.note.strip():
            raise ValueError("an omitted proof requires an explanatory note")
        return self


class TheoremExtractionBatch(StrictModel):
    candidates: list[TheoremCandidate]
