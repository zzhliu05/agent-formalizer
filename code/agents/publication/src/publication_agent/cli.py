from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from formalization_agent.reader import PackageReadError
from review_agent.reader import ReviewReadError

from .builder import PublicationBuildError, build_publication, default_template_root
from .compiler import PublicationCompileError
from .reader import PublicationReadError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="publication-agent",
        description=(
            "Build an ElegantBook LaTeX bundle from Agent 3-accepted theorem records."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser(
        "build",
        help="Validate an accepted chapter inventory and generate one LaTeX bundle.",
    )
    build.add_argument("chapter_summary", type=Path)
    build.add_argument("output_dir", type=Path)
    build.add_argument(
        "--source-root",
        type=Path,
        action="append",
        required=True,
        help="Agent 1 theorem-package root; repeat for multiple extraction roots.",
    )
    build.add_argument("--template-root", type=Path, default=default_template_root())
    build.add_argument("--title", default="Multi-Agent Formal Mathematics Textbook")
    build.add_argument(
        "--subtitle",
        default="Natural Language, Formal Specifications, and Lean Verification",
    )
    build.add_argument("--author", default="Formal Mathematics Agents")
    build.add_argument("--chapter-title", default="Formal Mathematics")
    build.add_argument("--compile", action="store_true")
    build.add_argument("--compile-timeout-seconds", type=int, default=1800)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_publication(
                args.chapter_summary,
                args.source_root,
                args.output_dir,
                title=args.title,
                subtitle=args.subtitle,
                author=args.author,
                chapter_title=args.chapter_title,
                template_root=args.template_root,
                compile_pdf=args.compile,
                compile_timeout_seconds=args.compile_timeout_seconds,
            )
            print(
                json.dumps(
                    {
                        "output_dir": str(result.output_dir),
                        "tex_path": str(result.tex_path),
                        "manifest_path": str(result.manifest_path),
                        "pdf_path": str(result.pdf_path) if result.pdf_path else None,
                        "entry_count": result.entry_count,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    except (
        PackageReadError,
        PublicationBuildError,
        PublicationCompileError,
        PublicationReadError,
        ReviewReadError,
        ValueError,
    ) as exc:
        print(f"publication-agent: error: {exc}", file=sys.stderr)
        return 2
    return 1
