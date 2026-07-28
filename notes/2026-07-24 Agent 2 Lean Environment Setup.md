---
type: note
status: validated
created: 2026-07-24
updated: 2026-07-24
process: P001
---

# Agent 2 Lean Environment Setup

## Result

The local Lean environment for Agent 2 is configured and validated under
`code/agents/formalization/`.

- Lean is pinned by `lean-toolchain` to `leanprover/lean4:v4.28.0`.
- Mathlib is pinned by `lakefile.toml` to tag `v4.28.0`.
- `lake-manifest.json` resolves Mathlib to commit
  `8f9d9cff6bd728b17a24e163c9402775d9e6a365`.
- `lake exe cache get` completed for all 8,010 requested cache files.
- `lake build` completed successfully with 504 jobs.
- The smoke source imports `Mathlib.Data.Nat.Prime.Defs` and checks
  `Nat.prime_two`; it is not a textbook formalization artifact.

## Local Windows observations

The first dependency update was interrupted with an incomplete ProofWidgets Git
checkout. The generated package cache was moved into the ignored
`tmp/quarantine/` area, after which Lake cloned the dependency cleanly.

ProofWidgets cloud-release extraction then failed because Windows `tar` emitted
non-UTF-8 verbose output. A temporary ignored wrapper suppressed only the
verbose flag while delegating extraction to the system `tar`; the release
target then completed successfully.

The first Mathlib cache attempt exhausted temporary space in the default
`C:\Users\<user>\.cache\mathlib` location. The successful retry set
`MATHLIB_CACHE_DIR=E:\lean-cache\mathlib-v4.28.0` for that process. The Git
repository stayed in its original location.

An initial aggregate `import Mathlib` smoke test took more than ten minutes.
Replacing it with the smallest relevant Mathlib import produced a successful
build in under one minute. Agent 2 should therefore generate narrow imports
whenever practical.

## Scope

This milestone configures only the Lean 4 + Mathlib environment. It does not yet
implement Harmonic Aristotle authentication, task submission, polling,
artifact generation, or theorem-package translation.

Related: [[../docs/architecture/Four-Agent Pipeline]] -
[[../code/agents/formalization/README]]
