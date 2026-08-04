"""G2 — every number in the manuscript source is accounted for, in both directions.

Forward: no numeric atom in any source file may be unclassified. A results-derived number
cannot appear as a literal, because in source it must be a `{{results.key}}` placeholder.

Backward: every results value declared as quoted must actually be referenced somewhere. A
registry that binds a handful of numbers and reports "all clear" is worse than no registry,
because it converts an unexamined manuscript into a confident one. Coverage is therefore
part of the gate rather than a footnote in its output.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts.literature import Literature
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.sections import section_chain
from manuscript_guard.text.tokens import find_atoms

GATE = "G2"
SOURCE_GLOB = "*.md"


def source_files(manuscript_dir: Path) -> list[Path]:
    """Every Markdown source, skipping directories whose name starts with `_` or `.`.

    The underscore convention gives an author somewhere to keep notes and abandoned drafts
    without either polluting the report or being silently exempted from it: the rule is
    visible in the directory name.
    """
    if not manuscript_dir.exists():
        return []
    out = []
    for path in sorted(manuscript_dir.rglob(SOURCE_GLOB)):
        if any(part.startswith((".", "_")) for part in path.relative_to(manuscript_dir).parts):
            continue
        out.append(path)
    return out


def check_numbers(
    project: Project,
    namespace: dict[str, Value],
    results: Results,
    literature: Literature,
) -> Report:
    classifier = Classifier.load(project.extra_conventions, project.extra_terms)
    report = Report()
    referenced: set[str] = set()
    totals = dict.fromkeys(
        ("files", "atoms", "placeholders", "term", "structural", "convention", "project"), 0
    )
    # What the project's own allowlist accounted for, and which entries did it. Reported
    # every run: `conventions:` and `terms:` are self-service on purpose, but a project that
    # exempts half its numbers should not read exactly like one that exempts none.
    by_project: dict[str, int] = {}

    for path in source_files(project.path("manuscript")):
        totals["files"] += 1
        text = path.read_text(encoding="utf-8")

        placeholders, malformed = parse(text)
        totals["placeholders"] += len(placeholders)

        for raw, _offset, line in malformed:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="malformed-placeholder",
                    message=f"{raw} is not a valid binding and will be printed literally",
                    path=path,
                    line=line,
                    hint="the form is {{results.key}}, {{lit.key}}, {{table.key}} "
                    "or {{figure.key}}",
                )
            )

        for placeholder in placeholders:
            referenced.add(placeholder.ref)
            if placeholder.is_value and placeholder.ref not in namespace:
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="unresolved-binding",
                        message=f"{placeholder.raw} refers to a key that does not exist",
                        path=path,
                        line=placeholder.line,
                        col=placeholder.col,
                        hint=_nearest_hint(placeholder.ref, namespace),
                    )
                )

        for atom in find_atoms(text, mask(text)):
            totals["atoms"] += 1
            # Where the number sits decides what some rules mean. `p < 0.05` under Methods
            # is the threshold the author chose in advance; the same characters in Results
            # are a finding, and were passing as a convention.
            verdict = classifier.classify(atom, section_chain(text, atom.start))
            if verdict.kind != UNCLASSIFIED:
                totals[verdict.kind] += 1
                if classifier.is_project_exemption(verdict):
                    totals["project"] += 1
                    label = verdict.rule if verdict.rule != "terms" else f"terms: {verdict.detail}"
                    by_project[label] = by_project.get(label, 0) + 1
                continue
            in_table = atom.line_text.lstrip().startswith("|")
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="hand-authored-table" if in_table else "unclassified-number",
                    message=(
                        f"{atom.text!r} in a hand-written table row"
                        if in_table
                        else f"{atom.text!r} is not bound to any source"
                    ),
                    path=path,
                    line=atom.line,
                    col=atom.col,
                    context=atom.line_text.strip()[:160],
                    hint=(
                        "tables are generated from results; replace the table with "
                        "{{table.<key>}} and emit it from the analysis"
                        if in_table
                        else "bind it with {{results.<key>}} or {{lit.<key>}}; if it is a "
                        "writing convention, add it to `conventions:` in paper.yaml with a "
                        "justification"
                    ),
                )
            )

        report = report.merge(_fenced_code(path, text, classifier))

    if by_project:
        listed = "; ".join(
            f"{rule} ({count})" for rule, count in sorted(by_project.items(), key=lambda i: -i[1])
        )
        share = totals["project"] / totals["atoms"] if totals["atoms"] else 0
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="project-exemption",
                severity=WARN if share >= 0.25 else INFO,
                message=f"{totals['project']} of {totals['atoms']} numbers were accepted by "
                f"this project's own `conventions:` or `terms:`, not by the shipped rules — "
                f"{listed}",
                hint="that is what those settings are for, but a large share means the gate "
                "is mostly agreeing with the project about itself; worth a look in review",
            )
        )

    report = report.merge(_coverage(results, literature, referenced))
    return report.with_counts(
        source_files=totals["files"],
        numeric_atoms=totals["atoms"],
        bindings=totals["placeholders"],
        atoms_term=totals["term"],
        atoms_structural=totals["structural"],
        atoms_convention=totals["convention"],
        atoms_project_exempt=totals["project"],
    )


_FENCE = re.compile(
    r"^[ \t]*(?P<tick>`{3,}|~{3,})(?P<lang>[^\n]*)\n(?P<body>.*?)^[ \t]*(?P=tick)[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


def _fenced_code(path: Path, text: str, classifier: Classifier) -> Report:
    """Numbers inside a fenced block, judged as code rather than as prose.

    A listing renders, so it cannot go unchecked — but its numbers are code. Read as prose
    they produced eleven failures on one honest `## Statistical analysis` section: a `1.96`,
    a seed, a slice index, a package version. That is friction on correct writing, which is
    how a gate comes to be switched off, and the documented escape is `conventions:` — the
    one mechanism that makes G2 vacuous.

    So the same reader G3 uses on figure scripts runs here. A number in a string literal is
    a claim, because that is text the listing prints; a loop bound, an index or an argument
    is not. A block whose language the lexer does not know is left alone and said to be
    left alone, rather than passed over in silence.
    """
    from manuscript_guard.gates.figure_source import judge_code_numbers

    report = Report()
    for match in _FENCE.finditer(text):
        tag = match.group("lang").strip()
        language = tag.split()[0].lower() if tag else ""
        line = text.count("\n", 0, match.start()) + 1
        report = report.merge(
            judge_code_numbers(
                match.group("body"),
                language,
                path=path,
                line_offset=text.count("\n", 0, match.start("body")),
                gate=GATE,
                classifier=classifier,
                what=f"fenced block at line {line}",
            )
        )
    return report


def _coverage(results: Results, literature: Literature, referenced: set[str]) -> Report:
    """Direction two: declared values that nothing quotes."""
    report = Report()
    unquoted = sorted(k for k in results.quoted_keys if f"results.{k}" not in referenced)
    for key in unquoted:
        value = results.values[key]
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="unquoted-result",
                message=f"results key {key!r} is declared as quoted but nothing references it",
                path=value.source,
                hint=(
                    "reference it as {{results." + key + "}}, or mark it quoted=false in the "
                    "analysis to declare it an intermediate"
                ),
            )
        )

    unplaced = sorted(k for k in results.quoted_tables if f"table.{k}" not in referenced)
    for key in unplaced:
        table = results.tables[key]
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="unplaced-table",
                message=f"table {key!r} is emitted but no source file places it",
                path=table.source,
                hint="write {{table." + key + "}} where it belongs, or emit it with "
                "quoted=False if it is working output",
            )
        )

    unused = sorted(k for k in literature.values if f"lit.{k}" not in referenced)
    for key in unused:
        value = literature.values[key]
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="unused-literature",
                severity=WARN,
                message=f"literature key {key!r} is never quoted",
                path=value.source,
                hint="remove the entry, or quote it",
            )
        )

    return report.with_counts(
        results_quoted=len(results.quoted_keys),
        results_uncovered=len(unquoted),
        tables_unplaced=len(unplaced),
        literature_unused=len(unused),
    )


def _nearest_hint(ref: str, namespace: dict[str, Value]) -> str:
    """Suggest the closest existing key, which is almost always a typo fix."""
    import difflib

    close = difflib.get_close_matches(ref, namespace.keys(), n=3, cutoff=0.6)
    if close:
        return "did you mean " + ", ".join("{{" + c + "}}" for c in close) + "?"
    return "check the key exists in results/ or literature/"
