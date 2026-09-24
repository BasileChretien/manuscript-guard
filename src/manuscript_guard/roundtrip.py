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


def _untagged(stripped: str) -> bool:
    """Headings, fences, and a lone placeholder (which becomes a table or a figure)."""
    return (
        not stripped
        or stripped.startswith("#")
        or _FENCE.match(stripped) is not None
        or re.fullmatch(r"\{\{[^}]*\}\}", stripped) is not None
    )


def tag(text: str, relative: str) -> str:
    """Give every ordinary paragraph of one source file an invisible identifier.

    Headings are skipped: `[]{#id}# Methods` is not a heading. So are fenced divs and code
    blocks, and paragraphs that are nothing but a placeholder, because those become a table
    or a figure rather than a paragraph, and a bookmark would attach to the wrong thing.
    """
    out = []
    for index, para in enumerate(re.split(r"(\n\s*\n)", text)):
        stripped = para.strip()
        if para.strip("\n") == "" or _untagged(stripped):
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
        for index, para in enumerate(re.split(r"(\n\s*\n)", text)):
            stripped = para.strip()
            start = cursor + (len(para) - len(para.lstrip())) if stripped else cursor
            cursor += len(para)
            if _untagged(stripped):
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


@dataclass(frozen=True)
class Alignment:
    """What `align` made of one reworded paragraph, and why not when it made nothing."""

    rebuilt: str | None
    #: The protected tokens that did not come back as they rendered, as (rendered, token):
    #: `("3.84", "{{results.ror.point}}")`. This is what lets a refusal name the value and
    #: where it comes from instead of saying that something, somewhere, changed.
    changed: tuple[tuple[str, str], ...] = ()
    #: The paragraph could not be lined up with its own rendering, so nothing can be said
    #: about which part of it is a number.
    unaligned: bool = False
    #: It carries markup that plain Word text cannot bring back: a footnote, a link, an image.
    markup: bool = False


#: A word for alignment: a number with its decimal and thousands separators, a run of
#: letters, a run of whitespace, or one other character. Numbers are whole words so that
#: '13.84' can never contain '3.84'.
_WORD = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+|\s+|.", re.DOTALL)

#: A sign put directly in front of a value changes it.
_SIGNS = {"-", "−", "+", "±"}

#: Markdown that renders to something plain `w:t` text does not carry. Merging Word's text
#: over a paragraph with a footnote in it deleted the footnote; with a link, the address.
_MARKUP = re.compile(r"\^\[|\]\(")


def _token_spans(prose: list[str], rendered: str) -> list[tuple[int, int]] | None:
    """Where each protected token sits in the rendered paragraph: the gaps between the prose.

    Found without knowing how anything renders, which is what makes citations work - their
    rendering depends on a CSL style this code never sees.
    """
    flat = [_flatten(piece) for piece in prose]
    spans: list[tuple[int, int]] = []
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
            start, end, cursor = cursor, at, at + len(piece)
        elif index == len(prose) - 1:
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
        if first == block[1] and at > 0 and after[at - 1] in _SIGNS and tokens[index][:1].isdigit():
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
    """
    if _MARKUP.search(source):
        return Alignment(None, markup=True)
    prose, protected = segments(source)
    if not protected:
        return Alignment(returned.strip() or None)

    spans = _token_spans(prose, rendered)
    if spans is None:
        return Alignment(None, unaligned=True)
    tokens = [rendered[start:end] for start, end in spans]
    before, ranges = _words(rendered, spans)
    after = _WORD.findall(returned)
    placed, missing = _place(tokens, ranges, before, after)
    if missing:
        return Alignment(None, changed=tuple((tokens[i], protected[i]) for i in missing))

    new_prose: list[str] = []
    cursor = 0
    for start, end in placed:
        new_prose.append("".join(after[cursor:start]))
        cursor = end
    new_prose.append("".join(after[cursor:]))

    out: list[str] = []
    for index, piece in enumerate(new_prose):
        original = prose[index]
        # Unchanged prose keeps the source's own markdown; only an edited segment is taken
        # from Word, where inline formatting did not survive being read as plain text.
        same = _flatten(original) == _flatten(piece)
        out.append(original if same else piece)
        if index < len(protected):
            out.append(protected[index])
    return Alignment("".join(out).strip() or None)


def realign(source: str, rendered: str, returned: str) -> str | None:
    """The rebuilt paragraph, or None when it cannot be merged. See `align`."""
    return align(source, rendered, returned).rebuilt
