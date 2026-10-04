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
- What one holds has its character references resolved as well before it is read, once
  more for each script around it, and a carriage return is left out as it is read:
  `^&bsol;gamma^` is `\\gamma` there, so is `^~&amp;bsol;gamma~^`, and
  `^&bsol;&#13;gamma^` too. Resolving them here as pandoc does was tried, and passed the
  last two. So nothing is resolved: from a `~` or a `^` to the next space, a character
  reference is itself reported, whatever it stands for. None exists without a typed `&`
  and a `;` after it. Outside a script a reference is a character, and nothing is lost.
- A letter is what pandoc calls one, and pandoc may know a newer Unicode than the Python
  in use: 622 letters of Unicode 15.1 were none to Python 3.12. So a code point this
  Python has no name for is taken for a letter after a backslash.

So it reports what pandoc keeps, in those places and in four more: a command pandoc
cannot read as TeX is printed as typed (a brace after it never closed, a `%` between its
braces, an `\\end` with no `\\begin`); so is one in a value pandoc reads as code, `>` and
a tab before it; a backslash before a code point that is no letter in any Unicode yet is
an escape to pandoc; and so is one before a letter that Python's Unicode has and pandoc's
has not yet.

The end of the module is for TeX that pandoc has read as TeX already, in the manuscript's
text, where the build asks it: which of that is nothing but layout commands, and which
is a macro's definition (`layout_only`, `only_definitions`).
"""

from __future__ import annotations

import re
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
#: As much of a reference as a finding shows.
_SHOWN = 16


class Tex(NamedTuple):
    """What the document would be printed without, and what a finding needs to say of it
    truly.

    `command` is the backslash and the letters after it. `after` is the sign past which no
    maths was read, empty where there is none. `braces` says a `{` follows the command, so
    that dollar signs around the command alone would be no remedy.

    `unread` says why a `$` before the command opened no maths, where one did not: a
    `digit` after the next `$`, a `space` before it, an `open` one that no `$` follows, or
    one `paired` with an earlier `$` whose maths it closes. The command then stands
    between dollar signs, or after one, and "outside dollar signs" would be false.

    `reference` says `command` is no command but a character reference in a subscript or
    a superscript, whose sign is `after`."""

    command: str
    after: str = ""
    braces: bool = False
    unread: str = ""
    reference: bool = False


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
    letters. Whether the backslash before it doubles it is not read."""
    at = stretch.find(_BACKSLASH)
    while at != -1:
        if at + 1 < len(stretch) and _is_letter(stretch[at + 1]):
            return _command_at(stretch, at)
        at = stretch.find(_BACKSLASH, at + 1)
    return None


def _reference(stretch: str) -> str | None:
    """What may be a character reference in `stretch`: from its first `&` to the first `;`
    after it, or None where there is not both. It is not read further: an escape or
    another reference can stand inside one that pandoc resolves a script later."""
    at = stretch.find("&")
    end = -1 if at == -1 else stretch.find(";", at + 1)
    return None if end == -1 else stretch[at : end + 1][:_SHOWN]


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

    def _inline(self, at: int) -> tuple[int | None, str, int]:
        """Past the `$` that closes inline maths opening at `at`. Or None where pandoc
        reads none, with why, as `Tex.unread` names it, and how far the maths would have
        run: to the next `$`, or to the end of the line where there is none.

        It reads none where nothing, a space or a `$` stands directly after the `$`, where
        a space stands directly before the next `$` or a digit directly after it, and
        where there is no next `$`. A backslash takes the character after it, a `$` among
        them, and `\\text{...}` takes its braces whole."""
        text, size = self.text, len(self.text)
        index = at + 1
        if index >= size:
            return None, "open", size
        if text[index] == "$" or _is_space(text[index]):
            return None, "", at
        while index < size:
            character = text[index]
            if character == "$":
                if index + 1 < size and text[index + 1] in _DIGITS:
                    return None, "digit", index
                return index + 1, "", index
            if character == _BACKSLASH:
                group = (
                    self._group_end(index + 5) if text.startswith("text{", index + 1) else None
                )
                if group is None and index + 1 >= size:
                    return None, "open", size
                index = index + 2 if group is None else group
            elif character in _BLANK:
                while index < size and text[index] in _BLANK:
                    index += 1
                if index < size and text[index] == "$":
                    return None, "space", index
            else:
                index += 1
        return None, "open", size

    def maths(self, at: int) -> tuple[int | None, str, int]:
        """Past the maths pandoc reads from the `$` at `at`, display maths first as pandoc
        tries it; or None where it reads none, with why and how far, as `_inline` gives
        them."""
        end = self._display_end(at)
        return self._inline(at) if end is None else (end, "", end)


