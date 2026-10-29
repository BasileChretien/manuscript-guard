"""`communicate check` of the graphical abstract, and of an SVG a text attaches.

Each image under `communication/graphical-abstract/` is held to the journal's
`graphical_abstract` rules as G4 holds a figure (format, file size, smallest text), and to its
size, aspect ratio, words and labels (`comm-ga-size`, `comm-ga-aspect`, `comm-ga-words`,
`comm-ga-labels`, each a warning as G4's are), with a note where the journal gives no size
(`comm-ga-size-default`); its colours as G3 holds a figure's; each line of an SVG to the
statement it names (`comm-ga-text-not-in-statement`) and each value it prints to the results
now (`comm-ga-stale`); its numbers as a text's; and its alternative text, `alt-text.md`, as
G3 holds a figure's (`comm-alt-missing`, `comm-alt-long`, and G3's `figure-alt-number` and
`figure-alt-binding`). An SVG a text attaches, the overview slide, is held line by line the
same way (`svg_text`).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED
from manuscript_guard.communicate import GATE, graphical_abstract_folder
from manuscript_guard.communicate import texts as texts_module
from manuscript_guard.communicate.brief import fold
from manuscript_guard.communicate.checking import (
    ALT_TEXT,
    Context,
    _claimed,
    _finding,
    journal_rules,
)
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.text.tokens import find_atoms

#: How far a drawn aspect ratio may stand from the journal's and still be it: a pixel of
#: rounding.
_ASPECT_TOLERANCE = 0.01
_IMAGES = (".svg", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf", ".eps")


def images(project) -> list[Path]:
    root = graphical_abstract_folder(project)
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir()
                  if path.is_file() and path.suffix.lower() in _IMAGES)  # fmt: skip


def _as_figure_rules(rules: dict) -> dict:
    """The graphical abstract's rules in the shape G4 holds a figure to."""
    out = {key: rules[key] for key in ("formats", "max_file_mb", "min_text_pt") if key in rules}
    if "min_dpi" in rules:
        out["min_dpi"] = dict.fromkeys(("halftone", "combination", "line_art"), rules["min_dpi"])
    return out


def report_of(context: Context) -> Report:
    project = context.project
    drawn = images(project)
    if not drawn:
        return Report()
    rules, profile = journal_rules(project)
    from manuscript_guard.gates.figure_files import check_file
    from manuscript_guard.gates.journal import figure_rules

    grey = figure_rules(project).get("print") == "greyscale"
    found: list[Finding] = []
    if not any(key in rules for key in ("width_px", "height_px", "min_width_px",
                                        "min_height_px", "aspect_ratio")):  # fmt: skip
        from manuscript_guard.communicate.svg import DEFAULT_HEIGHT, DEFAULT_WIDTH

        found.append(_finding(
            "comm-ga-size-default",
            "the journal's profile gives no size for a graphical abstract, so its size is "
            f"not checked; the concepts are drawn at the default, {DEFAULT_WIDTH} by "
            f"{DEFAULT_HEIGHT} pixels",
            graphical_abstract_folder(project), severity=INFO,
            hint="where the journal states a size, record it under graphical_abstract in its "
            "profile, quoted (the journal-profile skill)",
        ))  # fmt: skip
    figure = _as_figure_rules(rules)
    for path in drawn:
        found += [replace(one, gate=GATE)
                  for one in check_file(path, figure, profile or path)]  # fmt: skip
        found += _dimensions(path, rules)
        from manuscript_guard.gates.figure_colours import colour_findings

        coloured = colour_findings(path, "graphical abstract", greyscale=grey)
        found += [replace(one, gate=GATE) for one in coloured or ()]
        if path.suffix.lower() == ".svg":
            found += svg_text(context, path, rules)
        elif path.suffix.lower() == ".pdf":
            found += _pdf_text(context, path)
    found += _alt(context, rules)
    return Report(tuple(found)).with_counts(graphical_abstract_images=len(drawn))


def _pixels(path: Path) -> tuple[float, float] | None:
    from manuscript_guard.gates.figure_files import raster_of
    from manuscript_guard.gates.figure_svg import _length

    if path.suffix.lower() == ".svg":
        try:
            root = ET.fromstring(read_text(path))
        except (ET.ParseError, ValueError):
            return None
        width, height = root.get("width"), root.get("height")
        sized = (_length(width, 0) if width else None, _length(height, 0) if height else None)
        if None not in sized:
            return sized  # type: ignore[return-value]
        view = (root.get("viewBox") or "").replace(",", " ").split()
        if len(view) == 4:
            try:
                return float(view[2]), float(view[3])
            except ValueError:
                return None
        return None
    raster = raster_of(path)
    return (float(raster.width), float(raster.height)) if raster is not None else None


