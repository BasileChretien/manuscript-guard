"""G7: a claim of novelty or absence rests on a recorded search for the earlier study.

The list in `data/novelty_claims.yaml` reads the claims (`currency/novelty.py`); each is held
to the entries of kind `novelty` in `literature/currency.yaml` placed on it, and their search
records (DESIGN.md, "A claim to be first, or that nothing is known, rests on a recorded
search"). G7 grades the record of the search, never whether the claim is true:

- `novelty-unsearched`: a priority or absence claim with no entry, or whose entry is not
  searched: no N1 the tool ran, or an N1 that kept works and no N2 the tool ran, whatever
  its day (the design asks for no order). A warning from drafting, a failure at submission
  (D4.2).
- `novelty-search-stale`: the claim was searched more than six months ago, as of the earlier
  of its newest N1 and, where N2 is needed, its newest N2. A warning, a failure at submission.
- `novelty-softer`: a softer claim ("little is known") not searched, or searched more than six
  months ago: a note (D4.3).
- `currency-entry-unplaced`: a sentence of a novelty entry that no claim the list reads has,
  folded, exactly: a note.
- `currency-record-edited`: a novelty entry's search record that no longer matches its digest
  or its schema, which refuses a `not_searched` that is empty or says nothing was left out.
- `currency-decision-not-human`: a `not_a_claim`, or a search by hand, in a model's name.
- `currency-reading-invalid`: a reading filed for a novelty entry, which is never read.

A claim on which an entry with a person's `not_a_claim` is placed is no claim. A search by
hand adds to the record and meets neither step: only the tool's searches can be run again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.currency import novelty, records
from manuscript_guard.currency.records import Entry
from manuscript_guard.findings import FAIL, INFO, WARN, Finding
from manuscript_guard.policy import SUBMISSION

#: The status of a search the tool ran and a source answered.
RUN = "run"
BY_HAND = "by hand"


@dataclass(frozen=True)
class Searched:
    """How far one entry's searches got: the day the claim is searched as of, or None and
    what is missing."""

    day: date | None
    how: str = ""


def searched(entry: Entry, searches: list[dict]) -> Searched:
    """Whether the sound search records of one novelty entry answer its claim: an N1 the tool
    ran, at any source, and, where any such N1 kept a work, an N2 the tool ran. The day is the
    earlier of the newest of each needed (Basile's answers of 2026-11-07)."""
    first = [one for one in searches if one["step"] == "N1" and one.get("status", RUN) == RUN]
    if not first:
        if not searches:
            how = f"{entry.id} is marked, not searched"
        elif all(one.get("status") == BY_HAND for one in searches):
            how = (f"{entry.id} is searched by hand only, and a search by hand never stands "
                   "in for the tool's N1")  # fmt: skip
        elif any(one["step"] == "N1" for one in searches):
            how = f"{entry.id}'s search for the earlier study (N1) was asked of no source"
        else:
            how = f"{entry.id} has no search for the earlier study (N1)"
        return Searched(None, how)
    day = max(date.fromisoformat(str(one["searched_on"])) for one in first)
    if not any(one.get("candidates") for one in first):
        return Searched(day)
    forward = [one for one in searches if one["step"] == "N2" and one.get("status", RUN) == RUN]
    if not forward:
        return Searched(None, f"{entry.id}'s search for the earlier study (N1) kept works, "
                        "and none was followed forward to the works citing it (N2)")
    return Searched(min(day, max(date.fromisoformat(str(one["searched_on"]))
                                 for one in forward)))  # fmt: skip


def _is_model(name: str) -> bool:
    from manuscript_guard.gates.literature import _MODEL_NAME

    return bool(_MODEL_NAME.search(name))


def _person_says_no_claim(entry: Entry) -> bool:
    by = str((entry.not_a_claim or {}).get("by") or "")
    return bool(by) and not _is_model(by)


def no_claim(placed: list[Entry]) -> bool:
    """Whether the claim is none: an entry placed on it carries a person's `not_a_claim`,
    whatever the others placed on it say."""
    return any(_person_says_no_claim(entry) for entry in placed)


def entries_on(claim: novelty.Claim, entries: list[Entry], words: dict[str, set[str]]
               ) -> list[Entry]:  # fmt: skip
    """The entries placed on a claim: those one of whose sentences has its words, folded,
    exactly (round 1 of #580: `NEAR` let one claim's search cover another)."""
    return [entry for entry in entries if claim.folded in words[entry.id]]


def check_novelty(project: Project, stage: str, held, path: Path
                  ) -> tuple[list[Finding], dict[str, int]]:  # fmt: skip
    """What G7 says of the claims of novelty and their entries, and its counts. `held` is the
    currency gate's records (`gates.currency._Records`)."""
    from manuscript_guard.gates import currency as gate
    from manuscript_guard.literature.passages import statement_words

    entries, report = records.read_entries(project)
    if report.failures:
        return [], {}
    entries = [entry for entry in entries if entry.novelty]
    found = novelty.claims(project)
    have = {claim.folded for claim in found}
    out: list[Finding] = []
    sound: dict[str, list[dict]] = {}
    for entry in entries:
        out += _of_entry(entry, held, path, have)
        sound[entry.id] = [read.record for read in held.searches.get(entry.id, [])
                           if read.problem is None and read.record]  # fmt: skip
    words = {entry.id: {statement_words(one) for one in entry.sentences} for entry in entries}
    stale_before = gate.months_before(gate.today(), gate.STALE_MONTHS)
    counts = {"novelty_claims": len(found), "novelty_searched": 0, "novelty_stale": 0,
              "novelty_not_claims": 0}  # fmt: skip
    for claim in found:
        placed = entries_on(claim, entries, words)
        if no_claim(placed):
            counts["novelty_not_claims"] += 1
            continue
        states = [searched(entry, sound[entry.id]) for entry in placed]
        days = [state.day for state in states if state.day is not None]
        if days and max(days) >= stale_before:
            counts["novelty_searched"] += 1
            continue
        if days:
            counts["novelty_stale"] += 1
        out.append(_said(claim, states, max(days) if days else None, stage, path))
    return out, counts


def _said(claim: novelty.Claim, states: list[Searched], day: date | None, stage: str,
          path: Path) -> Finding:  # fmt: skip
    from manuscript_guard.gates.currency import STALE_MONTHS, _shown

    shown = f"{claim.words!r}"
    binding = claim.list in novelty.BINDING
    severity = (FAIL if stage == SUBMISSION else WARN) if binding else INFO
    if day is not None:
        code = "novelty-search-stale" if binding else "novelty-softer"
        message = (f"{shown} is a claim about the literature, and its search for the earlier "
                   f"study is of {day}, more than {STALE_MONTHS} months ago")  # fmt: skip
        hint = ("run the searches again with `manuscript-guard references --replay <id>`, "
                "and read what they find")  # fmt: skip
    else:
        how = states[0].how if states else "no entry in literature/currency.yaml"
        code = "novelty-unsearched" if binding else "novelty-softer"
        message = f"{shown} is a claim about the literature, with no recorded search: {how}"
        hint = ("mark it with `manuscript-guard references --novelty \"<words>\" --as <who>`, "
                "search for the earlier study with `references --search <id> --terms ... "
                "--not-searched ...` and, where that keeps works, follow the nearest forward "
                "with `--forward <work>` (the literature-currency skill says how); or reword "
                "it")  # fmt: skip
    return Finding(gate="G7", code=code, severity=severity, message=message,
                   path=claim.path, line=claim.line, context=_shown(claim.text),
                   hint=hint)  # fmt: skip


def _of_entry(entry: Entry, held, path: Path, have: set[str]) -> list[Finding]:
    """What G7 says of one novelty entry's own records: its edited searches, readings filed
    for it, its sentences no claim has, and what a model signed."""
    from manuscript_guard.gates.currency import _edited, _finding
    from manuscript_guard.literature.passages import statement_words

    out = [_edited(read) for read in held.searches.get(entry.id, []) if read.problem]
    for read in held.readings.get(entry.id, []):
        out.append(_finding(
            "currency-reading-invalid", f"{entry.named}: {read.path.name} reads a claim of "
            "novelty, which is held to its searches and never read", read.path,
            "delete the reading: a claim of novelty is searched for, and nothing decides it"))
    for sentence in entry.sentences:
        if statement_words(sentence) not in have:
            out.append(_finding(
                "currency-entry-unplaced", f"{entry.named}: no claim of the manuscript reads "
                f"{' '.join(sentence.split())!r}", path,
                "mark the claim as the manuscript now has it with `manuscript-guard references "
                f"--novelty \"<words>\" --id {entry.id}`, which takes this sentence out of the "
                "entry, or remove the entry", INFO))  # fmt: skip
    by = str((entry.not_a_claim or {}).get("by") or "")
    if by and _is_model(by):
        out.append(_finding(
            "currency-decision-not-human", f"{entry.named}: {by!r} cannot say a sentence makes "
            "no claim about the literature", path,
            "only a named person says so, with why; a model may search, and the record shows "
            "what it found"))  # fmt: skip
    for read in held.searches.get(entry.id, []):
        record = read.record or {}
        if read.problem is None and record.get("status") == BY_HAND and _is_model(
                str(record.get("terms_by") or "")):  # fmt: skip
            out.append(_finding(
                "currency-decision-not-human", f"{entry.named}: {read.path.name} is a search "
                f"by hand filed in the name of {record['terms_by']!r}", read.path,
                "a search by hand is a person's word for what they searched: only a named "
                "person files one"))  # fmt: skip
    return out


__all__ = ["BY_HAND", "RUN", "Searched", "check_novelty", "entries_on", "no_claim", "searched"]
