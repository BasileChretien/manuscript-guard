"""A document a journal reviews blind names none of its authors.

A journal's profile says how its peer review is blinded (`blinding`). Where it is double or
triple, the reviewers are not to know who wrote the paper, and nothing checked that the
document sent them does not say. So the authors' names, their ORCID iDs and e-mail
addresses, and the names of their institutions are looked for:

- in the document's text: its paragraphs, notes, comments, headers and footers, the text a
  tracked change deleted included, since a reviewer who shows the changes reads it;
- in the text of each figure it holds, and of each figure the manuscript places;
- in the author fields Word keeps (`dc:creator`, `cp:lastModifiedBy`), in the author of each
  tracked change and comment (`w:author`), and in the list of the people who edited it
  (`word/people.xml`), which Word writes the moment a co-author opens the document.

The build checks the document it made, and `submit` the one it packs, which may be a copy a
co-author edited in Word: that is where the author fields come from.

A reference list is not read. The journals that review blind mostly ask for the authors' own
work to be cited in the third person, not taken out, and a self-citation then prints their
names there. A name is looked for as a person writes it: the given and the family name,
with any space between, and an initial with its stop before the family name ("A. Example")
or behind a comma after it ("Example, A."), never a bare initial. A family name
alone is not, since many are words ("Young", "Long"), nor is an institution's city or country.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import Finding, Report
from manuscript_guard.safexml import UnsafeDocument, open_archive, read_member, read_part

GATE = "BUILD"
CODE = "blind-document-names-author"
#: The kinds of review in which the reviewers are not to know the authors.
BLIND = ("double", "triple")

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CORE = {
    "{http://purl.org/dc/elements/1.1/}creator": "the document's author (dc:creator)",
    "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy": (
        "the document's last editor (cp:lastModifiedBy)"
    ),
}
#: The parts of a document that hold text a reader sees.
_TEXT_PART = re.compile(r"word/(?:document|footnotes|endnotes|comments|header\d*|footer\d*)\.xml")
#: A space of any kind, a line break inside a paragraph included.
_SPACE = r"\s+"


@dataclass(frozen=True)
class Sought:
    """Something that names an author: `what` as a finding says it, and how it is written."""

    what: str
    pattern: re.Pattern[str]


def sought(authors: dict | None) -> list[Sought]:
    """What names each author of `authors.yaml`, and each of their institutions."""
    found: list[Sought] = []
    authors = authors if isinstance(authors, dict) else {}
    for person in authors.get("authors") or []:
        if not isinstance(person, dict):
            continue
        given, family = str(person.get("given") or "").strip(), str(person.get("family") or "")
        family = family.strip()
        if given and family:
            found.append(Sought(f"{given} {family}", _name(given, family)))
        for field, label in (("orcid", "ORCID iD"), ("email", "e-mail address")):
            value = str(person.get(field) or "").strip()
            if value:
                pattern = re.compile(rf"(?<![\w.]){re.escape(value)}(?![\w])", re.IGNORECASE)
                found.append(Sought(f"the {label} {value}", pattern))
    for affiliation in authors.get("affiliations") or []:
        if isinstance(affiliation, dict):
            for piece in _institutions(str(affiliation.get("text") or "")):
                found.append(Sought(piece, _words(piece, re.IGNORECASE)))
    return found


def _name(given: str, family: str) -> re.Pattern[str]:
    """A name as it is written: "Ada Example", "A. Example", "Example, A.". An initial counts
    with its stop before the family name and after a comma behind it, and not bare: "A Cross-
    sectional study" and "patients on Ward A" name nobody (round 1 of #273)."""
    initial = re.escape(given[0])
    surname = _spaced(family)
    return re.compile(
        rf"(?<!\w)(?:{_spaced(given)}{_SPACE}{surname}|{initial}\.\s*{surname}"
        rf"|{surname},{_SPACE}{initial}[A-Z]?\.?)(?!\w)"
    )


#: An apostrophe as `authors.yaml` types it, and as pandoc prints it: "O'Brien" is printed
#: "O\N{RIGHT SINGLE QUOTATION MARK}Brien" (round 1 of #273).
_APOSTROPHE = "['\N{RIGHT SINGLE QUOTATION MARK}]"


def _spaced(words: str) -> str:
    return _SPACE.join(
        "".join(_APOSTROPHE if c in _APOSTROPHE[1:-1] else re.escape(c) for c in word)
        for word in words.split()
    )


def _words(piece: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){_spaced(piece)}(?!\w)", flags)


def _institutions(text: str) -> list[str]:
    """The parts of an affiliation that name an institution: those of three words or more
    between its commas. Not a city or a country, which name many other things."""
    return [piece.strip() for piece in text.split(",") if len(piece.split()) >= 3]


def names_in(text: str, wanted: list[Sought]) -> list[tuple[str, int]]:
    """Each thing of `wanted` that `text` holds, with where it starts: once for each place,
    however many of the ways it is written meet there."""
    found: list[tuple[str, int]] = []
    for one in wanted:
        end = -1
        for match in one.pattern.finditer(text):
            if match.start() >= end:
                found.append((one.what, match.start()))
            end = max(end, match.end())
    return sorted(found, key=lambda item: (item[1], item[0]))


