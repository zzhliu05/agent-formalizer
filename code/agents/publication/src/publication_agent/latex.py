from __future__ import annotations

import re
from collections.abc import Iterable

from .models import PublicationEntry

_INLINE_TOKEN_RE = re.compile(
    r"(\*\*[^*\n]+?\*\*|(?<!\*)\*[^*\n]+?\*(?!\*)|`[^`\n]+?`)"
)

_KIND_ENVIRONMENT = {
    "axiom": "axiom",
    "corollary": "corollary",
    "definition": "definition",
    "lemma": "lemma",
    "proposition": "proposition",
    "theorem": "theorem",
}

_PROOF_STATUS_EN = {
    "complete": "the textbook provides a complete proof",
    "partial": "the textbook provides only a partial proof",
    "omitted": "the textbook omits the proof",
    "by_reference": "the textbook proves the result by reference",
    "left_to_reader": "the textbook leaves the proof to the reader",
    "not_applicable": "this principle or definition has no proof obligation",
    "uncertain": "the completeness of the printed proof is uncertain",
}

_CONTEXT_RELATION_EN = {
    "explicit_dependency": "Explicit dependency",
    "local_definition": "Local definition",
    "notation": "Notation",
    "prior_result": "Prior result",
    "section_scope": "Section context",
}

_PROOF_ROLE_EN = {
    "case_analysis": "Case analysis",
    "citation": "Citation",
    "computation": "Computation",
    "conclusion": "Conclusion",
    "construction": "Construction",
    "deduction": "Deduction",
    "reduction": "Reduction",
}


def _escape_plain(text: str) -> str:
    glyphs = {
        "■": r"\ensuremath{\blacksquare}",
        "□": r"\ensuremath{\square}",
    }
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
    }
    return "".join(glyphs.get(char, replacements.get(char, char)) for char in text)


def _format_inline_plain(text: str) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _INLINE_TOKEN_RE.finditer(text):
        pieces.append(_escape_plain(text[cursor : match.start()]))
        token = match.group(0)
        if token.startswith("**"):
            pieces.append(r"\textbf{" + _escape_plain(token[2:-2]) + "}")
        elif token.startswith("*"):
            pieces.append(r"\emph{" + _escape_plain(token[1:-1]) + "}")
        else:
            pieces.append(r"\texttt{" + _escape_plain(token[1:-1]) + "}")
        cursor = match.end()
    pieces.append(_escape_plain(text[cursor:]))
    return "".join(pieces)


def markdown_to_latex(text: str) -> str:
    """Convert the constrained Markdown emitted by Agent 1 into safe LaTeX."""

    output: list[str] = []
    plain: list[str] = []

    def flush_plain() -> None:
        if not plain:
            return
        raw = "".join(plain)
        paragraphs = re.split(r"\n[ \t]*\n", raw)
        rendered = [
            _format_inline_plain(re.sub(r"[ \t]*\n[ \t]*", " ", paragraph))
            for paragraph in paragraphs
        ]
        output.append("\n\n".join(rendered))
        plain.clear()

    index = 0
    while index < len(text):
        if text.startswith("$$", index):
            end = text.find("$$", index + 2)
            if end < 0:
                raise ValueError("unbalanced display-math delimiter in source Markdown")
            flush_plain()
            output.append(text[index : end + 2])
            index = end + 2
            continue
        if text[index] == "$" and (index == 0 or text[index - 1] != "\\"):
            end = index + 1
            while True:
                end = text.find("$", end)
                if end < 0:
                    raise ValueError("unbalanced inline-math delimiter in source Markdown")
                if text[end - 1] != "\\":
                    break
                end += 1
            flush_plain()
            output.append(text[index : end + 1])
            index = end + 1
            continue
        plain.append(text[index])
        index += 1
    flush_plain()
    return "".join(output)


def _environment_for(entry: PublicationEntry) -> str:
    return _KIND_ENVIRONMENT.get(entry.kind, "theorem")


def _entry_heading(entry: PublicationEntry) -> str:
    pieces = [piece for piece in (entry.label, entry.title) if piece]
    if pieces:
        return " ".join(pieces)
    if entry.number:
        return f"Entry {entry.number}"
    return entry.theorem_id


def _render_context(entry: PublicationEntry) -> str:
    if not entry.context_items:
        return ""
    rows = [r"\subsection*{Prerequisites and Context}", r"\begin{itemize}"]
    for context in entry.context_items:
        raw_relation = str(context.get("relation", "context"))
        relation = markdown_to_latex(
            _CONTEXT_RELATION_EN.get(raw_relation, raw_relation.replace("_", " "))
        )
        label = markdown_to_latex(str(context.get("label_verbatim") or ""))
        relevance = markdown_to_latex(str(context.get("relevance", "")))
        source = markdown_to_latex(str(context.get("text_verbatim", "")))
        prefix = relation if not label else f"{relation}: {label}"
        rows.append(r"\item \textbf{" + prefix + "} " + source)
        if relevance:
            rows.append(r"\par\emph{Relevance: }" + relevance)
    rows.append(r"\end{itemize}")
    return "\n".join(rows)


