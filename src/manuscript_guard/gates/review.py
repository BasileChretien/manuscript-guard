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
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files

GATE = "G11"
REVIEW_DIR = "review"
DEFAULT_ROUNDS_REQUIRED = 2
#: From the most lenient to the strictest, in the vocabulary a journal uses.
VERDICT_ORDER = ("pass", "minor-revision", "major-revision", "reject")


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


def reading_slug(reader: str) -> str:
    """A reader's name as the part of a file name: `openai/gpt-x.1` is `openai-gpt-x-1`.

    Letters, digits and the marks that belong to them are kept, in any script, lower-cased
    and composed; every run of anything else is one hyphen. Empty for a name with no letter
    or digit in it, which names no file.

    The marks matter: in scripts that write vowels as marks on a consonant, two names can
    differ in nothing else, and dropping them made two people one file. Composing matters
    because some file systems store a name decomposed, and the same name must make the same
    file wherever the project is checked out.

    This form is also how the gate knows a reader. The panel's `Dr. Tanaka` and a reading
    filed as `Dr Tanaka` are the same file, so they are the same reader: matched letter for
    letter, the gate asked for a file that existed and `review --record` refused to write it.
    """
    text = unicodedata.normalize("NFC", unicodedata.normalize("NFC", reader).lower())
    kept = "".join(
        char if char.isalnum() or unicodedata.category(char).startswith("M") else "-"
        for char in text
    )
    return re.sub("-+", "-", kept).strip("-")


def reading_path(
    project: Project, round_number: int, reviewer: str, reader: str | None = None
) -> Path:
    """Where one reading of a remit is filed.

    A remit can be read more than once, by several models or by a model and a person. The
    plain `<reviewer>.yaml` is the reading nobody named, which is every record written before
    readings had names. A named reading sits beside it as `<reviewer>.<reader>.yaml`. A
    reviewer's id cannot hold a dot, so the first dot always ends it.
    """
    name = reviewer if reader is None else f"{reviewer}.{reading_slug(reader)}"
    return round_dir(project, round_number) / f"{name}.yaml"


def files_beside(directory: Path, reviewer: str) -> dict[str, list[Path]]:
    """The files beside a reviewer's record, by the name each is filed under.

    `<reviewer>.<name>.yaml`, files only, the name composed and lower-cased as a reader's
    is, so a file stored decomposed, or in another case, is found under the same name. Two
    files under one name is possible on a file system that tells them apart, and is the
    caller's to report.
    """
    found: dict[str, list[Path]] = {}
    for path in sorted(directory.glob(f"{reviewer}.*.yaml")):
        if path.is_file():
            name = path.name[len(reviewer) + 1 : -len(".yaml")]
            name = unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).lower())
            found.setdefault(name, []).append(path)
    return found


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
    #: The reviewer, and the reader in brackets when the reading has one.
    reviewer: str
    finding_id: str
    text: str


@dataclass(frozen=True)
class _Filed:
    """One reading of a remit that counts: it fits the schema and is filed as itself."""

    path: Path
    reader: str | None
    document: dict

    def who(self, reviewer: str) -> str:
        return reviewer if self.reader is None else f"{reviewer} [{self.reader}]"


def _misfiled(filed_as: str, reviewer: str, number: int, document: dict) -> str | None:
    """Why a reading is not what its file name says it is, or None when it is.

    The file name is how a reader the panel names is looked for. A record under one reader's
    name that says another's inside is one reading standing in for two, and the same goes
    for a record copied from another remit or another round.
    """
    reader = document.get("reader")
    if not reader:
        return "names no reader"
    if reading_slug(str(reader)) != filed_as:
        return (
            f"says its reader is {reader}, whose reading is filed as "
            f"{reviewer}.{reading_slug(str(reader))}.yaml"
        )
    if document["reviewer"] != reviewer:
        return f"says it is {document['reviewer']}'s remit"
    if document["round"] != number:
        return f"says it is of round {document['round']}"
    return None


