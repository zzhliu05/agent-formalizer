# PDF OCR Agent Instructions

This directory belongs to Agent 1 of [[docs/architecture/Three-Agent Pipeline]].

## Mission

For the current milestone, convert textbook PDFs into faithful, page-anchored Markdown chunks. Theorem identification and prerequisite inference are paused and must not be performed by the Gemini transcription step.

## Rules

- Preserve page-level provenance, reading order, original wording, and mathematical notation.
- Record uncertain symbols or damaged OCR explicitly; never guess silently.
- Preserve printed definitions, theorem labels, proofs, exercises, and surrounding prose as Markdown without semantic classification.
- Produce immutable Markdown chunks and a run manifest as defined in the architecture document.
- Do not produce theorem IDs, prerequisite graphs, Lean code, or mathematical acceptance decisions.
