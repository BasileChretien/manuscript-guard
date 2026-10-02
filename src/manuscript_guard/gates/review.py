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

    Letters and digits of any script are kept, lower-cased, and every run of anything else
    is one hyphen. Empty for a name with no letter or digit in it, which names no file.

    This is also what makes two spellings one reader. The panel's `Dr. Tanaka` and a reading
    filed as `Dr Tanaka` are the same file, so they are the same reader: matched letter for
    letter, the gate asked for a file that existed and `review --record` refused to write it.
    """
    kept = "".join(char if char.isalnum() else "-" for char in reader.lower())
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


def reading_files(directory: Path, reviewer: str) -> list[Path]:
    """Every record of one remit in a round: the plain one, then the named ones by name.

    Files only. A folder named like a reading is nothing to the gate, as it was before
    readings had names.
    """
    plain = directory / f"{reviewer}.yaml"
    named = sorted(path for path in directory.glob(f"{reviewer}.*.yaml") if path.is_file())
    return [*([plain] if plain.exists() else []), *named]


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
    """One reading of a remit that can be read: it fits the schema and is filed as itself."""

    path: Path
    reader: str | None
    document: dict

    def who(self, reviewer: str) -> str:
        return reviewer if self.reader is None else f"{reviewer} [{self.reader}]"


def _misfiled(path: Path, reviewer: str, number: int, document: dict) -> str | None:
    """Why a record that names a reader is not what its place says it is, or None when it is.

    The file name is how a reader the panel named is looked for. A record under one reader's
    name that says another's inside is one reading standing in for two, and the same goes
    for a record copied from another remit or another round.

    The reviewer's plain record is held to the last two as soon as it names a reader, since
    it then answers for that reader. Checked for named files only, another remit's reading
    copied over `desk-editor.yaml` satisfied the panel while the same copy under the
    reader's own file name was refused. A plain record that names no reader is read as it
    always was.
    """
    reader = str(document["reader"])
    slug = reading_slug(reader)
    if not slug:
        return f"names a reader, {reader!r}, with no letter or digit to name a file by"
    if path.name != f"{reviewer}.yaml":
        named = path.name[len(reviewer) + 1 : -len(".yaml")]
        if slug != named:
            return f"says its reader is {reader}, whose reading is filed as {reviewer}.{slug}.yaml"
    if document["reviewer"] != reviewer:
        return f"says it is {document['reviewer']}'s remit"
    if document["round"] != number:
        return f"says it is of round {document['round']}"
    return None


#: A line of a file that could not be parsed, saying it is somebody's reading.
_READER_LINE = re.compile("(?m)^reader[ \t]*:")


def _is_a_reading(path: Path, reviewer: str, expected: frozenset[str]) -> bool:
    """Whether a file that cannot be parsed is a reading rather than a note or a copy.

    It is one if it is filed under the name of a reader the panel asks for, or if it says
    `reader:` on a line of its own. A reading is edited by hand, to answer its findings, and
    `resolution: Fixed: it now says reporting` is not YAML: the file stopped parsing, and
    counted as a note, the reading's other findings stopped binding with it.
    """
    if path.name[len(reviewer) + 1 : -len(".yaml")] in expected:
        return True
    try:
        text = path.read_bytes()[:65536].decode("utf-8", errors="replace")
    except OSError:
        return False
    return _READER_LINE.search(text) is not None


def _filed(
    directory: Path,
    reviewer: str,
    number: int,
    severity: str,
    expected: frozenset[str] = frozenset(),
) -> tuple[list[_Filed], Report, bool]:
    """The readings of one remit, what is wrong with those that cannot be read, and whether
    any was refused. `expected` holds the file-name form of the readers the panel names."""
    report = Report()
    found: list[_Filed] = []
    refused = False
    for path in reading_files(directory, reviewer):
        plain = path.name == f"{reviewer}.yaml"
        unreadable = False
        if plain:
            # As it always was: a reviewer's own record that cannot be parsed stops the gate.
            document = read_structured(path)
        else:
            # Before readings had names nothing opened a file such as
            # `biostatistician.files.yaml`, so whatever it holds must not take the gate
            # down: UTF-16 from a shell redirect, a note in another code page, a date that
            # does not exist. PyYAML raises a plain ValueError for the last.
            try:
                document = read_structured(path)
            except (ContractError, OSError, ValueError):
                document, unreadable = None, True
        if unreadable and _is_a_reading(path, reviewer, expected):
            refused = True
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="reading-unreadable",
                    message=f"round {number}: {path.name} cannot be read as a review record",
                    path=path,
                    hint="it is a reading, and while it cannot be parsed nothing in it is "
                    "counted, its unanswered findings included. A value that holds a colon "
                    "and a space needs quotes: resolution: 'Fixed: it now says reporting'",
                )
            )
            continue
        if not plain and not (isinstance(document, dict) and document.get("reader")):
            # Until readings had names, a file such as `biostatistician.old.yaml` beside a
            # record was nothing to the gate, and a copy kept there must not start failing
            # a submission. It is said, because a reading that lost its `reader` line would
            # otherwise drop out of the round in silence, findings and all.
            what = "cannot be read and names no reader" if unreadable else "names no reader"
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="reading-unnamed",
                    severity=WARN,
                    message=f"round {number}: {path.name} {what}, so it is not counted as "
                    f"a reading of {reviewer}",
                    path=path,
                    hint="a reading beside a reviewer's record says who made it in "
                    "`reader:`. If this is a copy or a note, keep it outside the round",
                )
            )
            continue
        schema_report = validate(document, "review", path, gate=GATE)
        report = report.merge(schema_report)
        if not schema_report.ok or not isinstance(document, dict):
            refused = True
            continue
        if document.get("reader"):
            why = _misfiled(path, reviewer, number, document)
            if why is not None:
                refused = True
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="reading-misfiled",
                        severity=severity,
                        message=f"round {number}: {path.name} {why}",
                        path=path,
                        hint="a reading is filed as <reviewer>.<reader>.yaml and says the "
                        "same inside. It is not counted until it does; a reading by "
                        "another reader is another record "
                        "(`manuscript-guard review --record <reviewer> --reading <reader>`)",
                    )
                )
                continue
        found.append(_Filed(path, document.get("reader") or None, document))
    return found, report, refused


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
        expected = [str(reader) for reader in reviewer.get("readers") or ()]
        filed, problems, refused = _filed(
            directory,
            name,
            number,
            severity,
            frozenset(reading_slug(reader) for reader in expected) - {""},
        )
        report = report.merge(problems)
        unfinished = unfinished or refused

        # Who has read this remit. A panel that names the readers of a remit is held to each
        # of them: with every model reading every remit, one provider failing must not leave
        # a round that looks complete. A panel that names none needs one reading, by
        # anybody, which is how every round was read before readings had names.
        #
        # A reader is known by the form of its name that names its file, so the panel's
        # `Dr. Tanaka` is the reader of `desk-editor.dr-tanaka.yaml` however that record
        # punctuates it.
        by_reader: dict[str, Path] = {}
        for reading in filed:
            if reading.reader is None:
                continue
            known = reading_slug(reading.reader)
            if known in by_reader:
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="duplicate-reading",
                        severity=severity,
                        message=f"round {number}: {name} has two readings by "
                        f"{reading.reader} ({by_reader[known].name} and "
                        f"{reading.path.name})",
                        path=reading.path,
                        hint="one reader reads a remit once in a round; a second reading "
                        "of a changed manuscript is a further round",
                    )
                )
            else:
                by_reader[known] = reading.path

        for reader in expected:
            known = reading_slug(reader)
            if known in by_reader:
                continue
            unfinished = True
            if known:
                where = reading_path(project, number, name, reader)
                hint = (
                    "the panel names this reader for the remit. File its reading, or take "
                    "the reader out of the panel if it is not going to report"
                )
            else:
                where = panel_path(project, number)
                hint = (
                    "a reader's name needs a letter or a digit: it names the file the "
                    "reading is filed in. Give this reader a name in the panel"
                )
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="reading-missing",
                    severity=severity,
                    message=f"round {number}: {name} has no reading by {reader}",
                    path=where,
                    context=reviewer["remit"][:140],
                    hint=hint,
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
            filed, _problems, _refused = _filed(
                round_dir(project, number), reviewer["id"], number, WARN
            )
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
