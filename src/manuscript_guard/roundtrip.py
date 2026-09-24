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
import unicodedata
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.docxtext import TOKEN

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


def tag(text: str, relative: str, *, mark: bool = False) -> str:
    """Give every ordinary paragraph of one source file an invisible identifier.

    Headings are skipped: `[]{#id}# Methods` is not a heading. So are fenced divs and code
    blocks, and paragraphs that are nothing but a placeholder, because those become a table
    or a figure rather than a paragraph, and a bookmark would attach to the wrong thing.

    With `mark`, every binding and citation in a tagged paragraph gets a Word bookmark
    around it as well, written as raw OpenXML that pandoc passes through untouched. Only the
    build `import` compares with is marked, and it is what tells `align` exactly where each
    token's rendering begins and ends. It was a `[token]{#id}` span first, and a span adds
    brackets: beside an unbalanced one, pandoc paired them differently, the text still read
    the same, and the extent lost its first character - so a rewording wrote a `[` twice.
    """
    out = []
    counter = iter(range(1_000_000))
    slug = paragraph_slug(relative)
    for index, para in enumerate(re.split(r"(\n\s*\n)", text)):
        stripped = para.strip()
        if para.strip("\n") == "" or _untagged(stripped):
            out.append(para)
            continue
        marker = _TAG.format(slug=slug, index=index)
        body = stripped
        if mark:
            spans = _protected_spans(body)
            marked = [_bookmarked(body[a:b], slug, counter) for a, b in spans]
            for (a, b), replacement in reversed(list(zip(spans, marked, strict=True))):
                body = body[:a] + replacement + body[b:]
        out.append(para.replace(stripped, f"[]{{#{marker}}}{body}", 1))
    return "".join(out)


def _bookmarked(token: str, slug: str, counter) -> str:
    """`token` between a raw bookmark start and end, invisible in the built document."""
    number = next(counter)
    # Far above the identifiers pandoc numbers its own bookmarks with.
    ident = 1_000_000 + number
    start = f'`<w:bookmarkStart w:id="{ident}" w:name="{TOKEN}{slug}-{number}"/>`{{=openxml}}'
    end = f'`<w:bookmarkEnd w:id="{ident}"/>`{{=openxml}}'
    return f"{start}{token}{end}"


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


#: A binding or a citation: the parts of a paragraph the author does not own. Citations
#: are read in the forms pandoc reads - `[see @key, p. 4]` with its prefix and locator,
#: `[@key, p. 3 [emphasis added]]` with brackets inside it, and a narrative `@key`, with
#: its locator in `@key [p. 33]` - because only `[@key]` was protected at first, and a
#: rewording of a paragraph citing `@smith2020` merged it back as the text "Smith (2020)".
_BINDING = re.compile(r"\{\{[^}]*\}\}")
_KEY = r"-?@[A-Za-z][\w:.#$%&+?<>~/-]*(?<![:.#$%&+?<>~/-])"
#: A key at a bracket group's own level makes the group a citation. A narrative key ends on
#: a word character, so a full stop after it stays prose; an email address is no key.
_OWN_KEY = re.compile(rf"(?<![\w@]){_KEY}")
_NARRATIVE = re.compile(rf"(?<![\w`\[@]){_KEY}")
#: Whatever the patterns above miss, a key left in the prose: the paragraph is refused
#: rather than merged, since Word's text holds the citation's rendering and not the key.
_LOOSE_KEY = re.compile(r"(?<![\w`@])@[A-Za-z]")


def _bracket_groups(text: str) -> list[tuple[int, int]]:
    """Balanced bracket groups as (start, end), escaped brackets skipped."""
    groups: list[tuple[int, int]] = []
    open_: list[int] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            open_.append(index)
        elif char == "]" and open_:
            groups.append((open_.pop(), index + 1))
        index += 1
    return sorted(groups)


def _protected_spans(text: str) -> list[tuple[int, int]]:
    """Where the bindings and citations of a source paragraph are, in order.

    A bracketed citation is a balanced bracket group with a key at its own level, not only
    inside a nested group: "[see [@key]]" cites through its inner group, and
    "[@key, p. 3 [emphasis added]]" is one citation. Found by balance, because a pattern
    either stopped at the first inner bracket - and protected nothing - or started at the
    first `[` of the paragraph, and made the prose "[low, high) were rescaled as in" part of
    a citation.
    """
    spans = [m.span() for m in _BINDING.finditer(text)]

    def free(start: int, end: int) -> bool:
        return not any(s < end and start < e for s, e in spans)

    groups = _bracket_groups(text)
    for start, end in groups:
        inner = [(s, e) for s, e in groups if start < s and e < end]
        own = list(text[start + 1 : end - 1])
        for s, e in inner:
            own[s - start - 1 : e - start - 1] = " " * (e - s)
        if _OWN_KEY.search("".join(own)) and free(start, end):
            spans.append((start, end))
    for match in _NARRATIVE.finditer(text):
        start, end = match.span()
        if not free(start, end):
            continue
        locator = re.match(r"[ \t]+\[", text[end:])
        if locator:
            group = next((g for g in groups if g[0] == end + locator.end() - 1), None)
            if group and not _OWN_KEY.search(text[group[0] + 1 : group[1] - 1]):
                end = group[1]
        spans.append((start, end))
    return sorted(spans)


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
    spans = _protected_spans(paragraph)
    edges = [0] + [edge for span in spans for edge in span] + [len(paragraph)]
    prose = [paragraph[a:b] for a, b in zip(edges[::2], edges[1::2], strict=True)]
    return prose, [paragraph[a:b] for a, b in spans]


