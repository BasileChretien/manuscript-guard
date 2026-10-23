"""A LaTeX document as Markdown would write what it prints, for the gates that read a whole
document's sections and words (DESIGN.md, "LaTeX manuscripts", the reader's `printed_view`).

G4 counts a journal's words, finds its required sections and matches its statements in the
Markdown of the main text. A LaTeX document is given to it as the same Markdown:

- each heading as a `#` line, its level as LaTeX nests it, the shallowest a `#`;
- the body only: the preamble's title is the title page's, not the text's;
- an abstract closed where it ends, by a heading with no title, so that the text after it and
  before the next section counts as text, as LaTeX prints it;
- a binding as `{{namespace.key}}` and a citation as `[@key]` or a narrative `@key`, which the
  word count passes over as it does in Markdown and the display-item count reads;
- a float, a figure or a table, as the bindings it places, its caption and cells unread, since
  a journal counts a display item and not its words, and a table typed outside a float as
  nothing, as a Markdown table's rows are counted as no words; a displayed formula as
  nothing, and an inline one as one word; `\\verb` and `\\texttt` as a code span;
- a reference list typed in `thebibliography` as nothing, as Markdown's, which the build
  writes, is no part of the source;
- an abstract written in the preamble, which the class prints, under Abstract;
- LaTeX's single opening quote as a typographic one, since a backtick opens a code span in
  Markdown.

It is not the source's length. `printed` gives it with where each stretch of it comes from, so
that a gate that reads it as Markdown names the `.tex` file and line a finding stands on: a
stretch of prose keeps its source's line breaks, and what the view writes for an event, a
heading's `#` line or a binding's `{{...}}`, stands on the line its event starts on: a
binding a float or a formula holds on the line the float or the formula opens on.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field

from manuscript_guard.text.latex.commands import FLOATS
from manuscript_guard.text.latex.mask import NUL
from manuscript_guard.text.latex.structure import Source
from manuscript_guard.text.latex.views import bindings

#: An inline formula, one word as a journal counts it.
FORMULA = "x"
#: LaTeX's single opening quote, which Markdown would read as a code span's opening.
_QUOTE = "\N{LEFT SINGLE QUOTATION MARK}"
#: A line LaTeX prints as text that Markdown would read as a heading's or a rule's.
_MARKDOWN_LINE = re.compile(r"(?m)^([ \t]*)(#|-{3,}[ \t]*$|={3,}[ \t]*$)")


#: A stretch of the view: its text, the source it comes from and where in it, and whether its
#: line breaks are the source's (prose) or the view's own (what it writes for an event).
Piece = tuple[str, "Source | None", int, bool]


@dataclass(frozen=True)
class Printed:
    """The printed view, and where each stretch of it comes from: its start in `text`, its
    source, its start there, and whether its line breaks are the source's."""

    text: str
    origins: tuple[tuple[int, Source, int, bool], ...]
    _starts: list[int] = field(default_factory=list, compare=False, repr=False)
    _lines: list[int] = field(default_factory=list, compare=False, repr=False)

    def __post_init__(self) -> None:
        self._starts.extend(origin[0] for origin in self.origins)

    def place_line(self, line: int) -> tuple[Source, int] | None:
        """`place` for the first character the view's `line`, counted from 1, prints or that
        follows it: a paragraph that opens a line after a heading's is placed at its own line,
        not the heading's (round 1 of G7 in step 8)."""
        if not self._lines:
            self._lines.extend([0, *(at + 1 for at, char in enumerate(self.text) if char == "\n")])
        offset = self._lines[min(max(line, 1), len(self._lines)) - 1]
        while offset < len(self.text) - 1 and self.text[offset].isspace():
            offset += 1
        return self.place(offset)

    def place(self, offset: int) -> tuple[Source, int] | None:
        """The source and the line of it that `offset` of the view stands on, or None before
        anything the sources print."""
        index = bisect_right(self._starts, offset) - 1
        if index < 0:
            return None
        start, source, at, linear = self.origins[index]
        line = source.text.count("\n", 0, at) + 1
        if linear:
            line += self.text.count("\n", start, offset)
        return source, line


def printed_view(sources: list[Source], *, formula: str = "") -> str:
    """The document the sources make, as the build prints it, as Markdown. `sources` are in
    the include tree's order, each file before the files it inputs, and each file input is
    written where its `\\input` ends, which is where LaTeX prints it. `formula` is what an
    inline formula is written as, `FORMULA` by default."""
    return printed(sources, formula=formula).text


