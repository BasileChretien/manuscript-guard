"""Was the manuscript only reworded?

A language pass is trusted with the words: a co-author tidying a paragraph, an editing
service, a model asked to make the English read well. What it is not trusted with is what the
words are about. And that is where `check` is blind, because `check` reads the manuscript as
it is. An edit that puts `{{results.ror.lower}}` where `{{results.ror.upper}}` stood leaves two
bindings that resolve; one that drops `[@lee2019]` leaves a sentence with one citation fewer;
one that retypes a dose leaves a number the conventions allow as readily as the last. Every
gate passes, and the paper says something else.

So this compares the text with what it was, and holds three things to their places: every
binding, every citation key and every typed number. The words between them are free.

- One that is **gone, new or changed** fails. Either the edit was more than a rewording, and
  whoever reads it should know, or it was a slip.
- The same ones **in another order** pass with a warning that shows the place. A clause
  moved to the front of its sentence does that and is harmless; so do two values that changed
  places, which is not. No rule tells the two apart, so a person is shown both.
- A **minus sign** is part of its number where the dash can be nothing else, and one that
  is gone or new fails. After a mark that can open or close, `*n*-1` or `10^3^-10^5^`,
  the dash may be that of a range: there one that came or went is shown with a warning,
  for the same reason.

A number is compared as it is typed. "3" spelt out as "three", "1,200" closed up to "1200"
and "0.50" cut to "0.5" are each reported: the first two may be a matter of style, the third
is not, and nothing here guesses which. What a language edit does to the notation around a
number is free: the space before a unit or a per cent sign, the spaces around a sign of
comparison, a hyphen made a true minus sign.

The text before is the last commit's, or any commit's, or a copy somebody kept. It is a
command and no gate: `check` has one text and this needs two.

What it does not hold is in DESIGN.md's Known gaps: a unit, a sign of comparison, a "not",
"increased" for "decreased". Those are words, and reading them is a reviewer's work.
"""

from __future__ import annotations

import re
import subprocess
from bisect import bisect_left
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import load_project
from manuscript_guard.findings import FAIL, WARN, Finding, Report, merge_all
from manuscript_guard.gates.numbers import SOURCE_GLOB, source_files
from manuscript_guard.text.masking import (
    NUL,
    _frontmatter_spans,
    blank_comments,
    fenced_blocks,
    html_comments,
    mask,
)
from manuscript_guard.text.placeholders import NAMESPACES, PLACEHOLDER
from manuscript_guard.text.tokens import _ENCLOSED, _FRACTIONS
from manuscript_guard.zotero.citations import find_citations

GATE = "REWORDED"

BINDING = "binding"
CITATION = "citation"
NUMBER = "number"

