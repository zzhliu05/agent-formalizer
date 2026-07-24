# Formalization Agent Instructions

This directory belongs to Agent 2 of [[docs/architecture/Three-Agent Pipeline]].

## Mission

Translate a complete extraction package into Lean 4 + Mathlib and use the Harmonic Aristotle API adapter to obtain or complete a machine-checkable proof.

## Rules

- Record all material choices made while mapping textbook concepts to Mathlib.
- Keep API credentials outside the repository and sanitize saved request metadata.
- Provide Aristotle credentials through the `ARISTOTLE_API_KEY` process
  environment. Do not use the CLI `--api-key` option because command lines may
  be retained in shell history or process logs.
- Invoke Aristotle for project work as `uv run --locked aristotle ...` from
  this directory, or with an explicit `--project` path. Do not depend on the
  globally installed CLI for reproducible Agent 2 runs.
- Use the current official Aristotle API contract; do not invent endpoints or fields.
- Submit new projects with Aristotle agent questions disabled. Agent 2 must not
  call `Project.ask`, `aristotle continue`, answer an agent question, or start
  an autonomous follow-up loop. Agent 3 owns all semantic questioning and
  revision prompts after the first candidate handoff.
- Compile locally before handoff.
- Temporary placeholders are permitted only during work; they disqualify the review bundle.
- Do not mark a theorem accepted. Only Agent 3 may do so.
