from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .layout import parse_attempt_name
from .reader import sha256_bytes


class PreparationReadError(ValueError):
    """Raised when a preparation bundle is missing, tampered with, or unsupported."""


@dataclass(frozen=True)
class LoadedPreparation:
    theorem_id: str
    request: dict[str, Any]
    attempt_dir: Path
    request_path: Path
    prompt_path: Path
    project_dir: Path
    request_sha256: str
    artifact_hashes: dict[str, str]


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationReadError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PreparationReadError(f"{path} must contain a JSON object")
    return payload, raw


def _resolve_latest(path: Path) -> tuple[Path, dict[str, Any]]:
    pointer, _ = _read_json(path)
    required = {"schema_version", "theorem_id", "attempt", "path", "sha256"}
    if set(pointer) != required:
        raise PreparationReadError(
            f"preparation latest pointer fields must be exactly {sorted(required)}"
        )
    if pointer["schema_version"] != "1.0":
        raise PreparationReadError("unsupported preparation latest schema")
    if not isinstance(pointer["attempt"], int) or pointer["attempt"] < 1:
        raise PreparationReadError("preparation attempt must be a positive integer")
    if not isinstance(pointer["path"], str) or not pointer["path"]:
        raise PreparationReadError("preparation latest path must be a nonempty string")
    if (
        not isinstance(pointer["sha256"], str)
        or len(pointer["sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in pointer["sha256"])
    ):
        raise PreparationReadError("preparation latest sha256 is invalid")

    base = path.parent.resolve()
    relative = Path(pointer["path"])
    if relative.is_absolute():
        raise PreparationReadError("preparation latest path must be relative")
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise PreparationReadError("preparation latest path escapes its directory")
    if target.name != "request.json":
        raise PreparationReadError("preparation latest path must resolve to request.json")
    if parse_attempt_name(target.parent.name) != pointer["attempt"]:
        raise PreparationReadError(
            "preparation latest attempt does not match its target directory"
        )
    return target, pointer


def _resolve_input(input_path: Path) -> tuple[Path, dict[str, Any] | None]:
    path = input_path.resolve()
    if path.is_file():
        if path.name == "request.json":
            return path, None
        if path.name == "latest.json":
            return _resolve_latest(path)
        raise PreparationReadError("input file must be request.json or latest.json")

    if not path.is_dir():
        raise PreparationReadError(f"preparation input does not exist: {path}")
    direct = path / "request.json"
    if direct.is_file():
        return direct, None
    latest = path / "latest.json"
    if latest.is_file():
        return _resolve_latest(latest)
    compact = path / "prep" / "latest.json"
    if compact.is_file():
        return _resolve_latest(compact)
    nested = path / "formalization" / "preparation" / "latest.json"
    if nested.is_file():
        return _resolve_latest(nested)
    raise PreparationReadError(
        "directory must contain request.json, latest.json, or "
        "prep/latest.json (compact) or formalization/preparation/latest.json "
        "(legacy)"
    )


def _require_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise PreparationReadError(f"request field '{field}' must be nonempty")
    return value


def _safe_artifact(attempt_dir: Path, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute():
        raise PreparationReadError(f"artifact path must be relative: {relative_text}")
    target = (attempt_dir / relative).resolve()
    if not target.is_relative_to(attempt_dir):
        raise PreparationReadError(f"artifact path escapes attempt: {relative_text}")
    return target


def load_preparation(input_path: str | Path) -> LoadedPreparation:
    request_path, pointer = _resolve_input(Path(input_path))
    request, raw = _read_json(request_path)
    request_hash = sha256_bytes(raw)
    if pointer and request_hash != pointer["sha256"]:
        raise PreparationReadError(
            "request.json SHA-256 does not match the preparation latest pointer"
        )

    if request.get("schema_version") != "1.0":
        raise PreparationReadError("unsupported preparation request schema")
    if request.get("state") != "prepared" or request.get("submitted") is not False:
        raise PreparationReadError("preparation request is not in an unsubmitted prepared state")

    theorem_id = _require_string(request, "theorem_id")
    if pointer and theorem_id != pointer["theorem_id"]:
        raise PreparationReadError("latest pointer theorem_id does not match request")

    aristotle = request.get("aristotle")
    if not isinstance(aristotle, dict):
        raise PreparationReadError("request.aristotle must be an object")
    if aristotle.get("package") != "aristotlelib==2.1.0":
        raise PreparationReadError("preparation must pin aristotlelib==2.1.0")
    prompt_relative = aristotle.get("prompt_file")
    project_relative = aristotle.get("project_dir")
    if not isinstance(prompt_relative, str) or not isinstance(project_relative, str):
        raise PreparationReadError("prompt_file and project_dir must be relative strings")

    attempt_dir = request_path.parent.resolve()
    prompt_path = _safe_artifact(attempt_dir, prompt_relative)
    project_dir = _safe_artifact(attempt_dir, project_relative)
    if not prompt_path.is_file() or not prompt_path.read_text(
        encoding="utf-8-sig"
    ).strip():
        raise PreparationReadError("prepared prompt file is missing or empty")
    if not project_dir.is_dir():
        raise PreparationReadError("prepared project directory is missing")

    artifacts = request.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise PreparationReadError("request.artifacts must be a nonempty object")
    artifact_hashes: dict[str, str] = {}
    for relative_text, expected in artifacts.items():
        if not isinstance(relative_text, str) or not isinstance(expected, str):
            raise PreparationReadError("artifact names and hashes must be strings")
        target = _safe_artifact(attempt_dir, relative_text)
        if not target.is_file():
            raise PreparationReadError(f"prepared artifact is missing: {relative_text}")
        actual = sha256_bytes(target.read_bytes())
        if actual != expected:
            raise PreparationReadError(f"prepared artifact was modified: {relative_text}")
        artifact_hashes[relative_text] = expected

    return LoadedPreparation(
        theorem_id=theorem_id,
        request=request,
        attempt_dir=attempt_dir,
        request_path=request_path,
        prompt_path=prompt_path,
        project_dir=project_dir,
        request_sha256=request_hash,
        artifact_hashes=artifact_hashes,
    )
