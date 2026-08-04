"""G2 — every number in the manuscript source is accounted for, in both directions.

Forward: no numeric atom in any source file may be unclassified. A results-derived number
cannot appear as a literal, because in source it must be a `{{results.key}}` placeholder.

Backward: every results value declared as quoted must actually be referenced somewhere. A
registry that binds a handful of numbers and reports "all clear" is worse than no registry,
because it converts an unexamined manuscript into a confident one. Coverage is therefore
part of the gate rather than a footnote in its output.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts.literature import Literature
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.text.fences import fenced_spans
from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.sections import chain_at, heading_index
from manuscript_guard.text.tokens import find_atoms

GATE = "G2"
SOURCE_GLOB = "*.md"

# Unbound numbers reported per file before the rest are counted rather than listed.
#
# Nobody reads twenty thousand findings, and building them was quadratic — each one copied
# the whole findings tuple, so a file of 20,000 loose numbers took 72 seconds inside a
# command that is supposed to be safe to run on a manuscript someone sent you. Capping is
# also the honest shape: the count is still exact and the overflow says so, which is the
# same rule the AI-writing lint follows for a repeated phrase.
PER_FILE_CAP = 50


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
        loose = 0
        headings = heading_index(text)

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
            verdict = classifier.classify(atom, chain_at(headings, atom.start))
            if verdict.kind != UNCLASSIFIED:
                totals[verdict.kind] += 1
                if classifier.is_project_exemption(verdict):
                    totals["project"] += 1
                    label = verdict.rule if verdict.rule != "terms" else f"terms: {verdict.detail}"
                    by_project[label] = by_project.get(label, 0) + 1
                continue
            loose += 1
            if loose > PER_FILE_CAP:
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

        if loose > PER_FILE_CAP:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="unclassified-number",
                    message=f"{loose - PER_FILE_CAP} further unbound number(s) in "
                    f"{path.name}, not listed individually",
                    path=path,
                    hint="the first "
                    f"{PER_FILE_CAP} are above; a file in this state usually needs its "
                    "numbers bound in bulk rather than one finding at a time",
                )
            )

        report = report.merge(_fenced_code(path, text, classifier))

    report = report.merge(_paper_yaml_prose(project, classifier))

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
    for fence in fenced_spans(text):
        line = text.count("\n", 0, fence.start) + 1
        body = text[fence.body_start : fence.body_end]

        if fence.is_raw:
            # ```{=openxml} and friends are not listings. pandoc splices the contents into
            # the output verbatim, so this reaches the reader as formatted prose — and it
            # was being reported as "a language with no lexer", whose advice was to tag the
            # fence, which would only have made it quieter.
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="raw-block",
                    message=f"a raw {fence.info.strip()} block at line {line} is written "
                    f"straight into the built document, and nothing can read it",
                    path=path,
                    line=line,
                    context=body.strip()[:160],
                    hint="write it as Markdown so the gates can read it; a raw block is a "
                    "hole in every check this toolkit performs",
                )
            )
            continue

        report = report.merge(
            judge_code_numbers(
                body,
                fence.language,
                path=path,
                line_offset=text.count("\n", 0, fence.body_start),
                gate=GATE,
                classifier=classifier,
                what=f"fenced block at line {line}",
            )
        )
    return report


# Keys in paper.yaml that `build/document.py::_front_matter` writes into the YAML header
# pandoc receives. They render, so they are prose.
PAPER_PROSE = ("title", "short_title", "keywords")


def _paper_yaml_prose(project: Project, classifier: Classifier) -> Report:
    """Numbers in the front matter the *build* generates, which no gate read.

    Round one closed "front matter was masked whole" for `manuscript/*.md`. But the build
    synthesises a second YAML header from `paper.yaml` — `title`, `subtitle` from
    `short_title`, and `keywords` — and G2 only ever looked at `manuscript/`. So a
    `short_title` of "A 9.99-fold excess in 41 200 reports" arrived as a Subtitle-styled
    paragraph at the top of the .docx with `check` reporting nothing at all.

    The same classifier as prose, because that is what it becomes.
    """
    report = Report()
    for key in PAPER_PROSE:
        raw = project.paper.get(key)
        if not raw:
            continue
        for value in raw if isinstance(raw, list) else [raw]:
            text = str(value)
            for atom in find_atoms(text, mask(text)):
                if classifier.classify(atom, ("Title",)).kind != UNCLASSIFIED:
                    continue
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="unclassified-number",
                        message=f"{atom.text!r} in paper.yaml `{key}` is not bound to any source",
                        path=project.root / "paper.yaml",
                        context=text[:160],
                        hint="the build writes this into the document's front matter, where "
                        "pandoc renders it; bind it or reword the title",
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
