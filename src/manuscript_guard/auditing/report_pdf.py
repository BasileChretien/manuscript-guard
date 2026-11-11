"""The audit's report as a PDF: what the page draws, on pages a reader can keep and pass on
(the author's audit, 2026-11-10: "The best would be an interactive pdf").

It is drawn from the report's view (`auditing.report.view`, with every place and every
section, as `--details` gives them), so that the PDF, the page and the text say the same:
its first lines and what was not read; a table of what each check found, each check's name
a link to its section; the findings on the words by kind, each kind with its hint once and
every place of it, its message and its quote; then each other section as its text. Every
heading is a bookmark, a kind's under its paper's. `pdfwriter` sets it.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.pdfwriter import Pdf

#: How far a line of a section's text is set in for each space it opens with.
INDENT = 4.5
#: A check's name in the table, linked to the section whose heading opens with its first
#: word: "Numbers in the outputs" to "Numbers in the outputs", "Writing and language" to
#: the findings on the words.
_FIRST_WORD = re.compile(r"\w+")


def _key(heading: str) -> str:
    found = _FIRST_WORD.search(heading)
    return f"section:{found.group(0).lower() if found else heading}"


def written(view: dict, title: str, version: str) -> bytes:
    """The PDF of the report whose view is `view`, titled `title`."""
    pdf = Pdf(title=title, producer=f"manuscript-guard {version}")
    pdf.heading(title, 1, key="top")
    for line in view["header"]:
        pdf.text(line, size=10.5)
    pdf.gap(6)
    for heading, said in view["notes"]:
        pdf.heading(heading, 2)
        for item in said:
            pdf.text(item, indent=10, size=9.5)
    pdf.heading("What was checked", 2, key="checks")
    for name, said in view["checks"]:
        pdf.row(name, said, link=_key(name))
    if view.get("strict"):
        pdf.gap(4)
        pdf.text(view["strict"], size=8.5, gray=0.35)
    for paper in view["words"]:
        if not paper["note"] and not paper["kinds"]:
            continue
        pdf.heading(f"Writing and language: {paper['paper']} (not counted by --strict)", 1,
                    key=_key("Writing"))  # fmt: skip
        if paper["note"]:
            pdf.text(paper["note"])
            continue
        for kind in paper["kinds"]:
            _kind(pdf, kind)
    for heading, text in view["sections"]:
        pdf.heading(heading, 1, key=_key(heading))
        for line in text.split("\n"):
            stripped = line.lstrip(" ")
            if not stripped:
                pdf.gap(4)
                continue
            pdf.text(stripped, indent=INDENT * (len(line) - len(stripped)), size=9.5)
    if view.get("closing"):
        pdf.gap(10)
        pdf.text(view["closing"], size=10)
    return pdf.bytes()


def _kind(pdf: Pdf, kind: dict) -> None:
    """One kind of finding on the words: its title, gate and count, its hint once where its
    places share one, and each place, its message, its quote and its own hint."""
    pdf.heading(f"{kind['title']} ({kind['gate']}, {kind['count']})", 2)
    if kind.get("hint"):
        pdf.text(f"Hint: {kind['hint']}", kind="oblique", size=9, gray=0.3)
    for place in kind["places"]:
        pdf.gap(3)
        pdf.text(f"{place['where']}: {place['message']}", size=9.5, indent=6)
        if place.get("context"):
            pdf.text(place["context"], kind="code", size=8, indent=18, gray=0.35)
        if place.get("hint"):
            pdf.text(f"Hint: {place['hint']}", kind="oblique", size=8.5, indent=18, gray=0.3)


def report_pdf(report, discrimination, root: Path | None, paper_names: list[str]) -> bytes:
    """The PDF of the audit `report`: its view with every place and every section."""
    from manuscript_guard import __version__
    from manuscript_guard.auditing.report import view

    drawn = view(report, discrimination, root, details=True)
    names = ", ".join(paper_names) or "the paper"
    return written(drawn, f"Audit of {names}", __version__)
