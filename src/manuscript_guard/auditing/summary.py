"""The audit's report at a glance: what each check found, in a line, before the sections; and
G6's and G14's findings grouped by kind, a line to a place, each kind's advice once.

Asked for by Basile on 2026-11-09 after auditing one of his own papers through the web page:
"no one will read the current output". Its 103 findings on the words took three lines each,
the same advice repeated under every one of 90 abbreviations, and the sections that found
nothing came first. Every place of every finding, with its context and its advice, is still
printed with `--details`, and `--json` holds all of it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from manuscript_guard.findings import FAIL, Finding

#: How many places of one kind are listed before only a count of the rest.
PLACES = 8

#: What each kind of finding on the words is, in a few words, by its code. A code that is
#: not here is named by itself.
KINDS = {
    "abbreviation-undefined": "Abbreviations used and not defined",
    "abbreviation-used-before-defined": "Abbreviations used before they are defined",
    "abbreviation-redefined": "Abbreviations defined more than once",
    "abbreviation-unused": "Abbreviations defined and not used again",
    "spelling-variant": "Words in the other English",
    "spelling-mixed": "British and American spelling mixed",
    "spelling-not-as-declared": "Words not in the English chosen for the paper",
    "notation-interval": "Intervals written two ways",
    "notation-sign-spacing": "Signs spaced two ways",
    "notation-p-symbol": "P values written two ways",
    "notation-percent": "Percentages written two ways",
    "notation-unit": "Numbers run into their units",
    "notation-space-missing": "Numbers and words run together",
    "term-avoided": "Terms the field avoids",
    "vocabulary-conflict": "One thing named two ways",
    "code-name-in-prose": "Names from the code in the text",
    "ai-phrasing": "Phrasing to look at",
    "ai-cadence": "Habits more frequent than in papers by people",
    "vague-attribution": "Claims attributed to no one",
    "revision-residue": "Words left from a revision",
    "placeholder-template": "Instructions left from a template",
    "model-artefact": "Words left by a language model",
    "no-headings": "No headings",
}


def kinds_of(found: list[Finding]) -> dict[tuple[str, str], list[Finding]]:
    """`found` by gate and code, in the order each kind is first met."""
    kinds: dict[tuple[str, str], list[Finding]] = {}
    for finding in found:
        kinds.setdefault((finding.gate, finding.code), []).append(finding)
    return kinds


def grouped(found: list[Finding], at: Callable[[Path | None, int | None], str]) -> list[str]:
    """G6's and G14's findings by kind, the kinds with most first: a title and a count, a
    line to each of its first `PLACES` places, and its advice once. `at` says a place: a
    line, or a PDF's page and line."""
    lines: list[str] = []
    ordered = sorted(kinds_of(found).items(), key=lambda kind: -len(kind[1]))
    for (gate, code), unordered in ordered:
        mine = sorted(unordered, key=lambda one: (str(one.path), one.line or 0))
        lines += ["", f"  {KINDS.get(code, code)} ({gate}, {len(mine)})"]
        # One hint for the kind where its places share it, as G14's do; each its own where
        # they differ, as G6's rates do.
        shared = len({finding.hint for finding in mine}) == 1
        for finding in mine[:PLACES]:
            where = at(finding.path, finding.line) if finding.line else "the paper"
            failing = "FAIL: " if finding.severity == FAIL else ""
            lines.append(f"    {where}: {failing}{finding.message}")
            if finding.context and gate in QUOTING:
                lines.append(f"      > {finding.context}")
            if finding.hint and not shared:
                lines.append(f"      Hint: {finding.hint}")
        if len(mine) > PLACES:
            lines.append(f"    and {len(mine) - PLACES} more: {DETAILS} lists every place")
        if mine[0].hint and shared:
            lines.append(f"    Hint: {mine[0].hint}")
    return lines


#: The gates whose messages name a rule, not the words it matched, so that the words are
#: shown beside each place: G6's phrasing, "importance-tail: An '-ing' tail ...", says what
#: kind of phrase it found and not which (round 1 of #600). G14's quote the word.
QUOTING = frozenset({"G6"})
#: How the report names the option that lists every place, on the command line and on the
#: web page, which shows the same text.
DETAILS = "--details (on the web page, the box \"List every place of every finding\")"


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def _membership(report) -> str:
    if not report.compared:
        return "not run: no outputs were given to compare the numbers with (--against)"
    said = (f"{_n(len(report.matched), 'number')} found in the outputs, "
            f"{len(report.unmatched)} not found")  # fmt: skip
    return said + (" (counted by --strict)" if report.unmatched else "")


def _arithmetic(report) -> str:
    counted = [_n(len(report.sums_off), "total") + " off its counts" if report.sums_off else "",
               _n(len(report.over_n), "column") + " over its n" if report.over_n else "",
               _n(len(report.flows_broken), "flow") + " that does not add up"
               if report.flows_broken else ""]  # fmt: skip
    counted = [part for part in counted if part]
    said = "; ".join(counted) + (" (counted by --strict)" if counted else "")
    if report.over_n_rounding:
        said += ("; " if said else "") + (
            _n(len(report.over_n_rounding), "column") + " over its n by no more than rounding")
    if report.disagreements:
        said += ("; " if said else "") + (
            f"{_n(len(report.disagreements), 'number')} that may not fit the ones beside it")
    return said or "nothing disagrees with the numbers beside it"


