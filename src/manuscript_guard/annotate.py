"""The annotated copy: every number in the document, coloured by what backs it.

`check` gives a verdict. It does not let a co-author, a supervisor or a reviewer *see* why
any particular number is trusted, and "the tool says it is fine" is not something a careful
reader should have to accept. This builds the document with every number highlighted and
linked: hover it in Word and the provenance appears, click it and you land on the entry in
the provenance appendix.

**Four tiers, not two.** A binary verified/not would be a lie in one specific place, and it
is the place that matters most:

  traced     bound to a results value or to a literature value backed by a stored source.
             There is an artefact behind it and a digest over the artefact.
  attested   bound to a value resting on a person's written word, because the source could
             not be stored. Traceable to a name and a date, not to a document.
  exempt     a convention or a structural reference. **Nobody checked this number.** The
             gate agreed not to look at it, which is a different thing from verifying it,
             and colouring it like a traced value would be the annotated copy's one
             opportunity to mislead.
  defect     unbound, and the gate says so.

The tiers are the point of the exercise. An author who sees how much of their Methods is
amber has learned something a pass/fail line cannot tell them.

Everything here derives from the same substitution and the same classifier the gates use —
the annotation is emitted *during* substitution, where the pipeline already knows exactly
which key it is replacing, rather than by re-reading the output and guessing. A second
implementation of "what is this number" would drift from the first, which is the failure
this repository has spent several rounds of review correcting elsewhere.
"""

from __future__ import annotations

import bisect
import difflib
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts.values import RESULTS, Value
from manuscript_guard.text.inline import (
    code_spans,
    equation_spans,
    link_text_spans,
    markable_core,
)
from manuscript_guard.text.masking import front_matter_end, mask
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.sections import chain_at, heading_index
from manuscript_guard.text.tokens import find_atoms

TRACED = "traced"
ATTESTED = "attested"
EXEMPT = "exempt"
DEFECT = "defect"

#: Style id, Word highlight colour, and what the colour means in the legend. Word's
#: `w:highlight` takes a fixed vocabulary of colour names, not hex, so these are chosen from
#: what it has: green for an artefact, cyan for a person's word, yellow for unchecked, red
#: for a defect.
TIERS: dict[str, tuple[str, str, str]] = {
    TRACED: ("mg-traced", "green", "traced to a results value or a stored source"),
    ATTESTED: ("mg-attested", "cyan", "rests on a named person's written word"),
    EXEMPT: ("mg-exempt", "yellow", "exempted by rule — nobody checked this number"),
    DEFECT: ("mg-defect", "red", "not bound to any source"),
}

_STYLE = (
    '<w:style w:type="character" w:customStyle="1" w:styleId="{sid}">'
    '<w:name w:val="{sid}"/><w:rPr><w:highlight w:val="{colour}"/></w:rPr></w:style>'
)

#: Anchors are numbered per build rather than derived from the key, because one key may be
#: quoted many times and each occurrence needs its own tooltip target.
_ANCHOR = "mg-n{n}"


@dataclass(frozen=True)
class Mark:
    """One annotated number: what it is, and what to say when a reader hovers it.
    `unmarked` says why it carries no mark in the text, when it carries none."""

    anchor: str
    tier: str
    shown: str
    label: str
    detail: str
    unmarked: str = ""

    @property
    def tooltip(self) -> str:
        return f"{self.label} — {self.detail}" if self.detail else self.label


# Why a number is listed in the appendix and not marked in the text.
IN_CODE = "in code, where a mark would print as text"
IN_EQUATION = "in an equation, which a mark would break"
IN_MARKUP = "inside markup a mark would break"
IN_LINK = "in a link's text, where a mark, itself a link, cannot go"
IN_FRONT_MATTER = "in the front matter"
READ_OTHERWISE = "with a mark there, pandoc read the paragraph differently"


@dataclass(frozen=True)
class _Piece:
    """What goes in place of `text[start:end]`: a number, marked or as the manuscript
    prints it, or a rendered table, each of whose numbers is one or the other."""

    start: int
    end: int
    plain: str
    mark: Mark | None = None
    table: tuple[tuple[str, Mark | None], ...] = ()


