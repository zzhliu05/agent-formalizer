---
type: note
status: active
created: 2026-07-24
updated: 2026-07-24
---

# Agent 1 Test Corpus Formalization Batch

Process: P001

This note records the deduplicated scope and execution status for formalizing
all current Agent 1 test data that is suitable for proof generation. It links
to [[../docs/architecture/Three-Agent Pipeline]] and follows the Agent 2
boundary documented in [[2026-07-24 Agent 2 Lean Proof Generation]].

## Corpus Inventory

Three private output families exist:

| Output family | Latest records | Interpretation | Batch decision |
| --- | ---: | --- | --- |
| `outputs/private-tests/folland/` | 30 | Early Gemini joint OCR/extraction candidates for labels 0.4–0.13; each label appears in three runs, and none contains a proof sketch. | Superseded evaluation data; do not submit as proof tasks. |
| `outputs/private-tests/folland-gpt55-large/theorems/` | 13 | Earlier GPT-5.5 packages for labels 0.4–0.16. Their package hashes differ from the later extraction run. | Superseded by the later complete-range run. |
| `outputs/private-tests/folland-gpt55-large/theorem-extraction/` | 21 | Later GPT-5.5 packages covering the continuous range 0.4–0.24. All `latest.json` hashes validate. | Canonical batch input. |

The canonical 21-record set contains:

- 16 records marked `complete` by Agent 1, including the source-level Axiom of
  Choice;
- three `partial` proofs: 0.7, 0.10, and 0.16;
- two proofs by reference: 0.13 and 0.14;
- three records with explicit extraction uncertainties: 0.10, 0.23, and 0.24;
- no incomplete chunk-boundary records and no nonempty boundary notes.

Agent 2 treats 0.4 as a declaration-only source axiom. It must not invent a
proof or add a new Lean axiom merely to make the batch appear complete.
Consequently the proof-generation scope is 20 records: 15 complete,
three partial, and two by reference.

## Preparation

All 20 proof targets passed immutable package and hash validation and produced
an Agent 2 `attempt-001` preparation under:

`outputs/private-tests/agent2-folland-batch/`

The preparation policy explicitly allows the three recorded uncertainties.
Those uncertainties remain in the source bundle and Aristotle prompt; this is
an execution permission, not an assertion that the source is semantically
unambiguous.

## Live Aristotle Batch

All submissions use the project-isolated `aristotlelib 2.1.0` runtime,
questions disabled, and a process-only `ARISTOTLE_API_KEY`. Runtime artifacts
and logs remain ignored private outputs.

All 20 proof targets reached `ready_for_review`. The final mechanical gates
were:

1. safe archive extraction;
2. protected source and toolchain files unchanged;
3. no `sorry`, `admit`, or `sorryAx`;
4. a locally passing Lean 4.28.0 kernel check;
5. a `ready_for_review` handoff to Agent 3.

The initial submission wave reached the account's concurrent-project limit.
Labels 0.20, 0.21, and 0.22 required later immutable attempts; 0.20 also had
one deliberately early retry rejected before a remote ID was assigned. Label
0.8 recovered a transport error using the same Project and Task IDs.

Eleven candidates initially entered Lean validation at once. Because each
process grew to roughly 1.7 GB after loading Mathlib, eight local processes
were deliberately interrupted to avoid exhausting physical memory. Agent 2
therefore gained a `revalidate` command that verifies the saved archive and
repeats only the local gates without making another Aristotle submission.
All eight interrupted candidates passed controlled two-at-a-time
revalidation. The implementation has 16 passing unit tests.

## Final Record Status

| Label | Agent 1 source status | Agent 2 status | Generation attempt | Execution note |
| --- | --- | --- | ---: | --- |
| 0.4 | axiom | `declaration_only` | — | Not submitted as a proof target. |
| 0.5 | complete | `ready_for_review` | 1 | Passed directly. |
| 0.6 | complete | `ready_for_review` | 1 | Passed directly. |
| 0.7 | partial | `ready_for_review` | 1 | Local revalidation passed. |
| 0.8 | complete | `ready_for_review` | 1 | Transport recovery passed. |
| 0.9 | complete | `ready_for_review` | 1 | Passed directly. |
| 0.10 | partial; uncertain | `ready_for_review` | 1 | Local revalidation passed. |
| 0.11 | complete | `ready_for_review` | 1 | Passed directly. |
| 0.12 | complete | `ready_for_review` | 1 | Local revalidation passed. |
| 0.13 | by reference | `ready_for_review` | 1 | Local revalidation passed. |
| 0.14 | by reference | `ready_for_review` | 1 | Local revalidation passed. |
| 0.15 | complete | `ready_for_review` | 1 | Local revalidation passed. |
| 0.16 | partial | `ready_for_review` | 1 | Passed directly after resume. |
| 0.17 | complete | `ready_for_review` | 1 | Local revalidation passed. |
| 0.18 | complete | `ready_for_review` | 1 | Passed directly after resume. |
| 0.19 | complete | `ready_for_review` | 1 | Passed directly after resume. |
| 0.20 | complete | `ready_for_review` | 3 | Two capacity-limited attempts preceded the accepted task. |
| 0.21 | complete | `ready_for_review` | 2 | One capacity-limited attempt preceded the accepted task. |
| 0.22 | complete | `ready_for_review` | 2 | One capacity-limited attempt preceded the accepted task. |
| 0.23 | complete; uncertain | `ready_for_review` | 1 | Local revalidation passed. |
| 0.24 | complete; uncertain | `ready_for_review` | 1 | Passed directly after resume. |

The final cross-stage audit found zero failures across the canonical Agent 1
hash, preparation request, generation latest pointer, run record, handoff,
current Lean-file hashes, and successful build log for all 20 proof targets.
A repository scan also found no persisted Aristotle credential.

No candidate is accepted as mathematically faithful until Agent 3
back-translates the Lean statement, compares it with the canonical Agent 1
record, and independently inspects the declaration's axioms.

## Next

Run Agent 3 over all 20 handoffs. Give extra attention to the three uncertain
source records, the three partial proofs, the two proofs by reference, and any
Lean declaration whose statement depends on a non-obvious Mathlib encoding.
Decide separately how the source-level Axiom of Choice should be represented;
do not turn it into an unreviewed project axiom.