#: What a quoting view writes for a cross-reference, whose number only the compiled
#: document knows: a character no text holds, which a quote's number may stand for (step 8).
POINTER = "\ue000"
#: Where the view G7's text recycling compares opens and closes a quotation LaTeX makes with a
#: command, one of csquotes' (`_QUOTING`), or a `quote`, `quotation` or `displayquote`
#: environment: characters no text holds, between which every word is quoted (rounds 1 and 2
#: of step 13).
QUOTE_OPEN, QUOTE_CLOSE = chr(0xE001), chr(0xE002)
#: A float's caption, or a subfigure's, its short form passed over, to the brace its text
#: opens with.
_CAPTION = re.compile(r"\\(?:sub)?caption\*?\s*(?:\[[^\[\]]*\]\s*)?\{")
#: A quotation csquotes marks with a command: `\\enquote`, `\\textquote`, `\\blockquote`,
#: a language's `\\foreign...` and `\\hyphen...` forms, and the `c` forms that cite (round 2
#: of step 13). Its arguments are read by `_quoted_text`.
_QUOTING = re.compile(
    r"\\(?P<lang>foreign|hyphen|hybrid)?"
    r"(?P<kind>enquote|textcquote|textquote|blockcquote|blockquote|quote)(?![A-Za-z])\*?"
)
#: The start and the end of a quotation environment.
_QUOTATION = re.compile(r"\\(begin|end)\s*\{(?:quote|quotation|displayquote)\}")
#: What the view G2's pointers read writes for a display LaTeX numbers, `DISPLAY`, its kind and
#: its labels, and for a cross-reference, `REFERENCE`, its command and its labels, each to
#: `MARK_END`: characters no text holds (step 13). A display's kind is `t` or `f`, and `T` or
#: `F` where the view cannot say what LaTeX numbers: a float with no `\\caption` it reads, a
#: `\\captionof`, a `longtable`'s caption, a page `\\includepdf` takes in.
DISPLAY, REFERENCE, MARK_END = chr(0xE003), chr(0xE004), chr(0xE005)
#: What that view writes where the appendix begins, at `\\appendix` or IEEEtran's
#: `\\appendices`, to `MARK_END`; `environment` before it where the appendix package's
#: `appendices` or an `appendix` environment opens, and `end` where it ends: the displays
#: between are the supplement's (2026-10-23; rounds 1 and 2). And `references` where the
#: reference list stands, which ends a supplement's part a heading opened (round 2): where
#: a typed `thebibliography` ends, since the view writes the list over from its `\\begin`.
APPENDIX = chr(0xE006)
_APPENDIX = re.compile(
    r"\\(?:appendix|appendices)(?![A-Za-z@])|\\(?P<end>begin|end)\s*\{(?:appendices|appendix)\}"
    r"|(?P<references>\\(?:bibliography|printbibliography)(?![A-Za-z@])"
    r"|\\end\s*\{thebibliography\})"
)
#: A label, which a caption before it in its float gives the number of.
_LABEL = re.compile(r"\\label\s*\{([^{}]*)\}")
#: What numbers a display the view cannot count, by the kinds it may number.
_UNCOUNTED = re.compile(r"\\captionof\s*\{\s*(?P<kind>table|figure)\s*\}|\\includepdf(?![A-Za-z])")


def printed_document(folder, *, supplementary: bool, quoting: bool = False) -> str:
    """A LaTeX manuscript's main text or supplement as Markdown would print it: the files its
    include tree prints, a file nothing inputs and the author's packages left out (step 8).
    `quoting` is the view a quote of the paper is looked for in (`printed`)."""
    return printed_of(folder, supplementary=supplementary, quoting=quoting).text


def printed_of(folder, *, supplementary: bool, quoting: bool = False,
               compared: bool = False) -> Printed:  # fmt: skip
    """`printed_document`, with where each stretch of it comes from."""
    from manuscript_guard.text.latex.structure import read_document

    sources = read_document(folder, supplementary=supplementary).sources
    kept = [source for source in sources
            if not source.loose and not source.path.lower().endswith(".sty")]  # fmt: skip
    return printed(kept, quoting=quoting, compared=compared)


