"""`audit --cited FILE`: each citation beside its sentence, for the referee to judge.

A referee asks of each citation whether the work cited says what the sentence says it does.
That is a reading no rule makes, so the table makes none: it lists, a row for each work a
citation names, the sentence (`auditing.sentences`), its file, line and section, the
citation as typed, and the reference list's entry as typed with its DOI and PMID; with
`--lookup`, what the registries said of the work (its title, its year, and whether it was
retracted, withdrawn or put under concern) and its abstract as Europe PMC holds it, asked by
its PMID or its DOI (Basile, 2026-10-29, decision 7); and an empty last column, "Does it
support the sentence? (yours)". A citation of three works is three rows, one for each work.

What is read: a numbered marker (`[3]`, `[3, 5]`, `[3-5]`) where the file's reference list
is numbered, held to it by number as G7's census holds it, and a LaTeX `\\cite` and its kin,
by key, held to the `thebibliography`. What is not, and the file says so: a citation by
author and year, a pandoc citation by key, a superscript number in a .docx, which the text
reads as a digit run on to the word, and Word's citation fields (Zotero, EndNote), which
print the citation the field holds and are not read as one. The table is written to FILE,
Markdown or, by its suffix, HTML; the audit's own output gives counts only, since the file
quotes the manuscript.

Nothing is sent without `--lookup`, and then each DOI or PMID a row names goes to Europe PMC,
once, with nothing else; `--dry-run` lists what would be. An answer is kept only in the
folder `--lookup-cache` names, and read from there the next time.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from manuscript_guard.auditing.references import BY_PLACE, NUMBERED, Census, Entry
from manuscript_guard.auditing.sentences import View

#: The suffixes `--cited` writes, and what each is written as.
FORMATS = {".md": "markdown", ".markdown": "markdown", ".html": "html", ".htm": "html"}
#: The last column, left empty.
YOURS = "Does it support the sentence? (yours)"
#: What the file says is not read, every time.
NOT_READ = (
    "a citation by author and year, \"(Smith et al., 2019)\"",
    "a pandoc citation by key, `[@smith2019]`",
    "a superscript citation number in a .docx, which its text reads run on to the word",
    "Word's citation fields (Zotero, EndNote), whose printed text is not read as a citation",
)
#: Who is asked for an abstract.
EUROPE_PMC = "Europe PMC"


@dataclass(frozen=True)
class Row:
    """One work a citation names, beside the sentence it is cited in. `entry` is None where
    the list holds none for it, and `why` says so."""

    path: Path
    line: int
    section: str
    sentence: str
    written: str
    entry: Entry | None
    why: str = ""


@dataclass
class CitedRead:
    """The rows, and what was not read: how many citations of each kind not listed were
    seen, and a note for each file whose citations could not be held to a list."""

    rows: list[Row] = field(default_factory=list)
    author_year: int = 0
    pandoc: int = 0
    notes: list[tuple[Path, str]] = field(default_factory=list)
    #: What Europe PMC was asked, or would be with `dry_run`; None without --lookup.
    fetched: list | None = None
    dry_run: bool = False
    #: The file the table was written to.
    written: Path | None = None


def cited_sentences(views: list[View], lists: Mapping[Path, Census]) -> CitedRead:
    """A row for each work each citation names, in the order the files and citations
    stand; `lists` gives each file's reference list, a LaTeX file's its document's."""
    read = CitedRead()
    for view in views:
        census = lists.get(view.path)
        numbered = census is not None and census.style in (NUMBERED, BY_PLACE)
        by_number = {e.number: e for e in census.entries} if census is not None else {}
        by_key = {e.key: e for e in census.entries if e.key} if census is not None else {}
        skipped = 0
        read.notes += [(view.path, note) for note in view.notes]
        for cite in view.cites:
            if cite.kind == "author-year":
                read.author_year += 1
                continue
            if cite.kind == "pandoc":
                read.pandoc += 1
                continue
            if cite.kind == "numbered" and not numbered:
                skipped += 1
                continue
            if cite.kind == "latex" and (cite.key == "*" or not cite.prints):
                continue
            index = view.owner(cite.start)
            if index is None:
                continue
            sentence = view.sentences[index]
            for entry, why in _entries(cite, by_number, by_key, census):
                read.rows.append(Row(view.path, sentence.line, sentence.place.title,
                                     sentence.text, cite.written, entry, why))  # fmt: skip
        if skipped:
            read.notes.append((view.path, _unlisted(census, skipped)))
    return read


