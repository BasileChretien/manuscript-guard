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

So: **prose comes back; generated things do not.** A hunk that touches a binding or a
citation is refused and reported — "'3.84' comes from results.ror.point. Change the
analysis, not the document." — and the refusal is the feature rather than a limitation.
Comments become review findings, because a co-author's comment is the most valuable thing
in the returned file and losing it on import would be worse than not importing at all.

Everything is keyed on an invisible per-paragraph identifier carried into the document as
a Word bookmark, so "which paragraph is this" is exact rather than a similarity score.
That makes a move and a rewording orthogonal, and it makes sub-paragraph alignment
possible: a paragraph can be reworded around its bindings without them being touched.
"""

from __future__ import annotations

import difflib
import html
import re
import unicodedata
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.docxtext import spaced

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


_PROPERTY_ELEMENT = re.compile(r"<property\b[^>]*>.*?</property>", re.DOTALL)

#: Pandoc's own inputs, which it writes into the document as properties because they are
#: metadata. They are paths on the machine that built it, and useless to anyone reading it.
_BUILD_INPUTS = ("bibliography", "csl")


def _custom_properties(existing: str | None, digest: str) -> str:
    """The custom-properties part with the source stamp added, every other property kept.

    It used to be replaced whole. Pandoc writes metadata there, and Word's Zotero plugin
    keeps a document's citation style there (ZOTERO_PREF_1, ...): the stamp erased the
    style, and Word asked for one again after every build. Kept, except pandoc's own inputs:
    `bibliography` carried the absolute path of references.bib to every co-author.
    """
    ours = _CUSTOM_XML.format(name=PROPERTY, value=digest)
    if not existing:
        return ours
    dropped = (PROPERTY, *_BUILD_INPUTS)
    kept = [
        element
        for element in _PROPERTY_ELEMENT.findall(existing)
        if not any(f'name="{name}"' in element for name in dropped)
    ]
    elements = kept + _PROPERTY_ELEMENT.findall(ours)
    # Property ids must be unique, and custom properties number from 2.
    numbered = [
        re.sub(r'\bpid="\d+"', f'pid="{i}"', element, count=1)
        for i, element in enumerate(elements, start=2)
    ]
    return ours[: ours.index("<property")] + "".join(numbered) + "</Properties>"


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
        existing = zin.read(_CUSTOM).decode("utf-8") if _CUSTOM in names else None
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
        zout.writestr(_CUSTOM, _custom_properties(existing, digest))
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
    # By name: the part now holds other properties too, and the first 64-hex value in it
    # need not be ours.
    found = re.search(rf'name="{PROPERTY}"[^>]*>\s*<vt:lpwstr>([0-9a-f]{{64}})</vt:lpwstr>', xml)
    return found.group(1) if found else None


def comments_in(document: Path) -> list[Comment]:
    """Word comments, read from the file rather than through pandoc.

    Straight out of `word/comments.xml`, because that is where the author and the date are.
    A co-author's comment is the most useful thing in a returned document and the easiest
    to lose.

    The anchor lives in `document.xml`, as a `w:commentRangeStart` inside the paragraph it
    marks. Paired with the invisible paragraph identifiers, that turns "reviewer 2 said
    something about the Methods" into a point that knows which paragraph it is about - and
    a claimed revision can then be checked against *that* paragraph rather than against the
    file containing it.
    """
    from manuscript_guard.docxtext import DocumentUnreadable, comment_anchors, comment_texts

    try:
        found = comment_texts(document)
        anchors = comment_anchors(document) if found else {}
    except DocumentUnreadable as exc:
        raise RoundTripError(f"{document.name} is not a readable .docx: {exc}") from exc

    out: list[Comment] = []
    for attributes, text in found:
        if text:
            out.append(
                Comment(
                    author=attributes.get("author") or "an unnamed reviewer",
                    date=attributes.get("date", "")[:10],
                    text=text,
                    where=anchors.get(attributes.get("id", ""), ""),
                )
            )
    return out


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
_TAG = "mg-p-{slug}-{index}"


def paragraph_slug(relative: str) -> str:
    """A per-file component that is unique, stable, and legal in a Word bookmark.

    Keyed on the path relative to `manuscript/`, not on the filename. `source_files` walks
    subdirectories, so two files named `notes.md` in different folders produced identical
    identifiers - and the consequence was not a confused report but silent data loss: the
    built document carried the same bookmark twice, `paragraph_text` could only return one
    of them, and a co-author's edit to the other was neither merged nor refused. It vanished,
    with `import --apply` exiting 0 and saying "nothing came back".

    `gates/review.py` already learned this and keys `file_digests` on the relative path; the
    lesson had not reached here. A short digest carries the uniqueness because a bookmark
    name may not contain a separator, and a readable stem is kept in front of it because the
    identifier ends up in a revision record a person reads.
    """
    import hashlib

    stem = re.sub(r"[^A-Za-z0-9]+", "_", Path(relative).stem)[:12].strip("_") or "f"
    return f"{stem}{hashlib.sha256(relative.encode('utf-8')).hexdigest()[:6]}"
_TAGGED = re.compile(r"^\[\]\{#(mg-p-[A-Za-z0-9_.-]+)\}")

# Blocks that are not paragraphs of prose. A marker in front of a fence turns it into text:
# `[]{#id}::: {#refs}` printed ":::" in the document, and the reference list it was meant to
# place never appeared. A marker in front of a code fence would do the same to the code.
_FENCE = re.compile(r"(:::|```|~~~)")
# A link or footnote definition, `[reg]: https://...` or `[^1]: The note.`, which pandoc
# reads only at the start of a block. With a marker in front it was a paragraph: every
# `[text][reg]` in the manuscript printed with its brackets and linked nowhere, and the
# definition printed as a line of text, on every build.
#
# A block goes without a marker only when every line of it is a definition in a shape that
# pandoc can read no other way. Three versions that modelled pandoc's grammar more closely
# were each caught in review leaving a block unmarked that pandoc printed - a co-author's
# edit to it was dropped, and `import` said nothing came back - and one of them took
# minutes over a line of attributes. Everything else is marked, as it always was: a
# definition written another way prints as text, which is visible where the other is not.
#
# A link: a plain label, one token for its address - no real address has a space - and
# perhaps a title, on one line. Pandoc takes almost any words after `[label]:` for an
# address, so `[Methods]: patients were enrolled.` is a definition to it and prints nothing;
# marked, it prints as written. The label is read as inline markup: with `@` in it the line
# may be a citation, and code, maths or HTML opened in it can run past its `]`. No brace
# anywhere: a binding is filled in after this reading, and its value could change it.
_LINK_LINE = re.compile(
    r" {0,3}\[[^\[\]\\`$<@^|{\n]*\]:[ \t]+"
    r"(?:<[^<>\s\\{]+>|[^\s\"'(<\[{\\][^\s\[\]\\{]*)"
    r"(?:[ \t]+(?:\"[^\s\"\\\[\]{][^\"\\\[\]{\n]*\"|'[^\s'\\\[\]{][^'\\\[\]{\n]*'"
    r"|\([^()\\\[\]{\n]*\)))?"
    r"[ \t]*"
)
# A footnote: its label and its text on one line. Pandoc parses a note's text by itself, so
# nothing in it reaches the body - but a line under it is more of the note, even a link's
# definition, and that link then resolves nowhere. So links come first.
_NOTE_LINE = re.compile(r" {0,3}\[\^[^\s\[\]\\`^]+\]:[ \t]+\S[^\n]*")


def _only_definitions(block: str) -> bool:
    """Whether every line of a block is a link or footnote definition in a shape pandoc
    can only read as one, the links before the notes."""
    lines = block.strip("\n").split("\n")
    links = 0
    while links < len(lines) and _LINK_LINE.fullmatch(lines[links]):
        links += 1
    return all(_NOTE_LINE.fullmatch(line) for line in lines[links:])


def _untagged(block: str, above: str) -> bool:
    """Headings, fences, link and footnote definitions, and a lone placeholder (which
    becomes a table or a figure). `above` is what separates the block from the one before
    it, empty at the start of the text."""
    stripped = block.strip()
    return (
        not stripped
        or stripped.startswith("#")
        or _FENCE.match(stripped) is not None
        # Not `stripped`: a no-break space is text to pandoc, and a line that ends in one
        # is not a definition; nor is one indented four spaces. And only under a line that
        # pandoc too takes for blank: one holding a no-break or full-width space, or a form
        # feed, separates blocks here, while pandoc read it and the definition under it as
        # a paragraph.
        or (above.strip(" \t\n") == "" and _only_definitions(block))
        or re.fullmatch(r"\{\{[^}]*\}\}", stripped) is not None
    )


def tag(text: str, relative: str) -> str:
    """Give every ordinary paragraph of one source file an invisible identifier.

    Headings are skipped: `[]{#id}# Methods` is not a heading. So are fenced divs and code
    blocks, and paragraphs that are nothing but a placeholder, because those become a table
    or a figure rather than a paragraph, and a bookmark would attach to the wrong thing. So
    are link and footnote definitions, which put nothing in the body of the document.
    """
    out = []
    pieces = re.split(r"(\n\s*\n)", text)
    for index, para in enumerate(pieces):
        stripped = para.strip()
        if para.strip("\n") == "" or _untagged(para, pieces[index - 1] if index else ""):
            out.append(para)
            continue
        marker = _TAG.format(slug=paragraph_slug(relative), index=index)
        out.append(para.replace(stripped, f"[]{{#{marker}}}{stripped}", 1))
    return "".join(out)


def tagged_paragraphs(project) -> dict[str, tuple[Path, str, int]]:
    """The identifier of every source paragraph: its file, its text, and where it starts.

    The offset is what makes a merge exact. Splicing by `text.replace(original, rebuilt, 1)`
    rewrote the *first* paragraph reading that way — and a limitation restated in the
    Abstract and again in the Discussion is ordinary in a paper, so an edit to the second
    copy silently rewrote the first and left the second alone. Two corruptions, nothing
    reported, after the identifier had been established precisely so nothing had to be
    guessed. `bind` already learned this; the round trip had not.
    """
    from manuscript_guard.gates.numbers import source_files

    found: dict[str, tuple[Path, str]] = {}
    root = project.path("manuscript")
    for path in source_files(root):
        relative = path.relative_to(root).as_posix()
        slug = paragraph_slug(relative)
        # Front matter stripped, exactly as `assemble` strips it before tagging. Indexing
        # the raw source here while the document was tagged from the stripped text put every
        # identifier one block out of step - the two must read the same string or the
        # identifier stops naming anything.
        from manuscript_guard.build.assemble import strip_front_matter

        raw = path.read_text(encoding="utf-8")
        text, _title = strip_front_matter(raw)
        # Offsets are into the file on disk, not into the stripped copy: the merge splices
        # into the real file, and a paragraph would land one front matter earlier.
        cursor = len(raw) - len(text)
        pieces = re.split(r"(\n\s*\n)", text)
        for index, para in enumerate(pieces):
            stripped = para.strip()
            start = cursor + (len(para) - len(para.lstrip())) if stripped else cursor
            cursor += len(para)
            if _untagged(para, pieces[index - 1] if index else ""):
                continue
            found[_TAG.format(slug=slug, index=index)] = (path, stripped, start)
    return found


def read_blocks(document: Path):
    """The body of a document as a reader sees it; see `docxtext.blocks`."""
    from manuscript_guard.docxtext import DocumentUnreadable, blocks

    try:
        return blocks(document)
    except DocumentUnreadable as exc:
        raise RoundTripError(f"{document.name} is not a readable .docx: {exc}") from exc


def paragraph_order(document: Path) -> list[str]:
    """The identifiers a returned document carries, in the order they now appear.

    Read from the XML because pandoc discards bookmarks on the way back to markdown. This is
    what makes a move visible: the same identifier, in a different place.
    """
    return [name for block in read_blocks(document) for name in block.names]


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
    return {
        block.names[0]: block.text
        for block in read_blocks(document)
        if block.names and not block.table
    }


#: Inline Markdown that does not reach Word as its own text, by kind: what a refusal calls
#: it, its pattern, and the group Word's paragraph shows of it (None: nothing at all). An
#: empty name is something a merge can bring back, because `_escaped` writes Word's text
#: into the source so that it reads as it did in Word.
#:
#: Only bindings and citations used to be told apart from prose, and everything else was
#: taken to read in Word as it did in the source. A comment, a footnote and raw TeX read as
#: nothing there, a link as its words without the address, `10^9^/L` as "109/L". A rewording
#: rebuilt from Word's text deleted them, or printed 109, and nothing was reported.
_INLINE: dict[str, tuple[str, str, str | None]] = {
    # A hard line break reaches Word's text as a space, and nothing in it says there was one.
    "break": ("a line break", r"(?:\\|[ ]{2,})(?P<break_text>\n)", "break_text"),
    # Pandoc's no-break space, which Word's text carries as the character; see `_shows`. The
    # character itself, and every other space but layout, is text and needs no kind.
    "nbsp": ("", r"\\ ", None),
    "escape": ("", r"\\(?P<escape_text>[!-/:-@\[-`{-~])", "escape_text"),
    "raw": ("a raw inline", r"(?P<raw_ticks>`+).+?(?<!`)(?P=raw_ticks)\{=[^}]*\}", None),
    "coded": (
        "code with attributes",
        r"(?P<coded_ticks>`+)(?P<coded_text>.+?)(?<!`)(?P=coded_ticks)\{(?!\{)[^}]*\}",
        "coded_text",
    ),
    "code": ("", r"(?P<code_ticks>`+)(?P<code_text>.+?)(?<!`)(?P=code_ticks)(?!`)", "code_text"),
    # Shown decoded; see `_shows`. After code, where `&amp;` is printed as it is written.
    "entity": ("", r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);", None),
    "comment": ("an HTML comment", r"<!--.*?-->", None),
    # Two levels of brackets inside, which covers a citation with a locator in a footnote.
    "note": ("a footnote", r"\^\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\[\]]*\])*\])*\]", None),
    "note_ref": ("a footnote", r"\[\^[^\]\s]+\]", None),
    "image": ("an image", r"!\[[^\]]*\](?:\([^)]*\)|\[[^\]]*\])", None),
    "link": ("a link", r"\[(?P<link_text>[^\]]*)\](?:\([^)]*\)|\[[^\]]*\])", "link_text"),
    "span": ("a span with attributes", r"\[(?P<span_text>[^\]]*)\]\{(?!\{)[^}]*\}", "span_text"),
    "autolink": (
        "a link",
        r"<(?P<autolink_text>[A-Za-z][A-Za-z0-9+.-]*:[^\s<>]+|[^\s<>@]+@[^\s<>@]+)>",
        "autolink_text",
    ),
    # Pandoc's rule for a dollar: no space inside either end, no digit after the closing one.
    # So "US$ 5" and "$5 and $10" are prose. `_read` fills each binding in with digits before
    # scanning, so `US$5–US${{results.hi}}` is read as pandoc will read it; `{{` is refused
    # here too for `segments`, which scans the paragraph before any binding is filled in.
    "math": (
        "an equation",
        r"\$\$.+?\$\$|(?<![\\$])\$(?=\S)[^$]*?(?<=\S)\$(?!\d|\{\{)",
        None,
    ),
    "tex": ("raw TeX", r"\\[A-Za-z]+\*?(?:\[[^\]]*\])*(?:\{[^{}]*\})*", None),
    # A tag only if its attributes are attributes: pandoc prints `<LOD ... LOD/2 and >` as
    # the text it is.
    "html": (
        "inline HTML",
        r"</?[A-Za-z][A-Za-z0-9-]*"
        r"(?:\s+[A-Za-z_:][\w:.-]*(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+))?)*\s*/?>",
        None,
    ),
    "struck": ("struck-through text", r"~~(?P<struck_text>.+?)~~", "struck_text"),
    "sup": ("a superscript", r"\^(?P<sup_text>(?:[^\s^\\]|\\.)+)\^", "sup_text"),
    "sub": ("a subscript", r"~(?P<sub_text>(?:[^\s~\\]|\\.)+)~", "sub_text"),
}

#: One pass, the first alternative winning at each position: a citation inside a footnote
#: belongs to the footnote, and a comment inside backticks is code.
_SCAN = re.compile(
    "|".join(f"(?P<{kind}>{pattern})" for kind, (_name, pattern, _shows) in _INLINE.items()),
    re.DOTALL,
)

#: What renders nothing into the paragraph, so a binding or a citation inside it is not one
#: of the paragraph's own tokens: it is printed in a footnote, or dropped with the comment.
_OPAQUE = frozenset({"raw", "comment", "note", "note_ref", "image", "math", "tex", "html"})

#: Kinds whose shown text is itself Markdown, so emphasis inside it is read as emphasis.
_MARKDOWN_INSIDE = frozenset({"link", "span", "struck", "sup", "sub"})

#: Emphasis, strong before single so `***x***` and `*a **b** c*` pair up as pandoc pairs
#: them: no space just inside a delimiter, and an underscore inside a word is a letter.
_EMPHASIS = (
    (2, re.compile(r"\*\*(?=[^\s*]).*?(?<=[^\s*])\*\*", re.DOTALL)),
    (2, re.compile(r"(?<![^\W_])__(?=[^\s_]).*?(?<=[^\s_])__(?![^\W_])", re.DOTALL)),
    (1, re.compile(r"\*(?=[^\s*]).*?(?<=[^\s*])\*", re.DOTALL)),
    (1, re.compile(r"(?<![^\W_])_(?=[^\s_]).*?(?<=[^\s_])_(?![^\W_])", re.DOTALL)),
)

#: Emphasis or code wrapped around a binding is split between the prose on either side of
#: it. Rebuilding one side from Word's text dropped its delimiter and kept the other, and
#: `**ratio {{results.x}} was**` merged as `**ratio {{results.x}} was`: literal asterisks in
#: the document, where the author had bold.
_HALF_SPAN = "one end of an emphasis or code span"

#: Every space but layout, as a character that is neither a space nor a letter, for pairing
#: emphasis. Pandoc reads a no-break space as text, so a `*` with one just inside it still
#: opens or closes italics; `_EMPHASIS` reads `\s`, took it for a space, and the paragraph
#: was refused as unaligned.
_TEXT_SPACES = str.maketrans(
    {chr(code): "." for code in range(0x80, 0x3001) if chr(code).isspace()}
)


def _shows(match: re.Match[str]) -> str:
    """What Word's paragraph shows of one construct `_SCAN` found."""
    kind = match.lastgroup or ""
    if kind == "entity":
        return html.unescape(match.group(0))
    if kind == "nbsp":
        return "\u00a0"
    group = _INLINE[kind][2]
    return match.group(group) if group else ""


