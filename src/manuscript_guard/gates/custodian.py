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

A count held back is printed all the same where what stands beside it gives it away: a row
whose total and other cells are printed leaves the "<5" one number. So G2 also fails each
count held back that what the manuscript or the supplement prints lets a reader work out by
subtraction (`count-recoverable`), from one to below the minimum. It fails in a sum the
analysis declares (`em.relation("sum", …)`), or a step or the arms of a flow, where every
key of it is bound. In a table it binds, by a total row or column (`stats/margins.py`) or a
column's header n, it warns: a total read from a label need not be the sum of the counts
beside it, and a header's n is their total only where every one of the column has one of
the categories (Basile, 2026-10-29). `deposit` asks the same of every table of the results
files it carries (`recoverable_cells`), and warns.

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
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import number_in
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.text.placeholders import parse
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
    a whole number with no unit that is not a parameter, a software version or a label, and
    that is not said to be no count (`count: false`, a harvested cell outside its entry's
    `counts`). A harvested cell said to be one (`count: true`), a number held back or one
    written "3.0", is one whatever its value, and its display is read (`_small`)."""
    number = value.value
    if value.count is True:
        return not value.role and not value.label
    return (
        isinstance(number, int)
        and not isinstance(number, bool)
        and not value.unit
        and not value.role
        and not value.label
        and value.count is not False
    )


def check_small_cells(project: Project, results: Results) -> Report:
    """A failure for each count the manuscript binds that the custodian forbids printing."""
    minimum = minimum_cell_count(project)
    if minimum is None:
        return Report()
    report = Report()
    said: set[str] = set()
    for path, placeholders, lined in _printing(project):
        for placeholder in placeholders:
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
                    line=placeholder.line if lined else None,
                    hint=UNREAD_HINT if wrong == UNREAD else
                    f"report it as fewer than the minimum, \"<{minimum}\", or merge the "
                    "category with another, in the analysis; a number that is no count of "
                    "people is emitted with its unit",
                )
            )
    return report


def _printing(project: Project) -> list[tuple[Path, list, bool]]:
    """What prints the results: the manuscript's sources, in its format, with their lines,
    and each figure's alternative text, which the build prints into its picture
    (`gates/figure_alt.py`), with none."""
    from manuscript_guard.gates.figure_alt import alt_texts, literal

    found = [(bound.path, bound.placeholders, True) for bound in bound_files(project)]
    return found + [(sidecar, parse(literal(raw))[0], False)
                    for _name, sidecar, raw in alt_texts(project)]  # fmt: skip


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
    #275).

    A harvested cell said to be a count that is text ("2 (1.5%)", "2/40") is read as
    `deposit` reads a table cell (`count_in_cell`), and one that names no count it can read
    ("n=2") is refused: what holds digits in a count column may be one (round 2 of #471)."""
    if value.count is True and isinstance(value.value, str):
        from manuscript_guard.deposit.counts import count_in_cell

        stated = count_in_cell(value.display)
        if stated is None:
            return UNREAD
        return "a count below" if 0 < stated < minimum else None
    largest = held_largest(value.display)
    if largest is None:
        return "a count below" if 0 < _printed(value.display) < minimum else None
    return "a bound tighter than" if 1 <= largest < minimum - 1 else None


#: A harvested count cell `count_in_cell` reads no count from, and what to do about it.
UNREAD = "a cell this tool reads as a count, failing closed, and cannot hold to"
UNREAD_HINT = ("write the count plainly in the output (\"2\" or \"2 (1.5%)\"); if the column "
               "holds no count, name the entry's count columns in `counts` and leave it out")


def held_largest(display: str) -> int | None:
    """The largest whole count a display that holds a count back allows, "<5" and "≤4" 4,
    or None where it holds none back: below a bound, the whole number under it."""
    held = _HELD_BACK.fullmatch(display)
    if held is None:
        return None
    bound = Decimal(held["bound"])
    return math.ceil(bound) - 1 if held["sign"] == "<" else math.floor(bound)


def _printed(display: str) -> float:
    """The number a display prints, read as the emitter reads a display, or 0 where it holds
    the count back behind a comparator ("<5", round 1 of #275). "3 patients", "3.0" and "+3"
    print 3 (round 2)."""
    return number_in(display) or 0


# ------------------------------------------------------- a count held back, worked out


