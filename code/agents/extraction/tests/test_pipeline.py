from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfWriter

from pdf_ocr_agent.models import ChunkExtraction, SourceAnchor, TheoremCandidate
from pdf_ocr_agent.pipeline import ExtractionPipeline, shift_candidate_pages, theorem_id


def _pdf(path: Path, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _candidate(page: int = 1) -> TheoremCandidate:
    return TheoremCandidate(
        local_id="t1",
        kind="theorem",
        title="Sample theorem",
        original_text="For every natural number n, n = n.",
        normalized_statement="For every natural number n, n = n.",
        variables=["n is a natural number"],
        assumptions=[],
        conclusion="n = n",
        source_anchor=SourceAnchor(page_start=page, page_end=page, section="1"),
        confidence=0.99,
    )


class FakeExtractor:
    def extract(self, pdf_path: Path, prompt: str) -> ChunkExtraction:
        return ChunkExtraction(chunk_summary="test", candidates=[_candidate()])


def test_chunk_plan_uses_overlap(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "book.pdf", 7)
    chunks = ExtractionPipeline(None).plan_chunks(pdf, pages_per_chunk=3, overlap_pages=1)
    assert chunks == [(1, 3), (3, 5), (5, 7)]


def test_page_shift_and_theorem_id_are_stable() -> None:
    candidate = shift_candidate_pages(_candidate(), 10)
    assert candidate.source_anchor.page_start == 11
    assert theorem_id("book", candidate) == theorem_id("book", candidate)


def test_pipeline_writes_agent_contract(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "book.pdf", 1)
    output = tmp_path / "outputs"
    result = ExtractionPipeline(FakeExtractor()).run(
        pdf,
        output,
        document_id="My Book",
        pages_per_chunk=1,
        overlap_pages=0,
        source_page_offset=14,
    )
    assert result.document_id == "my-book"
    assert len(result.theorem_ids) == 1
    extraction = output / result.theorem_ids[0] / "extraction"
    latest = json.loads((extraction / "latest.json").read_text(encoding="utf-8"))
    attempt = extraction / latest["attempt"]
    theorem = json.loads((attempt / "theorem.json").read_text(encoding="utf-8"))
    assert theorem["theorem_id"] == result.theorem_ids[0]
    assert theorem["source_anchor"]["page_start"] == 15
    assert (attempt / "context.md").is_file()
    assert (attempt / "source.txt").is_file()
