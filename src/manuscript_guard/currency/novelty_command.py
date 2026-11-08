"""`references --novelty`, and the claims of novelty in `references` and `--explain`.

A claim the list in `data/novelty_claims.yaml` reads is marked as an entry of kind `novelty` in
`literature/currency.yaml`, found by words of its own, folded and taken as one run. Sentences
whose folded words are the same are one claim here, in one file or several. With `--id`, the
sentence goes into that entry's `also`, and each sentence of the entry that no claim of the
manuscript has any more is taken out, so that a claim reworded is marked again with its
searches. With `--not-a-claim --why`, a person says the sentence makes no claim about the
literature.
"""

from __future__ import annotations

from datetime import date

from manuscript_guard.contracts.project import Project
from manuscript_guard.currency import novelty, records
from manuscript_guard.currency.command import Refused, Row, _search_line, _where


def mark(project: Project, words: str, by: str | None, entry_id: str | None = None,
         question: str | None = None, not_a_claim: str | None = None) -> str:  # fmt: skip
    """Mark the claim that holds `words` as an entry of kind `novelty`, or with `entry_id`
    put it into that entry; with `not_a_claim`, a person's word that it is no claim."""
    from manuscript_guard.gates.literature import _MODEL_NAME
    from manuscript_guard.literature.passages import statement_words

    if by is not None and not by.strip():
        raise Refused("--as names the person who marks the claim")
    if not_a_claim is not None:
        if not by or _MODEL_NAME.search(by):
            raise Refused("--not-a-claim is a person's word that the sentence makes no claim "
                          "about the literature: --as names that person, never a model")
        if not not_a_claim.strip():
            raise Refused("--not-a-claim needs --why, the reason")
    found = novelty.claims(project)
    wanted = statement_words(words)
    holding = [claim for claim in found if wanted and wanted in claim.folded]
    distinct = {claim.folded for claim in holding}
    if len(distinct) != 1:
        where = "; ".join(_where(project, claim.path, claim.line) for claim in holding)
        raise Refused(f"{len(distinct)} claims the list reads hold those words"
                      + (f" ({where}): give more of them" if holding else
                         "; `manuscript-guard references` lists the claims it reads"))
    claim = holding[0]
    text = " ".join(claim.text.split())
    document, report = records.read_document(project)
    # Round 1 of #583: a file that could not be read was taken for none, and written over.
    if report.failures:
        raise Refused("; ".join(finding.message for finding in report.failures))
    document = document or {"schema": records.SCHEMA, "entries": []}
    entries = [dict(raw) for raw in document.get("entries") or []]
    on = [raw for raw in entries if raw.get("kind") == records.NOVELTY and claim.folded in
          {statement_words(one) for one in records._entry(raw).sentences}]  # fmt: skip
    if entry_id is not None:
        raw = next((one for one in entries if one["id"] == entry_id), None)
        if raw is None:
            raise Refused(f"literature/currency.yaml has no entry {entry_id}")
        if raw.get("kind") != records.NOVELTY:
            raise Refused(f"{entry_id} is not a claim of novelty")
        if any(one is not raw for one in on):
            raise Refused(f"the claim has an entry already, {on[0]['id']}")
        if on and not_a_claim is None:
            raise Refused(f"{entry_id} holds the claim already")
        said = (f"{entry_id} holds the claim" if on
                else _put_into(raw, text, claim.folded, {one.folded for one in found}))
    else:
        if on:
            raise Refused(f"the claim has an entry already, {on[0]['id']}: put another "
                          f"sentence into it with --id {on[0]['id']}")  # fmt: skip
        raw = {"id": records.next_id(document), "kind": records.NOVELTY, "sentence": text}
        entries.append(raw)
        said = f"marked as {raw['id']}: {_where(project, claim.path, claim.line)}"
    if by and "marked_by" not in raw:
        raw |= {"marked_by": by.strip(), "marked_on": date.today().isoformat()}
    if question is not None:
        from manuscript_guard.currency.searching import framed

        raw.update(framed(project, raw, question))
    if not_a_claim is not None:
        raw["not_a_claim"] = {"by": str(by).strip(), "why": " ".join(not_a_claim.split()),
                              "decided_on": date.today().isoformat()}  # fmt: skip
        said += f"; {str(by).strip()} says it makes no claim about the literature"
    records.write_document(project, {**document, "entries": entries})
    records.ensure_gitignore(project)
    return said


