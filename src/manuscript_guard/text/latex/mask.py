"""A LaTeX file read as `masking.mask` reads a Markdown one: what is not prose blanked.

The contract is `mask`'s: the same length, every line break kept, and what is not prose
replaced by NUL, so that a finding names the `.tex` line. Two additions keep the length. A
sign TeX prints as a space is a space: `~`, `\\,`, `\\quad`, `\\\\`, and `&` in a table. An
escaped character is that character at the backslash's place, with a NUL after it, so that
`95\\%` reads as `95%`.

One pass, linear in the file, under TeX's default category codes. The preamble is blanked but
for `\\title` and `\\thanks`; maths keeps what it holds but its commands, braces and delimiters,
as Markdown's `mask` keeps `$...$`; a comment, a listing, a label, a key and a binding are
blanked; a command not in `commands.py` has its name blanked and its arguments read. What the
reader cannot read exactly is refused (`Refusal`), and past the first refusal the rest of the
file is read as prose, so that nothing the reader did not understand is hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.text.latex.commands import (
    COMMANDS,
    ENVIRONMENTS,
    MATHS,
    RAW,
    REFUSED,
    REFUSED_ENVIRONMENTS,
    SPACES,
    TABLES,
)

NUL = "\x00"
PROSE, BLANK, MATHS_READ, PREAMBLE = "prose", "blank", "maths", "preamble"
#: Commands whose prose argument LaTeX prints though it stands in the preamble: the title, its
#: note, and a definition's default argument, printed at each use that omits it (round 1 of
#: #380: `\\newcommand{\\ci}[1][95]{...}` hid the 95).
PRINTED_IN_PREAMBLE = frozenset(
    {"title", "thanks", "newcommand", "renewcommand", "providecommand", "newenvironment",
     "renewenvironment"}
)  # fmt: skip
#: Names that open no conditional though they start with `if`: a symbol and a command whose
#: branches are its arguments, both read.
NOT_CONDITIONALS = frozenset({"iff", "ifthenelse"})
_LETTERS = re.compile(r"[A-Za-z]+")
_LETTERS_AT = re.compile(r"[A-Za-z@]+")
_TEXT = re.compile(r"[^\\%{}\[\]$&~#`'\n]+")
_ENVIRONMENT_NAME = re.compile(r"[ \t]*\n?[ \t]*\{([^{}\n]*)\}")
_BRACED_NAME = re.compile(r"\{\s*\\([A-Za-z@]+|[^A-Za-z@\s])\s*\}")
_PARAMETERS = re.compile(r"(?:#[1-9])*")
#: An input encoding set by a package's option or by `\\inputencoding`, a few hundred
#: characters at most, so that an option never closed is not read to the file's end.
_INPUTENC = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*\[([^\]]{0,300})\]\s*\{inputenc\}"
    r"|\\inputencoding\s*\{([^}]{0,40})\}"
)
_CONDITIONALS = re.compile(r"\\(?:if[A-Za-z]*|fi|else)(?![A-Za-z])")
_DOCUMENT = re.compile(r"\\begin\s*\{document\}")


@dataclass(frozen=True)
class Refusal:
    """Why the reader stopped reading a file as LaTeX, and where."""

    code: str
    offset: int
    message: str


@dataclass(frozen=True)
class Reading:
    masked: str
    refusals: tuple[Refusal, ...]


@dataclass
class _Frame:
    kind: str  # "group", "arg", "opt", "env" or "maths"
    role: str
    start: int
    closer: str = ""
    rest: tuple[str, ...] = ()
    command: str = ""
    definition: bool = False
    table: bool = False


def mask(text: str, *, body: bool | None = None) -> str:
    """`text` with what is not prose replaced by NUL. `body` says whether the file opens in
    the document's body, as a file input from it does; None reads it from the file."""
    return read(text, body=body).masked


def read(text: str, *, body: bool | None = None) -> Reading:
    """The masked text and the first refusal. With `body` None, a file with a
    `\\begin{document}` opens in the preamble and one without in the body; a file read to its
    end or to a refusal without reaching a `\\begin{document}`, whose only one is in a comment
    say, is read again as body, so that none of it is hidden as preamble (round 1 of #380:
    one refused before it was not)."""
    opens_in_body = _DOCUMENT.search(text) is None if body is None else body
    reader = _Reader(text, opens_in_body)
    reading = reader.run()
    if body is None and not reader.body:
        return _Reader(text, True).run()
    return reading


