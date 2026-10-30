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
* Journal (G4), with `--journal`: the main document held to the journal's profile, what was
  not checked, and the profile's rules no gate checks (`auditing.journal`).
* Document, with `--journal`: what each .docx holds besides its text (`auditing.document`),
  and with `--authors` each author named where the journal's review is blind.
* Causal words, with `--design`: each sentence of the Abstract, the Discussion and the
  Conclusion that claims a cause with no hedge, negation or citation (`auditing.causal`).
* Cited sentences, with `--cited`: how many rows the file holds and what was not read
  (`auditing.cited`); the sentences themselves are in the file only.
* Self-citation, with `--journal` and `--authors` or `--lookup`: the references whose
  registry record lists an author, and those the journal published (`auditing.selfcite`).

`--strict` counts the numbers not found in the outputs, a paper or a stretch of one that
could not be read, an audit that read no number, and what is exact arithmetic: a total that
its counts do not add up to (`sum-off`), categories that add up to more than their column's
n (`over-header-n`), and a count held back that a printed total gives away
(`count-recoverable`), a flow whose arithmetic does not hold under a heading, a caption or a
paragraph that names a flow (`flow-broken`; under none it is a note, Basile, 2026-10-29), and an
interval or a test of the Abstract that differs from its counterpart where the paper reports
(`abstract-conflict`); and an author named in a document the journal reviews blind
(`blind-document-names-author`, Basile, 2026-10-29). Nothing else is counted: the P worked
out from a statistic, G6 and G14 (the author, 2026-10-28), G7's findings, a count held back
that only a column's n gives away, which holds only where none of the column lacks the
characteristic, a number of the Abstract found nowhere the paper reports (the author,
2026-10-28), G4's findings and the Document section's counts, the causal words, the cited
sentences and the self-citation counts (Basile, 2026-10-29).
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
JOURNAL = "Journal (G4)"
DOCUMENT = "Document"
CAUSAL = "Causal words"
CITED = "Cited sentences"
SELF_CITATION = "Self-citation"
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
    return (found + _journal_items(report.journal) + _document_items(report)
            + _causal_items(report.causal) + _cited_items(report.cited)
            + _self_citation_items(report.self_citation))  # fmt: skip


def _causal_items(read) -> list[Item]:
    """Each sentence that claims a cause, a warning not counted; and each file none of whose
    sentences was read, as a note."""
    if read is None:
        return []
    from manuscript_guard.auditing.causal import CODE, HINT, said

    return [
        *(Item(CAUSAL, "audit", CODE, said(one), WARN, False, one.path, one.line, one.sentence,
               HINT) for one in read.found),
        *(Item(CAUSAL, "audit", "causal-words-not-read", _unplaced(path), INFO, False, path)
          for path in read.unplaced),
        *(Item(CAUSAL, "audit", "causal-words-not-read", f"{path.name}: {note}", INFO, False,
               path) for path, note in read.notes),
    ]  # fmt: skip


def _unplaced(path: Path) -> str:
    return (f"{path.name}: no heading names its Abstract, Discussion or Conclusion, so none of "
            "its sentences was read for causal words")  # fmt: skip


def _cited_items(read) -> list[Item]:
    """The cited sentences: how many rows the file holds, never a sentence; what was not
    listed; and what Europe PMC would be asked, on a dry run."""
    if read is None:
        return []
    found = [Item(CITED, "audit", "cited-written", _cited_said(read), INFO, False,
                  read.written)]  # fmt: skip
    found += [Item(CITED, "audit", "cited-not-listed", note, INFO, False, path)
              for path, note in read.notes]  # fmt: skip
    if read.dry_run:
        found += [Item(CITED, "audit", "would-ask", f"{one.entry.label}: would ask {one.asked}",
                       INFO, False, one.entry.path, one.entry.line)
                  for one in read.fetched or []]  # fmt: skip
    return found


