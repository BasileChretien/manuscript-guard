"""Bringing a co-author's edits back from Word without losing the bindings.

The design says the document is a build artefact and never edited. That is the right rule
and it is also, on its own, unusable: co-authors edit in Word, senior ones especially, and
"please learn Markdown" is not a thing anyone gets to say. So the round trip has to exist,
and the question is what it is allowed to carry.

Converting a built document back shows exactly what is at stake. `{{results.ror.point}}`
returns as `3.84`, `[@fictionalClassSignal2019]` returns as "(Fictional and Fictional 2021)",
and an emitted table returns as ordinary text. A naive import would replace every binding
with the literal it currently renders to — turning a checked manuscript into an unchecked
one that still *passes*, because the literals match what the analysis said at that moment.
It would fail silently, months later, the first time the analysis changed.

So: **prose comes back; generated things do not.** A hunk that touches a binding, a
citation, a table or a figure is refused and reported — "Sophie changed 3.84 to 4.02; that
number is results.ror.point, so change the analysis" — and the refusal is the feature rather
than a limitation. Comments become review findings, because a co-author's comment is the
most valuable thing in the returned file and losing it on import would be worse than not
importing at all.

Both sides of the diff are pushed through the same `docx -> markdown` conversion, so what
remains is the edit rather than pandoc's formatting habits.
"""

from __future__ import annotations

import difflib
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

#: Where the source digest travels. A sidecar cannot survive being emailed, and the whole
#: point is to recognise a document that came back from somebody else's machine.
PROPERTY = "manuscript-guard-source"
_CUSTOM = "docProps/custom.xml"

_CUSTOM_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
    'custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/'
    'docPropsVTypes">'
    '<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" name="{name}">'
    "<vt:lpwstr>{value}</vt:lpwstr></property></Properties>"
)
_CUSTOM_RELS = (
    '<Override PartName="/docProps/custom.xml" ContentType="application/'
    'vnd.openxmlformats-officedocument.custom-properties+xml"/>'
)
_CUSTOM_REL = (
    '<Relationship Id="rIdMgCustom" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/custom-properties" Target="docProps/custom.xml"/>'
)


class RoundTripError(Exception):
    """The edits could not be brought back."""


@dataclass(frozen=True)
class Comment:
    """One Word comment, which becomes something the author has to answer."""

    author: str
    date: str
    text: str


@dataclass(frozen=True)
class Hunk:
    """One difference between the document we built and the one that came back."""

    before: str
    after: str
    protected: str | None = None

    @property
    def applied(self) -> bool:
        return self.protected is None