def _verb_delimiter(text: str, at: int) -> str:
    """The character that opens and closes a `\\verb`: any but a letter, a space or a star."""
    character = text[at : at + 1]
    return "" if not character or character.isalpha() or character.isspace() else character


def _opens_comment(text: str, start: int, end: int) -> bool:
    """Whether an unescaped `%` stands between `start` and `end`, on one line."""
    at = text.find("%", start, end)
    while at >= 0:
        before = at - 1
        while before >= 0 and text[before] == "\\":
            before -= 1
        if (at - 1 - before) % 2 == 0:
            return True
        at = text.find("%", at + 1, end)
    return False


def _comment_end(text: str, at: int) -> int:
    """Where a comment opened at `at` ends: before its line's break."""
    end = text.find("\n", at)
    return len(text) if end < 0 else end


def _maths_keeps(character: str) -> bool:
    """Whether maths keeps a character of its text: all of it, as Markdown's `mask` keeps
    `$...$`; its commands, braces and delimiters are blanked apart."""
    return True


def _note_role(kind: str) -> str:
    """How a citation's note or another prose argument is read."""
    return PROSE if kind == "p" else BLANK


class _Reader:
    def __init__(self, text: str, body: bool) -> None:
        self.text = text
        self.n = len(text)
        self.out = list(text)
        self.pos = 0
        self.body = body
        self.stack: list[_Frame] = []
        self.pending: tuple[str, ...] = ()
        self.command = ""
        self.refused: Refusal | None = None
        self.letters = _LETTERS
        self.definitions = 0
        self.tables: list[bool] = []

    # -- running -----------------------------------------------------------------------
    def run(self) -> Reading:
        while self.pos < self.n and self.refused is None:
            if self.pending and self._argument():
                continue
            self._step()
        if self.refused is None and self.stack:
            first = self.stack[0]
            self._refuse("tex-unbalanced", first.start, f"{_opened(first)} is not closed")
        masked = "".join(self.out)
        if self.refused is None:
            return Reading(masked, ())
        at = self.refused.offset
        return Reading(masked[:at] + self.text[at:], (self.refused,))

    def _refuse(self, code: str, at: int, message: str) -> None:
        if self.refused is None:
            self.refused = Refusal(code, at, message)

    def _role(self) -> str:
        if self.stack:
            return self.stack[-1].role
        return PROSE if self.body else PREAMBLE

    def _reads(self) -> bool:
        return self._role() in (PROSE, MATHS_READ)

    def _blank(self, start: int, end: int) -> None:
        for index in range(start, min(end, self.n)):
            if self.out[index] not in "\n\r":
                self.out[index] = NUL

    def _keep_or_blank(self, start: int, end: int) -> None:
        role = self._role()
        if role == MATHS_READ:
            for index in range(start, min(end, self.n)):
                if not _maths_keeps(self.text[index]) and self.out[index] not in "\n\r":
                    self.out[index] = NUL
        elif role != PROSE:
            self._blank(start, end)

    # -- arguments -----------------------------------------------------------------------
    def _after_space(self, at: int) -> int:
        seen_break = False
        while at < self.n and self.text[at] in " \t\r\n":
            if self.text[at] == "\n":
                if seen_break:
                    return at
                seen_break = True
            at += 1
        return at

    def _argument(self) -> bool:
        """Take the next argument the last command expects where it stands. False where
        there is none, and the text is read on as it comes. `\\\\` takes its star and its
        length only where they follow it at once, as amsmath's does: a `[0.5, 1.2]` opening
        the next row prints (round 1 of #380)."""
        at = self.pos if self.command == "\\" else self._after_space(self.pos)
        here = self.text[at : at + 1]
        while self.pending:
            spec = self.pending[0]
            if spec == "*":
                self.pending = self.pending[1:]
                if here == "*":
                    self._blank(at, at + 1)
                    self.pos = at + 1
                    return True
                continue
            if spec[0] == "[":
                if here == "[":
                    self._open("opt", spec[1], at, "]")
                    return True
                self.pending = self.pending[1:]
                continue
            if spec[0] == "(":
                # A trim such as `(lr)` is a few letters: looked for that far, on its line.
                end = self.text.find(")", at, at + 32) if here == "(" else -1
                if end >= 0 and "\n" not in self.text[at:end]:
                    self._blank(at, end + 1)
                    self.pos = end + 1
                    self.pending = self.pending[1:]
                    return True
                self.pending = self.pending[1:]
                continue
            return self._mandatory(spec[1], at, here)
        return False

    def _mandatory(self, kind: str, at: int, here: str) -> bool:
        if kind == "c" and here in ("\\", "{"):
            named = _BRACED_NAME.match(self.text, at) if here == "{" else None
            end = named.end() if named else self._name_end(at) if here == "\\" else -1
            if end < 0:
                self._open("arg", "b", at, "}")
                return True
            self._defines(named.group(1) if named else self.text[at + 1 : end], at)
            self._blank(at, end)
            self.pos = end
            self.pending = self.pending[1:]
            return True
        if here != "{":
            self.pending = ()
            return False
        if kind == "r":
            end = self._group_end(at)
            if end < 0:
                said = f"the argument of \\{self.command} is not closed"
                self._refuse("tex-unbalanced", at, said)
                return True
            self._blank(at, end)
            self.pos = end
            self.pending = self.pending[1:]
            return True
        self._open("arg", kind, at, "}")
        return True

    def _open(self, kind: str, spec: str, at: int, closer: str) -> None:
        role = self._role()
        if role == BLANK or spec in "bc":
            chosen = BLANK
        elif spec == "d":
            chosen = PROSE
        elif role == PREAMBLE:
            chosen = PROSE if self.command in PRINTED_IN_PREAMBLE else PREAMBLE
        else:
            chosen = _note_role(spec)
        frame = _Frame(kind, chosen, at, closer, self.pending[1:], self.command, spec == "d")
        self.definitions += frame.definition
        self.stack.append(frame)
        self._blank(at, at + 1)
        self.pos = at + 1
        self.pending = ()

    def _group_end(self, at: int) -> int:
        """Where a brace group opened at `at` ends, read as characters: `%` and `#` are no
        signs in a URL."""
        depth = 0
        for index in range(at, self.n):
            character = self.text[index]
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return index + 1
        return -1

    # -- one token -------------------------------------------------------------------------
    def _step(self) -> None:
        at, character = self.pos, self.text[self.pos]
        if character == "\\":
            self._control(at)
        elif character == "%":
            end = _comment_end(self.text, at)
            self._blank(at, end)
            self.pos = end
        elif character == "{":
            self.stack.append(_Frame("group", self._role(), at))
            self._blank(at, at + 1)
            self.pos = at + 1
        elif character == "}":
            self._close_group(at)
        elif character == "]" and self.stack and self.stack[-1].kind == "opt":
            self._close(at, 1)
        elif character == "$":
            self._dollar(at)
        elif character in "&~":
            self._space(at, 1, table_only=character == "&")
        elif character == "#" and self.definitions and self.text[at + 1 : at + 2].isdigit():
            self._blank(at, at + 2)
            self.pos = at + 2
        elif character in "`'" and self.text[at + 1 : at + 2] == character:
            self._quote(at, "\N{LEFT DOUBLE QUOTATION MARK}" if character == "`"
                        else "\N{RIGHT DOUBLE QUOTATION MARK}")  # fmt: skip
        else:
            run = _TEXT.match(self.text, at)
            end = run.end() if run else at + 1
            self._keep_or_blank(at, end)
            self.pos = end

    def _space(self, at: int, width: int, *, table_only: bool = False) -> None:
        if self._reads() and (not table_only or self._in_table()):
            self.out[at] = " "
            self._blank(at + 1, at + width)
        else:
            self._keep_or_blank(at, at + width)
        self.pos = at + width

    def _quote(self, at: int, mark: str) -> None:
        if self._role() == PROSE:
            self.out[at], self.out[at + 1] = mark, NUL
        else:
            self._keep_or_blank(at, at + 2)
        self.pos = at + 2

    def _in_table(self) -> bool:
        """Whether the innermost environment is a table: kept apart from the stack, so that a
        file of braces and `&` is not read again for each `&` (round 1 of #380)."""
        return bool(self.tables) and self.tables[-1]

    def _close_group(self, at: int) -> None:
        top = self.stack[-1] if self.stack else None
        if top is None or top.kind not in ("group", "arg"):
            self._refuse("tex-unbalanced", at, "this brace closes nothing that is open")
            return
        self._close(at, 1)

    def _close(self, at: int, width: int) -> None:
        frame = self.stack.pop()
        self.definitions -= frame.definition
        self._blank(at, at + width)
        self.pos = at + width
        if frame.kind in ("arg", "opt"):
            self.pending, self.command = frame.rest, frame.command

    def _dollar(self, at: int) -> None:
        top = self.stack[-1] if self.stack else None
        # The maths that is open closes first: `$x$$y$` is two formulas (round 1 of #380).
        if top is not None and top.kind == "maths" and self.text.startswith(top.closer, at):
            self._close(at, len(top.closer))
            return
        closer = "$$" if self.text.startswith("$$", at) else "$"
        role = self._role()
        if role in (BLANK, PREAMBLE):
            self._blank(at, at + len(closer))
            self.pos = at + len(closer)
        elif role == MATHS_READ:
            self._refuse("tex-unbalanced", at, "maths is opened inside maths")
        else:
            self.stack.append(_Frame("maths", MATHS_READ, at, closer))
            self._blank(at, at + len(closer))
            self.pos = at + len(closer)

    # -- commands --------------------------------------------------------------------------
    def _name_end(self, at: int) -> int:
        if at + 1 >= self.n:
            return at + 1
        word = self.letters.match(self.text, at + 1)
        return word.end() if word else at + 2

    def _control(self, at: int) -> None:
        end = self._name_end(at)
        name = self.text[at + 1 : end]
        if not name:
            self._blank(at, end)
            self.pos = end
        elif self.letters.fullmatch(name):
            self._blank(at, end)
            self.pos = end
            self._word(name, at, end)
        else:
            self._symbol(name, at)

    def _symbol(self, symbol: str, at: int) -> None:
        reads = self._reads()
        self.pos = at + 2
        if symbol in "%$&#_{}":
            if reads:
                self.out[at], self.out[at + 1] = symbol, NUL
            else:
                self._blank(at, at + 2)
        elif symbol == "\\":
            self._space(at, 2)
            self.command, self.pending = "\\", COMMANDS["\\"]
        elif symbol in " ,;:>\n":
            self._space(at, 2 if symbol != "\n" else 1)
            self.pos = at + 2
        elif symbol in "([" and self._role() == PROSE:
            self.stack.append(_Frame("maths", MATHS_READ, at, "\\" + {"(": ")", "[": "]"}[symbol]))
            self._blank(at, at + 2)
        elif symbol in ")]" and self.stack and self.stack[-1].closer == "\\" + symbol:
            self._close(at, 2)
        elif symbol in ")]" and self._reads():
            self._refuse("tex-unbalanced", at, f"\\{symbol} closes no maths that is open")
        else:
            self._blank(at, at + 2)

    def _word(self, name: str, at: int, end: int) -> None:
        if name in REFUSED:
            self._refuse("tex-refused", at, f"\\{name} is not read: {REFUSED[name]}")
        elif name in ("makeatletter", "makeatother"):
            if name == "makeatletter" and self.body:
                self._refuse("tex-refused", at, "\\makeatletter in the body changes how "
                             "characters are read")  # fmt: skip
            self.letters = _LETTERS_AT if name == "makeatletter" else _LETTERS
        elif name == "iffalse":
            self._skip_false(at)
        elif name.startswith("if") and name not in COMMANDS and name not in NOT_CONDITIONALS:
            if self.body:
                said = "a conditional in the body prints one branch, and which is not read"
                self._refuse("tex-refused", at, f"\\{name} is not read: {said}")
        elif name == "verb":
            self._verb(at, end)
        elif name in ("begin", "end"):
            self._environment(name, at, end)
        elif name in ("def", "gdef", "edef", "xdef", "let"):
            self._definition(name, at, end)
        elif name in SPACES:
            if self._reads():
                self.out[at] = " "
        elif name in ("usepackage", "RequirePackage", "inputencoding"):
            self._encoding(at)
            if name in COMMANDS:
                self.command, self.pending = name, COMMANDS[name]
        elif name in COMMANDS:
            self.command, self.pending = name, COMMANDS[name]

    def _encoding(self, at: int) -> None:
        """Refuse an input encoding other than UTF-8, set by a package's option or by
        `\\inputencoding` (round 1 of #380: only `\\usepackage` was read)."""
        found = _INPUTENC.match(self.text, at)
        named = (found.group(1) or found.group(2) or "") if found else ""
        if found and not {o.strip() for o in named.split(",")} & {"utf8", "utf8x"}:
            self._refuse("tex-refused", at, "the input encoding is not UTF-8, in which the file "
                         "is read")  # fmt: skip

    def _skip_false(self, at: int) -> None:
        """Blank an `\\iffalse` block to its `\\fi`, or to its `\\else`, whose branch TeX
        prints and the reader reads (round 1 of #380). A conditional in a comment counts for
        nothing, and neither do `\\iff` and `\\ifthenelse`."""
        depth, scanned, comment = 1, self.pos, False
        for match in _CONDITIONALS.finditer(self.text, self.pos):
            start = match.start()
            # Read forward only, from the last conditional or the last line break, so that a
            # long line of conditionals is not read again for each.
            newline = self.text.rfind("\n", scanned, start)
            if newline >= 0:
                scanned, comment = newline + 1, False
            if not comment:
                comment = _opens_comment(self.text, scanned, start)
                scanned = start
            word = match.group(0)[1:]
            if comment or word in NOT_CONDITIONALS:
                continue
            if word == "else":
                if depth == 1:
                    self._blank(at, match.end())
                    self.pos = match.end()
                    return
                continue
            depth += -1 if word == "fi" else 1
            if depth == 0:
                self._blank(at, match.end())
                self.pos = match.end()
                return
        self._refuse("tex-unbalanced", at, "\\iffalse is not closed by \\fi")

    def _verb(self, at: int, end: int) -> None:
        start = end + (self.text[end : end + 1] == "*")
        delimiter = _verb_delimiter(self.text, start)
        close = self.text.find(delimiter, start + 1) if delimiter else -1
        if close < 0 or close > _comment_end(self.text, start + 1):
            self._refuse("tex-unbalanced", at, "\\verb is not closed on its line")
            return
        self._blank(at, start + 1)
        self._keep_or_blank(start + 1, close)
        self._blank(close, close + 1)
        self.pos = close + 1

    def _definition(self, name: str, at: int, end: int) -> None:
        start = self._after_space(end)
        if self.text[start : start + 1] != "\\":
            return
        name_end = self._name_end(start)
        self._defines(self.text[start + 1 : name_end], start)
        self._blank(start, name_end)
        self.pos = name_end
        if name == "let":
            return
        parameters = _PARAMETERS.match(self.text, name_end).end()
        if self.text[parameters : parameters + 1] != "{":
            self._refuse("tex-refused", at, f"\\{name} with delimited parameters is not read")
            return
        self._blank(name_end, parameters)
        self.command = name
        self._open("arg", "d", parameters, "}")

    def _defines(self, name: str, at: int) -> None:
        if name in COMMANDS or name in ("begin", "end", "verb", "def"):
            self._refuse("tex-refused", at, f"\\{name} is defined again, and the reader reads "
                         "it as LaTeX defines it")  # fmt: skip

    def _environment(self, which: str, at: int, end: int) -> None:
        named = _ENVIRONMENT_NAME.match(self.text, end)
        if not named:
            return
        name = named.group(1).strip()
        self._blank(at, named.end())
        self.pos = named.end()
        if self.definitions:
            # In a definition's body an environment is text to be expanded at each use, not
            # one that opens here (round 1 of #380: `\newenvironment{tight}{\begin{itemize}}
            # {\end{itemize}}` was refused).
            return
        if which == "end":
            self._end(name, at)
        elif name in REFUSED_ENVIRONMENTS:
            self._refuse("tex-refused", at, f"{name} is not read: {REFUSED_ENVIRONMENTS[name]}")
        elif name == "document":
            self.body = True
        elif name in RAW:
            ending = re.compile(r"\\end\s*\{" + re.escape(name) + r"\}")
            closing = ending.search(self.text, self.pos)
            if closing is None:
                self._refuse("tex-unbalanced", at, f"\\begin{{{name}}} is not closed")
                return
            self._blank(at, closing.end())
            self.pos = closing.end()
        else:
            role = self._role()
            maths = name in MATHS and role in (PROSE, MATHS_READ)
            self.stack.append(_Frame("env", MATHS_READ if maths else role, at, name,
                                     table=name in TABLES))  # fmt: skip
            self.tables.append(name in TABLES)
            self.command, self.pending = "begin", ENVIRONMENTS.get(name, ())

    def _end(self, name: str, at: int) -> None:
        if name == "document":
            if self.stack:
                first = self.stack[0]
                self._refuse("tex-unbalanced", first.start, f"{_opened(first)} is not closed")
                return
            self._blank(at, self.n)
            self.pos = self.n
            return
        top = self.stack[-1] if self.stack else None
        if top is None or top.kind != "env" or top.closer != name:
            self._refuse("tex-unbalanced", at, f"\\end{{{name}}} closes no \\begin{{{name}}}")
            return
        self.stack.pop()
        self.tables.pop()
        self.pending = ()


def _opened(frame: _Frame) -> str:
    if frame.kind == "env":
        return f"\\begin{{{frame.closer}}}"
    if frame.kind == "maths":
        return f"maths opened with {frame.closer}"
    if frame.kind in ("arg", "opt"):
        return f"an argument of \\{frame.command}"
    return "a brace"
