"""G12 — is the paper the study that was registered?

A registration says, before the study, what it will measure and how. Outcome switching is the
paper reporting something else: a registered primary outcome dropped or demoted, a secondary
one promoted, an outcome nobody registered reported as though it had been, all said nowhere.
And a study registered after it started, or after its first results, registered nothing in
advance. Both are well documented, by COMPare for trials among others, and both go unnoticed
when the registration number is read as a token and nothing more.

`paper.yaml` lists the registrations, and under each the author quotes the outcomes the
registry holds, with the role each has there and the planned result that reports it. The
registry's record is kept in `design/registrations/` by `lookup --registrations`. This reads
both, offline, and holds them to each other exactly:

* the identifier is in the manuscript, has a record, and the registry knows it;
* it was registered before the study's actual start as the registry gives it, the start of
  its data analysis, and the first results (`design/plan.frozen.yaml`), unless `paper.yaml`
  gives the reason and the manuscript says it was registered retrospectively;
* each quoted outcome is word for word in the registry's record, in a field of the role
  given where the registry keeps primary and secondary apart, and in the first version where
  the registration was updated; its result is one the plan lists and the analysis reports;
* a registered outcome the paper does not report, and a reported one that was not registered
  or was registered in another role, is named in the plan's Deviations section;
* where the registry lists its outcomes apart, every primary one is quoted.

Whether the quoted words mean the outcome the paper measures is not decided here: that is the
panel's and the co-authors'. A mismatch warns while the paper is drafted and fails at
submission, as the author decided; an identifier that is missing or unknown fails from
internal review.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from manuscript_guard.contracts._schema import ContractError, read_structured, read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.emit import FROZEN_PLAN
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.gates import design
from manuscript_guard.registrations import (
    ASKED,
    EU_PAS,
    NAMED_IN_TEXT,
    NAMES,
    OSF,
    Declared,
    Outcome,
    declared,
    digest_holds,
    file_name,
    read_record,
    record_path,
)
from manuscript_guard.text.masking import blank_comments
from manuscript_guard.text.reader import manuscript_files

GATE = "G12"
PAPER = Path("paper.yaml")
#: The words a manuscript says a late registration with, a line break or two between them:
#: "registered", "registration", never "registry" (round 1 of #390: "a retrospective
#: registry-based cohort" said it).
RETROSPECTIVE = re.compile(
    r"(?i)\bretrospective(?:ly)?\s+regist(?:ered|ration)\b"
    r"|\bregist(?:ered|ration)\s+(?:was\s+)?retrospective(?:ly)?\b"
)
#: The designs a registry calls observational, and the one it calls interventional.
OBSERVATIONAL = frozenset({"cohort", "case-control", "self-controlled", "disproportionality"})
#: What ISRCTN writes in the field for a trial that has none.
_NONE_REGISTERED = re.compile(r"(?i)^\s*(?:there are\s+)?no secondary outcome measures?\W*$")
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = {**dict.fromkeys(map(ord, "‘’‚‛′"), "'"),
           **dict.fromkeys(map(ord, "“”„″"), '"')}  # fmt: skip


def fold(text: str) -> str:
    """Words as they are compared: compatibility forms, case, dashes, quotation marks and
    spacing folded, so that a quote copied from a page or wrapped by YAML is what it was."""
    text = unicodedata.normalize("NFKC", text).translate(_DASHES).translate(_QUOTES)
    return " ".join(text.casefold().split())


def says_retrospective(text: str) -> bool:
    return bool(RETROSPECTIVE.search(text))


def named_in(text: str, entry: Declared) -> bool:
    """Whether the manuscript gives the registration's identifier."""
    if entry.registry == OSF:
        pattern = rf"(?i)osf\.io/{re.escape(entry.id.rsplit('/', 1)[-1])}(?![a-z0-9])"
    elif entry.registry == EU_PAS:
        pattern = rf"(?i)(?<![A-Za-z0-9])EU\s?PAS\s?{re.escape(entry.id[5:])}(?![0-9])"
    else:
        pattern = rf"(?i)(?<![A-Za-z0-9]){re.escape(entry.id)}(?![A-Za-z0-9])"
    return bool(re.search(pattern, text))


