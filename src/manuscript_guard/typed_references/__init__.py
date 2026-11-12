"""A reference list and citations typed in a Word paper, brought into `init --from`'s project.

A Word paper's citations are typed, "(Smith & Jones, 2020)", and so is its reference list.
Brought in as typed, every year, volume and page failed G2, and nothing said what to do (the
real-paper corpus: PsyArXiv fyxeq_v2 had about 190 such numbers, d8hkq_v1 about 280). So
`init --from` reads the list that `text.reference_lists` finds, writes each entry it reads
exactly to `literature/references.bib` (`entries`), and makes each citation that names
exactly one of them `[@key]` (`citations`). The rest stays as typed and is listed.

The key is Better BibTeX's authorYear form: the first author's family name, in the letters
a to z, its accents off (`key_letters`), and the year, "smith2020"; the list's own letter
where it gives one, "smith2020a"; and where two entries would have one key, a letter after
the second's, as Better BibTeX gives one. A `.bib` field is written as the entry types it:
the title braced whole, which pandoc would otherwise turn to sentence case, lowering
"Japan"; a family name of several words braced, so that "van der Berg" is one; and `&`, `%`,
`#`, `$` and `_` escaped, which a `.bib` value otherwise reads as TeX.

What is not done: a numbered list ("[3]", "3.") is not read, nor its citations; a list
`reference_lists` does not find is left alone, and so are the paper's citations; where
`literature/references.bib` is already there nothing is written over it, and every
citation stays as typed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from manuscript_guard.typed_references.citations import Left, make_citations
from manuscript_guard.typed_references.entries import Entry, Unread, read_entry

#: Where the bibliography goes, from the project's root.
BIBLIOGRAPHY = "literature/references.bib"
#: An entry that opens with its number: "[3]", "3.", "3)", "3\\.".
_NUMBERED = re.compile(r"[ ]{0,3}(?:\[\d+\]|\d+\\?[.)](?:\s|$))")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SUFFIXES = "abcdefghijklmnopqrstuvwxyz"
#: What a `.bib` value reads as TeX, escaped.
_TEX = {"&": r"\&", "%": r"\%", "#": r"\#", "$": r"\$", "_": r"\_"}
#: The order of a `.bib` entry's fields.
_ORDER = ("author", "title", "journal", "publisher", "year", "volume", "number", "pages",
          "doi", "url")  # fmt: skip


@dataclass(frozen=True)
class TypedReferences:
    """What `init --from` made of a paper's typed reference list and citations: the text
    with each citation that names one entry a key, the entries read with their keys, those
    not read, how many citations were made keys and those left as typed. `said` is why
    nothing was read, where nothing was."""

    text: str
    entries: tuple[tuple[str, Entry], ...] = ()
    unread: tuple[Unread, ...] = ()
    converted: int = 0
    left: tuple[Left, ...] = ()
    said: str = ""


def read(text: str, *, bib_there: bool = False) -> TypedReferences:
    """The typed reference lists of a paper's Markdown `text` read, and its citations made
    keys where each names one entry. With `bib_there`, `references.bib` is already in the
    project, and nothing is changed."""
    from manuscript_guard.text.reference_lists import is_bibliography_heading, reference_lists

    if bib_there:
        return TypedReferences(text, said=f"{BIBLIOGRAPHY} was already there, and init writes "
                               "over nothing: no entry was written to it, and every citation "
                               "stays as typed")  # fmt: skip
    spans = reference_lists(text)
    if not spans:
        return TypedReferences(text, said="no reference list was found under a heading or a "
                               "title in bold, so none was read, and every citation stays as "
                               "typed")  # fmt: skip
    lines: list[tuple[int, str]] = []
    # A work typed alike in two lists, the paper's and its supplement's, is one entry: two
    # would have two keys, and every citation of it name two (round 1 of #638).
    seen: set[str] = set()
    for start, end in spans:
        first = text.count("\n", 0, start) + 1
        written = text[start:end].split("\n")
        for number, line in enumerate(written[1:], start=first + 1):
            if line.strip() and not is_bibliography_heading(line) and line.strip() not in seen:
                seen.add(line.strip())
                lines.append((number, line))
    if any(_NUMBERED.match(line) for _number, line in lines):
        return TypedReferences(text, said="the reference list numbers its entries, and init "
                               "--from reads an author-year list only: the list and its "
                               "citations stay as typed")  # fmt: skip
    read_ = [read_entry(line, number) for number, line in lines]
    entries = [entry for entry in read_ if isinstance(entry, Entry)]
    unread = tuple(entry for entry in read_ if isinstance(entry, Unread))
    keyed, unkeyed = _keyed(entries)
    unread += unkeyed
    apart = [*spans, *((found.start(), found.end()) for found in _COMMENT.finditer(text))]
    made = make_citations(text, keyed, unread, apart)
    return TypedReferences(made.text, tuple(keyed), tuple(sorted(unread, key=_line)),
                           made.converted, made.left)  # fmt: skip


def _line(entry: Unread) -> int:
    return entry.line


def _keyed(entries: list[Entry]) -> tuple[list[tuple[str, Entry]], tuple[Unread, ...]]:
    """Each entry with its key, and those whose first author's name gives no key."""
    taken: set[str] = set()
    keyed: list[tuple[str, Entry]] = []
    unkeyed: list[Unread] = []
    for entry in entries:
        name = key_letters(entry.families[0])
        if not name:
            unkeyed.append(Unread(entry.line, entry.families[0], "its first author's name "
                                  "holds no letter a citation key is written in"))  # fmt: skip
            continue
        base = f"{name}{entry.year[:4]}"
        key = f"{base}{entry.year[4:]}"
        for suffix in _SUFFIXES:
            if key not in taken:
                break
            key = f"{base}{entry.year[4:]}{suffix}"
        taken.add(key)
        keyed.append((key, entry))
    return keyed, tuple(unkeyed)


