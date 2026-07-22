# Formalization Agent Instructions

This directory belongs to Agent 2 of [[docs/architecture/Three-Agent Pipeline]].

## Mission

Translate a complete extraction package into Lean 4 + Mathlib and use the Harmonic Aristotle API adapter to obtain or complete a machine-checkable proof.

## Rules

- Record all material choices made while mapping textbook concepts to Mathlib.
- Keep API credentials outside the repository and sanitize saved request metadata.
- Use the current official Aristotle API contract; do not invent endpoints or fields.
- Compile locally before handoff.
- Temporary placeholders are permitted only during work; they disqualify the review bundle.
- Do not mark a theorem accepted. Only Agent 3 may do so.
