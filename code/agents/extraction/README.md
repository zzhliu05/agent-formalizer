# PDF OCR and Theorem Extraction Agent

This is the first executable Agent 1 prototype for P001. It uses Gemini's native PDF understanding to jointly perform recognition, layout-aware parsing, formula transcription, theorem extraction, and prerequisite-context extraction.

The design follows the main practical lessons of [CC-OCR V2](https://arxiv.org/abs/2605.03903): document literacy must cover recognition, parsing, grounding, extraction, and question answering; relying on an unverified plain-text OCR intermediate can propagate errors; and evidence location is required for auditable results.

## Safety

- Never commit API keys or put them in command arguments.
- Supply `GEMINI_API_KEY` through the process environment.
- PDF files under `raw/textbooks/` are ignored by default because source licensing must be checked before publication.
- Put OCR experiments on unlicensed or privately held books under `outputs/private-tests/`; this directory is never published.
- Gemini uploads are deleted after each request on a best-effort basis.
- Temporary Gemini capacity and rate-limit errors use three bounded attempts with exponential backoff.

## Install

From the project root:

```powershell
python -m venv code/agents/extraction/.venv
code/agents/extraction/.venv/Scripts/python -m pip install -e "code/agents/extraction[dev]"
```

## Run

```powershell
$env:GEMINI_API_KEY = "your-rotated-key"
code/agents/extraction/.venv/Scripts/python -m pdf_ocr_agent `
  raw/textbooks/example.pdf `
  --output-root outputs/pipeline `
  --document-id example-textbook
```

Useful options:

- `--model`: defaults to `GEMINI_MODEL` or `gemini-3.5-flash-lite`, which succeeded on the first scanned-textbook test.
- `--max-attempts`: defaults to 3; set to 1 for a no-retry quota probe.
- `--pages-per-chunk`: defaults to 12.
- `--overlap-pages`: defaults to 2, preserving nearby definitions across chunk boundaries.
- `--source-page-offset`: preserves original PDF page anchors when running on a temporary page subset.
- `--dry-run`: validates the PDF and reports chunk boundaries without calling Gemini.

Each theorem is written to:

```text
outputs/pipeline/<theorem_id>/extraction/attempt-NNN/
  theorem.json
  context.md
  source.txt
```

`outputs/pipeline/<theorem_id>/extraction/latest.json` points to the newest immutable attempt.

Run-level files under `outputs/pipeline/_runs/<run_id>/` preserve each chunk's page OCR observations and structured response, including empty or failed-detection cases needed for prompt evaluation.

If visual OCR detects theorem-like printed labels but returns no candidates, the Gemini adapter conditionally performs one text-only recovery pass over the page observations. It does not invoke this extra pass for label-free chunks.

Candidates that still lack both prerequisites and notation trigger one batch context-enrichment pass. Local merge logic locks the extracted statement and source anchor, accepting only contextual fields from that pass.
