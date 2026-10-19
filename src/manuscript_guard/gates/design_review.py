"""G12 — a panel reads the plan before there are results.

A review panel reads the manuscript, which is written once the analysis has run: by then
the design is spent, and a reviewer who says the comparison cannot answer the question is
saying it too late. So a design round is a panel that reads `design/plan.md`, and the
feasibility results (`feasibility.*`), at the `design` stage. Its remits ask whether the
design supports the inference the plan intends, and name the risks of the study type:
confounding, selection, immortal time, missing data, multiplicity, leakage.

It is kept apart from the manuscript's rounds, in `review/design/`: `panel-<n>.yaml` names
the readers and their remits, and `round-<n>/<reviewer>.yaml` is a reading, written by
`manuscript-guard review --record <reviewer> --design --round <n> --verdict <verdict>` with
the digest of the plan it read. So a design round never counts toward the manuscript's
rounds, and a manuscript round never answers the design. A remit read more than once, by
several models or by a model and a person, is filed as a manuscript round's is: each reader
the panel lists for the reviewer under `readers` has a reading of its own,
`round-<n>/<reviewer>.<reader>.yaml` (`--reading <reader>`), and nothing else beside the
record is read.

A reading of a plan that has changed since is stale. A major finding not answered, by a
resolution or by an override with its reason, is a warning, and a failure at submission
only: what an unanswered design objection means is the author's to weigh while there is
still an analysis to change. An override, an objection left standing, is the
statistician's to accept, and is said until they sign it (`override_signables`). A reading
is sealed as a manuscript reading is (`review --seal <reviewer> --design --round <n>`), and
one changed after its seal fails at submission.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.gates.review import (
    _answered,
    _check_seal,
    files_beside,
    reading_slug,
    review_root,
)
from manuscript_guard.sign_offs import Signable, digest_of, settle

GATE = "G12"
DESIGN_DIR = "design"
SCHEMA = "manuscript-guard/design-review/1"
#: What every key a feasibility script emits opens with, as G12 asks for them.
FEASIBILITY = "feasibility."


def design_root(project: Project) -> Path:
    return review_root(project) / DESIGN_DIR


def design_panel_path(project: Project, round_number: int) -> Path:
    return design_root(project) / f"panel-{round_number}.yaml"


def design_record_path(
    project: Project, round_number: int, reviewer: str, reader: str | None = None
) -> Path:
    """Where one reading of a design remit is filed: the reviewer's plain record, or a named
    reader's beside it, as `gates.review.reading_path` files a manuscript round's."""
    name = reviewer if reader is None else f"{reviewer}.{reading_slug(reader)}"
    return design_root(project) / f"round-{round_number}" / f"{name}.yaml"


def design_panels(project: Project) -> list[tuple[int, Path]]:
    root = design_root(project)
    found = []
    for path in sorted(root.glob("panel-*.yaml")) if root.is_dir() else []:
        number = path.stem.split("-", 1)[1]
        if number.isascii() and number.isdigit():
            found.append((int(number), path))
    return sorted(found)


def plan_digest(project: Project) -> str:
    """What a design round reads: the plan's bytes, and each feasibility result's value and
    display, by key. A plan edited, or the data counted again, is another plan to read."""
    from manuscript_guard.gates.design import plan_path

    digest = hashlib.sha256()
    plan = plan_path(project)
    digest.update(plan.read_bytes() if plan.is_file() else b"")
    counted: dict[str, list] = {}
    results = project.path("results")
    for path in sorted(results.glob("*.json")) if results.is_dir() else []:
        try:
            document = read_structured(path)
        except ContractError:
            continue
        values = document.get("values") if isinstance(document, dict) else None
        for key, spec in (values or {}).items() if isinstance(values, dict) else ():
            if key.startswith(FEASIBILITY) and isinstance(spec, dict):
                counted[key] = [spec.get("value"), spec.get("display")]
    digest.update(json.dumps(counted, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


def check_design_rounds(project: Project, *, submission: bool = False) -> Report:
    """Each design round's readings against the plan as it stands, and their major
    findings answered."""
    found = design_panels(project)
    if not found:
        # Nothing, counts included: a project with no design round reads as it did before.
        return Report()
    severity = FAIL if submission else WARN
    current = plan_digest(project)
    report = Report()
    open_major = 0
    readings: list[tuple[int, tuple[str, str], str, Report, bool]] = []
    current_rounds = 0
    for number, path in found:
        try:
            panel = read_structured(path)
        except ContractError as exc:
            report = report.with_findings(_finding("design-panel-unreadable", str(exc), path))
            continue
        checked = validate(panel, "panel", path, gate=GATE)
        report = report.merge(checked)
        if not checked.ok or not isinstance(panel, dict):
            continue
        repeated = _repeated([reviewer["id"] for reviewer in panel["reviewers"]])
        if repeated:
            report = report.with_findings(_finding(
                "design-duplicate-reviewer",
                f"design round {number}: {', '.join(repeated)} appears more than once in the "
                "panel, so one record answers each of its remits", path, severity=severity,
                hint="give each reviewer a distinct id; two reviewers with the same remit are "
                "one reviewer",
            ))  # fmt: skip
        fresh_round = True
        for reviewer in _once_each(panel["reviewers"]):
            said, filed = _readings(project, number, reviewer, current, severity)
            report = report.merge(said)
            for who, label, read, fresh, opened in filed:
                readings.append((number, who, label, read, fresh))
                fresh_round = fresh_round and fresh
                open_major += opened
        current_rounds += int(fresh_round)
    # A stale reading is superseded by a later reading of the plan as it stands by the same
    # reader of the same remit: rounds 1 and 2 of #308, the further round the stale hint
    # asks for left it stale for good, and then a later round of one reviewer silenced the
    # others' too. Its open majors still bind: a later reading does not answer them.
    read_again: dict[tuple[str, str], int] = {}
    for number, who, _label, _read, fresh in readings:
        if fresh:
            read_again[who] = max(read_again.get(who, 0), number)
    for number, who, label, read, fresh in readings:
        later = read_again.get(who, 0)
        if not fresh and later > number:
            read = Report(tuple(
                replace(f, code="design-review-superseded", severity=INFO,
                        message=f"{f.message} [superseded by design round {later}]",
                        hint=f"{label} read the plan as it stands in design round {later}")
                if f.code == "design-review-stale" else f
                for f in read.findings
            ))  # fmt: skip
        report = report.merge(read)
    for signable in override_signables(project):
        report = report.with_findings(*settle(project, signable))
    return report.with_counts(
        design_rounds=len(found), design_rounds_current=current_rounds,
        design_open_major=open_major,
    )  # fmt: skip


def _repeated(names: list) -> list:
    """The names given more than once, each once, sorted."""
    return sorted({name for name in names if names.count(name) > 1}, key=str)


def _once_each(reviewers: list[dict]) -> list[dict]:
    """The panel's reviewers, one entry for each id: one record answers every slot sharing
    its id, so it is not read again, and its overrides not listed twice (round 1 of #313).
    The entry names the readers of every such slot, so that a reader named only by a later
    one is still read (round 1 of #348)."""
    merged: dict = {}
    for reviewer in reviewers:
        name = reviewer["id"]
        if name not in merged:
            merged[name] = dict(reviewer)
            continue
        readers = list(merged[name].get("readers") or ())
        readers += [r for r in reviewer.get("readers") or () if r not in readers]
        if readers:
            merged[name]["readers"] = readers
    return list(merged.values())


def _asked(
    project: Project, number: int, reviewer: dict, severity: str = WARN
) -> tuple[list[str | None], Report]:
    """Whose readings of one remit the round asks for: the reviewer's plain record, unless
    the panel names readers and there is none, and each reader the panel names. And what is
    wrong with the names: a reader whose name has no letter or digit, or two that would be
    filed as one, said as G11 says a reader it cannot file, a failure at submission (round 1
    of #315: it was always a warning)."""
    name = reviewer["id"]
    readers = [str(reader) for reader in reviewer.get("readers") or ()]
    plain = design_record_path(project, number, name)
    asked: list[str | None] = [None] if plain.is_file() or not readers else []
    report = Report()
    known: dict[str, str] = {}
    for reader in readers:
        slug = reading_slug(reader)
        if slug and slug not in known:
            known[slug] = reader
            asked.append(reader)
            continue
        report = report.with_findings(_finding(
            "design-reader-unnamed",
            f"design round {number}: {name}'s reader {reader!r} "
            + (f"would be filed as {known[slug]}'s reading" if slug else
               "has no letter or digit to name its file"),
            design_panel_path(project, number), severity=severity,
            hint="a reader is known by the letters and digits of its name; name each so "
            "that they differ in those, and list each once",
        ))  # fmt: skip
    return asked, report


def _readings(
    project: Project, number: int, reviewer: dict, current: str, severity: str
) -> tuple[Report, list[tuple[tuple[str, str], str, Report, bool, int]]]:
    """What is wrong with one remit's names and the files beside it, and each reading the
    round asks for: who made it, as (reviewer, reader's file name) and as it is shown, what
    it says, whether it read the plan as it stands, and how many of its major findings are
    open. A file beside the record that the panel names no reader for is said and not
    read, as G11 leaves one."""
    name = reviewer["id"]
    asked, report = _asked(project, number, reviewer, severity)
    filed = []
    for reader in asked:
        label = name if reader is None else f"{name} ({reader})"
        read, fresh, opened = _reading(project, number, name, reader, current, severity)
        filed.append(((name, reading_slug(reader) if reader else ""), label, read, fresh, opened))
    directory = design_record_path(project, number, name).parent
    named = {reading_slug(reader) for reader in asked if reader is not None}
    for slug, paths in files_beside(directory, name).items() if directory.is_dir() else ():
        for path in paths if slug not in named else ():
            report = report.with_findings(_finding(
                "design-reading-unnamed",
                f"design round {number}: {path.name} is not a reading the panel asks for, "
                "so it is not read", path, severity=WARN,
                hint=f"if it is a reading, add its reader to {name}'s `readers` in "
                f"{design_panel_path(project, number).name}; if it is a copy or a note, keep "
                "it outside the round",
            ))  # fmt: skip
    return report, filed


def override_signables(project: Project) -> list[Signable]:
    """Each major finding of a design round that is overridden and not resolved: the
    statistician signs the override, bound to the finding's words and to the reason given,
    so that a reason rewritten after the signature wants it again. An objection to the design
    left standing is a judgement of the design, and the author's reason alone does not settle
    it. A named reader's findings are signed apart from the plain record's: their ids are
    numbered by each reading."""
    out: list[Signable] = []
    for number, path in design_panels(project):
        panel = _read(path)
        if not validate(panel, "panel", path, gate=GATE).ok:
            continue
        for reviewer in _once_each(panel["reviewers"]):
            name = reviewer["id"]
            for reader in _asked(project, number, reviewer)[0]:
                record = design_record_path(project, number, name, reader)
                document = _read(record)
                if not validate(document, "design-review", record, gate=GATE).ok:
                    continue
                who = name if reader is None else f"{name}.{reading_slug(reader)}"
                out += _overridden(number, who, document, record)
    return out


def _overridden(number: int, who: str, document: dict, record: Path) -> list[Signable]:
    out = []
    for finding in document.get("findings") or []:
        reason = str(finding.get("overridden") or "").strip()
        if finding.get("severity") != "major" or not reason or \
                str(finding.get("resolution") or "").strip():  # fmt: skip
            continue
        key = f"{GATE}/design-override/{number}/{who}/{finding['id']}"
        raised = _finding(
            "design-override-unsigned",
            # What was overridden, and why; who signs is the hint's, as `settle` writes it
            # (round 1 of #313: "nobody has signed" stayed once signed).
            f"design round {number}: {who} {finding['id']} is overridden "
            f"({reason if len(reason) <= 100 else reason[:99] + '…'})",
            record, severity=WARN,
        )  # fmt: skip
        digest = digest_of(key, finding.get("finding"), reason)
        out.append(Signable("statistician", key, digest, (raised,)))
    return out


def _read(path: Path) -> dict:
    """A panel or a reading as a mapping, or an empty one where it cannot be read: the
    rounds' own check says why."""
    try:
        document = read_structured(path)
    except ContractError:
        return {}
    return document if isinstance(document, dict) else {}


def _reading(
    project: Project, number: int, name: str, reader: str | None, current: str, severity: str
) -> tuple[Report, bool, int]:
    """What one reading says: the report, whether it read the plan as it stands, and how
    many of its major findings are open."""
    path = design_record_path(project, number, name, reader)
    label = name if reader is None else f"{name} ({reader})"
    named = "" if reader is None else f" --reading {_quoted(reader)}"
    report = Report()
    if not path.is_file():
        return report.with_findings(_finding(
            "design-review-missing", f"design round {number}: {label} has not read the plan",
            path, severity=WARN,
            hint=f"once they have, `manuscript-guard review --record {name} --design --round "
            f"{number}{named} --verdict <verdict>`",
        )), False, 0  # fmt: skip
    try:
        document = read_structured(path)
    except ContractError as exc:
        return report.with_findings(_finding("design-review-unreadable", str(exc), path)), \
            False, 0  # fmt: skip
    checked = validate(document, "design-review", path, gate=GATE)
    if not checked.ok or not isinstance(document, dict):
        return report.merge(checked), False, 0
    misfiled = _misfiled(document, number, name, reader)
    if misfiled is not None:
        return report.with_findings(_finding(
            "design-reading-misfiled", f"design round {number}: {path.name} {misfiled}",
            path, severity=severity,
            hint="a reading is filed under its reviewer and its reader, and says the same "
            "inside; it is not counted until it does",
        )), False, 0  # fmt: skip
    fresh = document["plan_sha256"] == current
    if not fresh:
        report = report.with_findings(_finding(
            "design-review-stale",
            f"design round {number}: {label} read a plan that has changed since", path,
            severity=WARN, context=f"read {document['reviewed_on']} by "
            f"{document['reviewed_by']}",
            hint="the plan or the feasibility results changed after the reading; record a "
            "further design round that reads the plan as it stands",
        ))  # fmt: skip
    sealed = _check_seal(path, document, number, label, severity)
    report = report.with_findings(*(
        replace(f, gate=GATE, code=f"design-{f.code}", message=f"design {f.message}",
                hint=(f.hint or "").replace(
                    "review --seal <reviewer> --round <n>`, with `--reading <reader>` for a "
                    "named reading",
                    f"review --seal {name} --design --round {number}{named}`"))
        for f in sealed.findings
    ))  # fmt: skip
    # An override is signed by its finding's id, so two findings of one id share one
    # sign-off, and either answers for the other (round 1 of #313).
    repeated = _repeated([f.get("id") for f in document.get("findings") or [] if f.get("id")])
    if repeated:
        report = report.with_findings(_finding(
            "design-finding-id-repeated",
            f"design round {number}: {label} gives {', '.join(map(str, repeated))} to more "
            "than one finding", path, severity=severity,
            hint="number each finding of a reading once: an answer and a sign-off are held to "
            "the finding by its id",
        ))  # fmt: skip
    opened = 0
    for finding in document.get("findings") or []:
        if finding.get("severity") == "major" and not _answered(finding):
            opened += 1
            report = report.with_findings(_finding(
                "design-major-open",
                f"design round {number}: {label} {finding.get('id')}: "
                f"{str(finding.get('finding', ''))[:120]}", path, severity=severity,
                hint="answer it in `resolution` with what the plan now does, or in "
                "`overridden` with why it stands; a design objection answered before the "
                "analysis is one the analysis can still meet",
            ))  # fmt: skip
    return report, fresh, opened


def _misfiled(document: dict, number: int, name: str, reader: str | None) -> str | None:
    """Why a named reading is not the one its file name says, or None. The reviewer's plain
    record is read as it stands, as G11 reads a manuscript round's."""
    if reader is None:
        return None
    said = document.get("reader")
    if reading_slug(str(said or "")) != reading_slug(reader):
        return f"is {reader}'s reading and says its reader is {said or 'nobody'}"
    if document["reviewer"] != name:
        return f"says it is {document['reviewer']}'s remit"
    if document["round"] != number:
        return f"says it is of design round {document['round']}"
    return None


def _quoted(reader: str) -> str:
    """A reader's name as it is typed after `--reading`: in quotes where it has a space."""
    return f'"{reader}"' if any(char.isspace() for char in reader) else reader


def _finding(
    code: str, message: str, path: Path, *, severity: str = FAIL, hint: str | None = None,
    context: str | None = None,
) -> Finding:
    return Finding(gate=GATE, code=code, severity=severity, message=message, path=path,
                   hint=hint, context=context)  # fmt: skip