def _named_reading(
    path: Path, filed_as: str, reviewer: str, number: int, severity: str
) -> tuple[_Filed | None, Report]:
    """The reading the panel asks for under this name, or what is wrong with the file.

    The panel names the reader, so this file is that reader's reading whatever it holds,
    and anything that stops it being read is a failure: its findings cannot be counted, the
    unanswered ones included. A reading is edited by hand, to answer its findings, and
    `resolution: Fixed: it now says reporting` is not YAML.
    """
    try:
        document = read_structured(path)
    except (ContractError, OSError, ValueError, RecursionError):
        return None, Report().with_findings(
            Finding(
                gate=GATE,
                code="reading-unreadable",
                message=f"round {number}: {path.name} cannot be read as a review record",
                path=path,
                hint="the panel asks for this reading, and while it cannot be parsed nothing "
                "in it is counted, its unanswered findings included. It must be UTF-8 YAML; "
                "a value that holds a colon and a space needs quotes: "
                "resolution: 'Fixed: it now says reporting'",
            )
        )
    schema_report = validate(document, "review", path, gate=GATE)
    if not schema_report.ok or not isinstance(document, dict):
        return None, schema_report
    why = _misfiled(filed_as, reviewer, number, document)
    if why is not None:
        return None, schema_report.with_findings(
            Finding(
                gate=GATE,
                code="reading-misfiled",
                severity=severity,
                message=f"round {number}: {path.name} {why}",
                path=path,
                hint="a reading is filed as <reviewer>.<reader>.yaml and says the same "
                "inside. It is not counted until it does; a reading by another reader is "
                "another record "
                "(`manuscript-guard review --record <reviewer> --reading <reader>`)",
            )
        )
    return _Filed(path, str(document["reader"]), document), schema_report


def _readings(
    project: Project, number: int, reviewer: dict, severity: str
) -> tuple[list[_Filed], Report, bool]:
    """Every reading of one remit that counts, what is wrong with the rest, and whether the
    remit is unfinished.

    **The panel says who reads.** A remit is read by the reviewer's plain record, and by
    each reader its panel entry lists under `readers`, whose reading is the file named for
    that reader. Nothing else beside the record is a reading, and nothing else is opened.

    Two review rounds of this gate each found a reading that dropped out of a round without
    a failure, because the gate decided from a file's contents whether it was a reading: one
    that stopped parsing was taken for a note, then one saved in UTF-16 was, and a note in
    another code page took the gate down. The author chose to stop guessing. Which files are
    readings is written in the panel, by `review --record --reading` when it files one, and
    a file the panel does not name is reported and left unread.
    """
    name = reviewer["id"]
    directory = round_dir(project, number)
    report = Report()
    filed: list[_Filed] = []
    unfinished = False

    # The reviewer's own record, read as it always was: one that cannot be parsed stops the
    # gate, and its `reviewer` and `round` are not compared with its place.
    plain = directory / f"{name}.yaml"
    refused = False
    if plain.exists():
        document = read_structured(plain)
        schema_report = validate(document, "review", plain, gate=GATE)
        report = report.merge(schema_report)
        if schema_report.ok and isinstance(document, dict):
            filed.append(_Filed(plain, None, document))
        else:
            refused = unfinished = True

    expected = [str(reader) for reader in reviewer.get("readers") or ()]
    asked: dict[str, str] = {}
    for reader in expected:
        known = reading_slug(reader)
        if not known:
            unfinished = True
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="reading-missing",
                    severity=severity,
                    message=f"round {number}: {name} has no reading by {reader}",
                    path=panel_path(project, number),
                    context=reviewer["remit"][:140],
                    hint="a reader's name needs a letter or a digit: it names the file the "
                    "reading is filed in. Give this reader a name in the panel",
                )
            )
        elif known in asked:
            # One file cannot hold two readings, so one reading would answer for both.
            unfinished = True
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="duplicate-reader",
                    severity=severity,
                    message=f"round {number}: {name}'s readers {asked[known]} and {reader} "
                    f"would both be filed as {name}.{known}.yaml",
                    path=panel_path(project, number),
                    hint="a reader is known by the letters and digits of its name. Name "
                    "these two so that they differ in those, or list the reader once",
                )
            )
        else:
            asked[known] = reader

    beside = files_beside(directory, name)
    for known, reader in asked.items():
        paths = beside.pop(known, [])
        if not paths:
            unfinished = True
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="reading-missing",
                    severity=severity,
                    message=f"round {number}: {name} has no reading by {reader}",
                    path=reading_path(project, number, name, reader),
                    context=reviewer["remit"][:140],
                    hint="the panel names this reader for the remit. File its reading, or "
                    "take the reader out of the panel if it is not going to report",
                )
            )
        elif len(paths) > 1:
            unfinished = True
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="duplicate-reading",
                    severity=severity,
                    message=f"round {number}: {name} has two readings by {reader} "
                    f"({' and '.join(path.name for path in paths)})",
                    path=paths[1],
                    hint="one reader reads a remit once in a round; a second reading of a "
                    "changed manuscript is a further round",
                )
            )
        else:
            reading, problems = _named_reading(paths[0], known, name, number, severity)
            report = report.merge(problems)
            if reading is None:
                unfinished = True
            else:
                filed.append(reading)

    # Whatever else sits beside the record. Before readings had names nothing looked at
    # `biostatistician.old.yaml` or at notes kept in the round, and a copy must not start
    # failing a submission, nor a note in UTF-16 take the gate down. So these are not
    # opened. They are said, because a reading filed by hand without its reader in the
    # panel would otherwise be ignored in silence.
    for paths in beside.values():
        for path in paths:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="reading-unnamed",
                    severity=WARN,
                    message=f"round {number}: {path.name} is not a reading the panel asks "
                    "for, so it is not read or counted",
                    path=path,
                    hint=f"if it is a reading, add its reader to {name}'s `readers` in "
                    f"{panel_path(project, number).name} by hand: `manuscript-guard review "
                    "--record` names a reader when it files the reading, and does not write "
                    "over a file that is there. If it is a copy or a note, keep it outside "
                    "the round",
                )
            )

    if not expected and not filed and not refused:
        unfinished = True
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="review-missing",
                severity=severity,
                message=f"round {number}: {name} has not reported",
                path=reading_path(project, number, name),
                context=reviewer["remit"][:140],
            )
        )
    return filed, report, unfinished


