"""Writing a planned package: the folder, the .zip of it, MANIFEST.yaml and SHA256SUMS.

The files are copied, and each copy's digest is taken again and held to the plan's. A file
that changed between the two is a package nobody planned, and one the data custodian may have
signed off as it was: the folder is removed and nothing is written. The .zip holds the folder
with every date set to the first one a .zip can hold, and its files in order, so that two
packages of an unchanged project are one file.
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from manuscript_guard import __version__
from manuscript_guard.contracts.project import Project

from .plan import Entry, PackageError, Plan, settings

SCHEMA = "manuscript-guard/package/1"
MANIFEST = "MANIFEST.yaml"
SUMS = "SHA256SUMS"
#: The earliest date a .zip entry can carry, given to every entry.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
#: The size from which an entry is written in ZIP64, which a size past 2 GiB needs and which
#: has to be said before the entry is written.
ZIP64_FROM = 1 << 31


@dataclass(frozen=True)
class Written:
    directory: Path
    archive: Path
    manifest: Path


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _place(directory: Path, entry: Entry) -> None:
    from .plan import inside

    if not inside(entry.path):
        raise PackageError(f"{entry.path} is not a path inside the package")
    target = directory / entry.path
    target.parent.mkdir(parents=True, exist_ok=True)
    if entry.data is not None:
        target.write_bytes(entry.data)
    else:
        assert entry.source is not None
        shutil.copyfile(entry.source, target)
    if _digest(target) != entry.sha256:
        raise PackageError(f"{entry.path} changed while the package was written; package "
                           "it again once nothing is writing to it")  # fmt: skip


def manifest_text(project: Project, plan: Plan, *, checked: bool) -> str:
    from manuscript_guard.build.submission import _commit

    doi = settings(project).get("doi")
    document = {
        "schema": SCHEMA,
        "title": project.paper.get("title", ""),
        "package": plan.name,
        "doi": str(doi) if doi else "none yet",
        "packaged_with": f"manuscript-guard {__version__}",
        **_commit(project),
        "checks": (
            "passed" if checked else "SKIPPED — packaged with --skip-checks while G1 was "
            "failing: the results may not be what the analysis writes"
        ),
        "with_manuscript": plan.with_manuscript,
        **({"companion_written_with": plan.pandoc} if plan.pandoc else {}),
        "files": [{"file": e.path, "bytes": e.size, "sha256": e.sha256} for e in plan.entries],
        "withheld": [{"path": w.path, "why": w.why} for w in plan.withheld],
    }
    return (
        "# Every file of this package and its SHA-256, and every file left out and why.\n"
        "# Written by `manuscript-guard package`; SHA256SUMS holds the same digests for\n"
        "# `sha256sum -c`.\n\n" + yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    )


def _zip(directory: Path, archive: Path) -> None:
    files = sorted((p for p in directory.rglob("*") if p.is_file()),
                   key=lambda p: p.relative_to(directory).as_posix())  # fmt: skip
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as out:
        for path in files:
            info = zipfile.ZipInfo(f"{directory.name}/{path.relative_to(directory).as_posix()}",
                                   date_time=ZIP_DATE)  # fmt: skip
            info.compress_type = zipfile.ZIP_DEFLATED
            # As a Unix .zip, whatever made it, so that the bytes do not depend on the system.
            info.create_system = 3
            info.external_attr = 0o644 << 16
            large = path.stat().st_size >= ZIP64_FROM
            with path.open("rb") as source, out.open(info, "w", force_zip64=large) as target:
                shutil.copyfileobj(source, target, 1 << 20)


def write_package(project: Project, plan: Plan, *, checked: bool = True) -> Written:
    """Write the package into build/package/, replacing the one there."""
    if not plan.report.ok:
        raise PackageError("the package is refused; nothing is written")
    home = project.path("build") / "package"
    directory, archive = home / plan.name, home / f"{plan.name}.zip"
    if directory.exists():
        shutil.rmtree(directory)
    archive.unlink(missing_ok=True)
    directory.mkdir(parents=True)
    try:
        for entry in plan.entries:
            _place(directory, entry)
        manifest = directory / MANIFEST
        manifest.write_text(manifest_text(project, plan, checked=checked), encoding="utf-8",
                            newline="\n")  # fmt: skip
        named = sorted([(e.path, e.sha256) for e in plan.entries]
                       + [(MANIFEST, _digest(manifest))])  # fmt: skip
        (directory / SUMS).write_text("".join(f"{sha}  {path}\n" for path, sha in named),
                                      encoding="utf-8", newline="\n")  # fmt: skip
        _zip(directory, archive)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        archive.unlink(missing_ok=True)
        raise
    return Written(directory, archive, manifest)


def deposit_steps(project: Project, written: Written) -> str:
    """What the author does next, which the tool does not do for them."""
    doi = settings(project).get("doi")
    first = (
        f"  The package names its DOI, {doi}. Name it in the Data availability statement, "
        "and cite the deposit in the reference list."
        if doi else
        "  1. At the repository you deposit in (Zenodo, OSF, Dryad, figshare, an institutional "
        "or a journal's own), reserve the DOI before you publish the record, where it allows "
        "that.\n  2. Write it in paper.yaml as package.doi, and run `manuscript-guard package` "
        "again, so that README.md and CITATION.cff carry it.\n  3. Name it in the Data "
        "availability statement, and cite the deposit in the reference list: `check` says "
        "where the statement does not name package.doi."
    )
    return (
        f"package: {written.directory}\n"
        f"archive: {written.archive}\n\n"
        "Nothing has been uploaded: depositing is yours to do.\n"
        f"{first}\n"
        f"  Upload {written.archive.name}, or the files of the folder, and publish the record."
    )


__all__ = ["Written", "deposit_steps", "manifest_text", "write_package"]
