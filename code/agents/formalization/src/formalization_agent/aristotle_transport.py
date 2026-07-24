from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class AristotleTransportError(RuntimeError):
    """Raised for sanitized Aristotle SDK transport failures."""


@dataclass(frozen=True)
class RemoteTaskSnapshot:
    project_id: str
    task_id: str
    status: str
    percent_complete: int | None
    created_at: str | None = None
    last_updated_at: str | None = None


class AristotleTransport(Protocol):
    async def submit(
        self, prompt: str, project_dir: Path
    ) -> RemoteTaskSnapshot: ...

    async def get_task(
        self, project_id: str, task_id: str
    ) -> RemoteTaskSnapshot: ...

    async def download_result(self, project_id: str, destination: Path) -> Path: ...


class SDKAristotleTransport:
    """Non-interactive adapter for the pinned aristotlelib 2.1.0 SDK."""

    async def submit(self, prompt: str, project_dir: Path) -> RemoteTaskSnapshot:
        try:
            from aristotlelib.project import AgentQuestionsSetting, Project

            project = await Project.create_from_directory(
                prompt=prompt,
                project_dir=project_dir,
                agent_questions_setting=AgentQuestionsSetting.DISABLED,
            )
            tasks = []
            for retry in range(10):
                tasks, _ = await project.get_tasks(limit=1)
                if tasks:
                    break
                await asyncio.sleep(min(retry + 1, 5))
            if not tasks:
                raise AristotleTransportError(
                    "Aristotle created a project but returned no task"
                )
            task = tasks[0]
            return _snapshot(task)
        except AristotleTransportError:
            raise
        except Exception as exc:
            raise AristotleTransportError(_sanitize_exception(exc)) from exc

    async def get_task(
        self, project_id: str, task_id: str
    ) -> RemoteTaskSnapshot:
        try:
            from aristotlelib.agent_task import AgentTask

            task = await AgentTask.from_id(task_id)
            if task.project_id != project_id:
                raise AristotleTransportError(
                    "Aristotle task belongs to a different project"
                )
            return _snapshot(task)
        except AristotleTransportError:
            raise
        except Exception as exc:
            raise AristotleTransportError(_sanitize_exception(exc)) from exc

    async def download_result(self, project_id: str, destination: Path) -> Path:
        try:
            from aristotlelib.project import Project

            project = await Project.from_id(project_id)
            if not project.has_files:
                raise AristotleTransportError(
                    "Aristotle project has no generated result files"
                )
            return await project.get_files(destination=destination)
        except AristotleTransportError:
            raise
        except Exception as exc:
            raise AristotleTransportError(_sanitize_exception(exc)) from exc


def _snapshot(task: object) -> RemoteTaskSnapshot:
    status = getattr(getattr(task, "status", None), "name", "UNKNOWN")
    created = getattr(task, "created_at", None)
    updated = getattr(task, "last_updated_at", None)
    return RemoteTaskSnapshot(
        project_id=str(getattr(task, "project_id")),
        task_id=str(getattr(task, "agent_task_id")),
        status=str(status),
        percent_complete=getattr(task, "percent_complete", None),
        created_at=created.isoformat() if created else None,
        last_updated_at=updated.isoformat() if updated else None,
    )


def _sanitize_exception(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return f"{type(exc).__name__} (HTTP {status_code}): {exc}"
    return f"{type(exc).__name__}: {exc}"
