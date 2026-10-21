"""G3 — each figure says what it shows to a reader who cannot see it.

A screen reader reads a picture's alternative text, and nothing else of it. More journals
ask for one with each figure, in the manuscript's own file or in a box of the portal, and
Word and PDF carry it with the picture. The build placed every figure as `![](path)`, so
every document went out with none.

A figure's alternative text is written once, in its `<name>.guard.yaml` under `alt:`, beside
its print width and kind. It may quote values by binding, `{{results.ror.point}}`, as prose
does, and the build writes it as the picture's description in Word. A number typed into it
is held as prose's is: one that is a result, typed, is stale in waiting.

* `figure-alt-missing`: a figure the manuscript places has no alternative text. A note while
  drafting, a warning from internal review, and a failure at submission where the journal's
  profile says it requires one (`figures.alt_text: required`); a note at every stage where
  the profile applies its artwork rules from acceptance.
* `figure-alt-long`: the text is longer than the journal takes (`alt_text_max_chars`), counted
  as the build prints it, with each binding's display. A note while drafting, then a
  warning; a note at every stage where the profile applies its rules from acceptance.
* `figure-alt-number`: a number in it is bound to nothing and is not a convention, a label or
  a declared term, as G2 would say of it in prose; or it types a parameter, a software
  version or a dictionary's release the analysis declares.
* `figure-alt-binding`: a binding in it names a value nothing emits, or is a table, a figure
  or an anchor, which print no words.

An HTML comment in the text is printed by the build, and its bindings and numbers are read
like the rest. The prose's mask still hides a link's target, a URL, a citation key and
attributes in it, which the build prints as written. Whether
the text says what the figure shows is not checked: that is the figure review's, and a
person's (`readable-and-accessible`).
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.tokens import find_atoms

GATE = "G3"
#: What a figure's sidecar calls its alternative text.
KEY = "alt"
#: Every ASCII punctuation character, each of which pandoc's Markdown reads as itself after
#: a backslash (its `all_symbols_escapable`), and some of which it reads as markup without
#: one: `*` as emphasis, `[` as a link, `@` as a citation, `$` as maths, `"` as a quotation
#: mark it curls.
_PUNCTUATION = re.compile(r"([!-/:-@\[-`{-~])")
#: The white space folded to one space: ASCII's alone. A no-break space the author typed,
#: "10 mg", is printed as typed.
_SPACE = re.compile(r"[ \t\r\n\f\v]+")
#: What stands for the `<` that opens a comment while the text is read, so that no comment
#: is read in it: the build prints one as written. One character for one, so every offset
#: holds, and a `<` that opens no comment, `p < 0.05`, is left as it is.
_NOT_A_COMMENT = "\N{SINGLE LEFT-POINTING ANGLE QUOTATION MARK}"


def sidecar_of(project: Project, name: str) -> Path:
    return project.path("figures") / f"{name}.guard.yaml"


def raw_alt(project: Project, name: str) -> str | None:
    """The alternative text a figure's sidecar gives, as written; None where it gives none,
    or something that is not text."""
    from manuscript_guard.gates.figure_files import _sidecar

    said = _sidecar(sidecar_of(project, name)).get(KEY)
    return said if isinstance(said, str) and said.strip() else None


def alt_texts(project: Project) -> list[tuple[str, Path, str]]:
    """Each figure the manuscript places that has alternative text: its name, its sidecar
    and the text as written. For the checks that read what the build prints from it."""
    from manuscript_guard.gates.figure_files import _placed

    found = []
    for name, _supplementary in _placed(project):
        raw = raw_alt(project, name)
        if raw is not None:
            found.append((name, sidecar_of(project, name), raw))
    return found


def literal(raw: str) -> str:
    """`raw` as the checks read it: the `<` of each `<!` replaced by a character that opens
    nothing, so that a comment's bindings and numbers are read, as the build prints them."""
    return raw.replace("<!", _NOT_A_COMMENT + "!")


def fold(text: str) -> str:
    return _SPACE.sub(" ", text).strip(" \t\r\n\f\v")


def printed_alt(raw: str, namespace: dict[str, Value]) -> str:
    """The text as the build prints it: each value binding its display, an anchor nothing,
    anything else left as written, and its ASCII white space folded to single spaces."""
    placeholders, _ = parse(literal(raw))
    out = raw
    for placeholder in sorted(placeholders, key=lambda p: p.start, reverse=True):
        if placeholder.is_anchor:
            replacement = ""
        elif placeholder.is_value and placeholder.ref in namespace:
            replacement = namespace[placeholder.ref].display
        else:
            continue
        out = out[: placeholder.start] + replacement + out[placeholder.end :]
    return fold(out)


def as_markdown(text: str) -> str:
    """`text` written so that pandoc reads it back as exactly that text: every ASCII
    punctuation character escaped, and its white space folded to single spaces, since a
    picture's description is one line."""
    return _PUNCTUATION.sub(r"\\\1", fold(text))


def alt_markdown(project: Project, name: str, namespace: dict[str, Value]) -> str | None:
    """The figure's alternative text as the build writes it into the image's description,
    or None where it has none."""
    raw = raw_alt(project, name)
    return None if raw is None else as_markdown(printed_alt(raw, namespace))


