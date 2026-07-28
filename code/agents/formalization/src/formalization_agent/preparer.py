from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .prompts import (
    build_aristotle_prompt,
    build_notes_template,
    build_source_theorem_markdown,
)
from .layout import (
    attempt_name,
    iter_attempt_dirs,
    parse_attempt_name,
    short_preparation_root,
)
from .reader import LoadedTheoremPackage, load_theorem_package, sha256_bytes


class PreparationError(ValueError):
    """Raised when a valid extraction package is not safe to formalize."""


@dataclass(frozen=True)
class PreparationPolicy:
    allow_uncertain: bool = False
    allow_source_axiom: bool = False
    allow_declaration_only: bool = False


@dataclass(frozen=True)
class PreparationResult:
    theorem_id: str
    attempt: int
    attempt_dir: Path
    project_dir: Path
    prompt_path: Path
    request_path: Path
    request_sha256: str


def _validate_for_proof(loaded: LoadedTheoremPackage, policy: PreparationPolicy) -> None:
    result = loaded.package.result
    if not result.record_complete_in_chunk:
        raise PreparationError(
            "Agent 1 marked the theorem record incomplete at the chunk boundary"
        )
    if result.boundary_note:
        raise PreparationError(
            f"Agent 1 reported a theorem-boundary issue: {result.boundary_note}"
        )
    if result.kind == "definition":
        raise PreparationError(
            f"source kind '{result.kind}' is not a proof-bearing target for Agent 2"
        )
    if result.kind == "axiom" and not policy.allow_source_axiom:
        raise PreparationError(
            "source kind 'axiom' requires an explicit allow_source_axiom policy"
        )
    if result.proof_status == "not_applicable" and not (
        result.kind == "axiom"
        and policy.allow_source_axiom
        and policy.allow_declaration_only
    ):
        raise PreparationError(
            "proof status 'not_applicable' requires an axiom plus explicit "
            "allow_source_axiom and allow_declaration_only policies"
        )
    if result.uncertainties and not policy.allow_uncertain:
        raise PreparationError(
            "Agent 1 recorded extraction uncertainties; inspect them or pass "
            "--allow-uncertain explicitly"
        )


def _next_attempt(preparation_root: Path) -> int:
    attempts = [
        parsed
        for child in iter_attempt_dirs(preparation_root)
        if (parsed := parse_attempt_name(child.name)) is not None
    ]
    return max(attempts, default=0) + 1


def _write_text(path: Path, text: str) -> str:
    data = text.replace("\r\n", "\n").encode("utf-8")
    path.write_bytes(data)
    return sha256_bytes(data)


def _write_json(path: Path, payload: object) -> str:
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.write_bytes(data)
    return sha256_bytes(data)


def _staging_lakefile() -> str:
    return """name = "formalization_agent"
version = "0.1.0"
defaultTargets = ["Main"]

[[lean_lib]]
name = "Main"

[[require]]
name = "mathlib"
git = "https://github.com/leanprover-community/mathlib4.git"
rev = "v4.28.0"
"""


def _main_scaffold(theorem_id: str) -> str:
    return f"""import Mathlib.Data.Real.Basic

/-!
Agent 2 staging module for `{theorem_id}`.
Aristotle must replace this comment with one faithful theorem declaration and
a complete proof, then verify it with `lake build`.
-/
"""


