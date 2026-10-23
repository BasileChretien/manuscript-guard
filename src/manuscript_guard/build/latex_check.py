"""BUILD for a LaTeX manuscript: what the reader refused, and the files nothing inputs.

Each refusal of the LaTeX reader is a finding at its file and line: a group, an environment,
maths, a `\\verb` or an `\\iffalse` left open (`tex-unbalanced`), and what the reader does not
read exactly, an `\\input` it cannot follow among them (`tex-refused`). Both fail at every
stage: past a refusal the rest of the file is read as prose, so the gates read it, but not as
LaTeX prints it. A `.tex` file that no `\\input` the reader follows names is a warning
(`tex-not-input`): it is read as loose body under no heading. That is a file nothing inputs,
and also one input past a refusal or from inside a definition, which LaTeX may still print.
A `.tex` file that holds a document of its own, its own `\\begin{document}`, beside a
document's entry file is another document, which is never read as part of that one
(`tex-second-document`): it fails at every stage, as a file of the other format does, since
no gate reads it and no build prints it. A file a class or a package inputs is neither: it
is the class's. A Markdown manuscript has none of these.
"""

from __future__ import annotations

from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.text.latex.structure import SECOND_DOCUMENT, SUPPLEMENT_ENTRY, read_document
from manuscript_guard.text.reader import LATEX, manuscript_format

GATE = "BUILD"
_HINTS = {
    "tex-unbalanced": "close it where it should close, or take out what closes nothing",
    "tex-refused": "write it so that it can be read, or take it out; the rest of the file is "
    "read as prose until then",
    SECOND_DOCUMENT: f"if it is the supplement, make it manuscript/{SUPPLEMENT_ENTRY}; if it is "
    "not, move it out of manuscript/ or into a folder whose name starts with '_'",
}


def check_latex(project) -> Report:
    """Every refusal of the reader, in the main text's document and the supplement's, and
    every file of either that nothing inputs."""
    folder = project.path("manuscript")
    if manuscript_format(folder) != LATEX:
        return Report()
    findings: list[Finding] = []
    has_supplement = any((folder / "supplementary").rglob("*.tex"))
    for supplementary in (False, True) if has_supplement else (False,):
        document = read_document(folder, supplementary=supplementary)
        texts = {source.path: source.text for source in document.sources}
        for path, refusal in document.refusals:
            # A document of its own is no source of this one, and is read here for its line.
            text = texts.get(path) or (folder / path).read_text(encoding="utf-8",
                                                                 errors="replace")  # fmt: skip
            findings.append(
                Finding(
                    gate=GATE,
                    code=refusal.code,
                    message=f"manuscript/{path}: {refusal.message}",
                    path=folder / path,
                    line=text.count("\n", 0, refusal.offset) + 1,
                    hint=_HINTS.get(refusal.code),
                )
            )
        entry = SUPPLEMENT_ENTRY if supplementary else "main.tex"
        for path in document.loose:
            findings.append(
                Finding(
                    gate=GATE,
                    code="tex-not-input",
                    severity=WARN,
                    message=f"manuscript/{path} is named by no \\input the reader follows: it "
                    "is read as body under no heading",
                    path=folder / path,
                    hint=f"\\input it where it belongs from {entry}, outside a definition and "
                    "before any refusal, or move it into a folder whose name starts with '_'",
                )
            )
    return Report(tuple(findings))
