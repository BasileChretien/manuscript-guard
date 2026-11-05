"""G7: each claim in scope has a decided entry, and each entry is held to its records.

`literature/currency.yaml` says, for a citing sentence and one work it cites, whether the work
is still the one to cite (`currency/`). G7 reads the records only, never a model or the
network:

- `currency-record-missing`: a claim in scope has no entry, or its entry no decision (a note
  while drafting, a warning from internal-review, a failure at submission where paper.yaml
  sets `references.currency: required`). Its message says how far the entry got: no entry,
  marked and not searched, or read fewer times than the rules need.
- `currency-record-stale`: the newest search of an entry is more than six months old (a
  warning, a failure at submission).
- `currency-record-edited`: a search, works or reading record no longer matches its digest,
  or no longer fits its schema.
- `currency-reading-invalid`: a sealed reading names a hierarchy, a scale or a level the
  hierarchy in force does not have, or an entry there is none of.
- `currency-quote-not-found`: a reading's quote is not in the work's stored abstract or text;
  `currency-quote-unchecked` (a note): there was nothing stored to look in.
- `currency-decision-mismatch`: an entry decided by `rules` says other than the rules give
  from its readings and works records.
- `currency-decision-not-human`: a decision's or an answer's `by` names a model.
- `currency-change-unanswered`: a proposed `replace` or `add` that no person has answered (a
  warning, a failure at submission).
- `currency-uncertain`, `currency-entry-unplaced`: notes.
- `currency-candidate-retracted`: a work the decision keeps or proposes is now retracted, by
  its works record.

Where the works store holds no record of a work an entry's readings name, as in a clone,
since git leaves the store out, the rules decide nothing for it and G7 checks no decision of
theirs, and a note says so (`currency-quote-unchecked`). A proposed change counts as accepted
once a sentence matching the entry cites the candidate, by its DOI or PMID in
`references.bib`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts.project import Project
from manuscript_guard.currency import records, rules
from manuscript_guard.currency.records import Entry, Read
from manuscript_guard.currency.survey import Claim, Survey, survey
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.policy import DRAFTING, INTERNAL_REVIEW, SUBMISSION, stage_index

GATE = "G7"
#: How old an entry's newest search may be, in months.
STALE_MONTHS = 6
_PROPOSALS = (rules.REPLACE, rules.ADD)


def today() -> date:
    """Today, as G7 reads it; a test puts another day here."""
    return date.today()


def months_before(day: date, months: int) -> date:
    """The day `months` calendar months before `day`, the last of its month where the month
    is shorter."""
    import calendar

    month = day.month - months
    year = day.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return day.replace(year=year, month=month,
                       day=min(day.day, calendar.monthrange(year, month)[1]))  # fmt: skip


def _finding(code: str, message: str, path: Path, hint: str, severity: str = FAIL,
             line: int | None = None, context: str | None = None) -> Finding:  # fmt: skip
    return Finding(gate=GATE, code=code, message=message, path=path, hint=hint,
                   severity=severity, line=line, context=context)  # fmt: skip


def _shown(text: str) -> str:
    shown = " ".join(text.split())
    return shown if len(shown) <= 140 else shown[:137] + "..."


class _Records:
    """The sealed records of the project, each read once: readings and searches by entry,
    works by id."""

    def __init__(self, project: Project, literature: Any = None) -> None:
        self.project = project
        self._literature = literature
        self.readings: dict[str, list[Read]] = {}
        self.unfiled: list[Read] = []
        for read in records.read_readings(project):
            entry = (read.record or {}).get("entry")
            (self.readings.setdefault(str(entry), []) if entry else self.unfiled).append(read)
        self.searches: dict[str, list[Read]] = {}
        for read in records.read_searches(project):
            entry = (read.record or {}).get("entry")
            (self.searches.setdefault(str(entry), []) if entry else self.unfiled).append(read)
        self._works: dict[str, Read | None] = {}

    def work(self, work: str) -> Read | None:
        if work not in self._works:
            self._works[work] = records.read_work(self.project, work)
        return self._works[work]

    @property
    def literature(self) -> Any:
        """The literature ledger, read once, where the caller did not give it."""
        if self._literature is None:
            from manuscript_guard.contracts.literature import load_literature

            self._literature, _report = load_literature(self.project.path("literature"))
        return self._literature

    def good_work(self, work: str) -> dict | None:
        read = self.work(work)
        return read.record if read is not None and read.problem is None else None


def check_currency(project: Project, stage: str = DRAFTING, literature: Any = None) -> Report:
    """Each claim in scope held to its entry, and each entry to its records. `literature` is
    the ledger `check` read, which K5 reads; without it the ledger is read here."""
    found, report = survey(project)
    held = _Records(project, literature)
    path = records.currency_path(project)
    try:
        from manuscript_guard.currency.hierarchy import hierarchies

        known = hierarchies(project)
    except ContractError as exc:
        known = None
        report = report.with_findings(_finding(
            "currency-reading-invalid", f"the hierarchy of evidence cannot be read: {exc}",
            path, "name a file in the shape of data/evidence_hierarchies.yaml under "
            "`references.hierarchy` in paper.yaml, or take the key away"))  # fmt: skip
    for read in held.unfiled:
        report = report.with_findings(_edited(read))
    bib = _bib(project)
    for entry in found.entries:
        report = report.with_findings(*_of_entry(entry, found, held, known, bib, path, stage))
    report = report.with_findings(*_missing(found, held, project, path, stage))
    decided = [entry for entry in found.entries if entry.decision]
    return report.with_counts(
        currency_entries=len(found.entries),
        currency_claims=len(found.claims),
        currency_by_rules=sum(entry.decision["by"] == "rules" for entry in decided),
        currency_by_person=sum(entry.decision["by"] != "rules" for entry in decided),
    )


def _bib(project: Project) -> dict[str, dict[str, str]]:
    from manuscript_guard.literature.bibfile import read_entries as read_bib

    bib = project.path("literature") / "references.bib"
    return read_bib(bib) if bib.is_file() else {}


def _edited(read: Read) -> Finding:
    return _finding(
        "currency-record-edited", f"{read.path.name}: {read.problem}", read.path,
        "these records are the tool's: put the file back as it was written (git checkout), "
        "or file the reading again with `manuscript-guard references --reading`")  # fmt: skip


def _of_entry(entry: Entry, found: Survey, held: _Records, known, bib: dict,
              path: Path, stage: str) -> list[Finding]:  # fmt: skip
    """What G7 says of one entry."""
    out: list[Finding] = []
    if entry.id not in found.placed:
        out.append(_finding(
            "currency-entry-unplaced", f"{entry.named}: no sentence of the manuscript citing "
            f"@{entry.citekey} reads so", path,
            "mark the sentence as the manuscript now has it with `manuscript-guard references "
            f"--mark \"<words>\" @{entry.citekey} --id {entry.id}`, or remove the entry",
            INFO))  # fmt: skip
    out += _not_human(entry, path)
    readings = held.readings.get(entry.id, [])
    searches = held.searches.get(entry.id, [])
    out += [_edited(read) for read in [*readings, *searches] if read.problem]
    usable = [read.record for read in readings if read.problem is None]
    usable, invalid = _fitting(usable, entry, known, bib)
    out += [_finding("currency-reading-invalid", f"{entry.named}: {why}", path,
                     "file the reading again, on a scale and levels the hierarchy has",
                     ) for why in invalid]  # fmt: skip
    works = sorted({work for record in usable for work, _f, _q in records.quotes_of(record)})
    out += [_edited(read) for work in works
            if (read := held.work(work)) is not None and read.problem]  # fmt: skip
    absent = missing_works(entry, usable, held, bib)
    out += _quotes(entry, usable, held, path, absent)
    out += _decision(entry, usable, held, bib, path, stage, absent,
                     accepted=entry.id in found.accepted)
    out += _stale(entry, searches, path, stage)
    return out


def _not_human(entry: Entry, path: Path) -> list[Finding]:
    from manuscript_guard.gates.literature import _MODEL_NAME

    out = []
    for part in ("decision", "answer"):
        by = str((getattr(entry, part) or {}).get("by") or "")
        # The rules decide; they never answer a proposal, which is a person's to answer.
        if by and (by == "rules" if part == "answer" else by != "rules" and _MODEL_NAME.search(by)):
            out.append(_finding(
                "currency-decision-not-human", f"{entry.named}: {by!r} cannot sign a "
                f"{'decision' if part == 'decision' else 'answer'} on a cited work", path,
                "a model may read the works; the rules decide from the readings, and only a "
                "named person overrules them or answers a proposed change"))  # fmt: skip
    return out


def _fitting(usable: list[dict], entry: Entry, known, bib: dict
             ) -> tuple[list[dict], list[str]]:  # fmt: skip
    """The readings the rules may read, and why each other is not one."""
    from manuscript_guard.currency.hierarchy import level_problem

    fields = bib.get(entry.citekey)
    cited = records.work_id(fields)
    fit, why = [], []
    for record in usable:
        levels = [record["cited"]["level"]["value"],
                  *(one["level"]["value"] for one in record.get("candidates") or [])]
        problem = (level_problem(known, record["hierarchy"], record["scale"], levels)
                   if known is not None else "the hierarchy cannot be read")  # fmt: skip
        if problem is None and cited is not None and not records.is_work(
                fields, record["cited"]["work"]):  # fmt: skip
            problem = (f"the reading is of {record['cited']['work']}, and @{entry.citekey} "
                       f"is {cited}")  # fmt: skip
        if problem is None:
            fit.append(record)
        else:
            why.append(f"{record['reader']}'s reading {record.get('number', '')}: {problem}")
    return fit, why


def _stored_texts(held: _Records, work: str, citekey: str | None, cited: bool) -> list[str]:
    """The texts a quote of `work` is looked for in: its works record's title and abstract,
    and for the cited work its stored copies under literature/sources/."""
    texts = []
    record = held.good_work(work)
    if record is not None:
        texts += [str(record.get(name)) for name in ("title", "abstract") if record.get(name)]
    if cited and citekey:
        from manuscript_guard.literature.sources import (
            UnreadableSource,
            read_source,
            stored_files,
        )

        for stored in stored_files(held.project.path("literature") / "sources", citekey):
            try:
                texts.append(read_source(stored))
            except UnreadableSource:
                continue
    return texts


def quote_in(texts: Iterable[str], quote: str) -> bool:
    """Whether a quote is in one of `texts`, word for word, as a passage is looked for in
    its source (`literature.passages.looked_for`): with words left out marked, each piece in
    order; else whole, as words of its own."""
    from manuscript_guard.gates.quotations import _ELIDED, _SIC, _as_words, quoted_in
    from manuscript_guard.literature.sources import normalise

    whole = normalise(_SIC.sub("", quote)).lower()
    for text in texts:
        if _ELIDED.search(quote):
            if quoted_in(text, quote):
                return True
        elif _as_words(normalise(text).lower(), whole, 0) >= 0:
            return True
    return False


def cited_id(entry: Entry, usable: list[dict], bib: dict) -> str | None:
    """The works store's id of an entry's cited work: as its readings name it, where that
    is the `references.bib` entry's DOI or PMID, else the entry's (`work_id`)."""
    fields = bib.get(entry.citekey)
    named = usable[0]["cited"]["work"] if usable else None
    if named and (fields is None or records.is_work(fields, named)):
        return named
    return records.work_id(fields) or named


def needed_works(entry: Entry, usable: list[dict], bib: dict) -> list[str]:
    """The works the rules need a record of to decide an entry: the cited work and each
    candidate a reading names."""
    cited = cited_id(entry, usable, bib)
    ids = {cited} if cited else set()
    for record in usable:
        ids |= {str(one["work"]) for one in record.get("candidates") or []}
    return sorted(ids)


def missing_works(entry: Entry, usable: list[dict], held: _Records, bib: dict) -> list[str]:
    """The works of `needed_works` the store holds no sound record of: until it does, the
    rules write no decision for the entry, and G7 checks none."""
    return [work for work in needed_works(entry, usable, bib) if held.good_work(work) is None]


def _quotes(entry: Entry, usable: list[dict], held: _Records, path: Path,
            absent: list[str]) -> list[Finding]:  # fmt: skip
    """Each reading's quotes, looked for in what is stored of the work each is of."""
    missing, unchecked = [], 0
    for record in usable:
        cited = record["cited"]["work"]
        for work, name, quote in records.quotes_of(record):
            texts = _stored_texts(held, work, entry.citekey, work == cited)
            if not texts:
                unchecked += 1
            elif not quote_in(texts, quote):
                missing.append(f"{record['reader']} on {name} of {work}: {_shown(quote)!r}")
    out = []
    if missing:
        out.append(_finding(
            "currency-quote-not-found", f"{entry.named}: {len(missing)} quote(s) of a reading "
            f"are not in the work's stored abstract or text: {'; '.join(missing)}", path,
            "a reading quotes each field from the work, word for word; file it again with "
            "the words the work has"))  # fmt: skip
    by_rules = (entry.decision or {}).get("by") == "rules"
    if unchecked or (absent and (usable or by_rules)):
        why = (f"{unchecked} quote(s) of its readings could not be checked: nothing of the "
               "work is stored" if unchecked else "")
        if absent:
            why = (why + "; " if why else "") + (
                f"the works store holds no record of {', '.join(absent)}, so the rules decide "
                "nothing" + (" and their decision was not checked" if by_rules else ""))
        out.append(_finding(
            "currency-quote-unchecked", f"{entry.named}: {why}", path,
            "the works store stays out of git; run `manuscript-guard references` where it is "
            "kept to check them", INFO))  # fmt: skip
    return out


