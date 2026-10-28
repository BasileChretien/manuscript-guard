"""G7 for a paper that has no `references.bib`: its reference list counted, its numbered
citations held to the list, and, only when asked, each DOI and PMID looked up.

The list is the one `audit` cuts from the text (`audit.bibliography_spans`), or in LaTeX the
`thebibliography` the reader finds. What is counted: its entries, and the DOIs and PMIDs
typed in them. Where the entries carry their numbers, "1." or "[1]", a bracketed citation in
the text, `[3]`, `[3, 5]`, `[3-5]`, is held to the list: a number the list does not hold is
reported, and so is an entry no citation names. A .docx whose list Word numbers itself
prints no number in its text, so there an entry's number is its place in the list, and only
where the text cites by number. A bracket after a value that encloses it, `64 [55-72]`, is
an interval and no citation (`audit._intervals`). In LaTeX each `\\cite` key is held to the
`\\bibitem` keys, and a `\\nocite{*}` cites them all.

Looking up sends each DOI to Crossref and OpenAlex and each PMID to PubMed, through the
transport `lookup` uses, and nothing is sent without `--lookup`. What they answer is read as
G7 reads a record (`gates.lookups._standing`): retracted, withdrawn, under concern, published
since. A record is kept only in the folder `--lookup-cache` names, and read from there the
next time instead of asking again.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from manuscript_guard.gates.identifiers import normal_doi

NUMBERED = "numbered"
#: A .docx list whose numbers Word prints: an entry's number is its place.
BY_PLACE = "numbered by place"
KEYED = "keyed"
UNNUMBERED = "not numbered"

#: An entry that carries its number: "12." / "12)" / "[12]".
_NUMBERED_ENTRY = re.compile(r"\s*(?:\[(\d{1,3})\]|(\d{1,3})[.)])(?=\s)")
#: A bracketed citation of numbers, as the marker rule reads one (`audit._WHOLE_MARKER`):
#: "[3]", "[3, 5]", "[3-5]", "[3–5, 8]". Not a link's text, `[3](url)`.
_MARKER = re.compile(
    r"\[\s*(\d{1,3}(?:\s*[-\u2013\u2014]\s*\d{1,3})?"
    r"(?:\s*[,;]\s*\d{1,3}(?:\s*[-\u2013\u2014]\s*\d{1,3})?)*)\s*\](?!\()"
)
_PART = re.compile(r"(\d{1,3})(?:\s*[-\u2013\u2014]\s*(\d{1,3}))?")
#: The widest range read as a run of citations, `[3-12]`: a wider one is not expanded.
MAX_RANGE = 100
_DOI = re.compile(r"\b10\.\d{4,9}(?:\.\d+)*/[^\s\"<>{}]+")
_PMID = re.compile(r"\bPMID\s*:?\s*(\d{1,9})\b", re.IGNORECASE)
_BIBITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")


@dataclass(frozen=True)
class Entry:
    """One entry of a reference list: how the report names it, the line it starts on, its
    number or its key, and the DOIs and PMIDs typed in it."""

    label: str
    line: int
    number: int | None = None
    key: str | None = None
    dois: tuple[str, ...] = ()
    pmids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Problem:
    """Something G7 reports of the list or of a citation, where it stands."""

    code: str
    message: str
    line: int | None = None
    path: Path | None = None


@dataclass
class Census:
    """What a paper's reference list holds, and what is wrong between it and the text."""

    path: Path
    entries: tuple[Entry, ...] = ()
    style: str = UNNUMBERED
    markers: int = 0
    problems: list[Problem] = field(default_factory=list)
    note: str = ""

    @property
    def dois(self) -> int:
        return sum(1 for entry in self.entries if entry.dois)

    @property
    def pmids(self) -> int:
        return sum(1 for entry in self.entries if entry.pmids)


