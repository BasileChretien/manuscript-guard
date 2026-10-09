"""G2 — every number in the manuscript source is accounted for, in both directions.

Forward: no numeric atom in any source file may be unclassified. A results-derived number
cannot appear as a literal, because in source it must be a `{{results.key}}` placeholder.

Backward: every results value declared as quoted must actually be referenced somewhere. A
registry that binds a handful of numbers and reports "all clear" is worse than no registry,
because it converts an unexamined manuscript into a confident one. Coverage is therefore
part of the gate rather than a footnote in its output.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_left
from pathlib import Path

from manuscript_guard.classify import (
    CONVENTION,
    STRUCTURAL,
    UNCLASSIFIED,
    Classifier,
    Verdict,
    declarable,
)
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.literature import Literature
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import Value, number_in
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.roundtrip import splits_a_paragraph
from manuscript_guard.text.masking import (
    blank_comments,
    fenced_blocks,
    front_matter_abstract,
    front_matter_end,
    front_matter_problem,
    mask,
)
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.sections import chain_at, chains_at, footnote_index, heading_index
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


#: Everything under here is supplementary material: checked like the rest of the manuscript,
#: built as its own document, and not counted against the main text's limits. A directory
#: rather than a declaration, because that is how figures and results already work — and
#: because a heading can be renamed without anyone noticing what left the submission.
SUPPLEMENTARY = "supplementary"


def source_files(manuscript_dir: Path, *, main_text_only: bool = False) -> list[Path]:
    """Every Markdown source, skipping directories whose name starts with `_` or `.`.

    The underscore convention gives an author somewhere to keep notes and abandoned drafts
    without either polluting the report or being silently exempted from it: the rule is
    visible in the directory name.

    `main_text_only` drops `supplementary/`. Every gate that reads prose should read the
    supplement too — a fabricated number in a supplementary table is still fabricated — so
    this is for the two places that mean the main text specifically: the journal's word and
    display-item limits, and the count the title page declares to the editor.
    """
    if not manuscript_dir.exists():
        return []
    out = []
    for path in sorted(manuscript_dir.rglob(SOURCE_GLOB)):
        parts = path.relative_to(manuscript_dir).parts
        if any(part.startswith((".", "_")) for part in parts):
            continue
        if main_text_only and len(parts) > 1 and parts[0] == SUPPLEMENTARY:
            continue
        out.append(path)
    return out


def is_supplementary(manuscript_dir: Path, path: Path) -> bool:
    """Does this source belong to the supplement rather than to the paper?"""
    try:
        parts = Path(path).relative_to(manuscript_dir).parts
    except ValueError:
        return False
    return len(parts) > 1 and parts[0] == SUPPLEMENTARY


def printed_order(paths: list[Path], *, supplementary: bool) -> list[Path]:
    """The files of one document in the order the build prints them: the supplement's by
    file name, the main text's with `main.md` first and the rest by file name, whatever
    their paths sort as. Shared with the paragraph record, which reads what stands beside a
    paragraph across the files: read in path order, `1_methods.md` came before `main.md`,
    and the heading opening it was beside no paragraph it stands beside in Word."""
    if supplementary:
        return sorted(paths, key=lambda path: path.name)
    main = [path for path in paths if path.name == "main.md"]
    return main + sorted((path for path in paths if path.name != "main.md"), key=lambda p: p.name)


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
    choices = [value for value in namespace.values() if value.role]
    chosen = chosen_rules(classifier)
    declares = any(value.role == "parameter" for value in choices)

    for path in source_files(project.path("manuscript")):
        totals["files"] += 1
        text = read_text(path)
        loose = 0
        headings = heading_index(text)
        notes = footnote_index(text)

        # Read as prose until it is fixed, a `# Methods` in it heads a section here while
        # pandoc refuses the whole file; see `front_matter_problem`.
        problem = front_matter_problem(text)
        if problem is not None:
            report = report.with_findings(unreadable_header(path, *problem, GATE))
        # Read here and printed by nothing: the build strips the block.
        abstract = front_matter_abstract(text)
        if abstract is not None:
            report = report.with_findings(abstract_in_header(path, *abstract, GATE))

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
            elif placeholder.is_value and (what := _splits(namespace[placeholder.ref])):
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="value-splits-paragraph",
                        message=f"{placeholder.raw} prints {what} into its paragraph, where "
                        f"it can break the paragraph in parts in Word",
                        path=path,
                        line=placeholder.line,
                        col=placeholder.col,
                        hint="a value is printed inside a sentence; write what it holds in the "
                        ".md, as a block of its own, and bind only the numbers in it",
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
            # A footnote's text is judged where it stands and at every reference to it in
            # the same file, where pandoc prints it.
            verdict = classifier.classify_under(
                atom, chains_at(headings, notes, atom.start), scan
            )
            if verdict.kind != UNCLASSIFIED:
                totals[verdict.kind] += 1
                if classifier.is_project_exemption(verdict):
                    totals["project"] += 1
                    label = verdict.rule if verdict.rule != "terms" else f"terms: {verdict.detail}"
                    by_project[label] = by_project.get(label, 0) + 1
                typed = typed_choice(atom.text, verdict, choices, chosen)
                if typed is not None:
                    report = report.with_findings(_typed_finding(typed, atom, path))
                elif declares and verdict.kind == CONVENTION and verdict.rule in chosen:
                    report = report.with_findings(_undeclared_threshold(atom, path))
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
    report = report.merge(_unread_parameters(namespace))
    report = report.merge(_prose_as_value(namespace, referenced))

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
    head = front_matter_end(text)
    for fence in fenced_blocks(text):
        line = text.count("\n", 0, fence.start) + 1
        body = text[fence.body_start : fence.body_end]

        if fence.is_raw and fence.start < head:
            # The build strips the manuscript's front matter, so a raw block there - LaTeX
            # under `header-includes`, the usual one - reaches no document, and reporting it
            # as written straight into the build was a false alarm on every such paper.
            continue
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
                        hint=_how_to_declare(atom)
                        + "bind it or reword the title: the build writes this into the "
                        "document's front matter, where pandoc renders it",
                    )
                )
    return report


#: A sentence, for judging whether two bindings are quoted as one interval. Line breaks do
#: not end one: every manuscript here is hard-wrapped.
_STOPS = ".!?"
_SENTENCE_END = re.compile(rf"[{_STOPS}](?:\s|$)")


def _sentence(text: str, ends: list[int], start: int) -> int:
    """Which sentence of `text` the binding at `start` is in: how many end before it.

    `ends` is where the sentences of the whole text end, found once for the file. The count
    was a search from the top of the file for every bound, stopped at the binding: quadratic
    in the bounds of a file, 186 s for 20,000 of them. Stopped there, the search took the
    binding for the end of the text, so a stop typed against a binding ended a sentence
    with no white space after it. It still does, for that binding alone, which is what the
    last line adds: the bounds are grouped as they were, and DESIGN.md has the limit under
    Known gaps.
    """
    before = bisect_left(ends, start - 1)
    return before + 1 if start and text[start - 1] in _STOPS else before


def unreadable_header(path: Path, reason: str, line: int, gate: str) -> Finding:
    """A file that opens with a `---` block pandoc cannot read as YAML, and so refuses."""
    return Finding(
        gate=gate,
        code="front-matter-unreadable",
        message="the block at the top of this file opens like YAML front matter, and "
        "pandoc cannot read it as YAML, so it refuses to build the paper",
        path=path,
        line=line,
        context=reason,
        hint="fix the YAML, or close the header with `---` or `...` before the text "
        "starts; a line of dashes meant as a rule needs a blank line under it",
    )


def abstract_in_header(path: Path, line: int, words: str, gate: str) -> Finding:
    """An abstract in a file's front matter, which the build does not print.

    Refused rather than printed from the header: under an Abstract heading it prints, is
    counted against the journal's abstract limit, and carries the paragraph identifiers
    the Word import maps edits back with, like the rest of the text.
    """
    return Finding(
        gate=gate,
        code="front-matter-abstract",
        message=f"{path.name} has an abstract in its front matter, which the build does not print",
        path=path,
        line=line,
        context=words[:120],
        hint="move it out of the front matter and under a `# Abstract` heading, where "
        "the build prints it and the journal's abstract limit counts it",
    )


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
    bounds = [(placeholder, value) for placeholder, value in quoted if value.bounds]
    if not bounds:
        return report
    # The sentences are read where `parse` read the bindings: with each HTML comment
    # blanked. Pandoc drops a comment. Read as typed, a stop inside one ended a sentence
    # between two bounds, and a reversal there passed and was printed; and a stop with a
    # comment typed against it ended none, so the bounds of two sentences were compared.
    read = blank_comments(text) if "<!--" in text else text
    ends = [match.start() for match in _SENTENCE_END.finditer(read)]
    by_sentence: dict[int, list] = {}
    for placeholder, value in bounds:
        sentence = _sentence(read, ends, placeholder.start)
        by_sentence.setdefault(sentence, []).append((placeholder, value))

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
        # In the order each interval is first quoted. They were walked as a set, whose order
        # the hash seed of the process decides: two intervals reversed on one line changed
        # places in the report from one run of `check` to the next.
        intervals = dict.fromkeys((value.bounds, value.level or "") for _p, value in group)
        for estimate, level in intervals:
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


# Where the figure starts in an atom: `P<0.05` is one atom, and `.05` has no nought.
_FIGURE = re.compile(r"\d|\.\d")


def stated_number(text: str) -> float | None:
    """The number an atom states, read past what is typed before its figure: `P<0.05` and
    `p<.05` state 0.05. A sign is not read; a threshold has none."""
    at = _FIGURE.search(text)
    if at is None:
        return None
    figure = text[at.start() :]
    return number_in("0" + figure if figure.startswith(".") else figure)


def chosen_rules(classifier: Classifier) -> frozenset[str]:
    """The conventions that hold only in the Methods: the thresholds an author chooses in
    advance, which are the ones an analysis can declare as parameters."""
    return frozenset(rule.id for rule in classifier.conventions if rule.methods_only)


def typed_choice(
    text: str, verdict: Verdict, choices: list[Value], chosen: frozenset[str]
) -> Value | None:
    """The declared parameter or software version a typed number states, if it states one.

    A threshold typed in the Methods passes as a convention, and a version as the name of a
    thing. Once the analysis declares the value it ran with, a typed copy is the one that
    stays behind when the code changes, so it has to be bound. Only the Methods-only
    conventions are read for a parameter: "2" in "a 2 x 2 table" is the name of a structure
    whatever a parameter equals. A parameter is compared by the number it states, a version
    by its text.
    """
    if verdict.kind == CONVENTION and verdict.rule in chosen:
        stated = stated_number(text)
        if stated is None:
            return None
        for value in choices:
            if value.role == "parameter" and number_in(value.display) == stated:
                return value
    elif verdict.kind == STRUCTURAL and verdict.rule == "software-version":
        for value in choices:
            if value.role == "software" and value.display == text:
                return value
    return None


def _typed_finding(value: Value, atom, path: Path) -> Finding:
    if value.role == "software":
        code = "typed-software-version"
        what = f"the version of {value.key.removeprefix('software.')} this analysis ran with"
    else:
        code = "typed-parameter"
        what = f"the analysis parameter {value.key}"
    return Finding(
        gate=GATE,
        code=code,
        message=f"{atom.text!r} is {what}, typed rather than bound",
        path=path,
        line=atom.line,
        col=atom.col,
        context=atom.line_text.strip()[:160],
        hint=f"write {value.reference}: the analysis declares the value it ran with, and a "
        "typed copy is what stays behind when the code changes",
    )


def _undeclared_threshold(atom, path: Path) -> Finding:
    """A threshold typed in the Methods of an analysis that declares its parameters, and
    equal to none of them. Either the code chose it and does not say so, or the code chose
    another value and this is the copy left behind: the typed-parameter rule finds a copy
    only while it still agrees."""
    return Finding(
        gate=GATE,
        code="threshold-undeclared",
        severity=WARN,
        message=f"{atom.text!r} is a threshold typed in the Methods, and no parameter the "
        f"analysis declares has this value",
        path=path,
        line=atom.line,
        col=atom.col,
        context=atom.line_text.strip()[:160],
        hint="if the code applies it, declare it with parameter() and bind it; if the code "
        "applies another value, the Methods and the code disagree",
    )


def _unread_parameters(namespace: dict[str, Value]) -> Report:
    """A parameter the script declares and never reads describes a method it did not run.

    Binding it in the Methods would print the right number for a step that is not there:
    the example's signal criterion, at least 3 cases, was stated and never applied. What the
    emitter records is only whether the value handed back is read again, so this finds the
    parameter declared and forgotten, and not one read and then ignored.
    """
    report = Report()
    for value in namespace.values():
        if value.role == "parameter" and value.read is False:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="parameter-unread",
                    message=f"{value.key} is declared, and the analysis never reads the value "
                    f"parameter() handed back",
                    path=value.source,
                    hint="use the returned value in the step it stands for, or remove the "
                    "parameter: the Methods would state a choice the code never applied",
                )
            )
    return report


def _splits(value: Value) -> str | None:
    """What in a value's display would break the paragraph that prints it; None if nothing.

    Identifiers are given to the source before bindings are substituted, and a paragraph whose
    source holds display maths gets none (`roundtrip.splits_a_paragraph`). A value printing
    `$$y = 2.1 x$$` put it into a paragraph that had one: pandoc gave the equation a Word
    paragraph of its own, only the part before it carried the identifier, and a co-author's
    swap of that part moved the whole sentence in the .md. A line break is refused too: what
    can start on the next line - a blank line, a fence, a `<div>` - ends the paragraph there.
    """
    if "\n" in value.display or "\r" in value.display:
        return "a line break"
    return splits_a_paragraph(value.display)


def _prose_as_value(namespace: dict[str, Value], referenced: set[str]) -> Report:
    """A binding that substitutes words rather than a number.

        em.value("conclusion", "The drug causes liver failure and should be withdrawn")

    resolves, passes every gate, and is painted green in the annotated copy — "traced to a
    results value", the strongest thing that document says — on a sentence the author typed
    into an analysis script. It also leaves the manuscript sources, which is where G6 reads
    prose, so the writing lint never sees it either. Publishing a claim through the results
    file is the one route by which text escapes everything that reads text.

    A warning rather than a refusal, and judged on whether the display carries a digit rather
    than on whether it reads like a sentence. A drug name or a cohort label is a perfectly
    good thing to keep in one place, and `label=True` already means "this is a name, not a
    measurement" — so saying so is both the way out and a declaration on the record.
    """
    report = Report()
    for ref in sorted(referenced):
        value = namespace.get(ref)
        if value is None or value.label:
            continue
        if any(character.isdigit() for character in value.display):
            continue
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="prose-as-value",
                severity=WARN,
                message=f"{{{{{ref}}}}} substitutes words rather than a number: "
                f"{value.display[:60]!r}",
                path=value.source,
                hint="prose belongs in the manuscript, where the writing gate reads it and a "
                "reviewer sees it in context. If this is a name rather than a claim, emit it "
                "with label=True",
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


#: A name that YAML reads as it is written, between the brackets of `terms: [...]`.
_PLAIN_NAME = re.compile(r"[\w+./-]+")


def _how_to_declare(atom) -> str:
    """What to say first of an unbound atom where it reads as a name written with a
    subscript or a superscript (`classify.declarable`): how to declare it. Empty where it
    reads as anything else.

    A name is matched against the terms with its signs taken out, so that is how it is
    declared, and `CO~2~` reported without a word of it left the author to find out that
    `terms: ['CO~2']` worked.
    """
    name = declarable(atom)
    if name is None:
        return ""
    shown = name if _PLAIN_NAME.fullmatch(name) else json.dumps(name, ensure_ascii=False)
    return (
        "if this is a name and not a number, declare it in paper.yaml without its subscript "
        f"and superscript signs, `terms: [{shown}]`; otherwise "
    )


def _hint_for(atom) -> str:
    """A hint that names the thing the author is looking at.

    "Bind it with {{results.<key>}}" is true of every unbound number and useful for almost
    none of them: an author who has just written a study period does not think of a date as
    a result, so the generic hint reads as the tool not understanding the sentence. Dates
    and design parameters are the two that come up in every observational paper, and both
    have a specific answer. So has a name written with a subscript: how it is declared.
    """
    declare = _how_to_declare(atom)
    if declare:
        return declare + _GENERIC_HINT
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