def _answered(finding: dict) -> bool:
    return bool(
        str(finding.get("resolution", "")).strip() or str(finding.get("overridden", "")).strip()
    )


#: What a round says when it no longer describes the manuscript: a record is stale, or a
#: file is on nobody's list. Both are superseded by a later round that is complete.
OUTDATED = frozenset({"review-stale", "review-uncovered"})


@dataclass(frozen=True)
class _Round:
    number: int
    report: Report
    #: A record is missing or malformed: the round never happened in full.
    unfinished: bool
    #: Finished when it was read, but not of the manuscript as it now stands.
    outdated: bool
    unresolved: tuple[Open, ...]
    #: Readings that were read: one for each reviewer, more where several read a remit.
    readings: int = 0

    @property
    def current(self) -> bool:
        return not self.unfinished and not self.outdated


def _superseded(round_: _Round, latest: int) -> Report:
    """An earlier round's staleness, as history rather than as a failure.

    Editing the manuscript made every earlier record stale, and recording a new round —
    what `review --record` says to do, since it will not re-stamp a record — cleared none
    of them. `check --submission` then passed only if somebody hand-edited a digest or
    deleted a round, the two things a record exists to prevent. Once a later round is
    complete and current, the earlier ones are the history of the review: still listed,
    still counted, and their unanswered major findings still bind.
    """
    findings = tuple(
        replace(
            finding,
            code="review-superseded",
            severity=INFO,
            message=f"{finding.message}  [superseded by round {latest}]",
            hint=f"round {latest} read the manuscript as it stands; this record stays as "
            "the history of the review",
        )
        if finding.code in OUTDATED
        else finding
        for finding in round_.report.findings
    )
    return replace(round_.report, findings=findings)


def rounds_required(project: Project) -> int:
    # `setting`, so a `review:` the schema refuses is the schema's finding and not a crash
    # here: `review: [1]` has no `get`, and `rounds_required: two` is no number.
    review = project.setting("review") or {}
    return int(review.get("rounds_required", DEFAULT_ROUNDS_REQUIRED))


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
                    "see the panel schema; `manuscript-guard review` shows where the review stands",
                ),
            ),
            {"review_rounds": 0},
        )

    report = Report()
    current = manuscript_digest(project)
    checked: list[_Round] = []

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

        checked.append(_check_round(project, number, document, current, severity))

    # The latest round that describes the manuscript as it stands supersedes every outdated
    # round before it. A round that never finished is not rescued: a missing record is a
    # remit nobody answered, whenever it was.
    latest = max((r.number for r in checked if r.current), default=0)
    complete_rounds = 0
    readings = 0
    open_major: list[Open] = []
    for round_ in checked:
        superseded = round_.outdated and round_.number < latest
        report = report.merge(_superseded(round_, latest) if superseded else round_.report)
        complete_rounds += int(round_.current or (superseded and not round_.unfinished))
        open_major.extend(round_.unresolved)
        readings += round_.readings

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
        review_readings=readings,
    )


