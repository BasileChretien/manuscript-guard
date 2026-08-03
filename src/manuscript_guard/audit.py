"""Auditing a paper that was never written with this toolkit.

`manuscript-guard check` works because the manuscript source contains bindings: a
results-derived number cannot be written as a literal, so nothing passes by coincidence.
An existing paper has no bindings. Every number is a literal, and the only question that can
be asked is the weak one: does this number appear anywhere in the outputs?

That question is much less useful than it sounds, and the honest thing is to say so with a
measurement rather than a disclaimer. In the project that preceded this one, set-membership
checking of exactly this kind was measured and found near-vacuous: with the analysis outputs
as the backing set, **100% of integers up to 100 and 97% of integers up to 1000 already
matched something**, and of fifteen deliberately corrupted headline numbers it detected
none.

So this audit reports two things, and the second is not optional:

* the numbers in the paper that match nothing — the actual candidates for a stale value;
* **what a match is worth in this particular project**, computed from the backing set the
  user supplied, so a clean report cannot be mistaken for a clean paper.

It is a triage tool for existing work. For a paper being written, bind the numbers instead.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.text.docx import NotADocx, is_docx, read_docx
from manuscript_guard.text.masking import mask
from manuscript_guard.text.tokens import find_atoms

PAPER_SUFFIXES = {".docx", ".md", ".txt", ".markdown"}
BACKING_SUFFIXES = {".json", ".csv", ".tsv", ".txt", ".yaml", ".yml", ".md"}
FIGURE_SUFFIXES = {".svg", ".pdf"}

_NUMBER = re.compile(r"\d[\d,  ]*(?:\.\d+)?(?:[eE][+-]?\d+)?")


# Digests, ids and hashes, stripped from backing text before numbers are extracted. Two
# reasons: a hex run like "4e308" parses as an overflowing float, and, worse, the digit
# fragments inside hashes would join the backing set and make every match likelier, quietly
# inflating the very statistic this module exists to report honestly.
_OPAQUE = re.compile(
    r"\b[0-9a-fA-F]{16,}\b|\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b"
)
_MAX_DIGITS = 24


@dataclass
class Candidate:
    text: str
    normalised: str
    source: Path
    line: int
    context: str


@dataclass
class AuditReport:
    papers: tuple[Path, ...] = ()
    backing_files: tuple[Path, ...] = ()
    backing_values: set[str] = field(default_factory=set)
    matched: list[Candidate] = field(default_factory=list)
    unmatched: list[Candidate] = field(default_factory=list)
    classified: int = 0
    unreadable: list[str] = field(default_factory=list)

    @property
    def examined(self) -> int:
        return len(self.matched) + len(self.unmatched) + self.classified


def normalise_number(text: str) -> str:
    """A comparable form: no thousands separators, no trailing zeros, no sign noise."""
    cleaned = text.replace(",", "").replace(" ", "").replace(" ", "").rstrip("%")
    if len(cleaned) > _MAX_DIGITS:
        return cleaned
    try:
        value = float(cleaned)
    except (ValueError, OverflowError):
        return cleaned
    if not math.isfinite(value):
        return cleaned
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(round(value, 10)).rstrip("0").rstrip(".")


def _numbers_in(text: str) -> set[str]:
    return {normalise_number(m.group(0)) for m in _NUMBER.finditer(_OPAQUE.sub(' ', text))}


def load_backing(paths: list[Path]) -> tuple[set[str], list[Path]]:
    """Every number appearing anywhere in the supplied outputs."""
    values: set[str] = set()
    used: list[Path] = []

    def take(path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix not in BACKING_SUFFIXES:
            return
        try:
            if suffix == ".json":
                text = json.dumps(json.loads(path.read_text(encoding="utf-8", errors="replace")))
            elif suffix in {".csv", ".tsv"}:
                delimiter = "\t" if suffix == ".tsv" else ","
                with path.open(encoding="utf-8", errors="replace", newline="") as handle:
                    text = " ".join(
                        " ".join(row) for row in csv.reader(handle, delimiter=delimiter)
                    )
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError, json.JSONDecodeError):
            return
        values.update(_numbers_in(text))
        used.append(path)

    for given in paths:
        if given.is_dir():
            for path in sorted(given.rglob("*")):
                if path.is_file():
                    take(path)
        elif given.is_file():
            take(given)

    return values, used


# A line that is nothing but a bibliography heading. Everything after it is page ranges,
# volume numbers and years belonging to other people's papers: not the author's claims, and
# reporting them buries the findings that matter.
_BIBLIOGRAPHY = re.compile(
    r"^\s*(?:#+\s*)?(?:\d+[.)]\s*)?(?:references|bibliography|works cited|literature cited)"
    r"\s*[:.]?\s*(?:\|\s*)*$",
    re.IGNORECASE,
)


# A reference-list entry, recognised by its shape rather than by a heading. citeproc appends
# the bibliography with no heading of its own, so there is often nothing to cut at, and every
# volume number and page range in it would otherwise be reported as an unexplained figure.
_REFERENCE_ENTRY = re.compile(
    r"^\s*[A-Z][\w'’-]+,\s+[A-Z][\w.'’-]*"        # "Fictional, Anne"
    r".{0,200}?\b(?:19|20)\d{2}[a-z]?\b",          # ... and a year not far behind
)


def looks_like_reference(line: str) -> bool:
    return bool(_REFERENCE_ENTRY.match(line))


def strip_bibliography(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _BIBLIOGRAPHY.match(line):
            return "\n".join(lines[:index])
    return text


def read_paper(path: Path) -> str:
    text = read_docx(path) if is_docx(path) else path.read_text(encoding="utf-8", errors="replace")
    return strip_bibliography(text)


def read_figure(path: Path) -> str | None:
    from manuscript_guard.gates.figures import _extract_text

    return _extract_text(path)


def audit(
    papers: list[Path],
    backing: list[Path],
    *,
    figures: list[Path] | None = None,
    classifier: Classifier | None = None,
) -> AuditReport:
    classifier = classifier or Classifier.load()
    values, used = load_backing(backing)
    report = AuditReport(backing_values=values, backing_files=tuple(used))

    sources: list[tuple[Path, str]] = []
    for path in papers:
        try:
            sources.append((path, read_paper(path)))
        except (NotADocx, OSError) as exc:
            report.unreadable.append(str(exc))
    for path in figures or []:
        text = read_figure(path)
        if text is None:
            report.unreadable.append(
                f"{path.name}: no text layer, so its numbers cannot be audited"
            )
            continue
        sources.append((path, text))

    report.papers = tuple(path for path, _text in sources)

    for path, text in sources:
        for atom in find_atoms(text, mask(text)):
            if classifier.classify(atom).kind != UNCLASSIFIED:
                report.classified += 1
                continue
            if looks_like_reference(atom.line_text):
                report.classified += 1
                continue
            candidate = Candidate(
                text=atom.text,
                normalised=normalise_number(atom.text),
                source=path,
                line=atom.line,
                context=atom.line_text.strip()[:140],
            )
            if candidate.normalised in values:
                report.matched.append(candidate)
            else:
                report.unmatched.append(candidate)

    return report


# --------------------------------------------------------------------------- discrimination


@dataclass(frozen=True)
class Discrimination:
    """How much a match is worth, measured against the backing set actually supplied."""

    small_integers: float
    medium_integers: float
    two_decimals: float

    def verdict(self) -> str:
        if self.small_integers > 0.5:
            return (
                "A match on a small integer means almost nothing here. Check those by hand."
            )
        if self.small_integers > 0.2:
            return "Matches on small integers are weak evidence."
        return "Matches carry real information in this project."


def measure_discrimination(values: set[str]) -> Discrimination:
    """What fraction of arbitrary numbers would match this backing set by chance.

    Reported alongside every audit because the alternative is a clean report that means
    nothing. The predecessor project measured 100% of integers up to 100 as already
    "backed"; a check with that property will tell you a paper is fine no matter what is
    in it.
    """
    small = sum(1 for n in range(1, 101) if str(n) in values) / 100
    medium = sum(1 for n in range(1, 1001) if str(n) in values) / 1000
    sample = [f"{n / 100:.2f}" for n in range(100, 1000, 7)]
    decimals = sum(1 for s in sample if normalise_number(s) in values) / len(sample)
    return Discrimination(small_integers=small, medium_integers=medium, two_decimals=decimals)


def render(report: AuditReport, discrimination: Discrimination, root: Path | None = None) -> str:
    def show(path: Path) -> str:
        if root is None:
            return path.name
        try:
            return str(path.relative_to(root))
        except ValueError:
            return path.name

    lines: list[str] = []
    lines.append(
        f"Audited {len(report.papers)} file(s) against {len(report.backing_values)} distinct "
        f"numbers from {len(report.backing_files)} output file(s)."
    )
    lines.append(
        f"{report.examined} numeric tokens: {report.classified} conventions or references, "
        f"{len(report.matched)} found in the outputs, {len(report.unmatched)} not found."
    )

    if report.unreadable:
        lines.append("")
        lines.append("Could not read:")
        lines += [f"  {item}" for item in report.unreadable]

    if report.unmatched:
        lines.append("")
        lines.append("NOT FOUND IN ANY OUTPUT — check each of these:")
        by_source: dict[Path, list[Candidate]] = {}
        for candidate in report.unmatched:
            by_source.setdefault(candidate.source, []).append(candidate)
        for source, items in by_source.items():
            lines.append(f"  {show(source)}")
            for candidate in items[:40]:
                lines.append(f"    line {candidate.line}: {candidate.text}")
                lines.append(f"      {candidate.context}")
            if len(items) > 40:
                lines.append(f"    (+{len(items) - 40} more)")

    lines.append("")
    lines.append("What a match is worth here:")
    lines.append(
        f"  integers 1-100    {discrimination.small_integers:6.0%} of all possible values "
        f"already match"
    )
    lines.append(f"  integers 1-1000   {discrimination.medium_integers:6.0%}")
    lines.append(f"  two-decimal       {discrimination.two_decimals:6.0%}")
    lines.append(f"  {discrimination.verdict()}")
    if discrimination.small_integers > 0.5:
        lines.append(
            "  Point --against at the analysis outputs rather than the raw data if you can. "
            "A row-level dataset contains most small integers, so it matches almost anything."
        )
    lines.append("")
    lines.append(
        "This audit asks only whether a number appears somewhere in the outputs. It cannot "
        "tell whether it appears in the right place, or whether the sentence around it is "
        "true. For a paper still being written, bind the numbers instead: "
        "`manuscript-guard init`."
    )
    return "\n".join(lines)
