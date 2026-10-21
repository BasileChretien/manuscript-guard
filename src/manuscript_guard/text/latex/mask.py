"""A LaTeX file read as `masking.mask` reads a Markdown one: what is not prose blanked.

The contract is `mask`'s: the same length, every line break kept, and what is not prose
replaced by NUL, so that a finding names the `.tex` line. Two additions keep the length. A
sign TeX prints as a space is a space: `~`, `\\,`, `\\quad`, `\\\\`, and `&` in a table. An
escaped character is that character at the backslash's place, with a NUL after it, so that
`95\\%` reads as `95%`.

One pass, linear in the file, under TeX's default category codes. The preamble is blanked but
for `\\title`, `\\thanks`, and a definition's body and default argument, which print where it
is used; maths keeps what it holds but its commands, braces and delimiters,
as Markdown's `mask` keeps `$...$`; a comment, a listing, a label, a key and a binding are
blanked; a command not in `commands.py` has its name blanked and its arguments read. What the
reader cannot read exactly is refused (`Refusal`), and past the first refusal the rest of the
file is read as prose, so that nothing the reader did not understand is hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.text.latex.commands import (
    AMSMATH,
    CITATIONS,
    COMMANDS,
    ENVIRONMENTS,
    FLOATS,
    LISTINGS,
    MATHS,
    PARAMETERS,
    RAW,
    REFUSED,
    REFUSED_ENVIRONMENTS,
    SIUNITX,
    SPACES,
    TABLES,
    TYPED_TABLES,
)
from manuscript_guard.text.placeholders import NAMESPACES

NUL = "\x00"
PROSE, BLANK, MATHS_READ, PREAMBLE = "prose", "blank", "maths", "preamble"
#: Commands whose prose argument LaTeX prints though it stands in the preamble: the title, its
#: note, and a definition's default argument, printed at each use that omits it (round 1 of
#: #380: `\\newcommand{\\ci}[1][95]{...}` hid the 95). The abstract, as a command or an
#: environment, which a class such as PNAS's prints from the preamble (round 2 of #385: it
#: was refused, and so was `\\let\\oldabstract\\abstract`, which only names it).
PRINTED_IN_PREAMBLE = frozenset(
    {"title", "thanks", "newcommand", "renewcommand", "providecommand", "newenvironment",
     "renewenvironment", "DeclareRobustCommand", "NewDocumentCommand", "RenewDocumentCommand",
     "ProvideDocumentCommand", "DeclareDocumentCommand", "abstract"}
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
class Input:
    """An `\\input` or `\\include` where the reader met it, with the state it stands in: the
    file it names starts in that state."""

    offset: int
    end: int
    path: str
    body: bool
    environments: tuple[str, ...]


@dataclass(frozen=True)
class Heading:
    """A heading where its command stands, its level as Markdown counts `#`, its title, and
    where its title's argument ends, or -1 where nothing of it is the title (an abstract)."""

    start: int
    level: int
    title: str
    end: int = -1


@dataclass(frozen=True)
class BindingUse:
    """A `\\mg` where it stands, to the brace that closes it, and what its braces hold: None
    where it is followed by none. Whether that is a binding is `views.py`'s to say."""

    start: int
    end: int
    inner: str | None


@dataclass(frozen=True)
class Listing:
    """What a listing holds, between its `\\begin` and its `\\end`, and the language an
    `lstlisting` names, or "" where it names none."""

    start: int
    end: int
    language: str


@dataclass(frozen=True)
class Cited:
    """One key a citation command names: the key, where it stands, whether the command prints
    the authors' names in the sentence, and the command to its keys' closing brace."""

    key: str
    offset: int
    narrative: bool
    start: int
    end: int


