"""G8: a randomised trial's table of baseline characteristics with a column of P values.

In a randomised trial a test of a difference at baseline tests a null hypothesis that the
randomisation makes true by design: any difference between the groups is due to chance.
CONSORT advises against such tests. Its 2010 explanation and elaboration does so under
item 15, baseline data (Moher et al., BMJ 2010;340:c869, PMC2844943), and the CONSORT 2025
explanation and elaboration under item 25 (Hopewell et al., BMJ 2025, doi
10.1136/bmj-2024-081124, PMC11995452); both were read on their pages on 2026-11-12 (`READ_ON`).
Both say to judge an imbalance by how strongly the characteristic predicts the outcome and how
large it is.

So where the paper's `study_type` is one whose guidelines include CONSORT
(`data/study_types.yaml`, read here, no design named in this file), a table whose caption
holds the word "baseline" and whose header row has a P header (`P_HEADERS`) is a warning,
`baseline-p-values`, at every stage. The tables read are those the analysis emits (`em.table`,
and those the build writes from a model's card) and those the manuscript types, in the main
text and in the supplement alike (`text.captioned`): Markdown pipe and grid tables, and a
LaTeX manuscript's tables through its reader. Nothing stands the warning down.

The word is read whole, case folded: "postbaseline" names no baseline, and nor does
"from baseline", "since baseline", "baseline-adjusted" or "adjusted for baseline", which a
table of a trial's outcomes is captioned with ("Change from baseline in HbA1c"). Another
wording, "characteristics of participants at randomisation", is not read (DESIGN.md, Known
gaps). `audit --design trial` reads a paper's tables by the same rule (`auditing/baseline`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from manuscript_guard.findings import WARN, Finding, Report

GATE = "G8"
CODE = "baseline-p-values"
#: The guideline whose designs the check reads, by its name in `data/study_types.yaml`.
GUIDELINE = "CONSORT"
#: The day the two explanations were read on their pages.
READ_ON = "2026-11-12"

#: The headers of a column of P values, exactly; each may end in one note mark (`NOTE_MARKS`).
P_HEADERS = ("P", "p", "P value", "p value", "P-value", "p-value")
#: What a header may end in after its words: an asterisk, a dagger and the marks after it, or
#: a superscript letter or digit typed as one character.
NOTE_MARKS = (
    "*\N{DAGGER}\N{DOUBLE DAGGER}\N{SECTION SIGN}\N{PILCROW SIGN}\N{DOUBLE VERTICAL LINE}#"
    "\N{MODIFIER LETTER SMALL A}\N{MODIFIER LETTER SMALL B}\N{MODIFIER LETTER SMALL C}"
    "\N{MODIFIER LETTER SMALL D}\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO}\N{SUPERSCRIPT THREE}"
    "\N{SUPERSCRIPT FOUR}"
)
#: One note mark at a header's end: up to three of `NOTE_MARKS`, or a superscript as Markdown
#: writes it (`^a^`) and as the LaTeX reader prints one (`^a`, `^` for `$^\dagger$`).
_NOTE = re.compile(rf"[ \t]?(?:\^[^\s^]{{0,3}}\^?|[{re.escape(NOTE_MARKS)}]{{1,3}})\Z")
#: The P in italics or in maths, as Markdown types it: `*P*`, `_p_`, `**P**`, `$p$`.
_STYLED_P = re.compile(r"\A(?:(?P<mark>\*{1,2}|_{1,2})(?P<p>[Pp])(?P=mark)|\$(?P<math>[Pp])\$)")

#: The word, whole: no letter or digit on either side.
_BASELINE = re.compile(r"(?<![^\W_])baseline(?![^\W_])", re.IGNORECASE)
#: Where the word names the time a change is measured from, as a table of outcomes does, the
#: word perhaps in italics or bold.
_FROM_BASELINE = re.compile(
    r"(?<![^\W_])(?:from|since)\s+[*_]{0,2}baseline(?![^\W_])"
    r"|(?<![^\W_])baseline[*_]{0,2}[\s-]+adjusted"
    r"|(?<![^\W_])adjusted\s+for\s+[*_]{0,2}baseline(?![^\W_])",
    re.IGNORECASE,
)

#: The documents a manuscript's tables are read in: the main text's, then the supplement's.
_DOCUMENTS = (False, True)

#: What the finding says CONSORT says.
SAYS = ("CONSORT advises against testing differences between the groups at baseline, "
        "since the randomisation makes any such difference due to chance "
        "(the CONSORT 2010 explanation and elaboration, item 15, and the CONSORT 2025 "
        "explanation and elaboration, item 25)")  # fmt: skip
#: What to do instead.
HINT = ("describe the groups at baseline and leave the P values out; where an imbalance "
        "matters, judge it by how strongly the characteristic predicts the outcome and how "
        "large it is, and adjust the analysis for the prognostic covariates the plan names in "
        "advance")  # fmt: skip


def p_header(header: str) -> bool:
    """Whether a column's header is a P value's (`P_HEADERS`), its P perhaps in italics or
    maths and its end perhaps a note mark."""
    text = " ".join(header.split())
    styled = _STYLED_P.match(text)
    if styled is not None:
        text = (styled["p"] or styled["math"]) + text[styled.end():]
    return _NOTE.sub("", text, count=1) in P_HEADERS


def p_columns(headers: Iterable[str]) -> tuple[str, ...]:
    """The headers of a header row that head a column of P values, as typed."""
    return tuple(header for header in headers if p_header(header))


def names_baseline(caption: str | None) -> bool:
    """Whether a caption holds the word "baseline", but for the time a change is measured
    from."""
    if not caption:
        return False
    measured = [(one.start(), one.end()) for one in _FROM_BASELINE.finditer(caption)]
    return any(not any(start <= word.start() < end for start, end in measured)
               for word in _BASELINE.finditer(caption))  # fmt: skip


def consort_designs() -> frozenset[str]:
    """The `study_type`s whose guidelines include CONSORT, read from the data file."""
    from manuscript_guard.gates.design import study_types

    return frozenset(name for name, kind in study_types().items()
                     if GUIDELINE in (kind.get("guidelines") or ()))  # fmt: skip


def applies(study_type: str | None) -> bool:
    """Whether the paper's design is one CONSORT is the guideline of."""
    return study_type in consort_designs()


