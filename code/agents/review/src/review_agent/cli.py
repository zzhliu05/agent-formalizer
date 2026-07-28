from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from formalization_agent.generator import GenerationError
from formalization_agent.preparation_reader import PreparationReadError
from formalization_agent.reader import PackageReadError

from .chapter import ACCEPTED_VERDICTS, ChapterReviewError, run_chapter_review
from .loop import ReviewLoopError, run_review_loop
from .provider import DEFAULT_ENDPOINT, GPT55ReviewClient, ReviewProviderError
from .reader import ReviewReadError
from .reviewer import ReviewError, review_candidate
from .revision import (
    RevisionError,
    SDKRevisionTransport,
    next_validation_repair_number,
    revise_and_validate,
    write_validation_repair_request,
)


def _default_formalization_root() -> Path:
    return Path(__file__).resolve().parents[3] / "formalization"


def _provider_from_env(args: argparse.Namespace) -> GPT55ReviewClient:
    key = os.environ.get("REVIEW_MODEL_API_KEY")
    if not key:
        raise ReviewError("REVIEW_MODEL_API_KEY is not set")
    return GPT55ReviewClient(
        api_key=key,
        endpoint=args.endpoint,
        model=args.model,
        deployment=args.deployment,
        reasoning_effort=args.reasoning_effort,
    )


