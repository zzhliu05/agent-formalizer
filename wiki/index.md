---
type: wiki
status: seed
created: 2026-07-22
updated: 2026-07-24
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

The vault scaffold is initialized and P001 defines the three-agent architecture. Agent 1 now has a strict two-stage implementation under `code/agents/extraction/`: Gemini performs page-anchored PDF-to-Markdown conversion only, and a separate ShanghaiTech GPT-5.5 adapter extracts source-grounded theorem statements, complete printed proofs, proof-omission states, and prerequisite context. The larger private Folland test is recorded in [[../notes/2026-07-23 GPT-5.5 Theorem Extraction Test]]. Agent 2 has a validated Lean 4.28.0 + Mathlib v4.28.0 environment and a project-isolated `aristotlelib 2.1.0` runtime under `code/agents/formalization/`. It validates immutable Agent 1 packages, prepares Aristotle projects, performs non-interactive and resumable first-candidate generation, validates returned Lean locally, and writes an Agent 3 handoff. The credentialed Folland Proposition 0.16 run reached `ready_for_review`, as recorded in [[../notes/2026-07-24 Agent 2 Lean Proof Generation]]. Agent 3 back-translation and its semantic questioning loop remain pending.