#: Quotes are compared as quotes, whichever way they curl. Pandoc curls them, Word's
#: autocorrect curls them again, and a co-author with autocorrect off types them straight -
#: none of which is an edit.
_STRAIGHT = str.maketrans(
    "\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f", "''''" + '""""'
)


def _comparable(text: str) -> str:
    """Rendered text reduced to what an edit could change: straight quotes, single spaces."""
    return re.sub(r"\s+", " ", text.translate(_STRAIGHT)).strip()


@dataclass(frozen=True)
class Alignment:
    """What `align` made of one reworded paragraph, and why not when it made nothing."""

    rebuilt: str | None
    #: The protected tokens that did not come back as they rendered, as (rendered, token):
    #: `("3.84", "{{results.ror.point}}")`. This is what lets a refusal name the value and
    #: where it comes from instead of saying that something, somewhere, changed.
    changed: tuple[tuple[str, str], ...] = ()
    #: Where its bindings and citations were rendered is not known - the build compared
    #: with did not mark them all - so nothing can be said about which part is a number.
    unaligned: bool = False
    #: It carries markup that plain Word text cannot bring back: a footnote, a link, an
    #: image, an equation.
    markup: bool = False
    #: An edited segment holds half of some formatting whose other half is across a token.
    wraps: bool = False


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

#: Markdown that renders to something plain `w:t` text does not carry. Merging Word's text
#: over a paragraph with a footnote in it deleted the footnote; with a link, the address;
#: with display maths, the equation and everything after it, which pandoc sets apart as
#: paragraphs of their own; with inline TeX, the equation, which Word holds as OMML
#: rather than as text; with an HTML comment, the comment.
_MARKUP = re.compile(
    r"\^\[|\]\(|\$\$|<!--|(?<![\\$])\$(?=\S)[^$]*?(?<=\S)\$(?!\d)"
)


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
        glued = after[at - 1] if at > 0 else ""
        signed = len(glued) == 1 and unicodedata.category(glued) in _SIGNS
        if first == block[1] and signed and tokens[index][:1].isdigit():
            missing.append(index)
            continue
        placed.append((at, at + last - first))
    return placed, missing


