---
type: source
status: active
created: 2026-07-28
updated: 2026-07-28
process: P002
arxiv: "2510.01346v2"
doi: "10.48550/arXiv.2510.01346"
---

# Aristotle: IMO-level Automated Theorem Proving

Source: [Achim et al., “Aristotle: IMO-level Automated Theorem Proving,” arXiv:2510.01346v2](https://arxiv.org/abs/2510.01346)

Local source: [[../../raw/papers/2510.01346v2 Aristotle IMO-level Automated Theorem Proving.pdf]]

PDF SHA-256: `3CB2F3760B9F73EF24CAF36CEAFA600E75DA5CA51F31DD46F662AAC3B6263749`

Authors: Tudor Achim, Alex Best, Alberto Bietti, Kevin Der, Mathïs Fédérico, Sergei Gukov, Daniel Halpern-Leistner, Kirsten Henningsgard, Yury Kudryashov, Alexander Meiburg, Martin Michelsen, Riley Patterson, Eric Rodriguez, Laura Scharff, Vikram Shanker, Vladmir Sicca, Hari Sowrirajan, Aidan Swope, Matyas Tamas, Vlad Tenev, Jonathan Thomm, Harold Williams, and Lawrence Wu (the paper identifies the collective as The Harmonic Team).

Version: v2, 2025-10-10. Categories: `cs.AI`, `cs.CL`. License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Paper Summary

The paper presents Aristotle, a hybrid automated theorem-proving system whose accepted outputs are complete Lean 4 + Mathlib proofs rather than unverified natural-language answers. Its three main subsystems are:

1. a learned Lean proof search system based on highly parallel Monte Carlo Graph Search;
2. an informal reasoning loop that proposes a proof, decomposes it into short lemmas, formalizes the lemma statements, and revises them using Lean feedback;
3. a dedicated plane-geometry solver based on Yuclid.

The search system treats Lean proof construction as an AND/OR hypergraph problem. A proof state succeeds when one action succeeds, while an action that creates multiple goals succeeds only when every resulting goal is proved. The policy proposes Lean actions from the current proof state, proof history, and optional informal proof; a learned value function guides search.

The lemma-based outer loop is deliberately iterative. Failed proof attempts preserve successfully proved lemmas, revise unproved or strategically weak lemmas, correct formalization errors through the Lean REPL, and retry the target. The training pipeline likewise uses formal feedback, proof search, reinforcement learning, and faithfulness filtering when an informal reference proof exists.

The paper reports formally verified solutions to five of the six IMO 2025 problems. The original IMO problem statements were manually translated into Lean, whereas the intermediate lemma statements were autoformalized. The authors also report contributions to Mathlib and other formalization projects, work on advanced topics, and detection of false or unnecessarily constrained exercises in a Lean-based real-analysis textbook.

## Relevance to P001

This paper is a direct architectural reference for [[../../docs/architecture/Four-Agent Pipeline|the local four-Agent pipeline]]:

- **Formal feedback should control progress.** Aristotle repeatedly uses Lean execution to correct statements and proofs; the local pipeline similarly treats kernel validation as a deterministic gate.
- **Informal decomposition and formal search are complementary.** The paper's lemma-generation loop supports separating source-grounded mathematical interpretation from Lean proof construction.
- **A failed candidate is useful state.** Keeping proved lemmas and revising failed ones parallels the local Agent 2/Agent 3 recovery loop, where diagnostics and lineage are preserved rather than discarded.
- **Machine verification is necessary but not sufficient for textbook fidelity.** The paper filters formal proofs for faithfulness when an informal proof is available. The local Agent 3 goes further by freezing a Lean-only reconstruction and independently comparing the formal statement and proof method with the source.
- **Autoformalization remains a boundary.** The IMO evaluation manually formalized the original problem statements. This supports maintaining a dedicated, provenance-heavy Agent 1 instead of treating statement formalization as solved by proof search alone.
- **Search and orchestration are distinct layers.** Aristotle's inner Lean search sits inside a larger reasoning loop; likewise, the local project should keep the proof provider behind explicit handoff, validation, and review contracts.

## Important Qualifications

- The system description does not expose every implementation, model, training-data, compute, or deployment detail needed for independent reproduction.
- The headline IMO result includes manual formalization of the six original problem statements; it is evidence for proof solving under formal inputs, not a fully autonomous PDF-to-Lean pipeline.
- The geometry subsystem operates outside Lean and is machine verified through a separate path, so its trust boundary differs from the Lean subsystem.
- Performance claims and textbook examples are reported by the source authors. They should not be treated as locally reproduced results until independently checked.
- The paper optimizes for theorem proving performance. Pedagogical preservation, exact source-proof alignment, publication provenance, and multi-stage acceptance authority remain local project requirements.

## Questions for Follow-up

- Which Aristotle API behaviors exposed to Agent 2 correspond to the paper's inner search versus its outer lemma-revision system?
- Can the local revision request schema preserve reusable proved lemmas explicitly, instead of only preserving task and artifact lineage?
- Which paper-reported faithfulness signals could strengthen Agent 3 without weakening its independent-review boundary?
- How should non-Lean solvers such as Yuclid be represented in a publication pipeline whose current acceptance model assumes Lean artifacts?

## Related Local Pages

- [[HyperTree Proof Search for Neural Theorem Proving]]
- [[../../docs/architecture/Four-Agent Pipeline|Four-Agent Formalization and Publication Pipeline]]
- [[../process-log]]
- [[../../code/agents/formalization/README|Agent 2 Lean Formalization]]
- [[../../code/agents/review/README|Agent 3 Independent Review]]
