from __future__ import annotations

import asyncio
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from formalization_agent.aristotle_transport import (
    RemoteTaskSnapshot,
    SDKAristotleTransport,
)
from formalization_agent.candidate_validation import (
    BuildOutcome,
    CandidateValidationError,
    safe_extract_tar,
    strip_lean_comments_and_strings,
    validate_candidate,
)
from formalization_agent.generator import (
    GenerationError,
    generate_proof,
    resume_generation,
)
from formalization_agent.preparation_reader import (
    PreparationReadError,
    load_preparation,
)
from formalization_agent.preparer import prepare_formalization

from test_preparation import FORMALIZATION_ROOT, _valid_payload, _write_package


def _successful_build(
    project_root: Path,
    main_path: Path,
    template_root: Path,
    timeout_seconds: int,
) -> BuildOutcome:
    del project_root, main_path, template_root, timeout_seconds
    return BuildOutcome(
        command=["lean", "Main.lean"],
        exit_code=0,
        timed_out=False,
        duration_seconds=0.01,
        stdout="",
        stderr="",
    )


def _result_archive(prepared_project: Path, archive_path: Path) -> None:
    candidate = archive_path.parent / "candidate"
    shutil.copytree(prepared_project, candidate)
    (candidate / "Main.lean").write_text(
        "import Mathlib.Data.Real.Basic\n\n"
        "theorem generated_demo : True := by\n"
        "  trivial\n",
        encoding="utf-8",
    )
    (candidate / "FORMALIZATION_NOTES.md").write_text(
        "# Formalization notes\n\nGenerated independently.\n",
        encoding="utf-8",
    )
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in candidate.rglob("*"):
            if path.is_file():
                archive.add(path, arcname=path.relative_to(candidate).as_posix())


class FakeTransport:
    def __init__(self, archive_bytes: bytes) -> None:
        self.archive_bytes = archive_bytes
        self.snapshots = [
            RemoteTaskSnapshot("project-1", "task-1", "IN_PROGRESS", 50),
            RemoteTaskSnapshot("project-1", "task-1", "COMPLETE", 100),
        ]
        self.submit_calls = 0
        self.download_calls = 0

    async def submit(
        self, prompt: str, project_dir: Path
    ) -> RemoteTaskSnapshot:
        self.submit_calls += 1
        self.submitted_prompt = prompt
        self.submitted_project_dir = project_dir
        return RemoteTaskSnapshot("project-1", "task-1", "QUEUED", 0)

    async def get_task(
        self, project_id: str, task_id: str
    ) -> RemoteTaskSnapshot:
        self.last_ids = (project_id, task_id)
        return self.snapshots.pop(0)

    async def download_result(self, project_id: str, destination: Path) -> Path:
        self.download_calls += 1
        self.downloaded_project_id = project_id
        destination.write_bytes(self.archive_bytes)
        return destination


class PreparationReaderTests(unittest.TestCase):
    def test_loads_and_verifies_preparation_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, extraction = _write_package(root / "input", _valid_payload())
            prepared = prepare_formalization(
                extraction,
                output_root=root / "output",
                template_root=FORMALIZATION_ROOT,
            )
            loaded = load_preparation(prepared.attempt_dir.parent)
            self.assertEqual(loaded.theorem_id, prepared.theorem_id)
            self.assertEqual(
                loaded.request["aristotle"]["agent_questions_setting"],
                "DISABLED",
            )

            loaded.prompt_path.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(PreparationReadError, "modified"):
                load_preparation(prepared.attempt_dir)


class TransportTests(unittest.TestCase):
    def test_sdk_submission_disables_agent_questions(self) -> None:
        from aristotlelib.project import AgentQuestionsSetting, Project

        task = SimpleNamespace(
            project_id="project-1",
            agent_task_id="task-1",
            status=SimpleNamespace(name="QUEUED"),
            percent_complete=0,
            created_at=None,
            last_updated_at=None,
        )
        project = SimpleNamespace(get_tasks=AsyncMock(return_value=([task], None)))
        create = AsyncMock(return_value=project)
        with patch.object(Project, "create_from_directory", new=create):
            snapshot = asyncio.run(
                SDKAristotleTransport().submit("prove it", Path("."))
            )

        self.assertEqual(snapshot.status, "QUEUED")
        self.assertEqual(
            create.await_args.kwargs["agent_questions_setting"],
            AgentQuestionsSetting.DISABLED,
        )