def _cited_said(read) -> str:
    """How many rows the file holds, and what more is in it."""
    rows = len(read.rows)
    sentences = len({(row.path, row.line, row.sentence) for row in read.rows})
    listed = sum(1 for row in read.rows if row.entry is not None)
    said = (f"{rows} row{'s' if rows != 1 else ''}, one for each work a citation names, in "
            f"{sentences} sentence{'s' if sentences != 1 else ''}; {listed} with its entry of "
            f"the reference list, {rows - listed} with none")
    if read.written is not None:
        said += f"; written to {read.written}"
    fetched = read.fetched
    if fetched and not read.dry_run:
        found = sum(1 for one in fetched if one.answer.get("abstract"))
        said += (f"; Europe PMC asked of {len(fetched)} work"
                 f"{'s' if len(fetched) != 1 else ''}, {found} with an abstract")  # fmt: skip
    if read.author_year or read.pandoc:
        said += (f"; not listed: {read.author_year} citation(s) by author and year, "
                 f"{read.pandoc} pandoc citation(s) by key")  # fmt: skip
    return said


def _self_citation_items(said) -> list[Item]:
    """The self-citation counts, each with its list of entries; none counted."""
    if said is None:
        return []
    if said.note:
        return [Item(SELF_CITATION, "audit", "self-citation-not-counted", said.note, INFO,
                     False)]  # fmt: skip
    found = [Item(SELF_CITATION, "audit", "self-citation-read", _looked_said(said), INFO, False)]
    if said.authors_note:
        found.append(Item(SELF_CITATION, "audit", "self-citation-not-counted",
                          said.authors_note, INFO, False))  # fmt: skip
    found += [Item(SELF_CITATION, "audit", "self-citation-author",
                   f"{author.shown}: {_entries_said(listed)}, whose registry record lists an "
                   "author of that family name and first initial", INFO, False)
              for author, listed in said.authors]  # fmt: skip
    if said.journal:
        found.append(Item(SELF_CITATION, "audit", "self-citation-journal",
                          f"{said.journal}: {_entries_said(said.in_journal)}, published in it "
                          "by what the registries say", INFO, False))  # fmt: skip
    return found


def _entries_said(listed: list) -> str:
    count = len(listed)
    said = f"{count} reference{'s' if count != 1 else ''}"
    return said + (" (" + ", ".join(one.entry.label for one in listed) + ")" if listed else "")


def _looked_said(said) -> str:
    return (f"{said.looked} entr{'y' if said.looked == 1 else 'ies'} looked up, {said.no_people} "
            f"of them with no author list from a registry and {said.no_journal} with no "
            f"journal; {said.unlooked} not looked up, having no DOI or PMID, and not counted")


def _journal_items(run) -> list[Item]:
    """G4 held to the journal's profile: its findings, none counted; what it did not check,
    and the profile's rules no gate checks, as notes."""
    if run is None:
        return []
    if run.note:
        found = [Item(JOURNAL, "G4", "journal-not-run", run.note, INFO, False, run.paper)]
    else:
        found = [_from_finding(JOURNAL, finding) for finding in run.findings]
    found += [Item(JOURNAL, "G4", "journal-not-checked", f"not checked here: {what}", INFO,
                   False, run.profile) for what in run.skipped]  # fmt: skip
    found += [Item(JOURNAL, "G4", "journal-manual-rule", f"to check by hand: {rule}", INFO,
                   False, run.profile, context=quote or None) for rule, quote in run.manual]
    found += [Item(JOURNAL, "G4", "journal-not-main-document", f"{other.name} was read as "
                   "the rest of the submission, and not held to the journal's limits", INFO,
                   False, other) for other in run.others]  # fmt: skip
    return found


def _document_items(report) -> list[Item]:
    """What each .docx holds besides its text, none counted; and each author named in a
    document the journal reviews blind, each counted."""
    from manuscript_guard.auditing.document import described

    found: list[Item] = []
    for facts in report.documents:
        held = facts.insertions + facts.deletions + facts.moves + facts.comments + facts.hidden
        found.append(Item(DOCUMENT, "audit", "document-unreadable" if facts.note else
                          "document-holds", described(facts), INFO if facts.note or not held
                          else WARN, False, facts.path))  # fmt: skip
        found += [Item(DOCUMENT, "audit", "document-person", f"{where}: {name}", INFO, False,
                       facts.path) for where, name in facts.people]  # fmt: skip
    run = report.journal
    if run is not None:
        found += [Item(DOCUMENT, "audit", f.code, f.message, FAIL, True, f.path, f.line,
                       f.context, f.hint) for f in run.named]  # fmt: skip
        if run.blind_note:
            found.append(Item(DOCUMENT, "audit", "authors-not-looked-for", run.blind_note,
                              INFO, False, run.paper))  # fmt: skip
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
        "flows_named": report.flows_named,
        "flows_broken": len(report.flows_broken),
        **_abstract_counts(report.abstract),
        "reference_entries": sum(len(c.entries) for c in report.references),
        **_reader_counts(report),
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
            "findings": [placed(item.as_dict(), item.path, item.line, report.pdfs)
                         for item in listed],
        },
        indent=2,
        # As `check --json`: a pipe on Windows is cp1252.
        ensure_ascii=True,
    )


