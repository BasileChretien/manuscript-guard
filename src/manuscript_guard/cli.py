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
import shutil
import sys
import textwrap
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
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
from manuscript_guard.build.latex_values import check_values
from manuscript_guard.build.tex_check import check_tex
from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts import (
    ContractError,
    Unreadable,
    load_namespace,
    load_project,
    read_text,
)
from manuscript_guard.findings import WARN, Finding, Report, merge_all
from manuscript_guard.gates import (
    check_bound_units,
    check_boxes,
    check_citations,
    check_consistency,
    check_datasets,
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
from manuscript_guard.gates.custodian import (
    check_recoverable,
    check_restricted_inputs,
    check_small_cells,
)
from manuscript_guard.gates.data_quality import check_data_quality, check_quality_reported
from manuscript_guard.gates.data_sources import (
    check_data_sources,
    check_declared_datasets,
    check_statement_sources,
)
from manuscript_guard.gates.data_statement import check_deposit_doi, check_package_doi
from manuscript_guard.gates.design_review import check_design_rounds
from manuscript_guard.gates.figure_alt import check_figure_alt
from manuscript_guard.gates.figure_colours import check_figure_colours
from manuscript_guard.gates.formats import check_format, not_read_in_latex
from manuscript_guard.gates.methods_review import check_method_passages, check_methods_review
from manuscript_guard.gates.numbers import chosen_rules, typed_choice, why_no_manuscript
from manuscript_guard.gates.registration import check_registration
from manuscript_guard.gates.related import check_related
from manuscript_guard.gates.shortlist import check_shortlist
from manuscript_guard.gates.synthetic import check_synthetic_inputs
from manuscript_guard.paper_edit import KEYS as PAPER_KEYS
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
from manuscript_guard.scaffold import ENGLISHES, UNTITLED, init_project, rules_to_add
from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import parse, substitute
from manuscript_guard.text.reader import LATEX, manuscript_files, manuscript_format
from manuscript_guard.text.sections import chains_at, footnote_index, heading_index
from manuscript_guard.text.shown import printable
from manuscript_guard.text.tokens import find_atoms


def _run_gates(
    start: Path, *, submission: bool = False, stage: str | None = None
) -> tuple[Report, object, str, dict]:
    """Run every gate, then apply the stage policy: `_gate_run` without the namespace."""
    report, project, chosen, deferred, _namespace = _gate_run(
        start, submission=submission, stage=stage
    )
    return report, project, chosen, deferred


def _gate_run(
    start: Path, *, submission: bool = False, stage: str | None = None
) -> tuple[Report, object, str, dict, dict]:
    """Run every gate, then apply the stage policy; with the namespace the gates read too,
    which `next` asks which unbound number one published value reads as.

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
        ("G3", lambda: check_figure_colours(project)),
        ("G10", lambda: check_figure_reviews(project, content_digest)),
        ("G7", lambda: check_citations(project, literature)),
        ("G7", lambda: check_literature_chain(project, literature)),
        ("G7", lambda: check_prose_quotations(project)),
        ("G7", lambda: check_passages(project, chosen)),
        ("G7", lambda: check_recycling(project, chosen)),
        ("G4", lambda: check_journal(project)),
        ("G4", lambda: check_boxes(project, namespace, chosen)),
        ("G4", lambda: check_shortlist(project)),
        ("G4", lambda: check_package_doi(project, submission=at_submission)),
        # It reads paper.yaml and the receipts, and none of the manuscript.
        ("G4", lambda: check_deposit_doi(project, submission=at_submission)),
        ("G4", lambda: check_statement_sources(project)),
        ("G8r", lambda: check_reporting(project)),
        ("G6", lambda: check_writing(project, results, submission=at_submission)),
        ("G9", lambda: check_methods(project, namespace, results)),
        ("G12", lambda: check_design(project, results, chosen).merge(
            check_design_rounds(project, submission=at_submission))),
        # A check of its own, since it reads the manuscript: one that cannot be read stops
        # it and not the plan's.
        ("G12", lambda: check_registration(project, results, chosen)),
        ("G12", lambda: check_data_sources(project, chosen)),
        ("G12", lambda: check_declared_datasets(project, results)),
        ("G7", lambda: check_method_passages(project)),
        ("G12", lambda: check_methods_review(project)),
        ("G8", lambda: check_consistency(results)),
        ("G2", lambda: check_small_cells(project, results)),
        ("G2", lambda: check_recoverable(project, results)),
        ("G1", lambda: check_restricted_inputs(project, results)),
        ("G1", lambda: check_synthetic_inputs(project, results, submission=at_submission)),
        ("G1", lambda: check_datasets(project, results)),
        ("G1", lambda: check_values(project, namespace, results)),
        ("G8", lambda: check_reported(project, results)),
        ("G8", lambda: check_relations(results)),
        ("G8", lambda: check_recomputed(project, namespace, results)),
        ("G8", lambda: check_related(project, namespace, results, submission=at_submission)),
        ("G13", lambda: check_revision(project, submission=at_submission)),
        ("G14", lambda: check_language(project, chosen)),
        ("G15", lambda: check_models(project, results)),
        ("G16", lambda: check_data_quality(project, results, chosen, submission=at_submission)),
        ("G16", lambda: check_quality_reported(
            project, results, chosen, submission=at_submission)),
        ("BUILD", lambda: check_shapes(project).merge(check_tex(project, namespace, results))),
        ("BUILD", lambda: check_latex(project)),
    ):
        if latex and _MARKDOWN_BUILD & set(gate.__code__.co_names):
            # The Markdown build's own checks: a LaTeX manuscript's build is checked by
            # `check_latex` and its compile (step 13).
            continue
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
    return report, project, chosen, deferred, namespace


#: The checks that read the manuscript only as Markdown, by the name each entry of
#: `_run_gates` calls. On a LaTeX manuscript they are not run, and each of their gates reports
#: `not-read-in-latex`. A check leaves this set in the step that teaches it LaTeX (DESIGN.md,
#: "LaTeX manuscripts", Order of work).
_NOT_READ_IN_LATEX: frozenset[str] = frozenset()
#: The Markdown build's own checks: of the shapes it refuses, of TeX in its text, and of the
#: title a Markdown file's header gives against paper.yaml's. A LaTeX manuscript has none of
#: them: its build is checked by `check_latex`, which reads it as the reader does, and by its
#: compile, so these do not run on one and nothing is said (step 13). Its `\title` is not
#: compared with paper.yaml's (DESIGN.md, the LaTeX known gaps).
_MARKDOWN_BUILD = frozenset({"check_shapes", "check_tex"})


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
    from manuscript_guard.gates.numbers import _is_latex

    if _is_latex(project):
        print("manuscript-guard bind: LaTeX numbers a LaTeX manuscript's tables and figures "
              "itself; point to one with `Table~\\ref{...}`", file=sys.stderr)  # fmt: skip
        return 2
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
    from manuscript_guard.gates.numbers import _is_latex

    project, _ = load_project(args.path)
    # A LaTeX manuscript has its entry file, and the gates read it (step 12).
    empty = None if _is_latex(project) else why_no_manuscript(project)
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
    supplementary, refusal = _document_kind(project, known, returned, name)
    if refusal:
        print(refusal)
    return supplementary


def _document_kind(project, known: dict, returned, name: str) -> tuple[bool | None, str]:
    """`_which_document`'s answer, and what it says when there is none."""
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
        return None, (
            f"{name} carries no paragraph identifier this manuscript knows, so there is no "
            f"telling whether it is the manuscript or its supplement, and import compares "
            f"paragraphs only through those identifiers. Nothing was imported. A supplement of "
            f"headings, tables and figures carries none, and holds nothing import compares; "
            f"otherwise, import the document the co-author was sent, edited in place."
        )
    if kinds == {True, False}:
        return None, (
            f"{name} carries paragraphs of both the manuscript and its supplement. They are "
            f"built as two documents and imported one at a time, and a paragraph pasted from "
            f"one into the other is not something import can apply. Nothing was imported: "
            f"make the move in the .md yourself, and import each document on its own."
        )
    return kinds == {True}, ""


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
        _comments_all_the_same(project, edited, carried, numbered, offered, applying=args.apply)
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
        _comments_all_the_same(project, edited, carried, numbered, offered, applying=args.apply)
        return 1

    try:
        returned = read_blocks(edited)
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
        # to one is an answer, said with the suggestions: neither is filed (`_threads`).
    known = tagged_paragraphs(project)
    supplementary = _which_document(project, known, returned, edited.name)
    if supplementary is None:
        # The comments need no identifier to be read, and are the most useful thing in the
        # document: refusing the edits is no reason to drop them. With no telling which
        # document it is they have no record to go in, so they are printed and not filed.
        threads = _threads(project, edited, {}, offered) or []
        _report_comments(threads)
        if threads:
            print(f"\nThe comments are not filed: each is filed with the document it was made "
                  f"in, and there is no telling which one {edited.name} is. Import the "
                  f"document the co-author was sent, edited in place, and they are filed "
                  f"with it.")  # fmt: skip
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

    # Each comment, anchored where the import vouches for the paragraph it was made on, with
    # the identifier that paragraph has now, as `respond --open` anchors a point.
    threads = _threads(project, edited, {name: name for name in trusted} | dict(followed), offered)
    unread = threads is None
    threads = threads or []
    if plan.empty and not threads and not strangers and not unaccounted and not unread:
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

    filed = _file_comments(
        project, edited, threads, stamp=carried, supplementary=supplementary, applying=args.apply
    )
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
    # A paragraph not compared is not applied either, nor a comment that could not be filed.
    return 1 if outstanding or strangers or unaccounted or not filed or unread else 0


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


def _report_comments(comments) -> None:
    """Each co-author comment, with what it was made on and the replies to it. The comment
    is the co-author's text, quoted, never the tool's words."""
    from manuscript_guard.filed_comments import made_on
    from manuscript_guard.gates.comments import NO_WORDS

    for comment in comments:
        author = printable(f"{comment.author} ({comment.date})").replace("\n", " ")
        block = getattr(comment, "block", "")
        on = f", {made_on(block)}" if block else ""
        print(f"\ncomment from {author}{on}, quoted:")
        print(quoted(comment.text) if comment.text else f"    {NO_WORDS}")
        for reply in getattr(comment, "replies", ()):
            by = printable(f"{reply.by} ({reply.date})").replace("\n", " ")
            print(f"  reply from {by}, quoted:")
            print(quoted(reply.text) if reply.text else f"    {NO_WORDS}")


def _threads(project, edited: Path, vouched: dict[str, str], offered) -> list | None:
    """The comment threads of a returned document (`filed_comments.threads_of`), less a
    review panel's own (`offered`), or None once it has said why they cannot be read."""
    from manuscript_guard.filed_comments import FilingError, threads_of
    from manuscript_guard.roundtrip import tagged_paragraphs

    sources = {name: entry[1] for name, entry in tagged_paragraphs(project).items()}
    try:
        return threads_of(edited, vouched=vouched, sources=sources, panel=offered)
    except FilingError as exc:
        print(f"manuscript-guard: {exc}. Its comments are not filed.", file=sys.stderr)
        return None


def _comments_all_the_same(
    project, edited: Path, stamp: str, numbered, offered, *, applying: bool
) -> None:
    """File the comments of a document whose edits were refused whole: a comment nobody
    transcribed is lost to the checks, whatever became of the edits. Only where the
    identifiers say which document it is, and anchored only to a paragraph whose identifier
    the import vouches for, as an edit is merged only there."""
    from manuscript_guard.roundtrip import RoundTripError, read_blocks, tagged_paragraphs

    try:
        returned = read_blocks(edited)
    except RoundTripError as exc:
        print(f"\nThe comments in {edited.name} are not filed: {exc}")
        return
    present = {n for b in returned if not b.table for n in b.names}
    trusted = numbered.trusted | (numbered.unsure & present)
    threads = _threads(project, edited, {n: n for n in trusted} | dict(numbered.followed), offered)
    if not threads:
        return
    supplementary, _refusal = _document_kind(
        project, tagged_paragraphs(project), returned, edited.name
    )
    if supplementary is None:
        _report_comments(threads)
        print(f"\nThe comments are not filed: each is filed with the document it was made in, "
              f"and there is no telling which one {edited.name} is.")  # fmt: skip
        return
    if _file_comments(project, edited, threads, stamp=stamp, supplementary=supplementary,
                      applying=applying) and applying:  # fmt: skip
        print("The edits were not imported; the comments are filed all the same.")


def _file_comments(
    project, edited: Path, threads, *, stamp: str, supplementary: bool, applying: bool
) -> bool:
    """Print each comment, and with `--apply` file it as a finding the author answers
    (`filed_comments`); without, say what would be filed. False where some could not be."""
    from manuscript_guard.filed_comments import (
        FilingError,
        not_seeded,
        plan_filing,
        seeded,
        write_filing,
    )
    from manuscript_guard.roundtrip import printed_of

    if not threads:
        return True
    _report_comments(threads)
    threads, answered_there = not_seeded(threads, seeded(project))
    for thread, number in answered_there:
        print(f"\n{printable(thread.commenter)}'s comment of {thread.date or 'no date'} is a "
              f"point of revision round {number} already, answered in the response, and is "
              f"not filed again.")  # fmt: skip
    filings = plan_filing(
        project, threads, stamp=stamp, printed=printed_of(edited), supplementary=supplementary,
        today=date.today().isoformat(),
    )  # fmt: skip
    ok = True
    if filings:
        print()
    for filing in filings:
        where = filing.path.relative_to(project.root).as_posix()
        if filing.refused:
            ok = False
            print(f"not filed in {where}: {filing.refused}.")
            continue
        said = []
        if filing.added:
            said.append(f"{len(filing.added)} new ({', '.join(filing.added)})")
        if filing.extended:
            said.append(f"replies or Word's Resolve added to {', '.join(filing.extended)}")
        if filing.kept:
            said.append(f"{filing.kept} filed already")
        if filing.document is None:
            print(f"{where}: {'; '.join(said)}, nothing new.")
        elif not applying:
            print(f"--apply files in {where}: {'; '.join(said)}.")
        else:
            try:
                write_filing(filing)
            except (FilingError, OSError) as exc:
                ok = False
                print(f"not filed in {where}: {exc}")
                continue
            print(f"filed in {where}: {'; '.join(said)}.")
        for identifier in filing.reworded:
            print(f"  {identifier} reads differently in {edited.name}; the record keeps the "
                  f"words it was filed with.")  # fmt: skip
    if filings and ok:
        print("G11 reports each comment until it is answered in its record: what was done in "
              "`resolution`, or why it is left in `overridden`.")  # fmt: skip
    return ok


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
    if manuscript_format(manuscript) == LATEX:
        from manuscript_guard.gates.revision import PRINTED_COPY, rendered_manuscript

        # The documents as LaTeX prints them, values in, which is what G13 reads the paper
        # in now (step 8); and the sources as the submission folder writes them, inputs and
        # values in and comments out, the text the journal received (step 12).
        folder.mkdir(parents=True, exist_ok=True)
        text = rendered_manuscript(project, rendered)
        (folder / PRINTED_COPY).write_text(text, encoding="utf-8", newline="\n")
        from manuscript_guard.build.latex_pack import written_documents

        namespace, results = load_namespace(project)[:2]
        try:
            documents = written_documents(project, namespace, results).documents
        except BuildError as exc:
            print(f"the round keeps no copy of the LaTeX sources: {exc}")
            return folder
        (folder / "latex").mkdir(exist_ok=True)
        for name, written in documents:
            (folder / "latex" / f"{name}.tex").write_text(written, encoding="utf-8", newline="")
        return folder
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


def _no_document(tex: Path) -> str:
    """Why a `.tex` found in a folder starts no paper: it could not be read, or it has no
    `\\documentclass` (fix-only round of #463)."""
    from manuscript_guard.auditing.latex import unreadable_said

    return unreadable_said(tex) or (f"{tex.as_posix()} has no \\documentclass, so it starts no "
                               "document")  # fmt: skip


def _audit_refused(args: argparse.Namespace, said: str, *details: str) -> int:
    """An audit that did not happen, exit 2: why, on stderr, and under `--json` on stdout as
    well, as an object whose `ok` is false, so that a script reading stdout is told rather
    than handed nothing (round 1 of #463)."""
    for line in (said, *details):
        print(line, file=sys.stderr)
    if args.json:
        import json

        print(json.dumps({"ok": False, "error": said,
                          "details": [line.strip() for line in details]},
                         indent=2, ensure_ascii=True))  # fmt: skip
    return 2


def cmd_audit(args: argparse.Namespace) -> int:
    """Check an existing paper's numbers against existing outputs, and what needs none.

    For papers that were never written with this toolkit. Weaker than `check` by nature,
    and the report says how much weaker, measured against the outputs supplied. Without
    outputs no number is compared, and the rest is read all the same.
    """
    from manuscript_guard.audit import (
        FIGURE_SUFFIXES,
        PAPER_SUFFIXES,
        audit,
        doc_passed_over,
        is_lock_file,
        measure_discrimination,
    )
    from manuscript_guard.auditing import report as sections
    from manuscript_guard.auditing.gates import run_gates
    from manuscript_guard.auditing.latex import is_entry
    from manuscript_guard.auditing.references import look_up

    if (args.dry_run or args.lookup_cache) and not args.lookup:
        return _audit_refused(args, "manuscript-guard audit: --dry-run and --lookup-cache go "
                              "with --lookup")  # fmt: skip
    if args.minimum_cell_count is not None and args.minimum_cell_count < 1:
        return _audit_refused(args, "manuscript-guard audit: --minimum-cell-count is a whole "
                              "number from 1")  # fmt: skip
    # A `.tex` in a folder is a paper only where it starts a document; the others are read
    # where one inputs them, and named where none does.
    found_tex: list[Path] = []

    def expand(given: list[Path], suffixes: set[str]) -> list[Path]:
        found: list[Path] = []
        for path in given:
            if path.is_dir():
                for p in sorted(path.rglob("*")):
                    # Word's lock file beside an open document, "~$x.docx", is no paper.
                    if not p.is_file() or p.suffix.lower() not in suffixes or is_lock_file(p):
                        continue
                    if p.suffix.lower() == ".tex" and not is_entry(p):
                        found_tex.append(p)
                    else:
                        found.append(p)
            elif path.is_file():
                found.append(path)
        return found

    # A .doc in a folder is not read, and was passed over without a word: the paper in it
    # went unaudited and the report did not say so. It is named, as a note.
    docs = [
        p
        for folder in args.paper
        if folder.is_dir()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.suffix.lower() == ".doc" and not is_lock_file(p)
    ]

    # A path that is not there is a typo, and auditing without it answers a different
    # question: a missing output reports every number it held as absent from the paper.
    given = [*args.paper, *(args.against or []), *(args.figures or [])]
    missing = [path for path in given if not path.exists()]
    if missing:
        return _audit_refused(args, *(f"manuscript-guard audit: {path} does not exist"
                                      for path in missing))  # fmt: skip

    papers = expand(args.paper, PAPER_SUFFIXES)
    figures = expand(args.figures or [], FIGURE_SUFFIXES)
    if not papers and not figures:
        return _audit_refused(
            args, "nothing to audit: no .docx, .md or .tex that starts a document found in "
            "what you gave me", *(f"  {doc_passed_over(doc)}" for doc in docs),
            *(f"  {_no_document(tex)}" for tex in found_tex),
        )  # fmt: skip

    report = audit(papers, args.against, figures=figures,
                   whole_numbers=tuple(args.whole_numbers), passed_over=docs,
                   found_tex=found_tex, minimum=args.minimum_cell_count)  # fmt: skip
    if args.against and not report.backing_files:
        return _audit_refused(args, "--against gave the audit nothing it can read:",
                              *(f"  {item}" for item in report.skipped))  # fmt: skip
    if not report.papers:
        # "Audited 0 file(s) … 0 not found" read as a clean report, and exited 0 under
        # --strict, when every paper given was unreadable.
        return _audit_refused(args, "nothing given could be audited:",
                              *(f"  {item}" for item in (*report.unreadable,
                                                         *report.passed_over)))  # fmt: skip
    read = set(report.papers)
    report.gates = [
        *(run_gates(path, english=args.english, residue=args.submission_residue)
          for path in papers if path.suffix.lower() != ".tex" and path in read),
        *(run_gates(tree.entry, tree, english=args.english, residue=args.submission_residue)
          for tree in report.trees),
    ]  # fmt: skip
    if args.lookup:
        report.lookups = look_up(report.references, dry_run=args.dry_run,
                                 cache=args.lookup_cache)  # fmt: skip
    discrimination = measure_discrimination(report.backing_values) if args.against else None
    if args.json:
        print(sections.as_json(report, discrimination))
    else:
        print(sections.render(report, discrimination, Path.cwd()))
    if not report.examined:
        # An empty paper, or one whose numbers are all in pictures, printed "0 numeric
        # tokens" and passed --strict: an audit that read nothing.
        print(
            "the audit read no number in what it was given, so nothing was checked",
            file=sys.stderr,
        )
    # A paper or figure the audit could not read is a check that did not happen, which
    # --strict must not pass; nor is a paper with no number in it (`auditing.report`).
    return 1 if args.strict and sections.failed(report) else 0


def _reread(project, new: Path, page: str | None = None) -> int:
    """`journal --reread`: the stored page against the page read again, and the rules whose
    quotes it no longer holds. Writes nothing: adopting the page is the author's."""
    from manuscript_guard.gates.journal_quotes import DIFF_LINES, reread

    try:
        text = new.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"manuscript-guard: {new} cannot be read as UTF-8 text: {exc}", file=sys.stderr)
        return 2
    try:
        found = reread(project, text, page)
    except (LookupError, ValueError) as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
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
    # A box records no date of its own: only the instructions page and the blocks that do.
    dated = "" if found.blocks and all(b.startswith("boxes.") for b in found.blocks) else (
        " and today's retrieved_on")  # fmt: skip
    inside = stored.is_relative_to(project.root)
    where = stored.relative_to(project.root).as_posix() if inside else str(stored)
    print(
        f"Read the difference for rules the page added, too. To adopt the page, save it over "
        f"{where}, then record page_sha256: {found.digest}{dated} in the "
        + (f"profile's {', '.join(found.blocks)}." if found.blocks else "profile.")
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

    if args.page and not args.reread:
        print("manuscript-guard: --page names the page --reread reads again; give it with "
              "--reread <file>", file=sys.stderr)  # fmt: skip
        return 2
    if args.reread:
        return _reread(project, args.reread, args.page)

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
    if args.receipt is not None:
        return _receipt(project, args.receipt, args.only)
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


def _receipt(project, site: str, only: list[str] | None) -> int:
    """`verify --receipt SITE`, run where the data are: each harvest entry naming the site
    run in a copy, and the receipt written."""
    from manuscript_guard.harvest import HarvestError, make_receipt

    if only:
        print("manuscript-guard: --receipt runs every entry naming the site; it takes no "
              "--only", file=sys.stderr)  # fmt: skip
        return 2
    try:
        path, written, warned = make_receipt(project, site)
    except HarvestError as exc:
        print(f"manuscript-guard: no receipt written: {exc}", file=sys.stderr)
        return 1
    print(f"manuscript-guard verify --receipt {site} — {project.root}")
    for said in warned:
        print(f"  [WARN] {said}")
    for name in written:
        print(f"  wrote {name}, from the run")
    print(f"  wrote {path.relative_to(project.root).as_posix()}")
    print("\nSend the outputs and the receipt, never the data. The receipt is not signed: it "
          "is this site's declaration of what ran and what came out.")
    return 0


def _from_project(root: Path, given: str | Path) -> str:
    """A path the command was given, as harvest.yaml writes it: from the project's root,
    where a relative one is read from too."""
    from manuscript_guard.harvest import HarvestError

    path = Path(given)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(root.resolve())
        except ValueError:
            raise HarvestError(f"{given} is outside the project {root}") from None
    return path.as_posix()


def cmd_harvest(args: argparse.Namespace) -> int:
    """Add an entry to harvest.yaml and harvest it, or harvest every entry again. It reads
    output files and writes results fragments; it runs nothing."""
    from manuscript_guard.harvest import HarvestError, load_entries

    project, contract_report = load_project(args.path)
    if not contract_report.ok:
        print(contract_report.render(project.root))
        return 2
    root = project.root
    try:
        flags = ("script", "key", "input", "row_key", "columns", "digits", "receipt",
                 "counts", "restricted", "synthetic", "not_quoted")  # fmt: skip
        given = [name for name in flags
                 if getattr(args, name) is not None and getattr(args, name) is not False]
        if args.output is None and given:
            raise HarvestError(
                f"--{given[0].replace('_', '-')} describes an entry to add, and no OUTPUT was "
                "given: name it first, before --input, --columns or --counts, which take "
                "every word after them")  # fmt: skip
        entries = [_added(root, args)] if args.output is not None else load_entries(root)
        if not entries:
            raise HarvestError("harvest.yaml names no output to harvest: add one with "
                               "`harvest OUTPUT --script S --key K`")  # fmt: skip
    except HarvestError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    return _harvest_each(root, entries)


def _added(root: Path, args: argparse.Namespace):
    """The entry the command's flags describe, checked and added to harvest.yaml."""
    from manuscript_guard.contracts._schema import validate
    from manuscript_guard.harvest import (
        Entry,
        HarvestError,
        Input,
        append_entry,
        harvested_document,
    )
    from manuscript_guard.harvest.config import HARVEST_FILE

    if not (args.script and args.key):
        raise HarvestError("an output is added with --script, the script that writes it, and "
                           "--key, the name its results go by")  # fmt: skip
    entry = Entry(
        key=args.key, output=_from_project(root, args.output),
        script=_from_project(root, args.script),
        inputs=tuple(Input(_from_project(root, given), args.restricted, args.synthetic)
                     for given in args.input or ()),
        row_key=args.row_key, columns=tuple(args.columns) if args.columns else None,
        digits=args.digits, receipt=args.receipt, quoted=not args.not_quoted,
        counts=tuple(args.counts) if args.counts else None,
    )  # fmt: skip
    checked = validate({"entries": [entry.spec()]}, "harvest", root / HARVEST_FILE)
    if not checked.ok:
        raise HarvestError(checked.render(root))
    # Read first, so that an output that cannot be harvested leaves no entry behind.
    harvested_document(root, entry)
    append_entry(root, entry)
    return entry


def _harvest_each(root: Path, entries: list) -> int:
    """Harvest each entry, saying what each wrote or why it could not."""
    from manuscript_guard.harvest import HarvestError, harvest_entry

    failed = 0
    for entry in entries:
        try:
            written = harvest_entry(root, entry)
        except HarvestError as exc:
            failed += 1
            print(f"  [FAIL] {entry.key}: {exc}")
            continue
        print(f"  {entry.output} -> {written.relative_to(root).as_posix()}, table.{entry.key}")
    receipted = any(entry.receipt for entry in entries)
    print("\nNothing was run: that each script writes its output is declared, and `check` "
          "says so until `verify` re-runs it"
          + (", or the site's receipt covers it." if receipted else "."))
    return 1 if failed else 0


def cmd_package(args: argparse.Namespace) -> int:
    """Write the package an author deposits: the code, the results and what they ran with,
    and never the data a custodian keeps. It refuses while G1 fails, since a package of
    results the analysis no longer writes is the wrong package, and it uploads nothing."""
    from manuscript_guard.deposit import PackageError, deposit_steps, plan_package, write_package

    project, contract_report = load_project(args.path)
    _namespace, results, _literature, load_report = load_namespace(project)
    stage = resolve_stage(project, None, False)
    checks, _deferred = apply_stage(
        merge_all([contract_report, load_report, check_freshness(project, results),
                   check_restricted_inputs(project, results)]), stage)  # fmt: skip
    try:
        plan = plan_package(project, results, with_manuscript=args.with_manuscript,
                            citation=args.citation or args.root_citation,
                            ro_crate=args.ro_crate, companion=args.companion)  # fmt: skip
    except PackageError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(_package_listing(project, plan))
        if args.root_citation:
            print("\n".join(_root_citation(project, plan, dry_run=True)))
        if not checks.ok:
            print(f"\n{checks.render(project.root)}\n\nIt would not be written while these fail.")
        return 0 if plan.report.ok and checks.ok else 1
    if not checks.ok and not args.skip_checks:
        print(checks.render(project.root))
        print(f"\n{len(checks.failures)} failing. A package is what others will run again, so "
              "it is not written while the results are not what the analysis writes.\n"
              "Use --skip-checks only to see what it would hold; MANIFEST.yaml says so.")
        return 1
    if not plan.report.ok:
        print(plan.report.render(project.root))
        print("\nThe package is not written.")
        return 1
    if plan.report.findings:
        print(plan.report.render(project.root))
    try:
        written = write_package(project, plan, checked=checks.ok)
    except PackageError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    print(f"{len(plan.entries) + 2} files, {sum(not i.included for i in plan.inputs)} input(s) "
          f"withheld.\n{deposit_steps(project, written)}")  # fmt: skip
    if args.root_citation:
        print("\n" + "\n".join(_root_citation(project, plan, dry_run=False)))
    return 0


def cmd_deposit(args: argparse.Namespace) -> int:
    """Stage a bundle for a target in build/deposit/, once the data custodian's checks pass;
    nothing is sent anywhere (`deposit/command.py`)."""
    from manuscript_guard.deposit.command import run

    return run(args)


def _root_citation(project, plan, *, dry_run: bool) -> list[str]:
    """What `--root-citation` did, or would do, at the project's root: each file written
    where none was, and each kept, with the fields where it differs from the package's."""
    from manuscript_guard.deposit.metadata import root_citation

    return [f"root: {line}" for line in root_citation(project, plan.entries, dry_run=dry_run)]


def _package_listing(project, plan) -> str:
    """What `package --dry-run` says: each file that would go and why, each file left out
    and why, and what stops the package."""
    lines = [f"manuscript-guard package --dry-run — {project.root}",
             f"would write build/package/{plan.name}/ and {plan.name}.zip", ""]  # fmt: skip
    width = max((len(entry.path) for entry in plan.entries), default=0)
    lines += [f"  in   {entry.path.ljust(width)}  {entry.why}" for entry in plan.entries]
    lines += ["  in   MANIFEST.yaml, SHA256SUMS", ""]
    lines += [f"  out  {held.path}  {held.why}" for held in plan.withheld]
    if plan.report.findings:
        lines += ["", plan.report.render(project.root)]
    return "\n".join(lines)


def cmd_set(args: argparse.Namespace) -> int:
    """Write one setting of paper.yaml, keeping every comment and every other line."""
    from manuscript_guard.contracts import find_root
    from manuscript_guard.paper_edit import Refused, set_key, value_of, written

    try:
        path = find_root(args.path) / "paper.yaml"
    except ContractError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    try:
        done = set_key(path, args.key, list(args.value))
    except Refused as exc:
        print(f"manuscript-guard: {path} is as it was, since {exc}", file=sys.stderr)
        return 2
    new = value_of(args.key, list(args.value))
    if done.how == "unchanged":
        print(f"{path}: {args.key} is already {written(new)}; nothing written")
        return 0
    try:
        was = "not set" if done.before is None else written(done.before)
    except (TypeError, AttributeError):  # a value the schema refuses: a number, a mapping
        was = repr(done.before)
    print(f"{path}: {args.key} is now {written(new)} (it was {was})")
    back = args.key == "stage" and done.before in STAGES
    if back and STAGES.index(new) < STAGES.index(done.before):
        print(
            f"The stage moved back: a finding that starts to fail after {new}, up to "
            f"{done.before}, is now listed as not due."
        )
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """What to do now, from one run of every gate; writes nothing, and exits 0 once it has
    decided, whatever it found: `check` is the command whose exit says pass or fail."""
    from manuscript_guard import guide

    state = guide.inspect(args.path, stage=args.stage)
    actions = guide.decide(state)
    if args.json:
        print(guide.to_json(state, actions))
    else:
        print(guide.render(state, actions, every=args.all))
    return 0


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


def cmd_palettes(args: argparse.Namespace) -> int:
    """List the palettes shipped with the toolkit, with what the colour check says of each,
    or show one. Reads nothing of a project."""
    import json as json_module

    from manuscript_guard import palettes

    if args.show:
        try:
            found = palettes.palette(args.show)
            codes = palettes.colours(args.show, args.colours)
        except palettes.PaletteError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json_module.dumps({"name": found.name, "colours": codes,
                                     "collection": found.collection, "kind": found.kind,
                                     "distinct": found.distinct, "lightness": found.lightness,
                                     "lightness_kept": found.lightness_kept,
                                     "claims_cvd": found.claims_cvd}, indent=1))  # fmt: skip
            return 0
        for line in palettes.describe(found, codes):
            print(line)
        return 0
    try:
        rows = palettes.chosen(kind=args.kind, colours=args.colours, safe=args.safe,
                               collection=args.collection)  # fmt: skip
    except palettes.PaletteError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json_module.dumps([palettes.row(found) for found in rows], indent=1))
        return 0
    if not rows:
        print("no palette answers that; `manuscript-guard palettes` lists them all")
        return 1
    for line in palettes.table(rows, args.colours):
        print(line)
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
    from manuscript_guard.gates.numbers import _is_latex

    if _is_latex(project) or args.file.suffix.lower() == ".tex":
        return _explain_latex(project, args.file)
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
    return _explained(rows)