_RECOVERED_HINT = (
    "hold back a second count of the same row or column as well, or the total, or merge the "
    "category with another, in the analysis: a count held back beside its total and the "
    "other counts that make it up is printed all the same"
)
_LABEL_HINT = (
    "a total a table names by its label may not be the sum of the counts beside it (the "
    "patients with any of several events, rows that overlap); where it is, hold back a "
    "second count of the same row or column as well, or the total, or merge the category "
    "with another, in the analysis"
)
_BY_N_HINT = (
    "the header's n gives it where every one of the column has one of the categories; where "
    "some have none, say how many beside it, or hold back a second category as well"
)


def recoverable(table, minimum: int | None) -> list:
    """Each count `table` (`text.tables.Table`) holds back that one of its lines gives away
    (`stats.margins.recovered`) and that the custodian forbids: from one to below `minimum`.
    Without a minimum, any from one: a count held back says it hides what it holds."""
    from manuscript_guard.stats.margins import recovered, table_lines

    return [found for found in recovered(table_lines(table)) if _forbidden(found.value, minimum)]


def recoverable_counts(total: int, shown: Sequence, minimum: int) -> list[int]:
    """The places of the counts held back that a total printed beside them gives away, as
    `recoverable` reads a table's line: the counts are the whole of the total, each printed
    as itself (an integer), held back behind the minimum ("<5", from nought to four), or not
    printed at all (None, from nought to the total). A data profile's column is such a line
    (`vault/profile.py`)."""
    from manuscript_guard.stats.margins import Count, Line, Member, recovered

    def count(at: int, one: object) -> Member:
        if isinstance(one, int) and not isinstance(one, bool):
            return Member(Count(one, one, str(one), at), str(at))
        high = total if one is None else held_largest(str(one))
        if high is None:
            raise ValueError(f"a count printed {one!r} is neither a count nor held back")
        return Member(Count(0, high, str(one), at, held=True), str(at))

    members = tuple(count(at, one) for at, one in enumerate(shown))
    line = Line(Member(Count(total, total, str(total), -1), "total"), members, "the total",
                "count", "counts")  # fmt: skip
    return [found.member.count.line for found in recovered([line])
            if _forbidden(found.value, minimum)]  # fmt: skip


def _forbidden(value: int, minimum: int | None) -> bool:
    """Whether a count worked out is one the custodian forbids: nought is not a small cell."""
    return value >= 1 and (minimum is None or value < minimum)


def as_cells(table) -> tuple:
    """An emitted table (`contracts.results.Table`) as a paper's table is read: its header,
    then its rows, each cell at the row it is in."""
    from manuscript_guard.text.tables import TableCell

    return (tuple(TableCell(str(name), 0) for name in table.columns),
            *(tuple(TableCell(str(cell), at) for cell in row)
              for at, row in enumerate(table.rows, 1)))  # fmt: skip


def check_recoverable(project: Project, results: Results) -> Report:
    """Each count held back that what the manuscript or the supplement prints gives away
    (`count-recoverable`). A failure where the analysis declares the total a sum: a sum
    relation, or a step or the arms of a flow, all its keys bound. A warning in an emitted
    table it binds, where the total is read from the table's label alone or from a column's
    header n: neither need be the sum of the counts beside it (Basile, 2026-10-29)."""
    minimum = minimum_cell_count(project)
    if minimum is None:
        return Report()
    from manuscript_guard.stats.margins import recovered

    tables: dict[str, tuple[Path, int | None]] = {}
    values: dict[str, tuple[Path, int | None]] = {}
    for path, placeholders, lined in _printing(project):
        for placeholder in placeholders:
            book = {"table": tables, "results": values}.get(placeholder.namespace)
            if book is not None:
                book.setdefault(placeholder.key, (path, placeholder.line if lined else None))
    findings = [
        _recovered(f"table.{key}: ", found, *tables[key], declared=False)
        for key, table in sorted(results.tables.items()) if key in tables
        for found in recoverable(as_cells(table), minimum)
    ]  # fmt: skip
    # A key in two lines, a stage that ends one step and starts the next, is said once.
    said: set[str] = set()
    for found in recovered(_value_lines(results, frozenset(values))):
        key = found.member.name.removeprefix("results.")
        if _forbidden(found.value, minimum) and key not in said:
            said.add(key)
            findings.append(_recovered("", found, *values[key], declared=True))
    return Report(tuple(findings))


