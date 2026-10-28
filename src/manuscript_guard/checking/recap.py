"""The recap of a round of checking, and the table a journal is sent.

`checker recap` writes `checks/recap.md` from the record (`checks/decisions.csv`), the
register of pages (`checks/bundles.csv`) and the items as the project has them now: what the
co-authors asked to change in the manuscript and in the code, what is still open, what they
said about versions of an item that are gone, what each of them checked, and, item by item,
who verified it. `submit` packs the tables of it, without the co-authors' notes, as
`coauthor-verification.md`.

**Tamper-evident by a hash chain, unsigned.** The footer records the digest of the manuscript,
the number of rows of the record and the head of a chain over them, and a root digest of the
tables. The chain starts at h0 = SHA-256 of `manuscript-guard/decisions-chain/1`, and each next
head is the SHA-256 of the previous head, in hex, followed by the canonical JSON of one row of
the record (`chain`). It is computed whenever it is wanted and stored nowhere but in a recap.
`checker recap --check` makes the recap again and names the first line that differs. Held to a
head recorded elsewhere, an earlier recap kept in git or the copy in a submission pack, that
shows a hand edit of any line of the recap but the one naming the earlier recap, which is taken
as the file gives it and not verified, and a row of the record edited, deleted or moved. It
does not show a rewrite of the record and of every copy of the head by someone who can write
to them, and nothing in it is signed.

Nothing in a recap says when it was written: a recap of the same record and the same
manuscript is the same bytes, whenever it is made.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.checking.store import FLAGS, Decision, Standing, decisions_path, status

RECAP = "checks/recap.md"
#: What `submit` calls the publisher's copy in the pack.
PACKED = "coauthor-verification.md"
CHAIN_SEED = "manuscript-guard/decisions-chain/1"
TITLE = "# Co-author checking: recap"
PUBLISHER_TITLE = "# Co-author verification"
FOOTER = "## The record this was made from"
#: The groups counted in a line rather than listed item by item: every author's and every
#: reference's item is asked, and a row each would bury the numbers.
COUNTED = (("reference", "References"), ("author", "Authors"))
#: What a recap says of the protection it gives, and of what it does not.
TAMPER = (
    "**What this record can show.** This recap is tamper-evident by a hash chain, unsigned. Its "
    "last section records the digest of the manuscript, the number of rows of "
    "`checks/decisions.csv` and the head of a hash chain over them, and a root digest of its "
    "tables. `manuscript-guard checker recap --check` makes the recap again from the record and "
    "the manuscript and names the first line that differs. Held to a head recorded elsewhere "
    "(an earlier recap kept in git, the copy in a submission pack, a digest quoted in a "
    "message), that shows a hand edit of any line of this file but the one naming the earlier "
    "recap, which `--check` takes as the file gives it and does not verify, and a row of the "
    "record edited, deleted or moved. It does not show a rewrite of the record and of every "
    "copy of the head by someone who can write to them all, and nothing in it is signed. A "
    "name on a decision is the answers file's claim: the token of the page it came from "
    "shows which page, not who answered."
)
_MANUSCRIPT = re.compile(r"^- Manuscript: document digest `([0-9a-f]{64})`", re.MULTILINE)
_RECORD = re.compile(r"^- Record: `checks/decisions\.csv`, (\d+) row\(s\), chain head "
                     r"`([0-9a-f]{64})`", re.MULTILINE)  # fmt: skip
_EARLIER = re.compile(r"^- Earlier recap: (\d+) row\(s\), chain head `([0-9a-f]{64})`",
                      re.MULTILINE)  # fmt: skip


class RecapError(Exception):
    """The record or a recap could not be read."""


@dataclass(frozen=True)
class Head:
    """How many rows of the record a chain head is the head of, and the head."""

    rows: int
    head: str


@dataclass(frozen=True)
class Recap:
    text: str
    head: Head
    root: str
    #: The decisions that are current and ask for a change, each its maker's latest.
    flags: tuple[Decision, ...]
    earlier: Head | None
    #: Whether the record's first rows still give the earlier recap's head; None with none.
    earlier_holds: bool | None
    #: The head of the record's first n rows, for each n from none (`chain`).
    heads: tuple[str, ...] = ()


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def record_rows(project_root: Path) -> list[dict]:
    """Every row of the record as the CSV reader gives it, each cell under its column, the
    columns of the header line as written, and a cell past the last column under "+"."""
    path = decisions_path(project_root)
    if not path.is_file():
        return []
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle, restkey="+")]
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise RecapError(f"{path} cannot be read: {exc}") from exc


def _lf(value: object) -> object:
    """A cell with its line endings as LF: a checkout that writes CRLF (git's `autocrlf`)
    turns the line break inside a quoted note into CRLF, and the row is the same row."""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(value, list):
        return [_lf(one) for one in value]
    return value


def chain(rows: list[dict]) -> list[str]:
    """The head after each number of rows, from none: `chain(rows)[n]` is the head of the
    first n. h0 is the SHA-256 of `CHAIN_SEED`; each next is the SHA-256 of the head before
    it, in hex, and the row's canonical JSON, each cell's line endings as LF."""
    head = hashlib.sha256(CHAIN_SEED.encode("utf-8")).hexdigest()
    heads = [head]
    for row in rows:
        lf = {key: _lf(value) for key, value in row.items()}
        head = hashlib.sha256((head + canonical(lf)).encode("utf-8")).hexdigest()
        heads.append(head)
    return heads


def open_flags(standing: Standing) -> tuple[Decision, ...]:
    """Each person's current `wrong` or `code`: about the item as it is now, and their latest
    answer on it. Any later answer of theirs on it as it is now takes its place: an ok, or an
    `unsure`, which leaves the item under "Still open"."""
    return tuple(d for d in standing.wrong if d.status in ("wrong", "code"))


def _inline(text: object) -> str:
    return " ".join(str(text or "").split())


#: A run of backslashes before a `|`: each is doubled, and the bar escaped, so a cell that
#: holds `a\|b` neither splits nor loses its backslash.
_BAR = re.compile(r"(\\*)\|")


def _cell(text: object) -> str:
    return _BAR.sub(lambda found: found[1] * 2 + "\\|", _inline(text)) or "—"


def _register(project_root: Path) -> dict:
    """The register of pages, or `RecapError` where it cannot be read: re-saved by a
    spreadsheet in another encoding, or holding a byte the CSV reader refuses."""
    from manuscript_guard.checking.register import read_register, register_path

    try:
        return read_register(project_root)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise RecapError(f"{_shown(register_path(project_root), project_root)} cannot be read: "
                         f"{_relative(exc, project_root)}") from exc


def _shown(path: Path, project_root: Path) -> str:
    """A path as the recap may print it: under the project, relative to it; elsewhere, its
    name alone. A recap holds no absolute path, so it is the same on every machine."""
    try:
        return Path(path).resolve().relative_to(Path(project_root).resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _relative(said: object, project_root: Path) -> str:
    """A message with the project's folder taken out of every path it names."""
    text = str(said)
    root = Path(project_root).resolve()
    forms = {str(root), root.as_posix(), str(project_root), Path(project_root).as_posix()}
    # An OSError gives its file name as Python writes a string, each backslash doubled.
    forms |= {form.replace("\\", "\\\\") for form in forms}
    for form in sorted(forms, key=len, reverse=True):
        for sep in ("\\\\", "\\", "/"):
            text = text.replace(form + sep, "")
    return text


def _found(pattern: re.Pattern[str], text: str) -> Head | None:
    found = pattern.search(text)
    return Head(int(found[1]), found[2]) if found else None


def _footer(text: str) -> str:
    """What follows the last footer heading, where the digests are: nothing a note says,
    since every note is written on a line of its own items."""
    at = text.rfind("\n" + FOOTER + "\n")
    return text[at:] if at >= 0 else ""


def earlier_in(text: str) -> Head | None:
    """The earlier recap a recap names, from its footer."""
    return _found(_EARLIER, _footer(text))


def earlier_for(project) -> Head | None:
    """The earlier recap the next one names: the one in `checks/recap.md`, where its record
    is not the record as it is now, and the one that recap names where it is, so that a recap
    made again of the same record is the same bytes."""
    path = project.root / RECAP
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RecapError(f"{path} cannot be read: {exc}") from exc
    recorded = _found(_RECORD, _footer(text))
    rows = record_rows(project.root)
    if recorded is None:
        return None
    if recorded == Head(len(rows), chain(rows)[-1]):
        return earlier_in(text)
    return recorded


@dataclass(frozen=True)
class _Seen:
    """What the sections are written from."""

    project: object
    items: object
    standing: Standing
    register: dict
    by_id: dict[str, dict]

    def who(self, decision: Decision) -> str:
        from manuscript_guard.checking.people import standing_of

        marks = [] if decision.bundle in self.register else ["claimed"]
        why = standing_of(self.project, decision.by)
        marks += [why] if why else []
        return _inline(decision.by) + (f" ({'; '.join(marks)})" if marks else "")

    def title(self, decision: Decision) -> str:
        """The item as the person saw it: its title now where the answer is about it as it is
        now, and the title recorded with the answer where it is about an earlier version."""
        item = self.by_id.get(decision.id) or {}
        now = item.get("title") if item.get("digest") == decision.digest else None
        return _inline(now or decision.title or item.get("title") or decision.id)

    def ordered(self, decisions) -> list[Decision]:
        """In the order the items are asked, an item gone after them, then by person."""
        place = {identifier: n for n, identifier in enumerate(self.by_id)}
        return sorted(decisions, key=lambda d: (place.get(d.id, len(place)), d.id, d.by))


def make(project, items, *, earlier: Head | None, publisher: bool = False) -> Recap:
    """The recap as the record, the register and the items give it now, naming `earlier`."""
    from manuscript_guard.gates.review import document_digest

    rows = record_rows(project.root)
    heads = chain(rows)
    head = Head(len(rows), heads[-1])
    standing = status(project.root, items)
    seen = _Seen(project, items, standing, _register(project.root),
                 {str(item["id"]): item for item in items.items})  # fmt: skip
    people = _people_rows(seen)
    reconciled, undescribed = _methods_state(project, items)
    table, counted = _item_rows(seen, reconciled)
    manuscript = document_digest(project)
    root = hashlib.sha256(canonical({"people": people, "items": table, "counted": counted,
                                     "manuscript": manuscript, "chain": head.head}
                                    ).encode("utf-8")).hexdigest()  # fmt: skip
    holds = None if earlier is None else (
        earlier.rows <= head.rows and heads[earlier.rows] == earlier.head)  # fmt: skip
    title = str(items.title or "")
    out = [PUBLISHER_TITLE if publisher else TITLE, ""]
    out += [f"Of: {_inline(title)}", ""] if title else []
    out += [TAMPER, ""]
    if not publisher:
        out += _working(seen, undescribed)
    out += _people_section(people) + _item_section(table, counted)
    out += _footer_lines(manuscript, head, earlier, holds, root)
    flags = tuple(seen.ordered(open_flags(standing)))
    return Recap("\n".join(out) + "\n", head, root, flags, earlier, holds, tuple(heads))


# ------------------------------------------------------------------ what is asked of whom


def _sentences(item: dict) -> list[str]:
    said = [f"  - {s.get('section') or 'the manuscript'}"
            + (f":{s['line']}" if s.get("line") else "") + f': "{_inline(s.get("text"))}"'
            for s in item.get("sentences") or []]  # fmt: skip
    return said or ["  - not a sentence of the manuscript"]


def _steps_of(item: dict) -> str:
    return next((str(row[1]) for row in item.get("facts") or []
                 if len(row) > 1 and row[0] == "Steps"), "")  # fmt: skip


def _said(seen: _Seen, decision: Decision) -> str:
    """Who, when and why, each on the line it stands on: a cell of the record may hold a line
    break, and a line of the record's own could otherwise open a line of the recap."""
    return (f"{seen.who(decision)}, {_inline(decision.when)}: "
            f"{_inline(decision.note) or 'no note'}")  # fmt: skip


def _flag_line(seen: _Seen, decision: Decision) -> str:
    return (f"- **{seen.title(decision)}** ({_inline(decision.group) or 'no group'}): "
            f"{_said(seen, decision)}")  # fmt: skip


def _working(seen: _Seen, undescribed: list[str]) -> list[str]:
    """The sections for the authors: each change asked for, with the sentence or the steps,
    what is still open, and what was said of versions that are gone."""
    standing = seen.standing
    out = ["## Changes asked for in the manuscript", ""]
    wrong = seen.ordered(d for d in standing.wrong if d.status == "wrong")
    for decision in wrong:
        out += [_flag_line(seen, decision), *_sentences(seen.by_id.get(decision.id) or {})]
    out += ([] if wrong else ["None."]) + ["", "## Changes asked for in the code", ""]
    code = seen.ordered(d for d in standing.wrong if d.status == "code")
    for decision in code:
        item = seen.by_id.get(decision.id) or {}
        place = (item.get("sentences") or [{}])[0]
        out.append(f"- **{_steps_of(item) or seen.title(decision)}**, at "
                   f"{place.get('section', '?')}:{place.get('line', '?')}: "
                   f"{_said(seen, decision)}")  # fmt: skip
    out += [] if code else ["None."]
    if undescribed:
        out += ["", "Steps of the analysis no Methods text describes:", "", *undescribed]
    out += ["", "## Still open", ""]
    unsure = seen.ordered(d for d in standing.wrong if d.status not in ("wrong", "code"))
    out += [_flag_line(seen, d) for d in unsure]
    for identifier, decisions in standing.disagreements:
        said = "; ".join(f"{seen.who(d)} says {_inline(d.status)}" for d in decisions)
        out.append(f"- disagreement on **{_inline(decisions[0].title or identifier)}**: {said}")
    out += [] if unsure or standing.disagreements else ["None."]
    out += ["", "## Said of a version of an item that is gone", "",
            "Recorded, and counting for nothing: the item changed after the answer, or the "
            "project no longer has it. The notes are kept here.", ""]  # fmt: skip
    gone = seen.ordered((*standing.stale, *standing.earlier, *standing.orphaned))
    out += [f"- [{_inline(d.status)}] {_flag_line(seen, d)[2:]}" for d in gone] or ["None."]
    return [*out, ""]


# ---------------------------------------------------------------------------- the tables


def _people_rows(seen: _Seen) -> list[list[str]]:
    """One row for each author, in the order `authors.yaml` gives, then each other name the
    record holds: their current answers by status, their answers about earlier versions, and
    how many current answers came from no page built for them.

    A name that is no author's is one person by its folded form, as the counts take it, and
    written as the record first spells it: "Jane Doe" and "jane doe" are one row, not two
    each counting both."""
    from manuscript_guard.approvals import authors_of, name_of
    from manuscript_guard.checking.people import fold
    from manuscript_guard.checking.store import read_decisions

    standing = seen.standing
    authors = [name_of(author) for author in authors_of(seen.project)]
    folded = {fold(name) for name in authors}
    answered = {fold(d.by) for d in (*standing.counting, *standing.stale)} - folded
    spelt: dict[str, str] = {}
    for decision in read_decisions(seen.project.root):
        if fold(decision.by) in answered:
            spelt.setdefault(fold(decision.by), decision.by)
    named = [spelt[key] for key in sorted(spelt)]
    rows = []
    for person in [*authors, *named]:
        mine = [d for d in standing.counting if fold(d.by) == fold(person)]
        earlier = [d for d in standing.stale if fold(d.by) == fold(person)]
        counts = [sum(d.status == s for d in mine) for s in ("ok", "wrong", "code", "unsure")]
        claimed = sum(d.bundle not in seen.register for d in mine)
        rows.append([_who_name(seen, person), *map(str, counts), str(len(earlier)),
                     str(claimed)])  # fmt: skip
    return rows


def _who_name(seen: _Seen, person: str) -> str:
    from manuscript_guard.checking.people import standing_of

    why = standing_of(seen.project, person)
    return person + (f" ({why})" if why else "")


def _people_section(rows: list[list[str]]) -> list[str]:
    out = ["## What each co-author checked", "",
           "Each person's answers about the items as they are now, and those about an earlier "
           "version of an item, which count for nothing. Claimed: answers from no page "
           "`checker build` made for them, so the name is the answers file's word.", "",
           "| Co-author | Verified | Text to change | Code to change | Not sure "
           "| About an earlier version | Claimed |",
           "|---|---|---|---|---|---|---|"]  # fmt: skip
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return [*out, ""]


def _item_rows(seen: _Seen, reconciled: dict[str, str]) -> tuple[list[list[str]], list[list[str]]]:
    """A row for each item but the references and the authors, and a count for those."""
    by_item: dict[str, list[Decision]] = {}
    for decision in seen.standing.counting:
        by_item.setdefault(decision.id, []).append(decision)
    stale: dict[str, list[Decision]] = {}
    for decision in seen.standing.stale:
        stale.setdefault(decision.id, []).append(decision)
    counted_groups = dict(COUNTED)
    table: list[list[str]] = []
    counts = {group: [0, 0, 0, 0] for group in counted_groups}
    for item in seen.items.items:
        identifier, group = str(item["id"]), str(item.get("group") or "")
        mine = by_item.get(identifier, [])
        ok = [d for d in mine if d.status == "ok"]
        flagged = [d for d in mine if d.status in FLAGS]
        if group in counted_groups:
            tally = counts[group]
            tally[0] += 1
            tally[1] += bool(ok)
            tally[2] += bool(flagged)
            tally[3] += not mine
            continue
        verified = "; ".join(seen.who(d) for d in ok)
        if str(item.get("already") or "").strip():
            verified = "; ".join(filter(None, (f"before this round: {item['already']}",
                                               verified)))  # fmt: skip
        table.append([
            str(len(table) + 1), group, _inline(item.get("title")), str(item["digest"]),
            verified, "; ".join(f"{seen.who(d)}: {d.status}" for d in flagged),
            "; ".join(seen.who(d) for d in stale.get(identifier, [])),
            reconciled.get(identifier, ""),
        ])  # fmt: skip
    counted = [[name, *map(str, counts[group])] for group, name in COUNTED if counts[group][0]]
    return table, counted


def _item_section(table: list[list[str]], counted: list[list[str]]) -> list[str]:
    out = ["## Verification, item by item", "",
           "Verified by: each person whose answer about the item as it is now is ok. Flagged "
           "by: each whose answer about it as it is now asks for a change or is not sure. "
           "Answered an earlier version: each whose latest answer is about the item before it "
           "changed. Methods: how the claim's pairs stand in `methods.lock`, which records the "
           "author reading each text against its code.", "",
           "| # | Group | Item | Digest | Verified by | Flagged by | Answered an earlier "
           "version | Methods reconciled |",
           "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in table]
    out += [""] if table else ["No item but the references and the authors.", ""]
    for name, total, ok, flagged, none in counted:
        out.append(f"{name}: {total} item(s); {ok} verified by at least one person, {flagged} "
                   f"flagged, {none} not answered about as they are now.")  # fmt: skip
    return [*out, ""] if counted else out


def _footer_lines(manuscript: str, head: Head, earlier: Head | None, holds: bool | None,
                  root: str) -> list[str]:  # fmt: skip
    if earlier is None:
        before = "- Earlier recap: none"
    else:
        verdict = (f"the first {earlier.rows} row(s) of the record still give it" if holds
                   else f"the record now has {head.rows} row(s), fewer than it counted: rows "
                   "were deleted since" if earlier.rows > head.rows
                   else f"the first {earlier.rows} row(s) of the record do not give it: a row "
                   "among them was edited, deleted or moved since")  # fmt: skip
        before = f"- Earlier recap: {earlier.rows} row(s), chain head `{earlier.head}`; {verdict}"
    return [
        FOOTER, "",
        f"- Manuscript: document digest `{manuscript}` (the prose, the results, the ledger and "
        "the references, as `approve` and `build` digest them)",
        f"- Record: `checks/decisions.csv`, {head.rows} row(s), chain head `{head.head}`",
        before,
        f"- Root digest: `{root}` (of the tables, the manuscript's digest and the chain head)",
    ]  # fmt: skip


# ------------------------------------------------------------------------ the Methods


def _methods_state(project, items) -> tuple[dict[str, str], list[str]]:
    """How each methods item's pairs stand in `methods.lock`, by the item's identifier; and a
    line for each step of the analysis no Methods text points at."""
    import yaml

    from manuscript_guard.checking.methods import numbered
    from manuscript_guard.contracts import load_namespace
    from manuscript_guard.contracts._schema import ContractError
    from manuscript_guard.gates.methods import _judged, _locked, anchored, read_lock

    if not any(item.get("group") == "methods" for item in items.items):
        return {}, []
    try:
        claims, _open = anchored(project)
        steps = load_namespace(project)[1].steps
        lock = read_lock(project)
    except (ContractError, yaml.YAMLError, OSError) as exc:
        said = _inline(_relative(exc, project.root))
        return {}, [f"- the Methods could not be read against `methods.lock`: {said}"]
    pairs = _judged(claims, steps, _locked(lock) if isinstance(lock, dict) else [])
    out: dict[str, str] = {}
    for identifier, _section, claim in numbered(claims, project.path("manuscript")):
        said = [_pair_said(pair) for pair in pairs if pair.claim is claim]
        out[identifier] = said[0][1] if len({s[1] for s in said}) == 1 else "; ".join(
            f"{step}: {text}" for step, text in said)  # fmt: skip
    described = {step for claim in claims for step in claim.steps}
    alone = [f"- `{name}`, {step.where}" for name, step in sorted(steps.items())
             if name not in described]  # fmt: skip
    for item in items.items:
        if item.get("group") == "methods" and str(item["id"]) not in out:
            out[str(item["id"])] = "no code is linked"
    return out, alone


def _pair_said(pair) -> tuple[str, str]:
    on = pair.read_on or "an unrecorded day"
    return pair.step, {
        "read": f"on {on}",
        "code": f"code changed since {on}",
        "claim": f"text changed since {on}",
        "unknown": "no such step ran",
    }.get(pair.standing, "never")


# --------------------------------------------------------------------- write and check


def write(project, items) -> Recap:
    """Write `checks/recap.md`, naming the earlier recap as `earlier_for` finds it."""
    made = make(project, items, earlier=earlier_for(project))
    path = project.root / RECAP
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(made.text, encoding="utf-8", newline="\n")
    return made


def check(project, items, path: Path) -> tuple[int, list[str]]:
    """Make again the recap `path` holds, the authors' or the publisher's, naming the earlier
    recap it names, and compare: 0 and what it was made from where they are the same bytes, 1
    and the first line that differs where they are not. Either way it says that the line
    naming the earlier recap was read from the file and not verified: nothing outside the
    file holds it.

    A folder is refused: `--check` takes a recap, and the project is named before it."""
    if path.is_dir():
        raise RecapError(f"{path} is a folder, and --check takes a recap file; name the project "
                         "first and the file after it: `checker recap <project> --check "
                         "[file]`")  # fmt: skip
    if not path.is_file():
        raise RecapError(f"{path} does not exist; `manuscript-guard checker recap` writes one")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RecapError(f"{path} cannot be read: {exc}") from exc
    publisher = text.split("\n", 1)[0] == PUBLISHER_TITLE
    made = make(project, items, earlier=earlier_in(text), publisher=publisher)
    unverified = (f"  the earlier recap's head ({_earlier_said(made.earlier)}) is read from "
                  "this file and not verified: --check takes that line as the file gives it")
    if made.text == text:
        return 0, [f"{path}: the record and the manuscript give it as it is: "
                   f"{made.head.rows} row(s), chain head {made.head.head}, root digest "
                   f"{made.root}", unverified]  # fmt: skip
    old, new = text.split("\n"), made.text.split("\n")
    at = next((n for n, (one, two) in enumerate(zip(old, new, strict=False)) if one != two),
              min(len(old), len(new)))  # fmt: skip
    said = [f"{path}: line {at + 1} differs from what the record and the manuscript give now",
            f"  the file: {old[at] if at < len(old) else '(it ends here)'}",
            f"  now:      {new[at] if at < len(new) else '(it ends here)'}"]  # fmt: skip
    return 1, [*said, *_why(text, made), unverified]


def _earlier_said(earlier: Head | None) -> str:
    return "none" if earlier is None else f"{earlier.rows} row(s), {earlier.head}"


def _why(text: str, made: Recap) -> list[str]:
    """What the footer of `text` says of the difference: the manuscript changed, rows were
    added to the record since, or the rows it was made from are not in the record as they
    were."""
    footer = _footer(text)
    said = []
    digest = _MANUSCRIPT.search(footer)
    if digest and f"`{digest[1]}`" not in made.text:
        said.append("  the manuscript has changed since the recap was made")
    recorded = _found(_RECORD, footer)
    if recorded is None:
        return [*said, "  the file records no chain head, so the record cannot be held to it"]
    if recorded == made.head:
        return said
    if recorded.rows <= made.head.rows and made.heads[recorded.rows] == recorded.head:
        said.append(f"  {made.head.rows - recorded.rows} row(s) were added to the record since; "
                    f"its first {recorded.rows} are those the recap was made from: run "
                    "`manuscript-guard checker recap` again")  # fmt: skip
    else:
        said.append(f"  the first {recorded.rows} row(s) of the record do not give the head the "
                    "recap records: a row among them was edited, deleted or moved since it "
                    "was made")  # fmt: skip
    return said