def _explained(rows: list[tuple[int, str, str, str, bool]]) -> int:
    """`explain`'s table: each number's line, text, kind and the rule that decided it."""
    if not rows:
        print("no numeric atoms outside masked regions")
        return 0
    rows.sort(key=lambda row: row[0])
    width = max(len(r[1]) for r in rows)
    for line, atom_text, kind, rule, failed in rows:
        marker = "FAIL" if failed else "ok  "
        print(f"{marker} {line:>5}  {atom_text:<{width}}  {kind:<12} {rule}")
    return 0


def _explain_latex(project, file: Path) -> int:
    """`explain` of a LaTeX manuscript's file: each number as G2 classifies it there, read
    through the include tree under the headings over it, a binding written `\\mg{...}`
    (step 12). G2's check of pointers to tables and figures is Markdown's only."""
    from manuscript_guard.gates.numbers import _files_read, _is_latex

    if not _is_latex(project):
        print(f"manuscript-guard explain: {file} is a LaTeX file in a Markdown manuscript, "
              "which no gate reads", file=sys.stderr)  # fmt: skip
        return 2
    wanted = file.resolve()
    read = next((each for each in _files_read(project) if each.path.resolve() == wanted), None)
    if read is None:
        print(f"manuscript-guard explain: {file} is no file of the manuscript's include tree, "
              "which is what the gates read", file=sys.stderr)  # fmt: skip
        return 2
    classifier = Classifier.load(project.extra_conventions, project.extra_terms)
    namespace, _results, _literature, _loaded = load_namespace(project)
    choices = [value for value in namespace.values() if value.role]
    chosen = chosen_rules(classifier)
    scan = read.scan(classifier)
    rows = []
    for atom in find_atoms(read.text, read.masked):
        verdict = classifier.classify_under(atom, read.chains(atom.start), scan)
        typed = typed_choice(atom.text, verdict, choices, chosen)
        rule = verdict.rule or "-"
        if typed is not None:
            rule = f"{rule}, typed: write {read.spell(typed.reference)}"
        failed = verdict.kind == UNCLASSIFIED or typed is not None
        rows.append((atom.line, atom.text, verdict.kind, rule, failed))
    return _explained(rows)


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
    from manuscript_guard.cards import model_cards

    project, _ = load_project(args.path)
    _namespace, results, _literature, _loaded = load_namespace(project)
    if not results.models:
        print("no models: an analysis records one with em.model() in Python, em$model() in R")
        return 0
    lines, report = model_cards(project, results)
    for line in lines:
        print(line)
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


