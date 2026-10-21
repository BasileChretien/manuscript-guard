"""Command line entry point.

Exit codes are part of the contract, because hooks and CI read them:
    0  every gate passed
    1  at least one gate failed
    2  the check could not be run at all
"""

from __future__ import annotations

import argparse
import codecs
import contextlib
import hashlib
import re
import sys
import unicodedata
from collections.abc import Collection
from datetime import date
from pathlib import Path

from manuscript_guard import __version__
from manuscript_guard.assurance import assurance, record_verified
from manuscript_guard.build import (
    LIVE,
    OFFLINE,
    PLAIN,
    BuildError,
    MisreadError,
    assemble,
    build_document,
)
from manuscript_guard.build.assemble import check_shapes
from manuscript_guard.build.document import abbreviations
from manuscript_guard.build.latex_check import check_latex
from manuscript_guard.build.tex_check import check_tex
from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts import (
    ContractError,
    Unreadable,
    load_namespace,
    load_project,
    read_text,
)
from manuscript_guard.findings import Report, merge_all
from manuscript_guard.gates import (
    check_bound_units,
    check_citations,
    check_consistency,
    check_design,
    check_figure_reviews,
    check_figures,
    check_freshness,
    check_journal,
    check_language,
    check_literature_chain,
    check_methods,
    check_models,
    check_numbers,
    check_passages,
    check_prose_quotations,
    check_recomputed,
    check_recycling,
    check_relations,
    check_reported,
    check_reporting,
    check_review,
    check_revision,
    check_writing,
    content_digest,
    manuscript_digest,
    panels,
    reconcile,
    scaffold_completion,
    source_files,
    sync_bib,
)
from manuscript_guard.gates.custodian import check_restricted_inputs, check_small_cells
from manuscript_guard.gates.design_review import check_design_rounds
from manuscript_guard.gates.figure_alt import check_figure_alt
from manuscript_guard.gates.formats import check_format, not_read_in_latex
from manuscript_guard.gates.numbers import chosen_rules, typed_choice, why_no_manuscript
from manuscript_guard.gates.related import check_related
from manuscript_guard.gates.shortlist import check_shortlist
from manuscript_guard.gates.synthetic import check_synthetic_inputs
from manuscript_guard.policy import (
    DESCRIPTIONS,
    STAGES,
    SUBMISSION,
    apply_stage,
    resolve_stage,
    summarise_deferred,
)
from manuscript_guard.record import FIGURE_VERDICTS
from manuscript_guard.record import VERDICTS as RECORD_VERDICTS
from manuscript_guard.scaffold import init_project, rules_to_add
from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import parse, substitute
from manuscript_guard.text.reader import LATEX, manuscript_files, manuscript_format
from manuscript_guard.text.sections import chains_at, footnote_index, heading_index
from manuscript_guard.text.tokens import find_atoms


def _run_gates(
    start: Path, *, submission: bool = False, stage: str | None = None
) -> tuple[Report, object, str, dict]:
    """Run every gate, then apply the stage policy.

    Every gate always runs. What the stage changes is which findings *fail*: someone still
    writing the analysis is told about the unreviewed figures, but not stopped by them.
    Nothing is skipped, and the caller reports what was deferred. The one exception is a
    LaTeX manuscript: a check not yet taught LaTeX does not run, and its gate reports
    `not-read-in-latex` instead, which fails at submission.

    Two things here used to be wrong, and both made the tool claim more than it checked.

    The gates were behind `if contract_report.ok and load_report.ok`. A project with no
    results yet — the ordinary state at `design` and `analysis` — failed that condition, so
    none of the twelve gates ran, the loading failures were demoted by the stage policy,
    and the run printed "0 failing, 0 warnings". A manuscript full of unbound numbers and
    model artefacts passed in silence. Now every gate runs, `load_results` and
    `load_literature` return empty-but-usable objects on failure, and a gate that raises is
    reported as `gate-errored` rather than quietly dropped.

    And the stage was resolved *after* `check_review` had already been handed the raw
    `--submission` flag, which is the only thing that sets G11's severity. `--submission`
    and `--stage submission` therefore gave different verdicts on the same project, and a
    project declaring `stage: submission` in paper.yaml — the natural thing to write once
    you are submitting — never had the review gate enforced at all. The stage is resolved
    first now, and the flag derived from it.

    A manuscript file that cannot be read, one saved in a code page for instance, stops each
    gate that reads the manuscript, and only those. It is one finding for each such file,
    which names the gates that did not run; the others report as usual.
    """
    project, contract_report = load_project(start)
    namespace, results, literature, load_report = load_namespace(project)

    chosen = resolve_stage(project, stage, submission)
    at_submission = chosen == SUBMISSION

    unreadable = _unreadable_sources(project)
    stopped: list[str] = []
    gate_reports: list[Report] = []
    latex = manuscript_format(project.path("manuscript")) == LATEX
    unread: list[str] = []
    for name, gate in (
        ("G11", lambda: check_review(project, submission=at_submission)),
        ("G1", lambda: check_freshness(project, results)),
        ("G2", lambda: check_numbers(project, namespace, results, literature)),
        ("G2", lambda: check_bound_units(project, results)),
        ("G3", lambda: check_figures(project, results)),
        ("G3", lambda: check_figure_alt(project, namespace, chosen)),
        ("G10", lambda: check_figure_reviews(project, content_digest)),
        ("G7", lambda: check_citations(project, literature)),
        ("G7", lambda: check_literature_chain(project, literature)),
        ("G7", lambda: check_prose_quotations(project)),
        ("G7", lambda: check_passages(project, chosen)),
        ("G7", lambda: check_recycling(project, chosen)),
        ("G4", lambda: check_journal(project)),
        ("G4", lambda: check_shortlist(project)),
        ("G8r", lambda: check_reporting(project)),
        ("G6", lambda: check_writing(project, results, submission=at_submission)),
        ("G9", lambda: check_methods(project, namespace, results)),
        ("G12", lambda: check_design(project, results, chosen).merge(
            check_design_rounds(project, submission=at_submission))),
        ("G8", lambda: check_consistency(results)),
        ("G2", lambda: check_small_cells(project, results)),
        ("G1", lambda: check_restricted_inputs(project, results)),
        ("G1", lambda: check_synthetic_inputs(project, results, submission=at_submission)),
        ("G8", lambda: check_reported(project, results)),
        ("G8", lambda: check_relations(results)),
        ("G8", lambda: check_recomputed(project, namespace, results)),
        ("G8", lambda: check_related(project, namespace, results, submission=at_submission)),
        ("G13", lambda: check_revision(project, submission=at_submission)),
        ("G14", lambda: check_language(project)),
        ("G15", lambda: check_models(project, results)),
        ("BUILD", lambda: check_shapes(project).merge(check_tex(project, namespace, results))),
        ("BUILD", lambda: check_latex(project)),
    ):
        if latex and _NOT_READ_IN_LATEX & set(gate.__code__.co_names):
            # A check that reads only Markdown would read nothing here and pass: it is not
            # run, and its gate says so once.
            if name not in unread:
                unread.append(name)
            continue
        report = _guarded(name, gate, unreadable)
        if report is None:
            # A gate run as several checks stopped once, and is named once.
            if name not in stopped:
                stopped.append(name)
        else:
            gate_reports.append(report)

    reports = [contract_report, load_report, _unreadable_report(project, unreadable, stopped)]
    reports += [check_format(project), Report(tuple(not_read_in_latex(name) for name in unread))]
    report, deferred = apply_stage(merge_all(reports + gate_reports), chosen)
    return report, project, chosen, deferred


#: The checks that read the manuscript only as Markdown, by the name each entry of
#: `_run_gates` calls. On a LaTeX manuscript they are not run, and each of their gates reports
#: `not-read-in-latex`. A check leaves this set in the step that teaches it LaTeX (DESIGN.md,
#: "LaTeX manuscripts", Order of work).
_NOT_READ_IN_LATEX = frozenset(
    {
        "check_related",
        "check_numbers", "check_bound_units", "check_small_cells", "check_citations",
        "check_prose_quotations", "check_journal", "check_reporting", "check_writing",
        "check_methods", "check_synthetic_inputs", "check_reported", "check_recomputed",
        "check_revision", "check_language", "check_models", "check_shapes", "check_tex",
        "check_passages",
        "check_recycling",
    }
)  # fmt: skip


def _unreadable_sources(project) -> dict[Path, Unreadable]:
    """Each manuscript file whose text cannot be had, with the error that says why.

    Read once before the gates, because a gate stops at the first file it cannot read. Left
    to the gates, one file was seven findings, a second file went unnamed until the first
    was put right, and which file was first depended on the gate: G4 does not read the
    supplement.
    """
    found: dict[Path, Unreadable] = {}
    for path in manuscript_files(project):
        try:
            read_text(path)
        except Unreadable as error:
            found[path] = error
    return found


def _unreadable_report(project, unreadable: dict[Path, Unreadable], stopped: list[str]) -> Report:
    """One finding for each manuscript file that could not be read, placed at the file.

    It names the gates that stopped there, so that what the run did not check is on the
    record: a gate left out without a word would read as a gate that passed. Its code is in
    no stage's deferral list, so it fails everywhere, as `gate-errored` did.
    """
    from manuscript_guard.findings import Finding

    listed = " and ".join(part for part in (", ".join(stopped[:-1]), *stopped[-1:]) if part)
    findings = []
    for path, error in unreadable.items():
        try:
            shown = path.relative_to(project.root).as_posix()
        except ValueError:  # `paths:` can put the manuscript outside the project
            shown = str(path)
        findings.append(
            Finding(
                gate="G0",
                code="manuscript-unreadable",
                message=f"{shown}: {error.reason}",
                path=path,
                line=error.line,
                hint=f"{listed} read the manuscript and did not run" if stopped else None,
            )
        )
    return Report(tuple(findings))


def _guarded(name: str, gate, unreadable: Collection[Path] = ()) -> Report | None:
    """Run one gate; turn a crash into a finding rather than a silent absence.

    A gate that raised used to take the whole set down with it. Reporting the crash keeps
    the promise that every gate runs — and `gate-errored` is in no stage's deferral list,
    so it fails everywhere. A checker that could not check is not a pass.

    None where the gate stopped at one of the `unreadable` manuscript files. Those are
    reported once each by `_unreadable_report`, which names the gates that return None here.
    """
    from manuscript_guard.findings import Finding

    try:
        return gate()
    except ContractError as exc:
        if isinstance(exc, Unreadable) and exc.path in unreadable:
            return None
        # A file the gate reads cannot be used, and the error is a sentence for the author
        # that names it. The same code, which fails at every stage, but not worded as a
        # fault of the tool: no class name before the sentence, and no bug in the hint.
        return Report(
            (
                Finding(
                    gate=name,
                    code="gate-errored",
                    message=f"{name} could not run: {exc}",
                    hint="put that file right; the manuscript has not been checked by this gate",
                ),
            )
        )
    except Exception as exc:  # noqa: BLE001 - any gate failure must be visible, not fatal
        return Report(
            (
                Finding(
                    gate=name,
                    code="gate-errored",
                    message=f"{name} could not run: {type(exc).__name__}: {exc}",
                    hint="this is a bug in manuscript-guard, or a file it could not read; "
                    "the manuscript has not been checked by this gate",
                ),
            )
        )


def _round_lines(summary) -> list[str]:
    """Who read each remit of a round and what each concluded, with the strictest verdict.

    The verdict is reported and decides nothing: what blocks a submission is an unanswered
    major finding, which the report below lists with the reader who raised it.
    """
    if summary is None or not summary.readings:
        return []
    strictest = summary.strictest
    by = ", ".join(part for part in (strictest.reviewer, strictest.reader) if part)
    lines = [f"strictest verdict: {strictest.verdict} ({by})"]
    rows = []
    for reading in summary.readings:
        found = f"{reading.findings} finding{'' if reading.findings == 1 else 's'}"
        if reading.major:
            found += f", {reading.major} major ({reading.open_major} open)"
        rows.append((reading.reviewer, reading.reader or "", reading.verdict, found))
    widths = [max(len(row[column]) for row in rows) for column in range(3)]
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row, widths, strict=False)]
        lines.append("  ".join([*cells, row[3]]).rstrip())
    return lines


def cmd_review(args: argparse.Namespace) -> int:
    """Show where the review stands, and write the record a reviewer has to file."""
    if args.reading is not None and not (args.record or args.seal):
        # Ignored in silence, it looked as though a reading had been filed.
        print(
            "manuscript-guard: --reading names who made a reading and goes with --record or "
            "--seal: `review --record <reviewer> --reading <reader> --verdict <verdict>`",
            file=sys.stderr,
        )
        return 2
    if args.seal and (
        args.record or args.record_figure or args.providers or args.run or args.dry_run
    ):
        print(
            "manuscript-guard: --seal seals a reading already filed, on its own: "
            "`review --seal <reviewer> --round <n>`",
            file=sys.stderr,
        )
        return 2
    if (args.record or args.record_figure) and (args.providers or args.run or args.dry_run):
        # The models' part of the command answered first, and the record was not filed.
        print(
            "manuscript-guard: --record files a record, and --providers, --run and --dry-run "
            "are about the models that read the panel: give one or the other",
            file=sys.stderr,
        )
        return 2
    if args.suggestions and (
        args.record or args.record_figure or args.seal or args.providers or args.run
        or args.dry_run or args.design
    ):  # fmt: skip
        print(
            "manuscript-guard: --suggestions writes the round's suggested edits into a "
            "document, on its own: `review --suggestions --round <n>`",
            file=sys.stderr,
        )
        return 2
    if args.design:
        return _design_round(args)
    if args.suggestions:
        return _write_suggestions(args)
    if args.providers:
        # Before the project is loaded: the list of providers is worth having without one.
        from manuscript_guard.panel.commands import list_providers

        return list_providers(args.path)
    if args.run or args.dry_run:
        from manuscript_guard.panel.commands import run_panel

        if not args.run:
            print(
                "manuscript-guard: --dry-run goes with --run: `review --run --dry-run` shows "
                "what a run of the panel would send",
                file=sys.stderr,
            )
            return 2
        return run_panel(
            args.path,
            round_number=args.round,
            one_each=args.one_each,
            dry_run=args.dry_run,
            yes=args.yes,
        )

    project, _ = load_project(args.path)
    digest = manuscript_digest(project)
    if args.digest:
        print(digest)
        return 0

    if args.seal:
        from manuscript_guard.record import RecordError, seal_review

        try:
            sealed = seal_review(
                project,
                args.seal,
                round_number=1 if args.round is None else args.round,
                reading=args.reading,
            )
        except RecordError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        print(f"sealed {sealed}")
        print(
            "Answer its findings in `resolution:` or `overridden:`. Anything else changed "
            "in what the reader wrote is reported as reading-altered."
        )
        return 0

    if args.record or args.record_figure:
        from manuscript_guard.record import RecordError, write_figure_review, write_review

        if not args.verdict:
            print(
                "manuscript-guard: --verdict is required. The record is written after the "
                "reading, and a placeholder verdict is a claim that somebody looked.",
                file=sys.stderr,
            )
            return 2
        try:
            if args.record_figure:
                written = write_figure_review(
                    project, args.record_figure, verdict=args.verdict, reviewed_by=args.by
                )
            else:
                written = write_review(
                    project,
                    args.record,
                    verdict=args.verdict,
                    round_number=1 if args.round is None else args.round,
                    reviewed_by=args.by,
                    remit=args.remit or "",
                    summary=args.summary or "",
                    reading=args.reading,
                )
        except RecordError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        if written.panel is not None:
            print(f"panel: {written.panel}")
        print(f"wrote {written.path}")
        print("Add the findings there. An empty list says the reviewer found nothing.")
        if args.record:
            again = f" --round {args.round}" if args.round is not None else ""
            named = f' --reading "{args.reading}"' if args.reading else ""
            print(
                "Then seal what the reader wrote: "
                f"`manuscript-guard review --seal {args.record}{again}{named}`"
            )
        return 0

    if args.files:
        # Paste-ready, because a reviewer who has to assemble this by hand will instead
        # omit it and go back to having a typo void their review.
        from manuscript_guard.gates.review import file_digests

        print("file_sha256:")
        for name, value in sorted(file_digests(project).items()):
            print(f"  {name}: {value}")
        return 0

    print(f"manuscript digest: {digest}")
    found = panels(project)
    if not found:
        print("no review panels. The review-panel skill assembles one.")
    else:
        from manuscript_guard.gates.review import round_summaries

        summaries = {summary.number: summary for summary in round_summaries(project)}
        for number, path in found:
            print(f"  round {number}: {path.name}")
            for line in _round_lines(summaries.get(number)):
                print(f"    {line}")
    report = check_review(project, submission=args.submission)
    print(report.render(project.root))
    return 0 if report.ok else 1


def _write_suggestions(args: argparse.Namespace) -> int:
    """`review --suggestions`: the round's suggested edits as tracked changes in a copy of
    the document, for the author to accept or refuse in Word."""
    from datetime import datetime, timezone

    from manuscript_guard.build.document import relative_to_root
    from manuscript_guard.suggestions import SuggestionsError, write_round

    project, _ = load_project(args.path)
    found = panels(project)
    number = args.round if args.round is not None else (found[-1][0] if found else 1)
    style = _journal_style(project, argparse.Namespace(csl=None, offline=True))
    when = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        outcome = write_round(project, number, csl=style, date=when)
    except SuggestionsError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    for note in outcome.notes:
        print(f"round {number}: {note}")
    if not outcome.placed:
        print(f"round {number}: no reading the gate counts suggests an edit.")
        return 0
    written = [p for p in outcome.placed if not p.dropped]
    dropped = [p for p in outcome.placed if p.dropped]

    def who(placed) -> str:
        return printable(f"{placed.edit.author}, {placed.edit.finding}")

    if written:
        print(f"round {number}: {len(written)} edit(s) written as tracked changes, each with "
              "its finding as a comment:")  # fmt: skip
        for placed in written:
            print(f"  {who(placed)}: {printable(_shown(placed.shown_old))} -> "
                  f"{printable(_shown(placed.shown_new))}")  # fmt: skip
    if dropped:
        print(f"round {number}: {len(dropped)} edit(s) not written; each stays a finding to "
              "answer in its record:")  # fmt: skip
        for placed in dropped:
            print(f"  {who(placed)}: {printable(_shown(placed.edit.old))}: {placed.dropped}")
    if outcome.report is not None and outcome.report.findings:
        print(outcome.report.render(project.root))
    for document in outcome.documents:
        shown = relative_to_root(project, document)
        print(
            f"\nwrote {shown}. Open it in Word and accept or reject each change; to refuse one "
            f"with a reason, reply to its comment. Then `manuscript-guard import {shown} "
            f"--apply` brings the accepted words into the source and records each finding's "
            f"answer. It is for you, not for the journal."
        )
    return 0


def _shown(text: str, limit: int = 60) -> str:
    folded = " ".join(text.split())
    return "'" + (folded if len(folded) <= limit else folded[:limit] + "...") + "'"


def _design_round(args: argparse.Namespace) -> int:
    """`review --design`: file or seal a design round's reading, or say where they stand."""
    from manuscript_guard.gates.design_review import check_design_rounds
    from manuscript_guard.record import RecordError, seal_design_review, write_design_review

    if args.providers or args.record_figure:
        print(
            "manuscript-guard: --design is a design round: `review --design --run` has the "
            "models read the plan, and `review --record <reviewer> --design --verdict "
            "<verdict>` files a reading by hand",
            file=sys.stderr,
        )
        return 2
    if args.run or args.dry_run:
        from manuscript_guard.panel.commands import run_panel

        if not args.run:
            print(
                "manuscript-guard: --dry-run goes with --run: `review --design --run "
                "--dry-run` shows what a run of the design panel would send",
                file=sys.stderr,
            )
            return 2
        return run_panel(
            args.path, round_number=args.round, one_each=args.one_each,
            dry_run=args.dry_run, yes=args.yes, design=True,
        )  # fmt: skip
    project, _ = load_project(args.path)
    round_number = 1 if args.round is None else args.round
    try:
        if args.seal:
            sealed = seal_design_review(
                project, args.seal, round_number=round_number, reading=args.reading
            )
            print(f"sealed {sealed}")
            return 0
        if args.record:
            if not args.verdict:
                print("manuscript-guard: --verdict is required", file=sys.stderr)
                return 2
            written = write_design_review(
                project, args.record, verdict=args.verdict, round_number=round_number,
                reviewed_by=args.by, remit=args.remit or "", summary=args.summary or "",
                reading=args.reading,
            )  # fmt: skip
            print(f"panel: {written.panel}")
            print(f"wrote {written.path}")
            named = f' --reading "{args.reading.strip()}"' if args.reading else ""
            print(
                "Add the findings there, then seal what the reader wrote: "
                f"`manuscript-guard review --seal {args.record} --design --round {round_number}"
                f"{named}`"
            )
            return 0
    except RecordError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    report = check_design_rounds(project, submission=args.submission)
    print(report.render(project.root))
    return 0 if report.ok else 1



