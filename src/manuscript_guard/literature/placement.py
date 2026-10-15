"""Where a quote that is not in its source nearly is, and what stands in the way.

G7 holds a ledger quote to its stored source exactly, once the differences that are not
differences are folded (`sources.normalise`). When the quote is not there, the reason is
most often one a person puts right in a minute once it is named:

* a line number, a column of the next page or a running header stands between two of the
  quote's words in the text read from a PDF;
* a word is split by a hyphen at the end of a line;
* the source writes "2·6" where the quote has "2.6", or a symbol the quote typed otherwise;
* the quote was retyped, and a word differs.

This finds the quote's words in the source in order, a few words apart at most, and says
which of these it is, and where. It decides nothing: the quote still fails until it is
what the source says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from manuscript_guard.literature.sources import (
    _EQUIVALENT,
    _SCRIPT,
    _TAG,
    HTML_SUFFIXES,
    PDF_SUFFIXES,
    TEXT_SUFFIXES,
    UnreadableSource,
    _read_pdf,
    normalise,
)

#: The most words that may stand between two of the quote's words for it to be read as
#: there, interrupted.
GAP = 12
#: How many of the quote's first words a reading may start from: a quote whose first word
#: was retyped is still found by its second.
STARTS = 3
#: The longest stretch of the source a message shows.
SHOWN = 80

_WORD = re.compile(r"\w+")
#: What lies between the two halves of a word split by a hyphen: at the end of a line, or a
#: soft hyphen within one.
_SPLIT = re.compile(
    r"[-\N{HYPHEN}\N{NON-BREAKING HYPHEN}][ \t]*\r?\n[ \t]*|\N{SOFT HYPHEN}[ \t]*(?:\r?\n[ \t]*)?"
)
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class _Token:
    word: str
    start: int
    end: int


@dataclass(frozen=True)
class Break:
    """What stands between two of the quote's words in the source."""

    before: str
    between: str
    after: str
    line: int

    @property
    def numbers(self) -> bool:
        """Whether only numbers stand there: line numbers, or a column of figures."""
        return all(word.isdigit() for word in _WORD.findall(self.between))


@dataclass(frozen=True)
class Split:
    """A word of the quote that the source splits with a hyphen."""

    first: str
    second: str
    line: int


@dataclass(frozen=True)
class Differs:
    """Where the quote's words stand together in the source and what is between two of them,
    or before the first or after the last, is not what the quote has."""

    before: str
    source: str
    quote: str
    after: str
    line: int


@dataclass(frozen=True)
class Placement:
    """How much of a quote the source holds in order, and where."""

    #: The quote's words, and how many of them the source holds in order.
    words: int
    found: int
    #: How many of the quote's first words are not found before the rest, and the lines
    #: those found run over.
    first: int
    lines: tuple[int, int]
    #: The source from the first word found to the last, as it writes it.
    excerpt: str
    breaks: tuple[Break, ...] = ()
    splits: tuple[Split, ...] = ()
    #: Where every word is there and together: the first place the two differ.
    differs: Differs | None = None
    #: The quote's first words not found.
    opening: str = ""
    #: Where the source holds fewer than all: the last word found, the quote's next one,
    #: and what the source has after the last.
    last: str = ""
    missing: str = ""
    instead: str = ""


def layout_text(path: Path) -> str:
    """A stored source's text with its lines where they are in the file: a text file as it
    is, an HTML page with its tags blanked, and a PDF as `read_source` reads it."""
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES or suffix == "":
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in HTML_SUFFIXES:
        raw = path.read_text(encoding="utf-8", errors="replace")

        def blank(match: re.Match[str]) -> str:
            return re.sub(r"[^\n]", " ", match.group(0))

        return _TAG.sub(blank, _SCRIPT.sub(blank, raw))
    if suffix in PDF_SUFFIXES:
        return _read_pdf(path)
    raise UnreadableSource(f"{path.name}: no reader for {suffix}")


def _fold(word: str) -> str:
    for source, target in _EQUIVALENT.items():
        word = word.replace(source, target)
    return word.lower()


def _tokens(text: str) -> list[_Token]:
    return [_Token(_fold(m.group(0)), m.start(), m.end()) for m in _WORD.finditer(text)]


