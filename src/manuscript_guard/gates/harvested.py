"""G1 of a fragment `harvest` wrote: is the output still the one read, and what covers it?

A harvested fragment is held as an emitted one is, its inputs, its script and its digest
(`gates/freshness.py`), and to three more things:

- the output it was read from: one changed since fails (`harvested-output-changed`), as an
  input does, and one gone fails (`harvested-output-missing`), as an input does;
- the site's receipt, where one covers it: a receipt changed or gone since the harvest fails
  (`receipt-changed`), one whose output is not the output here fails
  (`receipt-output-mismatch`), and the script changed since the site ran it fails
  (`script-newer`), since the numbers are the site's run of the script as it was. Its inputs
  are at the site, and one not here is a note (`input-at-site`), not `input-missing`;
- what shows the script writes it: nothing does, until `verify` re-runs the script and reads
  the same values from what it wrote, or a site's receipt covers the run. Until then it warns
  (`harvest-declared`) at every stage, as the author decided (2026-10-28).
"""

from __future__ import annotations

from manuscript_guard.contracts.project import Project
from manuscript_guard.emit import input_digest_matches, source_digest_matches
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report

GATE = "G1"
#: The start of the context of a finding only the site that holds the data can answer, by a
#: new run and receipt: `next` routes it to no command (`guide/routes.py`).
RECEIPT_CONTEXT = "answered by the receipt of"


def receipted(fragment) -> bool:
    """Whether a site's receipt covers this fragment: its inputs are at the site."""
    return bool((fragment.harvested or {}).get("receipt"))


def input_at_site(fragment, declared: dict) -> Finding:
    site = fragment.harvested["receipt"].get("site", "the site")
    return Finding(
        gate=GATE, code="input-at-site", severity=INFO,
        message=f"input {declared['path']} is held at {site}; its receipt records its digest",
        path=fragment.path,
    )  # fmt: skip


def check_harvested(project: Project, fragment) -> Report:
    """The findings of one fragment, none where `harvest` did not write it."""
    harvested = fragment.harvested
    if not isinstance(harvested, dict):
        return Report()
    from manuscript_guard.harvest import standing

    output = project.root / str(harvested.get("output", ""))
    findings = []
    if not output.is_file():
        findings.append(_finding(
            "harvested-output-missing", fragment,
            f"{harvested.get('output')}, the output {fragment.path.name} was harvested from, "
            "is not there",
            "restore it, or run the script that writes it and harvest it again",
        ))  # fmt: skip
    elif not input_digest_matches(output, str(harvested.get("sha256", ""))):
        findings.append(_finding(
            "harvested-output-changed", fragment,
            f"{harvested.get('output')} changed since {fragment.path.name} was harvested from "
            "it",
            "harvest it again (`manuscript-guard harvest`), so that the results are the "
            "output's",
        ))  # fmt: skip
    if receipted(fragment):
        findings += _receipt(project, fragment, output)
    covered = standing(project.path("build"), fragment.path, harvested)
    if covered == "declared":
        findings.append(Finding(
            gate=GATE, code="harvest-declared", severity=WARN,
            message=f"{fragment.path.name} was harvested from {harvested.get('output')}, and "
            f"that {fragment.generated_by} writes it is declared: nothing here ran it",
            path=fragment.path,
            hint="run `manuscript-guard verify`, which runs the script in a copy and reads the "
            "output it writes; where the data are held at a site, its `verify --receipt`",
        ))  # fmt: skip
    return Report(tuple(findings))


def _receipt(project: Project, fragment, output) -> list[Finding]:
    """What the receipt recorded for the fragment says now."""
    from manuscript_guard.harvest import HarvestError, read_receipt, run_of

    recorded = fragment.harvested["receipt"]
    path = project.root / str(recorded.get("path", ""))
    site = recorded.get("site", "the site")
    # By its digest with its line endings left out, as an input's: git may check a receipt
    # out with CRLF, and that is the same receipt.
    if not path.is_file() or not input_digest_matches(path, str(recorded.get("sha256", ""))):
        said = "is gone" if not path.is_file() else "changed"
        return [_finding(
            "receipt-changed", fragment,
            f"the receipt of {site}, {recorded.get('path')}, {said} since {fragment.path.name} "
            "was harvested",
            "a receipt is the site's record of its run; ask the site for theirs, and harvest "
            "the output it covers again",
        )]  # fmt: skip
    try:
        run = run_of(read_receipt(path), fragment.harvested["spec"]["key"])
    except (HarvestError, KeyError, TypeError):
        run = None
    if run is None:
        return [_finding("receipt-changed", fragment,
                         f"the receipt of {site} records no run of {fragment.path.stem}",
                         "ask the site for the receipt of the run")]  # fmt: skip
    found = []
    named = [out for out in run["outputs"] if out["path"] == fragment.harvested.get("output")]
    if output.is_file() and not (named and input_digest_matches(output, named[0]["sha256"])):
        found.append(_finding(
            "receipt-output-mismatch", fragment,
            f"{fragment.harvested.get('output')} is not the output the receipt of {site} "
            "records",
            "harvest the output the site sent with its receipt",
        ))  # fmt: skip
    script = project.root / run["script"]["path"]
    if script.is_file() and not source_digest_matches(script, run["script"]["sha256"]):
        found.append(Finding(
            gate=GATE, code="script-newer",
            message=f"{run['script']['path']} has changed since {site} ran it for its receipt "
            f"of {recorded.get('ran_at')}",
            path=script,
            context=f"{RECEIPT_CONTEXT} {site}",
            hint=f"send the script to {site} and have them run `manuscript-guard verify "
            f"--receipt {site}` again",
        ))  # fmt: skip
    return found


def _finding(code: str, fragment, message: str, hint: str) -> Finding:
    return Finding(gate=GATE, code=code, severity=FAIL, message=message, path=fragment.path,
                   hint=hint)  # fmt: skip