def cmd_proof(args: argparse.Namespace) -> int:
    """Compare the publisher's proof with the document sent, and list the corrections.

    Exit 1 where the proof needs a correction, 0 where it needs none, and 2 where there is
    nothing to compare: no proof that can be read, no document sent, or a proof that reads
    as too little of it. Nothing is sent, and nothing is written but `--out`."""
    from manuscript_guard.proof import NotSent, NotThisProof, UnreadableProof, check_proof
    from manuscript_guard.proof.report import as_json, markdown, render

    if not args.proof.is_file():
        print(f"manuscript-guard proof: {args.proof} does not exist", file=sys.stderr)
        return 2
    project, _ = load_project(args.path)
    try:
        report = check_proof(project, args.proof, against=args.against,
                             supplementary=args.supplementary)  # fmt: skip
    except (NotSent, UnreadableProof, NotThisProof) as exc:
        print(f"manuscript-guard proof: {exc}", file=sys.stderr)
        return 2
    print(as_json(report) if args.json else render(report, project.root))
    if args.out is not None:
        args.out.write_text(markdown(report), encoding="utf-8", newline="\n")
        if not args.json:
            print(f"\nThe corrections are written to {args.out}, to paste into your reply.")
    return 1 if report.corrections else 0


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


def cmd_values(args: argparse.Namespace) -> int:
    """Write each LaTeX document's values file, `mgvalues.sty`, beside its entry file, from the
    results as they stand (DESIGN.md, "LaTeX manuscripts", "The values file")."""
    from manuscript_guard.build.latex_values import bound_refs, values_files

    project, _ = load_project(args.path)
    namespace, results, _literature, load_report = load_namespace(project)
    if not load_report.ok:
        print(load_report.render(project.root))
        return 2
    written = values_files(project, namespace, results)
    if not written:
        folder = project.path("manuscript")
        print("manuscript-guard: values writes a LaTeX manuscript's values file, and "
              f"{folder} holds no LaTeX entry file", file=sys.stderr)  # fmt: skip
        return 2
    bound = bound_refs(project)
    for each in written:
        each.path.write_text(each.text, encoding="utf-8", newline="\n")
        entries = each.text.count(r"\expandafter\def")
        print(f"wrote {each.path} ({entries} entr{'y' if entries == 1 else 'ies'})")
    # A value it has no way to print is left out; one a document binds prints `??` there.
    refused = [found for each in written for found in each.refused
               if found.ref in bound.get(each.path.parent, set())]  # fmt: skip
    for found in refused:
        print(f"manuscript-guard: {found}; the document prints ?? for it", file=sys.stderr)
    return 1 if refused else 0



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


