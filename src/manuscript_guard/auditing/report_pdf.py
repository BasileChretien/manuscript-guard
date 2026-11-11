"""The audit's report as a PDF: what the page draws, on pages a reader can keep and pass on
(the author's audit, 2026-11-10: "The best would be an interactive pdf"; 2026-11-11: "Make
the pdf interactive and visually appealing ... professional, modern", with a line at the
bottom saying it was made with manuscript-guard, and one saying how few of its checks an
audit runs, with a link to using it fully).

It is drawn from the report's view (`auditing.report.view`, with every place and every
section, as `--details` gives them), so that the PDF, the page and the text say the same:

* a cover band with the title, and the report's first lines;
* "What was checked": a tile for each check in the colour of where it stands
  (`summary.standings`: nothing found, to look at, counted as an error, not run), what it
  found, and a link to its section;
* what was not read, and how the headings were read;
* the findings on the words by kind, each kind with its count, its hint once in a box, and
  every place, its message, its quote under a rule and its own hint;
* each other section as its text, under a heading that links back to the summary;
* what an audit leaves to a paper written with manuscript-guard, with a link to how.

Every heading is a bookmark, a kind's under its paper's; every page has the report's title
at its top, from the second, and at its foot "Made with manuscript-guard", a link to the
project, and the page's number of all. `pdfwriter` sets it, in the standard fonts.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

from manuscript_guard.auditing.summary import CLEAR, COUNTED, LOOK, NOT_RUN
from manuscript_guard.pdfwriter import HEIGHT, MARGIN, WIDTH, Margins, Pdf, rgb

#: How far a line of a section's text is set in for each space it opens with.
INDENT = 4.5
#: A check's name in the table, linked to the section whose heading opens with its first
#: word: "Numbers in the outputs" to "Numbers in the outputs", "Writing and language" to
#: the findings on the words.
_FIRST_WORD = re.compile(r"\w+")
#: Where a reader learns to use the tool fully: its front page, which links the rest.
HOME = "https://basilechretien.github.io/manuscript-guard/"
SHOWN_HOME = "basilechretien.github.io/manuscript-guard"

INK = rgb("#1b2433")
MUTED = rgb("#556070")
FAINT = rgb("#8a93a3")
LINE = rgb("#d9dee7")
PANEL = rgb("#f3f5f9")
ACCENT = rgb("#1f5f8b")
DEEP = rgb("#15324f")
SOFT = rgb("#c9dcec")
CALL = rgb("#eaf2f9")
WHITE = (1.0, 1.0, 1.0)
#: Each standing's colour and the words its tile says it in.
STANDING = {
    CLEAR: (rgb("#2e7d4f"), "NOTHING FOUND"),
    LOOK: (rgb("#a8650a"), "TO LOOK AT"),
    COUNTED: (rgb("#b3261e"), "COUNTED AS AN ERROR"),
    NOT_RUN: (rgb("#7a8294"), "NOT RUN"),
}
COLUMN = WIDTH - 2 * MARGIN
#: The months in English, whatever the machine's language: the report is in English.
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")  # fmt: skip


def _key(heading: str) -> str:
    found = _FIRST_WORD.search(heading)
    return f"section:{found.group(0).lower() if found else heading}"


def written(view: dict, title: str, version: str, *, gates: int = 17,
            on: datetime.date | None = None) -> bytes:  # fmt: skip
    """The PDF of the report whose view is `view`, titled `title`; `gates` is how many the
    tool has, which the closing says an audit runs few of; `on` is the day it is dated."""
    pdf = Pdf(title=title, producer=f"manuscript-guard {version}", author="manuscript-guard",
              subject="What manuscript-guard's audit found in a paper",
              frame=Margins(running=title, foot=f"Made with manuscript-guard {version}  ·  "
                            f"{SHOWN_HOME}", uri=HOME, color=FAINT, rule=LINE))  # fmt: skip
    _cover(pdf, view, title, version, on or datetime.date.today())
    _glance(pdf, view)
    for heading, said in view["notes"]:
        _note(pdf, heading, said)
    _words(pdf, view)
    for heading, text in view["sections"]:
        _section(pdf, heading, text)
    _closing(pdf, view, gates)
    return pdf.bytes()


# ---------------------------------------------------------------------------- the parts


def _cover(pdf: Pdf, view: dict, title: str, version: str, on: datetime.date) -> None:
    """The band at the top of the first page: what it is, the title, the day and the
    version; then the report's first lines."""
    pdf.ensure(0)
    lines = pdf.wrap(title, "bold", 21, COLUMN)
    band = 74 + 26 * len(lines)
    # Past the page's edges, so that no reader leaves a hairline of paper beside it.
    pdf.rect(-2, HEIGHT + 2, WIDTH + 4, band + 2, DEEP)
    pdf.rect(-2, HEIGHT - band, WIDTH + 4, 3.5, ACCENT)
    pdf.put("MANUSCRIPT-GUARD   ·   AUDIT REPORT", x=MARGIN, top=HEIGHT - 30, kind="bold",
            size=8, color=SOFT)  # fmt: skip
    pdf.y = HEIGHT - 44
    pdf.bookmark(title, 1, key="top")
    for at, line in enumerate(lines):
        pdf.put(line, x=MARGIN, top=HEIGHT - 44 - 26 * at, kind="bold", size=21, color=WHITE)
    dated = f"{on.day} {MONTHS[on.month - 1]} {on.year}  ·  manuscript-guard {version}"
    pdf.put(dated, x=MARGIN, top=HEIGHT - band + 26, size=9, color=SOFT)
    pdf.y = HEIGHT - band - 22
    for line in view["header"]:
        _flow(pdf, line, size=10.5, color=INK)
    pdf.gap(10)