def _named(match: re.Match[str]) -> str:
    """What a refusal calls it; empty for what a merge brings back."""
    return _INLINE[match.lastgroup or ""][0]


def _tokens(paragraph: str) -> list[re.Match[str]]:
    """The paragraph's own bindings and citations: not those inside a footnote or comment."""
    opaque = [m.span() for m in _SCAN.finditer(paragraph) if m.lastgroup in _OPAQUE]
    return [
        m
        for m in _PROTECTED.finditer(paragraph)
        if not any(start <= m.start() < end for start, end in opaque)
    ]


def segments(paragraph: str) -> tuple[list[str], list[str]]:
    """Split a source paragraph into its prose and the parts the author does not own.

    Returns `(prose, protected)` with `len(prose) == len(protected) + 1`, so the paragraph is
    `prose[0] + protected[0] + prose[1] + ...`. A binding or a citation inside a footnote or a
    comment stays in the prose, with the markup it belongs to.
    """
    tokens = _tokens(paragraph)
    edges = [0] + [edge for m in tokens for edge in m.span()] + [len(paragraph)]
    prose = [paragraph[a:b] for a, b in zip(edges[::2], edges[1::2], strict=True)]
    return prose, [m.group(0) for m in tokens]


def _spaced(text: str) -> str:
    """Runs of layout whitespace as one space, kept at the ends: a stretch retyped from
    `3.84%` to `3.84 %` differs only there, and stripping it made the edit disappear. A
    no-break space is kept, as Word's text keeps it; see `docxtext.spaced`."""
    return spaced(text)