def _bind_pointers(args: argparse.Namespace, project) -> int:
    """`bind --pointers`: each typed pointer to a table or a figure, and the ref or num binding
    that prints it as it reads now (`binding.typed_pointers`). A typed pointer is not a
    defect, so finding some is no failure: the exit is 0 either way."""
    from manuscript_guard.binding import SelectionError, apply, label, select, typed_pointers

    items = typed_pointers(project)
    if not items:
        print("no typed pointer to a table or a figure that a binding could print as it reads.")
        return 0
    if args.apply:
        try:
            chosen = select(items, args.only, project.root)
        except SelectionError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        applied, _rest = apply(chosen)
        for item, binding in applied:
            print(f"{label(item, project.root)}  {item.text!r} -> {binding}")
        print(f"\nreplaced {len(applied)} typed pointer(s) with the binding that prints them.")
        return 0
    for item in items:
        print(f"{label(item, project.root)}  {item.text!r} -> {{{{{item.certain}}}}}")
        print(f"    {item.hint}")
    print(
        f"\n{len(items)} typed pointer(s) can be bound, each printing what it reads now. "
        "`manuscript-guard bind --pointers --apply` replaces all of them; add "
        "`--only FILE:LINE` for one line."
    )
    return 0


def cmd_bind(args: argparse.Namespace) -> int:
    """Show every unbound number and what would give it a source.

    `check` says a number is unbound; the annotated copy colours it red. Neither says what
    to type next, and usually the answer is that the number is already in `results/` and was
    typed instead of bound. That case is detected and offered as a replacement.
    """
    from manuscript_guard.binding import SelectionError, apply, label, routes, select, unbound

    project, _ = load_project(args.path)
    empty = why_no_manuscript(project)
    if empty is not None:
        # "every number in the manuscript is accounted for" was said of no manuscript.
        print(f"manuscript-guard bind: {empty}", file=sys.stderr)
        return 2
    if args.pointers:
        return _bind_pointers(args, project)
    namespace, _results, _literature, _ = load_namespace(project)
    items = unbound(project, namespace)

    if not items:
        print("every number in the manuscript is accounted for.")
        return 0

    if args.apply:
        try:
            chosen = select(items, args.only, project.root)
        except SelectionError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2

        applied, _rest = apply(chosen)
        # Named, not counted. "replaced 7 literal(s)" tells an author nothing about which
        # seven, and every one of these rewrote a sentence: a suggestion is a guess from a
        # matching value, so the line where it landed is the only way to review it after the
        # fact. `git diff` says the same thing, but only if you already know to look.
        for item, binding in applied:
            print(f"{label(item, project.root)}  {item.text!r} -> {binding}")
        print(f"\nreplaced {len(applied)} literal(s) with the binding they match.")

        accepted = {(item.path, item.start) for item, _b in applied}
        items = [item for item in items if (item.path, item.start) not in accepted]
        if not items:
            print("Re-run `manuscript-guard check` to confirm.")
            return 0
        print(f"{len(items)} left:\n")

    for item in items:
        print(f"\n{label(item, project.root)}  {item.text!r}")
        for route in routes(item):
            print(f"    {route}")
        print(f"    hint: {item.hint}")

    certain = [item for item in items if item.certain]
    if certain and not args.apply:
        # Real selectors from this list, not a fixed example: the example said `main.md:12`,
        # a selector is the path from the project root, and the one command the tool
        # suggested was refused.
        # A selector names a line, so two suggestions on one line are one selector: naming
        # it twice read as two suggestions and promised "just those two" for one line. And
        # `--only` refuses a line that also holds a number with no single answer, so such a
        # line is not offered.
        undecided = {label(item, project.root) for item in items if not item.certain}
        offered = dict.fromkeys(label(item, project.root) for item in certain)
        chosen = [selector for selector in offered if selector not in undecided][:2]
        message = (
            f"\n{len(certain)} of {len(items)} match exactly one published value. "
            f"`manuscript-guard bind --apply` replaces all of those"
        )
        if chosen:
            only = " ".join(f"--only {selector}" for selector in chosen)
            which = "just that line" if len(chosen) == 1 else "just those two lines"
            message += f"; `--apply {only}` replaces {which}"
        print(message + ".")
    return 1




def _unexamined(document: Path, identified: int, listed: bool = False) -> str:
    """How much of the returned document this command could not look at.

    Import compares paragraphs that carry an identifier. Table cells, headings, captions,
    list items, block quotes and any paragraph the co-author newly wrote carry none, so an
    edit to one is not merged and not refused. Outside tables such an edit is at least
    listed; inside one it is only counted here. A co-author who corrects a number in a table
    has every reason to believe it landed.
    """
    import re as _re
    import zipfile as _zip

    try:
        with _zip.ZipFile(document) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
    except (OSError, KeyError, _zip.BadZipFile):
        return ""
    total = len(_re.findall(r"<w:p\b", xml))
    missed = max(0, total - identified)
    if not missed:
        return ""
    return (
        f"{missed} of {total} paragraphs in {document.name} carry no identifier and were "
        f"not compared: table cells, headings, captions, list items, block quotes, "
        f"paragraphs tied to markup in or around them, such as display maths, a comment "
        f"closing past them, or a fence, `</div>` or definition directly under them, and "
        f"anything newly written. "
        + (
            "Those outside tables that changed are listed above; "
            if listed
            else "None outside a table changed; "
        )
        + "an edit inside a table is not reported at all."
    )


def _which_document(project, known: dict, returned, name: str) -> bool | None:
    """Whether a returned document is the supplement; None when it is not one document.

    `build` writes the supplement as a document of its own, and import compared every
    returned document with a fresh build of the paper. An edited supplementary.docx reported
    every paragraph of the paper as deleted in Word, exit 1, and its own edits went nowhere.
    The paragraph identifiers a document carries say which one it is, because each names its
    source file; the source stamp cannot, since both documents carry the same one. A document
    carrying neither kind is refused when the project has a supplement, because it could be
    either, and compared with the paper when it has none. Whether there is a supplement is
    read from the source files: read from the identifiers, a supplement of headings and tables,
    which has none, was taken for no supplement, and compared with the paper.
    """
    from manuscript_guard.gates.numbers import is_supplementary, source_files

    manuscript_dir = project.path("manuscript")
    kinds = {
        is_supplementary(manuscript_dir, known[identifier][0])
        for block in returned
        for identifier in block.names
        if identifier in known
    }
    has_supplement = any(is_supplementary(manuscript_dir, p) for p in source_files(manuscript_dir))
    if not kinds and has_supplement:
        print(
            f"{name} carries no paragraph identifier this manuscript knows, so there is no "
            f"telling whether it is the manuscript or its supplement, and import compares "
            f"paragraphs only through those identifiers. Nothing was imported. A supplement of "
            f"headings, tables and figures carries none, and holds nothing import compares; "
            f"otherwise, import the document the co-author was sent, edited in place."
        )
        return None
    if kinds == {True, False}:
        print(
            f"{name} carries paragraphs of both the manuscript and its supplement. They are "
            f"built as two documents and imported one at a time, and a paragraph pasted from "
            f"one into the other is not something import can apply. Nothing was imported: "
            f"make the move in the .md yourself, and import each document on its own."
        )
        return None
    return kinds == {True}


def _refused_inserted(plan, inserted: dict[str, list], returned: list, project):
    """The plan with each paragraph that holds a citation a co-author inserted with a
    reference manager refused, naming the work, where it was merged or let be: its words
    came back as prose, and merged they were written into the source as text, a year G2 then
    caught as a number nobody bound. Where `references.bib` holds the work, its key is given."""
    from dataclasses import replace

    from manuscript_guard.merge import Refusal

    entries = _bib_entries(project)
    why_of = {
        name: tuple(_said_inserted(work, entries) for work in works)
        for name, works in inserted.items()
    }
    text_of = {name: block.text for block in returned for name in block.names}
    refused = [
        replace(refusal, why=refusal.why + why_of[refusal.name])
        if refusal.name in why_of
        else refusal
        for refusal in plan.refused
    ]
    told = {refusal.name for refusal in refused}
    refused += [
        Refusal(name, text_of.get(name, ""), why)
        for name, why in why_of.items()
        if name not in told and name in text_of
    ]
    merged = {name: text for name, text in plan.merged.items() if name not in why_of}
    return replace(plan, merged=merged, refused=tuple(refused))


def _bib_entries(project) -> dict[str, dict[str, str]]:
    from manuscript_guard.literature.bibfile import read_entries

    path = project.path("literature") / "references.bib"
    try:
        return read_entries(path) if path.is_file() else {}
    except (OSError, UnicodeDecodeError, ValueError):
        return {}


def _plain_title(text: str) -> str:
    """A title as compared: letters and digits of any script, case and the rest folded."""
    return " ".join(re.sub(r"[\W_]+", " ", text.replace("{", "").replace("}", "")).lower().split())


def _first_family(authors: str) -> str:
    """The first author's family name in a `.bib` author field: before the comma, or the
    last word."""
    first = authors.replace("{", "").replace("}", "").split(" and ")[0].strip()
    family = first.split(",")[0] if "," in first else (first.split() or [""])[-1]
    return family.strip().lower()


def _doi_of(written: str) -> str:
    """A DOI as the gates read it, whatever it is dressed in, `doi:`, `http://dx.doi.org/`
    or a stop after it, in one case (round 2 of #350: only `https://doi.org/` was taken off,
    and the entry with the DOI written otherwise lost to a duplicate without one)."""
    from manuscript_guard.gates.identifiers import normal_doi

    return normal_doi(written).lower()


def _the_work(work, fields: dict[str, str]) -> bool:
    """Whether a `.bib` entry is the work a citation field names: by its DOI where both give
    one, or else by its title, and then by its year and first author wherever both say them.
    A title alone was too little: two works whose titles share only "COVID-19" in Latin
    letters were one. An entry with no DOI is matched by its title (round 2 of #298: it was
    never found where the field gave a DOI)."""
    doi, known = _doi_of(work.doi), _doi_of(fields.get("doi", ""))
    if doi and known:
        return known == doi
    title = _plain_title(work.title)
    if not title or _plain_title(fields.get("title", "")) != title:
        return False
    year = fields.get("year", "").strip()
    if work.year and year and work.year != year:
        return False
    family = _first_family(fields.get("author", ""))
    return not (work.author and family and work.author.strip().lower() != family)


def _said_inserted(work, entries: dict[str, dict[str, str]]) -> str:
    """What the import says of a work a co-author cited with their reference manager. The
    entry with the field's DOI first, wherever it stands: a duplicate with no DOI above it was
    taken for the work (round 1 of #350)."""
    doi = _doi_of(work.doi)
    key = next((key for key, fields in entries.items()
                if doi and _doi_of(fields.get("doi", "")) == doi), None)  # fmt: skip
    if key is None:
        key = next((key for key, fields in entries.items() if _the_work(work, fields)), None)
    said = f"{work} was cited in Word with a reference manager, whose field the build does not read"
    if key is not None:
        return f"{said}: cite it in the .md as [@{key}]"
    return f"{said}, and is not in references.bib: add it to the library, then cite it in the .md"


def _style_built_with(
    project, name: str, digest: str, recorded: str | None, given: Path | None
) -> tuple[Path | None, str | None]:
    """The citation style a document was built with, found by the digest it carries: the
    file `--csl` names, or else the one where the build recorded it. None, and why, where
    neither is that style."""
    from manuscript_guard.roundtrip import style_digest

    if given is not None:
        if given.is_file() and style_digest(given) == digest:
            return given, None
        return None, (
            f"{given} is not the citation style {name} was built with: its digest differs, "
            "or it is not a file"
        )
    if recorded:
        place = Path(recorded)
        place = place if place.is_absolute() else project.root / place
        if place.is_file() and style_digest(place) == digest:
            return place, None
    where = f", {recorded}," if recorded else ""
    return None, (
        f"{name} was built with a citation style{where} that is not there now, or has changed "
        f"since. Its citations are compared with the default style's, so each paragraph that "
        f"cites is refused below. Pass the style it was built with: --csl FILE."
    )


def cmd_import(args: argparse.Namespace) -> int:
    """Bring a co-author's edits back from Word, without losing the bindings.

    Everything is keyed on the invisible identifier each paragraph carries, so "which
    paragraph is this" is an exact question. That makes moves and wording changes orthogonal:
    a paragraph can be reordered, reworded, or both, and `merge` applies all of it in one
    pass from one reading of the file.
    """
    import tempfile
    from dataclasses import replace

    from manuscript_guard.gates.review import document_digest
    from manuscript_guard.merge import apply_plan, plan_import
    from manuscript_guard.roundtrip import (
        LIVE_CITATIONS,
        OFFLINE_CITATIONS,
        RoundTripError,
        cited_of,
        comments_in,
        inserted_citations,
        named_now,
        numbering,
        numbering_refusal,
        read_blocks,
        read_citations,
        read_printed,
        recorded_citations,
        records_moves,
        stamp_of,
        tagged_paragraphs,
    )

    project, _loaded = load_project(args.path)
    edited = args.document
    if not edited.exists():
        print(f"manuscript-guard: {edited} does not exist", file=sys.stderr)
        return 2

    try:
        carried = stamp_of(edited)
    except RoundTripError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    if _refused_marked_up(edited, "imported"):
        return 1
    if carried is None:
        print(
            f"{edited.name} carries no record of the source it was built from, so there is "
            f"no way to tell which text these edits were made against. Only a document this "
            f"tool built can be imported."
        )
        return 1
    # A document of a review panel's suggested edits (`review --suggestions`): each is a
    # tracked change, and one still undecided is neither accepted nor refused. Read as
    # accepted, as every other tracked change is, a suggestion nobody looked at would merge.
    from manuscript_guard.tracked import TrackedError, offered_of, pending

    try:
        offered = offered_of(edited) or []
        undecided = pending(edited, {entry["author"] for entry in offered}) if offered else 0
    except TrackedError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    if undecided:
        print(
            f"{edited.name} still holds {undecided} tracked change(s) the review panel "
            f"suggested. Accept or reject each one in Word first, save, and import it again: "
            f"an edit nobody decided is neither, and nothing is imported while one is left."
        )
        return 1
    # Before the digest, and past --force: under other numbering an edit has no hunk to
    # check by hand, only a paragraph that is not the one it was made in.
    stale = carried != document_digest(project)
    try:
        numbered = numbering(project, edited, stale=stale)
    except RoundTripError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    if numbered.refusal:
        print(numbering_refusal(edited.name, numbered.refusal))
        return 1
    if stale and not args.force:
        print(
            f"{edited.name} was built from a different version of the manuscript than the "
            f"one on disk. Merging edits made against text that has since changed is how a "
            f"correction lands on the wrong sentence.\n"
            f"  Resolve it by hand, or re-send the co-author a current build.\n"
            f"  --force imports anyway: an edit is merged only where the paragraph it was "
            f"made in reads as it did at the build, and every hunk still has to be read."
        )
        return 1

    try:
        returned = read_blocks(edited)
        comments = comments_in(edited)
    except RoundTripError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    decided = []
    if offered:
        from manuscript_guard.suggestions import decisions

        try:
            decided, told = decisions(edited, offered)
        except TrackedError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        # The panel's own comments are its findings, which are in the records, and a reply
        # to one is an answer, said with the suggestions.
        comments = [c for c in comments if (c.author, c.text) not in told]
    known = tagged_paragraphs(project)
    supplementary = _which_document(project, known, returned, edited.name)
    if supplementary is None:
        # The comments need no identifier to be read, and are the most useful thing in the
        # document: refusing the edits is no reason to drop them.
        _report_comments(comments)
        return 1
    try:
        # Its record is the one written for the document it is, the paper or the supplement:
        # both carry the same source stamp, and the supplement's record passed for the
        # paper's.
        printed, record = read_printed(
            project.path("build"), edited, supplementary=supplementary
        )
        cited = cited_of(edited)
    except RoundTripError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    # The comparison is built as the document was: see `roundtrip.CITED_PROPERTY`.
    citations = read_citations(project.path("build"), edited, supplementary=supplementary)
    try:
        # A citation a co-author inserted with their own reference manager; see below.
        inserted = inserted_citations(
            edited, citations.get("fields") if cited == LIVE_CITATIONS else None
        )
    except RoundTripError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    mode, style, narrative = OFFLINE, None, None
    if cited == LIVE_CITATIONS:
        # Each citation as the source writes it, on both sides: in the build compared with,
        # and in the returned document, each field read by what it cites.
        mode = PLAIN
        fields = citations.get("fields")
        narrative = citations.get("names")
        if fields is None:
            print(
                f"{edited.name} was built with live Zotero citations, and the record of what "
                f"each one cites is not here: it is written beside the build that made the "
                f"document. A citation Zotero has refreshed reads as changed, and its "
                f"paragraph is refused below. Import it where it was built.\n"
            )
        else:
            try:
                returned = read_blocks(edited, fields=recorded_citations(fields))
            except RoundTripError as exc:
                print(f"manuscript-guard: {exc}", file=sys.stderr)
                return 2
    elif cited != OFFLINE_CITATIONS:
        style, said = _style_built_with(
            project, edited.name, cited.split()[1], citations.get("style"), args.csl
        )
        if style is None and args.csl is not None:
            print(f"manuscript-guard: {said}", file=sys.stderr)
            return 2
        if said:
            print(said + "\n")

    namespace, results, _literature, _r = load_namespace(project)
    # What the assembly reports is not import's to enforce: a source the build refuses is
    # still refused by `check` and the build after the import, and refusing here blocked
    # the return of a document built before a refusal existed.
    assembled, _ar = assemble(project, namespace, results)

    # The document as it was sent, rebuilt from the source, is what the returned one is
    # compared with - so import needs everything a build needs, pandoc first. A second copy
    # has every binding and citation bookmarked, which is how a reworded paragraph learns
    # where each of them begins and ends without guessing at how they render.
    marked_assembly, _mr = assemble(project, namespace, results, mark=True)
    with tempfile.TemporaryDirectory() as scratch:
        reference = Path(scratch) / "reference.docx"
        tokens = Path(scratch) / "reference-tokens.docx"
        try:
            for assembly, output in ((assembled, reference), (marked_assembly, tokens)):
                build_document(
                    project,
                    assembly,
                    mode=mode,
                    csl=style,
                    narrative=narrative,
                    output=output,
                    supplementary=supplementary,
                    verify_reading=False,
                    sent=True,
                )
            abbreviated = abbreviations()
        except BuildError as exc:
            print(
                f"manuscript-guard: import compares {edited.name} with a fresh build of the "
                f"source, and the build failed: {exc}",
                file=sys.stderr,
            )
            return 2
        sent = read_blocks(reference)
        # The marked build is this command's own, not a document anyone sent, and a failure
        # to read it once stopped the import of every paragraph over a file the author had
        # never seen. Without it no token has a position: a reworded paragraph holding a
        # binding or citation is refused, and every other change is still examined.
        try:
            marked: list | None = read_blocks(tokens)
        except RoundTripError as exc:
            print(
                f"manuscript-guard: {exc}. That is the build import reads where each binding "
                f"and citation sits from, so no reworded paragraph holding a binding or "
                f"citation can be merged this time; each is refused below. Please report it.",
                file=sys.stderr,
            )
            marked = None

    # Only the identifiers that still name the paragraph they named at the build. The rest
    # would put an edit into whichever paragraph now sits there. A value paragraph an older
    # document may never have carried is asked about only in the document it belongs to:
    # a supplement does not lack the paper's.
    present = {n for b in returned if not b.table for n in b.names}
    building = {n for b in sent for n in b.names}
    unsure = numbered.unsure & building
    trusted = numbered.trusted | (unsure & present)
    # And those followed to where their paragraph stands now, compared under the identifier
    # it has now: the returned document is read under those, and the source is not renamed.
    followed = numbered.followed
    vouched, compared = trusted | set(followed), trusted | set(followed.values())
    every = known
    known = {name: entry for name, entry in every.items() if name in compared}
    # And one the document's record does not hold: its block had no identifier when it was
    # built - a list item made a paragraph since, or a release that tags more kinds of block.
    # Never compared, it is still weighed as a join into the paragraph above it, as main
    # weighs every paragraph; left out, the join merged as a rewording and its text was in
    # the source twice.
    untagged_then = building - set(numbered.sent) if numbered.recorded else set()
    now_named = named_now(followed)
    # What the document printed when it was built, read under the same names. Its record is
    # a file beside the build that built it: on another machine, or with build/ cleaned, it
    # is not there, and the import says so rather than read the document less exactly
    # without a word.
    if printed is None and record is not None:
        build = project.path("build")
        where = f"{build.name}/{record.parent.name}/{record.name}"
        print(
            f"{edited.name} names a record of what it printed when it was built, {where}, "
            f"which is not here or is not this document's: it is written beside the build, on "
            f"the machine that built it, and that build says so where it could not write it. "
            f"The import goes by the rules for a document built before that record, which "
            f"refuse more.\n"
        )
    if printed is not None:
        printed = [replace(b, names=tuple(map(now_named, b.names))) for b in printed]
    # Where each bookmark sits goes by the same names: read under the old ones, a block
    # holding two identifiers could not say whose text either held.
    renamed = [
        replace(
            block,
            names=tuple(map(now_named, block.names)),
            at=tuple((now_named(name), offset) for name, offset in block.at),
        )
        for block in returned
    ]
    # The words of each suggestion accepted in Word, which are written where they were
    # found rather than merged from Word's text: see `merge.plan_import`.
    accepted = None
    if decided:
        from manuscript_guard.suggestions import accepted_words

        accepted = accepted_words(project, decided, named=now_named)
    plan = plan_import(
        known,
        sent,
        renamed,
        marked,
        abbreviated,
        every=every,
        built=tuple(map(now_named, numbered.sent)),
        unsure=unsure | untagged_then,
        beside_changed=numbered.beside_changed,
        followed=frozenset(followed.values()),
        same_text={now_named(was): now for was, now in numbered.same_text.items()},
        stale=stale,
        printed=printed,
        accepted=accepted,
    )
    if inserted:
        # Only the paragraphs compared, `known`, which goes by the names they have now: one
        # that is not is said to be so below, and is named in a refusal as having no file.
        plan = _refused_inserted(
            plan,
            {
                now_named(name): works
                for name, works in inserted.items()
                if now_named(name) in known
            },
            renamed,
            project,
        )

    # Only paragraphs carrying an identifier are compared at all. Everything else - table
    # cells, headings, captions, list items, block quotes, the reference list, and anything
    # the co-author newly wrote - is invisible to this command, and saying nothing about
    # that let a co-author believe they had corrected a table when the correction went
    # nowhere.
    # A figure or equation deleted or dragged is outside a table too: asked only of the
    # paragraphs without an identifier, the note said none had changed beside the report
    # that a figure could not be found.
    outside = [k for k in plan.lost if k != "table"] + [k for k, _ in plan.strayed if k != "table"]
    unexamined = _unexamined(
        edited,
        sum(1 for b in returned if b.names and not b.table),
        listed=bool(plan.unidentified or plan.vanished or plan.reordered or outside),
    )
    # A paragraph whose identifier no longer names the text it was built from: the source
    # changed there since, or this version numbers or tags paragraphs by other rules. Its
    # edit belongs to a paragraph that is not there now, so it is not compared; saying so is
    # the only way it does not vanish. An empty one in a document that records nothing is
    # what releases before 0.2.45 put under an HTML comment, and nobody wrote in it.
    strangers = sorted(
        {
            n
            for b in returned
            if not b.table and (numbered.recorded or b.text.strip())
            for n in b.names
            if n not in vouched
        }
    )
    # And one that did not come back, deleted or joined in Word. Looked for among those that
    # came back only, its deletion left no trace, and the import said nothing came back.
    unaccounted = [n for n in numbered.sent if n not in vouched and n not in present]
    values = sorted(unsure - present)
    said = _not_compared(edited, strangers, unaccounted, values)
    unexamined = "\n  ".join(part for part in (unexamined, *said) if part)
    unaccounted += values

    if plan.empty and not comments and not strangers and not unaccounted:
        what = "supplement" if supplementary else "manuscript"
        print(f"nothing came back: the document matches the {what} on disk.")
        if unexamined:
            print(f"  {unexamined}")
        _answer_suggestions(project, decided, {}, applying=args.apply, named=now_named)
        return 0

    _report_plan(project, known, plan, applying=args.apply, followed=set(followed.values()))
    if not records_moves(edited):
        print(
            f"\n{edited.name} was built before manuscript-guard let Word record moves: its "
            f"settings ask Word not to. A paragraph moved in it comes back as a deletion and new "
            f"text, and is refused. Rebuild and resend the document for moves to come back."
        )

    if args.apply:
        apply_plan(known, plan)
        if plan.moved:
            print(f"\nreordered {len(plan.moved)} paragraph(s) in the manuscript source.")
        if plan.merged:
            print(f"merged {len(plan.merged)} reworded paragraph(s), bindings intact.")

    _report_comments(comments)
    _answer_suggestions(project, decided, plan.merged, applying=args.apply, named=now_named)

    if unexamined:
        print(f"\n{unexamined}")

    if not args.apply and (plan.moved or plan.merged):
        print(f"\n`manuscript-guard import {edited} --apply` applies the safe changes.")

    # Comments alone are not a failure. Exit 1 meant a hook or a CI step keyed on the code
    # reported a problem when a co-author had done nothing but leave notes. Anything not
    # applied is: a paragraph moved into another file was reported "not applied" and still
    # exited 0.
    outstanding = bool(
        plan.refused
        or plan.gone
        or plan.displaced
        or plan.joined
        or plan.misplaced
        or plan.withheld
        or plan.lost
        or plan.strayed
        or plan.unidentified
        or plan.vanished
        or plan.reordered
        or plan.held_back
    ) or (not args.apply and bool(plan.moved or plan.merged))
    # A paragraph not compared is not applied either.
    return 1 if outstanding or strangers or unaccounted else 0


