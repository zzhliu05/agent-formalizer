from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from formalization_agent.preparation_reader import (
    LoadedPreparation,
    load_preparation,
)
from formalization_agent.reader import (
    LoadedTheoremPackage,
    load_theorem_package,
    sha256_bytes,
)


class ReviewReadError(ValueError):
    """Raised when an Agent 2 handoff or Agent 1 package is inconsistent."""


@dataclass(frozen=True)
class LoadedCandidate:
    theorem_id: str
    handoff_path: Path
    handoff: dict[str, Any]
    run_path: Path
    run: dict[str, Any]
    preparation: LoadedPreparation
    candidate_root: Path
    main_path: Path
    lean_sources: dict[str, str]
    source_theorem_json_sha256: str


def _read_object(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewReadError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReviewReadError(f"{path} must contain a JSON object")
    return payload, raw


def _safe_relative(base: Path, relative_text: str, label: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute():
        raise ReviewReadError(f"{label} must be a relative path")
    target = (base / relative).resolve()
    if not target.is_relative_to(base.resolve()):
        raise ReviewReadError(f"{label} escapes its artifact directory")
    return target


def load_candidate(handoff_input: str | Path) -> LoadedCandidate:
    path = Path(handoff_input).resolve()
    if path.is_dir():
        path = path / "handoff.json"
    if path.name != "handoff.json" or not path.is_file():
        raise ReviewReadError("review input must be handoff.json or its attempt directory")
    handoff, _ = _read_object(path)
    if handoff.get("schema_version") != "1.0":
        raise ReviewReadError("unsupported Agent 2 handoff schema")
    if handoff.get("state") != "ready_for_review":
        raise ReviewReadError("Agent 2 handoff is not ready_for_review")
    review = handoff.get("review")
    if not isinstance(review, dict) or review.get("owner") != "agent3":
        raise ReviewReadError("handoff does not assign review ownership to Agent 3")
    theorem_id = handoff.get("theorem_id")
    if not isinstance(theorem_id, str) or not theorem_id:
        raise ReviewReadError("handoff theorem_id is invalid")

    run_path = path.parent / "run.json"
    run, _ = _read_object(run_path)
    if run.get("theorem_id") != theorem_id or run.get("state") != "ready_for_review":
        raise ReviewReadError("run.json does not match the ready handoff")
    agent2_run = handoff.get("agent2_run")
    if not isinstance(agent2_run, dict) or agent2_run.get("run_json") != "run.json":
        raise ReviewReadError("handoff Agent 2 run reference is invalid")
    if (
        agent2_run.get("project_id") != run.get("aristotle", {}).get("project_id")
        or agent2_run.get("task_id") != run.get("aristotle", {}).get("task_id")
    ):
        raise ReviewReadError("handoff Aristotle identifiers do not match run.json")
    validation = run.get("validation")
    if not isinstance(validation, dict) or validation.get("local_lean_check") != "passed":
        raise ReviewReadError("Agent 2 local Lean validation did not pass")

    preparation_ref = run.get("preparation", {}).get("request_path")
    if not isinstance(preparation_ref, str):
        raise ReviewReadError("run has no preparation request reference")
    preparation_relative = Path(preparation_ref)
    if preparation_relative.is_absolute():
        raise ReviewReadError("preparation path must be relative")
    preparation_path = (path.parent / preparation_relative).resolve()
    formalization_root = path.parent.parent.parent.resolve()
    if (
        formalization_root.name != "formalization"
        or not preparation_path.is_relative_to(formalization_root)
        or "preparation" not in preparation_path.parts
    ):
        raise ReviewReadError("preparation path escapes the theorem formalization tree")
    preparation = load_preparation(preparation_path)
    if preparation.theorem_id != theorem_id:
        raise ReviewReadError("preparation theorem_id does not match handoff")

    source = handoff.get("source")
    if not isinstance(source, dict):
        raise ReviewReadError("handoff source metadata is missing")
    source_hash = source.get("agent1_theorem_json_sha256")
    if source_hash != preparation.request.get("input", {}).get(
        "theorem_json_sha256"
    ):
        raise ReviewReadError("handoff and preparation source hashes differ")
    if source.get("preparation_request_sha256") != preparation.request_sha256:
        raise ReviewReadError("handoff and preparation request hashes differ")

    candidate = handoff.get("candidate")
    if not isinstance(candidate, dict):
        raise ReviewReadError("handoff candidate metadata is missing")
    candidate_root = _safe_relative(
        path.parent, str(candidate.get("project_root", "")), "candidate root"
    )
    main_path = _safe_relative(
        path.parent, str(candidate.get("main_path", "")), "candidate Main.lean"
    )
    if not candidate_root.is_dir() or not main_path.is_file():
        raise ReviewReadError("candidate project or Main.lean is missing")
    if not main_path.is_relative_to(candidate_root):
        raise ReviewReadError("candidate Main.lean is outside the candidate project")

    expected_hashes = candidate.get("lean_file_hashes")
    if not isinstance(expected_hashes, dict) or not expected_hashes:
        raise ReviewReadError("handoff has no Lean file hashes")
    actual_lean_paths = {
        lean_path.relative_to(candidate_root).as_posix()
        for lean_path in candidate_root.rglob("*.lean")
        if ".lake" not in lean_path.parts
    }
    if actual_lean_paths != set(expected_hashes):
        raise ReviewReadError(
            "candidate Lean file set does not match the Agent 2 handoff"
        )
    main_relative = main_path.relative_to(candidate_root).as_posix()
    if main_relative not in expected_hashes:
        raise ReviewReadError("candidate Main.lean is not hash-bound by the handoff")
    lean_sources: dict[str, str] = {}
    for relative_text, expected_hash in expected_hashes.items():
        if not isinstance(relative_text, str) or not isinstance(expected_hash, str):
            raise ReviewReadError("candidate Lean hash map is malformed")
        lean_path = _safe_relative(candidate_root, relative_text, "Lean source")
        if lean_path.suffix != ".lean" or not lean_path.is_file():
            raise ReviewReadError(f"candidate Lean source is missing: {relative_text}")
        raw = lean_path.read_bytes()
        if sha256_bytes(raw) != expected_hash:
            raise ReviewReadError(f"candidate Lean source changed: {relative_text}")
        try:
            lean_sources[relative_text] = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ReviewReadError(
                f"candidate Lean source is not UTF-8: {relative_text}"
            ) from exc

    return LoadedCandidate(
        theorem_id=theorem_id,
        handoff_path=path,
        handoff=handoff,
        run_path=run_path,
        run=run,
        preparation=preparation,
        candidate_root=candidate_root,
        main_path=main_path,
        lean_sources=lean_sources,
        source_theorem_json_sha256=str(source_hash),
    )


def load_source_after_blind_translation(
    source_input: str | Path,
    *,
    expected_theorem_id: str,
    expected_sha256: str,
) -> LoadedTheoremPackage:
    loaded = load_theorem_package(source_input)
    if loaded.package.theorem_id != expected_theorem_id:
        raise ReviewReadError("Agent 1 theorem_id does not match the Lean candidate")
    if loaded.theorem_json_sha256 != expected_sha256:
        raise ReviewReadError("Agent 1 theorem hash does not match the Agent 2 handoff")
    return loaded
