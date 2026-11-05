"""Replies in Word to the comments of reference currency, filed as Word kept them, and what a
reader says each one says.

- `import` files each reply to a comment `references --comments` wrote (`replies_in`,
  `file_replies`) under `literature/currency/replies/<id>.<n>.yaml`: the name Word gives its
  author, its date and its words, sealed by `reply_sha256`. It decides nothing.
- A reader, the agent through the `word-roundtrip` skill, a person, or a model, reads the
  reply and records what it says (`assess`): `refuses`, `agrees` or `other`, with the reply's
  own words that say it, once and sealed, beside it (`<id>.<n>.<reader>.yaml`).
- A refusal answers the proposal (`answer.status: refused`, `by` the replier, `why` the
  quote, `answered_on` the reply's date, `reply` and `assessed_by`), where the replier is a
  person of authors.yaml, the proposal is the one the comment showed and nobody has answered
  it, and the manuscript has not accepted it by citing the work: the manuscript wins.
  Agreeing answers nothing: a proposal is accepted by citing the work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from manuscript_guard.contracts._schema import validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.currency import records
from manuscript_guard.currency.records import Entry, Read

REPLY_SCHEMA = "manuscript-guard/currency-reply/1"
ASSESSMENT_SCHEMA = "manuscript-guard/currency-assessment/1"
FOLDER = "replies"
SAYS = ("refuses", "agrees", "other")
_REPLY_NAME = re.compile(r"(c[1-9][0-9]*)\.([1-9][0-9]*)\.yaml")
_ASSESSMENT_NAME = re.compile(r"(c[1-9][0-9]*)\.([1-9][0-9]*)\.([^.]+)\.yaml")


def folder(project: Project) -> Path:
    return records.folder(project) / FOLDER


def reply_path(project: Project, entry: str, number: int) -> Path:
    return folder(project) / f"{entry}.{number}.yaml"


def assessment_path(project: Project, entry: str, number: int, reader: str) -> Path:
    return folder(project) / f"{entry}.{number}.{records.safe_name(reader)}.yaml"


# ------------------------------------------------------------------- reading the records


@dataclass
class Held:
    """The reply and assessment records, each read once: replies by entry and number,
    assessments by entry and reply, and those whose name is not theirs or no longer read."""

    replies: dict[tuple[str, int], Read]
    assessments: dict[tuple[str, int], list[Read]]
    broken: list[Read]

    def of(self, entry: str) -> list[Read]:
        return [read for (one, _n), read in sorted(self.replies.items()) if one == entry]


def held(project: Project) -> Held:
    found = Held({}, {}, [])
    where = folder(project)
    if not where.is_dir():
        return found
    for path in sorted(where.glob("*.yaml")):
        reply = _REPLY_NAME.fullmatch(path.name)
        if reply:
            read = records._sealed(path, "currency-reply", "reply_sha256")
            said = read.record or {}
            if read.problem is None and (str(said.get("entry")), str(said.get("number"))) != (
                    reply[1], reply[2]):  # fmt: skip
                read = Read(path, said, f"its name is not that of {said.get('entry')}'s reply "
                            f"{said.get('number')}", edited=True)  # fmt: skip
            found.replies[(reply[1], int(reply[2]))] = read
            if read.problem:
                found.broken.append(read)
            continue
        assessed = _ASSESSMENT_NAME.fullmatch(path.name)
        read = records._sealed(path, "currency-assessment", "assessment_sha256")
        said = read.record or {}
        if read.problem is None and (assessed is None or (
                str(said.get("entry")), str(said.get("reply")),
                records.safe_name(str(said.get("reader")))) != assessed.groups()):  # fmt: skip
            read = Read(path, said, "its name is not that of the assessment it holds",
                        edited=True)  # fmt: skip
        if read.problem:
            found.broken.append(read)
        elif assessed is not None:
            found.assessments.setdefault((assessed[1], int(assessed[2])), []).append(read)
    return found


def author_named(project: Project, name: str) -> str | None:
    """The author of authors.yaml whose full name is `name`, as authors.yaml writes it, or
    None where no author's is: Word's name for a person is compared with the full name only,
    folded for case and Unicode's composed form."""
    from manuscript_guard.approvals import authors_of, name_of
    from manuscript_guard.checking.people import fold

    wanted = fold(name)
    for author in authors_of(project):
        if wanted and fold(name_of(author)) == wanted:
            return name_of(author)
    return None


