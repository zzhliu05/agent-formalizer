from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from formalization_agent.candidate_validation import BuildRunner, run_local_lean_check
from formalization_agent.layout import (
    generation_latest_path,
    iter_attempt_dirs,
    parse_attempt_name,
    theorem_id_from_root,
)

from .loop import ReviewLoopResult, run_review_loop
from .provider import ReviewProvider
from .revision import RevisionTransport


class ChapterReviewError(RuntimeError):
    """Raised when a chapter review inventory is unsafe or empty."""


ACCEPTED_VERDICTS = {"accepted", "accepted_declaration"}


@dataclass(frozen=True)
class ChapterItemResult:
    theorem_id: str
    status: str
    verdict: str | None
    handoff_path: Path | None
    final_review_path: Path | None
    cycles: int
    revision_count: int
    semantic_revision_count: int
    agent2_validation_repair_count: int
    stop_reason: str | None
    error: str | None


@dataclass(frozen=True)
class ChapterReviewResult:
    chapter_root: Path
    summary_path: Path
    complete: bool
    items: tuple[ChapterItemResult, ...]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _theorem_number(theorem_id: str) -> tuple[int, str]:
    match = re.search(r"-0-(\d+)(?:-|$)", theorem_id)
    return (int(match.group(1)) if match else 10**9, theorem_id)