def _finding(code: str, message: str, severity: str, path: Path | None, hint: str) -> Finding:
    return Finding(gate=GATE, code=code, message=message, severity=severity, path=path,
                   hint=hint)  # fmt: skip


@dataclass(frozen=True)
class _Context:
    """What every registration is held to: the manuscript, the plan, the results."""

    project: Project
    text: str
    deviations: str
    planned: list[design.Planned] | None
    results: Results | None
    frozen: str | None
    #: Whether the first results were written from synthetic inputs only.
    dry_run: bool
    late: str
    stage: str | None


def _manuscript(project: Project) -> str:
    return "\n".join(blank_comments(read_text(p)) for p in manuscript_files(project))


def _first_results(project: Project) -> tuple[str | None, bool]:
    """The day the first results were written, as the plan's frozen copy records it, and
    whether they were written from synthetic inputs only: a dry run, which dates nothing
    of the study."""
    try:
        record = read_structured(project.root / FROZEN_PLAN)
    except ContractError:
        return None, False
    if not isinstance(record, dict):
        return None, False
    stamp = record.get("frozen_at")
    day = stamp[:10] if isinstance(stamp, str) and re.match(r"\d{4}-\d{2}-\d{2}", stamp) else None
    return day, record.get("synthetic") is True


def _context(project: Project, results: Results | None, stage: str | None) -> _Context:
    from manuscript_guard.policy import SUBMISSION

    path = design.plan_path(project)
    plan = design._read_plan(path)[0] if path.is_file() else ""
    frozen, dry_run = _first_results(project)
    return _Context(
        project=project,
        text=_manuscript(project),
        deviations=design.deviations_said(plan),
        planned=design.planned_results(plan) if plan else None,
        results=results,
        frozen=frozen,
        dry_run=dry_run,
        late=FAIL if stage == SUBMISSION else WARN,
        stage=stage,
    )


def check_registration(
    project: Project, results: Results | None = None, stage: str | None = None
) -> Report:
    """Each registration `paper.yaml` lists, held to its record, the manuscript and the plan."""
    entries = declared(project)
    paper = project.root / PAPER
    if not entries:
        return _undeclared(project, paper)
    context = _context(project, results, stage)
    report = Report()
    outcomes = 0
    for entry in entries:
        report = report.merge(_one(context, entry, paper))
        outcomes += len(entry.outcomes)
    return report.with_counts(registrations=len(entries), registered_outcomes=outcomes)


def _undeclared(project: Project, paper: Path) -> Report:
    """A trial with no registration, and identifiers the manuscript gives that `paper.yaml`
    does not list. Where it lists any, the others are taken to be other studies'."""
    findings = []
    if project.study_type == "trial":
        findings.append(_finding(
            "registration-missing",
            "paper.yaml names the study a trial and lists no registration", FAIL, paper,
            "a trial is registered before its first participant; list it under `registration` "
            "with its identifier, so that the paper can be held to it",
        ))  # fmt: skip
    named = sorted(set(NAMED_IN_TEXT.findall(_manuscript(project))))
    if named:
        findings.append(_finding(
            "registration-undeclared",
            f"the manuscript gives {', '.join(named)}, and paper.yaml lists no registration",
            WARN, paper,
            "if one is this study's registration, list it under `registration` in paper.yaml "
            "and run `manuscript-guard lookup --registrations`; if each is another study's, "
            "nothing is needed",
        ))  # fmt: skip
    # No count where nothing is listed: a paper with no registration reads as it did before.
    return Report(tuple(findings))


