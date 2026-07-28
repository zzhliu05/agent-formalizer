from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from .reader import sha256_bytes


class CandidateValidationError(ValueError):
    """Raised when a downloaded Aristotle candidate fails an Agent 2 gate."""

    def __init__(self, message: str, build: BuildOutcome | None = None):
        super().__init__(message)
        self.build = build


@dataclass(frozen=True)
class BuildOutcome:
    command: list[str]
    exit_code: int | None
    timed_out: bool
    duration_seconds: float
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CandidateValidation:
    project_root: Path
    main_path: Path
    lean_file_hashes: dict[str, str]
    build: BuildOutcome


BuildRunner = Callable[[Path, Path, Path, int], BuildOutcome]

_PROHIBITED_RE = re.compile(r"\b(sorryAx|sorry|admit)\b")
_DECLARATION_RE = re.compile(r"\b(theorem|lemma)\b")
_IMPORT_RE = re.compile(
    r"^\s*import\s+([A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*)",
    re.MULTILINE,
)


def safe_extract_tar(
    archive_path: Path,
    destination: Path,
    *,
    max_files: int = 5000,
    max_total_bytes: int = 500 * 1024 * 1024,
) -> None:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    total_bytes = 0
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        if len(members) > max_files:
            raise CandidateValidationError("result archive contains too many entries")
        for member in members:
            if "\\" in member.name:
                raise CandidateValidationError(
                    f"unsafe result archive path separator: {member.name}"
                )
            if member.name in {".", "./"} and member.isdir():
                continue
            pure = PurePosixPath(member.name)
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or not pure.parts
                or ":" in pure.parts[0]
            ):
                raise CandidateValidationError(
                    f"unsafe result archive path: {member.name}"
                )
            normalized = pure.as_posix()
            if normalized in seen:
                raise CandidateValidationError(
                    f"duplicate result archive path: {member.name}"
                )
            seen.add(normalized)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise CandidateValidationError(
                    f"unsupported result archive entry: {member.name}"
                )
            if not (member.isdir() or member.isfile()):
                raise CandidateValidationError(
                    f"unsupported result archive type: {member.name}"
                )
            total_bytes += member.size
            if total_bytes > max_total_bytes:
                raise CandidateValidationError("result archive is too large")

        for member in members:
            if member.name in {".", "./"} and member.isdir():
                continue
            target = (destination / PurePosixPath(member.name)).resolve()
            if not target.is_relative_to(destination):
                raise CandidateValidationError(
                    f"result archive escapes destination: {member.name}"
                )
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise CandidateValidationError(
                    f"cannot read result archive entry: {member.name}"
                )
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def strip_lean_comments_and_strings(source: str) -> str:
    output: list[str] = []
    index = 0
    block_depth = 0
    in_string = False
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if block_depth:
            if current == "/" and following == "-":
                block_depth += 1
                output.extend("  ")
                index += 2
            elif current == "-" and following == "/":
                block_depth -= 1
                output.extend("  ")
                index += 2
            else:
                output.append("\n" if current == "\n" else " ")
                index += 1
            continue
        if in_string:
            if current == "\\" and following:
                output.extend("  ")
                index += 2
            elif current == '"':
                in_string = False
                output.append(" ")
                index += 1
            else:
                output.append("\n" if current == "\n" else " ")
                index += 1
            continue
        if current == "/" and following == "-":
            block_depth = 1
            output.extend("  ")
            index += 2
        elif current == "-" and following == "-":
            while index < len(source) and source[index] != "\n":
                output.append(" ")
                index += 1
        elif current == '"':
            in_string = True
            output.append(" ")
            index += 1
        else:
            output.append(current)
            index += 1
    if block_depth:
        raise CandidateValidationError("Lean source contains an unterminated block comment")
    if in_string:
        raise CandidateValidationError("Lean source contains an unterminated string")
    return "".join(output)


def _find_project_root(extracted_root: Path) -> tuple[Path, Path]:
    main_files = [
        path
        for path in extracted_root.rglob("Main.lean")
        if ".lake" not in path.parts
    ]
    if len(main_files) != 1:
        raise CandidateValidationError(
            f"expected exactly one Main.lean, found {len(main_files)}"
        )
    main_path = main_files[0].resolve()
    return main_path.parent, main_path


def compact_candidate_tree(extracted_root: Path, destination: Path) -> Path:
    """Keep only the Lean project tree; the original archive remains authoritative."""
    project_root, _ = _find_project_root(extracted_root)
    target = destination.resolve()
    if target.exists():
        raise CandidateValidationError(
            f"compact candidate destination already exists: {target}"
        )
    project_root.replace(target)
    if extracted_root.exists():
        shutil.rmtree(extracted_root)
    return target


