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

It is not the source's length: the gates that read it name the document, not a line of it.
"""

from __future__ import annotations

import re

from manuscript_guard.text.latex.mask import NUL
from manuscript_guard.text.latex.structure import Source
from manuscript_guard.text.latex.views import bindings

#: An inline formula, one word as a journal counts it.
FORMULA = "x"
#: LaTeX's single opening quote, which Markdown would read as a code span's opening.
_QUOTE = "\N{LEFT SINGLE QUOTATION MARK}"
#: A line LaTeX prints as text that Markdown would read as a heading's or a rule's.
_MARKDOWN_LINE = re.compile(r"(?m)^([ \t]*)(#|-{3,}[ \t]*$|={3,}[ \t]*$)")


def printed_view(sources: list[Source]) -> str:
    """The document the sources make, as the build prints it, as Markdown. `sources` are in
    the include tree's order, each file before the files it inputs, and each file input is
    written where its `\\input` ends, which is where LaTeX prints it."""
    levels = [heading.level for source in sources for heading in source.reading.headings]
    shallowest = min(levels, default=1)
    queue = iter(sources)

    def written(source: Source) -> str:
        return _printed(source, shallowest, lambda: written(next(queue)))

    return "\n\n".join(written(source) for source in queue)


def _cuts(source: Source) -> list[int]:
    """Where each file the source inputs ends its `\\input`, in order: the include tree reads
    each file there, and lists it next."""
    return [end for end, _after in source.resumes]


def _printed(source: Source, shallowest: int, child=lambda: "") -> str:
    """One source's part of the view: its body, with each event written as Markdown, and
    `child()` where each file it inputs is printed."""
    reading = source.reading
    events: list[tuple[int, int, str | None]] = [(cut, cut, None) for cut in _cuts(source)]
    for heading in reading.headings:
        hashes = "#" * (heading.level - shallowest + 1)
        events.append((heading.start, _title_end(heading),
                       f"\n\n{hashes} {heading.title}\n\n"))  # fmt: skip
    events += _abstracts_closed(reading)
    placeholders = bindings(source)[0]
    for placeholder in placeholders:
        events.append((placeholder.start, placeholder.end, " {{" + placeholder.ref + "}} "))
    events += _citations(source)
    events += _formulas(reading)
    # A code span as Markdown writes one, which a journal's count passes over.
    events += [(start, end, "`" + _prose(reading.masked[start + 1 : end - 1]) + "`")
               for start, end in reading.code]  # fmt: skip
    for start, end in reading.floats:
        placed = [p.ref for p in placeholders if start <= p.start < end]
        events.append((start, end, "".join(" {{" + ref + "}} " for ref in placed)))
    # A table typed outside a float: its cells are no words of the text, as a Markdown
    # table's rows are none. Nor is a reference list typed in the source.
    events += [(start, end, " ") for start, end in (*reading.tables, *reading.references)]
    # A file that never reaches the body prints nothing but an abstract written in its
    # preamble, and the files it inputs are read.
    ranges = _printed_ranges(reading)

    def shown(start: int, end: int) -> str:
        return "".join(_prose(reading.masked[max(start, low) : min(end, high)])
                       for low, high in ranges if max(start, low) < min(end, high))  # fmt: skip

    def inside(offset: int) -> bool:
        return any(low <= offset <= high for low, high in ranges)

    out, at = [], 0
    # The outermost event at each place is written, and those it holds go with its span. A
    # file input is never passed over: where an event holds its `\\input`, as a float may, it
    # is printed after that event, and before an event that starts where the `\\input` ends.
    ordered = sorted(events, key=lambda event: (event[0], event[2] is not None, -event[1]))
    for start, end, written in ordered:
        if written is None:
            if start > at:
                out.append(shown(at, start))
                at = start
            out.append(child())
            continue
        if start < at or not inside(start):
            continue
        out.append(shown(at, start))
        out.append(written)
        at = end
    out.append(shown(at, len(reading.masked)))
    return "".join(out)


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


def _formulas(reading) -> list[tuple[int, int, str]]:
    """A displayed formula as nothing, and an inline one as one word."""
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
