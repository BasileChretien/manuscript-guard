"""Two versions side by side: sections, tables, figures, numbers and claims.

- **Sections** are matched by their titles as printed, without their numbers, in any case: a
  second section of one title with the second. Each is the same, changed (with its words in
  each version), new or gone, and moved where it no longer stands in the order it did.
- **Tables** are matched by their label, "Table 2" with "Table 2", "Supplementary Table 1"
  with "Table S1", and one with no label by its caption; then cell by cell, the header by its
  columns and each row by its first cell. A row added or removed is said. A table renumbered
  is one gone and one new (DESIGN.md, "Known gaps").
- **Figures** are matched by their label, and their captions compared. A picture is not.
- **Numbers**, with citation keys and bindings, as `reworded` reads them (`reworded.facts`),
  in the prose: those of the reference list and of the tables are left to the reference list
  and the tables. One gone and one new in the same changed sentence (`claims.changed`, which
  lines the sentences up), or in a sentence that reads alike but for its citations and
  bindings, is one changed; the rest are gone or new, each where its sentence is not in the
  other version.
- **Claims**: each changed sentence that claims more, less or the opposite (`claims.moved`).

Each is a fact with its place; none is a verdict, and none is counted by `--strict`.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable, Sequence

from manuscript_guard import claims
from manuscript_guard.auditing.report import Item
from manuscript_guard.comparing.versions import Display, Heading, Version
from manuscript_guard.findings import INFO, WARN
from manuscript_guard.gates.revision import as_quoted
from manuscript_guard.reworded import Fact, facts

GATE = "compare"
SECTIONS = "Sections"
TABLES = "Tables"
FIGURES = "Figures"
NUMBERS = "Numbers, citations and bindings"
CLAIMS = "Claims"
#: How much of a sentence a finding shows with it.
SHOWN = 160


def shown(text: str) -> str:
    said = " ".join(text.split())
    return said if len(said) <= SHOWN else said[: SHOWN - 3] + "..."


def _key(title: str) -> str:
    return " ".join(re.findall(r"\w+", title.casefold()))


def _item(section: str, code: str, message: str, version: Version, line: int | None,
          severity: str = INFO, context: str | None = None) -> Item:  # fmt: skip
    path, at = version.place(line) if line else (version.path, None)
    return Item(section, GATE, code, message, severity, False, path, at, context)


def _words(text: str) -> int:
    return len(as_quoted(text).split())


def _ordered(pairs: list[tuple[int, int]]) -> set[tuple[int, int]]:
    """The longest run of `pairs`, given in the old order, that is in order in the new: the
    rest moved."""
    best: list[list[tuple[int, int]]] = []
    for pair in pairs:
        longest = max((run for run in best if run[-1][1] < pair[1]), key=len, default=[])
        best.append([*longest, pair])
    return set(max(best, key=len, default=[]))


# ---------------------------------------------------------------------------- sections


def _named(heading: Heading) -> str:
    if not heading.level:
        return "the text before the first heading"
    if not heading.title:
        return "a section with no title"
    return f"the section {heading.title!r}"


def _occurrences(headings: Sequence[Heading]) -> dict[tuple[str, int], int]:
    seen: Counter[str] = Counter()
    keyed = {}
    for at, heading in enumerate(headings):
        key = _key(heading.title)
        keyed[(key, seen[key])] = at
        seen[key] += 1
    return keyed


def sections(old: Version, new: Version) -> list[Item]:
    """Each section of either version: the same, changed, new, gone or moved."""
    was, now = _occurrences(old.sections), _occurrences(new.sections)
    pairs = sorted((at, now[key]) for key, at in was.items() if key in now)
    kept = _ordered(pairs)
    matched = {after: before for before, after in pairs}
    found: list[Item] = []
    for at, heading in enumerate(new.sections):
        if at not in matched:
            found.append(_item(SECTIONS, "section-new", f"{_named(heading)} is new in v2",
                               new, heading.line))  # fmt: skip
            continue
        before = old.sections[matched[at]]
        words = _words(before.body), _words(heading.body)
        same = as_quoted(before.body) == as_quoted(heading.body)
        said = ("the same in both versions" if same else
                f"changed: {words[0]:,} words in v1, {words[1]:,} in v2")  # fmt: skip
        code = "section-same" if same else "section-changed"
        if (matched[at], at) not in kept:
            code, said = "section-moved", f"moved, and {said}"
        found.append(_item(SECTIONS, code, f"{_named(heading)}: {said}", new, heading.line))
    gone = sorted(set(range(len(old.sections))) - set(matched.values()))
    found += [_item(SECTIONS, "section-gone", f"{_named(old.sections[at])} is gone from v2",
                    old, old.sections[at].line) for at in gone]  # fmt: skip
    return found


# ------------------------------------------------------------------------------ tables


def _matched(old: Sequence[Display], new: Sequence[Display]) -> list[tuple[int | None, int | None]]:
    """Each display of either version with its counterpart, or None: by label; one with no
    label by its caption, and then by the order of those with neither."""
    pairs: list[tuple[int | None, int | None]] = []
    left = list(range(len(old)))
    for at, item in enumerate(new):
        found = None
        if item.label is not None:
            found = next((b for b in left if old[b].label == item.label), None)
        elif item.caption:
            found = next((b for b in left if old[b].label is None
                          and _key(old[b].caption) == _key(item.caption)), None)  # fmt: skip
        else:
            found = next((b for b in left if old[b].label is None and not old[b].caption), None)
        if found is not None:
            left.remove(found)
        pairs.append((found, at))
    return pairs + [(b, None) for b in left]


def _name(item: Display) -> str:
    if item.label:
        return item.label
    return f"the table {shown(item.caption)!r}" if item.caption else "a table with no caption"


def _rows(rows: Sequence[tuple[str, ...]]) -> dict[tuple[str, int], tuple[str, ...]]:
    seen: Counter[str] = Counter()
    keyed = {}
    for row in rows:
        key = _key(row[0]) if row else ""
        keyed[(key, seen[key])] = row
        seen[key] += 1
    return keyed


def _cells(name: str, was: Sequence[tuple[str, ...]], now: Sequence[tuple[str, ...]]) -> list[str]:
    """What changed in a table, cell by cell: the header by its columns, each row by its
    first cell."""
    said = []
    header = now[0] if now else ()
    head_was = was[0] if was else ()
    for column in range(max(len(header), len(head_was))):
        one = head_was[column] if column < len(head_was) else ""
        two = header[column] if column < len(header) else ""
        if " ".join(one.split()) != " ".join(two.split()):
            said.append(f"{name}, the header, column {column + 1}: {one!r} in v1, {two!r} in v2")
    stood, stands = _rows(was[1:]), _rows(now[1:])
    for key, row in stands.items():
        if key not in stood:
            said.append(f"{name}: the row {row[0] if row else ''!r} is new in v2")
            continue
        before = stood[key]
        for column in range(1, max(len(row), len(before))):
            one = before[column] if column < len(before) else ""
            two = row[column] if column < len(row) else ""
            if " ".join(one.split()) == " ".join(two.split()):
                continue
            title = header[column] if column < len(header) else str(column + 1)
            said.append(f"{name}, row {row[0]!r}, column {title!r}: {one!r} in v1, {two!r} "
                        "in v2")  # fmt: skip
    said += [f"{name}: the row {row[0] if row else ''!r} is gone from v2"
             for key, row in stood.items() if key not in stands]  # fmt: skip
    return said


def _display_item(section: str, code: str, message: str, display: Display) -> Item:
    return Item(section, GATE, code, message, INFO, False, display.path, display.line)


def tables(old: Version, new: Version) -> list[Item]:
    """Each table of either version: gone, new, its caption changed, and its cells."""
    found: list[Item] = []
    for before, after in _matched(old.tables, new.tables):
        if after is None:
            gone = old.tables[before]
            found.append(_display_item(TABLES, "table-gone", f"{_name(gone)} is gone from v2",
                                       gone))  # fmt: skip
            continue
        table = new.tables[after]
        if before is None:
            found.append(_display_item(TABLES, "table-new", f"{_name(table)} is new in v2",
                                       table))  # fmt: skip
            continue
        was = old.tables[before]
        changes = []
        if table.label and _key(was.caption) != _key(table.caption):
            changes.append(f"{_name(table)}: its caption changed: {shown(was.caption)!r} in "
                           f"v1, {shown(table.caption)!r} in v2")  # fmt: skip
        changes += _cells(_name(table), was.rows, table.rows)
        if not changes:
            cells = sum(len(row) for row in table.rows)
            found.append(_display_item(TABLES, "table-same", f"{_name(table)}: the same in both "
                                       f"versions, cell by cell ({cells} cells)", table))
        found += [_display_item(TABLES, "table-changed", said, table) for said in changes]
    return found


def figures(old: Version, new: Version) -> list[Item]:
    """Each figure of either version by its label: its caption the same or changed, new or
    gone. Its picture is not compared."""
    found: list[Item] = []
    for before, after in _matched(old.figures, new.figures):
        if after is None:
            gone = old.figures[before]
            found.append(_display_item(FIGURES, "figure-gone", f"{gone.label} is gone from v2",
                                       gone))  # fmt: skip
        elif before is None:
            figure = new.figures[after]
            found.append(_display_item(FIGURES, "figure-new", f"{figure.label} is new in v2",
                                       figure))  # fmt: skip
        else:
            was, figure = old.figures[before], new.figures[after]
            if _key(was.caption) == _key(figure.caption):
                said, code = "its caption is the same in both versions", "figure-same"
            else:
                said = (f"its caption changed: {shown(was.caption)!r} in v1, "
                        f"{shown(figure.caption)!r} in v2")  # fmt: skip
                code = "figure-changed"
            found.append(_display_item(FIGURES, code, f"{figure.label}: {said} (its picture "
                                       "is not compared)", figure))  # fmt: skip
    return found


# ----------------------------------------------------------------------------- numbers


def prose(version: Version, *, apart: bool = True) -> tuple[str, Callable[[int], int]]:
    """The version's text as its sentences are cut, and the line of the version each of its
    lines is: the lines set apart emptied, the reference list's and the tables', unless
    `apart` is false. A .docx's paragraphs, a line each, are set a blank line apart, so that
    a sentence ends where its paragraph does: a heading is no part of the sentence after it."""
    lines = version.text.split("\n")
    if apart and version.set_apart:
        lines = ["" if at in version.set_apart else line for at, line in enumerate(lines, 1)]
    if version.kind == "Word":
        return "\n\n".join(lines), lambda line: (line + 1) // 2
    return "\n".join(lines), lambda line: line


class _Read:
    """A version's prose, its facts and its sentences, each fact with its sentence."""

    def __init__(self, version: Version) -> None:
        self.version = version
        text, self.line = prose(version)
        self.text = text
        self.facts = facts(text)
        self.sentences = claims.sentences(text)
        spans = claims.sentence_spans(text)
        starts = [start for start, _first, _end in spans]
        self.spans = spans
        self.of = [bisect_right(starts, fact.start) - 1 for fact in self.facts]

    def said(self, line: int) -> str:
        """Where a line of the prose stands, in words: "line 4", "results.tex line 2"."""
        path, at = self.version.place(self.line(line))
        named = "" if path == self.version.path else f"{path.name} "
        return f"{named}line {at}" if at else f"{named}at a line not known".strip()

    def sentence(self, at: int) -> str:
        if at < 0 or at >= len(self.spans):
            return ""
        _start, first, end = self.spans[at]
        return self.text[first:end]


