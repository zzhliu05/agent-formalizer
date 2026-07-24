from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from formalization_agent.candidate_validation import BuildRunner, run_local_lean_check
from formalization_agent.reader import sha256_bytes

from .lean_audit import audit_candidate
from .models import (
    BlindBacktranslation,
    ComparisonIssue,
    MechanicalAudit,
    RevisionRequest,
    SemanticComparison,
    Verdict,
)
from .provider import ReviewProvider
from .reader import (
    LoadedCandidate,
    load_candidate,
    load_source_after_blind_translation,
)


class ReviewError(RuntimeError):
    """Raised when Agent 3 cannot produce a trustworthy review artifact."""


@dataclass(frozen=True)
class ReviewResult:
    theorem_id: str
    attempt: int
    verdict: Verdict
    attempt_dir: Path
    review_path: Path
    review_markdown_path: Path
    revision_request_path: Path | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: object) -> str:
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def _write_text(path: Path, text: str) -> str:
    data = text.replace("\r\n", "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def _next_attempt(root: Path) -> int:
    attempts: list[int] = []
    if root.is_dir():
        for child in root.iterdir():
            if child.is_dir() and child.name.startswith("attempt-"):
                suffix = child.name.removeprefix("attempt-")
                if suffix.isdigit():
                    attempts.append(int(suffix))
    return max(attempts, default=0) + 1


def _default_review_root(candidate: LoadedCandidate) -> Path:
    generation_root = candidate.handoff_path.parent.parent
    if generation_root.name != "generation":
        raise ReviewError("Agent 2 handoff is not under a generation directory")
    formalization_root = generation_root.parent
    if formalization_root.name != "formalization":
        raise ReviewError("Agent 2 generation is not under formalization")
    return formalization_root.parent / "review"


def _mechanical_issues(audit: MechanicalAudit) -> list[ComparisonIssue]:
    issues: list[ComparisonIssue] = []
    if not audit.independent_build_passed:
        issues.append(
            ComparisonIssue(
                code="lean_build_failed",
                severity="error",
                aspect="other",
                explanation="Agent 3's independent Lean build did not pass.",
                revision_instruction="Return a candidate that compiles under the pinned Lean environment.",
            )
        )
    if audit.prohibited_placeholders:
        issues.append(
            ComparisonIssue(
                code="prohibited_placeholder",
                severity="error",
                aspect="proof_steps",
                explanation=(
                    "Lean source contains prohibited proof placeholders: "
                    + ", ".join(audit.prohibited_placeholders)
                ),
                revision_instruction=(
                    "Replace every placeholder, including placeholders in helper lemmas, "
                    "with kernel-checked proofs."
                ),
            )
        )
    if audit.forbidden_declarations:
        issues.append(
            ComparisonIssue(
                code="new_unproved_declaration",
                severity="error",
                aspect="axioms",
                explanation=(
                    "Candidate introduces unproved declarations: "
                    + ", ".join(audit.forbidden_declarations)
                ),
                revision_instruction=(
                    "Remove candidate-defined axiom/constant/opaque declarations "
                    "and prove all required helpers."
                ),
            )
        )
    if not audit.axiom_audit_passed:
        issues.append(
            ComparisonIssue(
                code="axiom_audit_failed",
                severity="error",
                aspect="axioms",
                explanation="Lean #print axioms audit did not complete successfully.",
                revision_instruction="Return declarations that can be inspected with #print axioms.",
            )
        )
    if "sorryAx" in audit.axioms:
        issues.append(
            ComparisonIssue(
                code="sorry_axiom_dependency",
                severity="error",
                aspect="axioms",
                explanation="At least one declaration depends on sorryAx.",
                revision_instruction="Eliminate the sorryAx dependency with a complete proof.",
            )
        )
    if audit.unapproved_axioms:
        issues.append(
            ComparisonIssue(
                code="unapproved_axiom_dependency",
                severity="error",
                aspect="axioms",
                explanation=(
                    "Candidate depends on axioms outside the approved Lean/Mathlib baseline: "
                    + ", ".join(audit.unapproved_axioms)
                ),
                revision_instruction="Remove every nonstandard axiom dependency.",
            )
        )
    return issues


def _final_verdict(
    audit: MechanicalAudit,
    comparison: SemanticComparison,
    source_proof_status: str,
) -> Verdict:
    if not audit.passed:
        return "needs_reformalization"
    if source_proof_status != "complete":
        return "needs_reextraction"
    return comparison.verdict


def _review_markdown(
    *,
    theorem_id: str,
    audit: MechanicalAudit,
    backtranslation: BlindBacktranslation,
    comparison: SemanticComparison,
    verdict: Verdict,
) -> str:
    issue_lines = "\n".join(
        f"- `{issue.code}` ({issue.aspect}): {issue.explanation}"
        for issue in comparison.issues
    ) or "- None."
    steps = "\n".join(
        f"{index}. {step}" for index, step in enumerate(backtranslation.proof_steps, 1)
    )
    return f"""# Agent 3 Review

Theorem ID: `{theorem_id}`

## Mechanical Audit

- Independent Lean build: `{"passed" if audit.independent_build_passed else "failed"}`
- Placeholder scan: `{"passed" if not audit.prohibited_placeholders else "failed"}`
- New axiom/constant/opaque scan: `{"passed" if not audit.forbidden_declarations else "failed"}`
- `#print axioms`: `{"passed" if audit.axiom_audit_passed else "failed"}`
- Observed axioms: `{", ".join(audit.axioms) if audit.axioms else "none"}`

## Lean-Only Back-Translation

{backtranslation.statement_natural_language}

Proof method: {backtranslation.proof_method_summary}

{steps}

## Source Comparison

- Statement match: `{str(comparison.statement_match).lower()}`
- Proof method: `{comparison.proof_method_match}`
- Source proof complete: `{str(comparison.source_proof_complete).lower()}`

{issue_lines}

## Verdict

`{verdict}`
"""


def review_candidate(
    handoff_input: str | Path,
    source_input: str | Path,
    *,
    provider: ReviewProvider,
    template_root: str | Path,
    review_root: str | Path | None = None,
    build_timeout_seconds: int = 1800,
    build_runner: BuildRunner = run_local_lean_check,
) -> ReviewResult:
    candidate = load_candidate(handoff_input)
    root = (
        Path(review_root).resolve()
        if review_root is not None
        else _default_review_root(candidate)
    )
    root.mkdir(parents=True, exist_ok=True)
    attempt = _next_attempt(root)
    attempt_name = f"attempt-{attempt:03d}"
    attempt_dir = root / attempt_name
    staging = root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        audit = audit_candidate(
            candidate,
            template_root=template_root,
            work_dir=staging / "mechanical",
            build_timeout_seconds=build_timeout_seconds,
            build_runner=build_runner,
        )
        _write_json(staging / "mechanical" / "audit.json", audit.model_dump(mode="json"))

        lean_input = {
            "schema_version": "1.0",
            "theorem_id": candidate.theorem_id,
            "allowed_input_class": "lean_only",
            "lean_files": candidate.lean_sources,
            "declaration_names": audit.declaration_names,
            "axiom_output": audit.axiom_output,
        }
        _write_json(staging / "blind" / "lean-input.json", lean_input)
        blind_response = provider.backtranslate(
            lean_sources=candidate.lean_sources,
            declaration_names=audit.declaration_names,
            axiom_output=audit.axiom_output,
        )
        if not isinstance(blind_response.value, BlindBacktranslation):
            raise ReviewError("blind provider returned the wrong schema")
        backtranslation = blind_response.value
        backtranslation_hash = _write_json(
            staging / "blind" / "backtranslation.json",
            {
                "schema_version": "1.0",
                "created_at": _now(),
                "input_policy": "lean_only",
                "result": backtranslation.model_dump(mode="json"),
                "provider": blind_response.metadata,
            },
        )

        # This is intentionally the first source-package read in the review flow.
        source = load_source_after_blind_translation(
            source_input,
            expected_theorem_id=candidate.theorem_id,
            expected_sha256=candidate.source_theorem_json_sha256,
        )
        result = source.package.result
        comparison_response = provider.compare(
            backtranslation,
            source_statement=result.statement_verbatim,
            source_proof=result.proof_verbatim or "",
            source_proof_status=result.proof_status,
            source_proof_steps=[step.text_verbatim for step in result.proof_steps],
            source_context=[item.text_verbatim for item in result.context_items],
            source_uncertainties=result.uncertainties,
        )
        if not isinstance(comparison_response.value, SemanticComparison):
            raise ReviewError("comparison provider returned the wrong schema")
        comparison = comparison_response.value
        mechanical_issues = _mechanical_issues(audit)
        if mechanical_issues:
            comparison = SemanticComparison.model_validate(
                {
                    **comparison.model_dump(mode="json"),
                    "issues": [
                        *[
                            issue.model_dump(mode="json")
                            for issue in mechanical_issues
                        ],
                        *[
                            issue.model_dump(mode="json")
                            for issue in comparison.issues
                        ],
                    ],
                    "verdict": (
                        "needs_reextraction"
                        if comparison.proof_method_match == "unverifiable"
                        else "needs_reformalization"
                    ),
                    "rationale": (
                        "Agent 3 mechanical gates failed independently of the "
                        "semantic comparison. " + comparison.rationale
                    ),
                }
            )
        verdict = _final_verdict(audit, comparison, result.proof_status)

        comparison_hash = _write_json(
            staging / "comparison" / "comparison.json",
            {
                "schema_version": "1.0",
                "created_at": _now(),
                "blind_backtranslation_sha256": backtranslation_hash,
                "source_theorem_json_sha256": source.theorem_json_sha256,
                "result": comparison.model_dump(mode="json"),
                "effective_verdict": verdict,
                "provider": comparison_response.metadata,
            },
        )
        review_payload: dict[str, Any] = {
            "schema_version": "1.0",
            "theorem_id": candidate.theorem_id,
            "attempt": attempt,
            "created_at": _now(),
            "verdict": verdict,
            "input": {
                "agent2_handoff_path": str(candidate.handoff_path),
                "agent2_main_sha256": candidate.handoff["candidate"][
                    "lean_file_hashes"
                ][
                    candidate.main_path.relative_to(candidate.candidate_root).as_posix()
                ],
                "agent1_theorem_json_sha256": source.theorem_json_sha256,
            },
            "isolation": {
                "blind_stage_input": "lean_only",
                "source_opened_after_backtranslation_sha256": backtranslation_hash,
                "agent2_prose_used": False,
            },
            "artifacts": {
                "mechanical/audit.json": sha256_bytes(
                    (staging / "mechanical" / "audit.json").read_bytes()
                ),
                "blind/backtranslation.json": backtranslation_hash,
                "comparison/comparison.json": comparison_hash,
            },
        }
        review_hash = _write_json(staging / "review.json", review_payload)
        review_markdown_path = staging / "review.md"
        _write_text(
            review_markdown_path,
            _review_markdown(
                theorem_id=candidate.theorem_id,
                audit=audit,
                backtranslation=backtranslation,
                comparison=comparison,
                verdict=verdict,
            ),
        )

        revision_path: Path | None = None
        if verdict == "needs_reformalization":
            issues = comparison.issues or [
                ComparisonIssue(
                    code="semantic_reformalization_required",
                    severity="error",
                    aspect="other",
                    explanation=comparison.rationale,
                    revision_instruction="Revise the Lean theorem and proof to match the source exactly.",
                )
            ]
            instructions = [
                issue.revision_instruction
                for issue in issues
                if issue.severity == "error" and issue.revision_instruction
            ]
            revision = RevisionRequest(
                theorem_id=candidate.theorem_id,
                review_attempt=attempt,
                review_json_sha256=review_hash,
                source_theorem_json_sha256=source.theorem_json_sha256,
                candidate_main_sha256=review_payload["input"]["agent2_main_sha256"],
                current_project_id=str(
                    candidate.handoff["agent2_run"]["project_id"]
                ),
                current_task_id=str(candidate.handoff["agent2_run"]["task_id"]),
                issues=issues,
                instructions=instructions
                or ["Revise the candidate to satisfy every recorded error."],
                constraints=[
                    "Do not use sorry, admit, sorryAx, or a new axiom, constant, "
                    "or opaque declaration.",
                    "Preserve protected source and pinned project files.",
                    "Match both the source statement and the printed proof method exactly.",
                    "Return a complete Lean proof that builds under Lean 4.28.0 and Mathlib v4.28.0.",
                ],
            )
            revision_path = staging / "revision_request.json"
            _write_json(revision_path, revision.model_dump(mode="json"))

        staging.replace(attempt_dir)
        latest = {
            "schema_version": "1.0",
            "theorem_id": candidate.theorem_id,
            "attempt": attempt,
            "path": f"{attempt_name}/review.json",
            "sha256": review_hash,
            "verdict": verdict,
        }
        latest_temp = root / f".latest-{uuid.uuid4().hex}.json"
        _write_json(latest_temp, latest)
        latest_temp.replace(root / "latest.json")
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    return ReviewResult(
        theorem_id=candidate.theorem_id,
        attempt=attempt,
        verdict=verdict,
        attempt_dir=attempt_dir,
        review_path=attempt_dir / "review.json",
        review_markdown_path=attempt_dir / "review.md",
        revision_request_path=(
            attempt_dir / "revision_request.json"
            if revision_path is not None
            else None
        ),
    )
