---
type: project-spec
status: active
created: 2026-07-22
updated: 2026-07-24
---

# Three-Agent Formalization Pipeline

## Objective

Convert textbook PDFs into traceable Lean 4 + Mathlib theorems through exactly three specialized agents. The orchestration layer only moves artifacts and records state; it is not a fourth reasoning agent.

```text
PDF source
  -> Agent 1: OCR and theorem/context extraction
  -> Agent 2: Lean formalization through Harmonic Aristotle
  -> Agent 3: semantic and formal audit
  -> accepted artifact or routed revision
```

Each theorem receives a stable `theorem_id`. Every downstream artifact must retain that identifier and the original page references so that an accepted Lean theorem can be traced back to the textbook.

## Agent 1 — PDF OCR and Theorem Extraction

### Current milestone: separated OCR and theorem extraction

Gemini performs only page-faithful PDF-to-Markdown conversion. It must not classify theorem records, infer prerequisites, assign theorem IDs, or emit formalization packages.

The OCR output contract is:

```text
outputs/ocr/<document_id>/<run_id>/
  manifest.json
  chunks/
    chunk-NNNN-pages-PPPPP-QQQQQ.md
```

Each Markdown chunk carries original PDF page anchors, OCR confidence, warnings, and overlapping boundary pages when configured. Downstream stages must treat these files as transcriptions, not verified mathematical interpretations.

Agent 1 has two active internal stages without creating an additional project agent:

1. **OCR stage:** Gemini 3.5 Flash-Lite converts PDF chunks to Markdown only.
2. **Theorem stage:** the ShanghaiTech GPT-5.5 adapter converts Markdown chunks into theorem/context packages.

The Gemini adapter never receives the theorem extraction schema or prompts. The GPT-5.5 adapter consumes the Markdown, not the PDF, so model responsibilities remain auditable.

### Theorem extractor responsibilities

- Read only the page-anchored Markdown emitted by the OCR stage.
- Detect theorem-like units, including definitions, lemmas, propositions, corollaries, exercises promoted as claims, and named results.
- Preserve the original theorem wording and source anchors: document identifier, edition when known, page range, section, and nearby heading.
- Preserve the complete printed proof and split it into exhaustive source-grounded steps.
- Mark proofs as `partial`, `omitted`, `by_reference`, `left_to_reader`, or `uncertain` whenever the printed source does not supply a complete proof.
- Extract the theorem context required for formalization:
  - local definitions and notation;
  - variable domains and standing assumptions;
  - earlier results explicitly or implicitly used;
  - relevant surrounding prose and proof sketch;
  - unresolved OCR ambiguities and confidence.
- Distinguish quoted source text from reconstructed or inferred context.

### Theorem extraction output contract

Write immutable attempts under `outputs/pipeline/<theorem_id>/extraction/attempt-NNN/` containing:

- `theorem.json`: identifier, source anchors, complete verbatim statement and proof, proof status, exhaustive proof steps, omission evidence, local context, uncertainties, provider metadata, and input hashes;
- `context.md`: readable prerequisite context, proof availability, and ambiguity notes;
- `source.txt`: the minimally necessary statement, proof, omission marker, and context evidence.

`outputs/pipeline/<theorem_id>/extraction/latest.json` identifies the newest attempt without overwriting prior evidence.

Before any candidate is written, all quoted fields must match the source Markdown after whitespace and Markdown-emphasis normalization. Fine proof-step segmentation that fails exact coverage is collapsed to one exhaustive verbatim step and flagged. Ungrounded labels are rejected and recorded in the run manifest. Chunk validation is transactional: a grounded candidate failure prevents all candidates in that chunk from being written.

Agent 1 must not write Lean code, invent missing proof steps, or silently repair a mathematically ambiguous source statement. Ambiguity is recorded for review or user resolution.

## Agent 2 — Lean Formalization

### Current milestone: first-candidate Lean proof generation

The local project under `code/agents/formalization/` pins Lean 4.28.0 and
Mathlib v4.28.0, matching the current Aristotle setup requirement supplied for
this project. The generated dependency manifest and a narrow-import Mathlib
smoke test build successfully. Agent 2 pins `aristotlelib 2.1.0` in its
project-local `pyproject.toml` and `uv.lock`; reproducible runs use
`uv run --locked aristotle`. A credentialed, read-only project-list request has
validated authentication and basic live service access.

The preparation adapter reads the immutable Agent 1 package, verifies its
latest-pointer and companion artifacts, applies formalization safety gates, and
produces a minimal Lean project plus prompt. The generation adapter then
submits that project through the pinned Aristotle SDK with agent questions
disabled, polls without interaction, supports resuming the same task after a
local timeout, downloads and safely extracts the result, checks protected
inputs and prohibited placeholders, performs local Lean kernel validation, and
writes the first candidate handoff for Agent 3.

The implementation is validated by a credentialed Folland Proposition 0.16
run. The task survived a local polling transport interruption through the
resumable Project/Task path, returned a complete theorem, passed local Lean
4.28.0 validation, and produced an Agent 3 handoff.

### Responsibilities