#: The signs a number is typed with. Every hyphen and dash a keyboard or an editor puts
#: before a number is one sign with the true minus: making one into another is a language
#: edit.
_MINUS = (
    "-\N{HYPHEN}\N{NON-BREAKING HYPHEN}\N{FIGURE DASH}\N{EN DASH}\N{MINUS SIGN}"
    "\N{SMALL HYPHEN-MINUS}\N{FULLWIDTH HYPHEN-MINUS}"
)
#: What a dash that stands against a number is: its minus sign for sure, perhaps its sign
#: and perhaps the dash of a range, or no sign.
SURE, MAYBE, NO = 2, 1, 0
#: What ends something, as the body of a class: a closing bracket, a bound value, which
#: the mask has blanked, and the marks that only ever close: a per cent, a per mille or a
#: degree sign, a prime, a closing quotation mark, a euro, pound, yen or cent sign.
_CLOSING = (
    r")\]}%\x00"
    "\N{DEGREE SIGN}\N{PER MILLE SIGN}\N{PRIME}\N{DOUBLE PRIME}"
    "\N{RIGHT SINGLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}"
    "\N{EURO SIGN}\N{POUND SIGN}\N{YEN SIGN}\N{CENT SIGN}"
)
#: After one of these a dash joins two things and is no sign: a letter, a figure, or what
#: ends something. "IL-6", "1.2-3.4", "80%-93%", "{{low}}-3".
_JOIN = re.compile(r"[^\W_]|[" + _CLOSING + "]")
#: The marks that open as well as close. After one, a dash before a number is its sign
#: where the mark opens and may be the dash of a range where it closes, and which it does
#: is not always to be known: `*n*-1` and `x*-1`, `10^3^-10^5^` and `x^2*y^-1`. Two
#: reviews found a rule that decided it wrong in a new place each time, so nothing decides
#: it now: such a dash is perhaps a sign, and one that came or went is shown, not refused.
_ATTACHED = "^~"
_SPACED = "*_$`'\""
#: How far back the word of a mark, or the gap before a dash, is read.
_WORD = 80
_SUPERSCRIPT = (
    "\N{SUPERSCRIPT ZERO}\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO}\N{SUPERSCRIPT THREE}"
    "\N{SUPERSCRIPT FOUR}-\N{SUPERSCRIPT NINE}"
)
_SUBSCRIPT = "\N{SUBSCRIPT ZERO}-\N{SUBSCRIPT NINE}"
#: A number as it is typed, with the dash or the plus that stands against it, whatever
#: that turns out to be. Figures, with commas between groups of three and one decimal
#: point: "0,5" is two numbers here and "1,2,3" three, so that a space typed after a comma
#: changes nothing. A point and figures with no nought before them, ".05", where nothing
#: that joins and no point stands before the point: "Fig.5", "1.2.3" and a note's number
#: after "45%." are read without it. A run of raised or lowered figures with its own sign,
#: as in ten to the minus eight typed with the characters, or the fifty of an IC50 typed
#: low: G2 leaves those out because a square metre claims nothing, and here nothing is
#: claimed, only compared. A fraction or an enclosed figure is a number by itself.
_NUMBER = re.compile(
    "(?P<sign>[" + _MINUS + "+])?(?P<figures>"
    r"\d+(?:,\d{3}(?!\d))*(?:[.\N{MIDDLE DOT}]\d+)?"
    r"|(?<![^\W_])(?<![." + _CLOSING + r"])\.\d+"
    "|[\N{SUPERSCRIPT PLUS SIGN}\N{SUPERSCRIPT MINUS}]?[" + _SUPERSCRIPT + "]+"
    "|[\N{SUBSCRIPT PLUS SIGN}\N{SUBSCRIPT MINUS}]?[" + _SUBSCRIPT + "]+"
    "|[" + _FRACTIONS + _ENCLOSED + "])"
)

#: How many lines or facts a message lists before it says how many more there are.
SHOWN = 6
#: How long git may take to answer. It reads one file or lists one folder.
GIT_SECONDS = 30


class NoBefore(Exception):
    """The text before the edit could not be had. The message is written for the author."""


@dataclass(frozen=True)
class Fact:
    """One thing a rewording leaves alone, and where it stands."""

    kind: str
    #: What is compared: a binding's name, a citation's key, a number's figures as typed.
    text: str
    start: int
    line: int
    #: Of a number: whether a dash stands against it as its minus sign, for sure or perhaps.
    minus: int = NO

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.text

    @property
    def shown(self) -> str:
        if self.kind == BINDING:
            return "{{" + self.text + "}}"
        if self.kind == CITATION:
            return "@" + self.text
        return f"'{'-' if self.minus == SURE else ''}{self.text}'"