def _dimensions(path: Path, rules: dict) -> list[Finding]:
    from manuscript_guard.communicate.svg import _ratio

    size = _pixels(path)
    if size is None:
        return []
    width, height = size
    hint = "draw it again at the journal's size (`communicate graphical-abstract`)"
    found = []
    for key, value, what in (("width_px", width, "wide"), ("height_px", height, "high")):
        wanted = rules.get(key)
        if isinstance(wanted, int) and round(value) != wanted:
            found.append(_finding("comm-ga-size", f"{path.name} is {value:g} pixels {what}, and "
                                  f"the journal asks for {wanted}", path, severity=WARN,
                                  hint=hint))  # fmt: skip
    for key, value, what in (("min_width_px", width, "wide"), ("min_height_px", height, "high")):
        least = rules.get(key)
        if isinstance(least, int) and value < least:
            found.append(_finding("comm-ga-size", f"{path.name} is {value:g} pixels {what}, and "
                                  f"the journal asks for at least {least}", path,
                                  severity=WARN, hint=hint))  # fmt: skip
    ratio = _ratio(rules.get("aspect_ratio"))
    if ratio and height and abs(width / height - ratio) / ratio > _ASPECT_TOLERANCE:
        found.append(_finding("comm-ga-aspect", f"{path.name} is {width:g} by {height:g} "
                              f"pixels, and the journal asks for {rules['aspect_ratio']}",
                              path, severity=WARN, hint=hint))  # fmt: skip
    return found


@dataclass(frozen=True)
class _Drawn:
    text: str
    statement: str
    refs: tuple[str, ...]
    size: float


def drawn_texts(path: Path) -> list[_Drawn] | None:
    """Each `<text>` of an SVG, with what it names; None where the file cannot be read."""
    from manuscript_guard.gates.figures import _svg_content_nodes

    try:
        root = ET.fromstring(read_text(path))
    except (ET.ParseError, ValueError):
        return None
    found = []
    for node in _svg_content_nodes(root):
        if node.tag.rsplit("}", 1)[-1] != "text":
            continue
        words = " ".join("".join(node.itertext()).split())
        if not words:
            continue
        try:
            size = float(str(node.get("font-size", "16")).rstrip("px") or 16)
        except ValueError:
            size = 16.0
        found.append(_Drawn(words, node.get("data-statement", "").strip(),
                            tuple((node.get("data-binding") or "").split()), size))  # fmt: skip
    return found


def svg_text(context: Context, path: Path, rules: dict) -> list[Finding]:
    from manuscript_guard.communicate.svg import pointers, printed

    drawn = drawn_texts(path)
    if drawn is None:
        return [_finding("comm-ga-unreadable", f"{path.name} is no SVG that can be read",
                         path, hint="draw it again")]  # fmt: skip
    statements = context.brief.by_id if context.brief is not None else {}
    shown = {**context.namespace, **pointers(context.project)}
    found: list[Finding] = []
    for one in drawn:
        for ref in one.refs:
            value = context.namespace.get(ref)
            if value is None:
                found.append(_finding("comm-binding-unknown", f"a line of {path.name} prints "
                                      f"{ref}, a value nothing emits", path,
                                      context=one.text[:160]))  # fmt: skip
            elif value.display not in one.text:
                found.append(_finding(
                    "comm-ga-stale",
                    f"a line of {path.name} prints {ref}, whose value is {value.display} now, "
                    "and the line does not hold it",
                    path, context=one.text[:160],
                    hint="draw it again from the results as they stand "
                    "(`communicate graphical-abstract`)",
                ))  # fmt: skip
        if one.statement:
            statement = statements.get(one.statement)
            if statement is None:
                found.append(_finding("comm-anchor-unknown", f"a line of {path.name} names "
                                      f"{one.statement}, which is no statement of the brief",
                                      path, context=one.text[:160]))  # fmt: skip
            elif fold(one.text) not in fold(printed(statement.text, shown)):
                found.append(_finding(
                    "comm-ga-text-not-in-statement",
                    f"a line of {path.name} names {one.statement}, which does not say it",
                    path, context=one.text[:160],
                    hint="change the statement's text in the brief and draw it again, rather "
                    "than the words in the SVG",
                ))  # fmt: skip
        else:
            label = texts_module.read(one.text)
            if any(sentence.claims for sentence in label.sentences):
                why = next(s.why for s in label.sentences if s.claims)
                found.append(_finding(
                    "comm-claim-unanchored",
                    f"a label of {path.name} claims ({why}) and names no statement of the "
                    "brief", path, context=one.text[:160],
                    hint="draw it from a statement of the brief (data-statement), or say it "
                    "without the claim",
                ))  # fmt: skip
    # Each statement's lines read together against its quote, as a post's sentence is: a
    # negation left off a line, or a hedge, draws a claim the paper does not make.
    for name in dict.fromkeys(one.statement for one in drawn if one.statement in statements):
        said = " ".join(one.text for one in drawn if one.statement == name)
        found += _claimed(said, statements[name].quote, f"the brief's {name}", path, None,
                          None)  # fmt: skip
    found += _drawn_numbers(context, path, "\n".join(one.text for one in drawn))
    found += _drawn_story(context, path, drawn)
    words = sum(len(one.text.split()) for one in drawn)
    most = rules.get("max_words")
    if isinstance(most, int) and words > most:
        found.append(_finding("comm-ga-words", f"{path.name} holds {words} words, and the "
                              f"journal takes {most}", path, severity=WARN,
                              hint="shorten the statements' text in the brief"))  # fmt: skip
    labels = len({one.statement for one in drawn if one.statement}) + sum(
        1 for one in drawn if not one.statement)
    most = rules.get("max_labels")
    if isinstance(most, int) and labels > most:
        found.append(_finding("comm-ga-labels", f"{path.name} holds {labels} labels (a "
                              "statement drawn, or a text of its own), and the journal takes "
                              f"{most}", path, severity=WARN,
                              hint="leave statements out of the brief's panels"))  # fmt: skip
    return found


