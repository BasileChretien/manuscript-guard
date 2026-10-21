"""Each difference between a proof and what was sent, and what it is.

What was sent is a run of tokens, part by part; the proof another, line by line. They are
lined up (`align`), every number standing for any number, so that a number changed in place
lines up with the one it was, and then each stretch is read:

- a number whose digits, sign or decimal mark changed, or a number gone or come, is a
  correction, named as a citation's where it stands in brackets or is set as a superscript,
  and as a reference's in the reference list;
- a unit, a percent sign or a comparator changed beside a number is a correction, and so is
  a unit of time spelt out as another ("weeks" as "months", not as "wk");
- any change in an entry of the reference list, or inside a citation, is a correction;
- a part of what was sent that the proof does not print at all is a correction;
- the same number set otherwise (grouped, a true minus, the leading zero) is typography,
  shown and not counted, and so is a minus set as a hyphen or a dash;
- any other change of words is a copy-editor's, shown for the author to accept or query;
- text the proof prints that was not sent, between parts, is shown as added.

Each correction and copy-edit names the part it is in, the page of the proof and the line
number the proof prints, where it prints one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from manuscript_guard.proof.align import Op, align
from manuscript_guard.proof.origin import Origin
from manuscript_guard.proof.reading import Reading
from manuscript_guard.proof.sent import CAPTION, CELL, PARAGRAPH, REFERENCE, Part, Sent
from manuscript_guard.proof.tokens import (
    DECIMAL_MARK,
    DIGITS,
    NUMBER,
    SIGN,
    TYPOGRAPHY,
    WORD,
    Token,
    compare_numbers,
    digits_of,
    is_unit,
    key,
    prepared,
    spelled,
    time_units,
    tokens,
)

CORRECTION, COPY_EDIT, MOVED, ADDED = "correction", "copy-edit", "moved", "added"
#: How many tokens either side of a change are shown with it.
CONTEXT = 4
#: Copy-edits of one part this few tokens apart are one copy-edit.
NEAR = 3
#: The fewest tokens of a paragraph, a caption or a reference that, none printed in place,
#: is left out whatever the proof prints there (`_Reader._missing`).
WHOLE = 6


@dataclass(frozen=True)
class Change:
    kind: str
    #: What changed: "number", "sign", "decimal mark", "citation", "reference", "unit or
    #: symbol", "missing", "words", "text", an author's name, an affiliation…
    what: str
    #: The part of what was sent it is in, as `Part.label` names it.
    part: str
    sent: str
    printed: str
    page: int | None = None
    line: int | None = None
    #: Where the number came from in the source, for a correction of one.
    source: str = ""
    note: str = ""
    #: The number as sent and as printed, for a correction of one.
    was: str = ""
    now: str = ""
    #: Where in the proof it is, for the order of the report.
    at: int = field(default=0, compare=False)
    #: The tokens of what was sent it covers, for putting copy-edits close together.
    span: tuple[int, int] = field(default=(0, 0), compare=False)


@dataclass(frozen=True)
class Comparison:
    reading: Reading
    changes: tuple[Change, ...]
    #: How many of the tokens sent the proof prints in their place, and how many there are.
    found: int
    total: int
    #: How many tokens of the proof line up with nothing sent.
    extra: int = 0


def compare(
    sent: Sent, reading: Reading, origin: Origin | None = None, quiet: frozenset[int] = frozenset()
) -> Comparison:
    """`quiet` are the lines of the proof found to be its title page (`front`): text the
    document sent does not have, and is not reported as added."""
    a = [t for index, part in enumerate(sent.parts) for t in tokens(prepared(part.text), index)]
    b = proof_tokens(reading, a)
    # Where each part starts, and where the last ends: what follows the document's last
    # token, a supplement typeset after it, is after its last part and not inside it.
    starts = frozenset(k for k in range(len(a)) if k == 0 or a[k].where != a[k - 1].where)
    ops = align([t.key for t in a], [t.key for t in b], starts | {len(a)})
    found = sum(op.i2 - op.i1 for op in ops if op.tag == "equal")
    extra = len(b) - sum(op.j2 - op.j1 for op in ops if op.tag == "equal")
    changes = _Reader(sent, reading, a, b, origin, quiet).read(ops)
    return Comparison(reading, tuple(changes), found, len(a), extra)


def best(sent: Sent, readings: list[Reading], origin: Origin | None = None) -> Comparison:
    """The comparison with the reading of the proof that finds most of what was sent, less
    what it reads that was not sent: a reading that puts the line numbers among the words
    finds every word and adds a number between each line."""
    done = [compare(sent, reading) for reading in readings]
    # Of two alike, the one of more lines says better where each change is.
    chosen = max(range(len(done)), key=lambda at: (done[at].found - done[at].extra,
                                                    len(readings[at].lines)))
    return compare(sent, readings[chosen], origin) if origin is not None else done[chosen]


# ---------------------------------------------------------------- the proof's tokens

#: What breaks a word at a line's end: a hyphen, a hyphen proper, or the soft hyphen read as
#: one (`proof_tokens`).
_HYPHENS = frozenset({"-", "\N{HYPHEN}", "\N{NON-BREAKING HYPHEN}"})


def proof_tokens(reading: Reading, sent: list[Token]) -> list[Token]:
    """The proof's tokens, a word broken at a line's end put together again: without the
    hyphen, unless what was sent has the two halves joined by one ("example-drug")."""
    words = {t.key for t in sent if t.kind == WORD}
    hyphened = {
        (sent[k - 2].key, sent[k].key) for k in range(2, len(sent))
        if sent[k - 1].key == "-" and sent[k - 1].glued and sent[k].glued
        and sent[k - 2].kind == WORD and sent[k].kind == WORD
    }  # fmt: skip
    # What a reader that takes the hyphen out at a line's end makes of a compound broken
    # at its own hyphen: poppler's layout order prints "exampledrug".
    rejoined = {one + two: (one, two) for one, two in hyphened if one + two not in words}
    out: list[Token] = []
    for index, line in enumerate(reading.lines):
        text = line.text.rstrip()
        found = _split_compounds(tokens(prepared(text), index), rejoined)
        if text.endswith("\N{SOFT HYPHEN}") and found and found[-1].kind == WORD:
            found.append(Token("-", "-", "mark", True, index))
        # A hyphen, not a dash: "5 mg" and an em dash at a line's end, then "twice", are no
        # word broken in two (round 1 of #397).
        if (out and found and found[0].kind == WORD and found[0].raw[:1].islower()
                and len(out) >= 2 and out[-1].raw in _HYPHENS and out[-1].glued
                and out[-2].kind == WORD):  # fmt: skip
            first, half = out[-2], found[0]
            if (first.key, half.key) in hyphened:
                found[0] = replace(half, glued=True)
            else:
                joined = first.raw + half.raw
                out[-2:] = [replace(first, raw=joined, key=key(joined))]
                found = found[1:]
        out += found
    return out


def _split_compounds(found: list[Token], rejoined: dict[str, tuple[str, str]]) -> list[Token]:
    out: list[Token] = []
    for token in found:
        halves = rejoined.get(token.key) if token.kind == WORD else None
        if halves is None:
            out.append(token)
            continue
        cut = len(halves[0])
        one, two = token.raw[:cut], token.raw[cut:]
        out += [replace(token, raw=one, key=key(one)), Token("-", "-", "mark", True, token.where),
                replace(token, raw=two, key=key(two), glued=True)]  # fmt: skip
    return out


# ---------------------------------------------------------------- reading the alignment


class _Reader:
    def __init__(self, sent: Sent, reading: Reading, a: list[Token], b: list[Token],
                 origin: Origin | None, quiet: frozenset[int]) -> None:  # fmt: skip
        self.sent, self.reading, self.a, self.b = sent, reading, a, b
        self.origin, self.quiet = origin, quiet
        self.first: dict[int, int] = {}
        self.last: dict[int, int] = {}
        for at, token in enumerate(a):
            self.first.setdefault(token.where, at)
            self.last[token.where] = at
        self.changes: list[Change] = []

    def read(self, ops: list[Op]) -> list[Change]:
        ops = _regrouped(ops, self.a, self.b)
        gone = self._missing(ops)
        for part, j in gone.items():
            self._say(CORRECTION, "missing", self.sent.parts[part], _short(self.sent.parts[part]
                      .text), "", j, note="not in the proof")  # fmt: skip
        for op in ops:
            if op.tag == "equal":
                self._equal(op)
            else:
                self._differ(op, gone)
        self._moved(ops)
        return _ordered(_swapped(_merged(self.changes)))

    def _missing(self, ops: list[Op]) -> dict[int, int]:
        """The parts the proof does not print, with where in the proof they would have
        stood: a part none of whose tokens the proof prints, or prints anything in place of;
        or a paragraph, a caption or a reference of `WHOLE` tokens or more none of which it
        prints in place, whatever it prints there (round 1 of #397: a paragraph left out
        where a running head stood was a copy-edit of the head). A heading the journal
        renames prints none of its words in place and is no part left out."""
        printed = [False] * len(self.a)
        deleted = [False] * len(self.a)
        at = [0] * len(self.a)
        for op in ops:
            for k in range(op.i1, op.i2):
                printed[k] = op.tag == "equal"
                deleted[k], at[k] = op.tag == "delete", op.j1
        gone = {}
        for part, first in self.first.items():
            span = range(first, self.last[part] + 1)
            if any(printed[k] for k in span):
                continue
            whole = self.sent.parts[part].kind in (PARAGRAPH, CAPTION, REFERENCE)
            if all(deleted[k] for k in span) or whole and len(span) >= WHOLE:
                gone[part] = at[first]
        return gone

    # -- one stretch

    def _equal(self, op: Op) -> None:
        for k in range(op.i2 - op.i1):
            one, two = self.a[op.i1 + k], self.b[op.j1 + k]
            if one.kind != NUMBER or two.kind != NUMBER:
                continue
            verdict, note = compare_numbers(one, two)
            part = self.sent.parts[one.where]
            if part.kind == CELL:
                # A cell said whole, as sent and as printed: its row and its column name it.
                lo = max(op.i1, self.first[one.where])
                hi = min(op.i2, self.last[one.where] + 1)
                sent = part.text
                printed = spelled(self.b[op.j1 + lo - op.i1 : op.j1 + hi - op.i1])
            else:
                sent, printed = self._context(op.i1 + k, op.i1 + k + 1, op.j1 + k,
                                              op.j1 + k + 1)  # fmt: skip
            if verdict in (DIGITS, SIGN, DECIMAL_MARK):
                what = self._kind_of_number(op.i1 + k, op.i1 + k + 1, part) or verdict
                if what == DIGITS:
                    what = "number"
                self._say(CORRECTION, what, part, sent, printed, op.j1 + k,
                          note=_number_note(verdict), was=one.raw, now=two.raw,
                          source=self._source(part, one.raw))  # fmt: skip
            elif verdict == TYPOGRAPHY:
                self._say(TYPOGRAPHY, "number", part, sent, printed, op.j1 + k, note=note)

    def _differ(self, op: Op, gone: dict[int, int]) -> None:
        # A part left out is said once, as missing; what the proof prints in its place is
        # added text, or what is left of the stretch.
        said = [t for t in self.a[op.i1 : op.i2] if t.where not in gone]
        shown = self.b[op.j1 : op.j2]
        if not said and shown and all(t.where in self.quiet for t in shown):
            return
        if not said and op.i2 > op.i1:
            if shown:
                self._say(ADDED, "text", None, "", spelled(shown), op.j1)
            return
        if not said and not self._inside(op.i1):
            # Between two parts, and between two cells: "Table 1 (continued)" and a header
            # row set again stand there as often as a row repeated (round 2 of #397).
            if shown:
                self._say(ADDED, "text", None, "", spelled(shown), op.j1)
            return
        part = self.sent.parts[(said[0] if said else self.a[op.i1 - 1]).where]
        sent, printed = self._context(op.i1, op.i2, op.j1, op.j2)
        numbers = [t for t in (*said, *shown) if t.kind == NUMBER]
        if numbers and digits_of(said) == digits_of(shown) and _rest(said) == _rest(shown):
            self._say(TYPOGRAPHY, "number", part, sent, printed, op.j1,
                      note="the digits are grouped, or the sign is set, otherwise")  # fmt: skip
            return
        if numbers:
            what = self._kind_of_number(op.i1, op.i2, part, shown) or "number"
            first = next((t.raw for t in said if t.kind == NUMBER), "")
            self._say(CORRECTION, what, part, sent, printed, op.j1, note=_gone_or_come(said, shown),
                      source=self._source(part, first) if first else "")  # fmt: skip
            return
        if self._unit_beside(op, said, shown):
            self._say(CORRECTION, "unit or symbol", part, sent, printed, op.j1)
        elif part.kind == REFERENCE:
            self._say(CORRECTION, "reference", part, sent, printed, op.j1)
        elif self._in_citation(op.i1, op.i2):
            self._say(CORRECTION, "citation", part, sent, printed, op.j1)
        else:
            self._say(COPY_EDIT, "words", part, _quoted(self.a, op.i1, op.i1, op.i2, op.i2),
                      _quoted(self.b, op.j1, op.j1, op.j2, op.j2), op.j1,
                      span=(op.i1, op.i2))  # fmt: skip

    def _moved(self, ops: list[Op]) -> None:
        """One note for each run the proof sets elsewhere, but for a table's cells and a
        caption: a float is set where the page has room."""
        runs: list[list[Op]] = []
        for op in ops:
            if not op.moved:
                continue
            if runs and runs[-1][-1].i2 == op.i1:
                runs[-1].append(op)
            else:
                runs.append([op])
        for run in runs:
            parts = sorted({self.a[k].where for op in run for k in range(op.i1, op.i2)})
            if not parts or all(self.sent.parts[p].kind in (CELL, "caption") for p in parts):
                continue
            j = min(op.j1 for op in run)
            self._say(MOVED, "place", self.sent.parts[parts[0]], "", "", j,
                      note=f"set elsewhere in the proof than where it stood ({len(parts)} "
                      f"part{'s' if len(parts) > 1 else ''})")  # fmt: skip

    # -- what a stretch is

    def _inside(self, i: int) -> bool:
        """Whether position `i` of what was sent falls inside a part, not between two."""
        return 0 < i < len(self.a) and self.a[i - 1].where == self.a[i].where

    def _kind_of_number(self, i1: int, i2: int, part: Part, shown: tuple = ()) -> str:
        if part.kind == REFERENCE:
            return "reference"
        if self._in_citation(i1, i2) or _superscript(self.a[i1:i2]) or _superscript(shown):
            return "citation"
        return ""

    def _in_citation(self, i1: int, i2: int) -> bool:
        """Whether a stretch is inside brackets, or inside parentheses that hold a year."""
        if not self.a:
            return False
        anchor = self.a[min(i1, len(self.a) - 1)].where
        lo, hi = self.first[anchor], self.last[anchor]
        for opening, closing in (("[", "]"), ("(", ")")):
            left = next((k for k in range(min(i1, hi + 1) - 1, lo - 1, -1)
                         if self.a[k].key in (opening, closing)), None)  # fmt: skip
            right = next((k for k in range(i2, hi + 1) if self.a[k].key in (opening, closing)),
                         None)  # fmt: skip
            if left is None or right is None:
                continue
            if self.a[left].key != opening or self.a[right].key != closing:
                continue
            inside = self.a[left + 1 : right]
            if opening == "[" or any(_year(t) for t in inside):
                return True
        return False

    def _unit_beside(self, op: Op, said: list[Token], shown: list[Token]) -> bool:
        before, after = time_units(said), time_units(shown)
        retimed = bool(before) and bool(after) and before != after
        if not retimed and not any(is_unit(t.raw) for t in (*said, *shown)):
            return False
        near = [*said, *shown]
        near += [self.a[k] for k in (op.i1 - 1, op.i2) if 0 <= k < len(self.a)]
        near += [self.b[k] for k in (op.j1 - 1, op.j2) if 0 <= k < len(self.b)]
        return any(t.kind == NUMBER for t in near)

    # -- saying it

    def _context(self, i1: int, i2: int, j1: int, j2: int) -> tuple[str, str]:
        part = self.a[min(i1, len(self.a) - 1)].where if self.a else 0
        lo = max(self.first.get(part, 0), i1 - CONTEXT)
        hi = min(self.last.get(part, i2) + 1, i2 + CONTEXT)
        sent = _quoted(self.a, lo, i1, i2, hi)
        printed = _quoted(self.b, max(0, j1 - CONTEXT), j1, j2, min(len(self.b), j2 + CONTEXT))
        return sent, printed

    def _source(self, part: Part, raw: str) -> str:
        return self.origin(part, raw) if self.origin is not None and raw else ""

    def _say(self, kind: str, what: str, part: Part | None, sent: str, printed: str, j: int,
             **more) -> None:  # fmt: skip
        page, line = self._where(j)
        self.changes.append(Change(kind, what, part.label if part else "", sent, printed,
                                   page, line, at=j, **more))  # fmt: skip

    def _where(self, j: int) -> tuple[int | None, int | None]:
        if not self.b:
            return None, None
        line = self.reading.lines[self.b[min(j, len(self.b) - 1)].where]
        return line.page, line.number


def _regrouped(ops: list[Op], a: list[Token], b: list[Token]) -> list[Op]:
    """The alignment with a number one side prints as two, "1737" and "1 737", taken as
    one stretch: each number standing for any number, the two were lined up as a number and
    a number come or gone, and the digits were compared apart."""
    out = list(ops)
    k = 0
    while k < len(out):
        op = out[k]
        run = b[op.j1 : op.j2] if op.tag == "insert" else a[op.i1 : op.i2]
        if op.moved or op.tag not in ("insert", "delete") or not run or any(
                t.kind != NUMBER for t in run):  # fmt: skip
            k += 1
            continue
        after = out[k + 1] if k + 1 < len(out) else None
        before = out[k - 1] if k else None
        if _numbers_at(after, a, b, first=True):
            whole = Op("replace", op.i1, after.i1 + 1, op.j1, after.j1 + 1)
            rest = Op("equal", after.i1 + 1, after.i2, after.j1 + 1, after.j2)
            if digits_of(a[whole.i1 : whole.i2]) == digits_of(b[whole.j1 : whole.j2]):
                out[k : k + 2] = [whole] + ([rest] if rest.i2 > rest.i1 else [])
                k += 1
                continue
        if _numbers_at(before, a, b, first=False):
            whole = Op("replace", before.i2 - 1, op.i2, before.j2 - 1, op.j2)
            rest = Op("equal", before.i1, before.i2 - 1, before.j1, before.j2 - 1)
            if digits_of(a[whole.i1 : whole.i2]) == digits_of(b[whole.j1 : whole.j2]):
                out[k - 1 : k + 1] = ([rest] if rest.i2 > rest.i1 else []) + [whole]
                continue
        k += 1
    return out


def _numbers_at(op: Op | None, a: list[Token], b: list[Token], *, first: bool) -> bool:
    """Whether `op` is a stretch lined up alike that starts (or ends) with a number."""
    if op is None or op.tag != "equal" or op.moved or op.i2 <= op.i1:
        return False
    i, j = (op.i1, op.j1) if first else (op.i2 - 1, op.j2 - 1)
    return a[i].kind == NUMBER == b[j].kind


def _quoted(found: list[Token], lo: int, i1: int, i2: int, hi: int) -> str:
    """The tokens from `lo` to `hi` as printed, the change from `i1` to `i2` among them, with
    no more than `CONTEXT` tokens either side of it, and the middle of a long one left out."""
    if i2 - i1 > 4 * CONTEXT:
        text = (f"{spelled(found[lo : i1 + 2 * CONTEXT])} \N{HORIZONTAL ELLIPSIS} "
                f"{spelled(found[i2 - 2 * CONTEXT : hi])}")  # fmt: skip
    else:
        text = spelled(found[lo:hi])
    return ("\N{HORIZONTAL ELLIPSIS}" if lo < i1 else "") + text + (
        "\N{HORIZONTAL ELLIPSIS}" if hi > i2 else "")  # fmt: skip


def _short(text: str, words: int = 12) -> str:
    said = text.split()
    return " ".join(said[:words]) + ("\N{HORIZONTAL ELLIPSIS}" if len(said) > words else "")


def _rest(found: list[Token]) -> list[str]:
    """What a run holds besides its numbers and its dashes."""
    return [t.key for t in found if t.kind != NUMBER and t.key != "-"]


def _year(token: Token) -> bool:
    return token.kind == NUMBER and token.raw.isdigit() and 1800 <= int(token.raw) <= 2100


def _superscript(found) -> bool:
    """Numbers set against the word or the mark before them, short as citation numbers are:
    how a superscript citation reads once its raise is gone ("action.12", "risk,4")."""
    numbers = [t for t in found if t.kind == NUMBER]
    return bool(numbers) and all(
        t.glued and len(t.raw) <= 3 and t.raw.isdigit() and (t.before.isalpha() or t.before
                                                              in ".,;:)")
        for t in numbers
    )  # fmt: skip


def _number_note(verdict: str) -> str:
    return {DIGITS: "the number is printed otherwise", SIGN: "the sign is lost or changed",
            DECIMAL_MARK: "the decimal mark is changed"}[verdict]  # fmt: skip


def _gone_or_come(said: list[Token], shown: list[Token]) -> str:
    sent = [t.raw for t in said if t.kind == NUMBER]
    printed = [t.raw for t in shown if t.kind == NUMBER]
    if sent and not printed:
        return "a number sent is not printed"
    if printed and not sent:
        return "the proof prints a number that was not sent"
    return "the numbers are printed otherwise"


def _swapped(changes: list[Change]) -> list[Change]:
    """Two corrections that trade what they print, two cells of a table or two numbers of a
    sentence, are said to be swapped."""
    out = list(changes)
    numbered = [k for k, c in enumerate(out) if c.kind == CORRECTION and c.was]
    for k in numbered:
        for m in numbered:
            one, two = out[k], out[m]
            if m <= k or one.part == two.part and one.sent == two.sent:
                continue
            if (one.was, one.now) == (two.now, two.was) or (
                    one.sent == two.printed and two.sent == one.printed):  # fmt: skip
                out[k] = replace(one, note=f"{one.note}; swapped with {two.part}")
                out[m] = replace(two, note=f"{two.note}; swapped with {one.part}")
    return out


def _merged(changes: list[Change]) -> list[Change]:
    """Copy-edits of one part close together as one, and added text of one page as one."""
    out: list[Change] = []
    for change in changes:
        last = out[-1] if out else None
        if (last and change.kind == CORRECTION == last.kind and change.part == last.part
                and (change.sent, change.printed) == (last.sent, last.printed)):  # fmt: skip
            # Two numbers of one cell: one correction of the cell.
            out[-1] = replace(last, was=f"{last.was}, {change.was}",
                              now=f"{last.now}, {change.now}")  # fmt: skip
            continue
        if (last and change.kind == ADDED == last.kind and change.page == last.page):
            out[-1] = replace(last, printed=f"{last.printed} {change.printed}")
            continue
        if (last and change.kind == COPY_EDIT == last.kind and change.part == last.part
                and change.span[0] - last.span[1] <= NEAR):  # fmt: skip
            out[-1] = replace(
                last, sent=f"{last.sent} \N{HORIZONTAL ELLIPSIS} {change.sent}",
                printed=f"{last.printed} \N{HORIZONTAL ELLIPSIS} {change.printed}",
                span=(last.span[0], change.span[1]),
            )
            continue
        out.append(change)
    return out


def _ordered(changes: list[Change]) -> list[Change]:
    """In the proof's order, as the production office reads it."""
    return sorted(changes, key=lambda c: (c.page or 0, c.at))
