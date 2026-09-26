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

import bisect
import difflib
import html
import itertools
import re
import unicodedata
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.docxtext import TOKEN, spaced
from manuscript_guard.text.fences import fenced_spans
from manuscript_guard.text.placeholders import PLACEHOLDER, VALUE_NAMESPACES

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
# A definition (`: text` or `~ text`, or the marker alone on its line), which also covers a
# `: caption` under a table.
_DEFINITION = re.compile(r" {0,3}[:~](?:[ \t]|$)")
# A table's caption: `Table:`, `table:`, or a colon alone, which pandoc takes for one beside a
# table. One block cannot tell whether a table is beside it, so any of them is a caption.
_CAPTION = re.compile(r" {0,3}(?:[Tt]able)?:")
# `[^1]: a footnote` or `[label]: https://...`.
_REFERENCE = re.compile(r" {0,3}\[[^\]\n]+\]:")
# An image alone in its paragraph, which pandoc makes a figure with a caption. Loosely, from
# `![` to a closing bracket: captions nest brackets and paths hold parentheses, and a
# paragraph that opens with an image and ends on a bracket losing its identifier is the
# safe way to be wrong.
_FIGURE = re.compile(r"!\[.*[)\]}]", re.DOTALL)
# A TeX command. `\newpage` alone is a raw block, and marked it became an empty paragraph.
_TEX = re.compile(r" {0,3}\\[A-Za-z]")
# The tags pandoc's reader takes for a block: its `blockHtmlTags`, `blockDocBookTags` and
# `epubTags` (Text/Pandoc/Readers/HTML/TagCategories.hs, 3.9.0.2), taken from its source and
# checked by `test_a_tag_ends_a_paragraph_exactly_when_pandoc_ends_it`, which asks pandoc about
# each. These end a paragraph wherever they stand: `text <div>x</div> more` is three blocks.
# Pandoc reads DocBook in markdown, so `<note>` and `<example>` are blocks as much as `<div>`;
# the first version of this list held HTML's own and marked a table row under `<example>`.
_BLOCK_HTML = (
    "address|article|aside|blockquote|body|canvas|caption|center|col|colgroup|dd|details|dir|"
    "div|dl|dt|fieldset|figcaption|figure|footer|form|frameset|h[1-6]|head|header|hgroup|hr|"
    "html|isindex|li|main|menu|meta|nav|noframes|ol|output|p|pre|script|section|summary|table|"
    "tbody|td|textarea|tfoot|th|thead|title|tr|ul|"
    "bibliolist|calloutlist|caution|classsynopsis|cmdsynopsis|epigraph|equation|example|"
    "formalpara|funcsynopsis|glosslist|important|informalequation|informalexample|"
    "informalfigure|informaltable|itemizedlist|literallayout|mediaobject|msgset|note|"
    "orderedlist|para|procedure|programlisting|programlistingco|qandaset|screen|screenco|"
    "screenshot|segmentedlist|sidebar|simpara|simplelist|synopsis|task|tip|variablelist|warning|"
    "case|default|switch"
)
# A raw HTML block only where a block starts, inline after text: pandoc's
# `eitherBlockOrInline`, less `script`, which it also lists as a block and splits at mid-line,
# and with `style`, which it lists as a block and reads inline mid-line all the same.
_OPENING_HTML = (
    "applet|area|audio|button|del|embed|iframe|ins|map|noscript|object|progress|source|style|"
    "svg|track|video"
)
# A tag pandoc does not know is inline wherever it stands, so "Concentrations <LLOQ and
# >ULOQ were excluded." is one paragraph. Anything but these used to be taken for a block,
# and such a paragraph went without an identifier. `_HTML_TAG` is the first line of a block,
# where either list opens one; `_HTML_LINE` a later line, where only a block tag does.
_HTML_TAG = re.compile(
    rf" {{0,3}}</?(?:{_BLOCK_HTML}|{_OPENING_HTML})(?=[\s/>]|$)", re.IGNORECASE
)
_HTML_LINE = re.compile(rf" {{0,3}}</?(?:{_BLOCK_HTML})(?=[\s/>]|$)", re.IGNORECASE)
# A block tag, whole, anywhere in a line - and not escaped: `\<div>` is text to pandoc, which
# is how `import` writes a `<div>` a co-author typed. `\\<div>` is a backslash and a tag.
_HTML_BLOCK_TAG = re.compile(
    rf"(?<!\\)(?:\\\\)*</?(?:{_BLOCK_HTML})(?![\w-])(?:\s[^<>]*)?/?>", re.IGNORECASE
)
_TEX_ENVIRONMENT = re.compile(r"\\begin[ \t]*\{")
# A brace not escaped: after an even number of backslashes, none included.
_UNESCAPED_OPEN = re.compile(r"(?<!\\)(?:\\\\)*\{")
_UNESCAPED_CLOSE = re.compile(r"(?<!\\)(?:\\\\)*\}")


