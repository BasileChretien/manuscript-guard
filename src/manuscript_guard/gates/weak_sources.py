"""G7: a sentence that claims an effect or a cause, and cites only works that cannot show one.

A case report shows that something happened to one patient; an editorial, a letter or a
comment says what someone thinks. None of them can show that one thing affects or causes
another. A sentence that says "X caused Y" and cites only such works claims more than they
show. One that says "a case of Y after X was reported", or "X may cause Y", does not.

So a sentence of the manuscript is noted (`effect-claim-weak-source`) when all of these hold:

- it cites one or more works (`gates.passages.citing_documents`: the main text and
  `manuscript/supplementary/`, Markdown or LaTeX);
- it holds a word that `claims.py` places on the effect or the causation rung of its ladder
  ("increased", "led to", "prevented", "caused", "demonstrated that"), read on that one
  sentence as `auditing/causal.py` reads a sentence;
- it holds none of the hedges `claims.py` lists ("may", "might", "appears");
- every work it cites has PubMed publication types in its lookup record
  (`sources.pubmed.pubtypes` of `literature/lookups/<citekey>.yaml`, with the record's
  digest as `lookup` wrote it), and each work's types, once the types that say nothing of
  the evidence (`GENERIC`) are set aside, are of `WEAK` only and at least one of them.

A work whose types are not known (no record, no PMID, a record edited by hand, a record of
identifiers the `references.bib` entry no longer has, PubMed silent) gives nothing, and
neither does any sentence that cites it: an unknown work may be the trial that shows the
effect. A negation does not silence the note: "X did not reduce Y", citing a
letter only, claims as much about an effect as "X reduced Y".

It is a note and never more, because the words are read from a list, and a list is not an
exact reading of what a sentence claims: "in patients with reduced renal function" holds an
effect word and claims no effect.

The sentence is named at the line its paragraph starts on, as the other G7 checks of a cited
sentence name it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, Finding, Report

GATE = "G7"
CODE = "effect-claim-weak-source"
#: The rungs of `claims.py`'s ladder whose words claim more than such a work can show.
RUNGS = ("effect", "causation")
#: PubMed's publication types for a work that cannot show an effect, as PubMed writes them.
WEAK = frozenset({"Case Reports", "Editorial", "Letter", "Comment"})
#: PubMed's publication types that say nothing of the evidence: what every article is, a
#: language, and who paid for the work. Set aside before a work's types are read.
GENERIC = frozenset({
    "Journal Article",
    "English Abstract",
    "Research Support, American Recovery and Reinvestment Act",
    "Research Support, N.I.H., Extramural",
    "Research Support, N.I.H., Intramural",
    "Research Support, Non-U.S. Gov't",
    "Research Support, U.S. Gov't, Non-P.H.S.",
    "Research Support, U.S. Gov't, P.H.S.",
    "Research Support, U.S. Government",
})  # fmt: skip
_WEAK = frozenset(kind.casefold() for kind in WEAK)
_GENERIC = frozenset(kind.casefold() for kind in GENERIC)
#: How much of a sentence the finding shows.
_SHOWN = 140


@dataclass(frozen=True)
class Typed:
    """A cited work's PubMed publication types, as its lookup record holds them, and the day
    the record was written."""

    types: tuple[str, ...]
    looked_up_on: str


@dataclass(frozen=True)
class WeakClaim:
    """A sentence that claims an effect or a cause and cites only works that cannot show one:
    where it is, its words, the words that claim, each with its rung, and each work it
    cites with its types."""

    path: Path
    line: int
    sentence: str
    words: tuple[tuple[str, str], ...]
    works: tuple[tuple[str, Typed], ...]


def _hedged(words: Sequence[tuple[str, object]]) -> bool:
    """Whether a sentence whose words are `words` holds a hedge of `claims.py`'s list."""
    from manuscript_guard.claims import HEDGE

    return any(kind == HEDGE for _word, kind in words)


def claimed(sentence: str) -> tuple[tuple[str, str], ...]:
    """The words of `RUNGS` in one sentence, each once, with its rung, in the order they
    stand; none where the sentence holds a hedge. Read as `auditing/causal.py` reads a
    sentence: what prints no prose blanked (citations, bindings, comments), from its first
    word to its end."""
    from manuscript_guard.claims import claim_words, lists, readable

    read = readable(sentence)
    words = claim_words(read, 0, len(read))
    if _hedged(words):
        return ()
    rungs = lists().rungs
    wanted = {rungs.index(rung) for rung in RUNGS}
    return tuple(dict.fromkeys(
        (word, rungs[kind]) for word, kind in words
        if isinstance(kind, int) and kind in wanted
    ))  # fmt: skip