def _latex_engine(project) -> str:
    """The engine the journal's profile names, as `latex: {engine: ...}`, or pdfLaTeX."""
    from manuscript_guard.gates.journal import _profile, profile_path

    profile = _profile(project)
    slug = project.target_journal
    if profile is None and slug and profile_path(project, slug) is not None:
        print(f"the journal's profile {slug} does not validate, so the engine it may name is "
              "not read: building with pdfLaTeX (round 3 of step 9)", file=sys.stderr)  # fmt: skip
    return ((profile or {}).get("latex") or {}).get("engine", "pdflatex")


def _build_latex(project, report, args: argparse.Namespace) -> int:
    """`build` for a LaTeX manuscript: its PDF, and its supplement's, compiled in a copy in
    `build/latex/` and given as `build/manuscript.pdf` and `build/supplementary.pdf`, an
    unchecked one named so, as the Word build names its documents (step 9)."""
    from manuscript_guard.build.latex import LatexMissing, build_latex

    if getattr(args, "marked_up", False) or getattr(args, "annotated", False):
        print("manuscript-guard: --marked-up and --annotated make Word copies, and a LaTeX "
              "manuscript is built as a PDF", file=sys.stderr)  # fmt: skip
        return 2
    if not report.ok and not args.skip_checks:
        print(report.render(project.root))
        print(f"\n{len(report.failures)} failing; not building. Use --skip-checks to override.")
        return 1
    namespace, results, _literature, _ = load_namespace(project)
    try:
        compiled = build_latex(project, namespace, results, engine=_latex_engine(project))
    except LatexMissing as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    except BuildError as exc:
        print(f"manuscript-guard: the PDF is not built: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"manuscript-guard: the PDF is not built: {exc}", file=sys.stderr)
        return 2
    return _pdfs_built(project, report, args, compiled)


def _pdfs_built(project, report, args: argparse.Namespace, compiled) -> int:
    """The PDFs compiled given as `build/manuscript.pdf` and `build/supplementary.pdf`, an
    unchecked one named so, each citation or reference LaTeX left undefined listed, and any
    failing at `--submission` (steps 9 and 11)."""
    mark = "" if report.ok else ".UNCHECKED"
    names = ("manuscript", "supplementary")
    project.path("build").mkdir(parents=True, exist_ok=True)
    for name, document in zip(names, compiled, strict=False):
        target = project.path("build") / f"{name}{mark}.pdf"
        if name == "manuscript" and args.output is not None:
            target = Path(args.output)
        try:
            target.write_bytes(document.pdf.read_bytes())
        except OSError as exc:
            # A PDF open in a reader that locks it, on Windows (round 2 of step 9).
            print(f"manuscript-guard: {target} could not be written: {exc}", file=sys.stderr)
            return 2
        print(f"built {target}" + ("" if name == "manuscript" else
                                   " (supplementary material, its own document)"))  # fmt: skip
        for left in document.undefined:
            print(f"  LaTeX left the {left} undefined")
    if not report.ok:
        print(f"{len(report.failures)} check(s) were failing, so this is named UNCHECKED. "
              "Fix them and rebuild before sending it anywhere.")  # fmt: skip
    if args.submission and any(document.undefined for document in compiled):
        print("an undefined citation or reference fails at submission: the PDF prints `?` "
              "where it stands")  # fmt: skip
        return 1
    return 0


def _latex_from_markdown(project, args: argparse.Namespace):
    """The LaTeX folder and PDFs of a Markdown manuscript, as `latex_pack.LatexPack`, or the
    exit status where it could not be made, said (step 11)."""
    from manuscript_guard.build.latex import LatexMissing
    from manuscript_guard.build.latex_out import build_from_markdown

    namespace, results, _literature, _ = load_namespace(project)
    assembled, assemble_report = assemble(project, namespace, results)
    if not assemble_report.ok:
        print(assemble_report.render(project.root))
        return 1
    _print_assembly_warnings(assemble_report, project)
    # Citeproc formats offline, with the journal's style kept by `style` or the one given.
    style = _journal_style(project, argparse.Namespace(csl=args.csl, offline=True))
    try:
        return build_from_markdown(project, assembled, engine=_latex_engine(project), csl=style)
    except LatexMissing as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    except BuildError as exc:
        print(f"manuscript-guard: the LaTeX is not built: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"manuscript-guard: the LaTeX is not built: {exc}", file=sys.stderr)
        return 2


def _build_markdown_latex(project, report, args: argparse.Namespace) -> int:
    """`build --latex` for a Markdown manuscript: the LaTeX source pandoc writes, checked
    against the Markdown, in one folder, and its PDFs (step 11)."""
    if getattr(args, "marked_up", False) or getattr(args, "annotated", False):
        print("manuscript-guard: --marked-up and --annotated make Word copies; build them "
              "without --latex", file=sys.stderr)  # fmt: skip
        return 2
    if not report.ok and not args.skip_checks:
        print(report.render(project.root))
        print(f"\n{len(report.failures)} failing; not building. Use --skip-checks to override.")
        return 1
    packed = _latex_from_markdown(project, args)
    if isinstance(packed, int):
        return packed
    print(f"the LaTeX source: {packed.folder}")
    # Each document with what LaTeX left undefined in it (round 1 of step 11).
    return _pdfs_built(project, report, args, list(packed.each))


def _without_stale_document(report, project, args: argparse.Namespace):
    """`report` less the `document-stale` of each document in `build/` that this Word build
    writes over, the one finding it clears by running: the paper, under its checked or
    UNCHECKED name, where `--output` sends it nowhere else; the supplement, where there is
    one; and the annotated copy, which an annotated build writes in their place. Every
    `document-stale` was set aside, so a stale `build/x.docx`, which no build rewrites, was
    passed without a word (round 1 of #452)."""
    from dataclasses import replace

    if getattr(args, "annotated", False):
        rewritten = {"manuscript.annotated.docx"}
    else:
        named = args.output is not None
        rewritten = set() if named else {"manuscript.docx", "manuscript.UNCHECKED.docx"}
        supplement = project.path("manuscript") / "supplementary"
        if supplement.is_dir() and any(path.is_file() for path in supplement.rglob("*")):
            rewritten.add("supplementary.docx")
    build = project.path("build").resolve()

    def rewrites(finding) -> bool:
        where = Path(finding.path).resolve() if finding.path else None
        return where is not None and where.parent == build and where.name in rewritten

    kept = tuple(f for f in report.findings if not (f.code == "document-stale" and rewrites(f)))
    return replace(report, findings=kept)


def _superseded_unchecked(project) -> None:
    """The UNCHECKED copy of an older source taken away once a checked build has written
    `manuscript.docx`: left, it stayed stale with no build that could clear it."""
    from manuscript_guard.build.document import SOURCE_STAMP

    unchecked = project.path("build") / "manuscript.UNCHECKED.docx"
    for path in (unchecked, unchecked.with_name(unchecked.name + SOURCE_STAMP)):
        if path.is_file():
            path.unlink()


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
    if manuscript_format(project.path("manuscript")) == LATEX:
        return _build_latex(project, report, args)
    if getattr(args, "latex", False):
        return _build_markdown_latex(project, report, args)
    # A stale .docx is this build's to clear: counted, it refused the build that would
    # rewrite it, and `--skip-checks` wrote an UNCHECKED copy beside it, a second finding.
    report = _without_stale_document(report, project, args)
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
        # With `--output` the name is the author's, and saying it is UNCHECKED was untrue.
        called = "this is named UNCHECKED" if args.output is None else "it is unchecked"
        print(
            f"{len(report.failures)} check(s) were failing, so {called}. "
            f"Fix them and rebuild before sending it anywhere."
        )
    elif args.output is None:
        _superseded_unchecked(project)
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

    # A document the blind check could not read is no more to be sent than one it read a
    # name in, and the build exited 0 for its own (`docx-unreadable`).
    named = any(f.code in (CODE, "docx-unreadable") for f in result.report.failures)
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
        print("The document names an author, or could not be read for their names, and the "
              "journal's review is blind: do not send it.")  # fmt: skip
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

    from manuscript_guard.text.reader import LATEX, manuscript_format

    if manuscript_format(project.path("manuscript")) == LATEX or getattr(args, "latex", False):
        return _submit_latex(project, report, args)
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
        coauthors = _coauthor_verification(project)
        pack = assemble_pack(project, document, checked=report.ok, extra=marked,
                             coauthor_verification=coauthors.text)  # fmt: skip
    except SubmissionError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    return _packed(project, report, pack, marked_notes, coauthors)


def _submit_latex(project, report, args: argparse.Namespace) -> int:
    """`submit` for a LaTeX manuscript, or `submit --latex` for a Markdown one: the source as
    one folder, `latex/`, compiled alone, and that compile's PDFs as the documents (steps 10
    and 11)."""
    from manuscript_guard.build import SubmissionError, assemble_pack
    from manuscript_guard.build.blinding import check_blinded_latex
    from manuscript_guard.build.latex import LatexMissing
    from manuscript_guard.build.latex_pack import pack_latex
    from manuscript_guard.gates.revision import rounds

    if args.document is not None:
        print("manuscript-guard: --document packs a Word document a co-author edited, and a "
              "LaTeX manuscript is packed from its source", file=sys.stderr)  # fmt: skip
        return 2
    from manuscript_guard.text.reader import LATEX, manuscript_format

    if manuscript_format(project.path("manuscript")) != LATEX:
        packed = _latex_from_markdown(project, args)
        if isinstance(packed, int):
            return packed
    else:
        namespace, results, _literature, _ = load_namespace(project)
        try:
            packed = pack_latex(project, namespace, results, engine=_latex_engine(project))
        except LatexMissing as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2
        except BuildError as exc:
            print(f"manuscript-guard: the pack is not assembled: {exc}", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"manuscript-guard: the pack is not assembled: {exc}", file=sys.stderr)
            return 2
    if packed.undefined:
        for left in packed.undefined:
            print(f"LaTeX left the {left} undefined")
        print("\nAn undefined citation or reference fails at submission: the PDF prints `?` "
              "where it stands. The pack is not assembled.")  # fmt: skip
        return 1
    blind = check_blinded_latex(project, list(packed.files))
    if not blind.ok:
        print(blind.render(project.root))
        print("\nThe source names an author, and the journal's review is blind. The pack is "
              "not assembled.")  # fmt: skip
        return 1
    notes = []
    if rounds(project):
        notes.append("no marked-up copy is packed: `build --marked-up` makes Word copies, "
                     "and the LaTeX source is packed without one")  # fmt: skip
    try:
        coauthors = _coauthor_verification(project)
        pack = assemble_pack(project, packed.documents[0], checked=report.ok,
                             extra=[(path, f"latex/{path.name}") for path in packed.files],
                             supplements=packed.documents[1:],
                             coauthor_verification=coauthors.text)  # fmt: skip
    except SubmissionError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    return _packed(project, report, pack, notes, coauthors)


@dataclass(frozen=True)
class _Coauthors:
    """What `submit` packs and says of the co-authors' checking: the publisher's copy of the
    recap, where the project has a record; a warning for each flag still open; and why no copy
    is packed, where one is not."""

    text: str | None = None
    flags: Report = field(default_factory=Report)
    notes: tuple[str, ...] = ()


def _coauthor_verification(project) -> _Coauthors:
    """The publisher's recap for the pack, and `coauthor-flag-open` for each current `wrong`
    or `code` that is still the latest answer of the person who gave it. Said, and never
    refused: whether to send with a co-author's flag open is the corresponding author's call
    (decision 7 (a)). The warnings need the record and the items only, so they are said where
    the copy cannot be made, the register unreadable, say (round 2 of #465)."""
    import csv
    import io

    from manuscript_guard.checking.items import ItemsError
    from manuscript_guard.checking.recap import RecapError, earlier_for, flags_of, make
    from manuscript_guard.checking.store import decisions_path
    from manuscript_guard.text.reader import LATEX, manuscript_format

    if not decisions_path(project.root).is_file():
        return _Coauthors()
    if manuscript_format(project.path("manuscript")) == LATEX:
        return _Coauthors(notes=("no coauthor-verification.md is packed: `checker` reads a "
                                 "Markdown manuscript only",))  # fmt: skip
    said = io.StringIO()
    try:
        # What it prints of the items it leaves out is for `checker`; what it could not read
        # is said below, since the table is the poorer for it.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
            items = _checking_items(project, None)
    except ItemsError as exc:
        return _Coauthors(notes=(f"no coauthor-verification.md is packed: {exc}",))
    unread = tuple(f"coauthor-verification.md: {line}" for line in said.getvalue().splitlines())
    try:
        text = make(project, items, earlier=earlier_for(project), publisher=True).text
    except RecapError as exc:
        text, unread = None, (*unread, f"no coauthor-verification.md is packed: {exc}")
    try:
        open_ = flags_of(project.root, items)
    except (OSError, UnicodeDecodeError, csv.Error):
        # The record itself cannot be read: the note above says so.
        open_ = ()
    flags = tuple(
        Finding(
            gate="BUILD", code="coauthor-flag-open", severity=WARN,
            message=f"{flag.by} answered {flag.status!r} on {flag.title or flag.id}, and has "
            f"given no later answer on it, nor has it changed since: {flag.note or 'no note'}",
            path=decisions_path(project.root),
            hint="any later answer of theirs on it, or an edit to the item, closes it: change "
            "what they asked for, or ask them again (`checker build`); `checker recap` lists "
            "each with its sentence or its steps",
        )
        for flag in open_
    )  # fmt: skip
    return _Coauthors(text, Report(flags), unread)


def _packed(project, report, pack, notes: list[str], coauthors: _Coauthors | None = None) -> int:
    """What `submit` says of the pack it assembled."""
    print(f"submission pack: {pack.directory}")
    if not report.ok:
        print(f"  assembled with --skip-checks; {pack.manifest.name} records that.")
    for path in pack.files:
        print(f"  {path.relative_to(pack.directory)}")
    print(f"  {pack.manifest.name}")
    for note in (*pack.notes, *notes):
        print(f"  {note}")
    # Said, and not refused: whether to send without an approval is the corresponding
    # author's call, and an approval given by e-mail is still one.
    from manuscript_guard.approvals import check_approvals

    approvals = check_approvals(project)
    if approvals.findings:
        print()
        print(approvals.render(project.root))
    coauthors = coauthors or _Coauthors()
    for note in coauthors.notes:
        print(f"  {note}")
    if coauthors.flags.findings:
        # As the approvals are: said, not refused (decision 7 (a) of Task 1).
        print()
        print(coauthors.flags.render(project.root))
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
    from manuscript_guard.deposit import package_signables
    from manuscript_guard.gates.design_review import override_signables
    from manuscript_guard.gates.journal_quotes import manual_signables
    from manuscript_guard.gates.models import signables
    from manuscript_guard.panel.custodian import send_signables
    from manuscript_guard.sign_offs import CORRESPONDING, ROLES, holder, is_holder, sign

    # As `deposit` refuses it where it labels nothing (round 2 of #460).
    if args.retrospective is not None and not args.finding.startswith("DEPOSIT/"):
        print(f"manuscript-guard: --retrospective is for a plan's deposit, "
              f"DEPOSIT/custodian/<target>/preregistration, and {args.finding} is not a "
              "deposit's", file=sys.stderr)  # fmt: skip
        return 2
    project, _ = load_project(args.path)
    _namespace, results, _literature, _loaded = load_namespace(project)
    standing = signables(project, results) + override_signables(project) + \
        manual_signables(project) + send_signables(project)  # fmt: skip
    # The package's, only where a sign-off of one is asked for: they are worked out from
    # every file the package would hold.
    if args.finding.startswith("PACKAGE/"):
        notes: list[str] = []
        standing += package_signables(project, results, notes)
        for note in dict.fromkeys(notes):
            print(f"manuscript-guard: {note}", file=sys.stderr)
    # A bundle's, only where one is asked for: it is worked out from every file it holds.
    if args.finding.startswith("DEPOSIT/"):
        from manuscript_guard.deposit.bundles import DepositError
        from manuscript_guard.deposit.command import deposit_signable

        try:
            bundled = deposit_signable(project, results, args.finding, args.retrospective)
        except DepositError as exc:
            if str(exc):
                print(f"manuscript-guard: {args.finding} cannot be planned: {exc}",
                      file=sys.stderr)  # fmt: skip
            return exc.status
        standing += [bundled] if bundled is not None else []
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
    from manuscript_guard.text.reader import CitationsUnknown
    from manuscript_guard.zotero import ZoteroUnavailable

    project, _ = load_project(args.path)
    try:
        path, count = sync_bib(project)
    except (ZoteroUnavailable, CitationsUnknown) as exc:
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
    if args.journals and args.registrations:
        print("manuscript-guard: ask for --journals or --registrations, not both", file=sys.stderr)
        return 2
    if args.journals:
        return _lookup_journals(project, args)
    if args.registrations:
        return _lookup_registrations(project, args)
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


def cmd_dictionary(args: argparse.Namespace) -> int:
    """Write the data dictionary out for whoever builds the form: REDCap's data dictionary,
    a plain CSV, or the form's outline. Each is written only where the dictionary reads and
    the shape can hold it; nothing is written on a refusal."""
    import os

    from manuscript_guard.contracts.dictionary import DICTIONARY, load_dictionary
    from manuscript_guard.dictionary_export import ExportRefused, outline, plain_csv, redcap

    wanted = [(target, make) for target, make in
              ((args.redcap, redcap), (args.csv, plain_csv), (args.outline, outline))
              if target is not None]  # fmt: skip
    if not wanted:
        print("say what to write: --redcap, --csv or --outline", file=sys.stderr)
        return 2
    # One file under two spellings, out.csv and OUT.csv on Windows, is one file (round 2).
    if len({os.path.normcase(target.resolve()) for target, _make in wanted}) < len(wanted):
        print("each of --redcap, --csv and --outline needs a file of its own", file=sys.stderr)
        return 2
    project, _ = load_project(args.path)
    dictionary, report = load_dictionary(project)
    if dictionary is None:
        if report.ok:
            print(f"there is no {DICTIONARY.as_posix()} to write out", file=sys.stderr)
            return 2
        print(report.render(project.root))
        return 1
    try:
        written = [(target, make(dictionary)) for target, make in wanted]
    except ExportRefused as refused:
        print(f"nothing written: {refused}", file=sys.stderr)
        return 1
    for target, made in written:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(made.text.encode("utf-8"))
        except OSError as exc:
            print(f"cannot write {target}: {exc.strerror or exc}", file=sys.stderr)
            return 1
        print(f"wrote {target}")
        for said in made.left_out:
            print(f"  left out {said}")
    return 0


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


def _lookup_registrations(project, args: argparse.Namespace) -> int:
    """`lookup --registrations`: each registration paper.yaml lists asked of its registry."""
    from manuscript_guard.lookup import registrations

    planned = registrations.plan(project, again=args.again)
    if not planned:
        print("paper.yaml lists no registration, so nothing was looked up")
        return 0
    due = [p for p in planned if not p.skipped]
    for one in planned:
        if one.skipped and one.skipped != "up to date":
            print(f"{one.id or one.written}: not looked up: {one.skipped}")
    if args.dry_run:
        for one in due:
            print(f"{one.id}: would ask {registrations.NAMES[one.registry]} ({one.why})")
        print(f"{len(due)} to look up, {len(planned) - len(due)} not; nothing was sent")
        return 0
    written = registrations.run(project, planned)
    late = sum(1 for _one, record, _path in written if record["status"] == "unresolvable")
    up_to_date = sum(1 for p in planned if p.skipped == "up to date")
    print(f"{len(written)} looked up, {up_to_date} up to date; records in design/registrations/")
    if late:
        print(f"{late} had an answer that did not come; `lookup --registrations` asks again "
              "for those")  # fmt: skip
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


def _checking_items(project, named: Path | None, *, build: bool = False,
                    told: list[str] | None = None):
    """What this project offers a co-author: what the toolkit finds, plus what the project adds.

    The toolkit finds the values quoted from the literature, the sentences that cite something,
    the references and the authors. A number transcribed from a table in a source document is not
    among them and cannot be — only the project knows where that one came from — so a project
    that traces its own writes `checks/items.json`, and those go in front.

    With `told`, what would be printed is added to it instead, for `next`, whose `--json` is
    the whole of what it prints and which says it among its notes.
    """
    from manuscript_guard.checking.items import SCHEMA, ItemsError, items_file, items_from
    from manuscript_guard.checking.produce import RESERVED_GROUPS, merge, produce_with_notes
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

    reserved = sorted({str(group.get("id")) for group in (contributed or {}).get("groups") or ()
                       if str(group.get("id")) in RESERVED_GROUPS})  # fmt: skip
    if reserved and build:
        # Taken whole, it would send the project's items under the toolkit's question, and
        # the toolkit's would not be sent. Refused where a page is made; read as before by
        # `import` and `status`, so that answers already given come in and are counted.
        raise ItemsError(
            f"{source} declares the group {reserved[0]!r}, whose id is now the toolkit's: its "
            "items are each Methods text beside the code G9 holds it to. Rename the project's "
            "group, and the `group` of each of its items, to another id (`methods-own`, say), "
            "and build again. The items keep their ids, so the answers recorded on them are "
            "still theirs; the digest holds the group, so they are asked again, notes kept."
        )
    produced, unread, notes, unavailable = produce_with_notes(project)
    if reserved:
        mine = [item for item in produced["items"] if item["group"] in reserved]
        produced = {**produced, "items": [i for i in produced["items"] if i not in mine]}
        unavailable = {}
        if mine:
            line = (f"{', '.join(reserved)}: the toolkit's {len(mine)} item(s) are left out, "
                    f"because {source.name} declares that group itself; rename it there to "
                    "send them (`checker build` says how).")  # fmt: skip
            if told is None:
                print(line)
            else:
                told.append(line)
    for said in notes if build else ():
        # A Methods claim left out of the round, or code shown from a script that changed
        # since its run: said where the page is built, which is where it can still be fixed.
        print(said)
    for said in unread:
        # A ledger the contract cannot read takes every value in it out of the round. Printed
        # rather than left to be noticed as a page that is suspiciously short.
        line = f"not read, so nothing from it is in this round — {said}"
        if told is None:
            print(line, file=sys.stderr)
        else:
            told.append(line)
    document, skipped = merge(produced, contributed)
    for group, count in sorted(skipped.items()):
        line = (f"{group}: {count} item(s) the toolkit found are left out, because this project "
                f"supplies that group itself in {source.name}.")  # fmt: skip
        if told is None:
            print(line)
        else:
            told.append(line)
    if not document["items"]:
        # Reachable on a project that has not got far enough to have anything to check, where
        # the schema's "items: [] should be non-empty" names a file that does not exist and a
        # rule the author never wrote. Say what was looked at instead.
        raise ItemsError(
            "there is nothing to check yet. A co-author is sent the values quoted from the "
            "literature (literature/ledger.yaml and attested.yaml), the sentences that cite "
            "something, the Methods beside the code their {{method.<step>}} anchors name, the "
            "references (literature/references.bib) and the authors (authors.yaml), and none "
            "of those holds anything. A project that traces numbers of "
            f"its own adds them in {source}: see contracts/schemas/checking.schema.json."
        )
    from dataclasses import replace

    return replace(items_from(document, source), unavailable=unavailable)


def cmd_checker(args: argparse.Namespace) -> int:
    """Send a co-author the numbers to check, and take their answers back.

    Four verbs, and they are the whole of a round: `build` writes one file per person, `import`
    records what they sent back, `status` says where the round stands, and `recap` writes
    `checks/recap.md`, who checked what, or with `--check` holds one to the record. Nothing
    here asks the
    co-author to install, sign in or configure anything, and nothing here is particular to a
    model or a vendor: the file is a page, the answers are JSON, the record is a CSV.
    """
    from manuscript_guard.checking import ItemsError

    if getattr(args, "check", None) is not None and args.verb != "recap":
        print("manuscript-guard: --check belongs to `checker recap`", file=sys.stderr)
        return 2
    project, _ = load_project(args.path)
    try:
        items = _checking_items(project, args.items, build=args.verb == "build")
    except ItemsError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    if args.verb == "build":
        return _checker_build(project, items, args)
    if args.verb == "import":
        return _checker_import(project, items, args)
    if args.verb == "recap":
        return _checker_recap(project, items, args)
    return _checker_status(project, items)


def _checker_people(project, args) -> list[tuple[str, str, str]] | str:
    """Whom `build` writes a page for, each as (the name their answers are recorded under, the
    name the page shows, the ORCID iD), or why it cannot say. The two names are one: kept apart
    in the tuple for a page whose greeting and record would differ."""
    from manuscript_guard.approvals import (
        AmbiguousAuthor,
        NoSuchAuthor,
        authors_of,
        find_author,
        name_of,
    )
    from manuscript_guard.checking.people import (
        Namesakes,
        SharedOrcid,
        fold,
        namesakes,
        namesakes_message,
        refuse_shared_orcids,
        resolve,
    )

    if args.every and args.name:
        return "give --for or --all, not both"
    if not args.every and args.leave_out:
        return "--except is for --all"
    if not args.every and not args.name.strip():
        return ("say who the file is for, with --for \"<name>\", or write one for every "
                "author with --all: a decision is recorded under their name")  # fmt: skip
    try:
        refuse_shared_orcids(project)
        # An ORCID iD given to --for is looked up as one; a name is not an iD.
        given = args.name.strip()
        as_orcid = given if re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", given) else ""
        found = None if args.every else resolve(project, args.name, as_orcid)
    except (AmbiguousAuthor, Namesakes, SharedOrcid) as exc:
        return str(exc)
    if found is not None:
        if found.author is None:
            print(f"{args.name.strip()} is not an author in authors.yaml: the page is built for "
                  "them all the same, and their answers will say so.")  # fmt: skip
            return [(args.name.strip(), args.name.strip(), "")]
        orcid = str(found.author.get("orcid") or "").strip()
        return [(found.by, found.by, orcid)]
    left_out = []
    for said in args.leave_out:
        try:
            left_out.append(find_author(project, said))
        except NoSuchAuthor as exc:
            return f"--except: {exc}"
    shared = namesakes(project)
    for group in shared.values():
        print(f"left out: {namesakes_message(name_of(group[0]))}.")
    people = [(name_of(a), name_of(a), str(a.get("orcid") or "").strip())
              for a in authors_of(project)
              if not any(a is other for other in left_out) and fold(name_of(a)) not in shared]
    if not people:
        if shared and not left_out:
            return namesakes_message(name_of(next(iter(shared.values()))[0]))
        return ("--all writes a page for each author in authors.yaml, and that leaves nobody"
                if left_out or shared else "--all writes a page for each author in "
                "authors.yaml, and it lists none")  # fmt: skip
    return people


def _page_name(name: str, others: list[str]) -> str:
    """The file name of a person's page, the same in every run. Two names that fold to one,
    "José García" and "Jose Garcia", each take a few characters of the digest of the name as
    written: numbered by their order, the second page took the first's file name in a run
    that built the second alone."""
    import hashlib
    import unicodedata

    from manuscript_guard.checking.bundle import slug
    from manuscript_guard.checking.people import fold

    named = slug(name)
    if not any(slug(other) == named and fold(other) != fold(name) for other in others):
        return named
    exact = unicodedata.normalize("NFC", " ".join(name.split()))
    return f"{named}-{hashlib.sha256(exact.encode('utf-8')).hexdigest()[:6]}"


def _register_place(project, out: Path) -> str:
    """How the register names a page's file: relative to the project where it is inside it,
    and as an absolute path where it is not."""
    try:
        return out.resolve().relative_to(project.root.resolve()).as_posix()
    except ValueError:
        return str(out.resolve())


def _same_file(project, recorded: str, out: Path) -> bool:
    """Whether the register's name for a file is `out`, as the file system compares names: on
    Windows without case, and, for a file that is there, as the file system itself says (a
    volume on macOS ignores case too)."""
    import os

    path = Path(recorded)
    path = path if path.is_absolute() else project.root / path
    if os.path.normcase(str(path.resolve())) == os.path.normcase(str(out.resolve())):
        return True
    try:
        return path.exists() and out.exists() and os.path.samefile(path, out)
    except OSError:
        return False


def _registered_to_another(project, out: Path, person: str) -> str | None:
    """Whom the register says the file `out` was last built for, where it is not `person`."""
    import csv

    from manuscript_guard.checking.people import fold
    from manuscript_guard.checking.register import register_path

    path = register_path(project.root)
    if not path.is_file():
        return None
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle)
                if row.get("file") and _same_file(project, str(row["file"]), out)]  # fmt: skip
    if rows and fold(str(rows[-1].get("person") or "")) != fold(person):
        return str(rows[-1].get("person") or "")
    return None


