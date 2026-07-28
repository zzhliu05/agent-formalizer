# Agent 1: PDF OCR and Theorem Extraction

Agent 1 has two executable but strictly separated stages:

1. Gemini converts image-based or mixed PDFs into page-anchored Markdown chunks. It does not identify theorem records, infer prerequisites, generate theorem IDs, or produce Lean.
2. The ShanghaiTech GPT-5.5 adapter consumes only those Markdown chunks and produces source-grounded theorem, proof, omission, and prerequisite-context records.

## OCR output contract

Each run is immutable:

```text
<output-root>/<document-id>/<run-id>/
  manifest.json
  chunks/
    chunk-0001-pages-00001-00012.md
    chunk-0002-pages-00011-00022.md
```

Every Markdown file contains YAML metadata, explicit `<!-- pdf-page: N -->` anchors, one section per source page, OCR confidence comments, and warnings for uncertain content. Printed theorem labels remain ordinary transcribed Markdown.

## Theorem output contract

The second stage writes append-only attempts:

```text
<output-root>/<theorem-id>/extraction/
  attempt-001/
    theorem.json
    context.md
    source.txt
  latest.json

<output-root>/_runs/<document-id>/<run-id>/manifest.json
```

`theorem.json` contains the complete printed statement, complete printed proof, ordered proof steps, source pages, proof-availability status, omission evidence, nearby context, provider metadata, and hashes. Proof status is one of `complete`, `partial`, `omitted`, `by_reference`, `left_to_reader`, `not_applicable`, or `uncertain`.

Every quoted field is checked against the input Markdown. A complete proof's step strings must exhaustively cover its proof text. When only the step partition is unreliable, it is replaced with one exhaustive verbatim evidence step and the downgrade is recorded in `uncertainties`. A label not present in the source is rejected and listed in the run manifest.

Cross-page grounding removes OCR page anchors, generated page headings, and
book running headers such as `**16** PROLOGUE` before comparison, so a page
break cannot be mistaken for printed proof text.

These checks prevent silent proof invention; they do not replace mathematical review by Agent 3.

## Safety

- Never commit API keys or put them in command arguments.
- Supply `GEMINI_API_KEY` and `GPT55_API_KEY` through the process environment.
- PDF files under `raw/textbooks/` are ignored by default because source licensing must be checked before publication.
- Put experiments on privately held books under `outputs/private-tests/`; this directory is never published.
- Gemini uploads are deleted after each request on a best-effort basis.
- Both network adapters use bounded retries and secret-safe errors.
- The GPT-5.5 client ignores ambient proxy and certificate-file environment overrides because they can break this endpoint's TLS connection on Windows.

## Install

From the project root:

```powershell
python -m venv code/agents/extraction/.venv
code/agents/extraction/.venv/Scripts/python -m pip install -e "code/agents/extraction[dev]"
```

## Run

### PDF to Markdown

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

### Markdown to theorem packages

```powershell
$env:GPT55_API_KEY = "your-rotated-key"
code/agents/extraction/.venv/Scripts/python -m theorem_extractor `
  outputs/ocr/example-textbook/<run-id> `
  --output-root outputs/pipeline `
  --document-id example-textbook
```

Defaults:

- endpoint: `https://genaiapi.shanghaitech.edu.cn/api/v1/start`;
- requested model: `GPT-5.5`;
- deployment label recorded in manifests: `east-US-2-gpt-5.5`;
- reasoning effort: `medium`;
- structured output: strict JSON Schema over the Chat Completions-compatible request;
- token limit field: `max_completion_tokens`.

The deployment label is provenance metadata; routing is performed by the supplied endpoint.
