from __future__ import annotations

import json

from .models import BlindBacktranslation


BLIND_SYSTEM_PROMPT = """You are the blind Lean-to-mathematics translator in Agent 3.
You receive Lean source only. Reconstruct the theorem statement and actual proof
method from the code. Never guess or search for an original textbook wording.
Describe every material tactic, reduction, case split, construction, imported
result, and logical dependency used by the Lean proof. Return only the requested
strict JSON object."""


COMPARISON_SYSTEM_PROMPT = """You are the isolated comparison stage in Agent 3.
Compare a previously frozen Lean-only back-translation against an Agent 1 source
record. Require mathematical equivalence of statement and exact agreement of the
proof method at the level supported by the printed source. Any changed domain,
quantifier, hypothesis, direction, edge case, construction, reduction, or cited
result is an error. If the printed proof is partial, omitted, or only by reference,
the method is unverifiable and the verdict must be needs_reextraction. Return only
the requested strict JSON object."""


def blind_translation_prompt(
    lean_sources: dict[str, str],
    declaration_names: list[str],
    axiom_output: str,
) -> str:
    payload = {
        "lean_sources": lean_sources,
        "declaration_names_detected_mechanically": declaration_names,
        "lean_print_axioms_output": axiom_output,
    }
    return (
        "Translate and explain only this Lean evidence. No original natural-language "
        "statement, proof, context, or Agent 2 rationale is available in this call.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )


def comparison_prompt(
    backtranslation: BlindBacktranslation,
    *,
    source_statement: str,
    source_proof: str,
    source_proof_status: str,
    source_proof_steps: list[str],
    source_context: list[str],
    source_uncertainties: list[str],
) -> str:
    payload = {
        "frozen_lean_only_backtranslation": backtranslation.model_dump(mode="json"),
        "agent1_source": {
            "statement_verbatim": source_statement,
            "proof_verbatim": source_proof,
            "proof_status": source_proof_status,
            "proof_steps_verbatim": source_proof_steps,
            "context_verbatim": source_context,
            "uncertainties": source_uncertainties,
        },
    }
    return (
        "The back-translation below was created and persisted before the source was "
        "opened. Compare it strictly with the source record.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )
