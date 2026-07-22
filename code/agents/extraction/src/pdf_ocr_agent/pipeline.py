from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader, PdfWriter

from .models import ChunkMarkdown
from .prompts import markdown_prompt


class ChunkExtractor(Protocol):
    model_name: str

    def extract(self, pdf_path: Path, prompt: str) -> ChunkMarkdown: ...


@dataclass(frozen=True)
class PdfChunk:
    path: Path
    page_start: int
    page_end: int


@dataclass(frozen=True)
class MarkdownRunResult:
    document_id: str
    run_id: str
    run_dir: Path
    chunk_files: tuple[Path, ...]


def _safe_document_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.").lower()
    if not cleaned:
        raise ValueError("document_id must contain at least one letter or number")
    return cleaned


def split_pdf(
    pdf_path: Path,
    target_dir: Path,
    *,
    pages_per_chunk: int,
    overlap_pages: int,
) -> list[PdfChunk]:
    if pages_per_chunk < 1:
        raise ValueError("pages_per_chunk must be positive")
    if overlap_pages < 0 or overlap_pages >= pages_per_chunk:
        raise ValueError("overlap_pages must satisfy 0 <= overlap < pages_per_chunk")

    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    if total_pages == 0:
        raise ValueError("PDF contains no pages")

    chunks: list[PdfChunk] = []
    step = pages_per_chunk - overlap_pages
    for start_index in range(0, total_pages, step):
        end_index = min(start_index + pages_per_chunk, total_pages)
        writer = PdfWriter()
        for page_index in range(start_index, end_index):
            writer.add_page(reader.pages[page_index])
        chunk_path = target_dir / f"pages-{start_index + 1:05d}-{end_index:05d}.pdf"
        with chunk_path.open("wb") as handle:
            writer.write(handle)
        chunks.append(PdfChunk(chunk_path, start_index + 1, end_index))
        if end_index == total_pages:
            break
    return chunks


def _validate_pages(result: ChunkMarkdown, page_count: int) -> None:
    actual = [page.page_number for page in result.pages]
    expected = list(range(1, page_count + 1))
    if actual != expected:
        raise ValueError(f"Gemini returned page sequence {actual}; expected {expected}")


def _chunk_markdown(
    *,
    document_id: str,
    run_id: str,
    chunk_index: int,
    original_page_start: int,
    original_page_end: int,
    source_pdf: str,
    model: str,
    result: ChunkMarkdown,
) -> str:
    sections = []
    for page in result.pages:
        original_page = original_page_start + page.page_number - 1
        warnings = "\n".join(f"> OCR warning: {warning}" for warning in page.warnings)
        section = (
            f"<!-- pdf-page: {original_page} -->\n\n"
            f"## PDF page {original_page}\n\n"
            f"{page.markdown.strip()}\n"
        )
        if warnings:
            section += f"\n{warnings}\n"
        section += f"\n<!-- ocr-confidence: {page.confidence:.3f} -->"
        sections.append(section)

    return f"""---
type: ocr-chunk
schema_version: "1.0"
document_id: {document_id}
run_id: {run_id}
chunk_index: {chunk_index}
pdf_page_start: {original_page_start}
pdf_page_end: {original_page_end}
source_pdf: {json.dumps(source_pdf, ensure_ascii=False)}
model: {model}
---

# OCR chunk {chunk_index:04d}: PDF pages {original_page_start}-{original_page_end}

{chr(10).join(sections)}
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class MarkdownPipeline:
    def __init__(self, extractor: ChunkExtractor | None) -> None:
        self._extractor = extractor

    def plan_chunks(
        self,
        pdf_path: Path,
        *,
        pages_per_chunk: int,
        overlap_pages: int,
    ) -> list[tuple[int, int]]:
        with tempfile.TemporaryDirectory(prefix="pdf-markdown-plan-") as temp_dir:
            chunks = split_pdf(
                pdf_path,
                Path(temp_dir),
                pages_per_chunk=pages_per_chunk,
                overlap_pages=overlap_pages,
            )
            return [(chunk.page_start, chunk.page_end) for chunk in chunks]

    def run(
        self,
        pdf_path: Path,
        output_root: Path,
        *,
        document_id: str,
        pages_per_chunk: int = 12,
        overlap_pages: int = 2,
        source_page_offset: int = 0,
    ) -> MarkdownRunResult:
        if self._extractor is None:
            raise RuntimeError("An extractor is required for a live run")
        if not pdf_path.is_file() or pdf_path.suffix.casefold() != ".pdf":
            raise ValueError(f"Expected an existing PDF file: {pdf_path}")
        if source_page_offset < 0:
            raise ValueError("source_page_offset must not be negative")

        safe_id = _safe_document_id(document_id)
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = output_root / safe_id / run_id
        chunks_dir = run_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=False)
        manifest_chunks = []
        chunk_files = []

        with tempfile.TemporaryDirectory(prefix="pdf-markdown-agent-") as temp_dir:
            chunks = split_pdf(
                pdf_path,
                Path(temp_dir),
                pages_per_chunk=pages_per_chunk,
                overlap_pages=overlap_pages,
            )
            for index, chunk in enumerate(chunks, start=1):
                original_start = chunk.page_start + source_page_offset
                original_end = chunk.page_end + source_page_offset
                result = self._extractor.extract(
                    chunk.path,
                    markdown_prompt(
                        document_id=safe_id,
                        original_page_start=original_start,
                        original_page_end=original_end,
                    ),
                )
                _validate_pages(result, chunk.page_end - chunk.page_start + 1)
                filename = f"chunk-{index:04d}-pages-{original_start:05d}-{original_end:05d}.md"
                chunk_path = chunks_dir / filename
                chunk_path.write_text(
                    _chunk_markdown(
                        document_id=safe_id,
                        run_id=run_id,
                        chunk_index=index,
                        original_page_start=original_start,
                        original_page_end=original_end,
                        source_pdf=pdf_path.name,
                        model=self._extractor.model_name,
                        result=result,
                    ),
                    encoding="utf-8",
                )
                chunk_files.append(chunk_path)
                manifest_chunks.append(
                    {
                        "chunk_index": index,
                        "pdf_page_start": original_start,
                        "pdf_page_end": original_end,
                        "path": f"chunks/{filename}",
                    }
                )

        manifest = {
            "schema_version": "1.0",
            "document_id": safe_id,
            "run_id": run_id,
            "source_pdf": pdf_path.name,
            "source_pdf_sha256": _sha256(pdf_path),
            "source_page_offset": source_page_offset,
            "model": self._extractor.model_name,
            "pages_per_chunk": pages_per_chunk,
            "overlap_pages": overlap_pages,
            "chunks": manifest_chunks,
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return MarkdownRunResult(safe_id, run_id, run_dir, tuple(chunk_files))
