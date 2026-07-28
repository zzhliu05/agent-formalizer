from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from .candidate_validation import (
    BuildRunner,
    CandidateValidationError,
    compact_candidate_tree,
    run_local_lean_check,
    safe_extract_tar,
)
from .generator import (
    GenerationError,
    GenerationResult,
    _complete_local_validation,
    _finalize_latest,
    _load_existing_run,
    _new_run,
    _now,
    _record_error,
    _write_build_log,
    _write_json_atomic,
)
from .layout import iter_attempt_dirs
from .reader import sha256_bytes

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RevisionValidationResult:
    generation: GenerationResult
    revision_request_sha256: str
    parent_run_path: Path


def _find_descendant_checkpoint(
    generation_root: Path,
    reviewed_parent_dir: Path,
    *,
    project_id: str,
    task_id: str,
) -> Path | None:
    """Return an in-project checkpoint descended from the reviewed run."""
    reviewed_parent = reviewed_parent_dir.resolve()
    runs: dict[Path, dict[str, object]] = {}
    for attempt_dir in iter_attempt_dirs(generation_root):
        run_path = attempt_dir / "run.json"
        if not run_path.is_file():
            continue
        try:
            payload = json.loads(run_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            runs[run_path.parent.resolve()] = payload

    matching = [
        (run_dir, run)
        for run_dir, run in runs.items()
        if run.get("aristotle", {}).get("project_id") == project_id
        and run.get("aristotle", {}).get("task_id") == task_id
        and run.get("state") in {"validation_failed", "ready_for_review"}
        and (run_dir / "result.tar.gz").is_file()
    ]
    for run_dir, run in matching:
        seen: set[Path] = set()
        current_dir = run_dir
        current = run
        while current_dir not in seen:
            if current_dir == reviewed_parent:
                return run_dir
            seen.add(current_dir)
            parent_text = current.get("revision", {}).get("parent_run_json")
            if not isinstance(parent_text, str):
                break
            parent_dir = Path(parent_text).resolve().parent
            if parent_dir == reviewed_parent:
                return run_dir
            next_run = runs.get(parent_dir)
            if next_run is None:
                break
            current_dir, current = parent_dir, next_run
    return None


def _is_descendant_checkpoint(
    generation_root: Path,
    reviewed_parent_dir: Path,
    *,
    project_id: str,
    task_id: str,
) -> bool:
    """Confirm that a task is an in-project revision descendant of a reviewed run."""
    return (
        _find_descendant_checkpoint(
            generation_root,
            reviewed_parent_dir,
            project_id=project_id,
            task_id=task_id,
        )
        is not None
    )


def validate_revision_archive(
    parent_run_input: str | Path,
    revision_request_input: str | Path,
    archive_input: str | Path,
    *,
    project_id: str,
    task_id: str,
    template_root: str | Path,
    build_timeout_seconds: int = 1800,
    build_runner: BuildRunner = run_local_lean_check,
) -> RevisionValidationResult:
    """Validate an Agent 3-requested Aristotle revision as a new Agent 2 attempt."""

    generation_root, parent_run_dir, parent_run, preparation = _load_existing_run(
        parent_run_input
    )
    if parent_run.get("state") != "ready_for_review":
        raise GenerationError("revision parent must be ready_for_review", parent_run_dir)
    if parent_run.get("aristotle", {}).get("project_id") != project_id:
        raise GenerationError(
            "revision project_id does not match the reviewed parent", parent_run_dir
        )

    revision_path = Path(revision_request_input).resolve()
    archive_path = Path(archive_input).resolve()
    try:
        revision_raw = revision_path.read_bytes()
        revision = json.loads(revision_raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationError(f"cannot read revision request: {exc}") from exc
    if not isinstance(revision, dict) or revision.get("schema_version") != "1.0":
        raise GenerationError("unsupported Agent 3 revision request")
    if revision.get("theorem_id") != preparation.theorem_id:
        raise GenerationError("revision request theorem_id does not match preparation")
    if revision.get("current_project_id") != project_id:
        raise GenerationError("revision request project_id does not match")
    parent_task_id = parent_run.get("aristotle", {}).get("task_id")
    current_task_id = revision.get("current_task_id")
    lineage_parent_dir = parent_run_dir
    if current_task_id != parent_task_id:
        lineage_parent_dir = (
            _find_descendant_checkpoint(
                generation_root,
                parent_run_dir,
                project_id=project_id,
                task_id=current_task_id,
            )
            if isinstance(current_task_id, str)
            else None
        )
    if lineage_parent_dir is None:
        raise GenerationError("revision request task_id does not match reviewed parent")
    for field in (
        "review_json_sha256",
        "source_theorem_json_sha256",
        "candidate_main_sha256",
    ):
        if not isinstance(revision.get(field), str) or not _SHA256_RE.fullmatch(
            revision[field]
        ):
            raise GenerationError(f"revision request {field} is invalid")
    if revision["source_theorem_json_sha256"] != preparation.request.get(
        "input", {}
    ).get("theorem_json_sha256"):
        raise GenerationError("revision request source theorem hash does not match")
    if not isinstance(revision.get("review_attempt"), int) or revision[
        "review_attempt"
    ] < 1:
        raise GenerationError("revision request review_attempt is invalid")
    if revision_path.parent.name != f"attempt-{revision['review_attempt']:03d}":
        raise GenerationError("revision request path does not match review_attempt")
    if not all(
        isinstance(revision.get(field), list) and revision[field]
        for field in ("issues", "instructions", "constraints")
    ):
        raise GenerationError("revision request is missing issues or instructions")

    review_path = revision_path.parent / "review.json"
    try:
        review_raw = review_path.read_bytes()
        review = json.loads(review_raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationError(f"cannot verify Agent 3 review: {exc}") from exc
    if (
        not isinstance(review, dict)
        or review.get("theorem_id") != preparation.theorem_id
        or review.get("attempt") != revision["review_attempt"]
        or review.get("verdict") != "needs_reformalization"
        or sha256_bytes(review_raw) != revision["review_json_sha256"]
    ):
        raise GenerationError("revision request does not match its Agent 3 review")

    parent_handoff_path = parent_run_dir / "handoff.json"
    try:
        parent_handoff = json.loads(
            parent_handoff_path.read_text(encoding="utf-8-sig")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationError(f"cannot verify reviewed Agent 2 handoff: {exc}") from exc
    candidate = (
        parent_handoff.get("candidate", {})
        if isinstance(parent_handoff, dict)
        else {}
    )
    main_text = candidate.get("main_path")
    project_text = candidate.get("project_root")
    if not isinstance(main_text, str) or not isinstance(project_text, str):
        raise GenerationError("reviewed handoff candidate paths are invalid")
    try:
        main_relative = Path(main_text).relative_to(Path(project_text)).as_posix()
    except ValueError as exc:
        raise GenerationError("reviewed handoff Main.lean path is invalid") from exc
    expected_main_hash = candidate.get("lean_file_hashes", {}).get(main_relative)
    if (
        expected_main_hash != revision["candidate_main_sha256"]
        or parent_run.get("validation", {})
        .get("lean_file_hashes", {})
        .get(main_relative)
        != expected_main_hash
    ):
        raise GenerationError("revision request candidate hash does not match parent")
    if not archive_path.is_file():
        raise GenerationError("revision result archive is missing")
    revision_hash = sha256_bytes(revision_raw)

    run_dir, run = _new_run(preparation, generation_root)
    run["state"] = "revision_received"
    run["revision"] = {
        "owner": "agent3",
        "parent_run_json": str((lineage_parent_dir / "run.json").resolve()),
        "parent_task_id": current_task_id,
        "reviewed_parent_run_json": str((parent_run_dir / "run.json").resolve()),
        "revision_request_path": str(revision_path),
        "revision_request_sha256": revision_hash,
    }
    run["aristotle"]["project_id"] = project_id
    run["aristotle"]["task_id"] = task_id
    run["aristotle"]["task_status"] = "COMPLETE"
    run["aristotle"]["status_history"] = [
        {
            "observed_at": _now(),
            "status": "COMPLETE",
            "percent_complete": 100,
        }
    ]
    run["updated_at"] = _now()
    _write_json_atomic(run_dir / "run.json", run)

    copied_archive = run_dir / "result.tar.gz"
    shutil.copyfile(archive_path, copied_archive)
    archive_hash = sha256_bytes(copied_archive.read_bytes())
    try:
        if generation_root.name == "gen":
            temporary_tree = run_dir / f".extract-{uuid.uuid4().hex}"
            try:
                safe_extract_tar(copied_archive, temporary_tree)
                compact_candidate_tree(temporary_tree, run_dir / "lean")
            except Exception:
                if temporary_tree.exists():
                    shutil.rmtree(temporary_tree)
                raise
            tree_name = "lean"
        else:
            safe_extract_tar(copied_archive, run_dir / "result")
            tree_name = "result"
        run["state"] = "downloaded"
        run["result"] = {
            "archive": "result.tar.gz",
            "archive_sha256": archive_hash,
            "archive_size_bytes": copied_archive.stat().st_size,
            "tree": tree_name,
        }
        run["updated_at"] = _now()
        _write_json_atomic(run_dir / "run.json", run)
        generated = _complete_local_validation(
            preparation,
            generation_root,
            run_dir,
            run,
            Path(template_root).resolve(),
            build_timeout_seconds,
            build_runner,
        )
    except CandidateValidationError as exc:
        if exc.build is not None:
            _write_build_log(run_dir / "build.log", exc.build)
        _record_error(run_dir, run, "validation_failed", exc)
        generated = GenerationResult(
            preparation.theorem_id,
            "validation_failed",
            run_dir,
            project_id,
            task_id,
            None,
        )
        _finalize_latest(generation_root, generated)
    except Exception as exc:
        _record_error(run_dir, run, "internal_error", exc)
        raise GenerationError(
            "unexpected failure while validating an Agent 3 revision",
            run_dir,
        ) from exc

    return RevisionValidationResult(
        generation=generated,
        revision_request_sha256=revision_hash,
        parent_run_path=parent_run_dir / "run.json",
    )
