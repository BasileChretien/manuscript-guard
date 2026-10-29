"""A flow of participants as a paper prints it in a list, held to its own arithmetic.

A CONSORT or STROBE flow is a diagram in most papers, and an image or a set of text boxes
says nothing of how its boxes connect. A list does: its nesting is the flow's structure. So
a flow is read from lists only, a Markdown nested list, a LaTeX `itemize`, `enumerate` or
`description` nested in another, a Word list with its levels, and only by its shape:

    - Assessed for eligibility (n = 412)
      - Excluded (n = 112)
        - Not meeting inclusion criteria (n = 87)
        - Declined to participate (n = 25)
    - Randomised (n = 300)
      - Drug (n = 151)
      - Placebo (n = 149)

A list is read as a flow where it has two levels or more, two items or more at the top,
the two stages `Emitter.flow` asks for at the least, and every item at every level
gives exactly one count, `n = 412` or `(n = 412)`. Its items at the top are the stages; the
items under a stage are the exclusions of the step to the next stage, and the items under an
exclusion the reasons it totals; the items under the last stage are the arms. That is the
flow `Emitter.flow` records, and it is held to the same arithmetic, `emit.flow_problem`:
each stage less its exclusions is the next, and the arms add up to the last stage.

Where the exclusions of a step, or the reasons under an exclusion, add up to more than it
removes, they are read as overlapping, one record excluded for several reasons, which the
flow can only allow for: said as a note, and held to `flow_problem`'s test for overlapping
reasons, none of them more than the step removed. A list where some items give a count and
others none, or two, is said as a note and not read: which numbers are the flow's is not
known. Items under a reason, and items under an arm, a step per arm, are said and not read.

Nothing but its shape is read, so a nested list of counts that is no flow, subgroups under
their groups, reads as one. What `audit --strict` counts is a broken flow under a heading, or
after a caption or a paragraph, that names a flow (`FLOW_NAMES`): any other is said as a
note (Basile, 2026-10-29). The heading is the nearest above the list in its file; the
caption or paragraph is the one directly before it.

Prose, a text box, a drawing and a figure are not read (DESIGN.md, "Known gaps").
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field, replace

from manuscript_guard.emit import flow_problem

#: A count as a flow prints it: `n = 412`, `(n = 412)`, `N = 1,204`, and `n = 12 345` with
#: its thousands parted by a space, a no-break space or a narrow one, as the Lancet prints
#: them. Not a share after it, `n = 45%`, nor a number that runs on into a decimal or a longer
#: grouping, nor one a space and a digit follow, which may be the first of a grouping
#: misprinted (round 1 of #472: "n = 12 345" was read as 12).
_SPACE = r"[ \t\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}]"
_GROUPED = r"[ \N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}\N{THIN SPACE}]"
COUNT = re.compile(
    rf"(?<![\w.])[nN]{_SPACE}*={_SPACE}*"
    rf"(?P<n>\d{{1,3}}(?:,\d{{3}})+|\d{{1,3}}(?:{_GROUPED}\d{{3}})+|\d+)"
    rf"(?!\d|[.,]\d|{_GROUPED}\d)(?!{_SPACE}*%)"
)
#: A Markdown list marker at the start of an item's text, taken off its label.
_MARKER = re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+")
#: The longest label a message quotes of an item.
_LABEL = 50
#: The fewest stages a flow has, as `Emitter.flow` asks.
LEAST_STAGES = 2
#: What names a flow in a heading, a caption or a paragraph, in English: a broken flow under
#: one is counted by `audit --strict`, and under none is a note (Basile, 2026-10-29). Not
#: "flow" alone, which "Blood flow" and "Flow cytometry" hold (round 1 of #472): "participant
#: flow" holds "participant", and a flow chart or a flow diagram is named.
FLOW_NAMES = re.compile(
    r"\b(?:flow[ -]?charts?|flow[ -]diagrams?|participants?|selection|CONSORT"
    r"|PRISMA|STROBE|study\s+population|enrol(?:l)?ments?|recruitment)\b",
    re.IGNORECASE,
)


def names_a_flow(text: str) -> bool:
    """Whether a heading, a caption or a paragraph names a flow (`FLOW_NAMES`)."""
    return bool(FLOW_NAMES.search(text))


@dataclass(frozen=True)
class Item:
    """One item of a list: its own text, its children's left out, its 1-based line, and the
    items nested under it."""

    text: str
    line: int
    children: tuple[Item, ...] = ()


@dataclass(frozen=True)
class FlowRead:
    """A nested list read as a flow, or found and not read (`read` False, with why among
    `notes`). `problems` are what is wrong with its arithmetic; `notes` what was allowed
    for or passed over."""

    line: int
    context: str
    read: bool
    stages: tuple[int, ...] = ()
    exclusions: tuple[tuple[int, ...], ...] = ()
    arms: tuple[int, ...] = ()
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: Whether the heading over it, or the caption or paragraph before it, names a flow:
    #: where neither does, its problems are notes to `audit --strict`.
    named: bool = False


@dataclass(frozen=True)
class Listed:
    """A list's items, with the titles of the headings over it in its file, the nearest and
    those it stands under, and the caption or paragraph directly before it."""

    items: tuple[Item, ...]
    heading: str = ""
    before: str = ""

    @property
    def named(self) -> bool:
        return names_a_flow(self.heading) or names_a_flow(self.before)


def heading_chain(headings: list[tuple[int, int, str]], before: int) -> str:
    """The titles of the headings over a place, each as (where, level, title) in document
    order, `before` the place: the nearest, and each above it of a lesser level, joined. A
    flow under "Participant flow" and then "Trial A" stands under both (round 1 of #472)."""
    chain: list[tuple[int, str]] = []
    for where, level, title in headings:
        if where >= before:
            break
        while chain and chain[-1][0] >= level:
            chain.pop()
        chain.append((level, title))
    return " / ".join(title for _level, title in chain)


def paragraph_before(lines: list[str], first: int) -> str:
    """The paragraph that ends directly before 1-based line `first`, past blank lines."""
    at = first - 2
    while at >= 0 and not lines[at].strip():
        at -= 1
    taken: list[str] = []
    while at >= 0 and lines[at].strip():
        taken.insert(0, lines[at].strip())
        at -= 1
    return " ".join(taken)


def counts_in(text: str) -> list[int]:
    """Each count `text` gives, in order."""
    return [int(re.sub(r"\D", "", found.group("n"))) for found in COUNT.finditer(text)]


def label(item: Item) -> str:
    """An item's text as a message quotes it: its marker and its count taken off."""
    said = " ".join(COUNT.sub(" ", _MARKER.sub("", item.text)).split()).strip(" ()[],;:-")
    return said if len(said) <= _LABEL else said[: _LABEL - 3].rstrip() + "..."


def _tree(entries: list[tuple[int, str, int]]) -> tuple[Item, ...]:
    """Items from (depth, text, line) in document order: an item is under the last one
    before it of a lesser depth."""
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for depth, text, line in entries:
        node: dict = {"text": text, "line": line, "children": []}
        while stack and stack[-1][0] >= depth:
            stack.pop()
        (stack[-1][1]["children"] if stack else roots).append(node)
        stack.append((depth, node))

    def frozen(node: dict) -> Item:
        return Item(node["text"], node["line"], tuple(frozen(c) for c in node["children"]))

    return tuple(frozen(node) for node in roots)


# ------------------------------------------------------------------------- reading lists


def markdown_lists(text: str, hidden: str) -> list[Listed]:
    """Each list of a Markdown paper, its items as pandoc makes them (`blocks.nested_items`),
    each item's text read in `hidden`, the text masked at the same offsets: from its marker
    to the next item or the end of its paragraph; with the heading pandoc prints nearest
    above it, and the paragraph before it, its code and comments blanked."""
    from manuscript_guard.text.blocks import find_headings, nested_items, scannable

    headings = [(text.count("\n", 0, one.start) + 1, one.level, one.title)
                for one in find_headings(text)]  # fmt: skip
    shown = scannable(text).split("\n")
    found = nested_items(text)
    starts = [start for start, _depth, _which in found]
    breaks = [match.start() for match in re.finditer(r"\n[ \t]*\n", text)]
    lists: dict[tuple[int, int], list[tuple[int, str, int]]] = {}
    kinds: dict[int, tuple[str, int]] = {}
    for index, (start, depth, which) in enumerate(found):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        after = bisect_right(breaks, start)
        if after < len(breaks):
            end = min(end, breaks[after])
        own = hidden[start:end].replace("\x00", " ")
        line = text.count("\n", 0, start) + 1
        if depth == 1:
            # Another kind of marker after a blank line starts another list, as pandoc reads
            # it: "1." under the "-" items of a list before it (round 1 of #472).
            kind = _marker_kind(text[start:end])
            part = kinds.get(which, (kind, 0))[1]
            if kinds.get(which, (kind,))[0] != kind and line > 1 and not shown[line - 2].strip():
                part += 1
            kinds[which] = (kind, part)
        lists.setdefault((which, kinds.get(which, ("", 0))[1]), []).append((depth, own, line))
    read = []
    for _key, entries in sorted(lists.items()):
        first = entries[0][2]
        read.append(Listed(_tree(entries), heading_chain(headings, first),
                           paragraph_before(shown, first)))  # fmt: skip
    return read


#: A list marker's kind: its bullet, or an ordered marker's delimiter.
_KIND = re.compile(r"[ \t]*(?:(?P<bullet>[-*+])|\d{1,9}(?P<delimiter>[.)]))")


def _marker_kind(text: str) -> str:
    found = _KIND.match(text)
    return "" if found is None else found.group("bullet") or "1" + found.group("delimiter")


def docx_lists(lines: list[str], levels: dict[int, int],
               ends: dict[int, int] | frozenset[int] = frozenset()) -> list[Listed]:  # fmt: skip
    """Each list of a Word document: a run of lines that are items of a list Word numbers or
    bullets, by their 1-based line and level (`DocxText.levels`). An empty line goes on with
    the run; any other line ends it, and so does each line of `ends`, a heading's, by its line
    and its level (1 where only lines are given), the headings over the run being its own,
    and the paragraph before it its caption or paragraph."""
    if not isinstance(ends, dict):
        ends = dict.fromkeys(ends, 1)
    lists: list[list[tuple[int, str, int]]] = []
    run: list[tuple[int, str, int]] = []
    for number, line in enumerate(lines, 1):
        if number in levels and number not in ends:
            run.append((levels[number] + 1, line, number))
        elif line.strip() or number in ends:
            if run:
                lists.append(run)
            run = []
    if run:
        lists.append(run)

    def listed(entries: list[tuple[int, str, int]]) -> Listed:
        first = entries[0][2]
        heading = heading_chain([(line, ends[line], lines[line - 1]) for line in sorted(ends)],
                                first)  # fmt: skip
        # A paragraph is a line of a Word document's text, and none is blank between two.
        before = next((line for line in reversed(lines[: first - 1]) if line.strip()), "")
        return Listed(_tree(entries), heading, before.strip())

    return [listed(entries) for entries in lists]


_LIST_EVENT = re.compile(
    r"\\(?P<edge>begin|end)[ \t]*\{(?P<env>itemize|enumerate|description)\*?\}"
    r"|\\item(?![A-Za-z@])"
)


def command_read(source):
    """Whether the reader reads a command starting at an offset of a LaTeX file: one it
    masks, outside a comment, a passage TeX skips, a definition's body, a code span and a
    listing."""
    reading = source.reading
    skipped = sorted([*reading.comments, *reading.unprinted, *reading.bodies, *reading.code,
                      *((one.start, one.end) for one in reading.listings)])  # fmt: skip
    masked = reading.masked

    def read(at: int) -> bool:
        if at >= len(masked) or masked[at] != "\x00":
            return False
        return not any(start <= at < end for start, end in skipped)

    return read


def latex_lists(source, hidden: str) -> list[Listed]:
    """Each list of a LaTeX file, from its `itemize`, `enumerate` and `description`
    environments and their `\\item`s where the reader reads them as commands, outside a
    comment, a passage TeX skips, a definition's body, a code span and a listing; each item's
    text read in `hidden`, the file's printed view at the source's offsets, from its `\\item`
    to the next command of a list; with the title of the heading of the file nearest above
    it, and the paragraph of the printed view before it, a caption's included."""
    read = command_read(source)
    events = [found for found in _LIST_EVENT.finditer(source.text) if read(found.start())]
    lists: list[Listed] = []
    entries: list[list] = []
    open_items: list[int | None] = []
    current: int | None = None
    opened = 0
    text = source.text
    shown = hidden.replace("\x00", " ").split("\n")

    def close() -> None:
        first = text.count("\n", 0, opened) + 1
        above = [(one.start, one.level, one.title) for one in source.reading.headings]
        lists.append(Listed(_tree([(d, t, line) for d, t, line in entries]),
                            heading_chain(above, opened), paragraph_before(shown, first)))

    for index, event in enumerate(events):
        if event.group("edge") == "begin":
            if not open_items:
                opened = event.start()
            open_items.append(None)
            current = None
        elif event.group("edge") == "end":
            if not open_items:
                continue
            open_items.pop()
            current = next((at for at in reversed(open_items) if at is not None), None)
            if not open_items:
                close()
                entries = []
        elif open_items:
            entries.append([len(open_items), "", text.count("\n", 0, event.start()) + 1])
            open_items[-1] = current = len(entries) - 1
        if current is not None:
            end = events[index + 1].start() if index + 1 < len(events) else len(hidden)
            entries[current][1] += hidden[event.end() : end].replace("\x00", " ")
    if entries:
        close()
    return lists


# ------------------------------------------------------------------------- reading flows


def _every(items: tuple[Item, ...]):
    for item in items:
        yield item
        yield from _every(item.children)


def read_flow(items: tuple[Item, ...]) -> FlowRead | None:
    """A list read as a flow, or None where it is none: a list of one level, one of a single
    stage, which `Emitter.flow` refuses too, or one whose items give no count. A list whose
    items do not each give exactly one count is found and not read."""
    if len(items) < LEAST_STAGES or not any(item.children for item in items):
        return None
    every = list(_every(items))
    counted = {id(item): counts_in(item.text) for item in every}
    if not any(counted.values()):
        return None
    first = items[0]
    context = " ".join(first.text.split())[:140]
    odd = next((item for item in every if len(counted[id(item)]) != 1), None)
    if odd is not None:
        many = len(counted[id(odd)])
        what = "no count" if not many else f"{many} counts"
        return FlowRead(first.line, context, False, notes=(
            f"a nested list of counts, and its item at line {odd.line} gives {what} where "
            "each gives one (n = N): not read as a flow",))  # fmt: skip

    def n(item: Item) -> int:
        return counted[id(item)][0]

    stages = [n(stage) for stage in items]
    arms = [n(child) for child in items[-1].children]
    notes: list[str] = []
    # Items under a stage that is not the last and that add up to it exactly are a breakdown
    # of it, arms randomised mid-flow or a review's sources, and never its exclusions (round
    # 1 of #472).
    broken_down = {at for at, stage in enumerate(items[:-1])
                   if stage.children and sum(n(c) for c in stage.children) == stages[at]}
    for at in sorted(broken_down):
        notes.append(f"the items under stage {at + 1} ({stages[at]}) add up to it: read as a "
                     "breakdown of it, not as its exclusions")  # fmt: skip
    exclusions = [[] if at in broken_down else [n(child) for child in stage.children]
                  for at, stage in enumerate(items[:-1])]  # fmt: skip
    held = [list(step) for step in exclusions]
    overlapping = []
    steps = zip(stages, stages[1:], exclusions, strict=False)
    for step, (here, there, reasons) in enumerate(steps, 1):
        if not reasons:
            # A step that lists no exclusion is held only to not growing; what it removes is
            # said (round 1 of #472, the funnel of a cohort that prints its stages alone).
            if there < here:
                held[step - 1] = [here - there]
                notes.append(f"stage {step + 1} ({there}) is {here - there} fewer than stage "
                             f"{step} ({here}), and no exclusion is listed")  # fmt: skip
            continue
        if there <= here < there + sum(reasons):
            overlapping.append(step)
            notes.append(f"the exclusions after stage {step} add up to {sum(reasons)}, more "
                         f"than the {here - there} it removes: read as overlapping, a record "
                         "excluded for more than one reason")  # fmt: skip
    problems = []
    problem = flow_problem(stages, held, arms, overlapping or False)
    if problem is not None:
        problems.append(problem)
    for at, stage in enumerate(items[:-1]):
        for exclusion in () if at in broken_down else stage.children:
            problems += _subtotal(exclusion, n, notes)
    if any(arm.children for arm in items[-1].children):
        notes.append("the items under an arm are not read: a step for each arm is not read")
    return FlowRead(first.line, context, True, tuple(stages),
                    tuple(tuple(step) for step in exclusions), tuple(arms), tuple(problems),
                    tuple(notes))  # fmt: skip


def _subtotal(exclusion: Item, n, notes: list[str]) -> list[str]:
    """What is wrong with the reasons under one exclusion, which it totals: a step from the
    exclusion's count to none, held as `flow_problem` holds a step."""
    reasons = [n(reason) for reason in exclusion.children]
    if not reasons:
        return []
    removed = n(exclusion)
    if any(reason.children for reason in exclusion.children):
        notes.append(f"the items under a reason of {label(exclusion)!r} are not read")
    overlapping = sum(reasons) > removed
    if flow_problem([removed, 0], [reasons], [], overlapping) is None:
        if overlapping:
            notes.append(f"the reasons under {label(exclusion)!r} (n = {removed}) add up to "
                         f"{sum(reasons)}: read as overlapping")  # fmt: skip
        return []
    if overlapping:
        return [f"the reasons under {label(exclusion)!r} (n = {removed}) cannot account for "
                f"it, even overlapping: one of them is {max(reasons)}"]  # fmt: skip
    return [f"the reasons under {label(exclusion)!r} (n = {removed}) add up to "
            f"{sum(reasons)}"]  # fmt: skip


def flows_in(lists: list) -> list[FlowRead]:
    """Each list of `lists` read as a flow, or found and not read, with whether what stands
    over it names a flow; the rest left out. A list given as its items alone is named by
    nothing."""
    found = []
    for entry in lists:
        listed = entry if isinstance(entry, Listed) else Listed(tuple(entry))
        flow = read_flow(listed.items)
        if flow is not None:
            found.append(replace(flow, named=listed.named))
    return found


def boxed_counts(boxes: tuple[str, ...]) -> int:
    """How many counts (n = N) the text boxes of a document give, which a flow drawn in
    boxes would: the note that it was not read is said where there are two or more."""
    return sum(len(counts_in(text)) for text in boxes)
