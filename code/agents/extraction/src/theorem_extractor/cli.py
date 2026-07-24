from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .client import DEFAULT_ENDPOINT, GPT55Client, GPT55ExtractionError
from .pipeline import TheoremExtractionPipeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="theorem-extractor",
        description=(
            "Extract complete theorem statements and source-grounded proofs from "
            "page-anchored Markdown using the ShanghaiTech GPT-5.5 endpoint."
        ),
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="+",
        help="One or more OCR chunk Markdown files or OCR run directories",
    )
    parser.add_argument("--output-root", type=Path, default=Path("outputs/pipeline"))
    parser.add_argument("--document-id")
    parser.add_argument("--endpoint", default=os.getenv("GPT55_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--model", default=os.getenv("GPT55_MODEL", "GPT-5.5"))
    parser.add_argument(
        "--deployment",
        default=os.getenv("GPT55_DEPLOYMENT", "east-US-2-gpt-5.5"),
        help="Deployment label recorded in manifests; routing is performed by the endpoint.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "low", "medium", "high", "xhigh"],
        default=os.getenv("GPT55_REASONING_EFFORT", "medium"),
    )
    parser.add_argument("--max-completion-tokens", type=int, default=32768)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=600)
    return parser


def _markdown_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved.is_file():
            files.append(resolved)
            continue
        if not resolved.is_dir():
            raise ValueError(f"Input does not exist: {resolved}")
        chunks = resolved / "chunks"
        search_root = chunks if chunks.is_dir() else resolved
        found = sorted(search_root.glob("*.md"))
        if not found:
            raise ValueError(f"No Markdown chunks found under {search_root}")
        files.extend(found)
    return list(dict.fromkeys(files))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    api_key = os.getenv("GPT55_API_KEY")
    if not api_key:
        raise SystemExit(
            "GPT55_API_KEY is not set; inject it through the process environment"
        )

    try:
        files = _markdown_files(args.input)
        with GPT55Client(
            api_key=api_key,
            endpoint=args.endpoint,
            model=args.model,
            deployment=args.deployment,
            reasoning_effort=args.reasoning_effort,
            max_completion_tokens=args.max_completion_tokens,
            max_attempts=args.max_attempts,
            timeout_seconds=args.timeout_seconds,
        ) as extractor:
            result = TheoremExtractionPipeline(extractor).run(
                files,
                args.output_root,
                document_id=args.document_id,
            )
    except (ValueError, GPT55ExtractionError) as exc:
        print(str(exc).replace(api_key, "[REDACTED]"), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "document_id": result.document_id,
                "run_id": result.run_id,
                "run_dir": str(result.run_dir),
                "theorem_count": len(result.theorem_ids),
                "rejected_candidate_count": result.rejected_candidate_count,
                "proof_status_counts": result.status_counts,
                "theorem_ids": result.theorem_ids,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0
