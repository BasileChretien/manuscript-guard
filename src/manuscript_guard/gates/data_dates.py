"""G2 — a date of the data that the analysis typed, where `dataset()` would have pinned it.

A date typed in the text fails G2 like any number. The way out G2 offered, a string emitted
with its display, `em.value("extracted", "2024-03-01", display="1 March 2024")`, ties the
date to nothing: data extracted again and run again went out under the old date, with every
gate green. `dataset()` pins it to the files it describes. So a sentence that says the data
were extracted, downloaded or retrieved, or what period they cover, and binds a date that
`dataset()` did not declare, is warned of (`data-date-not-declared`).

Which bindings stand in one sentence is `in_sentences`'s, and a sentence is read as `labels`
reads one. Its words are read with every binding and comment in it blanked, so that a key
named `extracted` says nothing. A date is a string value that is an ISO date, or whose
display reads as one (`dates.read_written`). A parameter is a choice the analysis made, a
study period it set, and is not warned of; nor is a number, which the analysis may well have
computed from the data, as the example computes its first and last year.

And one warning that reads no text: a dataset's date printed in another English than the one
`paper.yaml` declares now, which the emitter read when the analysis ran
(`dataset-date-english`).
"""

from __future__ import annotations

import re
from bisect import bisect_left
from pathlib import Path

from manuscript_guard.contracts.values import Value
from manuscript_guard.datasets import DATE_PARTS
from manuscript_guard.dates import parse_iso, read_written, written
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.labels import sentence_stops
from manuscript_guard.text.masking import blank_comments

GATE = "G2"

#: What a sentence about the data says of them: that they were taken from their source on
#: a date, or what period they cover.
_SAYS = re.compile(
    r"(?i)\b(?:extract(?:s|ed|ing|ion|ions)?|download(?:s|ed|ing)?|retriev(?:e|ed|al)|"
    r"snapshots?|quer(?:y|ied)|accessed|obtained|locked|lock|cut[- ]?off|frozen|freeze|"
    r"cover(?:s|ed|ing|age)?|span(?:s|ned|ning)?|until|through|up\s+to)\b"
)

#: The roles a date may be emitted under without `dataset()`: a choice the analysis made.
_DECLARED = frozenset({"dataset", "parameter"})


def is_typed_date(value: Value) -> bool:
    """Whether `value` is a date the analysis typed rather than declared with `dataset()`."""
    if value.role in _DECLARED or not isinstance(value.value, str):
        return False
    return parse_iso(value.value) is not None or read_written(value.display) is not None


def data_dates(files: list[tuple[Path, str, list]], namespace: dict[str, Value]) -> Report:
    """Each binding of a typed date in a sentence that says the data were extracted, or what
    period they cover."""
    report = Report()
    for path, text, located in files:
        read = blank_comments(text) if "<!--" in text else text
        stops = sentence_stops(read)
        by_sentence: dict[int, list] = {}
        for placeholder, sentence in located:
            by_sentence.setdefault(sentence, []).append(placeholder)
        for placeholders in by_sentence.values():
            typed = [p for p in placeholders
                     if (v := namespace.get(p.ref)) is not None and is_typed_date(v)]  # fmt: skip
            if not typed or not _SAYS.search(_words(read, stops, placeholders)):
                continue
            for placeholder in typed:
                report = report.with_findings(_typed(placeholder, namespace[placeholder.ref], path))
    return report


def _words(read: str, stops: list[int], placeholders: list) -> str:
    """The words of the sentence the bindings stand in, with each binding blanked."""
    first = min(p.start for p in placeholders)
    last = max(p.end for p in placeholders)
    before = bisect_left(stops, first)
    opens = stops[before - 1] + 1 if before else 0
    after = bisect_left(stops, last)
    closes = stops[after] + 1 if after < len(stops) else len(read)
    pieces, at = [], opens
    for placeholder in sorted(placeholders, key=lambda p: p.start):
        pieces.append(read[at : placeholder.start])
        at = placeholder.end
    pieces.append(read[at:closes])
    return " ".join(pieces)


def _typed(placeholder, value: Value, path: Path) -> Finding:
    return Finding(
        gate=GATE,
        code="data-date-not-declared",
        severity=WARN,
        message=f"{placeholder.raw} is a date of the data the analysis typed, "
        f"{value.display!r}, and nothing ties it to the data it dates",
        path=path,
        line=placeholder.line,
        col=placeholder.col,
        hint='declare the data with em.dataset("<name>", "<file>", extracted="2024-03-01", '
        'covers=(...), fingerprint=...) and bind {{results.dataset.<name>.extracted}}: the '
        "date is then pinned to the file, and data extracted again need a date of their own. "
        "A date the study chose rather than one of the data is a parameter, em.parameter()",
    )


def dates_in_english(namespace: dict[str, Value], english: str) -> Report:
    """Each dataset date printed otherwise than the English the paper declares prints it."""
    report = Report()
    for value in namespace.values():
        is_date = value.role == "dataset" and value.key.rsplit(".", 1)[-1] in DATE_PARTS
        dated = parse_iso(value.value) if is_date else None
        if dated is None or value.display == written(dated, english):
            continue
        source = value.source.name if value.source else "the results"
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="dataset-date-english",
                severity=WARN,
                message=f"results.{value.key} is printed {value.display!r}, and paper.yaml "
                f"declares {english}, which prints {written(dated, english)!r}",
                path=value.source,
                hint=f"run again the analysis that wrote {source}: the emitter reads the "
                "English when it runs",
            )
        )
    return report
