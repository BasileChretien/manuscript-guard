"""A LaTeX file's citations as the Markdown reader's records (DESIGN.md, "LaTeX manuscripts",
"Citations").

`citations` returns the `CitationUse` records `zotero.find_citations` returns for `[@key]`
and `@key`: one for each key a citation command names, with the key's own line and offset,
narrative where the command prints the authors' names in the sentence (`\\citet`,
`\\citealt`, `\\textcite`, `\\citeauthor`) and not otherwise, `\\cite` among them.
`\\nocite{*}` cites every entry of the bibliography, as LaTeX does. The scanner reads the keys
where it reads the command's braces (`mask.py`), so a key in a comment, an `\\iffalse` block or
a definition's body is no citation, and a citation command it does not know is refused.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from pathlib import Path

from manuscript_guard.text.latex.structure import Source
from manuscript_guard.zotero.citations import CitationUse

#: Every key of the bibliography, `\\nocite{*}`'s.
EVERY = "*"


def citations(source: Source, path: Path, bibliography: tuple[str, ...] = ()) -> list[CitationUse]:
    """Each key the file's citation commands name, in the order they are written, `*` as each
    key of `bibliography`."""
    text = source.text
    breaks = [found.start() for found in re.finditer("\n", text)]
    uses = []
    for cited in source.reading.cited:
        line = bisect_left(breaks, cited.offset) + 1
        raw = text[cited.start : cited.end]
        keys = bibliography if cited.key == EVERY else (cited.key,)
        uses += [CitationUse(citekey=key, path=path, line=line, narrative=cited.narrative,
                             raw=raw, start=cited.offset) for key in keys]  # fmt: skip
    return uses
