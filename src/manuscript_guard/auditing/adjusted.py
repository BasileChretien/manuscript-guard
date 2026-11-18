"""The audit's questions on numbers that may fit after all: a P larger than its statistic
gives, in a paper that says its P values are adjusted for multiple comparisons, and a share
off its column's n, in a table that says its shares are weighted (Basile, 2026-11-16,
decision 31: "Both"). What says so is read in `stats/adjusted.py`.

* **A paper's adjustment** is the first statement of it in the paper, outside its reference
  list: in any file of a LaTeX paper, and in a .docx's notes. A test in any file of the paper
  is read under it. A figure given with `--figures` is no part of a paper, and reads none.
* **A table's weighting** is said in its caption, its cells (its header and its rows'
  labels) or its note: in Markdown, the paragraph after it; in a .docx, the paragraph after
  it; in LaTeX, all of the float it stands in. Only that table's shares are let off. A PDF's
  tables are read as lines of text, so none is.

Each question is of the kind `report.question` makes: INFO, never counted, under "Questions
for the author", standing at its number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from manuscript_guard.stats.adjusted import REFEREE_P, Said, adjustment, weighting
from manuscript_guard.stats.shares import Share, _places
from manuscript_guard.text.tables import Table

#: The questions' codes.
ASKED_ADJUSTED = "question-p-adjusted"
ASKED_WEIGHTED = "question-share-weighted"
#: A table's name as its legend opens with it: "Table 2", "Table S1a", "eTable 3".
_NAME = re.compile(r"(?i:(?:Supplementary\s+|e|S)?Table)\s+[A-Za-z]?\d+[A-Za-z]?")


@dataclass(frozen=True)
class Asked:
    """A question asked of a number, as the report lists it: where it stands, what it asks,
    the number's context and what a referee's draft says of it (`report.question`)."""

    source: Path
    line: int
    message: str
    context: str
    code: str
    refereed: str = ""


@dataclass(frozen=True)
class Statement:
    """Where a paper says its P values are adjusted: the file, the line, and the quote."""

    path: Path
    line: int
    quote: str

    def said(self, path: Path, placers: dict) -> str:
        """'("...", line 12)', the line as the report says one of the file ("Methods,
        paragraph 3" in a .docx, "page 2, line 14" in a PDF), with the file's name where it
        is not `path`."""
        placer = placers.get(self.path)
        place = placer.said(self.line) if placer is not None else f"line {self.line}"
        if self.path != path:
            place = f"{self.path.name}, {place}"
        return f'("{self.quote}", {place})'


def statement(path: Path, hidden: str, lined: str, *, lines: bool,
              cuts: tuple[int, ...] = ()) -> Statement | None:  # fmt: skip
    """The first statement of an adjustment in one file's text as the audit reads it, its
    reference list blanked and masked (`hidden`), at its line in `lined`; `lines` where a
    line of it is a paragraph, `cuts` where its headings start and end."""
    found = adjustment(hidden, lines=lines, cuts=cuts)
    if found is None:
        return None
    return Statement(path, lined.count("\n", 0, found.start) + 1, found.quote)


def asked_p(test, verdict, statement_of: Statement, path: Path, placers: dict,
            described: str, context: str, line: int) -> Asked:  # fmt: skip
    """The question on a P larger than its statistic gives, in a paper that says it adjusts
    its P values."""
    from manuscript_guard.stats.adjusted import asked_p as message

    said = statement_of.said(path, placers)
    return Asked(path, line, message(test, verdict, said), context, ASKED_ADJUSTED,
                 REFEREE_P.format(described=described, said=said))  # fmt: skip


# ---------------------------------------------------------------------------------- tables


@dataclass(frozen=True)
class Weighted:
    """What says shares are weighted: what says it, "Table 2" or "Table 2's column", and
    the words quoted."""

    name: str
    quote: str


@dataclass(frozen=True)
class Weighting:
    """What says a table's shares are weighted: for the whole table, its caption, a row's
    label or its note; for single columns, the header cells over them, by column."""

    whole: Weighted | None = None
    columns: tuple[tuple[int, Weighted], ...] = ()

    def of(self, column: int | None) -> Weighted | None:
        """What says the shares of `column` are weighted, or None."""
        return self.whole or dict(self.columns).get(column)


#: A legend, as `text.captioned` reads one, "table" in any case: "TABLE 2.", "**Table 1:**".
LEGEND = re.compile(
    r"[ \t]*[*_]*(?i:(?:Supplementary[ \t]+|e|S)?Table)[ \t]+[A-Za-z]?\d+[A-Za-z]?[*_]*"
    "(?:[ \t]*[.:|\N{EN DASH}\N{EM DASH}-]|[ \t]+(?=[A-Z]))"
)
#: What a table's note opens with: "Note", "Notes", "Abbreviations", or a footnote's mark,
#: a lowercase letter alone, an asterisk, a dagger, a section sign, a raised mark.
NOTE_MARK = re.compile(
    r"[ \t]*(?:[*_]{0,2}(?i:notes?|abbreviations?)\b|[a-z](?=[\s.):,])"
    r"|[*\N{DAGGER}\N{DOUBLE DAGGER}\N{SECTION SIGN}]|\^[^^\s]{1,8}\^|<sup>"
    rf"|[\N{{SUPERSCRIPT ONE}}\N{{SUPERSCRIPT TWO}}\N{{SUPERSCRIPT THREE}}"
    rf"{chr(0x2070)}-{chr(0x209F)}{chr(0x1D43)}-{chr(0x1DBF)}])"
)


def weighted_tables(tables: list[Table], *, text: str, kind: str, latex=None
                    ) -> list[Weighting | None]:  # fmt: skip
    """For each of `tables`, what says its shares are weighted, None where nothing does.
    `text` is the file's text a line to each line its tables' cells name, `kind` "docx",
    "markdown" or "latex", `latex` a LaTeX file's `Source`. A caption is a legend or
    pandoc's; a note is the paragraph after the table where it opens with a note's mark
    (`NOTE_MARK`) and is no table's caption; in LaTeX, the float's text outside the table."""
    if kind == "latex":
        around = _latex_floats(latex)
        return [_weighting(table, *around.get(table[0][0].line, ("", ""))) if _cells(table)
                else None for table in tables]  # fmt: skip
    lines = text.split("\n")
    captions = [_caption_of(lines, table, kind) if _cells(table) else ""
                for table in tables]  # fmt: skip
    taken = {_plain(caption) for caption in captions if caption}
    return [_weighting(table, caption, _note(lines, table, taken, kind)) if _cells(table) else None
            for table, caption in zip(tables, captions, strict=True)]  # fmt: skip


def _cells(table: Table) -> list[int]:
    return [cell.line for row in table for cell in row]


def _plain(text: str) -> str:
    return " ".join(text.split())


def _a_caption(paragraph: str) -> bool:
    """Whether a paragraph is shaped as a caption: a legend, "table" in any case, or
    pandoc's "Table: ..."."""
    from manuscript_guard.text.captioned import _PANDOC

    return bool(LEGEND.match(paragraph) or _PANDOC.match(paragraph))


def _caption_of(lines: list[str], table: Table, kind: str) -> str:
    """A table's caption: the paragraph before it where it is a legend, "table" in any case,
    or pandoc's; in Markdown, else pandoc's after it. A legend after a table may be the next
    table's, as `text.captioned` would take it, so it is no caption here: one whose
    weighting is the next table's let off the table before it (round 1 of #703)."""
    from manuscript_guard.text.captioned import _PANDOC, _beside

    cells = _cells(table)
    if kind == "docx":
        before = _beside(lines, min(cells) - 1, -1, set(range(min(cells), max(cells) + 1)))
        return before if _a_caption(before) else ""
    before = _paragraph(lines, min(cells) - 1, -1)
    if _a_caption(before):
        return before
    after = _paragraph(lines, max(cells) + 1, 1)
    return after if _PANDOC.match(after) else ""


def _paragraph(lines: list[str], start: int, step: int) -> str:
    """The paragraph next to a table from line `start` (from 1) in the direction of `step`,
    past one blank line, as one line; "" at a table's row or the end of the text."""
    at = start
    if 1 <= at <= len(lines) and not lines[at - 1].strip(" \t|"):
        at += step
    taken = []
    while 1 <= at <= len(lines) and lines[at - 1].strip(" \t|"):
        if lines[at - 1].lstrip().startswith(("|", "+")):
            break
        taken.append(lines[at - 1])
        at += step
    return _plain(" ".join(taken if step > 0 else taken[::-1]))


def _note(lines: list[str], table: Table, captions: set[str], kind: str) -> str:
    """The paragraph after a table where it is its note: it opens with a note's mark, and is
    no caption, this table's, the next one's or any other's."""
    cells = _cells(table)
    if kind == "docx":
        from manuscript_guard.text.captioned import _beside

        # Past the lines of nothing but a cell's edge, as the table's rows are read.
        note = _beside(lines, max(cells) + 1, 1, set(range(min(cells), max(cells) + 1)))
    else:
        note = _paragraph(lines, max(cells) + 1, 1)
    if not note or _a_caption(note) or note in captions or not NOTE_MARK.match(note):
        return ""
    return note


def _weighting(table: Table, caption: str, note: str) -> Weighting | None:
    """What says `table`'s shares are weighted: its caption, a row's label (the cells of its
    first column) or its note for the whole table, else each header cell for its columns."""
    from manuscript_guard.stats.shares import _SHARE, _clean, _columns

    named = _NAME.search(caption)
    name = named.group(0) if named else "This table"
    for words in (caption, note, *(row[0].text for row in table if row)):
        said: Said | None = weighting(_plain(words))
        if said is not None:
            return Weighting(whole=Weighted(name, said.quote))
    columns: list[tuple[int, Weighted]] = []
    for row in table:
        placed = list(_columns(row))[1:]
        if any(_SHARE.fullmatch(_clean(cell.text)[0]) for _column, cell in placed):
            break
        for column, cell in placed:
            said = weighting(_plain(cell.text))
            if said is not None:
                columns += [(each, Weighted(f"{name}'s column", said.quote))
                            for each in range(column, column + max(cell.span, 1))]  # fmt: skip
    return Weighting(columns=tuple(columns)) if columns else None


def _latex_floats(source) -> dict[int, tuple[str, str]]:
    """Each LaTeX table by its header row's line: the caption of the float it stands in, and
    that float's text outside the table, which holds its notes."""
    from manuscript_guard.text.captioned import _floats, latex_captioned
    from manuscript_guard.text.latex.tables import spanned_tables

    if source is None:
        return {}
    floats = _floats(source.text)
    captions = {found.line: found.caption for found in latex_captioned(source)}
    found: dict[int, tuple[str, str]] = {}
    for (start, end), table in spanned_tables(source):
        low, high = next(((low, high) for low, high in floats if low <= start and end <= high),
                         (start, end))  # fmt: skip
        line = table[0][0].line
        found[line] = (captions.get(line, ""), source.text[low:start] + " " + source.text[end:high])
    return found


def asked_share(share: Share, weighted: Weighted, path: Path, described: str) -> Asked:
    """The question on a share off its column's n, in a table that says its shares are
    weighted."""
    assert share.over is not None
    shown = f"{share.count} of {share.over}"
    if share.over:
        exact = Fraction(100 * share.count, share.over)
        shown += f" ({float(exact):.{_places(share.percent)}f}%)"
    message = (f"{weighted.name} says its shares are weighted (\"{weighted.quote}\"). "
               f"{share.printed} is not {shown}. Is {share.percent}% the weighted share? If "
               "so nothing is wrong; if not, check the count, the share and the column's n.")
    named = weighted.name[0].lower() + weighted.name[1:] if weighted.name.startswith(
        "This table") else weighted.name
    refereed = (f"{described}; {named} says its shares are weighted (\"{weighted.quote}\"): "
                "the author is asked whether it is the weighted share.")
    return Asked(path, share.line, message, share.context, ASKED_WEIGHTED, refereed)


__all__ = ["ASKED_ADJUSTED", "ASKED_WEIGHTED", "LEGEND", "NOTE_MARK", "Asked", "Statement",
           "Weighted", "Weighting", "asked_p", "asked_share", "statement",
           "weighted_tables"]  # fmt: skip
