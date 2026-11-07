"""G14, its fifth reading — no name from the code in the prose.

"hr_adj_main was 1.42" and "patients with ckd_flag" are sentences written from the
analysis's side: the name is the script's, and the reader has never seen the script. Three
kinds of word are read as such a name (Basile, D12.1, 2026-11-06):

* exactly a key the analysis emitted, `ror.point`, or the same with the namespace its
  binding gives it, `results.ror.point`: the binding without its braces;
* exactly the name of a variable in the data dictionary (`design/data_dictionary.yaml`),
  `age_group`, which the finding gives with the dictionary's label for it;
* any word written as code writes one, with underscores between its parts, `hr_adj_main`.

A key or a name is read only where it is shaped as code is: with an underscore or a dot in
it, or in camelCase from two small letters, `ckdFlag`. The example's dictionary names a
variable `sex`, and `BMI`, `eGFR` and `CD4` are the prose's words too (D12.4, 2026-11-07).

**A code span is printed too.** A key or a dictionary name written in one,
`` `hr_adj_main` ``, is read as it is in a sentence. Any other word with underscores in a
code span is not: it is a function or a package, put in code on purpose (D12.3).

**What is not prose is not read.** The views this reads have the bindings, the citation
keys, the URLs and link targets, the listings, the comments, the maths, LaTeX's commands and
the reference list taken out already (`language._hidden`, `text/latex/words.py`). Here a path
or an address is set aside too, a word in a run of characters that holds a slash, an `@` or
a backslash before a letter, and so is a file's name, a dotted word whose last part is an
extension; and in Markdown the opening line of a fenced div, an HTML tag, a pandoc attribute
with an `=` in it and a TeX command, none of which is printed in the document.

**The finding is a warning, and a failure at submission** (D12.2): the version a journal
receives has no word its reader cannot know. A word that is right with its underscores, a
taxon as GTDB writes it or a variable a data paper documents on purpose, is listed under
`language: code_names_kept:` in `paper.yaml` and is then not read anywhere (D12.5). Each
name is reported once, where it first stands, with how often it does.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.gates.vocabulary import context
from manuscript_guard.policy import SUBMISSION
from manuscript_guard.text.masking import NUL

GATE = "G14"
CODE = "code-name-in-prose"

#: The namespace a binding gives a key of the results.
RESULTS = "results."

# A part of a name: letters and digits, the underscore no part of one.
_PART = r"[^\W_]+"
# What joins two parts with underscores: one or more, each typed bare, escaped as Markdown
# escapes it, `\_`, or as the LaTeX reader writes `\_`, an underscore and a NUL after it.
_UNDERSCORES = r"(?:\\?_\x00?)+"
# A word as this reading takes it: parts joined by underscores or by a dot.
_NAME = re.compile(rf"(?<![^\W_]){_PART}(?:(?:{_UNDERSCORES}|\.){_PART})*")
# What the name is with the backslashes and NULs of its underscores taken out.
_TYPED = re.compile(r"\\(?=_)|\x00")
# camelCase from two small letters: `ckdFlag`, and not `eGFR`, `mRNA` or `lncRNA`.
_CAMEL = re.compile(r"[a-z]{2,}[A-Z][a-z]")
# The last part of a file's name: `.py`, `.csv`, `.sas7bdat`.
_EXTENSION = re.compile(r"(?=[0-9]*[A-Za-z])[A-Za-z0-9]{1,10}")
# A backslash that separates the folders of a path: one before a letter or a digit, which
# Markdown escapes nothing with.
_FOLDER = re.compile(r"\\(?=[^\W_])")
# How far either side of a word its run of characters is looked at for a path.
_REACH = 200
# In Markdown, what is not printed: the opening or closing line of a fenced div, an HTML
# tag, a pandoc attribute holding an `=` (`{custom-style="Body_Text"}`) and a TeX command
# with its arguments.
_UNPRINTED = re.compile(
    r"^[ \t]*:{3,}[^\n]*"
    r"|</?[A-Za-z][A-Za-z0-9-]*(?:[ \t][^<>\n]*)?/?>"
    r"|\{[^{}\n]*=[^{}\n]*\}"
    r"|\\[A-Za-z]+(?:\[[^\[\]\n]*\])*(?:\{[^{}\n]*\})*",
    re.MULTILINE,
)

KEY = "key"
VARIABLE = "variable"
SNAKE = "snake"


@dataclass(frozen=True)
class Prose:
    """One manuscript file as this reading takes it: `printed` is the text G14 reads as
    sentences and headings, NUL elsewhere; `code` is the text of its code spans, NUL
    elsewhere. Both have the file's length, so an offset is the file's."""

    path: Path
    text: str
    printed: str
    code: str
    line_of: Callable[[int], int]


@dataclass(frozen=True)
class Names:
    """What the analysis and the dictionary name: the keys of the results, each variable's
    label by its name, and the words the paper keeps although they look like code."""

    keys: frozenset[str] = frozenset()
    labels: dict[str, str] = field(default_factory=dict)
    kept: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _Use:
    place: int
    offset: int
    length: int
    prose: Prose
    in_code: bool


@dataclass
class _Found:
    name: str
    kind: str
    label: str | None
    uses: list[_Use] = field(default_factory=list)


def code_shaped(name: str) -> bool:
    """Whether a key or a dictionary name is one no word of the prose is written like: with
    an underscore or a dot in it, or in camelCase from two small letters."""
    return "_" in name or "." in name or bool(_CAMEL.match(name))


def _exact(name: str, names: Names) -> tuple[str, str | None] | None:
    """What a word is that is exactly a dictionary's variable or a key of the results, and
    the variable's label; None for any other word. A variable before a key: its label says
    what to write instead."""
    if not code_shaped(name):
        return None
    if name in names.labels:
        return VARIABLE, names.labels[name]
    if name in names.keys or (name.startswith(RESULTS) and name[len(RESULTS) :] in names.keys):
        return KEY, None
    return None


def _runs_on(text: str, at: int) -> bool:
    """Whether the character at `at` belongs to the run a word stands in: anything but a
    blank, and a NUL only where the LaTeX reader put it after an underscore."""
    char = text[at]
    if char == NUL:
        return at > 0 and text[at - 1] == "_"
    return not char.isspace()


def _in_a_path(text: str, start: int, end: int) -> bool:
    """Whether the word from `start` to `end` is part of a path or an address: its run of
    characters holds a slash, an `@` or a backslash between two folders."""
    left = start
    while left > max(0, start - _REACH) and _runs_on(text, left - 1):
        left -= 1
    right = end
    while right < min(len(text), end + _REACH) and _runs_on(text, right):
        right += 1
    run = text[left:right]
    return "/" in run or "@" in run or bool(_FOLDER.search(run))


def _parts(word: str, start: int) -> list[tuple[int, str]]:
    """The parts of a dotted word as typed, each with its offset."""
    parts, at = [], start
    for part in word.split("."):
        parts.append((at, part))
        at += len(part) + 1
    return parts


def _names_in(
    text: str, names: Names, *, in_code: bool
) -> Iterable[tuple[int, int, str, str, str | None]]:
    """Each name from the code in `text`: its offset, its length as typed, the name, what
    it is and the variable's label. In a code span only a key or a dictionary's variable."""
    for found in _NAME.finditer(text):
        typed = found.group()
        name = _TYPED.sub("", typed)
        if not code_shaped(name) or name in names.kept:
            continue
        if _in_a_path(text, found.start(), found.end()):
            continue
        exact = _exact(name, names)
        if exact is not None:
            yield found.start(), len(typed), name, *exact
            continue
        parts = _parts(typed, found.start())
        if len(parts) > 1 and _EXTENSION.fullmatch(parts[-1][1]):
            continue  # a file's name: `ckd_flag.csv`
        for at, part in parts:
            plain = _TYPED.sub("", part)
            if "_" not in plain or plain in names.kept:
                continue
            exact = _exact(plain, names)
            if exact is not None:
                yield at, len(part), plain, *exact
            elif not in_code and any(char.isalpha() for char in plain):
                yield at, len(part), plain, SNAKE, None


def _unprinted(printed: str) -> str:
    """`printed` with what Markdown does not print taken out as NUL: `_UNPRINTED`."""
    return _UNPRINTED.sub(lambda found: re.sub(r"[^\n]", NUL, found.group()), printed)


def judge_code_names(passages: Iterable[Prose], names: Names, stage: str | None = None) -> Report:
    """The findings of this reading over the whole manuscript in the order it is read: one
    for each name, at its first use, with how often it is used. A warning, and a failure at
    the submission stage."""
    found: dict[str, _Found] = {}
    for place, prose in enumerate(passages):
        uses = [
            (offset, length, name, kind, label, in_code)
            for text, in_code in ((_unprinted(prose.printed), False), (prose.code, True))
            for offset, length, name, kind, label in _names_in(text, names, in_code=in_code)
        ]
        for offset, length, name, kind, label, in_code in sorted(uses, key=lambda use: use[0]):
            entry = found.setdefault(name, _Found(name, kind, label))
            entry.uses.append(_Use(place, offset, length, prose, in_code))
    severity = FAIL if stage == SUBMISSION else WARN
    return Report(tuple(_finding(entry, severity) for entry in found.values()))


def _finding(entry: _Found, severity: str) -> Finding:
    first = entry.uses[0]
    prose = first.prose
    times = len(entry.uses)
    where = "a code span" if first.in_code else "the prose"
    if entry.kind == VARIABLE:
        said = (f"{entry.name!r} is the name of a variable in the data dictionary, which "
                f"labels it {entry.label!r}")  # fmt: skip
        hint = f"write what it is, as the label says: {entry.label!r}"
    elif entry.kind == KEY:
        bare = entry.name.removeprefix(RESULTS)
        said = f"{entry.name!r} is a key of the results the analysis wrote"
        hint = (f"write what the value is, and bind the value itself as "
                f"`{{{{results.{bare}}}}}`")  # fmt: skip
    else:
        said = f"{entry.name!r} is written as a name in code is, with underscores"
        hint = (
            "write what it is in words; a subscript is written `C~max~`, or in maths. "
            "Put a function's or a package's name in a code span"
        )
    count = "once" if times == 1 else f"{times} times"
    return Finding(
        gate=GATE,
        code=CODE,
        severity=severity,
        message=f"{said}, and the reader has never seen it: it is used {count}, first in {where}",
        path=prose.path,
        line=prose.line_of(first.offset),
        context=context(prose.text, first.offset, first.length),
        hint=f"{hint}. If the paper is right to print it, list it under `language: "
        "code_names_kept:` in paper.yaml",
    )