def _script_end(line: str, at: int) -> int:
    """Where a subscript or a superscript opening at `at` ends at the latest: one holds no
    space but an escaped one, so by the first space with no backslash before it."""
    index = at + 1
    while index < len(line) and not (line[index] in _BLANK and line[index - 1] != _BACKSLASH):
        index += 1
    return index


def _in_scripts(stretch: str) -> Tex | None:
    """The first character reference that a subscript or a superscript in `stretch` can
    hold, each read from its sign to the next space, and only once where they nest."""
    read_to = 0
    for at, character in enumerate(stretch):
        if character not in _SCRIPT or at < read_to:
            continue
        read_to = _script_end(stretch, at)
        reference = _reference(stretch[at + 1 : read_to])
        if reference is not None:
            return Tex(reference, character, reference=True)
    return None


def _past(stretch: str, sign: str) -> Tex | None:
    """Any command in `stretch`, named with the sign past which no maths is read; or a
    reference in a subscript or a superscript there."""
    found = _first_command(stretch)
    return _in_scripts(stretch) if found is None else Tex(found[0], sign, found[1])


def tex_outside_maths(line: str) -> Tex | None:
    """The first TeX command of `line` that pandoc would leave out of a Word document, or
    None where it would leave none out. `line` is one line: a value of `paper.yaml` is
    folded into one before it is printed, and is read here as folded.

    See the module's account for what is reported that pandoc keeps."""
    reading = _Line(line)
    index, size, script_read_to = 0, len(line), 0
    # Where the last maths ended; and the last `$` that opened none, with why and how far
    # its maths would have run. A command directly after the first, or between the last
    # two, stands between dollar signs or after one, and the finding says so.
    closed, unopened, why, reach = -1, -1, "", -1
    while index < size:
        character = line[index]
        if character == _BACKSLASH:
            if index + 1 < size and _is_letter(line[index + 1]):
                command, braces = _command_at(line, index)
                unread = "paired" if index == closed else why if unopened < index < reach else ""
                return Tex(command, "", braces, unread)
            index += 2
            continue
        if character == "$":
            end, reason, would_reach = reading.maths(index)
            if end is None:
                unopened, why, reach = index, reason, would_reach
                index += 1
            else:
                index = closed = end
            continue
        if character in _HOLDS_A_DOLLAR:
            return _past(line[index + 1 :], character)
        if character in _SCRIPT and index >= script_read_to:
            script_read_to = _script_end(line, index)
            held = line[index + 1 : script_read_to]
            command = _first_command(held)
            if command is not None:
                return Tex(command[0], character, command[1])
            reference = _reference(held)
            if reference is not None:
                return Tex(reference, character, reference=True)
            if "$" in held:
                return _past(line[script_read_to:], character)
        index += 1
    return None


