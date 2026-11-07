"""Whether a review finding stands on words of the manuscript its reader read (item 1).

DESIGN.md, "What the panel finds of the defects we know": a reader sent only the title and
abstract raised every defect the example's first panel found, nearly always as major. A
finding raised is no evidence that the paper was read. So a finding quotes the words it is
about, or, for something missing, the heading of the section where it belongs, and the quote
is looked for in what the reading read, once, when the reading is filed: by `review --run`
in what each model was sent, and by `review --seal` in the files whose digests a reading
filed by hand carries, as they are written and as the build prints them.

**Found as G7 finds a passage in a work's source** (`gates.quotations.words_in`): folded as
G7 folds a quote, its white space, curly quotes, dashes and ligatures, as whole words, and
piece by piece in order where words are left out. Markdown's marks of emphasis, code and
tables are no words, and come out of both sides first, with what pandoc prints otherwise
than it is written: a link's text, a sub- or superscript and its dashes. **A quote holds at
least `QUOTE_WORDS` words, or is the whole title of a heading there**: a word or two is
found in any paper, and the example's abstract has a bold "Methods." in its first
paragraph. Of a quote with words left out, only the pieces of two words or more count.

What is found is kept in the record, `quotes: {anchored: [...], unanchored: [...]}`, and
sealed with what the reader wrote. G11 reads that, and never the text: by the time `check`
runs the files may have changed, and the results whose values the build prints with them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from manuscript_guard.gates.quotations import _ELIDED, _SIC, words_in
from manuscript_guard.literature.sources import WORDS_BESIDE, _words_of, normalise

#: The fewest words a quote holds, unless it is a heading's title: the fewest G7 wants beside
#: a value for the quote to show what the value is of.
QUOTE_WORDS = WORDS_BESIDE

#: Markdown's marks of emphasis and code, which are no part of a word: taken out.
_MARKS = re.compile(r"[*_`]")
#: A pipe between a table's cells, which stands between words: a space.
_CELLS = re.compile(r"\|")
#: The hashes that open a heading's line.
_HASHES = re.compile(r"(?m)^[ \t]{0,3}#+[ \t]*")
#: A Markdown link, which pandoc prints as its text, wrapped over lines or not.
_LINK = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")
#: Pandoc's subscript and superscript, `H~2~O` and `10^3^`, printed as what they hold.
_SCRIPTS = re.compile(r"([~^])([^\s~^]+)\1")
#: Pandoc's dashes, `--` and `---`, which Word prints as an en and an em dash, and which
#: `normalise` folds to one hyphen.
_DASHES = re.compile(r"-{2,}")
#: A section's number before its title, "2.", "2.1", "12" or "S1.", which a reader may
#: leave out: one or two digits, or dotted, so that a year opening a title stays in it
#: (round 1 of #581: "2020 cohort" was titled "cohort").
_NUMBER = re.compile(r"^(?:[a-z]?\d{1,2}(?:\.\d+)*\.?|\d+(?:\.\d+)+\.?)\s+")
#: The fewest words a piece of a quote with words left out holds for it to count.
_PIECE_WORDS = 2
#: What may close a heading or a quote of one, "Methods." or "Methods:".
_CLOSING = " .:;,"


def plain(text: str) -> str:
    """`text` without the marks Markdown sets around words: emphasis, code, a table's cell
    walls and a heading's hashes; a link as its text, a sub- or superscript as what it
    holds, and a pandoc dash as one hyphen, as Word prints them (round 1 of #581)."""
    text = _LINK.sub(r"\1", _HASHES.sub("", text))
    text = _DASHES.sub("-", _SCRIPTS.sub(r"\2", text))
    return _CELLS.sub(" ", _MARKS.sub("", text))


def _title(text: str) -> str:
    """A heading's title, or a quote of one, as the two are compared: folded, and without
    the section's number or a closing stop."""
    folded = normalise(plain(text)).lower().strip(_CLOSING)
    return _NUMBER.sub("", folded).strip(_CLOSING)


def words(quote: str) -> int:
    """How many words a quote holds, less what marks words left out: a word is a run between
    spaces with a letter or a digit in it, a run of a script written without spaces counted
    as G7 counts the words beside a value (`literature.sources._words_of`). Where words are
    left out, only the pieces of two words or more count: a word between elisions is found
    in almost any paper (round 1 of #581; Basile, 2026-11-07)."""
    pieces = _ELIDED.split(_SIC.sub(" ", plain(quote)))
    counted = [
        sum(len(_words_of(run)) or any(char.isdigit() for char in run) for run in piece.split())
        for piece in pieces
    ]
    return sum(count for count in counted if count >= _PIECE_WORDS)


@dataclass(frozen=True)
class Read:
    """What a reading read, as its quotes are looked for in it: each text folded, and the
    titles of its headings."""

    texts: tuple[str, ...]
    titles: frozenset[str]


def read_of(texts: Iterable[str], *, latex: bool = False) -> Read:
    """`texts`, the manuscript's files as a reader read them, with their headings: Markdown's
    as pandoc reads them, or LaTeX's sectioning commands."""
    texts = tuple(texts)
    found: set[str] = set()
    for text in texts:
        found |= set(_headings(text, latex))
    return Read(
        texts=tuple(normalise(plain(text)).lower() for text in texts),
        titles=frozenset(title for title in map(_title, found) if title),
    )


def _headings(text: str, latex: bool) -> list[str]:
    if latex:
        from manuscript_guard.text.latex.mask import read

        try:
            return [heading.title for heading in read(text).headings]
        except (ValueError, RecursionError):
            return []
    from manuscript_guard.text.blocks import find_headings

    return [heading.title for heading in find_headings(text)]


def stands(quote: str, read: Read) -> bool:
    """Whether `quote` is a heading's whole title in what was read, or holds `QUOTE_WORDS`
    words or more that stand there as words of their own, in one of its texts."""
    if _title(quote) in read.titles:
        return True
    if words(quote) < QUOTE_WORDS:
        return False
    wanted = plain(quote)
    return any(words_in(text, wanted) for text in read.texts)


def quoted(finding: Mapping[str, object]) -> bool:
    """Whether a finding gives a quote: some text that is not all white space."""
    quote = finding.get("quote")
    return isinstance(quote, str) and bool(quote.strip())


def sort_quotes(
    findings: Iterable[Mapping[str, object]], read: Read, *, must_quote: bool
) -> dict[str, list[str]]:
    """The ids of the findings whose quote stands in what was read, and of the rest. A
    finding that quotes nothing is unanchored where its reader had to quote (a model's,
    D1.2), and in neither list where it did not (a person's)."""
    anchored: list[str] = []
    unanchored: list[str] = []
    for finding in findings:
        if not quoted(finding):
            if must_quote:
                unanchored.append(str(finding["id"]))
            continue
        quote = str(finding["quote"])
        (anchored if stands(quote, read) else unanchored).append(str(finding["id"]))
    return {"anchored": anchored, "unanchored": unanchored}


__all__ = ["QUOTE_WORDS", "Read", "plain", "quoted", "read_of", "sort_quotes", "stands", "words"]