def _emphasis(text: str) -> list[tuple[int, int, int]]:
    """Emphasis spans in `text`, as (start, end, delimiter width)."""
    work = text
    found: list[tuple[int, int, int]] = []
    for width, pattern in _EMPHASIS:
        while spans := [m.span() for m in pattern.finditer(work)]:
            for start, end in spans:
                # Marked, not removed: offsets stay put, and a marked delimiter still reads
                # as something that is not a space, so `***x***` pairs its outer asterisks.
                inside = work[start + width : end - width]
                work = work[:start] + "\x01" * width + inside + "\x01" * width + work[end:]
                found.append((start, end, width))
    return found


@dataclass(frozen=True)
class _Reading:
    """A source paragraph read the way Word shows it, stretch by stretch.

    The paragraph is read whole, with each binding filled in by digits, because what a
    stretch is depends on its neighbours: `*{{results.x}}*` is emphasis around a number and
    `US$5–US${{results.hi}}` is a price, and neither is either when a stretch is read alone.
    """

    prose: list[str]
    protected: list[str]
    #: What Word shows of each stretch of prose, spaces normalised.
    shown: list[str]
    #: What each stretch holds that Word's text cannot carry back, named for the author.
    lost: list[tuple[str, ...]]
    #: The whole paragraph as Word shows it, with each token as the rendering given for it.
    whole: str


