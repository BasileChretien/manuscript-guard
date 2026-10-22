"""The words of a LaTeX file, as G14 reads a Markdown file's (DESIGN.md, "LaTeX manuscripts", the
reader's `words`; `language._hidden` for Markdown).

The view keeps the file's length and line breaks, and is NUL wherever G14 reads no word:
- what the reader blanks (`mask.py`);
- the preamble, but an abstract written there: the title is the title page's, as the title in
  Markdown's front matter is;
- maths, inline and displayed, and code, `\\verb` and `\\texttt`, as Markdown's are;
- a float that holds a figure, whose caption is not read, as an image's caption in Markdown is
  not;
- a word holding an accent command or `\\-`, `caf\\'e` or `co\\-operate`, whose letters the reader
  cannot write side by side at their places. `unread` gives where each is, so that G14 can say
  how many it did not read.

A count written as a subscript straight after a letter, `CO$_2$` or `CO\\textsubscript{2}`, is
written as Markdown writes it, `CO~2~`, with NUL after it, so that G14 reads a chemical formula
as one, as it does in Markdown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.text.latex.mask import NUL
from manuscript_guard.text.latex.structure import Source

#: An accent command with the letter it marks: `\\'e`, `\\'{e}`, `\\"{\\i}`, `\\c c`, `\\v{s}`.
_ACCENT = (
    r"\\(?:[`'^\"~=.]|[uvHcdbrkt](?![A-Za-z]))[ \t]*"
    r"(?:\{[ \t]*(?:\\[ij](?![A-Za-z]))?[ \t]*[A-Za-z]?[ \t]*\}|\\[ij](?![A-Za-z])|[A-Za-z])"
)
#: A letter typed as a command: `\\ss`, `\\o`, `\\ae`, the dotless `\\i`.
_LETTER = r"\\(?:ss|ae|AE|oe|OE|aa|AA|o|O|l|L|i|j)(?![A-Za-z])(?:[ \t]*\{\})?"
#: What splits a word in the reader's view: an accent, a letter typed as a command, or `\\-`.
_SPLITS = re.compile(rf"{_ACCENT}|{_LETTER}|\\-")
#: A count written as a subscript: `$_2$`, `$_{12}$`, `\\textsubscript{2}`.
_SUBSCRIPT = re.compile(r"\$_(?:\{(\d{1,2})\}|(\d))\$|\\textsubscript\{(\d{1,2})\}")


@dataclass(frozen=True)
class Words:
    """A file's words as G14 reads them, and where each word it does not read stands."""

    text: str
    unread: tuple[tuple[int, int], ...]


def words(source: Source) -> Words:
    """The file's words, NUL elsewhere, and the words holding an accent command or `\\-`."""
    reading = source.reading
    out = list(reading.masked)
    text = source.text
    for index, char in enumerate(text):
        if char == "\n":
            out[index] = "\n"
    _hide(out, [*_preamble(reading), *_maths(reading), *_code(reading), *reading.figures])
    _subscripts(out, text)
    unread = [span for span in _split_words(text) if _read(out, span)]
    _hide(out, unread)
    return Words("".join(out), tuple(unread))


def _preamble(reading) -> list[tuple[int, int]]:
    """The preamble, less each abstract written in it: where the body starts, or the whole
    file where it never does."""
    body = reading.body_start if reading.body_start >= 0 else len(reading.masked)
    spans, at = [], 0
    for start, end in sorted(reading.abstracts):
        if start >= body:
            break
        spans.append((at, start))
        at = end
    spans.append((at, body))
    return spans


def _maths(reading) -> list[tuple[int, int]]:
    return [(start, end) for start, end, _displayed in reading.maths]


def _code(reading) -> list[tuple[int, int]]:
    return list(reading.code)


def _hide(out: list[str], spans) -> None:
    for start, end in spans:
        for index in range(start, end):
            if out[index] != "\n":
                out[index] = NUL


def _subscripts(out: list[str], text: str) -> None:
    """A count written as a subscript after a letter, as Markdown's `~2~`, where it is read."""
    for found in _SUBSCRIPT.finditer(text):
        start = found.start()
        if not (start and text[start - 1].isalpha() and out[start - 1] != NUL):
            continue
        # Maths is hidden by now, so a `$_2$` is NUL; `\\textsubscript`'s digits are prose.
        if found.group(3) is not None and out[found.start(3)] == NUL:
            continue
        count = next(group for group in found.groups() if group is not None)
        written = f"~{count}~"
        out[start : found.end()] = list(written + NUL * (found.end() - start - len(written)))


def _split_words(text: str) -> list[tuple[int, int]]:
    """Each word holding an accent command, a letter typed as a command or `\\-`, with its
    letters and braces on either side: `na\\"{\\i}ve` whole. Linear in the file: a word is
    widened once, from where the last one ended."""
    spans: list[tuple[int, int]] = []
    for found in _SPLITS.finditer(text):
        if spans and found.start() < spans[-1][1]:
            continue
        start, floor = found.start(), spans[-1][1] if spans else 0
        while start > floor and _in_word(text[start - 1]):
            start -= 1
        end = found.end()
        while end < len(text):
            if _in_word(text[end]):
                end += 1
                continue
            more = _SPLITS.match(text, end)
            if more is None:
                break
            end = more.end()
        spans.append((start, end))
    return spans


def _in_word(char: str) -> bool:
    return char.isalnum() or char in "{}"


def _read(out: list[str], span: tuple[int, int]) -> bool:
    """Whether any of the word is read: one in a comment, maths or the preamble is not."""
    return any(out[index] not in (NUL, "\n") for index in range(*span))
