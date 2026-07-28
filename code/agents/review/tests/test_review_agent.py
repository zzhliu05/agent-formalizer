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
from formalization_agent.preparer import PreparationPolicy, prepare_formalization
from formalization_agent.reader import load_theorem_package

from review_agent.chapter import run_chapter_review
from review_agent.lean_audit import _extract_declarations
from review_agent.loop import run_review_loop
from review_agent.models import (
    BlindBacktranslation,
    ComparisonIssue,
    RevisionRequest,
    SemanticComparison,
)
from review_agent.prompts import blind_translation_prompt
from review_agent.provider import ProviderResult
from review_agent.reader import ReviewReadError, load_candidate
from review_agent.reviewer import (
    _source_context_with_citations,
    review_candidate,
)
from review_agent.revision import RemoteRevision, _has_downloadable_output

FORMALIZATION_ROOT = Path(__file__).resolve().parents[2] / "formalization"
SOURCE_SENTINEL = "SOURCE-ONLY-SENTINEL"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_payload(
    *,
    proof_status: str = "complete",
    kind: str = "theorem",
) -> dict[str, object]:
    complete = proof_status == "complete"
    declaration_only = proof_status == "not_applicable"
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
            "kind": kind,
            "label_verbatim": "Demo Theorem.",
            "title_verbatim": "",
            "statement_verbatim": f"Demo Theorem. {SOURCE_SENTINEL}",
            "proof_status": proof_status,
            "proof_verbatim": (
                "" if declaration_only else "Proof. The claim is immediate."
            ),
            "proof_steps": [] if declaration_only else [
                {
                    "order": 1,
                    "role": "conclusion",
                    "text_verbatim": "Proof. The claim is immediate.",
                    "source_pages": [1],
                }
            ],
            "omission": {
                "is_omitted": not complete and not declaration_only,
                "reason": (
                    "other" if not complete and not declaration_only else "none"
                ),
                "marker_verbatim": (
                    "details omitted"
                    if not complete and not declaration_only
                    else ""
                ),
                "note": (
                    "The printed source omits details."
                    if not complete and not declaration_only
                    else ""
                ),
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


def _write_source(
    root: Path,
    *,
    proof_status: str = "complete",
    kind: str = "theorem",
) -> Path:
    theorem_root = root / "source" / "review-demo-theorem"
    attempt = theorem_root / "extraction" / "attempt-001"
    attempt.mkdir(parents=True)
    theorem_bytes = (
        json.dumps(
            _source_payload(proof_status=proof_status, kind=kind),
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
    preparation_policy: PreparationPolicy | None = None,
    legacy_layout: bool = False,
) -> tuple[Path, Path]:
    prepared = prepare_formalization(
        source_root,
        output_root=root / "pipeline",
        template_root=FORMALIZATION_ROOT,
        policy=preparation_policy,
    )
    preparation_request = prepared.request_path
    prepared_project = prepared.project_dir
    if legacy_layout:
        theorem_root = root / "pipeline" / "review-demo-theorem"
        legacy_attempt = (
            theorem_root
            / "formalization"
            / "preparation"
            / "attempt-001"
        )
        shutil.copytree(prepared.attempt_dir, legacy_attempt)
        preparation_request = legacy_attempt / "request.json"
        prepared_project = legacy_attempt / "lean"
        generation = (
            theorem_root
            / "formalization"
            / "generation"
            / "attempt-001"
        )
        project = generation / "result" / "project_aristotle"
        project_root_ref = "result/project_aristotle"
    else:
        theorem_root = prepared.attempt_dir.parent.parent
        generation = theorem_root / "gen" / "001"
        project = generation / "lean"
        project_root_ref = "lean"
    shutil.copytree(prepared_project, project)
    (project / "Main.lean").write_text(main_source, encoding="utf-8")
    main_hash = _sha((project / "Main.lean").read_bytes())
    request_ref = os.path.relpath(preparation_request, generation).replace("\\", "/")
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
            "main_path": f"{project_root_ref}/Main.lean",
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
            "project_root": project_root_ref,
            "main_path": f"{project_root_ref}/Main.lean",
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
    return generation / "handoff.json", prepared_project


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
    if verdict == "accepted_complete_wrong_evidence":
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
            proof_step_correspondence=["The complete printed method matches."],
            source_proof_complete=True,
            source_method_evidence="partial_but_sufficient",
            omitted_detail_notes=["Lean expands a routine implicit detail."],
            issues=[],
            verdict="accepted",
            rationale="The complete proof and Lean method match.",
        )
    if verdict == "accepted_partial":
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
            proof_step_correspondence=[
                "Every printed high-level step matches the Lean construction."
            ],
            source_proof_complete=False,
            source_method_evidence="partial_but_sufficient",
            omitted_detail_notes=[
                "Lean supplies only the local verification omitted by the source."
            ],
            issues=[],
            verdict="accepted",
            rationale="The printed method is sufficient and matches exactly.",
        )
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
            source_method_evidence="complete",
            omitted_detail_notes=[],
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
            source_method_evidence="insufficient",
            omitted_detail_notes=["The printed source omits the method."],
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
        source_method_evidence="complete",
        omitted_detail_notes=[],
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