def _put_into(raw: dict, text: str, folded: str, have: set[str]) -> str:
    """Put the sentence `text` into a novelty entry's `also`, and take out each sentence of the
    entry that no claim has; where `sentence` goes, the first of `also` left takes its place."""
    from manuscript_guard.literature.passages import statement_words

    held = [str(raw["sentence"]), *(str(one) for one in raw.get("also") or ())]
    kept =[one for one in held if statement_words(one) in have]
    gone = [one for one in held if statement_words(one) not in have]
    kept.append(text)
    raw["sentence"], also = kept[0], kept[1:]
    if also:
        raw["also"] = also
    else:
        raw.pop("also", None)
    said = f"{raw['id']}: the claim is put into it"
    if gone:
        said += "; taken out, since no claim reads so now: " + "; ".join(
            repr(" ".join(one.split())) for one in gone)
    return said


def state_of(entries: list[records.Entry], held) -> str:
    """What G7 makes of a claim with these entries placed on it, in a few words: no entry, a
    person's word that it is no claim, searched as of a day (stale past six months), or
    what its search lacks. Read as `gates.novelty` reads it (round 1 of #583: the listing
    took a model's `not_a_claim` for a person's, and a stale search for a current one)."""
    from manuscript_guard.gates import currency as gate
    from manuscript_guard.gates.novelty import _person_says_no_claim, searched

    if not entries:
        return "no entry"
    noted = [entry for entry in entries if _person_says_no_claim(entry)]
    if noted:
        return f"no claim, by {noted[0].not_a_claim['by']}"
    states = [searched(entry, [read.record for read in held.searches.get(entry.id, [])
                               if read.problem is None and read.record])
              for entry in entries]  # fmt: skip
    days = [one.day for one in states if one.day is not None]
    if not days:
        return states[0].how
    if max(days) < gate.months_before(gate.today(), gate.STALE_MONTHS):
        return (f"stale, searched as of {max(days)}, more than {gate.STALE_MONTHS} months "
                "ago")  # fmt: skip
    return f"searched as of {max(days)}"


def rows(project: Project, held) -> list[Row]:
    """A row of `references` for each claim the list reads, with how far its search got."""
    from manuscript_guard.literature.passages import statement_words

    entries, _report = records.read_entries(project)
    entries = [entry for entry in entries if entry.novelty]
    out = []
    for claim in novelty.claims(project):
        placed = [entry for entry in entries
                  if claim.folded in {statement_words(one) for one in entry.sentences}]
        out.append(Row(placed[0].id if placed else None, "", _where(project, claim.path,
                                                                     claim.line),
                       f"{claim.list}: {state_of(placed, held)}", " ".join(claim.text.split()),
                       kind=records.NOVELTY))  # fmt: skip
    return out


def explain(project: Project, entry: records.Entry, held) -> str:
    """One novelty entry: its sentences and where each is placed, its question, what a person
    said of it, each search with its years and what it did not reach, and what G7 says."""
    from manuscript_guard.literature.passages import statement_words

    found = novelty.claims(project)
    lines = [f"{entry.id}  a claim of novelty"]
    for one in entry.sentences:
        at = [claim for claim in found if claim.folded == statement_words(one)]
        where = ", ".join(_where(project, claim.path, claim.line) for claim in at) or "unplaced"
        lines.append(f"  sentence ({where}): {' '.join(one.split())}")
    if entry.question:
        lines.append(f"  question: {entry.question}")
    if entry.marked_by:
        lines.append(f"  marked by {entry.marked_by}")
    if entry.not_a_claim:
        lines.append(f"  no claim, by {entry.not_a_claim.get('by')}: "
                     f"{entry.not_a_claim.get('why')}")  # fmt: skip
    for read in held.searches.get(entry.id, []):
        if read.problem:
            lines.append(f"  search {read.path.name}: {read.problem}")
            continue
        lines.append(_search_line(read.record))
        record = read.record
        years = record.get("years") or {}
        lines.append(f"    years {years.get('from') or 'from the first'} to {years.get('to')}"
                     + (f", from {record['seed']}" if record.get("seed") else "")
                     + f"; not searched: {record.get('not_searched')}")  # fmt: skip
    # Read over every entry that shares a sentence with this one, as G7 reads a claim over
    # every entry placed on it (round 2 of #583).
    mine = {statement_words(one) for one in entry.sentences}
    together = [one for one in records.read_entries(project)[0] if one.novelty
                and mine & {statement_words(said) for said in one.sentences}]  # fmt: skip
    lines.append(f"  G7: {state_of(together or [entry], held)}")
    return "\n".join(lines)


__all__ = ["explain", "mark", "rows", "state_of"]