def _escape(text: str) -> str:
    """For a Word tooltip attribute. Newlines are not allowed there."""
    out = " ".join(str(text).split())
    for bad, good in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")):
        out = out.replace(bad, good)
    return out[:250]


def _value_mark(anchor: str, ref: str, value: Value) -> Mark:
    """What to say about a bound number."""
    detail = ""
    # Prose is not a traced number. A results key holding "The drug causes liver failure and
    # should be withdrawn" substituted into the manuscript and came out green, labelled with
    # its key and "emitted by 01_disproportionality.json" — the strongest reassurance this
    # document offers, on a sentence the author typed into an analysis script and nothing
    # verified. It also slips past every prose gate, since those read manuscript sources.
    #
    # Judged on whether the display carries a digit, not on whether it reads like a sentence:
    # a rule about the shape of the text would be the wrong kind of rule, and `label=True`
    # already exists for the author to say "this is a name". A name stays traced, because it
    # really is traced to the analysis. Unlabelled prose is a defect.
    if not value.label and not any(character.isdigit() for character in value.display):
        return Mark(
            anchor=anchor,
            tier=DEFECT,
            shown=value.display,
            label=ref,
            detail="text published through the results file: no number in it, and nothing "
            "checked the words. Write it in the manuscript, or emit it with label=True if "
            "it is a name",
        )
    if value.origin == RESULTS:
        tier = TRACED
        source = value.source.name if value.source else "an analysis"
        detail = f"emitted by {source}"
    elif value.detail and value.detail.get("attested_by"):
        tier = ATTESTED
        detail = (
            f"attested by {value.detail['attested_by']} on "
            f"{value.detail.get('attested_on', 'an unrecorded date')}"
        )
    else:
        tier = TRACED
        if value.detail:
            citekey = value.detail.get("citekey")
            locator = value.detail.get("locator")
            detail = ", ".join(part for part in (citekey, locator) if part)
    if value.unit:
        detail = f"{detail}; unit {value.unit}" if detail else f"unit {value.unit}"
    return Mark(anchor=anchor, tier=tier, shown=value.display, label=ref, detail=detail)


def annotate(
    text: str,
    namespace: dict[str, Value],
    classifier: Classifier,
    *,
    counter: list[int],
    results=None,
    project=None,
    pandoc: str | None = None,
) -> tuple[str, list[Mark]]:
    """Substitute every binding and wrap every number in a highlight and a link.

    Returns the annotated markdown and the marks in document order. `counter` is a
    single-element list used to keep anchor numbers unique across files, which is the least
    ceremony that still guarantees it.

    Tables and figures are substituted here too. The first version annotated the source and
    substituted only *value* bindings, so `{{table.baseline}}` was printed literally and the
    annotated copy contained no tables and no figures at all — an audit document missing the
    artefacts most likely to carry a stale number.

    A mark never goes where it would change how the text reads. The number finder reads
    raw text, and a mark around what it found split `HbA~1c~` before its closing `~`, so
    the subscript was lost, and went inside a code span, where it printed as text. A number
    in code or an equation is left unmarked, and one inside other markup is marked on its
    digits or around the whole of the markup (`markable_core`). Given `pandoc`, the file is then
    read with and without its marks, and every mark in a paragraph that reads differently
    is taken out (`_checked`). A number left unmarked is listed in the appendix all the
    same, with the reason.
    """
    masked = mask(text)
    placeholders, _malformed = parse(text)
    unmarkable = _Unmarkable(text, masked, front_matter_end(text))
    pieces = [
        *_value_pieces(placeholders, namespace, counter, unmarkable),
        *_block_pieces(placeholders, results, project, counter),
        *_number_pieces(text, masked, classifier, counter, unmarkable),
    ]
    pieces.sort(key=lambda piece: piece.start)
    kept: list[_Piece] = []
    for piece in pieces:
        if kept and piece.start < kept[-1].end:  # overlapping; keep the first, the binding
            continue
        kept.append(piece)
    marks = [piece.mark for piece in kept if piece.mark is not None]
    marks += [mark for piece in kept for _part, mark in piece.table if mark is not None]
    if pandoc is not None:
        marks = _checked(text, kept, marks, pandoc)
    showing = {mark.anchor for mark in marks if not mark.unmarked}
    return _render(text, kept, showing), marks