def _read(paragraph: str, renderings: Sequence[str] = ()) -> _Reading:
    tokens = _tokens(paragraph)
    filled = list(paragraph)
    for m in tokens:
        filled[m.start() : m.end()] = "0" * (m.end() - m.start())
    filled_text = "".join(filled)

    shows = list(paragraph)  # what each character of the source puts into Word's text
    plain = list(filled_text)  # where emphasis is read: constructs set aside, as digits
    marks: list[tuple[int, int, str]] = []
    for m in _SCAN.finditer(filled_text):
        kind = m.lastgroup or ""
        start, end = m.span()
        group = _INLINE[kind][2]
        inner = m.span(group) if group else (start, start)
        shows[start:end] = [""] * (end - start)
        if kind in ("entity", "nbsp"):
            shows[start] = _shows(m)
        elif group:
            shows[inner[0] : inner[1]] = list(paragraph[inner[0] : inner[1]])
        keep = inner if kind in _MARKDOWN_INSIDE else (start, start)
        plain[start:end] = [
            filled_text[p] if keep[0] <= p < keep[1] else "0" for p in range(start, end)
        ]
        if name := _named(m):
            marks.append((start, end, name))
        elif kind in ("code", "coded") and any(start < t.start() < end for t in tokens):
            ticks = len(m.group(f"{kind}_ticks"))
            closing = m.end(f"{kind}_text")
            marks += [(start, start + ticks, _HALF_SPAN), (closing, closing + ticks, _HALF_SPAN)]

    for start, end, width in _emphasis("".join(plain).translate(_TEXT_SPACES)):
        shows[start : start + width] = [""] * width
        shows[end - width : end] = [""] * width
        if any(start < t.start() < end for t in tokens):
            marks += [(start, start + width, _HALF_SPAN), (end - width, end, _HALF_SPAN)]

    for index, m in enumerate(tokens):
        shows[m.start() : m.end()] = [""] * (m.end() - m.start())
        if index < len(renderings):
            shows[m.start()] = renderings[index]

    edges = [0] + [edge for m in tokens for edge in m.span()] + [len(paragraph)]
    ranges = list(zip(edges[::2], edges[1::2], strict=True))
    return _Reading(
        prose=[paragraph[a:b] for a, b in ranges],
        protected=[m.group(0) for m in tokens],
        shown=[_spaced("".join(shows[a:b])) for a, b in ranges],
        lost=[
            tuple(dict.fromkeys(name for start, end, name in marks if start < b and end > a))
            for a, b in ranges
        ],
        whole=_spaced("".join(shows)).strip(),
    )


