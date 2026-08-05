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
from datetime import date
from pathlib import Path

from manuscript_guard import __version__
from manuscript_guard.build import LIVE, OFFLINE, BuildError, assemble, build_document
from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts import ContractError, load_namespace, load_project
from manuscript_guard.findings import Report, merge_all
from manuscript_guard.gates import (
    check_citations,
    check_consistency,
    check_design,
    check_figure_reviews,
    check_figures,
    check_freshness,
    check_journal,
    check_literature_chain,
    check_methods,
    check_numbers,
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
from manuscript_guard.policy import (
    DESCRIPTIONS,
    STAGES,
    SUBMISSION,
    apply_stage,
    resolve_stage,
    summarise_deferred,
)
from manuscript_guard.scaffold import init_project
from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import substitute
from manuscript_guard.text.sections import chain_at, heading_index
from manuscript_guard.text.tokens import find_atoms


def _run_gates(
    start: Path, *, submission: bool = False, stage: str | None = None
) -> tuple[Report, object, str, dict]:
    """Run every gate, then apply the stage policy.

    Every gate always runs. What the stage changes is which findings *fail*: someone still
    writing the analysis is told about the unreviewed figures, but not stopped by them.
    Nothing is skipped, and the caller reports what was deferred.

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
    """
    project, contract_report = load_project(start)
    namespace, results, literature, load_report = load_namespace(project)

    chosen = resolve_stage(project, stage, submission)
    at_submission = chosen == SUBMISSION

    reports = [contract_report, load_report]
    for name, gate in (
        ("G11", lambda: check_review(project, submission=at_submission)),
        ("G1", lambda: check_freshness(project, results)),
        ("G2", lambda: check_numbers(project, namespace, results, literature)),
        ("G3", lambda: check_figures(project, results)),
        ("G10", lambda: check_figure_reviews(project, content_digest)),
        ("G7", lambda: check_citations(project, literature)),
        ("G5", lambda: check_literature_chain(project, literature)),
        ("G4", lambda: check_journal(project)),
        ("G8r", lambda: check_reporting(project)),
        ("G6", lambda: check_writing(project)),
        ("G9", lambda: check_methods(project)),
        ("G12", lambda: check_design(project)),
        ("G8", lambda: check_consistency(results)),
        ("G13", lambda: check_revision(project, submission=at_submission)),
    ):
        reports.append(_guarded(name, gate))

    report, deferred = apply_stage(merge_all(reports), chosen)
    return report, project, chosen, deferred


def _guarded(name: str, gate) -> Report:
    """Run one gate; turn a crash into a finding rather than a silent absence.

    A gate that raised used to take the whole set down with it. Reporting the crash keeps
    the promise that every gate runs — and `gate-errored` is in no stage's deferral list,
    so it fails everywhere. A checker that could not check is not a pass.
    """
    from manuscript_guard.findings import Finding

    try:
        return gate()
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


def cmd_review(args: argparse.Namespace) -> int:
    """Show where the review stands, and the digest a review record must carry."""
    project, _ = load_project(args.path)
    digest = manuscript_digest(project)
    if args.digest:
        print(digest)
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
        for number, path in found:
            print(f"  round {number}: {path.name}")
    report = check_review(project, submission=args.submission)
    print(report.render(project.root))
    return 0 if report.ok else 1



def cmd_bind(args: argparse.Namespace) -> int:
    """Show every unbound number and what would give it a source.

    `check` says a number is unbound; the annotated copy colours it red. Neither says what
    to type next, and usually the answer is that the number is already in `results/` and was
    typed instead of bound. That case is detected and offered as a replacement.
    """
    from manuscript_guard.binding import apply, routes, unbound

    project, _ = load_project(args.path)
    namespace, _results, _literature, _ = load_namespace(project)
    items = unbound(project, namespace)

    if not items:
        print("every number in the manuscript is accounted for.")
        return 0

    if args.apply:
        replaced, remaining = apply(items)
        print(f"replaced {replaced} literal(s) with the binding they match.")
        if remaining:
            print(f"{len(remaining)} left, which need a decision:\n")
        items = remaining
        if not items:
            print("Re-run `manuscript-guard check` to confirm.")
            return 0

    for item in items:
        where = item.path.relative_to(project.root).as_posix()
        print(f"\n{where}:{item.line}  {item.text!r}")
        for route in routes(item):
            print(f"    {route}")
        print(f"    hint: {item.hint}")

    certain = sum(1 for item in items if item.certain)
    if certain and not args.apply:
        print(
            f"\n{certain} of {len(items)} match exactly one published value. "
            f"`manuscript-guard bind --apply` replaces those and leaves the rest."
        )
    return 1




def _unexamined(document: Path, identified: int) -> str:
    """How much of the returned document this command could not look at.

    Import compares paragraphs that carry an identifier. Table cells, headings, captions and
    any paragraph the co-author newly wrote carry none, so an edit to one is not merged, not
    refused, and not reported - it simply does not exist as far as the tool is concerned.
    A co-author who corrects a number in a table has every reason to believe it landed.
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
        f"not compared: table cells, headings, captions, and anything newly written. An "
        f"edit to one of those is not reported here."
    )


def _crossed_files(known: dict, order: list[str]) -> list[str]:
    """Identifiers that came back sitting among a different file's paragraphs.

    `_reorder` groups by the *original* file, so a paragraph cut from one file and pasted
    into another was silently repositioned inside the file it came from and never applied
    to the file it went to. The docstring promised it would be "left alone and reported";
    it was neither.
    """
    present = [name for name in order if name in known]
    crossed = []
    for position, name in enumerate(present):
        home = known[name][0]
        neighbours = [
            known[other][0]
            for other in present[max(0, position - 1) : position + 2]
            if other != name
        ]
        if neighbours and home not in neighbours:
            crossed.append(name)
    return crossed


def _reorder(project, known: dict, order: list[str]) -> None:
    """Put the source paragraphs back in the order the returned document has them.

    Per file, and only among the paragraphs that moved: the text is taken from disk, never
    from Word, so a paragraph full of bindings survives a move intact. A paragraph that
    moved between files is left alone and reported, because splicing across files is a
    different operation from reordering within one.
    """
    from pathlib import Path as _Path

    by_file: dict[_Path, list[str]] = {}
    for name in order:
        if name in known:
            by_file.setdefault(known[name][0], []).append(name)

    for path, names in by_file.items():
        text = path.read_text(encoding="utf-8")
        # Only the paragraphs that actually reached the document. A source paragraph that
        # renders to nothing - an HTML comment, for instance - has no bookmark to come
        # back, and counting it made every reorder look like a paragraph leaving the file.
        present = set(names)
        mine = [n for n in known if known[n][0] == path and n in present]
        wanted = [n for n in names if n in set(mine)]
        if len(wanted) != len(mine):
            continue  # a paragraph left this file; not a reordering
        blocks = [known[n][1] for n in wanted]
        # Right to left, at the offsets the identifiers carry, so an earlier splice cannot
        # move a later one and a repeated paragraph cannot be confused for its twin.
        for name, replacement in sorted(
            zip(mine, blocks, strict=True), key=lambda pair: known[pair[0]][2], reverse=True
        ):
            _p, para, start = known[name]
            text = text[:start] + replacement + text[start + len(para) :]
        path.write_text(text, encoding="utf-8", newline="\n")


def cmd_import(args: argparse.Namespace) -> int:
    """Bring a co-author's edits back from Word, without losing the bindings.

    Everything is keyed on the invisible identifier each paragraph carries, so "which
    paragraph is this" is an exact question. That makes moves and wording changes orthogonal:
    a paragraph can be reordered, reworded, or both, and each is handled on its own terms.
    """
    import tempfile

    from manuscript_guard.build.document import pandoc as _pandoc
    from manuscript_guard.gates.review import document_digest
    from manuscript_guard.roundtrip import (
        RoundTripError,
        comments_in,
        moves,
        paragraph_order,
        paragraph_text,
        realign,
        stamp_of,
        tagged_paragraphs,
    )

    _ = _pandoc
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

    if carried is None:
        print(
            f"{edited.name} carries no record of the source it was built from, so there is "
            f"no way to tell which text these edits were made against. Only a document this "
            f"tool built can be imported."
        )
        return 1
    if carried != document_digest(project) and not args.force:
        print(
            f"{edited.name} was built from a different version of the manuscript than the "
            f"one on disk. Merging edits made against text that has since changed is how a "
            f"correction lands on the wrong sentence.\n"
            f"  Resolve it by hand, or re-send the co-author a current build.\n"
            f"  --force imports anyway, and you will have to check every hunk."
        )
        return 1

    namespace, results, _literature, _r = load_namespace(project)
    assembled, _ar = assemble(project, namespace, results)

    with tempfile.TemporaryDirectory() as scratch:
        reference = Path(scratch) / "reference.docx"
        build_document(project, assembled, mode=OFFLINE, output=reference)
        rendered = paragraph_text(reference)
        original_order = paragraph_order(reference)

    returned = paragraph_text(edited)
    known = tagged_paragraphs(project)
    comments = comments_in(edited)

    # A move needs no content from Word - the text is already on disk - so it is safe even
    # for a paragraph solid with bindings, and it is handled separately from any rewording.
    moved = moves([n for n in original_order if n in returned], paragraph_order(edited))

    merged, refused, gone = [], [], []
    for name, source in known.items():
        was, now = rendered.get(name), returned.get(name)
        if was is None:
            continue
        if now is None:
            gone.append((name, source[1]))
            continue
        if re.sub(r"\s+", " ", was).strip() == re.sub(r"\s+", " ", now).strip():
            continue
        rebuilt = realign(source[1], was, now)
        (merged if rebuilt else refused).append((name, source, was, now, rebuilt))

    # Only paragraphs carrying an identifier are compared at all. Everything else - table
    # cells, headings, captions, the reference list, and anything the co-author newly wrote
    # - is invisible to this command, and saying nothing about that let a co-author believe
    # they had corrected a table when the correction went nowhere.
    unexamined = _unexamined(edited, len(returned))

    if not (moved or merged or refused or gone or comments):
        print("nothing came back: the document matches the manuscript on disk.")
        if unexamined:
            print(f"  {unexamined}")
        return 0

    crossed = set(_crossed_files(known, paragraph_order(edited)))
    moved = [entry for entry in moved if entry[0] not in crossed]
    if crossed:
        print(f"{len(crossed)} paragraph(s) were moved into a different file:")
        for name in sorted(crossed):
            print(f"    {known[name][1].strip()[:80]}")
        print(
            "    Not applied. Moving a paragraph between files is a different operation "
            "from reordering within one; do it in the .md yourself."
        )

    if moved:
        print(f"{len(moved)} paragraph(s) came back in a different place:")
        for name, was_at, now_at in moved:
            print(f"    position {was_at} -> {now_at}: {known[name][1].strip()[:80]}")

    verb = "merging" if args.apply else "would merge"
    for _name, source, _was, now, _rebuilt in merged:
        where = source[0].relative_to(project.root).as_posix()
        print(f"\n{verb} into {where}:")
        print(f"    + {now.strip()[:150]}")

    for _name, _source, _was, now, _rebuilt in refused:
        print("\nNOT merged:")
        print(f"    + {now.strip()[:150]}")
        print(
            "    a number or a citation in this paragraph changed. Those come from the "
            "analysis and the ledger; change them there, not in the document."
        )

    for _name, text in gone:
        print(f"\ndeleted in Word, left in place here: {text.strip()[:110]}")
        print("    delete it in the .md yourself if that was intended.")

    if args.apply:
        if moved:
            _reorder(project, known, paragraph_order(edited))
            print(f"\nreordered {len(moved)} paragraph(s) in the manuscript source.")
        # By offset, never by text. `text.replace(original, rebuilt, 1)` rewrote the
        # *first* paragraph reading that way, and a limitation restated in the Abstract and
        # the Discussion is ordinary in a paper - so an edit to the Discussion copy silently
        # rewrote the Abstract and left the Discussion alone. Two corruptions, nothing
        # reported, after the identifier had been established precisely to avoid guessing.
        # Spliced at the offset the identifier carries, never by searching for the text.
        # `text.replace(original, rebuilt, 1)` rewrote the *first* paragraph reading that
        # way, so an edit to a sentence restated later in the paper corrupted the earlier
        # copy and left the edited one alone - with nothing reported either time.
        by_path: dict[Path, list[tuple[int, int, str]]] = {}
        for _name, source, _was, _now, rebuilt in merged:
            path, original, start = source
            by_path.setdefault(path, []).append((start, start + len(original), rebuilt))
        for path, spans in by_path.items():
            text = path.read_text(encoding="utf-8")
            for start, end, rebuilt in sorted(spans, reverse=True):
                text = text[:start] + rebuilt + text[end:]
            path.write_text(text, encoding="utf-8", newline="\n")
        if merged:
            print(f"merged {len(merged)} reworded paragraph(s), bindings intact.")

    for comment in comments:
        print(f"\ncomment from {comment.author} ({comment.date}): {comment.text[:200]}")
    if comments:
        print(
            f"\n{len(comments)} comment(s). Record them in a review file so G11 can see they "
            f"were answered: write them into review/round-<n>/<reviewer>.yaml."
        )

    if unexamined:
        print(f"\n{unexamined}")

    if not args.apply and (moved or merged):
        print(f"\n`manuscript-guard import {edited} --apply` applies the safe changes.")

    # Comments alone are not a failure. Exit 1 meant a hook or a CI step keyed on the code
    # reported a problem when a co-author had done nothing but leave notes.
    outstanding = bool(refused or gone) or (not args.apply and (moved or merged))
    return 1 if outstanding else 0




def _seeded(source: Path) -> list[dict]:
    """Reviewers and their points, read from the comments in a returned document.

    A journal usually sends a PDF or an email and the points get typed in, which is where
    a point quietly becomes the easier point next to it. When the reviewer commented in a
    document this tool built, their words and the place they were about are both already in
    the file - and losing either on the way in is work the author redoes by hand.
    """
    from manuscript_guard.roundtrip import comments_in

    # Grouped by the slug, not the raw author. "Reviewer 2" and "REVIEWER 2" are two
    # buckets and one id, which put two people's points under one heading in the letter that
    # goes to the journal.
    by_author: dict[str, list[dict]] = {}
    for comment in comments_in(source):
        slug = re.sub(r"[^a-z0-9]+", "-", comment.author.lower()).strip("-")
        by_author.setdefault(slug or "reviewer", []).append(
            {
                "id": "",
                "comment": comment.text,
                "response": "",
                **({"where": comment.where} if comment.where else {}),
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
            from manuscript_guard.roundtrip import stamp_of

            carried = stamp_of(args.source)
            if carried is None or (carried != document_digest(project) and not args.force):
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
            "reviewers": _seeded(args.source) if args.source else [
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
        if args.source:
            seeded = sum(len(r["points"]) for r in document["reviewers"])
            anchored = sum(
                1 for r in document["reviewers"] for p in r["points"] if p.get("where")
            )
            print(
                f"  {seeded} point(s) read from {args.source.name}, {anchored} of them "
                f"knowing which paragraph they are about."
            )
        print(
            "  submitted_files records the manuscript as it stands now, which is what a\n"
            "  claimed revision is checked against. Open the round *before* you start\n"
            "  revising, or there is no baseline to compare with."
        )
        return 0

    found = rounds(project)
    if not found:
        print("no revision rounds. `manuscript-guard respond --open` starts one.")
        return 1

    lines = ["# Response to reviewers", ""]
    for number, path in found:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        lines += [f"## Round {number} — {document.get('journal', '')}".rstrip(), ""]
        lines += [
            "We thank the reviewers for their comments. Each point is answered below, with "
            "what changed in the manuscript.",
            "",
        ]
        for reviewer in document.get("reviewers", []):
            lines += [f"### {reviewer['id'].replace('-', ' ').title()}", ""]
            for point in reviewer.get("points", []):
                lines += [f"**{point['id']}.** {point['comment'].strip()}", ""]
                response = str(point.get("response", "")).strip()
                lines += [response or "_No response recorded._", ""]
                rebutted = str(point.get("rebutted", "")).strip()
                if rebutted:
                    lines += [f"We have not made this change: {rebutted}", ""]
                for entry in point.get("changed") or []:
                    note = f" — {entry['note']}" if entry.get("note") else ""
                    lines += [f"- Changed: {entry['kind']} `{entry['name']}`{note}"]
                if point.get("changed"):
                    lines.append("")

    output = project.path("build") / "response-to-reviewers.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {output.relative_to(project.root).as_posix()}")

    report = check_revision(project, submission=args.submission)
    print(report.render(project.root))
    return 0 if report.ok else 1


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

    papers = expand(args.paper, PAPER_SUFFIXES)
    figures = expand(args.figures or [], FIGURE_SUFFIXES)
    if not papers and not figures:
        print("nothing to audit: no .docx or .md found in what you gave me", file=sys.stderr)
        return 2
    if not args.against:
        print("--against is required: point it at the analysis outputs", file=sys.stderr)
        return 2

    report = audit(papers, args.against, figures=figures)
    print(render(report, measure_discrimination(report.backing_values), Path.cwd()))
    return 1 if (report.unmatched and args.strict) else 0


def cmd_journal(args: argparse.Namespace) -> int:
    """Show the journal profiles available, or copy the annotated template into a project."""
    from manuscript_guard.gates.journal import available_profiles
    from manuscript_guard.paths import SHIPPED_JOURNALS

    project, contract_report = load_project(args.path)
    if not contract_report.ok:
        print(contract_report.render(project.root))
        return 2

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


def cmd_explain(args: argparse.Namespace) -> int:
    """Show how every numeric atom in a file was classified.

    The gate is only trustworthy if its reasoning can be inspected, and an author arguing
    with a finding needs to see which rule fired rather than guess.
    """
    project, _ = load_project(args.file.parent)
    classifier = Classifier.load(project.extra_conventions, project.extra_terms)
    text = args.file.read_text(encoding="utf-8")
    # The same section chain G2 uses. Without it every `methods_only` rule fired everywhere,
    # so `explain` reported a fabricated `p < 0.001` in the Results as a recognised
    # convention while `check` failed it — and this is the command an author reaches for
    # when a finding surprises them. Its answer was the input to deciding whether to add a
    # `conventions:` exemption, which is the one mechanism that makes G2 vacuous.
    headings = heading_index(text)
    rows = []
    for atom in find_atoms(text, mask(text)):
        verdict = classifier.classify(atom, chain_at(headings, atom.start))
        rows.append((atom.line, atom.text, verdict.kind, verdict.rule or "-"))
    if not rows:
        print("no numeric atoms outside masked regions")
        return 0
    width = max(len(r[1]) for r in rows)
    for line, atom_text, kind, rule in rows:
        marker = "FAIL" if kind == UNCLASSIFIED else "ok  "
        print(f"{marker} {line:>5}  {atom_text:<{width}}  {kind:<12} {rule}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    """Substitute bindings into build/, without producing a document yet."""
    project, _ = load_project(args.path)
    namespace, _results, _literature, load_report = load_namespace(project)
    if not load_report.ok:
        print(load_report.render(project.root))
        return 2

    rendered = {ref: value.display for ref, value in namespace.items()}
    out_dir = project.path("build") / "rendered"
    out_dir.mkdir(parents=True, exist_ok=True)
    manuscript_dir = project.path("manuscript")
    count = 0
    for path in source_files(manuscript_dir):
        target = out_dir / path.relative_to(manuscript_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            substitute(path.read_text(encoding="utf-8"), rendered),
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

    classifier = Classifier.load(project.extra_conventions, project.extra_terms)
    counter = [0]
    marked: list[Assembled] = []
    marks = []
    for item in assembled:
        source = item.path.read_text(encoding="utf-8") if item.path.exists() else item.text
        text, found = annotate(
            source, namespace, classifier, counter=counter, results=results, project=project
        )
        marked.append(Assembled(path=item.path, text=text))
        marks.extend(found)

    build_dir = project.path("build")
    reference = styled_reference(pandoc(), build_dir / ".cache" / "annotated-reference.docx")
    result = build_document(
        project,
        marked,
        mode=OFFLINE if args.offline else LIVE,
        output=build_dir / "manuscript.annotated.docx",
        reference_doc=reference,
        prologue=legend() + "\n\n",
        epilogue=appendix(marks) + figure_sheet(project, results),
    )
    added = finish(result.output, marks)
    print(result.report.render(project.root))
    tiers: dict[str, int] = {}
    for mark in marks:
        tiers[mark.tier] = tiers.get(mark.tier, 0) + 1
    print(f"wrote {result.output}")
    print("  " + "  ".join(f"{tier}: {count}" for tier, count in sorted(tiers.items())))
    print(f"  {added} number(s) carry a hover showing where they came from")
    if tiers.get("defect"):
        print("  red marks a number bound to nothing. Yellow is not a verification.")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Produce the .docx. Gates run first unless the author insists otherwise.

    Building without checking is offered because an author mid-draft wants to see the
    document, not a list of unfinished bindings. It is a flag rather than the default,
    so that the version you send anyone has passed.
    """
    report, project, _stage, _deferred = _run_gates(
        args.path, submission=args.submission, stage=getattr(args, "stage", None)
    )
    if not report.ok and not args.skip_checks:
        print(report.render(project.root))
        print(f"\n{len(report.failures)} failing; not building. Use --skip-checks to override.")
        return 1

    namespace, results, _literature, _ = load_namespace(project)
    assembled, assemble_report = assemble(project, namespace, results)
    if not assemble_report.ok:
        print(assemble_report.render(project.root))
        return 1

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

    try:
        result = build_document(project, assembled, mode=mode, csl=args.csl, output=output)
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
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    """Assemble everything a journal asks for, once the submission check passes."""
    from manuscript_guard.build import SubmissionError, assemble_pack

    report, project, _stage, _deferred = _run_gates(args.path, submission=True)
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

    document = args.document
    if document is None:
        mode = OFFLINE if args.offline else LIVE
        try:
            built = build_document(project, assembled, mode=mode, csl=args.csl)
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

    try:
        pack = assemble_pack(project, document, checked=report.ok)
    except SubmissionError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    print(f"submission pack: {pack.directory}")
    if not report.ok:
        print(f"  assembled with --skip-checks; {pack.manifest.name} records that.")
    for path in pack.files:
        print(f"  {path.relative_to(pack.directory)}")
    print(f"  {pack.manifest.name}")
    print("\nStill to write by hand: the covering letter. No file in the project holds it.")
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


def cmd_methods(args: argparse.Namespace) -> int:
    """Report or record the state of the Methods against the analysis."""
    project, _ = load_project(args.path)
    if not args.reconcile:
        report = check_methods(project)
        print(report.render(project.root))
        return 0 if report.ok else 1

    path, count = reconcile(project)
    print(f"recorded {count} analysis file(s) in {path}")
    print("This says the Methods have been read against the code as it now stands.")
    return 0


def _recipe_paths(workspace: Path, name: str | None) -> list[Path]:
    """Recipes shipped with the package, plus any the project has written itself.

    A project's own recipe wins, the way its own journal and checklist profiles already do:
    a guideline can be revised, or extended locally, without waiting for a release.
    """
    from manuscript_guard.paths import SHIPPED_RECIPES

    by_name: dict[str, Path] = {}
    for directory in (SHIPPED_RECIPES, workspace / "profiles" / "reporting" / "recipes"):
        if directory.exists():
            for path in sorted(directory.glob("*.recipe.yaml")):
                by_name[path.name.split(".recipe")[0]] = path
    if name:
        return [by_name[name]] if name in by_name else []
    return [by_name[key] for key in sorted(by_name)]


def cmd_fetch(args: argparse.Namespace) -> int:
    """Download a guideline's own checklist document, at the user's request.

    Deliberately not part of installation. This distributes nothing: it retrieves the
    document from the publisher for the person who asked, and prints the licence first so
    the terms are seen rather than buried.
    """
    import yaml

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
            document = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
            document.setdefault("meta", {})["download_url"] = args.url
            recipe_path.write_text(
                yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
                newline="\n",
            )
            print("    recorded download_url in the recipe")

    return 1 if failed else 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Generate checklist profiles from official documents, via recipes."""
    from manuscript_guard.paths import workspace as find_workspace
    from manuscript_guard.reporting import RecipeError, build_profile

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
        except (RecipeError, FileNotFoundError) as exc:
            failed += 1
            print(f"  {recipe.name}: {exc}")
            continue
        note = ""
        if unverified:
            note = f"  [{len(unverified)} NOT VERBATIM: {', '.join(unverified[:6])}]"
            failed += 1
        print(f"  {path.name}: {count} items{note}")
    return 1 if failed else 0


def cmd_init(args: argparse.Namespace) -> int:
    created = init_project(args.path, title=args.title)
    for path in created:
        print(f"created {path}")
    print("\nnext: describe your authors in authors.yaml, then write an analysis that calls emit()")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
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
        help="analysis outputs: .json, .csv, .tsv, .txt, or directories of them",
    )
    audit.add_argument(
        "--figures", nargs="+", type=Path, help="SVG or PDF figures to audit as well"
    )
    audit.add_argument("--strict", action="store_true", help="exit 1 if anything is unmatched")
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

    explain = sub.add_parser("explain", help="show how each number in a file was classified")
    explain.add_argument("file", type=Path)
    explain.set_defaults(func=cmd_explain)

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
    build.add_argument("--csl", type=Path, help="citation style, for offline builds")
    build.add_argument("-o", "--output", type=Path)
    build.add_argument("--skip-checks", action="store_true", help="build even if gates fail")
    build.add_argument("--stage", choices=STAGES, help="how far along you are")
    build.add_argument(
        "--submission",
        action="store_true",
        help="the version you send anywhere: unanswered review findings fail the build",
    )
    build.set_defaults(func=cmd_build)

    syncbib = sub.add_parser("sync-bib", help="rewrite references.bib from Zotero")
    syncbib.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    syncbib.set_defaults(func=cmd_sync_bib)

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
    submit.set_defaults(func=cmd_submit)

    methods = sub.add_parser("methods", help="check or record Methods-to-code reconciliation")
    methods.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    methods.add_argument(
        "--reconcile",
        action="store_true",
        help="record the analysis as it stands, after reading the Methods against it",
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
        " ": " ",
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
    args = build_parser().parse_args(argv)
    _survive_the_console()
    try:
        return int(args.func(args))
    except ContractError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