def _numbers_in(text: str) -> str:
    """`text` with everything blanked that prints no number of the author's: comments, the
    keys of the front matter, bindings, citation keys, addresses. A listing is printed, so
    it is put back: `mask` hides one because G2 reads it by other rules.

    Not a listing that a comment holds, or one under a key of the front matter that is not
    printed. `mask` blanks those twice, as a listing and as what holds it, and putting the
    listing back undid both: a text returned without its comments was told that the seed
    of a commented listing was gone."""
    hidden = mask(text)
    fences = fenced_blocks(text)
    if not fences:
        return hidden
    shown = list(hidden)
    for fence in fences:
        shown[fence.start : fence.end] = text[fence.start : fence.end]
    for start, end in (*html_comments(text, fences), *_frontmatter_spans(text)):
        shown[start:end] = NUL * (end - start)
    return "".join(shown)


def _opens(text: str, at: int) -> bool:
    """Can the mark at `at` only open what it marks? Then a dash after it is a sign.

    A caret or a tilde opens against its base, with no space, so it is counted in its own
    word: the first and the third open. The other marks open where their run stands at the
    start or after something that does not join. Where this says no, the mark may close, or
    may be a sign of its own, a product or a power, and the dash after it may be either."""
    mark = text[at]
    low = max(0, at - _WORD)
    if mark in _ATTACHED:
        start = at
        while start > low and not text[start - 1].isspace():
            start -= 1
        return text.count(mark, start, at + 1) % 2 == 1
    while at > low and text[at - 1] in _SPACED:
        at -= 1
    return at == 0 or _JOIN.match(text[at - 1]) is None


def _sign(text: str, at: int) -> int:
    """What the dash at `at` is to the number it stands against: SURE, MAYBE or NO.

    Sure where nothing stands before it that it could join: at the start, after a space, an
    opening bracket, a comma, a sign of comparison, a mark that opens there. No sign after
    what `_JOIN` lists. Perhaps one after a mark that may close, after the "e" of an
    exponent, which is also the E of a panel in "Figures 1E-1G", and after a figure and one
    space or line end, which is a range typed with a space on one side as often as a
    negative number."""
    if text[at] == "-":
        # Two or three hyphens are the dash pandoc prints for them: one dash, read by what
        # stands before the first.
        while at and text[at - 1] == "-":
            at -= 1
    if at == 0:
        return SURE
    before = text[at - 1]
    if before in _ATTACHED or before in _SPACED:
        return SURE if _opens(text, at - 1) else MAYBE
    if before in " \n":
        # One space, or the end of a line: a text is wrapped where a space stood.
        ended = text[at - 2] if at >= 2 else " "
        return MAYBE if not ended.isalpha() and _JOIN.match(ended) else SURE
    if _JOIN.match(before):
        exponent = before in "eE" and at >= 2 and text[at - 2].isdecimal()
        return MAYBE if exponent else NO
    return SURE


