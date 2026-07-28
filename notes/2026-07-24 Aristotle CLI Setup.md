---
type: note
status: validated
created: 2026-07-24
updated: 2026-07-24
process: P001
---

# Aristotle CLI Setup

## Result

The recommended `uv` installation path from the Aristotle setup instructions
was applied successfully:

```powershell
uv tool install aristotlelib
```

The local tool installation resolves to:

- `uv 0.11.21`
- `aristotlelib 2.1.0`
- executable `C:\Users\liuzi\.local\bin\aristotle.exe`

Both `aristotle --help` and `aristotle --version` completed successfully from
the Agent 2 Lean project directory.

## Installed CLI contract

The installed CLI exposes `submit`, `continue`, `formalize`, `download`,
`list`, `show`, `tasks`, and `cancel`.

For future Agent 2 work:

- `aristotle formalize <input_file>` formalizes a file;
- `aristotle submit <prompt> --project-dir <directory>` submits a project and
  supporting files;
- `--wait` waits for completion;
- `--destination <path>` saves the result archive when waiting.

These fields were taken directly from the installed CLI help rather than
inferred.

## Authentication boundary

`ARISTOTLE_API_KEY` was not present during installation and no authenticated
request was attempted. Credentials must be injected into the process
environment or an external secret store. They must not be placed in Git,
Markdown notes, saved prompts, or CLI `--api-key` arguments.

## Scope

This milestone installs and validates the command-line client only. It does not
yet prove account authentication, service availability, quota, task submission,
polling, result download, or local compilation of an Aristotle result.

Related: [[2026-07-24 Project-Isolated Aristotle CLI]] -
[[../code/agents/formalization/README]] -
[[2026-07-24 Agent 2 Lean Environment Setup]] -
[[../docs/architecture/Four-Agent Pipeline]]
