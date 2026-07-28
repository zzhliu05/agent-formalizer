---
type: source
status: active
created: 2026-07-28
updated: 2026-07-28
process: P002
arxiv: "2205.11491v1"
doi: "10.48550/arXiv.2205.11491"
---

# HyperTree Proof Search for Neural Theorem Proving

Source: [Lample et al., “HyperTree Proof Search for Neural Theorem Proving,” arXiv:2205.11491v1](https://arxiv.org/abs/2205.11491)

Local source: [[../../raw/papers/2205.11491v1 HyperTree Proof Search for Neural Theorem Proving.pdf]]

PDF SHA-256: `9DEFF4B44772A176314016CE0B277CAC20649F2ED8784031F34A6B29BB64FA48`

Authors: Guillaume Lample, Marie-Anne Lachaux, Thibaut Lavril, Xavier Martinet, Amaury Hayat, Gabriel Ebner, Aurélien Rodriguez, and Timothée Lacroix.

Version: v1, 2022-05-23. Categories: `cs.CL`, `cs.AI`. License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Paper Summary

The paper introduces HyperTree Proof Search (HTPS), an AlphaZero-inspired search procedure for neural automated theorem proving, together with an online training system. It evaluates the approach in Metamath, Lean, and a synthetic Equations environment.

Interactive theorem proving naturally produces a hypergraph rather than an ordinary game tree: one tactic is an edge from a goal to a set of subgoals, and that tactic succeeds only if every subgoal is proved. HTPS therefore selects and expands a partial proof hypertree whose leaves are multiple unexpanded goals. Its repeated cycle is:

1. **Selection:** combine a tactic policy, visit counts, and critic values to choose a promising partial proof hypertree.
2. **Expansion:** sample tactics for the selected unexpanded leaves and execute them in the formal environment.
3. **Back-propagation:** propagate leaf evaluations through the hypertree and update visit counts and action values.

The implementation uses virtual loss to batch several distinct selections, a policy model to generate tactics, and a critic to estimate whether goals are provable. Lean states require extra care because metavariables can couple subgoals; the system splits tactic states only where dependencies permit and relies on Lean kernel checks after tactic application.

The online training architecture runs provers and trainers asynchronously. Search traces yield minimal successful proof samples for the policy and soft value targets for the critic; failed and partially explored searches also provide learning signals. The paper's ablations argue that online model refresh, minimal-proof selection, soft critic targets, and stochastic search parameters materially affect performance.

The source reports improvements over prior systems on its Metamath, Lean miniF2F, and Equations evaluations. These are author-reported experimental results, not local reproductions.

## Relationship to Aristotle

[[Aristotle IMO-level Automated Theorem Proving]] cites HTPS as a direct antecedent for learned proof search over Lean states. The two papers share several structural ideas:

- proof construction is an AND/OR hypergraph problem rather than a single linear generation;
- model-guided search alternates formal execution with learned policy/value judgments;
- multiple subgoals produced by a tactic must all be discharged;
- search traces can be reused to improve subsequent attempts;
- the formal kernel, rather than the model, determines whether a candidate step is valid.

Aristotle extends this direction with Monte Carlo Graph Search, informal proof and lemma generation, iterative formalization feedback, test-time training, and a separate geometry subsystem.

## Relevance to P001

HTPS is most relevant to the internal behavior expected from an Agent 2 proof provider and to the recovery signals audited by Agent 3:

- **Artifact structure:** a proof attempt may contain useful solved subgoals even when the root theorem is not yet proved.
- **Failure is training evidence:** unsuccessful search should be preserved as structured diagnostic state, not collapsed into a generic error.
- **Subgoal dependencies matter:** Lean metavariables can make apparently separate goals inseparable, so orchestration must not assume naive parallel independence.
- **Kernel calls are the hard boundary:** policy and critic values prioritize work but cannot establish correctness.
- **Soft progress estimates are heuristic:** value estimates can guide search, while the local pipeline should continue to expose only deterministic validation outcomes as acceptance facts.
- **Minimal proofs serve search, not necessarily pedagogy:** the local Agent 3 and Agent 4 must independently preserve source method and explanatory structure.

## Important Qualifications

- The paper studies proof search from already formalized statements; it does not solve PDF extraction, source-statement formalization, or textbook provenance.
- The experiments use substantial distributed GPU and CPU resources and environment-specific datasets, so headline performance does not imply a lightweight reproducible local setup.
- Online training on evaluation statements changes how cumulative pass rates should be interpreted; transductive and held-out results must remain distinct.
- The Lean and Mathlib environment described in this 2022 paper predates the versions pinned by the local project.
- The search objective rewards finding valid proofs, whereas the local project also requires semantic fidelity to the source proof and pedagogical publication quality.

## Questions for Follow-up

- Can Agent 2 expose a provider-independent subgoal/search graph without depending on Aristotle's private internal representation?
- Should revision handoffs distinguish reusable proved lemmas from failed or merely high-value subgoals?
- Which HTPS progress quantities are safe to persist as heuristics without presenting them as validation facts?
- Can Agent 3 use proof dependency graphs to target semantic comparison while preserving its independent-review boundary?

## Related Local Pages

- [[Aristotle IMO-level Automated Theorem Proving]]
- [[../../docs/architecture/Four-Agent Pipeline|Four-Agent Formalization and Publication Pipeline]]
- [[../process-log]]
- [[../../code/agents/formalization/README|Agent 2 Lean Formalization]]
- [[../../code/agents/review/README|Agent 3 Independent Review]]
