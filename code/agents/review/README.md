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

Declaration discovery preserves nested Lean namespaces so every appended
`#print axioms` command resolves the same declaration that compiled in the
candidate, rather than producing a false unknown-identifier rejection.

It does not receive the source theorem, source proof, Agent 2 notes,
`SOURCE_THEOREM.md`, or `FORMALIZATION_NOTES.md`. The resulting
`blind/backtranslation.json` is persisted before the source package is read.
The second model call compares that frozen reconstruction with Agent 1's
verbatim statement, printed proof steps, context, proof-completeness status,
and recorded uncertainties.

An `accepted` verdict requires every statement check to pass and exact
proof-method agreement at the level supported by the printed source. A
`partial` or `left_to_reader` record can pass only when it explicitly preserves
the high-level method and Lean merely fills identified local omissions. A
`by_reference` record can pass only when Lean uses that same cited result or
its established formal counterpart. Missing usable method evidence remains
`needs_reextraction`.

A source axiom/principle with `not_applicable` proof status uses a separate
`accepted_declaration` terminal verdict: the statement and every mechanical
gate pass, but no source proof-method agreement is claimed.

## Mechanical gates

Agent 3 independently, in one combined kernel invocation:

- compiles the candidate using the pinned Lean 4.28.0 environment;
- compiles local imported modules into an isolated temporary `.olean` tree
  before checking the target, so multi-file candidates traverse the same
  independent gate without relying on Agent 2 build products;
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

The command returns exit code `0` for `accepted` or
`accepted_declaration`; a completed non-accepted review returns `3`, and an
execution failure returns `2`.

## Run the Agent 2/Agent 3 loop

```powershell
uv run --locked review-agent loop `
  "<agent2-handoff.json>" `
  "<agent1-theorem-root>" `
  --max-revisions 3 `
  --max-agent2-repairs-per-revision 3
```

For each `needs_reformalization` verdict, Agent 3 writes a structured
`revision_request.json`, calls `Project.ask` in `INSTRUCT` mode against the
existing Aristotle project, and disables agent questions. The returned archive
does not go directly back to Agent 3: Agent 2 first creates a new immutable
generation attempt and repeats protected-file, placeholder, declaration, and
Lean build validation. Agent 3 then reviews the new handoff from scratch.

If that Agent 2 validation returns `validation_failed`, the loop no longer
stops immediately. It freezes the failure message and the tail of `build.log`
into a new `validation-repair-NNN.json`, points the request at the rejected
Aristotle Task checkpoint, and automatically issues another in-project
follow-up. The repaired archive traverses the complete Agent 2 validation
boundary again. Byte-identical failed Lean checkpoints are detected and called
out explicitly in the next prompt. This inner repair loop is bounded by
`--max-agent2-repairs-per-revision`; those repairs do not consume the separate
Agent 3 semantic-revision allowance.

The loop stops on:

- `accepted`;
- `accepted_declaration`;
- `needs_reextraction`;
- the configured semantic-revision limit;
- the configured Agent 2 validation-repair limit; or
- a non-recoverable transport or integrity error.

If a local process is interrupted after a follow-up task was submitted, resume
that task without resubmission and immediately run the next review:

```powershell
uv run --locked review-agent continue `
  "<previous-agent2-handoff.json>" `
  "<agent1-theorem-root>" `
  "<revision_request.json>" `
  --task-id "<existing-aristotle-task-id>" `
  --max-agent2-repairs 3
```

An Aristotle follow-up can occasionally finish as `COMPLETE_WITH_ERRORS`, or
reach `OUT_OF_BUDGET` after leaving a useful incremental checkpoint. Agent 3
may recover either state only when the task advertises an output archive.
Recovery is not acceptance: the archive must still pass the complete Agent 2
protected-file, placeholder, declaration, and Lean build gates before a fresh
Agent 3 review. A further repair may continue from a locally rejected
placeholder-bearing checkpoint only when its project/task lineage traces back
to the reviewed candidate; the next archive still traverses every Agent 2 and
Agent 3 gate. The `continue` command also runs the automatic Agent 2
validation-repair loop after the resumed Task finishes. Terminal states without
a downloadable archive are rejected.

## Run a chapter to terminal review

```powershell
uv run --locked review-agent chapter `
  "<chapter-agent2-output-root>" `
  "<chapter-agent1-source-root>" `
  --max-revisions-per-theorem 8 `
  --max-agent2-repairs-per-revision 3
```

The chapter runner sorts numbered theorem IDs, reuses an accepted verdict only
when it is tied to the exact latest Agent 2 handoff, and persists
`_chapter_review/chapter-summary.json` after every terminal theorem. A
`needs_reformalization` result remains inside the Agent 3 → Aristotle → Agent 2
validation → Agent 3 loop until acceptance or the explicit per-theorem revision
limit. Source-evidence failures remain visible rather than being silently
weakened.

Agent 2 writes `gen/latest-ready.json` whenever a generation reaches
`ready_for_review`. If a newer generation fails validation, the chapter runner
uses that pointer, or safely scans backward for the most recent ready handoff,
rather than treating the failed latest attempt as if all prior valid evidence
had disappeared.

## Artifacts

Review attempts are append-only:

```text
outputs/pipeline/t-<16-hex>/review/
  latest.json
  attempt-NNN/
    review.json
    review.md
    revision_request.json        # only for needs_reformalization
    validation-repair-NNN.json   # only after Agent 2 validation_failed
    mechanical/
      audit.json
      build-and-axiom-audit.log
      lean-audit/
    blind/
      lean-input.json
      backtranslation.json
    comparison/
      comparison.json
```

Revision transport evidence is stored separately under
`outputs/pipeline/t-<16-hex>/revision/attempt-NNN/`. Revised Lean output is
stored under `gen/NNN/` as a new Agent 2 generation attempt, never over a
previous candidate. Agent 3 discovers the complete theorem ID through the
Agent 2 metadata and handoff, and remains compatible with legacy long-form
theorem directories.

## Verify

```powershell
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -m compileall -q src
uv run --locked review-agent --help
```
