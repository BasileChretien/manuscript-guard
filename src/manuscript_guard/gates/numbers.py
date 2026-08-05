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

        report = report.merge(_interval_order(placeholders, namespace, path, text))

        # One scan of this file per rule, reused by every atom in it. Matching each rule
        # against a window around each atom re-read the same characters once per number.
        scan = classifier.scan(text)
        for atom in find_atoms(text, mask(text)):
            totals["atoms"] += 1
            # Where the number sits decides what some rules mean. `p < 0.05` under Methods
            # is the threshold the author chose in advance; the same characters in Results
            # are a finding, and were passing as a convention.
            verdict = classifier.classify(atom, chain_at(headings, atom.start), scan)
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
                        else _hint_for(atom)
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

        report = report.merge(_fenced_code(path, text, classifier, headings))

    report = report.merge(_paper_yaml_prose(project, classifier))
    report = report.merge(_emitted_tables(results, classifier))
    report = report.merge(_declared_intervals(namespace))

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


def _fenced_code(path: Path, text: str, classifier: Classifier, headings=()) -> Report:
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
                # A listing inside a manuscript sits under real headings, so a `p < 0.001`
                # printed from one in the Results is a finding. A figure legend has no
                # heading chain and keeps every rule, which is why this is passed rather
                # than assumed.
                section=chain_at(headings, fence.start),
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


#: A sentence, for judging whether two bindings are quoted as one interval. Line breaks do
#: not end one: every manuscript here is hard-wrapped.
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def _interval_order(placeholders, namespace: dict[str, Value], path: Path, text: str) -> Report:
    """The bounds of one interval must be quoted low first.

    `{{results.ror.ci_high}} to {{results.ror.ci_low}}` resolves cleanly: both keys exist,
    neither is a literal, every gate passes — and the paper prints "3.84 (95% CI 7.02 to
    2.10)". Three keys named point, ci_low and ci_high are three unrelated numbers as far as
    any check is concerned, which is why `interval()` records which end each bound is.

    The table path has refused a typed composite cell since round two, on the grounds that
    "a point estimate and its bounds can be transposed and still pass". Prose is where that
    sentence actually gets written.

    Judged per sentence, because two intervals quoted in successive sentences say nothing
    about each other, and a paper may legitimately give the upper bound alone. And per level
    within a sentence, because "3.84 (95% CI 2.10 to 7.02; 90% CI 2.51 to 5.87)" is one
    sentence carrying two intervals, and the 90% lower bound follows the 95% upper one
    perfectly correctly.
    """
    report = Report()
    quoted = [
        (placeholder, namespace[placeholder.ref])
        for placeholder in placeholders
        if placeholder.is_value and placeholder.ref in namespace
    ]
    by_sentence: dict[int, list] = {}
    for placeholder, value in quoted:
        if not value.bounds:
            continue
        ends = [match.start() for match in _SENTENCE_END.finditer(text, 0, placeholder.start)]
        by_sentence.setdefault(len(ends), []).append((placeholder, value))

    for group in by_sentence.values():
        seen: dict[str, int] = {}
        for placeholder, value in group:
            if value.bound is None:
                continue
            # First mention wins. The guard used to read `value.bound in seen` while the keys
            # were `"{bounds}:{bound}"`, so it never matched and every later mention
            # overwrote the position. That cut both ways: a correctly ordered interval whose
            # lower bound is restated later in the same sentence — "2.10 to 7.02, and the
            # lower bound of 2.10 excludes unity" — was reported as reversed, and a genuinely
            # reversed one restated the other way round went unreported.
            seen.setdefault(f"{value.bounds}@{value.level or ''}:{value.bound}", placeholder.start)
        for estimate, level in {(value.bounds, value.level or "") for _p, value in group}:
            low = seen.get(f"{estimate}@{level}:low")
            high = seen.get(f"{estimate}@{level}:high")
            if low is None or high is None or low < high:
                continue
            named = f"the {level} interval" if level else "the interval"
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="interval-reversed",
                    message=f"{named} around {estimate} is quoted upper bound first, "
                    f"so it will print backwards",
                    path=path,
                    line=text.count("\n", 0, high) + 1,
                    hint="write the lower bound first; both bindings resolve either way, "
                    "which is why nothing else catches this",
                )
            )
    return report


