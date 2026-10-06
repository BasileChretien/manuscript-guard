"""G14, its third reading — one English.

A paper is in British or in American spelling, and `paper.yaml` says which. A manuscript
written by several hands, or revised from a draft in the other spelling, ends up with
"colour" on one page and "color" on the next, and a copy-editor finds each one by eye. This
reading finds them by list: the words one usage writes and the other does not, from VarCon
(Kevin Atkinson and Benjamin Titze), cut down to what a check needs by
`tools/derive_spelling_variants.py`.

Three findings, all warnings:

* `spelling-variant`: a word in the other usage's spelling, once for the word, where it
  first stands, with how often.
* `spelling-not-as-declared`: the manuscript is mostly in the other spelling. One finding
  in place of a hundred, because the likelier mistake is the line in `paper.yaml`.
* `spelling-mixed`: a British paper that writes both "organise" and "randomized". British
  usage takes either ending, Oxford's being `-ize`, and one paper takes one.

**The list decides, and it is cautious.** A word is reported only where no line of VarCon
accepts it in the paper's English, so "program", "meter", "fetus", "sulfur" and "judgment"
are never reported in a British paper: each is accepted there, in one sense or as a
variant. A word the list does not hold is not read at all, and it is a list of general
English: it has "haemoglobin" and not "hyperglycaemia". Where it is wrong for a field, the
project lists the spellings it keeps under `language: accepted_spellings:`.

**A name keeps its spelling.** Only a word in lower case is read, or one with a capital
where a sentence, a heading, a list item or a table cell starts. "World Health
Organization" and "Centers for Disease Control" are written as they call themselves, in
any paper.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.vocabulary import Passage, context, own_words
from manuscript_guard.text.masking import NUL

GATE = "G14"
DATA = Path(__file__).parent.parent / "data" / "spelling_variants.tsv"

BRITISH = "en-GB"
AMERICAN = "en-US"
_NAMES = {BRITISH: "British", AMERICAN: "American"}
#: The kinds of row that are each usage's own.
_KINDS = {BRITISH: ("gb", "ise"), AMERICAN: ("us",)}

#: From this many spellings of the other usage, when they are used more than the paper's
#: own, the manuscript is taken to be in the other English and one finding says so.
MANY = 5
#: How many words that finding lists.
LISTED = 12
#: How many words the finding on the two endings quotes for each.
EXAMPLES = 5

_WORD = re.compile(r"[^\W\d_]+")
# What may stand between the start of a sentence and its first word.
_OPENING = " \t*_\"'(["
_OPENING += "\N{LEFT DOUBLE QUOTATION MARK}\N{LEFT SINGLE QUOTATION MARK}"
# After one of these a capital is the sentence's, or the table cell's.
_ENDS = ".?!:|"
# A list item's marker or a heading's, with what may stand before the first word.
_MARKER = re.compile(r"(?:[-+*]|\d{1,9}[.)]|#{1,6})[ \t][" + re.escape(_OPENING) + "]*")
#: How far back the start of a sentence is looked for.
_REACH = 200
# Markup the other readings have no reason to hide and this one does, since CSS and HTML
# are written in American: `<span style="color:red">`. An HTML tag; a block of attributes
# that holds a key, `{fig-align="center"}`, which the masking hides only where it opens
# with `.` or `#`; the label of a reference link and the line that defines it, which a
# footnote's text is not. Each alternative stops at the next character that could open
# another of its kind, so a line of unclosed ones is read once. A LaTeX command is not
# here: `check` fails a manuscript that holds one, whatever its spelling.
_MARKUP = re.compile(
    r"</?[A-Za-z][^<>\n]*>"
    r"|\{[^{}=\n]*=[^{}\n]*\}"
    r"|\]\[[^\]\n]*\]"
    r"|^[ ]{0,3}\[(?!\^)[^\]\n]+\]:[^\n]*",
    re.MULTILINE,
)


@lru_cache(maxsize=1)
def _variants() -> tuple[dict[str, tuple[str, str]], frozenset[str]]:
    """The list: each word's kind and what the other usage writes instead; and the `-ize`
    spellings of the words British usage also writes with `-ise`."""
    words: dict[str, tuple[str, str]] = {}
    rows = iter(DATA.read_text(encoding="utf-8").splitlines())
    for line in rows:
        if line and not line.startswith("#"):
            break  # the names of the columns
    for line in rows:
        word, kind, instead = line.split("\t")
        words[word] = (kind, instead)
    return words, frozenset(instead for kind, instead in words.values() if kind == "ise")


def _opens_a_sentence(text: str, start: int) -> bool:
    """Does the word at `start` open a sentence, a heading, a list item or a table cell?
    A capital there is the sentence's; anywhere else it is taken for a name's."""
    floor = max(0, start - _REACH)
    line = text.rfind("\n", floor, start)
    if (line >= 0 or floor == 0) and _MARKER.fullmatch(text[line + 1 : start].lstrip(" \t")):
        return True
    breaks = 0
    for at in range(start - 1, floor - 1, -1):
        char = text[at]
        if char == "\n":
            breaks += 1
            if breaks == 2:
                return True
        elif char not in _OPENING:
            return char in _ENDS
    return floor == 0


def _prose(printed: str) -> str:
    """The manuscript's own words, with the markup this reading does not read hidden."""
    return _MARKUP.sub(lambda found: NUL * len(found.group(0)), own_words(printed))


def _in_an_identifier(text: str, start: int, end: int) -> bool:
    """`tumor_size` and `color2` are names somebody gave a variable, `color.csv` is a file,
    `info@color-lab.org` and `center@example.org` are addresses: none is a word of the
    paper. `_color_`, with the underscores of emphasis around it, is one."""
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    beyond = text[end + 1] if end + 1 < len(text) else ""
    if before.isdigit() or after.isdigit() or "@" in (before, after):
        return True
    if before == "_" and start > 1 and text[start - 2].isalnum():
        return True
    return after in ("_", ".") and beyond.isalnum()