def rules_decision(entry: Entry, usable: list[dict], held: _Records,
                   bib: dict) -> rules.Decision | None:  # fmt: skip
    """What the rules give for an entry from its readings, the works store and the
    literature ledger. K5 reads the entry's own sentence, not the manuscript's, with the
    values the ledger records from the cited work (`quotes_a_number`)."""
    readings = [records.as_reading(record) for record in usable]
    ids = {work for reading in readings for work in reading.candidates}
    works = {work: records.as_work(held.good_work(work)) for work in ids}
    cited_work = cited_id(entry, usable, bib)
    cited = records.as_work(held.good_work(cited_work)) if cited_work else None
    number = quotes_a_number(entry.sentence, entry.citekey, held.literature)
    return rules.decide(cited, works, readings, number=number)


def quotes_a_number(sentence: str, citekey: str, literature: Any) -> bool:
    """Whether a sentence quotes a value the literature ledger records from the work
    `citekey`, for K5 (Basile, 2026-11-04): a binding of one, `{{lit.key}}`, or its display
    written as words of their own. The ledger is read as `number-from-secondary-source`
    reads it (`lookups.values_quoted_from`). A year, another digit, or a binding of another
    work's value does not make it one."""
    import re

    from manuscript_guard.gates.lookups import values_quoted_from
    from manuscript_guard.literature.passages import statement_words
    from manuscript_guard.literature.sources import normalise

    values = values_quoted_from(literature).get(citekey, []) if literature is not None else []
    if not values:
        return False
    words = statement_words(sentence)
    keys = {match.group(1) for match in re.finditer(r"\{\{lit\.([^}]+)\}\}", words)}
    text = normalise(sentence)
    for value in values:
        if value.key in keys:
            return True
        shown = normalise(str(value.display or "")).strip()
        if shown and re.search(r"(?<![\w.])" + re.escape(shown) + r"(?![\w]|\.\d)", text):
            return True
    return False


