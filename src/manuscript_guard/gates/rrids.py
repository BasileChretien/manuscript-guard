"""G7, from the RRID records: each RRID the manuscript types is one the resolver knows, and a
cell line it names is not one Cellosaurus marks problematic.

`manuscript-guard lookup --resources` asks the RRID resolver about each RRID the main text
and the supplement type, Cellosaurus too for a cell line, and writes what they said to
`literature/rrids/` (`rrids.py`, `lookup/resources.py`). This reads those records and asks
nobody. Each finding stands at the first place the RRID is typed, and a record of an RRID
the manuscript no longer types is not read. What it says, each a warning at every stage, as
G7's own `lookup-missing` is, so that none fails a paper (Basile, 2026-11-12):

* `rrid-not-looked-up`: an RRID with no record. An answer that did not come is never
  written, so this is also what an outage leaves;
* `rrid-unresolved`: the resolver answered that it knows no such RRID;
* `cell-line-problematic`: Cellosaurus marks the line problematic, its comment quoted;
* `rrid-record-edited` and `rrid-record-misfiled`: a record changed by hand since it was
  written, or one that is another RRID's, which is then not read.

A record that is no RRID record fails as every contract does (`schema-violation`). A
resource the manuscript names with no RRID is not looked for: the author refused a presence
check of that kind.
"""

from __future__ import annotations

from typing import Any

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.rrids import (
    ABSENT,
    SCHEMA_NAME,
    Typed,
    digest_holds,
    first_places,
    record_path,
    typed,
)

GATE = "G7"
_AGAIN = "`manuscript-guard lookup --resources --again` asks the resolver again"


def _more(places: list[Typed]) -> str:
    """What a message says of the other places an RRID is typed: the finding stands at the
    first."""
    more = len(places) - 1
    return f" (typed at {more} other place{'' if more == 1 else 's'} too)" if more else ""


def _finding(code: str, message: str, places: list[Typed], hint: str) -> Finding:
    return Finding(gate=GATE, code=code, message=message, path=places[0].path,
                   line=places[0].line, hint=hint, severity=WARN)  # fmt: skip


def _record(project: Project, rrid: str, places: list[Typed]) -> tuple[dict | None, Report]:
    """The RRID's record, or what stops it being read."""
    path = record_path(project, rrid)
    if not path.is_file():
        return None, Report((_finding(
            "rrid-not-looked-up",
            f"{rrid} has no record of what the RRID resolver says of it{_more(places)}",
            places,
            "run `manuscript-guard lookup --resources`; an RRID whose answer did not come is "
            "not recorded, and is asked again",
        ),))  # fmt: skip
    try:
        document = read_structured(path)
    except ContractError as exc:
        return None, Report((Finding(gate=GATE, code="schema-violation", message=str(exc),
                                     path=path, hint="see the rrid schema"),))  # fmt: skip
    report = validate(document, SCHEMA_NAME, path, gate=GATE)
    if not report.ok:
        return None, report
    if document["rrid"] != rrid:
        return None, Report((_finding(
            "rrid-record-misfiled",
            f"{path.name} holds the record of {document['rrid']}, not of {rrid}",
            places, "two RRIDs that differ only in case, or in a `:` against a `-`, share "
            "a file name; write one of them as the resolver does, delete the file and run "
            "`manuscript-guard lookup --resources`",
        ),))  # fmt: skip
    if not digest_holds(document):
        return None, Report((_finding(
            "rrid-record-edited",
            f"the record of {rrid} no longer says what the resolver said",
            places, "what the resolver said is not the author's to edit; " + _AGAIN,
        ),))  # fmt: skip
    return document, Report()


def _judged(rrid: str, record: dict[str, Any], places: list[Typed]) -> list[Finding]:
    found = []
    if record["status"] == ABSENT:
        found.append(_finding(
            "rrid-unresolved",
            f"the RRID resolver does not know {rrid}, asked on {record['asked_on']}"
            f"{_more(places)}",
            places,
            "check the RRID against the resource's page at scicrunch.org/resolver or "
            "rrid.site: a typing error, or an RRID never issued, points the reader at nothing; "
            + _AGAIN,
        ))  # fmt: skip
    line = record.get("cellosaurus") or {}
    for problem in line.get("problems", []):
        name = line.get("name") or line.get("accession") or rrid
        found.append(_finding(
            "cell-line-problematic",
            f"Cellosaurus marks {name} ({rrid}) problematic: \"{problem}\" (Cellosaurus, "
            f"CC BY 4.0, asked on {record['asked_on']})",
            places,
            "say in the Methods how the line was authenticated, for instance by STR "
            "profiling, and whether the problem Cellosaurus records bears on the results; or "
            "use a line that is what it is called",
        ))  # fmt: skip
    return found


def check_rrids(project: Project) -> Report:
    """Each RRID the manuscript types, held to its record."""
    places = first_places(typed(project))
    report = Report()
    looked = 0
    for rrid, where in places.items():
        record, problems = _record(project, rrid, where)
        report = report.merge(problems)
        if record is None:
            continue
        looked += 1
        report = report.with_findings(*_judged(rrid, record, where))
    return report.with_counts(rrids=len(places), rrids_looked_up=looked)


__all__ = ["GATE", "check_rrids"]