def _checker_build(project, items, args) -> int:
    from manuscript_guard.approvals import authors_of, name_of
    from manuscript_guard.checking import status
    from manuscript_guard.checking.register import REGISTER

    people = _checker_people(project, args)
    if isinstance(people, str):
        print(f"manuscript-guard: {people}", file=sys.stderr)
        return 2
    title = args.title or str(project.paper.get("short_title") or project.paper.get("title") or "")
    # Back to the corresponding author unless told otherwise: the one who sent the page.
    to = args.to or " or ".join(name_of(a) for a in authors_of(project) if a.get("corresponding"))
    folder = (args.output or project.root / "checks") if args.every else None
    names = [name_of(a) for a in authors_of(project)] + [shown for _, shown, _ in people]
    targets = []
    for key, name, orcid in people:
        named = _page_name(name, names)
        out = (folder / f"check-{named}.html" if folder is not None
               else args.output or project.root / "checks" / f"check-{named}.html")  # fmt: skip
        targets.append((key, name, orcid, out))
    # Every file is held to the register before any is written: a page that is another
    # person's, found half way through `--all`, left the round half built.
    for key, _name, _orcid, out in targets:
        other = _registered_to_another(project, out, key)
        if other is not None:
            for *_, target in targets:  # what a failed run left beside them goes too
                target.with_name(target.name + ".part").unlink(missing_ok=True)
            print(f"manuscript-guard: {_register_place(project, out)} is the page built for "
                  f"{other} ({REGISTER}); it is not replaced with {key}'s, and no page is "
                  f"written. Name another file or folder with -o.", file=sys.stderr)  # fmt: skip
            return 2
    standing = status(project.root, items)
    asked = items.outstanding
    answered = sum(1 for item in asked if standing.answered.get(str(item["id"])))
    for key, name, orcid, out in targets:
        written = _write_page(project, items, out, person=key, shown=name, orcid=orcid,
                              title=title, to=to)  # fmt: skip
        if written is None:
            return 2
        print(f"wrote {out} ({written // 1024} kB)")
        # From the record as well as from the items file. "0 already checked by someone" was
        # printed after a whole round had come back and been imported, because this counted
        # only the `already` field a project may write. Then "10 item(s) to check, 10 already
        # checked" counted the same items twice: what the page asks, and who has answered
        # those. So the second number is a part of the first, and the items the page shows as
        # done already are counted apart.
        print(
            f"{len(asked)} item(s) for {name} to check, {answered} of them already "
            f"answered by someone else."
        )
    if standing.already:
        print(f"{standing.already} more on the page are marked as checked before this round.")
    print(f"Each page is recorded in {REGISTER}, with the digest of its token.")
    print(
        "Send each person their one file. It opens by double-clicking, needs nothing installed "
        "and no network, and its own button writes the answers file to send back."
    )
    return 0