def not_a_person(project: Project, name: str) -> str:
    """Why a reply by `name` cannot answer a proposal, or nothing where it can."""
    from manuscript_guard.gates.literature import _MODEL_NAME

    if not name.strip():
        return "Word gives the reply no author's name"
    if _MODEL_NAME.search(name):
        return f"{name!r} is a model's name, and only a person answers a proposed change"
    if author_named(project, name) is None:
        return f"{name!r} is no person of authors.yaml"
    return ""


# ------------------------------------------------------------------------ filing at import


@dataclass(frozen=True)
class Found:
    """A reply in a returned document to one of its currency comments."""

    offered: dict
    by: str
    date: str
    text: str


def replies_in(document: Path, offered: list[dict]) -> list[Found]:
    """Each reply Word records to a comment the document's list of proposals names: the
    comment known by its author and the digest of its words (`tracked.currency_offered_of`).
    A comment deleted, or resolved with no reply, gives nothing."""
    from manuscript_guard import tracked
    from manuscript_guard.suggestions import short_digest

    comments, parents = tracked.comments_of(document)
    out = []
    for entry in offered:
        for comment in comments:
            if comment.author != entry["author"] or short_digest(comment.text) != entry["written"]:
                continue
            for reply in tracked.replies_to(comment, comments, parents):
                found = Found(entry, reply.author, reply.date[:10], reply.text)
                if found not in out:
                    out.append(found)
    return out


def file_replies(project: Project, document: Path, found: list[Found], *,
                 applying: bool) -> list[str]:  # fmt: skip
    """File each reply as it came back, once: a reply filed already, by its author, date,
    words and comment, is not filed again. Without `applying` nothing is written, and what
    would be is said."""
    filed = held(project)
    taken = {(read.record["entry"], read.record["by"], read.record["date"], read.record["text"],
              read.record["comment"]): read.path.name
             for read in filed.replies.values() if read.record and read.problem is None}
    numbers: dict[str, int] = {}
    said = []
    today = date.today().isoformat()
    for one in found:
        entry = one.offered["entry"]
        key = (entry, one.by, one.date, one.text, one.offered["written"])
        who = one.by or "an unnamed author"
        if key in taken:
            said.append(f"{entry}: the reply by {who} is filed already, as {taken[key]}")
            continue
        number = numbers.get(entry) or 1
        while (entry, number) in filed.replies or reply_path(project, entry, number).exists():
            number += 1
        numbers[entry] = number + 1
        record = {"schema": REPLY_SCHEMA, "entry": entry, "number": number, "by": one.by,
                  "date": one.date, "text": one.text, "comment": one.offered["written"],
                  "decision": one.offered["decision"], "written_on": one.offered["date"],
                  "document": document.name, "filed_on": today}  # fmt: skip
        record["reply_sha256"] = records.sealed_digest(record, "reply_sha256")
        path = reply_path(project, entry, number)
        name = path.relative_to(project.root).as_posix()
        if not applying:
            said.append(f"{entry}: a reply by {who}, to be filed as {name}; --apply files it")
            continue
        _write(path, record, "currency-reply", "Filed by `manuscript-guard import`, as Word "
               "kept the reply. Sealed by `reply_sha256`.")  # fmt: skip
        taken[key] = path.name
        said.append(f"{entry}: a reply by {who}, filed as {name}")
    return said


