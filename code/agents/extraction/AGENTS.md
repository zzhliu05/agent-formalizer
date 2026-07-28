# Agent 1 Extraction Instructions

This directory belongs to Agent 1 of [[docs/architecture/Four-Agent Pipeline]].

## Mission

Run two strictly separated internal stages:

1. Gemini converts textbook PDFs into faithful, page-anchored Markdown chunks only.
2. The approved GPT-5.5 adapter consumes those Markdown chunks and extracts theorem/context packages with complete source-grounded statements and proof text.

## Rules

- Preserve page-level provenance, reading order, original wording, and mathematical notation.
- Record uncertain symbols or damaged OCR explicitly; never guess silently.
- Preserve printed definitions, theorem labels, proofs, exercises, and surrounding prose as Markdown without semantic classification.
- Produce immutable Markdown chunks and a run manifest as defined in the architecture document.
- Never give Gemini theorem identification, prerequisite inference, or theorem-package prompts.
- The GPT-5.5 stage must read Markdown, not the original PDF.
- Reject any GPT-5.5 statement, proof, proof step, omission marker, or context quotation that cannot be found in the source Markdown after whitespace and Markdown-emphasis normalization.
- Preserve the full printed proof. If the source omits details, cites another result, leaves work to the reader, or crosses a chunk boundary, record that condition explicitly instead of completing the proof.
- Proof-step segmentation may fall back to one exhaustive verbatim step when a finer model-generated partition would lose or change source text.
- Do not produce Lean code or mathematical acceptance decisions.