def weak(types: Sequence[str]) -> bool:
    """Whether a work of these PubMed publication types cannot show an effect: once the
    `GENERIC` ones are set aside, at least one is left and every one left is of `WEAK`."""
    kinds = {kind.casefold() for kind in types} - _GENERIC
    return bool(kinds) and kinds <= _WEAK


def _all_weak(works: Sequence[Typed | None]) -> bool:
    """Whether every work a sentence cites has its types known, and is `weak`."""
    return bool(works) and all(work is not None and weak(work.types) for work in works)


def weak_claims(sentences: Sequence, typed: Mapping[str, Typed | None]) -> list[WeakClaim]:
    """Each cited sentence (`checking.produce.CitedSentence`) that claims an effect or a
    cause with no hedge, every work it cites known by `typed` and weak."""
    found = []
    for cited in sentences:
        works = [typed.get(key) for key in cited.keys]
        if not _all_weak(works):
            continue
        words = claimed(cited.text)
        if not words:
            continue
        found.append(WeakClaim(Path(cited.path), cited.line, cited.text, words,
                               tuple(zip(cited.keys, works, strict=True))))  # fmt: skip
    return found


def _of_the_entry(record: dict, fields: dict[str, str] | None) -> bool:
    """Whether a lookup record is of the work the `references.bib` entry names now, as
    `gates/lookups.py` judges it: an entry unchanged since its lookup, or changed with its
    DOI and PMID as the record has them (round 1 of #492)."""
    from manuscript_guard.gates.identifiers import doi_of, pmid_of
    from manuscript_guard.literature.lookups import entry_digest

    if fields is None:
        return False
    if entry_digest(fields) == record["entry_sha256"]:
        return True
    wanted = {k: v for k, v in (("doi", doi_of(fields)), ("pmid", pmid_of(fields))) if v}
    return bool(wanted) and record["identifiers"] == wanted


def _typed(project: Project, citekey: str, fields: dict[str, str] | None) -> Typed | None:
    """The PubMed publication types the lookup record of `citekey` holds, or None where they
    are not known: no record, one that cannot be read or was changed after `lookup` wrote
    it, one of identifiers the entry `fields` no longer has, no answer from PubMed, or none
    of its types kept."""
    from manuscript_guard.literature.lookups import answers_digest, read_record

    record = read_record(project, citekey)
    if record is None or answers_digest(record) != record.get("answers_sha256"):
        return None
    if not _of_the_entry(record, fields):
        return None
    pubmed = record["sources"].get("pubmed") or {}
    types = pubmed.get("pubtypes") if pubmed.get("status") == "found" else None
    if not types:
        return None
    return Typed(tuple(types), record["looked_up_on"])


def said(claim: WeakClaim) -> str:
    """What the finding says of one sentence."""
    words = " and ".join(f"'{word}' ({rung})" for word, rung in claim.words)
    works = "; ".join(f"@{key} ({', '.join(work.types)}; looked up on {work.looked_up_on})"
                      for key, work in claim.works)  # fmt: skip
    return (f"{words} in a sentence with no hedge, whose every cited work PubMed types as a "
            f"case report, an editorial, a letter or a comment: {works}")


HINT = ("a case report, an editorial, a letter or a comment can say that something was seen, "
        "not that one thing affects or causes another: say what the work shows (\"a case of "
        "... after ... was reported\"), hedge the claim (\"may cause\"), or cite a study that "
        "can show the effect. The words are read from a list: where the sentence claims no "
        "effect, nothing needs doing")


def finding(claim: WeakClaim) -> Finding:
    shown = " ".join(claim.sentence.split())
    return Finding(
        gate=GATE,
        code=CODE,
        message=said(claim),
        severity=INFO,
        path=claim.path,
        line=claim.line,
        context=shown if len(shown) <= _SHOWN else shown[: _SHOWN - 3] + "...",
        hint=HINT,
    )


def check_weak_sources(project: Project) -> Report:
    """A note on each cited sentence that claims an effect or a cause, citing only works
    PubMed types as case reports, editorials, letters or comments."""
    from manuscript_guard.checking.produce import cited_sentences
    from manuscript_guard.gates.passages import citing_documents

    sentences = [cited for cited in cited_sentences(citing_documents(project))
                 if claimed(cited.text)]  # fmt: skip
    keys = sorted({key for cited in sentences for key in cited.keys})
    if not keys:
        return Report()
    from manuscript_guard.literature.bibfile import read_entries

    bib = project.path("literature") / "references.bib"
    entries = read_entries(bib) if bib.is_file() else {}
    typed = {key: _typed(project, key, entries.get(key)) for key in keys}
    return Report(tuple(finding(claim) for claim in weak_claims(sentences, typed)))


__all__ = ["CODE", "GENERIC", "RUNGS", "WEAK", "Typed", "WeakClaim", "check_weak_sources",
           "claimed", "finding", "weak", "weak_claims"]