def check_figure_alt(project: Project, namespace: dict[str, Value], stage: str) -> Report:
    """Each figure the manuscript places, for its alternative text."""
    from manuscript_guard.gates.figure_files import _placed
    from manuscript_guard.gates.journal import figure_rules
    from manuscript_guard.policy import INTERNAL_REVIEW, SUBMISSION, stage_index

    rules = figure_rules(project)
    # Where the journal applies its artwork rules once the paper is accepted, as G4 reads it.
    early = (stage_index(stage) < stage_index(INTERNAL_REVIEW)
             or rules.get("applies_from") == "acceptance")  # fmt: skip
    classifier = Classifier.load(project.extra_conventions, project.extra_terms)
    findings: list[Finding] = []
    placed = _placed(project)
    for name, supplementary in placed:
        own = rules.get("supplementary") if supplementary else None
        held = {**rules, **own} if isinstance(own, dict) else rules
        sidecar = sidecar_of(project, name)
        raw = raw_alt(project, name)
        if raw is None:
            required = held.get("alt_text") == "required"
            severity = INFO if early else FAIL if required and stage == SUBMISSION else WARN
            findings.append(_missing(name, sidecar, severity, required))
            continue
        findings += _bindings(name, raw, sidecar, namespace)
        findings += _numbers(name, raw, sidecar, classifier, namespace)
        longest = held.get("alt_text_max_chars")
        printed = printed_alt(raw, namespace)
        if isinstance(longest, int) and not isinstance(longest, bool) and len(printed) > longest:
            findings.append(
                Finding(
                    gate=GATE,
                    code="figure-alt-long",
                    severity=INFO if early else WARN,
                    message=f"the alternative text of figure {name!r} is {len(printed)} "
                    f"characters, and the journal takes {longest}",
                    path=sidecar,
                    context=printed[:120],
                    hint="say what the figure shows and its main message, and leave the "
                    "detail to the legend and the text",
                )
            )
    report = Report(tuple(findings))
    if not placed:
        return report
    return report.with_counts(
        figures_with_alt=sum(1 for name, _ in placed if raw_alt(project, name) is not None)
    )


def _missing(name: str, sidecar: Path, severity: str, required: bool) -> Finding:
    asks = "the journal requires one" if required else "a screen reader reads nothing else"
    return Finding(
        gate=GATE,
        code="figure-alt-missing",
        severity=severity,
        message=f"figure {name!r} has no alternative text, and {asks}",
        path=sidecar,
        hint=f"write it in {sidecar.name} under `alt:`: what the figure shows and its main "
        "message, in a sentence or two, not 'a figure'; quote a result by binding, "
        + "{{results.key}}; the figure-review skill has a note on writing it",
    )


def _bindings(name: str, raw: str, sidecar: Path, namespace: dict[str, Value]) -> list[Finding]:
    placeholders, malformed = parse(literal(raw))
    found = []
    for placeholder in placeholders:
        if placeholder.is_value and placeholder.ref in namespace:
            continue
        if placeholder.is_value:
            why = "names a value nothing emits"
        else:
            why = "prints no words: a table, a figure or an anchor has no place in it"
        found.append(_binding(name, placeholder.raw, why, sidecar))
    found += [_binding(name, text, "is not a binding pandoc's build reads", sidecar)
              for text, _start, _line in malformed]  # fmt: skip
    return found


def _binding(name: str, text: str, why: str, sidecar: Path) -> Finding:
    return Finding(
        gate=GATE,
        code="figure-alt-binding",
        message=f"in the alternative text of figure {name!r}, {text} {why}",
        path=sidecar,
        context=text,
        hint="quote a value the analysis emits, {{results.key}} or {{lit.key}}; "
        "`manuscript-guard bind` lists the keys",
    )


def _numbers(
    name: str, raw: str, sidecar: Path, classifier: Classifier, namespace: dict[str, Value]
) -> list[Finding]:
    """Each number typed into the text that G2 would not pass in prose: one bound to nothing
    that no rule accepts, and one that types a declared parameter, a software version or a
    dictionary's release (`gates/numbers.py`). Bindings are taken out by the mask before the
    numbers are looked for."""
    from manuscript_guard.gates.numbers import chosen_rules, typed_choice, typed_releases

    choices = [value for value in namespace.values() if value.role]
    dictionaries = [value for value in choices if value.role == "dictionary"]
    chosen = chosen_rules(classifier)
    text = literal(raw)
    releases = typed_releases(text, dictionaries)
    context = fold(raw)[:120]
    found = []
    for atom in find_atoms(text, mask(text)):
        release = next((value for start, end, value in releases
                        if start <= atom.start < end), None)  # fmt: skip
        verdict = classifier.classify(atom)
        typed = release or (
            None if verdict.kind == UNCLASSIFIED
            else typed_choice(atom.text, verdict, choices, chosen)
        )
        if typed is not None:
            why = f"types {typed.key}, which the analysis declares"
            hint = f"quote it by binding, {typed.reference}, so the text follows the analysis"
        elif verdict.kind == UNCLASSIFIED:
            why = "is bound to nothing"
            hint = ("quote the result by binding, {{results.key}}, so the text cannot disagree "
                    "with the analysis; a number that is no result is declared in paper.yaml, "
                    "as prose's are")  # fmt: skip
        else:
            continue
        found.append(
            Finding(
                gate=GATE,
                code="figure-alt-number",
                message=f"{atom.text!r} in the alternative text of figure {name!r} {why}",
                path=sidecar,
                context=context,
                hint=hint,
            )
        )
    return found