#: A paragraph that opens like a block: a heading, a list item, a block quote, a fenced div.
#: Word's text rarely does, and "1990. The year..." at the start of a paragraph is a list.
_OPENER = re.compile(
    r"(?P<mark>[#>]|:(?=::))|(?P<bullet>[-+])(?=\s)"
    r"|(?:\d+|[a-z]|[ivxlcdm]+)(?P<delim>[.)])(?=\s)"
    r"|(?P<paren>\()(?:\d+|[a-z]|[ivxlcdm]+)\)(?=\s)"
)

#: Every character Markdown can read as the start or end of markup, wherever it stands in
#: Word's text. Asking this module's own reading which ones mattered was tried first, and
#: its reading is close to pandoc's, not the same: `<LLOQ in mg/L and >` is a tag to pandoc
#: and was text to it, so the words were merged bare and deleted at the next build. A
#: backslash before punctuation never changes what pandoc prints, except before a quote, a
#: hyphen or a full stop, which it would stop typesetting; those are left alone here, and
#: only `_OPENER` escapes one, where it would open the paragraph as a list.
_MARKDOWN = re.compile(
    r"[\\`*\[^~{$]"
    r"|<(?=[A-Za-z/!?])"  # a tag, a comment or an autolink; "p < 0.05" is not one
    r"|(?<![A-Za-z0-9])@"  # a citation; the @ of an e-mail address follows a letter
    r"|&(?=#?\w+;)"  # an entity
    r"|(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])"  # emphasis; inside a word it is a letter
    r"|(?<=\])\("  # a link's address, whose `[` may stand in the source's own prose
)


