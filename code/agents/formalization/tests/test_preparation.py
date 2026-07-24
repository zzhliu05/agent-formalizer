from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from formalization_agent.preparer import (
    PreparationError,
    PreparationPolicy,
    prepare_formalization,
)
from formalization_agent.reader import PackageReadError, load_theorem_package


FORMALIZATION_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _valid_payload(
    *,
    theorem_id: str = "demo-theorem-001",
    kind: str = "theorem",
    proof_status: str = "complete",
    uncertainties: list[str] | None = None,
    record_complete: bool = True,
    boundary_note: str | None = None,
) -> dict[str, object]:
    proof_verbatim = "Let n be arbitrary. Equality follows by reflexivity."
    omission = {
        "is_omitted": False,
        "reason": None,
        "marker_verbatim": None,
        "note": None,
    }
    proof_steps: list[dict[str, object]] = [
        {
            "order": 1,
            "role": "conclusion",
            "text_verbatim": proof_verbatim,
            "source_pages": [1],
        }
    ]
    if proof_status != "complete":
        proof_verbatim = None
        proof_steps = []
        omission = {
            "is_omitted": True,
            "reason": "left_to_reader",
            "marker_verbatim": "The proof is immediate.",
            "note": "No printed proof was supplied.",
        }

    return {
        "schema_version": "1.0",
        "theorem_id": theorem_id,
        "document_id": "demo-document",
        "extraction_run_id": "run-001",
        "source": {
            "markdown_file": "chunk-0001.md",
            "markdown_sha256": "a" * 64,
            "pdf_pages": [1],
            "overlap_variant": False,
        },
        "result": {
            "source_pages": [1],
            "kind": kind,
            "label_verbatim": "Theorem 1",
            "title_verbatim": None,
            "statement_verbatim": "For every natural number n, n equals n.",
            "proof_status": proof_status,
            "proof_verbatim": proof_verbatim,
            "proof_steps": proof_steps,
            "omission": omission,
            "context_items": [
                {
                    "relation": "definition",
                    "label_verbatim": "Natural number",
                    "text_verbatim": "The variable n ranges over natural numbers.",
                    "source_pages": [1],
                    "relevance": "Fixes the domain of quantification.",
                }
            ],
            "uncertainties": uncertainties or [],
            "confidence": 0.99,
            "record_complete_in_chunk": record_complete,
            "boundary_note": boundary_note,
        },
        "provider": {
            "request_id": "private-provider-request",
            "requested_model": "test-model",
            "resolved_model": "test-model",
            "deployment": "test",
            "finish_reason": "stop",
            "usage": {"input_tokens": 10, "output_tokens": 20},
        },
    }


def _write_package(
    root: Path, payload: dict[str, object], *, with_latest: bool = True
) -> tuple[Path, Path]:
    extraction = root / str(payload["theorem_id"]) / "extraction"
    attempt = extraction / "attempt-001"
    attempt.mkdir(parents=True)
    theorem_json = attempt / "theorem.json"
    _write_json(theorem_json, payload)
    (attempt / "context.md").write_text("# Context\n\nTest context.\n", encoding="utf-8")
    (attempt / "source.txt").write_text("Test source excerpt.\n", encoding="utf-8")
    if with_latest:
        _write_json(
            extraction / "latest.json",
            {
                "theorem_id": payload["theorem_id"],
                "attempt": 1,
                "path": "attempt-001/theorem.json",
                "theorem_json_sha256": _sha256(theorem_json),
            },
        )
    return attempt, extraction


class ReaderTests(unittest.TestCase):
    def test_reads_latest_pointer_and_companion_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, extraction = _write_package(Path(directory), _valid_payload())
            loaded = load_theorem_package(extraction)

            self.assertEqual(loaded.package.theorem_id, "demo-theorem-001")
            self.assertEqual(loaded.package.result.proof_status, "complete")
            self.assertTrue(loaded.context_markdown_sha256)
            self.assertTrue(loaded.source_text_sha256)

    def test_rejects_tampered_latest_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            attempt, extraction = _write_package(Path(directory), _valid_payload())
            with (attempt / "theorem.json").open("a", encoding="utf-8") as handle:
                handle.write(" ")

            with self.assertRaisesRegex(PackageReadError, "SHA-256"):
                load_theorem_package(extraction)

    def test_rejects_schema_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = _valid_payload()
            payload["unexpected"] = True
            attempt, _ = _write_package(Path(directory), payload, with_latest=False)

            with self.assertRaisesRegex(PackageReadError, "invalid theorem package"):
                load_theorem_package(attempt)

    def test_rejects_missing_companion_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            attempt, _ = _write_package(
                Path(directory), _valid_payload(), with_latest=False
            )
            (attempt / "context.md").unlink()

            with self.assertRaisesRegex(PackageReadError, "context.md"):
                load_theorem_package(attempt)


