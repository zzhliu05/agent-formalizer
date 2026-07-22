---
type: wiki
status: seed
created: 2026-07-22
updated: 2026-07-22
---

# 多 Agent 形式化数学教材 Vault Index

This is the navigational map for the project. Start here after reading the newest relevant entries in [[process-log]] when project continuity matters.

## Core Pages

- [[process-log]] - newest-first agent memory for the research journey.

## Active Processes

- P001 — [[../docs/architecture/Three-Agent Pipeline|Three-Agent Formalization Pipeline]]: define and implement the PDF-to-Lean workflow across extraction, formalization, and independent review.

## Wiki Areas

- `wiki/topics/` - broad research areas and long-running themes.
- `wiki/concepts/` - reusable concepts, definitions, and conceptual building blocks.
- `wiki/methods/` - algorithms, mathematical tools, workflows, and technical procedures.
- `wiki/papers/` - durable source-oriented paper pages.

## Working Areas

- `raw/` - immutable sources.
- `notes/` - research notes, derivations, reading notes, scratch calculations, and speculative ideas.
- `code/` - scripts, notebooks, toy implementations, numerical experiments, and utilities.
- `outputs/` - generated tables, exports, summaries, and intermediate results.
- `figures/` - reusable generated or imported figures.
- `docs/` - project-level documentation and design specs.

## Current Status

The vault scaffold is initialized, P001 defines the three-agent architecture, and Agent 1 currently uses Gemini only for page-anchored PDF-to-Markdown conversion under `code/agents/extraction/`. The theorem/context extraction stage is paused pending a separate extractor and evaluation policy. See [[papers/CC-OCR V2]] and the superseded [[../notes/2026-07-22 Folland OCR Smoke Test]].
