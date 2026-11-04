"""The rules that decide whether a cited work gives way: K1 to K5 and D1 to D4.

One pure function, `decide`, from the cited work, the candidates (each as its works record
says) and the readings to a decision with the ids of the rules that made it. Nothing here
reads a file, the network or a model, so `references --reading` and G7 reach the same
answer from the same records.

- K1 integrity: a candidate with no works record, or one retracted, withdrawn or under an
  expression of concern, is out; so is a preprint whose published version is known.
- K2 level on the hierarchy's scale, 1 the strongest; K3 `same` on population, exposure and
  outcome (R2) before anything else; K4 recency, at the same or a stronger level only; K5 for
  a sentence that gives a number, a primary study before a synthesis, which at one level
  comes before K4.
- D1 `replace`: a candidate passes K1, is `same` on R2, does not contradict the sentence, and
  is at a stronger level, or at the same level with a search end date after the cited
  work's publication. D2 `add`: it passes K1, is `same` on R2, contradicts the sentence, at
  the same or a stronger level. D3 `keep` otherwise. D4 `uncertain`: two readings disagree on
  a field D1 or D2 uses, and nothing is proposed.

Two readings are needed before anything is decided: one gives no decision. Where a candidate
both contradicts and is stronger, it is `add` and never `replace`: a work that says the
sentence is wrong does not take its citation's place. Where one candidate gives `add` and
another `replace`, the entry is `add`, since the contradiction is what the author has to read
first.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

REPLACE, ADD, KEEP, UNCERTAIN = "replace", "add", "keep", "uncertain"
SAME, CONTRADICTS = "same", "contradicts"
#: The fields of a candidate's reading the decision uses, in the order they are compared:
#: two readings that differ on any of them, for a candidate that passes K1, are D4.
USED = ("level", "population", "exposure", "outcome", "stance", "search_end")
#: PubMed's publication types of a synthesis, read for K5.
SYNTHESES = frozenset({"review", "systematic review", "meta-analysis"})
#: Readings the rules need before they decide.
READINGS = 2


@dataclass(frozen=True)
class Work:
    """A work as its works record says: its publication date at the precision given, and its
    integrity facts."""

    id: str
    published: str | None = None
    retracted: bool = False
    withdrawn: bool = False
    under_concern: bool = False
    published_as: tuple[str, ...] = ()
    types: tuple[str, ...] = ()

    @property
    def synthesis(self) -> bool:
        return any(kind.casefold() in SYNTHESES for kind in self.types)


@dataclass(frozen=True)
class Fields:
    """What one reader read of one candidate (R1 to R4)."""

    level: int | None = None
    population: str | None = None
    exposure: str | None = None
    outcome: str | None = None
    stance: str | None = None
    search_end: str | None = None


@dataclass(frozen=True)
class Reading:
    """One reader's reading of an entry: the hierarchy and scale, the cited work's level, and
    each candidate's fields by its work id."""

    reader: str
    hierarchy: str
    scale: str
    cited_level: int
    candidates: Mapping[str, Fields] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    """What the rules give: an action, the candidate it names where it names one, the rules
    that decided, and why in words."""

    action: str
    candidate: str | None
    rules: tuple[str, ...]
    why: str


def date_parts(value: str) -> tuple[int, ...]:
    """A date written `YYYY`, `YYYY-MM` or `YYYY-MM-DD`, as its numbers."""
    return tuple(int(part) for part in value.split("-"))


def after(later: str | None, earlier: str | None) -> bool:
    """Whether `later` is after `earlier`, compared at the finest precision both have: a year
    against a day compares the years. Equal there is not after, and a date not known is
    after nothing."""
    if not later or not earlier:
        return False
    first, second = date_parts(later), date_parts(earlier)
    common = min(len(first), len(second))
    return first[:common] > second[:common]


def passes_k1(work: Work | None) -> bool:
    """K1: a work with a works record, not retracted, withdrawn or under concern, and not a
    preprint whose published version is known."""
    if work is None:
        return False
    return not (work.retracted or work.withdrawn or work.under_concern or work.published_as)


def _head(reading: Reading) -> tuple:
    """What every reading of an entry has to agree on before any candidate is compared: the
    hierarchy, its scale, and the cited work's level."""
    return (reading.hierarchy, reading.scale, reading.cited_level)


def _used(fields: Fields | None) -> tuple:
    """The fields of `USED` of one reading of a candidate; none where it was not read."""
    if fields is None:
        return (None,) * len(USED)
    return tuple(getattr(fields, name) for name in USED)


