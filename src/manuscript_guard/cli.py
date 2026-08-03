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
from manuscript_guard.scaffold import init_project
from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import substitute
from manuscript_guard.text.tokens import find_atoms


def _run_gates(start: Path, *, submission: bool = False) -> tuple[Report, object]:
    """Run every gate. `submission` raises the review gate's warnings to failures.

    Only G11 varies. An author mid-draft should be able to build a document to read; the
    version that goes to a journal should not carry unanswered major review findings.
    """
    project, contract_report = load_project(start)
    namespace, results, literature, load_report = load_namespace(project)

    reports = [contract_report, load_report]
    if contract_report.ok and load_report.ok:
        reports.append(check_review(project, submission=submission))
        reports.append(check_freshness(project, results))
        reports.append(check_numbers(project, namespace, results, literature))
        reports.append(check_figures(project, results))
        reports.append(check_figure_reviews(project, content_digest))
        reports.append(check_citations(project, literature))
        reports.append(check_literature_chain(project, literature))
        reports.append(check_journal(project))
        reports.append(check_reporting(project))
        reports.append(check_writing(project))
        reports.append(check_methods(project))
        reports.append(check_consistency(results))
    return merge_all(reports), project


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
    report, project = _run_gates(args.path, submission=args.submission)
    if args.json:
        print(report.to_json())
    else:
        print(f"manuscript-guard {__version__} — {project.root}")
        print(report.render(project.root))
        print(
            f"\n{len(report.failures)} failing, {len(report.warnings)} warning"
            f"{'' if len(report.warnings) == 1 else 's'}"
        )
    return 0 if report.ok else 1


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
        target.write_text(substitute(path.read_text(encoding="utf-8"), rendered), encoding="utf-8")
        count += 1
    print(f"rendered {count} file{'' if count == 1 else 's'} to {out_dir}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Produce the .docx. Gates run first unless the author insists otherwise.

    Building without checking is offered because an author mid-draft wants to see the
    document, not a list of unfinished bindings. It is a flag rather than the default,
    so that the version you send anyone has passed.
    """
    report, project = _run_gates(args.path, submission=args.submission)
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


def _recipe_paths(root: Path, name: str | None) -> list[Path]:
    directory = root / "profiles" / "reporting" / "recipes"
    paths = sorted(directory.glob("*.recipe.yaml"))
    if name:
        paths = [p for p in paths if p.name.split(".recipe")[0] == name]
    return paths


def cmd_fetch(args: argparse.Namespace) -> int:
    """Download a guideline's own checklist document, at the user's request.

    Deliberately not part of installation. This distributes nothing: it retrieves the
    document from the publisher for the person who asked, and prints the licence first so
    the terms are seen rather than buried.
    """
    import yaml

    from manuscript_guard.reporting import RecipeError, load_recipe
    from manuscript_guard.reporting.fetch import FetchError, fetch_document, licence_notice

    root = args.root or Path(__file__).resolve().parents[2]
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
                yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
            print("    recorded download_url in the recipe")

    return 1 if failed else 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Generate checklist profiles from official documents, via recipes."""
    from manuscript_guard.reporting import RecipeError, build_profile

    root = args.root or Path(__file__).resolve().parents[2]
    recipes_dir = root / "profiles" / "reporting" / "recipes"
    sources_dir = root / "profiles" / "reporting" / "sources"
    out_dir = root / "profiles" / "reporting"

    names = [args.guideline] if args.guideline else None
    recipes = sorted(recipes_dir.glob("*.recipe.yaml"))
    if names:
        recipes = [p for p in recipes if p.name.split(".recipe")[0] in names]
        if not recipes:
            print(f"no recipe for {args.guideline!r} in {recipes_dir}", file=sys.stderr)
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
        "--submission",
        action="store_true",
        help="hold the manuscript to submission standards: unanswered review findings fail",
    )
    check.set_defaults(func=cmd_check)

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
