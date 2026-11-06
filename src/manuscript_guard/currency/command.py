"""`manuscript-guard references`: the claims in scope, an entry explained, a claim marked, a
reading filed and the rules run, a proposal refused.

Nothing here searches or calls a model: a reading is written by a reader (an agent session, a
model, a person) and filed whole. What the command writes is `literature/currency.yaml`, a
reading under `literature/currency/readings/`, and the works store's `.gitignore`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.currency import records, rules
from manuscript_guard.currency.survey import Survey, find_sentence, survey


class Refused(Exception):
    """What the command will not do, in a sentence for the person; it exits 2."""


@dataclass(frozen=True)
class Row:
    id: str | None
    citekey: str
    where: str
    state: str
    sentence: str
    #: A line for each reply in Word to the entry's comment (`replies.said_of`).
    replies: tuple[str, ...] = ()


def _where(project: Project, path: Path, line: int) -> str:
    try:
        shown = path.relative_to(project.root).as_posix()
    except ValueError:
        shown = str(path)
    return f"{shown}:{line}"


def state_of(entry: records.Entry | None, held, accepted: bool = False) -> str:
    """How far one claim's entry got, in a few words."""
    if entry is None:
        return "no entry"
    decision = entry.decision
    if decision:
        said = decision["action"] + (f" {decision['candidate']}" if decision.get("candidate")
                                     else "")  # fmt: skip
        by = "by the rules" if decision["by"] == "rules" else f"by {decision['by']}"
        answer = entry.answer
        if decision["action"] in (rules.REPLACE, rules.ADD):
            said += (", accepted: the sentence cites it" if accepted
                     else f", {answer['status']} by {answer['by']}" if answer
                     else ", not answered: cite it (Zotero, then `sync-bib`), or "
                     f"`references --refuse {entry.id}`")  # fmt: skip
        return f"{said} ({by})"
    readings = [read for read in held.readings.get(entry.id, []) if read.problem is None]
    searches = [read for read in held.searches.get(entry.id, [])
                if read.problem is None and records.asked(read.record)]  # fmt: skip
    if not readings and not searches:
        return "marked, not searched"
    return f"searched {len(searches)}, read {len(readings)} of {rules.READINGS}, not decided"


def listing(project: Project) -> tuple[list[Row], list[records.Entry]]:
    """A row per claim in scope, and the entries no sentence matches."""
    from manuscript_guard.currency import replies
    from manuscript_guard.gates.currency import _Records

    found, report = survey(project)
    if report.failures:
        raise Refused("; ".join(finding.message for finding in report.failures))
    held = _Records(project)
    replied = replies.held(project)
    rows = [
        Row(claim.entry.id if claim.entry else None, claim.citekey,
            _where(project, claim.sentence.path, claim.sentence.line),
            state_of(claim.entry, held, bool(claim.entry and claim.entry.id in found.accepted)),
            " ".join(claim.sentence.text.split()),
            tuple(replies.said_of(project, claim.entry, replied,
                                  claim.entry.id in found.accepted) if claim.entry else ()))
        for claim in found.claims
    ]  # fmt: skip
    return rows, list(found.unplaced)


def unplaced_replies(project: Project, unplaced: list[records.Entry]) -> dict[str, list[str]]:
    """The lines of `replies.said_of` for each entry no sentence matches: an edit that left an
    entry unplaced leaves the replies to its comment standing."""
    from manuscript_guard.currency import replies

    replied = replies.held(project)
    return {entry.id: replies.said_of(project, entry, replied, False) for entry in unplaced}


def rendered(rows: list[Row], unplaced: list[records.Entry],
             replied: dict[str, list[str]] | None = None) -> str:  # fmt: skip
    lines = []
    for row in rows:
        lines.append(f"{row.id or '-'}  @{row.citekey}  {row.where}  {row.state}")
        lines.append(f"    {row.sentence}")
        lines += [f"    {said}" for said in row.replies]
    for entry in unplaced:
        lines.append(f"{entry.id}  @{entry.citekey}  unplaced: no sentence reads so")
        lines.append(f"    {' '.join(entry.sentence.split())}")
        lines += [f"    {said}" for said in (replied or {}).get(entry.id, [])]
    decided = sum(row.state not in ("no entry", "marked, not searched")
                  and "not decided" not in row.state for row in rows)  # fmt: skip
    lines.append(f"claims in scope: {len(rows)}, decided: {decided}; unplaced entries: "
                 f"{len(unplaced)}")  # fmt: skip
    return "\n".join(lines)


def _entry_of(project: Project, entry_id: str) -> tuple[dict, dict]:
    document, report = records.read_document(project)
    if report.failures:
        raise Refused("; ".join(finding.message for finding in report.failures))
    for raw in (document or {}).get("entries") or []:
        if raw["id"] == entry_id:
            return document, raw
    raise Refused(f"literature/currency.yaml has no entry {entry_id}")