#: Layout commands. Each prints no word in LaTeX either and does nothing in a Word document,
#: so TeX that is nothing but these loses nothing: the build warns of it and makes the
#: document. This is a list and no more than a list: a command that is not on it is refused
#: with the rest, `\centering` for one. The first kind takes nothing after it, the second a
#: number from 0 to 4 in brackets, the third a length in braces, which is never printed.
_BREAKS = (
    "newpage",
    "clearpage",
    "cleardoublepage",
    "bigskip",
    "medskip",
    "smallskip",
    "vfill",
    "hfill",
    "noindent",
)
_NUMBERED_BREAKS = ("pagebreak", "nopagebreak", "linebreak", "nolinebreak")
_LENGTHS = ("vspace", "hspace")
# A length: a number with a unit, a command that is a length, or a number of times one,
# and after it what it may stretch by and shrink by, once each. Three versions read more
# than that. Whatever stood between the braces was taken for a length, and
# `We enrolled \hspace{412} patients` was warned of and printed without its number. Then a
# number before any command was, `\hspace{412\patients}`, and a unit alone. And the number
# was digits, an optional point, digits, so that without a point the two runs shared the
# same digits: one that no unit follows was read every way, and twice the digits took four
# times as long. A sign stands before the number or, where there is none, before the
# command: read only before a digit, `\vspace{-\baselineskip}`, which is how a negative
# space is written, was refused. This is a list too: `1,5cm`, `1EM`, `1 true cm` and
# `\dimexpr` are lengths to LaTeX and none here, and the command they stand in is then
# refused with the rest.
_SIGN = r"[-+]?"
_UNSIGNED = r"(?:\d+(?:\.\d*)?|\.\d+)"
_NUMBER = rf"{_SIGN}{_UNSIGNED}"
_UNIT = r"(?:pt|pc|in|bp|cm|mm|dd|cc|sp|em|ex|mu)"
_LENGTH_COMMANDS = (
    "baselineskip",
    "bigskipamount",
    "columnwidth",
    "fill",
    "linewidth",
    "medskipamount",
    "paperheight",
    "paperwidth",
    "parindent",
    "parskip",
    "smallskipamount",
    "textheight",
    "textwidth",
)
_LENGTH = (
    rf"(?:{_NUMBER}[ ]*{_UNIT}"
    rf"|{_SIGN}(?:{_UNSIGNED}[ ]*)?\\(?:{'|'.join(_LENGTH_COMMANDS)}))"
)
_STRETCH = rf"(?:{_LENGTH}|{_NUMBER}[ ]*fil{{1,3}})"
_GLUE = rf"[ ]*{_LENGTH}(?:[ ]+plus[ ]+{_STRETCH})?(?:[ ]+minus[ ]+{_STRETCH})?[ ]*"
# One layout command. Nothing may follow one of the first two kinds but space or another
# piece: pandoc reads `\newpage[412]` and `\newpage{412 patients}` as one piece of TeX,
# and folds digits that open the next line into a command that takes no braces, `\newpage`
# over `412`. So what is read is read to its end, and a piece that holds anything else is
# no layout.
_LAYOUT = re.compile(
    r"\\(?:"
    rf"(?:{'|'.join(_BREAKS)})"
    rf"|(?:{'|'.join(_NUMBERED_BREAKS)})(?:\[[0-4]\])?"
    rf"|(?:{'|'.join(_LENGTHS)})\*?\{{{_GLUE}\}}"
    r")(?![A-Za-z@])"
)
# A macro's definition. It is raw TeX to pandoc and prints nothing, and pandoc applies it in
# maths. Marked `{=latex}` it is no longer applied, and `$\RR$` stays `\RR`, which Word cannot
# show: so a definition passes, since refusing it would leave no way to write one.
_DEFINER = re.compile(r"\\(?:(?:re)?newcommand|providecommand|DeclareMathOperator)\*?\s*")
_DEFINED = re.compile(r"\{\\[A-Za-z@]+\}|\\[A-Za-z@]+")
_ARGUMENTS = re.compile(r"(?:\s*\[[^\]\n]*\]){0,2}\s*")
_DEF = re.compile(r"\\def\s*\\[A-Za-z@]+[^{}\n]*")
_WHITE = re.compile(r"\s*")