def _validate_template(template_root: Path) -> tuple[str, bytes]:
    toolchain_path = template_root / "lean-toolchain"
    manifest_path = template_root / "lake-manifest.json"
    try:
        toolchain = toolchain_path.read_text(encoding="utf-8-sig").strip()
        manifest = manifest_path.read_bytes()
    except OSError as exc:
        raise PreparationError(f"cannot read Lean project template: {exc}") from exc
    if toolchain != "leanprover/lean4:v4.28.0":
        raise PreparationError(
            "Lean template must be pinned to leanprover/lean4:v4.28.0"
        )
    try:
        manifest_data = json.loads(manifest.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError(f"invalid lake-manifest.json: {exc}") from exc
    packages = manifest_data.get("packages", [])
    mathlib = next(
        (item for item in packages if isinstance(item, dict) and item.get("name") == "mathlib"),
        None,
    )
    if not mathlib or mathlib.get("inputRev") != "v4.28.0":
        raise PreparationError("lake-manifest.json must pin Mathlib v4.28.0")
    return toolchain, manifest


def prepare_formalization(
    input_path: str | Path,
    output_root: str | Path,
    template_root: str | Path,
    policy: PreparationPolicy | None = None,
) -> PreparationResult:
    active_policy = policy or PreparationPolicy()
    loaded = load_theorem_package(input_path)
    _validate_for_proof(loaded, active_policy)
    toolchain, manifest_bytes = _validate_template(Path(template_root).resolve())

    theorem_id = loaded.package.theorem_id
    try:
        preparation_root = short_preparation_root(
            Path(output_root), theorem_id
        )
    except ValueError as exc:
        raise PreparationError(str(exc)) from exc
    preparation_root.mkdir(parents=True, exist_ok=True)
    attempt = _next_attempt(preparation_root)
    attempt_directory_name = attempt_name(preparation_root, attempt)
    attempt_dir = preparation_root / attempt_directory_name
    if attempt_dir.exists():
        raise PreparationError(f"immutable attempt already exists: {attempt_dir}")

    staging_dir = preparation_root / f".staging-{uuid.uuid4().hex}"
    staging_dir.mkdir()
    try:
        project_dir = staging_dir / "lean"
        project_dir.mkdir()

        prompt_hash = _write_text(
            staging_dir / "prompt.txt", build_aristotle_prompt(loaded)
        )
        source_hash = _write_text(
            project_dir / "SOURCE_THEOREM.md",
            build_source_theorem_markdown(loaded),
        )
        notes_hash = _write_text(
            project_dir / "FORMALIZATION_NOTES.md", build_notes_template(loaded)
        )
        main_hash = _write_text(
            project_dir / "Main.lean", _main_scaffold(theorem_id)
        )
        lakefile_hash = _write_text(project_dir / "lakefile.toml", _staging_lakefile())
        toolchain_hash = _write_text(project_dir / "lean-toolchain", toolchain + "\n")
        (project_dir / "lake-manifest.json").write_bytes(manifest_bytes)
        manifest_hash = sha256_bytes(manifest_bytes)
        _write_text(project_dir / ".gitignore", ".lake/\n")

        request = {
            "schema_version": "1.0",
            "state": "prepared",
            "submitted": False,
            "theorem_id": theorem_id,
            "document_id": loaded.package.document_id,
            "extraction_run_id": loaded.package.extraction_run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "input": {
                "theorem_json_sha256": loaded.theorem_json_sha256,
                "context_markdown_sha256": loaded.context_markdown_sha256,
                "source_text_sha256": loaded.source_text_sha256,
                "source_pages": loaded.package.result.source_pages,
                "kind": loaded.package.result.kind,
                "proof_status": loaded.package.result.proof_status,
                "confidence": loaded.package.result.confidence,
                "uncertainty_count": len(loaded.package.result.uncertainties),
            },
            "policy": {
                "allow_uncertain": active_policy.allow_uncertain,
                "allow_source_axiom": active_policy.allow_source_axiom,
                "allow_declaration_only": active_policy.allow_declaration_only,
                "record_complete_required": True,
                "proof_bearing_target_required": (
                    loaded.package.result.proof_status != "not_applicable"
                ),
                "review_mode": (
                    "declaration_only"
                    if loaded.package.result.proof_status == "not_applicable"
                    else "proof_method"
                ),
            },
            "aristotle": {
                "interface": "python.Project.create_from_directory",
                "package": "aristotlelib==2.1.0",
                "prompt_file": "prompt.txt",
                "project_dir": "lean",
                "agent_questions_setting": "DISABLED",
                "polling_mode": "non_interactive",
            },
            "artifacts": {
                "prompt.txt": prompt_hash,
                "lean/SOURCE_THEOREM.md": source_hash,
                "lean/FORMALIZATION_NOTES.md": notes_hash,
                "lean/Main.lean": main_hash,
                "lean/lakefile.toml": lakefile_hash,
                "lean/lean-toolchain": toolchain_hash,
                "lean/lake-manifest.json": manifest_hash,
            },
        }
        request_hash = _write_json(staging_dir / "request.json", request)

        staging_dir.replace(attempt_dir)
        latest_payload = {
            "schema_version": "1.0",
            "theorem_id": theorem_id,
            "attempt": attempt,
            "path": f"{attempt_directory_name}/request.json",
            "sha256": request_hash,
        }
        latest_temp = preparation_root / f".latest-{uuid.uuid4().hex}.json"
        _write_json(latest_temp, latest_payload)
        latest_temp.replace(preparation_root / "latest.json")
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        raise

    return PreparationResult(
        theorem_id=theorem_id,
        attempt=attempt,
        attempt_dir=attempt_dir,
        project_dir=attempt_dir / "lean",
        prompt_path=attempt_dir / "prompt.txt",
        request_path=attempt_dir / "request.json",
        request_sha256=request_hash,
    )