def _answer_suggestions(project, decided, merged, *, applying: bool, named) -> None:
    """What `import` says of a review panel's suggested edits, and with `--apply` the answer
    each finding's record gets (`suggestions.answers`)."""
    if not decided:
        return
    from manuscript_guard.record import RecordError, answer_finding
    from manuscript_guard.suggestions import answers

    print(f"\nsuggested edits: {len(decided)}")
    for decision in decided:
        entry = decision.offered
        print(f"  {printable(entry['author'])}, {printable(entry['finding'])}: {decision.state}")
        for reply in decision.replies:
            print(f"    reply by {printable(reply.author or 'an unnamed author')}:")
            print(quoted(reply.text))
    for answer in answers(project, decided, merged=merged, today=date.today(), named=named):
        where = answer.record.name
        if answer.fields is None:
            print(f"  {where}, {printable(answer.finding)}: left open; {answer.said}")
            continue
        if not applying:
            print(f"  {where}, {printable(answer.finding)}: {answer.said}; --apply records it")
            continue
        try:
            answer_finding(answer.record, answer.finding, answer.fields)
        except RecordError as exc:
            print(f"  {where}, {printable(answer.finding)}: not recorded: {exc}")
            continue
        print(f"  {where}, {printable(answer.finding)}: {answer.said}; recorded")


def _not_compared(
    edited: Path, strangers: list[str], unaccounted: list[str], values: list[str]
) -> list[str]:
    """What `import` says of the paragraphs whose identifier it could not vouch for:
    those that came back, those it was built with that did not, and the value paragraphs a
    document that records nothing may never have carried."""

    def shown(names: list[str]) -> str:
        return ", ".join(names[:5]) + (", …" if len(names) > 5 else "")

    said = []
    if strangers:
        said.append(
            f"{len(strangers)} paragraph(s) in {edited.name} were not compared, because their "
            f"identifier no longer names the paragraph it named when the document was built "
            f"({shown(strangers)}): the source changed there since, or this version numbers "
            f"or tags paragraphs differently. Carry any edit in them over by hand. A paragraph "
            f"moved past one of them in Word may not be reported as moved."
        )
    if unaccounted:
        said.append(
            f"{len(unaccounted)} paragraph(s) {edited.name} was built with did not come back, "
            f"deleted or joined in Word, and were not compared, because their identifier no "
            f"longer names the paragraph it named then ({shown(unaccounted)}). Delete or join "
            f"them in the .md yourself if that was intended."
        )
    if values:
        said.append(
            f"{len(values)} paragraph(s) that are only a value are not in {edited.name} "
            f"({shown(values)}): deleted or joined in Word, or never in it, since the release "
            f"that built it may be one before 0.2.49, which gave them no identifier. Delete or "
            f"join them in the .md yourself if that was intended."
        )
    return said


#: How much of a comment is printed: enough to find it in Word.
COMMENT_SHOWN = 200


def quoted(text: str, limit: int = COMMENT_SHOWN) -> str:
    """Text somebody else wrote, framed as a quotation: each line behind `> `, cut at
    `limit` characters, and every control character, an escape sequence's included, shown
    as `?`. Printed this way a co-author's words cannot pass for the tool's own, to a person
    or to an agent reading the output, and cannot move the cursor or recolour the terminal."""
    shown = text if len(text) <= limit else text[:limit] + " [...]"
    return "\n".join(f"    > {line}" for line in printable(shown).split("\n"))


#: The bidirectional controls, which reorder what follows them on screen.
_BIDI = frozenset(map(chr, (0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F),
                            *range(0x2066, 0x206A))))  # fmt: skip


def printable(text: str) -> str:
    """`text` with every character a terminal would act on, rather than show, as `?`: a
    control character (an escape, a carriage return) and a bidirectional control. A line
    break is kept, and so is a no-break space, which Word puts in "5 mg" and before a
    French colon."""
    return "".join(
        "?" if c in _BIDI or (unicodedata.category(c) == "Cc" and c != "\n") else c for c in text
    )


def _report_comments(comments) -> None:
    """Each co-author comment, and where to record them so G11 can see they were answered.
    The comment is the co-author's text, quoted, never the tool's words."""
    for comment in comments:
        author = printable(f"{comment.author} ({comment.date})").replace("\n", " ")
        print(f"\ncomment from {author}, quoted:")
        print(quoted(comment.text))
    if comments:
        print(
            f"\n{len(comments)} comment(s). Record them in a review file so G11 can see they "
            f"were answered: write them into review/round-<n>/<reviewer>.yaml."
        )


def _report_plan(project, known: dict, plan, *, applying: bool, followed=frozenset()) -> None:
    """Say what the returned document changed and what will, or will not, be applied.

    `known` holds the paragraphs compared. A join can take in one that was not, which is
    named by its identifier: what the source now has under it is another paragraph.
    `followed` names those compared where they stand now, their identifier having shifted.
    """
    from manuscript_guard.roundtrip import AS_SENT

    def where(name: str) -> str:
        return known[name][0].relative_to(project.root).as_posix()

    def opening(name: str) -> str:
        if name not in known:
            return f"({name.removesuffix(AS_SENT)}, not compared)"
        # On one line: a held comment's source runs over several.
        return " ".join(known[name][1].split())[:80]

    if plan.misplaced:
        print(f"{len(plan.misplaced)} paragraph(s) were moved into a different section or file:")
        for name in sorted(plan.misplaced):
            # Its identifier shifted, so the .md changed above it since the build, and a
            # heading moved past it there reads the same as a move in Word.
            since = " (the .md changed above it since the build: check before moving it)"
            print(f"    {opening(name)}{since if name in followed else ''}")
        print(
            "    Not applied: import only reorders paragraphs within a section, and a heading, "
            "a table, a figure, a list, a quotation or anything else without an identifier, "
            "another file, or a paragraph it holds in place ends one. An HTML comment or a "
            "`\\newpage` ends one too, though Word shows nothing there. It holds a paragraph "
            "Word shows as an empty line, one with a line such as `\\end{table}` directly "
            "under it in the .md, one with a `<!--` that never closes, and one Word shows as "
            "more than one paragraph. Move it in the .md yourself."
        )

    # Text out of place among texts that all came back, only reordered, is one reorder: named
    # both here and below it was said twice, each list naming its own share of the items, and
    # a swapped list item was called a heading. Named first there and never cut: added after
    # the rest, a heading dragged past a table went unnamed beside a long reversed list. The
    # rest keeps twelve lines of its own: sharing them, twelve texts out of place cut a
    # heading the ordering kept.
    together = bool(plan.reordered)
    strayed = [(kind, text) for kind, text in plan.strayed if not (together and kind == "text")]
    folded = [text for kind, text in plan.strayed if (kind, text) not in strayed]
    rest = [*plan.reordered]
    for text in folded:
        if text in rest:
            rest.remove(text)
    reordered = folded + rest
    shown = len(folded) + 12
    if strayed:
        print(
            f"{len(strayed)} heading(s) or other text, table(s), figure(s) or equation(s) came "
            f"back somewhere else:"
        )
        for kind, text in strayed:
            article = "an" if kind == "equation" else "a"
            print(f"    '{text[:80]}'" if kind == "text" else f"    {article} {kind}")
        print(
            "    Not applied: each goes where the .md puts it. Move the heading or other text, "
            "the table's or figure's placeholder, or the equation, in the .md yourself; a "
            "caption goes with its table or figure."
        )

    if plan.held_back:
        print(
            f"{len(plan.held_back)} paragraph(s) were moved where a paragraph would reach the "
            "next build without its identifier:"
        )
        for name, lost in plan.held_back:
            print(f"    {opening(name)}")
            if lost != name:
                print(f"      (it would leave behind: {opening(lost)})")
        print(
            "    Not applied, nor any other move in that section. With what would be around it, "
            "pandoc would read that paragraph as something other than itself - a definition, a "
            "heading, part of a comment: no identifier, so a later edit to it could not come "
            "back. Move them in the .md yourself."
        )

    if plan.lost:
        what = " and ".join(f"{plan.lost.count(k)} {k}(s)" for k in sorted(set(plan.lost)))
        print(
            f"{what} of the document as sent could not be found in the returned one: deleted, "
            f"pasted twice, or changed while others were added or removed."
        )
        print(
            "    Nothing about them is applied, and a paragraph moved past one cannot be seen. "
            "Tables and figures are built from the analysis: change them there, or remove "
            "the placeholder from the .md. An equation is edited in the .md."
        )

    if plan.unidentified or plan.vanished or reordered:
        if reordered:
            print(
                "\nParagraphs without an identifier - headings, list items, quotations, "
                "captions - came back in a different order, and were not compared:"
            )
        else:
            print(
                f"\n{max(len(plan.unidentified), len(plan.vanished))} paragraph(s) without "
                f"an identifier - a heading, list item, quotation or caption, new text, or a "
                f"paragraph tied to markup in or around it, such as display maths, a comment "
                f"closing past it, or a fence, `</div>` or definition directly under it - came "
                f"back different and were not compared:"
            )
        for text in plan.vanished[:12]:
            print(f"    - {text[:120]}")
        for text in plan.unidentified[:12]:
            print(f"    + {text[:120]}")
        for text in reordered[:shown]:
            print(f"    ~ {text[:120]}")
        if len(reordered) > shown:
            print(f"    ~ and {len(reordered) - shown} more")
        print(
            "    Not applied; make these edits in the .md. They also mark where sections "
            "begin, so a paragraph moved past one of them may not be reported as moved: "
            "compare the two documents as text before trusting the rest."
        )

    if plan.moved:
        print(f"{len(plan.moved)} paragraph(s) came back in a different place:")
        for name, was_at, now_at in plan.moved:
            print(f"    position {was_at} -> {now_at}: {opening(name)}")

    if plan.withheld:
        print(f"{len(plan.withheld)} paragraph(s) came back in a different place, not applied:")
        for name in plan.withheld:
            print(f"    {opening(name)}")
        print(
            "    Their section also came back with text the document as sent did not have - a "
            "paragraph split, a new one, a heading or caption edited - with a paragraph "
            "whose identifier is on other text, or with one among them that was not "
            "compared, so where each of its paragraphs now stands cannot be read with "
            "certainty. Move them in the .md yourself if the moves were intended."
        )
        for text in plan.held_by[:3]:
            print(f"    new text: {text.strip()[:110]}")

    verb = "merging" if applying else "would merge"
    for name, rebuilt in plan.merged.items():
        print(f"\n{verb} into {where(name)}:")
        print(f"    + {rebuilt.strip()[:150]}")

    for refusal in plan.refused:
        print(f"\nNOT merged into {where(refusal.name)}:")
        print(f"    + {refusal.text.strip()[:150]}")
        for line in refusal.why:
            print(f"    {line}")

    for group in plan.joined:
        home = next(name for name in group if name in known)
        print(f"\n{len(group)} paragraphs came back joined into one, in {where(home)}:")
        for name in group:
            print(f"    {opening(name)}")
        print(
            "    Not applied: each of them is left as it was. Join them in the .md yourself "
            "if that was intended, and make any rewording there."
        )

    for name, text in plan.displaced:
        print(f"\nmoved in Word, left in place here: {known[name][1].strip()[:110]}")
        print(f"    + {text.strip()[:150]}")
        print(
            "    Nothing in the returned document says which paragraph the copy above is - "
            "Word did not record the move, or recorded one that did not take whole "
            "paragraphs - so it is not applied. Move the paragraph in the .md, and make any "
            "rewording there. Do not delete it and retype Word's copy: its numbers and "
            "citations would come back as typed text, not as bindings."
        )

    for name in plan.gone:
        print(f"\ndeleted in Word, left in place here: {known[name][1].strip()[:110]}")
        print(
            "    delete it in the .md yourself if that was intended. If it was moved instead, "
            "move it in the .md: retyped from Word's copy, its numbers and citations would "
            "come back as typed text."
        )


def _seeded(
    source: Path, trusted: frozenset[str], followed: dict[str, str] | None = None
) -> list[dict]:
    """Reviewers and their points, read from the comments in a returned document.

    A comment keeps its paragraph only where the identifier is in `trusted`, still naming
    the text it named at the build, or `followed` to the identifier naming that text now
    (`roundtrip.Numbering.followed`), which is what G13 looks up. Anywhere else it would
    anchor the point to whatever paragraph sits there now, and G13 would then check the
    revision against the wrong one.

    A journal usually sends a PDF or an email and the points get typed in, which is where
    a point quietly becomes the easier point next to it. When the reviewer commented in a
    document this tool built, their words and the place they were about are both already in
    the file - and losing either on the way in is work the author redoes by hand.
    """
    from manuscript_guard.roundtrip import comments_in

    # Grouped by the slug, not the raw author. "Reviewer 2" and "REVIEWER 2" are two
    # buckets and one id, which put two people's points under one heading in the letter that
    # goes to the journal.
    anchors = {name: name for name in trusted} | (followed or {})
    by_author: dict[str, list[dict]] = {}
    for comment in comments_in(source):
        slug = re.sub(r"[^a-z0-9]+", "-", comment.author.lower()).strip("-")
        by_author.setdefault(slug or "reviewer", []).append(
            {
                "id": "",
                "comment": comment.text,
                "response": "",
                **({"where": anchors[comment.where]} if comment.where in anchors else {}),
            }
        )

    reviewers = []
    for index, (slug, points) in enumerate(sorted(by_author.items()), start=1):
        for position, point in enumerate(points, start=1):
            point["id"] = f"{index}.{position}"
        reviewers.append({"id": slug, "points": points})
    if reviewers:
        return reviewers
    empty = {"id": "1.1", "comment": "No comments found in the document.", "response": ""}
    return [{"id": "reviewer-1", "points": [empty]}]