def explain(project: Project, entry_id: str, readings: bool = False) -> str:
    """One entry: its question, searches, how many readings are filed, and what the rules
    give, with why. The readings' fields and quotes are printed only with `readings`: a
    reader runs this before reading, and the second reading is made without the first."""
    from manuscript_guard.gates.currency import _bib, _Records, rules_decision

    _document, raw = _entry_of(project, entry_id)
    entry = records._entry(raw)
    held = _Records(project)
    lines = [f"{entry.id}  @{entry.citekey}", f"  sentence: {' '.join(entry.sentence.split())}"]
    if entry.question:
        lines.append(f"  question: {entry.question}")
    if entry.marked_by:
        lines.append(f"  marked by {entry.marked_by}")
    for read in held.searches.get(entry.id, []):
        if read.problem:
            lines.append(f"  search {read.path.name}: {read.problem}")
            continue
        lines.append(_search_line(read.record))
    filed = held.readings.get(entry.id, [])
    usable = [read.record for read in filed if not read.problem]
    if readings:
        for read in filed:
            lines += ([f"  reading {read.path.name}: {read.problem}"] if read.problem
                      else _reading_lines(read.record))  # fmt: skip
    elif filed:
        unusable = len(filed) - len(usable)
        lines.append(f"  readings: {len(filed)} filed"
                     + (f", {unusable} of them unusable" if unusable else "")
                     + f"; `references --explain {entry.id} --readings` prints them, which a "
                     "reader still to read the entry does not run")  # fmt: skip
    from manuscript_guard.gates.currency import missing_works

    absent = missing_works(entry, usable, held, _bib(project))
    # Round 2 of #499: with a work missing the rules decide nothing, and say no `keep`.
    given = rules_decision(entry, usable, held, _bib(project)) if usable and not absent \
        else None  # fmt: skip
    if given is None:
        lines.append(f"  the rules: {len(usable)} reading(s); they decide from "
                     f"{rules.READINGS}")  # fmt: skip
    else:
        lines.append(f"  the rules give: {given.action}"
                     + (f" {given.candidate}" if given.candidate else "")
                     + f" ({', '.join(given.rules)}): {given.why}")  # fmt: skip
    if absent:
        lines.append(f"  (the works store holds no record of {', '.join(absent)}: the rules "
                     "decide nothing until it does)")  # fmt: skip
    if entry.decision:
        accepted = entry.id in survey(project)[0].accepted
        lines.append(f"  decision: {state_of(entry, held, accepted)}"
                     + (f"; why: {entry.decision['why']}" if entry.decision.get("why")
                        else ""))  # fmt: skip
    if entry.answer and entry.answer.get("why"):
        lines.append(f"  answer: {entry.answer['why']}")
    from manuscript_guard.currency.replies import explained

    lines += explained(project, entry, entry.id in survey(project)[0].accepted)
    return "\n".join(lines)


def _search_line(one: dict) -> str:
    """One search record in a line: its step, source and date, the terms and who wrote them,
    and what came back."""
    step = one["step"] + (f" as {one['as_step']}" if one.get("as_step") else "")
    said = f"  search {one['number']} ({step}, {one['source']}, {one['searched_on']}): "
    said += repr(one["query"]) + (f" by {one['terms_by']}" if one.get("terms_by") else "")
    if one.get("cutoff"):
        said += f", from {one['cutoff']['date']}"
    status = one.get("status", "run")
    if status == "not asked":
        return said + f", not asked: {one['why']}"
    if status == "pending":
        return said + f", {one['hits']} ongoing, pending: {', '.join(one['trials']) or 'none'}"
    return said + (f", {one['hits']} hit(s), candidates: "
                   f"{', '.join(one['candidates']) or 'none'}")  # fmt: skip


def _reading_lines(record: dict) -> list[str]:
    who = record["reader"] + (f" ({record['provenance'].get('model')})"
                              if (record.get("provenance") or {}).get("model") else "")
    lines = [f"  reading {record.get('number')} by {who} on {record['read_on']}: "
             f"{record['hierarchy']}, {record['scale']}"]  # fmt: skip
    cited = record["cited"]
    lines.append(f"    cited {cited['work']}: level {cited['level']['value']} "
                 f"({cited['level']['quote']!r})")  # fmt: skip
    for one in record.get("candidates") or []:
        fields = ", ".join(f"{name} {one[name]['value']} ({one[name]['quote']!r})"
                           for name in records.FIELDS if one.get(name))  # fmt: skip
        lines.append(f"    {one['work']}: {fields}")
    return lines