def figure_captions(folder, *, supplementary: bool) -> list[tuple[str, int, str]]:
    """Each caption LaTeX numbers a figure by, in a float that holds a figure, as the view G7's
    text recycling compares prints it, its citations `[@key]` and its bindings `{{...}}`: the
    `.tex` file's path, the caption's line there, and its text, file by file; G4 counts a
    legend's words in it (step 13)."""
    from manuscript_guard.text.latex.structure import read_document

    sources = [source for source in read_document(folder, supplementary=supplementary).sources
               if not source.loose and not source.path.lower().endswith(".sty")]  # fmt: skip
    return captions_in(sources)


def captions_in(sources: list[Source]) -> list[tuple[str, int, str]]:
    """`figure_captions` of the sources of one document, in the include tree's order."""
    view = printed(sources, compared=True)
    ends = [at for at, *_rest in view.origins[1:]] + [len(view.text)]
    found = []
    for source in sources:
        reading, text = source.reading, source.text
        read, comments = _passed_over(reading)
        if _read_in_a_part(source):
            continue
        for start, end in reading.figures:
            for begun, opened, closed in _numbered_captions(text, start, end, read, comments):
                pieces = [view.text[at:until]
                          for (at, of, from_, _linear), until in zip(view.origins, ends,
                                                                       strict=True)
                          if of is source and opened < from_ < closed]  # fmt: skip
                found.append((source.path, text.count("\n", 0, begun) + 1, "".join(pieces)))
    return found


def printed(sources: list[Source], *, quoting: bool = False, formula: str = "",
            compared: bool = False, pointing: bool = False) -> Printed:  # fmt: skip
    """`printed_view`, with where each stretch of it comes from. With `quoting`, the view a
    quote of the paper is looked for in (G13, G8): an inline formula is what it holds, its
    bindings in place, and a cross-reference is `POINTER` (round 1 of G13 in step 8). With
    `compared`, the view G7's text recycling compares with the authors' earlier papers: each
    float's caption is written as a paragraph of its own, and each quotation LaTeX marks
    with a command between `QUOTE_OPEN` and `QUOTE_CLOSE` (round 1 of step 13). With
    `pointing`, the view G2's pointers read: each display LaTeX numbers and each
    cross-reference as `DISPLAY` and `REFERENCE` write them (step 13)."""
    text: list[str] = []
    origins: list[tuple[int, Source, int, bool]] = []
    at = 0
    for chunk, source, start, linear in _pieces(sources, quoting, formula, compared, pointing):
        if chunk and source is not None:
            origins.append((at, source, start, linear))
        text.append(chunk)
        at += len(chunk)
    return Printed("".join(text), tuple(origins))


def _pieces(sources: list[Source], quoting: bool = False, formula: str = "",
            compared: bool = False, pointing: bool = False) -> list[Piece]:  # fmt: skip
    """The view of the sources in pieces, each file input where its `\\input` ends."""
    levels = [heading.level for source in sources for heading in source.reading.headings]
    shallowest = min(levels, default=1)
    queue = iter(sources)

    def written(source: Source) -> list[Piece]:
        return _printed(source, shallowest, following, quoting, formula, compared, pointing)

    def following() -> list[Piece]:
        """The next file, the one the include tree read where this `\\input` ends; none
        where the list given holds no more (round 1 of step 7)."""
        source = next(queue, None)
        return [] if source is None else written(source)

    pieces: list[Piece] = []
    for count, source in enumerate(queue):
        if count:
            pieces.append(("\n\n", None, 0, False))
        pieces += written(source)
    return pieces


def _cuts(source: Source) -> list[int]:
    """Where each file the source inputs ends its `\\input`, in order: the include tree reads
    each file there, and lists it next."""
    return [end for end, _after in source.resumes]


