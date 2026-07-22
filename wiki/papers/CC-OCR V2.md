---
type: source
status: active
created: 2026-07-22
updated: 2026-07-22
---

# CC-OCR V2

Source: [Xu et al., “CC-OCR V2: Benchmarking Large Multimodal Models for Literacy in Real-world Document Processing,” arXiv:2605.03903](https://arxiv.org/abs/2605.03903)

## Relevance to P001

The paper evaluates document literacy across five connected capabilities: recognition, parsing, grounding, extraction, and question answering. It warns that downstream systems operating only on recognized text inherit OCR errors, while end-to-end multimodal processing can jointly use text and visual layout.

For the textbook extraction agent, this motivates:

- sending PDF pages to a multimodal model rather than relying exclusively on pre-extracted text;
- preserving formula structure as LaTeX-compatible text;
- requiring page evidence for theorem statements, notation, and prerequisites;
- using structured extraction rather than free-form summaries;
- recording ambiguity and confidence because no evaluated model dominates every task or document type;
- retaining overlapping page context to reduce boundary-related dependency loss.

## Limits

CC-OCR V2 is an evaluation benchmark, not a ready-made theorem extraction algorithm. The local Agent 1 design adapts its task taxonomy and auditability lessons to mathematical textbooks; theorem identification, prerequisite modeling, stable identifiers, and artifact packaging are project-specific additions.
