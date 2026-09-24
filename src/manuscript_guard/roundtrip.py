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

import bisect
import difflib
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.text.fences import fenced_spans

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


def _custom_properties(existing: str | None, digest: str) -> str:
    """The custom-properties part with the source stamp added, every other property kept.

    It used to be replaced whole. Pandoc writes metadata there, and Word's Zotero plugin
    keeps a document's citation style there (ZOTERO_PREF_1, ...): the stamp erased the
    style, and Word asked for one again after every build.
    """
    ours = _CUSTOM_XML.format(name=PROPERTY, value=digest)
    if not existing:
        return ours
    kept = [
        element
        for element in _PROPERTY_ELEMENT.findall(existing)
        if f'name="{PROPERTY}"' not in element
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

#: What an identifier numbers: the blocks between blank lines, and the blank runs between
#: them, so the pieces join back into the text they came from.
_BREAK = re.compile(r"(\n\s*\n)")

# Blocks that are not paragraphs of prose. A marker in front of a fence turns it into text:
# `[]{#id}::: {#refs}` printed ":::" in the document, and the reference list it was meant to
# place never appeared. A marker in front of a code fence would do the same to the code.
_FENCE = re.compile(r"(:::|```|~~~)")
# On a later line a fenced div's `:::` counts too: `Inner paragraph.\n:::` closes the div,
# and a marked block would take the closer with it when `import` spliced the paragraph.
_FENCE_LINE = re.compile(r" {0,3}(?:`{3,}|~{3,}|:{3,})")

# Four columns of indent: an indented code block, or a list item's continuation.
_INDENTED = re.compile(r"(?: {4}| {0,3}\t)")
_BULLET = re.compile(r" {0,3}[-*+](?:[ \t]|$)")
# `1.` `1)` `(1)` `a.` `(a)` `iv.` `II.` `#.` `(@)` `@label.`, then a space, a tab or nothing.
_ENUMERATOR = re.compile(
    r" {0,3}(?P<open>\()?(?P<num>\d+|[A-Za-z]+|#|@[\w-]*)"
    r"(?(open)\)|(?P<delim>[.)]))(?P<gap>[ \t]+|$)"
)
# Pandoc's own reading of a roman numeral, which is lenient about order and strict about
# letters: `mix.` is 1009 and a list, `dim.` is a word.
_ROMAN = re.compile(
    r"m*(?:cm)?d?(?:cd)?c*(?:xc)?l?(?:xl)?x*(?:ix)?v?(?:iv)?i*"
    r"|M*(?:CM)?D?(?:CD)?C*(?:XC)?L?(?:XL)?X*(?:IX)?V?(?:IV)?I*"
)
# A block quote; a line block or a pipe table.
_QUOTE_OR_BAR = re.compile(r" {0,3}[>|]")
# A setext underline, a table's ruling, a grid border, `---`. Only these characters, and at
# least one dash or equals sign among them.
_RULE = re.compile(r"(?=[^-=\n]*[-=])[ \t]*[-=:|+][-=:|+ \t]*")
_THEMATIC = re.compile(r" {0,3}([*_])(?:[ \t]*\1){2,}[ \t]*")
# A definition (`: text` or `~ text`), which also covers a `: caption` under a table.
_DEFINITION = re.compile(r" {0,3}[:~][ \t]")
_CAPTION = re.compile(r" {0,3}[Tt]able:")
# `[^1]: a footnote` or `[label]: https://...`.
_REFERENCE = re.compile(r" {0,3}\[[^\]\n]+\]:")
# An image alone in its paragraph, which pandoc makes a figure with a caption. Loosely, from
# `![` to a closing bracket: captions nest brackets and paths hold parentheses, and a
# paragraph that opens with an image and ends on a bracket losing its identifier is the
# safe way to be wrong.
_FIGURE = re.compile(r"!\[.*[)\]}]", re.DOTALL)
# A TeX command. `\newpage` alone is a raw block, and marked it became an empty paragraph.
_TEX = re.compile(r" {0,3}\\[A-Za-z]")
# Tags pandoc reads as inline, so a paragraph may open with one and stay a paragraph. Any
# other tag at the start of a line may open a raw HTML block - `<div>`, `<table>`, `<del>` -
# and is treated as one: leaving a paragraph unmarked costs it its identifier, while marking
# an HTML block rewrites it.
_INLINE_HTML = (
    "a|abbr|b|bdi|bdo|br|cite|code|data|dfn|em|font|i|img|kbd|mark|q|s|samp|small|span|"
    "strike|strong|sub|sup|time|tt|u|var|wbr"
)
_HTML_TAG = re.compile(
    rf" {{0,3}}</?(?!(?:{_INLINE_HTML})(?![\w-]))[A-Za-z][\w-]*(?=[\s/>]|$)", re.IGNORECASE
)
# The same tags, whole, anywhere in a line. Mid-line too `text <div>x</div> more` is three
# paragraphs to pandoc. Whole, because "values <LOQ were imputed" is a sentence.
_HTML_BLOCK_TAG = re.compile(
    rf"</?(?!(?:{_INLINE_HTML})(?![\w-]))[A-Za-z][\w-]*(?:\s[^<>]*)?/?>", re.IGNORECASE
)
_TEX_ENVIRONMENT = re.compile(r"\\begin[ \t]*\{")
# A comment, a declaration, a processing instruction. Opening a block only: inside a
# paragraph a comment is inline and the paragraph survives.
_HTML_LEAD = re.compile(r" {0,3}<[!?]")


def _enumerates(line: str) -> bool:
    """Whether a line starts an ordered list, by pandoc's rules rather than by its look."""
    found = _ENUMERATOR.match(line)
    if found is None:
        return False
    num, gap = found["num"], found["gap"]
    if len(num) > 1 and num.isalpha() and _ROMAN.fullmatch(num) is None:
        return False
    if found["delim"] == "." and len(num) == 1 and num.isupper() and gap:
        # "C. difficile was isolated" is a sentence. Pandoc wants two spaces or a tab after
        # a single capital and a period, so that an initial does not start a list.
        return gap[:2] == "  " or gap[:1] == "\t"
    return True


def _opens_block(line: str) -> bool:
    """Whether a block's first line makes it something other than a paragraph."""
    return (
        _INDENTED.match(line) is not None
        or _BULLET.match(line) is not None
        or _enumerates(line)
        or _QUOTE_OR_BAR.match(line) is not None
        or _RULE.fullmatch(line) is not None
        or _THEMATIC.fullmatch(line) is not None
        or _DEFINITION.match(line) is not None
        or _CAPTION.match(line) is not None
        or _REFERENCE.match(line) is not None
        or _TEX.match(line) is not None
        or _HTML_LEAD.match(line) is not None
        or _HTML_TAG.match(line) is not None
    )


def _untagged(block: str) -> bool:
    """Whether a block is anything other than one ordinary paragraph.

    Only a paragraph can carry the marker. In front of anything else it changes what pandoc
    reads: `[]{#id}- item one` is no longer a list, and the document printed every list in
    the manuscript as one run-on paragraph with its dashes in it. The same went for block
    quotes, numbered lists, line blocks, grid tables, rules, footnote definitions and a lone
    image, which stopped being a figure.

    Some blocks survive a marker and are still refused one. `[]{#id}| a | b |` is a table
    with a bookmark in its first cell; `[]{#id}Term\\n: definition` is a definition list with
    a bookmark on the term; a paragraph followed without a blank line by a code fence or a
    `<div>` becomes a paragraph and something else. `import` reads the bookmarked Word
    paragraph and splices its text over the *whole* source block, so a co-author's edit to
    one cell would have replaced the table with that cell's text. A block qualifies only if
    pandoc reads the whole of it as one paragraph.
    """
    lines = block.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return True
    stripped = block.strip()
    if (
        stripped.startswith("#")
        # Pandoc ends a paragraph at a LaTeX environment or a block-level HTML tag wherever
        # it opens, mid-line too, and carries on with a raw block.
        or _TEX_ENVIRONMENT.search(stripped) is not None
        or _HTML_BLOCK_TAG.search(stripped) is not None
        # One paragraph to pandoc's reader and three to its Word writer, which gives display
        # math a paragraph of its own: the bookmark stayed on the words before the equation,
        # and `import` spliced them over the equation and everything after it.
        or "$$" in stripped
        or _FENCE.match(stripped) is not None
        or re.fullmatch(r"\{\{[^}]*\}\}", stripped) is not None
        or _FIGURE.fullmatch(stripped) is not None
        or _opens_block(lines[0])
    ):
        return True
    # What can end a paragraph without a blank line. At the top level a list, a quote or a
    # heading cannot - pandoc wants a blank line before those. A definition follows a
    # one-line term, so only the second line can start one.
    rest = lines[1:]
    if (rest != [] and _DEFINITION.match(rest[0]) is not None) or any(
        _RULE.fullmatch(line) is not None
        or _FENCE_LINE.match(line) is not None
        or _HTML_TAG.match(line) is not None
        for line in rest
    ):
        return True
    # Inside a list item, which is what an indented block is, a nested list or the list's
    # next item needs no blank line. `  Matched on:\n  - age\n- Drugs were mapped.` is a
    # paragraph and two list items, and `import` spliced the items away with the paragraph.
    return lines[0][:1] == " " and any(
        _BULLET.match(line.lstrip()) is not None or _enumerates(line.lstrip()) for line in rest
    )


# Raw content pandoc carries across blank lines without reading it as markdown, wherever it
# opens: an HTML comment, a LaTeX environment (`\begin {table}` with a space included), and
# an HTML element whose content is verbatim.
_VERBATIM = "(?i:pre|script|style|textarea)"
_RAW_OPEN = re.compile(
    rf"<!--|\\begin[ \t]*\{{[^{{}}\n]+\}}|<(?P<tag>{_VERBATIM})(?=[\s>]|$)"
)
_RAW_CLOSE = re.compile(
    rf"(?P<comment>-->)|\\(?P<tex>begin|end)[ \t]*\{{(?P<env>[^{{}}\n]+)\}}"
    rf"|</(?P<tag>{_VERBATIM})(?=[\s>]|$)"
)


class _Closers:
    """Where each piece of raw content closes, found in one pass over the text.

    Searching from each block to the end of the text for its closer was quadratic: 80,000
    paragraphs that each left a comment open took 26 seconds, and so did 80,000 LaTeX
    environments with different names, in code `check` reaches through G13. Every closer is
    indexed once instead, and a LaTeX environment is matched to its own `\\end` the way
    pandoc matches it, nested environments of the same name included.
    """

    def __init__(self, text: str) -> None:
        self._comments: list[int] = []
        self._tags: dict[str, list[int]] = {}
        self._environments: dict[int, int] = {}
        open_environments: dict[str, list[int]] = {}
        for found in _RAW_CLOSE.finditer(text):
            if found["comment"]:
                self._comments.append(found.end())
            elif found["tag"]:
                self._tags.setdefault(found["tag"].lower(), []).append(found.end())
            elif found["tex"] == "begin":
                open_environments.setdefault(found["env"], []).append(found.start())
            elif open_environments.get(found["env"]):
                self._environments[open_environments[found["env"]].pop()] = found.end()

    def end_of(self, opened: re.Match[str]) -> int:
        """Where the raw content `opened` starts ends, or -1 if it never closes."""
        if opened["tag"]:
            ends = self._tags.get(opened["tag"].lower(), [])
        elif opened.group(0) == "<!--":
            ends = self._comments
        else:
            return self._environments.get(opened.start(), -1)
        at = bisect.bisect_right(ends, opened.end())
        return ends[at] if at < len(ends) else -1


def _raw_end(text: str, start: int, end: int, closers: _Closers) -> int:
    """Where raw content opened in `text[start:end]` ends if it runs past the block, else 0.

    The blocks it swallows are not paragraphs, and a marker in one names a paragraph no
    document contains. The block that opens it is not a whole paragraph either. An opener
    that never closes hides nothing: pandoc reads it as text.
    """
    position = start
    while (opened := _RAW_OPEN.search(text, position, end)) is not None:
        closed = closers.end_of(opened)
        if closed > end:
            return closed
        position = opened.end() if closed < 0 else closed
    return 0


def _blocks(text: str) -> Iterator[tuple[int, str, bool]]:
    """Every piece of `text` in order, with its index and whether it gets an identifier.

    `tag` and `tagged_paragraphs` both iterate this rather than splitting for themselves, so
    the identifier a document carries and the one `import` looks up are computed by the same
    code and cannot drift apart.

    Most of the decision is `_untagged`, one block at a time. What it cannot see is a block
    that is inside something opened earlier: the second half of a fenced code block with a
    blank line in it, or of a comment. A marker there would print inside the code, or name a
    paragraph that reaches no document.
    """
    fences = iter(fenced_spans(text))
    fence = next(fences, None)
    closers = _Closers(text)
    hidden = 0
    cursor = 0
    for index, piece in enumerate(_BREAK.split(text)):
        origin = cursor
        start = cursor + len(piece) - len(piece.lstrip())
        end = cursor + len(piece)
        cursor = end
        while fence is not None and fence.end <= start:
            fence = next(fences, None)
        inside = fence is not None and fence.start <= start
        if inside or start < hidden:
            # What hid this block can end inside it, and raw content opened after that point
            # swallows the blocks that follow just the same.
            resume = max(fence.end if inside else 0, hidden)
            if resume < end:
                hidden = max(hidden, _raw_end(text, resume, end, closers))
            yield index, piece, False
            continue
        # From the block's own first character, indentation included: `  <pre>` opens a
        # line, and a search starting at the `<` cannot see that it does.
        runs_on = _raw_end(text, origin, end, closers)
        hidden = max(hidden, runs_on)
        yield index, piece, not (runs_on or _untagged(piece))


def tag(text: str, relative: str) -> str:
    """Give every ordinary paragraph of one source file an invisible identifier.

    Headings are skipped: `[]{#id}# Methods` is not a heading. So are lists, quotes, tables,
    fenced divs, code, and paragraphs that are nothing but a placeholder, because those
    become a table or a figure rather than a paragraph. `_untagged` says why each one.
    """
    slug = paragraph_slug(relative)
    out = []
    for index, piece, marked in _blocks(text):
        if not marked:
            out.append(piece)
            continue
        stripped = piece.strip()
        marker = _TAG.format(slug=slug, index=index)
        out.append(piece.replace(stripped, f"[]{{#{marker}}}{stripped}", 1))
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
        for index, para, marked in _blocks(text):
            stripped = para.strip()
            start = cursor + (len(para) - len(para.lstrip())) if stripped else cursor
            cursor += len(para)
            if not marked:
                continue
            found[_TAG.format(slug=slug, index=index)] = (path, stripped, start)
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