@dataclass(frozen=True)
class Reading:
    masked: str
    refusals: tuple[Refusal, ...]
    inputs: tuple[Input, ...] = ()
    headings: tuple[Heading, ...] = ()
    #: Where each abstract runs, `\\begin{abstract}` to its `\\end`, or `\\abstract{...}`.
    abstracts: tuple[tuple[int, int], ...] = ()
    #: Each package loaded, where its `\\usepackage` stands.
    packages: tuple[tuple[int, str], ...] = ()
    #: Each `\\mg` read, outside a comment, a listing and siunitx's commands.
    bindings: tuple[BindingUse, ...] = ()
    #: What looks meant for a binding and is none: a near spelling of `\\mg`, `\\Mg{results.x}`,
    #: and a Markdown binding left in a `.tex`, `{{results.x}}`.
    suspects: tuple[tuple[int, int], ...] = ()
    #: Where each table the author typed runs, `\\begin{tabular}` to its `\\end`.
    tables: tuple[tuple[int, int], ...] = ()
    #: Each listing, read by G2's code check as a fenced block is.
    listings: tuple[Listing, ...] = ()
    #: Each key a citation command names, outside a definition's body.
    cited: tuple[Cited, ...] = ()
    #: Where each formula runs, and whether it is displayed rather than inline.
    maths: tuple[tuple[int, int, bool], ...] = ()
    #: Where each float runs, `\\begin{figure}` or `\\begin{table}` to its `\\end`.
    floats: tuple[tuple[int, int], ...] = ()
    #: Where the body starts: past `\\begin{document}`, 0 in a file that opens in it, or -1
    #: in one that never reaches it.
    body_start: int = 0
    #: Each code span, `\\verb` or `\\texttt`, from its opening delimiter to past its closing
    #: one: read as prose, and as Markdown's code span is where words are counted.
    code: tuple[tuple[int, int], ...] = ()
    #: What a journal's profile states of a LaTeX source, as the file states it: ("class",
    #: name), ("class_option", option), ("bst", style), and ("biblatex", its options).
    declared: tuple[tuple[str, str], ...] = ()


#: The level of each sectioning command, as Markdown's `#` counts it; a part stands over a
#: chapter (round 1 of #385: both were 0, and a chapter closed its part).
LEVELS = {"part": -1, "chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3,
          "paragraph": 4, "subparagraph": 5}  # fmt: skip
#: A path in braces after `\input`, which TeX finds past spaces and one line break.
_BRACED_PATH = re.compile(r"[ \t]*(?:\r?\n[ \t]*)?\{([^{}\n]*)\}")
#: Commands the reader knows that an author may define again, which it then reads as before:
#: `\abstract` was an unknown command, its arguments read, until it was given a heading.
_REDEFINABLE = frozenset({"abstract"})
_PACKAGES = re.compile(r"\s*(?:\[([^\]]{0,300})\])?\s*\{([^{}]{0,300})\}")
_NAMESPACE = "(?:" + "|".join(NAMESPACES) + r")\."
#: What TeX passes over before an argument: spaces, and one line break (round 1 of #400).
_GAP = r"[ \t]*(?:\r?\n[ \t]*)?"
#: What follows a `\\mg`: its options, and its braces with what they hold, on one line.
_BINDING = re.compile(_GAP + r"(?:\[[^\]\n]*\])?" + _GAP + r"\{(?P<inner>[^{}\n]*)\}")
#: What makes a command, or a Markdown binding, look meant for one.
_LOOKS_BOUND = re.compile(_GAP + r"(?:\[[^\]\n]*\])?" + _GAP + r"\{[ \t]*" + _NAMESPACE)
_MARKDOWN_BINDING = re.compile(r"\{\{[ \t]*" + _NAMESPACE)
_KEYED = re.compile(r"[ \t]*" + _NAMESPACE)
#: The word after a `\\mg` that no braces follow, shown with it: `\\mg results.x`.
_BARE = re.compile(r"[ \t]*[^\s{}\\%]*")
#: A `\\mg` that names a key, which a listing or a `\\verb` prints as typed. One that names
#: none documents the command and is left alone (round 1 of #400).
_MG_USE = re.compile(r"\\mg(?![A-Za-z@])" + _LOOKS_BOUND.pattern)
_LISTING_OPTIONS = re.compile(r"[ \t]*\[([^\]\n]*)\]")
_LANGUAGE = re.compile(r"language\s*=\s*\{?\s*(?:\[[^\]]*\])?\s*([A-Za-z][A-Za-z0-9+#]*)")
_BOUND_IN_SIUNITX = ("a binding in a siunitx command is not read: siunitx parses its number, "
                     "and a value prints as text; write \\mg{...} outside it")  # fmt: skip