def _reader_counts(report) -> dict[str, int]:
    """The counts of what `--journal` and `--authors` read, where either was given."""
    counts: dict[str, int] = {}
    run = report.journal
    if run is not None:
        counts["journal_findings"] = len(run.findings)
        counts["journal_manual_rules"] = len(run.manual)
        counts["authors_named"] = len(run.named)
    # A PDF's are not read, and are not counted as none (`auditing.document.pdf_facts`).
    word = [facts for facts in report.documents if not facts.pdf]
    if word:
        for key, name in (("tracked_insertions", "insertions"), ("tracked_deletions",
                          "deletions"), ("tracked_moves", "moves"), ("comments", "comments"),
                          ("hidden_runs", "hidden")):  # fmt: skip
            counts[key] = sum(getattr(facts, name) for facts in word)
    if report.causal is not None:
        counts["causal_sentences_read"] = report.causal.read
        counts["causal_words"] = len(report.causal.found)
    if report.cited is not None:
        counts["cited_rows"] = len(report.cited.rows)
        counts["cited_sentences"] = len({(row.path, row.line, row.sentence)
                                         for row in report.cited.rows})  # fmt: skip
    said = report.self_citation
    if said is not None and not said.note:
        counts["self_citation_looked_up"] = said.looked
        if said.journal:
            counts["self_citation_journal"] = len(said.in_journal)
    return counts


def _abstract_counts(read) -> dict[str, int]:
    if read is None or not read.compared:
        return {}
    return {"abstract_numbers": read.numbers, "abstract_matched": read.matched,
            "abstract_matched_as_rounding": len(read.rounded),
            "abstract_not_found": len(read.not_found),
            "abstract_conflicts": len(read.conflicts)}  # fmt: skip


# ------------------------------------------------------------------------------- the text


class _Show:
    """How the report names a file and a place in it: a file relative to `root`, a line as
    "line 12", and a line of a PDF's text as its page and its line (`auditing.pdf`)."""

    def __init__(self, root: Path | None, pdfs: dict | None = None) -> None:
        self.root = root
        self.pdfs = pdfs or {}

    def __call__(self, path: Path) -> str:
        if self.root is None:
            return path.name
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return path.name

    def pdf(self, path: Path | None):
        return self.pdfs.get(path) if path is not None else None

    def at(self, path: Path | None, line: int | None) -> str:
        """"line 12", or "page 3, line 12" in a PDF."""
        pdf = self.pdf(path)
        return pdf.said(line) if pdf is not None else f"line {line}"

    def located(self, path: Path, line: int | None) -> str:
        """"paper.md:12", or "paper.pdf, page 3, line 12"."""
        pdf = self.pdf(path)
        if pdf is None:
            return f"{self(path)}:{line}" if line else self(path)
        return f"{self(path)}, {pdf.said(line)}" if line else self(path)


def _shown(root: Path | None, pdfs: dict | None = None) -> _Show:
    return _Show(root, pdfs)


def placed(item_dict: dict, path: Path | None, line: int | None, pdfs: dict) -> dict:
    """A finding as JSON, its line given as a page and a line where it is a PDF's
    (`auditing.pdf.Place`)."""
    pdf = pdfs.get(path) if path is not None else None
    place = pdf.place(line) if pdf is not None else None
    return item_dict if place is None else {**item_dict, **place.as_dict()}


