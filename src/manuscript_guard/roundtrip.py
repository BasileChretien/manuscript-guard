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

Everything is keyed on an invisible per-paragraph identifier carried into the document as
a Word bookmark, so "which paragraph is this" is exact rather than a similarity score.
That makes a move and a rewording orthogonal, and it makes sub-paragraph alignment
possible: a paragraph can be reworded around its bindings without them being touched.
"""

from __future__ import annotations

import difflib
import re
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
    #: The paragraph it is attached to, when the document carries identifiers. A reviewer's
    #: point is about a *place* in the paper, and losing that on the way in means the author
    #: re-finds it by hand for every point.
    where: str = ""


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

    anchors = _comment_anchors(document)
    out: list[Comment] = []
    for block in re.findall(r"<w:comment\b(.*?)</w:comment>", xml, re.DOTALL):
        author = re.search(r'w:author="([^"]*)"', block)
        date = re.search(r'w:date="([^"]*)"', block)
        ident = re.search(r'w:id="([^"]*)"', block)
        text = " ".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", block, re.DOTALL))
        if text.strip():
            out.append(
                Comment(
                    author=author.group(1) if author else "an unnamed reviewer",
                    date=(date.group(1)[:10] if date else ""),
                    text=re.sub(r"\s+", " ", _unescape(text)).strip(),
                    where=anchors.get(ident.group(1), "") if ident else "",
                )
            )
    return out


def _comment_anchors(document: Path) -> dict[str, str]:
    """Which paragraph each comment is attached to.

    `word/comments.xml` holds the text; the anchor lives in `document.xml`, as a
    `w:commentRangeStart` inside the paragraph it marks. Paired with the invisible paragraph
    identifiers, that turns "reviewer 2 said something about the Methods" into a point that
    knows which paragraph it is about — and a claimed revision can then be checked against
    *that* paragraph rather than against the file containing it.
    """
    with zipfile.ZipFile(document) as archive:
        if "word/document.xml" not in archive.namelist():
            return {}
        xml = archive.read("word/document.xml").decode("utf-8")

    found: dict[str, str] = {}
    for block in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL):
        names = re.findall(r'<w:bookmarkStart[^>]*w:name="(mg-p-[^"]+)"', block)
        if not names:
            continue
        for ident in re.findall(r'<w:commentRangeStart[^>]*w:id="([^"]*)"', block):
            found[ident] = names[0]
    return found


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


#: A binding or a citation: the parts of a paragraph the author does not own.
_PROTECTED = re.compile(r"\{\{[^}]*\}\}|\[@[^\]]*\]")


def paragraph_text(document: Path) -> dict[str, str]:
    """The text of every identified paragraph, keyed by its identifier.

    Read from the XML rather than through pandoc, because pandoc discards the bookmarks and
    the bookmark is the identity. The cost is inline formatting: `<w:t>` runs concatenate to
    plain text, so a merged segment loses its bold. `realign` limits that to the segments
    that actually changed.
    """
    with zipfile.ZipFile(document) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    found: dict[str, str] = {}
    for block in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL):
        names = re.findall(r'<w:bookmarkStart[^>]*w:name="(mg-p-[^"]+)"', block)
        if not names:
            continue
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", block, re.DOTALL))
        found[names[0]] = re.sub(r"\s+", " ", _unescape(text)).strip()
    return found


def _unescape(text: str) -> str:
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        text = text.replace(entity, char)
    return text


def segments(paragraph: str) -> tuple[list[str], list[str]]:
    """Split a source paragraph into its prose and the parts the author does not own.

    Returns `(prose, protected)` with `len(prose) == len(protected) + 1`, so the paragraph is
    `prose[0] + protected[0] + prose[1] + ...`.
    """
    protected = _PROTECTED.findall(paragraph)
    prose = _PROTECTED.split(paragraph)
    return prose, protected


def _flatten(text: str) -> str:
    """Prose as it will appear in the document: emphasis markers gone, spaces normalised.

    Prose is unchanged by rendering *except* for its markdown. `**striking**` reaches Word
    as `striking`, so locating the source segment verbatim failed on any paragraph with
    emphasis in it — which is most of them. Compared flattened, rebuilt from the original.
    """
    text = re.sub(r"(\*\*|__|\*|_|`)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def realign(source: str, rendered: str, returned: str) -> str | None:
    """Rewrite one source paragraph with a co-author's wording, keeping its bindings.

    The paragraph-level merge had to refuse anything carrying a binding, because splicing
    the returned text in would replace `{{results.ror.point}}` with `3.84`. Refusing is safe
    and, in a paper where most paragraphs quote a number, refuses almost everything.

    Alignment makes the finer move possible. A source paragraph is prose and protected
    tokens in alternation. Its prose appears verbatim in the rendered form — rendering only
    changes the protected parts — so locating the prose segments in `rendered` reveals what
    each token rendered to, *without needing to know how it renders*. That matters for
    citations, whose rendering depends on a CSL style this code never sees.

    Those rendered forms are then located in the returned text. If any is missing, or they
    come back in a different order, the co-author changed a number or a citation and the
    paragraph is refused. Otherwise the text between them is the new prose, and the
    paragraph is rebuilt from the *source's* tokens and the *co-author's* words.

    Searching is sequential, so a paragraph quoting two values that render the same string
    still pairs them up in order rather than matching both to the first occurrence.

    An unchanged prose segment is kept exactly as the source has it, which preserves its
    markdown — only a segment the co-author actually edited loses its inline formatting.
    """
    prose, protected = segments(source)
    if not protected:
        return returned.strip() or None

    flat = [_flatten(piece) for piece in prose]

    # What each protected token rendered to: the gaps between the prose segments. Found
    # without knowing how anything renders, which is what makes citations work - their
    # rendering depends on a CSL style this code never sees.
    rendered_tokens: list[str] = []
    cursor = 0
    if flat[0]:
        at = rendered.find(flat[0])
        if at < 0:
            return None
        cursor = at + len(flat[0])
    for index in range(1, len(prose)):
        piece = flat[index]
        if piece:
            at = rendered.find(piece, cursor)
            if at < 0:
                return None
            rendered_tokens.append(rendered[cursor:at].strip())
            cursor = at + len(piece)
        elif index == len(prose) - 1:
            rendered_tokens.append(rendered[cursor:].strip())
            cursor = len(rendered)
        else:
            # Two protected tokens with nothing between them: there is no way to say where
            # one rendering ends and the next begins.
            return None
    if len(rendered_tokens) != len(protected) or any(not token for token in rendered_tokens):
        return None

    # The same rendered forms, in the same order, in what came back.
    new_prose: list[str] = []
    cursor = 0
    for token in rendered_tokens:
        at = returned.find(token, cursor)
        if at < 0:
            return None  # the co-author changed a number or a citation
        new_prose.append(returned[cursor:at])
        cursor = at + len(token)
    new_prose.append(returned[cursor:])

    out: list[str] = []
    for index, piece in enumerate(new_prose):
        original = prose[index]
        # Unchanged prose keeps the source's own markdown; only an edited segment is taken
        # from Word, where inline formatting did not survive being read as plain text.
        same = _flatten(original) == _flatten(piece)
        out.append(original if same else piece)
        if index < len(protected):
            out.append(protected[index])
    return "".join(out).strip() or None