def _recovered(prefix: str, found, path: Path, line: int | None, *,
               declared: bool) -> Finding:  # fmt: skip
    """A failure where the analysis `declared` the total a sum; otherwise a warning, with
    what the total has to be for the count to be the one worked out."""
    from manuscript_guard.stats.margins import said

    if declared:
        suffix, hint = "", _RECOVERED_HINT
    elif found.line.explicit:
        suffix = ", if the total is the sum of the counts beside it, which nothing declares"
        hint = _LABEL_HINT
    else:
        suffix, hint = ", if every one of the column has one of the categories", _BY_N_HINT
    return Finding(
        gate="G2", code="count-recoverable", severity=FAIL if declared else WARN,
        message=f"{prefix}{said(found)}{suffix}", path=path, line=line, hint=hint,
    )  # fmt: skip


def _value_lines(results: Results, shown: frozenset[str]) -> list:
    """The sums the analysis declares, and each step and the arms of each flow, as lines,
    where every key of one is bound: a reader works them out from what is printed."""
    from manuscript_guard.stats.margins import Line, Member, count_in

    def member(key: object) -> Member | None:
        value = results.values.get(key) if isinstance(key, str) and key in shown else None
        # A value that is not whole is no count, whatever its display rounds it to: 1,234.6
        # printed "1,235" (round 1 of #469).
        whole = value is not None and _whole_value(value.value)
        count = count_in(value.display, share=False) if whole else None
        return None if count is None else Member(count, f"results.{key}")

    def line(total: object, parts: list, of: str, part: str, several: str) -> None:
        printed = [member(key) for key in (total, *parts)]
        if len(parts) >= 2 and None not in printed and not printed[0].count.held:
            lines.append(Line(printed[0], tuple(printed[1:]), of, part, several))

    lines: list[Line] = []
    for relation in results.relations:
        if relation.get("kind") == "sum" and isinstance(relation.get("of"), list):
            key = relation.get("key")
            line(key, relation["of"], f"results.{key}, which the analysis declares their sum,",
                 "key it sums", "keys it sums")  # fmt: skip
    for name, flow in sorted(results.flows.items()):
        stages = [stage.get("key") for stage in flow.get("stages") or () if isinstance(stage, dict)]
        overlapping = flow.get("overlapping", False)
        steps = flow.get("exclusions") or ()
        for n, (here, there, step) in enumerate(zip(stages, stages[1:], steps, strict=False), 1):
            if overlapping is True or (isinstance(overlapping, list) and n in overlapping):
                continue
            reasons = [reason.get("key") for reason in step if isinstance(reason, dict)]
            line(here, [there, *reasons], f"stage {n} of flow {name}, results.{here},",
                 f"count of stage {n + 1} and its exclusions",
                 f"counts of stage {n + 1} and its exclusions")  # fmt: skip
        arms = [arm.get("key") for arm in flow.get("arms") or () if isinstance(arm, dict)]
        if stages and arms:
            line(stages[-1], arms, f"the last stage of flow {name}, results.{stages[-1]},",
                 "arm", "arms")
    return lines


def _whole_value(number: object) -> bool:
    return (isinstance(number, int) and not isinstance(number, bool)) or (
        isinstance(number, float) and number.is_integer())


def recoverable_cells(
    project: Project, results: Results, carried: frozenset[str] = frozenset()
) -> Report:
    """A warning for each count held back that a table of the results files `carried`
    (named from the project's root) gives away by one of its totals, as `check_recoverable`
    reads a table the manuscript binds: a deposit publishes every table of them, bound or
    not, and a total read from a table's label need not be a sum, so it does not refuse
    (Basile, 2026-10-29). A sum or a flow is not read here: a results file carries each
    value beside its display, and `deposit.counts` reads the value."""
    minimum = minimum_cell_count(project)
    if minimum is None:
        return Report()
    findings = []
    for key, table in sorted(results.tables.items()):
        try:
            relative = table.source.relative_to(project.root).as_posix()
        except ValueError:
            continue
        if relative in carried:
            findings += [_recovered(f"table.{key} in {relative}: ", found, table.source, None,
                                    declared=False)
                         for found in recoverable(as_cells(table), minimum)]  # fmt: skip
    return Report(tuple(findings))


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
