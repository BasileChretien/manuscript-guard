"""VERIFICATION.md and VERIFICATION.json: how the released paper was checked, as `check
--submission` and the records say, and what was checked by no one.

They hold, for the release as it is deposited: `check --submission` gate by gate, its
failures, warnings and notes counted and named by their codes; each dimension of `check`'s
assurance, what its gates found by machine and what no gate decides; the last run of
`verify` in this checkout, with the date it recorded; where the co-authors' checking stands,
counted by author; each author's approval; and the digests the approvals and the results are
held to. A finding is given by its code and never its words, and no one is named but the
authors, as on the companion page (decision 4(a)): a message, or a reader's record, may name
whoever a record names. Nothing reads a clock, so the same records give the same bytes.
"""

from __future__ import annotations

import contextlib
import io
import json
import re

from manuscript_guard.contracts._schema import ContractError, read_structured
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Report

SCHEMA = "manuscript-guard/verification/1"


def _gate_order(gate: str) -> tuple[int, str]:
    found = re.fullmatch(r"G(\d+)(.*)", gate)
    return (int(found[1]), found[2]) if found else (10_000, gate)


def _gates(report: Report) -> dict[str, dict]:
    from manuscript_guard.assurance import DIMENSIONS, STOPPED_AS

    named = {gate for dimension in DIMENSIONS for gate in dimension.gates}
    named |= {STOPPED_AS.get(f.gate, f.gate) for f in report.findings}
    out = {}
    for gate in sorted(named, key=_gate_order):
        found = [f for f in report.findings if STOPPED_AS.get(f.gate, f.gate) == gate]
        out[gate] = {
            "failing": sum(f.severity == FAIL for f in found),
            "warnings": sum(f.severity == WARN for f in found),
            "notes": sum(f.severity == INFO for f in found),
            "codes": sorted({f.code for f in found}),
        }
    return out


def _assurance(report: Report) -> list[dict]:
    from manuscript_guard.assurance import DIMENSIONS, _machine

    return [{"dimension": d.name, "gates": list(d.gates), "checked": _machine(report, d.gates),
             "not_checked": d.unchecked} for d in DIMENSIONS]  # fmt: skip


def _verify_run(project: Project) -> dict | None:
    from manuscript_guard.assurance import VERIFIED, VERIFIED_SCHEMA, fragments_digest

    try:
        record = read_structured(project.path("build") / VERIFIED)
    except ContractError:
        return None
    if not isinstance(record, dict) or record.get("schema") != VERIFIED_SCHEMA:
        return None
    left = record.get("not_rerun")
    return {
        "ran_on": str(record.get("ran_on", "an unrecorded date")),
        "values": record.get("values", 0),
        "reproduced": record.get("reproduced", 0),
        "not_rerun": sorted(str(n) for n in left) if isinstance(left, list) else [],
        "passed": bool(record.get("ok")),
        "results_unchanged_since": fragments_digest(project) == record.get("results_sha256"),
    }


def _checker(project: Project) -> dict:
    from manuscript_guard.approvals import authors_of, name_of
    from manuscript_guard.checking.items import ItemsError
    from manuscript_guard.checking.store import STATUSES, status
    from manuscript_guard.cli import _checking_items

    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):  # fmt: skip
            items = _checking_items(project, None)
        standing = status(project.root, items)
    except ItemsError:
        return {"readable": False}
    authors = [name_of(author) for author in authors_of(project)]
    by_author = {author: {s: standing.by_person.get(author, {}).get(s, 0) for s in STATUSES}
                 for author in authors if author in standing.by_person}  # fmt: skip
    others = [counts for person, counts in standing.by_person.items() if person not in authors]
    return {
        "readable": True,
        "by_author": by_author,
        "others_not_authors": {s: sum(c.get(s, 0) for c in others) for s in STATUSES},
        "unanswered": standing.outstanding,
        "stale": len(standing.stale),
    }


def _approvals(project: Project) -> list[dict]:
    from pathlib import Path

    from manuscript_guard.approvals import DIRECTORY, authors_of, check_approvals, name_of, slug_of

    codes = {Path(f.path).name: f.code for f in check_approvals(project).findings
             if f.path is not None}  # fmt: skip
    out = []
    for author in authors_of(project):
        name = f"{slug_of(author)}.yaml"
        path = project.root / DIRECTORY / name
        try:
            record = read_structured(path) if path.is_file() else None
        except ContractError:
            record = None
        when = record.get("approved_on") if isinstance(record, dict) else None
        code = codes.get(name)
        state = ("missing" if code == "approval-missing" else "stale" if code == "approval-stale"
                 else "unreadable" if code is not None or not when else "current")  # fmt: skip
        out.append({"author": name_of(author), "state": state,
                    **({"approved_on": str(when)} if when and state != "missing" else {})})
    return out