def _decision(entry: Entry, usable: list[dict], held: _Records, bib: dict, path: Path,
              stage: str, absent: list[str], *, accepted: bool) -> list[Finding]:  # fmt: skip
    decision = entry.decision
    if not decision:
        return []
    out: list[Finding] = []
    action, candidate = decision["action"], decision.get("candidate")
    if decision["by"] == "rules" and not absent:
        given = rules_decision(entry, usable, held, bib)
        if given is None:
            out.append(_finding(
                "currency-decision-mismatch", f"{entry.named}: decided by the rules "
                f"({action}), from {len(usable)} reading(s) the rules can read; they decide "
                f"from {rules.READINGS}", path,
                "file the readings with `manuscript-guard references --reading`, which writes "
                "the rules' decision; or have a person decide, with why"))  # fmt: skip
        elif (given.action, given.candidate, tuple(given.rules)) != (
                action, candidate, tuple(decision["rules"])):  # fmt: skip
            said = f"{given.action}" + (f" {given.candidate}" if given.candidate else "")
            out.append(_finding(
                "currency-decision-mismatch", f"{entry.named}: the entry says {action}"
                + (f" {candidate}" if candidate else "") + f" ({', '.join(decision['rules'])})"
                f", and the rules give {said} ({', '.join(given.rules)}) from its readings",
                path, "the rules' decision is written by `references --reading`; a person who "
                "decides otherwise writes their name and why under `by` and `why`"))  # fmt: skip
    if action == rules.UNCERTAIN:
        out.append(_finding(
            "currency-uncertain", f"{entry.named}: the readings disagree, and nothing is "
            "proposed", path, "read the readings with `manuscript-guard references --explain "
            f"{entry.id}`; a third reading, or a person's decision with why, settles it",
            INFO))  # fmt: skip
    if action in _PROPOSALS and not entry.answer and not accepted:
        out.append(_finding(
            "currency-change-unanswered", f"{entry.named}: {action} {candidate} is proposed "
            f"({', '.join(decision['rules'])}), and nobody has answered", path,
            f"read the proposal with `manuscript-guard references --explain {entry.id}`; "
            "accept it by citing the work in the sentence (add it to Zotero, then "
            f"`manuscript-guard sync-bib`), or refuse it with `references --refuse {entry.id} "
            "--why ... --as <you>`", FAIL if stage == SUBMISSION else WARN))  # fmt: skip
    kept = candidate if action in _PROPOSALS else cited_id(entry, usable, bib)
    record = held.good_work(kept) if kept else None
    if record is not None and (record.get("integrity") or {}).get("retracted"):
        out.append(_finding(
            "currency-candidate-retracted", f"{entry.named}: {kept}, which the decision "
            f"{'proposes' if action in _PROPOSALS else 'keeps'}, is retracted, by its "
            f"works record of {record['fetched_on']}", path,
            "cite other evidence, and decide the entry again"))  # fmt: skip
    return out


