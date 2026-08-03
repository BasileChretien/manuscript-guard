"""G7 — every citation resolves, and every literature value has a source.

Three failures this catches, in descending order of how quietly they happen:

1. **An unpinned citation key.** Better BibTeX derives an unpinned key from metadata, so
   correcting an author's initials or a publication year silently renames it. Every
   citation using the old key stops resolving, and the failure surfaces as a missing
   reference in a built document rather than as an error. Pinning is one menu item in
   Zotero and it removes the whole class.
2. **A citation key that resolves to nothing.** A typo, or an item deleted from the library.
3. **A literature value whose stored source is missing**, which turns a ledger entry from
   evidence back into an assertion.

The gate works from the committed `.bib` when Zotero is not running, so it still means
something in CI. Pinning can only be checked against Zotero itself, so that part downgrades
to a single warning rather than silently passing.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.contracts.literature import ATTESTED, Literature
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.zotero import ZoteroUnavailable, available, find_citations, library

GATE = "G7"
BIB_FILE = "references.bib"
_BIB_KEY = re.compile(r"^@\w+\s*\{\s*([^,\s]+)", re.MULTILINE)


def bib_keys(project: Project) -> frozenset[str]:
    path = project.path("literature") / BIB_FILE
    if not path.exists():
        return frozenset()
    return frozenset(_BIB_KEY.findall(path.read_text(encoding="utf-8", errors="replace")))


def check_citations(project: Project, literature: Literature) -> Report:
    report = Report()
    uses = []
    for path in source_files(project.path("manuscript")):
        uses.extend(find_citations(path.read_text(encoding="utf-8"), path))

    committed = bib_keys(project)
    zotero_keys: frozenset[str] = frozenset()
    unpinned: set[str] = set()
    online = available()
    if online:
        try:
            index = library()
            zotero_keys = frozenset(index)
            unpinned = {key for key, ref in index.items() if not ref.pinned}
        except ZoteroUnavailable as exc:
            online = False
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="zotero-unreadable",
                    severity=WARN,
                    message=str(exc),
                    hint="the committed references.bib is being used instead",
                )
            )

    known = committed | zotero_keys
    if not known:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="no-reference-source",
                severity=WARN,
                message="no references.bib and no running Zotero, so citations are unchecked",
                path=project.path("literature") / BIB_FILE,
                hint="run `manuscript-guard sync-bib` with Zotero open",
            )
        )

    seen: set[str] = set()
    for use in uses:
        seen.add(use.citekey)
        if known and use.citekey not in known:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="citation-unresolved",
                    message=f"@{use.citekey} matches nothing in the library",
                    path=use.path,
                    line=use.line,
                    hint=_nearest(use.citekey, known),
                )
            )

    for citekey in sorted(seen & unpinned):
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="citation-key-unpinned",
                message=f"@{citekey} is not pinned in Zotero",
                hint="in Zotero, right-click the item and pin the citation key; an unpinned "
                "key is regenerated from metadata and will change under you",
            )
        )

    if seen and not online and not unpinned:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="pinning-unchecked",
                severity=WARN,
                message="Zotero is not running, so citation keys were not checked for pinning",
                hint="run the check again with Zotero open before submitting",
            )
        )

    report = report.merge(_sources_exist(project, literature))
    stale = sorted(committed - seen) if committed else []
    for citekey in stale:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="reference-uncited",
                severity=WARN,
                message=f"references.bib holds @{citekey}, which nothing cites",
                path=project.path("literature") / BIB_FILE,
                hint="run `manuscript-guard sync-bib` to rebuild it from what is cited",
            )
        )

    return report.with_counts(
        citations=len(uses),
        citations_distinct=len(seen),
        citations_narrative=sum(1 for u in uses if u.narrative),
    )


def _sources_exist(project: Project, literature: Literature) -> Report:
    """A ledger entry without its stored source is an assertion, not evidence."""
    report = Report()
    root = project.path("literature")
    missing = 0
    for key, value in sorted(literature.values.items()):
        detail = value.detail or {}
        if value.origin == ATTESTED:
            continue
        source = detail.get("source_file")
        if not source:
            continue
        if not (root / source).exists():
            missing += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="literature-source-missing",
                    message=f"{key}: the stored source {source} is gone",
                    path=value.source,
                    hint="restore the file, or move the entry to attested.yaml and say who "
                    "read it",
                )
            )
    return report.with_counts(literature_sources_missing=missing)


def _nearest(citekey: str, known: frozenset[str]) -> str:
    import difflib

    close = difflib.get_close_matches(citekey, known, n=3, cutoff=0.6)
    if close:
        return "did you mean " + ", ".join(f"@{c}" for c in close) + "?"
    return "check the key exists and is pinned in Zotero"


def sync_bib(project: Project) -> tuple[Path, int]:
    """Write `literature/references.bib` from the keys the manuscript actually cites."""
    from manuscript_guard.zotero import export

    uses = []
    for path in source_files(project.path("manuscript")):
        uses.extend(find_citations(path.read_text(encoding="utf-8"), path))
    citekeys = sorted({use.citekey for use in uses})
    if not citekeys:
        raise ZoteroUnavailable("the manuscript cites nothing, so there is no bibliography")

    text = export(citekeys)
    path = project.path("literature") / BIB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, len(citekeys)
