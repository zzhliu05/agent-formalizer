from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Iterator


SHORT_LAYOUT = "agent2-short-v1"
_SHORT_PREPARATION = "prep"
_SHORT_GENERATION = "gen"
_THEOREM_METADATA = "theorem.json"


def short_theorem_key(theorem_id: str) -> str:
    """Return a stable compact directory key without weakening identity checks."""
    digest = hashlib.sha256(theorem_id.encode("utf-8")).hexdigest()[:16]
    return f"t-{digest}"


def ensure_short_theorem_root(output_root: Path, theorem_id: str) -> Path:
    """Create or verify the compact theorem directory and its identity metadata."""
    root = output_root.resolve() / short_theorem_key(theorem_id)
    root.mkdir(parents=True, exist_ok=True)
    metadata_path = root / _THEOREM_METADATA
    expected = {
        "schema_version": "1.0",
        "layout": SHORT_LAYOUT,
        "theorem_key": root.name,
        "theorem_id": theorem_id,
    }
    if metadata_path.is_file():
        try:
            actual = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read theorem layout metadata: {exc}") from exc
        if actual != expected:
            raise ValueError(
                f"short theorem key collision or modified metadata: {metadata_path}"
            )
        return root
    if any(root.iterdir()):
        raise ValueError(
            f"compact theorem directory exists without identity metadata: {root}"
        )
    temporary = root / f".{_THEOREM_METADATA}.{uuid.uuid4().hex}.tmp"
    temporary.write_text(
        json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(metadata_path)
    return root


def short_preparation_root(output_root: Path, theorem_id: str) -> Path:
    return ensure_short_theorem_root(output_root, theorem_id) / _SHORT_PREPARATION


def parse_attempt_name(name: str) -> int | None:
    """Accept both compact ``001`` and legacy ``attempt-001`` directories."""
    suffix = name.removeprefix("attempt-") if name.startswith("attempt-") else name
    if len(suffix) != 3 or not suffix.isdigit() or int(suffix) < 1:
        return None
    return int(suffix)


def attempt_name(root: Path, attempt: int) -> str:
    if attempt < 1:
        raise ValueError("attempt must be positive")
    return (
        f"{attempt:03d}"
        if root.name in {_SHORT_PREPARATION, _SHORT_GENERATION}
        else f"attempt-{attempt:03d}"
    )


def iter_attempt_dirs(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir() and parse_attempt_name(child.name) is not None:
            yield child


def generation_root_for_preparation(attempt_dir: Path) -> Path:
    preparation_root = attempt_dir.resolve().parent
    if preparation_root.name == _SHORT_PREPARATION:
        return preparation_root.parent / _SHORT_GENERATION
    if preparation_root.name == "preparation":
        formalization_root = preparation_root.parent
        if formalization_root.name != "formalization":
            raise ValueError(
                "legacy preparation directory must live under formalization"
            )
        return formalization_root / "generation"
    raise ValueError(
        "preparation attempt must live directly under prep or preparation"
    )


def theorem_root_for_generation(generation_root: Path) -> Path:
    root = generation_root.resolve()
    if root.name == _SHORT_GENERATION:
        return root.parent
    if root.name == "generation" and root.parent.name == "formalization":
        return root.parent.parent
    raise ValueError("generation directory is not part of a theorem layout")


def generation_latest_path(theorem_root: Path) -> Path | None:
    root = theorem_root.resolve()
    for candidate in (
        root / _SHORT_GENERATION / "latest.json",
        root / "formalization" / "generation" / "latest.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def theorem_id_from_root(theorem_root: Path) -> str | None:
    metadata = theorem_root.resolve() / _THEOREM_METADATA
    if metadata.is_file():
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        theorem_id = payload.get("theorem_id") if isinstance(payload, dict) else None
        return theorem_id if isinstance(theorem_id, str) and theorem_id else None
    latest = generation_latest_path(theorem_root)
    if latest is not None:
        try:
            payload = json.loads(latest.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        theorem_id = payload.get("theorem_id") if isinstance(payload, dict) else None
        return theorem_id if isinstance(theorem_id, str) and theorem_id else None
    return None