def _stale(entry: Entry, searches: list[Read], path: Path, stage: str) -> list[Finding]:
    dates = sorted(str(read.record["searched_on"]) for read in searches
                   if read.problem is None and records.asked(read.record))  # fmt: skip
    if not dates:
        return []
    newest = date.fromisoformat(dates[-1])
    if newest >= months_before(today(), STALE_MONTHS):
        return []
    return [_finding(
        "currency-record-stale", f"{entry.named}: its newest search was run on {newest}, "
        f"more than {STALE_MONTHS} months ago", path,
        "run the searches again and file their readings with `manuscript-guard references "
        f"--reading`; `references --explain {entry.id}` lists the searches it rests on",
        FAIL if stage == SUBMISSION else WARN)]  # fmt: skip


def _missing(found: Survey, held: _Records, project: Project, path: Path,
             stage: str) -> list[Finding]:  # fmt: skip
    """`currency-record-missing` for each claim in scope with no decided entry."""
    required = (project.setting("references") or {}).get("currency") == "required"
    if stage == SUBMISSION and required:
        severity = FAIL
    elif stage_index(stage) >= stage_index(INTERNAL_REVIEW):
        severity = WARN
    else:
        severity = INFO
    out = []
    for claim in found.claims:
        if claim.entry is not None and claim.entry.decision:
            continue
        out.append(_finding(
            "currency-record-missing", _missing_said(claim, held), claim.sentence.path,
            "mark it with `manuscript-guard references --mark \"<words>\" "
            f"@{claim.citekey}`, then file two readings with `references --reading`; or have "
            "a person decide the entry, with why", severity, claim.sentence.line,
            _shown(claim.sentence.text)))  # fmt: skip
    return out