def _entries(cite, by_number: dict, by_key: dict, census: Census | None):
    """The works a citation names, each with its entry or why there is none."""
    if cite.kind == "numbered":
        for number in dict.fromkeys(cite.numbers):
            entry = by_number.get(number)
            yield entry, "" if entry else f"the reference list holds no entry {number}"
        return
    entry = by_key.get(cite.key)
    if entry is not None:
        yield entry, ""
    elif census is None or not census.entries:
        yield None, (f"{cite.key}: the list BibTeX or biber makes from a .bib is not read, so "
                     "the entry is not shown")  # fmt: skip
    else:
        yield None, f"no \\bibitem of the list has the key {cite.key}"


def _unlisted(census: Census | None, skipped: int) -> str:
    """Why a file's numbered citations were not listed."""
    many = f"{skipped} number{'s' if skipped != 1 else ''} in brackets"
    if census is None or not census.entries:
        return (f"{many} not listed: no reference list was found under a heading in this "
                "file, so none can be held to one")  # fmt: skip
    return (f"{many} not listed: the reference list does not number its entries, so a "
            "number in brackets is not read as a citation")  # fmt: skip


# --------------------------------------------------------------------------- the abstracts


@dataclass(frozen=True)
class Abstract:
    """What Europe PMC was asked of one entry, or would be, and what it said: its answer as
    `search.europepmc_work` gives it, and where it came from, "asked", "kept" or "" for a
    dry run."""

    entry: Entry
    asked: str
    answer: Mapping[str, Any] = field(default_factory=dict)
    came: str = ""
    #: The file whose reference list holds the entry.
    where: Path | None = None


def _key(entry: Entry, where: Path | None) -> tuple:
    """An entry as it is known across the files read: by the file whose list holds it, as
    well as its line and its label, since entry 1 of two files may stand at one line in
    each (round 2 of #482). `where` is the census's file, or the row's."""
    return (entry.path or where, entry.line, entry.label)


def wanted(rows: list[Row]) -> list[tuple[Entry, Path]]:
    """Each entry a row names that has a DOI or a PMID, once, in the order of the rows,
    with the file whose list holds it."""
    seen: dict[tuple, tuple[Entry, Path]] = {}
    for row in rows:
        if row.entry is not None and (row.entry.dois or row.entry.pmids):
            seen.setdefault(_key(row.entry, row.path), (row.entry, row.path))
    return list(seen.values())


def _asked(entry: Entry) -> str:
    named = f"PMID {entry.pmids[0]}" if entry.pmids else f"doi:{entry.dois[0]}"
    return f"{EUROPE_PMC} for {named}"


def _kept_name(entry: Entry) -> str:
    named = f"pmid_{entry.pmids[0]}" if entry.pmids else f"doi_{entry.dois[0]}"
    return "europepmc__" + re.sub(r"[^A-Za-z0-9._-]", "_", named) + ".json"


def _identifiers(entry: Entry) -> dict[str, str]:
    return {"pmid": entry.pmids[0]} if entry.pmids else {"doi": entry.dois[0]}


def _read_kept(path: Path, wanted_ids: dict[str, str]) -> dict[str, Any] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("identifiers") != wanted_ids:
        return None
    answer = record.get("answer")
    return answer if isinstance(answer, dict) and "status" in answer else None


