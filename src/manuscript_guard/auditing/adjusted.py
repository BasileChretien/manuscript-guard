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
    """What says a table's shares are weighted: for the whole table, its caption or its
    note; for a single row, its label, by the lines of the row's cells; for single columns,
    the header cells over them, by column (rounds 1 and 2 of #703)."""

    whole: Weighted | None = None
    columns: tuple[tuple[int, Weighted], ...] = ()
    rows: tuple[tuple[frozenset[int], Weighted], ...] = ()

    def of(self, column: int | None, line: int | None = None) -> Weighted | None:
        """What says the share of `column` on `line` is weighted, or None."""
        by_row = next((said for lines, said in self.rows if line in lines), None)
        return self.whole or by_row or dict(self.columns).get(column)


#: A legend, as `text.captioned` reads one, "table" in any case: "TABLE 2.", "**Table 1:**".
LEGEND = re.compile(
    r"[ \t]*[*_]*(?i:(?:Supplementary[ \t]+|e|S)?Table)[ \t]+[A-Za-z]?\d+[A-Za-z]?[*_]*"
    "(?:[ \t]*[.:|\N{EN DASH}\N{EM DASH}-]|[ \t]+(?=[A-Z]))"
)
#: What a table's note opens with: "Note", "Notes", "Abbreviations", or a footnote's mark,
#: a lowercase letter alone, an asterisk, a dagger or a section sign before a space, a raised
#: mark. An asterisk glued to a word is emphasis, "*After weighting ...*" (round 2 of #703).
NOTE_MARK = re.compile(
    r"[ \t]*(?:[*_]{0,2}(?i:notes?|abbreviations?)\b|[a-z](?=[\s.):,])"
    r"|[*\N{DAGGER}\N{DOUBLE DAGGER}\N{SECTION SIGN}](?=\s)|\^[^^\s]{1,8}\^|<sup>"
    rf"|[\N{{SUPERSCRIPT ONE}}\N{{SUPERSCRIPT TWO}}\N{{SUPERSCRIPT THREE}}"
    rf"{chr(0x2070)}-{chr(0x209F)}{chr(0x1D43)}-{chr(0x1DBF)}])"
)


@dataclass(frozen=True)
class _Beside:
    """A paragraph next to a table, as one line, and the lines from 1 it runs over."""

    text: str
    lines: frozenset[int]


def weighted_tables(tables: list[Table], *, text: str, kind: str, latex=None
                    ) -> list[Weighting | None]:  # fmt: skip
    """For each of `tables`, what says its shares are weighted, None where nothing does.
    `text` is the file's text a line to each line its tables' cells name, `kind` "docx",
    "markdown" or "latex", `latex` a LaTeX file's `Source`. A caption is a legend or
    pandoc's, as the file's tables stand by theirs (`captions_of`); a note is the paragraph
    after the table where it opens with a note's mark (`NOTE_MARK`) and is no caption; in
    LaTeX, the float's text outside the table."""
    if kind == "latex":
        around = _latex_floats(latex)
        return [_weighting(table, *around.get(table[0][0].line, ("", ""))) if _cells(table)
                else None for table in tables]  # fmt: skip
    lines = text.split("\n")
    read = [table for table in tables if _cells(table)]
    befores = [_next_to(lines, table, kind, -1) for table in read]
    afters = [_next_to(lines, table, kind, 1) for table in read]
    captions = captions_of(befores, afters)
    taken = {caption for caption in captions if caption}
    said = {id(table): _weighting(table, caption, _note(after, taken))
            for table, caption, after in zip(read, captions, afters, strict=True)}
    return [said.get(id(table)) for table in tables]


def _cells(table: Table) -> list[int]:
    return [cell.line for row in table for cell in row]


def _plain(text: str) -> str:
    return " ".join(text.split())


def _a_caption(paragraph: str) -> bool:
    """Whether a paragraph is shaped as a caption: a legend, "table" in any case, or
    pandoc's "Table: ..."."""
    from manuscript_guard.text.captioned import _PANDOC

    return bool(LEGEND.match(paragraph) or _PANDOC.match(paragraph))


def _same(one: _Beside | None, other: _Beside | None) -> bool:
    """Whether two paragraphs beside tables are one, after one table and before the next."""
    return one is not None and other is not None and bool(one.lines & other.lines)


