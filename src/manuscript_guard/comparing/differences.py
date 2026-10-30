"""Two versions side by side: sections, tables, figures, numbers and claims.

- **Sections** are matched by their titles as printed, without their numbers, in any case: a
  second section of one title with the second. Each is the same, changed (with its words in
  each version), new or gone, and moved where it no longer stands in the order it did.
- **Tables** are matched by their label, "Table 2" with "Table 2", "Supplementary Table 1"
  with "Table S1", and one with no label by its caption; then cell by cell, each column by
  its header where the header is in each version once, by its place among the rest, and
  each row by its first cell. A column or a row added or removed is said. A table renumbered
  is one gone and one new (DESIGN.md, "Known gaps").
- **Figures** are matched by their label, and their captions compared. A picture is not.
- **Numbers**, with citation keys and bindings, as `reworded` reads them (`reworded.facts`),
  in the prose: those of the reference list and of the tables are left to the reference list
  and the tables. One gone and one new in two sentences paired within a changed stretch
  (`claims.changed`, which lines the sentences up), each with the one most like it by the
  words they share, or in a sentence that reads alike but for its citations and bindings, is
  one changed; the rest are gone or new, each where its sentence is not in the
  other version.
- **Claims**: each changed sentence that claims more, less or the opposite (`claims.moved`).

A PDF holds no table and no figure as one (`auditing.pdf`): where either version is a PDF, the
tables and the figures are not compared, and that is said once for each; a PDF's numbers in
its tables are compared as its prose's.

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


def _folded_header(text: str) -> str:
    return " ".join(text.casefold().split())


def _columns(was: Sequence[str], now: Sequence[str]) -> tuple[list[tuple[int, int]], list[int],
                                                               list[int]]:  # fmt: skip
    """The columns of a table in the two versions, paired: the first with the first, which
    holds the rows' labels; one whose header is in each version once, and not empty, with the
    one of that header, wherever it stands, as typed first, and in any case only where the
    header as typed has no partner ("n" and "N" in one table are two columns); the rest, with
    no header or one repeated, by their order among themselves. And the columns of v1 and of
    v2 that have none: a header in one version once and in the other not at all."""
    pairs = [(0, 0)] if was and now else []
    left_was, left_now = list(range(1, len(was))), list(range(1, len(now)))
    for fold in (lambda text: " ".join(text.split()), _folded_header):
        counted_was = Counter(fold(was[at]) for at in left_was)
        counted_now = Counter(fold(now[at]) for at in left_now)
        for at in list(left_was):
            key = fold(was[at])
            if key and counted_was[key] == 1 and counted_now[key] == 1:
                other = next(there for there in left_now if fold(now[there]) == key)
                pairs.append((at, other))
                left_was.remove(at)
                left_now.remove(other)
    counted_was = Counter(_folded_header(was[at]) for at in left_was)
    counted_now = Counter(_folded_header(now[at]) for at in left_now)

    def alone(header: str, mine: Counter, theirs: Counter) -> bool:
        return bool(header) and mine[header] == 1 and not theirs[header]

    gone = [at for at in left_was if alone(_folded_header(was[at]), counted_was, counted_now)]
    new = [at for at in left_now if alone(_folded_header(now[at]), counted_now, counted_was)]
    rest_was = [at for at in left_was if at not in gone]
    rest_now = [at for at in left_now if at not in new]
    pairs += list(zip(rest_was, rest_now, strict=False))
    gone += rest_was[len(rest_now) :]
    new += rest_now[len(rest_was) :]
    return sorted(pairs, key=lambda pair: pair[1]), gone, new


def _title(header: Sequence[str], at: int) -> str:
    return header[at] if at < len(header) and header[at].strip() else str(at + 1)


def _cells(name: str, was: Sequence[tuple[str, ...]], now: Sequence[tuple[str, ...]]) -> list[str]:
    """What changed in a table, cell by cell: each column in one version only, then each row
    by its first cell, its cells by their columns as `_columns` pairs them. A column in one
    version only is said once, and its cells are not compared."""
    head_was = was[0] if was else ()
    header = now[0] if now else ()
    pairs, gone, new = _columns(head_was, header)
    said = [f"{name}: the column {_title(header, at)!r} is new in v2" for at in new]
    said += [f"{name}: the column {_title(head_was, at)!r} is gone from v2" for at in gone]
    stood, stands = _rows(was[1:]), _rows(now[1:])
    for key, row in stands.items():
        if key not in stood:
            said.append(f"{name}: the row {row[0] if row else ''!r} is new in v2")
            continue
        before = stood[key]
        for one_at, two_at in pairs:
            if not one_at and not two_at:
                continue
            one = before[one_at] if one_at < len(before) else ""
            two = row[two_at] if two_at < len(row) else ""
            if " ".join(one.split()) == " ".join(two.split()):
                continue
            said.append(f"{name}, row {row[0]!r}, column {_title(header, two_at)!r}: {one!r} "
                        f"in v1, {two!r} in v2")  # fmt: skip
    said += [f"{name}: the row {row[0] if row else ''!r} is gone from v2"
             for key, row in stood.items() if key not in stands]  # fmt: skip
    return said


def _display_item(section: str, code: str, message: str, display: Display) -> Item:
    return Item(section, GATE, code, message, INFO, False, display.path, display.line)


def _pdf_of(old: Version, new: Version) -> Version | None:
    """The version that is a PDF, v2 before v1, or None."""
    return next((version for version in (new, old) if version.kind == "PDF"), None)


def _not_compared(kind: str, section: str, old: Version, new: Version) -> list[Item]:
    """What is said where either version is a PDF, in place of comparing its `kind`."""
    pdf = _pdf_of(old, new)
    if pdf is None:
        return []
    which = "v2" if pdf is new else "v1"
    return [Item(section, GATE, "displays-not-compared", f"the {kind} are not compared: {which} "
                 f"is a PDF, whose {kind} are lines of text and not read as {kind}; their "
                 "numbers are compared as the prose's", INFO, False, pdf.path)]  # fmt: skip


def tables(old: Version, new: Version) -> list[Item]:
    """Each table of either version: gone, new, its caption changed, and its cells."""
    if _pdf_of(old, new) is not None:
        return _not_compared("tables", TABLES, old, new)
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
        if not (was.read and table.read):
            unread = " and ".join(v for v, read in (("v1", was.read), ("v2", table.read))
                                  if not read)  # fmt: skip
            found.append(_display_item(TABLES, "table-not-read", f"{_name(table)}: its cells "
                                       f"in {unread} were not read: the float there holds no "
                                       "one table this reading pairs with its one caption, or "
                                       "a file it inputs was not read", table))  # fmt: skip
            found += [_display_item(TABLES, "table-changed", said, table) for said in changes]
            continue
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
    if _pdf_of(old, new) is not None:
        return _not_compared("figures", FIGURES, old, new)
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
    if version.kind == "PDF":
        # A PDF's heading is a line of its own, which no sentence goes on through.
        titled = {heading.line for heading in version.sections if heading.level}
        lines = ["" if at in titled else line for at, line in enumerate(lines, 1)]
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
        if self.version.pdf is not None and at:
            return self.version.pdf.said(at)
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
        for one, two in _paired(was, now, lost, came):
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


def _words_of(read: _Read, at: int) -> set[str]:
    """A sentence's words, without its numbers, as sentences are set side by side."""
    if not 0 <= at < len(read.sentences):
        return set()
    return set(re.findall(r"[^\W\d_]+", read.sentences[at].key.casefold()))


