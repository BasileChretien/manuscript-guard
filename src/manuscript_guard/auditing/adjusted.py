"""The audit's questions on numbers that may fit after all: a P larger than its statistic
gives, in a paper that says its P values are adjusted for multiple comparisons, and a share
off its column's n, in a table that says its shares are weighted (Basile, 2026-11-16,
decision 31: "Both"). What says so is read in `stats/adjusted.py`.

* **A paper's adjustment** is the first statement of it in the paper, outside its reference
  list: in any file of a LaTeX paper, and in a .docx's notes. A test in any file of the paper
  is read under it. A figure given with `--figures` is no part of a paper, and reads none.
* **A table's weighting** is said in its caption, the legend that numbers it
  (`numbered_captions`) or pandoc's; its note, the paragraph after it that opens with a
  note's mark; a row's label, for that row; or a header cell, for its column. In LaTeX the
  float's caption and its text outside the table. Only that table's shares are let off. A
  PDF's tables are read as lines of text, so none is.

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


#: A legend, "table" in any case: "TABLE 2.", "**Table 1:**", "Table S3 Baseline", "Table 2
#: (continued)"; its form ("Table", "Supplementary Table", "eTable"), the letter before its
#: number ("S", "A"), its number, and a letter after it ("1a").
LEGEND = re.compile(
    r"[ \t]*[*_]*(?P<form>(?i:(?:Supplementary[ \t]+|e|S)?Table))[ \t]+(?P<letter>[A-Za-z]?)"
    r"(?P<number>\d+)(?P<tail>[A-Za-z]?)[*_]*"
    "(?:[ \t]*[.:|\N{EN DASH}\N{EM DASH}-]|[ \t]*\\((?i:continued)|[ \t]+(?=[A-Z]))"
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


def weighted_tables(tables: list[Table], *, text: str, kind: str, latex=None,
                    masked: str | None = None) -> list[Weighting | None]:  # fmt: skip
    """For each of `tables`, what says its shares are weighted, None where nothing does.
    `text` is the file's text a line to each line its tables' cells name, `masked` the same
    masked, where its legends are looked for (a comment's are none), `kind` "docx",
    "markdown" or "latex", `latex` a LaTeX file's `Source`. A caption is the legend that
    numbers the table (`numbered_captions`), or pandoc's for its own table; a note is the
    paragraph after the table where it opens with a note's mark (`NOTE_MARK`) and is no
    caption; in LaTeX, the float's text outside the table."""
    if kind == "latex":
        around = _latex_floats(latex)
        return [_weighting(table, *around.get(table[0][0].line, ("", ""))) if _cells(table)
                else None for table in tables]  # fmt: skip
    lines = text.split("\n")
    shown = (masked if masked is not None else text).split("\n")
    read = sorted((table for table in tables if _cells(table)), key=lambda t: min(_cells(t)))
    numbered = numbered_captions(_paragraphs(lines, shown, read, kind), read)
    pandoc = _pandoc_captions(lines, read) if kind == "markdown" else [""] * len(read)
    captions = [" ".join(part for part in (one, two) if part)
                for one, two in zip(numbered, pandoc, strict=True)]  # fmt: skip
    taken = {caption for caption in captions if caption}
    said = {id(table): _weighting(table, caption, _note(_next_to(lines, table, kind, 1), taken),
                                  named=number)
            for table, caption, number in zip(read, captions, numbered, strict=True)}
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


@dataclass(frozen=True)
class _Paragraph:
    """A paragraph outside the tables, as one line, and its first and last lines from 1."""

    text: str
    first: int
    last: int


def _paragraphs(lines: list[str], shown: list[str], tables: list[Table], kind: str
                ) -> list[_Paragraph]:  # fmt: skip
    """The paragraphs of a file outside its tables, in order: a .docx's a line each, a
    Markdown file's its runs of lines with text. Read in `shown`, the masked lines, and said
    in `lines`."""
    inside = {line for table in tables for line in range(min(_cells(table)),
                                                         max(_cells(table)) + 1)}  # fmt: skip
    found: list[_Paragraph] = []
    run: list[int] = []

    def close() -> None:
        if run:
            found.append(_Paragraph(_plain(" ".join(lines[at - 1] for at in run)), run[0],
                                    run[-1]))  # fmt: skip
            run.clear()

    for at, line in enumerate(shown, start=1):
        text = line.replace("\x00", " ")
        if at in inside or not text.strip(" \t|") or text.lstrip().startswith(("|", "+")):
            close()
            continue
        run.append(at)
        if kind == "docx":
            close()
    close()
    return found


def numbered_captions(paragraphs: list[_Paragraph], tables: list[Table]) -> list[str]:
    """Each table's caption by its number: the legend "Table N" captions the Nth table of the
    file, before it or after it with other paragraphs between, but no other table (Basile,
    2026-11-18). Only where the file's legends number its tables: all in one form ("Table
    N", or all "Table SN", "Table AN" ...), numbered 1 to the number of tables read, each
    once. Else no table has one: a table given as a picture, a "Table 2 (continued)", or a
    "Table S1" beside a "Table 1" says the legends and the tables read do not match. A legend
    reaches its table across no other table and no other legend (round 3 of #703: a legend of
    a table given as a picture, before the next table's legend, reached the table after it);
    one that cannot reach its table captions nothing, and the file's other legends caption
    their tables still."""
    legends = [(paragraph, found) for paragraph in paragraphs
               if (found := LEGEND.match(paragraph.text)) is not None]  # fmt: skip
    forms = {(found["form"].lower(), found["letter"].upper(), found["tail"].lower())
             for _paragraph, found in legends}  # fmt: skip
    numbers = sorted(int(found["number"]) for _paragraph, found in legends)
    if len(forms) != 1 or numbers != list(range(1, len(tables) + 1)):
        return [""] * len(tables)
    spans = [(min(_cells(table)), max(_cells(table))) for table in tables]
    others = [paragraph for paragraph, _found in legends]
    captions = [""] * len(tables)
    for paragraph, found in legends:
        at = int(found["number"]) - 1
        first, last = spans[at]
        before = paragraph.last < first and (at == 0 or paragraph.first > spans[at - 1][1]) \
            and not across_a_legend(paragraph.last, first, others)  # fmt: skip
        after = paragraph.first > last and (at + 1 == len(tables)
                                            or paragraph.last < spans[at + 1][0]) \
            and not across_a_legend(last, paragraph.first, others)  # fmt: skip
        if before or after:
            captions[at] = paragraph.text
    return captions


def across_a_legend(low: int, high: int, legends: list[_Paragraph]) -> bool:
    """Whether a legend stands between lines `low` and `high`, from 1, both left out."""
    return any(low < legend.first and legend.last < high for legend in legends)


def _pandoc_captions(lines: list[str], tables: list[Table]) -> list[str]:
    """Each Markdown table's caption in pandoc's own syntax, "Table: ..." or ": ...": the
    paragraph before it that no table above took, else the one after it, as pandoc 3.9 gives
    one (`text.captioned`)."""
    from manuscript_guard.text.captioned import _PANDOC

    taken: set[int] = set()
    found = []
    for table in tables:
        caption = ""
        for step in (-1, 1):
            beside = _next_to(lines, table, "markdown", step)
            if beside is not None and _PANDOC.match(beside.text) and \
                    not beside.lines & taken:  # fmt: skip
                taken |= beside.lines
                caption = _PANDOC.sub("", beside.text, count=1)
                break
        found.append(caption)
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


def _weighting(table: Table, caption: str, note: str, *, named: str = "") -> Weighting | None:
    """What says `table`'s shares are weighted: its caption or its note for the whole table,
    a row's label (the cell of its first column) for that row, and each header cell for its
    columns. The table is named by its legend, `named`, or else by its caption."""
    from manuscript_guard.stats.shares import _SHARE, _clean, _columns

    named = _NAME.search(named or caption)
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
           "Weighted", "Weighting", "asked_p", "asked_share", "numbered_captions",
           "statement", "weighted_tables"]  # fmt: skip
