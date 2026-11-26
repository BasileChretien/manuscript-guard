"""Reading numbers out of source code, with enough context to judge them.

Prose tokenising is useless here. A figure script is full of numbers that are obviously
not claims — `size = 2`, `dpi = 300`, `alpha = 0.7` — and a checker that reports them all
gets switched off within a day. What distinguishes them is not their value but their
syntactic position, so this module records where each number sits: inside a string, or in
code as an argument to some named parameter, inside some chain of enclosing calls.

The lexer is deliberately small. It needs to know three things — where strings are, where
comments are, and what brackets and named arguments enclose a given number — and a full
parser for two languages would be a great deal of machinery for those three answers.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field

PYTHON = "python"
R = "r"

_LINE_COMMENT = {PYTHON: "#", R: "#"}
_IDENT = re.compile(r"[A-Za-z_.][A-Za-z0-9_.]*")
_NUMBER = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[LjJ]?")
_STRING_PREFIX = re.compile(r"(?:[rRbBuUfF]{0,3})$")

LANGUAGE_BY_SUFFIX = {
    ".py": PYTHON,
    ".r": R,
    ".rmd": R,
    ".qmd": R,
}


@dataclass(frozen=True)
class Token:
    kind: str  # "code" | "string" | "comment" | "number"
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class CodeNumber:
    """A numeric literal, with the syntactic context needed to classify it."""

    text: str
    start: int
    end: int
    line: int
    line_text: str
    in_string: bool
    names: tuple[str, ...] = field(default=())
    # Offset of this literal within `line_text`. Needed because a line can hold several
    # numbers sharing a digit string, and a checker that matches them by text rather than
    # by position judges the wrong one.
    col: int = 0
    # For a number inside a string, what the string holds between its quotes: "grey50" for
    # the 50 of `colour = "grey50"`, so that a check can tell a colour's name from a label.
    string: str | None = None
    # The number is the whole subscript of a bracket after a name, a call or another
    # subscript: the 1 of `edges[1]`, `fits[[1]]`, `edges[-1]`. An index, in either language.
    subscript: bool = False
    # The number is 0 (or 0L), compared by `==` or `!=` with a process's exit status: a name
    # assigned from `system2()`, `system()`, `os.system()` or `subprocess.call()`, or from a
    # `$status` or `.returncode`, or any of those written in place (`_exit_statuses`).
    exit_status: bool = False

    @property
    def context(self) -> str:
        return " > ".join(reversed(self.names)) if self.names else "(top level)"


def lex(text: str, language: str) -> list[Token]:
    """Split source into strings, comments and code atoms."""
    comment_char = _LINE_COMMENT[language]
    tokens: list[Token] = []
    i, n = 0, len(text)

    while i < n:
        ch = text[i]

        if ch in " \t\r\n":
            i += 1
            continue

        if ch == comment_char:
            end = text.find("\n", i)
            end = n if end == -1 else end
            tokens.append(Token("comment", text[i:end], i, end))
            i = end
            continue

        if ch in "\"'":
            start = i
            triple = language == PYTHON and text[i : i + 3] in ('"""', "'''")
            quote = text[i : i + 3] if triple else ch
            i += len(quote)
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text.startswith(quote, i):
                    i += len(quote)
                    break
                i += 1
            # Triple-quoted strings are documentation in practice, and a docstring that
            # mentions a gate name or a version is not a number the figure draws.
            tokens.append(Token("docstring" if triple else "string", text[start:i], start, i))
            continue

        match = _NUMBER.match(text, i)
        if match and not (i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_")):
            tokens.append(Token("number", match.group(0), i, match.end()))
            i = match.end()
            continue

        match = _IDENT.match(text, i)
        if match:
            tokens.append(Token("code", match.group(0), i, match.end()))
            i = match.end()
            continue

        # R's assignment arrow is two characters and must not split.
        if text.startswith("<-", i) or text.startswith("->", i):
            tokens.append(Token("code", text[i : i + 2], i, i + 2))
            i += 2
            continue

        tokens.append(Token("code", ch, i, i + 1))
        i += 1

    return tokens


def _line_of(text: str, offset: int) -> tuple[int, str, int]:
    """Line number, the line itself, and the offset of `offset` within it."""
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end == -1:
        end = len(text)
    return text.count("\n", 0, offset) + 1, text[start:end], offset - start


def numbers_in(text: str, language: str) -> list[CodeNumber]:
    """Every numeric literal in the source, in code and inside strings.

    Enclosing context is built with a bracket stack in one forward pass: each open bracket
    pushes a frame remembering the function it belongs to and the named argument currently
    being filled. A number then inherits the names of every frame it sits inside, so
    `scale_y_log10(breaks = c(0.5, 1, 2))` gives the 0.5 the chain c > breaks >
    scale_y_log10, and one look-up against the presentation list settles it.
    """
    tokens = lex(text, language)
    # What a subscript and a comparison are read in: the code, without its comments.
    code = [token for token in tokens if token.kind not in ("comment", "docstring")]
    at = {token.start: index for index, token in enumerate(code)}
    statuses = _exit_statuses(code)
    found: list[CodeNumber] = []

    stack: list[list[str | None]] = []  # [function, current named argument]
    target: str | None = None  # name being assigned at statement level

    for index, token in enumerate(tokens):
        if token.kind in ("comment", "docstring"):
            continue

        if token.kind == "string":
            for match in _NUMBER.finditer(token.text):
                offset = token.start + match.start()
                line, line_text, col = _line_of(text, offset)
                found.append(
                    CodeNumber(
                        text=match.group(0),
                        start=offset,
                        end=offset + len(match.group(0)),
                        line=line,
                        line_text=line_text,
                        in_string=True,
                        names=_names(stack, target),
                        col=col,
                        string=_between_quotes(token.text),
                    )
                )
            continue

        if token.kind == "number":
            line, line_text, col = _line_of(text, token.start)
            found.append(
                CodeNumber(
                    text=token.text,
                    start=token.start,
                    end=token.end,
                    line=line,
                    line_text=line_text,
                    in_string=False,
                    names=_names(stack, target),
                    col=col,
                    subscript=_whole_subscript(code, at[token.start]),
                    exit_status=_compared_with_a_status(code, at[token.start], statuses),
                )
            )
            continue

        text_ = token.text
        if text_ in "([{":
            previous = tokens[index - 1] if index else None
            function = _identifier(previous)
            stack.append([function, None])
        elif text_ in ")]}":
            if stack:
                stack.pop()
        elif text_ == ",":
            if stack:
                stack[-1][1] = None
        elif text_ in ("=", "<-", ":="):
            previous = tokens[index - 1] if index else None
            name = _identifier(previous)
            if stack:
                stack[-1][1] = name
            else:
                target = name

    return found


def _identifier(token: Token | None) -> str | None:
    """The token's text when it is a bare identifier, otherwise None."""
    if token is None or token.kind != "code":
        return None
    return token.text if _IDENT.fullmatch(token.text) else None


def _between_quotes(literal: str) -> str:
    """What a string literal holds: its text without the quotes around it."""
    quote = literal[:1]
    return literal[1:-1] if len(literal) > 1 and literal.endswith(quote) else literal[1:]


#: Words before a bracket that open no subscript: `x in [1]`, `return [1]`, `else [1]`.
_KEYWORDS = frozenset(keyword.kwlist) | {"function", "repeat", "next", "break", "print"}


def _text(tokens: list[Token], index: int) -> str | None:
    """The code token's text at `index`; None out of range, or for a string or a number."""
    if 0 <= index < len(tokens) and tokens[index].kind == "code":
        return tokens[index].text
    return None


def _whole_subscript(tokens: list[Token], index: int) -> bool:
    """Whether the number at `index` is all a subscript holds, signed or not: `x[1]`,
    `x[-1]`, `x[[2]]`, `f(x)[1]`, `rows[0][1]`. A bracket after anything but a name, a call
    or another subscript is a list (`ticks = [1]`), and its number is read as before."""
    opener = index - 1
    if _text(tokens, opener) in ("-", "+"):
        opener -= 1
    if _text(tokens, opener) != "[" or _text(tokens, index + 1) != "]":
        return False
    owner = opener - 1
    if _text(tokens, owner) == "[":  # R's `x[[2]]`
        if _text(tokens, index + 2) != "]":
            return False
        owner -= 1
    before = _text(tokens, owner)
    if before in (")", "]"):
        return True
    return owner >= 0 and _identifier(tokens[owner]) is not None and before not in _KEYWORDS


#: The calls whose value is the exit status of the process they ran, in R and in Python.
_STATUS_CALLS = frozenset({"system", "system2", "base::system", "base::system2", "os.system",
                           "subprocess.call"})  # fmt: skip
#: A zero as an exit status is written: R's integer, and the number of either language.
_ZERO = frozenset({"0", "0L"})


def _matching(tokens: list[Token], index: int, step: int) -> int | None:
    """The index of the bracket that closes (`step` 1) or opens (`step` -1) the one at
    `index`; None where there is none."""
    depth = 0
    while 0 <= index < len(tokens):
        text = _text(tokens, index)
        if text in ("(", "[", "{"):
            depth += step
        elif text in (")", "]", "}"):
            depth -= step
        if depth == 0:
            return index
        index += step
    return None


def _called(tokens: list[Token], opener: int) -> str | None:
    """The name of the call whose `(` is at `opener`, with its package where it is written
    `processx::run`."""
    name = _identifier(tokens[opener - 1]) if opener > 0 else None
    if name is None:
        return None
    if _text(tokens, opener - 2) == ":" and _text(tokens, opener - 3) == ":":
        package = _identifier(tokens[opener - 4]) if opener > 3 else None
        return f"{package}::{name}" if package else name
    return name


def _status_field(tokens: list[Token], index: int) -> bool:
    """Whether the operand ends at `index` in a process's status: `res$status`,
    `proc.returncode`, `subprocess.run(...).returncode`."""
    text = _text(tokens, index)
    if text is None:
        return False
    return text.endswith(".returncode") or (text == "status" and _text(tokens, index - 1) == "$")


def _ends_in_a_status(tokens: list[Token], index: int, statuses: frozenset[str]) -> bool:
    """Whether the operand of a comparison that ends at `index` is an exit status."""
    text = _text(tokens, index)
    if text == ")":
        opener = _matching(tokens, index, -1)
        return opener is not None and _called(tokens, opener) in _STATUS_CALLS
    return _status_field(tokens, index) or (text in statuses
                                            and _text(tokens, index - 1) not in ("$", "."))


def _starts_a_status(tokens: list[Token], index: int, statuses: frozenset[str]) -> bool:
    """Whether the expression that opens at `index` is an exit status: a status call, a
    call's `$status` or `.returncode`, a name holding one, or its own field."""
    if index >= len(tokens) or _identifier(tokens[index]) is None:
        return False
    after = index + 1
    if _text(tokens, after) == ":" and _text(tokens, after + 1) == ":":
        after += 3
    if _text(tokens, after) == "(":
        closer = _matching(tokens, after, 1)
        if closer is None:
            return False
        following = _text(tokens, closer + 1)
        if following == "$":
            return _text(tokens, closer + 2) == "status"
        if following is not None and following.startswith(".returncode"):
            return following == ".returncode"
        return _called(tokens, after) in _STATUS_CALLS
    if _text(tokens, after) == "$":
        return _text(tokens, after + 1) == "status"
    return tokens[index].text.endswith(".returncode") or tokens[index].text in statuses


def _assigns(tokens: list[Token], index: int) -> bool:
    """Whether the token at `index` assigns: `<-`, `:=`, or an `=` that is no part of `==`,
    `!=`, `<=` or `>=`."""
    text = _text(tokens, index)
    if text in ("<-", ":="):
        return True
    return text == "=" and _text(tokens, index - 1) not in ("!", "=", "<", ">") and \
        _text(tokens, index + 1) != "="  # fmt: skip


def _exit_statuses(tokens: list[Token]) -> frozenset[str]:
    """The names the script assigns an exit status to, outside any call's brackets: `status
    <- system2(...)`, `code = subprocess.run(...).returncode`. A name given one as a call's
    argument (`f(status = system2(...))`) is the call's, not the script's."""
    names: set[str] = set()
    brackets: list[str] = []
    for index in range(len(tokens)):
        text = _text(tokens, index)
        if text in ("(", "[", "{"):
            brackets.append(text)
        elif text in (")", "]", "}"):
            if brackets:
                brackets.pop()
        elif (_assigns(tokens, index) and (not brackets or brackets[-1] == "{")
              and index > 0 and _identifier(tokens[index - 1]) is not None
              and index + 1 < len(tokens)
              and _starts_a_status(tokens, index + 1, frozenset(names))):  # fmt: skip
            names.add(tokens[index - 1].text)
    return frozenset(names)


def _compared_with_a_status(tokens: list[Token], index: int, statuses: frozenset[str]) -> bool:
    """Whether the number at `index` is a zero compared, by `==` or `!=`, with an exit
    status, on either side: `status != 0`, `0 != status`, `system2(...) == 0L`."""
    if tokens[index].text not in _ZERO:
        return False
    if _text(tokens, index - 1) == "=" and _text(tokens, index - 2) in ("!", "="):
        return _ends_in_a_status(tokens, index - 3, statuses)
    if _text(tokens, index + 1) in ("!", "=") and _text(tokens, index + 2) == "=":
        return index + 3 < len(tokens) and _starts_a_status(tokens, index + 3, statuses)
    return False


def _names(stack: list[list[str | None]], target: str | None) -> tuple[str, ...]:
    names: list[str] = []
    for function, argument in stack:
        if argument:
            names.append(argument)
        if function:
            names.append(function)
    if target:
        names.append(target)
    return tuple(names)


def language_of(suffix: str) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(suffix.lower())


# What an author writes after the opening fence. Separate from the suffix table because a
# fence is tagged by language name, not by file extension: ```python, not ```.py.
LANGUAGE_BY_TAG = {
    "python": PYTHON,
    "py": PYTHON,
    "python3": PYTHON,
    "r": R,
    "rscript": R,
}


def language_of_tag(tag: str) -> str | None:
    return LANGUAGE_BY_TAG.get(tag.strip().lower())
