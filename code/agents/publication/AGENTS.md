# Publication Agent Instructions

This directory belongs to Agent 4 of the multi-agent formal mathematics
textbook pipeline.

## Mission

Turn only accepted Agent 1/2/3 theorem records into a reproducible LaTeX
textbook bundle containing the natural-language source material and clickable
links to the corresponding Lean source files.

## Rules

- Accept only chapter inventories whose terminal verdict is `accepted` or
  `accepted_declaration`.
- Revalidate the Agent 1 theorem hash, Agent 2 handoff and Lean source hashes,
  and Agent 3 review binding before publication.
- Never publish a latest-but-unaccepted Lean attempt.
- Copy every hash-bound Lean source needed by the accepted candidate into the
  publication bundle; links in the PDF must target those bundled files.
- Preserve source statement, context, proof-completeness status, proof text,
  and structured proof steps. Do not invent missing natural-language content.
- Mark omitted, partial, by-reference, or not-applicable proofs explicitly.
- Use the user-selected `elegantbook-en.tex` design. Keep the ElegantBook
  class, license, and used assets beside the generated document so the bundle
  is reproducible.
- Keep Agent 4's generated headings and metadata in English because the
  ElegantBook English template does not support Chinese text.
- Write a manifest with source, review, Lean, template, and generated-file
  hashes.