def check_blinded(project: Project, document: Path) -> Report:
    """What names an author in `document`, where the journal's profile says its review is
    blind. An empty report where it does not, or where `authors.yaml` names nobody."""
    from manuscript_guard.gates.journal import blinding

    kind = blinding(project)
    wanted = sought(project.authors)
    if kind not in BLIND or not wanted:
        return Report()
    try:
        places = _places(document) + _figures(project)
    except UnsafeDocument as exc:
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="docx-unreadable",
                    message=f"could not read {document.name} for the authors' names: {exc}",
                    path=document,
                ),
            )
        )
    report = Report()
    said: set[tuple[str, str]] = set()
    for where, text in places:
        for what, _start in names_in(text, wanted):
            if (what, where) in said:
                continue
            said.add((what, where))
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code=CODE,
                    message=f"{what!r} is in {where} of {document.name}, and the journal's "
                    f"review is {kind}-blind",
                    path=document,
                    hint=_HINTS.get(where.split(" (")[0], _HINTS["the text"]),
                )
            )
    return report


_HINTS = {
    "the text": "take it out of the manuscript, or write the authors' own work in the third "
    "person, and build again",
    "a figure": "draw the figure again without it",
    "the document's author": "build the document again, or clear the author fields in Word "
    "(File, Info, Check for Issues, Inspect Document) before it is sent",
    "the document's last editor": "build the document again, or clear the author fields in "
    "Word (File, Info, Check for Issues, Inspect Document) before it is sent",
    "the author of a tracked change or a comment": "accept or reject the changes and delete "
    "the comments, or remove their authors with Word's Inspect Document, before it is sent",
    "the people who edited it": "remove the personal information with Word's Inspect "
    "Document before it is sent",
}


def _places(document: Path) -> list[tuple[str, str]]:
    """Where in `document` a name can be, each with the text it holds there."""
    places: list[tuple[str, str]] = []
    with open_archive(document) as archive:
        names = archive.namelist()
        listed = _bibliography_styles(archive) if "word/styles.xml" in names else set()
        for name in names:
            if _TEXT_PART.fullmatch(name):
                root = read_part(archive, name)
                places.append(("the text", "\n".join(_paragraphs(root, listed))))
                authors = {node.get(f"{_W}author") for node in root.iter()} - {None}
                places += [("the author of a tracked change or a comment", a) for a in authors]
            elif name.startswith("word/media/") and name.lower().endswith(".svg"):
                figure = f"a figure ({name[len('word/media/') :]})"
                places.append((figure, _svg_text(read_member(archive, name))))
        if "docProps/core.xml" in names:
            for node in read_part(archive, "docProps/core.xml"):
                if node.tag in _CORE and node.text:
                    places.append((_CORE[node.tag], node.text))
        if "word/people.xml" in names:
            root = read_part(archive, "word/people.xml")
            held = [value for node in root.iter() for value in (node.text, *node.attrib.values())]
            places.append(("the people who edited it", "\n".join(v for v in held if v)))
    return places


def _bibliography_styles(archive) -> set[str]:
    """The identifiers of the styles named "Bibliography". Word keeps a built-in style's name
    in English, and a localised Word may give it another identifier (round 1 of #273)."""
    root = read_part(archive, "word/styles.xml")
    return {
        style.get(f"{_W}styleId", "")
        for style in root.iter(f"{_W}style")
        if (style.find(f"{_W}name") is not None)
        and style.find(f"{_W}name").get(f"{_W}val", "").casefold() == "bibliography"
    }


def _paragraphs(root: ET.Element, listed: set[str] = frozenset()) -> list[str]:
    """Each paragraph's text, deleted text included, a reference list's left out. A tab or a
    break inside a paragraph is a space, so a name split by one is still found."""
    out = []
    for paragraph in root.iter(f"{_W}p"):
        style = paragraph.find(f"{_W}pPr/{_W}pStyle")
        if style is not None and style.get(f"{_W}val") in {"Bibliography", *listed}:
            continue
        pieces = []
        for node in paragraph.iter():
            if node.tag in (f"{_W}t", f"{_W}delText"):
                pieces.append(node.text or "")
            elif node.tag in (f"{_W}tab", f"{_W}br", f"{_W}cr"):
                pieces.append(" ")
        out.append("".join(pieces))
    return out


def _svg_text(data: bytes) -> str:
    """The text of an SVG figure. matplotlib writes a DOCTYPE into every SVG it saves, which
    `parse_xml` refuses, and that refusal stopped the whole check (round 1 of #273): one with
    no internal subset declares no entity and is taken out first. An SVG still unreadable is
    read for nothing, as a raster figure is."""
    from manuscript_guard.safexml import parse_xml

    data = re.sub(rb"<!DOCTYPE[^\[>]*>", b"", data, count=1)
    try:
        root = parse_xml(data, what="an SVG figure")
    except UnsafeDocument:
        return ""
    return "\n".join(node.text for node in root.iter() if node.text and node.text.strip())


def _figures(project: Project) -> list[tuple[str, str]]:
    """The text of each figure the manuscript places, as G3 reads it from its SVG or PDF."""
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.figures import _extract_text
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.text.placeholders import parse

    keys = sorted(
        {
            placeholder.key
            for path in source_files(project.path("manuscript"))
            for placeholder in parse(read_text(path))[0]
            if placeholder.namespace == "figure"
        }
    )
    places = []
    for key in keys:
        for suffix in (".svg", ".pdf"):
            path = project.path("figures") / f"{key}{suffix}"
            text = _extract_text(path) if path.is_file() else None
            if text:
                places.append((f"a figure ({path.name})", text))
    return places