def _render_proof(entry: PublicationEntry) -> str:
    rows = [
        r"\subsection*{Natural-Language Proof}",
        r"\noindent\textbf{Source status: }"
        + _PROOF_STATUS_EN.get(entry.proof_status, entry.proof_status)
        + r".",
    ]
    if entry.proof:
        proof_text = re.sub(
            r"^\s*\*{1,2}Proof\.\*{1,2}\s*",
            "",
            entry.proof,
            count=1,
            flags=re.IGNORECASE,
        )
        rows.extend(
            [
                "",
                r"\begin{proof}[Textbook proof]",
                markdown_to_latex(proof_text),
                r"\end{proof}",
            ]
        )
    if entry.proof_steps:
        rows.extend(["", r"\paragraph{Structured proof steps}", r"\begin{enumerate}"])
        for step in entry.proof_steps:
            raw_role = str(step.get("role", "step"))
            role = markdown_to_latex(
                _PROOF_ROLE_EN.get(raw_role, raw_role.replace("_", " "))
            )
            step_text = re.sub(
                r"^\s*\*{1,2}Proof\.\*{1,2}\s*",
                "",
                str(step.get("text_verbatim", "")),
                count=1,
                flags=re.IGNORECASE,
            )
            text = markdown_to_latex(step_text)
            rows.append(r"\item \textbf{" + role + "} " + text)
        rows.append(r"\end{enumerate}")
    if entry.uncertainties:
        rows.extend(["", r"\begin{remark}", r"\textbf{Extraction uncertainties:}"])
        rows.append(r"\begin{itemize}")
        for uncertainty in entry.uncertainties:
            rows.append(r"\item " + markdown_to_latex(uncertainty))
        rows.extend([r"\end{itemize}", r"\end{remark}"])
    return "\n".join(rows)


def _render_formalization(entry: PublicationEntry) -> str:
    line_suffix = (
        f", declaration at line {entry.declaration_line}"
        if entry.declaration_line is not None
        else ""
    )
    declaration = entry.declaration_name or "Lean declaration"
    return "\n".join(
        [
            r"\subsection*{Lean Formalization}",
            r"\begin{remark}",
            r"\textbf{Agent 3 review: }"
            + markdown_to_latex(entry.verdict)
            + r".",
            r"\par\smallskip\noindent\textbf{Lean declaration: }\path{"
            + declaration
            + "}"
            + markdown_to_latex(line_suffix)
            + r".",
            "",
            r"\noindent\LeanSourceLink{"
            + entry.bundle_main_path
            + r"}{Open the corresponding Lean proof file}",
            r"\end{remark}",
        ]
    )


def render_entry(entry: PublicationEntry) -> str:
    environment = _environment_for(entry)
    heading = markdown_to_latex(_entry_heading(entry))
    pages = ", ".join(str(page) for page in entry.source_pages)
    statement = re.sub(
        r"^\s*\*\*[^*\n]+\*\*\s*",
        "",
        entry.statement,
        count=1,
    )
    rows = [
        r"\section{" + heading + "}",
        r"\begin{" + environment + "*}{" + heading + "}",
        markdown_to_latex(statement),
        r"\end{" + environment + "*}",
        "",
        r"\noindent\textbf{Source pages: }" + markdown_to_latex(pages) + r".",
    ]
    context = _render_context(entry)
    if context:
        rows.extend(["", context])
    rows.extend(["", _render_proof(entry), "", _render_formalization(entry)])
    return "\n".join(rows)


def render_book(
    entries: Iterable[PublicationEntry],
    *,
    title: str,
    subtitle: str,
    author: str,
    chapter_title: str,
) -> str:
    rendered_entries = "\n\n\\clearpage\n\n".join(
        render_entry(entry) for entry in entries
    )
    return rf"""% !TEX program = xelatex
% Generated by Agent 4. Do not edit generated theorem content by hand.
\documentclass[11pt]{{elegantbook}}

\title{{{markdown_to_latex(title)}}}
\subtitle{{{markdown_to_latex(subtitle)}}}
\author{{{markdown_to_latex(author)}}}
\institute{{Multi-Agent Formal Mathematics Textbook Project}}
\date{{\today}}
\version{{0.1}}
\bioinfo{{Pipeline}}{{Agent 1 $\rightarrow$ Agent 2 $\rightarrow$ Agent 3 $\rightarrow$ Agent 4}}
\extrainfo{{Every entry is bound to the exact Lean sources accepted by Agent 3.}}

\setcounter{{tocdepth}}{{2}}
\logo{{assets/logo-blue.png}}
\cover{{assets/cover.jpg}}
\definecolor{{customcolor}}{{RGB}}{{32,178,170}}
\colorlet{{coverlinecolor}}{{customcolor}}

\hypersetup{{
  colorlinks=true,
  linkcolor=structurecolor,
  urlcolor=blue,
  pdfnewwindow=true
}}
\urlstyle{{same}}

% The run: action opens the bundled source file in PDF viewers that permit
% local-file launch actions. The printed path remains useful when launch
% actions are disabled by viewer security settings.
\newcommand{{\LeanSourceLink}}[2]{{%
  \href{{run:#1}}{{\textbf{{#2}}}}%
  \par\smallskip\noindent\path{{#1}}%
}}

\begin{{document}}
\maketitle
\frontmatter
\tableofcontents

\mainmatter
\chapter{{{markdown_to_latex(chapter_title)}}}

\begin{{introduction}}
  \item This chapter contains only entries that passed Agent 3's mechanical,
        statement-equivalence, and proof-method gates.
  \item Each entry presents the textbook statement, prerequisite context,
        natural-language proof, and the corresponding Lean source entry point.
  \item If a PDF viewer blocks local launch actions, open the printed relative
        Lean path manually.
\end{{introduction}}

{rendered_entries}

\end{{document}}
"""