def _verify_protected_files(
    project_root: Path, prepared_project: Path, artifact_hashes: dict[str, str]
) -> None:
    protected = {
        "SOURCE_THEOREM.md",
        "lean-toolchain",
        "lakefile.toml",
        "lake-manifest.json",
    }
    artifact_prefix = next(
        (
            prefix
            for prefix in ("lean", "project", prepared_project.name)
            if any(f"{prefix}/{relative}" in artifact_hashes for relative in protected)
        ),
        prepared_project.name,
    )
    for relative in protected:
        artifact_key = f"{artifact_prefix}/{relative}"
        expected = artifact_hashes.get(artifact_key)
        prepared = prepared_project / relative
        candidate = project_root / relative
        if expected is None or not prepared.is_file():
            raise CandidateValidationError(
                f"prepared protected artifact is missing: {artifact_key}"
            )
        if not candidate.is_file():
            raise CandidateValidationError(
                f"Aristotle result removed protected file: {relative}"
            )
        if sha256_bytes(candidate.read_bytes()) != expected:
            raise CandidateValidationError(
                f"Aristotle result modified protected file: {relative}"
            )


def _scan_lean_files(
    project_root: Path, prepared_main_hash: str
) -> dict[str, str]:
    lean_files = [
        path for path in project_root.rglob("*.lean") if ".lake" not in path.parts
    ]
    if not lean_files:
        raise CandidateValidationError("Aristotle result contains no Lean source")
    hashes: dict[str, str] = {}
    has_declaration = False
    for path in lean_files:
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise CandidateValidationError(f"cannot read Lean source {path}: {exc}") from exc
        stripped = strip_lean_comments_and_strings(source)
        match = _PROHIBITED_RE.search(stripped)
        if match:
            relative = path.relative_to(project_root).as_posix()
            raise CandidateValidationError(
                f"prohibited Lean placeholder '{match.group(1)}' in {relative}"
            )
        has_declaration = has_declaration or bool(_DECLARATION_RE.search(stripped))
        hashes[path.relative_to(project_root).as_posix()] = sha256_bytes(
            path.read_bytes()
        )
    main_hash = hashes.get("Main.lean")
    if main_hash == prepared_main_hash:
        raise CandidateValidationError(
            "Aristotle returned the unchanged staging Main.lean without a proof"
        )
    if not has_declaration:
        raise CandidateValidationError(
            "Aristotle result contains no theorem or lemma declaration"
        )
    return hashes


def _run_lean_process(
    command: list[str],
    *,
    project_root: Path,
    lean_env: dict[str, str],
    timeout_seconds: float,
) -> BuildOutcome:
    start = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=project_root,
        env=lean_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=max(0.001, timeout_seconds))
        return BuildOutcome(
            command=command,
            exit_code=process.returncode,
            timed_out=False,
            duration_seconds=time.monotonic() - start,
            stdout=stdout,
            stderr=stderr,
        )
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            import signal

            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        return BuildOutcome(
            command=command,
            exit_code=None,
            timed_out=True,
            duration_seconds=time.monotonic() - start,
            stdout=stdout,
            stderr=stderr,
        )


def _local_import_order(project_root: Path, target: Path) -> list[Path]:
    """Return local imported modules in dependency-first order."""
    root = project_root.resolve()
    target = target.resolve()
    visiting: set[Path] = set()
    visited: set[Path] = set()
    ordered: list[Path] = []

    def visit(source_path: Path) -> None:
        source_path = source_path.resolve()
        if source_path in visited:
            return
        if source_path in visiting:
            relative = source_path.relative_to(root).as_posix()
            raise CandidateValidationError(
                f"local Lean import cycle contains {relative}"
            )
        visiting.add(source_path)
        try:
            source = source_path.read_text(encoding="utf-8-sig")
            stripped = strip_lean_comments_and_strings(source)
        except (OSError, UnicodeDecodeError) as exc:
            raise CandidateValidationError(
                f"cannot inspect local Lean imports in {source_path}: {exc}"
            ) from exc
        for module in _IMPORT_RE.findall(stripped):
            relative = Path(*module.split(".")).with_suffix(".lean")
            dependency = (root / relative).resolve()
            if dependency.is_relative_to(root) and dependency.is_file():
                visit(dependency)
        visiting.remove(source_path)
        visited.add(source_path)
        if source_path != target:
            ordered.append(source_path)

    visit(target)
    return ordered