def _write(path: Path, record: dict, schema: str, header: str) -> None:
    report = validate(record, schema, path)
    if not report.ok:
        problems = "; ".join(finding.message for finding in report.failures)
        from manuscript_guard.contracts import ContractError

        raise ContractError(f"{path.name} would not be valid: {problems}")
    text = f"# {header}\n" + yaml.safe_dump(record, sort_keys=False, allow_unicode=True,
                                             width=100)  # fmt: skip
    records._write_new(path, text)


# ------------------------------------------------------------------------------ assessing


def changed(entry: Entry, reply: dict) -> str:
    """Why a reply can no longer answer its entry's proposal, or nothing where it can: the
    proposal changed since the comment was written, or somebody answered it meanwhile."""
    from manuscript_guard.currency.comments import decision_digest, is_proposal

    if not is_proposal(entry) or decision_digest(entry.decision) != reply["decision"]:
        return "the proposal changed since the document was written"
    answer = entry.answer
    if answer:
        if answer.get("reply") == reply["number"]:
            return ""
        return (f"the proposal was answered already, {answer['status']} by {answer['by']} on "
                f"{answer['answered_on']}: only they take their answer back")  # fmt: skip
    return ""


def assess(project: Project, entry_id: str, number: int, says: str, quote: str,
           reader: str) -> str:  # fmt: skip
    """Record what reply `number` to entry `entry_id`'s comment says, once and sealed, with
    the reply's words that say it; and where it refuses, the entry's answer. A refusal by
    nobody authors.yaml names, or a model, is refused, and nothing is written."""
    from manuscript_guard.currency.command import Refused, _entry_of
    from manuscript_guard.currency.survey import survey
    from manuscript_guard.gates.currency import quote_in

    if says not in SAYS:
        raise Refused(f"--says is one of {', '.join(SAYS)}")
    reader = reader.strip()
    if not reader:
        raise Refused("--as names who read the reply")
    if not quote.strip():
        raise Refused("--quote gives the reply's words that say it")
    document, raw = _entry_of(project, entry_id)
    entry = records._entry(raw)
    read = held(project).replies.get((entry_id, number))
    if read is None:
        raise Refused(f"{entry_id} has no reply {number} filed: `import` files the replies")
    if read.problem:
        raise Refused(f"{read.path.name}: {read.problem}")
    reply = read.record
    if not quote_in([str(reply["text"])], quote):
        raise Refused(f"the quote is not in reply {number}, word for word")
    path = assessment_path(project, entry_id, number, reader)
    if path.exists():
        raise Refused(f"{reader} assessed reply {number} of {entry_id} already: an assessment "
                      "is written once")  # fmt: skip
    answer, why = None, ""
    if says == "refuses":
        problem = not_a_person(project, str(reply["by"]))
        if problem:
            raise Refused(f"reply {number} of {entry_id} cannot answer the proposal: {problem}. "
                          "Nothing is written; the person may refuse it with `references "
                          f"--refuse {entry_id} --why ... --as <them>`")  # fmt: skip
        why = changed(entry, reply)
        if not why and entry.answer:
            why = (f"the proposal was answered already, by this reply, assessed by "
                   f"{entry.answer.get('assessed_by')}")  # fmt: skip
        if not why and entry.id in survey(project)[0].accepted:
            why = ("the sentence cites the work it proposes, so the proposal counts as "
                   "accepted: the reply is listed beside it for the authors to settle")
        if not why:
            answer = {"status": "refused", "by": author_named(project, str(reply["by"])),
                      "why": " ".join(quote.split()),
                      "answered_on": reply["date"] or reply["filed_on"], "reply": number,
                      "assessed_by": reader}  # fmt: skip
    record = {"schema": ASSESSMENT_SCHEMA, "entry": entry_id, "reply": number,
              "reader": reader, "says": says, "quote": " ".join(quote.split()),
              "assessed_on": date.today().isoformat(),
              "reply_sha256": reply["reply_sha256"]}  # fmt: skip
    record["assessment_sha256"] = records.sealed_digest(record, "assessment_sha256")
    _write(path, record, "currency-assessment", "Written by `manuscript-guard references "
           "--assess`, once. Sealed by `assessment_sha256`.")  # fmt: skip
    filed = path.relative_to(project.root).as_posix()
    if answer is not None:
        entries = [dict(one) for one in document["entries"]]
        for one in entries:
            if one["id"] == entry_id:
                one["answer"] = answer
        records.write_document(project, {**document, "entries": entries})
        return (f"filed {filed}; {entry_id}: {entry.decision['action']} "
                f"{entry.decision.get('candidate')} refused by {answer['by']}, by reply {number}")
    if why:
        return f"filed {filed}; no answer is written: {why}"
    if says == "agrees":
        return (f"filed {filed}; {entry_id} agreed in Word, not yet cited: it is accepted once "
                "the sentence cites the work")  # fmt: skip
    return f"filed {filed}; the reply is listed for the authors"


