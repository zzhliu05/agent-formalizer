# Agent 3 Independent Review

Agent 3 is the acceptance authority for Lean candidates. It performs an
independent mechanical audit, freezes a natural-language reconstruction made
from Lean alone, and only then opens Agent 1's source package to compare the
formal statement and proof method.

## Isolation boundary

The first model call receives only:

- the candidate `.lean` files;
- discovered Lean declaration names;
- the output of an independent `#print axioms` audit.

It does not receive the source theorem, source proof, Agent 2 notes,
`SOURCE_THEOREM.md`, or `FORMALIZATION_NOTES.md`. The resulting
`blind/backtranslation.json` is persisted before the source package is read.
The second model call compares that frozen reconstruction with Agent 1's
verbatim statement, printed proof steps, context, proof-completeness status,
and recorded uncertainties.

An `accepted` verdict requires every statement check to pass, a complete
printed source proof, and an exact proof-method match. A partial, omitted,
by-reference, or left-to-reader source proof is routed to
`needs_reextraction`, because exact method agreement cannot be established
from missing evidence.

## Mechanical gates

Agent 3 independently:

- compiles the candidate using the pinned Lean 4.28.0 environment;
- scans every submitted Lean source for executable `sorry`, `admit`, and
  `sorryAx`;
- rejects candidate-introduced `axiom`, `constant`, and `opaque` declarations;
- runs `#print axioms` for every theorem/lemma declaration;
- rejects `sorryAx` and dependencies outside the approved Lean/Mathlib
  baseline (`propext`, `Classical.choice`, and `Quot.sound`).

These deterministic gates override any model-generated semantic verdict.

## Install

From this directory:

```powershell
uv sync --locked
```

Credentials are process-only. Do not place either key in a command-line
argument or repository file:

```powershell
$env:REVIEW_MODEL_API_KEY = "<comparison-model-key>"
$env:ARISTOTLE_API_KEY = "<aristotle-key>"
```

`REVIEW_MODEL_ENDPOINT` may override the default OpenAI-compatible review
endpoint. No key, source passage, or candidate proof is written to Git.

## Run one review

```powershell
uv run --locked review-agent review `
  "<agent2-handoff.json>" `
  "<agent1-theorem-root>"
```

The command returns exit code `0` only for `accepted`; a completed non-accepted
review returns `3`, and an execution failure returns `2`.

## Run the Agent 2/Agent 3 loop

```powershell
uv run --locked review-agent loop `
  "<agent2-handoff.json>" `
  "<agent1-theorem-root>" `
  --max-revisions 3
```

For each `needs_reformalization` verdict, Agent 3 writes a structured
`revision_request.json`, calls `Project.ask` in `INSTRUCT` mode against the
existing Aristotle project, and disables agent questions. The returned archive
does not go directly back to Agent 3: Agent 2 first creates a new immutable
generation attempt and repeats protected-file, placeholder, declaration, and
Lean build validation. Agent 3 then reviews the new handoff from scratch.

The loop stops on:

- `accepted`;
- `needs_reextraction`;
- an Agent 2 validation failure; or
- the configured revision limit.

If a local process is interrupted after a follow-up task was submitted, resume
that task without resubmission and immediately run the next review:

```powershell
uv run --locked review-agent continue `
  "<previous-agent2-handoff.json>" `
  "<agent1-theorem-root>" `
  "<revision_request.json>" `
  --task-id "<existing-aristotle-task-id>"
```

## Artifacts

Review attempts are append-only:

```text
outputs/pipeline/<theorem_id>/review/
  latest.json
  attempt-NNN/
    review.json
    review.md
    revision_request.json        # only for needs_reformalization
    mechanical/
      audit.json
      build.log
      axiom-audit.log
    blind/
      lean-input.json
      backtranslation.json
    comparison/
      comparison.json
```

Revision transport evidence is stored separately under
`outputs/pipeline/<theorem_id>/revision/attempt-NNN/`. Revised Lean output is
stored as a new Agent 2 generation attempt, never over a previous candidate.

## Verify

```powershell
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -m compileall -q src
uv run --locked review-agent --help
```
