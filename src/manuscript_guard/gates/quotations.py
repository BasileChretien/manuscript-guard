"""G7: a quotation written into the prose is in the source it cites.

G7 checks the literature ledger's quotes against the stored sources. A quotation written into
a sentence of the manuscript was checked against nothing: 'the agency judged the risk
"acceptable in all but the frailest patients" [@agency2019]' could be misremembered, and
nothing would say so. So each quoted span of four words or more, inside quotation marks, in
a sentence that cites a work, is looked for in that work's stored source under
`literature/sources/`, named by its citation key, with the same `contains()` the ledger's
quotes are read with. Where it is found in none of the sentence's cited works that have a
source, G7 warns (`quotation-not-in-source`); where none of them has a stored source, a note
says the quotation could not be checked (`quotation-unchecked`). Page numbers are not
compared: a PDF's page index is not the page printed on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.literature.sources import (
    HTML_SUFFIXES,
    PDF_SUFFIXES,
    TEXT_SUFFIXES,
    UnreadableSource,
    contains,
    filed_name,
    read_source,
)
from manuscript_guard.text.masking import blank_comments

GATE = "G7"
#: The fewest words a quotation holds for it to be looked for: "so-called" and a quoted term
#: are not quotations of a source.
WORDS = 4
#: A quotation, in straight or curly double marks, on one line or across a line break.
_QUOTED = re.compile(r'"([^"\n]+(?:\n[^"\n]+)*)"|\u201c([^\u201d]+)\u201d')
#: A citation key as the co-author items read one.
_KEY = re.compile(r"(?<![\w.])@([A-Za-z](?:[\w:.#$%&+?<>~/-]*\w)?)")


@dataclass(frozen=True)
class Quotation:
    """A quotation in a sentence that cites: the paragraph's line, the words, the keys."""

    line: int
    quote: str
    keys: tuple[str, ...]


def quotations_in(text: str) -> list[Quotation]:
    """Each quotation of four words or more in `text`, with the works cited in the sentences
    it stands in: a quotation of two sentences ends in the one that cites. The sentences are
    cut as the co-author's items are (`checking/produce.py`), per paragraph."""
    from manuscript_guard.checking.produce import _split

    found: list[Quotation] = []
    line = 1
    for paragraph in blank_comments(text).split("\n\n"):
        flat = " ".join(paragraph.split())
        quoted = [
            (match, " ".join((match.group(1) or match.group(2)).split()))
            for match in _QUOTED.finditer(flat)
        ]
        quoted = [(match, quote) for match, quote in quoted
                  if sum(any(c.isalpha() for c in word) for word in quote.split()) >= WORDS]
        # Cut into sentences only a paragraph that quotes and cites: the cut reads a long
        # paragraph slowly, and five thousand lines of one took `check` past its budget.
        if not quoted or "@" not in flat:
            line += paragraph.count("\n") + 2
            continue
        spans, at = [], 0
        for sentence in _split(flat):
            start = flat.find(sentence, at)
            start = at if start < 0 else start
            spans.append((start, start + len(sentence), sentence))
            at = start + len(sentence)
        for match, quote in quoted:
            spanned = [s for s in spans if s[0] < match.end() and match.start() < s[1]]
            keys = tuple(dict.fromkeys(k for s in spanned for k in _KEY.findall(s[2])))
            if keys:
                found.append(Quotation(line, quote, keys))
        line += paragraph.count("\n") + 2
    return found


def _source_of(sources: Path, key: str) -> Path | None:
    for suffix in sorted(TEXT_SUFFIXES | HTML_SUFFIXES | PDF_SUFFIXES):
        path = sources / filed_name(key, suffix)
        if path.is_file():
            return path
    return None


def check_prose_quotations(project: Project) -> Report:
    """A warning for each quotation not in the sources it cites; a note where none has one."""
    sources = project.path("literature") / "sources"
    read: dict[Path, str | None] = {}
    report = Report()
    for path in source_files(project.path("manuscript")):
        for quotation in quotations_in(read_text(path)):
            found = [(key, _source_of(sources, key)) for key in quotation.keys]
            stored = [(key, source) for key, source in found if source]
            if not stored:
                report = report.with_findings(_unchecked(path, quotation))
                continue
            texts = [(key, _text(read, source)) for key, source in stored]
            if any(text is not None and contains(text, quotation.quote) for _k, text in texts):
                continue
            # Named only where a source was read: a work with none was not looked in (round
            # 1 of #282: every cited key was named).
            looked_in = [key for key, text in texts if text is not None]
            if not looked_in:
                report = report.with_findings(_unchecked(path, quotation))
                continue
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="quotation-not-in-source",
                    severity=WARN,
                    message=f"the quotation {_shown(quotation.quote)} is not in the stored "
                    f"source of {', '.join('@' + key for key in looked_in)}",
                    path=path,
                    line=quotation.line,
                    hint="copy the words from the source rather than from memory, or cite the "
                    "work that says them",
                )
            )
    return report


def _text(read: dict[Path, str | None], source: Path) -> str | None:
    if source not in read:
        try:
            read[source] = read_source(source)
        except UnreadableSource:
            read[source] = None
    return read[source]


def _unchecked(path: Path, quotation: Quotation) -> Finding:
    return Finding(
        gate=GATE,
        code="quotation-unchecked",
        severity=INFO,
        message=f"the quotation {_shown(quotation.quote)} could not be checked: no stored "
        f"source of {', '.join('@' + key for key in quotation.keys)} can be read",
        path=path,
        line=quotation.line,
        hint="store the source under literature/sources/, named by its citation key",
    )


def _shown(quote: str) -> str:
    return repr(quote if len(quote) <= 80 else quote[:77] + "...")