def cmd_respond(args: argparse.Namespace) -> int:
    """Open a revision round, or write the point-by-point response.

    A response is a document made almost entirely of claims about the paper - "we have
    revised the Methods" - and nothing checked any of them. Opening a round records the
    manuscript as the journal received it, so each claim can be checked against whether the
    file it names actually changed.
    """
    import yaml

    from manuscript_guard.gates.review import file_digests
    from manuscript_guard.gates.revision import check_revision, rounds

    project, _ = load_project(args.path)

    if args.open:
        if args.source:
            # The same refusal `import` makes, for the same reason. Reading anchors out of a
            # document built from text that has since changed records a baseline describing
            # two different manuscripts - one command called that dangerous while the other
            # baked it into the revision record without a word.
            from manuscript_guard.gates.review import document_digest
            from manuscript_guard.roundtrip import (
                RoundTripError,
                numbering,
                numbering_refusal,
                stamp_of,
            )

            try:
                carried = stamp_of(args.source)
            except RoundTripError as exc:
                print(f"manuscript-guard: {exc}", file=sys.stderr)
                return 2
            if _refused_marked_up(args.source, "read for comments"):
                return 1
            if carried is None:
                # Not offered --force: there is no baseline to override. The refusal used to
                # suggest it, and then refused it.
                print(
                    f"{args.source.name} carries no record of the source it was built from, so "
                    f"there is no telling which paragraphs its comments point at. Only a "
                    f"document this tool built can seed a round, and --force does not change "
                    f"that.\n  Run `manuscript-guard respond --open` without --from and type "
                    f"the points into the round file."
                )
                return 1
            try:
                numbered = numbering(
                    project, args.source, stale=carried != document_digest(project)
                )
            except RoundTripError as exc:
                print(f"manuscript-guard: {exc}", file=sys.stderr)
                return 2
            if numbered.refusal:
                print(numbering_refusal(args.source.name, numbered.refusal))
                return 1
            trusted = numbered.trusted
            if numbered.unsure:
                # As `import` does: one the document carries, it was built with.
                from manuscript_guard.roundtrip import paragraph_order

                try:
                    trusted |= numbered.unsure & set(paragraph_order(args.source))
                except RoundTripError as exc:
                    print(f"manuscript-guard: {exc}", file=sys.stderr)
                    return 2
            if carried != document_digest(project) and not args.force:
                print(
                    f"{args.source.name} was not built from the manuscript as it now stands, "
                    f"so the paragraphs its comments point at are not the paragraphs on disk."
                    f"\n  Re-send a current build, or pass --force and check every anchor."
                )
                return 1

        number = max((n for n, _p in rounds(project)), default=0) + 1
        path = project.root / "revision" / f"round-{number}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema": "manuscript-guard/revision/1",
            "round": number,
            "journal": project.paper.get("target_journal", "the journal"),
            "received_on": date.today().isoformat(),
            "submitted_files": file_digests(project),
            "reviewers": _seeded(args.source, trusted, numbered.followed) if args.source else [
                {
                    "id": "reviewer-1",
                    "points": [
                        {
                            "id": "1.1",
                            "comment": "Quote the reviewer here, in their words.",
                            "response": "",
                        }
                    ],
                }
            ],
        }
        if args.source:
            # The paragraphs as they stood when the comments were made, so a point anchored
            # to one can be checked against that paragraph and not merely its file.
            # Hashed from the *source*, because that is what the gate re-hashes when it
            # checks. Hashing the .docx text instead made the two representations - rendered
            # prose against markdown carrying `{{bindings}}` - never equal, so the
            # comparison could not fire and the check was dead code. Its test passed because
            # the test built the baseline the way the gate reads it, not the way this
            # command writes it.
            from manuscript_guard.roundtrip import tagged_paragraphs

            document["submitted_paragraphs"] = {
                name: hashlib.sha256(entry[1].encode("utf-8")).hexdigest()
                for name, entry in tagged_paragraphs(project).items()
            }
        path.write_text(
            yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
            newline="\n",
        )
        print(f"opened {path.relative_to(project.root).as_posix()}")
        copied = _keep_submitted(project, number)
        print(
            f"  {copied.relative_to(project.root).as_posix()}/ keeps the manuscript as it "
            f"renders now, so a response that quotes the revised text is checked for saying "
            f"something the journal has not read"
        )
        from manuscript_guard.markedup.rounds import keep_sent

        kept, missing = keep_sent(project, number)
        for path in kept:
            print(
                f"  {path.relative_to(project.root).as_posix()} is the document the journal "
                f"received, which `build --marked-up` shows the revision's changes against"
            )
        if missing:
            print(f"  {missing}")
        if args.source:
            seeded = sum(len(r["points"]) for r in document["reviewers"])
            anchored = sum(
                1 for r in document["reviewers"] for p in r["points"] if p.get("where")
            )
            print(
                f"  {seeded} point(s) read from {args.source.name}, {anchored} of them "
                f"knowing which paragraph they are about."
            )
            from manuscript_guard.roundtrip import comments_in

            loose = sum(1 for c in comments_in(args.source) if c.where and c.where not in trusted)
            if loose:
                print(
                    f"  {loose} comment(s) were attached to a paragraph whose identifier no "
                    f"longer names the text commented on, so they are recorded without one: "
                    f"say in each point which paragraph it is about."
                )
        print(
            "  submitted_files records the manuscript as it stands now, which is what a\n"
            "  claimed revision is checked against. Open the round *before* you start\n"
            "  revising, or there is no baseline to compare with."
        )
        return 0

    # The same renderer the submission pack uses, so the letter an author reads here and the
    # letter the journal receives cannot come apart.
    from manuscript_guard.build.submission import response_letter

    letter = response_letter(project)
    if letter is None:
        print("no revision rounds. `manuscript-guard respond --open` starts one.")
        return 1

    output = project.path("build") / "response-to-reviewers.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(letter, encoding="utf-8", newline="\n")
    print(f"wrote {output.relative_to(project.root).as_posix()}")

    report = check_revision(project, submission=args.submission)
    print(report.render(project.root))
    return 0 if report.ok else 1


def _keep_submitted(project, number: int) -> Path:
    """Write each manuscript file as it renders now, bindings filled in, beside round
    `number`: the text the journal received, which a quoted revision must not be in."""
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.gates.revision import REVISION_DIR, SUBMITTED_DIR, displays
    from manuscript_guard.text.placeholders import substitute

    folder = project.root / REVISION_DIR / f"round-{number}" / SUBMITTED_DIR
    rendered = displays(project)
    manuscript = project.path("manuscript")
    for source in source_files(manuscript):
        target = folder / source.relative_to(manuscript)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(substitute(read_text(source), rendered), encoding="utf-8", newline="\n")
    return folder


def cmd_check(args: argparse.Namespace) -> int:
    report, project, stage, deferred = _run_gates(
        args.path, submission=args.submission, stage=args.stage
    )
    if args.json:
        print(report.to_json())
    else:
        print(f"manuscript-guard {__version__} — {project.root}")
        print(f"stage: {stage} ({DESCRIPTIONS[stage]})")
        print(report.render(project.root))
        print("\n" + "\n".join(assurance(report, project)))
        print(
            f"\n{len(report.failures)} failing, {len(report.warnings)} warning"
            f"{'' if len(report.warnings) == 1 else 's'}"
        )
        note = summarise_deferred(deferred)
        if note:
            print(note)
    return 0 if report.ok else 1


def cmd_hook(args: argparse.Namespace) -> int:
    """Handle a Claude Code hook event. Reads the event JSON on stdin."""
    from manuscript_guard.hooks import dispatch

    return dispatch(args.event)


def cmd_audit(args: argparse.Namespace) -> int:
    """Check an existing paper's numbers against existing outputs.

    For papers that were never written with this toolkit. Weaker than `check` by nature,
    and the report says how much weaker, measured against the outputs supplied.
    """
    from manuscript_guard.audit import (
        FIGURE_SUFFIXES,
        PAPER_SUFFIXES,
        audit,
        measure_discrimination,
        render,
    )

    def expand(given: list[Path], suffixes: set[str]) -> list[Path]:
        found: list[Path] = []
        for path in given:
            if path.is_dir():
                found += [
                    p
                    for p in sorted(path.rglob("*"))
                    if p.is_file() and p.suffix.lower() in suffixes
                ]
            elif path.is_file():
                found.append(path)
        return found

    # A path that is not there is a typo, and auditing without it answers a different
    # question: a missing output reports every number it held as absent from the paper.
    given = [*args.paper, *(args.against or []), *(args.figures or [])]
    missing = [path for path in given if not path.exists()]
    if missing:
        for path in missing:
            print(f"manuscript-guard audit: {path} does not exist", file=sys.stderr)
        return 2

    papers = expand(args.paper, PAPER_SUFFIXES)
    figures = expand(args.figures or [], FIGURE_SUFFIXES)
    if not papers and not figures:
        print("nothing to audit: no .docx or .md found in what you gave me", file=sys.stderr)
        return 2
    if not args.against:
        print("--against is required: point it at the analysis outputs", file=sys.stderr)
        return 2

    report = audit(papers, args.against, figures=figures,
                   whole_numbers=tuple(args.whole_numbers))  # fmt: skip
    if not report.backing_files:
        print("--against gave the audit nothing it can read:", file=sys.stderr)
        for item in report.skipped:
            print(f"  {item}", file=sys.stderr)
        return 2
    if not report.papers:
        # "Audited 0 file(s) … 0 not found" read as a clean report, and exited 0 under
        # --strict, when every paper given was unreadable.
        print("nothing given could be audited:", file=sys.stderr)
        for item in report.unreadable:
            print(f"  {item}", file=sys.stderr)
        return 2
    print(render(report, measure_discrimination(report.backing_values), Path.cwd()))
    if not report.examined:
        # An empty paper, or one whose numbers are all in pictures, printed "0 numeric
        # tokens" and passed --strict: an audit that read nothing.
        print(
            "the audit read no number in what it was given, so nothing was checked",
            file=sys.stderr,
        )
    # A paper or figure the audit could not read is a check that did not happen, which
    # --strict must not pass; nor is a paper with no number in it.
    failed = report.unmatched or report.unreadable or not report.examined
    return 1 if failed and args.strict else 0


def _reread(project, new: Path) -> int:
    """`journal --reread`: the stored page against the page read again, and the rules whose
    quotes it no longer holds. Writes nothing: adopting the page is the author's."""
    from manuscript_guard.gates.journal_quotes import DIFF_LINES, reread

    try:
        text = new.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"manuscript-guard: {new} cannot be read as UTF-8 text: {exc}", file=sys.stderr)
        return 2
    found = reread(project, text)
    if found is None:
        print("manuscript-guard: paper.yaml names no journal with a profile to read the page "
              "for", file=sys.stderr)  # fmt: skip
        return 2
    if not found.diff:
        print("The page read again is the stored page, word for word.")
    else:
        shown = list(found.diff[:DIFF_LINES])
        print("\n".join(shown))
        if len(found.diff) > DIFF_LINES:
            print(f"... and {len(found.diff) - DIFF_LINES} more lines of difference")
    gone = [key for key, on_page in found.rules if not on_page]
    print()
    for key, on_page in found.rules:
        print(f"  {'still on the page' if on_page else 'NOT on the page  '}  {key}")
    print()
    if gone:
        print(f"{len(gone)} rule(s) quote words the page no longer has: read each again, and "
              "correct its value and its quote, or remove it.")  # fmt: skip
    stored = found.stored
    inside = stored.is_relative_to(project.root)
    where = stored.relative_to(project.root).as_posix() if inside else str(stored)
    print(
        f"Read the difference for rules the page added, too. To adopt the page, save it over "
        f"{where}, then record page_sha256: {found.digest} and today's retrieved_on in the "
        "profile."
    )
    return 1 if gone else 0