def _paired(was: _Read, now: _Read, lost: list[int], came: list[int]) -> list[tuple[int, int]]:
    """The facts of a changed stretch, one gone with one new: each sentence of v1 with the
    sentence of v2 most like it, by the share of their words they have in common, each
    taken once, the likest first; and in each such pair of sentences the facts of one kind,
    in their order. A fact whose sentence has no counterpart, or none of its kind there, is
    paired with nothing."""
    alike = []
    for one in sorted({was.of[k] for k in lost}):
        mine = _words_of(was, one)
        for two in sorted({now.of[k] for k in came}):
            theirs = _words_of(now, two)
            shared = len(mine & theirs) / len(mine | theirs) if mine | theirs else 0.0
            if shared > 0:
                alike.append((-shared, one, two))
    used_was: set[int] = set()
    used_now: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _shared, one, two in sorted(alike):
        if one in used_was or two in used_now:
            continue
        used_was.add(one)
        used_now.add(two)
        for kind in dict.fromkeys(was.facts[k].kind for k in lost if was.of[k] == one):
            pairs += zip([k for k in lost if was.of[k] == one and was.facts[k].kind == kind],
                         [k for k in came if now.of[k] == two and now.facts[k].kind == kind],
                         strict=False)  # fmt: skip
    return pairs


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