def _split_at(source: str, tokens: list[_Token], k: int, word: str) -> bool:
    """Whether tokens k and k + 1 are `word` split by a hyphen."""
    if k + 1 >= len(tokens) or tokens[k].word + tokens[k + 1].word != word:
        return False
    return _SPLIT.fullmatch(source, tokens[k].end, tokens[k + 1].start) is not None


def _walk(
    source: str, tokens: list[_Token], words: list[str], first: int, at: int
) -> tuple[list[int], list[int]]:
    """The source tokens the quote's words from `first` on are found at, starting at `at`,
    each at most `GAP` words after the one before; and which of them are split words."""
    found, splits = [at], []
    k = at + 1
    if tokens[at].word != words[first]:
        splits.append(at)
        k = at + 2
    for word in words[first + 1 :]:
        for m in range(k, min(k + GAP + 1, len(tokens))):
            if tokens[m].word == word:
                found.append(m)
                k = m + 1
                break
            if _split_at(source, tokens, m, word):
                found.append(m)
                splits.append(m)
                k = m + 2
                break
        else:
            break
    return found, splits


def place(source: str, quote: str) -> Placement | None:
    """How much of `quote` the source holds in order, a few words apart at most; None where
    it holds fewer than two of its words so."""
    tokens = _tokens(source)
    quoted = _tokens(quote)
    words = [token.word for token in quoted]
    if len(words) < 2:
        return None
    # Where each word of the source starts, a word split by a hyphen among them.
    where: dict[str, list[int]] = {}
    for k, token in enumerate(tokens):
        where.setdefault(token.word, []).append(k)
        if k + 1 < len(tokens) and _split_at(source, tokens, k, token.word + tokens[k + 1].word):
            where.setdefault(token.word + tokens[k + 1].word, []).append(k)
    best: tuple[tuple[int, int, int], int, list[int], list[int]] | None = None
    for first in range(min(STARTS, len(words))):
        for at in where.get(words[first], ()):
            found, splits = _walk(source, tokens, words, first, at)
            end = found[-1] + (1 if found[-1] in splits else 0)
            spread = end - found[0] + 1 - len(found) - len(splits)
            score = (len(found), -first, -spread)
            if best is None or score > best[0]:
                best = (score, first, found, splits)
        if best is not None and best[0][0] == len(words) - first:
            break
    if best is None or len(best[2]) < 2:
        return None
    _score, first, found, splits = best
    return _placement(source, tokens, quote, quoted, first, found, splits)


def _line(source: str, at: int) -> int:
    return source.count("\n", 0, at) + 1


def _shown(text: str) -> str:
    text = _SPACE.sub(" ", text).strip()
    return text if len(text) <= SHOWN else text[: SHOWN - 3].rstrip() + "..."


def _placement(
    source: str,
    tokens: list[_Token],
    quote: str,
    quoted: list[_Token],
    first: int,
    found: list[int],
    splits: list[int],
) -> Placement:
    split = set(splits)

    def written(k: int) -> str:
        return source[tokens[k].start : tokens[k].end]

    breaks = []
    for here, there in zip(found, found[1:], strict=False):
        end = here + 1 if here in split else here
        if end + 1 < there:
            between = source[tokens[end].end : tokens[there].start]
            breaks.append(
                Break(written(end), _shown(between), written(there),
                      _line(source, tokens[end + 1].start))  # fmt: skip
            )
    halves = [Split(written(k), written(k + 1), _line(source, tokens[k].start)) for k in splits]
    last = found[-1] + (1 if found[-1] in split else 0)
    start, end = tokens[found[0]].start, tokens[last].end
    placement = Placement(
        words=len(quoted),
        found=len(found),
        first=first,
        lines=(_line(source, start), _line(source, end)),
        excerpt=_shown(source[start:end]),
        breaks=tuple(breaks),
        splits=tuple(halves),
        opening=" ".join(quote[t.start : t.end] for t in quoted[:first]),
    )
    if first + len(found) < len(quoted):
        return replace(
            placement,
            last=written(last),
            missing=quote[quoted[first + len(found)].start : quoted[first + len(found)].end],
            instead=" ".join(written(k) for k in range(last + 1, min(last + 4, len(tokens)))),
        )
    if first or breaks or halves:
        return placement
    return replace(placement, differs=_differs(source, tokens, quote, quoted, found))


def _differs(
    source: str, tokens: list[_Token], quote: str, quoted: list[_Token], found: list[int]
) -> Differs | None:
    """The first place where the quote's words stand together in the source and what lies
    between two of them, or before the first or after the last, differs."""
    return _within(source, tokens, quote, quoted, found) or _at_ends(
        source, tokens, quote, quoted, found
    )


