from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from formalization_agent.candidate_validation import BuildRunner, run_local_lean_check

from .provider import ReviewProvider
from .reviewer import ReviewResult, review_candidate
from .revision import (
    RevisionResult,
    RevisionTransport,
    next_validation_repair_number,
    revise_and_validate,
    write_validation_repair_request,
)


class ReviewLoopError(RuntimeError):
    """Raised when the Agent 2/Agent 3 loop cannot continue safely."""


@dataclass(frozen=True)
class ReviewLoopResult:
    theorem_id: str
    verdict: str
    cycles: int
    final_review: ReviewResult
    revisions: tuple[RevisionResult, ...]
    stop_reason: str

    @property
    def semantic_revision_count(self) -> int:
        return sum(
            revision.request_kind == "semantic_revision"
            for revision in self.revisions
        )

    @property
    def validation_repair_count(self) -> int:
        return sum(
            revision.request_kind == "agent2_validation_repair"
            for revision in self.revisions
        )


def run_review_loop(
    initial_handoff: str | Path,
    source_input: str | Path,
    *,
    provider: ReviewProvider,
    revision_transport: RevisionTransport,
    template_root: str | Path,
    max_revisions: int = 3,
    max_validation_repairs_per_revision: int = 3,
    build_timeout_seconds: int = 1800,
    poll_seconds: float = 30.0,
    remote_timeout_seconds: float = 7200.0,
    build_runner: BuildRunner = run_local_lean_check,
) -> ReviewLoopResult:
    if max_revisions < 0:
        raise ValueError("max_revisions cannot be negative")
    if max_validation_repairs_per_revision < 0:
        raise ValueError("max_validation_repairs_per_revision cannot be negative")
    current_handoff = Path(initial_handoff).resolve()
    revisions: list[RevisionResult] = []
    semantic_revisions = 0
    cycle = 0
    while True:
        cycle += 1
        reviewed = review_candidate(
            current_handoff,
            source_input,
            provider=provider,
            template_root=template_root,
            build_timeout_seconds=build_timeout_seconds,
            build_runner=build_runner,
        )
        if reviewed.verdict != "needs_reformalization":
            return ReviewLoopResult(
                theorem_id=reviewed.theorem_id,
                verdict=reviewed.verdict,
                cycles=cycle,
                final_review=reviewed,
                revisions=tuple(revisions),
                stop_reason="terminal_verdict",
            )
        if semantic_revisions >= max_revisions:
            return ReviewLoopResult(
                theorem_id=reviewed.theorem_id,
                verdict="needs_reformalization",
                cycles=cycle,
                final_review=reviewed,
                revisions=tuple(revisions),
                stop_reason="semantic_revision_limit",
            )
        if reviewed.revision_request_path is None:
            raise ReviewLoopError(
                "needs_reformalization review has no revision request"
            )
        revision_root = reviewed.attempt_dir.parent.parent / "revision"
        revised = asyncio.run(
            revise_and_validate(
                current_handoff,
                reviewed.revision_request_path,
                transport=revision_transport,
                template_root=template_root,
                revision_root=revision_root,
                poll_seconds=poll_seconds,
                timeout_seconds=remote_timeout_seconds,
                build_timeout_seconds=build_timeout_seconds,
                build_runner=build_runner,
                request_kind="semantic_revision",
            )
        )
        semantic_revisions += 1
        revisions.append(revised)
        repair_number = next_validation_repair_number(
            reviewed.revision_request_path
        ) - 1
        repairs_started = 0
        failed_fingerprints: set[str] = set()
        while revised.generation.state == "validation_failed":
            if repairs_started >= max_validation_repairs_per_revision:
                return ReviewLoopResult(
                    theorem_id=reviewed.theorem_id,
                    verdict="needs_reformalization",
                    cycles=cycle,
                    final_review=reviewed,
                    revisions=tuple(revisions),
                    stop_reason="agent2_validation_repair_limit",
                )
            repair_number += 1
            repairs_started += 1
            repair_request, fingerprint = write_validation_repair_request(
                reviewed.revision_request_path,
                revised.generation,
                repair_number=repair_number,
                previous_fingerprints=failed_fingerprints,
            )
            failed_fingerprints.add(fingerprint)
            revised = asyncio.run(
                revise_and_validate(
                    current_handoff,
                    repair_request,
                    transport=revision_transport,
                    template_root=template_root,
                    revision_root=revision_root,
                    poll_seconds=poll_seconds,
                    timeout_seconds=remote_timeout_seconds,
                    build_timeout_seconds=build_timeout_seconds,
                    build_runner=build_runner,
                    request_kind="agent2_validation_repair",
                )
            )
            revisions.append(revised)
        if revised.generation.state != "ready_for_review":
            return ReviewLoopResult(
                theorem_id=reviewed.theorem_id,
                verdict="needs_reformalization",
                cycles=cycle,
                final_review=reviewed,
                revisions=tuple(revisions),
                stop_reason=f"agent2_{revised.generation.state}",
            )
        if revised.generation.handoff_path is None:
            raise ReviewLoopError("Agent 2 revision passed without a handoff")
        current_handoff = revised.generation.handoff_path