def _one(context: _Context, entry: Declared, paper: Path) -> Report:
    if entry.id is None and entry.named:
        # Round 2 of #390: the registry was named, and the finding said it was not.
        name = NAMES.get(entry.named.strip().lower(), entry.named)
        return Report((_finding(
            "registration-id-malformed",
            f"registration {entry.written!r} in paper.yaml is not written as {name} writes its "
            "identifiers", FAIL, paper,
            "write it as the registry does, its letters and digits with no space between them: "
            "NCT04368728, EUPAS1000000417, ISRCTN17072692, osf.io/abcde, CRD42020123456",
        ),))  # fmt: skip
    if entry.id is None:
        return Report((_finding(
            "registration-id-malformed",
            f"registration {entry.written!r} in paper.yaml is not an identifier of a registry "
            "manuscript-guard knows, and no `registry:` is given", FAIL, paper,
            "write it as the registry does (NCT04368728, EUPAS1000000417, ISRCTN17072692, "
            "osf.io/abcde, CRD42020123456), or name the registry under `registry:`",
        ),))  # fmt: skip
    report = Report()
    if not named_in(context.text, entry):
        report = report.with_findings(_finding(
            "registration-not-in-manuscript",
            f"the manuscript does not give the registration {entry.id}", FAIL, paper,
            "give the registry and the identifier where the journal asks for them, usually at "
            "the end of the abstract and in the Methods",
        ))  # fmt: skip
    record, problem = _record(context.project, entry)
    if problem is not None:
        return report.with_findings(problem)
    return report.merge(_held(context, entry, record))


_AGAIN = "delete it and run `lookup --registrations` again"


def _record(project: Project, entry: Declared) -> tuple[dict[str, Any] | None, Finding | None]:
    """The registration's record, or the finding that says why there is none to read."""
    path = record_path(project, entry.id)
    name = NAMES.get(entry.registry, entry.registry)

    def failed(code: str, message: str, hint: str) -> tuple[None, Finding]:
        return None, _finding(code, message, FAIL, path, hint)

    if not path.is_file():
        if entry.registry in ASKED:
            how = "run `manuscript-guard lookup --registrations`"
        else:
            how = (f"{name} is not asked: copy its record by hand into design/registrations/"
                   f"{file_name(entry.id)}, with `source: by-hand`, who copied it and when")
        return failed("registration-not-looked-up",
                      f"registration {entry.id} has no record of what {name} holds", how)
    try:
        record = read_record(path)
    except ContractError as exc:
        return failed("registration-record-unreadable",
                      f"{path.name} is not a registration record: {exc}",
                      "it is written by `lookup --registrations`; delete it and run that "
                      "again, or put a by-hand record right")
    if record["id"] != entry.id:
        return failed("registration-record-misfiled",
                      f"{path.name} holds the record of {record['id']}, not {entry.id}", _AGAIN)
    if not digest_holds(record):
        return failed("registration-record-edited",
                      f"the record of {entry.id} no longer says what {name} said",
                      "what a registry said is not the author's to edit; " + _AGAIN)
    day = record.get("asked_on") or record.get("copied_on")
    if day and day > date.today().isoformat():
        return failed("registration-date-future",
                      f"the record of {entry.id} is dated {day}, in the future", _AGAIN)
    return record, None


def _held(context: _Context, entry: Declared, record: dict[str, Any]) -> Report:
    path = record_path(context.project, entry.id)
    name = NAMES.get(entry.registry, entry.registry)
    if record["status"] == "absent":
        return Report((_finding(
            "registration-unknown", f"{name} does not know {entry.id}: {record['why']}", FAIL,
            path, "check the identifier against the registry's page; a registration that "
            "cannot be found registers nothing",
        ),))  # fmt: skip
    if record["status"] == "unresolvable":
        return Report((_finding(
            "registration-unanswered",
            f"{name} did not answer for {entry.id} ({record['why']}): nothing is known of it",
            WARN, path, "run `manuscript-guard lookup --registrations` again",
        ),))  # fmt: skip
    report = Report()
    if record.get("source") == "by-hand":
        report = report.with_findings(_finding(
            "registration-by-hand",
            f"the record of {entry.id} was copied by hand by {record['copied_by']} on "
            f"{record['copied_on']}: what it says is theirs, not the registry's", INFO, path,
            "a co-author can hold it to the registry's page",
        ))  # fmt: skip
    for check in (_withdrawn, _design, _timing, _outcomes):
        report = report.merge(check(context, entry, record, path))
    return report


