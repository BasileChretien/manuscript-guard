"""TeX that stands outside maths in one line of Markdown, as pandoc reads the line.

Pandoc reads a backslash directly before a letter as the start of a TeX command, wherever
it stands, and the Word writer keeps TeX only as maths, between dollar signs. Anywhere else
the command is left out of the document with what it takes as TeX would: `IFN-\\gamma
release assays` is printed `IFN-release assays`, and `12 \\pm 3 months` is printed
without its `3`.

This is a model of that reading, for the text the build prints of `paper.yaml`, where
there is no pandoc to ask: `check` runs without one. What it must never do is pass a line
pandoc drops TeX from, and `tests/test_tex.py` holds it to pandoc for that, on tables and on
random lines. Each part of it is there because a line was passed without it:

- A `$` opens maths only as pandoc opens it. Not before a space, and not where the `$`
  that would close it follows a space or stands before a digit: `x$ \\gamma $y` and
  `$\\gamma$5` hold no maths.
- A backtick, `<`, `[` or `@` can hold a `$` that opens nothing: in code, in a tag, in a
  link's address, in a citation key. Past one, no maths is read here, and any backslash
  before a letter is reported, a doubled one too, with the sign named.
- A subscript or a superscript is read by pandoc on its own, with its escapes read once
  already. So maths cannot run past its end, and a doubled backslash in it is one
  backslash: `~a\\\\gamma~` loses its `\\gamma`. From a `~` or a `^` to the next space,
  any backslash before a letter is reported, and a `$` there ends the reading of maths.

So it reports TeX that pandoc keeps, in those places and in one more: a command pandoc
cannot read as TeX, a brace after it never closed, is printed as typed.
"""

from __future__ import annotations

import unicodedata
from typing import NamedTuple

_BACKSLASH = chr(92)
#: Signs that can hold a `$` which opens no maths.
_HOLDS_A_DOLLAR = "`<[@"
#: What opens a subscript and a superscript.
_SCRIPT = "~^"
_BLANK = " " + chr(9)
_DIGITS = "0123456789"
#: What pandoc takes for a space after the `$` that would open maths, with the spaces
#: Unicode calls separators: a no-break space among them, which is why `$\xa0x$` is no maths.
_SPACES = " " + "".join(chr(code) for code in (9, 10, 11, 12, 13, 0xA0))


class Tex(NamedTuple):
    """A TeX command the document would be printed without: the backslash and the letters
    after it, and the sign past which no maths was read, empty where there is none."""

    command: str
    after: str


def _is_space(character: str) -> bool:
    return character in _SPACES or unicodedata.category(character) == "Zs"


def _command_at(line: str, at: int) -> str:
    """The backslash at `at` and the letters after it."""
    end = at + 1
    while end < len(line) and line[end].isalpha():
        end += 1
    return line[at:end]


def _first_command(line: str, start: int, end: int) -> str | None:
    """The first backslash of `line[start:end]` that stands directly before a letter, with
    its letters. Whether the backslash before it doubles it is not read."""
    at = line.find(_BACKSLASH, start, end)
    while at != -1:
        if at + 1 < len(line) and line[at + 1].isalpha():
            return _command_at(line, at)
        at = line.find(_BACKSLASH, at + 1, end)
    return None


def _brace_pairs(line: str) -> dict[int, int]:
    """Where the `}` of each `{` stands, as pandoc pairs them in a `\\text{...}` group in
    maths: a brace directly after a backslash is not one, whatever stands before the
    backslash."""
    pairs: dict[int, int] = {}
    open_at: list[int] = []
    for at, character in enumerate(line):
        if at and line[at - 1] == _BACKSLASH:
            continue
        if character == "{":
            open_at.append(at)
        elif character == "}" and open_at:
            pairs[open_at.pop()] = at
    return pairs


class _Line:
    """One line, and the pairs of its braces, worked out once and only where maths holds a
    `\\text` group: from each group in turn, a line of them took time in their square."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._pairs: dict[int, int] | None = None

    def _group_end(self, at: int) -> int | None:
        """Past the `}` that closes the `{` at `at`, or None where none does."""
        if self._pairs is None:
            self._pairs = _brace_pairs(self.text)
        close = self._pairs.get(at)
        return None if close is None else close + 1

    def _display_end(self, at: int) -> int | None:
        """Past the `$$` that closes display maths opening at `at`: `$$`, one character at
        least, `$$`."""
        text = self.text
        if not text.startswith("$$", at) or text.startswith("$$", at + 2) or at + 2 >= len(text):
            return None
        close = text.find("$$", at + 3)
        return None if close < 0 else close + 2

    def _inline_end(self, at: int) -> int | None:
        """Past the `$` that closes inline maths opening at `at`, or None where pandoc
        reads none: nothing after the `$`, a space or a `$` directly after it, a space
        directly before the `$` that would close it, a digit directly after that one, or
        no such `$`. A backslash takes the character after it, a `$` among them, and
        `\\text{...}` takes its braces whole."""
        text, size = self.text, len(self.text)
        index = at + 1
        if index >= size or text[index] == "$" or _is_space(text[index]):
            return None
        while index < size:
            character = text[index]
            if character == "$":
                closed = index + 1
                return None if closed < size and text[closed] in _DIGITS else closed
            if character == _BACKSLASH:
                group = (
                    self._group_end(index + 5) if text.startswith("text{", index + 1) else None
                )
                if group is None and index + 1 >= size:
                    return None
                index = index + 2 if group is None else group
            elif character in _BLANK:
                while index < size and text[index] in _BLANK:
                    index += 1
                if index < size and text[index] == "$":
                    return None
            else:
                index += 1
        return None

    def maths_end(self, at: int) -> int | None:
        """Past the maths pandoc reads from the `$` at `at`, display maths first as pandoc
        tries it, or None where it reads none."""
        end = self._display_end(at)
        return self._inline_end(at) if end is None else end


def _script_end(line: str, at: int) -> int:
    """Where a subscript or a superscript opening at `at` ends at the latest: one holds no
    space but an escaped one, so by the first space with no backslash before it."""
    index = at + 1
    while index < len(line) and not (line[index] in _BLANK and line[index - 1] != _BACKSLASH):
        index += 1
    return index


def _past(line: str, start: int, sign: str) -> Tex | None:
    """Any command from `start` on, named with the sign past which no maths is read."""
    command = _first_command(line, start, len(line))
    return None if command is None else Tex(command, sign)


def tex_outside_maths(line: str) -> Tex | None:
    """The first TeX command of `line` that pandoc would leave out of a Word document, or
    None where it would leave none out. `line` is one line: a value of `paper.yaml` is
    folded into one before it is printed, and is read here as folded.

    See the module's account for what is reported that pandoc keeps."""
    reading = _Line(line)
    index, size, script_read_to = 0, len(line), 0
    while index < size:
        character = line[index]
        if character == _BACKSLASH:
            if index + 1 < size and line[index + 1].isalpha():
                return Tex(_command_at(line, index), "")
            index += 2
            continue
        if character == "$":
            end = reading.maths_end(index)
            index = index + 1 if end is None else end
            continue
        if character in _HOLDS_A_DOLLAR:
            return _past(line, index + 1, character)
        if character in _SCRIPT and index >= script_read_to:
            script_read_to = _script_end(line, index)
            command = _first_command(line, index + 1, script_read_to)
            if command is not None:
                return Tex(command, character)
            if line.find("$", index + 1, script_read_to) != -1:
                return _past(line, script_read_to, character)
        index += 1
    return None
