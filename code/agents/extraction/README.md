# PDF-to-Markdown OCR Agent

This is the current executable Agent 1 milestone for P001. Gemini is used only to convert image-based or mixed PDFs into page-anchored Markdown chunks. It does not identify theorem records, infer prerequisites, generate theorem IDs, or produce Lean.

The theorem and context extraction stage is intentionally deferred until a separate extractor and evaluation policy are selected.

## Output contract

Each run is immutable:

```text
<output-root>/<document-id>/<run-id>/
  manifest.json
  chunks/
    chunk-0001-pages-00001-00012.md
    chunk-0002-pages-00011-00022.md
```

Every Markdown file contains YAML metadata, explicit `<!-- pdf-page: N -->` anchors, one section per source page, OCR confidence comments, and warnings for uncertain content. Printed theorem labels remain ordinary transcribed Markdown.

The future theorem/context extractor will consume these Markdown chunks through a separate model adapter. It is not part of this package yet.

## Safety

- Never commit API keys or put them in command arguments.
- Supply `GEMINI_API_KEY` through the process environment.
- PDF files under `raw/textbooks/` are ignored by default because source licensing must be checked before publication.
- Put experiments on privately held books under `outputs/private-tests/`; this directory is never published.
- Gemini uploads are deleted after each request on a best-effort basis.
- Temporary capacity and rate-limit errors use bounded retries with exponential backoff.

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
  --output-root outputs/ocr `
  --document-id example-textbook
```

Options:

- `--model`: defaults to `GEMINI_MODEL` or `gemini-3.5-flash-lite`.
- `--pages-per-chunk`: defaults to 12.
- `--overlap-pages`: defaults to 2.
- `--source-page-offset`: restores original page anchors when processing a temporary PDF subset.
- `--max-attempts`: defaults to 3.
- `--dry-run`: validates the PDF and reports chunk boundaries without calling Gemini.
