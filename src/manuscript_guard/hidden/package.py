"""Which parts a Word file holds, and which of them Word reads as its text and shows.

A Word file is a package of parts, and its relationships say which part is which: `_rels/.rels`
names the main document, and the main document's own relationships name its styles, its
theme, its settings, its headers, footers, notes and comments. Word finds a part by its name
as the Open Packaging Conventions compare names (ISO/IEC 29500-2, 9.1.1): percent-escapes
decoded and letters of any case alike. So a styles part named `st%79les.xml` or
`Styles.xml` is the styles part, and was missed where the name was matched as written
(the security review of #574): the text its styles hide then read as shown. Two parts whose
names are alike that way are refused, as two of one name are, since which of them Word reads
is not known; and a main document the package does not hold is refused too.
"""

from __future__ import annotations

import posixpath
import string
from collections import Counter
from dataclasses import dataclass
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from manuscript_guard.hidden.styles import W, on_off
from manuscript_guard.safexml import UnsafeDocument, read_part

_RELATIONSHIPS = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
#: The notes a part holds, by the element each opens with, and the element that cites one.
NOTES = {f"{W}footnote": f"{W}footnoteReference", f"{W}endnote": f"{W}endnoteReference"}
#: The parts of these kinds hold text; a part of each other kind named here is read for the
#: properties of the text. Word's usual names stand where no relationship names one.
_TEXT_KINDS = frozenset({"header", "footer", "footnotes", "endnotes", "comments"})
_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_USUAL = {"styles": "word/styles.xml", "theme": "word/theme/theme1.xml",
          "settings": "word/settings.xml"}  # fmt: skip


def canonical(name: str) -> str:
    """A part's name as the packaging conventions compare it: from the package's root,
    percent-escapes decoded, its ASCII letters of any case (ISO/IEC 29500-2, 9.1.1.1)."""
    return posixpath.normpath(unquote(name).lstrip("/")).translate(_LOWER)


@dataclass(frozen=True)
class Shown:
    """The headers and footers a section shows, and the notes the text cites: None where
    the main document could not be read, and each is then taken as shown."""

    parts: frozenset[str] | None = None
    notes: frozenset[tuple[str, str]] | None = None


@dataclass(frozen=True)
class Package:
    """The parts of a Word file by what they are: each the name the archive holds it under,
    or None where the file has none."""

    main: str
    styles: str | None
    theme: str | None
    settings: str | None
    #: The part each relationship of the main document names, by the relationship's id.
    links: dict[str, str]
    #: The parts that hold the text: the main document, and those it names as such.
    stories: frozenset[str]
    #: Each relationship that names a part the file does not hold.
    missing: tuple[str, ...]


def _held(listed: list[str], file: str) -> dict[str, str]:
    twice = sorted(name for name, count in Counter(listed).items() if count > 1)
    alike = Counter(canonical(name) for name in set(listed))
    twice += sorted(name for name in set(listed) if alike[canonical(name)] > 1)
    if twice:
        raise UnsafeDocument(f"{file} holds two parts named {twice[0]}, or named alike, and "
                             "which of them Word reads is not known")  # fmt: skip
    return {canonical(name): name for name in listed}


def _links(archive, held: dict[str, str], part: str) -> list[tuple[str, str, str]]:
    """Each relationship of `part`: its id, its kind and the path it names."""
    folder, name = posixpath.split(part)
    rels = held.get(canonical(posixpath.join(folder, "_rels", f"{name}.rels")))
    if rels is None:
        return []
    found = []
    for link in read_part(archive, rels).iter(_RELATIONSHIPS):
        target = (link.get("Target") or "").strip()
        if not target or link.get("TargetMode") == "External":
            continue
        path = target if target.startswith("/") else posixpath.join(folder, target)
        kind = (link.get("Type") or "").rsplit("/", 1)[-1]
        found.append((link.get("Id") or "", kind, path))
    return found


def package_of(archive, file: str) -> Package:
    """The parts of the Word file `archive` (see the module's docstring)."""
    held = _held([info.filename for info in archive.infolist()], file)
    main = next((path for _id, kind, path in _links(archive, held, "")
                 if kind == "officeDocument"), "word/document.xml")  # fmt: skip
    if canonical(main) not in held:
        raise UnsafeDocument(f"{file}: its main document, {main}, is not in it")
    main = held[canonical(main)]
    named = dict.fromkeys(_USUAL)
    links: dict[str, str] = {}
    stories, missing = {main}, []
    for rid, kind, path in _links(archive, held, main):
        found = held.get(canonical(path))
        if found is None:
            if kind in _TEXT_KINDS or kind in _USUAL:
                missing.append(f"its {kind} part, {path}, is not in it")
            continue
        links[rid] = found
        if kind in _USUAL and named[kind] is None:
            named[kind] = found
        if kind in _TEXT_KINDS:
            stories.add(found)
    for kind, usual in _USUAL.items():
        if named[kind] is None:
            named[kind] = held.get(canonical(usual))
    return Package(main, named["styles"], named["theme"], named["settings"], links,
                   frozenset(stories), tuple(missing))  # fmt: skip


def shown(main: ET.Element | None, links: dict[str, str], settings: ET.Element | None) -> Shown:
    """The headers and footers the sections show, and the notes the text cites: a section's
    default header and footer, its first-page ones where it has a title page
    (`w:titlePg`), its even-page ones where the document has them (`w:evenAndOddHeaders`)."""
    if main is None:
        return Shown()
    even = settings is not None and bool(on_off(settings.find(f"{W}evenAndOddHeaders")))
    parts: set[str] = set()
    for section in main.iter(f"{W}sectPr"):
        first = bool(on_off(section.find(f"{W}titlePg")))
        for reference in (*section.findall(f"{W}headerReference"),
                          *section.findall(f"{W}footerReference")):  # fmt: skip
            kind = reference.get(f"{W}type") or "default"
            shows = kind == "default" or (kind == "first" and first) or (kind == "even" and even)
            target = links.get(reference.get(_R_ID) or "")
            if shows and target:
                parts.add(target)
    notes = {(note, cite.get(f"{W}id", "")) for note, cited in NOTES.items()
             for cite in main.iter(cited)}  # fmt: skip
    return Shown(frozenset(parts), frozenset(notes))