def _printed(
    source: Source, shallowest: int, child=lambda: [], quoting: bool = False, formula: str = "",
    compared: bool = False, pointing: bool = False,
) -> list[Piece]:
    """One source's part of the view: its body, with each event written as Markdown, and
    `child()` where each file it inputs is printed."""
    reading = source.reading
    events: list[tuple[int, int, str | None]] = [(cut, cut, None) for cut in _cuts(source)]
    for heading in reading.headings:
        hashes = "#" * (heading.level - shallowest + 1)
        events.append((heading.start, _title_end(heading),
                       f"\n\n{hashes} {_typeset(heading.title)}\n\n"))  # fmt: skip
    events += _abstracts_closed(reading)
    placeholders = bindings(source)[0]
    for placeholder in placeholders:
        events.append((placeholder.start, placeholder.end, _binding(placeholder)))
    events += _citations(source)
    # A formula and a typed table print the bindings they hold, which a Markdown file's
    # `$...$` and table rows hold as `{{...}}` too (round 1 of step 8).
    if quoting:
        events += _quoted_formulas(source, placeholders)
        events += [(start, end, POINTER) for start, end in reading.pointers]
    else:
        events += _formula_events(reading, placeholders, formula)
    # A code span as Markdown writes one, which a journal's count passes over.
    events += [(start, end, "`" + _prose(reading.masked[start + 1 : end - 1]) + "`")
               for start, end in reading.code]  # fmt: skip
    if pointing:
        events += _pointing_events(source)
    elif compared:
        events += _compared_events(source, placeholders)
    else:
        for start, end in reading.floats:
            events.append((start, end, _bindings_in(placeholders, start, end)))
    # A table typed outside a float: its cells are no words of the text, as a Markdown
    # table's rows are none. Nor is a reference list typed in the source.
    events += _table_events(reading, placeholders)
    # A file that never reaches the body prints nothing but an abstract written in its
    # preamble, and the files it inputs are read.
    ranges = _printed_ranges(reading)

    def shown(start: int, end: int) -> list[Piece]:
        return [(_prose(_typeset(reading.masked[max(start, low) : min(end, high)])), source,
                 max(start, low), True)
                for low, high in ranges if max(start, low) < min(end, high)]  # fmt: skip

    def inside(offset: int) -> bool:
        return any(low <= offset <= high for low, high in ranges)

    out: list[Piece] = []
    at = 0
    # The outermost event at each place is written, and those it holds go with its span. A
    # file input is never passed over: where an event holds its `\\input`, as a float may, it
    # is printed after that event, and before an event that starts where the `\\input` ends.
    ordered = sorted(events, key=lambda event: (event[0], event[2] is not None, -event[1]))
    for start, end, written in ordered:
        if written is None:
            if start > at:
                out += shown(at, start)
                at = start
            out += child()
            continue
        if start < at or not inside(start):
            continue
        out += shown(at, start)
        out.append((written, source, start, False))
        at = end
    out += shown(at, len(reading.masked))
    return out


def _compared_events(source: Source, placeholders) -> list[tuple[int, int, str]]:
    """The events the view G7's text recycling compares writes in place of a float's: the
    float as the bindings it places outside its captions, and each caption a paragraph of
    its own, read as the text around it is; and each quotation one of csquotes' commands or a
    quotation environment marks, between `QUOTE_OPEN` and `QUOTE_CLOSE` (rounds 1 and 2 of
    step 13)."""
    reading, text = source.reading, source.text
    read, comments = _passed_over(reading)
    events: list[tuple[int, int, str]] = []
    for start, end in reading.floats:
        captions = [(opened, closed) for _begun, opened, closed
                    in _arguments(text, _CAPTION, start, end, comments)
                    if read(opened)]  # fmt: skip
        outside = [placeholder for placeholder in placeholders
                   if not any(opened < placeholder.start < closed
                              for opened, closed in captions)]  # fmt: skip
        edges = [start, *(edge for opened, closed in captions for edge in (opened + 1, closed)),
                 end]  # fmt: skip
        for index in range(0, len(edges), 2):
            written = _bindings_in(outside, start, end) if index == 0 else ""
            events.append((edges[index], edges[index + 1],
                           written + ("\n\n" if captions else "")))  # fmt: skip
    for begun, opened, closed in _quoted_text(text, comments):
        if read(begun):
            events += [(begun, opened + 1, QUOTE_OPEN),
                       (closed, closed + 1, QUOTE_CLOSE)]  # fmt: skip
    for found in _QUOTATION.finditer(text):
        if read(found.start()):
            mark = f"\n\n{QUOTE_OPEN}" if found[1] == "begin" else f"{QUOTE_CLOSE}\n\n"
            events.append((found.start(), found.end(), mark))
    return events