def _withdrawn(context: _Context, entry: Declared, record: dict, path: Path) -> Report:
    if not record.get("withdrawn"):
        return Report()
    return Report((_finding(
        "registration-withdrawn", f"{entry.id} is withdrawn: the registry no longer stands "
        "behind it", context.late, path,
        "cite the registration that stands, or say in the manuscript why this one was withdrawn",
    ),))  # fmt: skip


def _design(context: _Context, entry: Declared, record: dict, path: Path) -> Report:
    kind = context.project.study_type
    wanted = "interventional" if kind == "trial" else (
        "observational" if kind in OBSERVATIONAL else None)  # fmt: skip
    said = record.get("study_type")
    if wanted is None or said is None or said == wanted:
        return Report()
    return Report((_finding(
        "registration-design-differs",
        f"paper.yaml names the study a {kind}, and {entry.id} registers an {said} study",
        context.late, path, "check the identifier: it may be another study's; or correct "
        "`study_type`",
    ),))  # fmt: skip


def _after(registered: str, other: str) -> bool:
    """Whether a date falls after another, as far as the less precise of the two goes: a
    study registered on 2020-04-27 that started in 2020-04 may have started after it."""
    width = min(len(registered), len(other))
    return registered[:width] > other[:width]


def _timing(context: _Context, entry: Declared, record: dict, path: Path) -> Report:
    dates = record["dates"]
    registered = dates["registered"]
    asked = record.get("asked_on") or record.get("copied_on") or ""
    late = [
        f"{what} ({dates[key]})"
        for key, what in (("study_start", "the study's start"),
                          ("analysis_start", "the start of its data analysis"))  # fmt: skip
        # A date after the day the registry was asked is a plan, not a start.
        if dates.get(key) and dates[key][:10] <= asked and _after(registered, dates[key])
    ]
    noted = Report()
    if context.frozen and _after(registered, context.frozen):
        if context.dry_run:
            noted = Report((_finding(
                "registration-after-dry-run",
                f"{entry.id} was registered on {registered}, after the first results "
                f"({context.frozen}), which were written from synthetic inputs only: they are "
                "not taken for the study's first results", INFO, path,
                f"{FROZEN_PLAN.as_posix()} says so; the study's own start dates still apply",
            ),))  # fmt: skip
        else:
            late.append(f"the first results ({context.frozen}, by {FROZEN_PLAN.as_posix()})")
    if not late:
        return noted
    said = f"{entry.id} was registered on {registered}, after {' and '.join(late)}"
    if entry.retrospective and says_retrospective(context.text):
        return noted.with_findings(_finding("registration-retrospective",
                                            said + ", as the paper says", INFO, path,
                                            entry.retrospective))  # fmt: skip
    if entry.retrospective:
        return noted.with_findings(_finding(
            "registration-retrospective-unsaid",
            said + "; paper.yaml gives the reason and the manuscript does not say it",
            context.late, context.project.root / PAPER,
            "say in the manuscript, where it gives the identifier, that the study was "
            "registered retrospectively, and why",
        ))  # fmt: skip
    return noted.with_findings(_finding(
        "registration-late", said, context.late, path,
        "a registration made after the study started, or after its results were known, "
        "registered nothing in advance: give the reason under `retrospective` in paper.yaml "
        "and say in the manuscript that it was registered retrospectively",
    ))  # fmt: skip


# ------------------------------------------------------------------------------ outcomes