def _near_binding(name: str) -> bool:
    """Whether a command's name is `mg` mistyped: another case, or one letter added, taken
    out, changed or swapped with its neighbour."""
    low = name.lower()
    if low == "mg":
        return name != "mg"
    if len(low) == 2:
        return low == "gm" or sum(a != b for a, b in zip(low, "mg", strict=True)) == 1
    if len(low) not in (1, 3):
        return False
    longer, shorter = (low, "mg") if len(low) == 3 else ("mg", low)
    return any(longer[:i] + longer[i + 1 :] == shorter for i in range(len(longer)))


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
    #: A heading's level and where its command stands, for the argument that is its title.
    heading: int | None = None
    origin: int = -1
    #: An environment the file was input inside, which it may close and need not.
    inherited: bool = False
    #: An argument of a siunitx command.
    siunitx: bool = False


def mask(text: str, *, body: bool | None = None) -> str:
    """`text` with what is not prose replaced by NUL. `body` says whether the file opens in
    the document's body, as a file input from it does; None reads it from the file."""
    return read(text, body=body).masked


def read(
    text: str,
    *,
    body: bool | None = None,
    environments: tuple[str, ...] = (),
    loose: bool = False,
    package: bool = False,
) -> Reading:
    """The masked text, the first refusal, and what the file inputs, heads and loads. With
    `body` None, a file with a `\\begin{document}` outside a comment opens in the preamble,
    and one without opens in the body, so that none of it is hidden as preamble (round 1 of
    #380). One read to its end without reaching its `\\begin{document}`, which stood in a
    listing say, is read again as body; one refused in its preamble keeps that refusal (round
    2). A file input from another opens inside the `environments` its `\\input` stood in. A
    `loose` file, which nothing inputs, is body that accepts what a preamble accepts. A
    `package` of the author's is read as LaTeX reads a package, with `@` a letter."""
    opens_in_body = not _has_document(text) if body is None else body
    reader = _Reader(text, opens_in_body, environments, loose, package)
    reading = reader.run()
    if body is None and not reader.body and reader.refused is None:
        return _Reader(text, True, environments, loose, package).run()
    return reading


def _has_document(text: str) -> bool:
    """Whether a `\\begin{document}` stands outside a comment, the text read forward once
    (round 3 of #380)."""
    scanned, comment = 0, False
    for match in _DOCUMENT.finditer(text):
        newline = text.rfind("\n", scanned, match.start())
        if newline >= 0:
            scanned, comment = newline + 1, False
        comment = comment or _opens_comment(text, scanned, match.start())
        if not comment:
            return True
        scanned = match.start()
    return False


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


#: How far a multi-citation's global note is looked for, `\\cites(see)(p.~5){a}{b}`.
_NOTE_REACH = 300