def _pointing_events(source: Source) -> list[tuple[int, int, str]]:
    """The events the view G2's pointers read writes in place of a float's and a
    cross-reference's: each float as the displays its captions number, in order, each with
    the labels after it; a float with no caption read, a `\\captionof`, a `longtable`'s caption
    and a `\\includepdf` as a display the view cannot count; and each cross-reference as its
    command and its labels (step 13)."""
    reading, text = source.reading, source.text
    read, comments = _passed_over(reading)
    events = [(start, end, _float_marks(source, start, end, read, comments))
              for start, end in reading.floats]  # fmt: skip
    # A caption outside the floats the reader knows numbers a display of a float it does not,
    # `SCfigure` or a `\\newfloat`, of a kind the view cannot tell (round 2 of step 13, part 2).
    # Not one in an `algorithm` or a `listing`, which number neither, nor in a definition's
    # body that holds no environment, which prints a caption where it is used (round 3); one
    # whose body begins or ends a float may print a whole float there (round 4).
    bodies = [(low, high) for low, high in reading.bodies
              if not _ENVIRONMENT.search(text, low, high)]  # fmt: skip
    known = [*reading.floats, *reading.tables, *bodies,
             *_spans(text, _OTHER_FLOATS, 0, len(text), read)]  # fmt: skip
    if not _read_in_a_part(source):
        for begun, _opened, closed in _arguments(text, _NUMBERED, 0, len(text), comments):
            if read(begun) and not any(low <= begun < high for low, high in known):
                events.append((begun, closed + 1,
                               DISPLAY + "T" + MARK_END + DISPLAY + "F" + MARK_END))  # fmt: skip
    for start, end in reading.tables:
        if text.startswith("\\begin{longtable}", start) and any(
            read(found.start()) for found in _NUMBERED.finditer(text, start, end)
        ):
            events.append((start, end, DISPLAY + "T" + MARK_END))
    for found in _UNCOUNTED.finditer(text):
        if read(found.start()):
            kinds = [found["kind"][0].upper()] if found["kind"] else ["T", "F"]
            # A `\\captionof`'s caption goes with it, as a float's does (round 1 of step 13,
            # part 2): a pointer in it is no citation.
            ended = found.end()
            if found["kind"]:
                ended = _group_end(text, _options_end(text, ended, comments), comments)
            events.append((found.start(), max(ended, found.end()),
                           "".join(DISPLAY + kind + MARK_END for kind in kinds)))  # fmt: skip
    for start, end in reading.pointers:
        typed = text[start:end]
        command = re.match(r"\\([A-Za-z]+)", typed)
        opened = typed.find("{")
        if command is None or opened < 0:
            continue
        labels = ",".join(label.strip() for label in typed[opened + 1 : -1].split(","))
        events.append((start, end, REFERENCE + command[1] + ":" + labels + MARK_END))
    # Not in a definition's body, which opens the appendix where it is used.
    for found in _APPENDIX.finditer(text, max(reading.body_start, 0)):
        if read(found.start()) and not any(low <= found.start() < high
                                           for low, high in reading.bodies):  # fmt: skip
            kind = ("references" if found["references"] else "end" if found["end"] == "end"
                    else "environment" if found["end"] else "")  # fmt: skip
            # A typed list's mark goes where it ends, past the list's own event (fix round).
            typed = (found["references"] or "").startswith("\\end")
            start = found.end() if typed else found.start()
            events.append((start, found.end(), APPENDIX + kind + MARK_END))
    return events


def _passed_over(reading):
    """What a view's events pass over: whether an offset is read, out of a comment, a listing,
    code and what TeX does not print; and the spans a group's braces are not counted in, by
    where each starts: a comment, and code, `\\verb|{|` and a listing, which print a brace as
    typed (round 3 of step 13), none empty, which a scan would jump to where it stands and
    stop there (round 4)."""
    listings = [(listing.start, listing.end) for listing in reading.listings]
    passed = [*reading.comments, *reading.unprinted, *reading.code, *listings]

    def read(at: int) -> bool:
        return not any(start <= at < end for start, end in passed)

    comments = {start: end for start, end in [*reading.comments, *reading.code, *listings]
                if end > start}  # fmt: skip
    return read, comments