def facts(text: str) -> list[Fact]:
    """Every binding, citation key and typed number of a manuscript file, in the order they
    stand."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    breaks = [found.start() for found in re.finditer("\n", text)]

    def fact(kind: str, held: str, start: int, minus: int = NO) -> Fact:
        return Fact(kind, held, start, bisect_left(breaks, start) + 1, minus)

    # What pandoc drops holds no binding and no citation. The bindings are the ones
    # `placeholders.parse` calls well formed, found here without its line of each, which it
    # counts from the top of the file every time.
    printed = blank_comments(text) if "<!--" in text else text
    found = [
        fact(BINDING, f"{binding['ns']}.{binding['key']}", binding.start())
        for binding in PLACEHOLDER.finditer(printed)
        if binding["ns"] in NAMESPACES
    ]
    found += [fact(CITATION, use.citekey, use.start) for use in find_citations(printed, Path())]
    shown = _numbers_in(text)
    for number in _NUMBER.finditer(shown):
        sign, figures = number["sign"], number["figures"]
        start, minus = number.start("figures"), NO
        read = _sign(shown, number.start()) if sign else NO
        if sign == "+" and read == SURE:
            figures, start = "+" + figures, number.start()
        elif sign and sign != "+" and read != NO:
            minus, start = read, number.start()
        found.append(fact(NUMBER, figures, start, minus))
    return sorted(found, key=lambda one: one.start)


# ------------------------------------------------------------------------ the comparison


def _times(count: int) -> str:
    return {1: "once", 2: "twice"}.get(count, f"{count} times")


def _listed(items: Sequence[str]) -> str:
    """"a", "a and b", "a, b and c", and past `SHOWN` of them how many more."""
    shown = list(items[:SHOWN])
    if len(items) > SHOWN:
        shown.append(f"{len(items) - SHOWN} more")
    if len(shown) < 2:
        return "".join(shown)
    return ", ".join(shown[:-1]) + " and " + shown[-1]


def _lines(found: Sequence[Fact]) -> str:
    # A line that holds it twice is named once: the count is in the sentence already.
    lines = [str(line) for line in dict.fromkeys(fact.line for fact in found)]
    return ("line " if len(lines) == 1 else "lines ") + _listed(lines)


_PUT_BACK = (
    "put it back as it stood; if the change is meant, it is a change to the paper and no "
    "rewording"
)


def _what(found: Sequence[Fact], alone: bool) -> str:
    """The fact these all are, named for a message: a number with its minus sign where
    every one of them has it for sure and the other text holds none of the number.
    Where both texts hold it the sentence counts both, and the sign of one text's is
    not the other's: "'-2' stood twice and stands once now" was said of a 2."""
    first = found[0]
    signed = alone and all(fact.minus == SURE for fact in found)
    if first.kind == NUMBER and not signed:
        return f"the number '{first.text}'"
    return f"the {first.kind} {first.shown}"


def _lost(before: Sequence[Fact], now: int, path: Path | None) -> Finding:
    what = _what(before, alone=now == 0)
    if now == 0 and len(before) == 1:
        message = f"{what} is gone: it stood on {_lines(before)} before the edit"
    elif now == 0:
        message = (
            f"{what} is gone: it stood {_times(len(before))} before the edit, on {_lines(before)}"
        )
    else:
        message = (
            f"{what} stood {_times(len(before))} before the edit, on {_lines(before)}, and "
            f"stands {_times(now)} now"
        )
    return Finding(GATE, "fact-lost", message, FAIL, path, hint=_PUT_BACK)


def _new(after: Sequence[Fact], was: int, path: Path | None, line: int) -> Finding:
    what = _what(after, alone=was == 0)
    if was == 0 and len(after) == 1:
        message = f"{what} is new: it did not stand in the text before the edit"
    elif was == 0:
        message = (
            f"{what} is new: it did not stand in the text before the edit, and stands "
            f"{_times(len(after))} now, on {_lines(after)}"
        )
    else:
        message = (
            f"{what} stands {_times(len(after))} now, on {_lines(after)}, and stood "
            f"{_times(was)} before the edit"
        )
    return Finding(GATE, "fact-new", message, FAIL, path, line, hint=_PUT_BACK)


def _untouched(before: Sequence[Fact], after: Sequence[Fact]) -> tuple[int, int]:
    """How many facts the two texts open with in common, and how many they close with."""
    shorter = min(len(before), len(after))
    head = 0
    while head < shorter and before[head].key == after[head].key:
        head += 1
    tail = 0
    while tail < shorter - head and before[-1 - tail].key == after[-1 - tail].key:
        tail += 1
    return head, tail


def _reordered(before: Sequence[Fact], after: Sequence[Fact]) -> list[tuple[int, int]]:
    """Where the same facts stand in another order: each stretch, as far as it has to reach
    for the two texts to hold the same facts again. The stretches do not overlap, and a
    clause moved in one sentence is told apart from one moved in the next.

    Read once, with a count of what one text has had that the other has not: a comparison
    that lined the texts up fact by fact would take the square of a manuscript's length."""
    stretches: list[tuple[int, int]] = []
    owed: Counter[tuple[str, str]] = Counter()
    unsettled = 0
    start = 0
    for index, (was, now) in enumerate(zip(before, after, strict=True)):
        for key, step in ((was.key, 1), (now.key, -1)):
            count = owed[key]
            owed[key] = count + step
            unsettled += (count + step != 0) - (count != 0)
        if unsettled == 0:
            if index > start:
                stretches.append((start, index + 1))
            start = index + 1
    return stretches


