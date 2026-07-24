from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import LatestExtractionPointer, TheoremPackage


class PackageReadError(ValueError):
    """Raised when an Agent 1 package is absent, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class LoadedTheoremPackage:
    package: TheoremPackage
    attempt_dir: Path
    theorem_json_path: Path
    context_markdown_path: Path
    source_text_path: Path
    latest_pointer_path: Path | None
    theorem_json_sha256: str
    context_markdown_sha256: str
    source_text_sha256: str
    context_markdown: str
    source_text: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> tuple[Any, bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PackageReadError(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8-sig")), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageReadError(f"{path} is not valid UTF-8 JSON: {exc}") from exc


def _resolve_latest(pointer_path: Path) -> tuple[Path, LatestExtractionPointer]:
    payload, _ = _read_json(pointer_path)
    try:
        pointer = LatestExtractionPointer.model_validate(payload)
    except ValidationError as exc:
        raise PackageReadError(f"invalid latest pointer {pointer_path}: {exc}") from exc

    relative = Path(pointer.path)
    if relative.is_absolute():
        raise PackageReadError("latest pointer path must be relative")

    base = pointer_path.parent.resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise PackageReadError("latest pointer escapes its extraction directory")
    if target.name != "theorem.json":
        raise PackageReadError("latest pointer must resolve to theorem.json")
    if target.parent.name != f"attempt-{pointer.attempt:03d}":
        raise PackageReadError(
            "latest pointer attempt number does not match its target directory"
        )
    return target, pointer


def _resolve_input(input_path: Path) -> tuple[Path, Path | None, LatestExtractionPointer | None]:
    path = input_path.resolve()
    if path.is_file():
        if path.name == "theorem.json":
            return path, None, None
        if path.name == "latest.json":
            theorem_json, pointer = _resolve_latest(path)
            return theorem_json, path, pointer
        raise PackageReadError("input file must be theorem.json or latest.json")

    if not path.is_dir():
        raise PackageReadError(f"input path does not exist: {path}")

    direct = path / "theorem.json"
    if direct.is_file():
        return direct, None, None

    latest = path / "latest.json"
    if latest.is_file():
        theorem_json, pointer = _resolve_latest(latest)
        return theorem_json, latest, pointer

    extraction_latest = path / "extraction" / "latest.json"
    if extraction_latest.is_file():
        theorem_json, pointer = _resolve_latest(extraction_latest)
        return theorem_json, extraction_latest, pointer

    raise PackageReadError(
        "directory must contain theorem.json, latest.json, or extraction/latest.json"
    )


def load_theorem_package(input_path: str | Path) -> LoadedTheoremPackage:
    theorem_json_path, pointer_path, pointer = _resolve_input(Path(input_path))
    payload, theorem_bytes = _read_json(theorem_json_path)
    theorem_hash = sha256_bytes(theorem_bytes)

    if pointer and theorem_hash != pointer.theorem_json_sha256:
        raise PackageReadError(
            "theorem.json SHA-256 does not match the immutable latest pointer"
        )

    try:
        package = TheoremPackage.model_validate(payload)
    except ValidationError as exc:
        raise PackageReadError(f"invalid theorem package {theorem_json_path}: {exc}") from exc

    if pointer and package.theorem_id != pointer.theorem_id:
        raise PackageReadError("latest pointer theorem_id does not match theorem.json")

    attempt_dir = theorem_json_path.parent
    context_path = attempt_dir / "context.md"
    source_path = attempt_dir / "source.txt"
    missing = [path.name for path in (context_path, source_path) if not path.is_file()]
    if missing:
        raise PackageReadError(
            f"theorem attempt is missing required companion file(s): {', '.join(missing)}"
        )

    try:
        context_bytes = context_path.read_bytes()
        source_bytes = source_path.read_bytes()
        context_markdown = context_bytes.decode("utf-8-sig")
        source_text = source_bytes.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise PackageReadError(f"cannot read theorem companion files: {exc}") from exc

    if not context_markdown.strip() or not source_text.strip():
        raise PackageReadError("context.md and source.txt must both be non-empty")

    return LoadedTheoremPackage(
        package=package,
        attempt_dir=attempt_dir,
        theorem_json_path=theorem_json_path,
        context_markdown_path=context_path,
        source_text_path=source_path,
        latest_pointer_path=pointer_path,
        theorem_json_sha256=theorem_hash,
        context_markdown_sha256=sha256_bytes(context_bytes),
        source_text_sha256=sha256_bytes(source_bytes),
        context_markdown=context_markdown,
        source_text=source_text,
    )