def _heading(pdf: Pdf, text: str, *, key: str | None = None, level: int = 1,
             back: bool = True) -> None:  # fmt: skip
    """A section's heading: an accent bar beside it, its bookmark, the place `key`, and a
    link back to the summary at its right."""
    size = 15.0 if level == 1 else 12.5
    lines = pdf.wrap(text, "bold", size, COLUMN - 14 - (110 if back else 0))
    pdf.gap(size * 0.9)
    top = pdf.ensure(size * 1.3 * len(lines) + 70)
    pdf.bookmark(text, level, key)
    pdf.rect(MARGIN, top + 1, 3.5, size * 1.25 * len(lines), ACCENT, 1.5)
    for at, line in enumerate(lines):
        pdf.put(line, x=MARGIN + 12, top=top - size * 1.25 * at, kind="bold", size=size,
                color=INK)  # fmt: skip
    if back:
        said = "Back to the summary"
        pdf.put(said, x=WIDTH - MARGIN - pdf.measure(said, "regular", 8), top=top - 4, size=8,
                color=ACCENT, link="checks")  # fmt: skip
    pdf.y = top - size * 1.25 * len(lines) - 8


def _flow(pdf: Pdf, text: str, *, size: float = 9.5, kind: str = "regular",
          color=INK, indent: float = 0.0, link: str | None = None) -> None:  # fmt: skip
    """Text flowing down the column from `indent`, a page broken where it must."""
    step = size * 1.35
    for line in pdf.wrap(text, kind, size, COLUMN - indent):
        top = pdf.ensure(step)
        pdf.put(line, x=MARGIN + indent, top=top, kind=kind, size=size, color=color, link=link)
        pdf.y = top - step


def _glance(pdf: Pdf, view: dict) -> None:
    """A tile for each check, two to a row, in the colour of where it stands, each a link to
    its section."""
    _heading(pdf, "What was checked", key="checks", level=2, back=False)
    standing = view.get("standing") or {}
    gap = 12.0
    wide = (COLUMN - gap) / 2
    checks = view["checks"]
    for at in range(0, len(checks), 2):
        pair = checks[at:at + 2]
        drawn = [(name, said, pdf.wrap(name, "bold", 10.5, wide - 26),
                  pdf.wrap(said, "regular", 8.8, wide - 26)) for name, said in pair]
        high = max(30 + 13 * len(names) + 11.5 * len(saids) for _n, _s, names, saids in drawn)
        top = pdf.ensure(high + gap)
        for column, (name, _said, names, saids) in enumerate(drawn):
            x = MARGIN + column * (wide + gap)
            color, words = STANDING[standing.get(name, LOOK)]
            pdf.rect(x, top, wide, high, PANEL, 6)
            pdf.rect(x + 7, top - 8, 3.5, high - 16, color, 1.75)
            pdf.put(words, x=x + 18, top=top - 9, kind="bold", size=7, color=color)
            for line_at, line in enumerate(names):
                pdf.put(line, x=x + 18, top=top - 21 - 13 * line_at, kind="bold", size=10.5,
                        color=INK)  # fmt: skip
            below = top - 23 - 13 * len(names)
            for line_at, line in enumerate(saids):
                pdf.put(line, x=x + 18, top=below - 11.5 * line_at, size=8.8, color=MUTED)
            pdf.link_area(x, top, wide, high, _key(name))
        pdf.y = top - high - gap
    pdf.gap(4)


