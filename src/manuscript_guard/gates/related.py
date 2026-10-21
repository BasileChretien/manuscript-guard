"""G8 — this paper against the earlier outputs of the same study or the same data.

A cohort of 1,204 in the conference abstract and 1,187 in the article, with nothing said,
reads to an editor as a number nobody can account for. Two papers from one database
extraction, the second not saying the first exists, read as duplicate publication, which
ICMJE asks authors to declare and journals treat as misconduct.

What is compared is what both sides state as data, never what their prose means:

- through a copy of the earlier project (`related --take`), every result key both emit,
  and the pairs the author declares for a key renamed since, value against value;
- through the earlier output's text or copied outputs, each value the author recorded
  with the sentence that states it, the sentence checked against the stored copy as the
  ledger's quotes are.

A difference is explained when the author records why, and the manuscript tells the reader
in a sentence that can be found in it. Unexplained, it warns, and fails at submission. A
difference in a declared choice of the analysis (a parameter, a coding dictionary's
release, a label such as the study period) is a change of method: it is listed, warns
without a reason, and never fails, since a method may rightly change between two papers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from fnmatch import fnmatchcase

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results, load_results
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.gates.revision import as_quoted, rendered_manuscript
from manuscript_guard.literature.related import (
    GATE,
    Output,
    Pair,
    Recorded,
    Related,
    load_related,
    read_snapshot,
)
from manuscript_guard.literature.sources import (
    UnreadableSource,
    contains,
    read_source,
    states_value,
)
from manuscript_guard.text.masking import blank_comments
from manuscript_guard.text.placeholders import substitute
from manuscript_guard.zotero.citations import find_citations

#: The roles of a value that is a choice of the analysis rather than a measurement.
METHOD_ROLES = frozenset({"parameter", "dictionary"})
#: A version of what the analysis ran on: not compared, since every later paper runs later
#: software, and not a method of the paper.
SOFTWARE = "software"

#: What each finding of a difference says of it, in the listing `related` prints.
STATES = {
    "related-number-differs": "differs",
    "related-reason-not-in-text": "differs; reason not in the text",
    "related-number-explained": "explained",
    "related-method-differs": "method changed",
    "related-method-explained": "method changed; reason given",
}


@dataclass(frozen=True)
class Compared:
    """One value held to the earlier output's: the keys, both printings, and what came of it."""

    output: str
    earlier: str
    here: str
    then: str
    now: str
    state: str


@dataclass
class _Seen:
    """What is read of the manuscript once, for every output that needs it."""

    project: Project
    displays: dict[str, str]
    _cited: frozenset[str] | None = None
    _text: str | None = None
    rows: list[Compared] = field(default_factory=list)

    @property
    def cited(self) -> frozenset[str]:
        """Every citekey the manuscript cites where a reader sees it, comments left out."""
        if self._cited is None:
            keys = set()
            for path in source_files(self.project.path("manuscript")):
                text = blank_comments(read_text(path))
                keys.update(use.citekey for use in find_citations(text, path))
            self._cited = frozenset(keys)
        return self._cited

    def says(self, sentence: str) -> bool:
        """Whether the manuscript prints `sentence`, as G13 looks for a quoted change: with
        its bindings filled in, comments, emphasis and line breaks left out. A binding in the
        sentence is read filled in too, as it is in a response's quote."""
        if self._text is None:
            self._text = as_quoted(rendered_manuscript(self.project, self.displays))
        return as_quoted(substitute(sentence, self.displays)) in self._text


def check_related(
    project: Project,
    namespace: dict[str, Value],
    results: Results,
    *,
    submission: bool = False,
) -> Report:
    """Each earlier output in `literature/related.yaml`, held to this paper."""
    return compare_related(project, namespace, results, submission=submission)[0]


def compare_related(
    project: Project,
    namespace: dict[str, Value],
    results: Results,
    *,
    submission: bool = False,
) -> tuple[Report, list[Compared]]:
    """The findings, and every value compared with what came of it."""
    related, report = load_related(project)
    if related is None:
        return report, []
    strict = FAIL if submission else WARN
    seen = _Seen(project, {ref: value.display for ref, value in namespace.items()})
    for output in related.outputs:
        report = report.merge(_files(project, related, output))
        report = report.merge(_disclosed(related, output, strict, seen))
        report = report.merge(_against_copy(project, related, output, results, strict, seen))
        for recorded in output.values:
            report = report.merge(
                _recorded(project, related, output, recorded, results, strict, seen)
            )
    counted = report.with_counts(
        related_outputs=len(related.outputs),
        related_values_compared=len(seen.rows),
        related_values_differ=sum(1 for row in seen.rows if row.state != "same"),
    )
    return counted, seen.rows