def _float_marks(source: Source, start: int, end: int, read, comments: dict) -> str:
    """What the view G2's pointers read writes for the float from `start` to `end`: a mark for
    each display its captions number, with the labels after it. A float with a starred caption
    only, or continued from the last (`\\ContinuedFloat`), numbers nothing. One with no caption
    read numbers nothing where its file is read inside a float or it holds a file input, whose
    captions are the float's (round 1 of step 13, part 2); otherwise it may number one
    through a command of the author's, which the view cannot count."""
    text = source.text
    kind = "f" if (start, end) in set(source.reading.figures) else "t"
    captions = [begun for begun, _opened, _closed
                in _numbered_captions(text, start, end, read, comments)]  # fmt: skip
    if _read_in_a_part(source) or any(
        read(found.start()) for found in _CONTINUED.finditer(text, start, end)
    ):
        return ""
    if not captions:
        inherited = start == 0 and bool(set(source.environments) & FLOATS)
        starred = any(read(found.start()) for found in _ANY_CAPTION.finditer(text, start, end))
        if starred or inherited or _holds_input(source, start, end):
            return ""
        return DISPLAY + kind.upper() + MARK_END
    labels = [(found.start(), found[1].strip()) for found in _LABEL.finditer(text, start, end)
              if read(found.start())]  # fmt: skip
    named = _named(captions, labels, _parts(text, start, end, read))
    return "".join(DISPLAY + kind + ",".join(labels_of) + MARK_END for labels_of in named)


def _named(captions: list[int], labels: list[tuple[int, str]], parts) -> list[list[str]]:
    """The labels each caption's display has: those after it, before the next; and a part's,
    "1a", the display of the caption its float numbers after it, or its last (round 2 of
    step 13, part 2)."""
    named: list[list[str]] = [[] for _ in captions]
    for at, label in labels:
        if any(low <= at < high for low, high in parts):
            after = [index for index, begun in enumerate(captions) if begun > at]
            named[after[0] if after else len(captions) - 1].append(label)
        else:
            before = [index for index, begun in enumerate(captions) if begun <= at]
            if before:
                named[before[-1]].append(label)
    return named


def _holds_input(source: Source, start: int, end: int) -> bool:
    """Whether the float from `start` to `end` holds a file input, read inside it."""
    return any(start < cut < end for cut in _cuts(source))


def _read_in_a_part(source: Source) -> bool:
    """Whether `source` is a file input inside a `subfigure` or a `subtable`, whose captions
    number a part of a float (round 2 of step 13, part 2)."""
    return bool(set(source.environments) & _PARTS)


def _parts(text: str, start: int, end: int, read) -> list[tuple[int, int]]:
    """Where each outermost `subfigure` or `subtable` between `start` and `end` runs."""
    return _spans(text, _SUBFLOAT, start, end, read)


def _spans(text: str, pattern: re.Pattern[str], start: int, end: int, read):
    """Where each outermost environment `pattern` begins and ends runs, between `start` and
    `end`."""
    parts, depth, opened = [], 0, 0
    for found in pattern.finditer(text, start, end):
        if not read(found.start()):
            continue
        if found[1] == "begin":
            opened = found.start() if depth == 0 else opened
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                parts.append((opened, found.end()))
    return parts


def _numbered_captions(text: str, start: int, end: int, read, comments: dict):
    """Each caption LaTeX numbers a float by between `start` and `end`, where it starts and
    where its argument runs: not one inside a `subfigure` or a `subtable`, which numbers a
    part of the float (round 1 of step 13, part 2)."""
    parts = _parts(text, start, end, read)
    return [(begun, opened_at, closed)
            for begun, opened_at, closed in _arguments(text, _NUMBERED, start, end, comments)
            if read(begun) and not any(low <= begun < high for low, high in parts)]  # fmt: skip


#: The environments of subcaption whose `\\caption` numbers a part of a float, not a float.
_PARTS = frozenset({"subfigure", "subtable"})
_SUBFLOAT = re.compile(r"\\(begin|end)\s*\{(?:subfigure|subtable)\}")
#: A float that continues the last of its kind, numbered as it is.
_CONTINUED = re.compile(r"\\ContinuedFloat(?![A-Za-z])")
#: The floats packages give that number neither a table nor a figure: an algorithm, and
#: minted's listing (round 3 of step 13, part 2).
_OTHER_FLOATS = re.compile(r"\\(begin|end)\s*\{(?:algorithm\*?|listing)\}")
#: Where an environment begins or ends.
_ENVIRONMENT = re.compile(r"\\(?:begin|end)\s*\{")


#: A caption LaTeX numbers: not a starred one, nor a subfigure's.
_NUMBERED = re.compile(r"\\caption(?![A-Za-z*])\s*(?:\[[^\[\]]*\]\s*)?\{")
#: A float's caption, numbered or starred.
_ANY_CAPTION = re.compile(r"\\caption\*?(?![A-Za-z])")


