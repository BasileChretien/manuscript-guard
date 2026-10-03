"""TeX that stands outside maths in one line of Markdown, as pandoc reads the line.

Pandoc reads a backslash directly before a letter as the start of a TeX command, wherever
it stands, and the Word writer keeps TeX only as maths, between dollar signs. Anywhere else
the command is left out of the document with what it takes as TeX would: `IFN-\\gamma
release assays` is printed `IFN-release assays`, and `12 \\pm 3 months` is printed
without its `3`.

This is a model of that reading, for the text the build prints of `paper.yaml`, where
there is no pandoc to ask: `check` runs without one. It is meant never to pass a line that
pandoc drops TeX from, and `tests/test_tex.py` holds it to pandoc for that, on tables and on
random lines. Each part of it is there because a simpler reading passes such a line. The
first two came from asking pandoc case by case, the third from random lines, and the last
two from the review of the change:

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
- What one holds has its character references resolved as well before it is read:
  `^&bsol;gamma^` is `\\gamma` there, and is left out. So from a `~` or a `^` to the next
  space, and past a sign of the second kind, the references are resolved before a
  backslash is looked for. Outside those a reference is a character, and nothing is lost.
- A letter is what pandoc calls one, and pandoc may know a newer Unicode than the Python
  in use: 622 letters of Unicode 15.1 were none to Python 3.12. So a code point this
  Python has no name for is taken for a letter after a backslash.

So it reports TeX that pandoc keeps, in those places and in three more: a command pandoc
cannot read as TeX is printed as typed (a brace after it never closed, a `%` between its
braces, an `\\end` with no `\\begin`); so is one in a value pandoc reads as code, `>` and
a tab before it; and a backslash before a code point that is no letter in any Unicode yet
is an escape to pandoc.
"""

from __future__ import annotations

import html
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
    """A TeX command the document would be printed without, and what a finding needs to
    say of it truly.

    `command` is the backslash and the letters after it. `after` is the sign past which no
    maths was read, empty where there is none. `braces` says a `{` follows the command, so
    that dollar signs around the command alone would be no remedy. `unread` says why the
    `$` directly before the command opened no maths, where one stands there: a `digit`
    after the `$` that would close it, a `space` before that one, an `open` one that
    nothing closes, or one `paired` with an earlier `$` whose maths it closes. The command
    then stands between dollar signs, and "outside" them would be false."""

    command: str
    after: str = ""
    braces: bool = False
    unread: str = ""


def _is_space(character: str) -> bool:
    return character in _SPACES or unicodedata.category(character) == "Zs"


def _is_letter(character: str) -> bool:
    """A letter, or a code point this Python has no name for, which a newer Unicode may
    call one."""
    return character.isalpha() or unicodedata.category(character) == "Cn"


def _command_at(line: str, at: int) -> tuple[str, bool]:
    """The backslash at `at` with the letters after it, and whether a `{` follows them."""
    end = at + 1
    while end < len(line) and _is_letter(line[end]):
        end += 1
    return line[at:end], line.startswith("{", end)


def _first_command(stretch: str) -> tuple[str, bool] | None:
    """The first backslash of `stretch` that stands directly before a letter, with its
    letters, once the character references in it are resolved. Whether the backslash before
    it doubles it is not read.

    Python resolves a reference with no `;` after it where the name is an old one, which
    pandoc does not, so more is found here than pandoc reads, never less."""
    text = html.unescape(stretch) if "&" in stretch else stretch
    at = text.find(_BACKSLASH)
    while at != -1:
        if at + 1 < len(text) and _is_letter(text[at + 1]):
            return _command_at(text, at)
        at = text.find(_BACKSLASH, at + 1)
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

    def _inline(self, at: int) -> tuple[int | None, str]:
        """Past the `$` that closes inline maths opening at `at`; or None where pandoc
        reads none, with why, as `Tex.unread` names it. It reads none where nothing, a
        space or a `$` stands directly after the `$`, where a space stands directly before
        the `$` that would close it or a digit directly after that one, and where there is
        no such `$`. A backslash takes the character after it, a `$` among them, and
        `\\text{...}` takes its braces whole."""
        text, size = self.text, len(self.text)
        index = at + 1
        if index >= size:
            return None, "open"
        if text[index] == "$" or _is_space(text[index]):
            return None, ""
        while index < size:
            character = text[index]
            if character == "$":
                closed = index + 1
                if closed < size and text[closed] in _DIGITS:
                    return None, "digit"
                return closed, ""
            if character == _BACKSLASH:
                group = (
                    self._group_end(index + 5) if text.startswith("text{", index + 1) else None
                )
                if group is None and index + 1 >= size:
                    return None, "open"
                index = index + 2 if group is None else group
            elif character in _BLANK:
                while index < size and text[index] in _BLANK:
                    index += 1
                if index < size and text[index] == "$":
                    return None, "space"
            else:
                index += 1
        return None, "open"

    def maths(self, at: int) -> tuple[int | None, str]:
        """Past the maths pandoc reads from the `$` at `at`, display maths first as pandoc
        tries it; or None where it reads none, with why."""
        end = self._display_end(at)
        return self._inline(at) if end is None else (end, "")


def _script_end(line: str, at: int) -> int:
    """Where a subscript or a superscript opening at `at` ends at the latest: one holds no
    space but an escaped one, so by the first space with no backslash before it."""
    index = at + 1
    while index < len(line) and not (line[index] in _BLANK and line[index - 1] != _BACKSLASH):
        index += 1
    return index


def _past(stretch: str, sign: str) -> Tex | None:
    """Any command in `stretch`, named with the sign past which no maths is read."""
    found = _first_command(stretch)
    return None if found is None else Tex(found[0], sign, found[1])


def tex_outside_maths(line: str) -> Tex | None:
    """The first TeX command of `line` that pandoc would leave out of a Word document, or
    None where it would leave none out. `line` is one line: a value of `paper.yaml` is
    folded into one before it is printed, and is read here as folded.

    See the module's account for what is reported that pandoc keeps."""
    reading = _Line(line)
    index, size, script_read_to = 0, len(line), 0
    # Where the last maths ended, and the last `$` that opened none, with why: a command
    # directly after either stands between dollar signs, and the finding says so.
    closed, unopened, why = -1, -1, ""
    while index < size:
        character = line[index]
        if character == _BACKSLASH:
            if index + 1 < size and _is_letter(line[index + 1]):
                command, braces = _command_at(line, index)
                unread = "paired" if index == closed else why if index == unopened + 1 else ""
                return Tex(command, "", braces, unread)
            index += 2
            continue
        if character == "$":
            end, reason = reading.maths(index)
            if end is None:
                unopened, why = index, reason
                index += 1
            else:
                index = closed = end
            continue
        if character in _HOLDS_A_DOLLAR:
            return _past(line[index + 1 :], character)
        if character in _SCRIPT and index >= script_read_to:
            script_read_to = _script_end(line, index)
            held = line[index + 1 : script_read_to]
            found = _past(held, character)
            if found is not None:
                return found
            if "$" in held:
                return _past(line[script_read_to:], character)
        index += 1
    return None
