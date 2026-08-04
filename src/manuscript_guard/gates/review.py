"""G11 — the manuscript has been read by people qualified to object to it.

Every other gate checks a property of the text. This one checks that somebody competent
disagreed with it, or failed to, on the record.

The same bargain as the figure review and the literature attestation, and it is worth being
explicit about the limit before describing the mechanism: **this cannot tell you a review
was any good.** It verifies that a panel was assembled and written down, that each member
produced a record covering their remit, that the records apply to the manuscript as it now
stands, and that every major finding was answered — resolved, or overridden with a reason.
A reviewer who writes "looks fine" satisfies the gate and helps nobody.

Two design points carry most of the value.

**The panel is recorded, not improvised.** A panel's composition decides what it can see;
three methodologists will not notice that the clinical framing is wrong. Writing down who
was asked and why makes the gaps visible while there is still time to fill them.

**The second panel is blinded by default.** A second round that reads the first round's
report inherits its blind spots, which is the one thing a second panel exists to avoid.

Severity depends on what is being built. An author mid-draft should be able to produce a
document to read; the version that goes to a journal should not have unanswered major
findings. So the gate warns during ordinary work and fails for a submission build.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files

GATE = "G11"
REVIEW_DIR = "review"
DEFAULT_ROUNDS_REQUIRED = 2


def manuscript_digest(project: Project) -> str:
    """A digest of the manuscript source, so a review can be tied to what it read."""
    digest = hashlib.sha256()
    for path in source_files(project.path("manuscript")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def file_digests(project: Project) -> dict[str, str]:
    """One digest per manuscript file, so a record can say what it actually read.

    Keyed by the path relative to `manuscript/`, not by filename. `source_files` walks
    subdirectories — that is a documented feature — and keying on `path.name` collapsed two
    files sharing a name into one dict entry. The loser vanished not only from
    `file_sha256` but from the set `review-uncovered` subtracts from, so a whole file could
    be unreviewed while the round reported complete. Splitting a paper into per-section
    folders, or two co-authors each writing a `results.md`, is enough to trigger it.
    """
    root = project.path("manuscript")
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_files(root)
    }


def stale_files(recorded: dict, project: Project) -> list[str]:
    """Of the files a record says it read, which have changed or gone.

    `manuscript_digest` hashes every byte of every file, and `review-stale` is a hard
    failure at submission — so removing one comma from the Discussion invalidated both
    completed panel rounds, including the biostatistician's read of the Methods.
    Copy-editing is the last thing anyone does to a paper, which put the harshest failure
    in the toolkit at the worst possible moment.

    So a record may list the files it read, and is judged on those alone. That is scoping,
    not leniency: it only holds because `review-uncovered` separately refuses to call a
    round complete while some manuscript file is in nobody's list. Without that companion
    check this would be a way to review one file and pass.

    Empty when the record lists nothing — an older record falls back to the
    whole-manuscript comparison its writer intended, rather than being silently treated as
    current.
    """
    if not isinstance(recorded, dict) or not recorded:
        return []
    current = file_digests(project)
    return sorted(
        name for name, digest in recorded.items() if current.get(name) != digest
    )


def document_digest(project: Project) -> str:
    """Everything that decides what a built document says: the prose *and* the results.

    `manuscript_digest` covers `manuscript/*.md`, which is what a reviewer read — and it is
    the wrong question for a built `.docx`, because in this toolkit the numbers in the
    document come from `results/`, not from the prose. Stamping a build with the manuscript
    digest alone meant the ordinary workflow slipped through: re-run the analysis on new
    data, leave the sentences untouched, and the stamp still matched while the document
    showed the old number. An adversarial review walked an ROR from 3.84 to 28.80 with
    `check --submission` reporting nothing.

    Cheap enough to recompute on every `check`: the fragments are already loaded, and their
    sidecars are 64 bytes each.
    """
    digest = hashlib.sha256()
    digest.update(manuscript_digest(project).encode("ascii"))

    results = project.path("results")
    if results.exists():
        for path in sorted(results.glob("*.json")):
            digest.update(path.name.encode("utf-8"))
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))

    # The ledger *and* the bibliography. An offline build runs citeproc over
    # `references.bib`, so the formatted citations — author names, year, title — are baked
    # into the .docx from that file. Leaving it out meant editing a reference's authors
    # changed what the document says while the stamp still matched: the same slip this
    # function was written to close, for the one input it forgot.
    for name in ("ledger.yaml", "references.bib"):
        path = project.path("literature") / name
        if path.exists():
            digest.update(name.encode("utf-8"))
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
    return digest.hexdigest()


def review_root(project: Project) -> Path:
    return project.root / REVIEW_DIR


def panel_path(project: Project, round_number: int) -> Path:
    return review_root(project) / f"panel-{round_number}.yaml"


def round_dir(project: Project, round_number: int) -> Path:
    return review_root(project) / f"round-{round_number}"


def panels(project: Project) -> list[tuple[int, Path]]:
    root = review_root(project)
    if not root.exists():
        return []
    found = []
    for path in sorted(root.glob("panel-*.yaml")):
        try:
            number = int(path.stem.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        found.append((number, path))
    return sorted(found)


@dataclass(frozen=True)
class Open:
    reviewer: str
    finding_id: str
    text: str


def rounds_required(project: Project) -> int:
    return int(project.paper.get("review", {}).get("rounds_required", DEFAULT_ROUNDS_REQUIRED))


def check_review(project: Project, *, submission: bool = False) -> Report:
    """`submission` raises every warning here to a failure."""
    severity = FAIL if submission else WARN
    found = panels(project)
    required = rounds_required(project)

    if not found:
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="no-review",
                    severity=FAIL if submission else INFO,
                    message=f"nobody has reviewed this manuscript ({required} round(s) expected)",
                    hint="the review-panel skill assembles a panel and records it; "
                    "`manuscript-guard review --open` writes the file",
                ),
            ),
            {"review_rounds": 0},
        )

    report = Report()
    current = manuscript_digest(project)
    complete_rounds = 0
    open_major: list[Open] = []

    for number, path in found:
        document = read_structured(path)
        schema_report = validate(document, "panel", path, gate=GATE)
        report = report.merge(schema_report)
        if not schema_report.ok or not isinstance(document, dict):
            continue

        ids = [reviewer["id"] for reviewer in document["reviewers"]]
        repeated = sorted({name for name in ids if ids.count(name) > 1})
        if repeated:
            # One review file answers every slot sharing its id, so a duplicate let a single
            # record stand in for two reviewers — and a panel's composition is the whole
            # point of recording it. "Three methodologists will not notice that the clinical
            # framing is wrong" is only true if there really were three people.
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="duplicate-reviewer",
                    severity=severity,
                    message=f"round {number}: {', '.join(repeated)} appears twice in the "
                    f"panel, so one record answers both remits",
                    path=path,
                    hint="give each reviewer a distinct id; two reviewers with the same "
                    "remit are one reviewer",
                )
            )

        round_report, complete, unresolved = _check_round(
            project, number, document, current, severity
        )
        report = report.merge(round_report)
        complete_rounds += int(complete)
        open_major.extend(unresolved)

    if complete_rounds < required:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="rounds-outstanding",
                severity=severity,
                message=f"{complete_rounds} of {required} review round(s) complete",
                hint="set review.rounds_required in paper.yaml if this paper needs fewer",
            )
        )

    if len(found) > 1:
        report = report.merge(_check_blinding(project, found, severity))

    for item in open_major:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="open-major-finding",
                severity=severity,
                message=f"{item.reviewer} {item.finding_id}: {item.text[:120]}",
                hint="record what was done in `resolution`, or why it was not in `overridden`",
            )
        )

    return report.with_counts(
        review_rounds=len(found),
        review_rounds_complete=complete_rounds,
        review_open_major=len(open_major),
    )


def _check_round(
    project: Project, number: int, panel: dict, current: str, severity: str
) -> tuple[Report, bool, list[Open]]:
    report = Report()
    directory = round_dir(project, number)
    unresolved: list[Open] = []
    complete = True
    # A record that lists no files read the whole manuscript, so one of those settles
    # coverage for the round. Otherwise coverage is the union of what the records listed.
    covered: set[str] = set()
    read_everything = False
    records = 0

    for reviewer in panel["reviewers"]:
        path = directory / f"{reviewer['id']}.yaml"
        if not path.exists():
            complete = False
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="review-missing",
                    severity=severity,
                    message=f"round {number}: {reviewer['id']} has not reported",
                    path=path,
                    context=reviewer["remit"][:140],
                )
            )
            continue

        document = read_structured(path)
        schema_report = validate(document, "review", path, gate=GATE)
        report = report.merge(schema_report)
        if not schema_report.ok or not isinstance(document, dict):
            complete = False
            continue

        # Per file when the record says which files it read, whole-manuscript otherwise.
        # Hashing every byte of every file meant one comma in the Discussion voided both
        # completed rounds — and `review-stale` is a hard failure at submission, so the
        # harshest check in the toolkit fired at the moment an author is copy-editing.
        records += 1
        read = document.get("file_sha256")
        if isinstance(read, dict) and read:
            changed = stale_files(read, project)
            outdated = bool(changed)
            covered |= set(read)
        else:
            changed = []
            outdated = document["manuscript_sha256"] != current
            read_everything = True
        if outdated:
            complete = False
            named = f" ({', '.join(changed)})" if changed else ""
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="review-stale",
                    severity=severity,
                    message=f"round {number}: {reviewer['id']} reviewed an earlier "
                    f"manuscript{named}",
                    path=path,
                    context=f"reviewed {document['reviewed_on']} by {document['reviewed_by']}",
                    hint="the text has changed since; re-review, or accept that the finding "
                    "list describes a version nobody will read",
                )
            )

        for finding in document.get("findings", []):
            if finding["severity"] != "major":
                continue
            answered = str(finding.get("resolution", "")).strip() or str(
                finding.get("overridden", "")
            ).strip()
            if not answered:
                unresolved.append(
                    Open(reviewer=reviewer["id"], finding_id=finding["id"], text=finding["finding"])
                )

    # What makes per-file scoping honest. A record listing the files it read is judged on
    # those alone, which is only defensible while every manuscript file is on somebody's
    # list — otherwise "reviewed" would mean "reviewed the Methods", and a Discussion added
    # after the round would sail through as reviewed by people who never saw it.
    if records and not read_everything:
        uncovered = sorted(set(file_digests(project)) - covered)
        if uncovered:
            complete = False
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="review-uncovered",
                    severity=severity,
                    message=f"round {number}: no reviewer read {', '.join(uncovered)}",
                    path=directory,
                    hint="add the file to the `file_sha256` map of whoever read it, or give "
                    "the round a reviewer whose remit covers it",
                )
            )

    return report, complete, unresolved


def _check_blinding(project: Project, found: list[tuple[int, Path]], severity: str) -> Report:
    """A later panel that read the earlier findings is not an independent look."""
    report = Report()
    for number, path in found[1:]:
        document = read_structured(path)
        if isinstance(document, dict) and not document.get("blinded", False):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="round-not-blinded",
                    # Always a warning, including under --submission. Written as
                    # `WARN if severity == WARN else severity` this was a tautology equal to
                    # `severity`, so it became a failure at submission — while DESIGN says,
                    # and still says, that an unblinded later round warns. Keeping it a
                    # warning is also the safer incentive: refusing to submit over it would
                    # be answered by not recording the second round at all, and a recorded
                    # unblinded review is worth more than an unrecorded one.
                    severity=WARN,
                    message=f"round {number} was not blinded to the earlier rounds",
                    path=path,
                    hint="a second panel that reads the first panel's report inherits its "
                    "blind spots, which is the one thing a second panel is for",
                )
            )
    return report


def open_panel(
    project: Project,
    round_number: int,
    reviewers: list[dict],
    *,
    blinded: bool | None = None,
) -> Path:
    """Write a panel file and the empty round directory."""
    from datetime import date

    import yaml

    path = panel_path(project, round_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    round_dir(project, round_number).mkdir(parents=True, exist_ok=True)

    document = {
        "schema": "manuscript-guard/panel/1",
        "round": round_number,
        "opened_on": date.today().isoformat(),
        "manuscript_sha256": manuscript_digest(project),
        "blinded": (round_number > 1) if blinded is None else blinded,
        "reviewers": reviewers,
    }
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return path