def _add_model_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("REVIEW_MODEL_ENDPOINT", DEFAULT_ENDPOINT),
    )
    parser.add_argument("--model", default="GPT-5.5")
    parser.add_argument("--deployment", default="east-US-2-gpt-5.5")
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high"),
        default="medium",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review-agent",
        description="Independently audit and semantically review Agent 2 Lean candidates.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    review = subparsers.add_parser(
        "review", help="Run one isolated Agent 3 review attempt."
    )
    review.add_argument("handoff", type=Path)
    review.add_argument("source", type=Path)
    review.add_argument(
        "--template-root", type=Path, default=_default_formalization_root()
    )
    review.add_argument("--review-root", type=Path, default=None)
    review.add_argument("--build-timeout-seconds", type=int, default=1800)
    _add_model_options(review)

    loop = subparsers.add_parser(
        "loop", help="Run Agent 2 -> Agent 3 revision cycles to a terminal verdict."
    )
    loop.add_argument("handoff", type=Path)
    loop.add_argument("source", type=Path)
    loop.add_argument(
        "--template-root", type=Path, default=_default_formalization_root()
    )
    loop.add_argument("--max-revisions", type=int, default=3)
    loop.add_argument(
        "--max-agent2-repairs-per-revision",
        type=int,
        default=3,
        help=(
            "Automatic Aristotle repairs allowed after each Agent 2 "
            "validation_failed checkpoint."
        ),
    )
    loop.add_argument("--build-timeout-seconds", type=int, default=1800)
    loop.add_argument("--poll-seconds", type=float, default=30.0)
    loop.add_argument("--remote-timeout-seconds", type=float, default=7200.0)
    _add_model_options(loop)

    continuation = subparsers.add_parser(
        "continue",
        help="Resume one Agent 3 revision and run the next Agent 3 review.",
    )
    continuation.add_argument("handoff", type=Path)
    continuation.add_argument("source", type=Path)
    continuation.add_argument("revision_request", type=Path)
    continuation.add_argument(
        "--template-root", type=Path, default=_default_formalization_root()
    )
    continuation.add_argument(
        "--task-id",
        help="Existing Aristotle follow-up task ID to resume without resubmission.",
    )
    continuation.add_argument("--build-timeout-seconds", type=int, default=1800)
    continuation.add_argument("--poll-seconds", type=float, default=30.0)
    continuation.add_argument("--remote-timeout-seconds", type=float, default=7200.0)
    continuation.add_argument(
        "--max-agent2-repairs",
        type=int,
        default=3,
        help=(
            "Automatic Aristotle repairs allowed if the resumed result fails "
            "Agent 2 validation."
        ),
    )
    _add_model_options(continuation)

    chapter = subparsers.add_parser(
        "chapter",
        help="Review every Agent 2 theorem in a chapter inventory sequentially.",
    )
    chapter.add_argument("chapter_root", type=Path)
    chapter.add_argument("source_root", type=Path)
    chapter.add_argument(
        "--template-root", type=Path, default=_default_formalization_root()
    )
    chapter.add_argument("--max-revisions-per-theorem", type=int, default=8)
    chapter.add_argument(
        "--max-agent2-repairs-per-revision",
        type=int,
        default=3,
        help=(
            "Automatic Aristotle repairs allowed after each Agent 2 "
            "validation_failed checkpoint."
        ),
    )
    chapter.add_argument("--build-timeout-seconds", type=int, default=1800)
    chapter.add_argument("--poll-seconds", type=float, default=30.0)
    chapter.add_argument("--remote-timeout-seconds", type=float, default=7200.0)
    _add_model_options(chapter)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with _provider_from_env(args) as provider:
            if args.command == "review":
                result = review_candidate(
                    args.handoff,
                    args.source,
                    provider=provider,
                    template_root=args.template_root,
                    review_root=args.review_root,
                    build_timeout_seconds=args.build_timeout_seconds,
                )
                payload = {
                    "theorem_id": result.theorem_id,
                    "attempt": result.attempt,
                    "verdict": result.verdict,
                    "review_path": str(result.review_path),
                    "review_markdown_path": str(result.review_markdown_path),
                    "revision_request_path": (
                        str(result.revision_request_path)
                        if result.revision_request_path
                        else None
                    ),
                }
            elif args.command == "loop":
                result = run_review_loop(
                    args.handoff,
                    args.source,
                    provider=provider,
                    revision_transport=SDKRevisionTransport(),
                    template_root=args.template_root,
                    max_revisions=args.max_revisions,
                    max_validation_repairs_per_revision=(
                        args.max_agent2_repairs_per_revision
                    ),
                    build_timeout_seconds=args.build_timeout_seconds,
                    poll_seconds=args.poll_seconds,
                    remote_timeout_seconds=args.remote_timeout_seconds,
                )
                payload = {
                    "theorem_id": result.theorem_id,
                    "verdict": result.verdict,
                    "cycles": result.cycles,
                    "revision_count": len(result.revisions),
                    "semantic_revision_count": result.semantic_revision_count,
                    "agent2_validation_repair_count": (
                        result.validation_repair_count
                    ),
                    "stop_reason": result.stop_reason,
                    "final_review_path": str(result.final_review.review_path),
                }
            elif args.command == "continue":
                if args.max_agent2_repairs < 0:
                    raise ReviewError("--max-agent2-repairs cannot be negative")
                revision_root = (
                    args.revision_request.resolve().parent.parent.parent
                    / "revision"
                )
                revised = asyncio.run(
                    revise_and_validate(
                        args.handoff,
                        args.revision_request,
                        transport=SDKRevisionTransport(
                            resume_task_id=args.task_id
                        ),
                        template_root=args.template_root,
                        revision_root=revision_root,
                        poll_seconds=args.poll_seconds,
                        timeout_seconds=args.remote_timeout_seconds,
                        build_timeout_seconds=args.build_timeout_seconds,
                        request_kind=(
                            "agent2_validation_repair"
                            if args.revision_request.name.startswith(
                                "validation-repair-"
                            )
                            else "semantic_revision"
                        ),
                    )
                )
                repair_count = 0
                repair_number = next_validation_repair_number(
                    args.revision_request
                )
                failed_fingerprints: set[str] = set()
                while (
                    revised.generation.state == "validation_failed"
                    and repair_count < args.max_agent2_repairs
                ):
                    repair_request, fingerprint = write_validation_repair_request(
                        args.revision_request,
                        revised.generation,
                        repair_number=repair_number,
                        previous_fingerprints=failed_fingerprints,
                    )
                    failed_fingerprints.add(fingerprint)
                    revised = asyncio.run(
                        revise_and_validate(
                            args.handoff,
                            repair_request,
                            transport=SDKRevisionTransport(),
                            template_root=args.template_root,
                            revision_root=revision_root,
                            poll_seconds=args.poll_seconds,
                            timeout_seconds=args.remote_timeout_seconds,
                            build_timeout_seconds=args.build_timeout_seconds,
                            request_kind="agent2_validation_repair",
                        )
                    )
                    repair_count += 1
                    repair_number += 1
                if (
                    revised.generation.state == "ready_for_review"
                    and revised.generation.handoff_path is not None
                ):
                    reviewed = review_candidate(
                        revised.generation.handoff_path,
                        args.source,
                        provider=provider,
                        template_root=args.template_root,
                        build_timeout_seconds=args.build_timeout_seconds,
                    )
                    verdict = reviewed.verdict
                    review_path = str(reviewed.review_path)
                else:
                    verdict = "needs_reformalization"
                    review_path = None
                payload = {
                    "theorem_id": revised.generation.theorem_id,
                    "verdict": verdict,
                    "revision_attempt_path": str(revised.attempt_dir),
                    "agent2_state": revised.generation.state,
                    "agent2_handoff_path": (
                        str(revised.generation.handoff_path)
                        if revised.generation.handoff_path
                        else None
                    ),
                    "agent2_validation_repair_count": repair_count,
                    "stop_reason": (
                        "next_review_completed"
                        if review_path is not None
                        else (
                            "agent2_validation_repair_limit"
                            if revised.generation.state == "validation_failed"
                            else f"agent2_{revised.generation.state}"
                        )
                    ),
                    "next_review_path": review_path,
                }
            else:
                chapter_result = run_chapter_review(
                    args.chapter_root,
                    args.source_root,
                    provider=provider,
                    revision_transport=SDKRevisionTransport(),
                    template_root=args.template_root,
                    max_revisions_per_theorem=args.max_revisions_per_theorem,
                    max_validation_repairs_per_revision=(
                        args.max_agent2_repairs_per_revision
                    ),
                    build_timeout_seconds=args.build_timeout_seconds,
                    poll_seconds=args.poll_seconds,
                    remote_timeout_seconds=args.remote_timeout_seconds,
                )
                payload = {
                    "complete": chapter_result.complete,
                    "theorem_count": len(chapter_result.items),
                    "accepted_count": sum(
                        item.verdict in ACCEPTED_VERDICTS
                        for item in chapter_result.items
                    ),
                    "declaration_only_count": sum(
                        item.verdict == "accepted_declaration"
                        for item in chapter_result.items
                    ),
                    "summary_path": str(chapter_result.summary_path),
                }
    except (
        ReviewError,
        ReviewReadError,
        ReviewProviderError,
        RevisionError,
        ReviewLoopError,
        ChapterReviewError,
        PackageReadError,
        PreparationReadError,
        GenerationError,
    ) as exc:
        print(f"review-agent: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command == "chapter":
        return 0 if payload["complete"] else 3
    return 0 if payload["verdict"] in ACCEPTED_VERDICTS else 3
