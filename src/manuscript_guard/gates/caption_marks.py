"""G3: a caption that points at a line and never says which line it is.

"Journals below the line have fewer editors than seats." A reader who looks only at the figure
and its caption, as many readers do, has to guess which of the lines drawn is meant and what
it stands for: equal shares, no association, the line of identity, a fitted trend. The figure
review asks whether every mark is explained (`legend-and-marks-explained`), but it is recorded
once and the caption is edited after.

So each caption is read for a line or a curve pointed at by where something stands against
it, "below the line", "right of the curves", with no word between "the" and the mark and
nothing after it that says which it is ("of no association", "at 1", "(y = x)", "that marks
..."). Where nothing else in the caption names a line or a curve either, "the dashed line
marks ...", "Kaplan-Meier curves", a warning at the place (`caption-line-unnamed`), at every
stage. A caption that names a line once may point at "the line" after, and is left alone,
even where it draws two.

The captions read: in a Markdown file of the main text or the supplement, a legend that opens
with its display ("Figure 1. ...", "**Table 2.** ..."), a table's caption (`Table: ...`) and an
image's (`![...](...)`), as G14 finds the first two (`glossary.markdown_captions`); in a LaTeX
file, each `\\caption{...}`; and the caption the analysis emits for a table. The words are read
as a reader reads them (`claims.readable`): not in a binding, a citation, a comment or code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard import claims
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import WARN, Finding, Report

GATE = "G3"
CODE = "caption-line-unnamed"

#: A mark a caption may point at: a line or a curve, one or several.
_MARK = r"(?:lines?|curves?)"
#: Where something stands against a mark: "below", "to the left of".
_PLACE = (
    r"(?:above|below|under|over|beneath|beyond|along|across|on|onto|crossing|crosses|touching"
    r"|near|(?:to\s+the\s+)?(?:left|right)\s+of)"
)
#: What, after the mark, says which it is: "of no association", "at 1", "(y = x)", "=", "for
#: the trend", "that marks", "drawn at".
_SAYS_WHICH = (
    r"(?:\(|=|(?:of|at|for|through|that|which|where|drawn|marking|showing|indicating|denoting"
    r"|representing)\b)"
)
#: A mark pointed at by its place, with nothing between "the" and the mark and nothing after it
#: that says which it is. The mark is the group `mark`.
_POINTED = re.compile(
    rf"(?<!\w){_PLACE}\s+(?:the|these|those|this|that)\s+(?P<mark>{_MARK})(?!\w)"
    rf"(?!\s*{_SAYS_WHICH})",
    re.IGNORECASE,
)
#: Any mention of a mark.
_MENTION = re.compile(rf"(?<!\w){_MARK}(?!\w)", re.IGNORECASE)
#: A display's pointer or number the build prints, `{{ref.figure.forest}}` or
#: `{{num.table.baseline}}`: read as what it prints, "Figure 1" or "1", at the same length, so
#: that a legend that opens with one, as the results-binding skill writes a figure's, is one.
_REFERENCE = re.compile(r"\{\{\s*(?P<ns>ref|num)\.(?P<kind>figure|table)\.[\w.-]+\s*\}\}")
#: An image with its caption, bounded as G14 bounds it: `![caption](target)`.
_IMAGE = re.compile(
    r"!\[(?P<caption>(?:[^\[\]]|\[[^\[\]]{0,300}\]){0,1000})\]"
    r"(?:\([^)\n]{0,1000}\)|\[[^\]\n]{0,300}\])"
)


@dataclass(frozen=True)
class Caption:
    """A caption's words as a reader reads them, where they stand, and how a finding names
    it: the file, the line it starts on and its offset in the file (None for an emitted
    table's), and the words as typed."""

    path: Path
    line: int | None
    start: int
    read: str
    typed: str
    named: str


def unnamed(read: str) -> re.Match[str] | None:
    """The first mark `read` points at by its place and never names (`_POINTED`), where no
    mention of a mark in it names one: None where every mention is such a pointing, or there
    is none."""
    pointed = list(_POINTED.finditer(read))
    if not pointed:
        return None
    marks = {found.start("mark") for found in pointed}
    if any(found.start() not in marks for found in _MENTION.finditer(read)):
        return None
    return pointed[0]


def markdown_captions(text: str, path: Path, named: str) -> list[Caption]:
    """Each caption of a Markdown file: its legends and its tables' captions, as G14 finds
    them, and its images'."""
    from manuscript_guard.gates.glossary import markdown_captions as captions_of
    from manuscript_guard.text.blocks import scannable

    read = claims.readable(text).replace("\x00", " ")
    shown = _REFERENCE.sub(_as_printed, scannable(text))
    spans = list(captions_of(shown))
    spans += [found.span("caption") for found in _IMAGE.finditer(shown)]
    return [Caption(path, text.count("\n", 0, start) + 1, start, read[start:end],
                    text[start:end], named) for start, end in sorted(spans)]  # fmt: skip


def _as_printed(found: re.Match[str]) -> str:
    """A pointer's binding as the build prints it, padded to its own length."""
    named = "" if found["ns"] == "num" else found["kind"].capitalize() + " "
    return f"{named}1".ljust(len(found[0]))


def latex_captions(source, path: Path) -> list[Caption]:
    """Each `\\caption{...}` of a LaTeX file, its text inside the braces."""
    from manuscript_guard.text.latex.printed import caption_spans

    text = source.text
    return [Caption(path, text.count("\n", 0, start) + 1, start, text[start:end],
                    text[start:end], "the caption") for start, end in caption_spans(source)]


def captions(project: Project, results: Results | None) -> list[Caption]:
    """Every caption of the manuscript, main text and supplement, in the order the files are
    listed, and then each caption the analysis emits for a table."""
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.text.reader import LATEX, manuscript_format

    root = project.path("manuscript")
    found: list[Caption] = []
    if manuscript_format(root) == LATEX:
        from manuscript_guard.text.latex.structure import read_document

        for supplementary in (False, True):
            for source in read_document(root, supplementary=supplementary).sources:
                if not source.loose and not source.path.lower().endswith(".sty"):
                    found += latex_captions(source, root / source.path)
    else:
        for path in source_files(root):
            found += markdown_captions(read_text(path), path, "the caption")
    for key, table in sorted((results.tables if results else {}).items()):
        if table.caption:
            found.append(Caption(table.source, None, 0, table.caption, table.caption,
                                 f"the caption of table {key!r}"))  # fmt: skip
    return found


def check_caption_marks(project: Project, results: Results | None) -> Report:
    """A warning for each caption that points at a line or a curve it never names."""
    report = Report()
    seen: set[tuple[Path, int]] = set()
    for caption in captions(project, results):
        found = unnamed(caption.read)
        if found is None or (caption.path, caption.start) in seen:
            continue
        seen.add((caption.path, caption.start))
        pointed = " ".join(caption.typed[found.start():found.end()].split())
        line = None if caption.line is None else (
            caption.line + caption.typed.count("\n", 0, found.start()))
        report = report.with_findings(Finding(
            gate=GATE, code=CODE, severity=WARN, path=caption.path, line=line,
            message=f"{caption.named} points at {pointed!r} and never says which "
            f"{found['mark'].lower().rstrip('s')} it is, or what it marks",
            context=" ".join(caption.typed.split())[:160],
            hint="name the mark by how it is drawn and what it stands for, as a reader of the "
            "figure alone needs it: \"below the dashed line of equal shares\", \"right of the "
            "vertical line at an odds ratio of 1\"",
            subject=found["mark"].lower(), at=caption.start + found.start(),
        ))  # fmt: skip
    return report