def _moved(before: Sequence[Fact], after: Sequence[Fact], path: Path | None) -> Finding:
    return Finding(
        GATE,
        "order-changed",
        "the same bindings, citations and numbers stand here in another order: before the "
        f"edit {_listed_plain(before)}; now {_listed_plain(after)}",
        WARN,
        path,
        after[0].line,
        hint="a clause that moved does this and nothing is wrong; if two values changed "
        "places, put them back",
    )


def _listed_plain(found: Sequence[Fact]) -> str:
    shown = [fact.shown for fact in found[:SHOWN]]
    if len(found) > SHOWN:
        shown.append(f"and {len(found) - SHOWN} more")
    return ", ".join(shown)


_UNSURE = (
    'after *, _, $, ^, ~, a quotation mark, the "e" of an exponent or a figure and a space, '
    "a dash before a number is its minus sign or the dash of a range, and nothing here can "
    "tell which: read the place"
)
_MOVED = (
    "if a minus sign went from one place to the other, two numbers changed; if their clauses "
    "changed places, nothing did: read the places"
)


def _signed(found: Sequence[Fact]) -> tuple[list[Fact], list[Fact]]:
    """Those with a minus sign for sure, and those with a dash that is one for sure or perhaps."""
    return (
        [fact for fact in found if fact.minus == SURE],
        [fact for fact in found if fact.minus != NO],
    )


def _newly(now: int, before: int) -> int:
    """How many more dashes that may be a sign there are now than there were."""
    return max(now - before, 0)


def _nth(places: Sequence[int]) -> str:
    """"1st", "2nd and 4th": which of a number's places, counted from the top of the file."""
    endings = {1: "st", 2: "nd", 3: "rd"}
    return _listed(
        [f"{at}{'th' if 10 < at % 100 < 14 else endings.get(at % 10, 'th')}" for at in places]
    )


def _sign_failure(
    figures: str,
    was: Sequence[Fact],
    now: Sequence[Fact],
    placed: Callable[[Sequence[Fact]], int | None],
    path: Path | None,
) -> Finding | None:
    """A minus sign that is gone or new for sure, of one number both texts may hold.

    From counts, as the rest is. A sign is gone for sure where more of the number had one
    for sure than have one for sure now, beyond those that are gone themselves and beyond
    the dashes that may be a sign and are new: `x * -1` made `x*-1` has the same sign in a
    place where it is no longer sure. A dash that may be a sign and stood before the edit is
    itself, and answers for nothing: counted with the dashes now, as it was at first, the
    `*n*-1` of a later paragraph answered for a slope of -1 made 1."""
    (sure, dashed), (sure_now, dashed_now) = _signed(was), _signed(now)
    maybe, maybe_now = len(dashed) - len(sure), len(dashed_now) - len(sure_now)
    gone, come = max(len(was) - len(now), 0), max(len(now) - len(was), 0)
    number, signed = f"the number '{figures}'", f"'-{figures}'"
    if len(sure) - gone > len(sure_now) + _newly(maybe_now, maybe):
        message = (
            f"{number} has lost its minus sign: {signed} stood on {_lines(sure)} before the edit"
        )
        if sure_now:
            message = (
                f"{number} stood as {signed} {_times(len(sure))} before the edit, on "
                f"{_lines(sure)}, and stands as {signed} {_times(len(sure_now))} now"
            )
        plain = [fact for fact in now if fact.minus == NO]
        return Finding(GATE, "sign-lost", message, FAIL, path, placed(plain or now), hint=_PUT_BACK)
    if len(sure_now) - come > len(sure) + _newly(maybe, maybe_now):
        message = (
            f"{number} has a minus sign it did not have: {signed} stands on {_lines(sure_now)}"
        )
        if sure:
            message = (
                f"{number} stands as {signed} {_times(len(sure_now))} now, on {_lines(sure_now)}, "
                f"and stood as {signed} {_times(len(sure))} before the edit"
            )
        return Finding(GATE, "sign-new", message, FAIL, path, placed(sure_now), hint=_PUT_BACK)
    return None


