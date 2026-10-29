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
  (`word/people.xml`), which Word writes the moment a co-author opens the document;
- in what the document holds and does not print: the address of each link, the code of each
  field that holds an address (`HYPERLINK`, `INCLUDEPICTURE`, `INCLUDETEXT`, `LINK`,
  `DDE`), and the company Word keeps (`Company`). Not a citation's field code, which
  holds the cited work's data, as a self-citation's reference does.

The build checks the document it made, and `submit` the one it packs, which may be a copy a
co-author edited in Word: that is where the author fields come from.

A reference list is not read, its links included. The journals that review blind mostly ask
for the authors' own work to be cited in the third person, not taken out, and a
self-citation then prints their names there. A name is looked for as a person writes it:
the given and the family name, with any space between, and an initial with its stop before
the family name ("A. Example") or behind a comma after it ("Example, A."), never a bare
initial. A family name alone is not, since many are words ("Young", "Long"), nor is an
institution's city or country.
"""

from __future__ import annotations

import re
import unicodedata
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
#: The relationships of those parts, where a link keeps its address.
_RELS_PART = re.compile(r"word/_rels/[^/]+\.xml\.rels")
_RELATIONSHIP = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
_COMPANY = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Company"
#: A picture's properties in Word, whose `descr` and `title` are its alternative text.
_DOC_PR = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
#: The fields whose code holds an address or a path: a link, a picture or a text taken in,
#: a table pasted as a link to its file (`LINK`, `DDE`, `DDEAUTO`, round 2 of #349). Not a
#: citation's (`ADDIN ZOTERO_ITEM`, `ADDIN EN.CITE`), whose code holds the cited work's
#: data, a self-citation's publisher included (round 1 of #349).
_ADDRESSED = re.compile(
    r"\s*(?:HYPERLINK|INCLUDEPICTURE|INCLUDETEXT|LINK|DDE|DDEAUTO)\b", re.IGNORECASE
)
#: A space of any kind, a line break inside a paragraph included.
_SPACE = r"\s+"
#: What stands between two words of a name in a LaTeX source: a space, a tie, a thin or a
#: control space, a brace, and a template's command round a word, `\fnm{Ada} \sur{Example}`
#: (round 3 of step 12, part 2).
_LATEX_SPACE = r"(?:[\s~{}]|\\[,;: ]|\\[A-Za-z]+\*?)+"
#: The accents LaTeX types as a command before the letter, by the combining character a
#: letter that bears one decomposes into.
_ACCENTS = {
    "\N{COMBINING ACUTE ACCENT}": "'",
    "\N{COMBINING GRAVE ACCENT}": "`",
    "\N{COMBINING CIRCUMFLEX ACCENT}": "^",
    "\N{COMBINING DIAERESIS}": '"',
    "\N{COMBINING TILDE}": "~",
    "\N{COMBINING MACRON}": "=",
    "\N{COMBINING DOT ABOVE}": ".",
    "\N{COMBINING CEDILLA}": "c",
    "\N{COMBINING CARON}": "v",
    "\N{COMBINING BREVE}": "u",
    "\N{COMBINING DOUBLE ACUTE ACCENT}": "H",
    "\N{COMBINING RING ABOVE}": "r",
    "\N{COMBINING OGONEK}": "k",
    "\N{COMBINING DOT BELOW}": "d",
}
#: The letters LaTeX types as a command of their own.
_LETTERS = {
    "\N{LATIN SMALL LETTER SHARP S}": "ss",
    "\N{LATIN SMALL LETTER O WITH STROKE}": "o",
    "\N{LATIN CAPITAL LETTER O WITH STROKE}": "O",
    "\N{LATIN SMALL LETTER AE}": "ae",
    "\N{LATIN CAPITAL LETTER AE}": "AE",
    "\N{LATIN SMALL LIGATURE OE}": "oe",
    "\N{LATIN CAPITAL LIGATURE OE}": "OE",
    "\N{LATIN SMALL LETTER A WITH RING ABOVE}": "aa",
    "\N{LATIN CAPITAL LETTER A WITH RING ABOVE}": "AA",
    "\N{LATIN SMALL LETTER L WITH STROKE}": "l",
    "\N{LATIN CAPITAL LETTER L WITH STROKE}": "L",
    "\N{LATIN SMALL LETTER DOTLESS I}": "i",
}


@dataclass(frozen=True)
class Sought:
    """Something that names an author: `what` as a finding says it, and how it is written."""

    what: str
    pattern: re.Pattern[str]


def sought(authors: dict | None, *, latex: bool = False) -> list[Sought]:
    """What names each author of `authors.yaml`, and each of their institutions. With `latex`,
    also as a LaTeX source types it: a tie or a template's commands between the words, an
    accent as a command, `Chr\\'{e}tien`, and `\\_` or `\\&` (round 3 of step 12, part 2)."""
    found: list[Sought] = []
    authors = authors if isinstance(authors, dict) else {}
    for person in authors.get("authors") or []:
        if not isinstance(person, dict):
            continue
        given, family = str(person.get("given") or "").strip(), str(person.get("family") or "")
        family = family.strip()
        if given and family:
            found.append(Sought(f"{given} {family}", _name(given, family, latex=latex)))
        for field, label in (("orcid", "ORCID iD"), ("email", "e-mail address")):
            value = str(person.get(field) or "").strip()
            if value:
                typed = "".join(_letter(character, latex=latex) for character in value)
                pattern = re.compile(rf"(?<![\w.]){typed}(?![\w])", re.IGNORECASE)
                found.append(Sought(f"the {label} {value}", pattern))
    for affiliation in authors.get("affiliations") or []:
        if isinstance(affiliation, dict):
            for piece in _institutions(str(affiliation.get("text") or "")):
                found.append(Sought(piece, _words(piece, re.IGNORECASE, latex=latex)))
    return found


def _name(given: str, family: str, *, latex: bool = False) -> re.Pattern[str]:
    """A name as it is written: "Ada Example", "A. Example", "Example, A.". An initial counts
    with its stop before the family name and after a comma behind it, and not bare: "A Cross-
    sectional study" and "patients on Ward A" name nobody (round 1 of #273). With `latex`,
    also as a LaTeX source types it, `A.~Example` (round 3 of step 12, part 2)."""
    space = _LATEX_SPACE if latex else _SPACE
    initial = _letter(given[0], latex=latex)
    surname = _spaced(family, latex=latex)
    stop = rf"\.(?:{_LATEX_SPACE})?" if latex else r"\.\s*"
    return re.compile(
        rf"(?<!\w)(?:{_spaced(given, latex=latex)}{space}{surname}|{initial}{stop}{surname}"
        rf"|{surname},{space}{initial}[A-Z]?\.?)(?!\w)"
    )


#: An apostrophe as `authors.yaml` types it, and as pandoc prints it: "O'Brien" is printed
#: "O\N{RIGHT SINGLE QUOTATION MARK}Brien" (round 1 of #273).
_APOSTROPHE = "['\N{RIGHT SINGLE QUOTATION MARK}]"


def _spaced(words: str, *, latex: bool = False) -> str:
    return (_LATEX_SPACE if latex else _SPACE).join(
        "".join(_APOSTROPHE if c in _APOSTROPHE[1:-1] else _letter(c, latex=latex) for c in word)
        for word in words.split()
    )


def _letter(character: str, *, latex: bool = False) -> str:
    """`character` as a pattern; with `latex`, also as LaTeX types it: `\\_` or `\\&`, an
    accented letter as `\\'{e}` or `{\\'e}`, and `\\ss` (round 3 of step 12, part 2)."""
    plain = re.escape(character)
    if not latex:
        return plain
    if character in "_&%#$":
        return rf"\\?{plain}"
    typed = []
    if character in _LETTERS:
        typed.append(rf"\\{_LETTERS[character]}(?![A-Za-z])\s*(?:\{{\}})?")
    letter, *marks = unicodedata.normalize("NFD", character)
    if len(marks) == 1 and marks[0] in _ACCENTS and letter.isascii():
        command, base = _ACCENTS[marks[0]], re.escape(letter)
        if letter in "ij":
            base = rf"(?:{base}|\\{letter}(?![A-Za-z])\s*)"
        argument = rf"\s*\{{\s*{base}\s*\}}"
        if command.isalpha():
            typed.append(rf"\\{command}(?:{argument}|\s+{base})")
        else:
            typed.append(rf"\\{re.escape(command)}(?:{argument}|\s*{base})")
    return rf"(?:{plain}|\{{?(?:{'|'.join(typed)})\}}?)" if typed else plain


def _words(piece: str, flags: int = 0, *, latex: bool = False) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){_spaced(piece, latex=latex)}(?!\w)", flags)


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
    return _named(places, wanted, kind, document)


def check_blinded_latex(project: Project, files: list[Path]) -> Report:
    """What names an author in the LaTeX submission folder's files, where the journal's review
    is blind: its `.tex` and `.sty` files read whole, the preamble's `\\author` and a
    `\\hypersetup`'s `pdfauthor` among them, and the text of each PDF picture (step 10); a
    name as LaTeX types it too (round 3 of step 12, part 2)."""
    from manuscript_guard.gates.journal import blinding

    kind = blinding(project)
    wanted = sought(project.authors, latex=True)
    if kind not in BLIND or not wanted:
        return Report()
    document = files[0] if files else project.path("build")
    return _named(latex_places(files), wanted, kind, document)


def latex_places(files: list[Path]) -> list[tuple[str, str]]:
    """Where in a LaTeX submission's files a name can be, each with the text it holds there:
    each `.tex` and `.sty` read whole, its `thebibliography` left out, and the text of each
    PDF or SVG picture."""
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.figures import _extract_text
    from manuscript_guard.text.latex.mask import read

    places = []
    for path in files:
        if path.suffix in (".tex", ".sty"):
            # A reference list typed in `thebibliography` names the authors cited, as the Word
            # check passes the bibliography over (round 2 of step 10).
            text = read_text(path)
            listed = read(text).references
            places.append(("the text", "".join(
                " " if any(start <= at < end for start, end in listed) else character
                for at, character in enumerate(text))))  # fmt: skip
        elif path.suffix.lower() in (".pdf", ".svg"):
            text = _extract_text(path)
            if text:
                places.append((f"a figure ({path.name})", text))
    return places


def docx_places(document: Path, *, body: bool = True) -> list[tuple[str, str]]:
    """Where in a .docx a name can be, each with the text it holds there (`_places`); with
    `body` False, not the body's paragraphs, which a caller reads its own way (`audit
    --authors`, its reference list cut as the audit finds it). Raises `UnsafeDocument` where
    the document cannot be read."""
    return _places(document) if body else _places(document, body=False)


def deleted_text(document: Path) -> str:
    """What a tracked change deleted in the body of a .docx, a paragraph to a line, outside a
    reference list styled "Bibliography": a reviewer who shows the changes reads it, and the
    text as accepted does not hold it."""
    with open_archive(document) as archive:
        names = archive.namelist()
        listed = _bibliography_styles(archive) if "word/styles.xml" in names else set()
        root = read_part(archive, "word/document.xml")
    return "\n".join(
        "".join(node.text or "" for node in paragraph.iter(f"{_W}delText"))
        for paragraph in root.iter(f"{_W}p") if not _in_reference_list(paragraph, listed)
    )


def found_in(places: list[tuple[str, str]], wanted: list[Sought], kind: str,
             document: Path) -> Report:  # fmt: skip
    """A finding for each name of `wanted` in each place of `document`, whose review is
    `kind`-blind: for a document read elsewhere than the build (`audit --authors`)."""
    return _named(places, wanted, kind, document)


def _named(places: list[tuple[str, str]], wanted, kind: str, document: Path) -> Report:
    """A finding for each name of `wanted` in each place."""
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
    "the alternative text of a picture": "take it out of the figure's `alt:` in its guard "
    "file and build again, or out of the picture's alternative text in Word",
    "the document's author": "build the document again, or clear the author fields in Word "
    "(File, Info, Check for Issues, Inspect Document) before it is sent",
    "the document's last editor": "build the document again, or clear the author fields in "
    "Word (File, Info, Check for Issues, Inspect Document) before it is sent",
    "the author of a tracked change or a comment": "accept or reject the changes and delete "
    "the comments, or remove their authors with Word's Inspect Document, before it is sent",
    "the people who edited it": "remove the personal information with Word's Inspect "
    "Document before it is sent",
    # Round 1 of #349: these three had the text's hint, and building again clears none.
    "the address of a link": "change the link's address or take the link out, in the "
    "manuscript or in Word (Remove Hyperlink), before it is sent",
    "a field's code": "change the field's address or take the field out; Alt+F9 shows the "
    "codes in Word",
    "the document's company": "clear the Company with Word's Inspect Document, and in the "
    "reference document's properties if the build takes it from there, before it is sent",
}


def _places(document: Path, *, body: bool = True) -> list[tuple[str, str]]:
    """Where in `document` a name can be, each with the text it holds there; with `body`
    False, not the paragraphs of its body (`docx_places`)."""
    places: list[tuple[str, str]] = []
    with open_archive(document) as archive:
        names = archive.namelist()
        listed = _bibliography_styles(archive) if "word/styles.xml" in names else set()
        cited: dict[str, set[str]] = {}
        codes: list[str] = []
        for name in names:
            if _TEXT_PART.fullmatch(name):
                root = read_part(archive, name)
                if body or name != "word/document.xml":
                    places.append(("the text", "\n".join(_paragraphs(root, listed))))
                authors = {node.get(f"{_W}author") for node in root.iter()} - {None}
                places += [("the author of a tracked change or a comment", a) for a in authors]
                # A picture's alternative text, which the build writes from its figure's
                # guard file and Word lets anyone type: read aloud, and printed nowhere.
                described = [node.get(key) for node in root.iter() if node.tag == _DOC_PR
                             for key in ("descr", "title") if node.get(key)]  # fmt: skip
                if described:
                    places.append(("the alternative text of a picture", "\n".join(described)))
                # A field's code holding an address is not printed and is in the file (round
                # 1 of #273); the reference list's are its own, as its text is.
                found, cited[name] = _addresses(root, listed)
                codes += found
            elif name.startswith("word/media/") and name.lower().endswith(".svg"):
                figure = f"a figure ({name[len('word/media/') :]})"
                places.append((figure, _svg_text(read_member(archive, name))))
        # A link's address: a mailto: or an ORCID iD behind words (round 1 of #273). Not an
        # address the reference list links to, wherever else it is linked: pandoc gives every
        # link to one address one identifier, and copies the links into the notes' part too
        # (round 2 of #349).
        linked: dict[str, dict[str, str]] = {}
        for name in names:
            if _RELS_PART.fullmatch(name):
                part = name.replace("word/_rels/", "word/").removesuffix(".rels")
                linked[part] = {
                    node.get("Id", ""): node.get("Target", "")
                    for node in read_part(archive, name).iter()
                    if node.tag == _RELATIONSHIP and node.get("TargetMode") == "External"
                }
        listed_at = {
            linked[part][at] for part, ids in cited.items() for at in ids
            if at in linked.get(part, {})
        }  # fmt: skip
        for targets in linked.values():
            shown = [target for target in targets.values() if target not in listed_at]
            if shown:
                places.append(("the address of a link", "\n".join(shown)))
        # A field's code that links to such an address is the list's too (round 3 of #349).
        codes = [code for code in codes if not any(at in code for at in listed_at)]
        if codes:
            places.append(("a field's code", "\n".join(codes)))
        if "docProps/core.xml" in names:
            for node in read_part(archive, "docProps/core.xml"):
                if node.tag in _CORE and node.text:
                    places.append((_CORE[node.tag], node.text))
        if "docProps/app.xml" in names:
            for node in read_part(archive, "docProps/app.xml"):
                if node.tag == _COMPANY and node.text:
                    places.append(("the document's company (Company)", node.text))
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


def _in_reference_list(paragraph: ET.Element, listed: set[str]) -> bool:
    style = paragraph.find(f"{_W}pPr/{_W}pStyle")
    return style is not None and style.get(f"{_W}val") in {"Bibliography", *listed}


def _addresses(root: ET.Element, listed: set[str]) -> tuple[list[str], set[str]]:
    """The codes of the fields that hold an address, outside the reference list; and the
    identifiers of the reference list's links, whose addresses are its own. A field's code
    is read from its `begin` to its `separate` or `end`, within one paragraph; a field
    nested in its code does not end it, and one left open at the paragraph's end is read
    as far as it goes (round 2 of #349)."""
    codes: list[str] = []
    cited: set[str] = set()
    for paragraph in root.iter(f"{_W}p"):
        if _in_reference_list(paragraph, listed):
            cited |= {link.get(f"{_R}id") for link in paragraph.iter(f"{_W}hyperlink")} - {None}
            continue
        # Each field open, innermost last: its code so far, or None once it is read.
        open_: list[list[str] | None] = []
        for node in paragraph.iter():
            if node.tag == f"{_W}fldSimple":
                codes.append(node.get(f"{_W}instr", ""))
            elif node.tag == f"{_W}fldChar":
                kind = node.get(f"{_W}fldCharType")
                if kind == "begin":
                    open_.append([])
                elif open_:
                    if open_[-1] is not None:
                        codes.append("".join(open_[-1]))
                        open_[-1] = None
                    if kind == "end":
                        open_.pop()
            elif node.tag == f"{_W}instrText" and open_ and open_[-1] is not None:
                open_[-1].append(node.text or "")
        codes += ["".join(code) for code in open_ if code is not None]
    return [code for code in codes if _ADDRESSED.match(code)], cited


def _paragraphs(root: ET.Element, listed: set[str] = frozenset()) -> list[str]:
    """Each paragraph's text, deleted text included, a reference list's left out. A tab or a
    break inside a paragraph is a space, so a name split by one is still found."""
    out = []
    for paragraph in root.iter(f"{_W}p"):
        if _in_reference_list(paragraph, listed):
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