def _escaped(
    text: str, opening: bool, after_token: bool = False, before_token: bool = False
) -> str:
    """Word's text written into Markdown so that it reads as the text it is.

    Word's text is literal. Put into the source as it is, a `*` typed there opens italics,
    an `@name` is a citation, a `{{results.x}}` is a binding - a number the co-author typed,
    entering the manuscript as though the analysis had produced it - and `CYP2D6\\*4`, shown
    in Word as `CYP2D6*4`, came back as the start of an emphasis span.

    Its edges are read with what will stand beside them. A `(` straight after a citation's
    `]` makes a link, and `(see Table 2)` became the address of one; a `<` straight before a
    binding whose value is a word opens a tag, and a `]` before one whose value opens with
    `(` makes the value a link's address. At the end of the text none of them looked like
    markup, because the citation and the binding were not there to see. The value is not
    seen here either, so a `]` is escaped before any token, whatever follows it.

    A `{` before a binding is written as an entity. Escaped, it still joined the binding's
    own braces: `\\{{{results.x}}` reads as the binding `{{{results.x}}`, which `check`
    refuses as malformed. The entity is a named one because `&#123;` puts the number 123
    into the prose, and `check` refuses that as a number bound to no source.
    """
    brace = before_token and text.endswith("{")
    text = _MARKDOWN.sub(lambda m: "\\" + m.group(0), text)
    if after_token and text.startswith("("):
        text = "\\" + text
    if before_token and text.endswith(("<", "&", "]")):
        text = text[:-1] + "\\" + text[-1]
    if brace:
        text = text.removesuffix("\\{") + "&lbrace;"
    if opening and (block := _OPENER.match(text)):
        at = next(block.start(g) for g in ("mark", "bullet", "delim", "paren") if block.group(g))
        text = text[:at] + "\\" + text[at:]
    return text


def _reads_as(rebuilt: str, renderings: Sequence[str], returned: str) -> bool:
    """Whether the rebuilt source, built, would read as what came back from Word."""
    reading = _read(rebuilt, renderings)
    if len(reading.protected) != len(renderings):
        return False
    return _untypeset(reading.whole) == _untypeset(returned)


#: Pandoc's `smart` typesetting puts a no-break space after an abbreviation it knows - "e.g.",
#: "et al.", "p." - where the source has a plain one. So where the source is read against
#: Word's text, that character stands for a space. Word's text read against Word's text
#: compares it as itself, so one the co-author typed is an edit.
_PANDOC_SPACE = {"\u00a0": " "}
_AS_SOURCE = str.maketrans(_PANDOC_SPACE)

#: Pandoc typesets prose: quotes curl, `--` becomes an en dash. None of that is an edit, and
#: none of it is something the source holds that Word's text lost.
_TYPESET = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2013": "--", "\u2014": "---", "\u2026": "...",
        **_PANDOC_SPACE,
    }
)


def _untypeset(text: str) -> str:
    return _spaced(text.translate(_TYPESET)).strip()


@dataclass(frozen=True)
class Alignment:
    """What `align` made of one reworded paragraph, and why not when it made nothing."""

    rebuilt: str | None
    #: The protected tokens that did not come back as they rendered, as (rendered, token):
    #: `("3.84", "{{results.ror.point}}")`. This is what lets a refusal name the value and
    #: where it comes from instead of saying that something, somewhere, changed.
    changed: tuple[tuple[str, str], ...] = ()
    #: The paragraph could not be lined up with its own rendering, so nothing can be said
    #: about which part of it is a number, or what a rewording of it would lose.
    unaligned: bool = False
    #: What the edited text carries that plain Word text cannot bring back, named for the
    #: author: `("a footnote", "an HTML comment")`.
    markup: tuple[str, ...] = ()
    #: Rebuilt, it would not read as what came back: Markdown the merge could not keep from
    #: being read as markup, or markup beside the edit that it would change.
    misread: bool = False
    #: Everything between two tokens was deleted, so rebuilt they would touch.
    touching: bool = False


