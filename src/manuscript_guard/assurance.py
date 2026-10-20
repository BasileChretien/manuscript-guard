"""What `check` assures, dimension by dimension, and what it leaves to people.

A run with no failure reads as "the paper is right", and it says much less: each gate holds
one thing to a record, and some things no gate looks at. So `check` ends by grouping what it
did by what it is about. For each dimension it says which gates checked it by machine and
what they found, what was recorded and by whom and when, and, in words, what no gate
decides. There is no score and no percentage, since a single number would be read as the
verdict this is not. The exit code is the findings' at the project's stage, as before.

The three kinds of statement are the evidence the toolkit has: a deterministic check that
ran, a record somebody made (a panel's reading, a figure review, a value attested, a re-run
of the analysis), and nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, WARN, Report

#: Where `verify` records its last run, in the project's build folder: it says what this
#: checkout re-ran, so it is never committed.
VERIFIED = "verify.json"
VERIFIED_SCHEMA = "manuscript-guard/verify-run/1"


@dataclass(frozen=True)
class Dimension:
    name: str
    gates: tuple[str, ...]
    #: What no gate decides in this dimension, said in words wherever the check is printed:
    #: a clause that follows "not checked:".
    unchecked: str


DIMENSIONS = (
    Dimension(
        "computational reproducibility", ("G1",),
        "whether the analysis gives these results when run again, which "
        "`manuscript-guard verify` tests in a copy",
    ),
    Dimension(
        "numerical provenance", ("G2", "G3", "G7", "G8"),
        "whether a number is the right one to report; each is held to the result or source "
        "it is bound to",
    ),
    Dimension(
        "reporting completeness", ("G4", "G5", "G13"),
        "whether an item is reported well; each is held to being answered",
    ),
    Dimension(
        "methodological validity", ("G9", "G12", "G15"),
        "whether the design supports the conclusion",
    ),
    Dimension(
        "literature", ("G7",),
        "whether a source supports what the paper says of it, beyond the words quoted from "
        "it",
    ),
    Dimension(
        "review", ("G10", "G11"),
        "whether the readers were right; each review is held to what it read",
    ),
    Dimension(
        "language and writing", ("G6", "G14"),
        "whether the paper is clear",
    ),
)

#: A gate `check` names otherwise when it stops: the reporting gate's findings are G5's, and
#: it stops as G8r (round 1 of #306).
STOPPED_AS = {"G8r": "G5"}

#: The count that says how much a gate read, where reading nothing is worth saying.
READ = {
    "G1": "fragments_checked", "G2": "numeric_atoms", "G3": "figures_checked",
    "G5": "checklists", "G6": "prose_words", "G7": "citations", "G9": "analysis_files",
    "G10": "figures_reviewed", "G11": "review_rounds", "G12": "design_sections",
    "G13": "revision_rounds", "G14": "abbreviations_read", "G15": "models",
}  # fmt: skip


def assurance(report: Report, project: Project) -> list[str]:
    """The lines `check` prints after its findings: one block a dimension."""
    lines = ["What was checked, by what (no score: none of this says the paper is right):"]
    recorded = {
        "computational reproducibility": _verified(project),
        "literature": [*_attested(project), *_passages(report, project)],
        "methodological validity": ["no review of the design"],
        "review": [*_rounds(project), *_figures(project)],
    }
    for dimension in DIMENSIONS:
        lines.append(f"  {dimension.name}")
        lines.append(f"    checked:     {_machine(report, dimension.gates)}")
        lines.append(f"    not checked: {dimension.unchecked}")
        for said in recorded.get(dimension.name, []):
            lines.append(f"    recorded:    {said}")
    return lines


def _machine(report: Report, gates: tuple[str, ...]) -> str:
    """What the dimension's gates found: failures and warnings, and which read nothing or
    did not run."""
    found = [f for f in report.findings if STOPPED_AS.get(f.gate, f.gate) in gates]
    failing = sum(f.severity == FAIL for f in found)
    warning = sum(f.severity == WARN for f in found)
    said = f"{', '.join(gates)}: {failing} failing, {warning} warning{'' if warning == 1 else 's'}"
    stopped = sorted(
        {STOPPED_AS.get(f.gate, f.gate) for f in found if f.code == "gate-errored"},
        key=gates.index,
    )
    empty = [
        gate for gate in gates
        if gate not in stopped and gate in READ and report.counts.get(READ[gate], 0) == 0
    ]  # fmt: skip
    if stopped:
        said += f"; {', '.join(stopped)} did not run"
    if empty:
        said += f"; {', '.join(empty)} read nothing"
    return said


def _verified(project: Project) -> list[str]:
    """What the last `verify` in this checkout said, and whether the results are still the
    ones it re-ran."""
    path = project.path("build") / VERIFIED
    try:
        record = read_structured(path)
    except ContractError:
        record = None
    if not isinstance(record, dict) or record.get("schema") != VERIFIED_SCHEMA:
        return ["no run of `verify` in this checkout"]
    when, total = record.get("ran_on", "an unrecorded date"), record.get("values", 0)
    said = f"`verify` re-ran the analysis on {when}: {record.get('reproduced', 0)} of {total} " \
        "values reproduced"  # fmt: skip
    left = record.get("not_rerun")
    if isinstance(left, list) and left:
        said += f"; {len(left)} fragment{'s' if len(left) > 1 else ''} not re-run"
    if not record.get("ok"):
        said += "; it did not pass"
    if fragments_digest(project) != record.get("results_sha256"):
        said += "; the results have changed since"
    return [said]


def fragments_digest(project: Project) -> str:
    """One digest of the results fragments as they are on disk, by name and bytes."""
    digest = hashlib.sha256()
    results = project.path("results")
    for path in sorted(results.glob("*.json")) if results.is_dir() else []:
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def record_verified(project: Project, result) -> Path:
    """Write what `verify` found, for `check` to say: when, how many of the values on disk
    it reproduced, the fragments it did not re-run, whether it passed, and the results it
    re-ran. Rounds 1 and 2 of #306: counted from the fragments that re-ran alone, a skipped or
    a failed one went unsaid, and "31 of 31" was printed of an analysis not all re-run. A
    fragment not re-run carries no values in the comparison, so its values are counted from
    the file, as `verify` counts them."""
    from manuscript_guard.verify import _values_of

    comparisons = result.comparisons
    left = [name for name, _why in result.skipped] + [c.fragment for c in comparisons if not c.ran]
    on_disk = 0
    for name in left:
        document = _read(project.path("results") / name)
        on_disk += len(_values_of(document)) if document else 0
    path = project.path("build") / VERIFIED
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": VERIFIED_SCHEMA,
        "ran_on": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        # A version found other on the re-run is a value on disk too, and counted as the
        # fragments not re-run count it (round 2 of #306).
        "values": on_disk + sum(
            len(c.agreed) + len(c.differed) + len(c.only_on_disk) + len(c.environment)
            for c in comparisons if c.ran
        ),
        "reproduced": sum(len(c.agreed) for c in comparisons),
        "not_rerun": left,
        "ok": bool(result.ok),
        "results_sha256": fragments_digest(project),
    }
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _rounds(project: Project) -> list[str]:
    """The panel's last round with readings: its number, its readers and when they read."""
    from manuscript_guard.gates.review import review_root

    rounds: dict[int, list[tuple[str, str]]] = {}
    for path in review_root(project).glob("round-*/*.yaml"):
        number = path.parent.name.removeprefix("round-")
        record = _read(path)
        if number.isdigit() and record.get("reviewed_by"):
            readers = rounds.setdefault(int(number), [])
            readers.append((str(record["reviewed_by"]), str(record.get("reviewed_on", ""))))
    if not rounds:
        return ["no panel's reading"]
    last = max(rounds)
    readers = sorted({by for by, _on in rounds[last]})
    dates = sorted({on for _by, on in rounds[last] if on})
    return [
        f"{len(rounds)} panel round{'s' if len(rounds) > 1 else ''} read; the last, round "
        f"{last}, by {', '.join(readers)}" + (f" on {dates[-1]}" if dates else "")
    ]