def _note(pdf: Pdf, heading: str, said: list[str]) -> None:
    """What was not read, or how the headings were read: a heading of the summary's level
    and each item in a panel."""
    pdf.gap(4)
    top = pdf.ensure(40)
    pdf.bookmark(heading.rstrip(":"), 2)
    pdf.put(heading.rstrip(":"), x=MARGIN, top=top, kind="bold", size=10.5, color=INK)
    pdf.y = top - 16
    for item in said:
        _boxed(pdf, item, color=MUTED, size=8.8)


def _boxed(pdf: Pdf, text: str, *, label: str = "", color=MUTED, size: float = 8.8,
           fill=PANEL, indent: float = 0.0) -> None:  # fmt: skip
    """`text` in a rounded panel, under `label` where there is one; flowing on, panel by
    panel, where it does not fit on one page."""
    lines = pdf.wrap(text, "regular", size, COLUMN - indent - 24)
    step = size * 1.35
    head = 12.0 if label else 0.0
    while lines:
        room = max(1, int((pdf.ensure(step + head + 16) - MARGIN - head - 14) // step))
        part, lines = lines[:room], lines[room:]
        high = head + step * len(part) + 14
        top = pdf.ensure(high)
        pdf.rect(MARGIN + indent, top, COLUMN - indent, high, fill, 5)
        if label:
            pdf.put(label, x=MARGIN + indent + 12, top=top - 8, kind="bold", size=7.5,
                    color=ACCENT)  # fmt: skip
        for at, line in enumerate(part):
            pdf.put(line, x=MARGIN + indent + 12, top=top - 8 - head - step * at, size=size,
                    color=color)  # fmt: skip
        pdf.y = top - high - 6
        label, head = "", 0.0


def _words(pdf: Pdf, view: dict) -> None:
    """The findings on the words, kind by kind; the paper's name over them wherever several
    papers were audited, though only one has findings (round 1 of #631), since no place
    under it names the paper again."""
    several = len(view["words"]) > 1
    for paper in (paper for paper in view["words"] if paper["note"] or paper["kinds"]):
        heading = f"Writing and language: {paper['paper']}" if several else "Writing and language"
        _heading(pdf, heading, key=_key("Writing"))
        if paper["note"]:
            _flow(pdf, paper["note"])
            continue
        _flow(pdf, "For a reader to look at, kind by kind: none of these is counted as an error.",
              size=9, color=MUTED)  # fmt: skip
        for kind in paper["kinds"]:
            _kind(pdf, kind)


def _kind(pdf: Pdf, kind: dict) -> None:
    """One kind of finding on the words: its title and count, its hint once where its places
    share one, and each place, its message, its quote and its own hint. The check's code
    (G14) is left to the text: it names nothing a reader of the PDF can look up there."""
    title = kind["title"]
    lines = pdf.wrap(title, "bold", 11.5, COLUMN - 50)
    pdf.gap(10)
    top = pdf.ensure(14 * len(lines) + 60)
    pdf.bookmark(f"{title} ({kind['count']})", 2)
    for at, line in enumerate(lines):
        pdf.put(line, x=MARGIN, top=top - 14 * at, kind="bold", size=11.5, color=INK)
    count = str(kind["count"])
    wide = pdf.measure(lines[-1], "bold", 11.5)
    pill = pdf.measure(count, "bold", 8) + 12
    last = top - 14 * (len(lines) - 1)
    pdf.rect(MARGIN + wide + 8, last + 1, pill, 13, SOFT, 6.5)
    pdf.put(count, x=MARGIN + wide + 14, top=last - 2, kind="bold", size=8, color=DEEP)
    pdf.y = top - 14 * len(lines) - 6
    if kind.get("hint"):
        _boxed(pdf, kind["hint"], label="WHAT TO DO", color=INK, size=8.8)
    for place in kind["places"]:
        _place(pdf, place)


def _place(pdf: Pdf, place: dict) -> None:
    """One place of a finding: where it is, what it says, its quote under a rule, and its
    own hint."""
    pdf.gap(4)
    top = pdf.ensure(40)
    pdf.put(place["where"], x=MARGIN + 6, top=top, kind="bold", size=8.3, color=ACCENT)
    pdf.y = top - 12
    _flow(pdf, place["message"], size=9.3, indent=6)
    if place.get("context"):
        step = 8.3 * 1.35
        for line in pdf.wrap(place["context"], "oblique", 8.3, COLUMN - 26):
            line_top = pdf.ensure(step)
            pdf.rule(MARGIN + 12, line_top + 1, MARGIN + 12, line_top - step + 1, LINE, 1.6)
            pdf.put(line, x=MARGIN + 20, top=line_top, kind="oblique", size=8.3, color=FAINT)
            pdf.y = line_top - step
    if place.get("hint"):
        _flow(pdf, f"What to do: {place['hint']}", size=8.3, color=MUTED, indent=20)


def _section(pdf: Pdf, heading: str, text: str) -> None:
    """Another section, as its text: its lines set in by their spaces, those in capitals,
    the text's own subheadings, in bold."""
    _heading(pdf, heading, key=_key(heading))
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        if not stripped:
            pdf.gap(4)
            continue
        loud = stripped[:12].isupper() and stripped.endswith(":")
        _flow(pdf, stripped, size=9, kind="bold" if loud else "regular",
              color=INK if loud else MUTED if stripped.startswith(("Hint", "What")) else INK,
              indent=INDENT * (len(line) - len(stripped)))  # fmt: skip


def _closing(pdf: Pdf, view: dict, gates: int) -> None:
    """The report's last line, then what an audit leaves to a paper written with the tool,
    with the link to how (the author, 2026-11-11: "only a few gates were checked, see this
    link to see how use fully this programme")."""
    if view.get("closing"):
        pdf.gap(10)
        _flow(pdf, view["closing"], size=9.5, color=MUTED)
    pdf.gap(14)
    body = pdf.wrap(
        "An audit reads a paper that is already written: its numbers, against each other and "
        "against the outputs given, and its words and its reference list, through three of "
        f"manuscript-guard's {gates} gates (G6, G7 and G14), in part. Written with "
        f"manuscript-guard, a paper is held to all {gates} as it is written: every number "
        "traced to the analysis that produced it, every quote found in its source, the "
        "figures reviewed, the analysis plan and the journal's rules kept, and the reporting "
        "checklist addressed.",
        "regular", 9.3, COLUMN - 36)  # fmt: skip
    step = 9.3 * 1.4
    high = 34 + step * len(body) + 30
    top = pdf.ensure(high)
    pdf.rect(MARGIN, top, COLUMN, high, CALL, 8)
    pdf.rect(MARGIN, top, 4, high, ACCENT, 2)
    pdf.bookmark("What an audit does not check", 1)
    pdf.put("This audit ran only a few of manuscript-guard's checks", x=MARGIN + 18,
            top=top - 14, kind="bold", size=11.5, color=DEEP)  # fmt: skip
    for at, line in enumerate(body):
        pdf.put(line, x=MARGIN + 18, top=top - 34 - step * at, size=9.3, color=INK)
    said = "See how to use it fully:"
    below = top - 34 - step * len(body) - 6
    wide = pdf.put(said, x=MARGIN + 18, top=below, kind="bold", size=9.3, color=DEEP)
    pdf.put(SHOWN_HOME, x=MARGIN + 18 + wide + 5, top=below, kind="bold", size=9.3,
            color=ACCENT, uri=HOME)  # fmt: skip
    pdf.y = top - high - 10


def report_pdf(report, discrimination, root: Path | None, paper_names: list[str]) -> bytes:
    """The PDF of the audit `report`: its view with every place and every section."""
    from manuscript_guard import __version__
    from manuscript_guard.auditing.report import view
    from manuscript_guard.gates import GATES

    drawn = view(report, discrimination, root, details=True)
    names = ", ".join(paper_names) or "the paper"
    return written(drawn, f"Audit of {names}", __version__, gates=len(GATES))