- Consume only a complete Agent 1 theorem package.
- Map extracted concepts to Lean 4 and Mathlib definitions, recording non-obvious modeling choices.
- Build a self-contained theorem statement and proof context, then submit the formalization task through a dedicated non-interactive Harmonic Aristotle adapter.
- Preserve Aristotle request identifiers, status, model/service metadata when returned, and a sanitized execution record without credentials.
- Compile the returned Lean artifact locally and iterate on formal errors before handing it to review.
- Stop after the first mechanically valid candidate. Do not ask Aristotle
  follow-up questions or autonomously iterate on semantic objections.

### Aristotle integration boundary

The current transport boundary is the official `aristotlelib 2.1.0`
existing-project workflow implemented through
`Project.create_from_directory`. Agent 2 passes
`AgentQuestionsSetting.DISABLED` and polls task status without using the SDK's
interactive wait helper. Authentication remains the `ARISTOTLE_API_KEY`
process environment variable.

Project/task identifiers, status transitions, archive hashes, and validation
results are recorded in sanitized generation metadata. API credentials must
never enter Git, prompts saved in the vault, or output artifacts.

### Output contract

Write immutable preparation attempts under
`outputs/pipeline/<theorem_id>/formalization/preparation/attempt-NNN/`:

- `request.json`: sanitized input/artifact hashes and Aristotle command shape;
- `prompt.txt`: exact task instructions for Aristotle;
- `project/Main.lean`: placeholder-free Lean staging module;
- `project/SOURCE_THEOREM.md`: statement, prerequisites, proof availability,
  and source-grounded proof text;
- `project/FORMALIZATION_NOTES.md`: required interpretation/build record;
- pinned Lean, Lake, and Mathlib project files.

Write immutable generation attempts under
`outputs/pipeline/<theorem_id>/formalization/generation/attempt-NNN/`:

- `run.json`: sanitized Aristotle task IDs, status history, archive hash, and
  mechanical validation status;
- `result.tar.gz` and safely extracted result project;
- `build.log`: local Lean kernel-validation result;
- `handoff.json`: exact source/candidate hashes and Agent 3 review ownership.

Agent 2 may use temporary `sorry` placeholders while working, but a bundle containing `sorry`, `admit`, or `sorryAx` is never eligible for acceptance.

## Agent 3 — Semantic and Formal Audit

### Responsibilities

- Treat the original Agent 1 package and Agent 2 Lean bundle as independent inputs.
- Translate the Lean theorem statement back into natural mathematical language without consulting Agent 2's prose explanation first.
- Compare the translation against the source theorem, checking:
  - quantifiers, variable domains, hypotheses, and conclusion;
  - implication direction and logical strength;
  - boundary conditions, exceptional cases, and uniqueness/existence claims;
  - definitions or typeclass assumptions that change the intended meaning.
- Run the Lean project build and reject any compilation failure.
- Statically reject `sorry`, `admit`, and explicit `sorryAx` occurrences in submitted Lean sources.
- Inspect the accepted theorem's axioms and reject any dependency on `sorryAx`; record any other nonstandard axioms for explicit review.
- Never modify the candidate proof while auditing it.
- Own the post-handoff questioning loop. Agent 3 may use the recorded
  Aristotle project to ask about an interpretation or issue a revision
  instruction; any revised candidate must pass Agent 2's mechanical gates
  before another semantic verdict.

### Output contract and routing

Write `outputs/pipeline/<theorem_id>/review/review.md` with the back-translation, comparison table, build result, axiom result, issues, and exactly one verdict:

- `accepted`: semantics match, Lean builds, and no prohibited placeholders or `sorryAx` dependency exists;
- `needs_reformalization`: source extraction is adequate but the Lean statement/proof is wrong or incomplete; route to Agent 2;
- `needs_reextraction`: the source statement or prerequisite context is missing or ambiguous; route to Agent 1.

Only Agent 3 can mark a theorem package as accepted.

## Shared State and Failure Policy

- Pipeline states are `extracted`, `formalizing`, `ready_for_review`, `accepted`, `needs_reformalization`, and `needs_reextraction`.
- Artifacts are append-only per attempt. Corrections create a new attempt directory rather than overwriting evidence used by a prior review.
- Each handoff records input artifact hashes so the review verdict is tied to an exact source and Lean candidate.
- Network errors, API timeouts, and rate limits do not change mathematical status; they leave the item retryable in `formalizing`.
- OCR uncertainty below the eventual configured threshold is surfaced to Agent 3 and cannot be silently promoted to `accepted`.

## Official Basis

- [Harmonic Aristotle](https://aristotle.harmonic.fun/) states that Aristotle can receive an English problem or work directly inside a Lean project.
- [aristotlelib 2.1.0](https://pypi.org/project/aristotlelib/2.1.0/) documents the `submit --project-dir` existing-project workflow used by Agent 2 preparation.
- [Aristotle technical report](https://harmonic.fun/pdf/Aristotle_IMO_Level_Automated_Theorem_Proving.pdf) treats a result as solved only when Lean 4 + Mathlib verifies a complete proof without gaps or unsound axioms such as `sorryAx`.
- [Aristotle API Terms](https://aristotle.harmonic.fun/terms) require users to independently review, test, and validate generated output.