def abstracts(
    rows: list[Row],
    *,
    dry_run: bool = False,
    cache: Path | None = None,
    transport: Callable | None = None,
    services: Any = None,
    pacer: Any = None,
) -> list[Abstract]:
    """Each entry the rows name, asked of Europe PMC by its PMID, else its DOI, or with
    `dry_run` only what would be asked. An answer is kept only in `cache`, never elsewhere,
    and one that did not come is asked for again, never kept."""
    from manuscript_guard.lookup import run, search
    from manuscript_guard.lookup.http import default_transport
    from manuscript_guard.lookup.sources import UNRESOLVABLE

    services = services or search.Services()
    ask = run._asker(transport or default_transport, pacer or run.Pacer(), run.Credentials())
    found: list[Abstract] = []
    for entry, where in wanted(rows):
        asked = _asked(entry)
        if dry_run:
            found.append(Abstract(entry, asked, where=where))
            continue
        ids = _identifiers(entry)
        kept = cache / _kept_name(entry) if cache is not None else None
        answer = _read_kept(kept, ids) if kept is not None and kept.exists() else None
        came = "kept"
        if answer is None:
            came = "asked"
            answer = search.europepmc_work(ids.get("doi"), ids.get("pmid"), ask, services)
            if kept is not None and answer.get("status") != UNRESOLVABLE:
                kept.parent.mkdir(parents=True, exist_ok=True)
                kept.write_text(json.dumps({"source": "europepmc", "identifiers": ids,
                                            "answer": answer}, indent=2, ensure_ascii=True)
                                + "\n", encoding="utf-8")  # fmt: skip
        found.append(Abstract(entry, asked, answer, came, where))
    return found


# ------------------------------------------------------------------------ what is written


@dataclass(frozen=True)
class Registry:
    """What the registries said of one entry, as the table shows it."""

    title: str = ""
    year: str = ""
    standing: str = ""


def registry_of(looked) -> Registry:
    """The title, the year and the standing of one entry, from `references.Looked`."""
    answers = looked.answers or {}
    title, year = "", ""
    for name in ("crossref", "pubmed", "openalex", "datacite"):
        answer = answers.get(name)
        if not isinstance(answer, dict):
            continue
        title = title or str(answer.get("title") or "")
        years = answer.get("years") if isinstance(answer.get("years"), dict) else {}
        found = answer.get("year") or next((years[k] for k in ("issued", "print", "online",
                                                               "posted") if k in years), None)
        year = year or (str(found) if found else "")
    if looked.problems:
        standing = "; ".join(p.message for p in looked.problems)
    elif looked.known:
        standing = "no registry said it was retracted, withdrawn or under concern"
    else:
        standing = "no registry that answered knows it"
    return Registry(title, year, standing)


def _abstract_said(one: Abstract | None) -> str:
    if one is None:
        return ""
    status = one.answer.get("status")
    if status == "found":
        return str(one.answer.get("abstract") or f"{EUROPE_PMC} holds the work and no abstract")
    if status == "absent":
        return f"{EUROPE_PMC} holds no work with this identifier"
    return f"{EUROPE_PMC} did not answer ({one.answer.get('why', 'no reason given')})"


def _entry_said(row: Row) -> str:
    if row.entry is None:
        return row.why
    ids = [f"doi:{doi}" for doi in row.entry.dois] + [f"PMID {p}" for p in row.entry.pmids]
    said = f"{row.entry.label}: {row.entry.text}" if row.entry.text else row.entry.label
    return said + (f" [{'; '.join(ids)}]" if ids else "")


def columns(lookup: bool) -> list[str]:
    """The table's columns: the registries' only with `--lookup`."""
    shown = ["#", "Where", "Section", "Sentence", "Cited", "Reference, as the list has it"]
    if lookup:
        shown += ["Registry title", "Year", "Standing", "Abstract (Europe PMC)"]
    return [*shown, YOURS]


def cells(read: CitedRead, looked: list | None, fetched: list[Abstract] | None,
          show) -> list[list[str]]:  # fmt: skip
    """Each row's cells, in the order of `columns`; each place as `show` gives it
    (`auditing.report._Show.located`), a PDF's as its page and line."""
    by_entry = {_key(one.entry, one.path): one for one in looked or []}
    by_abstract = {_key(one.entry, one.where): one for one in fetched or []}
    found = []
    for number, row in enumerate(read.rows, 1):
        shown = [str(number), show.located(row.path, row.line), row.section, row.sentence,
                 row.written, _entry_said(row)]  # fmt: skip
        if looked is not None:
            one = by_entry.get(_key(row.entry, row.path)) if row.entry is not None else None
            registry = registry_of(one) if one is not None and one.came else Registry()
            if one is not None and not one.came:
                registry = Registry(standing=f"not asked (--dry-run): would ask {one.asked}")
            if one is None and row.entry is not None:
                registry = Registry(standing="not looked up: no DOI or PMID in the entry")
            abstract = (by_abstract.get(_key(row.entry, row.path)) if row.entry is not None
                        else None)  # fmt: skip
            shown += [registry.title, registry.year, registry.standing, _abstract_said(abstract)]
        found.append([*shown, ""])
    return found