def _sign_warning(
    figures: str,
    was: Sequence[Fact],
    now: Sequence[Fact],
    placed: Callable[[Sequence[Fact]], int | None],
    path: Path | None,
) -> Finding | None:
    """A dash that came, went or changed places where nothing about it is sure.

    Only of a number that stands as often as it did: where it does not, that is told and
    fails. A dash more or fewer may be a sign more or fewer. As many dashes at other places
    of the number is two signs that changed places, "fell by -0.3 and rose by 0.3" made
    "fell by 0.3 and rose by -0.3", or two clauses that did, and the two look the same. A
    dash that stands where it stood and is only read another way, `x*-1` made `x * -1`, is
    no change."""
    if len(was) != len(now):
        return None
    dashed, dashed_now = _signed(was)[1], _signed(now)[1]
    number = f"the number '{figures}'"
    if len(dashed) > len(dashed_now):
        then = f"stands before it {_times(len(dashed_now))} now" if dashed_now else "does not now"
        message = (
            f"{number} may have lost a minus sign: a dash stood before it {_times(len(dashed))} "
            f"before the edit, on {_lines(dashed)}, and {then}"
        )
        line = placed([fact for fact in now if fact.minus == NO] or now)
        return Finding(GATE, "sign-unsure", message, WARN, path, line, hint=_UNSURE)
    if len(dashed) < len(dashed_now):
        then = f"stood before it {_times(len(dashed))}" if dashed else "none stood before it"
        message = (
            f"{number} may have gained a minus sign: a dash stands before it "
            f"{_times(len(dashed_now))} now, on {_lines(dashed_now)}, and {then} before the edit"
        )
        return Finding(GATE, "sign-unsure", message, WARN, path, placed(dashed_now), hint=_UNSURE)
    places = [at for at, fact in enumerate(was, 1) if fact.minus != NO]
    places_now = [at for at, fact in enumerate(now, 1) if fact.minus != NO]
    if places == places_now:
        return None
    message = (
        f"the dash before {number} stands at another of its {len(now)} places: before the edit "
        f"at the {_nth(places)}, on {_lines(dashed)}, and now at the {_nth(places_now)}, on "
        f"{_lines(dashed_now)}"
    )
    return Finding(GATE, "sign-moved", message, WARN, path, placed(dashed_now), hint=_MOVED)


def _by_key(found: Sequence[Fact]) -> dict[tuple[str, str], list[Fact]]:
    held: dict[tuple[str, str], list[Fact]] = {}
    for fact in found:
        held.setdefault(fact.key, []).append(fact)
    return held


def _placer(was: Sequence[Fact], now: Sequence[Fact]) -> Callable[[Sequence[Fact]], int | None]:
    """Where a finding about some of the facts of the text as it is now is placed.

    Where a fact stands more often than it did, which of them is the new one is not known
    from the facts alone. A finding is placed at the first that lies past what the two
    texts open with in common and before what they close with: after one edit that is the
    one. The message gives every line."""
    head, tail = _untouched(was, now)
    first, last = 0, -1
    if head + tail < len(now):
        first, last = now[head].start, now[len(now) - tail - 1].start

    def placed(found: Sequence[Fact]) -> int | None:
        between = [fact for fact in found if first <= fact.start <= last]
        return (between or found)[0].line if found else None

    return placed


