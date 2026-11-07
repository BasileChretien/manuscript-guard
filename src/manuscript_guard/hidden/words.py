"""What a text says that a person does not see: zero-width characters inside a word, and
words written to a model that reads it.

Both are read in any text, wherever a file holds it: the printed words of a Word document,
its notes and headers, a picture's alternative text, its properties. They are rules of the
characters and the words, not of how the text looks, which `hidden.word` reads.

**Zero-width characters.** U+200B (zero-width space), U+200C (zero-width non-joiner),
U+200D (zero-width joiner), U+2060 (word joiner) and U+FEFF (zero-width no-break space)
print nothing. Between two letters of the Latin, Greek or Cyrillic script, where none of
them has a use, they split a word so that a search for it fails, or carry a message coded
in the choice of character. Elsewhere they are left alone: the joiners belong in Arabic,
Persian and the scripts of India, and in an emoji. The tag characters, U+E0000 to U+E007F,
print nothing and each stands for an ASCII letter that a model may read; they are read
wherever they stand, except as the tags of a flag (U+1F3F4 and tags ending with U+E007F).

**Words to a model** are the rules under `to_a_model` in `data/ai_writing.yaml`: words that
tell a model reading the text what to do, "ignore all previous instructions", "give a
positive review". They are looked for in the text as a model reads it, with zero-width
characters and soft hyphens taken out, tag characters read as their letters, and spaces of
any kind folded to one.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DATA = Path(__file__).parent.parent / "data" / "ai_writing.yaml"

#: The characters that print nothing and are no part of a Latin, Greek or Cyrillic word.
ZERO_WIDTH = frozenset("\u200b\u200c\u200d\u2060\ufeff")
#: A soft hyphen prints only where the line breaks: taken out before the words are read,
#: and never reported, since a word processor puts them in words as a hint.
SOFT_HYPHEN = "\u00ad"
_TAGS = range(0xE0000, 0xE0080)
_CANCEL_TAG = 0xE007F
_BLACK_FLAG = "\U0001f3f4"
#: The scripts in which no zero-width character has a use inside a word.
_SCRIPTS = frozenset({"LATIN", "GREEK", "CYRILLIC"})
_SPACE = re.compile(r"\s+")
#: Two words with any space between them, a tab or a line break among them.
_TWO_WORDS = re.compile(r"\S\s+\S")
#: The characters that print nothing and are no format character either, which Unicode
#: says to pass over where they cannot be shown (Default_Ignorable_Code_Point): a
#: grapheme joiner, the Hangul fillers, the variation selectors, the Mongolian free
#: variation selectors.
_IGNORABLE = frozenset(chr(code) for code in (
    0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180C, 0x180D, 0x180F, 0x3164, 0xFFA0,
    *range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0),
))  # fmt: skip
#: How much of a word a reason quotes.
_WORD_SHOWN = 60


@dataclass(frozen=True)
class Spot:
    """A place in a text: where it starts and ends, what was found (`zero-width`, or the id
    of the rule of words to a model), and what it says as a model reads it."""

    start: int
    end: int
    rule: str
    said: str
    why: str


@lru_cache(maxsize=1)
def rules() -> tuple[tuple[str, re.Pattern[str], str], ...]:
    """The rules of words to a model, each its id, its pattern and why it is reported."""
    document = yaml.safe_load(DATA.read_text(encoding="utf-8")) or {}
    return tuple(
        (rule["id"], re.compile(rule["pattern"]), rule["why"])
        for rule in document.get("to_a_model", ())
    )


def _lettered(character: str) -> bool:
    if not unicodedata.category(character).startswith("L"):
        return False
    return unicodedata.name(character, "").split(" ", 1)[0] in _SCRIPTS


def _is_tag(character: str) -> bool:
    return ord(character) in _TAGS


def _spelt(tags: str) -> str:
    """What a run of tag characters spells, a letter for each that stands for one."""
    return "".join(chr(ord(c) - 0xE0000) for c in tags if 0x20 <= ord(c) - 0xE0000 < 0x7F)


def _a_flag(text: str, start: int, end: int) -> bool:
    """Whether the tags from `start` to `end` are a flag's: after a black flag, ending
    with the cancel tag, each but the last standing for a printable letter."""
    tags = text[start:end]
    return (
        start > 0
        and text[start - 1] == _BLACK_FLAG
        and ord(tags[-1]) == _CANCEL_TAG
        and all(0x20 <= ord(c) - 0xE0000 < 0x7F for c in tags[:-1])
    )


def _word_around(text: str, start: int, end: int) -> tuple[int, int]:
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] in ZERO_WIDTH):
        start -= 1
    while end < len(text) and (text[end].isalnum() or text[end] in ZERO_WIDTH):
        end += 1
    return start, end


def zero_width_in(text: str) -> list[Spot]:
    """Each word of `text` a zero-width character is inside, once, and each run of tag
    characters that is no flag's."""
    spots: list[Spot] = []
    at = 0
    while at < len(text):
        character = text[at]
        if character not in ZERO_WIDTH and not _is_tag(character):
            at += 1
            continue
        tagged = _is_tag(character)
        end = at
        while end < len(text) and (_is_tag(text[end]) if tagged else text[end] in ZERO_WIDTH):
            end += 1
        if tagged and not _a_flag(text, at, end):
            spelt = _spelt(text[at:end])
            shown = spelt if len(spelt) <= _WORD_SHOWN else spelt[: _WORD_SHOWN - 3] + "..."
            spots.append(Spot(at, end, "zero-width", spelt,
                              f"{end - at} tag character(s), which spell {shown!r}"))  # fmt: skip
        elif not tagged and at > 0 and end < len(text):
            if _lettered(text[at - 1]) and _lettered(text[end]):
                start, end = _word_around(text, at, end)
                spots.append(_inside_a_word(text[start:end], start, end))
        # Past the whole word once it is said, so that each character is read a bounded
        # number of times however many zero-width characters a word holds.
        at = end
    return spots


