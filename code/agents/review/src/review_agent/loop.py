from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from formalization_agent.candidate_validation import BuildRunner, run_local_lean_check

from .provider import ReviewProvider
from .reviewer import ReviewResult, review_candidate
from .revision import RevisionResult, RevisionTransport, revise_and_validate


class ReviewLoopError(RuntimeError):
    """Raised when the Agent 2/Agent 3 loop cannot continue safely."""


@dataclass(frozen=True)
class ReviewLoopResult:
    theorem_id: str
    verdict: str
    cycles: int
    final_review: ReviewResult
    revisions: tuple[RevisionResult, ...]


def run_review_loop(
    initial_handoff: str | Path,
    source_input: str | Path,
    *,
    provider: ReviewProvider,
    revision_transport: RevisionTransport,
    template_root: str | Path,
    max_revisions: int = 3,
    build_timeout_seconds: int = 1800,
    poll_seconds: float = 30.0,
    remote_timeout_seconds: float = 7200.0,
    build_runner: BuildRunner = run_local_lean_check,
) -> ReviewLoopResult:
    if max_revisions < 0:
        raise ValueError("max_revisions cannot be negative")
    current_handoff = Path(initial_handoff).resolve()
    revisions: list[RevisionResult] = []
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
            )
        if len(revisions) >= max_revisions:
            return ReviewLoopResult(
                theorem_id=reviewed.theorem_id,
                verdict="needs_reformalization",
                cycles=cycle,
                final_review=reviewed,
                revisions=tuple(revisions),
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
            )
        if revised.generation.handoff_path is None:
            raise ReviewLoopError("Agent 2 revision passed without a handoff")
        current_handoff = revised.generation.handoff_path
