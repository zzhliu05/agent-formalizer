from __future__ import annotations


def markdown_prompt(*, document_id: str, original_page_start: int, original_page_end: int) -> str:
    return f"""
You are the OCR transcription stage for a mathematical textbook pipeline.

Convert every page of this PDF chunk from document {document_id!r} into faithful Markdown. The chunk
corresponds to original PDF pages {original_page_start} through {original_page_end}. In page_number, report
the ONE-BASED PAGE NUMBER WITHIN THIS SUPPLIED CHUNK; the local pipeline will restore original PDF numbers.

Transcription rules:
- Return exactly one page object for every supplied PDF page, in reading order.
- Transcribe all legible content. Do not summarize, explain, classify, or extract theorem records.
- For a visually blank page, set markdown to exactly `[Blank page]` and confidence to 1.
- Preserve printed theorem, proposition, definition, proof, exercise, and section labels as ordinary text.
- Use Markdown headings and lists when the visual hierarchy supports them.
- Preserve inline mathematics as `$...$` and display mathematics as `$$...$$` using LaTeX.
- Preserve tables as Markdown tables when simple and HTML tables when row/column spans require it.
- Represent figures or diagrams with a short bracketed description; do not invent unseen details.
- Record uncertain characters or layout in warnings rather than silently correcting them.
- Do not output Lean code, theorem IDs, prerequisites, or semantic analysis.
- Return only the requested JSON structure.
""".strip()
