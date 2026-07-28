from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from publication_agent.latex import markdown_to_latex, render_book
from publication_agent.models import LeanSource, PublicationEntry
from publication_agent.reader import PublicationReadError, load_publication_entries


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _entry(tmp_path: Path) -> PublicationEntry:
    lean = tmp_path / "Main.lean"
    lean.write_text("import Mathlib\n\ntheorem demo : True := by trivial\n", encoding="utf-8")
    digest = _sha(lean.read_bytes())
    return PublicationEntry(
        theorem_id="demo-0-1",
        number="0.1",
        kind="theorem",
        label="0.1 Theorem.",
        title="Demo",
        statement="**0.1 Theorem.** If $x \\in X$, then $x=x$.",
        source_pages=(1,),
        proof_status="complete",
        proof="*Proof.* Reflexivity.",
        proof_steps=(
            {
                "order": 1,
                "role": "conclusion",
                "text_verbatim": "Use $x=x$.",
                "source_pages": [1],
            },
        ),
        context_items=(
            {
                "relation": "definition",
                "label_verbatim": "",
                "text_verbatim": "$X$ is a set.",
                "source_pages": [1],
                "relevance": "Defines the domain.",
            },
        ),
        uncertainties=(),
        verdict="accepted",
        theorem_json_path=tmp_path / "theorem.json",
        theorem_json_sha256="a" * 64,
        review_json_path=tmp_path / "review.json",
        review_json_sha256="b" * 64,
        handoff_path=tmp_path / "handoff.json",
        main_relative_path="Main.lean",
        main_sha256=digest,
        declaration_name="demo",
        declaration_line=3,
        lean_sources=(
            LeanSource(
                relative_path="Main.lean",
                source_path=lean,
                sha256=digest,
                text=lean.read_text(encoding="utf-8"),
            ),
        ),
    )


def test_markdown_to_latex_preserves_math_and_escapes_text() -> None:
    rendered = markdown_to_latex("**Result:** $a_b=c$ & 100%.")
    assert rendered == r"\textbf{Result:} $a_b=c$ \& 100\%."


def test_markdown_to_latex_rejects_unbalanced_math() -> None:
    with pytest.raises(ValueError, match="unbalanced"):
        markdown_to_latex("broken $x")


def test_render_book_contains_lean_run_link(tmp_path: Path) -> None:
    rendered = render_book(
        [_entry(tmp_path)],
        title="Book",
        subtitle="Formal",
        author="Agent",
        chapter_title="Chapter 0",
    )
    assert r"\LeanSourceLink{lean/0-1/Main.lean}" in rendered
    assert r"\href{run:#1}" in rendered
    assert r"$x \in X$" in rendered
    assert "Agent 3" in rendered
    assert r"\documentclass[11pt]{elegantbook}" in rendered
    assert "Natural-Language Proof" in rendered


def test_incomplete_chapter_is_rejected(tmp_path: Path) -> None:
    summary = tmp_path / "chapter-summary.json"
    summary.write_text(
        json.dumps({"complete": False, "items": [{"verdict": "accepted"}]}),
        encoding="utf-8",
    )
    with pytest.raises(PublicationReadError, match="not complete"):
        load_publication_entries(summary, [tmp_path])


def test_nonaccepted_chapter_item_is_rejected(tmp_path: Path) -> None:
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "verdict": "needs_reformalization",
                "input": {"agent1_theorem_json_sha256": "a" * 64},
            }
        ),
        encoding="utf-8",
    )
    summary = tmp_path / "chapter-summary.json"
    summary.write_text(
        json.dumps(
            {
                "complete": True,
                "items": [
                    {
                        "theorem_id": "bad",
                        "verdict": "needs_reformalization",
                        "final_review_path": str(review),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PublicationReadError, match="not accepted"):
        load_publication_entries(summary, [tmp_path])
