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

from manuscript_guard.docxtext import TOKEN, spaced

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
            spans = [token.span() for token in _tokens(body)]
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
#: A key as pandoc reads one: a letter of any alphabet, a digit or an underscore, then
#: word characters, each mark of punctuation between them single, or anything but a space
#: in braces - `@2019who`, `@Élodie2020`, `@{10.1000/xyz}`. Starting it at an ASCII letter
#: left those in the prose, and `@key::a` is the key `key` to pandoc.
_KEY = r"-?@(?:\{[^{}\s]+\}|\w(?:\w|[:.#$%&+?<>~/-](?=\w))*)"
#: A key at a bracket group's own level makes the group a citation. A narrative key ends on
#: a word character, so a full stop after it stays prose; an email address is no key, and
#: nor is `\@admin`, which is how a co-author's typed `@` is written back. Pandoc reads no
#: key straight after a full stop either: `cohort.@key`, a space deleted in Word, printed
#: the key. Nor straight after a dash, which would make `-@key` of it.
_OWN_KEY = re.compile(rf"(?<![\w@\\.]){_KEY}")
_NARRATIVE = re.compile(rf"(?<![\w`\[@\\.-]){_KEY}")
#: Whatever the patterns above miss, a key left in the prose: the paragraph is refused
#: rather than merged, since Word's text holds the citation's rendering and not the key.
_LOOSE_KEY = re.compile(r"(?<![\w`@\\.])@[\w{]")


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


#: What may stand between a narrative key and the bracket after it, for pandoc to read the
#: two as one citation: nothing, spaces, and a line break in a hard-wrapped source.
_LOCATOR = re.compile(r"[ \t]*(?:\n[ \t]*)?\[")
#: What makes a bracket group a link or a span rather than a citation or a locator.
_LINKED = re.compile(r"\(|\{(?!\{)")


def _protected_spans(
    text: str, literal: Sequence[tuple[int, int]] = ()
) -> list[tuple[int, int]]:
    """Where the bindings and citations of a source paragraph are, in order.

    A bracketed citation is a balanced bracket group with a key at its own level, not only
    inside a nested group: "[see [@key]]" cites through its inner group, and
    "[@key, p. 3 [emphasis added]]" is one citation. Found by balance, because a pattern
    either stopped at the first inner bracket - and protected nothing - or started at the
    first `[` of the paragraph, and made the prose "[low, high) were rescaled as in" part of
    a citation. A narrative key takes the bracket group after it, as pandoc does: `@key
    [p. 33]` is a key and its locator, and `@a [see @b]` is one citation. A group followed
    by `(` or `{` is a link or a span, and neither.

    A citation is one token with any binding inside it, `[@key, table {{results.t}}]`:
    found as a binding first, it dropped the citation, which then stayed in the prose. None
    is read in code or an autolink, `literal`, where pandoc reads none either.
    """
    groups = _bracket_groups(text)

    def within(at: int, spans: Sequence[tuple[int, int]]) -> bool:
        return any(s <= at < e for s, e in spans)

    groups = [(s, e) for s, e in groups if not _LINKED.match(text, e)]
    cites: list[tuple[int, int]] = []
    for start, end in groups:  # in order of start, so a group comes before those inside it
        if within(start, cites) or within(start, literal):
            continue
        inner = [(s, e) for s, e in groups if start < s and e < end]
        own = list(text[start + 1 : end - 1])
        for s, e in inner:
            own[s - start - 1 : e - start - 1] = " " * (e - s)
        if _OWN_KEY.search("".join(own)):
            cites.append((start, end))
    for match in _NARRATIVE.finditer(text):
        start, end = match.span()
        if within(start, cites) or within(start, literal):
            continue
        locator = _LOCATOR.match(text, end)
        group = locator and next((g for g in groups if g[0] == locator.end() - 1), None)
        if group:
            cites = [(s, e) for s, e in cites if not (group[0] <= s and e <= group[1])]
            end = group[1]
        cites.append((start, end))
    bindings = [m.span() for m in _BINDING.finditer(text) if not within(m.start(), cites)]
    return sorted(cites + bindings)


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

#: Where pandoc reads no citation, though a binding inside is filled in all the same.
_LITERAL = frozenset({"code", "coded", "autolink"})

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