class _Unmarkable:
    """Where no mark can go: code, equations, a link's text and the front matter, found
    once a file."""

    def __init__(self, text: str, masked: str, head: int) -> None:
        self._head = head
        code = code_spans(masked)
        self._spans = {
            IN_CODE: code,
            IN_EQUATION: equation_spans(masked, code),
            IN_LINK: link_text_spans(text),
        }

    def reason(self, start: int, end: int) -> str:
        if start < self._head:
            return IN_FRONT_MATTER
        for reason, spans in self._spans.items():
            at = bisect.bisect_right(spans, (start, float("inf"))) - 1
            if at >= 0 and spans[at][1] > start:
                return reason
            if at + 1 < len(spans) and spans[at + 1][0] < end:
                return reason
        return ""


def _value_pieces(placeholders, namespace, counter, unmarkable) -> list[_Piece]:
    """Each value binding, to be marked, or put in as its value where no mark can go."""
    pieces = []
    for placeholder in placeholders:
        if not placeholder.is_value:
            continue
        value = namespace.get(placeholder.ref)
        if value is None:
            continue
        counter[0] += 1
        mark = _value_mark(_ANCHOR.format(n=counter[0]), placeholder.ref, value)
        reason = unmarkable.reason(placeholder.start, placeholder.end)
        pieces.append(
            _Piece(
                placeholder.start,
                placeholder.end,
                value.display,
                replace(mark, unmarked=reason),
            )
        )
    return pieces


def _block_pieces(placeholders, results, project, counter) -> list[_Piece]:
    """Each table, its numbers marked, and each figure."""
    pieces = []
    for placeholder in placeholders:
        if placeholder.is_value or results is None:
            continue
        if placeholder.namespace == "table":
            table = results.tables.get(placeholder.key)
            if table is None:
                continue
            counter[0] += 1
            parts = _annotated_table(table, placeholder.key, counter)
            plain = "".join(part for part, _mark in parts)
            pieces.append(_Piece(placeholder.start, placeholder.end, plain, table=parts))
        elif placeholder.namespace == "figure" and project is not None:
            from manuscript_guard.build.assemble import find_figure
            from manuscript_guard.build.document import relative_to_root

            figure = find_figure(project, placeholder.key)
            if figure is None:
                continue
            raster = (figure.with_suffix(ext) for ext in (".png", ".jpg"))
            shown = next((path for path in raster if path.exists()), figure)
            image = f"![]({relative_to_root(project, shown)})"
            pieces.append(_Piece(placeholder.start, placeholder.end, image))
    return pieces


def _number_pieces(text, masked, classifier, counter, unmarkable) -> list[_Piece]:
    """Each number the gates read, classified, marked on the part a mark can go around."""
    headings = heading_index(text)
    scan = classifier.scan(text)
    pieces = []
    for atom in find_atoms(text, masked):
        verdict = classifier.classify(atom, chain_at(headings, atom.start), scan)
        counter[0] += 1
        anchor = _ANCHOR.format(n=counter[0])
        core = markable_core(text, atom.start, atom.end)
        start, end = core or (atom.start, atom.end)
        shown = text[start:end]
        if verdict.kind == UNCLASSIFIED:
            # The hover on a red number carries the way out, not just the verdict. "Not
            # bound to any source" tells an author what they already know from the colour;
            # what they need is the sentence that says what to type, which is the same one
            # the gate prints.
            from manuscript_guard.gates.numbers import _hint_for

            mark = Mark(anchor, DEFECT, shown, "not bound to any source", _hint_for(atom))
        else:
            mark = Mark(
                anchor, EXEMPT, shown, f"{verdict.kind}: {verdict.rule}", verdict.detail or ""
            )
        reason = unmarkable.reason(start, end) or ("" if core else IN_MARKUP)
        pieces.append(_Piece(start, end, shown, replace(mark, unmarked=reason)))
    return pieces


