"""The words of a LaTeX file, as G14 reads a Markdown file's (DESIGN.md, "LaTeX manuscripts", the
reader's `words`; `language._hidden` for Markdown).

The view keeps the file's length and line breaks, and is NUL wherever G14 reads no word:
- what the reader blanks (`mask.py`);
- the preamble, but an abstract written there: the title is the title page's, as the title in
  Markdown's front matter is;
- maths, inline and displayed, and code, `\\verb` and `\\texttt`, as Markdown's are;
- a float that holds a figure, whose caption is not read, as an image's caption in Markdown is
  not;
- an accent over no letter, `caf\\'{}e`, and the word it stands in. `unread` gives where each
  is, so that G14 can say how many it did not read.

A word holding an accent command, a letter typed as a command or `\\-`, `caf\\'e`, `Stra\\ss e`
or `co\\-operate`, is written as LaTeX prints it, `café`, `Straße`, `cooperate`, from where it
starts, with NUL after it to its end (2026-10-27: such a word was not read).

A count written as a subscript straight after a letter, `CO$_2$` or `CO\\textsubscript{2}`, is
written as Markdown writes it, `CO~2~`, with NUL after it, so that G14 reads a chemical formula
as one, as it does in Markdown.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from manuscript_guard.text.latex.mask import NUL
from manuscript_guard.text.latex.structure import Source

#: An accent command with the letter it marks: `\\'e`, `\\'{e}`, `\\"{\\i}`, `\\c c`, `\\v{s}`.
_ACCENT = (
    r"\\(?:[`'^\"~=.]|[uvHcdbrkt](?![A-Za-z]))[ \t]*"
    r"(?:\{[ \t]*(?:\\[ij](?![A-Za-z]))?[ \t]*[A-Za-z]?[ \t]*\}|\\[ij](?![A-Za-z])|[A-Za-z])"
)
#: A letter typed as a command: `\\ss`, `\\o`, `\\ae`, the dotless `\\i`; with the spaces after
#: it that TeX passes over before a letter, so `Stra\\ss e` is one word (2026-10-27).
_LETTER = (r"\\(?:ss|ae|AE|oe|OE|aa|AA|o|O|l|L|i|j)(?![A-Za-z])"
           r"(?:[ \t]*\{\}|[ \t]+(?=[A-Za-z]))?")
#: What splits a word in the reader's view: an accent, a letter typed as a command, or `\\-`.
_SPLITS = re.compile(rf"{_ACCENT}|{_LETTER}|\\-")
#: `_SPLITS` with its parts named: the accent, the letter it marks, braced, dotless or bare,
#: and the letter typed as a command.
_FOLDING = re.compile(
    r"\\(?P<accent>[`'^\"~=.]|[uvHcdbrkt](?![A-Za-z]))[ \t]*"
    r"(?:\{[ \t]*(?:\\(?P<dotless>[ij])(?![A-Za-z]))?[ \t]*(?P<braced>[A-Za-z]?)[ \t]*\}"
    r"|\\(?P<bare>[ij])(?![A-Za-z])|(?P<letter>[A-Za-z]))"
    r"|\\(?P<command>ss|ae|AE|oe|OE|aa|AA|o|O|l|L|i|j)(?![A-Za-z])"
    r"(?:[ \t]*\{\}|[ \t]+(?=[A-Za-z]))?"
    r"|\\-"
)
#: The combining mark each accent command sets over or under its letter, as LaTeX's
#: `\\'`, `\\"`, `\\c` and the others print it.
_MARKS = {"`": 0x300, "'": 0x301, "^": 0x302, "~": 0x303, "=": 0x304, "u": 0x306, ".": 0x307,
          '"': 0x308, "r": 0x30A, "H": 0x30B, "v": 0x30C, "d": 0x323, "c": 0x327, "k": 0x328,
          "b": 0x331, "t": 0x361}  # fmt: skip
#: The letter each command prints: `\\ss`, `\\ae`, `\\o`, the dotless `\\i`.
_LETTERS = {"ss": 0xDF, "ae": 0xE6, "AE": 0xC6, "oe": 0x153, "OE": 0x152, "aa": 0xE5,
            "AA": 0xC5, "o": 0xF8, "O": 0xD8, "l": 0x142, "L": 0x141, "i": 0x131,
            "j": 0x237}  # fmt: skip


def folded(found: re.Match[str]) -> str | None:
    """What a match of `_FOLDING` prints: the accented letter, composed where Unicode composes
    it (`\\'e` is `é`, `\\"{\\i}` is `ï`), the letter a command types, or nothing for `\\-`;
    None for an accent over no letter, `\\'{}`, which prints a mark alone."""
    if found["command"]:
        return chr(_LETTERS[found["command"]])
    if found["accent"] is None:
        return ""
    base = found["dotless"] or found["bare"] or found["braced"] or found["letter"]
    if not base:
        return None
    return unicodedata.normalize("NFC", base + chr(_MARKS[found["accent"]]))


def accented(text: str, masked: str) -> str:
    """`masked`, the reader's mask of `text`, with each accent command whose letter it reads
    written as the accented letter, at the command's backslash, and each letter typed as a
    command beside a letter it reads written as that letter, NUL for the rest of each: so a
    view that takes the NULs out prints `Chr\\'etien` as the PDF does, and not `Chretien`
    (Known gaps, 2026-10-27). The length and the line breaks are kept."""
    out = list(masked)
    for found in _FOLDING.finditer(text):
        written = folded(found)
        if not written:
            continue
        start, end = found.span()
        if found["accent"] is not None and (found["braced"] or found["letter"]):
            at = found.start("braced") if found["braced"] else found.start("letter")
            if masked[at] == NUL:
                continue
        elif not (start and masked[start - 1].isalpha()) and not (
                end < len(masked) and masked[end].isalpha()):
            continue
        # A letter Unicode composes with no accent, `Erd\\H{e}s`, is a letter and a combining
        # mark, and the mark goes in the place after it: written into one place, both made
        # the view a character longer from there on, every later slice one place off. An
        # accent command spans three places at least, so the mark has one.
        places = [index for index in range(start + 1, end) if out[index] not in "\r\n"]
        out[start] = written[0]
        rest = iter(written[1 : 1 + len(places)])
        for index in places:
            out[index] = next(rest, NUL)
    return "".join(out)
#: A count written as a subscript: `$_2$`, `$_{12}$`, `\\textsubscript{2}`.
_SUBSCRIPT = re.compile(r"\$_(?:\{(\d{1,2})\}|(\d))\$|\\textsubscript\{(\d{1,2})\}")


@dataclass(frozen=True)
class Words:
    """A file's words as G14 reads them, and where each word it does not read stands."""

    text: str
    unread: tuple[tuple[int, int], ...]


