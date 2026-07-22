from __future__ import annotations

from pydantic import BaseModel, Field


class PageMarkdown(BaseModel):
    """One-based page number within the PDF chunk supplied to Gemini."""

    page_number: int = Field(ge=1)
    markdown: str = Field(
        min_length=1,
        description="Faithful layout-aware Markdown transcription of the complete page",
    )
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(
        default_factory=list,
        description="Unreadable symbols, damaged regions, or uncertain layout decisions",
    )


class ChunkMarkdown(BaseModel):
    pages: list[PageMarkdown]