def stamp_into(document: Path, digest: str) -> None:
    """Record the source digest inside the .docx itself.

    The sidecar `.source.sha256` tells *this* machine whether its own build is current. It
    cannot survive an email, and a document coming back from a co-author is precisely the
    case where the question matters: edits made against text that has since changed must not
    be merged into it silently.
    """
    scratch = document.with_suffix(".stamping.docx")
    with zipfile.ZipFile(document) as zin, zipfile.ZipFile(
        scratch, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        names = set(zin.namelist())
        for item in zin.infolist():
            if item.filename == _CUSTOM:
                continue
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml" and _CUSTOM not in names:
                data = data.decode("utf-8").replace("</Types>", _CUSTOM_RELS + "</Types>")
                data = data.encode("utf-8")
            elif item.filename == "_rels/.rels" and _CUSTOM not in names:
                data = data.decode("utf-8").replace(
                    "</Relationships>", _CUSTOM_REL + "</Relationships>"
                )
                data = data.encode("utf-8")
            zout.writestr(item, data)
        zout.writestr(_CUSTOM, _CUSTOM_XML.format(name=PROPERTY, value=digest))
    scratch.replace(document)


def stamp_of(document: Path) -> str | None:
    """The source digest a returned document carries, if it carries one."""
    try:
        with zipfile.ZipFile(document) as archive:
            if _CUSTOM not in archive.namelist():
                return None
            xml = archive.read(_CUSTOM).decode("utf-8")
    except (OSError, zipfile.BadZipFile) as exc:
        raise RoundTripError(f"{document.name} is not a readable .docx: {exc}") from exc
    found = re.search(r"<vt:lpwstr>([0-9a-f]{64})</vt:lpwstr>", xml)
    return found.group(1) if found else None


def comments_in(document: Path) -> list[Comment]:
    """Word comments, read from the file rather than through pandoc.

    Straight out of `word/comments.xml`, because that is where the author and the date are.
    A co-author's comment is the most useful thing in a returned document and the easiest
    to lose.
    """
    with zipfile.ZipFile(document) as archive:
        if "word/comments.xml" not in archive.namelist():
            return []
        xml = archive.read("word/comments.xml").decode("utf-8")

    out: list[Comment] = []
    for block in re.findall(r"<w:comment\b(.*?)</w:comment>", xml, re.DOTALL):
        author = re.search(r'w:author="([^"]*)"', block)
        date = re.search(r'w:date="([^"]*)"', block)
        text = " ".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", block, re.DOTALL))
        if text.strip():
            out.append(
                Comment(
                    author=author.group(1) if author else "an unnamed reviewer",
                    date=(date.group(1)[:10] if date else ""),
                    text=re.sub(r"\s+", " ", text).strip(),
                )
            )
    return out


def as_markdown(pandoc: str, document: Path) -> str:
    """One conversion, used for both sides of the diff.

    Pandoc's `docx -> markdown` is not the inverse of `markdown -> docx`, so comparing the
    returned document against the markdown we fed in would report pandoc's own formatting
    choices as co-author edits. Rendering both sides the same way cancels them.
    """
    finished = subprocess.run(
        [
            pandoc,
            str(document),
            "-t",
            "markdown_strict",
            "--wrap=none",
            "--track-changes=accept",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if finished.returncode != 0:
        raise RoundTripError(f"pandoc could not read {document.name}:\n{finished.stderr}")
    return finished.stdout


def differences(before: str, after: str, protected: set[str]) -> list[Hunk]:
    """Paragraph-level differences, each judged safe or protected.

    Paragraphs rather than lines: a hard-wrapped file re-wraps on the way through Word, so a
    line diff reports the whole document as changed. A paragraph is the unit an author edits
    anyway.
    """
    old = [p.strip() for p in re.split(r"\n\s*\n", before) if p.strip()]
    new = [p.strip() for p in re.split(r"\n\s*\n", after) if p.strip()]

    hunks: list[Hunk] = []
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        was = "\n\n".join(old[i1:i2])
        now = "\n\n".join(new[j1:j2])
        hunks.append(Hunk(before=was, after=now, protected=_touches(was, now, protected)))
    return hunks


def source_paragraphs(project) -> list[tuple[Path, str]]:
    """Every paragraph of the manuscript source, with the file it came from."""
    from manuscript_guard.gates.numbers import source_files

    out: list[tuple[Path, str]] = []
    for path in source_files(project.path("manuscript")):
        for para in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
            if para.strip():
                out.append((path, para))
    return out


def locate(before: str, paragraphs: list[tuple[Path, str]]) -> tuple[Path, str] | None:
    """The source paragraph a returned paragraph came from, or None if it is not certain.

    Matched by similarity rather than equality, because the returned text has been through
    Word and back. Ambiguity is refused rather than resolved: splicing an edit into the
    wrong paragraph is the failure this whole command has to avoid, and a near-tie between
    two paragraphs is exactly when a guess would be wrong.
    """
    scored = []
    for path, para in paragraphs:
        ratio = difflib.SequenceMatcher(a=_plain(para), b=_plain(before), autojunk=False).ratio()
        scored.append((ratio, path, para))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < 0.6:
        return None
    if len(scored) > 1 and scored[1][0] > scored[0][0] - 0.05:
        return None
    return scored[0][1], scored[0][2]


def _plain(text: str) -> str:
    """Source text with its bindings and citations flattened, for comparison only."""
    text = re.sub(r"\{\{[^}]*\}\}", " ", text)
    text = re.sub(r"\[@[^\]]*\]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


GENERATED = re.compile(r"\{\{|\[@")


def _touches(before: str, after: str, protected: set[str]) -> str | None:
    """Why this hunk may not be applied, or None if it may.

    A protected string that survives the edit unchanged is fine — the co-author rewrote the
    sentence around a number, which is ordinary. What is refused is a protected string that
    the edit removed or altered, because the .md holds a binding there and applying the hunk
    would replace the binding with whatever the co-author typed.
    """
    for rendered in protected:
        if rendered and rendered in before and before.count(rendered) > after.count(rendered):
            return rendered
    return None