def _drawn_numbers(context: Context, path: Path, text: str) -> list[Finding]:
    """`comm-number-unbound` for a number of the image's text that is no value's display
    and no convention, as G3 reads a figure's."""
    from manuscript_guard.gates.figures import _allowed, _signed

    allowed = _allowed(value.display for value in context.namespace.values())
    scan = context.classifier.scan(text, lines_are_blocks=True)
    found = []
    for atom in find_atoms(text, text):
        signed = _signed(atom.text)
        if signed in allowed or signed.replace(",", "") in allowed:
            continue
        if context.classifier.classify(atom, None, scan).kind != UNCLASSIFIED:
            continue
        found.append(_finding("comm-number-unbound", f"{atom.text!r} is drawn in {path.name} "
                              "and is no value of the results", path,
                              context=atom.line_text.strip()[:160],
                              hint="draw it from a statement that binds the value"))  # fmt: skip
    return found


def _drawn_story(context: Context, path: Path, drawn: list[_Drawn]) -> list[Finding]:
    brief = context.brief
    if brief is None or not any(one.statement for one in drawn):
        return []
    primary = {one.id for one in brief.primary}
    if not primary:
        return []
    found = []
    named = {one.statement for one in drawn}
    if not primary & named:
        found.append(_finding("comm-primary-missing", f"{path.name} draws no primary finding "
                              f"of the brief ({', '.join(sorted(primary))})", path,
                              hint="draw it again (`communicate graphical-abstract`)"))  # fmt: skip
    findings = {one.id for one in brief.of("findings")}
    largest = max((one for one in drawn if one.statement in findings),
                  key=lambda one: one.size, default=None)  # fmt: skip
    if largest is not None and largest.statement not in primary and not any(
            one.size >= largest.size for one in drawn if one.statement in primary):  # fmt: skip
        found.append(_finding("comm-secondary-as-primary", f"{path.name} draws "
                              f"{largest.statement}, a secondary finding, larger than the "
                              "primary one", path, severity=WARN,
                              hint="the primary finding is the one a reader sees first"))
    return found


def _pdf_text(context: Context, path: Path) -> list[Finding]:
    from manuscript_guard.gates.figures import _extract_text

    text = _extract_text(path)
    if not text:
        return []
    return _drawn_numbers(context, path, text)


def _alt(context: Context, rules: dict) -> list[Finding]:
    from manuscript_guard.gates.figure_alt import alt_text_findings, printed_alt

    path = graphical_abstract_folder(context.project) / ALT_TEXT
    if not path.is_file() or not read_text(path).strip():
        return [_finding("comm-alt-missing", "the graphical abstract has no alternative text, "
                         "and a screen reader reads nothing else of it", path, severity=WARN,
                         hint="write it in alt-text.md: what it shows and its main message, "
                         "the values by binding; `communicate graphical-abstract` writes one")]
    raw = read_text(path)
    found = [replace(one, gate=GATE) for one in alt_text_findings(
        "graphical abstract", raw, path, context.classifier, context.namespace)]  # fmt: skip
    longest = rules.get("alt_text_max_chars")
    shown = printed_alt(raw, context.namespace)
    if isinstance(longest, int) and len(shown) > longest:
        found.append(_finding("comm-alt-long", f"the graphical abstract's alternative text is "
                              f"{len(shown)} characters printed, and the journal takes "
                              f"{longest}", path, severity=WARN, context=shown[:120],
                              hint="say what it shows and its main message, no more"))  # fmt: skip
    return found
