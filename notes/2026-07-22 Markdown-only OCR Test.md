---
type: note
status: active
created: 2026-07-22
updated: 2026-07-22
process: P001
---

# Markdown-only OCR Test

## Scope

Ran the current Gemini Markdown-only stage against original PDF pages 19–21 of a private, image-only local scan of Folland's *Real Analysis*. The test used `gemini-3.5-flash-lite`, one three-page chunk, no overlap, and original-page offset 18.

The output remains local under the Git-ignored `outputs/private-tests/folland-markdown-only/` tree.

## Result

- Generated one immutable run manifest and one Markdown chunk.
- Preserved PDF page anchors 19, 20, and 21.
- Transcribed the page text, printed definitions, theorem/proposition labels, proofs, lists, and display formulas as ordinary Markdown.
- Emitted no theorem IDs, candidates, prerequisite records, or semantic extraction fields.
- Visual comparison found the page order and major mathematical content consistent with the rendered scan.

## Known issue

On page 19, a set-family expression begins with an escaped left brace outside the inline math delimiter rather than placing the full expression inside `$...$`. The model assigned confidence 0.99 and emitted no warning, so confidence alone is not a sufficient Markdown-quality gate.

## Follow-up

- Add deterministic checks for unmatched or split math delimiters and escaped braces adjacent to `$...$`.
- Evaluate Markdown fidelity on tables, multi-line aligned equations, footnotes, and diagrams before chapter-scale conversion.
- Keep theorem/context extraction disabled until a separate model adapter is selected.