# ------------------------------------------------------------------------- what is shown


def said_of(project: Project, entry: Entry, found: Held, accepted: bool) -> list[str]:
    """A line for each reply filed to `entry`'s comment: who, when, and what became of it."""
    out = []
    for read in found.of(entry.id):
        if read.problem or not read.record:
            continue
        reply = read.record
        number = reply["number"]
        who = _printable(str(reply["by"])).replace("\n", " ") or "an unnamed author"
        head = f"reply {number} by {who} ({reply['date'] or '?'})"
        assessed = [one.record for one in found.assessments.get((entry.id, number), [])]
        notes = [_assessed(entry, number, one, accepted) for one in assessed] or [
            f"not assessed: `references --assess {entry.id} --reply {number} --says "
            "refuses|agrees|other --quote \"...\" --as <you>`"]  # fmt: skip
        why = changed(entry, reply)
        if why:
            notes.append(why)
        problem = not_a_person(project, str(reply["by"]))
        if problem:
            notes.append(f"{problem}, so a refusal in it cannot answer the proposal")
        out.append(f"{head}: " + "; ".join(notes))
    return out


def _assessed(entry: Entry, number: int, one: dict, accepted: bool) -> str:
    by = one["reader"]
    if one["says"] == "agrees":
        return f"agreed in Word ({by}), " + ("and cited" if accepted else "not yet cited")
    if one["says"] == "other":
        return f"says something else ({by}): read it with `references --explain {entry.id}`"
    if (entry.answer or {}).get("reply") == number:
        return f"refuses ({by}): it is the entry's answer"
    if accepted:
        return (f"refuses ({by}), and the sentence cites the work: accepted; the authors "
                "settle it")  # fmt: skip
    return f"refuses ({by})"


def explained(project: Project, entry: Entry, accepted: bool) -> list[str]:
    """What `--explain` says of the replies: each one's words, quoted, and its assessments."""
    found = held(project)
    lines = []
    for line, read in zip(said_of(project, entry, found, accepted),
                          [one for one in found.of(entry.id) if not one.problem], strict=True):
        lines.append(f"  {line}")
        text = str(read.record["text"]) or "(no words)"
        lines += [f"      > {part}" for part in _printable(text).split("\n")]
        for one in found.assessments.get((entry.id, read.record["number"]), []):
            lines.append(f"    assessed by {one.record['reader']} on "
                         f"{one.record['assessed_on']}: {one.record['says']}, "
                         f"\N{LEFT DOUBLE QUOTATION MARK}{_printable(one.record['quote'])}"
                         "\N{RIGHT DOUBLE QUOTATION MARK}")  # fmt: skip
    return lines


def _printable(text: str) -> str:
    return "".join(char if char == "\n" or char.isprintable() else "?" for char in text)


__all__ = ["ASSESSMENT_SCHEMA", "REPLY_SCHEMA", "SAYS", "Found", "Held", "assess",
           "assessment_path", "author_named", "changed", "explained", "file_replies", "folder",
           "held", "not_a_person", "replies_in", "reply_path", "said_of"]