def _render(text: str, pieces: list[_Piece], showing: set[str]) -> str:
    """`text` with each piece put in, the marks whose anchors are in `showing` as marks."""
    out: list[str] = []
    cursor = 0
    for piece in pieces:
        out.append(text[cursor : piece.start])
        if piece.table:
            out.extend(
                _wrap(mark) if mark is not None and mark.anchor in showing else part
                for part, mark in piece.table
            )
        elif piece.mark is not None and piece.mark.anchor in showing:
            out.append(_wrap(piece.mark))
        else:
            out.append(piece.plain)
        cursor = piece.end
    out.append(text[cursor:])
    return "".join(out)


def _annotated_table(table, key: str, counter: list[int]) -> list[tuple[str, Mark | None]]:
    """Render an emitted table in parts, each number in it a part with its mark.

    A table's numbers are traced by construction: the analysis emitted the table, and G2
    re-checks every cell in the fragment against what the analysis published. What the
    reader gains here is being able to hover a cell and see *which* table it came from,
    which matters most in the artefact a stale number is likeliest to survive in.
    """
    from manuscript_guard.build.assemble import render_table

    rendered = render_table(table)
    source = table.source.name if table.source else "an analysis"
    parts: list[tuple[str, Mark | None]] = []
    for number, line in enumerate(rendered.split("\n")):
        if number:
            parts.append(("\n", None))
        # The alignment row is punctuation, and the caption is prose.
        if set(line.strip()) <= set("|-: ") or line.lstrip().startswith(":"):
            parts.append((line, None))
            continue
        cursor = 0
        for atom in find_atoms(line, mask(line)):
            counter[0] += 1
            core = markable_core(line, atom.start, atom.end)
            start, end = core or (atom.start, atom.end)
            mark = Mark(
                anchor=_ANCHOR.format(n=counter[0]),
                tier=TRACED,
                shown=line[start:end],
                label=f"table.{key}",
                detail=f"emitted by {source}",
                unmarked="" if core else IN_MARKUP,
            )
            parts += [(line[cursor:start], None), (line[start:end], mark)]
            cursor = end
        parts.append((line[cursor:], None))
    return parts


_ANCHORS = re.compile(r"mg-n\d+")
_STYLES = frozenset(style for style, _colour, _meaning in TIERS.values())


def _checked(text: str, pieces: list[_Piece], marks: list[Mark], pandoc: str) -> list[Mark]:
    """`marks`, with every one in a paragraph pandoc reads differently for its marks taken
    out, and noted.

    The file is read with its marks and without, and each block compared once the marks
    are unwrapped. A mark `_core` placed wrongly, in a link's text or beside a quote pandoc
    would have made curly, changes its block, and every mark there is taken out: which one
    did it is not worked out, and a number left unmarked is listed in the appendix all the
    same. What still reads differently then loses every mark in the file, so the copy never
    reads otherwise than the manuscript does."""
    showing = {mark.anchor for mark in marks if not mark.unmarked}
    try:
        plain = _blocks(_render(text, pieces, set()), pandoc)
        if plain is None:
            return marks  # pandoc cannot read the manuscript; the build says so
        expected = [_key(block) for block in plain]
        for _attempt in range(2):
            read = _blocks(_render(text, pieces, showing), pandoc)
            if read is None:
                break
            changed = _changed_blocks(read, expected)
            if not changed:
                return _unmark(marks, showing)
            blamed = {anchor for block in changed for anchor in _anchors(block)} & showing
            if not blamed:
                break
            showing -= blamed
    except RecursionError:
        pass  # nested too deep to compare, so not compared: nothing is marked
    return _unmark(marks, set())


def _unmark(marks: list[Mark], showing: set[str]) -> list[Mark]:
    return [
        replace(mark, unmarked=READ_OTHERWISE)
        if not mark.unmarked and mark.anchor not in showing
        else mark
        for mark in marks
    ]


def _blocks(markdown: str, pandoc: str) -> list | None:
    finished = subprocess.run(
        [pandoc, "-f", "markdown", "-t", "json"],
        input=markdown.encode("utf-8"),
        capture_output=True,
    )
    return json.loads(finished.stdout)["blocks"] if finished.returncode == 0 else None


