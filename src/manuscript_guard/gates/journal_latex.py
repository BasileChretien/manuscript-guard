"""G4: a LaTeX manuscript states what the journal's profile asks of a LaTeX source (DESIGN.md,
"LaTeX manuscripts", "The journal profile").

A profile's `latex:` block names the class the journal asks for, and how its bibliography is
made: BibTeX with a `bst`, or biblatex with a `style`. Each is quoted from the journal's page,
as every rule of a profile is. Where the entry file's `\\documentclass`, `\\bibliographystyle`
or biblatex's `style=` differs, G4 warns: the journal may take the paper and set it again, or
send it back, and either way the author should know before the build. A Markdown manuscript,
and a profile with no `latex:` block, have nothing to compare.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report

GATE = "G4"
#: biblatex's `style=` or `bibstyle=`, after a comma, a comment or a line break: not
#: `citestyle=` (round 1 of step 6: `[%` and `style=apa]` on the next line was missed).
_STYLE = re.compile(r"(?:^|[,%\s])\s*(?:style|bibstyle)\s*=\s*([^,\s%]+)")


def check_latex_profile(project: Project, document: dict, path: Path) -> Report:
    """A warning where the LaTeX manuscript's class or bibliography is not the profile's."""
    from manuscript_guard.text.latex.structure import ENTRY, read_document
    from manuscript_guard.text.reader import LATEX, manuscript_format

    wanted = document.get("latex")
    folder = project.path("manuscript")
    if not wanted or manuscript_format(folder) != LATEX:
        return Report()
    entry = folder / ENTRY
    sources = read_document(folder, supplementary=False).sources
    if not any(source.path == ENTRY for source in sources):
        return Report()  # the entry file cannot be read, which is said where it is read
    # What the preamble states, in the entry file or a file or package it reads (round 1 of
    # step 6: `\\input{preamble}` holding biblatex was taken for none).
    found = {kind: value for source in sources if not source.loose
             for kind, value in source.reading.declared}  # fmt: skip
    journal = document.get("name") or "the journal"
    findings = []
    if wanted.get("class") and found.get("class") != wanted["class"]:
        findings.append(_differs("latex-class-differs", entry, path,
                                 f"the manuscript's class is {found.get('class') or 'none'}, and "
                                 f"{journal} asks for {wanted['class']}",
                                 f"\\documentclass{{{wanted['class']}}}"))  # fmt: skip
    findings += _bibliography(wanted.get("bibliography") or {}, found, journal, entry, path)
    return Report(tuple(findings))


def _bibliography(wanted: dict, found: dict, journal: str, entry: Path, path: Path) -> list:
    """Where the bibliography is made otherwise than the profile says."""
    kind = wanted.get("kind")
    if kind is None:
        return []
    style = _STYLE.search(found.get("biblatex", "")) if "biblatex" in found else None
    bst, named = wanted.get("bst", "..."), wanted.get("style", "...")
    if kind == "bibtex" and "biblatex" in found:
        return [_differs("latex-bibliography-differs", entry, path,
                         f"the manuscript loads biblatex, and {journal} asks for BibTeX",
                         f"\\bibliographystyle{{{bst}}} with BibTeX")]  # fmt: skip
    if kind == "biblatex" and "biblatex" not in found:
        return [_differs("latex-bibliography-differs", entry, path,
                         f"the manuscript does not load biblatex, and {journal} asks for it",
                         f"\\usepackage[style={named}]{{biblatex}}")]  # fmt: skip
    if kind == "bibtex" and wanted.get("bst") and found.get("bst") != wanted["bst"]:
        return [_differs("latex-bibliography-differs", entry, path,
                         f"the manuscript's bibliography style is {found.get('bst') or 'none'}, "
                         f"and {journal} asks for {wanted['bst']}",
                         f"\\bibliographystyle{{{wanted['bst']}}}")]  # fmt: skip
    written = style.group(1) if style else None
    if kind == "biblatex" and wanted.get("style") and written != wanted["style"]:
        return [_differs("latex-bibliography-differs", entry, path,
                         f"the manuscript's biblatex style is {written or 'the default'}, and "
                         f"{journal} asks for {wanted['style']}",
                         f"\\usepackage[style={wanted['style']}]{{biblatex}}")]  # fmt: skip
    return []


def _differs(code: str, entry: Path, profile: Path, message: str, wanted: str) -> Finding:
    return Finding(gate=GATE, code=code, severity=WARN, message=message, path=entry,
                   hint=f"write {wanted}, as the journal's page asks ({profile.name})")  # fmt: skip