#: A word for alignment: a number with its decimal and thousands separators, a run of
#: letters, a run of whitespace, or one other character. Numbers are whole words so that
#: '13.84' can never contain '3.84'.
_WORD = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+|\s+|.", re.DOTALL)

#: A sign or a comparison put directly in front of a value changes it: any dash, which
#: covers the en and em dashes Word's AutoCorrect makes of a hyphen, and any mathematical
#: symbol (minus, plus, plus-minus, <, less-or-equal, ~, approximately-equal). Listing
#: the four obvious ones missed the dashes, and `-{{results.ror.point}}` typed through
#: AutoCorrect merged as a negative ratio.
_SIGNS = frozenset({"Pd", "Sm"})


def _token_spans(flat: list[str], rendered: str) -> list[tuple[int, int]] | None:
    """Where each protected token sits in the rendered paragraph: the gaps between the prose.

    `flat` is each stretch of prose as Word shows it. Found without knowing how anything
    renders, which is what makes citations work - their rendering depends on a CSL style
    this code never sees. A no-break space pandoc added reads as the source's space, one for
    one, so the spans found are spans of `rendered` itself.
    """
    rendered = rendered.translate(_AS_SOURCE)
    flat = [piece.translate(_AS_SOURCE) for piece in flat]
    spans: list[tuple[int, int]] = []
    cursor = 0
    if flat[0]:
        at = rendered.find(flat[0])
        if at < 0:
            return None
        cursor = at + len(flat[0])
    for index in range(1, len(flat)):
        piece = flat[index]
        if piece:
            at = rendered.find(piece, cursor)
            if at < 0:
                return None
            start, end, cursor = cursor, at, at + len(piece)
        elif index == len(flat) - 1:
            start, end, cursor = cursor, len(rendered), len(rendered)
        else:
            # Two protected tokens with nothing between them: there is no way to say where
            # one rendering ends and the next begins.
            return None
        while start < end and rendered[start].isspace():
            start += 1
        while end > start and rendered[end - 1].isspace():
            end -= 1
        if start == end:
            return None
        spans.append((start, end))
    return spans


def _words(rendered: str, spans: list[tuple[int, int]]) -> tuple[list[str], list[tuple[int, int]]]:
    """The rendered paragraph as words, with a word boundary forced at every token's edge.

    Returns the words and, for each token, the range of word indices it occupies.
    """
    words: list[str] = []
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for start, end in spans:
        words += _WORD.findall(rendered[cursor:start])
        first = len(words)
        words += _WORD.findall(rendered[start:end])
        ranges.append((first, len(words)))
        cursor = end
    words += _WORD.findall(rendered[cursor:])
    return words, ranges


def _undone(returned: str, shown: str, sent: str) -> bool:
    """Whether Word's text only undid pandoc's typesetting: it reads as the source does, and
    the source reads as what was sent, but for typesetting.

    The second half is the guard. The reading is wrong where pandoc prints as text what it
    takes for markup - a footnote reference with no note, an image with no file - and a
    co-author who deleted that text matched it: the source was kept and the edit dropped.
    """
    return _spaced(returned) == shown and _untypeset(shown) == _untypeset(sent)


def _between(words: list[str], tokens: list[tuple[int, int]]) -> list[str]:
    """The prose either side of each token, given the range of words each token occupies."""
    prose: list[str] = []
    cursor = 0
    for start, end in tokens:
        prose.append("".join(words[cursor:start]))
        cursor = end
    prose.append("".join(words[cursor:]))
    return prose


def _place(
    tokens: list[str], ranges: list[tuple[int, int]], before: list[str], after: list[str]
) -> tuple[list[tuple[int, int]], list[int]]:
    """Where each token's words landed in `after`, and which tokens did not come back whole.

    A token must sit inside one stretch the two texts share, so none of its words changed; a
    sign typed directly in front of a value that starts that stretch is a change to it.
    """
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    equal = [op for op in matcher.get_opcodes() if op[0] == "equal"]
    placed: list[tuple[int, int]] = []
    missing: list[int] = []
    for index, (first, last) in enumerate(ranges):
        block = next((op for op in equal if op[1] <= first and last <= op[2]), None)
        if block is None:
            missing.append(index)
            continue
        at = first + block[3] - block[1]
        glued = after[at - 1] if at > 0 else ""
        signed = len(glued) == 1 and unicodedata.category(glued) in _SIGNS
        if first == block[1] and signed and tokens[index][:1].isdigit():
            missing.append(index)
            continue
        placed.append((at, at + last - first))
    return placed, missing