def numbers(old: Version, new: Version) -> list[Item]:
    """The numbers, citation keys and bindings of the prose gone, new or changed."""
    was, now = _Read(old), _Read(new)
    stood, stands = Counter(f.key for f in was.facts), Counter(f.key for f in now.facts)
    gone_left, new_left = stood - stands, stands - stood
    found: list[Item] = []
    taken_was: set[int] = set()
    taken_now: set[int] = set()
    for before, after in _units(was, now):
        lost = _taken([k for k in range(len(was.facts)) if was.of[k] in before],
                      was.facts, gone_left)  # fmt: skip
        came = _taken([k for k in range(len(now.facts)) if now.of[k] in after],
                      now.facts, new_left)  # fmt: skip
        for kind in dict.fromkeys(was.facts[k].kind for k in lost):
            pairs = zip([k for k in lost if was.facts[k].kind == kind],
                        [k for k in came if now.facts[k].kind == kind], strict=False)  # fmt: skip
            for one, two in pairs:
                taken_was.add(one)
                taken_now.add(two)
                fact = now.facts[two]
                found.append(_item(NUMBERS, "fact-changed", f"{was.facts[one].shown} on "
                                   f"{was.said(was.facts[one].line)} of v1 is {fact.shown} in "
                                   "v2", new, now.line(fact.line),
                                   context=shown(now.sentence(now.of[two]))))
        # What was taken out of the pools and found no partner goes back to them.
        for k in lost:
            if k not in taken_was:
                gone_left[was.facts[k].key] += 1
        for k in came:
            if k not in taken_now:
                new_left[now.facts[k].key] += 1
    found += _alone(was, gone_left, taken_was, (stood, stands), now, gone=True)
    found += _alone(now, new_left, taken_now, (stood, stands), was, gone=False)
    return found