class PreparationTests(unittest.TestCase):
    def test_creates_immutable_aristotle_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, extraction = _write_package(root / "input", _valid_payload())
            prepared = prepare_formalization(
                extraction,
                output_root=root / "output",
                template_root=FORMALIZATION_ROOT,
            )

            self.assertEqual(prepared.attempt, 1)
            self.assertTrue(prepared.request_path.is_file())
            self.assertTrue((prepared.project_dir / "SOURCE_THEOREM.md").is_file())
            self.assertTrue((prepared.project_dir / "Main.lean").is_file())
            request = json.loads(prepared.request_path.read_text(encoding="utf-8"))
            self.assertEqual(request["state"], "prepared")
            self.assertIs(request["submitted"], False)
            self.assertNotIn(
                "private-provider-request",
                prepared.request_path.read_text(encoding="utf-8"),
            )

            prompt = prepared.prompt_path.read_text(encoding="utf-8")
            self.assertIn("submit", json.dumps(request))
            self.assertIn("SOURCE_THEOREM.md", prompt)
            self.assertIn("complete kernel-checked proof", prompt)
            self.assertNotIn(
                "For every natural number",
                prompt,
                "source statement belongs in the project file, not the CLI prompt",
            )
            main = (prepared.project_dir / "Main.lean").read_text(encoding="utf-8")
            self.assertNotIn("sorry", main.lower())
            self.assertNotIn("admit", main.lower())

            second = prepare_formalization(
                extraction,
                output_root=root / "output",
                template_root=FORMALIZATION_ROOT,
            )
            self.assertEqual(second.attempt, 2)
            self.assertTrue(prepared.attempt_dir.is_dir())

    def test_allows_missing_printed_proof_and_labels_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = _valid_payload(proof_status="omitted")
            _, extraction = _write_package(root / "input", payload)
            prepared = prepare_formalization(
                extraction,
                output_root=root / "output",
                template_root=FORMALIZATION_ROOT,
            )

            prompt = prepared.prompt_path.read_text(encoding="utf-8")
            source = (prepared.project_dir / "SOURCE_THEOREM.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("construct a complete proof independently", prompt.lower())
            self.assertIn("no complete printed proof", source)

    def test_uncertainty_requires_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = _valid_payload(uncertainties=["The quantifier may be cropped."])
            _, extraction = _write_package(root / "input", payload)
            with self.assertRaisesRegex(PreparationError, "uncertainties"):
                prepare_formalization(
                    extraction,
                    output_root=root / "output",
                    template_root=FORMALIZATION_ROOT,
                )

            prepared = prepare_formalization(
                extraction,
                output_root=root / "output",
                template_root=FORMALIZATION_ROOT,
                policy=PreparationPolicy(allow_uncertain=True),
            )
            self.assertTrue(prepared.request_path.is_file())

    def test_rejects_non_proof_target_and_incomplete_boundary(self) -> None:
        for payload, pattern in (
            (_valid_payload(kind="axiom"), "not a proof-bearing"),
            (
                _valid_payload(record_complete=False),
                "incomplete at the chunk boundary",
            ),
            (
                _valid_payload(boundary_note="Statement continues on the next page."),
                "theorem-boundary issue",
            ),
        ):
            with self.subTest(pattern=pattern), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, extraction = _write_package(root / "input", payload)
                with self.assertRaisesRegex(PreparationError, pattern):
                    prepare_formalization(
                        extraction,
                        output_root=root / "output",
                        template_root=FORMALIZATION_ROOT,
                    )


if __name__ == "__main__":
    unittest.main()
