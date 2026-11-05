"""G7 — every citation resolves, and every literature value has a source.

Three failures this catches, in descending order of how quietly they happen:

1. **An unpinned citation key.** Better BibTeX derives an unpinned key from metadata, so
   correcting an author's initials or a publication year silently renames it. Every
   citation using the old key stops resolving, and the failure surfaces as a missing
   reference in a built document rather than as an error. Pinning is one line in the item's
   Extra field (`Citation Key: xyz`) and it removes the whole class.
2. **A citation key that resolves to nothing, or to several items.** A typo, an item deleted
   from the library, or a duplicate: two items carrying one key, which Better BibTeX refuses
   to export, so `sync-bib` stops on it.
3. **A literature value whose stored source is missing**, which turns a ledger entry from
   evidence back into an assertion.

The gate asks Zotero about the cited keys only (`zotero.lookup`), never for the whole
library, so its answer does not depend on how large the library is or how busy Zotero is.
It works from the committed `.bib` when Zotero is not running, so it still means something
in CI. Pinning can only be checked against Zotero itself, so that part downgrades to a
single warning rather than silently passing.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.contracts.literature import ATTESTED, Literature
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.duplicates import check_duplicates
from manuscript_guard.gates.identifiers import check_identifiers
from manuscript_guard.gates.lookups import check_lookups
from manuscript_guard.zotero import Lookup, ZoteroUnavailable, available, lookup
from manuscript_guard.zotero.citations import cited_as

GATE = "G7"
BIB_FILE = "references.bib"
_BIB_KEY = re.compile(r"^@\w+\s*\{\s*([^,\s]+)", re.MULTILINE)


def bib_keys(project: Project) -> frozenset[str]:
    path = project.path("literature") / BIB_FILE
    if not path.exists():
        return frozenset()
    return frozenset(_BIB_KEY.findall(path.read_text(encoding="utf-8", errors="replace")))


def check_citations(project: Project, literature: Literature) -> Report:
    from manuscript_guard.text.reader import citation_uses

    report = Report()
    uses = citation_uses(project)

    seen: set[str] = {use.citekey for use in uses}
    # What each key was first cited in, which a finding names it as (`cited_as`).
    raws: dict[str, str] = {}
    for use in uses:
        raws.setdefault(use.citekey, use.raw)
    committed = bib_keys(project)
    bib_path = project.path("literature") / BIB_FILE

    # Zotero is asked only when something is cited, and only about what is cited.
    zotero = Lookup()
    running = bool(seen) and available()
    online = running
    if running:
        try:
            zotero = lookup(tuple(sorted(seen)))
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

    known = committed | zotero.found
    checkable = online or bool(committed)
    if seen and not checkable:
        where = (
            "references.bib is empty" if bib_path.exists() else "there is no references.bib"
        )
        zotero_state = "Zotero could not be read" if running else "Zotero is not running"
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="no-reference-source",
                severity=WARN,
                message=f"{where} and {zotero_state}, so citations are unchecked",
                path=bib_path,
                hint="run `manuscript-guard sync-bib` with Zotero open",
            )
        )

    for use in uses:
        if checkable and use.citekey not in known and use.citekey not in zotero.ambiguous:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="citation-unresolved",
                    message=f"{cited_as(use.citekey, use.raw)} matches nothing in the library",
                    path=use.path,
                    line=use.line,
                    hint=_nearest(use.citekey, known, use.raw),
                )
            )

    for citekey in sorted(seen & set(zotero.ambiguous)):
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="citation-key-ambiguous",
                message=f"{cited_as(citekey, raws[citekey])} is carried by "
                f"{zotero.ambiguous[citekey]} items in Zotero, "
                "so Better BibTeX cannot tell which one is cited and `sync-bib` will stop",
                hint="merge the duplicates in Zotero (Duplicate Items), or move the extra copy "
                "to the trash, then run the check again",
            )
        )

    for citekey in sorted(seen & zotero.unpinned):
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="citation-key-unpinned",
                message=f"{cited_as(citekey, raws[citekey])} is not pinned in Zotero",
                hint=f"in Zotero, put the line `Citation Key: {citekey}` at the top of the "
                "item's Extra field; an unpinned key is regenerated from metadata and will "
                "change under you",
            )
        )

    if seen and not online:
        reason = "Zotero could not be read" if running else "Zotero is not running"
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="pinning-unchecked",
                severity=WARN,
                message=f"{reason}, so citation keys were not checked for pinning",
                hint="run the check again with Zotero open before submitting",
            )
        )

    report = report.merge(_sources_exist(project, literature))
    report = report.merge(check_identifiers(project))
    # What the registries said of each cited reference, read from the records `lookup`
    # wrote; nothing is asked here.
    report = report.merge(check_lookups(project, sorted(seen), literature))
    report = report.merge(check_duplicates(project, seen))
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
    """A ledger entry without its stored source is an assertion, not evidence.

    Unless the source is elsewhere for a reason that is not a fault. A new project keeps
    `literature/sources/` out of git and `literature/sources.yaml` in it (Basile, 2026-10-20,
    confirmed 2026-11-05), so on a fresh clone or in CI a copy the record lists is not there:
    that is noted, and the quote is not checked here. Only where git says the copy's path is
    ignored (`literature/away.py`): a tracked copy, or one where git cannot be asked, fails as
    any other does, and so does every copy where `paper.yaml` says they are committed
    (`literature: {sources_in_git: true}`)."""
    from manuscript_guard.literature.away import away
    from manuscript_guard.literature.copies import recorded_names

    report = Report()
    root = project.path("literature")
    recorded = None if project.sources_in_git else recorded_names(project)
    kept = away(project)
    missing = 0
    not_here = 0
    for key, value in sorted(literature.values.items()):
        detail = value.detail or {}
        if value.origin == ATTESTED:
            continue
        source = str(detail.get("source_file") or "").strip()
        if not source:
            # The ledger's schema refuses a blank `source_file`. Should one get here all the
            # same, it is a value with no source, not a value to pass over.
            missing += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="literature-source-missing",
                    message=f"{key}: no stored source is named",
                    path=value.source,
                    hint="name the file under literature/ that the quote was copied from, or "
                    "move the entry to attested.yaml and say who read it",
                )
            )
            continue
        if (root / source).exists():
            continue
        if kept.holds(source):
            not_here += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="literature-source-not-here",
                    severity=INFO,
                    message=f"{key}: {source} is not on this computer. literature/sources.yaml "
                    "records it as stored, and the copies are kept out of git, so the quote "
                    "was not checked against it here",
                    path=value.source,
                    hint="on the computer that holds the copies, `check` holds the quote to it; "
                    + _back_here(kept.saved_by_hand(source))
                    + ". A private repository that commits the copies sets "
                    "`literature: {sources_in_git: true}` in paper.yaml",
                )
            )
            continue
        missing += 1
        unread = recorded is None and not project.sources_in_git
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="literature-source-missing",
                message=f"{key}: the stored source {source} is gone",
                path=value.source,
                hint="restore the file, or move the entry to attested.yaml and say who read it. "
                "A file you saved by hand is recorded by `manuscript-guard sync-sources`, and "
                "a recorded copy git ignores is then a note where it is absent, as in CI"
                + (_unread_record(project) if unread else ""),
            )
        )
    return report.with_counts(literature_sources_missing=missing,
                              literature_sources_not_here=not_here)  # fmt: skip


def _back_here(by_hand: bool) -> str:
    """How a copy kept out of git gets onto this computer: `sync-sources` takes again what it
    took, and never writes into the name of a file the author saved (round 2 of #525)."""
    if by_hand:
        return ("it was saved there by hand, so get it from whoever saved it: "
                "`sync-sources` puts no other copy in its name")  # fmt: skip
    return "to have the copy here, run `manuscript-guard sync-sources`"


def _unread_record(project: Project) -> str:
    """Why literature/sources.yaml vouches for no copy, for a hint."""
    from manuscript_guard.literature.copies import newer_record

    newer = newer_record(project)
    if newer is not None:
        return (f"; literature/sources.yaml was written by a newer version of manuscript-guard "
                f"({newer}), which this one cannot read: upgrade it (pip install --upgrade "
                "manuscript-guard)")  # fmt: skip
    return ("; literature/sources.yaml is not a record `sync-sources` wrote, so it vouches "
            "for no copy")  # fmt: skip


def _nearest(citekey: str, known: frozenset[str], raw: str = "") -> str:
    """The keys of the library spelt nearest `citekey`, named as it is cited (`cited_as`)."""
    import difflib

    close = difflib.get_close_matches(citekey, known, n=3, cutoff=0.6)
    if close:
        return "did you mean " + ", ".join(cited_as(c, raw) for c in close) + "?"
    return "check the key exists and is pinned in Zotero"


def sync_bib(project: Project) -> tuple[Path, int]:
    """Write `literature/references.bib` from the keys the manuscript actually cites."""
    from manuscript_guard.text.reader import citation_uses
    from manuscript_guard.zotero import export

    citekeys = sorted({use.citekey for use in citation_uses(project, whole=True)})
    if not citekeys:
        raise ZoteroUnavailable("the manuscript cites nothing, so there is no bibliography")

    text = export(citekeys)
    path = project.path("literature") / BIB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path, len(citekeys)
