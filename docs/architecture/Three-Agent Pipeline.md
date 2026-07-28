---
type: project-spec
status: active
created: 2026-07-22
updated: 2026-07-27
---

# Four-Agent Formalization and Publication Pipeline

## Objective

Convert textbook PDFs into traceable Lean 4 + Mathlib theorems and a
cross-linked LaTeX textbook through exactly four specialized agents. The
orchestration layer only moves artifacts and records state; it is not a fifth
reasoning agent. The filename is retained for compatibility with existing vault
links created before Agent 4 was added.

```text
PDF source
  -> Agent 1: OCR and theorem/context extraction
  -> Agent 2: Lean formalization through Harmonic Aristotle
  -> Agent 3: semantic and formal audit
  -> accepted artifact or routed revision
  -> Agent 4: verified LaTeX publication with Lean source links
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
- For a multi-file result, resolve the target's local import graph and compile
  dependencies into an isolated temporary `.olean` tree before compiling the
  target; do not require provider-supplied build products.
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

For follow-up revisions, remote `COMPLETE_WITH_ERRORS` and `OUT_OF_BUDGET`
states are recoverable only when Aristotle exposes an output archive. The
status itself never counts as success: Agent 2 must independently validate the
recovered checkpoint before Agent 3 can review it. Failed, canceled, and
archive-less terminal tasks remain rejected and resumable or replaceable.
If local validation rejects a recovered checkpoint, a narrower follow-up may
continue from it only after verifying that its project and task ancestry leads
back to the reviewed Agent 2 run. This permits incremental placeholder repair
without weakening protected-file, hash, placeholder, build, or review gates.
The executable review loop now performs that recovery automatically: it
captures the Agent 2 error and bounded Lean build-log tail, detects repeated
Lean checkpoints, issues a hash-bound repair request against the failed Task,
and re-enters the complete Agent 2 gate sequence. A separate repair limit
prevents an unbounded no-progress loop.

### Output contract

New Agent 2 output uses a compact, deterministic theorem directory:
`outputs/pipeline/t-<SHA-256(theorem_id)[0:16]>/`. Its `theorem.json` binds the
short key to the complete theorem ID and is verified before reuse. Full IDs
remain in all provenance records.

Write immutable preparation attempts under
`outputs/pipeline/t-<16-hex>/prep/NNN/`:

- `request.json`: sanitized input/artifact hashes and Aristotle command shape;
- `prompt.txt`: exact task instructions for Aristotle;
- `lean/Main.lean`: placeholder-free Lean staging module;
- `lean/SOURCE_THEOREM.md`: statement, prerequisites, proof availability,
  and source-grounded proof text;
- `lean/FORMALIZATION_NOTES.md`: required interpretation/build record;
- pinned Lean, Lake, and Mathlib project files.

Write immutable generation attempts under
`outputs/pipeline/t-<16-hex>/gen/NNN/`:

- `run.json`: sanitized Aristotle task IDs, status history, archive hash, and
  mechanical validation status;
- `result.tar.gz` plus the safely extracted, normalized `lean/` project;
- `build.log`: local Lean kernel-validation result;
- `handoff.json`: exact source/candidate hashes and Agent 3 review ownership.

`gen/latest.json` always identifies the newest attempt, including a failed
one. `gen/latest-ready.json` advances only when a complete Agent 3 handoff is
available, so chapter orchestration can recover from a later rejected
checkpoint without weakening any validation.

The archive is retained as immutable transport evidence, but provider wrapper
directories such as `result/output-final_aristotle/` are not retained in the
working tree. Readers accept both this compact layout and the legacy
`<theorem_id>/formalization/{preparation,generation}/attempt-NNN/` layout.
Existing output is never migrated while an Agent 2 or Agent 3 process may be
writing it.

Agent 2 may use temporary `sorry` placeholders while working, but a bundle containing `sorry`, `admit`, or `sorryAx` is never eligible for acceptance.

## Agent 3 — Semantic and Formal Audit

### Responsibilities

The implementation under `code/agents/review/` separates review into two
model calls. The first call receives only Lean sources, declaration names, and
the independent axiom-audit output. Its natural-language statement and proof
reconstruction is saved before the second stage is allowed to open Agent 1's
source package. Agent 2 prose is excluded from both stages.

The second call checks both semantic statement equivalence and exact
proof-method correspondence at the level supported by the printed source.
Complete proofs require complete method agreement. Partial and
left-to-reader records may pass only when the source explicitly preserves the
high-level method and Lean fills identified local omissions. By-reference
records may pass only when Lean uses the same cited result or its established
formal counterpart. A source principle with no printed proof uses
declaration-only statement review and can never claim proof-method agreement.

- Treat the original Agent 1 package and Agent 2 Lean bundle as independent inputs.
- Translate the Lean theorem statement and complete proof back into natural
  mathematical language using only Lean as input.
- Compare the translation against the source theorem, checking:
  - quantifiers, variable domains, hypotheses, and conclusion;
  - implication direction and logical strength;
  - boundary conditions, exceptional cases, and uniqueness/existence claims;
  - definitions or typeclass assumptions that change the intended meaning.
- Run the Lean project build and reject any compilation failure.
- Statically reject `sorry`, `admit`, and explicit `sorryAx` occurrences across
  every submitted Lean source, including helper lemmas.
- Reject candidate-introduced `axiom`, `constant`, and `opaque` declarations.
- Run `#print axioms` for every theorem or lemma and reject `sorryAx` or an
  axiom outside the approved Lean/Mathlib baseline.
