from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .aristotle_transport import (
    AristotleTransport,
    AristotleTransportError,
    RemoteTaskSnapshot,
    SDKAristotleTransport,
)
from .candidate_validation import (
    BuildRunner,
    CandidateValidationError,
    run_local_lean_check,
    safe_extract_tar,
    validate_candidate,
)
from .preparation_reader import LoadedPreparation, load_preparation
from .reader import sha256_bytes


class GenerationError(RuntimeError):
    """Raised when a generation run cannot safely continue."""

    def __init__(self, message: str, run_dir: Path | None = None):
        super().__init__(message)
        self.run_dir = run_dir


@dataclass(frozen=True)
class GenerationResult:
    theorem_id: str
    state: str
    run_dir: Path
    project_id: str | None
    task_id: str | None
    handoff_path: Path | None


_TERMINAL_STATUSES = {
    "COMPLETE",
    "COMPLETE_WITH_ERRORS",
    "OUT_OF_BUDGET",
    "FAILED",
    "CANCELED",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _write_build_log(path: Path, build: object) -> None:
    command = " ".join(getattr(build, "command"))
    text = "\n".join(
        [
            f"command: {command}",
            f"exit_code: {getattr(build, 'exit_code')}",
            f"timed_out: {str(getattr(build, 'timed_out')).lower()}",
            f"duration_seconds: {getattr(build, 'duration_seconds'):.3f}",
            "",
            "stdout:",
            getattr(build, "stdout"),
            "",
            "stderr:",
            getattr(build, "stderr"),
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def _next_attempt(root: Path) -> int:
    attempts = []
    if root.is_dir():
        for child in root.iterdir():
            if child.is_dir() and child.name.startswith("attempt-"):
                suffix = child.name.removeprefix("attempt-")
                if suffix.isdigit():
                    attempts.append(int(suffix))
    return max(attempts, default=0) + 1


def _generation_root(preparation: LoadedPreparation) -> Path:
    preparation_root = preparation.attempt_dir.parent
    if preparation_root.name != "preparation":
        raise GenerationError(
            "preparation attempt must live directly under a preparation directory"
        )
    return preparation_root.parent / "generation"


def _new_run(
    preparation: LoadedPreparation, generation_root: Path
) -> tuple[Path, dict[str, Any]]:
    generation_root.mkdir(parents=True, exist_ok=True)
    attempt = _next_attempt(generation_root)
    run_dir = generation_root / f"attempt-{attempt:03d}"
    run_dir.mkdir()
    preparation_reference = os.path.relpath(
        preparation.request_path, start=run_dir
    ).replace("\\", "/")
    run = {
        "schema_version": "1.0",
        "state": "created",
        "theorem_id": preparation.theorem_id,
        "created_at": _now(),
        "updated_at": _now(),
        "preparation": {
            "request_path": preparation_reference,
            "request_sha256": preparation.request_sha256,
        },
        "aristotle": {
            "package": "aristotlelib==2.1.0",
            "api_version": "3",
            "agent_questions_setting": "DISABLED",
            "questioning_loop_owner": "agent3",
            "project_id": None,
            "task_id": None,
            "task_status": None,
            "status_history": [],
        },
        "result": None,
        "validation": None,
        "error": None,
        "error_history": [],
    }
    _write_json_atomic(run_dir / "run.json", run)
    return run_dir, run


def _record_snapshot(run: dict[str, Any], snapshot: RemoteTaskSnapshot) -> None:
    remote = run["aristotle"]
    remote["project_id"] = snapshot.project_id
    remote["task_id"] = snapshot.task_id
    remote["task_status"] = snapshot.status
    history = remote["status_history"]
    entry = {
        "observed_at": _now(),
        "status": snapshot.status,
        "percent_complete": snapshot.percent_complete,
    }
    if not history or (
        history[-1]["status"],
        history[-1]["percent_complete"],
    ) != (entry["status"], entry["percent_complete"]):
        history.append(entry)
    run["updated_at"] = _now()


def _record_error(
    run_dir: Path, run: dict[str, Any], state: str, exc: Exception
) -> None:
    error = {
        "occurred_at": _now(),
        "type": type(exc).__name__,
        "message": str(exc),
    }
    run["state"] = state
    run["updated_at"] = _now()
    run["error"] = error
    run.setdefault("error_history", []).append(error)
    _write_json_atomic(run_dir / "run.json", run)


async def _poll_to_terminal(
    transport: AristotleTransport,
    run_dir: Path,
    run: dict[str, Any],
    snapshot: RemoteTaskSnapshot,
    poll_seconds: float,
    timeout_seconds: float,
) -> RemoteTaskSnapshot:
    started = time.monotonic()
    _record_snapshot(run, snapshot)
    run["state"] = "running"
    _write_json_atomic(run_dir / "run.json", run)
    while snapshot.status not in _TERMINAL_STATUSES:
        if time.monotonic() - started >= timeout_seconds:
            run["state"] = "remote_running"
            run["updated_at"] = _now()
            _write_json_atomic(run_dir / "run.json", run)
            raise GenerationError(
                "polling timed out; the remote task remains resumable", run_dir
            )
        await asyncio.sleep(poll_seconds)
        snapshot = await transport.get_task(snapshot.project_id, snapshot.task_id)
        _record_snapshot(run, snapshot)
        _write_json_atomic(run_dir / "run.json", run)
    return snapshot


def _latest_payload(result: GenerationResult, run_hash: str) -> dict[str, Any]:
    attempt = int(result.run_dir.name.removeprefix("attempt-"))
    return {
        "schema_version": "1.0",
        "theorem_id": result.theorem_id,
        "attempt": attempt,
        "path": f"{result.run_dir.name}/run.json",
        "sha256": run_hash,
        "state": result.state,
    }


def _finalize_latest(generation_root: Path, result: GenerationResult) -> None:
    run_path = result.run_dir / "run.json"
    run_hash = sha256_bytes(run_path.read_bytes())
    _write_json_atomic(generation_root / "latest.json", _latest_payload(result, run_hash))


def _active_transport(
    transport: AristotleTransport | None,
) -> AristotleTransport:
    if transport is not None:
        return transport
    if not os.environ.get("ARISTOTLE_API_KEY"):
        raise GenerationError(
            "ARISTOTLE_API_KEY is not set in the current process environment"
        )
    return SDKAristotleTransport()


async def _finish_terminal_run(
    preparation: LoadedPreparation,
    generation_root: Path,
    run_dir: Path,
    run: dict[str, Any],
    snapshot: RemoteTaskSnapshot,
    transport: AristotleTransport,
    template_root: Path,
    build_timeout_seconds: int,
    build_runner: BuildRunner,
) -> GenerationResult:
    if snapshot.status != "COMPLETE":
        error = GenerationError(
            f"Aristotle task ended with status {snapshot.status}", run_dir
        )
        _record_error(run_dir, run, "remote_incomplete", error)
        result = GenerationResult(
            preparation.theorem_id,
            "remote_incomplete",
            run_dir,
            snapshot.project_id,
            snapshot.task_id,
            None,
        )
        _finalize_latest(generation_root, result)
        return result

    archive_path = run_dir / "result.tar.gz"
    await transport.download_result(snapshot.project_id, archive_path)
    archive_hash = sha256_bytes(archive_path.read_bytes())
    extracted_root = run_dir / "result"
    safe_extract_tar(archive_path, extracted_root)
    run["state"] = "downloaded"
    run["error"] = None
    run["result"] = {
        "archive": "result.tar.gz",
        "archive_sha256": archive_hash,
        "archive_size_bytes": archive_path.stat().st_size,
    }
    run["updated_at"] = _now()
    _write_json_atomic(run_dir / "run.json", run)

    validation = validate_candidate(
        extracted_root,
        preparation.project_dir,
        preparation.artifact_hashes,
        template_root,
        build_timeout_seconds,
        build_runner,
    )
    _write_build_log(run_dir / "build.log", validation.build)
    main_relative = validation.main_path.relative_to(run_dir).as_posix()
    run["state"] = "ready_for_review"
    run["error"] = None
    run["validation"] = {
        "local_lean_check": "passed",
        "placeholder_scan": "passed",
        "protected_files": "unchanged",
        "main_path": main_relative,
        "lean_file_hashes": validation.lean_file_hashes,
        "build_log": "build.log",
    }
    run["updated_at"] = _now()
    _write_json_atomic(run_dir / "run.json", run)

    handoff = {
        "schema_version": "1.0",
        "state": "ready_for_review",
        "theorem_id": preparation.theorem_id,
        "created_at": _now(),
        "agent2_run": {
            "run_json": "run.json",
            "project_id": snapshot.project_id,
            "task_id": snapshot.task_id,
        },
        "source": {
            "preparation_request_sha256": preparation.request_sha256,
            "agent1_theorem_json_sha256": preparation.request["input"][
                "theorem_json_sha256"
            ],
        },
        "candidate": {
            "project_root": validation.project_root.relative_to(run_dir).as_posix(),
            "main_path": main_relative,
            "lean_file_hashes": validation.lean_file_hashes,
            "build_log": "build.log",
        },
        "review": {
            "owner": "agent3",
            "questioning_loop_owner": "agent3",
            "semantic_verdict": "pending",
        },
    }
    handoff_path = run_dir / "handoff.json"
    _write_json_atomic(handoff_path, handoff)
    result = GenerationResult(
        preparation.theorem_id,
        "ready_for_review",
        run_dir,
        snapshot.project_id,
        snapshot.task_id,
        handoff_path,
    )
    _finalize_latest(generation_root, result)
    return result


def _resolve_run_input(input_path: Path) -> tuple[Path, dict[str, Any] | None]:
    path = input_path.resolve()
    if path.is_file() and path.name == "run.json":
        return path, None
    if path.is_file() and path.name == "latest.json":
        pointer = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(pointer, dict) or not isinstance(pointer.get("path"), str):
            raise GenerationError("generation latest pointer is invalid")
        relative = Path(pointer["path"])
        target = (path.parent / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(path.parent.resolve()):
            raise GenerationError("generation latest pointer path is unsafe")
        if target.name != "run.json":
            raise GenerationError("generation latest pointer must resolve to run.json")
        attempt = pointer.get("attempt")
        if not isinstance(attempt, int) or target.parent.name != f"attempt-{attempt:03d}":
            raise GenerationError(
                "generation latest attempt does not match its target directory"
            )
        return target, pointer
    if path.is_dir() and (path / "run.json").is_file():
        return path / "run.json", None
    if path.is_dir() and (path / "latest.json").is_file():
        return _resolve_run_input(path / "latest.json")
    raise GenerationError(
        "resume input must be run.json, a generation attempt, or generation/latest.json"
    )


def _load_existing_run(
    input_path: str | Path,
) -> tuple[Path, Path, dict[str, Any], LoadedPreparation]:
    try:
        run_path, pointer = _resolve_run_input(Path(input_path))
        raw = run_path.read_bytes()
        run = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationError(f"cannot read generation run: {exc}") from exc
    if not isinstance(run, dict) or run.get("schema_version") != "1.0":
        raise GenerationError("unsupported generation run schema")
    run_dir = run_path.parent.resolve()
    generation_root = run_dir.parent
    if pointer:
        if pointer.get("sha256") != sha256_bytes(raw):
            raise GenerationError("generation latest hash does not match run.json")
        if pointer.get("theorem_id") != run.get("theorem_id"):
            raise GenerationError("generation latest theorem_id does not match run")

    preparation_metadata = run.get("preparation")
    if not isinstance(preparation_metadata, dict):
        raise GenerationError("generation run has no preparation reference")
    reference = preparation_metadata.get("request_path")
    if not isinstance(reference, str) or not reference:
        raise GenerationError("generation preparation reference is invalid")
    preparation_path = (run_dir / Path(reference)).resolve()
    preparation = load_preparation(preparation_path)
    if preparation.request_sha256 != preparation_metadata.get("request_sha256"):
        raise GenerationError("generation preparation hash no longer matches")
    if preparation.theorem_id != run.get("theorem_id"):
        raise GenerationError("generation theorem_id does not match preparation")
    return generation_root, run_dir, run, preparation


async def generate_proof(
    preparation_input: str | Path,
    *,
    template_root: str | Path,
    generation_root: str | Path | None = None,
    poll_seconds: float = 30.0,
    timeout_seconds: float = 7200.0,
    build_timeout_seconds: int = 1800,
    transport: AristotleTransport | None = None,
    build_runner: BuildRunner = run_local_lean_check,
) -> GenerationResult:
    preparation = load_preparation(preparation_input)
    active_transport = _active_transport(transport)
    root = (
        Path(generation_root).resolve()
        if generation_root is not None
        else _generation_root(preparation)
    )
    run_dir, run = _new_run(preparation, root)

    try:
        prompt = preparation.prompt_path.read_text(encoding="utf-8-sig")
        snapshot = await active_transport.submit(prompt, preparation.project_dir)
        _record_snapshot(run, snapshot)
        run["state"] = "submitted"
        _write_json_atomic(run_dir / "run.json", run)
        snapshot = await _poll_to_terminal(
            active_transport,
            run_dir,
            run,
            snapshot,
            poll_seconds,
            timeout_seconds,
        )
        return await _finish_terminal_run(
            preparation,
            root,
            run_dir,
            run,
            snapshot,
            active_transport,
            Path(template_root).resolve(),
            build_timeout_seconds,
            build_runner,
        )
    except GenerationError:
        resumable = GenerationResult(
            preparation.theorem_id,
            run["state"],
            run_dir,
            run["aristotle"]["project_id"],
            run["aristotle"]["task_id"],
            None,
        )
        _finalize_latest(root, resumable)
        raise
    except (AristotleTransportError, CandidateValidationError) as exc:
        if isinstance(exc, CandidateValidationError) and exc.build is not None:
            _write_build_log(run_dir / "build.log", exc.build)
        state = (
            "validation_failed"
            if isinstance(exc, CandidateValidationError)
            else "transport_error"
        )
        _record_error(run_dir, run, state, exc)
        result = GenerationResult(
            preparation.theorem_id,
            state,
            run_dir,
            run["aristotle"]["project_id"],
            run["aristotle"]["task_id"],
            None,
        )
        _finalize_latest(root, result)
        return result
    except Exception as exc:
        _record_error(run_dir, run, "internal_error", exc)
        raise GenerationError(str(exc), run_dir) from exc


async def resume_generation(
    run_input: str | Path,
    *,
    template_root: str | Path,
    poll_seconds: float = 30.0,
    timeout_seconds: float = 7200.0,
    build_timeout_seconds: int = 1800,
    transport: AristotleTransport | None = None,
    build_runner: BuildRunner = run_local_lean_check,
) -> GenerationResult:
    root, run_dir, run, preparation = _load_existing_run(run_input)
    if run.get("state") == "ready_for_review":
        return GenerationResult(
            preparation.theorem_id,
            "ready_for_review",
            run_dir,
            run["aristotle"]["project_id"],
            run["aristotle"]["task_id"],
            run_dir / "handoff.json",
        )
    if run.get("state") not in {
        "submitted",
        "running",
        "remote_running",
        "transport_error",
    }:
        raise GenerationError(
            f"generation state '{run.get('state')}' is not resumable", run_dir
        )
    project_id = run["aristotle"].get("project_id")
    task_id = run["aristotle"].get("task_id")
    if not project_id or not task_id:
        raise GenerationError("generation run has no resumable remote identifiers", run_dir)
    active_transport = _active_transport(transport)
    try:
        snapshot = await active_transport.get_task(project_id, task_id)
        run["error"] = None
        run["updated_at"] = _now()
        _write_json_atomic(run_dir / "run.json", run)
        snapshot = await _poll_to_terminal(
            active_transport,
            run_dir,
            run,
            snapshot,
            poll_seconds,
            timeout_seconds,
        )
        return await _finish_terminal_run(
            preparation,
            root,
            run_dir,
            run,
            snapshot,
            active_transport,
            Path(template_root).resolve(),
            build_timeout_seconds,
            build_runner,
        )
    except GenerationError:
        resumable = GenerationResult(
            preparation.theorem_id,
            run["state"],
            run_dir,
            project_id,
            task_id,
            None,
        )
        _finalize_latest(root, resumable)
        raise
    except (AristotleTransportError, CandidateValidationError) as exc:
        if isinstance(exc, CandidateValidationError) and exc.build is not None:
            _write_build_log(run_dir / "build.log", exc.build)
        state = (
            "validation_failed"
            if isinstance(exc, CandidateValidationError)
            else "transport_error"
        )
        _record_error(run_dir, run, state, exc)
        result = GenerationResult(
            preparation.theorem_id,
            state,
            run_dir,
            project_id,
            task_id,
            None,
        )
        _finalize_latest(root, result)
        return result
    except Exception as exc:
        _record_error(run_dir, run, "internal_error", exc)
        raise GenerationError(str(exc), run_dir) from exc
