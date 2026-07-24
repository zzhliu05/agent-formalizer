from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

from formalization_agent.candidate_validation import BuildOutcome
from formalization_agent.preparer import prepare_formalization

from review_agent.loop import run_review_loop
from review_agent.models import (
    BlindBacktranslation,
    ComparisonIssue,
    SemanticComparison,
)
from review_agent.prompts import blind_translation_prompt
from review_agent.provider import ProviderResult
from review_agent.reader import ReviewReadError, load_candidate
from review_agent.reviewer import review_candidate
from review_agent.revision import RemoteRevision

FORMALIZATION_ROOT = Path(__file__).resolve().parents[2] / "formalization"
SOURCE_SENTINEL = "SOURCE-ONLY-SENTINEL"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_payload(*, proof_status: str = "complete") -> dict[str, object]:
    complete = proof_status == "complete"
    return {
        "schema_version": "1.0",
        "theorem_id": "review-demo-theorem",
        "document_id": "review-demo",
        "extraction_run_id": "run-001",
        "source": {
            "markdown_file": "chunk.md",
            "markdown_sha256": "a" * 64,
            "pdf_pages": [1],
            "overlap_variant": False,
        },
        "result": {
            "source_pages": [1],
            "kind": "theorem",
            "label_verbatim": "Demo Theorem.",
            "title_verbatim": "",
            "statement_verbatim": f"Demo Theorem. {SOURCE_SENTINEL}",
            "proof_status": proof_status,
            "proof_verbatim": "Proof. The claim is immediate.",
            "proof_steps": [
                {
                    "order": 1,
                    "role": "conclusion",
                    "text_verbatim": "Proof. The claim is immediate.",
                    "source_pages": [1],
                }
            ],
            "omission": {
                "is_omitted": not complete,
                "reason": "other" if not complete else "none",
                "marker_verbatim": "details omitted" if not complete else "",
                "note": "The printed source omits details." if not complete else "",
            },
            "context_items": [],
            "uncertainties": [],
            "confidence": 1.0,
            "record_complete_in_chunk": True,
            "boundary_note": "",
        },
        "provider": {
            "request_id": None,
            "requested_model": None,
            "resolved_model": None,
            "deployment": None,
            "finish_reason": None,
            "usage": None,
        },
    }