def _units(was: _Read, now: _Read) -> list[tuple[set[int], set[int]]]:
    """The sentences of v1 and of v2 in which a fact may have changed, by their places: each
    stretch the two texts differ in (`claims.changed`), and each sentence that stands once
    in each with the same words, which may differ in what those leave out, a citation key
    or a binding."""
    index_was = {id(s): at for at, s in enumerate(was.sentences)}
    index_now = {id(s): at for at, s in enumerate(now.sentences)}
    units = [({index_was[id(s)] for s in before}, {index_now[id(s)] for s in after})
             for before, after in claims.changed(was.sentences, now.sentences)]  # fmt: skip
    keyed_was = Counter(s.key for s in was.sentences)
    keyed_now = Counter(s.key for s in now.sentences)
    where = {s.key: at for at, s in enumerate(now.sentences)}
    units += [({at}, {where[s.key]}) for at, s in enumerate(was.sentences)
              if keyed_was[s.key] == 1 and keyed_now[s.key] == 1]  # fmt: skip
    return units


def _taken(indices: list[int], found: Sequence[Fact], left: Counter) -> list[int]:
    """Those of `indices` whose fact is one more in this version than in the other, taken
    out of `left`."""
    taken = []
    for k in indices:
        key = found[k].key
        if left[key] > 0:
            left[key] -= 1
            taken.append(k)
    return taken


