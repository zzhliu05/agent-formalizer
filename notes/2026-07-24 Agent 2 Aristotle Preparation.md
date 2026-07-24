---
type: implementation-note
status: resolved
created: 2026-07-24
process: P001
---

# Agent 2 Aristotle Preparation

Agent 2 now implements the offline boundary between an Agent 1 theorem package
and Harmonic Aristotle. It uses the `aristotlelib 2.1.0` existing-project
workflow: prepare a natural-language prompt and a pinned Lean project for the
later `submit --project-dir` call.

## Implemented

- Strict Pydantic models for the current Agent 1 `theorem.json` schema.
- Input resolution from `theorem.json`, `latest.json`, an extraction attempt,
  or a theorem root containing `extraction/latest.json`.
- SHA-256 verification of `theorem_json_sha256` in the immutable latest
  pointer.
- Required nonempty `context.md` and `source.txt` companion files.
- Safety rejection for incomplete theorem boundaries, definitions, axioms,
  non-proof targets, and extraction uncertainties without an explicit override.
- Explicit handling of partial or omitted printed proofs: Aristotle is asked to
  construct a complete proof independently and to record that provenance.
- Immutable `attempt-NNN` preparation bundles with a sanitized `request.json`,
  `prompt.txt`, source/context project document, notes template, and Lean
  4.28.0 / Mathlib v4.28.0 files.
- No network submission and no credential access in the preparation command.

## Verification

Eight unit tests cover valid package loading, immutable pointers, tamper
detection, schema drift, missing companions, omitted proofs, uncertainty
override, and non-proof/incomplete target rejection.

A real private Folland extraction package was read through its theorem root and
prepared successfully without printing or committing its source text:

```text
outputs/private-tests/agent2-preparation/
  folland-real-analysis-2e-pages-19-27-p00022-0-16-proposition/
    formalization/preparation/attempt-002/
```

The selected record is a proposition with a partial printed proof, one context
item, two extracted proof steps, zero recorded uncertainties, and a complete
statement boundary. The resulting `request.json` records `submitted: false` at
the CLI boundary; no Aristotle proof task or quota was consumed.

## Resolution

Remote submission, non-interactive polling, result validation, and Agent 3
handoff are implemented in [[2026-07-24 Agent 2 Lean Proof Generation]]. This
note remains the durable record for the earlier offline-preparation milestone.
