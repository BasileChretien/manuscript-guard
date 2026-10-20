"""A co-author's Word comments, filed as findings the author answers.

A comment is the most useful thing in a returned document, and `import` used to print it
and keep nothing: "Record them in a review file" was the reader's job, and a comment nobody
transcribed was lost to every check. So each comment is filed, as a finding in a record of
its own kind, and G11 reports it until the author answers it (`gates/comments.py`).

**One record per commenter per document built.** `review/comments/<document>-<build>/
<commenter>.yaml`: the document is the paper or its supplement, the build is the start of
the source stamp the returned document carries, and the commenter is the comment's Word
author, a label and not an identity, known by the letters and digits of its name as a
reader of a panel is (`reading_slug`). The record is outside every panel round: a
co-author's notes neither complete a round nor make one stale.

**What is filed is the comment as written**: its words, its date, its replies, what it was
made on (the words its range covers, the kind of block, the paragraph's identifier where the
import vouches for it, and a digest of that paragraph's source), and whether its thread was
resolved in Word. Its words are data: stored as they are, shown through `text.shown`, and
never read as an instruction. Its severity starts as `comment` and is the author's to change.

**Nothing is filed twice.** A comment is known again by the id Word keeps through a save
(`w16cid:durableId`), else by its paragraph's `w14:paraId`, else by its author, date and
words. Not by `w:id`: Word renumbers that each time it saves (verified in Word 16 on
2026-10-20), so a copy the co-author saved again, with one comment added above another,
would have filed the other a second time. A later copy can add replies to a comment filed
already, and mark its thread resolved; those are added to it.

**The record is sealed** (`words_sha256`): the commenter, the document and the build, and
each finding's words, place and replies. Severity and the answers are the author's and stay
out of it, as they do of a reading's seal. A record changed by hand so that a comment no
longer says what was filed, or is gone, is reported by G11, and `import` adds nothing to it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.gates.review import reading_slug, review_root

SCHEMA = "manuscript-guard/comments/1"
COMMENTS_DIR = "comments"
DEFAULT_SEVERITY = "comment"
#: How much of the words a comment was made on is kept: enough to find them in the paper.
ANCHOR_KEPT = 300
#: Who a comment with no author in Word is filed as.
UNNAMED = "an unnamed commenter"
MANUSCRIPT, SUPPLEMENTARY = "manuscript", "supplementary"

#: The kind of block a comment was made on, by the role `docxtext` reads from its style.
_BLOCKS = {"heading": "heading", "caption": "caption", "reference": "reference list",
       "list": "list item", "quote": "quotation"}  # fmt: skip
#: What a comment was made on, where "on a <block>" does not read.
_MADE_ON = {"text": "on text", "reference list": "on the reference list"}
#: A finding's fields that are the commenter's, and sealed. The author answers in the others.
WORDS = ("id", "key", "date", "block", "where", "paragraph_sha256", "unmatched", "anchored",
         "resolved_in_word", "finding", "replies")  # fmt: skip
#: The order a finding's fields are written in.
_ORDER = ("id", "key", "severity", *WORDS[2:], "resolution", "resolved_on", "overridden",
          "overridden_by")  # fmt: skip


class FilingError(Exception):
    """The comments could not be read from the document."""


@dataclass(frozen=True)
class Reply:
    by: str
    date: str
    text: str

    def as_dict(self) -> dict:
        return {"by": self.by, "date": self.date, "text": self.text}


@dataclass(frozen=True)
class Thread:
    """One comment and the replies to it, as `import` files them."""

    key: str
    author: str
    date: str
    text: str
    #: The kind of block its range starts in: "paragraph", "heading", "caption", "table"...
    block: str
    #: The words its range covers, cut at `ANCHOR_KEPT`.
    anchored: str
    #: The identifier of the paragraph it was made on, as the source names it now, where the
    #: import vouches that the identifier still names the text it named at the build.
    where: str = ""
    #: The SHA-256 of that paragraph's source, so G11 can say when it has changed since.
    paragraph_sha256: str = ""
    #: Made on a paragraph whose identifier the import cannot vouch for: the source changed
    #: there since the build, or the document numbers paragraphs by other rules.
    unmatched: bool = False
    resolved: bool = False
    replies: tuple[Reply, ...] = ()

    @property
    def commenter(self) -> str:
        return self.author or UNNAMED

    def finding(self, identifier: str) -> dict:
        found = {"id": identifier, "key": self.key, "severity": DEFAULT_SEVERITY}
        if self.date:
            found["date"] = self.date
        found["block"] = self.block
        if self.where:
            found["where"] = self.where
            found["paragraph_sha256"] = self.paragraph_sha256
        if self.unmatched:
            found["unmatched"] = True
        found["anchored"] = self.anchored
        if self.resolved:
            found["resolved_in_word"] = True
        found["finding"] = self.text
        if self.replies:
            found["replies"] = [reply.as_dict() for reply in self.replies]
        return found


def _key(comment) -> str:
    if comment.durable:
        return f"durable:{comment.durable}"
    if comment.paragraphs:
        return f"para:{comment.paragraphs[-1]}"
    said = json.dumps([comment.author, comment.date, comment.text], ensure_ascii=False)
    return f"text:{hashlib.sha256(said.encode('utf-8')).hexdigest()[:16]}"


def _block(paragraph) -> str:
    if paragraph is None:
        return "text"
    if paragraph.table:
        return "table"
    if paragraph.role in _BLOCKS:
        return _BLOCKS[paragraph.role]
    return "paragraph" if paragraph.names else "text"


def threads_of(
    document: Path,
    *,
    vouched: dict[str, str],
    sources: dict[str, str],
    panel: Sequence[dict] = (),
) -> list[Thread]:
    """The comment threads in a returned document, in the order Word keeps them.

    `vouched` maps each identifier the document carries that the import vouches for to the
    identifier its paragraph has now (`roundtrip.named_now`); `sources` holds the source
    text of each paragraph by the identifier it has now. A comment a review panel wrote
    with its suggested edits is not a co-author's, and neither is its thread: `panel` is
    the document's record of them (`tracked.offered_of`), and the comment is known as
    `suggestions.decisions` knows it, by its author and the digest of its words. Known
    by words alone, a co-author's "Agreed." in a thread of their own was dropped with
    the one they wrote under the panel's comment.

    A comment with no words, a picture alone or an empty comment, is filed too: it is a
    co-author's all the same, and its place says what it is about.
    """
    from manuscript_guard.docxtext import (
        DocumentUnreadable,
        comment_ranges,
        paragraphs_of,
        word_comments,
    )

    try:
        comments = word_comments(document)
        if not comments:
            return []
        ranges = comment_ranges(document)
        paragraphs = paragraphs_of(document)
    except DocumentUnreadable as exc:
        raise FilingError(f"{document.name} is not a readable .docx: {exc}") from exc
    from manuscript_guard.suggestions import short_digest

    ours = {(entry["author"], entry["comment"]) for entry in panel}
    starts = {}
    for paragraph in paragraphs:
        for ident in paragraph.comments:
            starts.setdefault(ident, paragraph)
    by_paragraph = {p: c for c in comments for p in c.paragraphs}

    def root_of(comment):
        seen = set()
        while comment.parent and comment.parent in by_paragraph and id(comment) not in seen:
            seen.add(id(comment))
            comment = by_paragraph[comment.parent]
        return comment

    replies: dict[int, list] = {}
    for comment in comments:
        root = root_of(comment)
        if root is not comment:
            replies.setdefault(id(root), []).append(comment)

    out = []
    for comment in comments:
        if root_of(comment) is not comment:
            continue
        if (comment.author, short_digest(comment.text)) in ours:
            continue
        answers = tuple(
            Reply(r.author or UNNAMED, r.date[:10], r.text) for r in replies.get(id(comment), ())
        )
        paragraph = starts.get(comment.identifier)
        block = _block(paragraph)
        named = paragraph.names[0] if block == "paragraph" else ""
        where = vouched.get(named, "")
        source = sources.get(where)
        anchored = ranges.get(comment.identifier, "")
        if len(anchored) > ANCHOR_KEPT:
            anchored = anchored[:ANCHOR_KEPT] + " [...]"
        out.append(
            Thread(
                key=_key(comment),
                author=comment.author,
                date=comment.date[:10],
                text=comment.text,
                block=block,
                anchored=anchored,
                where=where if source is not None else "",
                paragraph_sha256=_digest(source) if source is not None else "",
                unmatched=bool(named) and source is None,
                resolved=comment.done,
                replies=answers,
            )
        )
    return out


def made_on(block: str) -> str:
    """What a comment was made on, as `import` and G11 say it: \"on a heading\"."""
    return _MADE_ON.get(block, f"on a {block}")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def comments_root(project) -> Path:
    return review_root(project) / COMMENTS_DIR


