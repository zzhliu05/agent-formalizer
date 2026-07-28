from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .client import ExtractionResponse
from .models import ProofStatus, ProofStep, ProofStepRole, TheoremCandidate


class MarkdownTheoremExtractor(Protocol):
    model_name: str
    deployment_label: str

    def extract(
        self,
        *,
        document_id: str,
        chunk_name: str,
        markdown: str,
    ) -> ExtractionResponse: ...


@dataclass(frozen=True)
class TheoremRunResult:
    document_id: str
    run_id: str
    run_dir: Path
    theorem_ids: tuple[str, ...]
    status_counts: dict[str, int]
    rejected_candidate_count: int


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.").lower()
    if not cleaned:
        raise ValueError("document_id must contain at least one letter or number")
    return cleaned


def _slug(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.casefold()).strip("-")
    return (cleaned or fallback)[:64]


def _document_id_from_markdown(markdown: str, fallback: str) -> str:
    match = re.search(r"(?m)^document_id:\s*[\"']?([^\"'\r\n]+)", markdown)
    return _safe_id(match.group(1).strip()) if match else _safe_id(fallback)


def _page_anchors(markdown: str) -> set[int]:
    return {
        int(value)
        for value in re.findall(r"<!--\s*pdf-page:\s*(\d+)\s*-->", markdown)
    }


def _evidence_text(markdown: str) -> str:
    text = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", markdown, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"(?m)^\s*>\s*OCR warning:.*$", " ", text)
    text = re.sub(
        r"(?m)^\s*\*?\(注[:：].*(?:OCR|原文|印刷不清|符号连写|按标准).*\)\*?\s*$",
        " ",
        text,
    )
    text = re.sub(r"(?m)^\s*-{3,}(?:\s*\|\s*-{3,})*\s*$", " ", text)
    text = re.sub(r"(?m)^# OCR chunk .*$", " ", text)
    text = re.sub(r"(?m)^## PDF page \d+\s*$", " ", text)
    text = re.sub(
        (
            r"(?m)^\s*\**(?:"
            r"\d+\**\s+(?:\$\s*\\quad\s*\$\s*)?[A-Z][A-Z ]+"
            r"|[A-Z][A-Z ]+(?:\$\s*\\quad\s*\$\s*)?\**\d+"
            r")\**\s*$"
        ),
        " ",
        text,
    )
    text = re.sub(
        (
            r"(?m)^\s*\**(?:"
            r"\d+\s*\|\s*第\s*\d+\s*章\b.*"
            r"|(?:\d+(?:\.\d+)+\s+.+|习题\s*\d+|补\s*充\s*题)\s*\|\s*\d+"
            r")\**\s*$"
        ),
        " ",
        text,
    )
    return text


