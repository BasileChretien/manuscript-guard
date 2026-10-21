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

import math
import os
import re
import subprocess
from decimal import Decimal
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import number_in
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.text.reader import bound_files

#: How long `git ls-files` may take before the check says it could not ask.
GIT_SECONDS = 10


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
    for bound in bound_files(project):
        path = bound.path
        for placeholder in bound.placeholders:
            if placeholder.namespace != "results" or placeholder.key in said:
                continue
            value = results.values.get(placeholder.key)
            wrong = None if value is None or not is_count(value) else _small(value, minimum)
            if wrong is None:
                continue
            said.add(placeholder.key)
            report = report.with_findings(
                Finding(
                    gate="G2",
                    code="count-below-minimum",
                    message=f"results.{placeholder.key} is {value.display}, {wrong} the data "
                    f"custodian's minimum of {minimum}",
                    path=path,
                    line=placeholder.line,
                    hint=f"report it as fewer than the minimum, \"<{minimum}\", or merge the "
                    "category with another, in the analysis; a number that is no count of "
                    "people is emitted with its unit",
                )
            )
    return report


#: A count held back behind a comparator: "<5", "< 5", "≤4", "<=4".
#: A bound with a decimal or words after it, as the emitter takes a display: "<2.0", "<2
#: patients" (round 1 of #341).
_HELD_BACK = re.compile(
    r"\s*(?P<sign><=|<|\N{LESS-THAN OR EQUAL TO})\s*(?P<bound>\d+(?:\.\d+)?)(?![\d.])"
    r"(?:\s*[^\W\d][^<>\N{LESS-THAN OR EQUAL TO}]*)?\s*"
)


def _small(value, minimum: int) -> str | None:
    """What is wrong with how a count's display prints it, or None. A comparator hides the
    count only where every count it allows is one the custodian forbids or nought: "<2" and
    "≤3" under a minimum of 5 still say the count is one, or at most three (round 3 of
    #275)."""
    held = _HELD_BACK.fullmatch(value.display)
    if held is None:
        return "a count below" if 0 < _printed(value.display) < minimum else None
    bound = Decimal(held["bound"])
    # The largest whole count it allows: below a bound, the whole number under it.
    largest = math.ceil(bound) - 1 if held["sign"] == "<" else math.floor(bound)
    return "a bound tighter than" if 1 <= largest < minimum - 1 else None


def _printed(display: str) -> float:
    """The number a display prints, read as the emitter reads a display, or 0 where it holds
    the count back behind a comparator ("<5", round 1 of #275). "3 patients", "3.0" and "+3"
    print 3 (round 2)."""
    return number_in(display) or 0


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
    """Whether git tracks `relative` under `root`; False outside a repository or outside
    its work tree, None where git could not be asked. The path is matched as written, not
    as a pattern ("data[1].csv" is not "data1.csv"), and whatever its case where git itself
    ignores case; git is asked in English, whose words are read (round 1 of #275)."""
    try:
        ignorecase = _git(root, "config", "--bool", "core.ignorecase").stdout.strip() == "true"
        magic = "literal,icase" if ignorecase else "literal"
        finished = _git(root, "ls-files", "-z", "--", f":({magic}){relative}")
    except (OSError, subprocess.TimeoutExpired):
        return None
    if finished.returncode == 0:
        return bool(finished.stdout.strip("\0"))
    said = finished.stderr.lower()
    return False if "not a git repository" in said or "outside repository" in said else None


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    """git, its output read as UTF-8: `ls-files -z` writes a name unquoted, "データ.csv"
    as its UTF-8 bytes, which the locale's code page cannot read (round 1 of #341, as
    `impact` found under cp932 in round 1 of #280)."""
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *arguments],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_SECONDS,
        check=False,
        env={**os.environ, "LC_ALL": "C", "LANGUAGE": "C"},
    )