def _write_page(project, items, out: Path, *, person: str, shown: str, orcid: str, title: str,
                to: str) -> int | None:  # fmt: skip
    """Write one page and its row, and return its size; None, said, where either fails.

    The page is written under another name first, recorded, and only then given its own: a page
    whose row could not be written (the register open in a spreadsheet) is not left to be sent.
    The temporary file goes whatever happens, and one a failed run left goes first."""
    import os

    from manuscript_guard.checking import BundleError, build_page
    from manuscript_guard.checking import register as registered
    from manuscript_guard.checking.register import REGISTER, Row, token_sha256

    part = out.with_name(out.name + ".part")
    try:
        part.unlink(missing_ok=True)
        built = build_page(items, person=person, title=title, out=part, to=to, orcid=orcid,
                           shown=shown)  # fmt: skip
        registered.append_row(project.root, Row(
            built_on=built.built_on, person=built.person, orcid=built.orcid,
            bundle=built.bundle, token_sha256=token_sha256(built.token),
            state=built.state, items=str(built.items), file=_register_place(project, out),
        ))  # fmt: skip
        # Once the row is written it stays, if this fails: no answers match a page never sent.
        os.replace(part, out)
        return built.size
    except BundleError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"manuscript-guard: {out} or {REGISTER} could not be written ({exc}), so the page "
              f"for {shown} is not kept. Close whatever holds it open, and build again.",
              file=sys.stderr)  # fmt: skip
        return None
    finally:
        part.unlink(missing_ok=True)


def _checker_import(project, items, args) -> int:
    from manuscript_guard.checking.register import read_register
    from manuscript_guard.checking.store import AnswersError, read_answers, record

    if not args.answers:
        # Without this the missing flag reached `Path.read_text` on `None` and the author
        # got an AttributeError. A forgotten flag is not a bug in the project.
        print(
            "manuscript-guard: checker import needs the files the co-authors sent back: "
            "`checker import --answers answers-<name>.json [more.json ...]`",
            file=sys.stderr,
        )
        return 2
    register = read_register(project.root)
    # Every file is read, checked and held to the register before any is recorded: one refused
    # file leaves the record as it was, and the import can be run again without it.
    try:
        read = [read_answers(path, project_root=project.root, project=project,
                             register=register) for path in args.answers]  # fmt: skip
    except AnswersError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    counted, troubled = 0, False
    for answers in read:
        brought = record(project.root, answers, items)
        counted += len(brought.recorded)
        troubled = troubled or bool(brought.stale or brought.unknown or brought.refused)
        said = [] if brought.claimed is False else [
            "claimed: the file names no page in checks/bundles.csv, so the name is its word"]
        if answers.orcid_differs:
            said.append("ORCID differs from authors.yaml")
        elif brought.author is False:
            said.append("not an author in authors.yaml")
        marks = f" ({'; '.join(said)})" if said else " (from the page built for them)"
        print(f"{answers.path.name}: {len(brought.recorded)} decision(s) recorded for "
              f"{brought.by}{marks}")  # fmt: skip
        if brought.skipped:
            print(f"  {brought.skipped} answer(s) already recorded, not written again")
        for called, why in brought.stale:
            print(f"  recorded, counting for nothing: {called} — {why}; the note is kept")
        for called in brought.unknown:
            print(
                f"  recorded, counting for nothing: {called} — this project has no such item "
                f"now; a cited sentence edited since the page was built is a new item, to "
                f"send again"
            )
        for called, why in brought.refused:
            print(f"  not recorded: {called} — {why}")
    # As before: nothing that counts came in, and something was wrong with what did.
    return 1 if troubled and not counted else 0


def _checker_recap(project, items, args) -> int:
    """Write `checks/recap.md`, or with `--check` hold a recap to the record as it is now."""
    from manuscript_guard.checking import recap

    try:
        if args.check is not None:
            # A file named relative to the project, as every path in it is; an absolute
            # one stands as given.
            path = project.root / (recap.RECAP if args.check is True else args.check)
            code, said = recap.check(project, items, path)
            for line in said:
                print(line)
            return code
        made = recap.write(project, items)
    except recap.RecapError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    print(f"{project.root / recap.RECAP}: {len(items.items)} item(s), {made.head.rows} row(s) "
          f"of checks/decisions.csv, chain head {made.head.head}; root digest {made.root}")
    if made.earlier is not None and not made.earlier_holds:
        # Said and written into the recap, not refused: the recap is the record of it, and
        # `--check` against an earlier copy is what fails.
        print(f"  the earlier recap counted {made.earlier.rows} row(s) with chain head "
              f"{made.earlier.head}, and the record's first rows no longer give it: a row was "
              "edited, deleted or moved since")
    for flag in made.flags:
        print(f"  [{flag.status}] {flag.by} on {flag.title or flag.id}: {flag.note or '—'}")
    return 0


def _checker_status(project, items) -> int:
    from manuscript_guard.checking import status
    from manuscript_guard.checking.people import standing_of
    from manuscript_guard.checking.register import read_register

    standing = status(project.root, items)
    register = read_register(project.root)

    def claimed(decision) -> str:
        return "" if decision.bundle in register else " (claimed)"

    print(f"{len(items.items)} item(s); {standing.outstanding} nobody has answered")
    if standing.already:
        print(f"{standing.already} were already checked before this round")
    if standing.stale:
        print(
            f"{len(standing.stale)} answer(s) are about text that has changed since, so those "
            f"items are outstanding again:"
        )
        for decision in standing.stale:
            note = f": {decision.note}" if decision.note else ""
            print(f"  {decision.by}{claimed(decision)} on {decision.title or decision.id}{note}")
    if standing.earlier:
        print(
            f"{len(standing.earlier)} flag(s) on an earlier version of an item, given after the "
            f"same person's answer about this version; they count for nothing:"
        )
        for decision in standing.earlier:
            print(f"  [{decision.status}] {decision.by}{claimed(decision)} on "
                  f"{decision.title or decision.id}: {decision.note or '—'}")  # fmt: skip
    if standing.orphaned:
        print(
            f"{len(standing.orphaned)} answer(s) are about items this project no longer has; "
            f"they stay in the record and count for nothing:"
        )
        # By the person and the sentence: a cited sentence edited since it was answered is a new
        # item, and the old answer, named by its id, could not be traced to anyone or anything.
        for decision in standing.orphaned:
            print(f"  {decision.by}{claimed(decision)} on {decision.title or decision.id}")
    for person in standing.people:
        counts = standing.by_person[person]
        said = ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))
        number = sum(1 for d in standing.counting if d.by == person and d.bundle not in register)
        marks = [f"{number} claimed, from no page in checks/bundles.csv"] if number else []
        why = standing_of(project, person)
        marks += [why] if why else []
        print(f"  {person}: {said}" + (f" ({'; '.join(marks)})" if marks else ""))
    for decision in standing.wrong:
        print(f"  [{decision.status}] {decision.by}{claimed(decision)} on {decision.title}: "
              f"{decision.note or '—'}")  # fmt: skip
    for identifier, decisions in standing.disagreements:
        who = "; ".join(f"{d.by}{claimed(d)} says {d.status}" for d in decisions)
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
    from manuscript_guard.from_word import init_from_word, what_was_done

    word = args.from_docx
    if word is not None and args.latex:
        print("manuscript-guard init: --from writes a Word paper as a Markdown manuscript, "
              "and --latex starts a LaTeX one; nothing was made", file=sys.stderr)  # fmt: skip
        return 2
    converted = None
    try:
        if word is None:
            title = UNTITLED if args.title is None else args.title
            created = init_project(args.path, title=title, latex=args.latex,
                                   english=args.english)  # fmt: skip
        else:
            created, converted = init_from_word(args.path, word, title=args.title,
                                                english=args.english)  # fmt: skip
    except ContractError as exc:
        # A title read from the Word document that init does not take.
        read = word is not None and args.title is None and str(exc).startswith("the title")
        hint = "; give one with --title" if read else ""
        print(f"manuscript-guard init: {exc}{hint}", file=sys.stderr)
        return 2
    for path in created:
        print(f"created {path}")
    paper = (Path(args.path) / "paper.yaml").resolve()
    if args.english and paper not in {path.resolve() for path in created}:
        print(
            f"\npaper.yaml was already there and was left as it was, so english_variant: "
            f"{args.english} was not written into it: set it there"
        )
    if converted is not None:
        print("\n" + what_was_done(word, converted))
    rules = rules_to_add(args.path, latex=args.latex)
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


