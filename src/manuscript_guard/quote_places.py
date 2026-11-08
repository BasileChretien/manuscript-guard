"""Where a review finding's quote stands, and which readers of a round quote one sentence.

Item 1 of the plan of 2026-11-06 made every finding quote the manuscript (`anchoring.py`).
Measured (DESIGN.md, "What the panel finds of the defects we know", 2026-11-08), a quote
found shows where a finding points and is no evidence that its reader read the paper. Where
it points is what this module keeps: the sentence each anchored quote stands in, and the
section that sentence is under. `review` then shows the sentences quoted by more than one
reader of a round, and the sections each reading's quotes fall in. Basile's answers of
2026-11-08, each as recommended:

- **The place is the sentence** that holds the quote. A quote of a heading's whole title is
  at that heading; one across two sentences is at both; one whose words stand in two places,
  an abstract repeating a sentence of the Results, is at each.
- **It is found when the reading is filed**, as the quote is, in what the reading read: by
  `review --run` in the manuscript as each model was sent it, and by `review --seal` in the
  files the reading carries the digests of, as the build prints them and, where the quote is
  not found there, as they are written. It is kept in `quotes.places` and sealed with the
  reading. Found later, it would be looked for in the results of the day: a quote of a
  number stops standing when the analysis is run again, and no digest says so. A reading
  sealed before places were kept has none, and is read as before.
- **Readers are counted within one round**, each by name, a named reading's `reader` or else
  its `reviewed_by`: a model that read three remits is one reader, and two findings of one
  reader on one sentence count once.
- **It is shown and decides nothing.** No gate reads it, G11's counts and verdicts are as
  they were, and a group is of findings that point at one sentence, not of findings that say
  one thing: the reader given only the abstract quoted the opening of its Results for nine
  findings on four defects.

A sentence is cut as G8 cuts one (`claims.sentence_pieces`), at a heading's line and, in
LaTeX, at an environment's `\\begin` and `\\end`; its section is the heading over it of the
first level that has two headings or more in its file, so that a paper's title typed as its
one top heading is no section.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from manuscript_guard.anchoring import _titles, _written, plain, quoted
from manuscript_guard.gates.quotations import _ELIDED, _SIC, words_in
from manuscript_guard.literature.sources import normalise

#: The most of a sentence a record keeps: a table typed without a stop is one long sentence,
#: and two sentences that open with these many characters alike are read as one.
SENTENCE_CHARS = 400
#: The most sentences in a row a quote is placed across, at each of them (Basile,
#: 2026-11-08: two); a quote across more stands in the text and is placed nowhere.
IN_A_ROW = 2
#: The most of a sentence `review` shows.
SHOWN_CHARS = 72
#: A LaTeX environment's opening and closing, where a sentence ends.
_ENVIRONMENT = re.compile(r"\\(?:begin|end)\{[^{}]*\}")
#: The commands that open a LaTeX sentence and print no words of it, `\label{...}` after a
#: heading: left out of what a record keeps of it.
_OPENING_COMMANDS = re.compile(r"^(?:\\[A-Za-z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?\s*)+")
#: The hashes that open a Markdown heading's line, left out of what a record keeps of it.
_OPENING_HASHES = re.compile(r"^#+[ \t]*")
#: The folder of the supplement's files, where a section is the supplement's.
_SUPPLEMENT = "supplementary/"


@dataclass(frozen=True)
class Place:
    """A sentence a quote stands in, or a heading whose title it is: the file of the
    manuscript, as the reading names it, the section over it, and its words."""

    file: str
    section: str | None
    sentence: str
    heading: bool = False

    @property
    def key(self) -> tuple[str, str | None, bool, str]:
        """What makes two places one: the file, the section, and the words, whatever case."""
        return self.file, self.section, self.heading, self.sentence.lower()

    def record(self) -> dict[str, object]:
        kept: dict[str, object] = {"file": self.file, "section": self.section,
                                   "sentence": self.sentence}  # fmt: skip
        if self.heading:
            kept["heading"] = True
        return kept


@dataclass(frozen=True)
class _Sentence:
    section: str | None
    #: As a record keeps it: as Word prints it, white space and marks folded, case kept.
    kept: str
    #: Folded as `anchoring.stands` folds a text, as printed and as written.
    printed: str
    written: str


@dataclass(frozen=True)
class _Heading:
    titles: frozenset[str]
    title: str
    section: str | None


@dataclass(frozen=True)
class _Text:
    name: str
    sentences: tuple[_Sentence, ...]
    headings: tuple[_Heading, ...]


# ------------------------------------------------------------------ a text, cut and titled


def _heads(text: str, latex: bool) -> list[tuple[int, int, str, int]]:
    """Each heading of `text`: where it starts, its level, its title, and where its line or
    its title ends."""
    if latex:
        from manuscript_guard.text.latex.mask import read

        try:
            found = read(text).headings
        except (ValueError, RecursionError):
            return []
        return [(one.start, one.level, one.title, max(one.end, one.start)) for one in found]
    from manuscript_guard.text.blocks import find_headings

    heads = []
    for one in find_headings(text):
        end = _line_end(text, one.start)
        heads.append((one.start, one.level, one.title, _line_end(text, end + 1) if one.setext
                      else end))  # fmt: skip
    return heads


def _line_end(text: str, at: int) -> int:
    found = text.find("\n", at)
    return len(text) if found < 0 else found


def _top(heads: Sequence[tuple[int, int, str, int]]) -> int:
    """The level a section is read at: the first that has two headings or more, so that a
    title typed as the one heading over the rest is no section; else the first there is."""
    levels = Counter(level for _start, level, _title, _end in heads)
    shared = [level for level, count in levels.items() if count >= 2]
    return min(shared or levels or [1])


def _section_at(heads: Sequence[tuple[int, int, str, int]], top: int, at: int) -> str | None:
    """The title of the heading over `at`, of level `top` or above it, as Word prints it."""
    over = None
    for start, level, title, _end in heads:
        if start > at:
            break
        if level <= top:
            over = title
    return None if over is None else normalise(plain(over))


def _cut_on(text: str) -> str:
    """The text a file's sentences are cut on: itself. G8 cuts on it with its bindings,
    citations and comments blanked, and a binding alone on its line was then a blank line,
    which ended the sentence there and took the binding out of every sentence: a person's
    quote of it, as written, stood in the text and was placed nowhere. A Markdown file read
    as written has its comments blanked already, and a printed one holds no binding."""
    return text


def _read(name: str, text: str, latex: bool) -> _Text:
    """`text`, the file `name` as a reading read it, cut into its sentences and its
    headings, each with the section over it."""
    from manuscript_guard.claims import sentence_pieces

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    heads = _heads(text, latex)
    top = _top(heads)
    cuts = [at for start, _level, _title, end in heads for at in (start, end)]
    if latex:
        cuts += [at for found in _ENVIRONMENT.finditer(text) for at in found.span()]
    sentences = []
    for _start, first, end in sentence_pieces(text, _cut_on(text), cuts=cuts):
        piece = text[first:end]
        # As written, its white space folded: `plain` takes out every `_`, a binding's too.
        kept = normalise(piece)
        kept = _OPENING_COMMANDS.sub("", kept) if latex else _OPENING_HASHES.sub("", kept)
        sentences.append(_Sentence(
            section=_section_at(heads, top, first),
            kept=kept[:SENTENCE_CHARS],
            printed=normalise(plain(piece)).lower(),
            written=normalise(_written(piece)).lower(),
        ))  # fmt: skip
    headings = tuple(
        _Heading(frozenset(_titles(title)), normalise(plain(title)), _section_at(heads, top, start))
        for start, _level, title, _end in heads
    )
    return _Text(name, tuple(sentences), headings)


# ------------------------------------------------------------------- where a quote stands


def _probe(quote: str) -> str:
    """The longest piece of `quote`, folded: a sentence that does not hold it as characters
    cannot hold the quote, and is passed over without reading it as words."""
    pieces = [normalise(piece).lower() for piece in _ELIDED.split(_SIC.sub("", quote))]
    return max(pieces, key=len, default="")


def _holds(sentence_printed: str, sentence_written: str, quote: tuple[str, str, str, str]) -> bool:
    printed, written, probe_printed, probe_written = quote
    return (probe_printed in sentence_printed and words_in(sentence_printed, printed)) or (
        probe_written in sentence_written and words_in(sentence_written, written)
    )


def _place(quote: str, texts: Sequence[_Text]) -> list[Place]:
    """Where `quote` stands in `texts`: at each heading whose whole title it is; else in each
    sentence that holds it; else in each two sentences in a row that hold it together."""
    titles = _titles(quote)
    at_headings = [
        Place(text.name, heading.section, heading.title, heading=True)
        for text in texts for heading in text.headings if heading.titles & titles
    ]  # fmt: skip
    if at_headings:
        return _once(at_headings)
    printed, written = plain(quote), _written(quote)
    folded = (printed, written, _probe(printed), _probe(written))
    for size in range(1, IN_A_ROW + 1):
        found = [
            Place(text.name, sentence.section, sentence.kept)
            for text in texts
            for at in range(len(text.sentences) - size + 1)
            if _holds(" ".join(one.printed for one in text.sentences[at : at + size]),
                      " ".join(one.written for one in text.sentences[at : at + size]), folded)
            for sentence in text.sentences[at : at + size]
        ]  # fmt: skip
        if found:
            return _once(found)
    return []


def _once(places: Iterable[Place]) -> list[Place]:
    """Each place once, in the order found."""
    seen: dict[tuple, Place] = {}
    for place in places:
        seen.setdefault(place.key, place)
    return list(seen.values())


def place_quotes(
    findings: Iterable[Mapping[str, object]],
    anchored: Iterable[str],
    printed: Mapping[str, str],
    written: Mapping[str, str] | None = None,
    *,
    latex: bool = False,
) -> dict[str, list[dict[str, object]]]:
    """The places of each anchored finding's quote, by the finding's id, as a record keeps
    them: looked for in the files `printed`, by name, as the build printed them, and where
    the quote stands in none of them, in the files `written`, as a person may have copied
    it. A finding anchored and placed nowhere, its words across three sentences, has none."""
    wanted = set(anchored)
    shown = [_read(name, text, latex) for name, text in printed.items()]
    typed: list[_Text] | None = None
    places: dict[str, list[dict[str, object]]] = {}
    for finding in findings:
        ident = str(finding.get("id"))
        if ident not in wanted or not quoted(finding):
            continue
        quote = str(finding["quote"])
        found = _place(quote, shown)
        if not found and written:
            typed = typed if typed is not None else [
                _read(name, text, latex) for name, text in written.items()]  # fmt: skip
            found = _place(quote, typed)
        places[ident] = [place.record() for place in found]
    return places


# ------------------------------------------------------------------ what a record keeps


def places_of(document: Mapping[str, object]) -> tuple[tuple[str, tuple[Place, ...]], ...] | None:
    """Each anchored finding of a reading with the places its `quotes` keep for it, in the
    order the findings are anchored: none for one placed nowhere. None where the reading's
    quotes are not counted (`gates.review.quotes_of`: unsealed, altered, or never checked)
    and where they were checked before places were kept."""
    from manuscript_guard.gates.review import quotes_of

    lists = quotes_of(dict(document))
    quotes = document.get("quotes")
    if lists is None or not isinstance(quotes, Mapping):
        return None
    kept = quotes.get("places")
    if not isinstance(kept, Mapping):
        return None
    return tuple((ident, tuple(_places(kept.get(ident)))) for ident in lists[0])


def _places(given: object) -> list[Place]:
    if not isinstance(given, list):
        return []
    return [
        Place(str(one["file"]), one.get("section") if isinstance(one.get("section"), str) else None,
              str(one["sentence"]), bool(one.get("heading")))
        for one in given
        if isinstance(one, Mapping) and isinstance(one.get("file"), str)
        and isinstance(one.get("sentence"), str)
    ]  # fmt: skip


# ------------------------------------------------------------------- what `review` shows


@dataclass(frozen=True)
class Group:
    """A place, and who quoted it: each reader by name, with the findings, by remit and id."""

    place: Place
    readers: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


def groups(readings: Iterable[object]) -> list[Group]:
    """The places quoted in a round's readings, each with its readers, most readers first,
    then as first quoted. A reading is anything with `reviewer`, `who` and `places` (as
    `places_of` gives them, or None); one with none is passed over."""
    found: dict[tuple, tuple[Place, dict[str, list[tuple[str, str]]]]] = {}
    for reading in readings:
        for ident, places in getattr(reading, "places", None) or ():
            for place in places:
                _place_of, readers = found.setdefault(place.key, (place, {}))
                readers.setdefault(reading.who, []).append((reading.reviewer, ident))
    ordered = sorted(enumerate(found.values()), key=lambda pair: (-len(pair[1][1]), pair[0]))
    return [
        Group(place, tuple((who, tuple(dict.fromkeys(ids))) for who, ids in readers.items()))
        for _index, (place, readers) in ordered
    ]


def section_label(place: Place) -> str:
    """A place's section as `review` names it: the supplement's said so, and a sentence
    above every heading said to be."""
    label = place.section or "before any heading"
    return f"{label} (supplement)" if place.file.startswith(_SUPPLEMENT) else label


def sections(places: Iterable[tuple[str, Sequence[Place]]]) -> list[tuple[str, int]]:
    """How many of a reading's findings quote each section, a finding once in each section it
    stands in, most first, then as first quoted."""
    counted: Counter[str] = Counter()
    order: dict[str, int] = {}
    for _ident, found in places:
        for label in dict.fromkeys(section_label(place) for place in found):
            counted[label] += 1
            order.setdefault(label, len(order))
    return sorted(counted.items(), key=lambda pair: (-pair[1], order[pair[0]]))


def reading_line(places: Sequence[tuple[str, Sequence[Place]]] | None) -> str | None:
    """`quotes in: Abstract 3, Methods 1` for one reading, or None where nothing is placed."""
    found = sections(places or ())
    if not found:
        return None
    return "quotes in: " + ", ".join(f"{label} {count}" for label, count in found)


def _shown(place: Place) -> str:
    words = place.sentence
    if len(words) > SHOWN_CHARS:
        words = words[: SHOWN_CHARS - 3].rstrip() + "..."
    where = section_label(place)
    return f'{where}, the heading "{words}"' if place.heading else f'{where}: "{words}"'


def round_lines(readings: Sequence[object]) -> list[str]:
    """What `review` shows of one round's places: each sentence quoted by two readers or
    more, with its readers and their findings, then how many places one reader quoted, how
    many anchored findings stand in no sentence, and how many readings were filed before
    places were kept. Nothing where no reading's quotes are counted."""
    placed = [reading for reading in readings if getattr(reading, "places", None) is not None]
    before = sum(1 for reading in readings
                 if getattr(reading, "places", None) is None and getattr(reading, "anchored", 0))
    found = groups(placed)
    shared = [group for group in found if len(group.readers) >= 2]
    lines = []
    if shared:
        lines.append("quoted by two readers or more:")
        for group in shared:
            lines.append(f"  {len(group.readers)} readers, {_shown(group.place)}")
            for who, ids in group.readers:
                listed = ", ".join(f"{ident} ({reviewer})" for reviewer, ident in ids)
                lines.append(f"    {who}: {listed}")
    rest = []
    alone = len(found) - len(shared)
    if alone:
        rest.append(f"{alone} place{'' if alone == 1 else 's'} quoted by one reader")
    nowhere = sum(1 for reading in placed for _ident, places in reading.places if not places)
    if nowhere:
        rest.append(f"{nowhere} anchored finding{'' if nowhere == 1 else 's'} in no one "
                    "sentence or two")  # fmt: skip
    if before:
        rest.append(f"{before} reading{'' if before == 1 else 's'} filed before the "
                    "sentences quoted were kept")  # fmt: skip
    if rest:
        lines.append("; ".join(rest))
    return lines


__all__ = [
    "Group",
    "Place",
    "groups",
    "place_quotes",
    "places_of",
    "reading_line",
    "round_lines",
    "section_label",
    "sections",
]
