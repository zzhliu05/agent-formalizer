from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from pdf_ocr_agent.models import ChunkMarkdown, PageMarkdown
from pdf_ocr_agent.pipeline import MarkdownPipeline


def _pdf(path: Path, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


class FakeExtractor:
    model_name = "fake-markdown-model"

    def extract(self, pdf_path: Path, prompt: str) -> ChunkMarkdown:
        from pypdf import PdfReader

        return ChunkMarkdown(
            pages=[
                PageMarkdown(
                    page_number=index,
                    markdown=f"### Proposition 0.{index}\n\n$A = A$",
                    confidence=0.99,
                )
                for index in range(1, len(PdfReader(pdf_path).pages) + 1)
            ],
        )


def test_chunk_plan_uses_overlap(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "book.pdf", 7)
    chunks = MarkdownPipeline(None).plan_chunks(pdf, pages_per_chunk=3, overlap_pages=1)
    assert chunks == [(1, 3), (3, 5), (5, 7)]


def test_gemini_schema_is_transcription_only() -> None:
    assert set(ChunkMarkdown.model_fields) == {"pages"}
    assert set(PageMarkdown.model_fields) == {
        "page_number",
        "markdown",
        "confidence",
        "warnings",
    }


def test_pipeline_writes_markdown_chunks_with_original_page_numbers(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "book.pdf", 3)
    result = MarkdownPipeline(FakeExtractor()).run(
        pdf,
        tmp_path / "outputs",
        document_id="My Book",
        pages_per_chunk=2,
        overlap_pages=1,
        source_page_offset=14,
    )
    assert result.document_id == "my-book"
    assert len(result.chunk_files) == 2
    assert result.run_dir.parent.name == "my-book"
    assert result.run_dir.parent.parent.name == "outputs"
    first = result.chunk_files[0].read_text(encoding="utf-8")
    assert "PDF page 15" in first
    assert "PDF page 16" in first
    assert "theorem_id" not in first
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["model"] == "fake-markdown-model"
    assert manifest["chunks"][1]["pdf_page_start"] == 16
    assert set(manifest) >= {"source_pdf_sha256", "chunks", "overlap_pages"}


class MissingPageExtractor(FakeExtractor):
    def extract(self, pdf_path: Path, prompt: str) -> ChunkMarkdown:
        return ChunkMarkdown(
            pages=[PageMarkdown(page_number=1, markdown="page", confidence=1)],
        )


def test_pipeline_rejects_missing_page_transcription(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "book.pdf", 2)
    with pytest.raises(ValueError, match="expected"):
        MarkdownPipeline(MissingPageExtractor()).run(
            pdf,
            tmp_path / "outputs",
            document_id="book",
            pages_per_chunk=2,
            overlap_pages=0,
        )