def _archive_project(
    project: Path,
    destination: Path,
    *,
    main_source: str = (
        "import Mathlib.Data.Real.Basic\n\n"
        "theorem generated_demo : True := by\n"
        "  trivial\n"
    ),
) -> bytes:
    candidate = destination / "revised-project"
    shutil.copytree(project, candidate)
    (candidate / "Main.lean").write_text(main_source, encoding="utf-8")
    archive_path = destination / "fixture.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in candidate.rglob("*"):
            if path.is_file():
                archive.add(path, arcname=path.relative_to(candidate).as_posix())
    return archive_path.read_bytes()


class FakeRevisionTransport:
    def __init__(self, archive_bytes: bytes | list[bytes]) -> None:
        self.archive_bytes = (
            archive_bytes if isinstance(archive_bytes, list) else [archive_bytes]
        )
        self.calls = 0
        self.requests: list[RevisionRequest] = []

    async def revise(
        self,
        request: RevisionRequest,
        *,
        output_dir: Path,
        poll_seconds: float,
        timeout_seconds: float,
    ) -> RemoteRevision:
        del poll_seconds, timeout_seconds
        self.calls += 1
        self.requests.append(request)
        output_dir.mkdir(parents=True, exist_ok=True)
        archive = output_dir / "result.tar.gz"
        archive.write_bytes(
            self.archive_bytes[min(self.calls - 1, len(self.archive_bytes) - 1)]
        )
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
    def test_candidate_reader_keeps_legacy_agent2_layout_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root)
            handoff, _ = _write_ready_handoff(
                root, source, legacy_layout=True
            )

            loaded = load_candidate(handoff)

            self.assertEqual(loaded.theorem_id, "review-demo-theorem")
            self.assertEqual(loaded.handoff_path, handoff.resolve())
            self.assertIn("Main.lean", loaded.lean_sources)

    def test_axiom_audit_qualifies_declarations_inside_namespaces(self) -> None:
        source = """
namespace Outer
section
lemma helper : True := by trivial
namespace Inner
theorem result : True := by trivial
end Inner
end
end Outer

theorem topLevel : True := by trivial
"""
        self.assertEqual(
            _extract_declarations(source),
            ["Outer.Inner.result", "Outer.helper", "topLevel"],
        )

    def test_only_archive_bearing_error_completion_is_downloadable(self) -> None:
        self.assertTrue(_has_downloadable_output("COMPLETE", None))
        self.assertTrue(
            _has_downloadable_output("COMPLETE_WITH_ERRORS", "output-final.tar.gz")
        )
        self.assertTrue(
            _has_downloadable_output("OUT_OF_BUDGET", "output-final.tar.gz")
        )
        self.assertFalse(_has_downloadable_output("COMPLETE_WITH_ERRORS", None))
        self.assertFalse(_has_downloadable_output("OUT_OF_BUDGET", None))
        self.assertFalse(_has_downloadable_output("FAILED", "output-final.tar.gz"))

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
            build_calls: list[Path] = []

            def combined_build(
                project_root: Path,
                main_path: Path,
                template_root: Path,
                timeout_seconds: int,
            ) -> BuildOutcome:
                build_calls.append(main_path)
                return _successful_build(
                    project_root,
                    main_path,
                    template_root,
                    timeout_seconds,
                )

            reviewed = review_candidate(
                handoff,
                source,
                provider=provider,
                template_root=FORMALIZATION_ROOT,
                review_root=root / "reviews",
                build_runner=combined_build,
            )
            self.assertEqual(reviewed.verdict, "accepted")
            self.assertEqual(len(build_calls), 1)
            self.assertEqual(build_calls[0].name, "Audit.lean")
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
            candidate_root = handoff.parent / "lean"
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

    def test_partial_source_can_pass_when_printed_method_is_sufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root, proof_status="partial")
            handoff, _ = _write_ready_handoff(root, source)
            reviewed = review_candidate(
                handoff,
                source,
                provider=FakeProvider(["accepted_partial"]),
                template_root=FORMALIZATION_ROOT,
                review_root=root / "reviews",
                build_runner=_successful_build,
            )
            self.assertEqual(reviewed.verdict, "accepted")
            comparison = json.loads(
                (
                    reviewed.attempt_dir
                    / "comparison"
                    / "comparison.json"
                ).read_text(encoding="utf-8")
            )["result"]
            self.assertEqual(
                comparison["source_method_evidence"],
                "partial_but_sufficient",
            )
            self.assertTrue(comparison["omitted_detail_notes"])

    def test_complete_source_evidence_enum_is_normalized_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root)
            handoff, _ = _write_ready_handoff(root, source)
            reviewed = review_candidate(
                handoff,
                source,
                provider=FakeProvider(["accepted_complete_wrong_evidence"]),
                template_root=FORMALIZATION_ROOT,
                review_root=root / "reviews",
                build_runner=_successful_build,
            )
            self.assertEqual(reviewed.verdict, "accepted")
            comparison = json.loads(
                (
                    reviewed.attempt_dir
                    / "comparison"
                    / "comparison.json"
                ).read_text(encoding="utf-8")
            )["result"]
            self.assertEqual(comparison["source_method_evidence"], "complete")

    def test_left_to_reader_can_pass_when_printed_method_is_sufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root, proof_status="left_to_reader")
            handoff, _ = _write_ready_handoff(root, source)
            reviewed = review_candidate(
                handoff,
                source,
                provider=FakeProvider(["accepted_partial"]),
                template_root=FORMALIZATION_ROOT,
                build_runner=_successful_build,
            )
            self.assertEqual(reviewed.verdict, "accepted")
            comparison = json.loads(
                (
                    reviewed.attempt_dir
                    / "comparison"
                    / "comparison.json"
                ).read_text(encoding="utf-8")
            )["result"]
            self.assertEqual(
                comparison["source_method_evidence"],
                "partial_but_sufficient",
            )

    def test_source_axiom_without_proof_passes_declaration_only_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(
                root,
                proof_status="not_applicable",
                kind="axiom",
            )
            handoff, _ = _write_ready_handoff(
                root,
                source,
                preparation_policy=PreparationPolicy(
                    allow_source_axiom=True,
                    allow_declaration_only=True,
                ),
            )
            reviewed = review_candidate(
                handoff,
                source,
                provider=FakeProvider(["needs_reextraction"]),
                template_root=FORMALIZATION_ROOT,
                review_root=root / "reviews",
                build_runner=_successful_build,
            )
            self.assertEqual(reviewed.verdict, "accepted_declaration")
            self.assertIsNone(reviewed.revision_request_path)
            self.assertIn(
                "declaration-only",
                reviewed.review_markdown_path.read_text(encoding="utf-8"),
            )

    def test_by_reference_context_resolves_hash_bound_sibling_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root, proof_status="by_reference")
            theorem_path = source / "extraction" / "attempt-001" / "theorem.json"
            payload = json.loads(theorem_path.read_text(encoding="utf-8"))
            payload["result"]["proof_verbatim"] = "Apply Proposition 0.9."
            payload["result"]["proof_steps"] = [
                {
                    "order": 1,
                    "role": "other",
                    "text_verbatim": "Apply Proposition 0.9.",
                    "source_pages": [1],
                }
            ]
            theorem_bytes = (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            ).encode()
            theorem_path.write_bytes(theorem_bytes)
            latest_path = source / "extraction" / "latest.json"
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            latest["theorem_json_sha256"] = _sha(theorem_bytes)
            latest_path.write_text(
                json.dumps(latest, indent=2) + "\n",
                encoding="utf-8",
            )

            cited_id = "review-reference-p00001-0-9-proposition"
            cited_payload = _source_payload()
            cited_payload["theorem_id"] = cited_id
            cited_payload["result"]["label_verbatim"] = "0.9 Proposition."
            cited_payload["result"]["statement_verbatim"] = (
                "0.9 Proposition. The referenced result."
            )
            cited_root = root / "source" / cited_id
            cited_attempt = cited_root / "extraction" / "attempt-001"
            cited_attempt.mkdir(parents=True)
            cited_bytes = (
                json.dumps(
                    cited_payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode()
            (cited_attempt / "theorem.json").write_bytes(cited_bytes)
            (cited_attempt / "context.md").write_text(
                "# Context\n\nNone.\n",
                encoding="utf-8",
            )
            (cited_attempt / "source.txt").write_text(
                "0.9 Proposition. The referenced result.\n",
                encoding="utf-8",
            )
            (cited_root / "extraction" / "latest.json").write_text(
                json.dumps(
                    {
                        "theorem_id": cited_id,
                        "attempt": 1,
                        "path": "attempt-001/theorem.json",
                        "theorem_json_sha256": _sha(cited_bytes),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            context, citations = _source_context_with_citations(
                load_theorem_package(source)
            )
            self.assertIn("The referenced result.", context[-1])
            self.assertEqual(citations[0]["reference_number"], "0.9")
            self.assertEqual(citations[0]["theorem_id"], cited_id)
            self.assertEqual(
                citations[0]["theorem_json_sha256"],
                _sha(cited_bytes),
            )

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

    def test_loop_automatically_repairs_agent2_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root)
            handoff, prepared_project = _write_ready_handoff(root, source)
            failed_archive = _archive_project(
                prepared_project,
                root / "failed-archive",
                main_source=(
                    "import Main.Auxiliary\n\n"
                    "theorem generated_demo : True := by\n"
                    "  trivial\n"
                ),
            )
            fixed_archive = _archive_project(
                prepared_project,
                root / "fixed-archive",
            )
            transport = FakeRevisionTransport([failed_archive, fixed_archive])

            def import_sensitive_build(
                project_root: Path,
                main_path: Path,
                template_root: Path,
                timeout_seconds: int,
            ) -> BuildOutcome:
                if (
                    main_path.name == "Main.lean"
                    and "import Main.Auxiliary"
                    in main_path.read_text(encoding="utf-8")
                ):
                    return BuildOutcome(
                        command=["lean", "Main.lean"],
                        exit_code=1,
                        timed_out=False,
                        duration_seconds=0.01,
                        stdout="",
                        stderr="unknown module prefix 'Main'",
                    )
                return _successful_build(
                    project_root,
                    main_path,
                    template_root,
                    timeout_seconds,
                )

            result = run_review_loop(
                handoff,
                source,
                provider=FakeProvider(["needs_reformalization", "accepted"]),
                revision_transport=transport,
                template_root=FORMALIZATION_ROOT,
                max_revisions=2,
                max_validation_repairs_per_revision=2,
                build_runner=import_sensitive_build,
            )

            self.assertEqual(result.verdict, "accepted")
            self.assertEqual(result.stop_reason, "terminal_verdict")
            self.assertEqual(result.cycles, 2)
            self.assertEqual(result.semantic_revision_count, 1)
            self.assertEqual(result.validation_repair_count, 1)
            self.assertEqual(len(result.revisions), 2)
            self.assertEqual(
                result.revisions[0].generation.state, "validation_failed"
            )
            self.assertEqual(
                result.revisions[1].generation.state, "ready_for_review"
            )
            self.assertEqual(
                result.revisions[1].request_kind,
                "agent2_validation_repair",
            )
            self.assertEqual(transport.calls, 2)
            self.assertEqual(
                transport.requests[1].current_task_id,
                "revision-task-1",
            )
            self.assertIn(
                "unknown module prefix 'Main'",
                "\n".join(transport.requests[1].instructions),
            )
            self.assertTrue(
                result.revisions[1].request_path.name.startswith(
                    "validation-repair-"
                )
            )
            repaired_run = json.loads(
                (
                    result.revisions[1].generation.run_dir / "run.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                Path(repaired_run["revision"]["parent_run_json"]).resolve(),
                (
                    result.revisions[0].generation.run_dir / "run.json"
                ).resolve(),
            )

    def test_loop_stops_at_agent2_validation_repair_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root)
            handoff, prepared_project = _write_ready_handoff(root, source)
            failed_archive = _archive_project(
                prepared_project,
                root / "failed-archive",
                main_source=(
                    "import Mathlib.Data.Real.Basic\n\n"
                    "theorem generated_demo : True := by\n"
                    "  sorry\n"
                ),
            )
            transport = FakeRevisionTransport(failed_archive)
            result = run_review_loop(
                handoff,
                source,
                provider=FakeProvider(["needs_reformalization"]),
                revision_transport=transport,
                template_root=FORMALIZATION_ROOT,
                max_revisions=2,
                max_validation_repairs_per_revision=2,
                build_runner=_successful_build,
            )

            self.assertEqual(result.verdict, "needs_reformalization")
            self.assertEqual(
                result.stop_reason,
                "agent2_validation_repair_limit",
            )
            self.assertEqual(result.semantic_revision_count, 1)
            self.assertEqual(result.validation_repair_count, 2)
            self.assertEqual(transport.calls, 3)
            self.assertIn(
                "byte-identical",
                "\n".join(transport.requests[2].instructions),
            )

    def test_chapter_runner_persists_and_reuses_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _write_source(root)
            handoff, _ = _write_ready_handoff(root, source)
            (handoff.parent.parent / "latest.json").write_text(
                json.dumps({"path": "001/run.json"}) + "\n",
                encoding="utf-8",
            )
            failed_attempt = handoff.parent.parent / "002"
            failed_attempt.mkdir()
            (failed_attempt / "run.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "state": "validation_failed",
                        "theorem_id": "review-demo-theorem",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (handoff.parent.parent / "latest.json").write_text(
                json.dumps({"path": "002/run.json"}) + "\n",
                encoding="utf-8",
            )
            provider = FakeProvider(["accepted"])
            first = run_chapter_review(
                root / "pipeline",
                root / "source",
                provider=provider,
                revision_transport=FakeRevisionTransport(b""),
                template_root=FORMALIZATION_ROOT,
                build_runner=_successful_build,
            )
            self.assertTrue(first.complete)
            self.assertEqual(first.items[0].status, "accepted")
            summary = json.loads(
                first.summary_path.read_text(encoding="utf-8")
            )
            self.assertTrue(summary["complete"])
            self.assertEqual(summary["counts"]["accepted"], 1)

            second = run_chapter_review(
                root / "pipeline",
                root / "source",
                provider=FakeProvider([]),
                revision_transport=FakeRevisionTransport(b""),
                template_root=FORMALIZATION_ROOT,
                build_runner=_successful_build,
            )
            self.assertTrue(second.complete)
            self.assertEqual(second.items[0].status, "accepted_existing")


if __name__ == "__main__":
    unittest.main()