def _declared_intervals(namespace: dict[str, Value]) -> Report:
    """A bound must bracket the estimate it says it bounds.

    `interval()` already refuses `low <= point <= high` when it fails — but only there, and
    the results fragment is a contract with three other writers: `value(bounds=…)` called
    directly, the R emitter, and a hand-edited JSON file. Any of them could publish

        ror.point 12.00, ror.ci_low 2.10, ror.ci_high 7.02

    and `check` was silent, because the bracketing lived in one Python helper rather than in
    the file every gate reads. A point estimate outside its own confidence interval is the
    single most visible arithmetic error a reader can catch in a disproportionality paper.

    Checked here rather than at load time so it reads as a finding an author can see beside
    the others, and so one broken interval does not stop the rest of the run.

    Grouped by `(estimate, level)`, so an estimate carrying a 90% interval beside its 95% one
    has two intervals checked rather than one interval with four ends. Both must bracket the
    estimate; neither is compared with the other, because a 90% interval nested inside a 95%
    one is correct.
    """
    report = Report()
    intervals: dict[tuple[str, str], dict[str, Value]] = {}
    for value in namespace.values():
        if not value.bounds or not value.bound:
            continue
        target = f"{value.namespace}.{value.bounds}"
        if target not in namespace:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="bound-dangling",
                    message=f"{value.key!r} declares itself a bound of {value.bounds!r}, "
                    f"which no source publishes",
                    path=value.source,
                    hint="emit the estimate and its interval together with interval(), which "
                    "writes all three keys and cannot get this wrong",
                )
            )
            continue
        ends = intervals.setdefault((target, value.level or ""), {})
        if value.bound in ends:
            named = f" {value.level}" if value.level else ""
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="bound-duplicated",
                    message=f"{ends[value.bound].key!r} and {value.key!r} both declare "
                    f"themselves the{named} {value.bound} bound of {value.bounds!r}",
                    path=value.source,
                    hint="one of the two is the other end; an interval has one of each. A "
                    "second interval on the same estimate needs its own `level=`",
                )
            )
            continue
        ends[value.bound] = value

    for (target, level), ends in sorted(intervals.items()):
        about = f"the {level} interval around" if level else "the interval around"
        point = namespace[target]
        low, high = ends.get("low"), ends.get("high")
        declared = [v for v in (point, low, high) if v is not None]
        # A bound of something that is not a number cannot be compared, and saying nothing
        # would make that indistinguishable from having compared it — the failure this whole
        # section exists to remove one level down.
        unusable = [
            v.key
            for v in declared
            if isinstance(v.value, bool) or not isinstance(v.value, (int, float))
        ]
        if unusable:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="bound-uncheckable",
                    message=f"{about} {point.key!r} cannot be checked: "
                    f"{', '.join(sorted(unusable))} is not a number",
                    path=point.source,
                    hint="emit the estimate and its bounds as numbers with `digits=`; a value "
                    "already rendered as a string cannot be compared with anything",
                )
            )
            continue
        if low is not None and high is not None and float(low.value) > float(high.value):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="interval-inverted",
                    message=f"{about} {point.key!r} runs {low.display} to "
                    f"{high.display}: its lower bound is above its upper bound",
                    path=low.source or point.source,
                    hint="the two are swapped at the point they are computed; naming them "
                    "low and high in the analysis does not make them so",
                )
            )
            continue
        for end, value in (("low", low), ("high", high)):
            if value is None:
                continue
            outside = (
                float(value.value) > float(point.value)
                if end == "low"
                else float(value.value) < float(point.value)
            )
            if not outside:
                continue
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="estimate-outside-interval",
                    message=f"{point.key} is {point.display}, outside "
                    f"{'its ' + level if level else 'its own'} interval: the "
                    f"{end} bound is {value.display}",
                    path=point.source,
                    hint="a reader checks this one by eye in the first sentence of the "
                    "Results; interval() refuses it, so this was written some other way",
                )
            )
    return report.with_counts(intervals_checked=len(intervals))


_GENERIC_HINT = (
    "bind it with {{results.<key>}} or {{lit.<key>}}; if it is a writing convention, add it "
    "to `conventions:` in paper.yaml with a justification"
)

_DATE = re.compile(
    r"(?i)\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
)

_DURATION = re.compile(
    r"(?i)\b\d+(?:\.\d+)?\s*(?:days?|weeks?|months?|years?|hours?)\b"
    r"|\b(?:follow[\s-]?up|washout|wash[\s-]?out|risk\s+window|lag|induction|latency|"
    r"look[\s-]?back|baseline\s+period|enrolment|enrollment|censor\w*|grace\s+period)\b"
)


def _hint_for(atom) -> str:
    """A hint that names the thing the author is looking at.

    "Bind it with {{results.<key>}}" is true of every unbound number and useful for almost
    none of them: an author who has just written a study period does not think of a date as
    a result, so the generic hint reads as the tool not understanding the sentence. Dates
    and design parameters are the two that come up in every observational paper, and both
    have a specific answer.
    """
    window = atom.window
    if _DATE.search(window):
        return (
            "a date is one placeholder, not one per number in it: emit it as a string with "
            'a display — em.value("period.start", "2015-01-01", display="1 January 2015") — '
            "and write {{results.period.start}}. A study period is a fact about the data, so "
            "it should come from the data"
        )
    if _DURATION.search(window):
        return (
            "a follow-up window, washout or censoring horizon is a design parameter the "
            "analysis also uses: emit it from the script that applies it, so the prose and "
            "the code cannot drift. If it is a reported duration rather than a chosen one, "
            "it is a result like any other"
        )
    return _GENERIC_HINT


def _emitted_tables(results: Results, classifier: Classifier) -> Report:
    """The same rule the emitter applies, applied to what is actually on disk.

    "Tables are emitted, not written" rested entirely on a check inside the Python emitter,
    which held for exactly as long as Python was the only language that could emit a table.
    A rule enforced in one emitter is a rule an author steps around by switching language,
    and the results fragment is meant to be a cross-language contract — so the check has to
    be answerable from the fragment.

    It also turns the guarantee from trusted into verified. A fragment written by hand, or
    re-signed after an edit, or produced by an emitter nobody here has seen, is judged the
    same way as one this package wrote a second ago.
    """
    from manuscript_guard.tables import problems_in

    report = Report()
    if not results.tables:
        return report

    # Published values only. Folding every composed cell's `parts` into one set let a
    # single entry anywhere in the project whitelist its strings everywhere, including from
    # a table with no rows at all. A composed cell's parts excuse that cell alone, and
    # `tables.rebuilt` is what checks they really produced it.
    known = {value.display for value in results.values.values()}
    known.discard("")
    known |= {shown.replace(",", "") for shown in known}

    for key, table in results.tables.items():
        spec = {
            "columns": list(table.columns),
            "rows": [list(row) for row in table.rows],
            "caption": table.caption,
            "composed": list(table.composed),
        }
        for problem in problems_in(key, spec, known, classifier, results.code_lists):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code=problem.code,
                    message=f"{problem.where}: {problem.message}",
                    path=table.source,
                    hint="emit the table from the analysis rather than editing the fragment; "
                    "a cell nothing published is a number with no origin",
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