def _disagreement(readings: Sequence[Reading], works: Mapping[str, Work | None]) -> str | None:
    """What two readings disagree on, among what D1 and D2 use, or None."""
    heads = {_head(reading) for reading in readings}
    if len(heads) > 1:
        return "the hierarchy, the scale or the cited work's level"
    ids = sorted({work for reading in readings for work in reading.candidates})
    for work in ids:
        if not passes_k1(works.get(work)):
            continue
        said = {_used(reading.candidates.get(work)) for reading in readings}
        if len(said) > 1:
            names = [name for index, name in enumerate(USED)
                     if len({one[index] for one in said}) > 1]  # fmt: skip
            return f"{', '.join(names)} of {work}"
    return None


def _stronger(level: int, cited: int) -> bool:
    """K2: a level is stronger than another where its number is smaller."""
    return level < cited


def _qualifies(fields: Fields, cited_level: int, cited: Work | None) -> tuple[str, bool] | None:
    """Whether one candidate, read as `fields`, gives D2 `add` or D1 `replace`, and whether
    D1 rests on the date (K4); None where it gives neither."""
    if fields.level is None or (fields.population, fields.exposure, fields.outcome) != (
        SAME, SAME, SAME
    ):  # fmt: skip
        return None
    stronger = _stronger(fields.level, cited_level)
    level_with = fields.level == cited_level
    if fields.stance == CONTRADICTS:
        return (ADD, False) if stronger or level_with else None
    if stronger:
        return REPLACE, False
    if level_with and after(fields.search_end, cited.published if cited else None):
        return REPLACE, True
    return None


def _rank(fields: Fields, work: Work | None, number: bool) -> tuple:
    """K2, K5, then K4: the stronger level first; at one level, for a number, a primary
    study before a synthesis, since a number is cited from the study that measured it; then
    the more recent publication."""
    published = date_parts(work.published) if work and work.published else ()
    newest = tuple(-part for part in published) + (0,) * (3 - len(published))
    synthesis = bool(number and work is not None and work.synthesis)
    return (fields.level, synthesis, newest)


def decide(
    cited: Work | None,
    works: Mapping[str, Work | None],
    readings: Sequence[Reading],
    *,
    number: bool = False,
) -> Decision | None:
    """The decision of the rules for one entry, or None where fewer than `READINGS`
    readings are given. `works` holds each candidate's works record by its id, and None or
    nothing for one with none; `number` says the sentence gives a number (K5)."""
    if len(readings) < READINGS:
        return None
    disagreed = _disagreement(readings, works)
    if disagreed is not None:
        return Decision(UNCERTAIN, None, ("D4",),
                        f"the readings disagree on {disagreed}")  # fmt: skip
    reading = readings[0]
    found: dict[str, list[tuple[tuple, str, bool]]] = {ADD: [], REPLACE: []}
    for work_id, fields in sorted(reading.candidates.items()):
        work = works.get(work_id)
        if not passes_k1(work):
            continue
        qualified = _qualifies(fields, reading.cited_level, cited)
        if qualified is not None:
            action, by_date = qualified
            found[action].append((_rank(fields, work, number), work_id, by_date))
    for action, rule in ((ADD, "D2"), (REPLACE, "D1")):
        if found[action]:
            _rank_of, work_id, by_date = min(found[action])
            fields = reading.candidates[work_id]
            rules = ("K1", "K2", "K3", *(("K4",) if by_date else ()),
                     *(("K5",) if number else ()), rule)  # fmt: skip
            return Decision(action, work_id, rules, _why(action, fields, reading, by_date))
    return Decision(KEEP, None, ("K1", "K2", "K3", "D3"),
                    "no candidate that passes K1 and is the same question is stronger, "
                    "more recent at the same level, or against the sentence")  # fmt: skip


def _why(action: str, fields: Fields, reading: Reading, by_date: bool) -> str:
    """The decision in words."""
    if action == ADD:
        return (f"it contradicts the sentence at level {fields.level}, the cited work's "
                f"being {reading.cited_level}")  # fmt: skip
    if by_date:
        return (f"at the cited work's level, {fields.level}, its search ended "
                f"{fields.search_end}, after the cited work was published")  # fmt: skip
    return f"it is at level {fields.level}, stronger than the cited work's {reading.cited_level}"


__all__ = ["ADD", "KEEP", "READINGS", "REPLACE", "UNCERTAIN", "USED", "Decision", "Fields",
           "Reading", "Work", "after", "date_parts", "decide", "passes_k1"]
