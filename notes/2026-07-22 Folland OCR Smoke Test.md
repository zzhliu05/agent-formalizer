---
type: note
status: active
created: 2026-07-22
updated: 2026-07-22
process: P001
---

# Folland OCR Smoke Test

## Scope

Tested Agent 1 against a private, image-only local scan of Gerald B. Folland's *Real Analysis: Modern Techniques and Their Applications*, second edition. The source has 402 PDF pages and no extractable text layer in sampled pages.

The controlled test used original PDF pages 19–21, selected after visual rendering. The pages contain the local definition of cardinal comparison and ten labeled mathematical units spanning Axiom 0.4 through Corollary 0.13.

## Model Attempts

- `gemini-3.5-flash`: authentication succeeded, but the project had exhausted its free-tier request quota for that model.
- `gemini-2.5-flash`: the API reported that the model was unavailable to new users for this account.
- `gemini-3.5-flash-lite`: successfully performed visual PDF recognition and structured page OCR.

## Result

- The first Flash-Lite pass accurately transcribed the relevant pages, formulas, and printed labels but returned no theorem candidates.
- A conditional text-only recovery pass promoted all ten detected labels into theorem packages.
- A batch context-enrichment pass added local definitions and notation while local merge logic preserved the original extracted statements and page anchors.
- The Schröder–Bernstein Theorem package points to original PDF page 20 and cites the cardinal-comparison definition and `card(X)` notation from page 19.
- Correct test artifacts are stored locally under the Git-ignored `outputs/private-tests/folland/` tree and are not published.

## Follow-up

- Rotate the API key disclosed during interactive testing.
- Evaluate symbol-level transcription and prerequisite recall on additional pages before processing a full chapter.
- Add a deterministic quality report that distinguishes direct visual candidates from recovered and enriched candidates.