def said(what: str, headers: tuple[str, ...], design: str) -> str:
    """What is said of one table whose caption names baseline and that has P columns, in a
    study of the design labelled `design`."""
    named = " and ".join(repr(header) for header in headers)
    return (f"{what} is captioned as a table of baseline characteristics and has a column "
            f"of P values ({named}), and the study is a {design}: {SAYS}")  # fmt: skip


def label(study_type: str) -> str:
    """The design's label in the data file: "randomised trial"."""
    from manuscript_guard.gates.design import study_types

    return study_types()[study_type].get("label") or study_type


def check_baseline(project, results) -> Report:
    """A warning for each table of baseline characteristics with a column of P values, where
    the paper's design is a randomised trial's."""
    return judge_baseline(project.path("manuscript"), project.study_type, results.tables)


def judge_baseline(manuscript: Path, study_type: str | None, tables: Mapping) -> Report:
    """`check_baseline` of the manuscript in the folder `manuscript`, the design given and
    the emitted tables, by key, each with its `caption`, `columns` and `source`."""
    if not applies(study_type):
        return Report()
    design = label(study_type)
    findings = []
    for key, table in tables.items():
        headers = p_columns(table.columns)
        if headers and names_baseline(table.caption):
            findings.append(Finding(
                gate=GATE, code=CODE, severity=WARN, path=table.source,
                message=said(f"table {key!r}", headers, design), context=table.caption,
                hint=f"emit the table without the P column: {HINT}"))  # fmt: skip
    for path, captioned in typed_tables(manuscript):
        headers = p_columns(captioned.headers)
        if headers and names_baseline(captioned.caption):
            findings.append(Finding(
                gate=GATE, code=CODE, severity=WARN, path=path, line=captioned.line,
                message=said("this table", headers, design), context=captioned.caption, hint=HINT))
    return Report(tuple(findings))


def typed_tables(manuscript: Path) -> list:
    """Each table the manuscript types, with its file, in the main text and the supplement:
    `(path, Captioned)`."""
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.numbers import is_supplementary, source_files
    from manuscript_guard.text.captioned import latex_captioned, markdown_captioned
    from manuscript_guard.text.reader import LATEX, manuscript_format

    if not manuscript.is_dir():
        return []
    if manuscript_format(manuscript) == LATEX:
        from manuscript_guard.text.latex.structure import read_document

        return [(manuscript / source.path, captioned)
                for supplementary in _DOCUMENTS
                for source in read_document(manuscript, supplementary=supplementary).sources
                if not source.loose and not source.path.lower().endswith(".sty")
                for captioned in latex_captioned(source)]  # fmt: skip
    return [(path, captioned) for path in source_files(manuscript)
            if is_supplementary(manuscript, path) in _DOCUMENTS
            for captioned in markdown_captioned(read_text(path))]  # fmt: skip


__all__ = ["CODE", "GUIDELINE", "HINT", "NOTE_MARKS", "P_HEADERS", "READ_ON", "SAYS",
           "applies", "check_baseline", "consort_designs", "judge_baseline", "label",
           "names_baseline", "p_columns", "p_header", "typed_tables"]  # fmt: skip