def _times(count: int) -> str:
    return {1: "once", 2: "twice"}.get(count, f"{count} times")


def _places(places: list[str]) -> str:
    """"line 4", "lines 4 and 9", "results.tex line 2 and line 7"."""
    places = list(dict.fromkeys(places))
    if all(place.startswith("line ") for place in places) and len(places) > 1:
        places = [place[len("line ") :] for place in places]
        return "lines " + ", ".join(places[:-1]) + " and " + places[-1]
    return places[0] if len(places) == 1 else ", ".join(places[:-1]) + " and " + places[-1]


def _alone(read: _Read, left: Counter, taken: set[int], counts: tuple[Counter, Counter],
           other: _Read, *, gone: bool) -> list[Item]:  # fmt: skip
    """Each fact one version holds more often than the other, and not paired as changed: at
    the places where its sentence is not in the other version, where those are enough to
    account for it, and otherwise at every place it stands."""
    stood, stands = counts
    elsewhere = {sentence.key for sentence in other.sentences}
    found = []
    for key in [key for key, count in left.items() if count > 0]:
        mine = [k for k, fact in enumerate(read.facts) if fact.key == key and k not in taken]
        if not mine:
            continue
        alone = [k for k in mine
                 if 0 <= read.of[k] < len(read.sentences)
                 and read.sentences[read.of[k]].key not in elsewhere]  # fmt: skip
        mine = alone if len(alone) >= left[key] else mine
        first = read.facts[mine[0]]
        lines = _places([read.said(read.facts[k].line) for k in mine])
        if gone:
            said = (f"{first.shown} is gone: it stood on {lines} of v1" if not stands[key] else
                    f"{first.shown} stood {_times(stood[key])} in v1 and stands "
                    f"{_times(stands[key])} in v2; on {lines} of v1")  # fmt: skip
        elif not stood[key]:
            said = f"{first.shown} is new in v2" + (f", on {lines}" if len(mine) > 1 else "")
        else:
            said = (f"{first.shown} stands {_times(stands[key])} in v2 and stood "
                    f"{_times(stood[key])} in v1; on {lines} of v2")  # fmt: skip
        found.append(_item(NUMBERS, "fact-gone" if gone else "fact-new", said, read.version,
                           read.line(first.line), context=shown(read.sentence(read.of[mine[0]]))))
    return found


def claim_moves(old: Version, new: Version) -> list[Item]:
    """Each changed sentence of v2 that claims more, less or the opposite of what it did."""
    (was, _line), (now, line) = prose(old), prose(new)
    return [
        _item(CLAIMS, finding.code, finding.message.replace("before the edit", "in v1"), new,
              line(finding.line), WARN)
        for finding in claims.moved(was, now)
    ]  # fmt: skip