def _braces_end(text: str, at: int) -> int | None:
    """Past the `}` that closes the `{` at `at`, a brace after a backslash being no brace;
    None where `at` holds no `{` or it is never closed."""
    if at >= len(text) or text[at] != "{":
        return None
    depth, index = 0, at
    while index < len(text):
        character = text[index]
        if character == "\\":
            index += 2
            continue
        depth += (character == "{") - (character == "}")
        index += 1
        if depth == 0:
            return index
    return None


def _definition_end(raw: str, at: int) -> int | None:
    """Past the macro definition that opens at `at`, or None where none does."""
    opened = _DEFINER.match(raw, at)
    if opened is not None:
        name = _DEFINED.match(raw, opened.end())
        if name is None:
            return None
        return _braces_end(raw, _ARGUMENTS.match(raw, name.end()).end())
    opened = _DEF.match(raw, at)
    return None if opened is None else _braces_end(raw, opened.end())


def only_definitions(raw: str) -> bool:
    """Is `raw` macro definitions from end to end, and nothing else?"""
    at = _WHITE.match(raw).end()
    count = 0
    while at < len(raw):
        end = _definition_end(raw, at)
        if end is None:
            return False
        at = _WHITE.match(raw, end).end()
        count += 1
    return count > 0


def _pieces(raw: str) -> list[tuple[str, str]] | None:
    """What `raw` is made of, read from end to end: each piece with its kind, "definition"
    or "layout". None where it holds anything that is neither."""
    at = _WHITE.match(raw).end()
    pieces = []
    while at < len(raw):
        end = _definition_end(raw, at)
        kind = "definition"
        if end is None:
            command = _LAYOUT.match(raw, at)
            if command is None:
                return None
            end, kind = command.end(), "layout"
        pieces.append((kind, raw[at:end]))
        at = _WHITE.match(raw, end).end()
    return pieces


def layout_only(raw: str) -> bool:
    """Is `raw` nothing but layout commands from the list above?"""
    pieces = _pieces(raw)
    return bool(pieces) and all(kind == "layout" for kind, _text in pieces)


def tex_kind(raw: str) -> str:
    """What a piece of TeX is to the build: `definitions` where it is macro definitions
    from end to end, `layout` where it is those and layout commands or layout commands
    alone, and empty where it holds anything else, which the document would lose.

    Pandoc reads a definition directly over a page break as one piece. Each is let pass on
    its own, and the two together were refused."""
    pieces = _pieces(raw)
    if not pieces:
        return ""
    return "layout" if any(kind == "layout" for kind, _text in pieces) else "definitions"


def layout_part(raw: str) -> str:
    """The layout commands of `raw` where `tex_kind` calls it `layout`, and empty otherwise:
    the piece as it is written where it holds nothing else, and its layout commands on one
    line where definitions stand among them. It is what a warning names: a definition in
    the same piece does something, and named with the page break under it, it was said to
    do nothing in a Word document."""
    pieces = _pieces(raw)
    if not pieces:
        return ""
    layout = [text for kind, text in pieces if kind == "layout"]
    return raw.strip() if len(layout) == len(pieces) else " ".join(layout)


#: What opens a macro's definition in any form, the forms that are not read among them.
_DEFINES = re.compile(
    r"\\(?:let|[gex]?def|global|long|DeclareRobustCommand|(?:re)?newcommand|"
    r"providecommand|DeclareMathOperator)(?![A-Za-z@])"
)


def unread_definition(raw: str) -> bool:
    """Does `raw` open as a macro's definition in a form that is not read here?

    Pandoc applies `\\let`, `\\gdef` and a `\\newcommand` with no braces round its body as
    it applies the forms `only_definitions` reads, and the build refuses them. What it says
    of one is to write it as a `\\newcommand` with its braces, and that is said only of a
    piece whose opening definition is itself not read: a read one with something lost
    beside it was told so too, and is written so already. An environment is not said it:
    no `\\newcommand` can be one."""
    at = _WHITE.match(raw).end()
    return _DEFINES.match(raw, at) is not None and _definition_end(raw, at) is None
