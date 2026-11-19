"""The key `--json` gives each finding, which a run of the tool can be paired with another by.

A key is `gate|code|subject|digest` (Basile, 2026-11-19):

- the **subject** is what the finding is about, given by the gate that makes it: a number as
  typed, a short form and its scope, a rule and the words it matched, a reference entry's
  label. Never the message, which is reworded, nor the context, a window of characters
  around the place that a line moved or a paragraph re-wrapped changes.
- the **digest** stands for the sentence the finding stands in, with its part of the paper
  (abstract, main or supplement): the first 12 hex characters of SHA-256 of
  `part|sentence`, the sentence normalised (`normalised`). The sentence is cut by a copy of
  the sentence splitter frozen here (`_STOP`, `_BLOCK`), so that a change to the splitter
  the gates read with moves no key.
- a **paper-level** code, one about a form or a word over the whole paper (`PAPER_LEVEL`),
  has the digest `-`: fixing the first use of a short form moves its finding to the next
  use, and the finding is the same one.

Two findings of one sentence with the same subject are told apart by an ordinal among them,
counted by their offset in the text, `t(29)=2.05#1` and `#2` (`assign`). The ordinal counts
the findings whose key is the same, and nothing else: a number added in another sentence
moves no key. Two identical sentences of one part have one digest, though, so the findings
on one subject in both are numbered together, by their offsets, which in `check` are taken
in different files. A finding added to one of them may then move the other's key.

A code whose finding names no subject falls back to a digest of its context (of its message
where it has none), each path the finding names and every folder above it taken out whole,
then any other absolute path, and is marked `"key_from": "context"`.
`tests/test_finding_keys.py` holds which codes may.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: The parts of a paper a digest is taken in.
ABSTRACT, MAIN, SUPPLEMENT = "abstract", "main", "supplement"
#: The digest of a paper-level finding, and the subject of a finding that stands for a list.
NONE = "-"
#: What `key_from` says of a key made from the context.
FROM_CONTEXT = "context"

#: The codes about a form or a word over the whole paper, one finding for each form (and for
#: G14 each scope), whose key has no digest (Basile, 2026-11-19). `ai-cadence` is a rate
#: over the whole prose, keyed by its rule.
PAPER_LEVEL = frozenset({
    "abbreviation-undefined", "abbreviation-used-before-defined", "abbreviation-unused",
    "spelling-variant", "spelling-mixed", "spelling-not-as-declared",
    "notation-p-symbol", "notation-sign-spacing", "notation-interval", "notation-percent",
    "notation-unit", "notation-space-missing",
    "code-name-in-prose", "term-avoided", "ai-cadence",
})  # fmt: skip

# ---------------------------------------------------------------- the frozen splitter
# A copy of `claims._STOP`, `claims._BLOCK` and `claims._LETTER` as they stood at 7bda66a.
# Never edited to follow those: a key that moves with the splitter pairs nothing.

_STOP = re.compile(
    r"[.!?][)\]\"'*_\N{RIGHT SINGLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}]*"
    r"\s+(?![\sa-z])"
)
_BLOCK = re.compile(r"\n[ \t\x00]*(?:\n|#|>|[-*+][ \t]|\d+[.)][ \t]|\|)")
_FRONT = re.compile(r"\A---[ \t]*\n(?:.*?\n)?(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.DOTALL)
#: What marks where a part of the paper begins: a Markdown heading, a LaTeX sectioning
#: command or abstract environment, or a line that is a heading's name alone, as a Word
#: paper's or a PDF's text gives one.
_MARK = re.compile(
    r"^[ \t]*#{1,6}[ \t]+(?P<md>[^\n]*)$"
    r"|\\(?:sub)*section\*?\{(?P<tex>[^}\n]*)\}"
    r"|(?P<env>\\(?:begin|end)\{abstract\})"
    r"|^[ \t]*[*_]*(?P<alone>abstract|summary|introduction|background|methods?|"
    r"materials and methods|results|discussion|conclusions?|references)[*_.:]*[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
_NUMBERED = re.compile(r"^[\s*_\d.)\\]*")


@lru_cache(maxsize=32)
def _cuts(text: str) -> tuple[int, ...]:
    """Where each sentence of `text` starts, as the frozen splitter cuts it, the text's end
    last. A line of the front matter is a sentence of its own."""
    cuts = {0, len(text)}
    cuts.update(found.end() for found in _STOP.finditer(text))
    cuts.update(found.start() + 1 for found in _BLOCK.finditer(text))
    front = _FRONT.match(text)
    if front is not None:
        cuts.update(at + 1 for at in range(front.end()) if text[at] == "\n")
    return tuple(sorted(cuts))


def sentence_at(text: str, offset: int) -> str:
    """The sentence of `text` that `offset` stands in, as the frozen splitter cuts it."""
    cuts = _cuts(text)
    offset = min(max(offset, 0), len(text))
    low, high = 0, len(cuts) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if cuts[middle] <= offset:
            low = middle
        else:
            high = middle
    return text[cuts[low] : cuts[high]]


@lru_cache(maxsize=32)
def _marks(text: str) -> tuple[tuple[int, bool], ...]:
    """Where each part of `text` begins, with whether it is the abstract."""
    found = []
    for mark in _MARK.finditer(text):
        if mark["env"]:
            found.append((mark.start(), mark["env"].lower().startswith("\\begin")))
            continue
        title = _NUMBERED.sub("", mark["md"] or mark["tex"] or mark["alone"] or "")
        found.append((mark.start(), title.strip("*_ \t").casefold().startswith(ABSTRACT)
                      or title.strip("*_ \t.:").casefold() == "summary"))  # fmt: skip
    return tuple(found)


def part_of(text: str, offset: int, supplementary: bool = False) -> str:
    """The part of the paper `offset` of `text` stands in: the supplement where the file is
    one, the abstract under a heading that names it, the main text otherwise."""
    if supplementary:
        return SUPPLEMENT
    abstract = False
    for start, opens in _marks(text):
        if start > offset:
            break
        abstract = opens
    return ABSTRACT if abstract else MAIN


def in_supplement(path: Path | str | None) -> bool:
    """Whether a manuscript file is of the supplement: one under `manuscript/supplementary/`,
    where the build takes the supplement from."""
    parts = Path(path).parts if path is not None else ()
    if "manuscript" not in parts:
        return False
    at = len(parts) - 1 - parts[::-1].index("manuscript")
    return "supplementary" in parts[at + 1 : -1]


# ------------------------------------------------------------------- the normal form

_MINUS = dict.fromkeys(map(ord, "−‐‑‒–—―﹣－"), "-")
_QUOTES = {**dict.fromkeys(map(ord, "‘’‚‛′`´"), "'"),
           **dict.fromkeys(map(ord, "“”„‟″«»"), '"')}  # fmt: skip
#: What a sentence's digest does not see: spaces and blanked text, the characters of
#: emphasis, a soft hyphen and the characters of no width.
_UNSEEN = re.compile("[\\s\x00*_­​‌‍⁠﻿]+")
_BROKEN = re.compile(r"-[ \t]*\r?\n[ \t\x00]*")
_DASHES = re.compile(r"-{2,}")


def normalised(sentence: str) -> str:
    """`sentence` as its digest reads it: NFKC and case folded, a hyphen that ends a line
    joined to the word it breaks, one form for every minus and dash and one for each kind of
    quotation mark, and no spaces, emphasis, soft hyphens or characters of no width."""
    said = unicodedata.normalize("NFKC", sentence).casefold()
    said = _BROKEN.sub("", said.translate(_MINUS))
    said = _DASHES.sub("-", said.translate(_QUOTES))
    return _UNSEEN.sub("", said)


def digest(part: str, sentence: str) -> str:
    """The digest of `sentence` in `part`, 12 hex characters."""
    said = f"{part}|{normalised(sentence)}".encode()
    return hashlib.sha256(said).hexdigest()[:12]


def placed(text: str, offset: int, supplementary: bool = False) -> str:
    """The digest of the sentence `offset` of `text` stands in, with its part."""
    return digest(part_of(text, offset, supplementary), sentence_at(text, offset))


def in_table(header: Sequence, row: str) -> str:
    """The digest of a table's row as a finding's sentence: the row with its table's header
    row, so that one row in two tables of other headers is two sentences (`keys`)."""
    return digest(MAIN, " | ".join(getattr(cell, "text", str(cell)) for cell in header)
                  + "\n" + row)  # fmt: skip


_SPACES = re.compile(r"\s+")
#: An absolute path in a message, which names the folder of one run on one machine: what a
#: key from the context does not read.
_ABSOLUTE = re.compile(r"(?:\b[A-Za-z]:[\\/]|(?<![\w.~])/(?=[^\s/]))[^\s'\"`,;()<>|]*")


def subject(said: str) -> str:
    """A subject as a key holds it: its spaces made one, and no `|`, which parts a key."""
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", said)).strip().replace("|", "/")


def statistic(typed: str) -> str:
    """A number or a statistic as typed, as a subject: no spaces, one minus, a point for a
    raised one, in lower case, so that "t(29) = 2.05" and "t(29)=2.05" are one."""
    said = unicodedata.normalize("NFKC", typed).translate(_MINUS).replace("·", ".")
    return _UNSEEN.sub("", said.replace("\x00", " ")).casefold().replace("|", "/")


class Notice(str):
    """A note on what was read, said as a sentence, that knows the file or the part it is
    about, which its key names (`subject`): a string wherever one is used."""

    subject: str

    def __new__(cls, said: str, subject: str = "") -> Notice:
        made = super().__new__(cls, said)
        made.subject = subject
        return made

    def __getnewargs__(self) -> tuple[str, str]:  # type: ignore[override]
        # So that a copy, or a pickle, keeps what the note is about.
        return str(self), self.subject


# ------------------------------------------------------------------------- the keys


@dataclass(frozen=True)
class Keyed:
    """What a finding's key is made of: its gate and code, its subject (None where the gate
    gave none), the digest of its sentence (None where it has none), and its offset in the
    text, which orders two findings of one sentence; and what the key falls back on."""

    gate: str
    code: str
    subject: str | None
    sentence: str | None = None
    at: int | None = None
    context: str | None = None
    message: str = ""
    #: The paths a key from the context leaves out, longest first (`paths_of`).
    paths: tuple[str, ...] = ()

    @property
    def from_context(self) -> bool:
        return self.subject is None

    def parts(self) -> tuple[str, str, str, str]:
        if self.subject is None:
            said = self.context or self.message
            for path in (*self.paths, *_INSTALLED):
                said = _bounded(path).sub("", said)
            said = _ABSOLUTE.sub("", said)
            return self.gate, self.code, "~" + digest(NONE, said), NONE
        sentence = NONE if self.code in PAPER_LEVEL or not self.sentence else self.sentence
        return self.gate, self.code, subject(self.subject) or NONE, sentence


def paths_of(path: Path | str | None) -> tuple[str, ...]:
    """`path` and each folder above it, the drive or the root aside, as the platform writes
    them and with forward slashes, longest first: what a key from a finding's context leaves
    out, whole, a folder whose name holds a space included. The project's folder is among
    them wherever the finding's file is in it."""
    if path is None:
        return ()
    path = Path(path)
    found = {form for one in (path, *path.parents) if one != Path(one.anchor)
             for form in (str(one), one.as_posix()) if form}  # fmt: skip
    return tuple(sorted(found, key=len, reverse=True))


