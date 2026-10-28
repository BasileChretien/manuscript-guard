"""What the data custodian forbids, asked of a deposit before anything of it is written.

`deposit` sends a bundle somewhere the custodian may never have agreed to, so it asks first,
whatever the bundle and wherever it goes (`first`):

- every count below the custodian's minimum in the results files the bundle carries, as
  `package` reads them (`counts.settled_small_counts`), which the data custodian may sign
  off as `PACKAGE/custodian/small-counts`;
- for a preprint, every count the manuscript binds below the minimum, as G2 reads them
  (`count-below-minimum`): a preprint prints the manuscript;
- every input declared restricted that git tracks (`restricted-input-tracked`), a copy of the
  data outside the custodian's hands already;
- every masked count a reader could work out from the rest of the results files carried
  (`gates.custodian.recoverable_cells`, which finds nothing until Task 3 writes it).

Then, once the bundle is planned (`last`): no file of it is an input declared restricted, by
its name or by the file it is, and, where the custodian restricts sending, they have signed
off the bundle's list of files and their digests as it stands,
`DEPOSIT/custodian/<target>/<bundle>`. Any failure stops the deposit, and nothing is written.
"""

from __future__ import annotations

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import Finding, Report
from manuscript_guard.gates.custodian import (
    check_restricted_inputs,
    check_small_cells,
    recoverable_cells,
)
from manuscript_guard.sign_offs import Signable, digest_of, settle

from .counts import ROLE, settled_small_counts
from .plan import Entry, _declared, _identity, _key, inside

GATE = "DEPOSIT"


def deposit_id(target: str, bundle: str) -> str:
    """The id the data custodian signs a bundle off by: one for each target and bundle."""
    return f"{GATE}/custodian/{target}/{bundle}"


def first(project: Project, results: Results, carried: frozenset[str],
          *, preprint: bool) -> tuple[Report, Signable | None]:  # fmt: skip
    """What the custodian forbids of the results files `carried`, named from the project's
    root, and of the manuscript for a preprint; and the small counts to sign off, where any
    are found."""
    every = frozenset(f.path.relative_to(project.root).as_posix() for f in results.fragments)
    small, settled = settled_small_counts(project, results, every - carried)
    report = Report(tuple(settled))
    if preprint:
        report = report.merge(check_small_cells(project, results))
    report = report.merge(check_restricted_inputs(project, results))
    return report.merge(recoverable_cells(project, results, carried)), small


#: The SHA-256 of no bytes, which tells no file apart: an empty file holds nothing to keep.
EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _restricted_digests(project: Project, results: Results, keys: set[str],
                        declared: list[dict]) -> set[str]:  # fmt: skip
    """The SHA-256 of each input declared restricted: as each run recorded it, and as the
    file in the project is now, where it is there."""
    from .plan import _digest

    found = {str(record["sha256"]).lower() for fragment in results.fragments
             for record in fragment.inputs if isinstance(record, dict)
             and record.get("path") and record.get("sha256")
             and _key(record["path"]) in keys}  # fmt: skip
    for seen in declared:
        path = project.root / seen["path"]
        if inside(seen["path"]) and path.is_file():
            try:
                found.add(_digest(path))
            except OSError:
                continue
    return found - {EMPTY}


def restricted_entries(project: Project, results: Results,
                       entries: tuple[Entry, ...]) -> list[Finding]:  # fmt: skip
    """A failure for each file of the bundle that is an input declared restricted: by its
    path in the bundle, by the file it is copied from, as another name for that file, or by
    its bytes, those the runs recorded or the input holds now. A LaTeX source folder copies
    each file the build read under a name of its own (`latex_pack`), which neither its name
    nor the file it is would catch (round 1 of #460)."""
    declared = [seen for seen in _declared(results).values() if seen["restricted"]]
    keys = {key for key, seen in _declared(results).items() if seen["restricted"]}
    files = {found for seen in declared if inside(seen["path"])
             and (found := _identity(project.root / seen["path"]))}  # fmt: skip
    digests = _restricted_digests(project, results, keys, declared)
    found = []
    for entry in entries:
        named = _key(entry.path) in keys or entry.sha256 in digests
        source = entry.source
        if source is not None and not named:
            try:
                relative = source.resolve().relative_to(project.root.resolve()).as_posix()
            except ValueError:
                relative = None
            named = (relative is not None and _key(relative) in keys) or \
                (_identity(source) is not None and _identity(source) in files)  # fmt: skip
        if named:
            found.append(Finding(GATE, "deposit-restricted-input", f"{entry.path} is an input "
                                 "the analysis declares restricted, and the bundle would "
                                 "deposit it", path=source or project.root,
                                 hint="a restricted input stays in the custodian's hands: "
                                 "take it out of what the bundle carries"))  # fmt: skip
    return found


def signable(project: Project, target: str, bundle: str, entries: tuple[Entry, ...],
             signed_as: tuple[tuple[str, str], ...] = ()) -> Signable | None:  # fmt: skip
    """The bundle's list of files and digests, for the data custodian to sign off where they
    restrict sending; None where they do not. MANIFEST.yaml is left out, as `package` leaves
    it out: it names the commit and whether the tree is clean, which the sign-off itself
    changes, and every file it lists is signed by its own digest. A file `signed_as` names
    is signed by the digest given there, that of what it is made from."""
    from manuscript_guard.panel.custodian import restricts_sending

    from .write import MANIFEST

    if not restricts_sending(project):
        return None
    by_source = dict(signed_as)
    listed = sorted((entry.path, by_source.get(entry.path, entry.sha256)) for entry in entries
                    if entry.path != MANIFEST)  # fmt: skip
    finding = Finding(GATE, "deposit-not-authorised", f"the data custodian restricts where the "
                      f"paper's files may be sent, and this bundle sends {len(entries)} files "
                      f"to {target}", path=project.root / "paper.yaml")  # fmt: skip
    return Signable(ROLE, deposit_id(target, bundle),
                    digest_of("deposit", target, bundle, listed), (finding,))


def last(project: Project, results: Results, target: str, bundle: str,
         entries: tuple[Entry, ...], signed_as: tuple[tuple[str, str], ...] = (),
         ) -> tuple[Report, Signable | None]:  # fmt: skip
    """What stops the planned bundle: a restricted input in it, and the custodian's sign-off
    of it where they restrict sending, as it stands."""
    report = Report(tuple(restricted_entries(project, results, entries)))
    found = signable(project, target, bundle, entries, signed_as)
    if found is not None:
        report = report.with_findings(*settle(project, found))
    return report, found


__all__ = ["GATE", "deposit_id", "first", "last", "restricted_entries", "signable"]
