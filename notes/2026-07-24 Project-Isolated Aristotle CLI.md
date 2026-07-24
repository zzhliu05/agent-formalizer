---
type: note
status: validated
created: 2026-07-24
updated: 2026-07-24
process: P001
---

# Project-Isolated Aristotle CLI

## Result

Agent 2 now carries a reproducible Aristotle CLI dependency inside
`code/agents/formalization/`:

- `pyproject.toml` declares `aristotlelib==2.1.0`;
- `uv.lock` records the complete resolved dependency graph;
- `uv sync --locked` creates an ignored `.venv`;
- `uv run --locked aristotle ...` is the required Agent 2 invocation.

The globally installed CLI remains available for manual use, but it is no
longer a dependency of reproducible project runs.

## Validation

The isolated environment was created with CPython 3.13.5. The following all
resolved inside the project `.venv` and completed successfully:

```powershell
uv run --locked aristotle --version
uv run --locked aristotle --help
uv run --locked python -c "import importlib.metadata; print(importlib.metadata.version('aristotlelib'))"
```

Observed local paths:

- Python:
  `code/agents/formalization/.venv/Scripts/python.exe`
- Aristotle:
  `code/agents/formalization/.venv/Scripts/aristotle.exe`

The `.venv` directory is locally generated and Git-ignored. Only
`pyproject.toml` and `uv.lock` are durable project inputs.

## Authentication boundary

No Aristotle API key was present and no authenticated request was made.
`ARISTOTLE_API_KEY` remains the only approved credential input for project
runs. The CLI `--api-key` option is prohibited for Agent 2 automation because
process arguments may be retained.

Related: [[2026-07-24 Aristotle CLI Setup]] -
[[2026-07-24 Agent 2 Lean Environment Setup]] -
[[../code/agents/formalization/README]]