def record_path(project, stamp: str, supplementary: bool, commenter: str) -> Path:
    document = SUPPLEMENTARY if supplementary else MANUSCRIPT
    slug = reading_slug(commenter) or "unnamed"
    return comments_root(project) / f"{document}-{stamp[:12]}" / f"{slug}.yaml"


def records(project) -> list[Path]:
    """Every comments record, in a stable order."""
    root = comments_root(project)
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*/*.yaml") if path.is_file())


def words_digest(document: dict) -> str:
    """SHA-256 of what the commenter wrote, as `words_sha256` holds it: who, on which
    document of which build, and each finding's `WORDS`, in their order. Serialised as a
    reading's seal is (`gates.review.reading_digest`)."""
    core = {
        "commenter": document.get("commenter"),
        "document": document.get("document"),
        "built_from": document.get("built_from"),
        "findings": [
            {field: finding.get(field) for field in WORDS if field in finding}
            for finding in document.get("findings") or []
            if isinstance(finding, dict)
        ],
    }
    canonical = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Filing:
    """What one import files for one commenter, or why it files nothing."""

    path: Path
    commenter: str
    #: The ids of the findings this import adds, and of those it adds replies or Word's
    #: "resolved" to.
    added: tuple[str, ...] = ()
    extended: tuple[str, ...] = ()
    #: Threads filed already, as they are, and threads whose words differ from those filed
    #: under the same comment: the record keeps what was filed first.
    kept: int = 0
    reworded: tuple[str, ...] = ()
    #: The record to write, or None when nothing changes.
    document: dict | None = None
    #: Why nothing is filed for this commenter.
    refused: str = ""


def plan_filing(
    project,
    threads: Sequence[Thread],
    *,
    stamp: str,
    printed: str | None,
    supplementary: bool,
    today: str,
) -> list[Filing]:
    """What filing `threads` would do to the records, one `Filing` per commenter. Nothing
    is written: `write_filing` writes one."""
    grouped: dict[Path, list[Thread]] = {}
    for thread in threads:
        path = record_path(project, stamp, supplementary, thread.commenter)
        grouped.setdefault(path, []).append(thread)
    return [
        _plan_one(
            path, group, stamp=stamp, printed=printed, supplementary=supplementary, today=today
        )  # fmt: skip
        for path, group in grouped.items()
    ]


def _plan_one(
    path: Path,
    threads: list[Thread],
    *,
    stamp: str,
    printed: str | None,
    supplementary: bool,
    today: str,
) -> Filing:
    commenter = threads[0].commenter
    document_kind = SUPPLEMENTARY if supplementary else MANUSCRIPT
    if not path.exists():
        document = {
            "schema": SCHEMA,
            "commenter": commenter,
            "document": document_kind,
            "built_from": stamp,
            **({"printed": printed} if printed else {}),
            "filed_on": today,
            "findings": [t.finding(f"c{n}") for n, t in enumerate(threads, start=1)],
        }
        document = _sealed(document)
        added = tuple(f["id"] for f in document["findings"])
        return Filing(path, commenter, added=added, document=document)

    existing, why = _readable(path)
    if existing is None:
        return Filing(path, commenter, refused=why)
    if (
        existing.get("built_from") != stamp
        or existing.get("document") != document_kind
        or reading_slug(str(existing.get("commenter"))) != reading_slug(commenter)
    ):
        return Filing(
            path, commenter,
            refused="it says it holds the comments of another commenter, document or build; "
            "file it where it belongs, or move it out of review/comments/",
        )  # fmt: skip
    findings = [dict(f) for f in existing["findings"]]
    by_key = {f["key"]: f for f in findings}
    used = [int(f["id"][1:]) for f in findings if f["id"][1:].isdigit()]
    next_id = max(used, default=0) + 1
    added, extended, reworded, kept = [], [], [], 0
    for thread in threads:
        filed = by_key.get(thread.key)
        if filed is None:
            finding = thread.finding(f"c{next_id}")
            next_id += 1
            findings.append(finding)
            by_key[thread.key] = finding
            added.append(finding["id"])
            continue
        if filed["finding"] != thread.text:
            reworded.append(filed["id"])
        known = list(filed.get("replies") or [])
        new = [r.as_dict() for r in thread.replies if r.as_dict() not in known]
        grown = bool(new) or (thread.resolved and not filed.get("resolved_in_word"))
        if not grown:
            kept += 1
            continue
        if new:
            filed["replies"] = known + new
        if thread.resolved:
            # Kept once seen: another copy, saved before the thread was resolved, does not
            # unresolve it.
            filed["resolved_in_word"] = True
        extended.append(filed["id"])
    if not added and not extended:
        return Filing(path, commenter, kept=kept, reworded=tuple(reworded))
    document = _sealed({**existing, "findings": [_ordered(f) for f in findings]})
    return Filing(
        path, commenter, added=tuple(added), extended=tuple(extended), kept=kept,
        reworded=tuple(reworded), document=document,
    )  # fmt: skip


def _ordered(finding: dict) -> dict:
    """A finding's fields in the order they are written, any others after them."""
    return {key: finding[key] for key in _ORDER if key in finding} | {
        key: value for key, value in finding.items() if key not in _ORDER
    }


def _sealed(document: dict) -> dict:
    body = {key: value for key, value in document.items() if key != "words_sha256"}
    findings = body.pop("findings")
    return {**body, "words_sha256": words_digest(document), "findings": findings}


def _readable(path: Path) -> tuple[dict | None, str]:
    """The record at `path` as import may add to it, or None and why not."""
    try:
        document = read_structured(path)
    except (ContractError, OSError, ValueError, RecursionError):
        return None, "it cannot be read as a comments record; put it right, then import again"
    if not validate(document, "comments", path, gate="G11").ok or not isinstance(document, dict):
        return None, "it does not fit the comments schema; `manuscript-guard check` says where"
    if words_digest(document) != document.get("words_sha256"):
        return None, (
            "what it says a commenter wrote has changed since it was filed, and adding to it "
            "would seal the change; put it back as it was (`git diff` shows what changed)"
        )
    if _holds_comment(path.read_text(encoding="utf-8")):
        return None, (
            "it holds a YAML comment (`# ...`), which writing the record again would drop; "
            "move the note into `resolution` or `overridden`, then import again"
        )
    return document, ""


def _holds_comment(text: str) -> bool:
    """Whether the YAML holds a comment: a `#` outside every scalar, its quotes included."""
    import yaml

    spans: list[tuple[int, int]] = []

    def walk(node) -> None:
        if isinstance(node, yaml.ScalarNode):
            spans.append((node.start_mark.index, node.end_mark.index))
        elif isinstance(node, yaml.SequenceNode):
            for child in node.value:
                walk(child)
        elif isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                walk(key)
                walk(value)

    walk(yaml.compose(text))
    spans.sort()
    at = 0
    for start, end in [*spans, (len(text), len(text))]:
        if "#" in text[at:start]:
            return True
        at = max(at, end)
    return False


def write_filing(filing: Filing) -> None:
    """Write the record `filing` holds, and read it back: it must say exactly that."""
    import yaml

    if filing.document is None:
        return
    # Checked as G11 will read it: a record that does not fit its schema is counted by
    # nothing, its unanswered comments included, and import would add nothing to it.
    checked = validate(filing.document, "comments", filing.path, gate="G11")
    if not checked.ok:
        said = "; ".join(finding.message for finding in checked.failures)
        raise FilingError(f"{filing.path.name} would not fit its schema ({said}); nothing written")
    text = yaml.safe_dump(filing.document, sort_keys=False, allow_unicode=True, width=88)
    if yaml.safe_load(text) != filing.document:
        raise FilingError(f"{filing.path.name} would not read back as written; nothing written")
    filing.path.parent.mkdir(parents=True, exist_ok=True)
    filing.path.write_bytes(text.encode("utf-8"))


def seeded(project) -> dict[tuple[str, str], int]:
    """The points of every revision round, by the slug `respond --open --from` gives their
    reviewer and their words with layout spaces folded, each with its round: a journal
    reviewer's comment seeded there is answered in the response, not filed again here."""
    from manuscript_guard.gates.revision import rounds

    found: dict[tuple[str, str], int] = {}
    for number, path in rounds(project):
        try:
            document = read_structured(path)
        except (ContractError, OSError, ValueError, RecursionError):
            continue
        reviewers = document.get("reviewers") if isinstance(document, dict) else None
        for reviewer in reviewers if isinstance(reviewers, list) else []:
            points = reviewer.get("points") if isinstance(reviewer, dict) else None
            for point in points if isinstance(points, list) else []:
                if isinstance(point, dict) and isinstance(point.get("comment"), str):
                    words = " ".join(point["comment"].split())
                    found.setdefault((str(reviewer.get("id")), words), number)
    return found


def seeded_slug(author: str) -> str:
    """The reviewer id `respond --open --from` gives a comment's author."""
    import re

    return re.sub(r"[^a-z0-9]+", "-", author.lower()).strip("-") or "reviewer"


def not_seeded(
    threads: Sequence[Thread], points: dict[tuple[str, str], int]
) -> tuple[list[Thread], list[tuple[Thread, int]]]:
    """`threads` less those a revision round holds as a point already, and those, with
    their round."""
    kept, there = [], []
    for thread in threads:
        number = points.get((seeded_slug(thread.author or ""), " ".join(thread.text.split())))
        if number is None:
            kept.append(thread)
        else:
            there.append((thread, number))
    return kept, there


__all__ = [
    "DEFAULT_SEVERITY",
    "SCHEMA",
    "Filing",
    "FilingError",
    "Reply",
    "Thread",
    "comments_root",
    "not_seeded",
    "plan_filing",
    "record_path",
    "records",
    "seeded",
    "threads_of",
    "words_digest",
    "write_filing",
]