def compare(before: str, after: str, path: Path | None = None) -> Report:
    """What an edit did to the bindings, the citations and the typed numbers of one file.

    The counts are of the text as it is now."""
    was, now = facts(before), facts(after)
    stood, stands = _by_key(was), _by_key(now)
    placed = _placer(was, now)
    findings = [
        _lost(held, len(stands.get(key, ())), path)
        for key, held in stood.items()
        if len(held) > len(stands.get(key, ()))
    ]
    findings += [
        _new(held, len(stood.get(key, ())), path, placed(held))
        for key, held in stands.items()
        if len(held) > len(stood.get(key, ()))
    ]
    if not findings:
        # With one gone there is no saying which of the rest moved: the loss is told, and
        # the order once the loss is settled.
        findings = [
            _moved(was[start:end], now[start:end], path) for start, end in _reordered(was, now)
        ]
    # Only a number with a dash against it somewhere, in either text, can have had its sign
    # changed.
    for key in dict.fromkeys(fact.key for fact in (*was, *now) if fact.minus != NO):
        both = key[1], stood.get(key, ()), stands.get(key, ()), placed, path
        change = _sign_failure(*both) or _sign_warning(*both)
        findings += [change] if change else []
    kinds = Counter(fact.kind for fact in now)
    return Report(tuple(findings)).with_counts(
        reworded_files=1,
        reworded_bindings=kinds[BINDING],
        reworded_citations=kinds[CITATION],
        reworded_numbers=kinds[NUMBER],
    )


def _alone(text: str, path: Path, *, gone: bool, since: str) -> Report:
    """A file one of the two texts lacks. Every fact in it is gone or new with it, and a
    file of words alone is only told."""
    found = facts(text)
    kinds = Counter(fact.kind for fact in found)
    counts = {
        "reworded_files": 1,
        "reworded_bindings": kinds[BINDING],
        "reworded_citations": kinds[CITATION],
        "reworded_numbers": kinds[NUMBER],
    }
    if gone:
        code, said, holds = "file-lost", "this file is gone", "held"
        counts = dict.fromkeys(counts, 0)
    else:
        code, said, holds = "file-new", f"this file is new since {since}", "holds"
    if len(found) == 1:
        message, severity = f"{said}, and 1 binding, citation or number with it", FAIL
    elif found:
        message = f"{said}, and {len(found)} bindings, citations and numbers with it"
        severity = FAIL
    else:
        message, severity = f"{said}; it {holds} no binding, citation or number", WARN
    return Report((Finding(GATE, code, message, severity, path),)).with_counts(**counts)


