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

#: An invisible per-paragraph identifier, carried into the .docx as a Word bookmark.
#:
#: Pandoc emits `[]{#id}` as `w:bookmarkStart`, which is invisible, survives editing, and
#: travels with a paragraph when somebody cuts and pastes it. That makes "which source
#: paragraph is this" an exact question rather than a similarity score — and it makes moves
#: tractable, which similarity matching never could: a moved paragraph and a deleted one
#: followed by an inserted one look identical to a diff.
#:
#: Pandoc does *not* read bookmarks back into markdown, so they are read from
#: `word/document.xml` directly.
_TAG = "mg-p-{stem}-{index}"
_TAGGED = re.compile(r"^\[\]\{#(mg-p-[A-Za-z0-9_.-]+)\}")


def tag(text: str, stem: str) -> str:
    """Give every ordinary paragraph of one source file an invisible identifier.

    Headings are skipped: `[]{#id}# Methods` is not a heading. So are paragraphs that are
    nothing but a placeholder, because those become a table or a figure rather than a
    paragraph, and a bookmark would attach to the wrong thing.
    """
    out = []
    for index, para in enumerate(re.split(r"(\n\s*\n)", text)):
        stripped = para.strip()
        if not stripped or para.strip("\n") == "" or stripped.startswith("#"):
            out.append(para)
            continue
        if re.fullmatch(r"\{\{[^}]*\}\}", stripped):
            out.append(para)
            continue
        marker = _TAG.format(stem=stem, index=index)
        out.append(para.replace(stripped, f"[]{{#{marker}}}{stripped}", 1))
    return "".join(out)


def tagged_paragraphs(project) -> dict[str, tuple[Path, str]]:
    """The identifier of every source paragraph, and the paragraph it names."""
    from manuscript_guard.gates.numbers import source_files

    found: dict[str, tuple[Path, str]] = {}
    for path in source_files(project.path("manuscript")):
        text = path.read_text(encoding="utf-8")
        for index, para in enumerate(re.split(r"(\n\s*\n)", text)):
            stripped = para.strip()
            if not stripped or stripped.startswith("#") or re.fullmatch(r"\{\{[^}]*\}\}", stripped):
                continue
            found[_TAG.format(stem=path.stem, index=index)] = (path, stripped)
    return found


def paragraph_order(document: Path) -> list[str]:
    """The identifiers a returned document carries, in the order they now appear.

    Read from the XML because pandoc discards bookmarks on the way back to markdown. This is
    what makes a move visible: the same identifier, in a different place.
    """
    with zipfile.ZipFile(document) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return re.findall(r'<w:bookmarkStart[^>]*w:name="(mg-p-[^"]+)"', xml)


def moves(before: list[str], after: list[str]) -> list[tuple[str, int, int]]:
    """Paragraphs that came back in a different position, as (id, was, now).

    Only a reordering is reported. A move needs no content from Word at all — the text is
    already on disk — so applying one cannot lose a binding, which is why it is safe for
    exactly the paragraphs the content merge has to refuse.
    """
    shared = [name for name in after if name in set(before)]
    original = [name for name in before if name in set(after)]
    if shared == original:
        return []

    # Only the paragraphs outside the stable backbone. Comparing positions directly said
    # that moving one paragraph moved fifteen, because everything after it shifted by one -
    # true, and useless to a reader trying to see what their co-author did.
    matcher = difflib.SequenceMatcher(a=original, b=shared, autojunk=False)
    settled: set[str] = set()
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            settled.update(original[i1:i2])
    return [
        (name, original.index(name), shared.index(name))
        for name in shared
        if name not in settled
    ]


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
