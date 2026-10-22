"""G7: a quotation written into the prose is in the source it cites.

G7 checks the literature ledger's quotes against the stored sources. A quotation written into
a sentence of the manuscript was checked against nothing: 'the agency judged the risk
"acceptable in all but the frailest patients" [@agency2019]' could be misremembered, and
nothing would say so. So each quoted span of four words or more, inside quotation marks, in
a sentence that cites a work, is looked for in that work's stored source under
`literature/sources/`, named by its citation key, in every stored file of it, with the
same `contains()` the ledger's quotes are read with; a quotation with words left out is
looked for piece by piece (`quoted_in`). Where it is found in none of the sentence's cited
works that have a source, G7 warns (`quotation-not-in-source`); where none of them has a
stored source, a note says the quotation could not be checked (`quotation-unchecked`). Page
numbers are not compared: a PDF's page index is not the page printed on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.literature.sources import (
    UnreadableSource,
    contains,
    normalise,
    read_source,
    stored_files,
)
from manuscript_guard.text.masking import blank_comments
from manuscript_guard.text.reader import LATEX, manuscript_format

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


def _sources_of(sources: Path, key: str) -> list[Path]:
    """Every stored file of a work (`stored_files`, which `sync-sources` reads too)."""
    return stored_files(sources, key)


#: Where a writer left words of a source out: "[...]", "[. . .]", "[…]", "…" or "...".
_ELIDED = re.compile(
    r"\s*(?:\[\s*(?:\.\s*){3}\]|\[\s*\N{HORIZONTAL ELLIPSIS}\s*\]|\N{HORIZONTAL ELLIPSIS}"
    r"|\.\.\.)\s*"
)
#: A word the writer marks as the source's own, `[sic]`, `[*sic*]`, `[sic!]`: it leaves
#: nothing out, and is taken out.
_SIC = re.compile(r"\s*\[\s*[*_]{0,2}sic[*_]{0,2}!?\s*\]", re.IGNORECASE)


def quoted_in(text: str, quote: str) -> bool:
    """Whether a quotation is in a source's text: whole, less any [sic], or, where the writer
    left words out, each piece either side as words of its own, in the order quoted (round
    1 of #282: the whole was looked for, and an elided quotation was said to be absent).
    [sic] leaves nothing out, so the words either side of it stand together in the source,
    and a piece is not the end or the start of a longer word (round 1 of the review: "…
    effective" was found inside "ineffective")."""
    quote = _SIC.sub("", quote)
    # Whole, as main reads it, only where nothing was left out: one piece beside an elision
    # at either end is words of its own too (round 2 of the review).
    if not _ELIDED.search(quote):
        return contains(text, quote)
    # A piece with no letter or digit, a dash between two elisions, is no words to look for.
    folded = (normalise(piece).lower() for piece in _ELIDED.split(quote))
    pieces = [piece for piece in folded if any(c.isalnum() for c in piece)]
    haystack, at = normalise(text).lower(), 0
    for piece in pieces:
        found = _as_words(haystack, piece, at)
        if found < 0:
            return False
        at = found + len(piece)
    return True


def _as_words(haystack: str, piece: str, at: int) -> int:
    """Where `piece` stands from `at` on as words of its own, or -1: not after or before a
    letter or digit, nor a hyphen or an apostrophe joining it to one, nor a point between
    digits ("… effective" is no part of "cost-effective", nor "5 mg" of "2.5 mg"; a
    reference number after a full stop, "patients.12", is)."""
    found = haystack.find(piece, at)
    while found >= 0:
        end = found + len(piece)
        before = haystack[max(0, found - 2) : found].rjust(2)
        after = haystack[end : end + 2].ljust(2)
        joined_before = before[1].isalnum() or _joins(before[0], before[1], piece[0])
        joined_after = after[0].isalnum() or _joins(piece[-1], after[0], after[1])
        if not (piece[0].isalnum() and joined_before) and not (
            piece[-1].isalnum() and joined_after
        ):
            return found
        found = haystack.find(piece, found + 1)
    return -1


def _joins(left: str, mark: str, right: str) -> bool:
    """Whether `mark` joins `left` and `right` into one word or number."""
    if mark == ".":
        return left.isdigit() and right.isdigit()
    return mark in "-'" and left.isalnum() and right.isalnum()


def check_prose_quotations(project: Project) -> Report:
    """A warning for each quotation not in the sources it cites; a note where none has one."""
    sources = project.path("literature") / "sources"
    read: dict[Path, str | None] = {}
    report = Report()
    for path, quotation in _quotations(project):
        if True:
            stored = [(key, source) for key in quotation.keys
                      for source in _sources_of(sources, key)]  # fmt: skip
            if not stored:
                report = report.with_findings(_unchecked(path, quotation))
                continue
            texts = [(key, _text(read, source)) for key, source in stored]
            if any(text is not None and quoted_in(text, quotation.quote) for _k, text in texts):
                continue
            # Named only where a source was read: a work with none was not looked in (round
            # 1 of #282: every cited key was named).
            looked_in = list(dict.fromkeys(key for key, text in texts if text is not None))
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


def _quotations(project: Project) -> list[tuple[Path, Quotation]]:
    """Each quotation of the manuscript with the file and the line it is typed on. A LaTeX
    manuscript's are read in its documents as they print (`printed_of`), where ``...'' is a
    quotation and a citation is `[@key]`, each placed back at its `.tex` file's line (step
    8)."""
    folder = project.path("manuscript")
    if manuscript_format(folder) != LATEX:
        return [(path, quotation) for path in source_files(folder)
                for quotation in quotations_in(read_text(path))]  # fmt: skip
    from manuscript_guard.text.latex.printed import printed_of

    return [(folder / path, quotation) for part in (False, True)
            for path, quotation in printed_quotations(printed_of(folder, supplementary=part))]


def printed_quotations(view) -> list[tuple[str, Quotation]]:
    """Each quotation of a LaTeX document's printed view, with the path of the `.tex` file
    it is typed in and its line there (`Printed.place_line`)."""
    found = []
    for quotation in quotations_in(view.text):
        where = view.place_line(quotation.line)
        if where is not None:
            source, line = where
            found.append((source.path, replace(quotation, line=line)))
    return found


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