class ArchiveAndLeanScanTests(unittest.TestCase):
    def test_safe_extract_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "bad.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("../escape.txt")
                content = b"escape"
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            with self.assertRaisesRegex(CandidateValidationError, "unsafe"):
                safe_extract_tar(archive_path, root / "result")
            self.assertFalse((root / "escape.txt").exists())

    def test_scanner_ignores_comments_and_strings_but_not_code(self) -> None:
        harmless = """
        /- Nested /- sorry -/ comment -/
        def message := "admit and sorryAx"
        theorem good : True := by trivial
        """
        stripped = strip_lean_comments_and_strings(harmless)
        self.assertNotIn("sorry", stripped)
        self.assertIn("theorem good", stripped)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = root / "prepared"
            candidate = root / "candidate"
            prepared.mkdir()
            candidate.mkdir()
            artifacts = {}
            for name in (
                "SOURCE_THEOREM.md",
                "lean-toolchain",
                "lakefile.toml",
                "lake-manifest.json",
            ):
                (prepared / name).write_text(name, encoding="utf-8")
                shutil.copy2(prepared / name, candidate / name)
                artifacts[f"project/{name}"] = hashlib.sha256(
                    (prepared / name).read_bytes()
                ).hexdigest()
            (prepared / "Main.lean").write_text("import Mathlib\n", encoding="utf-8")
            artifacts["project/Main.lean"] = hashlib.sha256(
                (prepared / "Main.lean").read_bytes()
            ).hexdigest()
            (candidate / "Main.lean").write_text(
                "theorem bad : True := by sorry\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(CandidateValidationError, "placeholder"):
                validate_candidate(
                    candidate,
                    prepared,
                    artifacts,
                    FORMALIZATION_ROOT,
                    1,
                    _successful_build,
                )


class GenerationTests(unittest.TestCase):
    def test_noninteractive_generation_creates_agent3_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, extraction = _write_package(root / "input", _valid_payload())
            prepared = prepare_formalization(
                extraction,
                output_root=root / "output",
                template_root=FORMALIZATION_ROOT,
            )
            archive_path = root / "fixture-result.tar.gz"
            _result_archive(prepared.project_dir, archive_path)
            transport = FakeTransport(archive_path.read_bytes())

            generated = asyncio.run(
                generate_proof(
                    prepared.attempt_dir,
                    template_root=FORMALIZATION_ROOT,
                    generation_root=root / "generation",
                    poll_seconds=0,
                    timeout_seconds=10,
                    build_timeout_seconds=10,
                    transport=transport,
                    build_runner=_successful_build,
                )
            )

            self.assertEqual(generated.state, "ready_for_review")
            self.assertEqual(transport.submit_calls, 1)
            self.assertEqual(transport.download_calls, 1)
            self.assertTrue(generated.handoff_path and generated.handoff_path.is_file())
            handoff = json.loads(generated.handoff_path.read_text(encoding="utf-8"))
            self.assertEqual(handoff["review"]["owner"], "agent3")
            self.assertEqual(
                handoff["review"]["questioning_loop_owner"], "agent3"
            )
            run = json.loads(
                (generated.run_dir / "run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                run["aristotle"]["agent_questions_setting"], "DISABLED"
            )
            self.assertNotIn("api_key", json.dumps(run).lower())
            self.assertTrue((generated.run_dir / "build.log").is_file())

    def test_modified_protected_file_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, extraction = _write_package(root / "input", _valid_payload())
            prepared = prepare_formalization(
                extraction,
                output_root=root / "output",
                template_root=FORMALIZATION_ROOT,
            )
            candidate = root / "candidate"
            shutil.copytree(prepared.project_dir, candidate)
            (candidate / "Main.lean").write_text(
                "theorem generated_demo : True := by trivial\n", encoding="utf-8"
            )
            (candidate / "lean-toolchain").write_text(
                "leanprover/lean4:nightly\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(CandidateValidationError, "modified"):
                validate_candidate(
                    candidate,
                    prepared.project_dir,
                    load_preparation(prepared.attempt_dir).artifact_hashes,
                    FORMALIZATION_ROOT,
                    10,
                    _successful_build,
                )

    def test_timed_out_generation_can_resume_without_resubmission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, extraction = _write_package(root / "input", _valid_payload())
            prepared = prepare_formalization(
                extraction,
                output_root=root / "output",
                template_root=FORMALIZATION_ROOT,
            )
            archive_path = root / "fixture-result.tar.gz"
            _result_archive(prepared.project_dir, archive_path)
            generation_root = root / "generation"
            first_transport = FakeTransport(archive_path.read_bytes())
            with self.assertRaisesRegex(GenerationError, "resumable"):
                asyncio.run(
                    generate_proof(
                        prepared.attempt_dir,
                        template_root=FORMALIZATION_ROOT,
                        generation_root=generation_root,
                        poll_seconds=0,
                        timeout_seconds=0,
                        build_timeout_seconds=10,
                        transport=first_transport,
                        build_runner=_successful_build,
                    )
                )

            run = json.loads(
                (generation_root / "attempt-001" / "run.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(run["state"], "remote_running")
            second_transport = FakeTransport(archive_path.read_bytes())
            second_transport.snapshots = [
                RemoteTaskSnapshot("project-1", "task-1", "COMPLETE", 100)
            ]
            resumed = asyncio.run(
                resume_generation(
                    generation_root / "latest.json",
                    template_root=FORMALIZATION_ROOT,
                    poll_seconds=0,
                    timeout_seconds=10,
                    build_timeout_seconds=10,
                    transport=second_transport,
                    build_runner=_successful_build,
                )
            )
            self.assertEqual(resumed.state, "ready_for_review")
            self.assertEqual(
                first_transport.submit_calls,
                1,
                "resuming must not create a second Aristotle project",
            )
            self.assertEqual(second_transport.submit_calls, 0)


if __name__ == "__main__":
    unittest.main()
