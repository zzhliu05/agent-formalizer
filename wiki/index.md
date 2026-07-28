---
type: wiki
status: seed
created: 2026-07-22
updated: 2026-07-28
---

# 多 Agent 形式化数学教材 Vault Index

This is the navigational map for the project. Start here after reading the newest relevant entries in [[process-log]] when project continuity matters.

## Core Pages

- [[process-log]] - newest-first agent memory for the research journey.

## Active Processes

- P001 — [[../docs/architecture/Four-Agent Pipeline|Four-Agent Formalization Pipeline]]: define and implement the PDF-to-Lean workflow across extraction, formalization, and independent review.
- P002 — [[papers/HyperTree Proof Search for Neural Theorem Proving]] and [[papers/Aristotle IMO-level Automated Theorem Proving]]: study proof-hypergraph search, online learning, informal lemma decomposition, and formal feedback as direct references for the local formalization and review pipeline.

## Wiki Areas

- `wiki/topics/` - broad research areas and long-running themes.
- `wiki/concepts/` - reusable concepts, definitions, and conceptual building blocks.
- `wiki/methods/` - algorithms, mathematical tools, workflows, and technical procedures.
- `wiki/papers/` - durable source-oriented paper pages.

## Papers

- [[papers/Aristotle IMO-level Automated Theorem Proving]] — hybrid informal reasoning, Lean proof search, formal feedback, and IMO-level automated theorem proving.
- [[papers/HyperTree Proof Search for Neural Theorem Proving]] — proof-hypergraph search, learned policy/critic guidance, and online training for Metamath and Lean.
- [[papers/CC-OCR V2]] — document OCR and structured extraction benchmark relevant to Agent 1.

## Working Areas

- `raw/` - immutable sources.
- `notes/` - research notes, derivations, reading notes, scratch calculations, and speculative ideas.
- `code/` - scripts, notebooks, toy implementations, numerical experiments, and utilities.
- `outputs/` - generated tables, exports, summaries, and intermediate results.
- `figures/` - reusable generated or imported figures.
- `docs/` - project-level documentation and design specs.

## Current Status

The vault scaffold is initialized and P001 defines the four-agent architecture. Agent 1 now has a strict two-stage implementation under `code/agents/extraction/`: Gemini performs page-anchored PDF-to-Markdown conversion only, and a separate ShanghaiTech GPT-5.5 adapter extracts source-grounded theorem statements, complete printed proofs, proof-omission states, and prerequisite context. The larger private Folland test is recorded in [[../notes/2026-07-23 GPT-5.5 Theorem Extraction Test]]. Agent 2 has a validated Lean 4.28.0 + Mathlib v4.28.0 environment and a project-isolated `aristotlelib 2.1.0` runtime under `code/agents/formalization/`. It validates immutable Agent 1 packages, prepares Aristotle projects, performs non-interactive and resumable first-candidate generation, validates returned Lean locally, and writes an Agent 3 handoff. As recorded in [[../notes/2026-07-24 Agent 1 Test Corpus Formalization Batch]], all 20 proof-bearing records in the canonical Agent 1 test corpus now have real Aristotle candidates that passed local Lean validation and reached `ready_for_review`; source axiom 0.4 remains declaration-only. Agent 3 is now implemented under `code/agents/review/` with independent Lean build, placeholder and axiom gates, a persisted Lean-only back-translation before source access, exact source statement/proof-method comparison, and an Agent 3 -> Aristotle -> Agent 2 validation -> Agent 3 revision loop. The real Folland Proposition 0.6 cycle is recorded in [[../notes/2026-07-25 Agent 3 Review Loop]].