def align(source: str, rendered: str, returned: str) -> Alignment:
    """Rewrite one source paragraph with a co-author's wording, keeping its bindings.

    The paragraph-level merge had to refuse anything carrying a binding, because splicing
    the returned text in would replace `{{results.ror.point}}` with `3.84`. Refusing is safe
    and, in a paper where most paragraphs quote a number, refuses almost everything.

    Alignment makes the finer move possible. A source paragraph is prose and protected
    tokens in alternation. Its prose appears verbatim in the rendered form - rendering only
    changes the protected parts - so locating the prose segments in `rendered` reveals what
    each token rendered to, *without needing to know how it renders*.

    Those rendered forms are then found in the returned text by aligning the two word by
    word. The first version searched for each rendered form as a substring from the start of
    the paragraph: '3.84' was found inside '13.84' and merged as `1{{results.ror.point}}`,
    and in "Table 1 shows 1 events" the binding went onto the table number. Here a number is
    one word and cannot be found inside a longer one, and each token is placed where the
    unchanged words around it say it is. Tokens that come back out of order cannot both sit
    in shared stretches, so a transposed interval is still refused.

    Otherwise the text between the tokens is the new prose, and the paragraph is rebuilt from
    the *source's* tokens and the *co-author's* words. An unchanged prose segment is kept
    exactly as the source has it, which preserves its markdown - only a segment the
    co-author actually edited loses its inline formatting.

    Losing bold is a cost; losing a footnote is a corruption. An edited segment that holds
    something Word's text cannot carry back - a footnote, a comment, a link's address, the
    raised 9 in 10^9 - refuses the paragraph and names it. Only the edited segment counts:
    a footnote in a stretch the co-author left alone is kept from the source, where it was.

    Then the rebuilt paragraph is read back, by this module's reading of Markdown, and must
    read as what the co-author wrote. That catches what the reading can see - a delimiter
    left without its partner, a span stretched over new words - and not where it and
    pandoc disagree, which is why `_escaped` does not consult it.
    """
    reading = _read(source)
    prose, protected = reading.prose, reading.protected
    if not protected:
        return _align_plain(source, reading, rendered, returned)

    spans = _token_spans([shown.strip() for shown in reading.shown], rendered)
    if spans is None:
        return Alignment(None, unaligned=True)
    tokens = [rendered[start:end] for start, end in spans]
    before, ranges = _words(rendered, spans)
    after = _WORD.findall(returned)
    placed, missing = _place(tokens, ranges, before, after)
    if missing:
        return Alignment(None, changed=tuple((tokens[i], protected[i]) for i in missing))

    sent, new_prose = _between(before, ranges), _between(after, placed)
    out: list[str] = []
    lost: list[str] = []
    for index, piece in enumerate(new_prose):
        # Unchanged prose keeps the source's own markdown; only an edited segment is taken
        # from Word, where inline formatting did not survive being read as plain text.
        # Unchanged means it came back as it was sent, which catches a no-break space the
        # co-author typed, or as the source reads, which lets pandoc's own after "e.g." be
        # taken out again in Word without costing the stretch its formatting. See `_undone`.
        if _spaced(piece) == _spaced(sent[index]) or _undone(
            piece, reading.shown[index], sent[index]
        ):
            out.append(prose[index])
        else:
            lost += [name for name in reading.lost[index] if name not in lost]
            beside = {"after_token": index > 0, "before_token": index < len(protected)}
            out.append(_escaped(piece, opening=index == 0, **beside))
        if index < len(protected):
            out.append(protected[index])
    if lost:
        return Alignment(None, markup=tuple(lost))
    # With nothing between them there is nothing to escape: a citation's `]` against a value
    # that opens with `(` is a link, and the interval was its address. Nor can two touching
    # tokens be lined up again, so every later edit to the paragraph would be refused. After
    # the markup: a footnote deleted with the words around it is the reason to name.
    if not all(new_prose[1:-1]):
        return Alignment(None, touching=True)
    rebuilt = "".join(out).strip()
    if not _reads_as(rebuilt, tokens, returned):
        return Alignment(None, misread=True)
    return Alignment(rebuilt or None)


def _align_plain(source: str, reading: _Reading, rendered: str, returned: str) -> Alignment:
    """A paragraph with no binding or citation, which Word's text replaces whole.

    Unless that would lose something. What `_INLINE` names is refused by name. Anything it
    does not know is caught by reading the source as Word should show it: if that is not
    what Word does show, part of the source did not reach Word as text, and a rewording
    rebuilt from Word's text would delete it.
    """
    # As it was sent, or as the source reads; see `align`.
    if _spaced(returned).strip() == _spaced(rendered).strip() or _undone(
        returned.strip(), reading.shown[0].strip(), rendered
    ):
        return Alignment(source)
    if reading.lost[0]:
        return Alignment(None, markup=reading.lost[0])
    if _untypeset(reading.shown[0]) != _untypeset(rendered):
        return Alignment(None, unaligned=True)
    rebuilt = _escaped(returned.strip(), opening=True)
    if not _reads_as(rebuilt, (), returned):
        return Alignment(None, misread=True)
    return Alignment(rebuilt or None)


def realign(source: str, rendered: str, returned: str) -> str | None:
    """The rebuilt paragraph, or None when it cannot be merged. See `align`."""
    return align(source, rendered, returned).rebuilt