def _run_from_pointer(pointer_path: Path) -> Path:
    try:
        payload = json.loads(pointer_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChapterReviewError(
            f"cannot read generation pointer {pointer_path}: {exc}"
        ) from exc
    relative_text = payload.get("path") if isinstance(payload, dict) else None
    if not isinstance(relative_text, str):
        raise ChapterReviewError(f"generation pointer is invalid: {pointer_path}")
    relative = Path(relative_text)
    run_path = (pointer_path.parent / relative).resolve()
    generation_root = pointer_path.parent.resolve()
    if (
        relative.is_absolute()
        or not run_path.is_relative_to(generation_root)
        or run_path.name != "run.json"
    ):
        raise ChapterReviewError(f"generation pointer is unsafe: {pointer_path}")
    return run_path


def _ready_handoff(run_path: Path) -> Path | None:
    try:
        run = json.loads(run_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(run, dict) or run.get("state") != "ready_for_review":
        return None
    handoff = run_path.parent / "handoff.json"
    return handoff if handoff.is_file() else None


def _latest_handoff(theorem_root: Path) -> Path:
    latest_path = generation_latest_path(theorem_root)
    if latest_path is None:
        raise ChapterReviewError(
            f"generation latest pointer is missing for {theorem_root.name}"
        )
    current = _ready_handoff(_run_from_pointer(latest_path))
    if current is not None:
        return current

    ready_pointer = latest_path.parent / "latest-ready.json"
    if ready_pointer.is_file():
        ready = _ready_handoff(_run_from_pointer(ready_pointer))
        if ready is not None:
            return ready

    attempts = sorted(
        iter_attempt_dirs(latest_path.parent),
        key=lambda path: parse_attempt_name(path.name) or 0,
        reverse=True,
    )
    for attempt in attempts:
        ready = _ready_handoff(attempt / "run.json")
        if ready is not None:
            return ready
    raise ChapterReviewError(
        f"generation history has no ready handoff for {theorem_root.name}"
    )


def _current_acceptance(theorem_root: Path, handoff_path: Path) -> Path | None:
    latest_path = theorem_root / "review" / "latest.json"
    if not latest_path.is_file():
        return None
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8-sig"))
        if latest.get("verdict") not in ACCEPTED_VERDICTS:
            return None
        review_path = (latest_path.parent / Path(latest["path"])).resolve()
        if not review_path.is_relative_to(latest_path.parent.resolve()):
            return None
        review = json.loads(review_path.read_text(encoding="utf-8-sig"))
        reviewed_handoff = Path(review["input"]["agent2_handoff_path"]).resolve()
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ):
        return None
    return review_path if reviewed_handoff == handoff_path.resolve() else None


def _item_payload(item: ChapterItemResult) -> dict[str, Any]:
    return {
        "theorem_id": item.theorem_id,
        "status": item.status,
        "verdict": item.verdict,
        "handoff_path": str(item.handoff_path) if item.handoff_path else None,
        "final_review_path": (
            str(item.final_review_path) if item.final_review_path else None
        ),
        "cycles": item.cycles,
        "revision_count": item.revision_count,
        "semantic_revision_count": item.semantic_revision_count,
        "agent2_validation_repair_count": item.agent2_validation_repair_count,
        "stop_reason": item.stop_reason,
        "error": item.error,
    }


def run_chapter_review(
    chapter_root: str | Path,
    source_root: str | Path,
    *,
    provider: ReviewProvider,
    revision_transport: RevisionTransport,
    template_root: str | Path,
    max_revisions_per_theorem: int = 8,
    max_validation_repairs_per_revision: int = 3,
    build_timeout_seconds: int = 1800,
    poll_seconds: float = 30.0,
    remote_timeout_seconds: float = 7200.0,
    build_runner: BuildRunner = run_local_lean_check,
) -> ChapterReviewResult:
    root = Path(chapter_root).resolve()
    sources = Path(source_root).resolve()
    if not root.is_dir() or not sources.is_dir():
        raise ChapterReviewError("chapter and source roots must be directories")
    theorem_items = [
        (theorem_id, path)
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
        if generation_latest_path(path) is not None
        if (theorem_id := theorem_id_from_root(path)) is not None
    ]
    theorem_items.sort(key=lambda item: _theorem_number(item[0]))
    if not theorem_items:
        raise ChapterReviewError("chapter root contains no Agent 2 generations")

    output_root = root / "_chapter_review"
    summary_path = output_root / "chapter-summary.json"
    items: list[ChapterItemResult] = []
    for theorem_id, theorem_root in theorem_items:
        handoff: Path | None = None
        try:
            handoff = _latest_handoff(theorem_root)
            accepted_review = _current_acceptance(theorem_root, handoff)
            if accepted_review is not None:
                item = ChapterItemResult(
                    theorem_id=theorem_id,
                    status="accepted_existing",
                    verdict=json.loads(
                        accepted_review.read_text(encoding="utf-8-sig")
                    )["verdict"],
                    handoff_path=handoff,
                    final_review_path=accepted_review,
                    cycles=0,
                    revision_count=0,
                    semantic_revision_count=0,
                    agent2_validation_repair_count=0,
                    stop_reason="accepted_existing",
                    error=None,
                )
            else:
                source = sources / theorem_id
                if not source.is_dir():
                    raise ChapterReviewError(
                        f"Agent 1 source package is missing for {theorem_id}"
                    )
                loop: ReviewLoopResult = run_review_loop(
                    handoff,
                    source,
                    provider=provider,
                    revision_transport=revision_transport,
                    template_root=template_root,
                    max_revisions=max_revisions_per_theorem,
                    max_validation_repairs_per_revision=(
                        max_validation_repairs_per_revision
                    ),
                    build_timeout_seconds=build_timeout_seconds,
                    poll_seconds=poll_seconds,
                    remote_timeout_seconds=remote_timeout_seconds,
                    build_runner=build_runner,
                )
                item = ChapterItemResult(
                    theorem_id=theorem_id,
                    status=(
                        "accepted"
                        if loop.verdict in ACCEPTED_VERDICTS
                        else "terminal_nonaccepted"
                    ),
                    verdict=loop.verdict,
                    handoff_path=handoff,
                    final_review_path=loop.final_review.review_path,
                    cycles=loop.cycles,
                    revision_count=len(loop.revisions),
                    semantic_revision_count=loop.semantic_revision_count,
                    agent2_validation_repair_count=(
                        loop.validation_repair_count
                    ),
                    stop_reason=loop.stop_reason,
                    error=None,
                )
        except Exception as exc:
            item = ChapterItemResult(
                theorem_id=theorem_id,
                status="error",
                verdict=None,
                handoff_path=handoff,
                final_review_path=None,
                cycles=0,
                revision_count=0,
                semantic_revision_count=0,
                agent2_validation_repair_count=0,
                stop_reason="error",
                error=f"{type(exc).__name__}: {exc}",
            )
        items.append(item)
        _write_json_atomic(
            summary_path,
            {
                "schema_version": "1.0",
                "updated_at": _now(),
                "complete": False,
                "counts": {
                    "total": len(theorem_items),
                    "processed": len(items),
                    "accepted": sum(
                        entry.verdict in ACCEPTED_VERDICTS for entry in items
                    ),
                    "declaration_only": sum(
                        entry.verdict == "accepted_declaration" for entry in items
                    ),
                },
                "items": [_item_payload(entry) for entry in items],
            },
        )

    complete = all(item.verdict in ACCEPTED_VERDICTS for item in items)
    _write_json_atomic(
        summary_path,
        {
            "schema_version": "1.0",
            "updated_at": _now(),
            "complete": complete,
            "counts": {
                "total": len(items),
                "processed": len(items),
                "accepted": sum(
                    item.verdict in ACCEPTED_VERDICTS for item in items
                ),
                "declaration_only": sum(
                    item.verdict == "accepted_declaration" for item in items
                ),
            },
            "items": [_item_payload(item) for item in items],
        },
    )
    return ChapterReviewResult(
        chapter_root=root,
        summary_path=summary_path,
        complete=complete,
        items=tuple(items),
    )
