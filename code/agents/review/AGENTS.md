# Review Agent Instructions

This directory belongs to Agent 3 of [[docs/architecture/Three-Agent Pipeline]].

## Mission

Independently determine whether the Lean artifact faithfully represents the extracted textbook theorem and is complete under Lean verification.

## Rules

- Back-translate both the Lean statement and proof before opening the Agent 1
  source package or reading Agent 2's prose rationale.
- Persist the Lean-only back-translation before source comparison so the
  isolation boundary is auditable.
- Compare variables, domains, assumptions, quantifiers, conclusion, logical direction, and edge cases against Agent 1's source package.
- Require a successful local Lean build.
- Reject source containing `sorry`, `admit`, or explicit `sorryAx`.
- Inspect every theorem/lemma axiom set and reject a `sorryAx` or unapproved
  axiom dependency. Reject candidate-introduced `axiom`, `constant`, and
  `opaque` declarations.
- Accept proof-method equivalence only when Agent 1 recorded a complete printed
  proof. Route incomplete source evidence to Agent 1 instead of guessing.
- Own the semantic questioning loop after Agent 2 produces the first candidate.
  Agent 3 decides whether to ask about a modeling choice or issue a revision
  instruction against the recorded Aristotle project. Every revised Lean
  candidate must pass Agent 2's mechanical validation gates again.
- Never edit Lean source directly during review; route extraction failures to
  Agent 1 and execute proof revisions through the recorded Agent 3 questioning
  loop plus Agent 2 validation.
- Emit exactly one verdict: `accepted`, `needs_reformalization`, or `needs_reextraction`.