def _times(count: int) -> str:
    return "once" if count == 1 else f"{count} times"


def _most_used(counts: dict[str, int], limit: int) -> list[str]:
    """The words used most, and among those used as often the ones met first."""
    return sorted(counts, key=lambda word: -counts[word])[:limit]


def judge_spelling(
    passages: Iterable[Passage], variant: str, accepted: Iterable[str], paper: Path
) -> Report:
    """The findings of the spelling reading, for a paper in `variant`. `accepted` are the
    spellings the project keeps whatever the list says; `paper` is the file that names the
    variant, for the finding that is about it."""
    if not isinstance(variant, str) or variant not in _NAMES:
        # The schema reports an `english_variant` that is neither; a list is not even a
        # key to look up, and the gate's other readings are not to fall with this one.
        return Report((), {"spelling_own": 0, "spelling_other": 0})
    words, with_ize = _variants()
    kept = {word.lower() for word in accepted if isinstance(word, str)}
    british = variant == BRITISH
    other_variant = AMERICAN if british else BRITISH
    others = _KINDS[other_variant]

    first: dict[str, tuple[Passage, int]] = {}
    times: dict[str, int] = {}
    own = 0
    endings: dict[str, dict[str, int]] = {"ise": {}, "ize": {}}
    # For each ending, where it first stands: the passage's place, the offset, the word.
    ending_first: dict[str, tuple[int, int, Passage, str]] = {}

    for place, passage in enumerate(passages):
        text = _prose(passage.printed)
        for found in _WORD.finditer(text):
            word = found.group(0)
            key = word.lower()
            row = words.get(key)
            if (row is None and key not in with_ize) or key in kept or not word.isascii():
                continue
            if not word.islower() and not (
                word[1:].islower() and _opens_a_sentence(text, found.start())
            ):
                continue
            if _in_an_identifier(text, found.start(), found.end()):
                continue
            kind = row[0] if row is not None else ""
            if kind in others:
                times[key] = times.get(key, 0) + 1
                first.setdefault(key, (passage, found.start()))
                continue
            own += kind != ""
            # Only a British paper comes this far with a word in -ise: in an American
            # one it is the other usage's, and was counted above.
            ending = "ise" if kind == "ise" else ("ize" if key in with_ize else "")
            if ending:
                endings[ending][key] = endings[ending].get(key, 0) + 1
                ending_first.setdefault(ending, (place, found.start(), passage, key))

    findings: list[Finding] = []
    other = sum(times.values())
    theirs, ours = _NAMES[other_variant], _NAMES[variant]

    if len(times) >= MANY and other > own:
        listed = _most_used(times, LISTED)
        respell = ", ".join(
            f"{word} ({words[word][1].replace('/', ' or ')}, {_times(times[word])})"
            for word in listed
        )
        more = f", and {len(times) - len(listed)} more" if len(times) > len(listed) else ""
        findings.append(
            Finding(
                gate=GATE,
                code="spelling-not-as-declared",
                severity=WARN,
                message=(
                    f"{other} words are in {theirs} spelling ({len(times)} different ones) "
                    f"and {own} in {ours}; paper.yaml says english_variant: {variant}"
                ),
                path=paper,
                hint=(
                    f"if the paper is in {theirs} English, set english_variant: "
                    f"{other_variant}. If it is not, respell them, the most used first: "
                    f"{respell}{more}. Once they are the fewer, each is reported where it "
                    "stands"
                ),
            )
        )
    else:
        for key, (passage, offset) in first.items():
            instead = " or ".join(repr(form) for form in words[key][1].split("/"))
            findings.append(
                Finding(
                    gate=GATE,
                    code="spelling-variant",
                    severity=WARN,
                    message=(
                        f"{key!r} is the {theirs} spelling of {instead}, used "
                        f"{_times(times[key])}; this paper is in {ours} English"
                    ),
                    path=passage.path,
                    line=passage.line_of(offset),
                    context=context(passage.text, offset, len(key)),
                    hint="respell it, or list that one word under `language: "
                    "accepted_spellings:` in paper.yaml if it is this field's spelling or a "
                    "word of a name. This is its first use; the count is of the whole "
                    "manuscript",
                )
            )

    with_s, with_z = (sum(endings[ending].values()) for ending in ("ise", "ize"))
    if with_s and with_z:
        # The ending used less is the one to change; where they are level, the later one.
        if with_s == with_z:
            fewer = max(ending_first, key=lambda ending: ending_first[ending][:2])
        else:
            fewer = "ise" if with_s < with_z else "ize"
        _, offset, passage, key = ending_first[fewer]
        quoted = {
            ending: ", ".join(repr(word) for word in _most_used(endings[ending], EXAMPLES))
            for ending in endings
        }
        findings.append(
            Finding(
                gate=GATE,
                code="spelling-mixed",
                severity=WARN,
                message=(
                    f"both endings are used: -ise {_times(with_s)} ({quoted['ise']}) and "
                    f"-ize {_times(with_z)} ({quoted['ize']})"
                ),
                path=passage.path,
                line=passage.line_of(offset),
                context=context(passage.text, offset, len(key)),
                hint="British spelling takes either ending and a paper takes one; Oxford "
                f"spelling is -ize. This is the first word in -{fewer}, the ending used "
                "less" + (", or the later one, since they are level" * (with_s == with_z)),
            )
        )

    return Report(tuple(findings), {"spelling_own": own, "spelling_other": other})
