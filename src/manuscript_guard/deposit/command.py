"""`manuscript-guard deposit`: stage a bundle for a target, locally, and send nothing.

The order is the point. The data custodian's checks run first (`preflight.first`), before
anything is built; a release and a preprint are then held to `check --stage submission`, as
`submit` holds what it packs, since both are public; the bundle is planned in
memory (`bundles.py`, `preprint.py`); a restricted input in it, a name two of its files
share, and, where the custodian restricts sending, a list of files and digests they have not
signed off, stop it (`preflight.last`); and only then is anything written, to
`build/deposit/<target>-<bundle>/` and its archive. `--dry-run` stops before the writing.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import WARN
from manuscript_guard.sign_offs import Signable

from . import preflight
from .archive import TAR, ZIP, stage, sums
from .bundles import (
    BUNDLES,
    TARGETS,
    Bundle,
    DepositError,
    name_taken,
    pair_refusal,
    retrospective_refusal,
)
from .plan import PackageError


def _carried(project: Project, results: Results, bundle: str) -> frozenset[str]:
    """The results files the bundle carries, or shows on its page: those the package holds,
    for a release; none of a plan or a preprint, which carry the manuscript's bound counts
    at most."""
    if bundle != "release":
        return frozenset()
    from .plan import withheld_results

    every = frozenset(f.path.relative_to(project.root).as_posix() for f in results.fragments)
    return every - withheld_results(project, results)


def _checked(root: Path) -> object:
    """`check --stage submission`'s report; a refusal while it fails."""
    from manuscript_guard.cli import _run_gates

    report, project, _stage, _deferred = _run_gates(root, submission=True)
    if not report.ok:
        print(report.render(project.root))
        raise DepositError(f"{len(report.failures)} failing in `check --stage submission`. What is "
                           "deposited is what others read and cite, so it is held to the "
                           "submission's bar and not staged while the check fails, as "
                           "`submit` refuses.")  # fmt: skip
    return report


def plan(project: Project, results: Results, target: str, bundle: str,
         retrospective: str | None) -> Bundle:  # fmt: skip
    """The bundle, planned and not written; `DepositError` where it cannot be made."""
    from . import bundles, preprint

    if bundle == "preregistration":
        made = bundles.preregistration(project, retrospective)
    elif bundle == "release":
        checked = _checked(project.root)
        made = bundles.gh_pages(project, results) if target == "gh-pages" else \
            bundles.release(project, results, checked)  # fmt: skip
    else:
        _checked(project.root)
        made = preprint.arxiv(project) if target == "arxiv" else preprint.medrxiv(project)
    return replace(made, target=target)


def deposit_signable(project: Project, results: Results, finding: str,
                     retrospective: str | None) -> Signable | None:  # fmt: skip
    """The bundle `DEPOSIT/custodian/<target>/<bundle>` names, as it stands, for the data
    custodian to sign off; None where the custodian does not restrict sending, or the id
    names no target and bundle that go together."""
    parts = finding.split("/")
    if len(parts) != 4 or parts[:2] != [preflight.GATE, "custodian"]:
        return None
    target, bundle = parts[2], parts[3]
    if target not in TARGETS or bundle not in BUNDLES or pair_refusal(target, bundle):
        return None
    refusal = retrospective_refusal(bundle, retrospective)
    if refusal is not None:
        raise DepositError(refusal, 2)
    made = plan(project, results, target, bundle, retrospective)
    return preflight.signable(project, target, bundle, made.entries, made.signed_as)


def listing(project: Project, made: Bundle, *, written: bool) -> str:
    suffix = TAR if made.tarred is not None else ZIP
    verb = "wrote" if written else "would write"
    lines = [f"manuscript-guard deposit --target {made.target} --bundle {made.bundle} "
             f"\N{EM DASH} {project.root}",
             f"{verb} build/deposit/{made.name}/ and {made.name}{suffix}", ""]  # fmt: skip
    width = max((len(entry.path) for entry in made.entries), default=0)
    lines += [f"  in   {entry.path.ljust(width)}  {entry.why}" for entry in made.entries]
    lines.append(f"  in   {'SHA256SUMS'.ljust(width)}  the SHA-256 of every other file")
    if made.tarred is not None:
        lines.append(f"  the archive holds the {len(made.tarred)} source files, and not the "
                     "sheet or SHA256SUMS")  # fmt: skip
    if made.withheld:
        lines.append("")
        lines += [f"  out  {held.path}  {held.why}" for held in made.withheld]
    lines += [f"  note {note}" for note in made.notes]
    return "\n".join(lines)


