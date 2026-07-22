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

from .models import ChunkExtraction, TheoremCandidate
from .prompts import extraction_prompt


class ChunkExtractor(Protocol):
    def extract(self, pdf_path: Path, prompt: str) -> ChunkExtraction: ...


@dataclass(frozen=True)
class PdfChunk:
    path: Path
    page_start: int
    page_end: int


@dataclass(frozen=True)
class ExtractionResult:
    document_id: str
    run_id: str
    chunk_count: int
    theorem_ids: tuple[str, ...]


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


def shift_candidate_pages(candidate: TheoremCandidate, offset: int) -> TheoremCandidate:
    shifted = candidate.model_copy(deep=True)
    shifted.source_anchor.page_start += offset
    shifted.source_anchor.page_end += offset
    for item in shifted.notation:
        if item.source_page is not None:
            item.source_page += offset
    for item in shifted.prerequisites:
        if item.source_page is not None:
            item.source_page += offset
    for item in shifted.ambiguities:
        if item.source_page is not None:
            item.source_page += offset
    return shifted


def theorem_id(document_id: str, candidate: TheoremCandidate) -> str:
    identity = "|".join(
        [
            document_id,
            str(candidate.source_anchor.page_start),
            str(candidate.source_anchor.page_end),
            " ".join(candidate.normalized_statement.split()).casefold(),
        ]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"{document_id}-{digest}"


def _next_attempt_dir(extraction_root: Path) -> Path:
    attempts = []
    if extraction_root.exists():
        for path in extraction_root.glob("attempt-[0-9][0-9][0-9]"):
            attempts.append(int(path.name.removeprefix("attempt-")))
    number = max(attempts, default=0) + 1
    attempt_dir = extraction_root / f"attempt-{number:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    return attempt_dir


def _context_markdown(theorem_key: str, candidate: TheoremCandidate) -> str:
    notation = "\n".join(
        f"- `{item.symbol}` — {item.meaning} (page {item.source_page or 'unresolved'}, {item.source_status})"
        for item in candidate.notation
    ) or "- None extracted."
    prerequisites = "\n".join(
        f"- **{item.label}** ({item.kind}, {item.source_status}, confidence {item.confidence:.2f}): "
        f"{item.statement} — {item.relation}"
        + (f" [page {item.source_page}]" if item.source_page else "")
        for item in candidate.prerequisites
    ) or "- None extracted."
    ambiguities = "\n".join(
        f"- {item.text}: {item.reason}" + (f" [page {item.source_page}]" if item.source_page else "")
        for item in candidate.ambiguities
    ) or "- None reported."
    proof = candidate.proof_sketch or "No proof sketch was extracted."
    return f"""# Context for {theorem_key}

## Source Context

{candidate.surrounding_context or 'No additional surrounding prose was extracted.'}

## Variables

{chr(10).join(f'- {item}' for item in candidate.variables) or '- None extracted.'}

## Assumptions

{chr(10).join(f'- {item}' for item in candidate.assumptions) or '- None extracted.'}

## Notation

{notation}

## Prerequisites

{prerequisites}

## Proof Sketch

{proof}

## Ambiguities

{ambiguities}
"""


def materialize_candidate(
    *,
    output_root: Path,
    document_id: str,
    run_id: str,
    candidate: TheoremCandidate,
) -> str:
    theorem_key = theorem_id(document_id, candidate)
    extraction_root = output_root / theorem_key / "extraction"
    attempt_dir = _next_attempt_dir(extraction_root)
    payload = {
        "schema_version": "1.0",
        "theorem_id": theorem_key,
        "document_id": document_id,
        "run_id": run_id,
        **candidate.model_dump(mode="json"),
    }
    (attempt_dir / "theorem.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (attempt_dir / "context.md").write_text(
        _context_markdown(theorem_key, candidate), encoding="utf-8"
    )
    source = (
        f"[PDF pages {candidate.source_anchor.page_start}-{candidate.source_anchor.page_end}]\n"
        f"{candidate.original_text.strip()}\n"
    )
    (attempt_dir / "source.txt").write_text(source, encoding="utf-8")
    latest = {
        "theorem_id": theorem_key,
        "attempt": attempt_dir.name,
        "run_id": run_id,
    }
    (extraction_root / "latest.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return theorem_key


class ExtractionPipeline:
    def __init__(self, extractor: ChunkExtractor | None) -> None:
        self._extractor = extractor

    def plan_chunks(
        self,
        pdf_path: Path,
        *,
        pages_per_chunk: int,
        overlap_pages: int,
    ) -> list[tuple[int, int]]:
        with tempfile.TemporaryDirectory(prefix="pdf-ocr-plan-") as temp_dir:
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
    ) -> ExtractionResult:
        if self._extractor is None:
            raise RuntimeError("An extractor is required for a live run")
        if not pdf_path.is_file() or pdf_path.suffix.casefold() != ".pdf":
            raise ValueError(f"Expected an existing PDF file: {pdf_path}")
        if source_page_offset < 0:
            raise ValueError("source_page_offset must not be negative")

        safe_id = _safe_document_id(document_id)
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        candidates: dict[str, TheoremCandidate] = {}
        chunk_results: list[dict] = []

        with tempfile.TemporaryDirectory(prefix="pdf-ocr-agent-") as temp_dir:
            chunks = split_pdf(
                pdf_path,
                Path(temp_dir),
                pages_per_chunk=pages_per_chunk,
                overlap_pages=overlap_pages,
            )
            for chunk in chunks:
                prompt = extraction_prompt(
                    document_id=safe_id,
                    original_page_start=chunk.page_start + source_page_offset,
                    original_page_end=chunk.page_end + source_page_offset,
                )
                result = self._extractor.extract(chunk.path, prompt)
                chunk_results.append(
                    {
                        "original_page_start": chunk.page_start + source_page_offset,
                        "original_page_end": chunk.page_end + source_page_offset,
                        "response": result.model_dump(mode="json"),
                    }
                )
                page_count = chunk.page_end - chunk.page_start + 1
                for candidate in result.candidates:
                    if candidate.source_anchor.page_end > page_count:
                        raise ValueError(
                            f"Model returned page {candidate.source_anchor.page_end} for a {page_count}-page chunk"
                        )
                    shifted = shift_candidate_pages(
                        candidate, chunk.page_start - 1 + source_page_offset
                    )
                    key = theorem_id(safe_id, shifted)
                    existing = candidates.get(key)
                    if existing is None or shifted.confidence > existing.confidence:
                        candidates[key] = shifted

        output_root.mkdir(parents=True, exist_ok=True)
        theorem_keys = tuple(
            materialize_candidate(
                output_root=output_root,
                document_id=safe_id,
                run_id=run_id,
                candidate=candidate,
            )
            for _, candidate in sorted(candidates.items())
        )
        run_root = output_root / "_runs" / run_id
        run_root.mkdir(parents=True, exist_ok=False)
        for index, chunk_result in enumerate(chunk_results, start=1):
            (run_root / f"chunk-{index:04d}.json").write_text(
                json.dumps(chunk_result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        manifest = {
            "schema_version": "1.0",
            "run_id": run_id,
            "document_id": safe_id,
            "source_pdf": pdf_path.name,
            "source_page_offset": source_page_offset,
            "chunk_count": len(chunks),
            "theorem_ids": theorem_keys,
        }
        (run_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return ExtractionResult(safe_id, run_id, len(chunks), theorem_keys)
