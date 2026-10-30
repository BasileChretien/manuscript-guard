"""`audit --package PKG.zip|DIR`: a package `manuscript-guard package` or `deposit` wrote, held
to its own records, for an editor or a referee who was sent it with a paper (DESIGN.md, "A
package held to its own manifest").

Read: MANIFEST.yaml against its schema; each file it lists, there with the bytes and SHA-256 it
lists; SHA256SUMS, the same files and digests, the manifest's own among them; the files neither
lists; `checks: SKIPPED`; what was withheld, and why; each results file against its `.sha256`
and its `generated_by_sha256` against the script the package holds at `generated_by`; each
receipt a harvested results file names, its output's digest against the fragment's; and the
results digest VERIFICATION.json records, against the results packaged. VERIFICATION.json's
gate counts are quoted as the authors' check, not judged again. Nothing is run: `verify` is the
reader's to run, in a container or a virtual machine (`WORDING`).

`--strict` counts a file missing or different from what the manifest or SHA256SUMS lists, a
manifest that cannot be read, a results file whose bytes are not those its `.sha256` records,
and one whose script is not the script packaged beside it (decision 8 of the editor and referee
layer); nothing else.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from manuscript_guard.auditing.report import PACKAGE, Item
from manuscript_guard.auditing.unpack import MANIFEST
from manuscript_guard.findings import FAIL, INFO, WARN

GATE = "audit"
SUMS = "SHA256SUMS"
VERIFICATION = "VERIFICATION.json"
SCHEMA = "manuscript-guard/package/1"
#: The largest MANIFEST.yaml or VERIFICATION.json read.
LARGEST_RECORD = 16 << 20
#: Printed every time a package is read (the design of the editor and referee layer).
WORDING = (
    "Every file is the one the package's own manifest lists, and each result names the script "
    "packaged beside it. That shows the package is whole as written. Anyone who changes a file "
    "can write a new manifest, so it says nothing of who made the package or whether the "
    "analysis is right. `manuscript-guard verify`, run in the unpacked folder, re-runs the "
    "analysis: that runs the authors' code on your machine, so do it in a container or a "
    "virtual machine, and only where the inputs are packaged."
)
_SUM_LINE = re.compile(r"([0-9a-f]{64}) [ *](.+)")


@dataclass
class PackageRead:
    """What `--package` read, and what it found."""

    given: Path
    root: Path
    listed: int = 0
    summed: int | None = None
    files: int = 0
    results: int = 0
    by_script: int = 0
    receipts: int = 0
    results_dir: Path | None = None
    packaged_with: str | None = None
    found: list[Item] = field(default_factory=list)

    def say(self, code: str, message: str, severity: str = WARN, counted: bool = False,
            context: str | None = None) -> None:  # fmt: skip
        self.found.append(Item(PACKAGE, GATE, code, message, severity, counted, self.given,
                               context=context))  # fmt: skip


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(root: Path, name: str) -> Path | None:
    """The file `name` stands for in the package, None where it would be outside it."""
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return None
    parts = PurePosixPath(name).parts
    if ".." in parts:
        return None
    return root.joinpath(*parts)


def _all_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def check(given: Path, root: Path) -> PackageRead:
    """The package at `root`, as `given` names it, held to its own records."""
    read = PackageRead(given, root)
    manifest = _manifest(read)
    listed: dict[str, dict] = {}
    if manifest is not None:
        read.packaged_with = str(manifest.get("packaged_with") or "") or None
        listed = _listed_files(read, manifest)
        _checks_and_withheld(read, manifest)
    sums = _sums(read)
    present = _all_files(root)
    read.files = len(present)
    _held(read, listed, sums)
    _unlisted(read, present, listed, sums)
    _results(read, manifest)
    _verification(read)
    return read


def _manifest(read: PackageRead) -> dict | None:
    from manuscript_guard.contracts._schema import validate

    path = read.root / MANIFEST
    if path.stat().st_size > LARGEST_RECORD:
        read.say("package-manifest-invalid", f"{MANIFEST} is over {LARGEST_RECORD} bytes, and "
                 "was not read", FAIL, True)  # fmt: skip
        return None
    try:
        import yaml

        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - whatever the parser raises is about this file
        read.say("package-manifest-invalid", f"{MANIFEST} cannot be read: {exc}", FAIL, True)
        return None
    report = validate(document, "package", path)
    if not report.ok:
        read.say("package-manifest-invalid", f"{MANIFEST} is not a manifest of the shape "
                 f"{SCHEMA}: " + "; ".join(f.message for f in report.findings[:5]), FAIL, True)
        return None
    return document


def _listed_files(read: PackageRead, manifest: dict) -> dict[str, dict]:
    listed: dict[str, dict] = {}
    for entry in manifest["files"]:
        name = entry["file"]
        if _inside(read.root, name) is None:
            read.say("package-manifest-invalid", f"{MANIFEST} lists {name!r}, which is not a "
                     "path inside the package", FAIL, True)  # fmt: skip
            continue
        listed[name] = entry
    read.listed = len(listed)
    return listed


def _checks_and_withheld(read: PackageRead, manifest: dict) -> None:
    checks = str(manifest.get("checks") or "")
    if checks.upper().startswith("SKIPPED"):
        read.say("package-checks-skipped", "the manifest says the package was made with its "
                 "checks skipped", context=checks)  # fmt: skip
    for held in manifest.get("withheld") or []:
        read.say("package-withheld", f"{held['path']}: withheld, {held['why']}", INFO)


def _sums(read: PackageRead) -> dict[str, str] | None:
    path = read.root / SUMS
    if not path.is_file():
        read.say("package-sums-missing", f"the package has no {SUMS}")
        return None
    sums: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        read.say("package-sums-missing", f"{SUMS} cannot be read: {exc}")
        return None
    for number, line in enumerate(lines, 1):
        found = _SUM_LINE.fullmatch(line)
        if line.strip() and found is None:
            read.say("package-sums-differ", f"{SUMS} line {number} is not a digest and a path",
                     context=line[:120])  # fmt: skip
        elif found is not None:
            sums[found[2]] = found[1]
    read.summed = len(sums)
    return sums


def _held(read: PackageRead, listed: dict[str, dict], sums: dict[str, str] | None) -> None:
    """Each file the manifest or SHA256SUMS lists, there with the bytes and digest each
    records; said once a file."""
    names = [*listed, *(name for name in sums or {} if name not in listed)]
    for name in names:
        path = _inside(read.root, name)
        entry = listed.get(name)
        if path is None:
            read.say("package-sums-differ", f"{SUMS} lists {name!r}, which is not a path inside "
                     "the package")  # fmt: skip
            continue
        if not path.is_file():
            by = MANIFEST if entry is not None else SUMS
            read.say("package-file-missing", f"{name}: {by} lists it, and the package does not "
                     "hold it", FAIL, True)  # fmt: skip
            continue
        actual, size = _digest(path), path.stat().st_size
        wrong = []
        if entry is not None and (entry["sha256"] != actual or entry["bytes"] != size):
            wrong.append(f"{MANIFEST} lists {entry['bytes']} bytes, SHA-256 "
                         f"{entry['sha256'][:12]}")  # fmt: skip
        summed = (sums or {}).get(name)
        if summed is not None and summed != actual:
            wrong.append(f"{SUMS} lists SHA-256 {summed[:12]}")
        if wrong:
            read.say("package-file-changed", f"{name}: " + ", and ".join(wrong) + f"; the file "
                     f"holds {size} bytes, SHA-256 {actual[:12]}", FAIL, True)  # fmt: skip
        elif entry is not None and sums is not None and summed is None:
            read.say("package-sums-differ", f"{name}: {MANIFEST} lists it and {SUMS} does not")
    if sums is not None and listed and MANIFEST not in sums:
        read.say("package-sums-differ", f"{SUMS} does not list {MANIFEST}, so nothing records "
                 "the manifest's own digest")  # fmt: skip
    elif sums is not None and MANIFEST in sums and sums[MANIFEST] != _digest(read.root / MANIFEST):
        read.say("package-file-changed", f"{MANIFEST}: {SUMS} lists SHA-256 "
                 f"{sums[MANIFEST][:12]}, and the manifest is not that file", FAIL, True)


def _unlisted(read: PackageRead, present: list[str], listed: dict[str, dict],
              sums: dict[str, str] | None) -> None:  # fmt: skip
    for name in present:
        if name in listed or name in (MANIFEST, SUMS) or name in (sums or {}):
            continue
        read.say("package-file-unlisted", f"{name}: in the package, and neither {MANIFEST} nor "
                 f"{SUMS} lists it")  # fmt: skip


def _results_dir(root: Path) -> Path:
    """The results folder the packaged paper.yaml names, `results` by default."""
    import yaml

    folder = "results"
    try:
        paper = yaml.safe_load((root / "paper.yaml").read_text(encoding="utf-8"))
        named = ((paper or {}).get("paths") or {}).get("results")
        folder = named if isinstance(named, str) and named else folder
    except Exception:  # noqa: BLE001 - the default folder, where paper.yaml says nothing readable
        pass
    return _inside(root, folder.strip("/")) or root / "results"


def _results(read: PackageRead, manifest: dict | None) -> None:
    folder = _results_dir(read.root)
    if not folder.is_dir():
        read.say("package-no-results", "the package holds no results folder", INFO)
        return
    read.results_dir = folder
    withheld = {str(held["path"]) for held in (manifest or {}).get("withheld") or []}
    for path in sorted(folder.glob("*.json")):
        read.results += 1
        _result(read, path, withheld)


def _result(read: PackageRead, path: Path, withheld: set[str]) -> None:
    from manuscript_guard.emit import DIGEST_SUFFIX, source_digest_matches

    name = path.relative_to(read.root).as_posix()
    sidecar = path.with_name(path.name + DIGEST_SUFFIX)
    if not sidecar.is_file():
        read.say("package-result-no-digest", f"{name}: no {DIGEST_SUFFIX} beside it, so "
                 "nothing records the bytes the analysis wrote")  # fmt: skip
    else:
        recorded = sidecar.read_text(encoding="utf-8", errors="replace").split()
        if not recorded or recorded[0] != _digest(path):
            read.say("package-result-edited", f"{name}: its bytes are not those its "
                     f"{DIGEST_SUFFIX} records, so it is not the file the analysis wrote",
                     FAIL, True)  # fmt: skip
    try:
        document = json.loads(path.read_bytes().decode("utf-8").removeprefix(chr(0xFEFF)))
        provenance = document["provenance"]
        script = str(provenance["generated_by"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        read.say("package-result-unreadable", f"{name}: not a results file the audit can read "
                 f"({exc.__class__.__name__})")  # fmt: skip
        return
    at = _inside(read.root, script)
    if at is None or not at.is_file():
        held = " (the manifest says it was withheld)" if script in withheld else ""
        read.say("package-script-missing", f"{name}: written by {script}, which the package "
                 f"does not hold{held}")  # fmt: skip
    elif not provenance.get("generated_by_sha256"):
        read.say("package-result-unpinned", f"{name}: records no digest of {script}, so "
                 "nothing ties it to the script packaged")  # fmt: skip
    elif not source_digest_matches(at, str(provenance["generated_by_sha256"])):
        read.say("package-result-not-by-script", f"{name}: not written by the script packaged "
                 f"beside it: {script} is not the script whose digest it records", FAIL, True)
    else:
        read.by_script += 1
    harvested = provenance.get("harvested")
    if isinstance(harvested, dict) and isinstance(harvested.get("receipt"), dict):
        _receipt(read, name, harvested)


def _receipt(read: PackageRead, name: str, harvested: dict) -> None:
    """The site's receipt a harvested results file names, its output's digest against the
    one the results file was read from."""
    from manuscript_guard.emit import input_digest_matches
    from manuscript_guard.harvest import HarvestError, read_receipt, run_of

    recorded = harvested["receipt"]
    where = str(recorded.get("path", ""))
    path = _inside(read.root, where)
    if path is None or not path.is_file():
        read.say("package-receipt-not-packaged", f"{name}: harvested under the receipt "
                 f"{where or '(no path)'}, which the package does not hold", INFO)
        return
    read.receipts += 1
    if not input_digest_matches(path, str(recorded.get("sha256", ""))):
        read.say("package-receipt-differs", f"{name}: {where} is not the receipt it was "
                 "harvested under")  # fmt: skip
        return
    try:
        run = run_of(read_receipt(path), harvested["spec"]["key"])
    except (HarvestError, KeyError, TypeError):
        run = None
    output = str(harvested.get("output", ""))
    outs = [out for out in (run or {}).get("outputs", []) if out.get("path") == output]
    if not outs or outs[0].get("sha256") != harvested.get("sha256"):
        read.say("package-receipt-output-differs", f"{name}: the receipt {where} records no "
                 f"output {output} with the digest it was harvested from")  # fmt: skip


def _verification(read: PackageRead) -> None:
    """VERIFICATION.json, where the package holds one: its check quoted, its results digest
    held to the results packaged; the other digests are of the authors' project."""
    from manuscript_guard.assurance import results_digest

    path = read.root / VERIFICATION
    if not path.is_file():
        return
    try:
        if path.stat().st_size > LARGEST_RECORD:
            raise ValueError("too large to read")
        record = json.loads(path.read_text(encoding="utf-8"))
        check, digests = record["check"], record["digests"]
        gates = check["gates"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        read.say("package-verification-unreadable", f"{VERIFICATION} cannot be read: {exc}")
        return
    failing = sorted(gate for gate, said in gates.items()
                     if isinstance(said, dict) and said.get("failing"))  # fmt: skip
    read.say("package-verification-quoted", f"{VERIFICATION} says `check --stage submission` "
             f"{'passed' if check.get('passed') else 'did not pass'}"
             + (f", failing in {', '.join(failing)}" if failing else "")
             + ": the authors' check, quoted and not run again; its digests of the manuscript "
             "and of the title page are of the authors' project, and not recomputed", INFO)
    folder = read.results_dir or read.root / "results"
    if digests.get("results_sha256") != results_digest(folder):
        read.say("package-verification-differs", f"{VERIFICATION} records a digest of the "
                 "results that the results packaged do not give (a results file withheld, "
                 "or one changed since)")  # fmt: skip


def counts(read: PackageRead) -> dict[str, int]:
    return {"package_files": read.files, "package_listed": read.listed,
            "package_results": read.results, "package_results_by_script": read.by_script,
            "package_receipts": read.receipts,
            "package_counted": sum(item.counted for item in read.found)}  # fmt: skip


def summary(read: PackageRead) -> str:
    sums = ("no SHA256SUMS" if read.summed is None
            else f"{read.summed} line{'s' if read.summed != 1 else ''} of SHA256SUMS")
    return (f"{read.files} file{'s' if read.files != 1 else ''} in the package; {read.listed} "
            f"listed in {MANIFEST}, {sums}; {read.results} results file"
            f"{'s' if read.results != 1 else ''}, {read.by_script} with the digest of the "
            f"script packaged beside it; {read.receipts} receipt"
            f"{'s' if read.receipts != 1 else ''} read")  # fmt: skip


def render(read: PackageRead, show) -> list[str]:
    """The section: what was read, the findings, and the wording printed every time."""
    lines = [f"  {show(read.given)}: {summary(read)}"
             + (f"; packaged with {read.packaged_with}" if read.packaged_with else "") + "."]
    for heading, chosen in (
        ("A FILE THAT DIFFERS FROM WHAT THE PACKAGE LISTS, OR A RESULT NOT WRITTEN BY THE "
         "SCRIPT PACKAGED BESIDE IT (counted by --strict):", lambda i: i.counted),
        ("Warnings (not counted by --strict):", lambda i: not i.counted and i.severity == WARN),
        ("Notes:", lambda i: not i.counted and i.severity == INFO),
    ):
        mine = [item for item in read.found if chosen(item)]
        if mine:
            lines.append(heading)
            for item in mine:
                lines.append(f"  {item.message}")
                if item.context:
                    lines.append(f"      {item.context}")
    if not any(item.counted for item in read.found):
        lines.append("  Each file listed was read with the bytes and SHA-256 listed, and no "
                     "result read records a script other than the one packaged.")  # fmt: skip
    return [*lines, "", WORDING]


__all__ = ["PACKAGE", "WORDING", "PackageRead", "check", "counts", "render", "summary"]