def mark(project: Project, words: str, citekey: str, by: str | None,
         entry_id: str | None = None, question: str | None = None) -> str:  # fmt: skip
    """Mark the citing sentence of `citekey` that holds `words` as a claim to check: a new
    entry, or, with `entry_id`, an entry put on it again: one unplaced, or placed only on a
    sentence that does not read as it does. With `entry_id`, `citekey` may be the entry's
    work or the candidate it proposes, for a sentence where the author made the change.
    Exactly one sentence must hold the words; more or none is refused."""
    citekey = citekey.removeprefix("@")
    found, report = survey(project)
    if report.failures:
        raise Refused("; ".join(finding.message for finding in report.failures))
    matches = find_sentence(words, citekey, found.sentences)
    if len(matches) != 1:
        where = "; ".join(_where(project, one.path, one.line) for one in matches)
        raise Refused(f"{len(matches)} sentences citing @{citekey} hold those words"
                      + (f" ({where}): give more of them" if matches else ""))  # fmt: skip
    sentence = matches[0]
    _check_mark_by(by)
    document, _report = records.read_document(project)
    document = document or {"schema": records.SCHEMA, "entries": []}
    entries = [dict(raw) for raw in document.get("entries") or []]
    if entry_id is not None:
        return _place_again(project, document, entries, entry_id, citekey, sentence, found,
                            question)  # fmt: skip
    for raw in entries:
        placed = found.placed.get(raw["id"])
        if raw["citekey"] == citekey and placed is not None and placed.text == sentence.text:
            raise Refused(f"the claim is marked already, as {raw['id']}")
    new = {"id": records.next_id(document), "sentence": " ".join(sentence.text.split()),
           "citekey": citekey}  # fmt: skip
    if by:
        new |= {"marked_by": by, "marked_on": date.today().isoformat()}
    if question is not None:
        from manuscript_guard.currency.searching import framed

        new = framed(project, new, question)
    records.write_document(project, {**document, "entries": [*entries, new]})
    records.ensure_gitignore(project)
    return f"marked as {new['id']}: {_where(project, sentence.path, sentence.line)}"


def _check_mark_by(by: str | None) -> None:
    if by is not None and not by.strip():
        raise Refused("--as names the person who marks the claim")


def _place_again(project: Project, document: dict, entries: list[dict], entry_id: str,
                 citekey: str, sentence, found: Survey,
                 question: str | None = None) -> str:  # fmt: skip
    from manuscript_guard.gates.currency import _bib
    from manuscript_guard.literature.passages import statement_words

    for raw in entries:
        if raw["id"] != entry_id:
            continue
        candidate = (raw.get("decision") or {}).get("candidate")
        if raw["citekey"] != citekey and not (
                candidate and records.is_work(_bib(project).get(citekey), candidate)):
            raise Refused(f"{entry_id} is of @{raw['citekey']}, and @{citekey} is not the "
                          "work it proposes")  # fmt: skip
        placed = found.placed.get(entry_id)
        if placed is not None and statement_words(placed.text) == statement_words(
                raw["sentence"]):  # fmt: skip
            raise Refused(f"{entry_id} is placed already: a sentence reads as it does")
        raw["sentence"] = " ".join(sentence.text.split())
        if question is not None:
            from manuscript_guard.currency.searching import framed

            raw.update(framed(project, raw, question))
        records.write_document(project, {**document, "entries": entries})
        return f"{entry_id} placed again: {_where(project, sentence.path, sentence.line)}"
    raise Refused(f"literature/currency.yaml has no entry {entry_id}")


