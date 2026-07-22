from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .gemini import GeminiMarkdownExtractor, GeminiTranscriptionError
from .pipeline import MarkdownPipeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-ocr-agent",
        description="Convert a PDF into page-anchored Markdown chunks without theorem extraction.",
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/ocr"))
    parser.add_argument("--document-id")
    parser.add_argument(
        "--model", default=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--pages-per-chunk", type=int, default=12)
    parser.add_argument("--overlap-pages", type=int, default=2)
    parser.add_argument(
        "--source-page-offset",
        type=int,
        default=0,
        help="Add this value to page anchors when processing an extracted PDF subset.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    pdf_path = args.pdf.resolve()
    document_id = args.document_id or pdf_path.stem

    if args.dry_run:
        chunks = MarkdownPipeline(None).plan_chunks(
            pdf_path,
            pages_per_chunk=args.pages_per_chunk,
            overlap_pages=args.overlap_pages,
        )
        print(json.dumps({"pdf": str(pdf_path), "chunks": chunks}, ensure_ascii=False, indent=2))
        return 0

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set; inject a rotated key through the process environment")

    pipeline = MarkdownPipeline(
        GeminiMarkdownExtractor(
            api_key=api_key,
            model=args.model,
            max_attempts=args.max_attempts,
        )
    )
    try:
        result = pipeline.run(
            pdf_path,
            args.output_root.resolve(),
            document_id=document_id,
            pages_per_chunk=args.pages_per_chunk,
            overlap_pages=args.overlap_pages,
            source_page_offset=args.source_page_offset,
        )
    except GeminiTranscriptionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "document_id": result.document_id,
                "run_id": result.run_id,
                "run_dir": str(result.run_dir),
                "chunk_files": [str(path) for path in result.chunk_files],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0
