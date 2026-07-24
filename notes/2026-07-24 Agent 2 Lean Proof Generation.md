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

## Credentialed live test

A real Aristotle run completed for the private Folland Proposition 0.16
preparation:

- Project ID: `9f3b7adc-8227-42df-a9d1-e53805c86e40`
- Task ID: `a942b5f0-7bd1-4f7b-9159-a05a8e4f4bf8`
- Remote status: `COMPLETE`
- Local state: `ready_for_review`
- Candidate theorem: `folland_real_analysis_0_16`
- Candidate `Main.lean` SHA-256:
  `c79c11d79d10685b32419ddbfaa42781c02c09d03260404c28ec3f6fecb986ae`
- Local Lean exit code: `0`
- Local Lean duration: `637.845` seconds

The first polling process encountered a network transport interruption while
the remote task was still active. The `resume` command recovered the exact same
Project/Task pair without another submission, then downloaded and validated the
result. This is a production demonstration of the recovery path covered by the
unit tests.

The returned theorem contains no executable `sorry`, `admit`, or `sorryAx`.
Protected preparation files remained byte-identical, and `handoff.json` assigns
semantic review and any questioning loop to Agent 3. The API key was removed
from the parent process and does not occur in the run artifacts.