def as_planned(written: str) -> design.Planned | None:
    """A `reported_as` as the plan's Planned results would list it, or None where it is not
    written as a key: `ror.point`, `results.dose`, `ror.*`."""
    if group := design._PLANNED_GROUP.fullmatch(written):
        return design.Planned(group.group(1), True, 0)
    if key := design._PLANNED_KEY.fullmatch(written):
        return design.Planned(next(part for part in key.groups() if part), False, 0)
    return None


def _in_plan(planned: list[design.Planned] | None, wanted: design.Planned) -> bool:
    """Whether the plan lists the key, or a group it falls in."""
    for item in planned or []:
        if item.key == wanted.key and item.group == wanted.group:
            return True
        if item.group and wanted.key.startswith(f"{item.key}."):
            return True
    return False


def _matched(quotes: list[str], sections: list[dict]) -> set[int]:
    """The sections each quote can be given to, one quote to one section at most, as many
    as can be: one vague quote found in five registered outcomes stands for one of them."""
    holds = [[i for i, s in enumerate(sections) if q in fold(s["text"])] for q in quotes]
    given: dict[int, int] = {}

    def place(quote: int, tried: set[int]) -> bool:
        for section in holds[quote]:
            if section in tried:
                continue
            tried.add(section)
            if section not in given or place(given[section], tried):
                given[section] = quote
                return True
        return False

    for quote in range(len(quotes)):
        place(quote, set())
    return set(given)


def _short(text: str, width: int = 90) -> str:
    line = " ".join(text.split())
    return line if len(line) <= width else line[: width - 1].rstrip() + "…"


def _outcomes(context: _Context, entry: Declared, record: dict, path: Path) -> Report:
    paper = context.project.root / PAPER
    if not entry.outcomes_given:
        return Report((_finding(
            "registration-outcomes-undeclared",
            f"paper.yaml quotes none of the outcomes {entry.id} registers", context.late, paper,
            "under the registration, list each registered outcome in the registry's words with "
            "its role and the planned result that reports it (`registered`, `role`, "
            "`reported_as`); one not reported has no `reported_as`",
        ),))  # fmt: skip
    sections = record["sections"]
    first = (record.get("first_version") or {}).get("sections")
    held = first if first is not None else sections
    separated = any(s.get("role") in ("primary", "secondary") for s in sections)
    pool = [s for s in held if s.get("role")] or held
    findings: list[Finding] = []
    for outcome in entry.outcomes:
        later = sections if first is not None else None
        findings += _registered(context, entry, outcome, pool, later, separated, path)
        findings += _reported(context, entry, outcome, paper)
    if separated:
        findings += _unquoted(context, entry, held, path)
    elif entry.outcomes:
        findings.append(_finding(
            "registration-roles-unchecked",
            f"{entry.id} gives its outcomes as text, not as primary and secondary apart: the "
            "role of each, and whether every registered outcome is quoted, is not checked",
            INFO, path, "a co-author or the panel can hold the quotes to the registry's record",
        ))  # fmt: skip
    return Report(tuple(findings))


def _registered(context, entry, outcome: Outcome, pool, later, separated, path) -> list[Finding]:
    """Whether the quote is the registry's, in the role given, in the first version."""
    quote = fold(outcome.registered)
    key = as_planned(outcome.reported_as) if outcome.reported_as else None
    if key is not None and design._named(context.deviations, key):
        return []
    said = f"{entry.id}: the {outcome.role} outcome {_short(outcome.registered, 60)!r}"
    found = [s for s in pool if quote and quote in fold(s["text"])]
    if not found:
        added = later is not None and any(quote in fold(s["text"]) for s in later)
        if added:
            code, where = ("registration-outcome-added-later",
                           "is in the registration only since it was updated")
        else:
            code, where = ("registration-outcome-not-registered",
                           "is not in the registry's record of its outcomes")
        return [_finding(code, f"{said} {where}", context.late, path,
                         "quote the registry's own words; an outcome reported and not "
                         "registered is named, with its key, under Deviations from the plan")]
    roles = {s.get("role") for s in found}
    demoted = outcome.role == "secondary" and roles == {"primary"}
    promoted = outcome.role == "primary" and "primary" not in roles
    if separated and (demoted or promoted):
        other = "primary" if demoted else (
            "other pre-specified" if roles == {"other"} else "secondary")  # fmt: skip
        return [_finding(
            "registration-outcome-role-changed",
            f"{said} is registered among the {other} outcomes", context.late, path,
            "report it in the role it was registered in, or name its key under Deviations from "
            "the plan with why the role changed",
        )]  # fmt: skip
    return []


