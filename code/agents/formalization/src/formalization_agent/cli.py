from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .preparer import (
    PreparationError,
    PreparationPolicy,
    prepare_formalization,
)
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
        if args.command == "inspect":
            payload = _inspect(args.input)
        else:
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
    except (PackageReadError, PreparationError) as exc:
        print(f"formalization-agent: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