def _brace_group_runs_on(stripped: str) -> bool:
    """Whether a block holds half of a brace group: an open brace left unclosed, the head of
    a group that runs on past the blank line, or a close brace nothing opened, its tail.

    Only an unescaped brace counts, either way: an escaped one is text. Counting every
    brace refused the `\\{&lbrace;` `import` writes before a binding, three against two. And
    `import` escapes both braces a co-author types, so `{{table.x}}` typed in Word comes back
    `\\{\\{table.x\\}\\}`, none against none. A close brace used to go back bare and was a
    tail with nothing opened: `The ratio } was...` merged and went without an identifier.
    """
    return len(_UNESCAPED_OPEN.findall(stripped)) != len(_UNESCAPED_CLOSE.findall(stripped))


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
    value = PLACEHOLDER.fullmatch(stripped)
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
        # A brace group left open runs on across the blank line when it is raw TeX -
        # `\footnote{In one analysis.\n\nAnd in another.}` is one paragraph - so neither half
        # is the paragraph the bookmark lands in.
        or _brace_group_runs_on(stripped)
        or _FENCE.match(stripped) is not None
        # A lone table or figure, or a misspelt placeholder. Not a lone value, which is a
        # paragraph printing a number: skipped, a paragraph cut down to its number in Word
        # lost its identifier, and its next edit was dropped with "nothing came back".
        or (
            re.fullmatch(r"\{\{[^}]*\}\}", stripped) is not None
            and not (value and value.group("ns") in VALUE_NAMESPACES)
        )
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
        or _HTML_LINE.match(line) is not None
        for line in rest
    ):
        return True
    # Inside a list item, which is what an indented block is, a nested list, the list's next
    # item or a definition needs no blank line. `  Matched on:\n  - age\n- Drugs were
    # mapped.` is a paragraph and two list items, and `import` spliced the items away with
    # the paragraph.
    return lines[0][:1] == " " and any(
        _BULLET.match(line.lstrip()) is not None
        or _enumerates(line.lstrip())
        or _DEFINITION.match(line.lstrip()) is not None
        for line in rest
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


# A multiline table's rows are separated by blank lines, and a YAML block in the body may
# hold them too: both open on a line of dashes and close on one (or on `...`, for YAML).
# Any line of dashes ends a table, however short; see `_opens_table` for what opens one.
_DASH_GROUPS = re.compile(r" {0,3}-+(?:[ \t]+-+)*[ \t]*")
# A YAML block in the body: pandoc tries every `---` in column 0 with text straight under
# it, up to the first `---` or `...` in column 0, wherever in a block that falls. Read to
# the end without a limit: every attempt opens on an exact `---`, which is itself a stop
# line, so no two attempts read the same text.
_YAML_OPEN = re.compile(r"---[ \t]*")
_YAML_STOP = re.compile(r"(?:---|\.\.\.)[ \t]*")
_MAPPING, _OTHER = "mapping", "other"
_YAML_DEPTH = 100
_SEQUENCE_ITEMS = re.compile(r"(?:[ \t]*-(?:[ \t]+|$))+")


def _nesting(text: str) -> int:
    """How deep YAML's flow brackets or block sequences nest, read without parsing."""
    depth = deepest = 0
    for char in text:
        if char in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif char in "]}":
            depth = max(depth - 1, 0)
    for line in text.split("\n"):
        items = _SEQUENCE_ITEMS.match(line)
        if items:
            deepest = max(deepest, items.group(0).count("-"))
    return deepest


def _yaml_kind(text: str) -> str:
    """`_MAPPING` if pandoc keeps this as metadata; `_OTHER` otherwise.

    Composed, not loaded: constructing values raised on YAML pandoc accepts -
    `date: 2026-02-30` is a ValueError to PyYAML - and nothing here needs the values. With
    the pure-Python loader, not the C one: thousands of nesting levels overflowed the C
    stack and took the interpreter down, where Python's recursion limit raises instead.
    Nothing at all, a comment alone or a null, is empty metadata to pandoc, not something
    it gives up on.
    """
    import yaml

    if _nesting(text) > _YAML_DEPTH:
        # Composing thousands of levels ran into the recursion limit only after seconds,
        # once per opener. Too deep to be anyone's metadata; left unmarked all the same.
        return _OTHER
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except Exception:  # noqa: BLE001 - any failure to parse is "not metadata"
        return _OTHER
    empty = node is None or (
        isinstance(node, yaml.ScalarNode) and node.tag == "tag:yaml.org,2002:null"
    )
    return _MAPPING if empty or isinstance(node, yaml.MappingNode) else _OTHER


def _yaml_stop(pieces: list[str], index: int) -> tuple[int, bool, str] | None:
    """Where a YAML block tried at `pieces[index]` stops, whether the stop line is the first
    line of its block, and what it holds.

    Pandoc keeps a mapping as metadata. Anything else it gives up on quietly and reads as a
    rule, a table or prose - but only while nothing in it breaks the YAML: a marker at the
    start of a line inside it turns that fallback into a parse error, and the build fails.
    So whatever pandoc tries as YAML is left unmarked, mapping or not.
    """
    lines = pieces[index].split("\n")
    # A file's first block can open on blank lines, which pandoc skips.
    while lines and not lines[0].strip():
        lines.pop(0)
    if not (lines and _YAML_OPEN.fullmatch(lines[0]) and len(lines) > 1 and lines[1].strip()):
        return None
    body: list[str] = []
    for at in range(index, len(pieces)):
        chunk = lines[1:] if at == index else pieces[at].split("\n")
        for position, line in enumerate(chunk):
            if _YAML_STOP.fullmatch(line):
                # Only a `---` can open anything; a block opening on `...` is prose, and
                # marked, the marker removed the stop pandoc was reading to.
                opens = at != index and position == 0 and line.startswith("---")
                return at, opens, _yaml_kind("\n".join(body))
            body.append(line)
    return None


def _opens_table(line: str) -> bool:
    """A line of dashes that can open a multiline table. `-` and `- -` are list items to
    pandoc, which it tries first; a line with a first run of two dashes, or three dashes in
    all - a first column one dash wide - is not."""
    if _DASH_GROUPS.fullmatch(line) is None:
        return False
    return len(line.strip().split()[0]) >= 2 or line.count("-") >= 3


# Lines after which pandoc starts a new block whatever the next line holds, so a table can
# open straight under them: a setext `=` underline, a grid table's border, a line opening on
# `|`, `\end{...}`, a comment's closing `-->` and a YAML block's closing `...`. Fences, pipe
# rows and whole lines of block-level HTML are tested in `_ends_line`. Under prose, a list
# item, a quote, a definition, a caption, a TeX command, an image or a one-line reference
# definition, pandoc 3.9 opens no table: over a line of dashes, most of those are the header
# of a simple table, whose rows end at the next blank line.
_ENDS_LINE = re.compile(
    r" {0,3}(?:=+[ \t]*|\+(?:[-=:]+\+)+[ \t]*|\|.*|\\end[ \t]*\{.*)|\.\.\.[ \t]*"
    r"|(?:(?!<!--).)*-->[ \t]*"
)
# A heading or a whole-line comment ends a block too, but over a single run of dashes pandoc
# reads it as the text of a setext heading, and no table opens.
_HEADING_OR_COMMENT = re.compile(r" {0,3}(?:#+(?:[ \t].*)?|<[!?].*>[ \t]*)")
# A pipe table's separator row. The rows under it end a block without a leading `|` too.
_PIPE_SEPARATOR = re.compile(r" {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)+\|?[ \t]*")


def _ends_line(line: str, opener: str, piped: bool) -> bool:
    """Whether a table can open on `opener`, straight under `line`. `piped` says a pipe
    table's separator row sits above `line` in the block."""
    if _HEADING_OR_COMMENT.fullmatch(line):
        return len(opener.split()) > 1
    if _ENDS_LINE.fullmatch(line) or _FENCE_LINE.match(line) or (piped and "|" in line):
        return True
    # Either list: a line holding only `<del>` that starts a block is a raw block, and a table
    # opens under it. Asked only of block tags, this missed the table and marked its row.
    return _HTML_TAG.match(line) is not None and line.rstrip().endswith(">")


@dataclass(frozen=True)
class _Row:
    """One non-blank line of a block, as the table reader sees it."""

    block: int
    dashes: bool
    #: A line that can open a table, with text straight under it. A table and a YAML block
    #: both need that text, so a line of dashes with a blank line under it is only a rule.
    opens: bool
    #: The last line of its block, with a blank line under it.
    ends_block: bool
    #: The last line of its block, with a line pandoc does not call blank under it.
    joined: bool


class _Ruled:
    """Tables and YAML blocks that run across blank lines: where each one ends.

    Without this the middle rows of a three-row multiline table were ordinary-looking
    blocks, and a marker printed into a cell. Asked lazily, by `_blocks`, only of a block
    that is not already inside code, a comment or an earlier span - an example `---` inside
    a code fence is not an opener, and treated as one it swallowed the real YAML after it.
    """

    def __init__(self, pieces: list[str]) -> None:
        self._pieces = pieces
        self._rows: list[_Row] = []
        self._first_row: dict[int, int] = {}
        # Rows that open a table mid-block, straight under a line that ends a block.
        self._inner: dict[int, list[int]] = {}
        for index in range(0, len(pieces), 2):
            lines = [line for line in pieces[index].split("\n") if line.strip()]
            if not lines:
                continue
            # A "blank" line holding a no-break space straight under the block is text to
            # pandoc, however the text was split.
            joined = index + 1 < len(pieces) and (
                re.match(r"\n[ \t]*[^ \t\n]", pieces[index + 1]) is not None
            )
            self._first_row[index] = len(self._rows)
            for at, line in enumerate(lines):
                ends_block = at == len(lines) - 1 and not joined
                dashes = _DASH_GROUPS.fullmatch(line) is not None
                self._rows.append(
                    _Row(
                        block=index,
                        dashes=dashes,
                        opens=dashes and not ends_block and _opens_table(line),
                        ends_block=ends_block,
                        joined=at == len(lines) - 1 and joined,
                    )
                )
            self._inner[index] = self._inner_openers(lines, self._first_row[index])
        # Where the table read from each opening row ends, filled in as asked. Tables that
        # open straight under one another share an end, so each chain is walked once.
        self._ends: dict[int, int | None] = {}
        # The next line of dashes after each row, for finding where a table ends.
        self._next_dashes: list[int | None] = [None] * len(self._rows)
        following: int | None = None
        for row in range(len(self._rows) - 1, -1, -1):
            self._next_dashes[row] = following
            if self._rows[row].dashes:
                following = row
        self._opens = {
            block
            for block, row in self._first_row.items()
            if self._rows[row].opens and not self._closed_in(block, row)
        }

    def _inner_openers(self, lines: list[str], first: int) -> list[int]:
        """The rows of one block, after its first, where pandoc may open a table: straight
        under a line that always ends a block, or under a setext underline of dashes. Only
        the first line of a block was asked, and a table under a `::: {#tbl-a}` fence or a
        heading printed a marker into its rows. Wrong here, a table is followed that pandoc
        does not read, and paragraphs go unmarked, which corrupts nothing."""
        rows = self._rows
        found: list[int] = []
        piped = False
        for at in range(1, len(lines)):
            row, above = first + at, lines[at - 1]
            if rows[row].opens and (
                _ends_line(above, lines[at], piped)
                or (at >= 2 and rows[row - 1].dashes and not rows[row - 2].dashes)
            ):
                found.append(row)
            piped = piped or _PIPE_SEPARATOR.fullmatch(above) is not None
        return found

    def _end_row(self, start: int) -> int | None:
        """The row where the table pandoc reads from the opening line at row `start` ends.

        Pandoc tries a headed multiline table first. Its header runs down to the next line
        of dashes, and when there is a header above that line and text straight under it,
        the rows run on to the line of dashes after. A line holding only a no-break space
        is a header line too. Otherwise the table is headless and ends on the first line of
        dashes. Where a line that can open a table follows the end straight away, another
        table begins there. Ending always on the first line of dashes printed a marker into
        the rows of a headed table.

        Each row a walk passes is remembered with the walk's end, so a chain is walked once.
        What is remembered holds for a row however it is reached: a table opening straight
        under another that never finds its closing line leaves the first table's end,
        `row - 1`. Only a table asked about directly can find no line of dashes after it and
        be no table at all, and that is answered before anything is remembered.
        """
        if self._next_dashes[start] is None:
            return None
        rows = self._rows
        walked: list[int] = []
        end = start - 1
        while start not in self._ends:
            walked.append(start)
            first = self._next_dashes[start]
            if first is None:
                break
            headed = first > start + 1 or rows[start].joined
            under = rows[first].joined or (
                not rows[first].ends_block
                and first + 1 < len(rows)
                and rows[first + 1].block == rows[first].block
                and not rows[first + 1].dashes
            )
            end = first
            if headed and under and self._next_dashes[first] is not None:
                end = self._next_dashes[first]
            after = end + 1
            if not (
                after < len(rows)
                and rows[after].block == rows[end].block
                and rows[after].opens
            ):
                break
            start = after
        else:
            end = self._ends[start]
        for row in walked:
            self._ends[row] = end
        return end

    def _closed_in(self, block: int, row: int) -> bool:
        """Whether the table read from the block's opening line ends inside the block."""
        end = self._end_row(row)
        return end is not None and self._rows[end].block == block

    def _table_end(self, index: int) -> int | None:
        """The block where the table pandoc reads from the rule opening `index` ends."""
        end = self._end_row(self._first_row[index])
        return None if end is None else self._rows[end].block

    def end(self, index: int) -> int | None:
        """The block a span opened in `index` ends in, or None if it opens none: from the
        block's first line, or from a table opening further down it."""
        ends = [self._opened_end(index), self.inner_end(index)]
        found = [end for end in ends if end is not None]
        return max(found) if found else None

    def inner_end(self, index: int) -> int | None:
        """The last block reached by a table opening mid-block in `index`, if past it."""
        ends = [self._end_row(row) for row in self._inner.get(index, ())]
        blocks = [self._rows[end].block for end in ends if end is not None]
        later = [block for block in blocks if block > index]
        return max(later) if later else None

    def _opened_end(self, index: int) -> int | None:
        """The block a span opened on the first line of `index` ends in.

        A table runs to a line of dashes: a row that happens to read `...` is a row. A
        `---` pandoc tries as YAML is hidden up to where the YAML stops; a mapping ends
        there, and anything else pandoc reads again as a table from the same `---`.
        """
        if index not in self._opens:
            return None
        rule = self._table_end(index)
        tried = _yaml_stop(self._pieces, index)
        if tried is None:
            return rule
        stop, opens_block, kind = tried
        if kind == _MAPPING:
            return stop if stop != index else None
        # Given up on, the tried text must stay unbroken up to the stop, and pandoc reads a
        # table from the same `---` instead. When that table ends on the stop's own `---`, or
        # past it, the line is part of the table. When it ended earlier, the stop's `---` is
        # pandoc's next opener to try, and it has to be asked.
        tried_to = stop - 2 if opens_block and rule is not None and rule < stop else stop
        ends = [end for end in (tried_to, rule) if end is not None and end > index]
        return max(ends) if ends else None


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
    pieces = _BREAK.split(text)
    # A "blank" line holding a non-breaking space, an em or ideographic space or a form feed
    # separates blocks for the numbering and not for pandoc, which reads one paragraph
    # across it. Marked, the first half's bookmark sat on the whole joined paragraph and
    # `import` spliced it over the first half, writing the second half twice. Both halves go
    # unmarked instead: renumbering would move every identifier after them.
    joined = [
        index % 2 == 1 and re.search(r"[^ \t\n]", piece) is not None
        for index, piece in enumerate(pieces)
    ]
    ruled = _Ruled(pieces)
    ends = list(itertools.accumulate(len(piece) for piece in pieces))
    for index, piece in enumerate(pieces):
        apart = not (joined[max(index - 1, 0)] or joined[min(index + 1, len(pieces) - 1)])
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
            if resume == end == hidden:
                # The block where a table or YAML span ends: something can open after the
                # span in it. Read from the block's start, which only hides more, or from
                # where its code closes; missed, a second table's rows were marked.
                if not inside:
                    resume = start
                elif fence.end < end:
                    resume = fence.end
            if resume < end:
                hidden = max(hidden, _raw_end(text, resume, end, closers))
                # A table can open in it too and is followed as in any block: on its first
                # line or further down, or only further down when the block starts inside
                # code - its first line is code. A span pandoc does not have, from a line
                # taken for an opener, ran on to a real table's header underline and ended
                # there; read only further down, the block missed the real table's own top
                # rule, and its rows were marked. What seems to open inside the span, or in
                # the code above the close, only hides more.
                table = ruled.inner_end(index) if inside else ruled.end(index)
                if table is not None:
                    hidden = max(hidden, ends[table])
            yield index, piece, False
            continue
        # From the block's own first character, indentation included: `  <pre>` opens a
        # line, and a search starting at the `<` cannot see that it does.
        runs_on = _raw_end(text, origin, end, closers)
        closer = ruled.end(index)
        if closer is not None:
            runs_on = max(runs_on, ends[closer])
        hidden = max(hidden, runs_on)
        yield index, piece, apart and not (runs_on or _untagged(piece))


def tag(text: str, relative: str, *, mark: bool = False) -> str:
    """Give every ordinary paragraph of one source file an invisible identifier.

    Headings are skipped: `[]{#id}# Methods` is not a heading. So are lists, quotes, tables,
    fenced divs, code, and paragraphs that are nothing but a table or figure placeholder,
    because those become a table or a figure rather than a paragraph. A misspelt
    placeholder standing alone is skipped with them; `check` refuses it. `_untagged` says
    why each one.

    With `mark`, every binding and citation in a tagged paragraph gets a Word bookmark
    around it as well, written as raw OpenXML that pandoc passes through untouched. Only the
    build `import` compares with is marked, and it is what tells `align` exactly where each
    token's rendering begins and ends. It was a `[token]{#id}` span first, and a span adds
    brackets: beside an unbalanced one, pandoc paired them differently, the text still read
    the same, and the extent lost its first character - so a rewording wrote a `[` twice.
    """
    slug = paragraph_slug(relative)
    out = []
    counter = iter(range(1_000_000))
    for index, piece, marked in _blocks(text):
        if not marked:
            out.append(piece)
            continue
        stripped = piece.strip()
        marker = _TAG.format(slug=slug, index=index)
        body = stripped
        if mark:
            code = [m.span() for m in _SCAN.finditer(body) if m.lastgroup in ("code", "coded")]
            spans = [t.span() for t in _tokens(body) if _markable(body, t.start(), code)]
            bookmarked = [
                (_APART if body[a - 1 : a] == "`" else "") + _bookmarked(body[a:b], slug, counter)
                for a, b in spans
            ]
            for (a, b), replacement in reversed(list(zip(spans, bookmarked, strict=True))):
                body = body[:a] + replacement + body[b:]
        out.append(piece.replace(stripped, f"[]{{#{marker}}}{body}", 1))
    return "".join(out)


# A bookmark is raw inline code, and its opening backtick has to open it. Straight after a
# code span's closing backtick it joined that run instead: pandoc read the code and the
# bookmark as one raw span and wrote `age<65` into the document as XML, so the marked build
# was not a readable .docx and `import` stopped for the whole manuscript. An empty comment
# keeps the two apart, and the Word writer drops it.
_APART = "<!-- -->"


def _markable(body: str, start: int, code: list[tuple[int, int]]) -> bool:
    """Whether the token at `start` can carry bookmarks.

    Not inside code, where pandoc reads no raw span, and not after an odd run of
    backslashes, which would escape the bookmark's backtick. Unmarked, the token has no
    extent, and a rewording of its paragraph is refused, as one whose extents cannot be read
    is.
    """
    if any(a < start < b for a, b in code):
        return False
    before = body[:start]
    return (len(before) - len(before.rstrip("\\"))) % 2 == 0


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
        for index, para, marked in _blocks(text):
            stripped = para.strip()
            start = cursor + (len(para) - len(para.lstrip())) if stripped else cursor
            cursor += len(para)
            if not marked:
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
#: left those in the prose, and `@key::a` is the key `key` to pandoc. A `:` or `/` before a
#: `/` continues it too, as in a URL: `@key//` is the key `key/`.
_KEY = r"-?@(?:\{[^{}\s]+\}|\w(?:\w|[:.#$%&+?<>~/-](?=\w)|[:/](?=/))*)"
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

#: Code keeps literal what pandoc typesets in prose: dashes, an ellipsis, quotes. Rebuilt
#: from Word's text, code is prose, and `--offline` printed as "–offline", `<!--` as "<!–"
#: and `"exact"` with curly quotes. Escaping them would print Word's text as it is, and
#: would print a `--` a co-author typed as `--` too, where pandoc makes it the dash they
#: meant; so an edited stretch holding such code is refused instead.
_TYPESET_IN_CODE = "code with `--`, `...` or a quote in it"
_TYPESETS = re.compile(r"--|\.\.\.|['\"]")


def _uncarried(names: Sequence[str], edited: str) -> tuple[str, ...]:
    """What an edited stretch held that Word's text cannot carry back, as `edited` came back.

    Code pandoc would typeset counts only while Word's text still holds something to
    typeset: an edit that deleted the code was refused, naming code Word no longer showed.
    """
    return tuple(
        name for name in names if name != _TYPESET_IN_CODE or _TYPESETS.search(edited)
    )

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


def _unchanged(was: str, now: str) -> bool:
    """Whether a stretch came back as it was rendered, spaces kept at the ends.

    Both are Word's text, and Word changes no character nobody typed, so every difference is
    an edit. Quotes were compared as quotes at first, and a co-author turning ‘em the right
    way round left a stretch that read as untouched: the correction was dropped, and import
    said nothing had come back. What is written keeps Word's own quotes too: straightening
    them for pandoc to curl again turned „ein Signal“ into “ein Signal”.
    """
    return _spaced(was) == _spaced(now)


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
        elif kind == "code" and _TYPESETS.search(m.group("code_text")):
            marks.append((start, end, _TYPESET_IN_CODE))

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


#: A paragraph that opens like a block by its first character: a heading, a block quote, a
#: line block, a bullet - a `-` or `+` alone is one too. A numbered list, a caption and a
#: definition are judged by `_opened`, with the tagger's own reading of them.
_OPENER = re.compile(r"(?P<mark>[#>|])|(?P<bullet>[-+])(?=\s|$)")


def _opened(text: str, whole: bool = True) -> str:
    """Word's text escaped where it would open a paragraph as something else. `whole` says
    the text is the paragraph's last stretch, with no token after it to make it more.

    The writer used to keep its own short list of openers, and the tagger read blocks by
    pandoc's rules: `B) the ratio was...` merged as typed, pandoc made a list of it at the
    next build, `tag` gave it no identifier, and its next edit in Word was dropped with
    nothing reported. So a numbered list is judged here by the same `_enumerates` that
    `tag` asks, which knows "E. coli" is a sentence and "IV. The" is not, and a caption by
    the same `_CAPTION`, which takes any opening colon for one: beside a table or under a
    paragraph a bare `:` makes a caption or a definition. What they would read as a block
    gets one backslash, and pandoc prints it as typed. A paragraph that is nothing but a
    rule, `---` or `===`, has every dash and equals sign escaped: with the first alone,
    `\\---` printed a hyphen and an en dash. A stretch with a token after it is no rule.
    """
    if block := _OPENER.match(text):
        at = next(block.start(g) for g in ("mark", "bullet") if block.group(g))
        return text[:at] + "\\" + text[at:]
    # Judged as it may end up: `_respaced` turns pandoc's no-break space after an
    # abbreviation into a plain one after this, and "p." then "4" opens a list.
    first = text.split("\n", 1)[0].replace(_NBSP, " ")
    if (found := _ENUMERATOR.match(first)) and _enumerates(first):
        at = found.start("open") if found.group("open") else found.start("delim")
        return text[:at] + "\\" + text[at:]
    if found := _CAPTION.match(first):
        return text[: found.end() - 1] + "\\" + text[found.end() - 1 :]
    if whole and _RULE.fullmatch(first):
        line = text.split("\n", 1)[0]
        return re.sub(r"[-=]", lambda m: "\\" + m.group(0), line) + text[len(line) :]
    return text

#: A `<` pandoc can start a tag with: one before a letter of any script, or before the `/`,
#: `!` or `?` of a closing tag, a comment or a processing instruction. `<1b`, `< b` and `<_b`
#: print as typed; `<µg` opened a tag when only an ASCII letter was looked for. `[^\W\d_]`
#: also takes a numeral that is not a digit, `²` or `½`, on which pandoc opens nothing; that
#: costs a backslash, not a word.
_TAG_OPEN = r"<(?=[^\W\d_]|[/!?])"
_TAG_OPENS = re.compile(_TAG_OPEN)

#: Inside a tag, pandoc's whitespace is ASCII's. A no-break space Word's text holds is part of
#: an attribute's value: `dose=5 mg\>1`, with one in "5 mg", closed the tag when Python's `\s`
#: was taken for pandoc's. Pandoc's own after "e.g." is written back as a plain space, which
#: ends the value; it is read here as it came back, which only errs safe.
_TAG_SPACE = "[ \t\n\r\f]"
#: An attribute's value about to begin: an `=` and nothing after it but spaces.
_VALUE = re.compile(rf"={_TAG_SPACE}*\Z")
#: An unquoted attribute value running up to a `>`: an `=`, any spaces, then no space. Inside
#: a tag pandoc takes a backslash there for part of the value, so `=\>` and `HR=2.1\>1`
#: closed the tag the backslash was meant to keep shut.
_UNQUOTED = re.compile(rf"={_TAG_SPACE}*[^ \t\n\r\f]*\Z")
#: What a would-be tag can be closed or carried on by.
_TAG_PUNCTUATION = re.compile("[>'\"]")
#: A `<` Word typed, set aside where it is escaped and so opens nothing; see `_opens_value`.
_SET_ASIDE = "\x00"


def _opens_value(shown_before: str, bare_before: str | None, text: str, at: int) -> bool:
    """Whether a straight quote at `at` in Word's `text` would open a quoted attribute
    value: straight after an `=`, once a `<` of the source's or a value's stands before it.

    `bare_before` is `shown_before` with each `<` Word typed set aside, or None to count
    every `<` in `shown_before`; those in `text` are Word's and set aside either way. Word's
    own is escaped and opens nothing, and a quote escaped for it printed
    straight where pandoc had curled it, `family='binomial'` coming back as `'binomial’`. A
    kept stretch is read as Word shows it, so a `<` the source escaped counts too: that
    costs a straight quote, never a word.
    """
    where = len(shown_before) + at
    before = shown_before if bare_before is None else bare_before
    bare = _TAG_OPENS.search(before + text.replace("<", _SET_ASIDE))
    if bare is None or bare.start() >= where:
        return False
    return _VALUE.search(shown_before + text, 0, where) is not None


def _closers(shown_before: str, text: str, bare_before: str | None = None) -> list[str]:
    """How to write each `>`, `'` and `"` of Word's `text`, read after `shown_before`.

    A `>` is bare where no `<` that can open a tag stands before it. After one it is `\\>`,
    or `&gt;` at the end of an unquoted attribute value, where a backslash would be read as
    part of the value: an entity closes no tag anywhere, but G2 reads `\\>` as a threshold's
    `>` and not `&gt;`. A straight quote straight after an `=` opened a quoted value, which
    ran on past the paragraph's end, and the tag closed at a `>` in the next one. Escaped
    where `_opens_value` says it would, it opens nothing, and prints straight.
    """
    shown = shown_before + text
    opens = _TAG_OPENS.search(shown)
    out = []
    for found in _TAG_PUNCTUATION.finditer(text):
        char, at = found.group(), len(shown_before) + found.start()
        if char != ">":
            quoted = _opens_value(shown_before, bare_before, text, found.start())
            out.append("\\" + char if quoted else char)
        elif opens is None or opens.start() >= at:
            out.append(">")
        elif _UNQUOTED.search(shown, 0, at):
            out.append("&gt;")
        else:
            out.append("\\>")
    return out

#: Every character Markdown can read as the start or end of markup, wherever it stands in
#: Word's text. Asking this module's own reading which ones mattered was tried first, and
#: its reading is close to pandoc's, not the same: `<LLOQ in mg/L and >` is a tag to pandoc
#: and was text to it, so the words were merged bare and deleted at the next build. A
#: backslash before punctuation never changes what pandoc prints, except before a quote, a
#: hyphen or a full stop, which it would stop typesetting; those are left alone here, and
#: only `_opened` escapes one, where it would open the paragraph as a list.
_MARKDOWN = re.compile(
    r"[\\`*\[^~{}$]"
    rf"|{_TAG_OPEN}"  # a tag, a comment or an autolink; "p < 0.05" is not one
    r"|(?<![A-Za-z0-9])@"  # a citation; the @ of an e-mail address follows a letter
    r"|&(?=#?\w+;)"  # an entity
    r"|(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])"  # emphasis; inside a word it is a letter
    r"|(?<=\])\("  # a link's address, whose `[` may stand in the source's own prose
)


def _escaped(
    text: str,
    opening: bool,
    after_token: bool = False,
    before_token: bool = False,
    shown_before: str = "",
    bare_before: str | None = None,
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

    A `>` is escaped once Word's paragraph shows, before it, a `<` that can open a tag: in
    this text, or in `shown_before`, the text ahead of it (Word's, with each citation as its
    key, as pandoc reads it; `bare_before` is the same with Word's own `<` set aside, since
    this escapes it). That `<` need not be Word's:
    one the source kept bare, or one a binding's value brings, opens a tag that a `>` later in
    Word's text closes, and `Samples <LLOQ in {{results.unit}} and >ULOQ` printed "Samples
    ULOQ". Pandoc's tags are looser than `_read`'s, and `_read` fills a binding with digits,
    so the read-back saw text. A `<` that cannot open one is not counted, so `p < 0.05 and
    ROR > 2` stays as typed. A `<` in Word's text is escaped itself, above or at a token's
    edge, so counting one only adds a backslash pandoc does not need; it is counted all the
    same, in case this escaper and pandoc disagree about it, and G2 reads `\\>` as the `>` it
    prints. After an `=` the `>` is written `&gt;`, and a straight quote gets a backslash
    after a `<` of the source's or a value's, not after one Word typed; see `_closers`.
    """
    brace = before_token and text.endswith("{")
    closers = _closers(shown_before, text, bare_before)
    text = _MARKDOWN.sub(lambda m: "\\" + m.group(0), text)
    # `_MARKDOWN` neither adds nor removes a `>` or a quote, so they are the ones `closers` read.
    head, *rest = _TAG_PUNCTUATION.split(text)
    text = head + "".join(closer + part for closer, part in zip(closers, rest, strict=True))
    if after_token and text.startswith("("):
        text = "\\" + text
    if before_token and text.endswith(("<", "&", "]")):
        text = text[:-1] + "\\" + text[-1]
    if brace:
        text = text.removesuffix("\\{") + "&lbrace;"
    return _opened(text, whole=not before_token) if opening else text


_NBSP = "\u00a0"


def _respaced(text: str, abbreviations: frozenset[str], *, lead: bool, binding_next: bool) -> str:
    """Word's text as Markdown, the no-break space pandoc puts after an abbreviation written
    as the plain space pandoc makes one of again.

    Pandoc's smart typesetting turns the space after a word on its list - "e.g.", "al.",
    "p." - into a no-break space, before anything but a citation, a footnote reference or a
    line break. Carried back as the character, it went into the .md where nobody can see
    it: a diff showed the line as changed there, and a search for "et al. 2020" missed it.

    Only where pandoc will put it back, or the document would lose it. The word before it
    must be whole, as pandoc's reader takes words - letters, digits and single full stops -
    so `xe.g.` is no abbreviation, and neither is `p\\.`, whose full stop `_escaped` set
    apart at the opening, nor `desk@p.` (see `_run_on`). What follows must not be a space,
    and at the end of the stretch it must be a binding, never a citation. A word at the
    start of a stretch that follows a token is left alone, because the token's value may
    run into it.
    """
    if not abbreviations or _NBSP not in text:
        return text
    out = list(text)
    for at, char in enumerate(text):
        following = text[at + 1 : at + 2]
        if char != _NBSP or following.isspace() or not (following or binding_next):
            continue
        start = at
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "."):
            start -= 1
        if text[start:at] in abbreviations and not _run_on(text, start, lead):
            out[at] = " "
    return "".join(out)


def _run_on(text: str, start: int, lead: bool) -> bool:
    """Whether the word that ends at `start` runs on from something pandoc reads with it.

    Pandoc reads a bare `@` and the label after it - letters and digits, joined by `-` or
    `_` - as an example reference, so the abbreviation in `desk@p.` or `desk@lab-p.` is part
    of the label, and no no-break space follows it. `_escaped` leaves an `@` bare after a
    letter or a digit; an escaped `\\@` is a character of its own. Looking only at the
    character before the word missed `desk@lab-p.`, so the whole word is searched, once:
    a regular expression over the text before it rescanned a long URL from every place in
    it. A word reaching back to a token before the stretch runs on from the token's value,
    which may hold a label of its own. Either way the no-break space is kept, and where
    pandoc would have made one anyway, that costs nothing that shows.
    """
    word = start
    while word > 0 and not text[word - 1].isspace():
        word -= 1
    if word == 0 and not lead:
        return True
    backslashes = 0
    for char in text[word:start]:
        if char == "@" and backslashes % 2 == 0:
            return True
        backslashes = backslashes + 1 if char == "\\" else 0
    return False


def _reads_as(
    rebuilt: str, protected: Sequence[str], renderings: Sequence[str], returned: str
) -> bool:
    """Whether the rebuilt source, built, would read as what came back from Word.

    Its tokens must be the source's, each read as it was and none touching another. Counting
    them was not enough: an edit that left `[@a][@b]` read as a link, `@a:{{results.x}}` as
    the key `a:3.84`, and `cohort.@key` as no citation at all, with as many tokens found.
    A binding is read here as digits, so what its value does beside a key is checked apart:
    `@a {{results.x}}` with a value of `[pooled]` is a key and its locator.
    """
    reading = _read(rebuilt, renderings)
    if reading.protected != list(protected):
        return False
    found = _tokens(rebuilt)
    for index, (first, second) in enumerate(zip(found, found[1:], strict=False)):
        between = rebuilt[first.end() : second.start()]
        if not between:
            return False
        # A narrative key without its locator. One with it ends at the `]`, so nothing after it
        # reads on into the key, and pandoc takes no second locator.
        bare = first.text.lstrip("-").startswith("@") and not first.text.endswith("]")
        if not bare or not _BINDING.fullmatch(second.text):
            continue
        value = renderings[index + 1]
        # One mark of punctuation reads a key on into a value put straight after it; a key in
        # braces ends at its `}`.
        glued = not first.text.endswith("}") and re.fullmatch(r"[:.#$%&+?<>~/-]", between)
        # Spaces, a tab or one line break make a value that opens with `[` the key's locator,
        # as they make a bracket in the source one; a no-break space does not.
        located = _LOCATOR.fullmatch(between + "[") and value.startswith("[")
        if (glued and re.match(r"\w", value)) or located:
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
    #: Everything between two tokens was deleted, so rebuilt they would touch.
    touching: bool = False
    #: Rebuilt, it would be only this, which `tag` gives no identifier: a table, a figure,
    #: or a misspelt placeholder, `"{{result.ror.point}}"`. A later edit to it in Word could
    #: not come back, and would be skipped with "nothing came back".
    alone: str = ""
    #: Rebuilt, a brace kept from the source would lose its partner, written from Word and so
    #: escaped: `Set {x, {{results.x}}, y\} was chosen.` The source's braces paired, these do
    #: not, and the next build would give the paragraph no identifier.
    unpaired: bool = False


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
    abbreviations: frozenset[str] = frozenset(),
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

    `abbreviations` are the words pandoc puts a no-break space after; see `_respaced`.
    """
    reading = _read(source)
    prose, protected = reading.prose, reading.protected
    if not protected:
        return _align_plain(source, reading, rendered, returned, abbreviations)

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
    # What lies ahead of each stretch, for the rules that read a would-be tag; see `_closers`.
    # A `<` there that can open one, kept from the source or brought by a binding's value, is
    # bare, and a `>` in the stretch would close it; an `=` can make the `>` end an attribute's
    # value. Word's text, but a citation as its key: `(Smith 2020)` has a space,
    # `[@smith2020]` has none, and `HR=[@smith2020]\>1` closed a tag where Word's text said
    # it could not. `bare` is the same with each `<` Word typed set aside: the merge escapes it.
    ahead = bare = ""
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
            bare += piece
        else:
            lost += [name for name in _uncarried(reading.lost[index], piece) if name not in lost]
            # What the build printed of the stretch must be what the source reads as, or
            # part of it is something Word's text does not hold: `[Methods]` is a link to
            # the heading, and pandoc reads `<LLOQ in mg/L and >` as a tag.
            unread |= _untypeset(reading.shown[index]) != _untypeset(was_prose[index])
            if quote_open and _WORD_CLOSES.search(piece):
                # Straight even where `_closers` will escape it, after an `=`: left curly, it
                # closed nothing, and a value the source's own `='` had opened ran on into the
                # next paragraph. Escaped, it prints straight, the source's opener prints as
                # an apostrophe, and every word prints.
                piece = _WORD_CLOSES.sub("'", piece, count=1)
                quote_open = False
            beside = {"after_token": index > 0, "before_token": index < len(protected)}
            # The paragraph is stripped once rebuilt, so the first stretch is escaped as it
            # will open it: behind a space, a `#` or `:::` was not seen by `_OPENER`, and
            # the paragraph merged as a heading.
            opening = piece.lstrip() if index == 0 else piece
            binding_next = index < len(protected) and _BINDING.fullmatch(protected[index])
            tag = {"shown_before": ahead, "bare_before": bare}
            out.append(
                _respaced(
                    _escaped(opening, opening=index == 0, **tag, **beside),
                    abbreviations,
                    lead=index == 0,
                    binding_next=bool(binding_next),
                )
            )
            bare += piece.replace("<", _SET_ASIDE)
        ahead += piece
        if index < len(protected):
            out.append(protected[index])
            start, end = placed[index]
            shown = "".join(after[start:end])
            token = shown if _BINDING.fullmatch(protected[index]) else protected[index]
            ahead += token
            bare += token
    if lost:
        return Alignment(None, markup=tuple(lost))
    # With nothing between them there is nothing to escape: a citation's `]` against a value
    # that opens with `(` is a link, and the interval was its address. Nor can two touching
    # tokens be lined up again, so every later edit to the paragraph would be refused. After
    # the markup: a footnote deleted with the words around it is the reason to name.
    if not all(new_prose[1:-1]):
        return Alignment(None, touching=True)
    if unread:
        return Alignment(None, unaligned=True)
    rebuilt = "".join(out).strip()
    # A paragraph cut down to one token is still a paragraph, and keeps its identifier -
    # unless the token is one `tag` skips: a table, a figure, or a misspelt placeholder.
    # Merged, that would build without one. Only that shape is refused here, because it is
    # the one the reason names: `_untagged` skips more than a lone token, and asked of any
    # rewording it refused `B) the ratio was...` as "everything but it was deleted".
    if re.fullmatch(r"\{\{[^}]*\}\}", rebuilt) and _untagged(rebuilt):
        return Alignment(None, alone=rebuilt)
    # A stretch kept from the source keeps its braces bare, and one written from Word has
    # them escaped, so a pair with one half on each side of a token no longer pairs. The
    # paragraph would build without an identifier, and its next edit could not come back.
    if _brace_group_runs_on(rebuilt) and not _brace_group_runs_on(source):
        return Alignment(None, unpaired=True)
    if not _reads_as(rebuilt, protected, tokens, returned):
        return Alignment(None, misread=True)
    return Alignment(rebuilt or None)


def _align_plain(
    source: str,
    reading: _Reading,
    rendered: str,
    returned: str,
    abbreviations: frozenset[str] = frozenset(),
) -> Alignment:
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
    if lost := _uncarried(reading.lost[0], returned):
        return Alignment(None, markup=lost)
    if _untypeset(reading.shown[0]) != _untypeset(rendered):
        return Alignment(None, unaligned=True)
    rebuilt = _respaced(
        _escaped(returned.strip(), opening=True), abbreviations, lead=True, binding_next=False
    )
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
