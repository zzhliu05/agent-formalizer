from __future__ import annotations

import json

from .models import PageObservation, TheoremCandidate


def extraction_prompt(*, document_id: str, original_page_start: int, original_page_end: int) -> str:
    return f"""
You are Agent 1 in a traceable mathematical-textbook formalization pipeline.

Analyze this PDF chunk from document {document_id!r}. It corresponds to original PDF pages
{original_page_start} through {original_page_end}. In every page field, report the ONE-BASED PAGE
NUMBER WITHIN THIS SUPPLIED CHUNK, not the printed book page and not the original PDF page.

Perform the following jointly from the visual PDF, rather than trusting a plain-text OCR intermediate:
1. Inspect every supplied page and populate a page observation. Recognize theorem-bearing text and its
   prerequisite context faithfully, preserving mathematical symbols and printed labels.
2. Parse display and inline formulas into readable LaTeX where possible.
3. Locate every theorem-like statement: theorem, lemma, proposition, corollary, axiom, claim, or
   exercise that asserts a proposition.
4. For each statement, extract its local formalization context: variables, domains, standing assumptions,
   definitions, notation, earlier named results, relevant surrounding prose, and any available proof sketch.
5. Ground every quoted prerequisite or notation item to a page in this chunk. If a prerequisite is implied
   but not present, mark it inferred or unresolved and do not invent a quotation or page.
6. Record damaged OCR, uncertain symbols, missing context, or ambiguous scope explicitly.

Rules:
- Before returning an empty candidates list, check every page observation for printed words and labels such
  as Theorem, Proposition, Lemma, Corollary, Axiom, Claim, and numbered statements.
- A theorem candidate is required for every legible theorem-like printed statement, even when its proof begins
  on the same page or continues onto the next page.
- original_text must be a faithful transcription, not a mathematical correction.
- normalized_statement may repair spacing/layout only; do not strengthen, weaken, or silently fix content.
- Separate quoted source evidence from inference with source_status.
- Use confidence below 0.8 when a symbol, quantifier, page boundary, or dependency is materially uncertain.
- Do not produce Lean code.
- Do not claim that a theorem has been verified.
- Return only the requested JSON structure.
""".strip()


def candidate_recovery_prompt(pages: list[PageObservation]) -> str:
    observations = json.dumps(
        [page.model_dump(mode="json") for page in pages],
        ensure_ascii=False,
        indent=2,
    )
    return f"""
You are the theorem extraction stage of a mathematical textbook OCR agent.

The visual OCR stage returned the page observations below. It detected printed theorem-like labels but did
not populate theorem candidates. Create one candidate for EVERY detected theorem, proposition, lemma,
corollary, axiom, claim, or exercise-claim. The page numbers are already one-based within the supplied PDF
chunk and must be copied unchanged.

Use earlier page observations to attach definitions, notation, standing assumptions, and named results as
prerequisites. Mark evidence as quoted only when it appears in the observations; otherwise mark it inferred
or unresolved. Preserve each printed statement faithfully in original_text. Do not create Lean code and do
not claim formal verification.

PAGE OBSERVATIONS:
{observations}
""".strip()


def context_enrichment_prompt(
    pages: list[PageObservation], candidates: list[TheoremCandidate]
) -> str:
    observations = json.dumps(
        [page.model_dump(mode="json") for page in pages], ensure_ascii=False, indent=2
    )
    existing = json.dumps(
        [candidate.model_dump(mode="json") for candidate in candidates],
        ensure_ascii=False,
        indent=2,
    )
    return f"""
You are the context-enrichment stage of a mathematical textbook OCR agent.

Return exactly the same candidates with the same local_id, kind, title, original_text, normalized_statement,
variables, assumptions, conclusion, and source_anchor. Enrich only their notation, prerequisites,
surrounding_context, proof_sketch, ambiguities, and confidence using the page observations.

For every symbol or relation used in a candidate, look backward through the page observations for its local
definition. Definitions and notation ARE prerequisites even when the theorem does not cite them by name.
For every corollary or theorem whose proof invokes an earlier labeled result, add that result as a prerequisite.
Use source_status=quoted and a page only when the defining or prerequisite text appears below. Otherwise mark
the item inferred or unresolved. Do not leave prerequisites and notation both empty when earlier observations
define a symbol, relation, standing assumption, or named result used by the candidate.

PAGE OBSERVATIONS:
{observations}

LOCKED CANDIDATES:
{existing}
""".strip()
