"""What the gates read of a LaTeX manuscript's files, in the shapes they read a Markdown one in
(DESIGN.md, "LaTeX manuscripts", "The reader is chosen once").

- `bindings` gives each `\\mg{namespace.key}` as the `Placeholder` that `placeholders.parse`
  gives for `{{namespace.key}}`, with the line and column of the `.tex`, and what looks meant
  for one and is none: a `\\mg` whose braces hold no key, a near spelling of it, and a
  Markdown binding left in the file.
- `markdown_view` is the file as Markdown would write what it prints, at the same offsets: what
  the reader blanks is a space, and each binding is `{{namespace.key}}`, padded inside its
  braces to the command's width. So the gates that read the sentence a binding stands in, the
  label beside it or the unit after it read a LaTeX file as they read a Markdown one.
- `chain` gives the headings over a place as the Markdown reader's `Chain`, and `in_table`
  whether a place is in a table the author typed.

Past a refusal the rest of the file is read as typed, and its bindings are found there by
their shape, so that a result quoted after the refusal is not said to be quoted nowhere.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path

from manuscript_guard.text.latex.mask import _BARE, _BINDING, NUL
from manuscript_guard.text.latex.structure import Source, read_document
from manuscript_guard.text.placeholders import NAMESPACES, Placeholder
from manuscript_guard.text.sections import Chain

_KEY = re.compile(r"[ \t]*(?P<ns>[a-z]+)\.(?P<key>[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)[ \t]*")
_MG = re.compile(r"\\mg(?![A-Za-z@])")


@dataclass(frozen=True)
class File:
    """One file of a LaTeX manuscript, read: where it is, its source in the tree, its
    bindings and what looks meant for one, and its Markdown view."""

    path: Path
    source: Source
    placeholders: tuple[Placeholder, ...]
    malformed: tuple[tuple[str, int, int], ...]
    view: str

    @property
    def text(self) -> str:
        return self.source.text

    @property
    def scanned(self) -> str:
        """The view the classifier's rules read: the reader's NUL kept, to be taken out."""
        return markdown_view(self.source, list(self.placeholders), blank=NUL)


def bindings(source: Source) -> tuple[list[Placeholder], list[tuple[str, int, int]]]:
    """Each binding of a file, and each thing in it that looks meant for one and is none, as
    `placeholders.parse` gives them: the second as its text, offset and line."""
    text, reading = source.text, source.reading
    starts = [0, *(found.end() for found in re.finditer("\n", text))]
    good: list[Placeholder] = []
    malformed: list[tuple[str, int, int]] = []
    for start, end, inner in _uses(source):
        line = bisect_right(starts, start)
        keyed = _KEY.fullmatch(inner) if inner is not None else None
        if keyed is None or keyed["ns"] not in NAMESPACES:
            malformed.append((text[start:end], start, line))
            continue
        good.append(Placeholder(namespace=keyed["ns"], key=keyed["key"], raw=text[start:end],
                                start=start, end=end, line=line,
                                col=start - starts[line - 1] + 1))  # fmt: skip
    for start, end in reading.suspects:
        malformed.append((text[start:end], start, bisect_right(starts, start)))
    return good, sorted(malformed, key=lambda found: found[1])


def _uses(source: Source) -> list[tuple[int, int, str | None]]:
    """Each `\\mg` the reader read, and past a refusal each found by its shape."""
    reading = source.reading
    if not reading.refusals:
        return [(use.start, use.end, use.inner) for use in reading.bindings]
    # A refusal may stand before what the scan read, as an environment left open does at
    # its `\\begin`: only what the scan read before it is kept, and the rest is found by its
    # shape once (round 1 of #400: a binding after it was counted twice).
    refused = reading.refusals[0].offset
    kept = [(use.start, use.end, use.inner) for use in reading.bindings if use.start < refused]
    return kept + _by_shape(source.text, refused)


def _by_shape(text: str, after: int) -> list[tuple[int, int, str | None]]:
    """Each `\\mg` past a refusal, found by its shape alone."""
    found = []
    for use in _MG.finditer(text, after):
        written = _BINDING.match(text, use.end())
        end = written.end() if written else _BARE.match(text, use.end()).end()
        found.append((use.start(), end, written["inner"] if written else None))
    return found


def markdown_view(source: Source, placeholders: list[Placeholder], blank: str = " ") -> str:
    """The file as Markdown would write what it prints, at the same offsets: a blank is a
    space, or with `blank` NUL the reader's NUL, which the classifier's rules take out before
    they read (`classify._printed`), and a binding is `{{namespace.key}}` padded inside its
    braces."""
    out = list(source.reading.masked.replace(NUL, blank))
    text = source.text
    for placeholder in placeholders:
        width = placeholder.end - placeholder.start
        written = list("{{" + " " * (width - len(placeholder.ref) - 4) + placeholder.ref + "}}")
        # A line break between `\\mg` and its brace stays where it is, in the padding.
        for index in range(width):
            if text[placeholder.start + index] in "\r\n":
                written[index] = text[placeholder.start + index]
        out[placeholder.start : placeholder.end] = written
    return "".join(out)


def chain(source: Source, offset: int) -> Chain:
    """The headings over `offset`, outermost first, as the Markdown reader's `Chain`: LaTeX
    prints each heading it reads, so the printed chain is the same."""
    titles = tuple(heading.title for heading in source.chain_at(offset))
    return Chain(titles, titles)


class Tables:
    """Whether a place is in a table the author typed, found by bisection: a table's span may
    hold another's."""

    def __init__(self, spans: tuple[tuple[int, int], ...]) -> None:
        self.starts = [start for start, _end in spans]
        self.reach = list(accumulate((end for _start, end in spans), max))

    def __contains__(self, offset: int) -> bool:
        before = bisect_right(self.starts, offset)
        return bool(before) and self.reach[before - 1] > offset


def files(manuscript_dir: Path) -> list[File]:
    """Every file of the main text's document and then of the supplement's, each in the order
    its build prints it, the author's packages with them, and the files nothing inputs after."""
    found = []
    for supplementary in (False, True):
        for source in read_document(manuscript_dir, supplementary=supplementary).sources:
            good, malformed = bindings(source)
            found.append(File(manuscript_dir / source.path, source, tuple(good),
                              tuple(malformed), markdown_view(source, good)))  # fmt: skip
    return found