#: The commands, under the headings the top-level help lists them by, in that order. Every
#: command is in one group, but `hook`: an agent tool calls it and an author never does.
COMMAND_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Setup & Guide", ("init", "next", "set", "stages", "journal", "style", "install-skills")),
    (
        "Checking & Audit",
        (
            "check",
            "audit",
            "explain",
            "bind",
            "impact",
            "reworded",
            "methods",
            "checklist",
            "fetch",
            "transcribe",
        ),
    ),
    ("Analysis & Data",
     ("verify", "harvest", "values", "models", "dictionary", "palettes", "related")),  # fmt: skip
    ("Literature", ("lookup", "search", "sync-bib", "sync-sources", "passages")),
    ("Co-Authors & Review", ("review", "checker", "import", "respond", "approve", "sign")),
    ("Build, Release & Communicate",
     ("render", "build", "submit", "package", "deposit", "proof")),  # fmt: skip
)
HIDDEN_COMMANDS = frozenset({"hook"})


class _GroupedHelp(argparse.RawDescriptionHelpFormatter):
    """The top-level help, with the commands left out of argparse's own list.

    The usage line still names `<command>`; the commands themselves are listed under their
    groups by `_command_list`, in the epilog, which this formatter prints as written.
    """

    def add_arguments(self, actions) -> None:
        super().add_arguments(
            [action for action in actions if not isinstance(action, argparse._SubParsersAction)]
        )