def cmd_journal(args: argparse.Namespace) -> int:
    """Show the journal profiles available, or copy the annotated template into a project."""
    from manuscript_guard.gates.journal import available_profiles
    from manuscript_guard.paths import SHIPPED_JOURNALS

    project, contract_report = load_project(args.path)
    if not contract_report.ok:
        print(contract_report.render(project.root))
        return 2

    if args.reread:
        return _reread(project, args.reread)

    if args.template:
        source = SHIPPED_JOURNALS / "TEMPLATE.yaml"
        target = project.root / "profiles" / "journals" / f"{args.template}.yaml"
        if target.exists():
            print(f"{target} already exists; not overwriting", file=sys.stderr)
            return 2
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        print(f"created {target}")
        print(
            "\nFill it by reading the journal's own instructions page — the comments say what\n"
            "each field means and what to do when the page is silent. The answer to that last\n"
            "question is always to delete the line: an absent limit is not checked, and a\n"
            "guessed one is worse than none.\n"
            f"\nThen set `target_journal: {args.template}` in paper.yaml."
        )
        return 0

    chosen = project.target_journal
    print(f"target_journal: {chosen or '(none chosen)'}")
    found = available_profiles(project)
    print(f"profiles available: {', '.join(found) if found else 'none'}")
    if not found:
        print(
            "\nNone ship with the toolkit, on purpose: author guidelines change without\n"
            "announcement, so a rule compiled in would eventually be wrong and wrong silently.\n"
            "Start one with `manuscript-guard journal --template <slug>`."
        )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Re-run the analysis and check it still produces the recorded results.

    Separate from `check` on purpose: it executes the project's own code, which a gate must
    never do, and it takes as long as the analysis does.
    """
    from manuscript_guard.verify import VerifyError, render, verify

    project, contract_report = load_project(args.path)
    if not contract_report.ok:
        print(contract_report.render(project.root))
        return 2
    try:
        result = verify(project, only=args.only)
    except VerifyError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    print(f"manuscript-guard verify — {project.root}")
    print(render(result, project.root))
    if result.verified_nothing:
        # 2 is "could not run", which is exactly what this is. Exiting 0 here would make a
        # run that re-ran nothing indistinguishable, to CI, from one that reproduced
        # everything.
        print("\nNothing was re-run, so nothing was verified.", file=sys.stderr)
        return 2
    if not args.only:
        # What `check` says of reproducibility: a run of every script, and only that.
        record_verified(project, result)
    return 0 if result.ok else 1


def cmd_stages(args: argparse.Namespace) -> int:
    """What each stage means, and what starts to bind at it."""
    from manuscript_guard.policy import BINDS_AT

    for stage in STAGES:
        codes = sorted(code for code, at in BINDS_AT.items() if at == stage)
        print(f"{stage}\n  {DESCRIPTIONS[stage]}")
        if codes:
            print(f"  starts to fail: {', '.join(codes)}")
        print()
    print("Anything not listed fails at every stage: a gate has to opt in to being")
    print("deferred, so adding one cannot accidentally make it optional.")
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    """Everything that depends on each file named, or on each file changed since a commit.

    Read-only, and derived: it follows the records the gates read and keeps none of its own.
    """
    from manuscript_guard.impact import NoChanges, as_json, as_text, changed_files, impact_of

    # A folder was answered as one file no record names (round 1 of #280): its files are
    # what the records name, so it is refused rather than said to have nothing on it.
    for path in args.files:
        if path.is_dir():
            print(f"manuscript-guard: {path} is a folder; name the files in it, or name "
                  "none to take those changed since the last commit", file=sys.stderr)  # fmt: skip
            return 2
    start = args.files[0].parent if args.files else Path.cwd()
    project, _ = load_project(start)
    _namespace, results, literature, _ = load_namespace(project)
    files = list(args.files)
    if not files:
        try:
            files = changed_files(project, args.since)
        except NoChanges as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        if not files:
            if args.json:
                print("[]")
            else:
                print(f"nothing has changed since {args.since}")
            return 0
    impacts = [impact_of(project, results, literature, path) for path in files]
    # A name that is no file and that no record names is a slip of the keyboard, which was
    # answered as a file nothing depends on (round 1 of #280). A file deleted that a record
    # still names is answered: what depended on it is the question.
    named = zip(args.files, impacts, strict=True) if args.files else ()
    for path, impact in named:
        if not path.exists() and impact.empty:
            print(f"manuscript-guard: {path} does not exist, and no record names it",
                  file=sys.stderr)  # fmt: skip
            return 2
    if args.json:
        print(as_json(impacts))
        return 0
    for index, impact in enumerate(impacts):
        if index:
            print()
        print("\n".join(as_text(impact)))
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    """Show how every numeric atom in a file was classified.

    The gate is only trustworthy if its reasoning can be inspected, and an author arguing
    with a finding needs to see which rule fired rather than guess.
    """
    project, _ = load_project(args.file.parent)
    classifier = Classifier.load(project.extra_conventions, project.extra_terms)
    text = read_text(args.file)
    # The same section chain G2 uses. Without it every `methods_only` rule fired everywhere,
    # so `explain` reported a fabricated `p < 0.001` in the Results as a recognised
    # convention while `check` failed it — and this is the command an author reaches for
    # when a finding surprises them. Its answer was the input to deciding whether to add a
    # `conventions:` exemption, which is the one mechanism that makes G2 vacuous.
    headings = heading_index(text)
    notes = footnote_index(text)
    # A threshold the analysis declares is accepted by its convention and still fails
    # `check` typed, so this says so too, with the binding to write instead.
    namespace, _results, _literature, _loaded = load_namespace(project)
    choices = [value for value in namespace.values() if value.role]
    chosen = chosen_rules(classifier)
    rows = []
    for atom in find_atoms(text, mask(text)):
        verdict = classifier.classify_under(atom, chains_at(headings, notes, atom.start))
        typed = typed_choice(atom.text, verdict, choices, chosen)
        rule = verdict.rule or "-"
        if typed is not None:
            rule = f"{rule}, typed: write {typed.reference}"
        failed = verdict.kind == UNCLASSIFIED or typed is not None
        rows.append((atom.line, atom.text, verdict.kind, rule, failed))
    rows += _explained_refs(project, text)
    if not rows:
        print("no numeric atoms outside masked regions")
        return 0
    rows.sort(key=lambda row: row[0])
    width = max(len(r[1]) for r in rows)
    for line, atom_text, kind, rule, failed in rows:
        marker = "FAIL" if failed else "ok  "
        print(f"{marker} {line:>5}  {atom_text:<{width}}  {kind:<12} {rule}")
    return 0


def _explained_refs(project, text: str) -> list[tuple[int, str, str, str, bool]]:
    """A row for each ref and num binding of a file: what the build prints for it and from
    which display, or why it prints nothing (G2 says the same)."""
    from manuscript_guard.crossref import Refused
    from manuscript_guard.gates.pointers import display_numbers

    try:
        numbers = display_numbers(project)
    except Unreadable:
        # Another file of the manuscript cannot be read, so nothing can be counted; `check`
        # names it. This file's numbers are still explained.
        return []
    rows = []
    for placeholder in parse(text)[0]:
        if not placeholder.is_ref:
            continue
        display = numbers.display(placeholder)
        if isinstance(display, Refused):
            rows.append((placeholder.line, placeholder.raw, display.code, display.why, True))
            continue
        where = "the supplement" if display.supplementary else "the main text"
        shown = f"{placeholder.raw} -> {numbers.printed(placeholder)}"
        rule = f"numbered: {where}'s {display.kind} {display.number}, placed by {display.binding}"
        rows.append((placeholder.line, shown, "pointer", rule, False))
    return rows


def cmd_models(args: argparse.Namespace) -> int:
    """Print each model the analysis fitted as its card, with what G15 says of it.

    The card is what a co-author reads to say whether the model is the right one: what it is
    called, what the author says it is for, the sentence made from the fit, and each variable
    with the kind it was declared and how it entered."""
    from manuscript_guard.contracts.models import describe, table_rows

    project, _ = load_project(args.path)
    _namespace, results, _literature, _loaded = load_namespace(project)
    if not results.models:
        print("no models: an analysis records one with em.model() in Python, em$model() in R")
        return 0
    report = check_models(project, results)
    for key, model in results.models.items():
        print(f"{model.name}  (model.{key}, {model.source.name})")
        print(f"  fitted:      {model.kind or 'a model the toolkit has no name for'}")
        print(f"  formula:     {model.formula}")
        print(f"  from fit:    {describe(model, results.variables)}")
        print(f"  author says: {model.description or '(nothing)'}")
        rows = [["Variable", "Declared as", "Entered as", "Levels"]]
        rows += table_rows(model, results.variables)
        widths = [max(len(row[i]) for row in rows) for i in range(4)]
        for row in rows:
            cells = zip(row, widths, strict=True)
            print("    " + "  ".join(cell.ljust(width) for cell, width in cells))
        print(f"  converged:   {'yes' if model.converged else 'NO'}")
        mine = [f for f in report.findings if f.message.startswith(f"model {key!r}:")]
        for finding in mine:
            print(f"  [{finding.severity.upper()}] {finding.message.split(': ', 1)[1]}")
        print()
    # What G15 says of no one model, of a variable's data or of a name typed in the Methods,
    # counts in the exit code and so is printed.
    under_a_card = tuple(f"model {key!r}:" for key in results.models)
    for finding in report.findings:
        if not finding.message.startswith(under_a_card):
            where = f"{finding.path.name}:{finding.line}: " if finding.line else ""
            print(f"[{finding.severity.upper()}] {where}{finding.message}")
    return 0 if report.ok else 1


def cmd_passages(args: argparse.Namespace) -> int:
    """List each cited statement with the passages recorded for the works it cites, as G7
    finds them. Writes nothing. Exit 2 where `passages.yaml` cannot be used: every statement
    would be listed as carrying none."""
    import json

    from manuscript_guard.gates.passages import survey_of
    from manuscript_guard.literature.passages import listing, rendered

    project, _ = load_project(args.path)
    found, report = survey_of(project)
    if report.failures:
        for finding in report.failures:
            print(f"manuscript-guard passages: {finding.message}", file=sys.stderr)
        return 2
    sources = project.path("literature") / "sources"
    listed = listing(found, project.root, sources, missing=args.missing)
    print(json.dumps(listed, indent=2, ensure_ascii=False) if args.json else rendered(listed))
    return 0


def cmd_reworded(args: argparse.Namespace) -> int:
    """Compare the manuscript with what it was, and say what changed besides the wording.

    Exit 1 where a binding, a citation or a typed number is gone, new or changed; 0 where
    they all stand, in the same order or with a warning for each place where it differs; 2
    where there is no text before to compare with."""
    from manuscript_guard.reworded import NoBefore, against_commit, against_copy

    try:
        if args.before is not None:
            if len(args.paths) != 1:
                raise NoBefore(
                    "--before names the text one file had: give that one file, as in "
                    "`manuscript-guard reworded manuscript/main.md --before main-before.md`"
                )
            outcome = against_copy(args.paths[0], args.before)
        else:
            outcome = against_commit(args.paths or [Path.cwd()], args.since)
    except NoBefore as exc:
        print(f"manuscript-guard reworded: {exc}", file=sys.stderr)
        return 2

    report = outcome.report
    if args.json:
        print(report.to_json())
        return 0 if report.ok else 1

    def many(count: int, one: str) -> str:
        return f"{count} {one}" if count == 1 else f"{count} {one}s"

    counts = report.counts
    print(f"manuscript-guard {__version__} \N{EM DASH} {outcome.root}")
    print(
        f"compared with {outcome.against}: {many(counts.get('reworded_files', 0), 'file')}, "
        f"{many(counts.get('reworded_bindings', 0), 'binding')}, "
        f"{many(counts.get('reworded_citations', 0), 'citation')} and "
        f"{many(counts.get('reworded_numbers', 0), 'number')}"
    )
    print(Report(report.findings).render(outcome.root))
    print(
        f"\n{len(report.failures)} failing, {len(report.warnings)} warning"
        f"{'' if len(report.warnings) == 1 else 's'}"
    )
    return 0 if report.ok else 1


def cmd_render(args: argparse.Namespace) -> int:
    """Substitute bindings into build/, without producing a document yet."""
    project, _ = load_project(args.path)
    namespace, _results, _literature, load_report = load_namespace(project)
    if not load_report.ok:
        print(load_report.render(project.root))
        return 2

    from manuscript_guard.gates.pointers import display_numbers

    # A ref prints the number its table or figure has, as the build prints it.
    rendered = {ref: value.display for ref, value in namespace.items()}
    rendered |= display_numbers(project).bindings()
    out_dir = project.path("build") / "rendered"
    out_dir.mkdir(parents=True, exist_ok=True)
    manuscript_dir = project.path("manuscript")
    count = 0
    for path in source_files(manuscript_dir):
        target = out_dir / path.relative_to(manuscript_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            substitute(read_text(path), rendered),
            encoding="utf-8",
            newline="\n",
        )
        count += 1
    print(f"rendered {count} file{'' if count == 1 else 's'} to {out_dir}")
    return 0



def _build_annotated(project, namespace, results, assembled, args) -> int:
    """The copy a human checks by eye: every number coloured by what backs it.

    Built from the same assembly the real document uses, then re-run through the annotator,
    so the two cannot describe different text. Written under a name that says what it is,
    for the same reason an unchecked build is called UNCHECKED: this file must never be the
    one that reaches a journal.
    """
    from manuscript_guard.annotate import (
        annotate,
        appendix,
        figure_sheet,
        finish,
        legend,
        styled_reference,
    )
    from manuscript_guard.build.assemble import Assembled
    from manuscript_guard.build.document import pandoc
    from manuscript_guard.gates.pointers import display_numbers

    classifier = Classifier.load(project.extra_conventions, project.extra_terms)
    numbers = display_numbers(project)
    counter = [0]
    marked: list[Assembled] = []
    marks = []
    for item in assembled:
        source = read_text(item.path) if item.path.exists() else item.text
        text, found = annotate(
            source,
            namespace,
            classifier,
            counter=counter,
            results=results,
            project=project,
            pandoc=pandoc(),
            numbers=numbers,
        )
        marked.append(Assembled(path=item.path, text=text))
        marks.extend(found)

    build_dir = project.path("build")
    reference = styled_reference(pandoc(), build_dir / ".cache" / "annotated-reference.docx")
    result = build_document(
        project,
        marked,
        mode=OFFLINE if args.offline else LIVE,
        csl=_journal_style(project, args),
        output=build_dir / "manuscript.annotated.docx",
        reference_doc=reference,
        stamp=False,
        prologue=legend() + "\n\n",
        epilogue=appendix(marks) + figure_sheet(project, results),
        # Marked up for the author to read, not the document sent, which the plain build
        # checks from the same sources. The marks are checked where they are made:
        # `annotate` has pandoc read each file with them and without, and takes out every
        # mark of a paragraph that reads otherwise.
        verify_reading=False,
    )
    added = finish(result.output, marks)
    print(result.report.render(project.root))
    tiers: dict[str, int] = {}
    for mark in marks:
        tiers[mark.tier] = tiers.get(mark.tier, 0) + 1
    print(f"wrote {result.output}")
    print("  " + "  ".join(f"{tier}: {count}" for tier, count in sorted(tiers.items())))
    print(f"  {added} number(s) carry a hover showing where they came from")
    unmarked = sum(1 for mark in marks if mark.unmarked)
    if unmarked:
        print(
            f"  {unmarked} number(s) are not marked in the text, where a mark would change how "
            "it reads; the appendix lists each with the reason"
        )
    if tiers.get("defect"):
        print("  red marks a number bound to nothing. Yellow is not a verification.")
    return 0


def _print_assembly_warnings(report: Report, project) -> None:
    """Print what assembling found where it refused nothing: a warning, `two-titles`.

    `build` and `submit` printed assembling's report only when that held a failure, so a
    warning on its own was made and shown to nobody. Before the document is made, so that
    it is said whether or not pandoc then builds one. Without the counts, which say nothing
    beside a warning.
    """
    if report.findings:
        print(Report(report.findings).render(project.root))


def _refused_marked_up(document: Path, what: str) -> bool:
    """Say so and return True where `document` is a marked-up copy, which shows changes
    and is never the manuscript."""
    from manuscript_guard.markedup import marked_up_of

    if marked_up_of(document) is None:
        return False
    print(
        f"{document.name} is a marked-up copy: it shows the changes since a submission and "
        f"is not the manuscript, so it is not {what}. Use the document it was made from."
    )
    return True


def _marked_up(
    project, paper: Path, supplement: Path | None, *, since: Path | None,
    round_number: int | None, form: str, since_supplement: Path | None = None,
    by_option: bool = True,
) -> tuple[list[tuple[Path, Path]], list[str]]:  # fmt: skip
    """The marked-up copies of a built paper and supplement, each with the document it was
    compared with; and what to say of any not made. The supplement is held to the paper's
    rules: kept by the round as the paper is, or named with `since_supplement`, and marked
    up by the same comparison. Raises `MarkedUpError` where a copy asked for cannot be made,
    saying which. `by_option` is whether the command has `--since` and `--since-supplement`
    to name what was sent: `submit` has not. The caller takes earlier copies away first
    (`_cleared_marked_up`)."""
    from manuscript_guard.gates.revision import rounds
    from manuscript_guard.markedup import MarkedUpError
    from manuscript_guard.markedup.rounds import (
        PAPER,
        SUPPLEMENT,
        Asked,
        describe,
        make,
        sent_copy,
        target_for,
    )
    from manuscript_guard.roundtrip import RoundTripError, cited_of

    if since_supplement is not None and supplement is None:
        raise MarkedUpError("`--since-supplement` names a supplement, and none was built")
    numbers = [n for n, _path in rounds(project)]
    if round_number is not None and round_number not in numbers:
        raise MarkedUpError(f"there is no revision round {round_number}")
    number = round_number if round_number is not None else max(numbers, default=None)

    def sent(given: Path | None, name: str, option: str) -> Path | None:
        found = given if given is not None else (
            sent_copy(project, number, name) if number is not None else None
        )  # fmt: skip
        if found is not None and not found.is_file():
            raise MarkedUpError(f"{found} does not exist")
        if found is None and name == PAPER:
            where = (
                "no revision round is open"
                if number is None
                else f"round {number} kept no copy of the document the journal received"
            )
            named = f"name the document sent with `{option}`, or " if by_option else ""
            raise MarkedUpError(f"{where}; {named}put it at revision/round-<n>/submitted/{name}")
        return found

    asked = [(sent(since, PAPER, "--since"), paper)]
    notes: list[str] = []
    if supplement is not None:
        old_supplement = sent(since_supplement, SUPPLEMENT, "--since-supplement")
        if old_supplement is None:
            named = "name it with `--since-supplement`, or " if by_option else ""
            notes.append(
                "the supplement is not marked up: the round kept no copy of the one the "
                f"journal received; {named}put it at revision/round-<n>/submitted/{SUPPLEMENT}"
            )
        else:
            asked.append((old_supplement, supplement))
    made = []
    for old, new in asked:
        try:
            differ = cited_of(old) != cited_of(new)
        except RoundTripError:
            differ = False
        if differ:
            notes.append(
                f"{old.name} and {new.name} format their citations differently (live Zotero "
                f"fields against citeproc, or another style), so a citation may show as "
                f"changed that is not; build as the document sent was built"
            )
        target = target_for(project, new, form)
        try:
            result = make(project, Asked(old, new, target, number), form)
        except MarkedUpError as exc:
            which = "the supplement" if new == supplement else "the paper"
            kept = "".join(f"; {_shown_path(project, done)} was made" for _o, done in made)
            raise MarkedUpError(f"no marked-up copy of {which}: {exc}{kept}") from exc
        print(
            f"marked up {target.relative_to(project.root).as_posix()} against "
            f"{_shown_path(project, old)}: {describe(result)}"
        )
        made.append((old, target))
    return made, notes


def _refused_inputs(since: list[Path | None]) -> str | None:
    """Why the documents `--since` and `--since-supplement` name cannot be compared, before
    anything is taken away: a marked-up copy, which may be the very file a run would replace
    (round 2 of #396), or nothing at all."""
    from manuscript_guard.markedup import marked_up_of

    for given in since:
        if given is None:
            continue
        if not given.is_file():
            return f"{given} does not exist"
        if marked_up_of(given) is not None:
            return f"{given.name} is itself a marked-up copy; name the document that was sent"
    return None


def _cleared_marked_up(project) -> None:
    """Take away the marked-up copies an earlier run left in build/marked-up/, known by the
    property each carries and nothing else, so that a run that stops before it writes leaves
    none of an older source to be sent (round 2 of #396)."""
    from manuscript_guard.markedup import marked_up_of
    from manuscript_guard.markedup.rounds import FOLDER

    folder = project.path("build") / FOLDER
    for path in sorted(folder.glob("*.docx")) if folder.is_dir() else []:
        if marked_up_of(path) is not None:
            path.unlink()


def _shown_path(project, path: Path) -> str:
    try:
        return path.resolve().relative_to(project.root.resolve()).as_posix()
    except ValueError:
        return str(path)


def cmd_build(args: argparse.Namespace) -> int:
    """Produce the .docx. Gates run first unless the author insists otherwise.

    Building without checking is offered because an author mid-draft wants to see the
    document, not a list of unfinished bindings. It is a flag rather than the default,
    so that the version you send anyone has passed.
    """
    marked_up = getattr(args, "marked_up", False)
    if marked_up and getattr(args, "annotated", False):
        print("manuscript-guard: --marked-up and --annotated make different copies; ask for "
              "one at a time", file=sys.stderr)  # fmt: skip
        return 2
    marked_options = ("since", "since_supplement", "round", "highlight")
    if not marked_up and any(getattr(args, name, None) for name in marked_options):
        print("manuscript-guard: --since, --since-supplement, --round and --highlight go with "
              "--marked-up", file=sys.stderr)  # fmt: skip
        return 2
    report, project, _stage, _deferred = _run_gates(
        args.path, submission=args.submission, stage=getattr(args, "stage", None)
    )
    if marked_up:
        refused = _refused_inputs([args.since, args.since_supplement])
        if refused is not None:
            print(f"manuscript-guard: no marked-up copy: {refused}", file=sys.stderr)
            return 1
        _cleared_marked_up(project)
    if not report.ok and not args.skip_checks:
        print(report.render(project.root))
        print(f"\n{len(report.failures)} failing; not building. Use --skip-checks to override.")
        return 1

    namespace, results, _literature, _ = load_namespace(project)
    assembled, assemble_report = assemble(project, namespace, results)
    if not assemble_report.ok:
        print(assemble_report.render(project.root))
        return 1
    _print_assembly_warnings(assemble_report, project)

    if getattr(args, "annotated", False):
        # Wrapped like the ordinary build. Without this a pandoc failure - Zotero down
        # being the common one - came out of the annotated path as a Python traceback
        # instead of the message that names `--offline`.
        try:
            return _build_annotated(project, namespace, results, assembled, args)
        except BuildError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            if not args.offline:
                print(
                    "  If Zotero is not running, `--offline` formats citations from "
                    "references.bib instead.",
                    file=sys.stderr,
                )
            return 2

    mode = OFFLINE if args.offline else LIVE
    # An unchecked build gets a name that says so. Left as `manuscript.docx` it is the file
    # a co-author opens and a journal receives, and reverting the source afterwards makes
    # `check` pass while the stale document still holds the wrong number — the check and the
    # artefact disagreeing, silently, with nothing on disk recording which one was skipped.
    output = args.output
    if output is None and not report.ok:
        output = project.path("build") / "manuscript.UNCHECKED.docx"

    style = _journal_style(project, args)
    try:
        result = build_document(project, assembled, mode=mode, csl=style, output=output)
    except MisreadError as exc:
        # A refusal, like a failing gate, not a build that could not run.
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 1
    except BuildError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        if not args.offline:
            print(
                "  If Zotero is not running, `--offline` formats citations from "
                "references.bib instead.",
                file=sys.stderr,
            )
        return 2

    print(f"built {result.output} ({result.mode})")
    if not report.ok:
        print(
            f"{len(report.failures)} check(s) were failing, so this is named UNCHECKED. "
            f"Fix them and rebuild before sending it anywhere."
        )
    if result.report.findings:
        print(result.report.render(project.root))
    fields = result.report.counts.get("zotero_fields")
    if fields:
        print(f"{fields} live Zotero citation field{'' if fields == 1 else 's'}")

    try:
        supplement = _build_supplement(project, assembled, mode=mode, csl=style)
    except MisreadError as exc:
        print(f"manuscript-guard: the supplement is not built: {exc}", file=sys.stderr)
        return 1
    if supplement is not None:
        print(f"built {supplement} (supplementary material, its own document)")
    # Built, and said, but not to be sent: the journal's review is blind and the document
    # names an author. The supplement's findings were printed as it was built.
    from manuscript_guard.build.blinding import CODE, check_blinded

    named = any(f.code == CODE for f in result.report.failures)
    if supplement is not None:
        named = named or not check_blinded(project, supplement).ok
    if getattr(args, "marked_up", False):
        from manuscript_guard.markedup import MarkedUpError

        form = "highlighted" if args.highlight else "tracked"
        try:
            made, notes = _marked_up(
                project, result.output, supplement, since=args.since,
                round_number=args.round, form=form, since_supplement=args.since_supplement,
            )  # fmt: skip
        except MarkedUpError as exc:
            message = str(exc)
            if not message.startswith("no marked-up copy"):
                message = f"no marked-up copy: {message}"
            print(f"manuscript-guard: {message}", file=sys.stderr)
            return 1
        for note in notes:
            print(f"  {note}")
        for _old, marked in made:
            blind = check_blinded(project, marked)
            if not blind.ok:
                print(blind.render(project.root))
                named = True
    if named:
        print("The document names an author, and the journal's review is blind: do not send it.")
        return 1
    return 0


def _build_supplement(project, assembled, *, mode: str, csl: Path | None) -> Path | None:
    """The supplement, as its own document. `None` when the project has none.

    Built alongside the paper rather than on request, because a supplement that has to be
    asked for is one that arrives at the journal a version behind the manuscript it belongs
    to. A failure here is reported and does not fail the build: the paper is what the author
    was making. A refusal does (`MisreadError`, raised): pandoc reads the supplement
    otherwise than the gates did, and the one from the last build is removed with it.
    """
    from manuscript_guard.gates.numbers import is_supplementary

    manuscript_dir = project.path("manuscript")
    if not any(is_supplementary(manuscript_dir, a.path) for a in assembled):
        return None
    try:
        built = build_document(project, assembled, mode=mode, csl=csl, supplementary=True)
    except MisreadError:
        raise
    except BuildError as exc:
        print(f"manuscript-guard: the supplement did not build: {exc}", file=sys.stderr)
        return None
    if built.report.findings:
        print(built.report.render(project.root))
    return built.output


def cmd_submit(args: argparse.Namespace) -> int:
    """Assemble everything a journal asks for, once the submission check passes."""
    from manuscript_guard.build import SubmissionError, assemble_pack

    report, project, _stage, _deferred = _run_gates(args.path, submission=True)
    from manuscript_guard.gates.revision import rounds

    # A marked-up copy given as the document is refused by name before the copies are
    # cleared: in build/marked-up/, it would be taken away first and reported missing.
    if args.document is not None and _refused_marked_up(args.document, "packed as the manuscript"):
        return 1
    if rounds(project):
        # Before anything can stop the pack, as `build` does: a copy left by an earlier run
        # is of an older source (round 3 of #396).
        _cleared_marked_up(project)
    if not report.ok and not args.skip_checks:
        print(report.render(project.root))
        print(
            f"\n{len(report.failures)} failing. A submission pack is the version you send "
            f"anywhere, so it is not assembled while anything is outstanding.\n"
            f"Use --skip-checks only to see what the pack would contain."
        )
        return 1

    namespace, results, _literature, _ = load_namespace(project)
    assembled, assemble_report = assemble(project, namespace, results)
    if not assemble_report.ok:
        print(assemble_report.render(project.root))
        return 1
    _print_assembly_warnings(assemble_report, project)

    document = args.document
    if document is None:
        mode = OFFLINE if args.offline else LIVE
        style = _journal_style(project, args)
        try:
            built = build_document(project, assembled, mode=mode, csl=style)
        except MisreadError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 1
        except BuildError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        # `build` prints this report and `submit` used to drop it, so `submit` verified
        # strictly less than an ordinary build. The finding it discarded was
        # `no-live-citations` — the case where the Zotero filter failed quietly and every
        # citation in the pack is dead text that vanishes when someone hits Refresh in Word.
        # That is the least acceptable place to be the quieter command.
        if built.report.findings:
            print(built.report.render(project.root))
        if not built.report.ok:
            print("\nThe document did not build cleanly. The pack is not assembled.")
            return 1
        document = built.output
        # Built here as well as in `build`, so the supplement in the pack is the one that
        # belongs to this manuscript. Taking whatever `supplementary.docx` happened to be
        # lying in build/ is how a supplement arrives at a journal a version behind the
        # paper it is supplementing.
        try:
            _build_supplement(project, assembled, mode=mode, csl=style)
        except MisreadError as exc:
            print(f"manuscript-guard: the supplement is not built: {exc}", file=sys.stderr)
            print("\nThe pack is not assembled.")
            return 1

    # A build refused as a misread removes its document and its supplement, and a pack was
    # then assembled without either, and reported as made.
    from manuscript_guard.build.submission import supplement_for
    from manuscript_guard.gates.numbers import is_supplementary

    supplement = supplement_for(project, document)
    wants_supplement = any(
        is_supplementary(project.path("manuscript"), p)
        for p in source_files(project.path("manuscript"))
    )
    for needed in [document, *([supplement] if wants_supplement else [])]:
        if not needed.is_file():
            print(f"manuscript-guard: {needed} does not exist; build it first", file=sys.stderr)
            return 2
    # The document packed may be a copy a co-author edited in Word, which is where the
    # author fields come from; the build checked only the one it made.
    from manuscript_guard.build.blinding import check_blinded

    # At a revision, the copy that shows what changed since the round's document, which
    # journals ask for beside the manuscript itself.
    marked: list[tuple[Path, str]] = []
    marked_notes: list[str] = []
    if rounds(project):
        from manuscript_guard.markedup import MarkedUpError

        form = "highlighted" if args.highlight else "tracked"
        try:
            made, marked_notes = _marked_up(
                project, document, supplement if wants_supplement else None,
                since=None, round_number=None, form=form, by_option=False,
            )  # fmt: skip
        except MarkedUpError as exc:
            marked_notes = [f"no marked-up copy is packed: {exc}"]
            made = []
        suffix = "-highlighted" if form == "highlighted" else "-marked-up"
        marked = [(path, f"{path.name.split('.')[0]}{suffix}.docx") for _old, path in made]

    packed = [document] if args.document is not None else []
    packed += [supplement] if wants_supplement else []
    packed += [path for path, _name in marked]
    blind = merge_all([check_blinded(project, path) for path in packed])
    if not blind.ok:
        print(blind.render(project.root))
        print("\nThe document names an author, or could not be read to tell, and the "
              "journal's review is blind. The pack is not assembled.")  # fmt: skip
        return 1

    try:
        pack = assemble_pack(project, document, checked=report.ok, extra=marked)
    except SubmissionError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    print(f"submission pack: {pack.directory}")
    if not report.ok:
        print(f"  assembled with --skip-checks; {pack.manifest.name} records that.")
    for path in pack.files:
        print(f"  {path.relative_to(pack.directory)}")
    print(f"  {pack.manifest.name}")
    for note in (*pack.notes, *marked_notes):
        print(f"  {note}")
    # Said, and not refused: whether to send without an approval is the corresponding
    # author's call, and an approval given by e-mail is still one.
    from manuscript_guard.approvals import check_approvals

    approvals = check_approvals(project)
    if approvals.findings:
        print()
        print(approvals.render(project.root))
    print("\nStill to write by hand: the covering letter. No file in the project holds it.")
    _declare_in_letter(project)
    return 0


def _declare_in_letter(project) -> None:
    """The earlier outputs the covering letter has to declare: G8 sees whether the manuscript
    cites them, and no file holds the letter."""
    from manuscript_guard.literature.related import load_related

    try:
        related, _ = load_related(project)
    except ContractError:
        return
    overlapping = [o for o in related.outputs if o.overlaps] if related else []
    if overlapping:
        print("Declare in it the earlier outputs this paper overlaps with (ICMJE):")
        for output in overlapping:
            print(f"  {output.kind}: {output.citekey or output.title}")


def cmd_approve(args: argparse.Namespace) -> int:
    """Record an author's approval of the manuscript as it stands. The author's own act."""
    from manuscript_guard.approvals import NoSuchAuthor, approve, find_author, name_of

    project, _ = load_project(args.path)
    try:
        author = find_author(project, args.as_)
    except NoSuchAuthor as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    path = approve(project, author, args.note)
    print(f"{name_of(author)} approved the manuscript as it stands: {path}")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    """Record a named person's sign-off of a finding only they may close. Their own act."""
    from manuscript_guard.approvals import NoSuchAuthor
    from manuscript_guard.gates.design_review import override_signables
    from manuscript_guard.gates.journal_quotes import manual_signables
    from manuscript_guard.gates.models import signables
    from manuscript_guard.panel.custodian import send_signables
    from manuscript_guard.sign_offs import CORRESPONDING, ROLES, holder, is_holder, sign

    project, _ = load_project(args.path)
    _namespace, results, _literature, _loaded = load_namespace(project)
    standing = signables(project, results) + override_signables(project) + \
        manual_signables(project) + send_signables(project)  # fmt: skip
    found = [signable for signable in standing if signable.id == args.finding]
    if not found:
        ids = ", ".join(signable.id for signable in standing) or "none"
        print(
            f"manuscript-guard: no finding {args.finding} stands to be signed off "
            f"(those that do: {ids})",
            file=sys.stderr,
        )
        return 2
    signable = found[0]
    role = ROLES[signable.role]
    try:
        person = holder(project, signable.role)
    except NoSuchAuthor as exc:
        print(f"manuscript-guard: roles: {signable.role} in authors.yaml: {exc}", file=sys.stderr)
        return 2
    if person is None:
        # The corresponding author is marked on an author, not named under `roles:`, whose
        # schema refuses the key (round 1 of #318).
        missing = f"names no {signable.role} under `roles:`"
        if signable.role == CORRESPONDING:
            missing = "marks no single author `corresponding: true`"
        print(
            f"manuscript-guard: authors.yaml {missing}; only {role} signs off {signable.id}",
            file=sys.stderr,
        )
        return 2
    if not is_holder(project, person, args.as_):
        print(
            f"manuscript-guard: {args.as_!r} is not {role}; authors.yaml names {person.name}",
            file=sys.stderr,
        )
        return 2
    path = sign(project, signable, person, args.note)
    print(f"{person.name}, {role}, signed off {signable.id} as it stands: {path}")
    return 0


def cmd_sync_bib(args: argparse.Namespace) -> int:
    """Rewrite literature/references.bib from what the manuscript cites."""
    from manuscript_guard.zotero import ZoteroUnavailable

    project, _ = load_project(args.path)
    try:
        path, count = sync_bib(project)
    except ZoteroUnavailable as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {count} reference{'' if count == 1 else 's'} to {path}")
    return 0


def cmd_sync_sources(args: argparse.Namespace) -> int:
    """Copy each cited work's PDF, saved page or text from Zotero into literature/sources/, or
    each PDF of a folder named by DOI with `--from`."""
    from manuscript_guard.literature import copies, downloads
    from manuscript_guard.zotero import ZoteroUnavailable

    project, _ = load_project(args.path)
    try:
        offered = None if args.source is None else downloads.offer(project, args.source)
        outcomes = copies.sync(project, dry_run=args.dry_run, offered=offered)
    except (ZoteroUnavailable, copies.NothingToCopy, downloads.FolderUnreadable) as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    for line in copies.report(outcomes, dry_run=args.dry_run, offered=offered):
        print(line)
    return 0


def cmd_related(args: argparse.Namespace) -> int:
    """Copy an earlier output's project in, or list how this paper compares with each."""
    import json

    from manuscript_guard.gates.related import compare_related
    from manuscript_guard.literature.related import TakeError, load_related, read_snapshot, take

    project, _ = load_project(args.path)
    related, report = load_related(project)
    if related is None:
        if report.findings:
            print(report.render(project.root), file=sys.stderr)
            return 2
        print("manuscript-guard: there is no literature/related.yaml; the related-outputs "
              "skill says how to write one", file=sys.stderr)  # fmt: skip
        return 2
    if args.take is not None:
        return _take(project, related, args.take, take, TakeError)
    namespace, results, _literature, _loaded = load_namespace(project)
    found, rows = compare_related(project, namespace, results)
    if args.json:
        print(json.dumps({
            "outputs": [
                {"id": o.id, "kind": o.kind, "citekey": o.citekey, "title": o.title,
                 "shares": list(o.shares),
                 "copy": getattr(read_snapshot(project, o.id)[0], "manifest", None),
                 "compared": [vars(r) for r in rows if r.output == o.id]}
                for o in related.outputs
            ],
            "findings": [f.as_dict() for f in found.findings],
        }, indent=2, ensure_ascii=False))  # fmt: skip
        return 0
    for output in related.outputs:
        print(f"{output.name}, {output.kind}, shares {' and '.join(output.shares)}")
        copy = read_snapshot(project, output.id)[0]
        if copy is not None:
            m = copy.manifest
            at = f" at {m['revision']}" if m.get("revision") else ""
            commit = f" (commit {m['commit'][:12]})" if m.get("commit") else ""
            print(f"  copy of {m['project']}{at}{commit}, taken {m['taken_on']}")
        for row in (r for r in rows if r.output == output.id):
            named = row.earlier if row.earlier == row.here else f"{row.earlier} = {row.here}"
            print(f"  {named}: {row.then} there, {row.now} here: {row.state}")
    print()
    print(found.render(project.root))
    return 0


def _take(project, related, wanted: list[str], take, failed) -> int:
    """Copy each named output's project in; all those that name one where none is named."""
    known = {output.id: output for output in related.outputs}
    unknown = [name for name in wanted if name not in known]
    if unknown:
        print(f"manuscript-guard: no earlier output is named {', '.join(unknown)} in "
              "literature/related.yaml", file=sys.stderr)  # fmt: skip
        return 2
    chosen = [known[name] for name in wanted] or [o for o in related.outputs if o.project]
    if not chosen:
        print("manuscript-guard: no earlier output names its project (`project:`), so there "
              "is nothing to copy", file=sys.stderr)  # fmt: skip
        return 2
    code = 0
    for output in chosen:
        try:
            record = take(project, output)
        except failed as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            code = 2
            continue
        try:
            into = record.parent.relative_to(project.root).as_posix()
        except ValueError:  # `paths:` can put the literature folder outside the project
            into = str(record.parent)
        at = f" at {output.revision}" if output.revision else ""
        print(f"{output.id}: copied {output.project}{at} into {into}/")
    return code


def cmd_lookup(args: argparse.Namespace) -> int:
    """Look up each cited reference's DOI and PMID, and write what came back."""
    from manuscript_guard.lookup import run as lookup

    project, _ = load_project(args.path)
    if args.journals:
        return _lookup_journals(project, args)
    empty = why_no_manuscript(project)
    bib = project.path("literature") / lookup.BIB_FILE
    if empty or not bib.is_file():
        reason = empty or f"there is no {bib.relative_to(project.root).as_posix()}"
        print(f"manuscript-guard: nothing to look up: {reason}", file=sys.stderr)
        return 2
    planned = lookup.plan(project, again=args.again)
    due = [p for p in planned if not p.skipped]
    for one in planned:
        if one.skipped and one.skipped != "up to date":
            print(f"@{one.citekey}: not looked up: {one.skipped}")
    if not planned:
        print("the manuscript cites nothing, so nothing was looked up")
        return 0
    if args.dry_run:
        for one in due:
            ids = ", ".join(f"{k} {v}" for k, v in (("DOI", one.doi), ("PMID", one.pmid)) if v)
            what = f"look up {ids}" if ids else "search PubMed, Crossref and OpenAlex for its title"
            print(f"@{one.citekey}: would {what} ({one.again})")
        print(f"{len(due)} to look up, {len(planned) - len(due)} not; nothing was sent")
        return 0
    written = lookup.run(
        project, planned, credentials=lookup.Credentials.from_environment(project)
    )
    late = sum(
        1
        for _one, record, _path in written
        if any(s["status"] == "unresolvable" for s in record["sources"].values())
    )
    up_to_date = sum(1 for p in planned if p.skipped == "up to date")
    print(
        f"{len(written)} looked up, {up_to_date} up to date; records in "
        f"{(project.path('literature') / 'lookups').relative_to(project.root).as_posix()}/"
    )
    if late:
        print(
            f"{late} had an answer that did not come; `manuscript-guard lookup` asks again "
            "for those"
        )
        return 1
    return 0


#: The longest query sent: a search is for a topic, and a passage of the manuscript pasted
#: in would leave the machine with it.
MAX_QUERY = 300


def _search_filters(args: argparse.Namespace):
    """The filters as asked, or the reason they cannot be used."""
    from manuscript_guard.lookup.search import LANGUAGES, MAX_LIMIT, TYPES, Filters

    types = tuple(dict.fromkeys(t.strip() for given in args.type or [] for t in given.split(",")
                                if t.strip()))  # fmt: skip
    unknown = [t for t in types if t not in TYPES]
    if unknown:
        return f"no type {', '.join(map(repr, unknown))}; the types are {', '.join(TYPES)}"
    language = args.language.strip().lower() if args.language else None
    if language and language not in LANGUAGES:
        return (f"no language {args.language!r}; give it in two letters, one of "
                f"{', '.join(sorted(LANGUAGES))}")  # fmt: skip
    if args.since is not None and not 1000 <= args.since <= 9999:
        return f"--since takes a year, not {args.since}"
    if not 1 <= args.limit <= MAX_LIMIT:
        return f"--limit takes 1 to {MAX_LIMIT}, not {args.limit}"
    return Filters(since=args.since, types=types, language=language, limit=args.limit)


def cmd_search(args: argparse.Namespace) -> int:
    """Ask open registries for works a claim could cite. It proposes; it writes nothing."""
    import json

    from manuscript_guard.contracts.project import find_root
    from manuscript_guard.lookup import proposals
    from manuscript_guard.lookup.run import Credentials

    query = " ".join(args.query.split())
    if not query:
        print("manuscript-guard: nothing to search for: the query is empty", file=sys.stderr)
        return 2
    if len(query) > MAX_QUERY:
        print(
            f"manuscript-guard: a query of {len(query)} characters is not sent: write the "
            f"topic in at most {MAX_QUERY}, not a passage of the manuscript",
            file=sys.stderr,
        )
        return 2
    filters = _search_filters(args)
    if isinstance(filters, str):
        print(f"manuscript-guard: {filters}", file=sys.stderr)
        return 2
    project = None
    try:
        find_root(args.root or Path.cwd())
    except ContractError:
        if args.root is not None:
            raise
    else:
        project, _ = load_project(args.root or Path.cwd())
    credentials = Credentials.from_environment(project)
    if args.dry_run:
        for name, request in proposals.planned(query, filters, credentials, proposals.Services()):
            print(f"{proposals.NAMES[name]}: would ask {request.shown}")
        print("then PubMed for what each PMID it finds is, OpenAlex about the works it did not "
              "return, and Crossref about each preprint; nothing was sent")  # fmt: skip
        return 0
    result = proposals.run(query, filters, sort=args.sort, credentials=credentials)
    said = (json.dumps(proposals.as_json(result), indent=2, ensure_ascii=False)
            if args.json else proposals.render(result))  # fmt: skip
    if any(secret in said for secret in credentials.secrets):
        raise RuntimeError("the search's answer would have printed a key or the contact address")
    print(said)
    return 0 if proposals.answered(result) else 1


def cmd_style(args: argparse.Namespace) -> int:
    """Fetch the target journal's citation style from the CSL style repository, and keep it
    in the project for the offline build."""
    from manuscript_guard import journal_style
    from manuscript_guard.contracts._schema import read_structured
    from manuscript_guard.gates.journal import profile_path
    from manuscript_guard.lookup import styles

    project, _ = load_project(args.path)
    slug = project.target_journal
    path = profile_path(project, slug) if slug else None
    document = read_structured(path) if path is not None else None
    named = journal_style.profile_style(document) if isinstance(document, dict) else ""
    if not named:
        reason = (
            "paper.yaml names no target journal" if not slug
            else f"there is no profile for {slug}" if path is None
            else f"the profile of {slug} names no style (`references: {{csl: ...}}`)"
        )  # fmt: skip
        print(f"manuscript-guard: no style to fetch: {reason}", file=sys.stderr)
        return 2
    name = journal_style.style_name(named)
    if name is None:
        # Round 1 of #322: "vancouver.csl" was asked for as vancouver.csl.csl.
        stem = journal_style.name_of_file(named)
        file_named = f" (without its `.csl`: {stem!r})" if stem else ""
        print(
            f"manuscript-guard: {named!r} is not the name of a style in the CSL style "
            f"repository{file_named}, nor its zotero.org/styles URL; pass a style file to the "
            "build with `--csl FILE` instead",
            file=sys.stderr,
        )
        return 2
    record = journal_style.read_record(project, name)
    if record is not None and not journal_style.changed(project, record) and not args.again:
        print(f"{name}: kept since {record['retrieved_on']}, and unchanged; nothing was sent")
        return 0
    if args.dry_run:
        print(f"would fetch {name} from the CSL style repository; nothing was sent")
        return 0
    try:
        record = styles.store(project, name)
    except styles.NotFetched as exc:
        print(f"manuscript-guard: {exc}; nothing was written", file=sys.stderr)
        return 1
    parent = record.get("parent")
    where = journal_style.folder(project).relative_to(project.root).as_posix()
    print(
        f"stored {name}"
        + (f", and {parent['style']}, the style it depends on," if parent else "")
        + f" in {where}/{name}/; an offline build formats with it"
    )
    licence = record.get("licence") or (parent or {}).get("licence") or "see the files"
    print(
        "The styles are the CSL project's, under the licence each file names "
        f"({licence}): keep the notices in them."
    )
    return 0


def _journal_style(project, args: argparse.Namespace) -> Path | None:
    """The style an offline build formats with: `--csl` where it is given, or else the target
    journal's, where `manuscript-guard style` keeps it unchanged. None for pandoc's default.
    A live build formats in Zotero, with the style the profile names."""
    if args.csl is not None or not getattr(args, "offline", False):
        return args.csl
    from manuscript_guard.gates.journal import _profile
    from manuscript_guard.journal_style import profile_style, read_record, stored, style_name

    document = _profile(project)
    named = profile_style(document) if document is not None else ""
    found = stored(project, named) if named else None
    if named and found is None:
        # One never fetched is not one changed since (round 1 of #322: both were said to be).
        name = style_name(named)
        kept = bool(name) and read_record(project, name) is not None
        said = "is not kept as it was fetched" if kept else "is not kept"
        print(
            f"the journal's citation style {named} {said}, so citations are in pandoc's "
            "default style; `manuscript-guard check` says why"
        )
    return None if found is None else found.path


def _lookup_journals(project, args: argparse.Namespace) -> int:
    """`lookup --journals`: each ISSN of the shortlist asked of the NLM Catalog and DOAJ."""
    from manuscript_guard.contracts._schema import read_structured, validate
    from manuscript_guard.lookup import journals
    from manuscript_guard.lookup.run import Credentials
    from manuscript_guard.shortlist import issns, shortlist_path

    path = shortlist_path(project)
    document = read_structured(path)
    where = path.relative_to(project.root).as_posix()
    if document is None:
        print(f"manuscript-guard: nothing to look up: there is no {where}", file=sys.stderr)
        return 2
    checked = validate(document, "shortlist", path)
    if not checked.ok:
        print(checked.render(project.root), file=sys.stderr)
        print(f"manuscript-guard: {where} is not valid; nothing was looked up", file=sys.stderr)
        return 2
    wanted = issns(document)
    if not wanted:
        print(f"{where} gives no ISSN, so nothing was looked up")
        return 0
    due = journals.due(project, wanted, again=args.again)
    if args.dry_run:
        for issn in due:
            print(f"ISSN {issn}: would ask the NLM Catalog and DOAJ")
        print(f"{len(due)} to look up, {len(wanted) - len(due)} not; nothing was sent")
        return 0
    written = journals.run(project, due, credentials=Credentials.from_environment(project))
    late = sum(
        1
        for record, _path in written
        if any(s["status"] == "unresolvable" for s in record["sources"].values())
    )
    up_to_date = len(wanted) - len(due)
    print(f"{len(written)} looked up, {up_to_date} up to date; records in journals/lookups/")
    if late:
        print(f"{late} had an answer that did not come; `lookup --journals` asks again for those")
        return 1
    return 0


def cmd_checklist(args: argparse.Namespace) -> int:
    """Write or extend the completion file for a reporting guideline."""
    project, _ = load_project(args.path)
    names = [args.guideline] if args.guideline else list(project.reporting_guidelines)
    if not names:
        print("no reporting guideline set in paper.yaml, and none named", file=sys.stderr)
        return 2

    for name in names:
        try:
            path, total, added = scaffold_completion(project, name)
        except FileNotFoundError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        if added:
            print(f"{path}: {total} items, {added} new to answer")
        else:
            print(f"{path}: {total} items, all already present")
    return 0


def _checking_items(project, named: Path | None):
    """What this project offers a co-author: what the toolkit finds, plus what the project adds.

    The toolkit finds the values quoted from the literature, the sentences that cite something,
    the references and the authors. A number transcribed from a table in a source document is not
    among them and cannot be — only the project knows where that one came from — so a project
    that traces its own writes `checks/items.json`, and those go in front.
    """
    from manuscript_guard.checking.items import SCHEMA, ItemsError, items_file, items_from
    from manuscript_guard.checking.produce import merge, produce
    from manuscript_guard.contracts._schema import read_structured

    # The project's file is read raw and checked once, with the toolkit's, after the merge.
    # Reading it through `load_items` instead returned items carrying the `digest` it adds, and
    # the schema forbids a property it does not know: every project that had an items file of
    # its own — the only ones that had anything to merge — was refused, item by item.
    contributed = None
    source = items_file(project.root, named)
    if source.is_file():
        try:
            contributed = read_structured(source) or {}
        except Exception as exc:  # noqa: BLE001 — any unreadable file is one message
            raise ItemsError(f"{source} cannot be read: {exc}") from exc
        if not isinstance(contributed, dict):
            items_from(contributed, source)
        if contributed.get("schema") != SCHEMA:
            # Checked here because the merged document carries the toolkit's own schema key, so
            # a wrong one in the project's file would otherwise pass unremarked.
            raise ItemsError(
                f"{source}: schema is {contributed.get('schema')!r}, and this reads {SCHEMA!r}"
            )
        # And checked against the schema **before** the merge. The merge reads each item's `id`
        # and `group`, so an item written without one — the ordinary authoring mistake this
        # schema exists to report — raised a `KeyError` from inside the merge instead.
        items_from(contributed, source)
    elif named is not None:
        # A file named on the command line and not there is a mistake worth saying, where the
        # default being absent only means this project contributes nothing of its own.
        raise ItemsError(f"{named} does not exist")

    produced, unread = produce(project)
    for said in unread:
        # A ledger the contract cannot read takes every value in it out of the round. Printed
        # rather than left to be noticed as a page that is suspiciously short.
        print(f"not read, so nothing from it is in this round — {said}", file=sys.stderr)
    document, skipped = merge(produced, contributed)
    for group, count in sorted(skipped.items()):
        print(
            f"{group}: {count} item(s) the toolkit found are left out, because this project "
            f"supplies that group itself in {source.name}."
        )
    if not document["items"]:
        # Reachable on a project that has not got far enough to have anything to check, where
        # the schema's "items: [] should be non-empty" names a file that does not exist and a
        # rule the author never wrote. Say what was looked at instead.
        raise ItemsError(
            "there is nothing to check yet. A co-author is sent the values quoted from the "
            "literature (literature/ledger.yaml and attested.yaml), the sentences that cite "
            "something, the references (literature/references.bib) and the authors "
            "(authors.yaml), and none of those holds anything. A project that traces numbers of "
            f"its own adds them in {source}: see contracts/schemas/checking.schema.json."
        )
    return items_from(document, source)


def cmd_checker(args: argparse.Namespace) -> int:
    """Send a co-author the numbers to check, and take their answers back.

    Three verbs, and they are the whole of a round: `build` writes one file per person, `import`
    records what one of them sent back, `status` says where the round stands. Nothing here asks
    the co-author to install, sign in or configure anything, and nothing here is particular to a
    model or a vendor: the file is a page, the answers are JSON, the record is a CSV.
    """
    from manuscript_guard.checking import (
        AnswersError,
        BundleError,
        ItemsError,
        build_bundle,
        import_answers,
        status,
    )
    from manuscript_guard.checking.bundle import slug

    project, _ = load_project(args.path)
    try:
        items = _checking_items(project, args.items)
    except ItemsError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    title = args.title or str(project.paper.get("short_title") or project.paper.get("title") or "")
    if args.verb == "build":
        out = args.output or project.root / "checks" / f"check-{slug(args.name)}.html"
        try:
            written, size = build_bundle(
                items, person=args.name, title=title, out=out, to=args.to or ""
            )
        except BundleError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        asked = items.outstanding
        # From the record as well as from the items file. "0 already checked by someone" was
        # printed after a whole round had come back and been imported, because this counted only
        # the `already` field a project may write. Then "10 item(s) to check, 10 already checked"
        # counted the same items twice: what the page asks, and who has answered those. So the
        # second number is a part of the first, and the items the page shows as done already
        # are counted apart.
        standing = status(project.root, items)
        answered = sum(1 for item in asked if standing.answered.get(str(item["id"])))
        print(f"wrote {written} ({size // 1024} kB)")
        print(
            f"{len(asked)} item(s) for {args.name} to check, {answered} of them already "
            f"answered by someone else."
        )
        if standing.already:
            print(
                f"{standing.already} more on the page are marked as checked before this round."
            )
        print(
            "Send that one file. It opens by double-clicking, needs nothing installed and no "
            "network, and its own button writes the answers file to send back."
        )
        return 0

    if args.verb == "import":
        if args.answers is None:
            # Without this the missing flag reached `Path.read_text` on `None` and the author
            # got an AttributeError. A forgotten flag is not a bug in the project.
            print(
                "manuscript-guard: checker import needs the file a co-author sent back: "
                "`checker import --answers answers-<name>.json`",
                file=sys.stderr,
            )
            return 2
        try:
            brought = import_answers(project.root, args.answers, items)
        except AnswersError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        print(f"{len(brought.recorded)} decision(s) recorded for {brought.by}")
        for called, why in brought.stale:
            print(f"  not recorded: {called} — {why}")
        for called in brought.unknown:
            print(
                f"  not recorded: {called} — this project has no such item now; a cited "
                f"sentence edited since the page was built is a new item, to send again"
            )
        return 1 if (brought.stale or brought.unknown) and not brought.recorded else 0

    standing = status(project.root, items)
    print(f"{len(items.items)} item(s); {standing.outstanding} nobody has answered")
    if standing.already:
        print(f"{standing.already} were already checked before this round")
    if standing.stale:
        print(
            f"{len(standing.stale)} answer(s) are about text that has changed since, so those "
            f"items are outstanding again:"
        )
        for decision in standing.stale:
            print(f"  {decision.by} on {decision.title or decision.id}")
    if standing.orphaned:
        print(
            f"{len(standing.orphaned)} answer(s) are about items this project no longer has; "
            f"they stay in the record and count for nothing:"
        )
        # By the person and the sentence: a cited sentence edited since it was answered is a new
        # item, and the old answer, named by its id, could not be traced to anyone or anything.
        for decision in standing.orphaned:
            print(f"  {decision.by} on {decision.title or decision.id}")
    for person in standing.people:
        counts = standing.by_person[person]
        said = ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))
        print(f"  {person}: {said}")
    for decision in standing.wrong:
        print(f"  [{decision.status}] {decision.by} on {decision.title}: {decision.note or '—'}")
    for identifier, decisions in standing.disagreements:
        who = "; ".join(f"{d.by} says {d.status}" for d in decisions)
        print(f"  disagreement on {decisions[0].title or identifier}: {who}")
    return 0