def _anchors(block) -> set[str]:
    return set(_ANCHORS.findall(json.dumps(block)))


def _changed_blocks(read: list, expected: list[str]) -> list:
    """The blocks of `read` that, marks unwrapped, are not the blocks expected."""
    keys = [_key(block) for block in read]
    matcher = difflib.SequenceMatcher(None, keys, expected, autojunk=False)
    return [
        read[index]
        for tag, low, high, _other_low, _other_high in matcher.get_opcodes()
        if tag != "equal"
        for index in range(low, high)
    ]


def _key(block) -> str:
    return json.dumps(_unwrapped(block), sort_keys=True)


def _unwrapped(node):
    """Pandoc's reading with each mark replaced by what it holds, neighbouring words
    joined, and a table's column widths left out: a longer row, marks in it, made pandoc
    give a pipe table widths, which print nothing different."""
    if isinstance(node, list):
        out: list = []
        for item in node:
            inner = _marked_content(item)
            out.extend(_unwrapped(inner) if inner is not None else [_unwrapped(item)])
        joined: list = []
        for item in out:
            if _is_word(item) and joined and _is_word(joined[-1]):
                joined[-1] = {"t": "Str", "c": joined[-1]["c"] + item["c"]}
            else:
                joined.append(item)
        return joined
    if not isinstance(node, dict):
        return node
    if node.get("t") == "Cite":
        # The citation as written, which citeproc replaces and never prints: with a mark
        # on a locator, `p. 33`, it differed, and the paragraph lost every mark.
        citations, _written = node["c"]
        return {"t": "Cite", "c": [_unwrapped(citations), []]}
    if node.get("t") == "Table":
        attributes, caption, columns, *rest = node["c"]
        widthless = [[align, {"t": "ColWidthDefault"}] for align, _width in columns]
        return {"t": "Table", "c": _unwrapped([attributes, caption, widthless, *rest])}
    return {key: _unwrapped(value) for key, value in node.items()}


def _marked_content(item) -> list | None:
    """What a mark holds, when `item` is one: a styled span around a single link to an
    appendix anchor."""
    if not isinstance(item, dict) or item.get("t") != "Span":
        return None
    (_id, _classes, pairs), content = item["c"]
    if dict(pairs).get("custom-style") not in _STYLES or len(content) != 1:
        return None
    link = content[0]
    if link.get("t") != "Link" or not _ANCHORS.fullmatch(link["c"][2][0].lstrip("#")):
        return None
    return link["c"][1]


def _is_word(item) -> bool:
    return isinstance(item, dict) and item.get("t") == "Str"


def _wrap(mark: Mark) -> str:
    """A highlighted span wrapping a link to the appendix entry.

    The link exists for two reasons: clicking it lands on the full provenance, and the
    anchor gives the tooltip pass something unambiguous to key on. Matching on the visible
    text instead would attach the wrong tooltip the moment two numbers read the same, which
    in a paper full of 1s and 2s is immediately.
    """
    style, _colour, _legend = TIERS[mark.tier]
    shown = mark.shown.replace("[", r"\[").replace("]", r"\]")
    return f'[[{shown}](#{mark.anchor})]{{custom-style="{style}"}}'


def legend() -> str:
    """The key to the colours, which the document has to carry to be readable alone."""
    rows = "\n".join(
        f"| {tier} | {colour} | {meaning} |"
        for tier, (_s, colour, meaning) in TIERS.items()
    )
    return (
        "# How to read this copy\n\n"
        "This is an annotated copy, not the manuscript. Every number is highlighted by what\n"
        "backs it, and carries a link: hover it to see where it came from, click it to reach\n"
        "its entry in the appendix below.\n\n"
        "| Tier | Colour | Meaning |\n|---|---|---|\n" + rows + "\n\n"
        "**Yellow is not a verification.** It marks a number the gate agreed not to check —\n"
        "a convention such as an alpha level, or a pointer such as a table number. If a\n"
        "quantity your analysis produced is yellow, something is wrong with how it was\n"
        "written, not with the colour.\n"
    )


