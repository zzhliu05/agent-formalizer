from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Verdict = Literal["accepted", "needs_reformalization", "needs_reextraction"]
MethodMatch = Literal["match", "mismatch", "unverifiable"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlindBacktranslation(StrictModel):
    declaration_names: list[str] = Field(min_length=1)
    statement_natural_language: str = Field(min_length=1)
    variables_and_domains: list[str]
    hypotheses: list[str]
    conclusion: str = Field(min_length=1)
    proof_method_summary: str = Field(min_length=1)
    proof_steps: list[str] = Field(min_length=1)
    lean_dependencies: list[str]
    axioms_observed: list[str]
    ambiguity_notes: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class ComparisonIssue(StrictModel):
    code: str = Field(min_length=1)
    severity: Literal["error", "warning"]
    aspect: Literal[
        "statement",
        "variables",
        "domains",
        "hypotheses",
        "quantifiers",
        "conclusion",
        "direction",
        "edge_cases",
        "proof_method",
        "proof_steps",
        "source_completeness",
        "axioms",
        "other",
    ]
    explanation: str = Field(min_length=1)
    revision_instruction: str


class SemanticComparison(StrictModel):
    statement_match: bool
    variables_match: bool
    domains_match: bool
    hypotheses_match: bool
    quantifiers_match: bool
    conclusion_match: bool
    logical_direction_match: bool
    edge_cases_match: bool
    proof_method_match: MethodMatch
    proof_step_correspondence: list[str]
    source_proof_complete: bool
    issues: list[ComparisonIssue]
    verdict: Verdict
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_verdict(self) -> "SemanticComparison":
        statement_checks = (
            self.statement_match,
            self.variables_match,
            self.domains_match,
            self.hypotheses_match,
            self.quantifiers_match,
            self.conclusion_match,
            self.logical_direction_match,
            self.edge_cases_match,
        )
        has_error = any(issue.severity == "error" for issue in self.issues)
        if self.verdict == "accepted":
            if not all(statement_checks):
                raise ValueError("accepted comparison requires every statement check")
            if self.proof_method_match != "match":
                raise ValueError("accepted comparison requires matching proof methods")
            if not self.source_proof_complete:
                raise ValueError("accepted comparison requires a complete source proof")
            if has_error:
                raise ValueError("accepted comparison cannot contain error issues")
        if (
            self.proof_method_match == "unverifiable"
            and self.verdict != "needs_reextraction"
        ):
            raise ValueError(
                "an unverifiable source proof method must route to needs_reextraction"
            )
        return self


class MechanicalAudit(StrictModel):
    independent_build_passed: bool
    independent_build_exit_code: int | None
    independent_build_timed_out: bool
    declaration_names: list[str]
    prohibited_placeholders: list[str]
    forbidden_declarations: list[str]
    axiom_audit_passed: bool
    axioms: list[str]
    unapproved_axioms: list[str]
    axiom_output: str
    passed: bool

    @model_validator(mode="after")
    def validate_passed(self) -> "MechanicalAudit":
        expected = (
            self.independent_build_passed
            and bool(self.declaration_names)
            and not self.prohibited_placeholders
            and not self.forbidden_declarations
            and self.axiom_audit_passed
            and "sorryAx" not in self.axioms
            and not self.unapproved_axioms
        )
        if self.passed != expected:
            raise ValueError("mechanical audit passed flag does not match its gates")
        return self


class RevisionRequest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    theorem_id: str = Field(min_length=1)
    review_attempt: int = Field(ge=1)
    review_json_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_theorem_json_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_main_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_project_id: str = Field(min_length=1)
    current_task_id: str = Field(min_length=1)
    issues: list[ComparisonIssue] = Field(min_length=1)
    instructions: list[str] = Field(min_length=1)
    constraints: list[str] = Field(min_length=1)
