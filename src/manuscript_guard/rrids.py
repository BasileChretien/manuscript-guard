"""The Research Resource Identifiers a manuscript types, and what the resolver said of each.

An RRID names an antibody, a cell line, an organism, a plasmid or a tool: "RRID:AB_2298772",
"RRID:CVCL_0030", "RRID:SCR_002798", "RRID:IMSR_JAX:000664", "RRID:Addgene_12345". Only an
RRID the manuscript types is read: a resource written with none is not looked for (Basile,
2026-11-12).

**How one is read.** "RRID:" in capitals, a space or none after the colon (a line break
counts as the space), then the accession: the authority's prefix and the identifier it
issued, as the resolver's syntax gives them, `^RRID:[a-zA-Z]+.+$` (identifiers.org's
namespace `rrid`, read 2026-11-12), the prefix and each part after it joined by `_`, `:`,
`.` or `-` (`AB_`, `CVCL_`, `SCR_`, `IMSR_JAX:`, `Addgene_`, `MGI:`, `ZFIN_ZDB-GENO-`,
`BDSC_`, `WB-STRAIN:`, `MMRRC_…-UCD`, `nif-0000-`, `NXR_0.0005`), or one part of letters
then digits (`SAMN12345678`). Each joining mark is followed by a letter or a digit, so the
full stop, comma, colon, semicolon or bracket after an RRID is not part of it, nor is a word
of four small letters or more after a hyphen, "-derived"; a dot joins only before a digit.
The accession keeps its case as written. It
is read in the main text and the supplement, Markdown and LaTeX alike, outside comments and
code: a Markdown file as `masking.mask` leaves it with its code spans blanked too, a LaTeX
file as its reader masks it, with its `\\verb` and `\\texttt` blanked and `AB\\_1` read as
`AB_1`.

**What is kept.** `literature/rrids/<accession>.yaml` is what `manuscript-guard lookup
--resources` heard of one RRID on one day: whether the resolver knew it, each record it
gave (the resource's name, its types, its proper citation), and for a cell line what
Cellosaurus says of it, a problem it records quoted whole. An answer that did not come is
not written: no record, and the gate says the RRID was not looked up. G7 reads the records
offline (`gates/rrids.py`); nothing here opens a connection.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from manuscript_guard.contracts._schema import ContractError, read_structured, read_text, validate
from manuscript_guard.contracts.project import Project

RECORDS = ("literature", "rrids")
SCHEMA = "manuscript-guard/rrid/1"
SCHEMA_NAME = "rrid"
#: What `answers_sha256` digests: everything the record says but the digest itself.
ANSWERED = ("schema", "rrid", "asked_on", "status", "total", "hits", "cellosaurus")
FOUND = "found"
ABSENT = "absent"
#: Cellosaurus's licence for its data, which a record that quotes it carries.
CELLOSAURUS_LICENCE = "CC BY 4.0"

#: "RRID:" not inside a word, then one space or none, then the accession.
_LABEL = r"(?<![A-Za-z0-9_\-])RRID:"
#: The space after the colon: one space, a tab, a no-break space, or a line break.
_GAP = r"(?:[ \t  ]|\r?\n)?"
#: The authority's prefix and its parts, letters or digits, joined by `_`, `:`, a `.` before a
#: digit (NXR_0.0005, but SCR_002798 in "RRID:SCR_002798.Version 9"), or a `-` that is not
#: before a word of four small letters or more with no `:`, `_` or `-` after it: CVCL_0030 in
#: "RRID:CVCL_0030-derived", mmrrc_000231-unc whole. A mark after an RRID is no part of it.
#: Or one part of letters then digits, SAMN12345678; "RRID: pending" and "RRID:AB" are none.
_JOIN = r"(?:[_:]|\.(?=[0-9])|-(?![a-z]{4,}(?![A-Za-z0-9_:\-])))"
_ACCESSION = (rf"(?P<accession>[A-Za-z][A-Za-z0-9]*(?:{_JOIN}[A-Za-z0-9]+)+"
              r"|[A-Za-z]+[0-9][A-Za-z0-9]*)")
TYPED = re.compile(_LABEL + _GAP + _ACCESSION)
#: The documents of a manuscript, the main text's and the supplement's.
PARTS = (False, True)
_PUNCTUATION = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_NUL = "\x00"


@dataclass(frozen=True)
class Typed:
    """One RRID where the manuscript types it: the RRID as kept, `RRID:` and the accession
    as written, the file, its line there, and whether it is the supplement's."""

    rrid: str
    path: Path
    line: int
    supplementary: bool


