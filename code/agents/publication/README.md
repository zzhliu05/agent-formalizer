# Agent 4 — LaTeX Publication

Agent 4 turns a completed Agent 3 chapter inventory into a self-contained
English ElegantBook project based on the user-selected `elegantbook-en.tex`.
It publishes only terminally accepted records.

## What it verifies

For every chapter item the agent:

1. requires `accepted` or `accepted_declaration`;
2. loads the exact Agent 3 review recorded by the chapter summary;
3. loads and revalidates the selected Agent 2 handoff and every Lean SHA-256;
4. checks that Agent 3 reviewed that exact handoff, `Main.lean`, and Agent 1
   theorem hash;
5. finds and validates the matching immutable Agent 1 theorem package.

## Output

The generated directory contains:

- `book.tex` and optionally `book.pdf`;
- the local `elegantbook.cls`, license, cover, and logo;
- `lean/<theorem-number>/...` with all accepted hash-bound Lean files;
- `manifest.json` with complete provenance and SHA-256 bindings.

Each theorem section contains the source statement, source pages, prerequisite
context, proof-completeness status, available natural-language proof,
structured proof steps, Agent 3 verdict, Lean declaration name, and a PDF
`run:` hyperlink to the bundled `Main.lean`. Agent 4's fixed headings and
metadata are English so the generated document remains valid under
ElegantBook's `lang=en` restriction.

## Project-isolated setup

```powershell
cd "C:\Users\liuzi\Documents\agent formalizer\code\agents\publication"
uv sync --extra dev
uv run publication-agent --help
```

## Build Folland Chapter 0

```powershell
uv run publication-agent build `
  "..\..\..\outputs\private-tests\agent2-folland-batch\_chapter_review\chapter-summary.json" `
  "..\..\..\outputs\private-tests\agent4-folland-chapter-0" `
  --source-root "..\..\..\outputs\private-tests\folland-chapter-0-extraction-head" `
  --source-root "..\..\..\outputs\private-tests\folland-chapter-0-corpus" `
  --title "Multi-Agent Formal Mathematics Textbook" `
  --subtitle "A Formalized Edition of Folland's Real Analysis" `
  --chapter-title "Chapter 0: Preliminaries" `
  --compile
```

Compilation requires a TeX Live installation exposing `latexmk` and
`xelatex`. PDF viewers may block local-file launch actions; the linked relative
Lean path is also printed in the document.