def _reported(context: _Context, entry: Declared, outcome: Outcome, paper: Path) -> list[Finding]:
    """Whether the result that reports it is planned and reported, or its absence said."""
    from manuscript_guard.policy import DESIGN

    said = f"{entry.id}: the {outcome.role} outcome {_short(outcome.registered, 60)!r}"
    if outcome.reported_as is None:
        if fold(outcome.registered) in fold(context.deviations):
            return []
        return [_finding(
            "registration-outcome-dropped", f"{said} is not reported, and the plan's "
            "Deviations section does not say so", context.late, design.plan_path(context.project),
            "quote the registered outcome under Deviations from the plan with why it is not "
            "reported, or name the result that reports it under `reported_as`",
        )]  # fmt: skip
    key = as_planned(outcome.reported_as)
    if key is None or not _in_plan(context.planned, key):
        return [_finding(
            "registration-outcome-unplanned",
            f"{said} is reported as {outcome.reported_as}, which the plan's Planned results do "
            "not list", context.late, paper,
            "name it as the plan lists it, `ror.point`, `results.dose` or `ror.*`, and list it "
            "under Planned results",
        )]  # fmt: skip
    if context.results is None or context.stage in (None, DESIGN):
        return []
    quoted = design._emitted(context.results, key)
    if any(quoted) or design._named(context.deviations, key):
        return []
    return [_finding(
        "registration-outcome-unreported",
        f"{said} is reported as {outcome.reported_as}, and the analysis "
        + ("emits it with quoted=False" if quoted else "emits nothing under it"),
        context.late, paper, "report it, or name its key under Deviations from the plan",
    )]  # fmt: skip


def _unquoted(context: _Context, entry: Declared, held: list[dict], path: Path) -> list[Finding]:
    """The outcomes a registry lists apart that no quote stands for."""
    listed = [s for s in held if s.get("role") in ("primary", "secondary", "other")
              and not _NONE_REGISTERED.match(s["text"])]  # fmt: skip
    taken = _matched([fold(o.registered) for o in entry.outcomes if o.registered.strip()], listed)
    left = [s for i, s in enumerate(listed) if i not in taken]
    findings = [
        _finding(
            "registration-primary-unquoted",
            f"{entry.id}'s {s['label'].lower()}, {_short(s['text'])!r}, is quoted by no "
            "outcome in paper.yaml", context.late, path,
            "quote it under the registration, with the result that reports it, or with none "
            "and the same words under Deviations from the plan",
        )
        for s in left if s.get("role") == "primary"
    ]
    rest = [s["label"] for s in left if s.get("role") != "primary"]
    if rest:
        findings.append(_finding(
            "registration-secondary-unquoted",
            f"{len(rest)} of the outcomes {entry.id} registers besides its primary ones are "
            f"quoted by no outcome in paper.yaml: {', '.join(rest[:5])}"
            + (", …" if len(rest) > 5 else ""), WARN, path,
            "quote each one, reported or not; one reported elsewhere is still a registered "
            "outcome, and the reader is owed where",
        ))  # fmt: skip
    return findings


__all__ = [
    "GATE", "as_planned", "check_registration", "fold", "named_in", "says_retrospective",
]  # fmt: skip