def _abstract(read) -> str:
    if not read.compared:
        return f"not compared: {read.why_not}"
    said = (f"{_n(read.numbers, 'number')}: {read.matched} found where the paper reports its "
            f"results, {len(read.rounded)} only as a rounding, {len(read.not_found)} not "
            "found")  # fmt: skip
    if read.conflicts:
        said += f"; {_n(len(read.conflicts), 'interval or test', 'intervals or tests')} that " \
                "differ (counted by --strict)"  # fmt: skip
    return said


def _small_cells(report) -> str:
    if report.recovered:
        return (f"{_n(len(report.recovered), 'count')} held back that a total gives away "
                "(counted by --strict)")
    if report.recovered_by_n:
        return (f"{_n(len(report.recovered_by_n), 'count')} held back that a column's n may "
                "give away")
    return "no count held back can be worked out"


def _words(report) -> str:
    """G6's and G14's findings counted, and each paper they did not run on said: one
    unread paper beside another's findings is not a paper checked (round 1 of #600)."""
    unread = [run for run in report.gates if run.note]
    found = [finding for run in report.gates for finding in (*run.writing, *run.language)]
    said = (f"{_n(len(found), 'finding')} to look at, in {_n(len(kinds_of(found)), 'kind')} "
            "(not counted by --strict)" if found else "")  # fmt: skip
    if unread:
        names = ", ".join(run.paper.name for run in unread)
        said += ("; " if said else "") + f"not run on {names}: see below"
    return said or "nothing reported"


def _references(report) -> str:
    """The reference lists counted: the entries of those told apart, the identifiers of
    those whose entries were not, and a paper in which no list was read, each as it is
    (round 1 of #600: one list not told apart stood for all, and PMIDs went unsaid)."""
    from manuscript_guard.auditing.references import UNTOLD

    told = [census for census in report.references if not census.note and census.style != UNTOLD]
    untold = [census for census in report.references if census.style == UNTOLD]
    parts = []
    if told:
        parts.append(f"{_n(sum(len(c.entries) for c in told), 'entry', 'entries')} read, "
                     f"{sum(c.dois for c in told)} with a DOI")  # fmt: skip
    if untold:
        parts.append(f"{_n(sum(c.dois for c in untold), 'DOI')} and "
                     f"{_n(sum(c.pmids for c in untold), 'PMID')} read in a list whose "
                     "entries were not told apart")  # fmt: skip
    noted = [census for census in report.references if census.note]
    if noted:
        parts.append(f"{_n(len(noted), 'paper')} with no list read: see below")
    said = "; ".join(parts) or "no reference list read"
    if report.lookups is None:
        return said + "; none looked up in the registries (--lookup)"
    return said + f"; {_n(len(report.lookups), 'work')} looked up"


#: What `--strict` fails on, said once under the checks, so that "not counted by --strict"
#: means something to a reader who will never pass it (the author's audit, 2026-11-10).
STRICT = ("--strict, for a script, fails on what the audit counts, among it a number in no "
          "output, arithmetic that does not hold and a paper that could not be read. What is "
          "marked \"not counted by --strict\" is for a reader to look at.")


def checks(report) -> list[str]:
    """What each check found, a line each, in the order of the sections below, then what
    `--strict` counts (`STRICT`)."""
    found = rows(report)
    width = max(len(name) for name, _said in found)
    return [*(f"  {name.ljust(width)}  {said}" for name, said in found), "", STRICT]


def kinds(found: list[Finding], at: Callable[[Path | None, int | None], str], *,
          details: bool = False) -> list[dict]:  # fmt: skip
    """G6's and G14's findings by kind, as `grouped` orders them, each with every place: a
    title, its gate and code, a count, the hint the places share or None, and each place,
    where it is, what it says, its context and its own hint. What the page draws, a kind to
    a fold, every place inside it. With `details` every context, as the text gives them."""
    out = []
    ordered = sorted(kinds_of(found).items(), key=lambda kind: -len(kind[1]))
    for (gate, code), unordered in ordered:
        mine = sorted(unordered, key=lambda one: (str(one.path), one.line or 0))
        shared = len({finding.hint for finding in mine}) == 1
        out.append({
            "title": KINDS.get(code, code), "gate": gate, "code": code, "count": len(mine),
            "hint": mine[0].hint if shared else None,
            "places": [{"where": at(finding.path, finding.line) if finding.line else "the paper",
                        "message": finding.message,
                        # The words matched, where the message does not say them, as the
                        # text shows them (`QUOTING`); every context with `details`.
                        "context": finding.context if details or gate in QUOTING else None,
                        "failing": finding.severity == FAIL,
                        "hint": None if shared else finding.hint} for finding in mine],
        })  # fmt: skip
    return out


def rows(report) -> list[tuple[str, str]]:
    """What each check found, by check, in the order of the sections."""
    from manuscript_guard.auditing.report import MEMBERSHIP

    rows = [(MEMBERSHIP, _membership(report)), ("Arithmetic", _arithmetic(report))]
    if report.abstract is not None:
        rows.append(("Abstract against Results", _abstract(report.abstract)))
    rows.append(("Small cells", _small_cells(report)))
    if report.gates:
        rows.append(("Writing and language", _words(report)))
    if report.references:
        rows.append(("References", _references(report)))
    for name, present in (("Journal", report.journal), ("Causal words", report.causal),
                          ("Cited sentences", report.cited),
                          ("Self-citation", report.self_citation),
                          ("Package", report.package)):  # fmt: skip
        if present is not None:
            rows.append((name, "see its section below"))
    return rows


__all__ = ["KINDS", "PLACES", "checks", "grouped", "kinds", "kinds_of", "rows"]