def identifiers(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The DOIs and the PMIDs typed in `text`, each once, in order."""
    dois = [normal_doi(found.group(0)).rstrip(".,;:)]").lower() for found in _DOI.finditer(text)]
    pmids = [found.group(1) for found in _PMID.finditer(text)]
    return tuple(dict.fromkeys(dois)), tuple(dict.fromkeys(pmids))


def _entries_of(lines: list[str], spans: list[tuple[int, int]], paragraphs: bool) -> list[Entry]:
    """The entries under each list's heading: a paragraph each in a .docx, and in Markdown
    a block, or a line that starts with its number."""
    found: list[tuple[int, list[str]]] = []
    for start, end in spans:
        current: list[str] | None = None
        for index in range(start + 1, min(end, len(lines))):
            line = lines[index]
            if not line.strip():
                current = None
                continue
            if paragraphs or current is None or _NUMBERED_ENTRY.match(line):
                current = [line]
                found.append((index + 1, current))
            else:
                current.append(line)
    entries = []
    for place, (line, parts) in enumerate(found, start=1):
        text = " ".join(parts)
        numbered = _NUMBERED_ENTRY.match(text)
        number = int(numbered.group(1) or numbered.group(2)) if numbered else None
        dois, pmids = identifiers(text)
        label = f"entry {number}" if number is not None else f"entry {place} of the list"
        entries.append(Entry(label, line, number=number, dois=dois, pmids=pmids))
    return entries


def markers_in(hidden: str, intervals: list[tuple[int, int]]) -> list[tuple[int, str, list[int]]]:
    """Each bracketed citation of numbers in `hidden`, the text as the audit reads it, with
    the line it is on and the numbers it cites. One inside an interval's span, which runs
    from the value it follows to its closing bracket, is none (`audit._intervals`)."""
    found = []
    for marker in _MARKER.finditer(hidden):
        if any(start <= marker.start() < end for start, end in intervals):
            continue
        numbers: list[int] = []
        for part in _PART.finditer(marker.group(1)):
            low = int(part.group(1))
            high = int(part.group(2)) if part.group(2) else low
            if low <= high <= low + MAX_RANGE:
                numbers += range(low, high + 1)
            else:
                numbers += [low, high]
        found.append((hidden.count("\n", 0, marker.start()) + 1, marker.group(0), numbers))
    return found


def census_of_text(
    path: Path,
    original: str,
    spans: list[tuple[int, int]],
    hidden: str,
    intervals: list[tuple[int, int]],
    *,
    docx: bool,
) -> Census:
    """A Markdown, text or .docx paper's census: its lists are `spans` of `original`, its
    citations are read in `hidden`, where the lists are blanked."""
    if not spans:
        return Census(path, note="no reference list was found under a heading, so none was "
                      "counted")  # fmt: skip
    entries = _entries_of(original.split("\n"), spans, paragraphs=docx)
    census = Census(path, tuple(entries))
    markers = markers_in(hidden, intervals)
    census.markers = len(markers)
    if entries and all(entry.number is not None for entry in entries):
        census.style = NUMBERED
    elif docx and markers and not any(entry.number is not None for entry in entries):
        census.style = BY_PLACE
        entries = [
            Entry(f"entry {place}", entry.line, number=place, dois=entry.dois, pmids=entry.pmids)
            for place, entry in enumerate(entries, start=1)
        ]
        census.entries = tuple(entries)
    else:
        return census
    census.problems = _held_to_numbers(path, entries, markers)
    return census


def _held_to_numbers(
    path: Path, entries: list[Entry], markers: list[tuple[int, str, list[int]]]
) -> list[Problem]:
    numbers = {entry.number for entry in entries}
    highest = max(number for number in numbers if number is not None)
    problems = []
    cited: set[int] = set()
    held = f"{len(numbers)} entr{'y' if len(numbers) == 1 else 'ies'}, the last {highest}"
    for line, written, cites in markers:
        cited.update(cites)
        missing = [number for number in dict.fromkeys(cites) if number not in numbers]
        if missing:
            which = ", ".join(map(str, missing)) if len(missing) < 4 else (
                f"{missing[0]} to {missing[-1]}")  # fmt: skip
            problems.append(Problem(
                "citation-beyond-list",
                f"{written} cites {'entry' if len(missing) == 1 else 'entries'} {which}, which "
                f"the reference list does not hold: it has {held}", line, path,
            ))  # fmt: skip
    if markers:
        seen: set[int] = set()
        for entry in entries:
            if entry.number not in cited and entry.number not in seen:
                seen.add(entry.number)
                problems.append(Problem(
                    "entry-never-cited", f"{entry.label} of the reference list is cited "
                    "nowhere in the text", entry.line, path,
                ))  # fmt: skip
    return sorted(problems, key=lambda problem: problem.line or 0)


def census_of_latex(path: Path, files: list[tuple[Path, Any]]) -> Census:
    """A LaTeX document's census, its files given as their paths and their `Source`s: the
    `\\bibitem`s of its `thebibliography`, held to the keys its citation commands name."""
    entries: list[Entry] = []
    cited: list[tuple[Path, int, str]] = []
    for where, source in files:
        text, reading = source.text, source.reading
        for start, end in reading.references:
            items = list(_BIBITEM.finditer(text, start, end))
            for index, item in enumerate(items):
                stop = items[index + 1].start() if index + 1 < len(items) else end
                dois, pmids = identifiers(text[item.end() : stop])
                key = item.group(1).strip()
                entries.append(Entry(
                    f"\\bibitem{{{key}}}", text.count("\n", 0, item.start()) + 1, key=key,
                    dois=dois, pmids=pmids,
                ))  # fmt: skip
        cited += [(where, text.count("\n", 0, use.offset) + 1, use.key) for use in reading.cited]
    if not entries:
        note = ("no thebibliography was found: a list BibTeX or biber makes from a .bib is "
                "not read, so none was counted") if cited else "no reference list was found"
        return Census(path, note=note)
    census = Census(path, tuple(entries), style=KEYED, markers=len(cited))
    keys = {entry.key for entry in entries}
    every = any(key == "*" for _where, _line, key in cited)
    named = {key for _where, _line, key in cited}
    for where, line, key in cited:
        if key != "*" and key not in keys:
            census.problems.append(Problem(
                "citation-not-listed", f"\\cite{{{key}}} names no \\bibitem of the list",
                line, where,
            ))  # fmt: skip
    if not every:
        census.problems += [
            Problem("entry-never-cited", f"{entry.label} is cited nowhere in the text",
                    entry.line, path)
            for entry in entries if entry.key not in named
        ]  # fmt: skip
    return census


# ----------------------------------------------------------------------------- looking up


@dataclass(frozen=True)
class Looked:
    """What was asked of the registries for one entry, or would be, and what they said."""

    path: Path
    entry: Entry
    asked: str
    problems: tuple[Problem, ...] = ()
    #: Where the record came from: "asked", "kept" (the cache), or "" for a dry run.
    came: str = ""


def _asked(entry: Entry) -> str:
    parts = []
    if entry.dois:
        parts.append(f"Crossref and OpenAlex for doi:{entry.dois[0]}")
    if entry.pmids:
        parts.append(f"PubMed for PMID {entry.pmids[0]}")
    return "; ".join(parts)


def _kept_name(entry: Entry) -> str:
    named = [f"doi_{entry.dois[0]}"] if entry.dois else []
    named += [f"pmid_{entry.pmids[0]}"] if entry.pmids else []
    return re.sub(r"[^A-Za-z0-9._-]", "_", "__".join(named)) + ".json"


def _read_kept(path: Path, wanted: dict[str, str]) -> dict[str, Any] | None:
    """A record kept before for the same identifiers, or None."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("identifiers") != wanted:
        return None
    return record if isinstance(record.get("sources"), dict) else None


def look_up(
    censuses: list[Census],
    *,
    dry_run: bool = False,
    cache: Path | None = None,
    transport: Callable | None = None,
    services: Any = None,
    credentials: Any = None,
    today: date | None = None,
    pacer: Any = None,
) -> list[Looked]:
    """Each entry with a DOI or a PMID, asked of the registries, or with `dry_run` only what
    would be asked. A record is written into `cache` and read from it, never elsewhere."""
    from manuscript_guard.gates.lookups import _standing
    from manuscript_guard.lookup import run
    from manuscript_guard.lookup.http import default_transport

    services = services or run.Services()
    credentials = credentials or run.Credentials.from_environment(None)
    ask = run._asker(transport or default_transport, pacer or run.Pacer(), credentials)
    looked: list[Looked] = []
    for census in censuses:
        for entry in census.entries:
            if not entry.dois and not entry.pmids:
                continue
            asked = _asked(entry)
            if dry_run:
                looked.append(Looked(census.path, entry, asked))
                continue
            wanted = {k: v for k, v in (("doi", entry.dois[:1]), ("pmid", entry.pmids[:1])) if v}
            wanted = {k: v[0] for k, v in wanted.items()}
            kept = cache / _kept_name(entry) if cache is not None else None
            record = _read_kept(kept, wanted) if kept is not None and kept.exists() else None
            came = "kept"
            if record is None:
                came = "asked"
                planned = run.Planned(entry.label, doi=wanted.get("doi"), pmid=wanted.get("pmid"))
                record = run.look_up(planned, ask, services, credentials, today or date.today())
                run._never_kept(record, credentials)
                # An answer that did not come is asked for again, never kept as one.
                if kept is not None and not _unanswered(record):
                    kept.parent.mkdir(parents=True, exist_ok=True)
                    kept.write_text(json.dumps(record, indent=2, ensure_ascii=True) + "\n",
                                    encoding="utf-8")  # fmt: skip
            found = _standing(entry.label, {}, record.get("sources", {}), census.path, None)
            problems = tuple(
                Problem(f.code, f.message.removeprefix("@"), entry.line, census.path)
                for f in found
            ) + tuple(
                Problem("lookup-unanswered", f"{entry.label}: {name} did not answer ({why})",
                        entry.line, census.path)
                for name, why in _unanswered(record)
            )  # fmt: skip
            looked.append(Looked(census.path, entry, asked, problems, came))
    return looked


def _unanswered(record: dict[str, Any]) -> list[tuple[str, str]]:
    """Each registry that gave no answer, and why: a check that did not happen is said."""
    from manuscript_guard.lookup.sources import UNRESOLVABLE

    return [
        (name, str(answer.get("why", "no reason given")))
        for name, answer in record.get("sources", {}).items()
        if isinstance(answer, dict) and answer.get("status") == UNRESOLVABLE
    ]