def _finding(related: Related, code: str, message: str, **rest) -> Finding:
    return Finding(gate=GATE, code=code, message=message, **{"path": related.path, **rest})


# ----------------------------------------------------------------------- what is shared


def _files(project: Project, related: Related, output: Output) -> Report:
    """Its own files where an author of this paper wrote it, and the ones it names."""
    findings = []
    literature = project.path("literature")
    for name in output.files:
        if not (literature / name).is_file():
            findings.append(
                _finding(
                    related,
                    "related-file-missing",
                    f"{output.name}: {name} is not under {literature.name}/",
                    severity=WARN,
                    line=output.line,
                    hint="copy the earlier analysis's output there, or take it off `files`",
                )
            )
    # An earlier paper of the same authors on other data has nothing to compare: its files
    # are asked for only where it shares the data or the study as well.
    if (
        output.overlaps
        and output.project is None
        and not output.files
        and output.files_unavailable is None
    ):
        findings.append(
            _finding(
                related,
                "related-files-missing",
                f"{output.name}: it shares {' and '.join(output.shares)} with this paper, and "
                f"neither "
                f"its project nor its outputs are given, so it can be compared only with "
                f"what it printed",
                severity=WARN,
                line=output.line,
                hint="name its manuscript-guard project (`project:`, `revision:`) and run "
                "`manuscript-guard related --take`, or copy its analysis outputs in (`files:`), "
                "or say why they cannot be had (`files_unavailable:`)",
            )
        )
    return Report(tuple(findings))


def _disclosed(related: Related, output: Output, strict: str, seen: _Seen) -> Report:
    """Data or a study shared with authors is told to the journal: cited, or said."""
    if not output.overlaps:
        return Report()
    if output.citekey is not None and output.citekey in seen.cited:
        return Report()
    if output.disclosed_by is not None and seen.says(output.disclosed_by):
        return Report()
    if output.disclosed_by is not None:
        said = "the sentence `disclosed_by` gives is not in the manuscript"
    elif output.citekey is not None:
        said = "the manuscript does not cite it"
    else:
        said = "the manuscript neither cites it nor says it"
    return Report(
        (
            _finding(
                related,
                "related-undisclosed",
                f"{output.name} shares {' and '.join(output.shares)} with this paper, and {said}",
                severity=strict,
                line=output.line,
                context=output.disclosed_by,
                hint="cite it, or give in `disclosed_by` the manuscript's sentence that "
                "discloses it; declare it in the covering letter as well (ICMJE: overlapping "
                "publications)",
            ),
        )
    )


# ----------------------------------------------------------------------- the copy


def _against_copy(
    project: Project,
    related: Related,
    output: Output,
    results: Results,
    strict: str,
    seen: _Seen,
) -> Report:
    """Every key both projects emit, and every pair, value against value."""
    snapshot, problem = read_snapshot(project, output.id)
    if problem is not None:
        return Report(
            (
                _finding(
                    related,
                    "related-snapshot-unreadable",
                    f"{output.name}: its copy cannot be read: {problem}",
                    severity=strict,
                    line=output.line,
                    hint="take it again: `manuscript-guard related --take " + output.id + "`",
                ),
            )
        )
    if snapshot is None:
        if output.project is None:
            return Report()
        return Report(
            (
                _finding(
                    related,
                    "related-not-taken",
                    f"{output.name}: its project is named and no copy of it is kept, so its "
                    f"numbers were not compared",
                    severity=strict,
                    line=output.line,
                    hint=f"run `manuscript-guard related --take {output.id}`",
                ),
            )
        )
    report = Report()
    manifest = snapshot.manifest
    if snapshot.edited:
        report = report.with_findings(
            _finding(
                related,
                "related-snapshot-edited",
                f"{output.name}: its copy changed since it was taken: "
                + ", ".join(snapshot.edited),
                path=snapshot.folder,
                hint="a copied result edited by hand compares nothing; take it again: "
                f"`manuscript-guard related --take {output.id}`",
            )
        )
        return report
    if (manifest["project"], manifest.get("revision")) != (output.project, output.revision):
        report = report.with_findings(
            _finding(
                related,
                "related-taken-elsewhere",
                f"{output.name}: its copy was taken from {manifest['project']}"
                + (f" at {manifest['revision']}" if manifest.get("revision") else "")
                + ", which the entry no longer names, so another output was compared",
                severity=strict,
                line=output.line,
                hint=f"take it again: `manuscript-guard related --take {output.id}`",
            )
        )
    earlier, loaded = load_results(snapshot.folder / "results")
    if not loaded.ok:
        first = loaded.failures[0]
        return report.with_findings(
            _finding(
                related,
                "related-snapshot-unreadable",
                f"{output.name}: its copied results cannot be read: {first.message}",
                severity=strict,
                line=output.line,
                hint=f"take it again: `manuscript-guard related --take {output.id}`",
            )
        )
    paired = {pair.earlier for pair in output.pairs} | {pair.here for pair in output.pairs}
    for key in sorted(set(earlier.values) & set(results.values) - paired):
        if any(fnmatchcase(key, apart.keys) for apart in output.not_compared):
            continue
        if not (earlier.values[key].quoted and results.values[key].quoted):
            # Printed by neither paper or by one only: no reader sees the two side by side.
            continue
        report = report.merge(
            _compare(related, output, earlier.values[key], results.values[key], None, strict, seen)
        )
    for pair in output.pairs:
        then, now = earlier.values.get(pair.earlier), results.values.get(pair.here)
        if then is None or now is None:
            missing = (
                f"the earlier project emits no {pair.earlier}"
                if then is None
                else f"this project emits no {pair.here}"
            )
            report = report.with_findings(
                _finding(
                    related,
                    "related-pair-unmatched",
                    f"{output.name}: {missing}, so the pair compares nothing",
                    severity=strict,
                    line=pair.line,
                    hint="name keys both emit; the copy's are under "
                    f"{snapshot.folder.name}/results/",
                )
            )
            continue
        report = report.merge(_compare(related, output, then, now, pair, strict, seen))
    return report


