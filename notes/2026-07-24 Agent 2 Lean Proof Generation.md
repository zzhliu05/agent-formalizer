---
type: implementation-note
status: active
created: 2026-07-24
process: P001
---

# Agent 2 Lean Proof Generation

Agent 2 now implements the full first-candidate generation boundary after
offline preparation.

## Aristotle contract

The adapter uses pinned `aristotlelib 2.1.0` and
`Project.create_from_directory`. It explicitly supplies
`AgentQuestionsSetting.DISABLED`, then polls the returned task through SDK
status reads. It does not use the CLI `submit --wait` helper because that helper
enables a 15-minute interactive question mode. It never calls `Project.ask`,
answers an Aristotle question, or invokes `aristotle continue`.

If local polling expires while the task is still remote-running, `run.json`
retains the project and task IDs. The `resume` command continues the same task
without consuming another submission.

## Mechanical validation

After a terminal `COMPLETE` status, Agent 2:

- downloads the result archive and records its SHA-256;
- rejects archive links, devices, duplicate paths, path traversal, excessive
  entry counts, and excessive expanded size;
- confirms `SOURCE_THEOREM.md`, `lean-toolchain`, `lakefile.toml`, and
  `lake-manifest.json` remain byte-identical to the preparation package;
- rejects an unchanged staging `Main.lean`;
- scans executable Lean text, while ignoring comments and strings, for
  `sorry`, `admit`, and `sorryAx`;
- requires a theorem or lemma declaration;
- elaborates the candidate in the pinned Lean 4.28.0 / Mathlib v4.28.0
  environment and saves `build.log`.

Only a fully passing result receives `handoff.json` and the state
`ready_for_review`. The handoff assigns semantic review and the complete
questioning/revision loop to Agent 3.

## Verification

The combined Agent 2 suite now contains 15 passing tests. The new tests cover:

- preparation artifact tampering;
- disabled Aristotle questions at the SDK call boundary;
- malicious archive path rejection;
- Lean comment/string-aware placeholder scanning;
- protected-file mutation rejection;
- non-interactive submission, polling, download, validation, and Agent 3
  handoff;
- timeout and resume without a duplicate remote submission.

The production local Lean checker was also run against the private Folland
`attempt-004` staging project. It loaded the pinned Lake environment and
returned exit code zero without timeout. This validates the real subprocess
and environment wiring rather than only the mocked build runner.

## Live-test status

The current Codex process does not contain `ARISTOTLE_API_KEY`. The production
`generate` command was verified to fail closed before creating a local
generation attempt or remote project. A credentialed live proof run remains
pending runtime key injection; no Aristotle proof quota was consumed during
this implementation.
