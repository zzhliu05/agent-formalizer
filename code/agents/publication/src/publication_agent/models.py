from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LeanSource:
    relative_path: str
    source_path: Path
    sha256: str
    text: str


@dataclass(frozen=True)
class PublicationEntry:
    theorem_id: str
    number: str
    kind: str
    label: str
    title: str
    statement: str
    source_pages: tuple[int, ...]
    proof_status: str
    proof: str
    proof_steps: tuple[dict[str, Any], ...]
    context_items: tuple[dict[str, Any], ...]
    uncertainties: tuple[str, ...]
    verdict: str
    theorem_json_path: Path
    theorem_json_sha256: str
    review_json_path: Path
    review_json_sha256: str
    handoff_path: Path
    main_relative_path: str
    main_sha256: str
    declaration_name: str
    declaration_line: int | None
    lean_sources: tuple[LeanSource, ...]

    @property
    def bundle_slug(self) -> str:
        if self.number:
            return self.number.replace(".", "-")
        return self.theorem_id

    @property
    def bundle_main_path(self) -> str:
        return f"lean/{self.bundle_slug}/{self.main_relative_path}"


@dataclass(frozen=True)
class BuildResult:
    output_dir: Path
    tex_path: Path
    manifest_path: Path
    pdf_path: Path | None
    entry_count: int

