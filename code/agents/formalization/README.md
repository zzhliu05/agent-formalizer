# Agent 2 Lean Formalization

This directory is the local Lean 4 + Mathlib compilation environment for
Agent 2. It also contains the first implemented Aristotle integration stage:
strictly reading an Agent 1 theorem package and preparing a prompt plus a
minimal Lean project. Preparation is offline and does not submit a remote task.

## Read and prepare a theorem package

Restore the locked Python environment first:

```powershell
uv sync --locked
```

Validate an Agent 1 package without printing copyrighted source passages:

```powershell
uv run --locked formalization-agent inspect `
  "<theorem-root-or-theorem.json>"
```

Create an immutable Aristotle preparation bundle:

```powershell
uv run --locked formalization-agent prepare `
  "<theorem-root-or-theorem.json>"
```

The reader accepts `theorem.json`, `latest.json`, an extraction attempt
directory, or a theorem root containing `extraction/latest.json`. It verifies
the latest-pointer SHA-256, requires `context.md` and `source.txt`, and strictly
validates the Agent 1 schema. It rejects:

- incomplete theorem boundaries;
- definitions and axioms, which are not proof-bearing Agent 2 targets;
- `not_applicable` proof records;
- extraction uncertainties unless `--allow-uncertain` is supplied explicitly.

A partial, omitted, by-reference, or left-to-reader printed proof is allowed.
The generated prompt labels that status and instructs Aristotle to construct a
complete proof independently rather than inventing missing source text.

By default generated bundles are written beneath:

```text
outputs/pipeline/<theorem_id>/formalization/preparation/
  latest.json
  attempt-NNN/
    request.json
    prompt.txt
    project/
      Main.lean
      SOURCE_THEOREM.md
      FORMALIZATION_NOTES.md
      lean-toolchain
      lakefile.toml
      lake-manifest.json
```

`outputs/pipeline/` is ignored because source excerpts may be copyrighted. The
sanitized `request.json` stores input and artifact hashes, the pinned
`aristotlelib==2.1.0` interface, and the intended command shape, but never an
API key or provider request metadata from Agent 1.

The current preparation uses Aristotle's existing-project contract:

```powershell
$prompt = Get-Content -Raw "<attempt>\prompt.txt"
uv run --locked aristotle submit $prompt `
  --project-dir "<attempt>\project" `
  --wait
```

This command is documented for the next adapter stage; `prepare` does not run
it. Automatic submission, polling, download, local proof compilation, and
handoff to Agent 3 remain unimplemented.

## Project-isolated Aristotle CLI

The reproducible Agent 2 CLI is declared in `pyproject.toml`, pinned to
`aristotlelib==2.1.0`, and fully resolved in `uv.lock`. Create or restore the
ignored local `.venv` with:

```powershell
uv sync --locked
```

Run Aristotle through the locked project environment:

```powershell
uv run --locked aristotle --version
uv run --locked aristotle --help
```

Validated isolated installation:

- Package: `aristotlelib 2.1.0`
- Python: `.venv\Scripts\python.exe`
- Executable: `.venv\Scripts\aristotle.exe`
- Available commands: `submit`, `continue`, `formalize`, `download`, `list`,
  `show`, `tasks`, and `cancel`

From another directory, identify this project explicitly:

```powershell
uv run --project "C:\Users\liuzi\Documents\agent formalizer\code\agents\formalization" --locked aristotle --version
```

Authentication is intentionally not stored in this repository. Supply the
credential at runtime through the `ARISTOTLE_API_KEY` environment variable.
Avoid the CLI `--api-key` option because command-line arguments may be recorded
in shell history or process logs.

An authenticated, read-only `uv run --locked aristotle list` smoke test passed
on 2026-07-24. This validates the project-isolated CLI, account credential, and
basic service connectivity without submitting a proof task. No credential was
persisted.

### Optional global installation

The screenshot-recommended global installation is also available as a manual
fallback:

```powershell
uv tool install aristotlelib
aristotle --version
```

It currently resolves to
`C:\Users\liuzi\.local\bin\aristotle.exe`. Agent 2 automation must use the
project-isolated `uv run --locked aristotle` form instead.

## Pinned versions

- Lean: `leanprover/lean4:v4.28.0`
- Mathlib: `v4.28.0`

The project-local `lean-toolchain` selects Lean 4.28.0 without changing the
user's global Elan default.

## Verify

Run these commands from this directory:

```powershell
lake exe cache get
lake build
```

On the current Windows machine, the default cache directory on drive `C:` did
not have enough temporary space for the full Mathlib cache operation. The
successful setup redirected only the reusable download cache to drive `E:`
without moving the Git repository:

```powershell
$env:MATHLIB_CACHE_DIR = "E:\lean-cache\mathlib-v4.28.0"
lake exe cache get
lake build
```

This environment variable is process-local unless the user chooses to persist
it. Lake build outputs remain under the ignored `.lake/` directory in this
project.

`FormalizationAgent.lean` contains a minimal, narrowly imported Mathlib smoke
test only. Agent 2 should prefer the smallest practical Mathlib imports rather
than loading the aggregate `Mathlib` module. Formalized theorems should later
be generated as traceable pipeline artifacts under
`outputs/pipeline/<theorem_id>/formalization/`.