def _canonical(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def _evidence_canonical(value: str) -> str:
    text = value.replace("$\\blacksquare$", "■").replace("\\blacksquare", "■")
    text = text.replace("∎", "■")
    text = text.replace("**", "")
    output: list[str] = []
    in_math = False
    index = 0
    while index < len(text):
        char = text[index]
        escaped = index > 0 and text[index - 1] == "\\"
        if char == "$" and not escaped:
            token = "$$" if text[index : index + 2] == "$$" else "$"
            output.append(token)
            in_math = not in_math
            index += len(token)
            continue
        if char in {"*", "`"} and not escaped and not in_math:
            index += 1
            continue
        output.append(char)
        index += 1
    return _canonical("".join(output))


def _require_evidence(quoted: str, source: str, field: str) -> None:
    if quoted and _evidence_canonical(quoted) not in _evidence_canonical(source):
        raise ValueError(f"{field} is not verbatim evidence from the Markdown input")


def _evidence_safe_proof_steps(candidate: TheoremCandidate) -> TheoremCandidate:
    if not candidate.proof_verbatim:
        return candidate
    valid = True
    for index, step in enumerate(candidate.proof_steps, start=1):
        if step.order != index:
            valid = False
            break
        if _canonical(step.text_verbatim) not in _canonical(candidate.proof_verbatim):
            valid = False
            break
    if valid:
        covered = _canonical(" ".join(step.text_verbatim for step in candidate.proof_steps))
        valid = covered == _canonical(candidate.proof_verbatim)
    if valid:
        return candidate

    warning = (
        "The model's semantic proof-step partition did not exactly cover the source; "
        "the pipeline replaced it with one exhaustive verbatim evidence step."
    )
    return candidate.model_copy(
        update={
            "proof_steps": [
                ProofStep(
                    order=1,
                    role=ProofStepRole.OTHER,
                    text_verbatim=candidate.proof_verbatim,
                    source_pages=candidate.source_pages,
                )
            ],
            "uncertainties": [*candidate.uncertainties, warning],
        }
    )


def _evidence_safe_title(candidate: TheoremCandidate) -> TheoremCandidate:
    if not candidate.title_verbatim:
        return candidate
    if _evidence_canonical(candidate.title_verbatim) in _evidence_canonical(
        candidate.statement_verbatim
    ):
        return candidate
    warning = (
        "The model supplied a title that was not printed inside the theorem "
        "statement; the pipeline cleared the optional title field."
    )
    return candidate.model_copy(
        update={
            "title_verbatim": "",
            "uncertainties": [*candidate.uncertainties, warning],
        }
    )


def _evidence_safe_context(
    candidate: TheoremCandidate,
    *,
    source: str,
) -> TheoremCandidate:
    retained = [
        item
        for item in candidate.context_items
        if _evidence_canonical(item.text_verbatim) in _evidence_canonical(source)
    ]
    removed_count = len(candidate.context_items) - len(retained)
    if removed_count == 0:
        return candidate
    warning = (
        f"The pipeline removed {removed_count} optional context item(s) that "
        "were not verbatim evidence from the OCR Markdown."
    )
    return candidate.model_copy(
        update={
            "context_items": retained,
            "uncertainties": [*candidate.uncertainties, warning],
        }
    )


def _validate_candidate(
    candidate: TheoremCandidate,
    *,
    markdown: str,
    chunk_name: str,
) -> TheoremCandidate:
    candidate = _evidence_safe_title(candidate)
    candidate = _evidence_safe_proof_steps(candidate)
    evidence = _evidence_text(markdown)
    candidate = _evidence_safe_context(candidate, source=evidence)
    known_pages = _page_anchors(markdown)
    if not known_pages:
        raise ValueError(f"{chunk_name} contains no pdf-page anchors")
    page_fields = [candidate.source_pages]
    page_fields.extend(step.source_pages for step in candidate.proof_steps)
    page_fields.extend(item.source_pages for item in candidate.context_items)
    for pages in page_fields:
        if pages != sorted(set(pages)):
            raise ValueError("source_pages must be sorted and unique")
        if not set(pages).issubset(known_pages):
            raise ValueError(f"source_pages {pages} are outside {sorted(known_pages)}")

    _require_evidence(candidate.statement_verbatim, evidence, "statement_verbatim")
    _require_evidence(candidate.label_verbatim, candidate.statement_verbatim, "label_verbatim")
    _require_evidence(candidate.title_verbatim, candidate.statement_verbatim, "title_verbatim")
    _require_evidence(candidate.proof_verbatim, evidence, "proof_verbatim")
    _require_evidence(
        candidate.omission.marker_verbatim,
        evidence,
        "omission.marker_verbatim",
    )
    for index, item in enumerate(candidate.context_items, start=1):
        _require_evidence(item.text_verbatim, evidence, f"context_items[{index}]")
    for index, step in enumerate(candidate.proof_steps, start=1):
        if step.order != index:
            raise ValueError("proof_steps must be consecutively ordered from 1")
        _require_evidence(step.text_verbatim, candidate.proof_verbatim, f"proof_steps[{index}]")

    if not candidate.proof_verbatim and candidate.proof_steps:
        raise ValueError("proof_steps require nonempty proof_verbatim")
    return candidate


def _theorem_id(document_id: str, candidate: TheoremCandidate) -> str:
    page = min(candidate.source_pages)
    number = re.match(r"\s*(\d+\.\d+)\b", candidate.label_verbatim)
    if number:
        label = number.group(1).replace(".", "-")
    else:
        label = _slug(candidate.label_verbatim, fallback=candidate.kind.value)
    if not number and label == candidate.kind.value:
        digest = _sha256_bytes(_canonical(candidate.statement_verbatim).encode("utf-8"))[:10]
        label = f"{label}-{digest}"
    return f"{document_id}-p{page:05d}-{label}"


def _next_attempt(theorem_root: Path) -> tuple[int, Path]:
    extraction_root = theorem_root / "extraction"
    extraction_root.mkdir(parents=True, exist_ok=True)
    attempts = []
    for child in extraction_root.glob("attempt-*"):
        match = re.fullmatch(r"attempt-(\d{3})", child.name)
        if match and child.is_dir():
            attempts.append(int(match.group(1)))
    number = max(attempts, default=0) + 1
    return number, extraction_root / f"attempt-{number:03d}"


def _context_markdown(
    theorem_id: str,
    candidate: TheoremCandidate,
    *,
    document_id: str,
) -> str:
    lines = [
        "---",
        "type: theorem-extraction-context",
        'schema_version: "1.0"',
        f"theorem_id: {json.dumps(theorem_id, ensure_ascii=False)}",
        f"document_id: {json.dumps(document_id, ensure_ascii=False)}",
        f"proof_status: {candidate.proof_status.value}",
        "---",
        "",
        f"# Context for {candidate.label_verbatim}",
        "",
        "## Proof availability",
        "",
        f"- Status: `{candidate.proof_status.value}`",
        f"- Omitted: `{str(candidate.omission.is_omitted).lower()}`",
        f"- Reason: `{candidate.omission.reason.value}`",
        f"- Note: {candidate.omission.note or 'None'}",
        "",
        "## Prerequisite context",
        "",
    ]
    if not candidate.context_items:
        lines.append("No local prerequisite context was extracted.")
    for item in candidate.context_items:
        heading = item.label_verbatim or item.relation.value
        lines.extend(
            [
                f"### {heading}",
                "",
                f"Relation: `{item.relation.value}`; pages: {', '.join(map(str, item.source_pages))}.",
                "",
                item.text_verbatim,
                "",
                f"Relevance: {item.relevance}",
                "",
            ]
        )
    if candidate.uncertainties:
        lines.extend(["## Uncertainties", ""])
        lines.extend(f"- {item}" for item in candidate.uncertainties)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _source_text(candidate: TheoremCandidate) -> str:
    sections = [
        f"PAGES: {', '.join(map(str, candidate.source_pages))}",
        "",
        "STATEMENT (verbatim)",
        candidate.statement_verbatim,
        "",
        f"PROOF STATUS: {candidate.proof_status.value}",
        "PROOF (verbatim)",
        candidate.proof_verbatim or "[No proof text present in the source chunk]",
    ]
    if candidate.omission.is_omitted:
        sections.extend(
            [
                "",
                f"OMISSION REASON: {candidate.omission.reason.value}",
                f"OMISSION MARKER: {candidate.omission.marker_verbatim or '[No explicit marker]'}",
                f"OMISSION NOTE: {candidate.omission.note}",
            ]
        )
    if candidate.context_items:
        sections.extend(["", "CONTEXT EVIDENCE"])
        for item in candidate.context_items:
            sections.extend(["", item.text_verbatim])
    return "\n".join(sections).rstrip() + "\n"


class TheoremExtractionPipeline:
    def __init__(self, extractor: MarkdownTheoremExtractor) -> None:
        self._extractor = extractor

    def run(
        self,
        markdown_files: list[Path],
        output_root: Path,
        *,
        document_id: str | None = None,
    ) -> TheoremRunResult:
        if not markdown_files:
            raise ValueError("at least one Markdown file is required")
        resolved = [path.resolve() for path in markdown_files]
        for path in resolved:
            if not path.is_file() or path.suffix.casefold() != ".md":
                raise ValueError(f"Expected an existing Markdown file: {path}")

        first_markdown = resolved[0].read_text(encoding="utf-8")
        safe_document_id = (
            _safe_id(document_id)
            if document_id
            else _document_id_from_markdown(first_markdown, resolved[0].stem)
        )
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = output_root.resolve() / "_runs" / safe_document_id / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        theorem_ids: list[str] = []
        status_by_id: dict[str, str] = {}
        seen: dict[str, str] = {}
        chunk_records = []
        rejected_candidate_count = 0
        for markdown_path in resolved:
            markdown = markdown_path.read_text(encoding="utf-8")
            response = self._extractor.extract(
                document_id=safe_document_id,
                chunk_name=markdown_path.name,
                markdown=markdown,
            )
            produced = []
            rejected = []
            validated_candidates: list[TheoremCandidate] = []
            for candidate in response.batch.candidates:
                plain_label = candidate.label_verbatim.replace("*", "").strip()
                if re.search(
                    r"^(?:例|example|Àı)\s*\d+\.\d+\b",
                    plain_label,
                    flags=re.IGNORECASE,
                ):
                    rejected.append(
                        {
                            "label": candidate.label_verbatim,
                            "reason": "worked_example_not_theorem_like",
                        }
                    )
                    rejected_candidate_count += 1
                    continue
                try:
                    candidate = _validate_candidate(
                        candidate,
                        markdown=markdown,
                        chunk_name=markdown_path.name,
                    )
                except ValueError as exc:
                    if _evidence_canonical(candidate.label_verbatim) not in _evidence_canonical(
                        _evidence_text(markdown)
                    ):
                        rejected.append(
                            {
                                "label": candidate.label_verbatim,
                                "reason": "label_not_grounded_in_source",
                            }
                        )
                        rejected_candidate_count += 1
                        continue
                    candidate_id = _theorem_id(safe_document_id, candidate)
                    existing_latest = (
                        output_root
                        / candidate_id
                        / "extraction"
                        / "latest.json"
                    )
                    if existing_latest.is_file():
                        rejected.append(
                            {
                                "label": candidate.label_verbatim,
                                "reason": (
                                    "overlap_candidate_not_grounded_existing_record"
                                ),
                            }
                        )
                        rejected_candidate_count += 1
                        continue
                    if not re.search(r"\d+\.\d+", candidate.label_verbatim):
                        rejected.append(
                            {
                                "label": candidate.label_verbatim,
                                "reason": "non_numbered_candidate_not_grounded",
                            }
                        )
                        rejected_candidate_count += 1
                        continue
                    raise ValueError(
                        f"{markdown_path.name} / {candidate.label_verbatim}: {exc}"
                    ) from exc
                validated_candidates.append(candidate)

            for candidate in validated_candidates:
                theorem_id = _theorem_id(safe_document_id, candidate)
                fingerprint = _sha256_bytes(
                    _canonical(candidate.statement_verbatim).encode("utf-8")
                )
                if theorem_id in seen:
                    if seen[theorem_id] != fingerprint:
                        overlap_variant = True
                    else:
                        continue
                else:
                    overlap_variant = False
                seen[theorem_id] = fingerprint

                attempt_number, attempt_dir = _next_attempt(output_root / theorem_id)
                attempt_dir.mkdir(parents=False, exist_ok=False)
                payload = {
                    "schema_version": "1.0",
                    "theorem_id": theorem_id,
                    "document_id": safe_document_id,
                    "extraction_run_id": run_id,
                    "source": {
                        "markdown_file": markdown_path.name,
                        "markdown_sha256": _sha256_bytes(markdown.encode("utf-8")),
                        "pdf_pages": candidate.source_pages,
                        "overlap_variant": overlap_variant,
                    },
                    "result": candidate.model_dump(mode="json"),
                    "provider": {
                        "request_id": response.metadata.request_id,
                        "requested_model": response.metadata.requested_model,
                        "resolved_model": response.metadata.resolved_model,
                        "deployment": response.metadata.deployment,
                        "finish_reason": response.metadata.finish_reason,
                        "usage": response.metadata.usage,
                    },
                }
                theorem_json = attempt_dir / "theorem.json"
                theorem_json.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                (attempt_dir / "context.md").write_text(
                    _context_markdown(
                        theorem_id,
                        candidate,
                        document_id=safe_document_id,
                    ),
                    encoding="utf-8",
                )
                (attempt_dir / "source.txt").write_text(
                    _source_text(candidate),
                    encoding="utf-8",
                )
                latest = {
                    "theorem_id": theorem_id,
                    "attempt": attempt_number,
                    "path": f"attempt-{attempt_number:03d}/theorem.json",
                    "theorem_json_sha256": _sha256_bytes(theorem_json.read_bytes()),
                }
                (attempt_dir.parent / "latest.json").write_text(
                    json.dumps(latest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

                if theorem_id not in theorem_ids:
                    theorem_ids.append(theorem_id)
                produced.append(theorem_id)
                status = candidate.proof_status.value
                status_by_id[theorem_id] = status

            chunk_records.append(
                {
                    "path": markdown_path.name,
                    "sha256": _sha256_bytes(markdown.encode("utf-8")),
                    "provider_request_id": response.metadata.request_id,
                    "resolved_model": response.metadata.resolved_model,
                    "theorem_ids": produced,
                    "rejected_candidates": rejected,
                }
            )

        status_counts: dict[str, int] = {}
        for status in status_by_id.values():
            status_counts[status] = status_counts.get(status, 0) + 1
        manifest = {
            "schema_version": "1.0",
            "document_id": safe_document_id,
            "run_id": run_id,
            "requested_model": self._extractor.model_name,
            "deployment": self._extractor.deployment_label,
            "theorem_count": len(theorem_ids),
            "rejected_candidate_count": rejected_candidate_count,
            "proof_status_counts": status_counts,
            "chunks": chunk_records,
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return TheoremRunResult(
            document_id=safe_document_id,
            run_id=run_id,
            run_dir=run_dir,
            theorem_ids=tuple(theorem_ids),
            status_counts=status_counts,
            rejected_candidate_count=rejected_candidate_count,
        )