def rrid_of(found: re.Match[str]) -> str:
    """The RRID a match names, as it is kept: "RRID:" and the accession as written."""
    return "RRID:" + found.group("accession")


def accession(rrid: str) -> str:
    return rrid.split(":", 1)[1]


def is_cell_line(rrid: str) -> bool:
    """A Cellosaurus accession, which Cellosaurus is asked about."""
    return accession(rrid).upper().startswith("CVCL_")


def _blank(text: str, spans) -> str:
    chars = list(text)
    for start, end in spans:
        for at in range(start, min(end, len(chars))):
            if chars[at] != "\n":
                chars[at] = _NUL
    return "".join(chars)


def markdown_view(text: str) -> str:
    """A Markdown file as the reading reads it, at the same offsets: what `masking.mask`
    blanks, a comment, a fence, the front matter, a link's address, blanked, and the code
    spans too."""
    from manuscript_guard.text.masking import _code_spans, mask

    return _blank(mask(text), _code_spans(text))


def latex_view(source) -> str:
    """A LaTeX file as the reading reads it, at the same offsets: the reader's mask, which
    blanks a comment, a listing, a label and the preamble, with each `\\verb` and
    `\\texttt` blanked too."""
    return _blank(source.reading.masked, source.reading.code)


def _compact(view: str, dropped: set[int]) -> tuple[str, list[int]]:
    """The view without the characters at `dropped`, and the offset each kept one had."""
    kept = [at for at in range(len(view)) if at not in dropped]
    return "".join(view[at] for at in kept), kept


def _markdown_escapes(view: str) -> set[int]:
    """Each backslash that escapes a punctuation mark in Markdown, `AB\\_1` printing `AB_1`."""
    out: set[int] = set()
    at = 0
    while at < len(view) - 1:
        if view[at] == "\\" and view[at + 1] in _PUNCTUATION:
            out.add(at)
            at += 2
            continue
        at += 1
    return out


def _latex_escapes(view: str, text: str) -> set[int]:
    """The NUL the LaTeX reader leaves after a sign it reads in a control symbol's place,
    `\\_` as `_`, `\\,` as a space: the two are one character of the view."""
    return {at for at, char in enumerate(view)
            if char == _NUL and at and text[at - 1] == "\\"}  # fmt: skip


def found_in(view: str, text: str, dropped: set[int]) -> list[tuple[str, int]]:
    """Each RRID the view gives, with the line of `text` it opens on."""
    compact, offsets = _compact(view, dropped)
    out = []
    for found in TYPED.finditer(compact):
        offset = offsets[found.start()]
        out.append((rrid_of(found), text.count("\n", 0, offset) + 1))
    return out


def typed(project: Project) -> list[Typed]:
    """Each RRID the manuscript types, in the order of its files and lines. A Markdown file
    that cannot be read raises `Unreadable`, as `read_text` does."""
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    if manuscript_format(folder) == LATEX:
        return _typed_latex(folder)
    return _typed_markdown(folder)