def cmd_methods(args: argparse.Namespace) -> int:
    """Report or record the state of the Methods against the analysis."""
    # `--reconcile <project>` named the project before steps had names, and takes it for a
    # step's now. A folder holding a paper.yaml is that, whatever folder this runs in.
    for name in args.reconcile or ():
        if (Path(name) / "paper.yaml").is_file():
            print(
                f"error: {name} is a project, and --reconcile takes the names of steps: name "
                f"the project first, `manuscript-guard methods {name} --reconcile`",
                file=sys.stderr,
            )
            return 2
    project, _ = load_project(args.path)
    if args.explain:
        from manuscript_guard.gates.methods import explain_methods

        print("\n".join(explain_methods(project)))
        return 0
    if args.reconcile is None:
        report = check_methods(project)
        print(report.render(project.root))
        return 0 if report.ok else 1

    if args.reconcile:
        try:
            path, count = reconcile(project, steps=args.reconcile)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        print(f"recorded {count} pair(s) of step {', '.join(args.reconcile)} in {path}")
        print("This says the text pointing at each step has been read against its code.")
        return 0
    path, count = reconcile(project)
    print(f"recorded {count} analysis file(s) in {path}")
    print("This says the Methods have been read against the code as it now stands.")
    return 0


def _recipe_paths(workspace: Path, name: str | None) -> list[Path]:
    """Recipes shipped with the package, plus any the project has written itself.

    A project's own recipe wins, the way its own journal and checklist profiles already do:
    a guideline can be revised, or extended locally, without waiting for a release.
    """
    from manuscript_guard.paths import recipes

    by_name = recipes(workspace)
    if name:
        return [by_name[name]] if name in by_name else []
    return [by_name[key] for key in sorted(by_name)]


