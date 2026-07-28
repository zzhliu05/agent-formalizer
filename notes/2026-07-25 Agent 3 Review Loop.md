---
type: implementation-note
status: active
process: P001
created: 2026-07-25
updated: 2026-07-25
---

# Agent 3 Independent Review and Revision Loop

Agent 3 is implemented under `code/agents/review/` as the independent
acceptance boundary in [[../docs/architecture/Four-Agent Pipeline]].

## Review design

Each review attempt has two isolated semantic stages:

1. Agent 3 independently builds the candidate, scans every Lean file for
   placeholders and new axiom/constant/opaque declarations, runs
   `#print axioms`, and asks the
   review model to reconstruct the theorem statement and proof from Lean only.
2. The frozen back-translation is written to disk before Agent 1's theorem
   package is opened. A second model call compares the statement and proof
   method with the source evidence.

Agent 2 prose and source-derived project files are excluded from the blind
stage. Deterministic Lean gates override model output. Acceptance requires:

- an independent Lean build;
- no `sorry`, `admit`, or `sorryAx` in any Lean source;
- no candidate-introduced `axiom`, `constant`, or `opaque`;
- no unapproved `#print axioms` dependency;
- exact statement agreement; and
- exact proof-method agreement with a source proof marked `complete`.

When the source proof is partial, omitted, by reference, or left to the reader,
the method comparison is not treated as knowable; the record is routed to
`needs_reextraction`.

## Revision ownership

A semantic or mechanical rejection produces a hash-bound
`revision_request.json`. Agent 3 sends that request to the existing Aristotle
project through `Project.ask` in instruction mode with questions disabled.
Agent 2 does not compose or send the follow-up. It validates the returned
archive as a new immutable generation attempt and reruns all of its protected
file, placeholder, declaration, and Lean build gates before Agent 3 receives a
new handoff.

The implemented state loop is:

```text
Agent 2 ready_for_review
  -> Agent 3 review
  -> Agent 3 revision request
  -> Aristotle follow-up
  -> Agent 2 validates a new generation attempt
  -> Agent 3 reviews the new handoff
```

The CLI also supports resuming an already-created follow-up task by task ID,
so a local timeout does not require a duplicate Aristotle submission.

## Automated verification

- Agent 2: 17 tests passed.
- Agent 3: 7 tests passed.
- The integration fixture exercises a mismatch, structured revision, Agent 2
  archive validation, new handoff, and an accepted second review.
- Both packages compile with `python -m compileall`.

## Live Folland 0.6 cycle

The existing first Agent 2 candidate for Folland Proposition 0.6 was reviewed
with the production Lean environment and review-model adapter.

The initial Agent 3 review found:

- the Lean statement matched;
- the independent build and placeholder/axiom gates passed;
- the proof used high-level Mathlib inverse-existence lemmas rather than the
  explicit constructions used by the printed proof; and
- the verdict was `needs_reformalization`.

Agent 3 issued a real Aristotle revision. Agent 2 stored the returned candidate
as generation `attempt-002`, validated it as `ready_for_review`, and emitted a
revision-provenance handoff. Agent 3 then performed a fresh blind review as
review `attempt-003`.

The second review found:

- independent mechanical audit: passed;
- prohibited placeholders: none;
- candidate-introduced axiom/constant/opaque declarations: none;
- observed axioms: only `Classical.choice`, `Quot.sound`, and `propext`;
- statement match: true;
- proof-method match: match; and
- final verdict: `accepted`.

The revision replaced the high-level inverse-lemma proof with the source's
explicit constructions: a default-backed piecewise preimage map in one
direction and a selected representative from each nonempty fiber in the
other.

Private test artifacts are under:

```text
outputs/private-tests/agent2-folland-batch/
  folland-real-analysis-2e-pages-19-27-p00020-0-6-proposition/
    formalization/generation/attempt-002/
    revision/attempt-001/
    review/attempt-003/
```

These artifacts remain ignored because they include copyrighted source
evidence. No API credential was persisted.

## Next

Run Agent 3 over the remaining canonical Agent 2 handoffs. Complete-source
records can enter the revision loop; partial, by-reference, and uncertain
records should be expected to route to Agent 1 when exact method comparison is
not supported by source evidence.
