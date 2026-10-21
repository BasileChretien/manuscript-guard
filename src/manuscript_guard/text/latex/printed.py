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
  nothing, and an inline one as one word; `\\verb` and `\\texttt` as a code span.

It is not the source's length: the gates that read it name the document, not a line of it.
"""

from __future__ import annotations

import re

from manuscript_guard.text.latex.mask import NUL
from manuscript_guard.text.latex.structure import Source
from manuscript_guard.text.latex.views import bindings

#: An inline formula, one word as a journal counts it.
FORMULA = "x"
#: A line LaTeX prints as text that Markdown would read as a heading's or a rule's.
_MARKDOWN_LINE = re.compile(r"(?m)^([ \t]*)(#|-{3,}[ \t]*$|={3,}[ \t]*$)")


def printed_view(sources: list[Source]) -> str:
    """The document the sources make, in the order the build prints them, as Markdown."""
    levels = [heading.level for source in sources for heading in source.reading.headings]
    shallowest = min(levels, default=1)
    return "\n\n".join(_printed(source, shallowest) for source in sources)


def _printed(source: Source, shallowest: int) -> str:
    """One source's part of the view: its body, with each event written as Markdown."""
    reading = source.reading
    if _body(reading) < 0:
        return ""
    events: list[tuple[int, int, str]] = []
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
    # table's rows are none.
    events += [(start, end, " ") for start, end in reading.tables]
    out, at = [], _body(reading)
    # The outermost event at each place is written, and those it holds go with its span.
    for start, end, written in sorted(events, key=lambda event: (event[0], -event[1])):
        if start < at:
            continue
        out.append(_prose(reading.masked[at:start]))
        out.append(written)
        at = end
    out.append(_prose(reading.masked[at:]))
    return "".join(out)


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
    return _MARKDOWN_LINE.sub(r"\1\\\2", masked.replace(NUL, ""))