def _typed_markdown(folder: Path) -> list[Typed]:
    from manuscript_guard.gates.numbers import is_supplementary, source_files

    out = []
    for path in source_files(folder):
        supplementary = is_supplementary(folder, path)
        if supplementary not in PARTS:
            continue
        text = read_text(path)
        view = markdown_view(text)
        for rrid, line in found_in(view, text, _markdown_escapes(view)):
            out.append(Typed(rrid, path, line, supplementary))
    return out


def _typed_latex(folder: Path) -> list[Typed]:
    from manuscript_guard.text.latex.structure import read_document

    out: list[Typed] = []
    seen: set[str] = set()
    for supplementary in PARTS:
        for source in read_document(folder, supplementary=supplementary).sources:
            if source.loose or source.path.lower().endswith(".sty") or source.path in seen:
                continue
            seen.add(source.path)
            view = latex_view(source)
            for rrid, line in found_in(view, source.text, _latex_escapes(view, source.text)):
                out.append(Typed(rrid, folder / source.path, line, supplementary))
    return out


def unread_parts(project: Project) -> list[tuple[Path, int, str]]:
    """Each LaTeX file the reader stopped in, the line it stopped at and why: an RRID past
    there is not read."""
    from manuscript_guard.text.latex.structure import read_document
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    if manuscript_format(folder) != LATEX:
        return []
    out = []
    seen: set[str] = set()
    for supplementary in PARTS:
        for source in read_document(folder, supplementary=supplementary).sources:
            if source.path in seen:
                continue
            seen.add(source.path)
            for refusal in source.reading.refusals[:1]:
                line = source.text.count("\n", 0, refusal.offset) + 1
                out.append((folder / source.path, line, refusal.message))
    return out


# ------------------------------------------------------------------------------ records


def file_name(rrid: str) -> str:
    """The record's file name: the accession, a character other than a letter, a digit, `_`
    or `-` made a `-`, as a registration's is."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", accession(rrid)) + ".yaml"


def record_path(project: Project, rrid: str) -> Path:
    return project.root.joinpath(*RECORDS) / file_name(rrid)


def answers_digest(record: dict[str, Any]) -> str:
    """The SHA-256 of what a record says, kept in it: it catches an edit made without care,
    not one made by someone who runs the digest again."""
    value = {key: record.get(key) for key in ANSWERED}
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def digest_holds(record: dict[str, Any]) -> bool:
    return record.get("answers_sha256") == answers_digest(record)


def read_record(path: Path) -> dict[str, Any]:
    """A record as it is, held to its schema. Raises ContractError where it is not one."""
    document = read_structured(path)
    if not isinstance(document, dict):
        raise ContractError(f"{path.name} is not an RRID record")
    report = validate(document, SCHEMA_NAME, path)
    if not report.ok:
        raise ContractError("; ".join(f.message for f in report.failures))
    return document


def write_record(project: Project, record: dict[str, Any]) -> Path:
    """Write one record, after holding it to its schema."""
    path = record_path(project, record["rrid"])
    report = validate(record, SCHEMA_NAME, path)
    if not report.ok:
        problems = "; ".join(f.message for f in report.failures)
        raise ContractError(f"the record for {record['rrid']} is not valid: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100)
    path.write_bytes(text.encode("utf-8"))
    return path


def first_places(found: list[Typed]) -> dict[str, list[Typed]]:
    """Each RRID once, in the order first typed, with every place it is typed."""
    out: dict[str, list[Typed]] = {}
    for one in found:
        out.setdefault(one.rrid, []).append(one)
    return out


__all__ = [
    "ABSENT",
    "CELLOSAURUS_LICENCE",
    "FOUND",
    "PARTS",
    "RECORDS",
    "SCHEMA",
    "TYPED",
    "Typed",
    "accession",
    "answers_digest",
    "digest_holds",
    "file_name",
    "first_places",
    "found_in",
    "is_cell_line",
    "latex_view",
    "markdown_view",
    "read_record",
    "record_path",
    "rrid_of",
    "typed",
    "unread_parts",
    "write_record",
]