def layout(befores: list[_Beside | None], afters: list[_Beside | None]) -> str:
    """Where a file's legends stand: "before" its tables, where a legend stands before one
    with no table above it and none after one with no table below it; "after", the other way
    round; "" where neither, or both, is so. A legend between two tables is either's, and
    only the layout says whose."""
    alone_before = any(
        before is not None and _a_caption(before.text)
        and not (at and _same(before, afters[at - 1]))
        for at, before in enumerate(befores))  # fmt: skip
    alone_after = any(
        after is not None and _a_caption(after.text)
        and not (at + 1 < len(befores) and _same(after, befores[at + 1]))
        for at, after in enumerate(afters))  # fmt: skip
    if alone_before != alone_after:
        return "before" if alone_before else "after"
    return ""


def captions_of(befores: list[_Beside | None], afters: list[_Beside | None]) -> list[str]:
    """Each table's caption, given the paragraphs before and after each: where the file's
    legends stand before their tables, the one before; where after, the one after, which is
    then its own and never the next table's (round 2 of #703); and where the file says
    neither, only one no other table stands beside. "" where it has none."""
    shape = layout(befores, afters)
    found = []
    for at, (before, after) in enumerate(zip(befores, afters, strict=True)):
        before_ok = before is not None and _a_caption(before.text)
        after_ok = after is not None and _a_caption(after.text)
        shared_before = at > 0 and _same(before, afters[at - 1])
        shared_after = at + 1 < len(befores) and _same(after, befores[at + 1])
        if shape == "before":
            found.append(before.text if before_ok else "")
        elif shape == "after":
            found.append(after.text if after_ok else "")
        elif before_ok and not shared_before:
            found.append(before.text)
        elif after_ok and not shared_after:
            found.append(after.text)
        else:
            found.append("")
    return found


def _next_to(lines: list[str], table: Table, kind: str, step: int) -> _Beside | None:
    """The paragraph before a table (`step` -1) or after it (1): in a .docx the first line
    with text, past the lines of nothing but a cell's edge; in Markdown the paragraph past
    one blank line. None where a table's row or the end of the text comes first."""
    cells = _cells(table)
    inside = set(range(min(cells), max(cells) + 1))
    at = min(cells) - 1 if step < 0 else max(cells) + 1
    if kind == "docx":
        while 1 <= at <= len(lines):
            if at not in inside and lines[at - 1].strip(" \t|"):
                return _Beside(lines[at - 1].strip(), frozenset({at}))
            at += step
        return None
    if 1 <= at <= len(lines) and not lines[at - 1].strip(" \t|"):
        at += step
    taken: list[int] = []
    while 1 <= at <= len(lines) and lines[at - 1].strip(" \t|"):
        if lines[at - 1].lstrip().startswith(("|", "+")):
            break
        taken.append(at)
        at += step
    if not taken:
        return None
    return _Beside(_plain(" ".join(lines[line - 1] for line in sorted(taken))), frozenset(taken))


def _note(after: _Beside | None, captions: set[str]) -> str:
    """The paragraph after a table where it is its note: it opens with a note's mark, and is
    no caption, this table's, the next one's or any other's."""
    if after is None or _a_caption(after.text) or after.text in captions:
        return ""
    return after.text if NOTE_MARK.match(after.text) else ""


def _weighting(table: Table, caption: str, note: str) -> Weighting | None:
    """What says `table`'s shares are weighted: its caption or its note for the whole table,
    a row's label (the cell of its first column) for that row, and each header cell for its
    columns."""
    from manuscript_guard.stats.shares import _SHARE, _clean, _columns

    named = _NAME.search(caption)
    name = named.group(0) if named else "This table"
    for words in (caption, note):
        said: Said | None = weighting(_plain(words))
        if said is not None:
            return Weighting(whole=Weighted(name, said.quote))
    columns: list[tuple[int, Weighted]] = []
    rows: list[tuple[frozenset[int], Weighted]] = []
    header = True
    for row in table:
        placed = list(_columns(row))[1:]
        header = header and not any(_SHARE.fullmatch(_clean(cell.text)[0])
                                    for _column, cell in placed)  # fmt: skip
        if row and not header and (said := weighting(_plain(row[0].text))) is not None:
            rows.append((frozenset(cell.line for cell in row), Weighted(f"{name}'s row",
                                                                        said.quote)))
        for column, cell in placed if header else ():
            said = weighting(_plain(cell.text))
            if said is not None:
                columns += [(each, Weighted(f"{name}'s column", said.quote))
                            for each in range(column, column + max(cell.span, 1))]  # fmt: skip
    if not columns and not rows:
        return None
    return Weighting(columns=tuple(columns), rows=tuple(rows))


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
           "Weighted", "Weighting", "asked_p", "asked_share", "captions_of", "layout",
           "statement", "weighted_tables"]  # fmt: skip
