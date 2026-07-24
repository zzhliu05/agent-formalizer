from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .generator import GenerationError, generate_proof, resume_generation
from .preparer import (
    PreparationError,
    PreparationPolicy,
    prepare_formalization,
)
from .preparation_reader import PreparationReadError
from .reader import PackageReadError, load_theorem_package


def _find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def _default_template_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formalization-agent",
        description="Validate Agent 1 theorem packages and prepare Aristotle proof tasks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Validate a theorem package and print safe metadata."
    )
    inspect_parser.add_argument(
        "input", type=Path, help="theorem.json, latest.json, attempt dir, or theorem dir"
    )

    prepare_parser = subparsers.add_parser(
        "prepare", help="Create an immutable Aristotle project and prompt bundle."
    )
    prepare_parser.add_argument(
        "input", type=Path, help="theorem.json, latest.json, attempt dir, or theorem dir"
    )
    prepare_parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Pipeline output root (default: <repository>/outputs/pipeline).",
    )
    prepare_parser.add_argument(
        "--template-root",
        type=Path,
        default=_default_template_root(),
        help="Pinned Agent 2 Lean project containing lean-toolchain and manifest.",
    )
    prepare_parser.add_argument(
        "--allow-uncertain",
        action="store_true",
        help="Explicitly allow an Agent 1 record with extraction uncertainties.",
    )

    generate_parser = subparsers.add_parser(
        "generate",
        help="Submit a prepared task non-interactively and validate the Lean result.",
    )
    generate_parser.add_argument(
        "input",
        type=Path,
        help="preparation request.json, latest.json, attempt dir, or theorem dir",
    )
    generate_parser.add_argument(
        "--template-root",
        type=Path,
        default=_default_template_root(),
        help="Pinned Agent 2 Lean project used for local kernel validation.",
    )
    generate_parser.add_argument(
        "--generation-root",
        type=Path,
        default=None,
        help="Override the sibling formalization/generation output directory.",
    )
    generate_parser.add_argument(
        "--poll-seconds",
        type=float,
        default=30.0,
        help="Non-interactive Aristotle status polling interval.",
    )
    generate_parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=7200.0,
        help="Maximum time to wait before leaving the remote task resumable.",
    )
    generate_parser.add_argument(
        "--build-timeout-seconds",
        type=int,
        default=1800,
        help="Maximum time for local Lean kernel validation.",
    )

    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume non-interactive polling for an existing Aristotle generation.",
    )
    resume_parser.add_argument(
        "input",
        type=Path,
        help="run.json, generation attempt directory, or generation/latest.json",
    )
    resume_parser.add_argument(
        "--template-root",
        type=Path,
        default=_default_template_root(),
        help="Pinned Agent 2 Lean project used for local kernel validation.",
    )
    resume_parser.add_argument("--poll-seconds", type=float, default=30.0)
    resume_parser.add_argument("--timeout-seconds", type=float, default=7200.0)
    resume_parser.add_argument("--build-timeout-seconds", type=int, default=1800)
    return parser


def _inspect(input_path: Path) -> dict[str, object]:
    loaded = load_theorem_package(input_path)
    result = loaded.package.result
    return {
        "schema_version": loaded.package.schema_version,
        "theorem_id": loaded.package.theorem_id,
        "document_id": loaded.package.document_id,
        "kind": result.kind,
        "proof_status": result.proof_status,
        "source_pages": result.source_pages,
        "context_item_count": len(result.context_items),
        "proof_step_count": len(result.proof_steps),
        "uncertainty_count": len(result.uncertainties),
        "record_complete_in_chunk": result.record_complete_in_chunk,
        "theorem_json_sha256": loaded.theorem_json_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        exit_code = 0
        if args.command == "inspect":
            payload = _inspect(args.input)
        elif args.command == "prepare":
            output_root = args.output_root
            if output_root is None:
                output_root = _find_repo_root(Path.cwd()) / "outputs" / "pipeline"
            prepared = prepare_formalization(
                args.input,
                output_root=output_root,
                template_root=args.template_root,
                policy=PreparationPolicy(allow_uncertain=args.allow_uncertain),
            )
            payload = {
                "theorem_id": prepared.theorem_id,
                "attempt": prepared.attempt,
                "attempt_dir": str(prepared.attempt_dir),
                "project_dir": str(prepared.project_dir),
                "prompt_path": str(prepared.prompt_path),
                "request_path": str(prepared.request_path),
                "request_sha256": prepared.request_sha256,
                "submitted": False,
            }
        elif args.command == "generate":
            generated = asyncio.run(
                generate_proof(
                    args.input,
                    template_root=args.template_root,
                    generation_root=args.generation_root,
                    poll_seconds=args.poll_seconds,
                    timeout_seconds=args.timeout_seconds,
                    build_timeout_seconds=args.build_timeout_seconds,
                )
            )
            payload = {
                "theorem_id": generated.theorem_id,
                "state": generated.state,
                "run_dir": str(generated.run_dir),
                "project_id": generated.project_id,
                "task_id": generated.task_id,
                "handoff_path": (
                    str(generated.handoff_path) if generated.handoff_path else None
                ),
                "questioning_loop_owner": "agent3",
            }
            if generated.state != "ready_for_review":
                exit_code = 3
        else:
            generated = asyncio.run(
                resume_generation(
                    args.input,
                    template_root=args.template_root,
                    poll_seconds=args.poll_seconds,
                    timeout_seconds=args.timeout_seconds,
                    build_timeout_seconds=args.build_timeout_seconds,
                )
            )
            payload = {
                "theorem_id": generated.theorem_id,
                "state": generated.state,
                "run_dir": str(generated.run_dir),
                "project_id": generated.project_id,
                "task_id": generated.task_id,
                "handoff_path": (
                    str(generated.handoff_path) if generated.handoff_path else None
                ),
                "questioning_loop_owner": "agent3",
            }
            if generated.state != "ready_for_review":
                exit_code = 3
    except (
        PackageReadError,
        PreparationError,
        PreparationReadError,
        GenerationError,
    ) as exc:
        print(f"formalization-agent: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code