def _compare(
    related: Related,
    output: Output,
    then: Value,
    now: Value,
    pair: Pair | None,
    strict: str,
    seen: _Seen,
) -> Report:
    if SOFTWARE in (then.role, now.role):
        return Report()
    row = Compared(output.id, then.key, now.key, then.display, now.display, "same")
    if _same(then, now):
        seen.rows.append(row)
        return Report()
    named = then.key if then.key == now.key else f"{then.key} (here {now.key})"
    said = f"{output.name}: {named} is {then.display} there and {now.display} here"
    method = bool({then.role, now.role} & METHOD_ROLES) or then.label or now.label
    line = pair.line if pair is not None else output.line
    because = pair.because if pair is not None else None
    says = pair.manuscript_says if pair is not None else None
    judged = _judged(related, said, method, because, says, line, strict, seen)
    seen.rows.append(replace(row, state=STATES[judged.findings[0].code]))
    return judged


def _judged(
    related: Related,
    said: str,
    method: bool,
    because: str | None,
    says: str | None,
    line: int | None,
    strict: str,
    seen: _Seen,
) -> Report:
    """A difference: explained, a change of method, or a number nobody accounts for."""
    if method:
        if because is not None:
            return Report(
                (_finding(related, "related-method-explained", f"{said}: {because}",
                          severity=INFO, line=line),)
            )  # fmt: skip
        return Report(
            (
                _finding(
                    related,
                    "related-method-differs",
                    f"{said}: a choice of the analysis changed",
                    severity=WARN,
                    line=line,
                    hint="record why in a pair (`because:`) and say it in the Methods; the "
                    "review panel weighs it, nothing here judges it",
                ),
            )
        )
    if because is not None and says is not None and seen.says(says):
        return Report(
            (_finding(related, "related-number-explained", f"{said}: {because}",
                      severity=INFO, line=line),)
        )  # fmt: skip
    if because is not None:
        absent = (
            "and the manuscript does not print the sentence `manuscript_says` gives"
            if says is not None
            else "and no sentence of the manuscript is given that tells the reader"
        )
        return Report(
            (
                _finding(
                    related,
                    "related-reason-not-in-text",
                    f"{said}; the reason is recorded ({because}) {absent}",
                    severity=strict,
                    line=line,
                    context=says,
                    hint="give in `manuscript_says` the manuscript's sentence that says why, "
                    "as the manuscript writes it (a binding may be filled in)",
                ),
            )
        )
    return Report(
        (
            _finding(
                related,
                "related-number-differs",
                f"{said}, and nothing says why",
                severity=strict,
                line=line,
                hint="if one of them is wrong, put it right; otherwise record why in a pair "
                "(`because:`) and the manuscript's sentence that says so (`manuscript_says:`); "
                "keys that are not the same quantity go under `not_compared`",
            ),
        )
    )


def _same(then: Value, now: Value) -> bool:
    """Printed alike, or the same number to nine significant digits, as `verify` holds a
    re-run to: "2.3" and "2.31" of one estimate are one value printed to other places."""
    if _folded(then.display) == _folded(now.display):
        return True
    a, b = then.value, now.value
    if _numeric(a) and _numeric(b):
        return f"{float(a):.9g}" == f"{float(b):.9g}"
    return a == b


def _numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ----------------------------------------------------------------------- the text


