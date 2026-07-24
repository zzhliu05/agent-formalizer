---
type: note
status: validated
created: 2026-07-24
updated: 2026-07-24
process: P001
---

# Aristotle Authentication Smoke Test

## Result

The project-isolated Aristotle CLI successfully completed an authenticated,
read-only project-list request:

```powershell
uv run --locked aristotle list
```

The command returned the account's existing project table and exited with code
zero. This validates:

- resolution through the Agent 2 `.venv` and `uv.lock`;
- acceptance of the supplied Aristotle API credential;
- network access to the Aristotle service;
- basic account-level read access.

No proof task was submitted, continued, cancelled, or downloaded.

## Credential handling

The credential was injected only into the child process environment. Command
output was filtered, the environment variable disappeared with the process,
and the Windows clipboard was overwritten after the test. No credential value
was written to the repository, notes, shell command arguments, or output
artifacts.

## Remaining validation

The next bounded test should submit one small theorem fixture, wait for
completion, save the returned archive under a Git-ignored private-test
directory, compile the returned Lean source with the pinned Lean 4.28.0 +
Mathlib v4.28.0 environment, and scan it for `sorry`, `admit`, and `sorryAx`.

Related: [[2026-07-24 Project-Isolated Aristotle CLI]] -
[[../code/agents/formalization/README]] -
[[../docs/architecture/Three-Agent Pipeline]]