@dataclass(frozen=True)
class _Token:
    """One binding or citation found in a paragraph, answering as a regex match would."""

    at: int
    to: int
    text: str

    def start(self) -> int:
        return self.at

    def end(self) -> int:
        return self.to

    def span(self) -> tuple[int, int]:
        return (self.at, self.to)

    def group(self, _index: int = 0) -> str:
        return self.text


def _tokens(paragraph: str) -> list[_Token]:
    """The paragraph's own bindings and citations: not those inside a footnote or comment,
    and no citation in code, an autolink or a link's address."""
    scanned = list(_SCAN.finditer(paragraph))
    opaque = [m.span() for m in scanned if m.lastgroup in _OPAQUE]
    literal = [m.span() for m in scanned if m.lastgroup in _LITERAL]
    # A link's address: `(https://mastodon.social/@someone)` holds no citation.
    literal += [
        (m.end("link_text") + 1, m.end())
        for m in scanned
        if m.lastgroup == "link" and paragraph.startswith("(", m.end("link_text") + 1)
    ]
    return [
        _Token(a, b, paragraph[a:b])
        for a, b in _protected_spans(paragraph, literal)
        if not any(start <= a < end for start, end in opaque)
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


#: Quotes of every kind as the straight quote they are, for comparing stretches only: what is
#: written into the source keeps Word's own characters. Straightening those for pandoc to
#: curl again turned „ein Signal“ into “ein Signal” and the ’90s into ‘90s.
_STRAIGHT = str.maketrans(
    "\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f", "\u0027" * 4 + "\u0022" * 4
)


def _unchanged(was: str, now: str) -> bool:
    """Whether a stretch came back as it was rendered: quotes compared as quotes, spaces
    kept at the ends."""
    return _spaced(was.translate(_STRAIGHT)) == _spaced(now.translate(_STRAIGHT))


#: A straight single quote where pandoc reads it as opening a quotation, and one where it
#: reads it as closing one. Between two letters, as in "they're", it is neither. At the end
#: of a stretch a token follows it, so a quote there opens: `'{{results.x}} to one'`.
_OPENS = re.compile(r"'(?!\s)")
_CLOSES = re.compile(r"'(?!\w)")
#: Word's closing quote, where pandoc would read a straight one there as closing.
_WORD_CLOSES = re.compile("\u2019(?!\\w)")


def _left_open(stretch: str, first: bool, was_open: bool) -> bool:
    """Whether a straight single quote of the source is still open after this stretch.

    Pandoc pairs a straight opening quote with a straight closing one, across a number or a
    citation if need be. A stretch after a token starts beside it, so a quote at its very
    start is not opening one.
    """
    is_open = was_open
    for match in re.finditer(r"(?<!\\)'", stretch):
        at = match.start()
        after_space = at == 0 and first or at > 0 and not stretch[at - 1].isalnum()
        if after_space and _OPENS.match(stretch, at):
            is_open = True
        elif is_open and _CLOSES.match(stretch, at):
            is_open = False
    return is_open


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
    quiet: list[tuple[int, int]] = []  # where an `@` is not a key: code, a footnote, ...
    for m in _SCAN.finditer(filled_text):
        kind = m.lastgroup or ""
        start, end = m.span()
        if kind in _OPAQUE | _LITERAL:
            quiet.append((start, end))
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

    # A key the token patterns missed: Word's text holds its rendering, not the key.
    marks += [
        (m.start(), m.end(), "a citation")
        for m in _LOOSE_KEY.finditer(paragraph)
        if not any(s <= m.start() < e for s, e in quiet)
    ]

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
    binding whose value is a word opens a tag. At the end of the text neither looked like
    markup, because the citation and the binding were not there to see.
    """
    text = _MARKDOWN.sub(lambda m: "\\" + m.group(0), text)
    if after_token and text.startswith("("):
        text = "\\" + text
    if before_token and text.endswith(("<", "&")):
        text = text[:-1] + "\\" + text[-1]
    if opening and (block := _OPENER.match(text)):
        at = next(block.start(g) for g in ("mark", "bullet", "delim", "paren") if block.group(g))
        text = text[:at] + "\\" + text[at:]
    return text


def _reads_as(
    rebuilt: str, protected: Sequence[str], renderings: Sequence[str], returned: str
) -> bool:
    """Whether the rebuilt source, built, would read as what came back from Word.

    Its tokens must be the source's, each read as it was and none touching another. Counting
    them was not enough: an edit that left `[@a][@b]` read as a link, `@a:{{results.x}}` as
    the key `a:3.84`, and `cohort.@key` as no citation at all, with as many tokens found.
    """
    reading = _read(rebuilt, renderings)
    if reading.protected != list(protected):
        return False
    found = _tokens(rebuilt)
    for index, (first, second) in enumerate(zip(found, found[1:], strict=False)):
        between = rebuilt[first.end() : second.start()]
        if not between:
            return False
        # A key then one mark of punctuation reads on into a number put straight after it.
        glued = (
            not first.text.endswith(("]", "}"))
            and _BINDING.fullmatch(second.text)
            and re.fullmatch(r"[:.#$%&+?<>~/-]", between)
            and re.match(r"\w", renderings[index + 1])
        )
        if glued:
            return False
    return _untypeset(reading.whole) == _untypeset(returned)


#: Pandoc's `smart` typesetting puts a no-break space after an abbreviation it knows - "e.g.",
#: "et al.", "p." - where the source has a plain one. So where the source is read against
#: Word's text, that character stands for a space. Word's text read against Word's text
#: compares it as itself, so one the co-author typed is an edit.
_PANDOC_SPACE = {"\u00a0": " "}

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
    - read from bookmarks around them in a second build, so nothing about how a number or a
    citation renders is guessed. It used to be: the prose was looked for in the rendered
    text and the tokens were what lay between, and "(Smith et al. 2020)." ending a paragraph
    had its citation cut at "al.", merging as `[@smith2020]. 2020).`.

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

    spans = _checked(tokens, len(protected), len(rendered))
    if spans is None:
        return Alignment(None, unaligned=True)
    tokens = [rendered[start:end] for start, end in spans]
    before, ranges = _words(rendered, spans)
    after = _WORD.findall(returned)
    placed, missing = _place(tokens, ranges, before, after)
    if missing:
        return Alignment(None, changed=tuple((tokens[i], protected[i]) for i in missing))

    new_prose = _between(after, placed)

    # Each stretch as the build rendered it, between the same tokens: what a returned piece
    # is compared with, rendered text against rendered text.
    edges = [0] + [edge for span in spans for edge in span] + [len(rendered)]
    was_prose = [rendered[a:b] for a, b in zip(edges[::2], edges[1::2], strict=True)]
    out: list[str] = []
    lost: list[str] = []
    unread = False
    # A straight ' kept from the source that opens a quotation closed in an edited stretch:
    # Word's closing ’ there is written straight, or pandoc reads the kept one as an
    # apostrophe and prints "’a ratio of 3.84’". Only that one; the rest stay as typed.
    quote_open = False
    for index, piece in enumerate(new_prose):
        # Unchanged prose keeps the source's own markdown; only an edited segment is taken
        # from Word, where inline formatting did not survive being read as plain text.
        # Unchanged means it came back as it was sent, which catches a no-break space the
        # co-author typed, or as the source reads, which lets pandoc's own after "e.g." be
        # taken out again in Word without costing the stretch its formatting. See `_undone`.
        if _unchanged(was_prose[index], piece) or _undone(
            piece, reading.shown[index], was_prose[index]
        ):
            out.append(prose[index])
            # Open only if pandoc did open it: it prints the ' of 'Tis or '90s as ’.
            opened = quote_open or "\u2018" in was_prose[index]
            quote_open = opened and _left_open(prose[index], index == 0, quote_open)
        else:
            lost += [name for name in reading.lost[index] if name not in lost]
            # What the build printed of the stretch must be what the source reads as, or
            # part of it is something Word's text does not hold: `[Methods]` is a link to
            # the heading, and pandoc reads `<LLOQ in mg/L and >` as a tag.
            unread |= _untypeset(reading.shown[index]) != _untypeset(was_prose[index])
            if quote_open and _WORD_CLOSES.search(piece):
                piece = _WORD_CLOSES.sub("'", piece, count=1)
                quote_open = False
            beside = {"after_token": index > 0, "before_token": index < len(protected)}
            out.append(_escaped(piece, opening=index == 0, **beside))
        if index < len(protected):
            out.append(protected[index])
    if lost:
        return Alignment(None, markup=tuple(lost))
    if unread:
        return Alignment(None, unaligned=True)
    rebuilt = "".join(out).strip()
    if not _reads_as(rebuilt, protected, tokens, returned):
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
    if not _reads_as(rebuilt, (), (), returned):
        return Alignment(None, misread=True)
    return Alignment(rebuilt or None)


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
