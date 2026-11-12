"""Whether a reporting checklist's answer quotes words the manuscript has where it says (G5).

An item's `where:` names a heading, and any manuscript has a Methods. In the IICARus trial
(Hair, Macleod and Sena, Res Integr Peer Rev 2019;4:12), asking authors to complete the ARRIVE
checklist changed nothing: of 1,689 manuscripts, none was fully compliant in either arm. The
completed checklist is not the reporting; the sentence is. So an item may carry `quote:`, the
sentence (or a part of one) that addresses it, and the gate holds the quote to the manuscript.
A person or an agent names the sentence; this module only says whether it is there.

**Where it is looked for.** Under each heading `where` names, as G5 has always matched a
heading against `where` (`reporting._points_somewhere_real`): that heading's section,
subsections included, in the main text or the supplement. Where `where` names a table or a
figure ("Table 1", "Figure S2", "eTable 1"), in that display's caption as well: a legend typed
as a paragraph that opens with the display's pointer, as G2 reads one (`opening_pointer`), and
an emitted table's caption, numbered as the build numbers it (`display_numbers`).

**How it is found.** As a review finding's quote is found in the manuscript
(`anchoring.stands`), which is as G7 finds a passage in a work's source
(`gates.quotations.words_in`): typography, white space and case folded, as whole words, piece
by piece in order where words are left out, Markdown's marks of emphasis and code out of both
sides. Each section is read twice: as written, its bindings as the author typed them
(`{{results.x}}`), and as the build prints it, each value binding its display and each anchor
nothing (`figure_alt.printed_alt`), since an author often copies the sentence from the built
.docx. A quote matches one reading or the other, not a mixture of the two. A comment prints
nothing, and is no part of either.

A quote holds `QUOTE_WORDS` words or more: a word or two is found in any paper.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from manuscript_guard.anchoring import QUOTE_WORDS, _written, plain, words
from manuscript_guard.gates.figure_alt import printed_alt
from manuscript_guard.gates.pointers import _POINTER, TABLE, _kind
from manuscript_guard.gates.quotations import words_in
from manuscript_guard.literature.sources import normalise
from manuscript_guard.text.masking import blank_comments, without_front_matter
from manuscript_guard.text.sections import split_sections

__all__ = [
    "QUOTE_WORDS", "Caption", "Manuscript", "Placed", "captions", "display_named", "of_project",
    "read", "typed_legends",
]  # fmt: skip

#: What may close a `where` that names a display, "Table 1." or "Figure 2:".
_CLOSING = " .:;,"


@dataclass(frozen=True)
class Caption:
    """A display's caption, and the display it is of: its kind, its document, its number."""

    kind: str
    supplementary: bool
    number: int
    text: str

    @property
    def label(self) -> str:
        kind = "Table" if self.kind == TABLE else "Figure"
        return f"{kind} {'S' * self.supplementary}{self.number}"


@dataclass(frozen=True)
class _Part:
    """A stretch a quote may stand in: a section, under its heading's title, or a caption.
    Each text is folded as printed and as written: its own, and with its subsections."""

    title: str
    caption: tuple[str, bool, int] | None
    own: tuple[str, str]
    enclosed: tuple[str, str]

    @property
    def shown(self) -> str:
        if self.caption is not None:
            kind, supplementary, number = self.caption
            return f"the caption of {Caption(kind, supplementary, number, '').label}"
        return repr(self.title) if self.title else "the text before the first heading"


@dataclass(frozen=True)
class Placed:
    """Where a quote was looked for and whether it stands there; where it stands instead."""

    under: bool
    searched: tuple[str, ...]
    elsewhere: tuple[str, ...]


def display_named(where: str) -> tuple[str, bool, int] | None:
    """The display `where` names, whole, as G2 reads a pointer: "Table 1", "Figure S2",
    "Supplementary Table 3", "eFigure 1", a closing stop aside; None for anything else."""
    stripped = where.strip().rstrip(_CLOSING)
    found = _POINTER.match(stripped)
    if found is None or found.end() != len(stripped) or found["rest"]:
        return None
    supplementary = bool(found["supp"] or found["e"] or found["after"] or found["s0"])
    return _kind(found["kind"]), supplementary, int(found["n0"])


def _names(where: str, title: str) -> bool:
    """Whether `where` names the heading `title`, as G5 matches a heading to an answer."""
    lowered, heading = where.lower(), title.lower()
    return bool(heading) and (heading in lowered or lowered in heading)


def _folded(written: str, namespace: Mapping[str, object]) -> tuple[str, str]:
    """`written` as printed and as written, each folded as `anchoring.read_of` folds a text."""
    printed = printed_alt(written, namespace)  # type: ignore[arg-type]
    return normalise(plain(printed)).lower(), normalise(_written(written)).lower()


def _stands(quote: str, read: tuple[str, str]) -> bool:
    printed, written = read
    return words_in(printed, plain(quote)) or words_in(written, _written(quote))


