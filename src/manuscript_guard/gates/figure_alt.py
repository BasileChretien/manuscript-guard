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
  profile says it requires one (`figures.alt_text: required`).
* `figure-alt-long`: the text is longer than the journal takes (`alt_text_max_chars`), counted
  as the build prints it, with each binding's display. A note while drafting, then a warning.
* `figure-alt-number`: a number in it is bound to nothing and is not a convention, a label or
  a declared term, as G2 would say of it in prose.
* `figure-alt-binding`: a binding in it names a value nothing emits, or is a table, a figure
  or an anchor, which print no words.

Whether the text says what the figure shows is not checked: that is the figure review's,
and a person's (`readable-and-accessible`).
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


def sidecar_of(project: Project, name: str) -> Path:
    return project.path("figures") / f"{name}.guard.yaml"


def raw_alt(project: Project, name: str) -> str | None:
    """The alternative text a figure's sidecar gives, as written; None where it gives none,
    or something that is not text."""
    from manuscript_guard.gates.figure_files import _sidecar

    said = _sidecar(sidecar_of(project, name)).get(KEY)
    return said if isinstance(said, str) and said.strip() else None


def printed_alt(raw: str, namespace: dict[str, Value]) -> str:
    """The text as the build prints it: each value binding its display, an anchor nothing,
    anything else left as written, and its white space folded to single spaces."""
    placeholders, _ = parse(raw)
    out = raw
    for placeholder in sorted(placeholders, key=lambda p: p.start, reverse=True):
        if placeholder.is_anchor:
            replacement = ""
        elif placeholder.is_value and placeholder.ref in namespace:
            replacement = namespace[placeholder.ref].display
        else:
            continue
        out = out[: placeholder.start] + replacement + out[placeholder.end :]
    return " ".join(out.split())


def as_markdown(text: str) -> str:
    """`text` written so that pandoc reads it back as exactly that text: every ASCII
    punctuation character escaped, and its white space folded to single spaces, since a
    picture's description is one line."""
    return _PUNCTUATION.sub(r"\\\1", " ".join(text.split()))


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
    early = stage_index(stage) < stage_index(INTERNAL_REVIEW)
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
        findings += _numbers(name, raw, sidecar, classifier)
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
    placeholders, malformed = parse(raw)
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


def _numbers(name: str, raw: str, sidecar: Path, classifier: Classifier) -> list[Finding]:
    """Each number typed into the text that G2 would not pass in prose. Bindings are taken
    out by the mask before the numbers are looked for."""
    return [
        Finding(
            gate=GATE,
            code="figure-alt-number",
            message=f"{atom.text!r} in the alternative text of figure {name!r} is bound to "
            "nothing",
            path=sidecar,
            context=" ".join(raw.split())[:120],
            hint="quote the result by binding, {{results.key}}, so the text cannot disagree "
            "with the analysis; a number that is no result is declared in paper.yaml, as "
            "prose's are",
        )
        for atom in find_atoms(raw, mask(raw))
        if classifier.classify(atom).kind == UNCLASSIFIED
    ]