_DOWNLOAD_URL = re.compile(r"^(?P<indent>[ \t]*)download_url:.*$", re.MULTILINE)
_SOURCE_URL = re.compile(r"^(?P<indent>[ \t]*)source_url:.*$", re.MULTILINE)


def _record_download_url(workspace: Path, recipe_path: Path, url: str) -> tuple[Path, bool]:
    """Write `--save-url` into the project, never into the installed package.

    `_recipe_paths` falls back to the recipes shipped inside the package, and `--save-url`
    wrote back to whatever it returned — so on a normal pip install the command edited a file
    in site-packages. That change is invisible to git, lost on the next upgrade, applied to
    every other project on the machine, and on a system-wide install raises PermissionError
    as a traceback. A project's own recipe already wins over the shipped one, so the copy is
    also what the author meant.

    Rewritten line by line rather than through `yaml.safe_dump`, because a round trip drops
    every comment — and in these files the comments are the licence reasoning: which document
    the terms were read from, and why a related licence does not settle it. Losing that
    silently is worse than not recording the URL.
    """
    from manuscript_guard.reporting import RecipeError

    local = workspace / "profiles" / "reporting" / "recipes" / recipe_path.name
    copied = not recipe_path.is_relative_to(workspace)
    text = recipe_path.read_text(encoding="utf-8")

    line = f"download_url: {url}"
    if _DOWNLOAD_URL.search(text):
        text = _DOWNLOAD_URL.sub(lambda m: f"{m.group('indent')}{line}", text, count=1)
    elif found := _SOURCE_URL.search(text):
        indent = found.group("indent")
        text = f"{text[: found.end()]}\n{indent}{line}{text[found.end() :]}"
    else:
        raise RecipeError(
            f"{recipe_path.name}: no `meta.source_url` to record the download URL beside; "
            f"add `download_url:` to the recipe by hand"
        )

    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(text, encoding="utf-8", newline="\n")
    return local, copied