@lru_cache(maxsize=256)
def _bounded(path: str) -> re.Pattern[str]:
    """`path` where it stands whole in a message: after the start, a space, a quotation mark
    or a bracket, and before a separator, a quotation mark, a bracket, a space, a stop of a
    clause or the end, so that the folder `/data` is not cut out of `analysis/data/raw.csv`."""
    return re.compile(r"(?<![^\s'\"`(\[{<])" + re.escape(path)
                      + r"(?=[\\/\s'\"`)\]}>,;:]|\.(?:\s|\Z)|\Z)")  # fmt: skip


#: Where the tool runs from, and each folder above it: a message that names the tool's own
#: files names a folder that moves between two builds of it, as the corpus runs each commit.
_INSTALLED = paths_of(Path(__file__).resolve().parent)


def key(keyed: Keyed, ordinal: int | None = None) -> str:
    gate, code, said, sentence = keyed.parts()
    return "|".join((gate, code, said if ordinal is None else f"{said}#{ordinal}", sentence))


def assign(found: Sequence[Keyed]) -> list[str]:
    """The key of each of `found`, in order: two of one sentence with one subject numbered
    by their offset, from 1. A key with no sentence is never numbered."""
    plain = [key(one) for one in found]
    groups: dict[str, list[int]] = {}
    for index, said in enumerate(plain):
        groups.setdefault(said, []).append(index)
    out = list(plain)
    for said, indices in groups.items():
        if len(indices) < 2 or said.endswith("|" + NONE):
            continue
        ordered = sorted(indices, key=lambda i: (found[i].at is None, found[i].at or 0, i))
        for ordinal, index in enumerate(ordered, 1):
            out[index] = key(found[index], ordinal)
    return out


def keyed_json(found: Sequence[Keyed], dicts: list[dict]) -> list[dict]:
    """`dicts`, the JSON of each of `found`, each with its key, and `key_from` where the key
    is made from the context."""
    return [{**said, "key": one_key, **({"key_from": FROM_CONTEXT} if one.from_context else {})}
            for one, said, one_key in zip(found, dicts, assign(found), strict=True)]  # fmt: skip


def shared(dicts: Sequence[dict]) -> list[str]:
    """Each key two different findings of `dicts` share, where both stand in a sentence:
    what an ordinal is there to prevent. Two findings are different where anything but
    their key differs."""
    seen: dict[str, dict] = {}
    clashes = []
    for said in dicts:
        one_key = said.get("key", "")
        if one_key.endswith("|" + NONE) or said.get("key_from"):
            continue
        rest = {name: value for name, value in said.items() if name != "key"}
        if one_key in seen and seen[one_key] != rest and one_key not in clashes:
            clashes.append(one_key)
        seen.setdefault(one_key, rest)
    return clashes