def key_letters(family: str) -> str:
    """A family name as a Better BibTeX key writes it: in lower case, its accents taken off,
    a letter NFKD leaves whole written as G7 reads it ("Ødegård" is "odegard"), and nothing
    but the letters a to z, so "van der Berg" is "vanderberg" and "O'Neil" "oneil". Not G7's
    folding, which writes "oe" as "o" to compare a name with its umlaut: "Moe" is "moe"."""
    import unicodedata

    from manuscript_guard.gates.authors import LETTERS

    folded = unicodedata.normalize("NFKD", family.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z]", "", folded.translate(LETTERS))


def shifted(typed: TypedReferences, lines: int) -> TypedReferences:
    """`typed` with each line counted `lines` further down: as `main.md` has them, under
    the header `init` writes above the paper's text."""
    return replace(
        typed,
        entries=tuple((key, replace(entry, line=entry.line + lines))
                      for key, entry in typed.entries),
        unread=tuple(replace(entry, line=entry.line + lines) for entry in typed.unread),
        left=tuple(replace(one, line=one.line + lines) for one in typed.left),
    )  # fmt: skip


def bib(typed: TypedReferences, source: str) -> str:
    """`references.bib` with each entry read, its fields as the entry types them."""
    head = (f"% Written by `manuscript-guard init --from` from the reference list typed in "
            f"{source},\n% each field as the entry gives it. `sync-bib` writes this file "
            "again from Zotero:\n% import it there first (File > Import), or a work Zotero "
            "does not hold is lost from it.\n")  # fmt: skip
    return head + "".join(f"\n{_written(key, entry)}" for key, entry in typed.entries)


def _written(key: str, entry: Entry) -> str:
    authors = " and ".join(
        f"{{{family}}}, {initials}" if " " in family else f"{family}, {initials}"
        for family, initials in zip(entry.families, entry.initials, strict=True)
    )
    fields = {"author": authors, "year": entry.year[:4]}
    for name, value in entry.fields:
        if name in ("doi", "url"):
            fields[name] = value
        else:
            escaped = "".join(_TEX.get(char, char) for char in value)
            fields[name] = f"{{{escaped}}}" if name == "title" else escaped
    body = "".join(f"  {name} = {{{fields[name]}}},\n" for name in _ORDER if name in fields)
    return f"@{entry.kind}{{{key},\n{body}}}\n"


def write(root: Path, typed: TypedReferences, source: str, created: list[Path]) -> TypedReferences:
    """Write `references.bib` where `init` made it, and give `typed` its lines in `main.md`."""
    path = (Path(root) / BIBLIOGRAPHY).resolve()
    if typed.entries and path in {made.resolve() for made in created}:
        path.write_text(bib(typed, source), encoding="utf-8", newline="\n")
    main = (Path(root) / "manuscript" / "main.md").read_text(encoding="utf-8")
    return shifted(typed, main.count("\n") - typed.text.count("\n"))


def said(typed: TypedReferences) -> list[str]:
    """What `init --from` says it made of the typed references, for `what_was_done`."""
    if typed.said:
        return [f"  references: {typed.said}"]
    entries, many = len(typed.entries), len(typed.entries) != 1
    lines = [f"  references: {entries} entr{'ies' if many else 'y'} of the typed reference "
             f"list written to {BIBLIOGRAPHY}, and {typed.converted} citation"
             f"{'' if typed.converted == 1 else 's'} typed as text made [@key]. The typed list "
             "stays in main.md, and G2 does not read its numbers; once every citation is a "
             "key, delete it: the build prints the list from references.bib"]  # fmt: skip
    if typed.unread:
        lines.append(f"  {len(typed.unread)} entr{'ies' if len(typed.unread) != 1 else 'y'} "
                     "not read exactly, so not written, and the citations of each left as "
                     "typed:")  # fmt: skip
        lines += [f"    main.md:{entry.line}: {entry.why}" for entry in typed.unread]
    if typed.left:
        lines.append(f"  {len(typed.left)} citation{'s' if len(typed.left) != 1 else ''} "
                     "left as typed, nothing guessed:")  # fmt: skip
        lines += [f"    main.md:{one.line}: {one.shown}: {one.why}" for one in typed.left]
    return lines