def _missing_said(claim: Claim, held: _Records) -> str:
    facts = f", which {' and '.join(claim.facts)}" if claim.facts else ""
    if claim.entry is None:
        return f"@{claim.citekey}{facts}: no entry in literature/currency.yaml"
    entry = claim.entry
    searched = [read for read in held.searches.get(entry.id, [])
                if read.problem is None and records.asked(read.record)]  # fmt: skip
    read = [one for one in held.readings.get(entry.id, []) if one.problem is None]
    if not searched and not read:
        how = "marked, not searched"
    elif not read:
        how = f"searched ({len(searched)}), not read"
    else:
        how = f"read {len(read)} time(s); the rules decide from {rules.READINGS}"
    return f"{entry.named}{facts}: {how}, and not decided"


def readers_of(project: Project) -> list[str]:
    """For the entries the rules decided, who read them: each reader by name, or by model
    where a reading records its provenance, with "one model, read twice" (or "one reader")
    where one gave every reading of an entry."""
    entries, _report = records.read_entries(project)
    by_rules = {entry.id for entry in entries if (entry.decision or {}).get("by") == "rules"}
    readers: dict[str, list[str]] = {}
    models: set[str] = set()
    for read in records.read_readings(project):
        record = read.record
        if read.problem is None and record and record["entry"] in by_rules:
            model = (record.get("provenance") or {}).get("model")
            if model:
                models.add(str(model))
            readers.setdefault(record["entry"], []).append(str(model or record["reader"]))
    twice = {said[0] for said in readers.values() if len(said) > 1 and len(set(said)) == 1}
    return [name + (f" ({'one model' if name in models else 'one reader'}, read twice)"
                    if name in twice else "")
            for name in sorted({name for said in readers.values() for name in said})]  # fmt: skip


__all__ = ["GATE", "STALE_MONTHS", "check_currency", "months_before", "quote_in",
           "readers_of", "rules_decision", "today"]