def _within(
    source: str, tokens: list[_Token], quote: str, quoted: list[_Token], found: list[int]
) -> Differs | None:
    """The first two of the quote's words between which the source has something else."""
    for i in range(len(found) - 1):
        here, there = tokens[found[i]], tokens[found[i + 1]]
        theirs = source[here.end : there.start]
        ours = quote[quoted[i].end : quoted[i + 1].start]
        if normalise(theirs).lower() != normalise(ours).lower():
            return Differs(
                source[here.start : here.end], _SPACE.sub(" ", theirs), _SPACE.sub(" ", ours),
                source[there.start : there.end], _line(source, here.end),
            )  # fmt: skip
    return None


def _at_ends(
    source: str, tokens: list[_Token], quote: str, quoted: list[_Token], found: list[int]
) -> Differs | None:
    """What the quote has before its first word or after its last that the source has not."""
    head, tail = tokens[found[0]], tokens[found[-1]]
    ours = quote[: quoted[0].start].strip()
    theirs = source[max(0, head.start - len(ours) - 1) : head.start]
    if ours and not normalise(theirs).lower().endswith(normalise(ours).lower()):
        shown = _SPACE.sub(" ", theirs).strip()
        return Differs("", shown, ours, source[head.start : head.end], _line(source, head.start))
    ours = quote[quoted[-1].end :].strip()
    theirs = source[tail.end : tail.end + len(ours) + 1]
    if ours and not normalise(theirs).lower().startswith(normalise(ours).lower()):
        shown = _SPACE.sub(" ", theirs).strip()
        return Differs(source[tail.start : tail.end], shown, ours, "", _line(source, tail.end))
    return None


def said(placement: Placement, numbered: bool = True) -> str:
    """What a placement says, in a clause that follows "the quote does not appear in
    <source>"; with line numbers where the source's lines are a file's own."""

    def at(line: int, last: int | None = None) -> str:
        if not numbered:
            return ""
        if last is None or last == line:
            return f" (line {line})"
        return f" (lines {line}-{last})"

    if placement.first or placement.missing:
        said = f"{placement.found} of its {placement.words} words are there in order"
        said += f"{at(*placement.lines)}: '{placement.excerpt}'"
        if placement.first:
            word = "word" if placement.first == 1 else f"{placement.first} words"
            verb = "is" if placement.first == 1 else "are"
            said += f"; its first {word}, '{placement.opening}', {verb} not before them"
        if placement.missing:
            said += (
                f"; after '{placement.last}' the quote has '{placement.missing}', where the "
                f"source has '{placement.instead}'"
            )
        return said
    if not placement.breaks and not placement.splits:
        one = placement.differs
        if one is None:
            return f"its words are all there, in order and together{at(*placement.lines)}"
        place = (
            f"between '{one.before}' and '{one.after}'" if one.before and one.after
            else f"after '{one.before}'" if one.before else f"before '{one.after}'"
        )  # fmt: skip
        return (
            f"its words are all there, in order and together, and {place}{at(one.line)} the "
            f"source has '{one.source}' where the quote has '{one.quote}'"
        )
    parts = [
        f"'{one.first}' and '{one.second}' are one word, split by a hyphen{at(one.line)}"
        for one in placement.splits[:2]
    ]
    for one in placement.breaks[:2]:
        kind = "numbers, such as line numbers or a column of figures" if one.numbers else (
            "words the quote leaves out, or a column, a footnote or a running header"
        )  # fmt: skip
        parts.append(
            f"the source has '{one.between}' between '{one.before}' and "
            f"'{one.after}'{at(one.line)}: {kind}"
        )
    more = len(placement.splits) + len(placement.breaks) - len(parts)
    if more:
        parts.append(f"and {more} more")
    return "its words are all there in order; " + "; ".join(parts)


def why_not_found(path: Path, quote: str) -> str | None:
    """What a source that does not hold a quote holds of it, for G7's finding; None where it
    holds nothing in order, or cannot be read again."""
    try:
        text = layout_text(path)
    except (OSError, UnreadableSource):
        return None
    placement = place(text, quote)
    if placement is None:
        return None
    return said(placement, numbered=path.suffix.lower() not in PDF_SUFFIXES)