# ---------------------------------------------------------------- where the text before is


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Git, asked one thing. The file watcher is off: on a machine that turns it on, git
    can wait on it for ever, and nothing here is worth a watcher."""
    command = ["git", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", *args]
    try:
        return subprocess.run(
            command, cwd=cwd, capture_output=True, timeout=GIT_SECONDS, check=False
        )
    except FileNotFoundError as exc:
        raise NoBefore(
            "git is not installed, and the text before the edit is read from a commit; "
            "or name a copy of it: `manuscript-guard reworded FILE --before COPY`"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise NoBefore(f"git did not answer within {GIT_SECONDS} seconds in {cwd}") from exc
    except OSError as exc:
        raise NoBefore(f"git could not be run in {cwd}: {exc.strerror or exc}") from exc


def _commit(cwd: Path, since: str) -> str:
    """The commit `since` names, as git knows it."""
    if since.startswith("-"):
        raise NoBefore(f"'{since}' is no revision: a revision does not begin with a dash")
    inside = _git(cwd, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != b"true":
        raise NoBefore(
            f"{cwd} is not in a git repository, and the text before the edit is read from a "
            "commit; or name a copy of it: `manuscript-guard reworded FILE --before COPY`"
        )
    found = _git(cwd, "rev-parse", "--verify", "--quiet", since + "^{commit}")
    if found.returncode != 0:
        if since == "HEAD":
            raise NoBefore(f"the repository of {cwd} has no commit yet to compare with")
        raise NoBefore(f"git knows no commit named '{since}'")
    return found.stdout.decode("ascii", "replace").strip()


def _decoded(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NoBefore(f"{what} is not UTF-8, so it cannot be compared") from exc


def _at(commit: str, cwd: Path, name: str, since: str) -> str | None:
    """The file `name`, a path under `cwd` with forward slashes, as `commit` has it. None
    where the commit has no such file."""
    found = _git(cwd, "cat-file", "blob", f"{commit}:./{name}")
    if found.returncode != 0:
        return None
    return _decoded(found.stdout, f"{name} at {since}")


def _read(path: Path) -> bool:
    """Is this a file the gates read: Markdown, in no folder set aside by its name?"""
    return path.match(SOURCE_GLOB) and not any(part.startswith((".", "_")) for part in path.parts)


def _names_at(commit: str, root: Path, folder: str) -> list[str]:
    """The manuscript files `commit` has under `folder`, as paths under `root`."""
    found = _git(root, "ls-tree", "-r", "-z", "--name-only", commit, "--", f"./{folder}")
    if found.returncode != 0:
        return []
    names = _decoded(found.stdout, "a file name in the commit").split("\0")
    inside = len(Path(folder).parts)
    return sorted(
        name for name in names if name and _read(Path(*Path(name).parts[inside:]))
    )


@dataclass(frozen=True)
class Outcome:
    report: Report
    #: What the paths in the report are shown under.
    root: Path
    #: What the text was compared with, in words.
    against: str


def _one(name: str, cwd: Path, commit: str, since: str) -> Report:
    """One file, a path under `cwd`, against the same file in `commit`."""
    path = cwd / name
    before = _at(commit, cwd, name, since)
    if not path.is_file():
        if before is None:
            raise NoBefore(f"{path} does not exist, now or at {since}")
        return _alone(before, path, gone=True, since=since)
    after = read_text(path)
    if before is None:
        return _alone(after, path, gone=False, since=since)
    return compare(before, after, path)


def against_commit(paths: Sequence[Path], since: str) -> Outcome:
    """Each of `paths` against the commit `since`: a file by itself, a folder as the project
    it lies in, with every manuscript file that project has or had."""
    reports: list[Report] = []
    root: Path | None = None
    described = ""
    for given in paths:
        given = given.resolve()
        if given.is_dir():
            project, _ = load_project(given)
            cwd = project.root
            try:
                folder = project.path("manuscript").relative_to(cwd).as_posix()
            except ValueError as exc:
                raise NoBefore(
                    f"the manuscript folder {project.path('manuscript')} is not under the "
                    f"project {cwd}, so it is not compared as one; name its files"
                ) from exc
        elif given.parent.is_dir():
            cwd, folder = given.parent, None
        else:
            raise NoBefore(f"{given} does not exist")
        commit = _commit(cwd, since)
        described = described or (
            f"the last commit ({commit[:8]})" if since == "HEAD" else f"{since} ({commit[:8]})"
        )
        root = root or cwd
        if folder is None:
            reports.append(_one(given.name, cwd, commit, since))
            continue
        now = [path.relative_to(cwd).as_posix() for path in source_files(cwd / folder)]
        for name in sorted({*now, *_names_at(commit, cwd, folder)}):
            reports.append(_one(name, cwd, commit, since))
    return Outcome(merge_all(reports), root or Path.cwd(), described)


def against_copy(after: Path, before: Path) -> Outcome:
    """One file against a copy of what it was."""
    for path in (after, before):
        if not path.is_file():
            raise NoBefore(f"{path} is not a file" if path.exists() else f"{path} does not exist")
    report = compare(read_text(before), read_text(after), after)
    return Outcome(report, Path.cwd(), str(before))