def next_steps(made: Bundle, directory: Path, archive: Path) -> str:
    """What the author does next, which the tool does not do."""
    head = "Nothing has been uploaded or pushed: the tool sends nothing in this version."
    if made.target == "gh-pages":
        # One command a line, which PowerShell and a POSIX shell both run: `||` is no operator
        # in Windows PowerShell 5.1 (round 2 of #460).
        site = "../companion-site"
        return "\n".join([
            head, "To publish the page from a branch of its own, run, in the repository, each "
            "line as a command of its own:",
            "  git fetch origin",
            f"  git worktree add {site} gh-pages",
            "where no gh-pages branch is there yet, here or on the remote, run these two in "
            "place of the last line:",
            f"  git worktree add --detach {site}",
            f"  git -C {site} switch --orphan gh-pages",
            "where gh-pages is checked out in another worktree already, `git worktree add` "
            f"refuses it: use that worktree, which `git worktree list` names, for {site} in "
            "what follows. Then:",
            f"  cp \"{directory / 'index.html'}\" {site}/",
            f"  cp \"{directory / '.nojekyll'}\" {site}/",
            f"  git -C {site} add index.html .nojekyll",
            f"  git -C {site} commit -m \"The companion page\"",
            f"  git -C {site} push origin gh-pages",
            "and have the repository's Pages settings publish the gh-pages branch.",
        ])  # fmt: skip
    if made.target == "arxiv":
        return (f"{head}\nUpload {archive.name} at arXiv, and fill its form from "
                "arxiv_submission_sheet.md.")  # fmt: skip
    if made.target == "medrxiv":
        return (f"{head}\nUpload the files of {directory.name}/ at medRxiv, and fill its form "
                "from medrxiv_submission_sheet.md.")  # fmt: skip
    where = {"zenodo": "Zenodo", "zenodo-sandbox": "Zenodo's sandbox", "osf": "OSF"}[made.target]
    return f"{head}\nUpload {archive.name}, or the files of {directory.name}/, to {where}."


def _refused(exc: DepositError) -> int:
    if str(exc):
        print(f"manuscript-guard deposit: {exc}", file=sys.stderr)
    return exc.status


def run(args: argparse.Namespace) -> int:
    from manuscript_guard.contracts import load_namespace, load_project

    refusal = pair_refusal(args.target, args.bundle) or retrospective_refusal(
        args.bundle, args.retrospective)  # fmt: skip
    if refusal is not None:
        print(f"manuscript-guard deposit: {refusal}", file=sys.stderr)
        return 2
    project, _ = load_project(args.path)
    _namespace, results, _literature, _ = load_namespace(project)
    first, _small = preflight.first(project, results, _carried(project, results, args.bundle),
                                    preprint=args.bundle == "preprint")  # fmt: skip
    if not first.ok:
        print(first.render(project.root))
        print("\nWhat the data custodian forbids comes first, and stands. Nothing is built "
              "and nothing is written.")  # fmt: skip
        return 1
    try:
        made = plan(project, results, args.target, args.bundle, args.retrospective)
    except DepositError as exc:
        return _refused(exc)
    every = (*made.entries, sums(made.entries))
    stopped, signable = preflight.last(project, results, args.target, args.bundle, made.entries,
                                       made.signed_as)  # fmt: skip
    # What the custodian's checks warned of is said with the rest: a count held back that a
    # table's total read from its label gives away does not refuse (Basile, 2026-10-29).
    warned = tuple(finding for finding in first.findings if finding.severity == WARN)
    report = made.report.merge(stopped).with_findings(*warned, *name_taken(every))
    if args.dry_run:
        # What would go is listed even where it is refused: it is what the custodian signs.
        print(listing(project, made, written=False))
    if report.findings:
        print(("\n" if args.dry_run else "") + report.render(project.root))
    if not report.ok:
        if args.bundle == "preregistration" and args.retrospective is not None \
                and signable is not None:  # fmt: skip
            print(f"\nThe data custodian signs it off with the same reason: `manuscript-guard "
                  f"sign --as <them> --finding {signable.id} --retrospective "
                  f"\"{args.retrospective}\"`.")  # fmt: skip
        print("\nThe bundle is not written.")
        return 1
    if args.dry_run:
        return 0
    try:
        staged = stage(project, made.name, every, tarred=made.tarred)
    except (PackageError, OSError) as exc:  # a copy that changed, or a write refused
        print(f"manuscript-guard deposit: the bundle is not written: {exc}", file=sys.stderr)
        return 2
    print(listing(project, made, written=True))
    print(f"\nbundle:  {staged.directory}\narchive: {staged.archive}\n")
    print(next_steps(made, staged.directory, staged.archive))
    return 0


__all__ = ["deposit_signable", "listing", "plan", "run"]