def _command_list(commands: argparse._SubParsersAction) -> str:
    """Each group's heading, then each of its commands with its own one-line help."""
    helps = {choice.dest: choice.help or "" for choice in commands._choices_actions}
    width = max(shutil.get_terminal_size().columns - 2, 40)
    column = 4 + max(len(name) for _, names in COMMAND_GROUPS for name in names)
    blocks = []
    for heading, names in COMMAND_GROUPS:
        rows = [f"{heading}:"]
        for name in names:
            lines = textwrap.wrap(helps[name], max(width - column, 20)) or [""]
            rows.append(f"  {name:<{column - 2}}{lines[0]}")
            rows.extend(" " * column + line for line in lines[1:])
        blocks.append("\n".join(rows))
    blocks.append("Each command takes --help.")
    return "\n\n".join(blocks)


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
        formatter_class=_GroupedHelp,
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

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
        "supplements and the figures, and the analysis outputs to check them against. "
        "Without outputs no number is compared, and the rest is read: the numbers against "
        "each other, the words (G6, G14) and the reference list (G7).",
    )
    audit.add_argument(
        "paper", nargs="+", type=Path,
        help=".docx, .md or .tex files, or directories; a .tex is read with the files it "
        "inputs, and in a directory only a .tex with \\documentclass starts a paper",
    )  # fmt: skip
    audit.add_argument(
        "--against",
        nargs="+",
        type=Path,
        metavar="PATH",
        help="analysis outputs: .json, .csv, .tsv, .txt, .yaml, .yml, .md, or directories "
        "of them; anything else is named in the report as not read. Without it no number "
        "is compared with the analysis",
    )
    audit.add_argument(
        "--english",
        choices=("american", "british"),
        help="the paper's English, which G14 holds its spelling to; without it, the English "
        "most of its words are in",
    )
    audit.add_argument(
        "--submission-residue",
        action="store_true",
        help="G6 fails the residue of a revision that answers a reviewer or points at this "
        "manuscript, as check does at the submission stage, rather than warning of it",
    )
    audit.add_argument(
        "--lookup",
        action="store_true",
        help="ask Crossref and OpenAlex about each DOI of the reference list, DataCite and "
        "then doi.org about one Crossref has no record of, and PubMed about each PMID, "
        "whether the work was retracted, withdrawn or put under concern, or is not "
        "registered; nothing is sent without it",
    )
    audit.add_argument(
        "--dry-run",
        action="store_true",
        help="with --lookup, list what would be sent, and send nothing",
    )
    audit.add_argument(
        "--lookup-cache",
        type=Path,
        metavar="DIR",
        help="with --lookup, keep each answer in DIR and read it from there the next time; "
        "without it nothing is kept",
    )
    audit.add_argument(
        "--json", action="store_true", help="the report as JSON, in the shape check --json "
        "gives, each finding with its section and whether --strict counts it",
    )  # fmt: skip
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
        "--minimum-cell-count",
        type=int,
        metavar="N",
        help="the data custodian's minimum: a count held back that a total gives away is "
        "said where it is from 1 to below N; without it, any from 1",
    )
    audit.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if a number is in no output given, a paper, a figure or a stretch of "
        "one could not be read, no number was read, a table's total is not what its counts "
        "add up to, a characteristic's categories add up to more than their column's n, or "
        "a printed total gives away a count held back; nothing else is counted",
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
    verify.add_argument(
        "--receipt",
        metavar="SITE",
        help="at the site that holds the data: run each harvest entry naming SITE in a copy, "
        "and write receipts/SITE.receipt.json of what ran and what came out, by digest; "
        "refused where an output holds a count the custodian forbids",
    )
    verify.set_defaults(func=cmd_verify)

    harvest = sub.add_parser(
        "harvest",
        help="take in an output a script writes without the emitter (.csv, .tsv, .json) as "
        "results, by harvest.yaml; it runs nothing",
        description="With OUTPUT, adds an entry to harvest.yaml and harvests it; without, "
        "harvests every entry again. Each output is read as a table and written as "
        "results/<key>.json, its cells <key>.<row>.<column> and its table table.<key>, with "
        "the declared script and inputs as the emitter records them. Nothing is run, so "
        "`check` warns (harvest-declared) until `verify` re-runs the script and reads the "
        "same values, or a site's receipt covers it (docs/harvest.md).",
    )
    harvest.add_argument("output", nargs="?", help="the output file, from the project's root")
    harvest.add_argument("--script", help="the script that writes it")
    harvest.add_argument("--input", nargs="+", metavar="INPUT", help="the data it read")
    harvest.add_argument("--restricted", action="store_true",
                         help="the inputs given are restricted by the data custodian")
    harvest.add_argument("--synthetic", action="store_true",
                         help="the inputs given are synthetic, not the real data")
    harvest.add_argument("--key", help="the name its results go by: results/<key>.json")
    harvest.add_argument("--row-key", help="the column whose cells name the rows")
    harvest.add_argument("--columns", nargs="+", metavar="COLUMN",
                         help="the columns to take in, by header; all where absent")
    harvest.add_argument("--digits", type=int,
                         help="decimal places to show each number to; the output's own text "
                         "where absent")
    harvest.add_argument("--receipt", metavar="SITE",
                         help="the site that holds the data, whose receipt covers the output")
    harvest.add_argument("--not-quoted", action="store_true",
                         help="the table is working output, not placed in the manuscript")
    harvest.add_argument("--counts", nargs="+", metavar="COLUMN",
                         help="the columns whose cells are counts, held to the custodian's "
                         "minimum; every whole number where absent")
    harvest.add_argument(
        "--path", type=Path, default=Path.cwd(), help="the project (default: the one you are in)"
    )
    harvest.set_defaults(func=cmd_harvest)

    package = sub.add_parser(
        "package",
        help="write the package to deposit for reproducibility: the code, the results and "
        "what they ran with, never the data a custodian keeps",
        description="Writes build/package/<name>/ and its .zip: the analysis scripts, the "
        "results and their digests, the figure scripts and figures, the plan, the literature "
        "ledger, the lockfiles and the licence, with a README that says how to run it again "
        "and what `verify` checks, CITATION.cff, the results the paper binds (BOUND.md), the "
        "inputs and where each is (INPUTS.md), and every file's SHA-256. An input goes in "
        "only when it is declared synthetic or listed in paper.yaml's package.share; a "
        "restricted one never does. Refused while G1 fails, while a fragment holds a count "
        "below the custodian's minimum, and, where the custodian restricts sending, until "
        "they sign the package off. It uploads nothing. --citation, --ro-crate, "
        "--root-citation and --companion add a description of the package made from the "
        "records (docs/deposit.md).",
    )
    package.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    package.add_argument("--dry-run", action="store_true",
                         help="list what would go in and what would be left out, and write "
                         "nothing")  # fmt: skip
    package.add_argument("--with-manuscript", action="store_true",
                         help="add the manuscript's source; BOUND.md is there either way")
    package.add_argument("--skip-checks", action="store_true",
                         help="write it although G1 fails, and say so in MANIFEST.yaml")
    package.add_argument("--citation", action="store_true",
                         help="add .zenodo.json, the metadata of a Zenodo record of the "
                         "package, beside CITATION.cff")  # fmt: skip
    package.add_argument("--ro-crate", action="store_true",
                         help="describe the package as an RO-Crate 1.1 "
                         "(ro-crate-metadata.json), with only the relationships its files "
                         "show to hold, the rest in RELATIONS.md, and the model cards in "
                         "MODELS.md; implies --citation")  # fmt: skip
    package.add_argument("--root-citation", action="store_true",
                         help="also write CITATION.cff and .zenodo.json at the project's root, "
                         "each only where none is there; one there is never written over. "
                         "Implies --citation")  # fmt: skip
    package.add_argument("--companion", action="store_true",
                         help="add the companion page, ro-crate-preview.html, and its copy "
                         "index.html: one self-contained page of the paper's findings, the "
                         "evidence for each, its figures, methods, limitations and the "
                         "co-authors' checking, made from the records with pandoc; implies "
                         "--ro-crate")  # fmt: skip
    package.set_defaults(func=cmd_package)

    from manuscript_guard.deposit.bundles import BUNDLES, TARGETS

    deposit = sub.add_parser(
        "deposit",
        help="stage a bundle for Zenodo, OSF, arXiv, medRxiv or a GitHub Pages site in "
        "build/deposit/, with a deterministic archive, once the data custodian's checks pass; "
        "it sends nothing unless asked to reserve a Zenodo DOI, stage at Zenodo or OSF, or "
        "publish at Zenodo",
        description="Writes build/deposit/<target>-<bundle>/ and a .zip of it, or for arXiv "
        "a .tar.gz of the LaTeX source, and lists what went in and what stayed out. The data "
        "custodian's checks come first and stop it: a count below the minimum in the results "
        "it carries, or for a preprint in the manuscript; an input declared restricted that "
        "git tracks or that it would carry; and, where the custodian restricts sending, a "
        "bundle they have not signed off (DEPOSIT/custodian/<target>/<bundle>). A plan the "
        "first results were written from is no pre-registration, and goes only with "
        "--retrospective. A release and a preprint are refused while `check --stage submission` "
        "fails. Nothing is uploaded and nothing is pushed, unless --reserve-doi, --stage or "
        "--publish asks, with the host's token in the environment; --publish asks you at a "
        "terminal to type the DOI (docs/deposit.md).",
    )
    deposit.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    deposit.add_argument("--target", required=True, choices=TARGETS,
                         help="where the bundle is for")  # fmt: skip
    deposit.add_argument("--bundle", required=True, choices=BUNDLES,
                         help="what it holds: the analysis plan, the release of the package "
                         "and how it was checked, or the preprint")  # fmt: skip
    deposit.add_argument("--dry-run", action="store_true",
                         help="list what would go in and what would stay out, and write "
                         "nothing in build/deposit/")  # fmt: skip
    deposit.add_argument("--retrospective", metavar="WHY",
                         help="deposit a plan the first results were already written from, "
                         "labelled as deposited after them, with why it is deposited now")
    deposit.add_argument("--reserve-doi", action="store_true",
                         help="Zenodo: make a draft with its DOI reserved, recorded in "
                         "deposit/receipts/; for a release at Zenodo itself, write it into "
                         "paper.yaml as package.doi once you say yes (ZENODO_TOKEN, or "
                         "ZENODO_SANDBOX_TOKEN, in the environment)")  # fmt: skip
    deposit.add_argument("--stage", action="store_true",
                         help="stage the bundle and send it: to the Zenodo draft, or as a "
                         "private OSF project (OSF_TOKEN); each file's md5 is checked")
    deposit.add_argument("--publish", action="store_true",
                         help="Zenodo: publish the staged draft, only when the bundle is "
                         "unchanged since it was staged and you type its DOI at a terminal; "
                         "--yes does not answer that")  # fmt: skip
    deposit.add_argument("--yes", action="store_true",
                         help="with --reserve-doi, write package.doi without asking")
    deposit.set_defaults(func=cmd_deposit)

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
    journal.add_argument(
        "--page",
        metavar="FILE",
        help="with --reread: the page of its own a block of the profile names (its page_file, "
        "as the profile writes it) that FILE is read again in place of; without it, the "
        "instructions page",
    )
    journal.set_defaults(func=cmd_journal)

    set_ = sub.add_parser(
        "set",
        help="write one setting of paper.yaml (stage, target journal, English, reporting "
        "guidelines, study type), keeping its comments",
        description="Writes one key of paper.yaml and leaves every comment and every other "
        "line as it was: it replaces the value, or makes the commented example `# key: ...` "
        "the setting, or adds the key at the end. The file is read back before it is "
        "written, and refused, unchanged, where it would hold anything else.",
    )
    set_.add_argument("key", choices=PAPER_KEYS)
    set_.add_argument(
        "value",
        nargs="*",
        help="the value; for reporting_guideline each guideline, or none for an empty list",
    )
    set_.add_argument(
        "--path", type=Path, default=Path.cwd(), help="the project (default: the one you are in)"
    )
    set_.set_defaults(func=cmd_set)

    next_ = sub.add_parser(
        "next",
        help="say what to do now: the first thing to put right, or the choice that is due, "
        "with the skill and the exact command; writes nothing",
        description="Runs every gate once, as check does, and decides in a fixed order: what "
        "stops a gate, stale results, the plan, the choices due (journal, English, reporting "
        "guideline, study design), the numbers' sources, the other failures, the co-authors' "
        "checks, the warnings, the next stage, then the steps an author may take once nothing "
        "fails. Exits 0 whenever it has decided; check is the command whose exit says pass "
        "or fail.",
    )
    next_.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    next_.add_argument("--json", action="store_true",
                       help="the decision as JSON (schema manuscript-guard/next/1)")
    next_.add_argument("--all", action="store_true",
                       help="show every action in full, not the first three")
    next_.add_argument("--stage", choices=STAGES,
                       help="decide as at this stage; overrides `stage` in paper.yaml")
    next_.set_defaults(func=cmd_next)

    stages = sub.add_parser("stages", help="what each stage means and what binds at it")
    stages.set_defaults(func=cmd_stages)

    palettes_ = sub.add_parser(
        "palettes",
        help="list the palettes shipped, with what the colour check says of each, or show one",
    )
    palettes_.add_argument("--kind", choices=("qualitative", "sequential", "diverging",
                                              "multi-sequential", "cyclic"))  # fmt: skip
    palettes_.add_argument("--colours", type=int, help="how many colours the figure needs")
    palettes_.add_argument("--safe", action="store_true",
                           help="only those every reader can read for that use")  # fmt: skip
    palettes_.add_argument("--collection", help="e.g. MetBrewer, Crameri, ColorBrewer")
    palettes_.add_argument("--show", metavar="NAME", help="one palette's colours and licence")
    palettes_.add_argument("--json", action="store_true")
    palettes_.set_defaults(func=cmd_palettes)

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
    sign_.add_argument("--retrospective", metavar="WHY",
                       help="for a plan deposited after its first results "
                       "(DEPOSIT/custodian/<target>/preregistration): the reason `deposit` was "
                       "given, which its README holds")  # fmt: skip
    sign_.set_defaults(func=cmd_sign)

    explain = sub.add_parser("explain", help="show how each number in a file was classified")
    explain.add_argument("file", type=Path)
    explain.set_defaults(func=cmd_explain)

    proof = sub.add_parser(
        "proof",
        help="compare the publisher's proof with the document sent, and list the corrections",
        description="Reads the typeset proof (PDF, JATS XML, HTML or text) and holds it to "
        "the document in the submission pack, part by part and table cell by cell, and its "
        "title page to authors.yaml. A changed number, sign, decimal mark, unit, citation, "
        "reference, name, affiliation, ORCID iD or e-mail address, or a part the proof "
        "leaves out, is a correction; a copy-editor's change of words is shown for you to "
        "accept or query. Nothing is sent.",
    )
    proof.add_argument("proof", type=Path, help="the proof: .pdf, .xml, .html or .txt")
    proof.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    proof.add_argument(
        "--against", type=Path, metavar="DOCX",
        help="the document to compare with, where it is not the submission pack's",
    )  # fmt: skip
    proof.add_argument(
        "--supplementary", action="store_true",
        help="the proof is of the supplement, typeset as its own document",
    )  # fmt: skip
    proof.add_argument(
        "--out", type=Path, metavar="FILE",
        help="also write the corrections as a numbered list, to paste into the reply",
    )  # fmt: skip
    proof.add_argument("--json", action="store_true", help="the report as JSON")
    proof.set_defaults(func=cmd_proof)

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

    values = sub.add_parser(
        "values", help="write a LaTeX manuscript's values file, mgvalues.sty, from the results"
    )
    values.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    values.set_defaults(func=cmd_values)

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
        "--latex",
        action="store_true",
        help="a Markdown manuscript as LaTeX: the source pandoc writes, checked against the "
        "Markdown, in build/latex/submission/, and its PDF",
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
    lookup.add_argument(
        "--registrations",
        action="store_true",
        help="ask ClinicalTrials.gov, the EU PAS register, OSF or ISRCTN about each registration "
        "paper.yaml lists instead, and keep the answers in design/registrations/",
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

    dictionary = sub.add_parser(
        "dictionary",
        help="write the data dictionary out: REDCap's data dictionary, a plain CSV or the "
        "form's outline",
    )
    dictionary.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    dictionary.add_argument("--redcap", type=Path, help="REDCap's data dictionary, as CSV")
    dictionary.add_argument("--csv", type=Path, help="one row per variable, as CSV")
    dictionary.add_argument("--outline", type=Path, help="the form's outline, as Markdown")
    dictionary.set_defaults(func=cmd_dictionary)

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
    submit.add_argument(
        "--latex",
        action="store_true",
        help="pack a Markdown manuscript as LaTeX: the source in latex/ and its PDF",
    )
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
    checker.add_argument("verb", choices=["build", "import", "status", "recap"])
    checker.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    checker.add_argument("--for", dest="name", default="", help="build: who the file is for")
    checker.add_argument(
        "--all", dest="every", action="store_true",
        help="build: one page for each author in authors.yaml",
    )  # fmt: skip
    checker.add_argument(
        "--except", dest="leave_out", action="append", default=[], metavar="AUTHOR",
        help="build --all: leave this author out (again for more)",
    )  # fmt: skip
    checker.add_argument(
        "--to", default="",
        help="build: who they send the answers back to (the corresponding author unless given)",
    )  # fmt: skip
    checker.add_argument(
        "-o", "--output", type=Path,
        help="build: where to write the file, or with --all the folder for the files",
    )  # fmt: skip
    checker.add_argument("--title", help="build: what the page calls itself")
    checker.add_argument(
        "--answers", type=Path, nargs="+", help="import: the files the co-authors sent back"
    )
    checker.add_argument(
        "--items", type=Path,
        help="the items file, if not checks/items.json; a relative path is read from the "
        "working folder, where --check's is read under the project",
    )
    checker.add_argument(
        "--check", nargs="?", const=True, default=None, metavar="FILE",
        help="recap: make the recap in FILE (checks/recap.md unless given; a relative FILE "
        "is under the project) again from the record and the manuscript, and exit 1 at the "
        "first line that differs; name the project before --check",
    )  # fmt: skip
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
    init.add_argument(
        "--title", help=f"the paper's title; {UNTITLED!r} where none is given or read"
    )
    init.add_argument(
        "--latex",
        action="store_true",
        help="start the manuscript in LaTeX: manuscript/main.tex, with its values file",
    )
    init.add_argument(
        "--english",
        help=f"the English paper.yaml declares, whose spelling G14 holds the manuscript to: "
        f"{' or '.join(ENGLISHES)}. Without it none is declared, and G14 holds the paper to "
        "the one most of its words are in",
    )
    init.add_argument(
        "--from",
        dest="from_docx",
        type=Path,
        metavar="PAPER.docx",
        help="bring a paper written in Word into the project: its text as manuscript/main.md, "
        "each table a pipe table where it can be one, its pictures in manuscript/media/, and "
        "its title page set aside in a comment",
    )
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

    parser.epilog = _command_list(sub)
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


def _always(_args: argparse.Namespace) -> bool:
    return True


#: The commands that read the manuscript only as Markdown, and when an invocation reads it.
#: On a LaTeX manuscript each refuses with a sentence and exits 2 (DESIGN.md, "LaTeX
#: manuscripts", step 1): it read nothing of one, and said it found nothing, "rendered 0
#: files", "cites nothing", or read the `.tex` as Markdown. A command leaves this table in the
#: step that teaches it LaTeX.
_MARKDOWN_COMMANDS: dict[str, Callable[[argparse.Namespace], bool]] = {
    # `checker` draws its items from the manuscript for every verb, `import` and `status`
    # too, which match answers against them (round 2 of #404).
    **dict.fromkeys(
        ("checker", "impact", "import", "proof", "render", "reworded"),
        _always,
    ),
    # A round opened and checked reads a LaTeX manuscript (step 8); one seeded from a returned
    # .docx reads the Word copy a Markdown manuscript is built to.
    "respond": lambda args: args.source is not None,
    # `init --latex` sets up a LaTeX manuscript; without it, `main.md` would go beside one.
    "init": lambda args: not args.latex,
    # A design round reads the plan, not the manuscript (round 1 of #404).
    # A panel reads a LaTeX manuscript as the submission folder writes it (step 12); Word's
    # suggestions are a Markdown manuscript's.
    "review": lambda args: bool(args.suggestions),
}  # fmt: skip
#: The commands refused a `.tex` named whatever the project's format, since they read the
#: file given as Markdown; `impact` follows the records of any file, a header's included.
_READ_AS_MARKDOWN = frozenset({"reworded"})


def _named_paths(args: argparse.Namespace) -> list[Path]:
    """The files a command was given, by whichever of these names it takes them. A flag
    that shares the name, `review --files`, gives none (a list of `True` was read as one)."""
    found: list[Path] = []
    for name in ("file", "files", "paths", "paper"):
        value = getattr(args, name, None)
        values = value if isinstance(value, (list, tuple)) else [value]
        found += [Path(path) for path in values if isinstance(path, (str, Path))]
    return found


def _refused_for_latex(args: argparse.Namespace) -> str | None:
    """Why this command does not run here, where the manuscript, or a file it is given, is
    LaTeX; None where it runs."""
    command = args.command
    named = _named_paths(args)
    reads = _MARKDOWN_COMMANDS.get(command)
    if reads is None or not reads(args):
        return None
    typed = [path for path in named if path.suffix.lower() == ".tex"]
    if typed and command in _READ_AS_MARKDOWN:
        return (f"{command} does not read LaTeX yet: {typed[0]} is a LaTeX file; "
                "`manuscript-guard check` says what is read of a LaTeX manuscript")  # fmt: skip
    start = getattr(args, "path", None) or (named[0] if named else Path.cwd())
    start = start.parent if start.is_file() else start
    folder = _manuscript_folder(start, command)
    if folder is None or manuscript_format(folder) != LATEX:
        return None
    if command == "init":
        return (f"init writes a Markdown manuscript, and {folder / 'main.tex'} is a LaTeX "
                "one's; give --latex to set up a LaTeX project")  # fmt: skip
    return (f"{command} does not read a LaTeX manuscript yet, and {folder} holds one: "
            "`manuscript-guard check` says what is read of it")  # fmt: skip


def _manuscript_folder(start: Path, command: str) -> Path | None:
    """The manuscript folder of the project at `start`; for `init`, of the one it would make
    there. None where there is no project to read, which the command says itself."""
    if command == "init":
        return start / "manuscript"
    try:
        project, _ = load_project(start)
    except ContractError:
        return None
    return project.path("manuscript")


def main(argv: list[str] | None = None) -> int:
    from manuscript_guard.roundtrip import RoundTripError

    args = build_parser().parse_args(argv)
    _survive_the_console()
    refused = _refused_for_latex(args)
    if refused is not None:
        print(f"manuscript-guard: {refused}", file=sys.stderr)
        return 2
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