def words(source: Source) -> Words:
    """The file's words, NUL elsewhere, and the words holding an accent over no letter."""
    reading = source.reading
    out = list(reading.masked)
    text = source.text
    for index, char in enumerate(text):
        if char == "\n":
            out[index] = "\n"
    _hide(out, [*_preamble(reading), *_maths(reading), *_code(reading), *reading.figures])
    _subscripts(out, text)
    unread = []
    for span in _split_words(text):
        if not _read(out, span):
            continue
        written = _word(text, out, *span)
        if written is None:
            unread.append(span)
            continue
        start, end = span
        out[start:end] = list(written + NUL * (end - start - len(written)))
    _hide(out, unread)
    return Words("".join(out), tuple(unread))


def _word(text: str, out: list[str], start: int, end: int) -> str | None:
    """A word that holds an accent command, a letter typed as a command or `\\-`, as LaTeX
    prints it: what the view reads of it, each of those the letter it prints, side by side
    (Known gaps, 2026-10-27: `caf\\'e` was not read). None where an accent marks no letter."""
    pieces: list[str] = []
    at = start
    for found in _FOLDING.finditer(text, start, end):
        pieces += [char for char in out[at : found.start()] if char != NUL]
        written = folded(found)
        if written is None:
            return None
        pieces.append(written)
        at = found.end()
    pieces += [char for char in out[at:end] if char != NUL]
    return "".join(pieces)


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