def _check_round(
    project: Project, number: int, panel: dict, current: str, severity: str
) -> _Round:
    report = Report()
    directory = round_dir(project, number)
    unresolved: list[Open] = []
    unfinished = behind = False
    # A record that lists no files read the whole manuscript, so one of those settles
    # coverage for the round. Otherwise coverage is the union of what the records listed.
    covered: set[str] = set()
    read_everything = False
    records = 0

    for reviewer in panel["reviewers"]:
        name = reviewer["id"]
        filed, problems, incomplete = _readings(project, number, reviewer, severity)
        report = report.merge(problems)
        unfinished = unfinished or incomplete

        for reading in filed:
            document = reading.document
            who = reading.who(name)
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
                behind = True
                named = f" ({', '.join(changed)})" if changed else ""
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="review-stale",
                        severity=severity,
                        message=f"round {number}: {who} reviewed an earlier manuscript{named}",
                        path=reading.path,
                        context=f"reviewed {document['reviewed_on']} by "
                        f"{document['reviewed_by']}",
                        hint="the text has changed since. Record a further round that reads "
                        "it as it stands (`manuscript-guard review --record <reviewer> "
                        "--round <n> --verdict <verdict>`); once that round is complete it "
                        "supersedes this one",
                    )
                )

            # Every reading's major findings bind, whoever else read the remit: another
            # reader's clean reading does not answer them.
            for finding in document.get("findings", []):
                if finding["severity"] == "major" and not _answered(finding):
                    unresolved.append(
                        Open(reviewer=who, finding_id=finding["id"], text=finding["finding"])
                    )

    # What makes per-file scoping honest. A record listing the files it read is judged on
    # those alone, which is only defensible while every manuscript file is on somebody's
    # list — otherwise "reviewed" would mean "reviewed the Methods", and a Discussion added
    # after the round would sail through as reviewed by people who never saw it.
    if records and not read_everything:
        uncovered = sorted(set(file_digests(project)) - covered)
        if uncovered:
            behind = True
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

    return _Round(number, report, unfinished, behind, tuple(unresolved), records)


@dataclass(frozen=True)
class ReadingSummary:
    reviewer: str
    reader: str | None
    verdict: str
    findings: int
    major: int
    open_major: int


@dataclass(frozen=True)
class RoundSummary:
    number: int
    panel: Path
    readings: tuple[ReadingSummary, ...]

    @property
    def strictest(self) -> ReadingSummary | None:
        """The reading with the strictest verdict; the first of them when several share it.

        Reported, and nothing more. G11 has never decided anything on a verdict: a record
        cannot be re-stamped, so a verdict could only be cleared by a further round, and the
        thing an author can act on is a finding. What blocks a submission is an unanswered
        major finding, from any reader.
        """
        if not self.readings:
            return None
        return max(self.readings, key=lambda reading: VERDICT_ORDER.index(reading.verdict))


def round_summaries(project: Project) -> list[RoundSummary]:
    """Who read what in each round and what each concluded, for `manuscript-guard review`.

    Only readings the gate counts: one that fails its schema or is misfiled is in the gate's
    report, not here.
    """
    summaries = []
    for number, path in panels(project):
        document = read_structured(path)
        if not validate(document, "panel", path, gate=GATE).ok or not isinstance(document, dict):
            continue
        readings = []
        for reviewer in document["reviewers"]:
            filed, _problems, _incomplete = _readings(project, number, reviewer, WARN)
            for reading in filed:
                majors = [
                    finding
                    for finding in reading.document.get("findings", [])
                    if finding["severity"] == "major"
                ]
                readings.append(
                    ReadingSummary(
                        reviewer=reviewer["id"],
                        reader=reading.reader,
                        verdict=reading.document["verdict"],
                        findings=len(reading.document.get("findings", [])),
                        major=len(majors),
                        open_major=sum(1 for finding in majors if not _answered(finding)),
                    )
                )
        summaries.append(RoundSummary(number, path, tuple(readings)))
    return summaries


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