def appendix(marks: list[Mark]) -> str:
    """Every number in the document, in order, with what backs it."""
    if not marks:
        return ""
    rows = []
    for mark in marks:
        source = mark.detail or "—"
        if mark.unmarked:
            source = f"{source}. Not marked in the text: {mark.unmarked}"
        rows.append(
            f"| []{{#{mark.anchor}}}{mark.shown} | {mark.tier} | {mark.label} | {source} |"
        )
    return (
        "\n\n# Appendix: provenance of every number\n\n"
        "| Value | Tier | Name | Source |\n|---|---|---|---|\n" + "\n".join(rows) + "\n"
    )


def figure_sheet(project, results) -> str:
    """One page per figure: the picture, what the gate read out of it, and who reviewed it.

    Annotating the image itself was the obvious idea and the wrong one. Overlaying marks on
    an SVG is fragile for a hand-edited file and impossible for a raster, which is what most
    journals want — and the numbers a reader needs to check are not only the ones printed on
    the figure, but the declared presentational values, the review verdict and the date. A
    sheet holds all of that; an overlay holds one of them badly.
    """
    from manuscript_guard.build.document import relative_to_root
    from manuscript_guard.contracts._schema import read_structured
    from manuscript_guard.gates.figures import _declared
    from manuscript_guard.paths import FIGURE_SCRIPT_SUFFIXES

    root = project.path("figures")
    figures = (
        sorted(
            path
            for path in root.iterdir()
            if path.is_file()
            and path.suffix.lower() not in FIGURE_SCRIPT_SUFFIXES
            and not path.name.endswith((".guard.yaml", ".review.yaml", ".render.json"))
        )
        if root.exists()
        else []
    )
    if not figures:
        return ""

    out = [
        "\n\n# Appendix: figures\n",
        "One entry per figure: what the gate read out of it, what the author declared as\n"
        "presentation, and the record of the person who looked at it.\n",
    ]
    displays = {value.display for value in results.values.values()}
    for figure in figures:
        # Absolute, because pandoc resolves an image path against its own working
        # directory rather than the project root, and silently replaces a missing image
        # with its alt text - an audit sheet whose figures are absent would be worse than
        # no sheet at all.
        out.append(f"\n## {figure.name}\n")
        # A raster sibling in preference to the vector: pandoc cannot rasterise an SVG
        # without rsvg-convert, and warns and drops the image when it is absent. The vector
        # is the artefact of record; this sheet only needs the picture to be visible.
        raster = (figure.with_suffix(ext) for ext in (".png", ".jpg"))
        shown = next((path for path in raster if path.exists()), figure)
        out.append(f"![]({relative_to_root(project, shown)})\n")

        declared = figure.with_name(f"{figure.stem}.guard.yaml")
        review = figure.with_name(f"{figure.stem}.review.yaml")

        # `allow` and `allow_source` are the two sections a `.guard.yaml` has. This read
        # `presentational`, which no schema, no gate and no example has ever written — so
        # every figure sheet ever produced said no exemptions were declared, including for
        # the shipped example, which declares five. The sentence a reader trusts most on this
        # page was the one guaranteed to be wrong whenever it mattered.
        rows = [
            (f"| {value} | drawn in the figure | {why} |", value)
            for value, why in _declared(declared, "allow")
        ] + [
            (f"| {value} | in the figure's script | {why} |", value)
            for value, why in _declared(declared, "allow_source")
        ]
        if rows:
            out.append(
                "\nDeclared exemptions — every other number drawn here has to match a "
                "results value:\n\n| Value | Where | Reason |\n|---|---|---|\n"
                + "\n".join(row for row, _v in rows)
                + "\n"
            )
        elif declared.exists():
            out.append(
                f"\n`{declared.name}` declares no exemption with a reason, so every number "
                "drawn on this figure has to match a results value.\n"
            )
        else:
            out.append(
                "\nNo exemptions are declared, so every number drawn on this figure has to "
                "match a results value.\n"
            )

        if review.exists():
            record = read_structured(review) or {}
            out.append(
                f"\n**Reviewed** by {record.get('reviewed_by', 'an unrecorded reviewer')} on "
                f"{record.get('reviewed_on', 'an unrecorded date')} — verdict "
                f"{record.get('verdict', 'unrecorded')}.\n"
            )
            for finding in record.get("findings", ()) or ():
                if isinstance(finding, dict):
                    out.append(
                        f"\n- *{finding.get('severity', 'note')}*: {finding.get('finding', '')}\n"
                    )
        else:
            out.append("\n**Nobody has reviewed this figure.**\n")
    out.append(
        f"\nThe analysis published {len(displays)} display value(s) that a figure may draw.\n"
    )
    return "".join(out)


