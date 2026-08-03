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