def _figures(project: Project) -> list[str]:
    """Who reviewed the figures, and the last time one was."""
    reviews = [_read(path) for path in sorted(project.path("figures").rglob("*.review.yaml"))]
    reviews = [review for review in reviews if review.get("reviewed_by")]
    if not reviews:
        return []
    readers = sorted({str(review["reviewed_by"]) for review in reviews})
    dates = sorted(str(review.get("reviewed_on", "")) for review in reviews)
    when = (f", the last on {dates[-1]}" if len(reviews) > 1 else f" on {dates[-1]}") \
        if dates[-1] else ""  # fmt: skip
    return [
        f"{len(reviews)} figure review{'s' if len(reviews) > 1 else ''}, by "
        f"{', '.join(readers)}{when}"
    ]


def _attested(project: Project) -> list[str]:
    """The values a person attested having read in a source the toolkit could not store."""
    from manuscript_guard.contracts.literature import ATTESTED_FILE

    entries = _read(project.path("literature") / ATTESTED_FILE).get("entries")
    if not isinstance(entries, list):
        return []
    attested = [e for e in entries if isinstance(e, dict) and e.get("attested_by")]
    if not attested:
        return []
    people = sorted({str(entry["attested_by"]) for entry in attested})
    return [
        f"{len(attested)} value{'s' if len(attested) > 1 else ''} attested as read in a source "
        f"that could not be stored, by {', '.join(people)}"
    ]


def _passages(report: Report, project: Project) -> list[str]:
    """How many cited statements carry a passage of a work they cite, as G7 counted them, and
    the passages a person judged, by whom."""
    from manuscript_guard.literature.passages import read_passages

    total = report.counts.get("cited_statements", 0)
    if not total:
        return []
    carrying = report.counts.get("cited_statements_with_passage", 0)
    said = f"cited statements with a passage of a work they cite: {carrying} of {total}"
    passages, _report = read_passages(project.path("literature"))
    judged = [passage for passage in passages if passage.support is not None]
    if judged:
        people = sorted({str(passage.judged_by) for passage in judged})
        said += (
            f"; {len(judged)} passage{'' if len(judged) == 1 else 's'} judged against "
            f"{'its sentence' if len(judged) == 1 else 'their sentences'}, by {', '.join(people)}"
        )
    return [said]


def _read(path: Path) -> dict:
    """A record as a mapping, or an empty one where it cannot be read: the gates say why."""
    try:
        record = read_structured(path)
    except ContractError:
        return {}
    return record if isinstance(record, dict) else {}
