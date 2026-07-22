---
type: project-state
status: stable
created: 2026-07-22
updated: 2026-07-22
---

# 2026-07-22 Initial Vault State

This note records the initial vault system state for 多 Agent 形式化数学教材.

## Initial State Intent

- Preserve the initial vault scaffold and agent behavior as a known-good system state.
- Keep this state available as a comparison and recovery reference while project work begins.
- Avoid changing the vault system accidentally while sources, notes, code experiments, outputs, and figures accumulate.

## Project Context

- Purpose: 构建将数学材料转化为可教学、可追踪、可由 Lean 检验内容的完整多 Agent 形式化流程
- Domain: 形式化数学、多智能体协作、自动定理证明与教材工程
- User background and preferred stance: 面向具备大学数学或软件工程基础、但不要求已有 Lean 经验的数学与工程协作者
- Vault balance: 工程与代码优先，同时保留研究和写作区域
- Explanation style: 数学直觉 → 明确规格 → Agent 输入输出 → Lean 验证

## Tracked System Components

- `AGENTS.md`: project-local operating rules, vault retrieval policy, Obsidian conventions, human-readable naming guidance, workflow policies, and integrity rules.
- `.codex/hooks.json`: project-local `UserPromptSubmit` hook configuration.
- `.codex/hooks/vault_context_reminder.py`: hook script that injects the vault context reminder.
- `hooks/user-prompt-submit-reminder.txt`: hook payload.
- `wiki/index.md`: navigational map for the vault.
- `wiki/process-log.md`: newest-first agent memory and current project history.
- `raw/`, `wiki/topics/`, `wiki/concepts/`, `wiki/methods/`, `wiki/papers/`, `notes/`, `code/`, `outputs/`, and `figures/`: scaffold folders.

## Hook Behavior

The project-local hook should emit a compact `UserPromptSubmit` reminder inside this project and emit nothing outside it. Codex may ask the user to trust the project-local hook.

## How To Use This Initial State

- Use this note as a human-readable reference for the original scaffold.
- If the user later chooses git baseline pinning, record the branch or tag names here after they are created.
- Do not treat this note as evidence that git pinning has already happened.