def preamble(read: CitedRead, papers: list[str], lookup: str,
             show: Callable[[Path], str]) -> list[str]:  # fmt: skip
    """What the file says before its table: what was read, what was not, and what it is."""
    lines = [
        f"Cited sentences of {', '.join(papers)}, written by manuscript-guard audit --cited.",
        "This file quotes the manuscript: keep it out of a chat with a model and away from "
        "an agent, as the manuscript itself.",
        f"Each row is one work a citation names, beside the sentence it is cited in. The last "
        f"column, \"{YOURS}\", is yours to fill: nothing here judges it.",
        "Read: a number in brackets held to a numbered reference list, and a LaTeX \\cite "
        "held to the \\bibitem keys.",
        "Not read, and so not listed: " + "; ".join(NOT_READ) + ".",
    ]
    if read.author_year or read.pandoc:
        lines.append(f"Seen and not listed: {read.author_year} citation(s) by author and year, "
                     f"{read.pandoc} pandoc citation(s) by key.")  # fmt: skip
    lines += [f"{show(path)}: {note}." for path, note in read.notes]
    lines.append(lookup)
    return lines


def write(path: Path, read: CitedRead, papers: list[str], looked: list | None,
          fetched: list[Abstract] | None, lookup: str,
          show: Callable[[Path], str]) -> None:  # fmt: skip
    """The table, written to `path` as Markdown or HTML by its suffix, and only where no file
    is: one there may hold the referee's judgements (`FileExistsError`)."""
    head = preamble(read, papers, lookup, show)
    shown = columns(looked is not None)
    rows = cells(read, looked, fetched, show)
    if FORMATS[path.suffix.lower()] == "html":
        text = _html(head, shown, rows)
    else:
        text = _markdown(head, shown, rows)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _md_cell(text: str) -> str:
    return " ".join(text.split()).replace("\\", "\\\\").replace("|", "\\|")


def _markdown(head: list[str], shown: list[str], rows: list[list[str]]) -> str:
    lines = ["# Cited sentences", "", *(one for said in head for one in (said, "")),
             "| " + " | ".join(shown) + " |", "|" + "---|" * len(shown)]  # fmt: skip
    lines += ["| " + " | ".join(_md_cell(cell) for cell in row) + " |" for row in rows]
    if not rows:
        lines += ["", "No citation was read."]
    return "\n".join(lines) + "\n"


def _html(head: list[str], shown: list[str], rows: list[list[str]]) -> str:
    def cell(tag: str, text: str) -> str:
        return f"<{tag}>{html.escape(' '.join(text.split()))}</{tag}>"

    body = "\n".join("<tr>" + "".join(cell("td", c) for c in row) + "</tr>" for row in rows)
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>Cited sentences</title>\n<style>body{font-family:sans-serif;margin:1em}"
        "table{border-collapse:collapse}td,th{border:1px solid #999;padding:4px;"
        "vertical-align:top;text-align:left}</style>\n</head>\n<body>\n"
        "<h1>Cited sentences</h1>\n" + "\n".join(f"<p>{html.escape(said)}</p>" for said in head)
        + "\n<table>\n<thead><tr>" + "".join(cell("th", c) for c in shown) + "</tr></thead>\n"
        + f"<tbody>\n{body}\n</tbody>\n</table>\n"
        + ("" if rows else "<p>No citation was read.</p>\n") + "</body>\n</html>\n"
    )


__all__ = [
    "EUROPE_PMC",
    "FORMATS",
    "NOT_READ",
    "YOURS",
    "Abstract",
    "CitedRead",
    "Registry",
    "Row",
    "abstracts",
    "cells",
    "cited_sentences",
    "columns",
    "registry_of",
    "wanted",
    "write",
]