def _arguments(text: str, pattern: re.Pattern[str], start: int, end: int, comments: dict):
    """Where each command of `pattern` between `start` and `end` starts, and where the
    argument it opens runs, from its opening brace to its closing one, where that closes
    before `end`."""
    for found in pattern.finditer(text, start, end):
        closed = _closing(text, found.end() - 1, comments)
        if 0 <= closed < end:
            yield found.start(), found.end() - 1, closed


def _quoted_text(text: str, comments: dict):
    """Where each quotation csquotes marks with a command starts, and where its text runs,
    from its opening brace to its closing one: past a language's `{...}`, the options
    `[...]`, and a `c` form's citation key `{...}`."""
    for found in _QUOTING.finditer(text):
        if found["kind"] == "quote" and not found["lang"]:
            continue  # LaTeX's own `\\quote`, which begins the environment's body
        at = found.end()
        if found["lang"]:
            at = _group_end(text, at, comments)
        at = _options_end(text, at, comments)
        if "cquote" in found["kind"]:
            at = _options_end(text, _group_end(text, at, comments), comments)
        at = _ahead(text, at, comments)
        if at < 0 or at >= len(text) or text[at] != "{":
            continue
        closed = _closing(text, at, comments)
        if closed >= 0:
            yield found.start(), at, closed


def _ahead(text: str, at: int, comments: dict) -> int:
    """Past the white space and the comments from `at`, which LaTeX reads past between a
    command's arguments (round 3 of step 13); -1 stays -1."""
    while 0 <= at < len(text):
        if at in comments:
            at = comments[at]
        elif text[at].isspace():
            at += 1
        else:
            break
    return at


def _group_end(text: str, at: int, comments: dict) -> int:
    """Past the group `{...}` ahead of `at`; -1 where none is."""
    at = _ahead(text, at, comments)
    if at < 0 or at >= len(text) or text[at] != "{":
        return -1
    closed = _closing(text, at, comments)
    return closed + 1 if closed >= 0 else -1


def _options_end(text: str, at: int, comments: dict) -> int:
    """Past each option `[...]` ahead of `at`, a `]` inside braces kept in it, as csquotes
    asks for one: `[{\\cite[p.~3]{key}}]` (round 3 of step 13)."""
    while at >= 0:
        ahead = _ahead(text, at, comments)
        if ahead >= len(text) or text[ahead] != "[":
            return at
        # Within its paragraph: an option whose braces do not close there ends at its first
        # `]`, as it did before braces were counted (round 4 of step 13).
        blank = _BLANK_LINE.search(text, ahead)
        limit = blank.start() if blank else len(text)
        depth, at = 0, ahead + 1
        while at < limit and not (text[at] == "]" and depth == 0):
            if text[at] == "\\":
                at += 2
                continue
            if at in comments:
                at = comments[at]
                continue
            depth += {"{": 1, "}": -1}.get(text[at], 0)
            at += 1
        if at >= limit:
            at = text.find("]", ahead)
            if at < 0:
                return -1
        at += 1
    return at


#: A line with nothing on it, which ends a paragraph, in a file with CRLF line ends too
#: (round 5 of step 13).
_BLANK_LINE = re.compile(r"\n[ \t\r]*\n")


def _closing(text: str, opened: int, comments: dict) -> int:
    """Where the group that opens at `opened` closes, past escaped braces and what
    `comments` holds by where each starts, the comments the reader read and code; -1 where it
    does not. A `%` the reader did not read as a comment, in `\\url{}`, is a character (round
    2 of step 13)."""
    depth, at = 0, opened
    while at < len(text):
        character = text[at]
        if character == "\\":
            at += 2
            continue
        if at in comments:
            at = comments[at]
            continue
        depth += {"{": 1, "}": -1}.get(character, 0)
        if depth == 0:
            return at
        at += 1
    return -1


def _typeset(prose: str) -> str:
    """Prose with the dashes LaTeX joins from hyphens, `---` and `--`, as the characters it
    prints: a quotation with one is then the words its source holds (round 1 of G7 in step
    8). Code is written apart, as typed. Typed before the NULs go, so that hyphens a `{}`
    keeps apart stay apart, and before a line of `---` is escaped as Markdown's rule (round
    2)."""
    return prose.replace("---", "\u2014").replace("--", "\u2013")