def run_local_lean_check(
    project_root: Path,
    main_path: Path,
    template_root: Path,
    timeout_seconds: int,
) -> BuildOutcome:
    lake = shutil.which("lake")
    if not lake:
        raise CandidateValidationError("lake executable is not available")

    try:
        env_probe = subprocess.run(
            [lake, "--dir", str(template_root), "env"],
            cwd=template_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=max(1, min(timeout_seconds, 300)),
        )
    except subprocess.TimeoutExpired as exc:
        raise CandidateValidationError(
            "timed out while loading the pinned Lake environment"
        ) from exc
    if env_probe.returncode != 0:
        raise CandidateValidationError(
            f"cannot obtain the pinned Lake environment: {env_probe.stderr.strip()}"
        )
    lean_env = os.environ.copy()
    for line in env_probe.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            if key:
                lean_env[key] = value
    sysroot = lean_env.get("LEAN_SYSROOT")
    if not sysroot:
        raise CandidateValidationError("Lake environment did not provide LEAN_SYSROOT")
    executable = Path(sysroot) / "bin" / ("lean.exe" if os.name == "nt" else "lean")
    if not executable.is_file():
        raise CandidateValidationError(f"Lean executable is missing: {executable}")

    root = project_root.resolve()
    target = main_path.resolve()
    dependencies = _local_import_order(root, target)
    started = time.monotonic()
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    with tempfile.TemporaryDirectory(prefix="agent2-lean-modules-") as directory:
        module_root = Path(directory).resolve()
        inherited_path = lean_env.get("LEAN_PATH", "")
        lean_env["LEAN_PATH"] = (
            str(module_root)
            if not inherited_path
            else str(module_root) + os.pathsep + inherited_path
        )
        for dependency in dependencies:
            elapsed = time.monotonic() - started
            remaining = timeout_seconds - elapsed
            relative = dependency.relative_to(root)
            output = module_root / relative.with_suffix(".olean")
            output.parent.mkdir(parents=True, exist_ok=True)
            command = [
                str(executable),
                "-o",
                str(output),
                str(relative),
            ]
            outcome = _run_lean_process(
                command,
                project_root=root,
                lean_env=lean_env,
                timeout_seconds=remaining,
            )
            stdout_parts.append(
                f"[local module {relative.as_posix()}]\n{outcome.stdout}"
            )
            stderr_parts.append(
                f"[local module {relative.as_posix()}]\n{outcome.stderr}"
            )
            if outcome.timed_out or outcome.exit_code != 0:
                return BuildOutcome(
                    command=outcome.command,
                    exit_code=outcome.exit_code,
                    timed_out=outcome.timed_out,
                    duration_seconds=time.monotonic() - started,
                    stdout="\n".join(stdout_parts),
                    stderr="\n".join(stderr_parts),
                )

        relative_main = target.relative_to(root)
        command = [str(executable), str(relative_main)]
        outcome = _run_lean_process(
            command,
            project_root=root,
            lean_env=lean_env,
            timeout_seconds=timeout_seconds - (time.monotonic() - started),
        )
        stdout_parts.append(f"[target {relative_main.as_posix()}]\n{outcome.stdout}")
        stderr_parts.append(f"[target {relative_main.as_posix()}]\n{outcome.stderr}")
        return BuildOutcome(
            command=outcome.command,
            exit_code=outcome.exit_code,
            timed_out=outcome.timed_out,
            duration_seconds=time.monotonic() - started,
            stdout="\n".join(stdout_parts),
            stderr="\n".join(stderr_parts),
        )


def validate_candidate(
    extracted_root: Path,
    prepared_project: Path,
    artifact_hashes: dict[str, str],
    template_root: Path,
    build_timeout_seconds: int,
    build_runner: BuildRunner = run_local_lean_check,
) -> CandidateValidation:
    project_root, main_path = _find_project_root(extracted_root)
    _verify_protected_files(project_root, prepared_project, artifact_hashes)
    prepared_main_hash = next(
        (
            artifact_hashes[key]
            for key in ("lean/Main.lean", "project/Main.lean")
            if key in artifact_hashes
        ),
        None,
    )
    if not prepared_main_hash:
        raise CandidateValidationError("prepared Main.lean hash is missing")
    lean_hashes = _scan_lean_files(project_root, prepared_main_hash)
    build = build_runner(
        project_root, main_path, template_root, build_timeout_seconds
    )
    if build.timed_out:
        raise CandidateValidationError("local Lean validation timed out", build)
    if build.exit_code != 0:
        raise CandidateValidationError(
            f"local Lean validation failed with exit code {build.exit_code}",
            build,
        )
    return CandidateValidation(
        project_root=project_root,
        main_path=main_path,
        lean_file_hashes=lean_hashes,
        build=build,
    )
