"""G1 — is a dataset's date the date of the data the results were computed from?

`dataset()` pins the date the data were extracted to the files' digest, and refuses a run on
other files. That is the emitter's check, made as the analysis runs. This one is made on
what is on disk, whichever emitter wrote it, and where the data themselves are not, in CI
and in a co-author's clone of a project on restricted data:

- the pin is the start of the digest of the files the fragment recorded reading
  (`dataset-pin-mismatch`), so a fragment written by hand, or by an emitter that did not
  check, cannot date other data;
- every fragment that read one of those files read the same file (`dataset-read-differs`):
  a model fitted on the new extraction, beside Methods that date the old one, is told
  where the files are missing as well as where they are there.

That the file at the path is still the file read is G1's `input-changed`, which names the
dataset whose date it makes stale.
"""

from __future__ import annotations

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Fragment, Results
from manuscript_guard.datasets import dataset_digest, slug
from manuscript_guard.findings import Finding, Report

GATE = "G1"


def check_datasets(project: Project, results: Results) -> Report:
    """Each dataset's pin against its fragment's inputs, and every fragment that read its
    files against the files it pins."""
    del project  # the records are the whole of what is read
    report = Report()
    read_as: dict[str, list[tuple[Fragment, str]]] = {}
    for fragment in results.fragments:
        for declared in fragment.inputs:
            if isinstance(declared, dict) and declared.get("path") and declared.get("sha256"):
                read_as.setdefault(declared["path"], []).append((fragment, declared["sha256"]))
    for fragment in results.fragments:
        for name, record in sorted(fragment.datasets.items()):
            pinned = _pinned_inputs(fragment, name, record)
            if isinstance(pinned, Finding):
                report = report.with_findings(pinned)
                continue
            for path, digest in pinned.items():
                for other, other_digest in read_as.get(path, ()):
                    if other is not fragment and other_digest != digest:
                        report = report.with_findings(
                            _read_differs(name, record, path, fragment, other)
                        )
    return report.with_counts(datasets_checked=sum(len(f.datasets) for f in results.fragments))


def _pinned_inputs(fragment: Fragment, name: str, record: dict) -> dict[str, str] | Finding:
    """The digest the fragment recorded for each of the dataset's files, where the pin is
    the start of theirs; otherwise the finding that says it is not."""
    recorded = {d["path"]: d for d in fragment.inputs if isinstance(d, dict) and d.get("path")}
    inputs = list(record.get("inputs") or ())
    missing = [path for path in inputs if path not in recorded]
    pin = str(record.get("fingerprint", ""))
    if missing:
        return _mismatch(fragment, name, record, f"names {', '.join(missing)}, which this run "
                         f"did not record reading")  # fmt: skip
    digests = {path: str(recorded[path].get("sha256", "")) for path in inputs}
    whole = dataset_digest(sorted(digests.items()))
    accepted = {whole}
    if len(inputs) == 1:
        accepted.add(str(recorded[inputs[0]].get("raw_sha256", "")))
    if not pin or not any(digest.startswith(pin) for digest in accepted if digest):
        return _mismatch(fragment, name, record, f"pins {pin or 'nothing'}, and the data this "
                         f"run read are {whole[:16]}")  # fmt: skip
    return digests


def _mismatch(fragment: Fragment, name: str, record: dict, what: str) -> Finding:
    return Finding(
        gate=GATE,
        code="dataset-pin-mismatch",
        message=f"dataset {name!r}, dated as extracted on {record.get('extracted')}, {what}",
        path=fragment.path,
        context=f"written {fragment.generated_at} by {fragment.generated_by}",
        hint=f"re-run {fragment.generated_by}: dataset() pins the date to the data it reads, "
        f"and refuses other data",
    )


def _read_differs(
    name: str, record: dict, path: str, fragment: Fragment, other: Fragment
) -> Finding:
    return Finding(
        gate=GATE,
        code="dataset-read-differs",
        message=f"{other.path.name} read {path} as other data than the extraction "
        f"dataset.{slug(name)}.extracted dates ({record.get('extracted')}, in "
        f"{fragment.path.name})",
        path=other.path,
        context=f"written {other.generated_at} by {other.generated_by}",
        hint=f"re-run whichever of {other.generated_by} and {fragment.generated_by} read the "
        f"old data, so that every result comes from the extraction the Methods date",
    )


def dataset_of(fragment: Fragment, path: str) -> tuple[str, dict] | None:
    """The dataset of `fragment` whose files include `path`, with its record, or None."""
    for name, record in sorted(fragment.datasets.items()):
        if path in (record.get("inputs") or ()):
            return name, record
    return None