- Never modify the candidate proof while auditing it.
- Own the post-handoff questioning loop. Agent 3 may use the recorded
  Aristotle project to issue a structured revision instruction through
  `Project.ask` with questions disabled. Any revised archive must pass Agent
  2's protected-file, placeholder, declaration, and Lean-build gates as a new
  generation attempt before another isolated Agent 3 verdict. If those Agent 2
  gates fail, the orchestrator automatically returns the exact local
  diagnostics to the same Aristotle project and continues from that failed
  checkpoint until validation succeeds or the explicit repair bound is
  reached.

### Output contract and routing

Write immutable attempts under
`outputs/pipeline/<theorem_id>/review/attempt-NNN/`. Each attempt contains the
Lean-only input, frozen back-translation, independent mechanical/axiom logs,
source comparison, review summary, and-when rejected-a hash-bound
`revision_request.json`.

Emit exactly one verdict:

- `accepted`: semantics match, Lean builds, and no prohibited placeholders or `sorryAx` dependency exists;
- `accepted_declaration`: a source principle supplies no proof method, but its
  formal statement and all mechanical gates pass;
- `needs_reformalization`: source extraction is adequate but the Lean statement/proof is wrong or incomplete; route to Agent 2;
- `needs_reextraction`: the source statement or prerequisite context is missing or ambiguous; route to Agent 1.

Only Agent 3 can mark a theorem package as accepted.

The executable loop is:

```text
Agent 2 ready_for_review
  -> Agent 3 independent audit and blind Lean back-translation
  -> accepted / accepted_declaration / needs_reextraction
     or needs_reformalization
  -> Agent 3 Aristotle revision
  -> Agent 2 validates the returned archive as a new attempt
     -> validation_failed: diagnostic repair request -> Aristotle -> Agent 2
        (bounded inner loop)
  -> Agent 3 starts a fresh isolated review
```

## Agent 4 — Verified LaTeX Publication

The implementation under `code/agents/publication/` consumes a completed Agent
3 chapter inventory. It does not reason about or repair mathematics. It is a
strict publication boundary that refuses nonterminal records and republishes
only exact, hash-bound artifacts that Agent 3 accepted.

### Responsibilities

- Require every chapter item to have verdict `accepted` or
  `accepted_declaration`.
- Revalidate the recorded Agent 3 review, the exact Agent 2 handoff and
  `Main.lean` hash, every bundled Lean source hash, and the exact Agent 1
  theorem-package hash.
- Preserve the extracted statement, source pages, prerequisite context,
  proof-completeness status, available natural-language proof, structured proof
  steps, and uncertainty notes without inventing omitted material.
- Render each item with the project copy of the user-selected
  `elegantbook-en.tex` design and the locally vendored `elegantbook.cls`,
  license, cover, and logo. Agent 4's fixed headings and metadata remain in
  English to comply with the template's `lang=en` character restrictions.
- Copy every accepted Lean source into a short
  `lean/<theorem-number>/...` directory inside the publication bundle.
- Add one PDF launch hyperlink per theorem to its bundled `Main.lean` and print
  the same relative path for PDF viewers that block launch actions.
- Produce a provenance manifest binding the chapter summary, Agent 1 source,
  Agent 3 review, Agent 2 Lean files, LaTeX template dependencies, generated
  TeX, and compiled PDF by SHA-256.

### Output contract

Write one self-contained publication directory:

```text
outputs/publication/<book-or-chapter>/
  book.tex
  book.pdf
  manifest.json
  README.md
  elegantbook.cls
  License
  assets/
    cover.jpg
    logo-blue.png
  lean/
    <theorem-number>/
      Main.lean
      ... hash-bound helper modules
```

`book.pdf` is optional at generation time but must be present for a published
release. The build uses XeLaTeX through TeX Live. Publication cannot change an
Agent 3 verdict and never chooses a latest Agent 2 attempt merely because it is
newer.

## Shared State and Failure Policy

- Pipeline states are `extracted`, `formalizing`, `ready_for_review`,
  `accepted`, `accepted_declaration`, `needs_reformalization`, and
  `needs_reextraction`.
- Artifacts are append-only per attempt. Corrections create a new attempt directory rather than overwriting evidence used by a prior review.
- Each handoff records input artifact hashes so the review verdict is tied to an exact source and Lean candidate.
- Network errors, API timeouts, and rate limits do not change mathematical status; they leave the item retryable in `formalizing`.
- OCR uncertainty below the eventual configured threshold is surfaced to Agent 3 and cannot be silently promoted to `accepted`.
- Agent 4 never receives `needs_reformalization` or `needs_reextraction`
  records; an incomplete chapter summary is a hard publication failure.

## Official Basis

- [Harmonic Aristotle](https://aristotle.harmonic.fun/) states that Aristotle can receive an English problem or work directly inside a Lean project.
- [aristotlelib 2.1.0](https://pypi.org/project/aristotlelib/2.1.0/) documents the `submit --project-dir` existing-project workflow used by Agent 2 preparation.
- [Aristotle technical report](https://harmonic.fun/pdf/Aristotle_IMO_Level_Automated_Theorem_Proving.pdf) treats a result as solved only when Lean 4 + Mathlib verifies a complete proof without gaps or unsound axioms such as `sorryAx`.
- [Aristotle API Terms](https://aristotle.harmonic.fun/terms) require users to independently review, test, and validate generated output.
