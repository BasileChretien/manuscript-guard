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

import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts.values import RESULTS, Value
from manuscript_guard.text.masking import mask
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
    """One annotated number: what it is, and what to say when a reader hovers it."""

    anchor: str
    tier: str
    shown: str
    label: str
    detail: str

    @property
    def tooltip(self) -> str:
        return f"{self.label} — {self.detail}" if self.detail else self.label


def _escape(text: str) -> str:
    """For a Word tooltip attribute. Newlines are not allowed there."""
    out = " ".join(str(text).split())
    for bad, good in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")):
        out = out.replace(bad, good)
    return out[:250]


def _value_mark(anchor: str, ref: str, value: Value) -> Mark:
    """What to say about a bound number."""
    detail = ""
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
) -> tuple[str, list[Mark]]:
    """Substitute every binding and wrap every number in a highlight and a link.

    Returns the annotated markdown and the marks in document order. `counter` is a
    single-element list used to keep anchor numbers unique across files, which is the least
    ceremony that still guarantees it.

    Tables and figures are substituted here too. The first version annotated the source and
    substituted only *value* bindings, so `{{table.baseline}}` was printed literally and the
    annotated copy contained no tables and no figures at all — an audit document missing the
    artefacts most likely to carry a stale number.
    """
    placeholders, _malformed = parse(text)
    headings = heading_index(text)
    scan = classifier.scan(text)

    spans: list[tuple[int, int, Mark]] = []
    marks_from_tables: list[Mark] = []
    for placeholder in placeholders:
        if not placeholder.is_value:
            continue
        value = namespace.get(placeholder.ref)
        if value is None:
            continue
        counter[0] += 1
        spans.append(
            (
                placeholder.start,
                placeholder.end,
                _value_mark(_ANCHOR.format(n=counter[0]), placeholder.ref, value),
            )
        )

    for placeholder in placeholders:
        if placeholder.is_value or results is None:
            continue
        if placeholder.namespace == "table":
            table = results.tables.get(placeholder.key)
            if table is None:
                continue
            counter[0] += 1
            rendered, table_marks = _annotated_table(table, placeholder.key, counter)
            spans.append(
                (placeholder.start, placeholder.end, Mark("", "", rendered, "", ""))
            )
            marks_from_tables.extend(table_marks)
        elif placeholder.namespace == "figure" and project is not None:
            from manuscript_guard.build.assemble import find_figure

            figure = find_figure(project, placeholder.key)
            if figure is None:
                continue
            raster = (figure.with_suffix(ext) for ext in (".png", ".jpg"))
            shown = next((path for path in raster if path.exists()), figure)
            spans.append(
                (
                    placeholder.start,
                    placeholder.end,
                    Mark("", "", f"![]({shown.resolve().as_posix()})", "", ""),
                )
            )

    for atom in find_atoms(text, mask(text)):
        verdict = classifier.classify(atom, chain_at(headings, atom.start), scan)
        counter[0] += 1
        anchor = _ANCHOR.format(n=counter[0])
        if verdict.kind == UNCLASSIFIED:
            mark = Mark(anchor, DEFECT, atom.text, "not bound to any source", "")
        else:
            mark = Mark(
                anchor,
                EXEMPT,
                atom.text,
                f"{verdict.kind}: {verdict.rule}",
                verdict.detail or "",
            )
        spans.append((atom.start, atom.end, mark))

    spans.sort(key=lambda item: item[0])
    out: list[str] = []
    marks: list[Mark] = []
    cursor = 0
    for start, end, mark in spans:
        if start < cursor:  # overlapping; keep the first, which is the binding
            continue
        out.append(text[cursor:start])
        if mark.anchor:
            out.append(_wrap(mark))
            marks.append(mark)
        else:
            # A rendered table or figure: already annotated, or nothing to annotate.
            out.append(mark.shown)
        cursor = end
    out.append(text[cursor:])
    return "".join(out), marks + marks_from_tables


def _annotated_table(table, key: str, counter: list[int]) -> tuple[str, list[Mark]]:
    """Render an emitted table with every number in it marked.

    A table's numbers are traced by construction: the analysis emitted the table, and G2
    re-checks every cell in the fragment against what the analysis published. What the
    reader gains here is being able to hover a cell and see *which* table it came from,
    which matters most in the artefact a stale number is likeliest to survive in.
    """
    from manuscript_guard.build.assemble import render_table

    rendered = render_table(table)
    source = table.source.name if table.source else "an analysis"
    marks: list[Mark] = []
    out: list[str] = []
    for line in rendered.split("\n"):
        # The alignment row is punctuation, and the caption is prose.
        if set(line.strip()) <= set("|-: ") or line.lstrip().startswith(":"):
            out.append(line)
            continue
        cursor = 0
        pieces: list[str] = []
        for atom in find_atoms(line, mask(line)):
            counter[0] += 1
            mark = Mark(
                anchor=_ANCHOR.format(n=counter[0]),
                tier=TRACED,
                shown=atom.text,
                label=f"table.{key}",
                detail=f"emitted by {source}",
            )
            pieces.append(line[cursor : atom.start])
            pieces.append(_wrap(mark))
            marks.append(mark)
            cursor = atom.end
        pieces.append(line[cursor:])
        out.append("".join(pieces))
    return "\n".join(out), marks


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
        rows.append(
            f"| []{{#{mark.anchor}}}{mark.shown} | {mark.tier} | {mark.label} | "
            f"{mark.detail or '—'} |"
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
    from manuscript_guard.contracts._schema import read_structured
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
        out.append(f"![]({shown.resolve().as_posix()})\n")

        declared = figure.with_name(f"{figure.stem}.guard.yaml")
        review = figure.with_name(f"{figure.stem}.review.yaml")

        rows = []
        if declared.exists():
            document = read_structured(declared) or {}
            for entry in document.get("presentational", ()) or ():
                if isinstance(entry, dict):
                    rows.append(
                        f"| {entry.get('value', '?')} | declared presentational | "
                        f"{entry.get('why', '—')} |"
                    )
        if rows:
            out.append("\n| Value | Status | Reason |\n|---|---|---|\n" + "\n".join(rows) + "\n")
        else:
            out.append(
                "\nNo values are declared presentational, so every number drawn on this "
                "figure has to match a results value.\n"
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
