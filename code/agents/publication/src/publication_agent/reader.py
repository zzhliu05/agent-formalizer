from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from formalization_agent.reader import (
    LoadedTheoremPackage,
    PackageReadError,
    load_theorem_package,
)
from review_agent.reader import ReviewReadError, load_candidate

from .models import LeanSource, PublicationEntry

ACCEPTED_VERDICTS = {"accepted", "accepted_declaration"}
_NUMBER_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)(?!\d)")
_DECLARATION_RE = re.compile(
    r"^\s*(?:noncomputable\s+)?"
    r"(?:theorem|lemma|axiom|def|abbrev|example)\s+"
    r"([A-Za-z_][A-Za-z0-9_'.]*)",
)


class PublicationReadError(ValueError):
    """Raised when an accepted pipeline artifact is not publication-safe."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_object(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationReadError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PublicationReadError(f"{path} must contain a JSON object")
    return payload, raw


def _resolve_recorded_path(raw_path: object, *, relative_to: Path) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise PublicationReadError("chapter item contains an invalid artifact path")
    path = Path(raw_path)
    if not path.is_absolute():
        path = relative_to / path
    return path.resolve()


def _build_source_index(
    roots: Iterable[Path],
    expected_hashes: set[str],
) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for root_input in roots:
        root = root_input.resolve()
        if not root.is_dir():
            raise PublicationReadError(f"source root does not exist: {root}")
        for path in root.rglob("theorem.json"):
            try:
                digest = sha256_bytes(path.read_bytes())
            except OSError as exc:
                raise PublicationReadError(f"cannot hash {path}: {exc}") from exc
            if digest in expected_hashes:
                index.setdefault(digest, path.resolve())
        for pointer in root.rglob("latest.json"):
            try:
                payload, _ = _read_object(pointer)
            except PublicationReadError:
                continue
            digest = payload.get("theorem_json_sha256")
            if digest not in expected_hashes or digest in index:
                continue
            target_text = payload.get("path")
            if not isinstance(target_text, str):
                continue
            target = (pointer.parent / target_text).resolve()
            if target.is_file() and sha256_bytes(target.read_bytes()) == digest:
                index[digest] = target
    missing = expected_hashes - set(index)
    if missing:
        formatted = ", ".join(sorted(missing))
        raise PublicationReadError(
            f"cannot locate Agent 1 theorem package(s) for SHA-256: {formatted}"
        )
    return index


def _number_from_label(label: str, theorem_id: str) -> str:
    match = _NUMBER_RE.search(label) or _NUMBER_RE.search(theorem_id)
    return f"{match.group(1)}.{match.group(2)}" if match else ""


def _declaration_location(text: str) -> tuple[str, int | None]:
    in_block_comment = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if in_block_comment:
            if "-/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/-"):
            if "-/" not in stripped[2:]:
                in_block_comment = True
            continue
        if stripped.startswith("--"):
            continue
        match = _DECLARATION_RE.match(line)
        if match:
            return match.group(1), line_number
    return "", None


def _load_source(path: Path, expected_hash: str) -> LoadedTheoremPackage:
    try:
        loaded = load_theorem_package(path)
    except PackageReadError as exc:
        raise PublicationReadError(str(exc)) from exc
    if loaded.theorem_json_sha256 != expected_hash:
        raise PublicationReadError(
            f"Agent 1 theorem hash changed: {loaded.theorem_json_path}"
        )
    return loaded


def load_publication_entries(
    chapter_summary_input: str | Path,
    source_roots: Iterable[str | Path],
) -> tuple[list[PublicationEntry], str]:
    summary_path = Path(chapter_summary_input).resolve()
    summary, summary_raw = _read_object(summary_path)
    if summary.get("complete") is not True:
        raise PublicationReadError("Agent 3 chapter summary is not complete")
    items = summary.get("items")
    if not isinstance(items, list) or not items:
        raise PublicationReadError("Agent 3 chapter summary has no items")

    expected_hashes: set[str] = set()
    item_records: list[tuple[dict[str, Any], Path, dict[str, Any], bytes]] = []
    for item in items:
        if not isinstance(item, dict):
            raise PublicationReadError("chapter item must be a JSON object")
        verdict = item.get("verdict")
        if verdict not in ACCEPTED_VERDICTS:
            raise PublicationReadError(
                f"theorem {item.get('theorem_id')} is not accepted: {verdict}"
            )
        review_path = _resolve_recorded_path(
            item.get("final_review_path"),
            relative_to=summary_path.parent,
        )
        review, review_raw = _read_object(review_path)
        if review.get("verdict") != verdict:
            raise PublicationReadError(
                f"review verdict does not match chapter summary: {review_path}"
            )
        source_hash = review.get("input", {}).get("agent1_theorem_json_sha256")
        if not isinstance(source_hash, str) or len(source_hash) != 64:
            raise PublicationReadError(f"review has no valid Agent 1 hash: {review_path}")
        expected_hashes.add(source_hash)
        item_records.append((item, review_path, review, review_raw))

    source_index = _build_source_index(
        [Path(root) for root in source_roots],
        expected_hashes,
    )
    entries: list[PublicationEntry] = []
    seen_theorems: set[str] = set()
    seen_bundle_slugs: set[str] = set()

    for item, review_path, review, review_raw in item_records:
        theorem_id = item.get("theorem_id")
        if not isinstance(theorem_id, str) or not theorem_id:
            raise PublicationReadError("chapter item theorem_id is invalid")
        if theorem_id in seen_theorems:
            raise PublicationReadError(f"duplicate theorem in chapter summary: {theorem_id}")
        seen_theorems.add(theorem_id)

        handoff_path = _resolve_recorded_path(
            item.get("handoff_path"),
            relative_to=summary_path.parent,
        )
        try:
            candidate = load_candidate(handoff_path)
        except ReviewReadError as exc:
            raise PublicationReadError(str(exc)) from exc
        if candidate.theorem_id != theorem_id:
            raise PublicationReadError("chapter theorem does not match Agent 2 handoff")

        review_input = review.get("input")
        if not isinstance(review_input, dict):
            raise PublicationReadError(f"review input metadata is missing: {review_path}")
        reviewed_handoff = Path(str(review_input.get("agent2_handoff_path", ""))).resolve()
        if reviewed_handoff != candidate.handoff_path:
            raise PublicationReadError(
                f"review is not bound to the selected handoff: {review_path}"
            )
        expected_main_hash = review_input.get("agent2_main_sha256")
        main_relative = candidate.main_path.relative_to(candidate.candidate_root).as_posix()
        actual_main_hash = candidate.handoff["candidate"]["lean_file_hashes"].get(
            main_relative
        )
        if expected_main_hash != actual_main_hash:
            raise PublicationReadError(
                f"review is not bound to the selected Main.lean: {review_path}"
            )

        source_hash = str(review_input["agent1_theorem_json_sha256"])
        source = _load_source(source_index[source_hash], source_hash)
        if source.package.theorem_id != theorem_id:
            raise PublicationReadError("Agent 1 theorem_id does not match chapter item")
        result = source.package.result
        label = result.label_verbatim or ""
        number = _number_from_label(label, theorem_id)
        bundle_slug = number.replace(".", "-") if number else theorem_id
        if bundle_slug in seen_bundle_slugs:
            raise PublicationReadError(
                f"duplicate publication Lean directory: {bundle_slug}"
            )
        seen_bundle_slugs.add(bundle_slug)

        lean_sources: list[LeanSource] = []
        for relative_path, text in sorted(candidate.lean_sources.items()):
            source_path = candidate.candidate_root / relative_path
            lean_sources.append(
                LeanSource(
                    relative_path=relative_path,
                    source_path=source_path,
                    sha256=candidate.handoff["candidate"]["lean_file_hashes"][
                        relative_path
                    ],
                    text=text,
                )
            )
        main_text = candidate.lean_sources[main_relative]
        declaration_name, declaration_line = _declaration_location(main_text)
        entries.append(
            PublicationEntry(
                theorem_id=theorem_id,
                number=number,
                kind=result.kind,
                label=label,
                title=result.title_verbatim or "",
                statement=result.statement_verbatim,
                source_pages=tuple(result.source_pages),
                proof_status=result.proof_status,
                proof=result.proof_verbatim or "",
                proof_steps=tuple(step.model_dump() for step in result.proof_steps),
                context_items=tuple(
                    context.model_dump() for context in result.context_items
                ),
                uncertainties=tuple(result.uncertainties),
                verdict=str(item["verdict"]),
                theorem_json_path=source.theorem_json_path,
                theorem_json_sha256=source_hash,
                review_json_path=review_path,
                review_json_sha256=sha256_bytes(review_raw),
                handoff_path=candidate.handoff_path,
                main_relative_path=main_relative,
                main_sha256=str(actual_main_hash),
                declaration_name=declaration_name,
                declaration_line=declaration_line,
                lean_sources=tuple(lean_sources),
            )
        )

    def sort_key(entry: PublicationEntry) -> tuple[int, ...] | tuple[int, str]:
        if entry.number:
            return tuple(int(part) for part in entry.number.split("."))
        return (10**9, entry.theorem_id)

    entries.sort(key=sort_key)
    return entries, sha256_bytes(summary_raw)