def styled_reference(pandoc: str, target: Path) -> Path:
    """Pandoc's own reference document, plus the four highlight styles.

    Generated rather than committed: a reference `.docx` is a binary, this repository
    ignores `*.docx` precisely so that build products cannot be mistaken for sources, and a
    style sheet that can be regenerated from a command is one fewer thing to keep in sync.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    default = subprocess.run(
        [pandoc, "--print-default-data-file", "reference.docx"],
        capture_output=True,
        check=True,
    ).stdout
    scratch = target.with_suffix(".default.docx")
    scratch.write_bytes(default)

    extra = "".join(_STYLE.format(sid=sid, colour=colour) for sid, colour, _ in TIERS.values())
    with zipfile.ZipFile(scratch) as zin, zipfile.ZipFile(
        target, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/styles.xml":
                xml = data.decode("utf-8").replace("</w:styles>", extra + "</w:styles>")
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    scratch.unlink(missing_ok=True)
    return target


_HYPERLINK = re.compile(
    r'<w:hyperlink w:anchor="(mg-n\d+)"([^>]*)>(.*?)</w:hyperlink>', re.DOTALL
)
#: `w:rStyle` must come first inside `w:rPr` - OOXML fixes the order of run properties,
#: and Word drops what it finds out of place. Inserted after it, never before.
_RPR = re.compile(r"(<w:rPr>)(<w:rStyle[^>]*/>)?")
_RUN_NO_RPR = re.compile(r"<w:r>(?!<w:rPr>)")


def finish(document: Path, marks: list[Mark]) -> int:
    """Add the hover text and the highlight pandoc will not write.

    Two separate omissions, both found by opening the file rather than by reading the XML.

    Pandoc drops a link title on the way to `.docx`, so the tooltip has to be added here.
    And the highlight, applied in markdown as a custom character style wrapping the link,
    **never reached the page**: OOXML allows one `w:rStyle` per run, pandoc's Link writer
    puts `Hyperlink` there, and the custom style was silently discarded. Nothing failed —
    the styles were defined, the document was valid, and every number was simply unmarked.
    A style that loses a fight with another style is not a mechanism, so the colour is set
    as direct run formatting instead, where nothing can outrank it.

    Keyed on the anchor rather than on the visible text, because two numbers that read the
    same must not share a provenance.
    """
    tips = {mark.anchor: (_escape(mark.tooltip), TIERS[mark.tier][1]) for mark in marks}
    if not tips:
        return 0
    added = 0

    def add(match: re.Match[str]) -> str:
        nonlocal added
        found = tips.get(match.group(1))
        if not found:
            return match.group(0)
        tip, colour = found
        added += 1
        body = match.group(3)
        highlight = f'<w:highlight w:val="{colour}"/>'
        body = _RPR.sub(lambda m: f"{m.group(1)}{m.group(2) or ''}{highlight}", body)
        body = _RUN_NO_RPR.sub(f"<w:r><w:rPr>{highlight}</w:rPr>", body)
        return (
            f'<w:hyperlink w:anchor="{match.group(1)}"{match.group(2)} '
            f'w:tooltip="{tip}">{body}</w:hyperlink>'
        )

    scratch = document.with_suffix(".tooltips.docx")
    with zipfile.ZipFile(document) as zin, zipfile.ZipFile(
        scratch, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = _HYPERLINK.sub(add, data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)
    scratch.replace(document)
    return added