def file_reading(project: Project, path: Path) -> str:
    """Hold a reading to its schema, the hierarchy and its entry, file it once and sealed,
    then run the rules for the entry and write their decision (`by: rules`). A person's
    decision is left as it is, and so is the reading's entry where the rules would change a
    decision somebody answered: nothing is filed then."""
    from manuscript_guard.currency.hierarchy import hierarchies, level_problem
    from manuscript_guard.gates.currency import (
        _bib,
        _fitting,
        _Records,
        missing_works,
        rules_decision,
    )

    try:
        record = read_structured(path)
    except ContractError as exc:
        raise Refused(str(exc)) from exc
    if record is None:
        raise Refused(f"{path}: no such file")
    if isinstance(record, dict):
        record = records.folded_reading(record)
    report = validate(record, "currency-reading", path)
    if not report.ok:
        raise Refused("; ".join(finding.message for finding in report.failures))
    document, raw = _entry_of(project, str(record["entry"]))
    entry = records._entry(raw)
    levels = [record["cited"]["level"]["value"],
              *(one["level"]["value"] for one in record["candidates"])]
    problem = level_problem(hierarchies(project), record["hierarchy"], record["scale"], levels)
    bib = _bib(project)
    _fit, unfit = _fitting([record], entry, hierarchies(project), bib)
    if problem or unfit:
        raise Refused(problem or unfit[0])
    named = [one["work"] for one in record["candidates"]]
    # The cited work under its other identifier is the cited work too (round 3 of #499).
    if len(set(named)) != len(named) or record["cited"]["work"] in named or any(
            records.is_work(bib.get(entry.citekey), work) for work in named):  # fmt: skip
        raise Refused("each candidate is read once, and the cited work is not a candidate")
    held = _Records(project)
    usable = [read.record for read in held.readings.get(entry.id, []) if read.problem is None]
    usable, _unfit = _fitting(usable, entry, hierarchies(project), bib)
    number = 1
    while records.reading_path(project, entry.id, str(record["reader"]), number).exists():
        number += 1
    numbered = {**record, "number": number}
    given = rules_decision(entry, [*usable, numbered], held, bib)
    absent = missing_works(entry, [*usable, numbered], held, bib)
    if absent:
        given = None
    _check_answered(entry, given)
    filed = records.file_reading(project, record, date.today().isoformat())
    records.ensure_gitignore(project)
    said = f"filed {filed.relative_to(project.root).as_posix()}"
    if absent:
        return (f"{said}; the works store holds no record of {', '.join(absent)}, so the "
                "rules decide nothing until it does")  # fmt: skip
    if given is None:
        return f"{said}; the rules decide from {rules.READINGS} readings"
    if entry.decision and entry.decision["by"] != "rules":
        return (f"{said}; the rules give {given.action}, and {entry.decision['by']}'s decision "
                "stands")  # fmt: skip
    decision = {"action": given.action, **({"candidate": given.candidate} if given.candidate
                                           else {}),
                "rules": list(given.rules), "by": "rules",
                "decided_on": date.today().isoformat()}
    entries = [dict(one) for one in document["entries"]]
    for one in entries:
        if one["id"] == entry.id:
            one["decision"] = decision
            if entry.decision and _same(entry.decision, given) and entry.answer:
                one["answer"] = entry.answer
    records.write_document(project, {**document, "entries": entries})
    return (f"{said}; the rules give {given.action}"
            + (f" {given.candidate}" if given.candidate else "")
            + f" ({', '.join(given.rules)}): {given.why}")  # fmt: skip


def _same(decision: dict, given: rules.Decision) -> bool:
    return (decision["action"], decision.get("candidate")) == (given.action, given.candidate)


def _check_answered(entry: records.Entry, given: rules.Decision | None) -> None:
    """Refuse a reading that would take a person's answer from under them: the rules' new
    decision is another proposal than the one answered. An answer from a reply in Word
    refused the proposal its comment showed, rule ids and all (`comments.decision_digest`,
    which G7 holds the reply to), so for it other rule ids are another proposal too."""
    from manuscript_guard.currency.comments import decision_digest

    if given is None or not entry.answer or not entry.decision:
        return
    other = not _same(entry.decision, given) or (
        entry.answer.get("reply") is not None and decision_digest(entry.decision)
        != decision_digest({"action": given.action, "candidate": given.candidate,
                            "rules": list(given.rules)}))  # fmt: skip
    if entry.decision["by"] == "rules" and other:
        raise Refused(
            f"{entry.id}'s proposal was answered ({entry.answer['status']} by "
            f"{entry.answer['by']}), and with this reading the rules give {given.action}"
            + (f" {given.candidate}" if given.candidate else "")
            + f" ({', '.join(given.rules)})"
            + ": the person takes their answer away first, and the reading is filed then"
        )  # fmt: skip


def refuse(project: Project, entry_id: str, why: str, by: str) -> str:
    """Record a person's refusal of an entry's proposed change, with the reason."""
    from manuscript_guard.gates.literature import _MODEL_NAME

    if not why.strip() or not by.strip():
        raise Refused("a refusal names the person (--as) and the reason (--why)")
    if _MODEL_NAME.search(by):
        raise Refused(f"{by!r} cannot answer a proposed change: only a named person does")
    document, raw = _entry_of(project, entry_id)
    decision = raw.get("decision") or {}
    if decision.get("action") not in (rules.REPLACE, rules.ADD):
        raise Refused(f"{entry_id} proposes no change to refuse")
    answer = raw.get("answer")
    if answer:
        raise Refused(f"{entry_id}'s proposal was answered already, {answer['status']} by "
                      f"{answer['by']} on {answer['answered_on']}: only they take their "
                      "answer back")  # fmt: skip
    entries = [dict(one) for one in document["entries"]]
    for one in entries:
        if one["id"] == entry_id:
            one["answer"] = {"status": "refused", "by": by.strip(), "why": why.strip(),
                             "answered_on": date.today().isoformat()}  # fmt: skip
    records.write_document(project, {**document, "entries": entries})
    return f"{entry_id}: {decision['action']} {decision.get('candidate')} refused by {by.strip()}"


__all__ = ["Refused", "Row", "explain", "file_reading", "listing", "mark", "refuse",
           "rendered", "state_of"]
