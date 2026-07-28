from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from formalization_agent.generator import GenerationResult
from formalization_agent.candidate_validation import BuildRunner, run_local_lean_check
from formalization_agent.revision_validation import validate_revision_archive

from .models import RevisionRequest
from .reader import load_candidate


class RevisionError(RuntimeError):
    """Raised when an Agent 3 revision cannot reach Agent 2 validation."""


@dataclass(frozen=True)
class RemoteRevision:
    project_id: str
    task_id: str
    status: str
    archive_path: Path
    status_history: list[dict[str, Any]]


@dataclass(frozen=True)
class RevisionResult:
    attempt_dir: Path
    remote: RemoteRevision
    generation: GenerationResult
    request_kind: str
    request_path: Path


class RevisionTransport(Protocol):
    async def revise(
        self,
        request: RevisionRequest,
        *,
        output_dir: Path,
        poll_seconds: float,
        timeout_seconds: float,
    ) -> RemoteRevision: ...


def _has_downloadable_output(status: str, file_name: object) -> bool:
    """Allow a non-clean remote completion only when it produced an archive.

    Aristotle can report ``COMPLETE_WITH_ERRORS`` after Lean work completed, or
    leave a useful incremental checkpoint when a follow-up reaches
    ``OUT_OF_BUDGET``. Such output is never trusted directly: it is merely
    downloaded and remains subject to the complete Agent 2 local validation
    gate and a fresh Agent 3 review.
    """

    return status == "COMPLETE" or (
        status in {"COMPLETE_WITH_ERRORS", "OUT_OF_BUDGET"}
        and isinstance(file_name, str)
        and bool(file_name.strip())
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _redact_runtime_secret(message: str) -> str:
    api_key = os.environ.get("ARISTOTLE_API_KEY")
    return message.replace(api_key, "<redacted>") if api_key else message


def revision_prompt(request: RevisionRequest) -> str:
    issue_lines = "\n".join(
        f"- [{issue.code}/{issue.aspect}] {issue.explanation}\n"
        f"  Required correction: {issue.revision_instruction}"
        for issue in request.issues
    )
    instructions = "\n".join(f"- {item}" for item in request.instructions)
    constraints = "\n".join(f"- {item}" for item in request.constraints)
    return f"""Agent 3 rejected the current Lean candidate for theorem
`{request.theorem_id}`. Revise the existing project files in place.

Review issues:
{issue_lines}

Required changes:
{instructions}

Hard constraints:
{constraints}

Read the protected SOURCE_THEOREM.md only to implement these corrections.
Do not alter SOURCE_THEOREM.md, lean-toolchain, lakefile.toml, or
lake-manifest.json. Do not ask questions. Finish with a complete locally
buildable Main.lean.
"""


def _failed_candidate_fingerprint(run_dir: Path) -> str:
    """Hash the rejected Lean checkpoint so repeated no-op repairs are visible."""
    lean_files = sorted(
        (
            path
            for path in run_dir.rglob("*.lean")
            if ".lake" not in path.parts
        ),
        key=lambda path: path.relative_to(run_dir).as_posix(),
    )
    digest = hashlib.sha256()
    if lean_files:
        for path in lean_files:
            relative = path.relative_to(run_dir).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            content = path.read_bytes()
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return digest.hexdigest()
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8-sig"))
    archive_hash = run.get("result", {}).get("archive_sha256", "")
    digest.update(str(archive_hash).encode("utf-8"))
    return digest.hexdigest()


def next_validation_repair_number(base_request_input: str | Path) -> int:
    request_dir = Path(base_request_input).resolve().parent
    numbers: list[int] = []
    for path in request_dir.glob("validation-repair-*.json"):
        suffix = path.stem.removeprefix("validation-repair-")
        if suffix.isdigit() and int(suffix) > 0:
            numbers.append(int(suffix))
    return max(numbers, default=0) + 1


def write_validation_repair_request(
    base_request_input: str | Path,
    failed_generation: GenerationResult,
    *,
    repair_number: int,
    previous_fingerprints: set[str] | None = None,
    build_log_limit: int = 12000,
) -> tuple[Path, str]:
    """Create a hash-bound follow-up for an Agent 2 validation failure."""
    if repair_number < 1:
        raise RevisionError("validation repair number must be positive")
    base_path = Path(base_request_input).resolve()
    try:
        base = RevisionRequest.model_validate_json(
            base_path.read_text(encoding="utf-8-sig")
        )
        run_path = failed_generation.run_dir / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RevisionError(f"cannot prepare Agent 2 validation repair: {exc}") from exc
    if (
        failed_generation.state != "validation_failed"
        or run.get("state") != "validation_failed"
    ):
        raise RevisionError(
            "Agent 2 validation repair requires a validation_failed generation"
        )
    if (
        run.get("theorem_id") != base.theorem_id
        or failed_generation.theorem_id != base.theorem_id
    ):
        raise RevisionError("failed generation theorem_id does not match review")
    project_id = run.get("aristotle", {}).get("project_id")
    task_id = run.get("aristotle", {}).get("task_id")
    if (
        project_id != base.current_project_id
        or project_id != failed_generation.project_id
        or task_id != failed_generation.task_id
        or not isinstance(task_id, str)
        or not task_id
    ):
        raise RevisionError("failed generation Aristotle lineage is inconsistent")

    error = run.get("error", {})
    error_message = (
        str(error.get("message", "Agent 2 validation failed"))
        if isinstance(error, dict)
        else "Agent 2 validation failed"
    )
    build_path = failed_generation.run_dir / "build.log"
    build_excerpt = ""
    if build_path.is_file():
        build_excerpt = build_path.read_text(
            encoding="utf-8-sig", errors="replace"
        )[-build_log_limit:]
    fingerprint = _failed_candidate_fingerprint(failed_generation.run_dir)
    repeated = fingerprint in (previous_fingerprints or set())
    diagnostics = [f"Agent 2 error: {error_message}"]
    if build_excerpt:
        diagnostics.append(
            "Tail of Agent 2's pinned Lean build log:\n" + build_excerpt
        )
    if repeated:
        diagnostics.append(
            "The rejected Lean sources are byte-identical to an earlier failed "
            "checkpoint. Make a concrete source change; do not return the same files."
        )

    repair = RevisionRequest(
        theorem_id=base.theorem_id,
        review_attempt=base.review_attempt,
        review_json_sha256=base.review_json_sha256,
        source_theorem_json_sha256=base.source_theorem_json_sha256,
        candidate_main_sha256=base.candidate_main_sha256,
        current_project_id=base.current_project_id,
        current_task_id=task_id,
        issues=[
            {
                "code": "agent2_validation_failed",
                "severity": "error",
                "aspect": "other",
                "explanation": error_message,
                "revision_instruction": (
                    "Repair the current remote Lean checkpoint so it passes every "
                    "Agent 2 local validation gate. Use the supplied build diagnostics, "
                    "preserve the Agent 3 semantic corrections, and return a genuinely "
                    "changed project when the previous checkpoint made no progress."
                ),
            }
        ],
        instructions=[
            "Continue from the current failed Aristotle checkpoint; do not restart "
            "from the original candidate.",
            "Preserve every semantic and proof-method correction required by the "
            "originating Agent 3 review.",
            *diagnostics,
            "Run the pinned Lean build before finishing and return a placeholder-free "
            "project.",
        ],
        constraints=list(
            dict.fromkeys(
                [
                    *base.constraints,
                    "Do not weaken or remove an already completed theorem or helper proof.",
                    "Do not undo the originating Agent 3 statement or proof-method corrections.",
                ]
            )
        ),
    )
    output_path = base_path.parent / f"validation-repair-{repair_number:03d}.json"
    serialized = (
        json.dumps(
            repair.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if output_path.exists():
        if output_path.read_text(encoding="utf-8-sig") != serialized:
            raise RevisionError(
                f"validation repair request already exists with different content: "
                f"{output_path}"
            )
    else:
        temporary = output_path.parent / f".{output_path.name}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(output_path)
    return output_path, fingerprint


class SDKRevisionTransport:
    def __init__(self, *, resume_task_id: str | None = None) -> None:
        self.resume_task_id = resume_task_id

    async def revise(
        self,
        request: RevisionRequest,
        *,
        output_dir: Path,
        poll_seconds: float,
        timeout_seconds: float,
    ) -> RemoteRevision:
        if not os.environ.get("ARISTOTLE_API_KEY"):
            raise RevisionError("ARISTOTLE_API_KEY is not set")
        try:
            from aristotlelib.agent_task import AgentTask
            from aristotlelib.project import (
                AgentQuestionsSetting,
                FollowUpMode,
                Project,
            )

            project = await Project.from_id(request.current_project_id)
            if self.resume_task_id:
                task = await AgentTask.from_id(self.resume_task_id)
                task_project_id = getattr(task, "project_id", None)
                if (
                    task_project_id is not None
                    and str(task_project_id) != request.current_project_id
                ):
                    raise RevisionError(
                        "resume task does not belong to the reviewed Aristotle project"
                    )
            else:
                task = await project.ask(
                    prompt=revision_prompt(request),
                    mode=FollowUpMode.INSTRUCT,
                    agent_questions_setting=AgentQuestionsSetting.DISABLED,
                )
            started = time.monotonic()
            history: list[dict[str, Any]] = []
            progress_path = output_dir / "remote-progress.json"
            terminal = {
                "COMPLETE",
                "COMPLETE_WITH_ERRORS",
                "OUT_OF_BUDGET",
                "FAILED",
                "CANCELED",
            }
            while True:
                status = task.status.name
                entry = {
                    "observed_at": _now(),
                    "status": status,
                    "percent_complete": task.percent_complete,
                }
                if not history or (
                    history[-1]["status"],
                    history[-1]["percent_complete"],
                ) != (entry["status"], entry["percent_complete"]):
                    history.append(entry)
                    progress_path.write_text(
                        json.dumps(
                            {
                                "schema_version": "1.0",
                                "project_id": request.current_project_id,
                                "task_id": str(task.agent_task_id),
                                "status_history": history,
                            },
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                if status in terminal:
                    break
                if time.monotonic() - started >= timeout_seconds:
                    raise RevisionError(
                        "Agent 3 revision polling timed out; remote task remains resumable"
                    )
                await asyncio.sleep(poll_seconds)
                task = await AgentTask.from_id(task.agent_task_id)
            if not _has_downloadable_output(
                status, getattr(task, "file_name", None)
            ):
                raise RevisionError(f"Aristotle revision ended with status {status}")
            output_dir.mkdir(parents=True, exist_ok=True)
            archive = output_dir / "result.tar.gz"
            await project.get_files(destination=archive)
            return RemoteRevision(
                project_id=request.current_project_id,
                task_id=str(task.agent_task_id),
                status=status,
                archive_path=archive,
                status_history=history,
            )
        except RevisionError:
            raise
        except Exception as exc:
            message = _redact_runtime_secret(str(exc))
            raise RevisionError(f"{type(exc).__name__}: {message}") from exc


def _next_attempt(root: Path) -> int:
    attempts = []
    if root.is_dir():
        for child in root.iterdir():
            if child.is_dir() and child.name.startswith("attempt-"):
                suffix = child.name.removeprefix("attempt-")
                if suffix.isdigit():
                    attempts.append(int(suffix))
    return max(attempts, default=0) + 1


async def revise_and_validate(
    handoff_input: str | Path,
    revision_request_input: str | Path,
    *,
    transport: RevisionTransport,
    template_root: str | Path,
    revision_root: str | Path,
    poll_seconds: float = 30.0,
    timeout_seconds: float = 7200.0,
    build_timeout_seconds: int = 1800,
    build_runner: BuildRunner = run_local_lean_check,
    request_kind: str = "semantic_revision",
) -> RevisionResult:
    candidate = load_candidate(handoff_input)
    request_path = Path(revision_request_input).resolve()
    try:
        request = RevisionRequest.model_validate_json(
            request_path.read_text(encoding="utf-8-sig")
        )
    except Exception as exc:
        raise RevisionError(f"invalid revision request: {exc}") from exc
    if request.theorem_id != candidate.theorem_id:
        raise RevisionError("revision request theorem_id does not match handoff")
    if request.current_project_id != candidate.handoff["agent2_run"]["project_id"]:
        raise RevisionError("revision request project_id does not match handoff")

    root = Path(revision_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    attempt = _next_attempt(root)
    attempt_name = f"attempt-{attempt:03d}"
    attempt_dir = root / attempt_name
    staging = root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        remote = await transport.revise(
            request,
            output_dir=staging,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
        )
        (staging / "remote.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "project_id": remote.project_id,
                    "task_id": remote.task_id,
                    "status": remote.status,
                    "status_history": remote.status_history,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        validated = validate_revision_archive(
            candidate.run_path,
            request_path,
            remote.archive_path,
            project_id=remote.project_id,
            task_id=remote.task_id,
            template_root=template_root,
            build_timeout_seconds=build_timeout_seconds,
            build_runner=build_runner,
        )
        (staging / "agent2-validation.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "request_kind": request_kind,
                    "request_path": str(request_path),
                    "state": validated.generation.state,
                    "agent2_run_dir": str(validated.generation.run_dir),
                    "agent2_handoff_path": (
                        str(validated.generation.handoff_path)
                        if validated.generation.handoff_path
                        else None
                    ),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        staging.replace(attempt_dir)
    except Exception as exc:
        if staging.exists() and not (staging / "remote-progress.json").is_file():
            shutil.rmtree(staging)
        if staging.exists():
            raise RevisionError(
                f"{exc}; resumable revision state: {staging}"
            ) from exc
        raise
    return RevisionResult(
        attempt_dir=attempt_dir,
        remote=remote,
        generation=validated.generation,
        request_kind=request_kind,
        request_path=request_path,
    )
