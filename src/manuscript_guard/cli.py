"""Command line entry point.

Exit codes are part of the contract, because hooks and CI read them:
    0  every gate passed
    1  at least one gate failed
    2  the check could not be run at all
"""

from __future__ import annotations

import argparse
import sys
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
    rows = []
    for atom in find_atoms(text, mask(text)):
        verdict = classifier.classify(atom)
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

    mode = OFFLINE if args.offline else LIVE
    try:
        result = build_document(
            project, assembled, mode=mode, csl=args.csl, output=args.output
        )
    except BuildError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    print(f"built {result.output} ({result.mode})")
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
            document = build_document(project, assembled, mode=mode, csl=args.csl).output
        except BuildError as exc:
            print(f"manuscript-guard: {exc}", file=sys.stderr)
            return 2

    try:
        pack = assemble_pack(project, document)
    except SubmissionError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    print(f"submission pack: {pack.directory}")
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
    review.add_argument("--submission", action="store_true")
    review.set_defaults(func=cmd_review)

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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ContractError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
