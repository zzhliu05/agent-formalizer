from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class PublicationCompileError(RuntimeError):
    """Raised when the generated ElegantBook project does not compile."""


def compile_book(
    tex_path: Path,
    *,
    timeout_seconds: int = 1800,
) -> Path:
    latexmk = shutil.which("latexmk")
    if not latexmk:
        raise PublicationCompileError(
            "latexmk was not found; install or expose a TeX Live distribution"
        )
    root = tex_path.resolve().parent
    build_dir = root / "build"
    build_dir.mkdir(exist_ok=True)
    command = [
        latexmk,
        "-xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        f"-outdir={build_dir}",
        tex_path.name,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PublicationCompileError(
            f"LaTeX compilation timed out after {timeout_seconds} seconds"
        ) from exc
    log = (
        "command: "
        + subprocess.list2cmdline(command)
        + f"\nexit_code: {completed.returncode}\n\n[stdout]\n"
        + completed.stdout
        + "\n[stderr]\n"
        + completed.stderr
    )
    (root / "compile.log").write_text(log, encoding="utf-8")
    built_pdf = build_dir / f"{tex_path.stem}.pdf"
    if completed.returncode != 0 or not built_pdf.is_file():
        raise PublicationCompileError(
            f"LaTeX compilation failed; inspect {root / 'compile.log'}"
        )
    final_pdf = root / f"{tex_path.stem}.pdf"
    shutil.copy2(built_pdf, final_pdf)
    return final_pdf