def cmd_fetch(args: argparse.Namespace) -> int:
    """Download a guideline's own checklist document, at the user's request.

    Deliberately not part of installation. This distributes nothing: it retrieves the
    document from the publisher for the person who asked, and prints the licence first so
    the terms are seen rather than buried.
    """
    from manuscript_guard.paths import workspace as find_workspace
    from manuscript_guard.reporting import RecipeError, load_recipe
    from manuscript_guard.reporting.fetch import FetchError, fetch_document, licence_notice

    root = find_workspace(args.root)
    sources = root / "profiles" / "reporting" / "sources"
    paths = _recipe_paths(root, args.guideline)
    if not paths:
        print(f"no recipe for {args.guideline!r}", file=sys.stderr)
        return 2
    if args.url and len(paths) > 1:
        print("--url applies to one guideline; name it", file=sys.stderr)
        return 2

    failed = 0
    for recipe_path in paths:
        try:
            recipe, meta = load_recipe(recipe_path)
        except RecipeError as exc:
            print(f"  {recipe_path.name}: {exc}")
            failed += 1
            continue

        url = args.url or meta.get("download_url")
        if not url:
            print(f"  {meta['name']}: no download URL recorded")
            print(f"    open {meta['source_url']}, save the file into {sources},")
            print("    or re-run with --url <direct link> --save-url")
            failed += 1
            continue

        print(licence_notice(meta))
        try:
            result = fetch_document(
                url,
                sources / recipe.document,
                expected_sha256=meta.get("sha256"),
                overwrite=args.force,
            )
        except FetchError as exc:
            print(f"    FAILED: {exc}")
            failed += 1
            continue

        if result.bytes_written == 0:
            print(f"    already present: {result.path.name}")
        else:
            print(f"    saved {result.bytes_written // 1024} KB to {result.path.name}")
        if not result.matches:
            failed += 1
            print(
                f"    CHECKSUM MISMATCH: expected {result.expected[:16]}…, "
                f"got {result.digest[:16]}…"
            )
            print("    The published checklist may have been revised. Check the recipe.")
        elif args.save_url and args.url:
            written, copied = _record_download_url(root, recipe_path, args.url)
            if copied:
                print(f"    copied the shipped recipe to {written.parent}")
            print(f"    recorded download_url in {written.name}")

    return 1 if failed else 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Generate checklist profiles from official documents, via recipes."""
    from manuscript_guard.paths import workspace as find_workspace
    from manuscript_guard.reporting import RecipeError, build_profile, load_recipe
    from manuscript_guard.reporting.build import rows_digest_of
    from manuscript_guard.safexml import UnsafeDocument

    root = find_workspace(args.root)
    sources_dir = root / "profiles" / "reporting" / "sources"
    out_dir = root / "profiles" / "reporting"

    recipes = _recipe_paths(root, args.guideline)
    if not recipes:
        print(f"no recipe for {args.guideline!r}", file=sys.stderr)
        return 2

    failed = 0
    for recipe in recipes:
        try:
            path, count, unverified = build_profile(
                recipe, sources_dir, out_dir, allow_changed=args.allow_changed
            )
        except (RecipeError, FileNotFoundError, UnsafeDocument) as exc:
            # UnsafeDocument: a document that is not well-formed, or that declares a DTD,
            # which a truncated download or a page saved by hand can be.
            failed += 1
            print(f"  {recipe.name}: {exc}")
            continue
        note = ""
        if unverified:
            note = f"  [{len(unverified)} NOT VERBATIM: {', '.join(unverified[:6])}]"
            failed += 1
        print(f"  {path.name}: {count} items{note}")
        if not load_recipe(recipe)[1].get("rows_sha256"):
            digest = rows_digest_of(recipe, sources_dir)
            if digest:
                print(f"    rows_sha256: {digest}  (record it in the recipe's meta)")
    return 1 if failed else 0


def cmd_install_skills(args: argparse.Namespace) -> int:
    """Copy the skills to a folder an agent tool reads."""
    from manuscript_guard import skillcopy
    from manuscript_guard.contracts import find_root

    if args.dir is not None:
        folder = args.dir
    elif args.project:
        # A ContractError where there is no paper.yaml above here, which `main` prints.
        folder = skillcopy.project_folder(find_root(Path.cwd()))
    else:
        folder = skillcopy.user_folder()

    if args.dry_run and not args.remove:
        print("manuscript-guard: --dry-run goes with --remove", file=sys.stderr)
        return 2
    if args.verify or args.remove:
        return _skills_kept(skillcopy, folder, args)
    try:
        done = skillcopy.install(folder)
    except (skillcopy.SkillsMissing, skillcopy.StampUnreadable, OSError) as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    there = len(done.written) + len(done.unchanged)
    already = f" ({len(done.unchanged)} already there)" if done.unchanged else ""
    print(
        f"{there} skill{'' if there == 1 else 's'} of manuscript-guard {__version__} in "
        f"{folder}{already}"
    )
    for name in done.removed:
        print(f"removed {name}, which this release no longer has")
    if args.dir is None:
        print(
            "By their documentation, Codex, Gemini CLI, Mistral Vibe and Kimi Code CLI read "
            "`.agents/skills`. Start a new session of the agent tool to see them."
        )
    shared = args.dir is None and not args.project
    for name, why in done.left:
        print(
            f"manuscript-guard: {folder / name} {why}, so it was left as it is; "
            f"{skillcopy.way_forward(why, shared=shared)}",
            file=sys.stderr,
        )
    return 1 if done.left else 0


def _skills_kept(skillcopy, folder: Path, args: argparse.Namespace) -> int:
    """`install-skills --verify` and `--remove`: what a folder holds of the copied skills,
    and taking them away. Exit 1 where something is not as it was copied, or not there."""
    try:
        if args.verify:
            checked = skillcopy.verify(folder)
        else:
            done = skillcopy.remove(folder, dry_run=args.dry_run)
    except (skillcopy.StampUnreadable, OSError) as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    if args.verify:
        if checked.version is None:
            print(f"no skills of manuscript-guard in {folder}: it has no stamp")
            return 1
        print(
            f"{len(checked.matching)} skill(s) of manuscript-guard {checked.version} in "
            f"{folder} are as they were copied"
        )
        for name, why in checked.edited:
            print(f"{folder / name} {why}")
        for name in checked.missing:
            print(f"{folder / name} {skillcopy.GONE}")
        return 1 if checked.edited or checked.missing else 0
    if done is None:
        print(f"nothing to remove: {folder} has no stamp, so nothing in it is manuscript-guard's")
        return 0
    verb = "would remove" if args.dry_run else "removed"
    for name in done.removed:
        print(f"{verb} {folder / name}")
    for name in done.missing:
        print(f"{folder / name} {skillcopy.GONE}, so there was nothing to remove")
    for name, why in done.left:
        print(
            f"manuscript-guard: {folder / name} {why}, so it was left as it is; delete it "
            "yourself if it should go",
            file=sys.stderr,
        )
    if done.stamp_removed:
        print(f"{verb} {folder / skillcopy.STAMP}")
    elif not args.dry_run:
        print(f"kept {folder / skillcopy.STAMP}, which now records only what was left")
    if args.dry_run:
        print("nothing was changed")
    return 1 if done.left else 0


def _note_stale_skills(start: Path) -> None:
    """Say, on stderr, when a copy of the skills is from another release than this tool.

    After `check` and `build`, which are what an agent runs whatever tool it is under. It
    never changes what the command printed or returned, and anything that goes wrong in
    finding out is no reason to lose the command's own answer.
    """
    try:
        from manuscript_guard import skillcopy
        from manuscript_guard.contracts import find_root

        try:
            root = find_root(Path(start))
        except (ContractError, OSError):
            root = None
        notice = skillcopy.stale_notice(root)
        # A process started with its error stream closed has none, and `print` then writes
        # to standard output, after the JSON of `check --json`. With nowhere to say it, it
        # is not said.
        if notice and sys.stderr is not None:
            print(notice, file=sys.stderr)
    except Exception:  # noqa: BLE001 - a notice must never cost the command its answer
        return


def cmd_init(args: argparse.Namespace) -> int:
    from manuscript_guard.contracts.results import HOW_TO_EMIT

    created = init_project(args.path, title=args.title)
    for path in created:
        print(f"created {path}")
    rules = rules_to_add(args.path)
    if rules:
        print(
            "\nAGENTS.md was already there and says nothing of manuscript-guard, so it was "
            "left as it was. An agent tool reads its rules from that file. Add these to it:\n\n"
            + rules
        )
    print(
        "\nnext: describe your authors in authors.yaml, then write an analysis that "
        f"publishes its results with {HOW_TO_EMIT}"
    )
    return 0


class _Parser(argparse.ArgumentParser):
    """A parser that reads an option only where it is written in full.

    argparse reads any prefix of an option that names one option only, so `build --subm` was
    a submission build. The submission guard looks for the word `--submission` in a command,
    and a spelling it cannot list is a submission it does not see.

    The setting is each parser's own, and on the top parser alone it leaves every command
    reading abbreviations. A command is made by the class of the parser it is added to, so
    setting it here reaches each of them, and one added later.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **{**kwargs, "allow_abbrev": False})


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="manuscript-guard",
        description="Make every number in a scientific manuscript traceable to its source.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="run every gate")
    check.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    check.add_argument("--json", action="store_true", help="machine-readable output")
    check.add_argument(
        "--stage",
        choices=STAGES,
        help="how far along you are; overrides `stage` in paper.yaml. Findings that do not "
        "bind yet are reported as INFO rather than failing",
    )
    check.add_argument(
        "--submission",
        action="store_true",
        help="shorthand for --stage submission: everything binds",
    )
    check.set_defaults(func=cmd_check)

    audit = sub.add_parser(
        "audit",
        help="check an existing paper's numbers against existing outputs",
        description="For papers not written with this toolkit. Give it the manuscript, the "
        "supplements and the figures, and the analysis outputs to check them against.",
    )
    audit.add_argument("paper", nargs="+", type=Path, help=".docx/.md files, or directories")
    audit.add_argument(
        "--against",
        nargs="+",
        type=Path,
        required=True,
        metavar="PATH",
        help="analysis outputs: .json, .csv, .tsv, .txt, .yaml, .yml, .md, or directories "
        "of them; anything else is named in the report as not read",
    )
    audit.add_argument(
        "--figures", nargs="+", type=Path, help="SVG or PDF figures to audit as well"
    )
    audit.add_argument(
        "--whole-numbers",
        nargs="+",
        default=[],
        metavar="LABEL",
        help="the table rows, by a word or words of their label, whose cells are means of "
        "whole numbers (a Likert-type scale, a count): each is held to its column's n",
    )
    audit.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if anything is unmatched or a paper or figure could not be read",
    )
    audit.set_defaults(func=cmd_audit)

    verify = sub.add_parser(
        "verify",
        help="re-run the analysis and check it still produces the recorded results",
        description="Runs the project's analysis scripts into a scratch copy and compares "
        "the fragments value by value. This is the check a recomputed .sha256 cannot pass: "
        "a digest can be forged, a result cannot be forged into existence. Separate from "
        "`check` because it executes your code, and because it is slow.",
    )
    verify.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    verify.add_argument(
        "--only",
        nargs="+",
        metavar="FRAGMENT",
        help="verify only these fragments, by stem (e.g. 01_disproportionality)",
    )
    verify.set_defaults(func=cmd_verify)

    journal = sub.add_parser(
        "journal",
        help="list journal profiles, or start one from the annotated template",
        description="No journal profile ships with the toolkit, deliberately: author "
        "guidelines change without announcement, so a rule compiled in would eventually be "
        "wrong and would be wrong silently. Every profile is read from the journal's own "
        "page and stamped with the date it was read.",
    )
    journal.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    journal.add_argument(
        "--template",
        metavar="SLUG",
        help="copy the annotated template to profiles/journals/<SLUG>.yaml",
    )
    journal.add_argument(
        "--reread",
        metavar="FILE",
        type=Path,
        help="the journal's page read again, as text: show what changed from the stored page "
        "and which rules quote words it no longer has; writes nothing",
    )
    journal.set_defaults(func=cmd_journal)

    stages = sub.add_parser("stages", help="what each stage means and what binds at it")
    stages.set_defaults(func=cmd_stages)

    hook = sub.add_parser("hook", help="handle a Claude Code hook event (reads stdin)")
    hook.add_argument(
        "event",
        choices=("guard-write", "after-edit", "guard-submission", "session-start"),
    )
    hook.set_defaults(func=cmd_hook)

    review = sub.add_parser("review", help="show where the review stands")
    review.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    review.add_argument("--digest", action="store_true", help="print the manuscript digest only")
    review.add_argument(
        "--files",
        action="store_true",
        help="print the per-file digests a review record lists as what it read",
    )
    review.add_argument("--submission", action="store_true")
    review.add_argument(
        "--record",
        metavar="REVIEWER",
        help="write review/round-N/REVIEWER.yaml for the manuscript as it now stands, with "
        "the digests filled in. G11 blocks submission until every reviewer has filed one, "
        "and there was no command that produced one",
    )
    review.add_argument(
        "--reading",
        metavar="READER",
        help="with --record or --seal: who made this reading, where a remit is read more "
        "than once "
        "(openai/<model>, or a person's name). Written as review/round-N/REVIEWER.READER.yaml "
        "beside the reviewer's plain record (under review/design/ with --design), so neither "
        "replaces the other, and listed among the reviewer's readers in the panel, which is "
        "what makes the gate read it",
    )
    review.add_argument(
        "--seal",
        metavar="REVIEWER",
        help="seal review/round-N/REVIEWER.yaml (or its reading, with --reading) once its "
        "findings are written: adds reading_sha256, a digest of what the reader wrote, and "
        "G11 reports reading-altered if that changes. Once only; `review --run` seals what "
        "it files",
    )
    review.add_argument(
        "--design",
        action="store_true",
        help="a design round: with --record, write review/design/round-N/REVIEWER.yaml for "
        "the analysis plan and the feasibility results as they now stand; with --seal, seal "
        "it; with --run, have the models in review.models read the plan; alone, say where "
        "the design rounds stand (G12)",
    )
    review.add_argument(
        "--record-figure",
        metavar="FIGURE",
        help="write <figure>.review.yaml, with the content digest G10 asks for and never "
        "printed",
    )
    review.add_argument(
        "--verdict",
        choices=sorted({*RECORD_VERDICTS, *FIGURE_VERDICTS}),
        help="required with --record or --record-figure",
    )
    review.add_argument(
        "--round",
        type=int,
        help="review round. Default 1 with --record; with --run, the first round somebody "
        "has not reported in",
    )
    review.add_argument("--by", help="who did the reading; defaults to the reviewer id")
    review.add_argument("--remit", help="what this reviewer is responsible for noticing")
    review.add_argument("--summary", help="the reviewer's overall comment")
    review.add_argument(
        "--providers",
        action="store_true",
        help="list the model providers a panel can be read by, the environment variable "
        "each key comes from, and whether it is set. No key is printed",
    )
    review.add_argument(
        "--run",
        action="store_true",
        help="have the round's panel read by the models in paper.yaml's review.models and "
        "file each reading as a review record. Says which files go to which provider and "
        "how many calls that is, then needs a yes before anything is sent",
    )
    review.add_argument(
        "--dry-run",
        action="store_true",
        help="with --run: say which files would go to which provider and how many calls "
        "that is, write the exact request bodies under build/, and send nothing",
    )
    review.add_argument(
        "--one-each",
        action="store_true",
        help="with --run: one model per reviewer, dealt across review.models in turn, "
        "instead of every model reading every remit",
    )
    review.add_argument(
        "--yes",
        action="store_true",
        help="with --run: send without being asked. For a script the author wrote; an "
        "agent asks the author first. The statement of what is sent where is still printed",
    )
    review.add_argument(
        "--suggestions",
        action="store_true",
        help="write the edits the round's readings suggest into "
        "build/suggestions/round-N.docx as Word tracked changes, each under its reader's "
        "name with its finding as a comment; accept or refuse them in Word, then `import` "
        "that document to record what was decided. An edit that would change a number, a "
        "binding or a citation, or whose words are not found exactly once, is not written",
    )
    review.set_defaults(func=cmd_review)

    bind = sub.add_parser(
        "bind", help="show every unbound number and how to give it a source"
    )
    bind.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    bind.add_argument(
        "--apply",
        action="store_true",
        help="replace the literals that match exactly one published value",
    )
    bind.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="FILE:LINE",
        help="with --apply, replace just this suggestion; repeatable. Without it, --apply "
        "takes every unambiguous one, which means one wrong guess can only be avoided by "
        "declining all the right ones",
    )
    bind.add_argument(
        "--pointers",
        action="store_true",
        help="offer, for each typed pointer to a table or figure (\"Table 2\"), the "
        "{{ref.table.<key>}} or {{num.table.<key>}} binding that prints it as it reads, so "
        "that the build numbers it from then on",
    )
    bind.set_defaults(func=cmd_bind)

    importer = sub.add_parser(
        "import", help="bring a co-author's Word edits back into the manuscript source"
    )
    importer.add_argument("document", type=Path, help="the edited .docx")
    importer.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    importer.add_argument("--apply", action="store_true", help="merge the safe hunks")
    importer.add_argument(
        "--force", action="store_true", help="import even if it was built from older source"
    )
    importer.add_argument(
        "--csl",
        type=Path,
        help="the citation style the document was built with, where it is no longer where "
        "the build found it",
    )
    importer.set_defaults(func=cmd_import)

    respond = sub.add_parser(
        "respond", help="open a revision round, or write the point-by-point response"
    )
    respond.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    respond.add_argument("--open", action="store_true", help="start a new round")
    respond.add_argument(
        "--from",
        dest="source",
        type=Path,
        help="seed the round from the comments in a returned .docx",
    )
    respond.add_argument("--submission", action="store_true")
    respond.add_argument(
        "--force", action="store_true", help="seed even from an out-of-date document"
    )
    respond.set_defaults(func=cmd_respond)

    approve_ = sub.add_parser(
        "approve",
        help="record an author's approval of the manuscript as it stands; the author's own act",
    )
    approve_.add_argument("path", nargs="?", type=Path, default=Path("."))
    approve_.add_argument(
        "--as", dest="as_", required=True,
        help="the author: ORCID iD, e-mail address, full name or family name",
    )  # fmt: skip
    approve_.add_argument("--note", help="anything the author says with the approval")
    approve_.set_defaults(func=cmd_approve)

    sign_ = sub.add_parser(
        "sign",
        help="record a named person's sign-off of a finding only they may close, such as a "
        "G15 warning for the statistician; that person's own act",
    )
    sign_.add_argument("path", nargs="?", type=Path, default=Path("."))
    sign_.add_argument(
        "--as", dest="as_", required=True,
        help="the person authors.yaml names for the role: ORCID iD, e-mail address or name",
    )  # fmt: skip
    sign_.add_argument(
        "--finding", required=True, help="the id the finding's hint names, such as "
        "G15/model-few-events/adjusted",
    )  # fmt: skip
    sign_.add_argument("--note", help="anything the person says with the sign-off")
    sign_.set_defaults(func=cmd_sign)

    explain = sub.add_parser("explain", help="show how each number in a file was classified")
    explain.add_argument("file", type=Path)
    explain.set_defaults(func=cmd_explain)

    impact = sub.add_parser(
        "impact",
        help="list what depends on a file: results, sentences, figures, Methods, readings "
        "and answers that go stale when it changes",
    )
    impact.add_argument(
        "files", nargs="*", type=Path,
        help="files of the project; with none, the files changed since --since",
    )  # fmt: skip
    impact.add_argument("--since", default="HEAD", help="the commit to compare with (HEAD)")
    impact.add_argument("--json", action="store_true", help="print JSON")
    impact.set_defaults(func=cmd_impact)

    models = sub.add_parser(
        "models", help="print each fitted model as its card, with what G15 says of it"
    )
    models.add_argument("path", nargs="?", type=Path, default=Path("."))
    models.set_defaults(func=cmd_models)

    reworded = sub.add_parser(
        "reworded",
        help="check that an edit changed the wording and nothing else",
        description="Compares the manuscript with what it was and holds every binding, "
        "citation key and typed number to its place. One that is gone, new or changed "
        "fails; the same ones in another order pass with a warning for each place. A "
        "sentence the edit made claim more, less or the opposite, by a hedge, a limit, a "
        "negation or a word of the claim-strength ladder that came or went, passes with a "
        "warning. Run it after a language edit, by a person, a service or a model, and "
        "before committing it: the text before is the last commit's unless another is named.",
    )
    reworded.add_argument(
        "paths",
        nargs="*",
        type=Path,
        metavar="PATH",
        help="manuscript files to compare, or a project's folder for all of its manuscript "
        "(default: the project of the current folder)",
    )
    reworded.add_argument(
        "--since",
        default="HEAD",
        metavar="REVISION",
        help="the git revision that holds the text before the edit (default: the last commit)",
    )
    reworded.add_argument(
        "--before",
        type=Path,
        metavar="COPY",
        help="a copy of one file as it was before the edit, for a text that is not in git",
    )
    reworded.add_argument("--json", action="store_true", help="the report as JSON")
    reworded.set_defaults(func=cmd_reworded)

    passages = sub.add_parser(
        "passages",
        help="list each cited statement with the passage of the cited work that supports it",
        description="Lists each sentence of the manuscript that cites a work, with the "
        "stored copy of each work it cites and the passages literature/passages.yaml records "
        "for it, as G7 finds them: in the stored copy, not in it, or not checked. Passages "
        "whose sentence the manuscript no longer has are listed as stale. Writes nothing.",
    )
    passages.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    passages.add_argument(
        "--missing",
        action="store_true",
        help="only the statements that carry no passage of any work they cite",
    )
    passages.add_argument("--json", action="store_true", help="the listing as JSON")
    passages.set_defaults(func=cmd_passages)

    render = sub.add_parser("render", help="substitute bindings into build/rendered")
    render.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    render.set_defaults(func=cmd_render)

    build = sub.add_parser("build", help="produce the .docx")
    build.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    build.add_argument(
        "--offline",
        action="store_true",
        help="format citations from references.bib instead of live Zotero fields",
    )
    build.add_argument(
        "--annotated",
        action="store_true",
        help="write manuscript.annotated.docx instead: every number highlighted by what "
        "backs it, with its source shown on hover",
    )
    build.add_argument(
        "--csl",
        type=Path,
        help="citation style, for offline builds; the journal's, kept by `style`, otherwise",
    )
    build.add_argument("-o", "--output", type=Path)
    build.add_argument("--skip-checks", action="store_true", help="build even if gates fail")
    build.add_argument("--stage", choices=STAGES, help="how far along you are")
    build.add_argument(
        "--submission",
        action="store_true",
        help="the version you send anywhere: unanswered review findings fail the build",
    )
    build.add_argument(
        "--marked-up",
        action="store_true",
        help="also write build/marked-up/: the revision with every change since the document "
        "the journal received shown as Word tracked changes",
    )
    build.add_argument(
        "--since",
        type=Path,
        help="with --marked-up: the document sent, where the revision round kept none",
    )
    build.add_argument(
        "--since-supplement",
        type=Path,
        help="with --marked-up: the supplement sent, where the revision round kept none",
    )
    build.add_argument(
        "--round", type=int, help="with --marked-up: the revision round, the latest by default"
    )
    build.add_argument(
        "--highlight",
        action="store_true",
        help="with --marked-up: show the changes highlighted and struck through, not tracked",
    )
    build.set_defaults(func=cmd_build)

    syncbib = sub.add_parser("sync-bib", help="rewrite references.bib from Zotero")
    syncbib.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    syncbib.set_defaults(func=cmd_sync_bib)

    syncsources = sub.add_parser(
        "sync-sources",
        help="copy each cited work's PDF or saved page from Zotero, or from a folder of PDFs "
        "named by DOI",
    )
    syncsources.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    syncsources.add_argument(
        "--dry-run", action="store_true", help="say what would be copied, and copy nothing"
    )
    syncsources.add_argument(
        "--from",
        dest="source",
        type=Path,
        metavar="FOLDER",
        help="take each PDF of a folder named by DOI, as auto-paper-harvester saves them, "
        "instead of asking Zotero",
    )
    syncsources.set_defaults(func=cmd_sync_sources)

    lookup = sub.add_parser(
        "lookup",
        help="look up each cited DOI and PMID, search by its title for a reference with "
        "neither, and keep what the registries said",
    )
    lookup.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    lookup.add_argument(
        "--again", action="store_true", help="look up every cited reference, recorded or not"
    )
    lookup.add_argument(
        "--dry-run", action="store_true", help="say what would be looked up, and send nothing"
    )
    lookup.add_argument(
        "--journals",
        action="store_true",
        help="ask the NLM Catalog and DOAJ about each journal of journals/shortlist.yaml instead",
    )
    lookup.set_defaults(func=cmd_lookup)

    related = sub.add_parser(
        "related",
        help="compare the paper with the earlier outputs of the same data in "
        "literature/related.yaml, or copy an earlier project in",
    )
    related.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    related.add_argument(
        "--take",
        nargs="*",
        metavar="ID",
        help="copy the results and plan of each named output's project, at its revision, into "
        "literature/related/<id>/ (all that name a project, where none is given)",
    )
    related.add_argument("--json", action="store_true", help="the comparison as JSON")
    related.set_defaults(func=cmd_related)

    search = sub.add_parser(
        "search",
        help="ask PubMed, Europe PMC and OpenAlex for works a claim could cite; it proposes, "
        "and writes nothing",
    )
    search.add_argument("query", help="the topic, in a few words; it is sent as written")
    search.add_argument("--since", type=int, metavar="YEAR", help="works published from YEAR")
    search.add_argument(
        "--type",
        action="append",
        metavar="TYPE",
        help="review, systematic-review, meta-analysis, guideline, rct, cohort or preprint; "
        "several are joined by OR (repeat, or separate with commas)",
    )
    search.add_argument("--language", metavar="CODE", help="in two letters, e.g. en")
    search.add_argument("--limit", type=int, default=10, help="how many to show (default 10)")
    search.add_argument(
        "--sort",
        choices=("relevance", "newest", "cited"),
        default="relevance",
        help="the order: the registries' relevance (default), year, or citation count",
    )
    search.add_argument("--json", action="store_true", help="the candidates as JSON")
    search.add_argument(
        "--dry-run", action="store_true", help="say what would be asked, and send nothing"
    )
    search.add_argument(
        "--root",
        type=Path,
        help="the paper project whose `lookup.contact` is sent; by default the one this "
        "folder is in, if any",
    )
    search.set_defaults(func=cmd_search)

    style = sub.add_parser(
        "style",
        help="fetch the journal's citation style from the CSL style repository, for the "
        "offline build",
    )
    style.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    style.add_argument(
        "--again", action="store_true", help="fetch it again, though it is kept and unchanged"
    )
    style.add_argument(
        "--dry-run", action="store_true", help="say what would be fetched, and send nothing"
    )
    style.set_defaults(func=cmd_style)

    checklist = sub.add_parser("checklist", help="write the completion file for a checklist")
    checklist.add_argument("guideline", nargs="?", help="e.g. STROBE; defaults to paper.yaml")
    checklist.add_argument("--path", type=Path, default=Path.cwd())
    checklist.set_defaults(func=cmd_checklist)

    submit = sub.add_parser("submit", help="assemble the submission pack")
    submit.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    submit.add_argument("--offline", action="store_true")
    submit.add_argument("--csl", type=Path)
    submit.add_argument("--document", type=Path, help="use an existing .docx instead of building")
    submit.add_argument("--skip-checks", action="store_true")
    submit.add_argument(
        "--highlight",
        action="store_true",
        help="at a revision, pack the changes highlighted and struck through, not tracked",
    )
    submit.set_defaults(func=cmd_submit)

    checker = sub.add_parser(
        "checker", help="send a co-author the numbers to check, and take their answers back"
    )
    checker.add_argument("verb", choices=["build", "import", "status"])
    checker.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    checker.add_argument("--for", dest="name", default="", help="build: who the file is for")
    checker.add_argument("--to", default="", help="build: who they send the answers back to")
    checker.add_argument("-o", "--output", type=Path, help="build: where to write the file")
    checker.add_argument("--title", help="build: what the page calls itself")
    checker.add_argument(
        "--answers", type=Path, help="import: the file a co-author sent back"
    )
    checker.add_argument(
        "--items", type=Path, help="the items file, if not checks/items.json"
    )
    checker.set_defaults(func=cmd_checker)

    methods = sub.add_parser("methods", help="check or record Methods-to-code reconciliation")
    methods.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    methods.add_argument(
        "--reconcile",
        nargs="*",
        metavar="STEP",
        help="record the analysis as it stands, after reading the Methods against it; with "
        "step names, record only the pairs of those steps, after reading each against its text",
    )
    methods.add_argument(
        "--explain",
        action="store_true",
        help="list each Methods claim with the step it points at and how the pair stands",
    )
    methods.set_defaults(func=cmd_methods)

    fetch = sub.add_parser("fetch", help="download a guideline's own checklist document")
    fetch.add_argument("guideline", nargs="?", help="e.g. STROBE; default is all recipes")
    fetch.add_argument("--url", help="direct link, when the recipe records none")
    fetch.add_argument("--save-url", action="store_true", help="record --url in the recipe")
    fetch.add_argument("--force", action="store_true", help="re-download over an existing file")
    fetch.add_argument("--root", type=Path, help="toolkit root holding profiles/")
    fetch.set_defaults(func=cmd_fetch)

    transcribe = sub.add_parser(
        "transcribe", help="build checklist profiles from official documents"
    )
    transcribe.add_argument("guideline", nargs="?", help="e.g. STROBE; default is all recipes")
    transcribe.add_argument("--root", type=Path, help="toolkit root holding profiles/")
    transcribe.add_argument(
        "--allow-changed",
        action="store_true",
        help="transcribe even if the document no longer matches the recipe's checksum",
    )
    transcribe.set_defaults(func=cmd_transcribe)

    init = sub.add_parser("init", help="scaffold a new manuscript project")
    init.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    init.add_argument("--title", default="Untitled manuscript")
    init.set_defaults(func=cmd_init)

    skills = sub.add_parser(
        "install-skills",
        help="copy the skills to a folder an agent tool reads (for one with no plugin)",
    )
    where = skills.add_mutually_exclusive_group()
    where.add_argument(
        "--project",
        action="store_true",
        help="into .agents/skills of the project you are in, not of your home",
    )
    where.add_argument("--dir", type=Path, default=None, help="into this folder")
    kept = skills.add_mutually_exclusive_group()
    kept.add_argument(
        "--verify",
        action="store_true",
        help="say which copied skills are as they were copied, and change nothing",
    )
    kept.add_argument(
        "--remove",
        action="store_true",
        help="take away the copied skills that are as they were copied, then the stamp",
    )
    skills.add_argument("--dry-run", action="store_true", help="with --remove: change nothing")
    skills.set_defaults(func=cmd_install_skills)

    return parser


#: What to write when the terminal cannot take the character. Every one of these appears in
#: ordinary findings, because the prose in this toolkit is typed properly.
_FOLD = str.maketrans(
    {
        "—": "--",
        "–": "-",
        "…": "...",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "≥": ">=",
        "≤": "<=",
        "×": "x",
        "≈": "~",
        "±": "+/-",
        "→": "->",
        "•": "*",
        "\u00a0": " ",
    }
)


def _survive_the_console() -> None:
    """Make output printable on a console that is not UTF-8.

    Every finding this tool writes is full of em dashes, and a Windows console is whatever
    code page it was started with. Each rejects a different subset: cp437 and cp850 cannot
    take an em dash or an ellipsis, cp1252 takes both but not `≥`. Printing one raised
    `UnicodeEncodeError` from inside `print`, so `check` exited 2 — "the check could not be
    run at all" — on a manuscript that was merely failing a gate, and CI reading the exit
    code could not tell the two apart. `check --json` died the same way, mid-document,
    while a machine was parsing it.

    Folding is per write and all-or-nothing, so a line either reads as typed or reads as
    ASCII throughout, rather than switching styles around whichever glyph the code page
    happened to know.

    Folding to ASCII rather than forcing UTF-8 on the stream: forcing it turns a cp1252
    console into mojibake, which is harder to read than `--`, and unlike `errors="replace"`
    this keeps the text meaningful.
    """
    # De-duplicated and marked. Each call captured the previous `write` and wrapped it
    # again, so a host calling `main()` in a loop on a legacy console — or this project's
    # own test suite, which calls it dozens of times — nested wrappers until Python raised
    # RecursionError, which `main` does not catch. `sys.stdout is sys.stderr` is also the
    # ordinary case under pytest's capture, and that double-wrapped on a single call.
    seen: list = []
    for stream in (sys.stdout, sys.stderr):
        if any(stream is already for already in seen):
            continue
        seen.append(stream)
        encoding = getattr(stream, "encoding", None) or "utf-8"
        if codecs.lookup(encoding).name in {"utf-8", "utf-8-sig", "utf-32", "utf-16"}:
            continue
        if getattr(stream, "_manuscript_guard_folded", False):
            continue
        write = stream.write

        def safe(text: str, _write=write, _encoding=encoding) -> int:
            try:
                text.encode(_encoding)
            except UnicodeEncodeError:
                text = text.translate(_FOLD).encode(_encoding, "replace").decode(_encoding)
            return _write(text)

        stream.write = safe  # type: ignore[method-assign]
        with contextlib.suppress(AttributeError):
            stream._manuscript_guard_folded = True


def main(argv: list[str] | None = None) -> int:
    from manuscript_guard.roundtrip import RoundTripError

    args = build_parser().parse_args(argv)
    _survive_the_console()
    # Every error this toolkit raises on purpose says what went wrong in words. Catching
    # only the contract errors here meant `import` without pandoc, or `respond --from` a
    # file that is not a .docx, ended in a traceback instead of that sentence.
    try:
        return int(args.func(args))
    except (ContractError, BuildError, RoundTripError) as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    finally:
        if args.command in ("check", "build"):
            _note_stale_skills(getattr(args, "path", None) or Path.cwd())


if __name__ == "__main__":
    sys.exit(main())