def _digests(project: Project) -> dict[str, str]:
    from manuscript_guard.approvals import front_digest
    from manuscript_guard.assurance import fragments_digest
    from manuscript_guard.gates.review import document_digest

    return {"document_sha256": document_digest(project), "front_sha256": front_digest(project),
            "results_sha256": fragments_digest(project)}  # fmt: skip


def record_of(project: Project, report: Report) -> dict:
    return {
        "schema": SCHEMA,
        "title": str(project.paper.get("title", "")),
        "check": {"stage": "submission", "passed": report.ok, "gates": _gates(report)},
        "assurance": _assurance(report),
        "verify": _verify_run(project),
        "checker": _checker(project),
        "approvals": _approvals(project),
        "digests": _digests(project),
    }


_STATES = {"current": "approved it on {on}, as it stands", "missing": "has not approved it",
           "stale": "approved it on {on}, and it has changed since",
           "unreadable": "an approval that cannot be read"}  # fmt: skip


def _markdown(record: dict) -> str:
    check = record["check"]
    lines = [f"# How this release was checked: {record['title']}", "",
             "Written by `manuscript-guard deposit` from `check --submission` and the "
             "project's records. No score: none of this says the paper is right.", "",
             f"## `check --submission`: {'passed' if check['passed'] else 'did not pass'}", "",
             "| Gate | Failing | Warnings | Notes | Codes |", "|---|---|---|---|---|"]  # fmt: skip
    for gate, said in check["gates"].items():
        codes = ", ".join(f"`{code}`" for code in said["codes"]) or "none"
        lines.append(f"| {gate} | {said['failing']} | {said['warnings']} | {said['notes']} | "
                     f"{codes} |")  # fmt: skip
    lines += ["", "## What was checked, by what", ""]
    for dimension in record["assurance"]:
        lines += [f"- **{dimension['dimension']}**: {dimension['checked']}. Not checked: "
                  f"{dimension['not_checked']}."]  # fmt: skip
    run = record["verify"]
    lines += ["", "## The last run of `verify`", ""]
    if run is None:
        lines.append("No run of `verify` is recorded in the checkout the release was made in.")
    else:
        lines.append(f"`verify` re-ran the analysis on {run['ran_on']}: {run['reproduced']} of "
                     f"{run['values']} values reproduced; it "
                     f"{'passed' if run['passed'] else 'did not pass'}"
                     + (f"; not re-run: {', '.join(run['not_rerun'])}" if run["not_rerun"]
                        else "")
                     + ("." if run["results_unchanged_since"]
                        else "; the results have changed since."))  # fmt: skip
    lines += ["", "## The co-authors' checking", ""]
    checker = record["checker"]
    if not checker["readable"]:
        lines.append("The checker's items could not be read.")
    elif not checker["by_author"] and not any(checker["others_not_authors"].values()):
        lines.append("No co-author has recorded a check (`manuscript-guard checker`).")
    else:
        for author, counts in checker["by_author"].items():
            said = ", ".join(f"{n} {s}" for s, n in counts.items())
            lines.append(f"- {author}: {said}")
        others = checker["others_not_authors"]
        if any(others.values()):
            said = ", ".join(f"{n} {s}" for s, n in others.items())
            lines.append(f"- others, not authors: {said}")
        lines.append(f"- {checker['unanswered']} item(s) nobody has answered; {checker['stale']} "
                     "answer(s) of text that has changed since")  # fmt: skip
    lines += ["", "## The authors' approval", ""]
    for said in record["approvals"]:
        state = _STATES[said["state"]].format(on=said.get("approved_on", ""))
        lines.append(f"- {said['author']}: {state}")
    digests = record["digests"]
    lines += ["", "## Digests", "",
              "- the manuscript and its results, as the approvals hold them: "
              f"`{digests['document_sha256']}`",
              f"- the title page, CRediT statement and declarations: `{digests['front_sha256']}`",
              "- the results files, by name and bytes: "
              f"`{digests['results_sha256']}`", ""]  # fmt: skip
    return "\n".join(lines)


def verification(project: Project, report: Report) -> tuple[str, str]:
    """VERIFICATION.md and VERIFICATION.json, from the report of `check --submission`."""
    record = record_of(project, report)
    return _markdown(record), json.dumps(record, indent=2, sort_keys=True,
                                         ensure_ascii=False) + "\n"


__all__ = ["SCHEMA", "record_of", "verification"]
