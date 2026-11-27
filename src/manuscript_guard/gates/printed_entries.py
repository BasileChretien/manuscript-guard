"""Whether the paper's bibliography prints every entry of `references.bib`, or the cited ones.

BibTeX, biblatex and pandoc's citeproc print only the works a citation names unless they are
told to print them all: in LaTeX by `\\nocite{*}`, for pandoc by a `nocite` key in the
metadata holding `@*`. G7 reads which, to say of the entries nothing cites either one note
for the file, since none of them reaches the paper, or a warning for each, since every one
does (Basile, 2026-11-27, "One note per .bib").

A `\\nocite` of single keys, `\\nocite{smith2019}` or `nocite: '@smith2019'`, cites those
keys and no other: the reader counts them as cited, and it does not make the list print
every entry.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: A `\\nocite` and its keys, between its braces.
_NOCITE = re.compile(r"\\nocite\s*\{([^{}]*)\}")
#: A TeX comment: a `%` after an even number of backslashes, to its line's end.
_COMMENT = re.compile(r"((?:^|[^\\])(?:\\\\)*)%[^\n]*", re.MULTILINE)
#: Pandoc's citation of every entry, `@*`, as a citation stands: after no letter, digit or `@`.
_EVERY = re.compile(r"(?<![\w@])@\*")


def every_entry_tex(text: str) -> bool:
    """Whether a LaTeX file asks for every entry: a `\\nocite` outside a comment whose keys,
    parted at commas, hold `*`. Read in the file as typed, not as the reader reads it, so a
    `\\nocite{*}` the reader records nowhere counts too, in a hook's body, in a definition
    or past a part it refuses."""
    uncommented = _COMMENT.sub(r"\1", text)
    return any("*" in (key.strip() for key in found.group(1).split(","))
               for found in _NOCITE.finditer(uncommented))  # fmt: skip


def every_entry_markdown(text: str) -> bool:
    """Whether a Markdown file's front matter asks pandoc for every entry: a `nocite` whose
    text, or a string in whose list, holds `@*`."""
    from manuscript_guard.text.masking import front_matter_said

    return any(_EVERY.search(said) for said in front_matter_said(text, "nocite"))


def every_entry_printed(texts: Iterable[str], *, latex: bool) -> bool:
    """Whether any of a manuscript's files asks for every entry, read as its format is."""
    asks = every_entry_tex if latex else every_entry_markdown
    return any(asks(text) for text in texts)


def prints_every_entry(project) -> bool:
    """Whether the paper's bibliography prints every entry of `references.bib`: a LaTeX file
    the main text's or the supplement's document inputs asks for them all, or the front
    matter of a Markdown file under `manuscript/` does. A LaTeX file nothing inputs is not
    read, since TeX does not read it."""
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    if manuscript_format(folder) == LATEX:
        from manuscript_guard.text.latex.structure import read_document

        texts = [source.text for supplementary in (False, True)
                 for source in read_document(folder, supplementary=supplementary).sources
                 if not source.loose]  # fmt: skip
        return every_entry_printed(texts, latex=True)
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.numbers import source_files

    return every_entry_printed((read_text(path) for path in source_files(folder)), latex=False)