def _write_source(root: Path, *, proof_status: str = "complete") -> Path:
    theorem_root = root / "source" / "review-demo-theorem"
    attempt = theorem_root / "extraction" / "attempt-001"
    attempt.mkdir(parents=True)
    theorem_bytes = (
        json.dumps(
            _source_payload(proof_status=proof_status),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    (attempt / "theorem.json").write_bytes(theorem_bytes)
    (attempt / "context.md").write_text("# Context\n\nNone.\n", encoding="utf-8")
    (attempt / "source.txt").write_text(
        f"Demo Theorem. {SOURCE_SENTINEL}\n", encoding="utf-8"
    )
    (theorem_root / "extraction" / "latest.json").write_text(
        json.dumps(
            {
                "theorem_id": "review-demo-theorem",
                "attempt": 1,
                "path": "attempt-001/theorem.json",
                "theorem_json_sha256": _sha(theorem_bytes),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return theorem_root


def _write_ready_handoff(
    root: Path,
    source_root: Path,
    *,
    main_source: str = (
        "import Mathlib.Data.Real.Basic\n\n"
        "theorem generated_demo : True := by\n"
        "  trivial\n"
    ),
) -> tuple[Path, Path]:
    prepared = prepare_formalization(
        source_root,
        output_root=root / "pipeline",
        template_root=FORMALIZATION_ROOT,
    )
    generation = (
        root
        / "pipeline"
        / "review-demo-theorem"
        / "formalization"
        / "generation"
        / "attempt-001"
    )
    project = generation / "result" / "project_aristotle"
    shutil.copytree(prepared.project_dir, project)
    (project / "Main.lean").write_text(main_source, encoding="utf-8")
    main_hash = _sha((project / "Main.lean").read_bytes())
    request_ref = os.path.relpath(prepared.request_path, generation).replace("\\", "/")
    run = {
        "schema_version": "1.0",
        "state": "ready_for_review",
        "theorem_id": "review-demo-theorem",
        "preparation": {
            "request_path": request_ref,
            "request_sha256": prepared.request_sha256,
        },
        "aristotle": {
            "project_id": "project-1",
            "task_id": "task-1",
            "task_status": "COMPLETE",
        },
        "validation": {
            "local_lean_check": "passed",
            "placeholder_scan": "passed",
            "protected_files": "unchanged",
            "main_path": "result/project_aristotle/Main.lean",
            "lean_file_hashes": {"Main.lean": main_hash},
            "build_log": "build.log",
        },
    }
    generation.mkdir(parents=True, exist_ok=True)
    (generation / "run.json").write_text(
        json.dumps(run, indent=2) + "\n", encoding="utf-8"
    )
    source_latest = json.loads(
        (source_root / "extraction" / "latest.json").read_text(encoding="utf-8")
    )
    handoff = {
        "schema_version": "1.0",
        "state": "ready_for_review",
        "theorem_id": "review-demo-theorem",
        "agent2_run": {
            "run_json": "run.json",
            "project_id": "project-1",
            "task_id": "task-1",
        },
        "source": {
            "preparation_request_sha256": prepared.request_sha256,
            "agent1_theorem_json_sha256": source_latest[
                "theorem_json_sha256"
            ],
        },
        "candidate": {
            "project_root": "result/project_aristotle",
            "main_path": "result/project_aristotle/Main.lean",
            "lean_file_hashes": {"Main.lean": main_hash},
            "build_log": "build.log",
        },
        "review": {
            "owner": "agent3",
            "questioning_loop_owner": "agent3",
            "semantic_verdict": "pending",
        },
    }
    (generation / "handoff.json").write_text(
        json.dumps(handoff, indent=2) + "\n", encoding="utf-8"
    )
    return generation / "handoff.json", prepared.project_dir


def _successful_build(
    project_root: Path,
    main_path: Path,
    template_root: Path,
    timeout_seconds: int,
) -> BuildOutcome:
    del project_root, template_root, timeout_seconds
    stdout = ""
    if main_path.name == "Agent3AxiomAudit.lean":
        stdout = (
            "'generated_demo' depends on axioms: "
            "[propext, Classical.choice, Quot.sound]\n"
        )
    return BuildOutcome(
        command=["lean", main_path.name],
        exit_code=0,
        timed_out=False,
        duration_seconds=0.01,
        stdout=stdout,
        stderr="",
    )


def _backtranslation() -> BlindBacktranslation:
    return BlindBacktranslation(
        declaration_names=["generated_demo"],
        statement_natural_language="The proposition True holds.",
        variables_and_domains=[],
        hypotheses=[],
        conclusion="True",
        proof_method_summary="Close the goal by the trivial constructor.",
        proof_steps=["Apply the constructor of True."],
        lean_dependencies=[],
        axioms_observed=["propext", "Classical.choice", "Quot.sound"],
        ambiguity_notes=[],
        confidence=1.0,
    )


def _comparison(verdict: str) -> SemanticComparison:
    if verdict == "accepted":
        return SemanticComparison(
            statement_match=True,
            variables_match=True,
            domains_match=True,
            hypotheses_match=True,
            quantifiers_match=True,
            conclusion_match=True,
            logical_direction_match=True,
            edge_cases_match=True,
            proof_method_match="match",
            proof_step_correspondence=["The sole source step matches trivial."],
            source_proof_complete=True,
            issues=[],
            verdict="accepted",
            rationale="The statement and proof method match.",
        )
    if verdict == "needs_reextraction":
        return SemanticComparison(
            statement_match=True,
            variables_match=True,
            domains_match=True,
            hypotheses_match=True,
            quantifiers_match=True,
            conclusion_match=True,
            logical_direction_match=True,
            edge_cases_match=True,
            proof_method_match="unverifiable",
            proof_step_correspondence=[],
            source_proof_complete=False,
            issues=[
                ComparisonIssue(
                    code="source_method_incomplete",
                    severity="error",
                    aspect="source_completeness",
                    explanation="The source does not print a complete proof.",
                    revision_instruction="Recover a complete source proof if available.",
                )
            ],
            verdict="needs_reextraction",
            rationale="Exact method agreement cannot be established.",
        )
    return SemanticComparison(
        statement_match=False,
        variables_match=True,
        domains_match=True,
        hypotheses_match=True,
        quantifiers_match=True,
        conclusion_match=False,
        logical_direction_match=True,
        edge_cases_match=True,
        proof_method_match="mismatch",
        proof_step_correspondence=[],
        source_proof_complete=True,
        issues=[
            ComparisonIssue(
                code="wrong_conclusion",
                severity="error",
                aspect="conclusion",
                explanation="The Lean conclusion differs from the source.",
                revision_instruction="Change the Lean conclusion to match the source exactly.",
            )
        ],
        verdict="needs_reformalization",
        rationale="The candidate conclusion is wrong.",
    )


class FakeProvider:
    def __init__(self, verdicts: list[str]) -> None:
        self.verdicts = verdicts
        self.backtranslation_inputs: list[dict[str, str]] = []
        self.comparison_calls = 0

    def backtranslate(
        self,
        *,
        lean_sources: dict[str, str],
        declaration_names: list[str],
        axiom_output: str,
    ) -> ProviderResult:
        del declaration_names, axiom_output
        self.backtranslation_inputs.append(lean_sources)
        assert SOURCE_SENTINEL not in json.dumps(lean_sources)
        return ProviderResult(_backtranslation(), {"request_id": "blind-1"})

    def compare(self, backtranslation: BlindBacktranslation, **_: object) -> ProviderResult:
        del backtranslation
        verdict = self.verdicts[min(self.comparison_calls, len(self.verdicts) - 1)]
        self.comparison_calls += 1
        return ProviderResult(_comparison(verdict), {"request_id": "compare-1"})


def _archive_project(project: Path, destination: Path) -> bytes:
    candidate = destination / "revised-project"
    shutil.copytree(project, candidate)
    (candidate / "Main.lean").write_text(
        "import Mathlib.Data.Real.Basic\n\n"
        "theorem generated_demo : True := by\n"
        "  trivial\n",
        encoding="utf-8",
    )
    archive_path = destination / "fixture.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in candidate.rglob("*"):
            if path.is_file():
                archive.add(path, arcname=path.relative_to(candidate).as_posix())
    return archive_path.read_bytes()


class FakeRevisionTransport:
    def __init__(self, archive_bytes: bytes) -> None:
        self.archive_bytes = archive_bytes
        self.calls = 0

    async def revise(
        self,
        request: object,
        *,
        output_dir: Path,
        poll_seconds: float,
        timeout_seconds: float,
    ) -> RemoteRevision:
        del request, poll_seconds, timeout_seconds
        self.calls += 1
        output_dir.mkdir(parents=True, exist_ok=True)
        archive = output_dir / "result.tar.gz"
        archive.write_bytes(self.archive_bytes)
        return RemoteRevision(
            project_id="project-1",
            task_id=f"revision-task-{self.calls}",
            status="COMPLETE",
            archive_path=archive,
            status_history=[
                {
                    "observed_at": "2026-07-25T00:00:00+00:00",
                    "status": "COMPLETE",
                    "percent_complete": 100,
                }
            ],
        )


class ReviewAgentTests(unittest.TestCase):
    def test_blind_prompt_contains_no_source_statement(self) -> None:
        prompt = blind_translation_prompt(
            {"Main.lean": "theorem demo : True := by trivial"},
            ["demo"],
            "'demo' depends on axioms: []",
        )
        self.assertNotIn(SOURCE_SENTINEL, prompt)

    def test_review_accepts_only_after_independent_audit_and_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root)
            handoff, _ = _write_ready_handoff(root, source)
            provider = FakeProvider(["accepted"])
            reviewed = review_candidate(
                handoff,
                source,
                provider=provider,
                template_root=FORMALIZATION_ROOT,
                review_root=root / "reviews",
                build_runner=_successful_build,
            )
            self.assertEqual(reviewed.verdict, "accepted")
            self.assertIsNone(reviewed.revision_request_path)
            payload = json.loads(reviewed.review_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["isolation"]["blind_stage_input"], "lean_only")
            blind_input = (
                reviewed.attempt_dir / "blind" / "lean-input.json"
            ).read_text(encoding="utf-8")
            self.assertNotIn(SOURCE_SENTINEL, blind_input)

    def test_placeholder_forces_reformalization_even_if_model_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root)
            handoff, _ = _write_ready_handoff(
                root,
                source,
                main_source=(
                    "import Mathlib.Data.Real.Basic\n\n"
                    "theorem generated_demo : True := by\n"
                    "  sorry\n"
                ),
            )
            reviewed = review_candidate(
                handoff,
                source,
                provider=FakeProvider(["accepted"]),
                template_root=FORMALIZATION_ROOT,
                review_root=root / "reviews",
                build_runner=_successful_build,
            )
            self.assertEqual(reviewed.verdict, "needs_reformalization")
            self.assertTrue(
                reviewed.revision_request_path
                and reviewed.revision_request_path.is_file()
            )

    def test_bodyless_opaque_declaration_forces_reformalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root)
            handoff, _ = _write_ready_handoff(
                root,
                source,
                main_source=(
                    "import Mathlib.Data.Real.Basic\n\n"
                    "opaque hidden_gap : True\n\n"
                    "theorem generated_demo : True := hidden_gap\n"
                ),
            )
            reviewed = review_candidate(
                handoff,
                source,
                provider=FakeProvider(["accepted"]),
                template_root=FORMALIZATION_ROOT,
                review_root=root / "reviews",
                build_runner=_successful_build,
            )
            self.assertEqual(reviewed.verdict, "needs_reformalization")
            audit = json.loads(
                (reviewed.attempt_dir / "mechanical" / "audit.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(audit["forbidden_declarations"], ["opaque hidden_gap"])

    def test_untracked_lean_file_is_rejected_before_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root)
            handoff, _ = _write_ready_handoff(root, source)
            candidate_root = handoff.parent / "result" / "project_aristotle"
            (candidate_root / "Untracked.lean").write_text(
                "axiom hidden_gap : True\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ReviewReadError, "Lean file set does not match"
            ):
                load_candidate(handoff)

    def test_incomplete_source_method_routes_to_reextraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root, proof_status="partial")
            handoff, _ = _write_ready_handoff(root, source)
            reviewed = review_candidate(
                handoff,
                source,
                provider=FakeProvider(["needs_reextraction"]),
                template_root=FORMALIZATION_ROOT,
                review_root=root / "reviews",
                build_runner=_successful_build,
            )
            self.assertEqual(reviewed.verdict, "needs_reextraction")
            self.assertIsNone(reviewed.revision_request_path)

    def test_agent2_agent3_loop_rechecks_revised_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root)
            handoff, prepared_project = _write_ready_handoff(root, source)
            archive = _archive_project(prepared_project, root / "archive")
            provider = FakeProvider(["needs_reformalization", "accepted"])
            transport = FakeRevisionTransport(archive)
            result = run_review_loop(
                handoff,
                source,
                provider=provider,
                revision_transport=transport,
                template_root=FORMALIZATION_ROOT,
                max_revisions=2,
                build_runner=_successful_build,
            )
            self.assertEqual(result.verdict, "accepted")
            self.assertEqual(result.cycles, 2)
            self.assertEqual(len(result.revisions), 1)
            self.assertEqual(transport.calls, 1)
            self.assertEqual(
                result.revisions[0].generation.state, "ready_for_review"
            )
            revised = load_candidate(
                result.revisions[0].generation.handoff_path  # type: ignore[arg-type]
            )
            self.assertIn("revision", revised.handoff)


if __name__ == "__main__":
    unittest.main()
