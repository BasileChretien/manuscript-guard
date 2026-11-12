"""A LaTeX paper's files read in the input encoding it declares, for `audit`.

A paper saved in Latin-1 declares it, `\\usepackage[latin1]{inputenc}`, and TeX reads every
file of its tree in that encoding. Read as UTF-8, its accented letters were replacement
characters, and the reader refused the declaration, so that the rest of the file went
unread (corpus run of 2026-11-11). `audit` reads the files of a folder whose `.tex` and `.sty`
files declare one of `CODECS` in that encoding, so that the gates read the characters TeX
prints, and writes each declaration as UTF-8's, padded to its length so that every offset
stays: the text is then UTF-8 that says so (Basile, 2026-11-11, "Read more, and be honest").

A project's files are read as UTF-8, as the submission folder writes them, so a project that
declares another encoding in a file that is not ASCII is still refused there (`mask`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from manuscript_guard.text.latex.mask import _INPUTENC, _opens_comment

#: Each input encoding inputenc knows that a folder is read in, by its name there, and the
#: codec that decodes it: ISO 8859-1, ISO 8859-15, and Windows' code page 1252 by both names.
CODECS = {"latin1": "latin_1", "latin9": "iso8859_15", "cp1252": "cp1252",
          "ansinew": "cp1252"}  # fmt: skip
#: What a declaration's name is written as in the text read: UTF-8's.
UTF8 = "utf8"


def _declarations(text: str) -> Iterable[tuple[re.Match[str], int, int]]:
    """Each declaration of an input encoding outside a comment, and where its name runs."""
    for found in _INPUTENC.finditer(text):
        line = text.rfind("\n", 0, found.start()) + 1
        if _opens_comment(text, line, found.start()):
            continue
        group = 1 if found.group(1) is not None else 2
        yield found, found.start(group), found.end(group)


def declared(texts: Iterable[str]) -> str | None:
    """The name of the one encoding of `CODECS` that the files declare, or None where they
    declare none, or declare another beside it that decodes otherwise: UTF-8, ASCII or any
    other inputenc knows (round 1 of #637: a paper's `[utf8]` was not counted, and an old
    draft's `[latin1]` beside it had the folder read as Latin-1). `texts` may be read with
    any encoding that keeps ASCII, Latin-1 for one: a declaration is ASCII."""
    codecs: set[str] = set()
    names: list[str] = []
    for text in texts:
        for _found, start, end in _declarations(text):
            for option in text[start:end].split(","):
                name = option.strip()
                if name in CODECS:
                    names.append(name)
                if name:
                    codecs.add(CODECS.get(name, _OTHERS.get(name, name)))
    return names[0] if names and len(codecs) == 1 else None


def in_tree(document, originals: dict[str, str]) -> str | None:
    """`declared` of the files `document` reads, the entry and those it reaches, their
    `originals` given by path, as read before each declaration was written as UTF-8's: only
    where the reader reads them, not in a comment, an `\\iffalse` block or past a refusal
    (round 2 of #637: decided for the folder, a stray Latin-1 draft beside a paper that
    declares nothing had the paper misread)."""
    texts = []
    for source in document.sources:
        if source.loose or source.path not in originals:
            continue
        reading, text = source.reading, list(originals[source.path])
        past = [(refusal.offset, len(text)) for refusal in reading.refusals]
        for start, end in [*reading.comments, *reading.unprinted, *past]:
            text[start:end] = " " * (end - start)
        texts.append("".join(text))
    return declared(texts)


#: The encodings inputenc knows that decode as UTF-8 does, by their names there.
_OTHERS = {"utf8": "utf_8", "utf8x": "utf_8"}


def as_utf8(text: str) -> str:
    """`text`, read in the encoding it declares, with each declaration of one of `CODECS`
    written as UTF-8's at the same length: `[latin1]` as `[utf8  ]`."""
    out = list(text)
    for _found, start, end in _declarations(text):
        options = text[start:end].split(",")
        if not any(option.strip() in CODECS for option in options):
            continue
        written = ",".join(option.replace(option.strip(), UTF8.ljust(len(option.strip())))
                           if option.strip() in CODECS else option
                           for option in options)  # fmt: skip
        out[start:end] = written
    return "".join(out)
