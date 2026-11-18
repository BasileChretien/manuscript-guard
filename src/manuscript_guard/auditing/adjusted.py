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
_NAME = re.compile(r"(?:Supplementary\s+|e|S)?Table\s+[A-Za-z]?\d+[A-Za-z]?")


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
    """What says a table's shares are weighted: the table's name and the words quoted."""

    name: str
    quote: str


def weighted_tables(tables: list[Table], *, text: str, kind: str, latex=None
                    ) -> list[Weighted | None]:  # fmt: skip
    """For each of `tables`, what says its shares are weighted, None where nothing does.
    `text` is the file's text a line to each line its tables' cells name, `kind` "docx",
    "markdown" or "latex", `latex` a LaTeX file's `Source`."""
    if kind == "latex":
        around = _latex_floats(latex)
        return [_weighted(table, *around.get(table[0][0].line, ("", ""))) if table and table[0]
                else None for table in tables]  # fmt: skip
    if kind == "docx":
        from manuscript_guard.text.captioned import docx_captioned

        lines = text.split("\n")
        # Each table alone: a table with no cell has no lines to find its caption by.
        return [_weighted(table, docx_captioned(lines, [table])[0].caption,
                          _docx_note(lines, table))
                if any(row for row in table) else None for table in tables]  # fmt: skip
    from manuscript_guard.text.captioned import markdown_captioned

    lines = text.split("\n")
    captions = {found.line: found.caption for found in markdown_captioned(text)}
    return [_weighted(table, captions.get(table[0][0].line, ""), _markdown_note(lines, table))
            if table and table[0] else None for table in tables]  # fmt: skip


def _weighted(table: Table, caption: str, note: str) -> Weighted | None:
    """What says `table`'s shares are weighted, in its caption, its cells or its note."""
    cells = " | ".join(" ".join(cell.text.split()) for row in table for cell in row)
    for words in (caption, cells, note):
        said: Said | None = weighting(words)
        if said is not None:
            named = _NAME.search(caption)
            return Weighted(named.group(0) if named else "This table", said.quote)
    return None


def _docx_note(lines: list[str], table: Table) -> str:
    """The paragraph after a .docx's table, read a paragraph to a line, unless it is a
    caption (`_a_caption`)."""
    from manuscript_guard.text.captioned import _beside

    cells = [cell.line for row in table for cell in row]
    inside = set(range(min(cells), max(cells) + 1))
    after = _beside(lines, max(cells) + 1, 1, inside)
    return "" if _a_caption(after) else after


def _markdown_note(lines: list[str], table: Table) -> str:
    """The paragraph after a Markdown table, past one blank line, unless it is a caption
    (`_a_caption`)."""
    last = max(cell.line for row in table for cell in row)
    taken, at = [], last + 1
    if at <= len(lines) and not lines[at - 1].strip():
        at += 1
    while at <= len(lines) and lines[at - 1].strip() and not lines[at - 1].lstrip().startswith(
            ("|", "+")):  # fmt: skip
        taken.append(lines[at - 1])
        at += 1
    note = " ".join(taken)
    return "" if _a_caption(note) else note


def _a_caption(paragraph: str) -> bool:
    """Whether a paragraph after a table is a caption, "Table 2. ..." or pandoc's "Table:
    ...": the next table's, whose weighting is not this one's, or this table's own, which its
    caption gives already."""
    from manuscript_guard.text.captioned import _LEGEND, _PANDOC

    return bool(_LEGEND.match(paragraph) or _PANDOC.match(paragraph))


def _latex_floats(source) -> dict[int, tuple[str, str]]:
    """Each LaTeX table by its header row's line: the caption of the float it stands in, and
    all of that float's text, which holds its notes."""
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
        found[line] = (captions.get(line, ""), source.text[low:high])
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
    named = "this table" if weighted.name == "This table" else weighted.name
    refereed = (f"{described}; {named} says its shares are weighted (\"{weighted.quote}\"): "
                "the author is asked whether it is the weighted share.")
    return Asked(path, share.line, message, share.context, ASKED_WEIGHTED, refereed)


__all__ = ["ASKED_ADJUSTED", "ASKED_WEIGHTED", "Asked", "Statement", "Weighted", "asked_p",
           "asked_share", "statement", "weighted_tables"]  # fmt: skip