def _key_list(keys: str) -> str:
    """A citation's keys with each comment in them blanked, at the same offsets: LaTeX drops
    `%` to the end of its line, so `\\citep{a,%` and `b}` on the next line cite a and b."""
    return re.sub(r"(?<!\\)%[^\n]*", lambda found: " " * len(found.group(0)), keys)


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
    def __init__(
        self,
        text: str,
        body: bool,
        environments: tuple[str, ...] = (),
        loose: bool = False,
        package: bool = False,
    ) -> None:
        self.text = text
        self.n = len(text)
        self.out = list(text)
        self.pos = 0
        self.body = body
        self.loose = loose
        self.stack: list[_Frame] = []
        self.pending: tuple[str, ...] = ()
        self.command = ""
        self.refused: Refusal | None = None
        self.letters = _LETTERS_AT if package else _LETTERS
        self.definitions = 0
        self.environments: list[str] = []
        self.inputs: list[Input] = []
        self.headings: list[Heading] = []
        self.abstracts: list[tuple[int, int]] = []
        self.packages: list[tuple[int, str]] = []
        self.bindings: list[BindingUse] = []
        self.suspects: list[tuple[int, int]] = []
        self.tables: list[tuple[int, int]] = []
        self.listings: list[Listing] = []
        self.cited: list[Cited] = []
        self.citation_at = -1
        self.maths: list[tuple[int, int, bool]] = []
        self.floats: list[tuple[int, int]] = []
        self.code: list[tuple[int, int]] = []
        self.declared: list[tuple[str, str]] = []
        self.body_start = 0 if body else -1
        self.siunitx = 0
        #: The command a definition being read defines, until its body opens.
        self.defining = ""
        self.heading_at = -1
        for name in environments:
            role = MATHS_READ if name in MATHS else self._role()
            self.stack.append(_Frame("env", role, 0, name, table=name in TABLES, inherited=True))
            self.environments.append(name)

    # -- running -----------------------------------------------------------------------
    def run(self) -> Reading:
        while self.pos < self.n and self.refused is None:
            if self.pending and self._argument():
                continue
            self._step()
        opened = [frame for frame in self.stack if not frame.inherited]
        if self.refused is None and opened:
            self._refuse("tex-unbalanced", opened[0].start, f"{_opened(opened[0])} is not closed")
        masked = "".join(self.out)
        # A table the file was input inside and does not close runs to its end.
        tables = self.tables + [(0, self.n) for frame in self.stack
                                if frame.inherited and frame.closer in TYPED_TABLES]  # fmt: skip
        # So does a float or a displayed formula: a figure's file input inside `figure`.
        floats = self.floats + [(0, self.n) for frame in self.stack
                                if frame.inherited and frame.closer in FLOATS]  # fmt: skip
        maths = self.maths + [(0, self.n, True) for frame in self.stack
                              if frame.inherited and frame.closer in MATHS]  # fmt: skip
        found = (tuple(self.inputs), tuple(self.headings), tuple(self.abstracts),
                 tuple(self.packages), tuple(self.bindings), tuple(self.suspects),
                 tuple(sorted(tables)), tuple(self.listings), tuple(self.cited),
                 tuple(sorted(maths)), tuple(sorted(floats)), self.body_start,
                 tuple(self.code), tuple(self.declared))  # fmt: skip
        if self.refused is None:
            return Reading(masked, (), *found)
        at = self.refused.offset
        return Reading(masked[:at] + self.text[at:], (self.refused,), *found)

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
        there is none, and the text is read on as it comes. In amsmath's environments, its
        cases and matrices among them, `\\\\` takes its length only where it follows at once:
        a `[0.5, 1.2]` opening the next row prints (rounds 1 and 4 of #380). Elsewhere it
        skips spaces before it, as the kernel's and a bare array's do, and `\\\\ [2pt]` in a
        table or an array is a length (rounds 2 and 3)."""
        amsmath = self.command == "\\" and bool(self.environments) and (
            self.environments[-1] in AMSMATH
        )
        at = self.pos if amsmath else self._after_space(self.pos)
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
                if here == "[" and spec[1] == "o":
                    # An option list is blanked, a value read (`commands.py`, `[o]`).
                    close = self.text.find("]", at, at + 300)
                    listed = "=" in self.text[at : close if close >= 0 else at + 300]
                    self._open("opt", "b" if listed else "p", at, "]", siunitx=listed)
                    return True
                if here == "[":
                    self._open("opt", spec[1], at, "]")
                    return True
                self.pending = self.pending[1:]
                continue
            if spec[0] == "(":
                # A trim such as `(lr)` is a few letters: looked for that far, on its line. A
                # multi-citation's global note is a phrase, and may wrap (round 1 of step 5).
                reach, stop = (_NOTE_REACH, "\n\n") if self.command in CITATIONS else (32, "\n")
                end = self.text.find(")", at, at + reach) if here == "(" else -1
                if end >= 0 and stop not in self.text[at:end]:
                    self._blank(at, end + 1)
                    self.pos = end + 1
                    self.pending = self.pending[1:]
                    return True
                if here == "(" and self.command in CITATIONS:
                    # Read past, the note would hide the keys after it (round 2 of step 5).
                    said = f"its global note is not closed within {_NOTE_REACH} characters"
                    self._refuse("tex-refused", at, f"\\{self.command} is not read: {said}")
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
            # A definition whose body is not there defines nothing a later body is of.
            self.defining = ""
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

    def _open(
        self, kind: str, spec: str, at: int, closer: str, *, siunitx: bool | None = None
    ) -> None:
        role = self._role()
        # A body prints where it is used, but a LaTeX parameter's is a size. What is being
        # defined is spent on the body that opens, whatever its role (round 2 of #400: left
        # set, it blanked the next body that defined nothing, `\AtBeginDocument`'s).
        parameter = spec == "d" and self.defining in PARAMETERS
        if spec == "d":
            self.defining = ""
        if role == BLANK or spec in "bc":
            chosen = BLANK
        elif spec == "d":
            chosen = BLANK if parameter else PROSE
        elif role == PREAMBLE:
            chosen = PROSE if self._printed_from_preamble(self.command) else PREAMBLE
        else:
            chosen = _note_role(spec)
        frame = _Frame(kind, chosen, at, closer, self.pending[1:], self.command, spec == "d",
                       siunitx=self.command in SIUNITX if siunitx is None else siunitx)  # fmt: skip
        self.siunitx += frame.siunitx
        heads = self.command in LEVELS or self.command == "abstract"
        if kind == "arg" and spec == "p" and heads and not self.definitions and chosen == PROSE:
            frame.heading = LEVELS.get(self.command, 1)
            frame.origin = self.heading_at
        if kind == "arg" and spec == "b" and self.command in CITATIONS and not self.definitions:
            self._cite(at)
        self.definitions += frame.definition
        self.stack.append(frame)
        # A Markdown binding as a command's argument, `\\emph{{results.x}}` (round 1 of #400:
        # only one opening a group of its own was seen).
        # `\\mg{{results.x}}` is `\\mg`'s own, said once there (round 2 of #400), but in
        # siunitx, where `\\mg` records nothing (round 3).
        mg_says_it = self.command == "mg" and not self.siunitx
        if closer == "}" and not mg_says_it and _MARKDOWN_BINDING.match(self.text, at):
            self.suspects.append((at, self._suspect_end(at)))
        self._blank(at, at + 1)
        self.pos = at + 1
        self.pending = ()

    def _cite(self, at: int) -> None:
        """Record each key the citation's braces at `at` name, where it stands: split at the
        commas, as natbib and biblatex split them, a space round each taken off."""
        end = self._group_end(at, comments=True)
        if end < 0:
            return  # the brace left open is refused where it stands
        narrative = CITATIONS[self.command]
        offset = at + 1
        for part in _key_list(self.text[at + 1 : end - 1]).split(","):
            key = part.strip()
            if key:
                self.cited.append(Cited(key, offset + part.index(key), narrative,
                                        self.citation_at, end))  # fmt: skip
            offset += len(part) + 1

    def _group_end(self, at: int, *, comments: bool = False) -> int:
        """Where a brace group opened at `at` ends, read as characters: `%` and `#` are no
        signs in a URL. With `comments`, a brace in a comment is passed over, as LaTeX passes
        over a comment in a citation's keys."""
        depth, index = 0, at
        while index < self.n:
            character = self.text[index]
            index += 1
            if comments and character == "%" and self.text[index - 2] != "\\":
                index = _comment_end(self.text, index - 1)
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return index
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
            if _MARKDOWN_BINDING.match(self.text, at):
                self.suspects.append((at, self._suspect_end(at)))
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
        return bool(self.environments) and self.environments[-1] in TABLES

    def _close_group(self, at: int) -> None:
        top = self.stack[-1] if self.stack else None
        if top is None or top.kind not in ("group", "arg"):
            self._refuse("tex-unbalanced", at, "this brace closes nothing that is open")
            return
        self._close(at, 1)

    def _close(self, at: int, width: int) -> None:
        frame = self.stack.pop()
        self.definitions -= frame.definition
        self.siunitx -= frame.siunitx
        self._blank(at, at + width)
        self.pos = at + width
        if frame.kind in ("arg", "opt"):
            self.pending, self.command = frame.rest, frame.command
        if frame.heading is not None:
            if frame.command == "abstract":
                self.headings.append(Heading(frame.origin, 1, "Abstract"))
                self.abstracts.append((frame.origin, at + width))
            else:
                title = " ".join("".join(self.out[frame.start + 1 : at]).replace(NUL, "").split())
                self.headings.append(Heading(frame.origin, frame.heading, title, at + width))
        if frame.kind == "maths":
            self.maths.append((frame.start, at + width, frame.closer in ("$$", "\\]")))
        if frame.kind == "arg" and frame.command == "texttt" and not self.definitions:
            self.code.append((frame.start, at + width))

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
        elif (symbol in ")]" and self.stack and self.stack[-1].kind == "maths"
              and self.stack[-1].closer == "\\" + symbol):  # fmt: skip
            self._close(at, 2)
        elif symbol in ")]" and self._reads():
            self._refuse("tex-unbalanced", at, f"\\{symbol} closes no maths that is open")
        else:
            self._blank(at, at + 2)

    def _word(self, name: str, at: int, end: int) -> None:
        if name in REFUSED:
            self._refuse("tex-refused", at, f"\\{name} is not read: {REFUSED[name]}")
        elif name in ("makeatletter", "makeatother"):
            if name == "makeatletter" and self.body and not self.loose:
                self._refuse("tex-refused", at, "\\makeatletter in the body changes how "
                             "characters are read")  # fmt: skip
            self.letters = _LETTERS_AT if name == "makeatletter" else _LETTERS
        elif name == "iffalse":
            self._skip_false(at)
        elif name.startswith("if") and name not in COMMANDS and name not in NOT_CONDITIONALS:
            if self.body and not self.loose:
                said = "a conditional in the body prints one branch, and which is not read"
                self._refuse("tex-refused", at, f"\\{name} is not read: {said}")
        elif name in ("input", "include") and not self.definitions:
            self._input(at, end)
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
            if name != "inputencoding":
                self._packages(at, end)
            if name in COMMANDS:
                self.command, self.pending = name, COMMANDS[name]
        elif name == "mg":
            self._binding(at, end)
            self.command, self.pending = name, COMMANDS[name]
        elif name in COMMANDS:
            if name in LEVELS or name == "abstract":
                self.heading_at = at
            if name in CITATIONS:
                self.citation_at = at
            if name in ("documentclass", "bibliographystyle"):
                self._declares(name, end)
            self.command, self.pending = name, COMMANDS[name]
        elif self._unknown_citation(name):
            # A citation command the reader does not know would hide its keys from G7 (DESIGN.md,
            # "Citations"); one an author defines is refused where it is used.
            said = ("a citation command the reader does not know, whose keys G7 would not see; "
                    "cite with \\cite or one of the natbib and biblatex commands it reads")
            self._refuse("tex-refused", at, f"\\{name} is not read: {said}")
        elif _near_binding(name) and _LOOKS_BOUND.match(self.text, end):
            self.suspects.append((at, self._suspect_end(at)))

    def _unknown_citation(self, name: str) -> bool:
        """Whether a command the reader does not know is one that cites, where what it cites
        would print: its name holds `cite`, outside a definition's body and outside the
        preamble, where natbib's and biblatex's settings stand, `\\setcitestyle` and
        `\\DeclareCiteCommand` among them (round 1 of step 5)."""
        return "cite" in name.lower() and not self.definitions and self._role() != PREAMBLE

    def _binding(self, at: int, end: int) -> None:
        """Record a `\\mg` where it stands, with what its braces hold. In a siunitx command
        `\\mg` is the milligram siunitx defines, `\\qty{5}{\\mg}`, and one that names a key is
        refused, since siunitx parses what it holds and a value's display is formatted text."""
        written = _BINDING.match(self.text, end)
        if self.siunitx:
            if written and _KEYED.match(written.group("inner")):
                self._refuse("tex-refused", at, _BOUND_IN_SIUNITX)
            return
        stop = written.end() if written else _BARE.match(self.text, end).end()
        self.bindings.append(BindingUse(at, stop, written.group("inner") if written else None))

    def _suspect_end(self, at: int) -> int:
        """Where something that looks meant for a binding ends: at the braces that close it,
        on its line."""
        line_end = self.text.find("\n", at)
        line_end = self.n if line_end < 0 else line_end
        close = self.text.find("}", at, line_end)
        if close < 0:
            return line_end
        while close < line_end and self.text[close] == "}":
            close += 1
        return close

    def _input(self, at: int, end: int) -> None:
        """Record an `\\input` with the state it stands in. Its path is read raw; one not
        written in braces, or holding a command, is refused where the tree is read. Its
        argument is then taken as any blanked argument is, so that the mask is the same with
        or without the tree (the old-against-new test of #385)."""
        braced = _BRACED_PATH.match(self.text, end)
        path = braced.group(1) if braced else ""
        stop = braced.end() if braced else end
        self.inputs.append(Input(at, stop, path, self.body, tuple(self.environments)))
        self.command, self.pending = "input", COMMANDS["input"]

    def _packages(self, at: int, end: int) -> None:
        listed = _PACKAGES.match(self.text, end)
        if listed and not self.definitions:
            for name in listed.group(2).split(","):
                if name.strip():
                    self.packages.append((at, name.strip()))
                if name.strip() == "biblatex":
                    self.declared.append(("biblatex", listed.group(1) or ""))

    def _declares(self, name: str, end: int) -> None:
        """Record the class a `\\documentclass` names and its options, or the style a
        `\\bibliographystyle` names, as a journal's profile states them (G4)."""
        found = _PACKAGES.match(self.text, end)
        if found is None or self.definitions:
            return
        if name == "documentclass":
            self.declared.append(("class", found.group(2).strip()))
            for option in (found.group(1) or "").split(","):
                if option.strip():
                    self.declared.append(("class_option", option.strip()))
        else:
            self.declared.append(("bst", found.group(2).strip()))

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
            # `\\else` is a line break and a word, not `\else` (round 2 of #380).
            before = start - 1
            while before >= 0 and self.text[before] == "\\":
                before -= 1
            word = match.group(0)[1:]
            if comment or word in NOT_CONDITIONALS or (start - 1 - before) % 2:
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
        # A line break looked for between the delimiters only: looked for to the line's end,
        # a line of `\verb|x|` was read again for each (CI on #380, macOS and Windows).
        if close < 0 or self.text.find("\n", start + 1, close) >= 0:
            self._refuse("tex-unbalanced", at, "\\verb is not closed on its line")
            return
        self._blank(at, start + 1)
        self._keep_or_blank(start + 1, close)
        self._blank(close, close + 1)
        self.pos = close + 1
        if not self.definitions:
            self.code.append((start, close + 1))
        bound = _MG_USE.search(self.text, start + 1, close)
        if bound is not None:
            self._refuse("tex-refused", bound.start(), _bound_as_typed("\\verb"))

    def _definition(self, name: str, at: int, end: int) -> None:
        start = self._after_space(end)
        if self.text[start : start + 1] != "\\":
            return
        name_end = self._name_end(start)
        self._defines(self.text[start + 1 : name_end], start)
        self._blank(start, name_end)
        self.pos = name_end
        if name == "let":
            self.defining = ""
            return
        parameters = _PARAMETERS.match(self.text, name_end).end()
        if self.text[parameters : parameters + 1] != "{":
            self._refuse("tex-refused", at, f"\\{name} with delimited parameters is not read")
            return
        self._blank(name_end, parameters)
        self.command = name
        self._open("arg", "d", parameters, "}")

    def _printed_from_preamble(self, name: str) -> bool:
        """Whether what `name` takes is printed though it stands in the preamble: the title
        and a definition's default anywhere there, an abstract only outside any environment
        or argument (round 3 of #385: one in `filecontents` was read, and nothing prints it)."""
        if name != "abstract":
            return name in PRINTED_IN_PREAMBLE
        return name in PRINTED_IN_PREAMBLE and all(f.kind == "group" for f in self.stack)

    def _defines(self, name: str, at: int) -> None:
        self.defining = name
        if name in _REDEFINABLE:
            return
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
            # {\end{itemize}}` was refused). Its arguments are still taken: a minipage's width
            # is no number of the paper's (round 2).
            if which == "begin":
                self.command, self.pending = "begin", ENVIRONMENTS.get(name, ())
            return
        if which == "end":
            self._end(name, at)
        elif name in REFUSED_ENVIRONMENTS:
            self._refuse("tex-refused", at, f"{name} is not read: {REFUSED_ENVIRONMENTS[name]}")
        elif name == "document":
            self.body = True
            self.body_start = self.pos
        elif name in RAW:
            ending = re.compile(r"\\end\s*\{" + re.escape(name) + r"\}")
            closing = ending.search(self.text, self.pos)
            if closing is None:
                self._refuse("tex-unbalanced", at, f"\\begin{{{name}}} is not closed")
                return
            if name in LISTINGS:
                self._listing(name, closing.start())
            self._blank(at, closing.end())
            self.pos = closing.end()
            bound = _MG_USE.search(self.text, at, closing.start()) if name in LISTINGS else None
            if bound is not None:
                self._refuse("tex-refused", bound.start(), _bound_as_typed(name))
        else:
            role = self._role()
            if role == PREAMBLE and self._printed_from_preamble(name):
                role = PROSE
            maths = name in MATHS and role in (PROSE, MATHS_READ)
            self.stack.append(_Frame("env", MATHS_READ if maths else role, at, name,
                                     table=name in TABLES))  # fmt: skip
            self.environments.append(name)
            if name == "abstract" and role == PROSE:
                self.headings.append(Heading(at, 1, "Abstract"))
            self.command, self.pending = "begin", ENVIRONMENTS.get(name, ())

    def _end(self, name: str, at: int) -> None:
        opened = [frame for frame in self.stack if not frame.inherited]
        if name == "document":
            if opened:
                first = opened[0]
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
        self.environments.pop()
        self.pending = ()
        if name == "abstract" and top.role == PROSE:
            self.abstracts.append((top.start, self.pos))
        if name in TYPED_TABLES:
            self.tables.append((0 if top.inherited else top.start, at))
        if name in MATHS:
            self.maths.append((0 if top.inherited else top.start, self.pos, True))
        if name in FLOATS:
            self.floats.append((0 if top.inherited else top.start, self.pos))

    def _listing(self, name: str, end: int) -> None:
        """Record what a listing holds, and the language an `lstlisting`'s options name."""
        start, language = self.pos, ""
        options = _LISTING_OPTIONS.match(self.text, start) if name == "lstlisting" else None
        if options is not None:
            start = options.end()
            named = _LANGUAGE.search(options.group(1))
            language = named.group(1).lower() if named else ""
        self.listings.append(Listing(start, end, language))


def _bound_as_typed(where: str) -> str:
    return (f"a binding in {where} is printed as typed, not as its value: bind the number "
            "outside it")  # fmt: skip


def _opened(frame: _Frame) -> str:
    if frame.kind == "env":
        return f"\\begin{{{frame.closer}}}"
    if frame.kind == "maths":
        return f"maths opened with {frame.closer}"
    if frame.kind in ("arg", "opt"):
        return f"an argument of \\{frame.command}"
    return "a brace"