def _recorded(
    project: Project,
    related: Related,
    output: Output,
    recorded: Recorded,
    results: Results,
    strict: str,
    seen: _Seen,
) -> Report:
    """A value read from the earlier output: in its stored copy, and as this paper has it."""
    path = project.path("literature") / recorded.source_file
    where = f"{output.name}: {recorded.value}"
    if not path.is_file():
        return Report(
            (
                _finding(
                    related,
                    "related-source-missing",
                    f"{where} is read from {recorded.source_file}, which is not in the "
                    f"literature folder",
                    line=recorded.line,
                    hint="store the published copy under sources/, or the copied output "
                    "where `files` names it",
                ),
            )
        )
    try:
        text = read_source(path)
    except UnreadableSource as exc:
        return Report(
            (_finding(related, "related-source-unreadable", f"{where}: {exc}", severity=WARN,
                      line=recorded.line,
                      hint="the value cannot be held to a copy nothing can read"),)
        )  # fmt: skip
    if not contains(text, recorded.quote):
        return Report(
            (
                _finding(
                    related,
                    "related-quote-not-in-source",
                    f"{where}: the quote is not in {recorded.source_file}",
                    line=recorded.line,
                    context=recorded.quote[:140],
                    hint="copy the sentence from the stored copy rather than retyping it",
                ),
            )
        )
    if not states_value(recorded.quote, recorded.value):
        return Report(
            (
                _finding(
                    related,
                    "related-value-not-in-quote",
                    f"{where} is not in the quote offered for it",
                    line=recorded.line,
                    context=recorded.quote[:140],
                    hint="quote the sentence that states it, or record it as the earlier "
                    "output prints it",
                ),
            )
        )
    now = results.values.get(recorded.here)
    if now is None:
        return Report(
            (
                _finding(
                    related,
                    "related-pair-unmatched",
                    f"{where}: this project emits no {recorded.here}, so it is compared with "
                    f"nothing",
                    severity=strict,
                    line=recorded.line,
                    hint="name the key this paper reports the same quantity under",
                ),
            )
        )
    if now.role == SOFTWARE:
        return Report()
    row = Compared(output.id, recorded.here, now.key, recorded.value, now.display, "same")
    if _same_printed(recorded.value, now):
        seen.rows.append(row)
        return Report()
    said = f"{output.name}: {recorded.here} is {recorded.value} there and {now.display} here"
    method = now.role in METHOD_ROLES or now.label
    judged = _judged(
        related, said, method, recorded.because, recorded.manuscript_says, recorded.line,
        strict, seen,
    )  # fmt: skip
    seen.rows.append(replace(row, state=STATES[judged.findings[0].code]))
    return judged


#: The spaces a printed number may group its digits with (no-break, thin, narrow no-break),
#: and the minus sign, each as the ASCII it is read as. Written by code point, since each
#: looks like the character it stands for.
_SPACES = str.maketrans({chr(0x00A0): " ", chr(0x2009): " ", chr(0x202F): " ", chr(0x2212): "-"})
_MIDDLE_DOT = chr(0x00B7)
#: A number as a paper prints it: a sign, digits that may be grouped by commas or spaces, a
#: decimal point or a middle dot, and a percent sign. The digits before the point may be left
#: out, as a style that drops the leading zero writes ".45".
_PRINTED = re.compile(
    r"^([-+]?)(\d{1,3}(?:[, ]\d{3})+|\d+)?(?:[." + _MIDDLE_DOT + r"](\d+))?\s?%?$"
)


def _printed(text: str) -> tuple[Decimal, int] | None:
    """The number a printed value is, and its decimal places; None for anything else."""
    found = _PRINTED.match(text.translate(_SPACES).strip())
    if found is None:
        return None
    sign, whole, fraction = found.groups()
    if whole is None and fraction is None:
        return None  # a sign alone, or a percent sign
    try:
        number = Decimal(sign + re.sub(r"[, ]", "", whole or "0") + "." + (fraction or "0"))
    except InvalidOperation:
        return None
    return number, len(fraction or "")


def _same_printed(printed: str, now: Value) -> bool:
    """Whether a value the earlier output printed is this one: as numbers where both
    printings are one, otherwise as text."""
    then, here = _printed(printed), _printed(now.display)
    if then is None or here is None:
        return _folded(printed) == _folded(now.display)
    return _within(then, here)


def _within(then: tuple[Decimal, int], here: tuple[Decimal, int]) -> bool:
    """Within half a unit of the coarser printing: "2.3" there is "2.31" here. Each side is
    the value rounded to its own places, and the coarser grid's midpoints lie on the finer
    one, so one value printed twice is never further apart than that."""
    places = min(then[1], here[1])
    return abs(then[0] - here[0]) <= Decimal(5) / Decimal(10) ** (places + 1)


def _folded(text: str) -> str:
    return " ".join(text.translate(_SPACES).split()).casefold()