def _inside_a_word(written: str, start: int, end: int) -> Spot:
    codes = ", ".join(sorted({f"U+{ord(c):04X}" for c in written if c in ZERO_WIDTH}))
    word = "".join(c for c in written if c not in ZERO_WIDTH)
    shown = word if len(word) <= _WORD_SHOWN else word[: _WORD_SHOWN - 3] + "..."
    return Spot(start, end, "zero-width", word, f"{codes} inside the word {shown!r}")


def as_read(text: str) -> tuple[str, list[int]]:
    """`text` as a model reads it, and where each of its characters came from in `text`:
    every character that prints nothing taken out (a format character, U+200B and the
    other zero-width ones, the soft hyphen and the marks of direction among them, and
    those Unicode says to pass over), tag characters read as their letters, each
    character in its compatibility form (NFKC: a full-width letter as the letter), and
    each run of spaces one space (the security review of #574: a mark of direction
    inside a word, or full-width letters, hid the words from the rules)."""
    out: list[str] = []
    origin: list[int] = []
    for at, character in enumerate(text):
        if _is_tag(character):
            character = _spelt(character)
            if not character:
                continue
        elif ord(character) > 0x7F:
            if character in _IGNORABLE or unicodedata.category(character) == "Cf":
                continue
            character = unicodedata.normalize("NFKC", character)
            if len(character) != 1:
                out.extend(character)
                origin.extend([at] * len(character))
                continue
        if character.isspace():
            if out and out[-1] == " ":
                continue
            character = " "
        out.append(character)
        origin.append(at)
    return "".join(out), origin


def to_a_model_in(text: str) -> list[Spot]:
    """Each place in `text` where words tell a model reading it what to do."""
    if not text or len(text) < 8:
        return []
    read, origin = as_read(text)
    spots: list[Spot] = []
    for rule, pattern, why in rules():
        for match in pattern.finditer(read):
            if match.end() <= match.start():
                continue
            spots.append(Spot(origin[match.start()], origin[match.end() - 1] + 1, rule,
                              _SPACE.sub(" ", match.group(0)).strip(), why))  # fmt: skip
    return sorted(spots, key=lambda spot: (spot.start, spot.end))


def printable(text: str) -> str:
    """`text` with each character that does not print written as its escape: a control
    character, a format character, a line or paragraph separator. What a file names, a
    part, a style, a note, is said with it, so that it cannot move a terminal's cursor,
    turn the direction of the text or start a line of its own (the security review of
    #574)."""
    if text.isprintable():
        return text
    return "".join(character if character.isprintable()
                   else character.encode("unicode_escape").decode("ascii")
                   for character in text)  # fmt: skip


def worth_reading(text: str) -> bool:
    """Whether `text` could hold anything these rules find: a space of any kind between
    words (a tab, a line break: round 1 of #574), or a character past the ones ASCII has.
    Most of a Word file's attribute values hold neither."""
    return bool(text) and (not text.isascii() or _TWO_WORDS.search(text) is not None)