def _rendered(found, root: Path | None, show: _Show) -> str:
    """Findings as `Report.render` gives them, a PDF's at its page and line."""
    if not any(show.pdf(finding.path) is not None for finding in found):
        return Report(tuple(found)).render(root)
    lines: list[str] = []
    for finding in Report(tuple(found)).sorted().findings:
        where = finding.located()
        if show.pdf(finding.path) is not None:
            where = show.located(finding.path, finding.line)
        elif root is not None and finding.path is not None and finding.path.is_relative_to(root):
            where = where.replace(str(finding.path), str(finding.path.relative_to(root)), 1)
        lines.append(f"  [{finding.severity.upper():4}] {finding.gate} {where}")
        lines.append(f"         {finding.message}")
        if finding.context:
            lines.append(f"         > {finding.context}")
        if finding.hint:
            lines.append(f"         hint: {finding.hint}")
    return "\n".join(lines)


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
    show = _shown(root, report.pdfs)
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
                  *_gates(report, root, show)]  # fmt: skip
    if report.references:
        lines += ["", f"=== {REFERENCES} (not counted by --strict) ===",
                  *_references(report, show)]  # fmt: skip
    if report.journal is not None:
        lines += ["", f"=== {JOURNAL} (not counted by --strict) ===",
                  *_journal(report.journal, root, show)]  # fmt: skip
    if report.documents or report.journal is not None:
        lines += ["", f"=== {DOCUMENT} ===", *_document(report, show)]
    if report.causal is not None:
        lines += ["", f"=== {CAUSAL} (--design {report.causal.design}; not counted by "
                  "--strict) ===", *_causal(report.causal, show)]  # fmt: skip
    if report.cited is not None:
        lines += ["", f"=== {CITED} (not counted by --strict) ===", *_cited(report.cited, show)]
    if report.self_citation is not None:
        lines += ["", f"=== {SELF_CITATION} (not counted by --strict) ===",
                  *_self_citation(report.self_citation)]  # fmt: skip
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
                lines.append(f"    {show.at(source, candidate.line)}: {candidate.text}")
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
                lines.append(f"    {show.at(source, number)}: {', '.join(numbers[number])}")
            if len(ordered) > LISTED:
                ranges = "" if show.pdf(source) else f": {_ranges(ordered[LISTED:])}"
                lines.append(f"    (+{len(ordered) - LISTED} more lines{ranges})")
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
            lines.append(f"    {show.at(source, item.line)}: {item.message}")
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
                lines.append(f"    {show.at(source, item.line)}: {item.message}")
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
            lines += [f"    {show.at(source, item.line)}: {item.message}"
                      for item in listed[:LISTED]]  # fmt: skip
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
             "(a stage less its exclusions is the next, the arms add up to the last stage); "
             f"{report.flows_named} under a heading, a caption or a paragraph that names a "
             "flow, whose faults --strict counts."]
    lines += _listed("FLOWS WHOSE ARITHMETIC DOES NOT HOLD, under a name for a flow (counted by "
                     "--strict):", report.flows_broken, show)  # fmt: skip
    if report.flow_notes:
        lines.append("Notes on flows (not counted by --strict):")
        by_paper: dict[Path, list] = {}
        for item in report.flow_notes:
            by_paper.setdefault(item.source, []).append(item)
        for source, listed in by_paper.items():
            lines.append(f"  {show(source)}")
            lines += [f"    {show.at(source, item.line) + ': ' if item.line else ''}"
                      f"{item.message}"
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


def _gates(report, root: Path | None, show: _Show) -> list[str]:
    lines: list[str] = []
    for run in report.gates:
        if run.note:
            lines.append(f"  {run.note}")
            continue
        lines.append(f"  {show(run.paper)}: {len(run.writing)} from G6, "
                     f"{len(run.language)} from G14"
                     + ("; lines are those of the text pandoc converts it to, as `init "
                        "--from` writes it" if run.converted else ""))  # fmt: skip
        found = (*run.writing, *run.language)
        if found:
            lines.append(_rendered(found, root, show))
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


def _journal(run, root: Path | None, show) -> list[str]:
    """G4 held to the profile: what it found, what it did not check, and the editor's
    checklist."""
    lines = [f"  {show(run.paper)} held to {show(run.profile)}"
             + ("; lines are those of the text pandoc converts it to" if run.converted
                else "")]  # fmt: skip
    if run.note:
        lines.append(f"  {run.note}")
    elif run.findings:
        lines.append(_rendered(run.findings, root, show))
    elif run.limits_unchecked:
        # Not "within every limit" where a limit was not checked (round 2 of #478).
        lines.append("  Nothing found in what was checked; a limit not checked is listed "
                     "below.")  # fmt: skip
    else:
        lines.append("  Within every limit, and every section and statement the profile "
                     "requires is there.")  # fmt: skip
    lines += [f"  {other.name}: read as the rest of the submission, not held to the journal's "
              "limits" for other in run.others]  # fmt: skip
    lines.append("  Not checked here:")
    lines += [f"    {what}" for what in run.skipped]
    if run.manual:
        lines.append("  The journal's rules no gate checks, for the editor to check by hand:")
        for rule, quote in run.manual:
            lines.append(f"    [ ] {rule}")
            if quote:
                lines.append(f"        \"{quote}\"")
    return lines


def _document(report, show) -> list[str]:
    """What each .docx holds besides its text, the names Word keeps, and the authors named in
    a document the journal reviews blind."""
    from manuscript_guard.auditing.document import described

    lines: list[str] = []
    if not report.documents:
        lines.append("  Not applicable: no .docx was given, nor a PDF; tracked changes, "
                     "comments and the names Word keeps are a Word file's.")  # fmt: skip
    for facts in report.documents:
        lines.append(f"  {described(facts)} (not counted by --strict)")
        if facts.note or (facts.pdf and facts.unread):
            continue
        fields = "the PDF's Author field" if facts.pdf else "the fields Word keeps"
        lines += [f"    {where}: {name}" for where, name in facts.people] or [
            f"    no person's name in {fields}"]
    run = report.journal
    if run is None:
        return lines
    if run.named:
        lines.append("AN AUTHOR NAMED IN A DOCUMENT THE JOURNAL REVIEWS BLIND (counted by "
                     "--strict):")  # fmt: skip
        lines += [f"  {show(f.path)}: {f.message}" for f in run.named]
    if run.blind_note:
        lines.append(f"  {run.blind_note}")
    elif run.looked and not run.named:
        # Only where the authors were looked for: a review that is not blind, with no
        # --authors, is said nothing of (round 1 of #478).
        lines.append(f"  The journal's review is {run.looked}-blind, and no author was found "
                     "named in what was read.")  # fmt: skip
    return lines


def _causal(read, show) -> list[str]:
    """The causal words: what was read, what was passed over and why, and each sentence."""
    from manuscript_guard.auditing.causal import said

    passed = read.hedged + read.negated + read.cited
    lines = [f"  {read.read} sentence{'s' if read.read != 1 else ''} read in the Abstract, the "
             f"Discussion and the Conclusion; {passed} with a causal word passed over: "
             f"{read.hedged} hedged, {read.negated} negated, {read.cited} cited."]  # fmt: skip
    found = [_Said(one.path, one.line, said(one), one.sentence) for one in read.found]
    lines += _listed("A CAUSAL WORD IN A SENTENCE WITH NO HEDGE, NEGATION OR CITATION (not "
                     "counted by --strict):", found, show)  # fmt: skip
    if not read.found:
        lines.append("  No sentence read claims a cause with no hedge, negation or citation.")
    lines += [f"  {_unplaced(path)}" for path in read.unplaced]
    lines += [f"  {show(path)}: {note}" for path, note in read.notes]
    return lines


def _cited(read, show) -> list[str]:
    """The cited sentences, as counts: the sentences are in the file only."""
    lines = [f"  {_cited_said(read)}."]
    lines += [f"  {show(path)}: {note}." for path, note in read.notes]
    if read.dry_run:
        lines += [f"  would ask {one.asked} ({one.entry.label})" for one in read.fetched or []]
    return lines


def _self_citation(said) -> list[str]:
    """The self-citation counts, each with its entries; never a ratio or a verdict."""
    if said.note:
        return [f"  {said.note}."]
    lines = [f"  {_looked_said(said)}."]
    if said.authors_note:
        lines.append(f"  {said.authors_note}.")
    lines += [f"  {author.shown}: {_entries_said(listed)}, whose registry record lists an author "
              "of that family name and first initial (a namesake counts too)"
              for author, listed in said.authors]  # fmt: skip
    if said.journal:
        lines.append(f"  {said.journal}: {_entries_said(said.in_journal)}, published in it by "
                     "what the registries say")  # fmt: skip
    return lines


def _at(path: Path | None, line: int | None, paper: Path, show) -> str:
    """"line 3: ", or "refs.tex line 3: " where the line is another file's than the paper's:
    a LaTeX paper's `thebibliography` in a file it inputs (round 1 of #463)."""
    if not line:
        return ""
    return (f"{show(path)} {show.at(path, line)}: " if path is not None and path != paper
            else f"{show.at(paper, line)}: ")  # fmt: skip


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
