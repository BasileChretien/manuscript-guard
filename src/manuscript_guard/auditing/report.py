"""The audit's report, in sections, as text and as JSON.

What was read and what was not comes first, then a section for each kind of check:

* Membership: each number against the outputs given, and what a match is worth there. With
  no outputs given, no number is compared, and the report says so at its top.
* Arithmetic: numbers held to the ones beside them, which needs no outputs: a table's
  totals to the counts they total, a characteristic's categories to their column's n, and a
  flow printed as a nested list to its own arithmetic (`stats.flows`).
* Abstract against Results: each number of the Abstract looked for where the paper reports,
  and each of its intervals and tests held to its one counterpart there
  (`auditing.abstract`).
* Small cells recoverable by subtraction: each count held back ("<5") that a total beside it
  gives away, with the count it can only be.
* Writing (G6) and Language (G14): the gates `check` runs on the words, on a project made for
  the paper (`auditing.gates`).
* References (G7): the reference list counted, and the numbered citations held to it; what
  the registries said, with `--lookup`.

`--strict` counts the numbers not found in the outputs, a paper or a stretch of one that
could not be read, an audit that read no number, and what is exact arithmetic: a total that
its counts do not add up to (`sum-off`), categories that add up to more than their column's
n (`over-header-n`), and a count held back that a printed total gives away
(`count-recoverable`), a flow whose arithmetic does not hold (`flow-broken`), and an
interval or a test of the Abstract that differs from its counterpart where the paper reports
(`abstract-conflict`). Nothing else is counted: the P worked out from a statistic, G6 and
G14 (the author, 2026-10-28), G7's findings, a count held back that only a column's n
gives away, which holds only where none of the column lacks the characteristic, and a
number of the Abstract found nowhere the paper reports (the author, 2026-10-28).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report

INPUTS = "Inputs"
MEMBERSHIP = "Membership"
ARITHMETIC = "Arithmetic"
SMALL_CELLS = "Small cells recoverable by subtraction"
ABSTRACT = "Abstract against Results"
WRITING = "Writing (G6)"
LANGUAGE = "Language (G14)"
REFERENCES = "References (G7)"
#: What the report says at its top where no outputs were given.
NO_OUTPUTS = "No outputs given: no number was compared with the analysis"
#: How many items of one kind are listed for one file before only a count.
LISTED = 40


@dataclass(frozen=True)
class Item:
    """One thing the report says, in the shape `check --json` gives a finding, with its
    section and whether `--strict` counts it."""

    section: str
    gate: str
    code: str
    message: str
    severity: str
    counted: bool
    path: Path | None = None
    line: int | None = None
    context: str | None = None
    hint: str | None = None

    def as_dict(self) -> dict:
        return {
            "section": self.section, "gate": self.gate, "code": self.code,
            "severity": self.severity, "counted": self.counted, "message": self.message,
            "path": None if self.path is None else str(self.path), "line": self.line,
            "context": self.context, "hint": self.hint,
        }  # fmt: skip


def items(report) -> list[Item]:
    """Everything the report says, item by item, in the order of its sections."""
    found = [
        *(Item(INPUTS, "audit", "unreadable", said, FAIL, True) for said in report.unreadable),
        *(Item(INPUTS, "audit", "output-not-read", said, WARN, False) for said in report.skipped),
        *(Item(INPUTS, "audit", "passed-over", said, INFO, False) for said in report.passed_over),
        *(Item(INPUTS, "audit", "not-audited", said, INFO, False) for said in report.not_audited),
    ]
    if not report.examined:
        found.append(Item(INPUTS, "audit", "nothing-read", "the audit read no number in what "
                          "it was given, so nothing was checked", FAIL, True))  # fmt: skip
    found += [
        Item(MEMBERSHIP, "audit", "not-found", f"{c.text} is in no output given", FAIL, True,
             c.source, c.line, c.context)
        for c in report.unmatched
    ]  # fmt: skip
    found += [
        Item(MEMBERSHIP, "audit", "not-found-on-a-reference-line", f"{c.text} is in no output "
             "given, on a line read as a reference entry", WARN, False, c.source, c.line,
             c.context)
        for c in report.reference_like
    ]  # fmt: skip
    found += [
        Item(ARITHMETIC, "audit", "does-not-fit", d.message, WARN, False, d.source, d.line,
             d.context)
        for d in report.disagreements
    ]  # fmt: skip
    found += [
        Item(ARITHMETIC, "audit", "sum-off", d.message, FAIL, True, d.source, d.line, d.context)
        for d in report.sums_off
    ]  # fmt: skip
    found += [
        Item(ARITHMETIC, "audit", "over-header-n", d.message, FAIL, True, d.source, d.line,
             d.context)
        for d in report.over_n
    ]  # fmt: skip
    found += [
        Item(ARITHMETIC, "audit", "mean-not-assessable", d.message, INFO, False, d.source,
             d.line, d.context)
        for d in report.means_not_assessable
    ]  # fmt: skip
    found += [
        Item(ARITHMETIC, "audit", "whole-numbers-unfound", f"--whole-numbers {label!r}: no "
             "mean was read in a row whose label holds it", INFO, False)
        for label in report.whole_numbers_unfound
    ]  # fmt: skip
    found += _flow_items(report)
    found += _abstract_items(report.abstract)
    found += [
        Item(SMALL_CELLS, "G2", "count-recoverable", d.message, FAIL, True, d.source, d.line,
             d.context)
        for d in report.recovered
    ]  # fmt: skip
    found += [
        Item(SMALL_CELLS, "G2", "count-recoverable", f"{d.message}, if none of the column "
             "lacks the characteristic", WARN, False, d.source, d.line, d.context)
        for d in report.recovered_by_n
    ]  # fmt: skip
    for run in report.gates:
        if run.note:
            found.append(Item(WRITING, "G6", "gates-not-run", run.note, INFO, False, run.paper))
        for section, findings in ((WRITING, run.writing), (LANGUAGE, run.language)):
            found += [_from_finding(section, finding) for finding in findings]
    for census in report.references:
        found += [
            Item(REFERENCES, "G7", p.code, p.message, WARN, False, p.path or census.path, p.line)
            for p in census.problems
        ]  # fmt: skip
    for looked in report.lookups or []:
        entry = looked.entry
        where = entry.path or looked.path
        if not looked.came:
            found.append(Item(REFERENCES, "G7", "would-ask", f"{entry.label}: would ask "
                              f"{looked.asked}", INFO, False, where, entry.line))
            continue
        found.append(Item(REFERENCES, "G7", "looked-up", f"{entry.label}: asked "
                          f"{looked.asked}" + (", answered from the records kept"
                                               if looked.came == "kept" else ""),
                          INFO, False, where, entry.line))  # fmt: skip
        found += [
            Item(REFERENCES, "G7", p.code, p.message, WARN, False, p.path, p.line)
            for p in looked.problems
        ]  # fmt: skip
    return found


def _flow_items(report) -> list[Item]:
    """Each flow whose arithmetic does not hold, and each note on one."""
    return [
        *(Item(ARITHMETIC, "audit", "flow-broken", d.message, FAIL, True, d.source, d.line,
               d.context) for d in report.flows_broken),
        *(Item(ARITHMETIC, "audit", "flow-note", d.message, INFO, False, d.source,
               d.line or None, d.context or None) for d in report.flow_notes),
    ]  # fmt: skip


def _abstract_items(read) -> list[Item]:
    """What the Abstract against Results says, item by item: a conflict counted, the rest
    not."""
    if read is None:
        return []
    if not read.compared:
        return [Item(ABSTRACT, "audit", "abstract-not-compared", f"not compared: "
                     f"{read.why_not}", INFO, False)]  # fmt: skip
    return [
        *(Item(ABSTRACT, "audit", "abstract-conflict", d.message, FAIL, True, d.source,
               d.line, d.context) for d in read.conflicts),
        *(Item(ABSTRACT, "audit", "abstract-not-found", f"{c.text} in the Abstract is "
               "found nowhere the paper reports", WARN, False, c.source, c.line, c.context)
          for c in read.not_found),
        *(Item(ABSTRACT, "audit", "abstract-rounded", f"{c.text} in the Abstract is found "
               "only as a rounding of a number the paper reports", INFO, False, c.source,
               c.line, c.context) for c in read.rounded),
    ]  # fmt: skip


def _from_finding(section: str, finding: Finding) -> Item:
    return Item(section, finding.gate, finding.code, finding.message, finding.severity, False,
                finding.path, finding.line, finding.context, finding.hint)  # fmt: skip


def failed(report) -> bool:
    """What `--strict` fails on."""
    return any(item.counted for item in items(report))


def as_json(report, discrimination) -> str:
    """The report as `check --json` gives one: `ok` is what `--strict` would say."""
    listed = items(report)
    counts = {
        "files": len(report.papers),
        "outputs": len(report.backing_files),
        "numbers": report.examined,
        "classified": report.classified,
        "matched": len(report.matched),
        "not_found": len(report.unmatched),
        "not_found_on_reference_lines": len(report.reference_like),
        "not_compared": report.uncompared,
        "totals_off": len(report.sums_off),
        "over_header_n": len(report.over_n),
        # Apart, as the text says them: --strict counts the first and not the second.
        "recoverable": len(report.recovered),
        "recoverable_by_n": len(report.recovered_by_n),
        "flows": report.flows_read,
        "flows_broken": len(report.flows_broken),
        **_abstract_counts(report.abstract),
        "reference_entries": sum(len(c.entries) for c in report.references),
    }
    worth = None
    if discrimination is not None and report.compared:
        worth = {"integers_1_100": discrimination.small_integers,
                 "integers_1_1000": discrimination.medium_integers,
                 "two_decimals": discrimination.two_decimals,
                 "verdict": discrimination.verdict()}  # fmt: skip
    abstract = getattr(report.abstract, "discrimination", None)
    return json.dumps(
        {
            "ok": not any(item.counted for item in listed),
            "compared": report.compared,
            "counts": counts,
            "what_a_match_is_worth": worth,
            "abstract_compared": bool(report.abstract and report.abstract.compared),
            "what_an_abstract_match_is_worth": None if abstract is None else {
                "integers_1_100": abstract.small_integers,
                "integers_1_1000": abstract.medium_integers,
                "two_decimals": abstract.two_decimals,
                "verdict": abstract.verdict()},
            "findings": [item.as_dict() for item in listed],
        },
        indent=2,
        # As `check --json`: a pipe on Windows is cp1252.
        ensure_ascii=True,
    )


def _abstract_counts(read) -> dict[str, int]:
    if read is None or not read.compared:
        return {}
    return {"abstract_numbers": read.numbers, "abstract_matched": read.matched,
            "abstract_matched_as_rounding": len(read.rounded),
            "abstract_not_found": len(read.not_found),
            "abstract_conflicts": len(read.conflicts)}  # fmt: skip


# ------------------------------------------------------------------------------- the text


def _shown(root: Path | None):
    def show(path: Path) -> str:
        if root is None:
            return path.name
        try:
            return str(path.relative_to(root))
        except ValueError:
            return path.name

    return show


def _ranges(numbers: list[int]) -> str:
    """"3-25, 29": sorted line numbers, with any no more than two apart shown as a range,
    since reference entries are usually separated by blank lines."""
    runs: list[list[int]] = []
    for number in numbers:
        if runs and number - runs[-1][-1] <= 2:
            runs[-1].append(number)
        else:
            runs.append([number])
    return ", ".join(f"{r[0]}-{r[-1]}" if len(r) > 1 else str(r[0]) for r in runs)


def render(report, discrimination, root: Path | None = None) -> str:
    show = _shown(root)
    lines = _header(report)
    for heading, said in (
        ("Could not read:", report.unreadable),
        ("Outputs not read as given:", report.skipped),
        ("Passed over in a folder (a note, not counted by --strict):", report.passed_over),
        ("Not audited:", report.not_audited),
    ):
        if said:
            lines += ["", heading, *(f"  {item}" for item in said)]
    lines += ["", f"=== {MEMBERSHIP} ===", *_membership(report, discrimination, show)]
    lines += ["", f"=== {ARITHMETIC} ===", *_arithmetic(report, show)]
    if report.abstract is not None:
        lines += ["", f"=== {ABSTRACT} ===", *_abstract(report.abstract, show)]
    lines += ["", f"=== {SMALL_CELLS} ===", *_small_cells(report, show)]
    if report.gates:
        lines += ["", f"=== {WRITING} and {LANGUAGE} (not counted by --strict) ===",
                  *_gates(report, root)]  # fmt: skip
    if report.references:
        lines += ["", f"=== {REFERENCES} (not counted by --strict) ===",
                  *_references(report, show)]  # fmt: skip
    lines.append("")
    if report.compared:
        lines.append(
            "This audit asks only whether a number appears somewhere in the outputs. It "
            "cannot tell whether it appears in the right place, or whether the sentence "
            "around it is true. For a paper still being written, bind the numbers instead: "
            "`manuscript-guard init`."
        )
    else:
        lines.append(
            "No number was compared with the analysis: give --against the outputs to compare "
            "them. For a paper still being written, bind the numbers instead: "
            "`manuscript-guard init`."
        )
    return "\n".join(lines)


def _header(report) -> list[str]:
    if report.compared:
        first = (f"Audited {len(report.papers)} file(s) against {len(report.backing_values)} "
                 f"distinct numbers from {len(report.backing_files)} output file(s).")  # fmt: skip
        apart = (
            f", and {len(report.reference_like)} not found on lines read as reference entries"
            if report.reference_like
            else ""
        )
        second = (f"{report.examined} numeric tokens: {report.classified} conventions or "
                  f"references, {len(report.matched)} found in the outputs, "
                  f"{len(report.unmatched)} not found{apart}.")  # fmt: skip
        return [first, second]
    return [
        f"Audited {len(report.papers)} file(s). {NO_OUTPUTS}.",
        f"{report.examined} numeric tokens: {report.classified} conventions or references, "
        f"{report.uncompared} not compared.",
    ]


def _membership(report, discrimination, show) -> list[str]:
    if not report.compared:
        return ["  Nothing was compared: --against names the outputs to compare the numbers "
                "with."]
    lines: list[str] = []
    if report.unmatched:
        lines.append("NOT FOUND IN ANY OUTPUT — check each of these:")
        by_source: dict[Path, list] = {}
        for candidate in report.unmatched:
            by_source.setdefault(candidate.source, []).append(candidate)
        for source, listed in by_source.items():
            lines.append(f"  {show(source)}")
            for candidate in listed[:LISTED]:
                lines.append(f"    line {candidate.line}: {candidate.text}")
                lines.append(f"      {candidate.context}")
            if len(listed) > LISTED:
                lines.append(f"    (+{len(listed) - LISTED} more)")
    if report.reference_like:
        lines += [""] if lines else []
        lines.append(
            "NOT FOUND, ON LINES READ AS REFERENCE ENTRIES — mostly volumes, pages and years; "
            "a caption or sentence misread as an entry shows up here (not counted by --strict):"
        )
        by_line: dict[Path, dict[int, list[str]]] = {}
        for candidate in report.reference_like:
            numbers = by_line.setdefault(candidate.source, {})
            numbers.setdefault(candidate.line, []).append(candidate.text)
        for source, numbers in by_line.items():
            lines.append(f"  {show(source)}")
            ordered = sorted(numbers)
            for number in ordered[:LISTED]:
                lines.append(f"    line {number}: {', '.join(numbers[number])}")
            if len(ordered) > LISTED:
                lines.append(f"    (+{len(ordered) - LISTED} more lines: "
                             f"{_ranges(ordered[LISTED:])})")  # fmt: skip
    if not lines:
        lines.append("  Every number compared is in the outputs.")
    lines += ["", *_worth(discrimination)]
    return lines


def _worth(discrimination) -> list[str]:
    lines = [
        "What a match is worth here:",
        f"  integers 1-100    {discrimination.small_integers:6.0%} of all possible values "
        f"already match",
        f"  integers 1-1000   {discrimination.medium_integers:6.0%}",
        f"  two-decimal       {discrimination.two_decimals:6.0%}",
        f"  {discrimination.verdict()}",
    ]
    if discrimination.small_integers > 0.5:
        lines.append(
            "  Point --against at the analysis outputs rather than the raw data if you can. "
            "A row-level dataset contains most small integers, so it matches almost anything."
        )
    return lines


def _listed(heading: str, found: list, show) -> list[str]:
    """A heading, then each item under the file it is in, with its line and its row."""
    if not found:
        return []
    lines = [heading]
    by_paper: dict[Path, list] = {}
    for item in found:
        by_paper.setdefault(item.source, []).append(item)
    for source, listed in by_paper.items():
        lines.append(f"  {show(source)}")
        for item in listed[:LISTED]:
            lines.append(f"    line {item.line}: {item.message}")
            lines.append(f"      {item.context}")
        if len(listed) > LISTED:
            lines.append(f"    (+{len(listed) - LISTED} more)")
    return lines


def _arithmetic(report, show) -> list[str]:
    lines = _listed("TOTALS THAT THEIR COUNTS DO NOT ADD UP TO (counted by --strict):",
                    report.sums_off, show)  # fmt: skip
    over = _listed("CATEGORIES THAT ADD UP TO MORE THAN THEIR COLUMN'S N, their shares to 100 "
                   "(counted by --strict):", report.over_n, show)  # fmt: skip
    lines += ([""] if lines and over else []) + over
    if lines and report.disagreements:
        lines.append("")
    if report.disagreements:
        lines.append(
            "NUMBERS THAT DO NOT FIT THE ONES BESIDE THEM: a P and its statistic, t and z "
            "read as two-sided; a ratio and its interval; an interval and its P; an n (%) "
            "and its denominator; a mean of whole numbers and its n (not counted by "
            "--strict):"
        )
        by_paper: dict[Path, list] = {}
        for item in report.disagreements:
            by_paper.setdefault(item.source, []).append(item)
        for source, listed in by_paper.items():
            lines.append(f"  {show(source)}")
            for item in listed:
                lines.append(f"    line {item.line}: {item.message}")
                lines.append(f"      {item.context}")
    if report.whole_numbers:
        lines += [""] if lines else []
        lines.append(
            f"Means of whole numbers (--whole-numbers): {report.means_read} read in the rows "
            f"named, {len(report.means_not_assessable)} not assessable, every mean printed "
            f"to their places being possible for their n (any n of 10 to the power of the "
            f"places or more, and a few just under)."
        )
        apart: dict[Path, list] = {}
        for item in report.means_not_assessable:
            apart.setdefault(item.source, []).append(item)
        for source, listed in apart.items():
            lines.append(f"  {show(source)}")
            lines += [f"    line {item.line}: {item.message}" for item in listed[:LISTED]]
            if len(listed) > LISTED:
                lines.append(f"    (+{len(listed) - LISTED} more)")
        lines += [
            f"  --whole-numbers {label!r}: no mean was read in a row whose label holds it"
            for label in report.whole_numbers_unfound
        ]
    flows = _flows(report, show)
    lines += ([""] if lines and flows else []) + flows
    return lines or ["  Nothing read here disagrees with the numbers beside it."]


def _flows(report, show) -> list[str]:
    """The flows read from nested lists: a count of them, each whose arithmetic does not
    hold, and the notes."""
    if not report.flows_read and not report.flow_notes:
        return []
    lines = [f"Flows read from nested lists: {report.flows_read}, each held to its arithmetic "
             "(a stage less its exclusions is the next, the arms add up to the last stage)."]
    lines += _listed("FLOWS WHOSE ARITHMETIC DOES NOT HOLD (counted by --strict):",
                     report.flows_broken, show)  # fmt: skip
    if report.flow_notes:
        lines.append("Notes on flows (not counted by --strict):")
        by_paper: dict[Path, list] = {}
        for item in report.flow_notes:
            by_paper.setdefault(item.source, []).append(item)
        for source, listed in by_paper.items():
            lines.append(f"  {show(source)}")
            lines += [f"    {f'line {item.line}: ' if item.line else ''}{item.message}"
                      for item in listed[:LISTED]]  # fmt: skip
            if len(listed) > LISTED:
                lines.append(f"    (+{len(listed) - LISTED} more)")
    return lines


def _abstract(read, show) -> list[str]:
    """The Abstract against Results, ending with what a match is worth there."""
    if not read.compared:
        return [f"  Not compared: {read.why_not}."]
    lines = [f"{read.numbers} number(s) in the Abstract the conventions do not explain: "
             f"{read.matched} found where the paper reports (the Methods, the Results, its "
             f"tables, a file with no Abstract), {len(read.rounded)} matched as a rounding, "
             f"{len(read.not_found)} not found."]
    for heading, found in (
        ("AN INTERVAL OR A TEST THAT DIFFERS FROM ITS COUNTERPART IN ONE NUMBER (counted by "
         "--strict):", read.conflicts),
        ("NOT FOUND WHERE THE PAPER REPORTS (not counted by --strict):", read.not_found),
        ("MATCHED AS A ROUNDING (not counted by --strict):", read.rounded),
    ):
        listed = [_Said(c.source, c.line, c.message if hasattr(c, "message") else c.text, c.context)
                  for c in found]  # fmt: skip
        listing = _listed(heading, listed, show)
        lines += ([""] if listing else []) + listing
    worth = _worth(read.discrimination)
    worth[0] = ("What a match is worth here, against the numbers the paper reports, "
                "roundings counted in:")
    return [*lines, "", *worth[:5]]


@dataclass(frozen=True)
class _Said:
    source: Path
    line: int
    message: str
    context: str


def _small_cells(report, show) -> list[str]:
    if report.minimum is None:
        lines = ["No minimum given (--minimum-cell-count): a count held back is taken to hide "
                 "every count from 1 to its bound."]  # fmt: skip
    else:
        lines = [f"The data custodian's minimum: {report.minimum} (--minimum-cell-count)."]
    found = _listed("GIVEN AWAY BY A TOTAL PRINTED BESIDE IT (counted by --strict):",
                    report.recovered, show)  # fmt: skip
    by_n = _listed("GIVEN AWAY BY ITS COLUMN'S N, if none of the column lacks the "
                   "characteristic (not counted by --strict):", report.recovered_by_n, show)
    lines += found + ([""] if found and by_n else []) + by_n
    if not found and not by_n:
        lines.append("  No count held back (\"<5\") can be worked out from a total beside it.")
    return lines


def _gates(report, root: Path | None) -> list[str]:
    lines: list[str] = []
    for run in report.gates:
        if run.note:
            lines.append(f"  {run.note}")
            continue
        lines.append(f"  {_shown(root)(run.paper)}: {len(run.writing)} from G6, "
                     f"{len(run.language)} from G14"
                     + ("; lines are those of the text pandoc converts it to, as `init "
                        "--from` writes it" if run.converted else ""))  # fmt: skip
        found = (*run.writing, *run.language)
        if found:
            lines.append(Report(found).render(root))
    return lines


def _references(report, show) -> list[str]:
    lines: list[str] = []
    looked: dict[Path, list] = {}
    for one in report.lookups or []:
        looked.setdefault(one.path, []).append(one)
    for census in report.references:
        if census.note:
            lines.append(f"  {show(census.path)}: {census.note}")
            continue
        count = len(census.entries)
        style = census.style
        if census.markers and style != "not numbered":
            style += f", {census.markers} citation{'s' if census.markers != 1 else ''} read"
        lines.append(f"  {show(census.path)}: {count} entr{'y' if count == 1 else 'ies'}, "
                     f"{census.dois} with a DOI, {census.pmids} with a PMID; {style}")  # fmt: skip
        for problem in census.problems[:LISTED]:
            lines.append(f"    {_at(problem.path, problem.line, census.path, show)}"
                         f"{problem.message}")  # fmt: skip
        if len(census.problems) > LISTED:
            lines.append(f"    (+{len(census.problems) - LISTED} more)")
        lines += _looked(looked.get(census.path, []), census.path, show)
    if report.lookups is None:
        lines.append(
            "  Nothing was looked up: --lookup asks Crossref and OpenAlex of each DOI, and "
            "DataCite and doi.org of one Crossref has no record of, and PubMed of each PMID, "
            "whether the work was retracted, withdrawn or put under concern, and --lookup "
            "--dry-run shows what would be sent."
        )
    return lines


def _at(path: Path | None, line: int | None, paper: Path, show) -> str:
    """"line 3: ", or "refs.tex line 3: " where the line is another file's than the paper's:
    a LaTeX paper's `thebibliography` in a file it inputs (round 1 of #463)."""
    if not line:
        return ""
    return f"{show(path)} line {line}: " if path is not None and path != paper else (
        f"line {line}: ")  # fmt: skip


def _looked(looked: list, paper: Path, show) -> list[str]:
    if not looked:
        return []
    if not looked[0].came:
        return [f"    would ask {one.asked} ({one.entry.label})" for one in looked]
    kept = sum(1 for one in looked if one.came == "kept")
    lines = [f"    looked up {len(looked)} entr{'y' if len(looked) == 1 else 'ies'}"
             + (f", {kept} from the records kept" if kept else "")]  # fmt: skip
    said = [problem for one in looked for problem in one.problems]
    lines += [f"    {_at(p.path, p.line, paper, show)}{p.message}" for p in said]
    if not said:
        known = sum(1 for one in looked if one.known)
        lines.append(f"    no registry said a work was retracted, withdrawn or under concern: "
                     f"{len(looked)} asked, {known} known to a registry that answered")  # fmt: skip
    return lines
