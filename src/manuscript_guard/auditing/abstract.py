"""The audit's Abstract against Results: each number the Abstract gives, looked for where the
paper reports, and each interval and test the Abstract gives held to its counterpart there.

An abstract summarises: every number in it should be reported in the paper too. Where the
paper reports is read as G8 reads it (`gates.reported.Walk`): the Methods, the Results, every
table of every file, and the whole of a file with no Abstract, which is a supplement. A line
is placed under the headings over it, a Markdown paper's (`split_sections`), a Word
document's heading styles (`DocxText.headings`), a LaTeX document's printed view, its places
read back to the `.tex` lines (`printed`, `place_line`). Where no file has an Abstract
heading, or none a Results heading, nothing is compared, and the report says so.

* **Not found.** A number of the Abstract the classifier leaves unexplained, found nowhere
  the paper reports, is said. A rounding of one is a match, "53%" for "53.3%" (the author,
  2026-10-28), and counted apart: the Abstract's number is one the reported number rounds
  to at its places. A match here is as weak as the audit's against the outputs, and the
  section ends with what one is worth, the roundings counted in.
* **Conflict.** An exact pairing only. An interval of the Abstract (`reported_intervals`) of
  the same estimate and level as one interval where the paper reports, two of whose three
  numbers agree with it, estimate, lower bound and upper bound, and whose third does not; or
  a test (`reported_tests`) of the same kind, degrees of freedom and statistic as one test
  there, whose P cannot be the same. Two printed numbers agree where one value could be
  printed as both, each to its places: 1.5 and 1.52 agree, 1.90 and 1.89 do not. Where two
  intervals or tests there could be its counterpart, it has none.

`--strict` counts a conflict, and not a number not found (the author, 2026-10-28).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from math import ceil, floor
from pathlib import Path

from manuscript_guard.stats.intervals import ReportedInterval, reported_intervals
from manuscript_guard.stats.reported import Reported, p_range, reported_tests
from manuscript_guard.text.section_names import names_abstract, names_results
from manuscript_guard.text.sections import Section
from manuscript_guard.text.tokens import Atom

NUL = "\x00"
#: What the section is called in the report.
NO_ABSTRACT = "no file has a heading that names the Abstract"
NO_RESULTS = "no file has a Results heading outside the Abstract"


@dataclass(frozen=True)
class Piece:
    """One file as the section reads it: its text as masked, at the offsets of the text its
    numbers were read in; where each line stands (`place`, None for a file with no
    headings); the lines in a table; whether its document has an Abstract and a Results
    heading; and the numbers the classifier left unexplained in it."""

    path: Path
    hidden: str
    place: Callable[[int], object] | None
    tables: frozenset[int]
    abstract: bool
    results: bool
    atoms: tuple[Atom, ...]


@dataclass
class AbstractRead:
    compared: bool = False
    #: Why nothing was compared, where nothing was.
    why_not: str = ""
    numbers: int = 0
    matched: int = 0
    #: Each number matched only as a rounding, and each found nowhere the paper reports, as
    #: the audit's `Candidate`; each conflict as its `Disagreement`.
    rounded: list = field(default_factory=list)
    not_found: list = field(default_factory=list)
    #: Each number found as printed, as its `Candidate`: `matched` of them.
    found: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    #: What a match is worth against what the paper reports, roundings counted in.
    discrimination: object = None


def in_abstract(place: object) -> bool:
    return isinstance(place, str) and names_abstract(place)


def placed(sections: list[Section], walk=None) -> tuple[Callable[[int], object], bool, bool]:
    """Where each line of one document stands, given its headings, and whether it has an
    Abstract and a Results heading outside it. `walk` is the `Walk` of the files before it,
    whose headings a file of a paper split into files goes on under, as G8 reads them."""
    from manuscript_guard.gates.reported import REPORTED, Walk

    place = (walk if walk is not None else Walk()).placing(sections)
    abstract = any(in_abstract(place(s.line)) for s in sections if names_abstract(s.title))
    results = any(place(s.line) is REPORTED for s in sections if names_results(s.title))
    return place, abstract, results


def place_lines(view, place: Callable[[int], object]) -> dict[str, dict[int, object]]:
    """Each line of a LaTeX document's files, by the file's path, placed as the printed view's
    line it was printed from is (`Printed.place_line`). Where several lines of the view that
    print something share one `.tex` line, a place in the Abstract or where the paper reports
    is kept over one that is neither: the untitled heading that closes an abstract stands on
    `\\end{abstract}`'s line, and the Abstract's last sentence before it was placed nowhere,
    as was Results text before a `\\section` on its line (round 1 of #472)."""
    from manuscript_guard.gates.reported import REPORTED

    lines = view.text.split("\n")
    found: dict[str, dict[int, object]] = {}
    for number, printed in enumerate(lines, 1):
        if not printed.replace(NUL, " ").strip():
            continue
        where = view.place_line(number)
        if where is None:
            continue
        mine = found.setdefault(where[0].path, {})
        kept = mine.get(where[1])
        if where[1] in mine and (kept is REPORTED or in_abstract(kept)):
            continue
        mine[where[1]] = place(number)
    return found


# ----------------------------------------------------------------------- printed numbers


def _decimal(printed: str) -> tuple[Decimal, int] | None:
    """A printed number's value and its places, or None where it is no number."""
    cleaned = (printed.replace(",", "").replace(" ", "").replace("\xa0", "")
               .replace("\N{MINUS SIGN}", "-").rstrip("%"))  # fmt: skip
    cleaned = re.sub(r"^\N{EN DASH}(?=\d)", "-", cleaned)
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or not value.is_finite():
        return None
    return value, max(0, -exponent)


def _box(value: Decimal, places: int) -> tuple[Decimal, Decimal]:
    """The values a number printed to `places` stands for, as a half-open range."""
    half = Decimal(5).scaleb(-(places + 1))
    return value - half, value + half


def agree(one: str, other: str) -> bool:
    """Whether one value could be printed as both numbers, each to its own places."""
    first, second = _decimal(one), _decimal(other)
    if first is None or second is None:
        return one == other
    low, high = _box(*first)
    other_low, other_high = _box(*second)
    return low < other_high and other_low < high


def coarser(printed: str) -> set[tuple[str, int]]:
    """Each number, normalised, with its places, that `printed` rounds to at fewer places
    than its own: "53.3" to 53, "0.725" to 0.72, 0.73, 0.7 and 1. A number at the edge of
    its rounding agrees with two."""
    from manuscript_guard.audit import normalise_number

    read = _decimal(printed)
    if read is None:
        return set()
    value, places = read
    low, high = _box(value, places)
    found = set()
    for fewer in range(places):
        unit = Decimal(1).scaleb(-fewer)
        half = unit / 2
        for k in range(floor((low - half) / unit) + 1, ceil((high + half) / unit)):
            found.add((normalise_number(str((Decimal(k) * unit).quantize(unit))), fewer))
    return found


def printed_parts(text: str) -> list[str]:
    """The numbers an atom carries, as printed: `audit.parts_of` without normalising them."""
    from manuscript_guard.audit import _COMPOUND, _LABELLED, _NUMBER

    stripped = _LABELLED.sub("", text.strip().strip("()[]"), count=1)
    if not _COMPOUND.match(stripped):
        return [stripped]
    return [found.group(0) for found in _NUMBER.finditer(stripped)] or [stripped]


def _numbers(text: str) -> list[str]:
    from manuscript_guard.audit import _NUMBER, _OPAQUE

    return [found.group(0) for found in _NUMBER.finditer(_OPAQUE.sub(" ", text.replace(NUL, " ")))]


# ------------------------------------------------------------------------------- reading


def _kept(hidden: str, keep: Callable[[int], bool]) -> str:
    """`hidden` with each line `keep` refuses blanked to spaces, so offsets hold, and what is
    masked a space too: a LaTeX file's `95\\%` prints a NUL after its sign, across which no
    interval is read."""
    return "\n".join(line.replace(NUL, " ") if keep(number) else " " * len(line)
                     for number, line in enumerate(hidden.split("\n"), 1))  # fmt: skip


def where(piece: Piece, line: int) -> str:
    """What a line of a file is: "reported" in a table, anywhere in a file whose document has
    no Abstract, and under the Methods or the Results; "abstract" in the Abstract; else ""."""
    from manuscript_guard.gates.reported import REPORTED

    if line in piece.tables or not piece.abstract:
        return "reported"
    place = piece.place(line) if piece.place is not None else None
    if place is REPORTED:
        return "reported"
    return "abstract" if in_abstract(place) else ""


def _parts(piece: Piece) -> tuple[str, str, set[int]]:
    """A file's Abstract and what it reports, each as its text with the other lines blanked,
    and the lines of its Abstract."""
    count = piece.hidden.count("\n") + 1
    kinds = {line: where(piece, line) for line in range(1, count + 1)}
    abstract = {line for line, kind in kinds.items() if kind == "abstract"}
    return (_kept(piece.hidden, abstract.__contains__),
            _kept(piece.hidden, lambda line: kinds[line] == "reported"), abstract)  # fmt: skip


def against_results(pieces: list[Piece]) -> AbstractRead:
    """The section, over every file the audit read."""
    from manuscript_guard.audit import Candidate, measure_discrimination, normalise_number

    read = AbstractRead()
    if not any(piece.abstract for piece in pieces):
        read.why_not = NO_ABSTRACT
        return read
    if not any(piece.results for piece in pieces):
        read.why_not = NO_RESULTS
        return read
    read.compared = True
    split = [(piece, *_parts(piece)) for piece in pieces]
    printed = [number for _piece, _abstract, reported, _lines in split
               for number in _numbers(reported)]  # fmt: skip
    exact = {normalise_number(number) for number in printed}
    rounded = {found for number in printed for found in coarser(number)}
    read.discrimination = measure_discrimination(exact | {value for value, _at in rounded})
    intervals = [(piece.path, reported, found) for piece, _a, reported, _l in split
                 for found in reported_intervals(reported)]  # fmt: skip
    tests = [(piece.path, reported, found) for piece, _a, reported, _l in split
             for found in reported_tests(reported)]  # fmt: skip
    for piece, abstract, _reported, lines in split:
        spans = _conflicts(read, piece.path, abstract, intervals, tests)
        for atom in piece.atoms:
            if atom.line not in lines or any(start <= atom.start < end for start, end in spans):
                continue
            read.numbers += 1
            states = [_state(part, exact, rounded) for part in printed_parts(atom.text)]
            candidate = Candidate(atom.text, normalise_number(atom.text), piece.path,
                                  atom.line, atom.line_text.strip()[:140])  # fmt: skip
            if "" in states:
                read.not_found.append(candidate)
            elif "rounded" in states:
                read.rounded.append(candidate)
            else:
                read.matched += 1
                read.found.append(candidate)
    return read


def _state(part: str, exact: set[str], rounded: set[tuple[str, int]]) -> str:
    from manuscript_guard.audit import normalise_number

    value = normalise_number(part)
    if value in exact:
        return "exact"
    places = _decimal(part)
    return "rounded" if places is not None and (value, places[1]) in rounded else ""


# ----------------------------------------------------------------------------- conflicts

#: An estimate's name, read as one: its abbreviation, or its words, either way.
_NAMED = {
    "odds ratio": "or", "risk ratio": "rr", "relative risk": "rr", "hazard ratio": "hr",
    "rate ratio": "irr", "incidence rate ratio": "irr", "reporting odds ratio": "ror",
    "proportional reporting ratio": "prr", "prevalence ratio": "pr",
    "subdistribution hazard ratio": "shr", "mean difference": "md", "risk difference": "rd",
    "absolute difference": "ard", "standardised mean difference": "smd",
    "standardized mean difference": "smd",
}  # fmt: skip


def estimate_of(interval: ReportedInterval) -> tuple[str, str, str]:
    """What an interval estimates, as pairing reads it: its kind, its name, an abbreviation
    and its words taken as one, and its level, 95 where none is stated."""
    name = " ".join(interval.name.lower().split())
    name = re.sub(r"(ratio|risk|ence)s$", r"\1", name)
    return interval.kind, _NAMED.get(name, name), interval.level or "95"


def _line(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


def _whole_line(text: str, at: int) -> str:
    """The line `at` stands on, as the report quotes one."""
    start = text.rfind("\n", 0, at) + 1
    end = text.find("\n", at)
    return " ".join(text[start : end if end >= 0 else len(text)].split())[:140]


def _conflicts(read: AbstractRead, path: Path, abstract: str, intervals: list,
               tests: list) -> list[tuple[int, int]]:  # fmt: skip
    """Each conflict of one file's Abstract, put in `read`, and where each stands."""
    from manuscript_guard.audit import Disagreement

    spans = []
    for given in reported_intervals(abstract):
        found = _counterpart_interval(given, intervals)
        if found is None:
            continue
        found_in, text, other = found
        said = (f"the Abstract gives {given.written}, and where the paper reports, "
                f"{_at(found_in, text, other.start, path)}gives {other.written}")  # fmt: skip
        read.conflicts.append(Disagreement(path, _line(abstract, given.start), said,
                                           _whole_line(abstract, given.start)))
        spans.append((given.start, given.end))
    for given in reported_tests(abstract):
        found = _counterpart_test(given, tests)
        if found is None:
            continue
        found_in, text, other = found
        said = (f"the Abstract gives {_test(given)}, and where the paper reports, "
                f"{_at(found_in, text, other.start, path)}gives {_test(other)}")  # fmt: skip
        read.conflicts.append(Disagreement(path, _line(abstract, given.start), said,
                                           _whole_line(abstract, given.start)))
        spans.append((given.start, given.end))
    return spans


def _at(found_in: Path, text: str, start: int, path: Path) -> str:
    line = _line(text, start)
    return f"line {line} " if found_in == path else f"{found_in.name} line {line} "


def _test(test: Reported) -> str:
    return f"{test.written}, P {test.sign} {test.p}"


def _counterpart_interval(given: ReportedInterval, intervals: list):
    """The one interval where the paper reports that an Abstract's differs from in exactly
    one of its three numbers, or None: where one agrees in all three, where none or several
    differ in one, or where the Abstract's cannot be read."""
    numbers = (given.estimate, given.low, given.high)
    near = {}
    for found_in, text, other in intervals:
        if estimate_of(other) != estimate_of(given):
            continue
        agreeing = sum(agree(a, b) for a, b in zip(numbers, (other.estimate, other.low,
                                                              other.high), strict=True))
        if agreeing == 3:
            return None
        if agreeing == 2:
            near.setdefault((other.estimate, other.low, other.high), (found_in, text, other))
    return next(iter(near.values())) if len(near) == 1 else None


def p_apart(mine: tuple[float, float], theirs: tuple[float, float]) -> bool:
    """Whether no P can be both: the ranges two printed P stand for do not meet, a range's
    end being no part of it."""
    return not (mine[0] < theirs[1] and theirs[0] < mine[1])


def _counterpart_test(given: Reported, tests: list):
    """The one test where the paper reports of the same kind, degrees of freedom and
    statistic as an Abstract's whose P cannot be the Abstract's, or None: where one of them
    has a P that can, or several could be its counterpart."""
    from manuscript_guard.audit import normalise_number

    mine = p_range(given.sign, given.p)
    if mine is None:
        return None
    df = tuple(normalise_number(one) for one in given.df)
    near = {}
    for found_in, text, other in tests:
        if other.kind != given.kind or tuple(normalise_number(one) for one in other.df) != df:
            continue
        if not agree(given.statistic, other.statistic):
            continue
        theirs = p_range(other.sign, other.p)
        if theirs is None:
            return None
        if not p_apart(mine, theirs):
            return None
        near.setdefault((other.statistic, other.sign, other.p), (found_in, text, other))
    return next(iter(near.values())) if len(near) == 1 else None
