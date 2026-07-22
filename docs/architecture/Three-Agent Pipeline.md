---
type: project-spec
status: active
created: 2026-07-22
updated: 2026-07-22
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

### Responsibilities

- Read textbook PDFs with OCR when embedded text is missing or unreliable.
- Detect theorem-like units, including definitions, lemmas, propositions, corollaries, exercises promoted as claims, and named results.
- Preserve the original theorem wording and source anchors: document identifier, edition when known, page range, section, and nearby heading.
- Extract the theorem context required for formalization:
  - local definitions and notation;
  - variable domains and standing assumptions;
  - earlier results explicitly or implicitly used;
  - relevant surrounding prose and proof sketch;
  - unresolved OCR ambiguities and confidence.
- Distinguish quoted source text from reconstructed or inferred context.

### Output contract

Write one theorem package under `outputs/pipeline/<theorem_id>/extraction/` containing:

- `theorem.json`: identifier, source anchors, normalized statement, assumptions, variables, conclusion, dependencies, and OCR confidence;
- `context.md`: readable source context, prerequisite explanations, notation map, and ambiguity notes;
- `source.txt`: the minimally necessary OCR excerpt with page markers.

Agent 1 must not write Lean code or silently repair a mathematically ambiguous source statement. Ambiguity is recorded for review or user resolution.

## Agent 2 — Lean Formalization

### Responsibilities

- Consume only a complete Agent 1 theorem package.
- Map extracted concepts to Lean 4 and Mathlib definitions, recording non-obvious modeling choices.
- Build a self-contained theorem statement and proof context, then submit the formalization task through a dedicated Harmonic Aristotle API adapter.
- Preserve Aristotle request identifiers, status, model/service metadata when returned, and a sanitized execution record without credentials.
- Compile the returned Lean artifact locally and iterate on formal errors before handing it to review.

### Aristotle integration boundary

The concrete endpoint, authentication header, request fields, polling behavior, quotas, and retry rules must be implemented from the current official Aristotle API documentation. They are intentionally not hard-coded in this architecture document. API credentials must come from the runtime environment or a local secret store and must never enter Git, prompts saved in the vault, or output artifacts.

### Output contract

Write the formalization bundle under `outputs/pipeline/<theorem_id>/formalization/`:

- `Main.lean`: Lean theorem statement and proposed proof;
- `formalization.md`: mapping choices, imported Mathlib concepts, and known limitations;
- `aristotle-run.json`: sanitized request/run metadata and completion status;
- `build.log`: local Lean build result.

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
- [Aristotle technical report](https://harmonic.fun/pdf/Aristotle_IMO_Level_Automated_Theorem_Proving.pdf) treats a result as solved only when Lean 4 + Mathlib verifies a complete proof without gaps or unsound axioms such as `sorryAx`.
- [Aristotle API Terms](https://aristotle.harmonic.fun/terms) require users to independently review, test, and validate generated output.