def align(
    source: str,
    rendered: str,
    returned: str,
    tokens: Sequence[tuple[int, int]] | None,
) -> Alignment:
    """Rewrite one source paragraph with a co-author's wording, keeping its bindings.

    The paragraph-level merge had to refuse anything carrying a binding, because splicing
    the returned text in would replace `{{results.ror.point}}` with `3.84`. Refusing is safe
    and, in a paper where most paragraphs quote a number, refuses almost everything.

    Alignment makes the finer move possible. A source paragraph is prose and protected
    tokens in alternation, and `tokens` says where each token's rendering sits in `rendered`
    - read from bookmarks pandoc put around them in the build compared with, so nothing about
    how a number or a citation renders has to be known or guessed.

    It used to be guessed: the source's prose was flattened and searched for in the rendered
    text, and the tokens were whatever lay between. Pandoc typesets prose (`drug's` reaches
    Word as `drug’s`), so every paragraph with a binding and an apostrophe was refused; and a
    short piece of prose could be found inside a token's rendering. "(Smith et al. 2020)."
    ending a paragraph had its citation cut at "al.", and a rewording merged as
    `[@smith2020]. 2020).`.

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
    if _LOOSE_KEY.search("\x00".join(prose)):
        return Alignment(None, unaligned=True)
    if not protected:
        return Alignment(returned.strip().translate(_STRAIGHT) or None)

    spans = _checked(tokens, len(protected), len(rendered))
    if spans is None:
        return Alignment(None, unaligned=True)
    shown = [rendered[start:end] for start, end in spans]
    before, ranges = _words(rendered, spans)
    after = _WORD.findall(returned)
    placed, missing = _place(shown, ranges, before, after)
    if missing:
        return Alignment(None, changed=tuple((shown[i], protected[i]) for i in missing))

    new_prose: list[str] = []
    cursor = 0
    for start, end in placed:
        new_prose.append("".join(after[cursor:start]))
        cursor = end
    new_prose.append("".join(after[cursor:]))

    # The prose as it was rendered, between the same tokens: what each returned piece is
    # compared with. Both sides are rendered text, so nothing about markdown is modelled.
    edges = [0] + [edge for span in spans for edge in span] + [len(rendered)]
    was_prose = [rendered[a:b] for a, b in zip(edges[::2], edges[1::2], strict=True)]
    wrapping = _wrapping(prose)
    out: list[str] = []
    for index, piece in enumerate(new_prose):
        # Unchanged prose keeps the source's own markdown; only an edited segment is taken
        # from Word, where inline formatting did not survive being read as plain text.
        same = _comparable(was_prose[index]) == _comparable(piece)
        if not same and index in wrapping:
            return Alignment(None, wraps=True)
        # Straight quotes, for pandoc to curl: Word's closing `’` beside the source's opening
        # `'` made pandoc read the opening one as an apostrophe.
        out.append(prose[index] if same else piece.translate(_STRAIGHT))
        if index < len(protected):
            out.append(protected[index])
    return Alignment("".join(out).strip() or None)


#: Inline markers that open and close with the same characters. They were paired in order,
#: first with second, so one literal `*` earlier in the paragraph - "marked * in Table 2" -
#: shifted every pair after it and `*{{x}}*` merged as `{{x}}* overall`. Now a segment holding
#: one is treated as wrapping whenever another segment holds the same kind: sometimes a
#: refusal a closer reading would allow, never a half-open marker.
_SYMMETRIC = (r"\*\*", r"__", r"~~", r"(?<![\w*])\*|\*(?![\w*])", r"(?<!\w)_|_(?!\w)", r"`")
#: Super- and subscript cannot contain a space, so only one pressed against a token can wrap it.
_SCRIPT_OPEN = re.compile(r"[\^~][^\s^~]*$")
_SCRIPT_CLOSE = re.compile(r"^[^\s^~]*[\^~]")
_TAG_OPEN = re.compile(r"<([A-Za-z][\w-]*)(?:\s[^<>]*)?(?<!/)>")
_TAG_CLOSE = re.compile(r"</([A-Za-z][\w-]*)\s*>")


def _wrapping(prose: list[str]) -> set[int]:
    """The prose segments that may hold half of some formatting around a token.

    An edited segment is taken from Word without its markdown, so the half in it went and
    the half in an untouched segment stayed: `[{{x}}]{.smallcaps}` with its first segment
    edited merged as `The new value {{x}}]{.smallcaps}`, and the document printed the brace.
    Brackets count only when a span or a link follows them - an interval "[{{lo}}, {{hi}}]"
    is text - and `^` and `~` only pressed against a token, as "About ~{{x}} reports" is text.
    """
    parts = [re.sub(r"\\.", "  ", part) for part in prose]
    found: set[int] = set()
    for pattern in _SYMMETRIC:
        holders = {i for i, part in enumerate(parts) if re.search(pattern, part)}
        if len(holders) > 1:
            found |= holders
        parts = [re.sub(pattern, lambda m: " " * len(m.group(0)), part) for part in parts]
    for i in range(len(prose) - 1):
        if _SCRIPT_OPEN.search(prose[i]) and _SCRIPT_CLOSE.search(prose[i + 1]):
            found |= {i, i + 1}

    joined = "\x00".join(re.sub(r"\\.", "  ", part) for part in prose)
    owner = [i for i, part in enumerate(prose) for _ in range(len(part) + 1)]

    def across(a: int, b: int) -> None:
        if "\x00" in joined[a:b]:
            found.update((owner[a], owner[b]))

    for start, end in _bracket_groups(joined):
        if joined[end : end + 1] in ("{", "(", "["):
            across(start, end - 1)
    opened: dict[str, list[int]] = {}
    for at, name, opening in sorted(
        [(m.start(), m.group(1).lower(), True) for m in _TAG_OPEN.finditer(joined)]
        + [(m.start(), m.group(1).lower(), False) for m in _TAG_CLOSE.finditer(joined)]
    ):
        if opening:
            opened.setdefault(name, []).append(at)
        elif opened.get(name):
            across(opened[name].pop(), at)
    return found


def _checked(
    tokens: Sequence[tuple[int, int]] | None, count: int, length: int
) -> list[tuple[int, int]] | None:
    """The token extents, if there is one per token and they read in order with a seam.

    Two tokens with nothing between them - `{{results.a}}{{results.b}}` - are known apart in
    the build, but not in Word's text, where '1' and '2' come back as '12'. Refused here, as
    what it is, rather than further on as a value that changed when none had.
    """
    if tokens is None or len(tokens) != count:
        return None
    spans = [(int(start), int(end)) for start, end in tokens]
    edges = [edge for span in spans for edge in span]
    if any(start >= end for start, end in spans) or edges != sorted(edges) or edges[-1] > length:
        return None
    if any(first[1] == second[0] for first, second in zip(spans, spans[1:], strict=False)):
        return None
    return spans


def realign(
    source: str,
    rendered: str,
    returned: str,
    tokens: Sequence[tuple[int, int]] | None,
) -> str | None:
    """The rebuilt paragraph, or None when it cannot be merged. See `align`."""
    return align(source, rendered, returned, tokens).rebuilt
