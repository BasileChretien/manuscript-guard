"""Whether a text names a model, as G4's AI-use check reads it (DESIGN.md, "The AI-use
statement names the models the records hold", "How a statement names a model").

A name and the text are read alike, as words and their parts, with upper and lower case
one. A **word** is a run of letters and digits, and a point or a hyphen between two digits
does not end it: "4.5", "4-5" and "2.5-72b" are each one word. Its **parts** are what is left
when it is cut between a letter and a digit and at each point or hyphen in it, so `gpt4o`
is "gpt", "4", "o" and "4.5" and "4-5" are each "4", "5": providers write one version both
ways. The text names the model where the name's parts stand in it in a row, from the first
part of one of its words to the last part of one of its words, and where two digits the name
joins with a point are in one word of the text.

A model has several names (`names_of`): the one asked for and the one the provider reported,
each with its provider, a date stamped at its end, a final `latest` and a local model's tag
taken away, alone or together.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

#: A word: letters and digits, a point or a hyphen between two digits inside it. `[^\W_]` is
#: a letter or a digit of any script.
_WORD = re.compile(r"[^\W_](?:[^\W_]|(?<=\d)[.\-](?=\d))*")
#: Where a word is cut: between a letter and a digit, either way round, and at a point or a
#: hyphen, which in a word stands only between two digits.
_CUT = re.compile(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)|[.\-]")


def _fold(text: str) -> str:
    """Upper and lower case as one."""
    return text.casefold()


@dataclass(frozen=True)
class Part:
    """One part of a word, folded, and where it stands in its word."""

    text: str
    #: The part opens its word.
    first: bool
    #: The part closes its word.
    last: bool
    #: A point joins it to the part before it, in the same word.
    after_point: bool


def _plain(text: str) -> str:
    """`text` with each full-width or half-width form as its plain one, and each character
    of category So, superscript or subscript as a space, so that "™" or a footnote's "¹"
    ends the name before it rather than join it as "TM" or "1" (rounds 2 and 3)."""
    out = []
    for c in unicodedata.normalize("NFC", text):
        tag = unicodedata.decomposition(c).split(" ", 1)[0]
        if tag in ("<wide>", "<narrow>"):
            out.append(unicodedata.normalize("NFKC", c))
        elif tag in ("<super>", "<sub>") or unicodedata.category(c) == "So":
            out.append(" ")
        else:
            out.append(c)
    return "".join(out)


def parts(text: str) -> list[Part]:
    """The parts of every word of `text`, in order, read as `_plain` writes it: a name typed
    in full-width letters and digits, as a Japanese input method types them ("ＧＰＴ－５．１"),
    is the name typed plainly (round 1 of the code)."""
    found: list[Part] = []
    for word in _WORD.finditer(_plain(text)):
        token = word.group()
        # Each piece with whether a point stands just before it: a letter-digit cut and a
        # hyphen mark nothing.
        pieces: list[tuple[str, bool]] = []
        at, point = 0, False
        for cut in _CUT.finditer(token):
            if cut.start() > at:
                pieces.append((token[at : cut.start()], point))
                point = False
            point = point or cut.group() == "."
            at = cut.end()
        if at < len(token):
            pieces.append((token[at:], point))
        last = len(pieces) - 1
        found += [Part(_fold(piece), index == 0, index == last, after)
                  for index, (piece, after) in enumerate(pieces)]  # fmt: skip
    return found


def names(text: str, name: str) -> bool:
    """Whether `text` names `name` by the rule above."""
    return bool(name.strip()) and _found(parts(text), parts(name))


def _found(said: list[Part], wanted: list[Part]) -> bool:
    if not wanted:
        return False
    size = len(wanted)
    for start in range(len(said) - size + 1):
        if not said[start].first or not said[start + size - 1].last:
            continue
        if all(said[start + k].text == wanted[k].text for k in range(size)) and all(
            not said[start + k].first for k in range(1, size) if wanted[k].after_point
        ):
            return True
    return False


#: A date a provider stamps at the end of a version, after a hyphen, an underscore, a point,
#: a colon or an at sign: eight digits that begin 20, or four, two and two joined by hyphens.
_DATE = re.compile(r"[-_.:@](?:20\d{6}|20\d{2}-\d{2}-\d{2})$")
#: A final part `latest`, with what stands before it.
_LATEST = re.compile(r"[^\w]+latest$|_latest$", re.IGNORECASE)
#: A local model's tag, after a colon: `llama3.1:8b-instruct-q4_K_M`.
_TAG = re.compile(r":[^:/]*$")


def _shorter(name: str) -> set[str]:
    """`name` with one of the four things taken away, each that applies."""
    out = set()
    if "/" in name:
        out.add(name.rsplit("/", 1)[1])
    for pattern in (_DATE, _LATEST, _TAG):
        cut = pattern.sub("", name)
        if cut != name:
            out.add(cut)
    return {found for found in out if found.strip()}


def names_of(*spellings: str | None) -> tuple[str, ...]:
    """Every name of a model spelt as `spellings`: each, and each with its provider, a date
    stamp, a final `latest` and a tag taken away, alone or together. In a stable order."""
    seen: dict[str, None] = {}
    todo = [s.strip() for s in spellings if s and s.strip()]
    while todo:
        name = todo.pop(0)
        if name in seen:
            continue
        seen[name] = None
        todo.extend(sorted(_shorter(name) - set(seen)))
    return tuple(seen)


def named(text: str, spellings: Iterable[str | None]) -> bool:
    """Whether `text` names the model spelt as `spellings`, by any of its names."""
    said = parts(text)
    return any(_found(said, parts(name)) for name in names_of(*spellings))


__all__ = ["Part", "named", "names", "names_of", "parts"]
