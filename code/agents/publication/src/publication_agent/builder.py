from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .compiler import compile_book
from .latex import render_book
from .models import BuildResult, PublicationEntry
from .reader import load_publication_entries, sha256_bytes


class PublicationBuildError(RuntimeError):
    """Raised when an Agent 4 publication bundle cannot be completed."""


def default_template_root() -> Path:
    return Path(__file__).resolve().parents[2] / "templates" / "elegantbook"


def _copy_template_dependencies(template_root: Path, output_root: Path) -> dict[str, str]:
    required = {
        "elegantbook.cls": "elegantbook.cls",
        "License": "License",
        "figure/cover.jpg": "assets/cover.jpg",
        "figure/logo-blue.png": "assets/logo-blue.png",
    }
    hashes: dict[str, str] = {}
    for source_relative, target_relative in required.items():
        source = template_root / source_relative
        if not source.is_file():
            raise PublicationBuildError(f"ElegantBook dependency is missing: {source}")
        target = output_root / target_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        hashes[target_relative] = sha256_bytes(target.read_bytes())
    return hashes


def _copy_lean_sources(
    entries: Iterable[PublicationEntry],
    output_root: Path,
) -> list[dict[str, Any]]:
    manifest_entries: list[dict[str, Any]] = []
    for entry in entries:
        bundle_root = output_root / "lean" / entry.bundle_slug
        lean_files: list[dict[str, str]] = []
        for source in entry.lean_sources:
            target = bundle_root / source.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = source.source_path.read_bytes()
            if sha256_bytes(raw) != source.sha256:
                raise PublicationBuildError(
                    f"Lean source changed while bundling: {source.source_path}"
                )
            target.write_bytes(raw)
            lean_files.append(
                {
                    "path": target.relative_to(output_root).as_posix(),
                    "sha256": source.sha256,
                }
            )
        linked_main = output_root / entry.bundle_main_path
        if not linked_main.is_file():
            raise PublicationBuildError(
                f"generated Lean hyperlink has no target: {entry.bundle_main_path}"
            )
        manifest_entries.append(
            {
                "theorem_id": entry.theorem_id,
                "number": entry.number,
                "kind": entry.kind,
                "verdict": entry.verdict,
                "source": {
                    "theorem_json": str(entry.theorem_json_path),
                    "theorem_json_sha256": entry.theorem_json_sha256,
                    "pages": list(entry.source_pages),
                },
                "review": {
                    "review_json": str(entry.review_json_path),
                    "review_json_sha256": entry.review_json_sha256,
                },
                "formalization": {
                    "handoff": str(entry.handoff_path),
                    "main_path": entry.bundle_main_path,
                    "main_sha256": entry.main_sha256,
                    "declaration_name": entry.declaration_name,
                    "declaration_line": entry.declaration_line,
                    "lean_files": lean_files,
                },
            }
        )
    return manifest_entries


def _write_readme(output_root: Path, entry_count: int) -> None:
    text = f"""# Agent 4 LaTeX Bundle

This bundle contains {entry_count} accepted formal mathematics entries.

- `book.tex`: generated ElegantBook source.
- `book.pdf`: compiled output when `--compile` was used.
- `lean/`: hash-verified Lean sources linked from the PDF.
- `manifest.json`: provenance and SHA-256 bindings.
- `elegantbook.cls`, `License`, `assets/`: local ElegantBook dependencies.

Open the PDF and use each "Open the corresponding Lean proof file" link. Some PDF viewers
disable local launch actions; the same relative path is printed below the link.
"""
    (output_root / "README.md").write_text(text, encoding="utf-8")


def build_publication(
    chapter_summary: str | Path,
    source_roots: Iterable[str | Path],
    output_dir: str | Path,
    *,
    title: str = "Multi-Agent Formal Mathematics Textbook",
    subtitle: str = "Natural Language, Formal Specifications, and Lean Verification",
    author: str = "Formal Mathematics Agents",
    chapter_title: str = "Formal Mathematics",
    template_root: str | Path | None = None,
    compile_pdf: bool = False,
    compile_timeout_seconds: int = 1800,
) -> BuildResult:
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise PublicationBuildError(f"output directory already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries, summary_hash = load_publication_entries(chapter_summary, source_roots)
    template = (
        Path(template_root).resolve()
        if template_root is not None
        else default_template_root().resolve()
    )

    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent)
    )
    pdf_path: Path | None = None
    try:
        template_hashes = _copy_template_dependencies(template, staging)
        manifest_entries = _copy_lean_sources(entries, staging)
        tex = render_book(
            entries,
            title=title,
            subtitle=subtitle,
            author=author,
            chapter_title=chapter_title,
        )
        tex_path = staging / "book.tex"
        tex_path.write_text(tex, encoding="utf-8", newline="\n")
        _write_readme(staging, len(entries))
        manifest = {
            "schema_version": "1.0",
            "agent": "agent4-publication",
            "chapter_summary": str(Path(chapter_summary).resolve()),
            "chapter_summary_sha256": summary_hash,
            "entry_count": len(entries),
            "template": {
                "source_root": str(template),
                "dependencies": template_hashes,
            },
            "generated": {
                "tex": "book.tex",
                "tex_sha256": sha256_bytes(tex_path.read_bytes()),
                "pdf": "book.pdf" if compile_pdf else None,
            },
            "entries": manifest_entries,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if compile_pdf:
            pdf_path = compile_book(
                tex_path,
                timeout_seconds=compile_timeout_seconds,
            )
            manifest["generated"]["pdf_sha256"] = sha256_bytes(pdf_path.read_bytes())
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return BuildResult(
        output_dir=destination,
        tex_path=destination / "book.tex",
        manifest_path=destination / "manifest.json",
        pdf_path=(destination / "book.pdf") if pdf_path is not None else None,
        entry_count=len(entries),
    )