@dataclass(frozen=True)
class Manuscript:
    """The manuscript's sections and captions, as a checklist's quotes are looked for."""

    parts: tuple[_Part, ...]

    def names_display(self, where: str) -> bool:
        """Whether `where` names a display with a caption read here."""
        named = display_named(where)
        return named is not None and any(part.caption == named for part in self.parts)

    def _named(self, where: str) -> list[_Part]:
        display = display_named(where)
        return [part for part in self.parts
                if (part.caption is None and _names(where, part.title))
                or (part.caption is not None and part.caption == display)]  # fmt: skip

    def judged(self, quote: str | None, where: str) -> Placed | None:
        """`place`, or None where `quote` is no quote: none, or fewer than `QUOTE_WORDS`
        words, which are found in any paper."""
        quote = (quote or "").strip()
        if words(quote) < QUOTE_WORDS:
            return None
        return self.place(quote, where)

    def place(self, quote: str, where: str) -> Placed:
        """Whether `quote` stands under what `where` names; and if not, where it does: the
        sections whose own text holds it, else those that hold it with their subsections."""
        named = self._named(where)
        searched = tuple(dict.fromkeys(part.shown for part in named))
        if any(_stands(quote, part.enclosed) for part in named):
            return Placed(True, searched, ())
        own = [part.shown for part in self.parts if _stands(quote, part.own)]
        found = own or [part.shown for part in self.parts if _stands(quote, part.enclosed)]
        return Placed(False, searched, tuple(dict.fromkeys(found)))


def _sections(text: str, namespace: Mapping[str, object]) -> Iterable[_Part]:
    shown = without_front_matter(blank_comments(text.replace("\r\n", "\n")))
    for section in split_sections(shown):
        yield _Part(section.title, None, _folded(section.body, namespace),
                    _folded(section.enclosed, namespace))  # fmt: skip


def read(
    texts: Sequence[str],
    namespace: Mapping[str, object],
    captions: Iterable[Caption] = (),
) -> Manuscript:
    """The manuscript `texts`, each a Markdown file or a LaTeX document as it prints in
    Markdown, and the `captions` of its displays, read for quotes. `namespace` gives each
    value binding's display, as `load_namespace` does."""
    parts = [part for text in texts for part in _sections(text, namespace)]
    for caption in captions:
        folded = _folded(caption.text, namespace)
        parts.append(_Part("", (caption.kind, caption.supplementary, caption.number), folded,
                           folded))  # fmt: skip
    return Manuscript(tuple(parts))


def of_project(project, namespace: Mapping[str, object] | None, results) -> Manuscript:
    """A project's manuscript read for quotes: each Markdown file, main text and supplement,
    with the captions of the displays it places; or a LaTeX manuscript's two documents as
    they print in Markdown, as G5 reads its headings (step 8). The values are loaded where
    `namespace` or `results` is not given."""
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.text.reader import LATEX, manuscript_format

    if namespace is None or results is None:
        from manuscript_guard.contracts import load_namespace

        loaded, found, _literature, _report = load_namespace(project)
        namespace = loaded if namespace is None else namespace
        results = found if results is None else results
    folder = project.path("manuscript")
    if manuscript_format(folder) == LATEX:
        from manuscript_guard.text.latex.printed import printed_document

        return read([printed_document(folder, supplementary=part, quoting=True)
                     for part in (False, True)], namespace)  # fmt: skip
    from manuscript_guard.contracts._schema import read_text

    texts = [read_text(path) for path in source_files(folder)]
    return read(texts, namespace, captions(project, texts, results))


def captions(project, texts: Sequence[str], results) -> list[Caption]:
    """The captions of a Markdown manuscript's displays, as G2 finds them: each legend typed
    as a paragraph that opens with its display's pointer ("Figure 1. ..."), and each emitted
    table's caption, under the number the build gives the one table it places."""
    from manuscript_guard.gates.pointers import display_numbers

    found = typed_legends(texts)
    numbers = display_numbers(project)
    for (kind, key), displays in numbers.placed.items():
        table = results.tables.get(key) if kind == TABLE else None
        if table is None or not table.caption or len(displays) != 1:
            continue
        if numbers.uncounted(displays[0].supplementary, kind):
            continue
        found.append(Caption(kind, displays[0].supplementary, displays[0].number, table.caption))
    return found


def typed_legends(texts: Sequence[str]) -> list[Caption]:
    """Each legend of the Markdown `texts` typed as a paragraph that opens with the pointer
    to its display, "Figure 1. ..." or "**Table 2.** ...": found as G14 finds a legend
    (`glossary.markdown_captions`) and named as G2 reads a caption's pointer
    (`pointers.opening_pointer`); a comment is none."""
    from manuscript_guard.gates.glossary import markdown_captions
    from manuscript_guard.gates.pointers import opening_pointer

    found = []
    for text in texts:
        shown = blank_comments(text)
        for start, end in markdown_captions(shown):
            legend = shown[start:end].strip()
            pointer = opening_pointer(legend)
            named = display_named(pointer.group()) if pointer is not None else None
            if named is not None:
                found.append(Caption(*named, legend))
    return found