def _binding(placeholder) -> str:
    """A binding in prose as LaTeX prints its value: where it stands, nothing added round it,
    so a sentence quoted from the paper that ends after one is found in it (step 8, G13)."""
    return "{{" + placeholder.ref + "}}"


def _formula_events(reading, placeholders, formula: str = "") -> list[tuple[int, int, str]]:
    """Each formula as the view writes it, with the bindings it holds."""
    return [(start, end, written + _bindings_in(placeholders, start, end))
            for start, end, written in _formulas(reading, formula)]  # fmt: skip


def _quoted_formulas(source: Source, placeholders) -> list[tuple[int, int, str]]:
    """Each inline formula as what it holds between its `$` or `\\(`, its bindings
    `{{...}}`, so that "$n = \\mg{results.n}$" reads as a quote of the PDF has it; a displayed
    one, or another shape, as the view writes it."""
    events = []
    for start, end, written in _formulas(source.reading):
        typed = source.text[start:end]
        width = 1 if typed.startswith("$") and not typed.startswith("$$") else 0
        width = 2 if typed.startswith("\\(") else width
        if not width or not typed.endswith(typed[0] if width == 1 else "\\)"):
            events.append((start, end, written + _bindings_in(placeholders, start, end)))
            continue
        inner = list(typed)
        for placeholder in sorted(placeholders, key=lambda p: p.start, reverse=True):
            if start <= placeholder.start and placeholder.end <= end:
                inner[placeholder.start - start : placeholder.end - start] = _binding(placeholder)
        events.append((start, end, "".join(inner)[width:-width]))
    return events


def _table_events(reading, placeholders) -> list[tuple[int, int, str]]:
    """Each typed table and reference list as nothing but the bindings it holds."""
    return [(start, end, " " + _bindings_in(placeholders, start, end))
            for start, end in (*reading.tables, *reading.references)]  # fmt: skip


def _bindings_in(placeholders, start: int, end: int) -> str:
    """The bindings a span holds, each as Markdown writes it, in the order they stand."""
    return "".join(" {{" + p.ref + "}} " for p in placeholders if start <= p.start < end)


def _printed_ranges(reading) -> list[tuple[int, int]]:
    """What of a file prints: each abstract written in its preamble, then its body."""
    body = _body(reading)
    if body < 0:
        body = len(reading.masked)
    return [*((start, end) for start, end in reading.abstracts if start < body),
            (body, len(reading.masked))]  # fmt: skip


def _body(reading) -> int:
    """Where the file's printed text starts: past `\\begin{document}`, or -1 for none."""
    return reading.body_start


def _title_end(heading) -> int:
    """Where a heading's command and title end, which its `#` line stands for."""
    return max(heading.end, heading.start)


def _formulas(reading, formula: str = "") -> list[tuple[int, int, str]]:
    """A displayed formula as nothing, and an inline one as one word. Given `formula`, `$x$`,
    an inline one as it and a displayed one as it in double signs, `$$x$$`, so that neither
    is passed over (round 3 of step 10)."""
    if formula:
        return [(start, end, f" {formula[0]}{formula}{formula[-1]} " if display else
                 f" {formula} ") for start, end, display in reading.maths]  # fmt: skip
    return [(start, end, " " if display else f" {FORMULA} ")
            for start, end, display in reading.maths]  # fmt: skip


def _abstracts_closed(reading) -> list[tuple[int, int, str]]:
    """A heading with no title where each abstract ends, so that what follows is text."""
    return [(end, end, "\n\n#\n\n") for _start, end in reading.abstracts]


def _citations(source: Source) -> list[tuple[int, int, str]]:
    """Each citation command as Markdown writes it: `[@a; @b]`, or `@a` where it is narrative."""
    commands: dict[tuple[int, int], list] = {}
    for cited in source.reading.cited:
        commands.setdefault((cited.start, cited.end), []).append(cited)
    events = []
    for (start, end), keys in commands.items():
        if keys[0].narrative:
            written = " ".join("@" + cited.key for cited in keys)
        else:
            written = "[" + "; ".join("@" + cited.key for cited in keys) + "]"
        events.append((start, end, f" {written} "))
    return events


def _prose(masked: str) -> str:
    """What the reader keeps of a stretch, as Markdown would print it: the blanks taken out,
    and a line Markdown would read as a heading or a rule escaped."""
    return _MARKDOWN_LINE.sub(r"\1\\\2", masked.replace(NUL, "").replace("`", _QUOTE))
