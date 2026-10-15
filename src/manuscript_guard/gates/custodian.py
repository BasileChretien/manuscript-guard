"""What a data custodian forbids: a small count printed, and its data in the repository.

Many custodians of health data, pharmacovigilance and claims databases among them, forbid
publishing a count below a minimum, since a cell of two patients in a rare category can
name them. `paper.yaml` says what the custodian's minimum is:

    custodian:
      minimum_cell_count: 5

and G2 then fails each count the manuscript or the supplement binds that prints a number at
least one and below the minimum (`count-below-minimum`), naming the key. A count is a whole
number the analysis emitted with no unit, that is neither a parameter, a software version nor
a label: "5 years" is emitted with its unit and is no count of people. Nought is not a small
cell, and a count whose display hides it ("<5") prints no small number.

And an input the analysis declares restricted (`em.add_input(path, restricted=True)`, or
`em$add_input(path, restricted = TRUE)` in R) is data that may not leave the custodian's
hands: G1 fails it when git tracks it (`restricted-input-tracked`), since a pushed repository
is a copy of it outside them.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.text.placeholders import parse

#: How long `git ls-files` may take before the check says it could not ask.
GIT_SECONDS = 10
#: A display that prints a whole number and nothing else, its thousands grouped or not.
_WHOLE = re.compile(r"\d{1,3}(?:[,\s]\d{3})*|\d+")


def minimum_cell_count(project: Project) -> int | None:
    """The custodian's minimum, where `paper.yaml` declares one."""
    custodian = (project.paper or {}).get("custodian")
    minimum = custodian.get("minimum_cell_count") if isinstance(custodian, dict) else None
    return minimum if isinstance(minimum, int) and not isinstance(minimum, bool) else None


def is_count(value) -> bool:
    """Whether a results value is a count of something, as far as the emitter recorded:
    a whole number with no unit that is not a parameter, a software version or a label."""
    number = value.value
    return (
        isinstance(number, int)
        and not isinstance(number, bool)
        and not value.unit
        and not value.role
        and not value.label
    )


def check_small_cells(project: Project, results: Results) -> Report:
    """A failure for each count the manuscript binds that the custodian forbids printing."""
    minimum = minimum_cell_count(project)
    if minimum is None:
        return Report()
    report = Report()
    said: set[str] = set()
    for path in source_files(project.path("manuscript")):
        for placeholder in parse(read_text(path))[0]:
            if placeholder.namespace != "results" or placeholder.key in said:
                continue
            value = results.values.get(placeholder.key)
            if value is None or not is_count(value) or not 0 < _printed(value.display) < minimum:
                continue
            said.add(placeholder.key)
            report = report.with_findings(
                Finding(
                    gate="G2",
                    code="count-below-minimum",
                    message=f"results.{placeholder.key} is {value.display}, a count below "
                    f"the data custodian's minimum of {minimum}",
                    path=path,
                    line=placeholder.line,
                    hint="report it as fewer than the minimum with a display such as \"<5\", "
                    "or merge the category with "
                    "another, in the analysis; a number that is no count of people is "
                    "emitted with its unit",
                )
            )
    return report


def _printed(display: str) -> int:
    """The whole number a display prints, or 0 where it prints something else: "<5" holds a
    count back, and is how the emitter lets an analysis do so (round 1 of #275)."""
    found = _WHOLE.fullmatch(display.strip())
    return int(re.sub(r"[,\s]", "", found.group(0))) if found else 0


def check_restricted_inputs(project: Project, results: Results) -> Report:
    """A failure for each input declared restricted that git tracks."""
    restricted = sorted(
        {
            str(record["path"])
            for fragment in results.fragments
            for record in fragment.inputs
            if isinstance(record, dict) and record.get("restricted") and record.get("path")
        }
    )
    report = Report()
    for relative in restricted:
        tracked = _tracked(project.root, relative)
        if tracked is False:
            continue
        report = report.with_findings(
            Finding(
                gate="G1",
                code="restricted-input-tracked",
                # Where git could not be asked, a warning: nothing is known to be wrong.
                severity=FAIL if tracked else WARN,
                message=(
                    f"{relative} is declared restricted, and git tracks it"
                    if tracked
                    else f"{relative} is declared restricted, and git could not say whether "
                    f"it tracks it"
                ),
                path=project.root / relative,
                hint="git rm --cached the file and list it in .gitignore; once pushed, a copy "
                "is outside the custodian's hands, and the history has to be rewritten",
            )
        )
    return report


def _tracked(root: Path, relative: str) -> bool | None:
    """Whether git tracks `relative` under `root`; False outside a repository, None where
    git could not be asked."""
    try:
        finished = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "ls-files", "--error-unmatch", "--", relative],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=GIT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if finished.returncode == 0:
        return True
    if "not a git repository" in finished.stderr.lower():
        return False
    return False if "did not match any file" in finished.stderr else None
