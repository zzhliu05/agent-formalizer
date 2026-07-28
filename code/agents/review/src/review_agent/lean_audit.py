from __future__ import annotations

import re
import shutil
from pathlib import Path

from formalization_agent.candidate_validation import (
    BuildRunner,
    run_local_lean_check,
    strip_lean_comments_and_strings,
)

from .models import MechanicalAudit
from .reader import LoadedCandidate

_PLACEHOLDER_RE = re.compile(r"\b(sorryAx|sorry|admit)\b")
_FORBIDDEN_DECLARATION_RE = re.compile(
    r"\b(axiom|constant|opaque)\s+([^\s:({]+)"
)
_DECLARATION_RE = re.compile(
    r"\b(?:theorem|lemma)\s+([A-Za-z_][A-Za-z0-9_'.]*)"
)
_SCOPE_OPEN_RE = re.compile(
    r"^\s*(namespace|section)\b(?:\s+([A-Za-z_][A-Za-z0-9_'.]*))?"
)
_SCOPE_END_RE = re.compile(r"^\s*end\b")
_AXIOM_LIST_RE = re.compile(r"depends on axioms:\s*\[([^\]]*)\]", re.DOTALL)
_STANDARD_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}


def _extract_declarations(source: str) -> list[str]:
    """Return theorem/lemma names as they resolve at the end of a Lean file."""
    scopes: list[tuple[str, str | None]] = []
    declarations: set[str] = set()
    for line in source.splitlines():
        opened = _SCOPE_OPEN_RE.match(line)
        if opened:
            scopes.append((opened.group(1), opened.group(2)))
            continue
        if _SCOPE_END_RE.match(line):
            if scopes:
                scopes.pop()
            continue
        namespace = ".".join(
            name
            for kind, name in scopes
            if kind == "namespace" and name
        )
        for match in _DECLARATION_RE.finditer(line):
            name = match.group(1)
            if name.startswith("_root_."):
                qualified = name.removeprefix("_root_.")
            elif namespace:
                qualified = f"{namespace}.{name}"
            else:
                qualified = name
            declarations.add(qualified)
    return sorted(declarations)


def _parse_axioms(output: str) -> list[str]:
    axioms: set[str] = set()
    for match in _AXIOM_LIST_RE.finditer(output):
        for item in match.group(1).split(","):
            value = item.strip().strip("'\"")
            if value:
                axioms.add(value)
    if "sorryAx" in output:
        axioms.add("sorryAx")
    return sorted(axioms)


def audit_candidate(
    candidate: LoadedCandidate,
    *,
    template_root: str | Path,
    work_dir: str | Path,
    build_timeout_seconds: int = 1800,
    build_runner: BuildRunner = run_local_lean_check,
) -> MechanicalAudit:
    placeholders: set[str] = set()
    forbidden: set[str] = set()
    declarations: set[str] = set()
    for source in candidate.lean_sources.values():
        stripped = strip_lean_comments_and_strings(source)
        placeholders.update(_PLACEHOLDER_RE.findall(stripped))
        forbidden.update(
            f"{kind} {name}"
            for kind, name in _FORBIDDEN_DECLARATION_RE.findall(stripped)
        )
        declarations.update(_extract_declarations(stripped))

    template = Path(template_root).resolve()
    mechanical_root = Path(work_dir).resolve()
    audit_root = mechanical_root / "lean-audit"
    shutil.copytree(
        candidate.candidate_root,
        audit_root,
        ignore=shutil.ignore_patterns(".lake"),
    )
    main_relative = candidate.main_path.relative_to(candidate.candidate_root)
    main_copy = audit_root / main_relative
    audit_path = audit_root / "Audit.lean"
    audit_source = main_copy.read_text(encoding="utf-8-sig").rstrip() + "\n\n"
    for name in sorted(declarations):
        audit_source += f"#print axioms {name}\n"
    audit_path.write_text(audit_source, encoding="utf-8")
    axiom_build = build_runner(
        audit_root,
        audit_path,
        template,
        build_timeout_seconds,
    )
    build_passed = (
        not axiom_build.timed_out
        and axiom_build.exit_code is not None
        and axiom_build.exit_code == 0
    )
    axiom_passed = (
        bool(declarations)
        and build_passed
    )
    axiom_output = "\n".join(
        part for part in (axiom_build.stdout, axiom_build.stderr) if part
    )
    (mechanical_root / "build-and-axiom-audit.log").write_text(
        "\n".join(
            (
                f"command: {' '.join(axiom_build.command)}",
                f"exit_code: {axiom_build.exit_code}",
                f"timed_out: {str(axiom_build.timed_out).lower()}",
                f"duration_seconds: {axiom_build.duration_seconds:.6f}",
                "",
                "[stdout]",
                axiom_build.stdout,
                "",
                "[stderr]",
                axiom_build.stderr,
            )
        ),
        encoding="utf-8",
    )
    axioms = _parse_axioms(axiom_output)
    unapproved = sorted(set(axioms) - _STANDARD_AXIOMS)
    passed = (
        build_passed
        and bool(declarations)
        and not placeholders
        and not forbidden
        and axiom_passed
        and "sorryAx" not in axioms
        and not unapproved
    )
    return MechanicalAudit(
        independent_build_passed=build_passed,
        independent_build_exit_code=axiom_build.exit_code,
        independent_build_timed_out=axiom_build.timed_out,
        declaration_names=sorted(declarations),
        prohibited_placeholders=sorted(placeholders),
        forbidden_declarations=sorted(forbidden),
        axiom_audit_passed=axiom_passed,
        axioms=axioms,
        unapproved_axioms=unapproved,
        axiom_output=axiom_output,
        passed=passed,
    )
