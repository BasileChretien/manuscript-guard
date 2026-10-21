"""The edits a review panel's readings suggest, placed in the manuscript or dropped.

A finding may carry `edits`: the manuscript's words as they stand (`old`) and the words to
put in their place (`new`). `review --suggestions --round N` writes each edit it can place
as a Word tracked change, authored by its reader, with the finding as a comment over it
(`tracked.write`); the author accepts or refuses each in Word, and `import` of that
document records what was decided as the finding's answer.

**An edit is placed exactly, or not at all.** Nothing here guesses where words were meant
to go. An edit is dropped, and says why, unless every one of these holds:

- it comes from a reading that is sealed and reads as it was sealed: the edit is the
  reader's, and is shown in Word under the reader's name;
- `old` and `new` are words: no markup character, which a tracked change cannot carry, and
  `new` on one line;
- `old` is found exactly once in the manuscript's prose, front matter and comments left out,
  inside one paragraph that carries an identifier, and once in that paragraph as the build
  printed it. Pandoc's typesetting is read as what it is: a straight quote in `old` finds a
  curly one, `--` an en dash, a space a line break or a no-break space;
- the edit is prose: `reworded`, comparing the paragraph before and after, finds nothing to
  say of a binding, a citation or a typed number. What it says of how strongly a sentence
  claims (`claims.py`) drops nothing: the edit is written, and its comment says so after
  the finding, so that the author sees the move where they decide it;
- written into the source where its words are (`write_in`, which is how `import` writes
  one accepted in Word), the paragraph reads as Word shows it with the edit accepted, and
  is still a paragraph of its own under its identifier. Only the edit's own words change:
  emphasis, code or a link beside them stays as the source has it, and emphasis around
  them goes round the new words, as Word shows those. Words that run across a line break,
  or into a binding, a citation or an inline construct, are not written;
- no other placed edit changes any of the same words, and with the edits before it in its
  paragraph written too, it still holds.

Each reading has at most `PER_READING` edits written.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

PER_READING = 10

#: What an edit may not hold: a character Markdown can read as markup, which a tracked
#: change in Word's text cannot carry back, and which would let an edit open emphasis, a
#: link, a binding or a citation.
_MARKUP = re.compile(r"[*_`\[\]{}<>\\$^~@#|&]")

#: Pandoc's smart typesetting, as a pattern for each thing typed: what `old` says as typed
#: finds the same in the source and what pandoc printed of it in Word.
_TYPESET = (
    ("---", "(?:---|—)"),
    ("--", "(?:--|–)"),
    ("...", "(?:\\.\\.\\.|…)"),
    ("'", "['‘’]"),
    ('"', '["“”]'),
)
#: A space in `old`: a run of spaces, tabs or no-break spaces with at most one line break,
#: which is what Markdown reads as one space.
_SPACE = "(?:[ \\t\\u00a0]*\\n[ \\t\\u00a0]*|[ \\t\\u00a0]+)"
_RUN = re.compile(r"\s+")
_SOFT = re.compile(r"[ \t]*\n[ \t]*|[ \t]+")


@dataclass(frozen=True)
class Edit:
    """One edit a reading suggests, with where it comes from."""

    round: int
    reviewer: str
    reader: str | None
    record: Path
    finding: str
    severity: str
    said: str
    #: Its place among its finding's edits, from 1.
    index: int
    of: int
    old: str
    new: str
    author: str

    @property
    def comment(self) -> str:
        """The finding, as the Word comment over the edit says it."""
        return comment_of(self.finding, self.severity, self.said, self.index, self.of)


def comment_of(finding: str, severity: str, said: str, index: int, of: int) -> str:
    """What the Word comment over an edit says: the finding, and which of its edits."""
    count = f", edit {index} of {of}" if of > 1 else ""
    return f"{finding} ({severity}{count}): {' '.join(said.split())}"


@dataclass(frozen=True)
class Placed:
    """Where an edit goes, or why it goes nowhere."""

    edit: Edit
    dropped: str = ""
    paragraph: str = ""
    supplementary: bool = False
    #: The words as the build printed them, and as Word will show the new ones.
    shown_old: str = ""
    shown_new: str = ""
    #: Where `old` is in its paragraph's source.
    start: int = 0
    end: int = 0
    #: What `reworded` says the edit does to how strongly its sentence claims, if anything.
    claim: str = ""

    @property
    def comment(self) -> str:
        """The Word comment over the edit: its finding, and the move of a claim it makes."""
        return f"{self.edit.comment} {self.claim}" if self.claim else self.edit.comment


@dataclass
class Found:
    """What a round's readings suggest, and what was not looked at and why."""

    edits: list[Edit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def short_digest(text: str) -> str:
    """Sixteen hex digits of the SHA-256 of `text` with its spaces folded: what the
    document records of a suggestion's words, which says which words they were and holds
    none of them."""
    folded = " ".join(text.split())
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()[:16]


def author_of(reviewer: str, reader: str | None, reviewed_by: str) -> str:
    """Who a tracked change is by: the reviewer, and the reader where one is named, as
    `biostatistician (openai/gpt-x)`."""
    who = reader or reviewed_by
    return f"{reviewer} ({who})" if who and who != reviewer else reviewer


def edits_of(project, number: int) -> Found:
    """Every edit suggested by a reading of round `number` that the gate counts, in the
    order of the panel and of each reading's findings. A reading that is not sealed, or no
    longer reads as it was sealed, has its edits left out and is named in `notes`."""
    from manuscript_guard.gates.review import filed_readings, reading_digest

    found = Found()
    for reviewer, reader, path, document in filed_readings(project, number):
        findings = document.get("findings") or []
        if not any(finding.get("edits") for finding in findings):
            continue
        sealed = document.get("reading_sha256")
        if not sealed:
            found.notes.append(
                f"{path.name}: not sealed, so its edits are not written; seal what the reader "
                f"wrote with `manuscript-guard review --seal {reviewer} --round {number}"
                + (f' --reading "{reader}"' if reader else "")
                + "`"
            )
            continue
        if sealed != reading_digest(document):
            found.notes.append(
                f"{path.name}: what the reader wrote has changed since it was sealed "
                "(reading-altered), so its edits are not written"
            )
            continue
        author = author_of(reviewer, reader, str(document.get("reviewed_by") or ""))
        for finding in findings:
            edits = finding.get("edits") or []
            for index, edit in enumerate(edits, start=1):
                found.edits.append(
                    Edit(
                        round=number,
                        reviewer=reviewer,
                        reader=reader,
                        record=path,
                        finding=str(finding["id"]),
                        severity=str(finding["severity"]),
                        said=" ".join(str(finding["finding"]).split()),
                        index=index,
                        of=len(edits),
                        old=str(edit["old"]),
                        new=str(edit["new"]),
                        author=author,
                    )
                )
    return found


def pattern_of(old: str) -> re.Pattern[str]:
    """`old` as a pattern that finds it as typed in the source and as pandoc printed it, as
    whole words: "the" is not found in "other", nor "port" in "reports"."""
    pieces = []
    words = _RUN.split(old.strip())
    for word in words:
        at, out = 0, []
        while at < len(word):
            for typed, finds in _TYPESET:
                if word.startswith(typed, at):
                    out.append(finds)
                    at += len(typed)
                    break
            else:
                out.append(re.escape(word[at]))
                at += 1
        pieces.append("".join(out))
    stripped = old.strip()
    head = "(?<![^\\W_])" if stripped[:1].isalnum() else ""
    tail = "(?![^\\W_])" if stripped[-1:].isalnum() else ""
    return re.compile(head + _SPACE.join(pieces) + tail)


def found_in(text: str, old: str) -> list[tuple[int, int]]:
    """Where `old` is in `text`, as typed or as pandoc printed it, every place it is: the
    reading `review --suggestions` places an edit by, which places it only where this
    finds one place."""
    return [match.span() for match in _starts(pattern_of(old), text)]


def _searchable(raw: str) -> str:
    """A source file with its front matter and its comments blanked, offsets kept: what a
    reader is sent of it, as far as words go."""
    from manuscript_guard.text.masking import blank_comments, front_matter_end

    head = front_matter_end(raw)
    blanked = "".join(char if char == "\n" else " " for char in raw[:head]) + raw[head:]
    return blank_comments(blanked)


def _starts(pattern: re.Pattern[str], text: str) -> list[re.Match[str]]:
    """Every match of `pattern` in `text`, overlapping ones too: `aa` is twice in `aaa`."""
    found, at = [], 0
    while (match := pattern.search(text, at)) is not None:
        found.append(match)
        at = match.start() + 1
    return found


def _folded(text: str) -> str:
    return _SOFT.sub(" ", text).strip()


def refused_words(old: str, new: str) -> str:
    """Why `old` and `new` are not an edit of words, or nothing where they are: the other
    half of the reading an edit is placed by (`found_in`)."""
    for name, text in (("old", old), ("new", new)):
        if not text.strip():
            return f"its {name} words are empty"
        if found := _MARKUP.search(text):
            return (
                f"its {name} words hold {found.group(0)!r}, which Markdown reads as markup: "
                "an edit is words only"
            )
    if "\n" in new.strip():
        return "its new words run over more than one line"
    if re.search(r"\n[ \t]*\n", old):
        return "its words run across two paragraphs"
    if _folded(old) == _folded(new):
        return "it changes nothing"
    return ""


@dataclass(frozen=True)
class _Context:
    """What placing reads once: the source files, searchable and as they are, the
    paragraphs, the build as printed."""

    sources: list[tuple[Path, str]]
    paragraphs: dict[str, tuple[Path, str, int]]
    printed: dict[str, str]
    extents: dict[str, tuple]
    supplementary: frozenset[str]
    raws: dict[Path, str]
    as_sent: list[str]


def _in_source(context: _Context, edit: Edit) -> tuple[str, int, int] | str:
    """The paragraph `old` is in and where in its source, or why it is in none."""
    pattern = pattern_of(edit.old)
    matches = [
        (path, match) for path, text in context.sources for match in _starts(pattern, text)
    ]
    if not matches:
        if any(pattern.search(text) for text in context.as_sent):
            return (
                "its words are in the manuscript only with a value or a table the analysis "
                "prints, which an edit does not change; quote the words around it"
            )
        # What the reader was sent is the build as printed: `*P* value` reads "P value".
        if any(pattern.search(text) for text in context.printed.values()):
            return (
                "its words are in the manuscript only as the build prints them, across "
                "markup the build does not print (emphasis, code, a link, a citation, a line "
                "break), which an edit does not change; quote the words beside it"
            )
        return "its words are not in the manuscript as it stands"
    if len(matches) > 1:
        return (
            f"its words are in the manuscript {len(matches)} times; it needs enough of them "
            "to be found once"
        )
    path, match = matches[0]
    for name, (where, text, start) in context.paragraphs.items():
        if where == path and start <= match.start() and match.end() <= start + len(text):
            return name, match.start() - start, match.end() - start
    return (
        "its words are not in a paragraph the build marks (a heading, a list, a table, a "
        "caption or a quotation), so Word could not bring the change back"
    )


#: What `_SCAN` finds that `_INLINE` gives no name, as a refusal names it.
_UNNAMED = {"code": "code", "entity": "a character reference"}


def _in_the_way(paragraph: str, start: int, end: int) -> str:
    """Why the words at `start:end` of a source paragraph cannot be written over, or nothing
    where they are prose: they are inside a binding, a citation or an inline construct Word
    shows without its markup (code, a link, a footnote, maths, raw markup), or they run
    across a hard line break, which writing them would delete. Emphasis is not in the way:
    the new words are written inside it, as Word shows them."""
    from manuscript_guard.roundtrip import _INLINE, _SCAN, _tokens

    for token in _tokens(paragraph):
        if token.at < end and start < token.to:
            inside = "a binding" if token.text.startswith("{{") else "a citation"
            return f"its words are inside {inside}, which an edit does not change"
    for found in _SCAN.finditer(paragraph):
        kind = found.lastgroup or ""
        if kind == "nbsp" or not (found.start() < end and start < found.end()):
            continue
        if kind == "break":
            return "its words run across a line break, which writing them would delete"
        inside = _INLINE[kind][0] or _UNNAMED.get(kind, "an escaped character")
        return f"its words are inside {inside}, which an edit does not change"
    return ""


@dataclass(frozen=True)
class Words:
    """An edit's words, as its reading holds them: what `write_in` writes. `printed` is the
    digest the document recorded of the old words as the build printed them, which `import`
    holds them to; empty where nothing was recorded yet."""

    old: str
    new: str
    printed: str = ""


@dataclass(frozen=True)
class Written:
    """A paragraph with edits written into it: its source without the anchors that end it,
    those anchors, the paragraph as Word shows it with the edits accepted, and where each of
    its values and citations is in that (None where it has none to place)."""

    bare: str
    anchors: str
    shown: str
    tokens: tuple[tuple[int, int], ...] | None

    @property
    def source(self) -> str:
        return self.bare + self.anchors


def _once(pattern: re.Pattern[str], text: str, where: str) -> re.Match[str] | str:
    found = _starts(pattern, text)
    if len(found) == 1:
        return found[0]
    if found:
        return f"its words are in the paragraph {len(found)} times {where}"
    return f"its words are not in the paragraph {where}"


def write_in(
    source: str, printed: str, tokens: Sequence[tuple[int, int]] | None, edits: Sequence[Words]
) -> Written | str:
    """The paragraph `source`, which the build printed as `printed` with its values and
    citations at `tokens`, with each edit's new words written where its old words are; or
    why they cannot be.

    The other half of how a suggestion is made exact. `import` merges a rewording by
    rebuilding each edited stretch between two values from Word's text, which holds no
    markup, so emphasis or code beside the words would be flattened. A suggestion's words
    are known, and where they were found, so they are written there instead and nothing
    else in the paragraph is touched; `import` then merges whatever else the author changed
    in it against this, by its own rules (`merge.plan_import`).

    Nothing is guessed. Each edit's old words are found once in the source, its comments
    left out, and once in what the build printed, and where the document recorded a digest
    of the printed ones, they
    are those. They lie outside every binding, citation and inline construct and across no
    line break (`_in_the_way`), and no two edits change the same words. Written, the
    paragraph is a change of words to `reworded`, a move of a claim aside (`CLAIM_CODES`,
    which the edit's comment says instead), and it reads as Word shows it with the
    edits accepted. That the file still marks it as a paragraph of its own is asked apart,
    of the file (`_stays_marked`), and `import` asks it of every write it makes.
    """
    from manuscript_guard.reworded import CLAIM_CODES, compare
    from manuscript_guard.roundtrip import _checked, _read, _reads_as, anchors_apart

    apart = anchors_apart(source)
    if apart is None:
        return "its paragraph ends in a way import cannot merge into"
    bare, anchors = apart
    # Words in a comment print nowhere, and placing an edit does not count them either
    # (`_searchable`): counted here, a comment repeating the words refused the write.
    prose = _uncommented(bare)
    places = []
    for words in edits:
        pattern = pattern_of(words.old)
        here = _once(pattern, prose, "as it stands")
        if isinstance(here, str):
            return here
        why = _in_the_way(bare, here.start(), here.end())
        if why:
            return why
        shown = _once(pattern, printed, "as the build printed it")
        if isinstance(shown, str):
            return shown
        if words.printed and short_digest(shown.group(0)) != words.printed:
            return "its words as the build printed them are not the ones the document showed"
        places.append((here.span(), shown.span(), words))

    def overlap(one: tuple[int, int], two: tuple[int, int]) -> bool:
        return one[0] < two[1] and two[0] < one[1]

    for i, (one, one_shown, _words) in enumerate(places):
        for two, two_shown, _other in places[i + 1 :]:
            if overlap(one, two) or overlap(one_shown, two_shown):
                return "two of its edits change some of the same words"
    reading = _read(bare)
    spans: list[tuple[int, int]] = []
    if reading.protected:
        checked = _checked(tokens, len(reading.protected), len(printed))
        if checked is None:
            return "its values and citations could not be lined up with the build"
        spans = checked
        for _here, (a, b), _w in places:
            if any(a < end and start < b for start, end in spans):
                return "its words run into a value or a citation as the build printed it"
    written, shown_text = bare, printed
    # From the last edit to the first, so that the offsets before each still hold.
    for (start, end), _shown, words in sorted(places, key=lambda p: p[0], reverse=True):
        written = written[:start] + words.new.strip() + written[end:]
    for _here, (a, b), words in sorted(places, key=lambda p: p[1], reverse=True):
        new = " ".join(words.new.split())
        shown_text = shown_text[:a] + new + shown_text[b:]
        spans = _shifted(spans, b, len(new) - (b - a))
    report = compare(source, written + anchors)
    # A move of how strongly a sentence claims is said in the edit's comment, not a reason
    # to drop it (Basile, 2026-10-20): a reviewer who asks for "associated" means the move.
    facts = [found for found in report.findings if found.code not in CLAIM_CODES]
    if facts:
        return f"it is more than a change of words: {facts[0].message}"
    renderings = [shown_text[start:end] for start, end in spans]
    if not _reads_as(written, reading.protected, renderings, shown_text):
        return "written into the source, it would not read as Word shows it"
    return Written(written, anchors, shown_text, tuple(spans) if reading.protected else None)


def _uncommented(text: str) -> str:
    """`text` with its HTML comments blanked, offsets kept: words there print nowhere."""
    from manuscript_guard.text.masking import blank_comments

    return blank_comments(text)


def _shifted(spans: list[tuple[int, int]], after: int, by: int) -> list[tuple[int, int]]:
    """Each value's or citation's place in the printed paragraph once the words ending at
    `after` are `by` characters longer: the ones after them move with them."""
    return [(start + by, end + by) if start >= after else (start, end) for start, end in spans]


def _stays_marked(raw: str, start: int, before: str, after: str) -> bool:
    """Whether the source file `raw`, with the paragraph `before` at `start` written as
    `after`, still marks every paragraph it marked, under the same identifiers, and this one
    with its new text: a block `tag` reads as something else, a list or a heading, is no
    paragraph, and the next build gives it no identifier."""
    from manuscript_guard.roundtrip import marked_blocks

    spliced = raw[:start] + after + raw[start + len(before) :]
    expected = [(index, after if at == start else text) for index, text, at in marked_blocks(raw)]
    return [(index, text) for index, text, _at in marked_blocks(spliced)] == expected


def _comes_back(
    context: _Context, name: str, edits: Sequence[Placed], source: str
) -> str:
    """Why the paragraph `name`, with `edits` accepted in Word, could not be written into
    the source as `import` writes it; empty if it could."""
    words = [Words(placed.edit.old, placed.edit.new) for placed in edits]
    written = write_in(source, context.printed[name], context.extents.get(name), words)
    if isinstance(written, str):
        return written
    path, _text, start = context.paragraphs[name]
    if not _stays_marked(context.raws[path], start, source, written.source):
        return (
            "written into the source, it would no longer be a paragraph of its own (a list, "
            "a heading or a caption to pandoc), and the next build would not find it again"
        )
    return ""


def place(context: _Context, edits: Sequence[Edit]) -> list[Placed]:
    """Each edit placed, or dropped with the reason, in the order given."""
    out: list[Placed] = []
    per_reading: dict[Path, int] = {}
    for edit in edits:
        count = per_reading[edit.record] = per_reading.get(edit.record, 0) + 1
        if count > PER_READING:
            out.append(Placed(edit, f"its reading suggests more than {PER_READING} edits, "
                                    f"and only the first {PER_READING} are written"))  # fmt: skip
            continue
        why = refused_words(edit.old, edit.new)
        if why:
            out.append(Placed(edit, why))
            continue
        where = _in_source(context, edit)
        if isinstance(where, str):
            out.append(Placed(edit, where))
            continue
        name, start, end = where
        why = _in_the_way(context.paragraphs[name][1], start, end)
        if why:
            out.append(Placed(edit, why))
            continue
        printed = context.printed.get(name)
        if printed is None:
            out.append(Placed(edit, "its paragraph is not in the document as built"))
            continue
        found = _starts(pattern_of(edit.old), printed)
        if len(found) != 1:
            out.append(Placed(edit, (
                f"its words are in the paragraph {len(found)} times as the build printed it"
                if found else "its words are not in the paragraph as the build printed it"
            )))  # fmt: skip
            continue
        out.append(
            Placed(
                edit,
                paragraph=name,
                supplementary=name in context.supplementary,
                shown_old=found[0].group(0),
                shown_new=" ".join(edit.new.split()),
                start=start,
                end=end,
            )
        )
    return _settled(context, out)


def _settled(context: _Context, placed: list[Placed]) -> list[Placed]:
    """Drop edits that change the same words as another, and those that could not be
    written into the source as `import` writes them, alone or with the edits before them in
    their paragraph."""
    live = [p for p in placed if not p.dropped]
    clashing = set()
    for i, one in enumerate(live):
        for other in live[i + 1 :]:
            if one.paragraph == other.paragraph and one.start < other.end and other.start < one.end:
                clashing.update({id(one), id(other)})
    kept: dict[str, list[Placed]] = {}
    out = []
    for p in placed:
        if p.dropped:
            out.append(p)
            continue
        if id(p) in clashing:
            out.append(_dropped(p, "another edit changes some of the same words, and only one "
                                   "of them could be shown"))  # fmt: skip
            continue
        source = context.paragraphs[p.paragraph][1]
        why = _comes_back(context, p.paragraph, [p], source)
        if not why and kept.get(p.paragraph):
            why = _comes_back(context, p.paragraph, [*kept[p.paragraph], p], source)
            if why:
                why = "with the edits before it in its paragraph accepted, " + why
        if why:
            out.append(_dropped(p, why))
            continue
        p = replace(p, claim=_claim_moved(source, p))
        kept.setdefault(p.paragraph, []).append(p)
        out.append(p)
    return out


def _claim_moved(source: str, placed: Placed) -> str:
    """What the edit alone does to how strongly its paragraph's sentences claim, as its
    comment adds it, or nothing. Basile chose on 2026-10-20 that such an edit be written
    and say so, not dropped: a reviewer who asks for "associated" where the text says
    "caused" means the move."""
    from manuscript_guard.claims import moved

    edited = source[: placed.start] + placed.edit.new.strip() + source[placed.end :]
    said = [" ".join(found.message.split()) for found in moved(source, edited)]
    if not said:
        return ""
    said = [one[0].upper() + one[1:] for one in said]
    return "Note: " + "; ".join(said) + "."


def _dropped(placed: Placed, why: str) -> Placed:
    return Placed(placed.edit, why)


#: Where the documents are written: a folder of the build, not the build itself, which
#: `check` holds to the source (`document-stale`). This document is for the author alone,
#: and goes stale the moment an accepted edit is imported.
FOLDER = "suggestions"


class SuggestionsError(Exception):
    """The document could not be made, and the reason is in the message."""


def document_path(project, number: int, *, supplementary: bool = False) -> Path:
    name = f"round-{number}" + ("-supplementary" if supplementary else "")
    return project.path("build") / FOLDER / f"{name}.docx"


@dataclass(frozen=True)
class Outcome:
    """What `write_round` made: the documents, each edit placed or dropped, what was not
    looked at, and what the builds reported."""

    documents: tuple[Path, ...]
    placed: tuple[Placed, ...]
    notes: tuple[str, ...]
    report: object = None


def _offered(placed: Placed, number: int) -> dict:
    """What a document records of one suggestion it carries: who made it, for which
    finding, and digests of its words, never the words."""
    edit = placed.edit
    return {
        "n": number,
        "round": edit.round,
        "reviewer": edit.reviewer,
        "reader": edit.reader,
        "finding": edit.finding,
        "index": edit.index,
        "author": edit.author,
        "old": short_digest(placed.shown_old),
        "new": short_digest(placed.shown_new),
        "comment": short_digest(edit.comment),
        "written": short_digest(placed.comment),
    }


def write_round(project, number: int, *, csl: Path | None, date: str) -> Outcome:
    """Write round `number`'s edits into a copy of the document as tracked changes.

    The document is built offline, as `build --offline` builds it, into `build/suggestions/`,
    and its record of what it printed goes where every build's goes, so that `import` reads
    it as exactly as it reads the document a co-author was sent. A supplement gets a
    document of its own where an edit is in it. A document no edit could be placed in is not
    kept.
    """
    import tempfile

    from manuscript_guard import tracked
    from manuscript_guard.build import OFFLINE, BuildError, assemble, build_document
    from manuscript_guard.contracts import load_namespace
    from manuscript_guard.docxtext import blocks
    from manuscript_guard.findings import Report
    from manuscript_guard.gates.numbers import is_supplementary
    from manuscript_guard.roundtrip import _sources, tagged_paragraphs
    from manuscript_guard.text.placeholders import substitute

    found = edits_of(project, number)
    if not found.edits:
        return Outcome((), (), tuple(found.notes), Report())
    namespace, results, _literature, _report = load_namespace(project)
    manuscript_dir = project.path("manuscript")
    raws = {path: raw for path, _relative, raw in _sources(project)}
    sources = [(path, _searchable(raw)) for path, raw in raws.items()]
    shown = {ref: value.display for ref, value in namespace.items()}
    paragraphs = tagged_paragraphs(project)
    supplement = frozenset(
        name for name, (path, _t, _s) in paragraphs.items()
        if is_supplementary(manuscript_dir, path)
    )  # fmt: skip
    looking = _Context(sources, paragraphs, {}, {}, supplement, raws,
                       [substitute(text, shown) for _path, text in sources])  # fmt: skip
    kinds = {False}
    for edit in found.edits:
        where = _in_source(looking, edit)
        if not isinstance(where, str) and where[0] in supplement:
            kinds.add(True)

    assembled, _ar = assemble(project, namespace, results)
    marked_assembly, _mr = assemble(project, namespace, results, mark=True)
    printed: dict[str, str] = {}
    extents: dict[str, tuple] = {}
    report = Report()
    outputs = {}
    try:
        for supplementary in sorted(kinds):
            output = document_path(project, number, supplementary=supplementary)
            output.parent.mkdir(parents=True, exist_ok=True)
            built = build_document(project, assembled, mode=OFFLINE, csl=csl, output=output,
                                   supplementary=supplementary)  # fmt: skip
            report = report.merge(built.report)
            outputs[supplementary] = output
            these = {b.names[0]: b.text for b in blocks(output) if b.names and not b.table}
            printed.update(these)
            with tempfile.TemporaryDirectory() as scratch:
                marked_output = Path(scratch) / "marked.docx"
                build_document(project, marked_assembly, mode=OFFLINE, csl=csl,
                               output=marked_output, supplementary=supplementary,
                               verify_reading=False, sent=True)  # fmt: skip
                for block in blocks(marked_output):
                    name = block.names[0] if block.names and not block.table else None
                    if name in these and these[name].replace(" ", " ") == block.text.replace(
                        " ", " "
                    ):
                        extents[name] = block.tokens
    except BuildError as exc:
        raise SuggestionsError(f"the document could not be built: {exc}") from None

    context = _Context(sources, paragraphs, printed, extents, supplement, raws,
                       looking.as_sent)  # fmt: skip
    placed = place(context, found.edits)
    numbered = {id(p): n for n, p in enumerate((p for p in placed if not p.dropped), start=1)}
    final: dict[int, Placed] = {}
    kept = []
    for supplementary, output in outputs.items():
        mine = [p for p in placed if not p.dropped and p.supplementary == supplementary]
        placements = [
            tracked.Placement(numbered[id(p)], p.paragraph, p.shown_old, p.shown_new,
                              p.edit.author, date, p.comment)  # fmt: skip
            for p in mine
        ]
        offered = [_offered(p, numbered[id(p)]) for p in mine]
        written = tracked.write(output, output, placements, offered) if placements else []
        said = {w.number: w.dropped for w in written}
        for p in mine:
            why = said.get(numbered[id(p)], "")
            final[id(p)] = _dropped(p, why) if why else p
        if any(not w.dropped for w in written):
            kept.append(output)
        else:
            for stale in (output, output.with_name(output.name + ".source.sha256")):
                stale.unlink(missing_ok=True)
    return Outcome(
        tuple(kept), tuple(final.get(id(p), p) for p in placed), tuple(found.notes), report
    )


ACCEPTED, REFUSED, CHANGED, GONE = "accepted", "refused", "changed", "gone"


@dataclass(frozen=True)
class Decision:
    """What the author did in Word with one suggestion the document carried."""

    offered: dict
    #: `ACCEPTED`: its bookmark holds the new words; `REFUSED`: the old; `CHANGED`: other
    #: words; `GONE`: the bookmark is not there.
    state: str
    #: The identifier of the paragraph its bookmark starts in, as the returned document
    #: names it.
    paragraph: str = ""
    replies: tuple = ()


def decisions(document: Path, offered: Sequence[dict]) -> tuple[list[Decision], set]:
    """What was done with each suggestion, and the comments that are the panel's own or
    replies to them, as (author, text): those are said with the suggestions, not as a
    co-author's comments."""
    from manuscript_guard import tracked

    found = tracked.decided(document)
    comments, parents = tracked.comments_of(document)
    told: set[tuple[str, str]] = set()
    out = []
    for entry in offered:
        if entry["n"] in found:
            text, names = found[entry["n"]]
            digest = short_digest(text)
            state = {entry["new"]: ACCEPTED, entry["old"]: REFUSED}.get(digest, CHANGED)
            paragraph = names[0] if names else ""
        else:
            state, paragraph = GONE, ""
        replies = []
        for comment in comments:
            ours = comment.author == entry["author"]
            # The comment as Word holds it: the finding, and what the edit does to a claim.
            if ours and short_digest(comment.text) == entry.get("written", entry["comment"]):
                told.add((comment.author, comment.text))
                for reply in tracked.replies_to(comment, comments, parents):
                    told.add((reply.author, reply.text))
                    if reply not in replies:
                        replies.append(reply)
        out.append(Decision(entry, state, paragraph, tuple(replies)))
    return out, told


@dataclass(frozen=True)
class Answer:
    """What a finding's record gets for the edits decided in Word, or why it gets nothing."""

    record: Path
    finding: str
    fields: dict | None
    said: str


def _quoted(text: str, limit: int = 120) -> str:
    folded = " ".join(text.split())
    return "“" + (folded if len(folded) <= limit else folded[:limit] + "…") + "”"


def answers(
    project,
    decided: Sequence[Decision],
    *,
    merged: dict[str, str],
    today,
    named=lambda name: name,
) -> list[Answer]:
    """The answer each finding gets, one per finding with an edit in the document.

    An accepted edit is the finding's resolution once the import merged its paragraph with
    the new words in it. A finding whose edits were all refused is answered only where the
    author replied to a comment of it in Word: the reply is the override's reason and its
    author the override's, and with no reply the finding stays open, since refusing a
    wording is not a reason for leaving what the finding says. A finding with an edit that
    was changed in Word, or whose place is gone, is left to the author, as is one that is
    answered already, or whose record no longer holds the edit the document was made from.
    """
    out = []
    for path, finding, group in _by_finding(project, decided):
        found = _finding_of(path, finding, group)
        if isinstance(found, str):
            out.append(Answer(path, finding, None, found))
            continue
        why = _undecidable(group, found, merged, named)
        if why:
            out.append(Answer(path, finding, None, why))
            continue
        fields, said = _answer(group, found, today)
        out.append(Answer(path, finding, fields, said))
    return out


def _by_finding(project, decided: Sequence[Decision]) -> list[tuple[Path, str, list[Decision]]]:
    """The decisions grouped by the finding they are edits of: its record and its id."""
    from manuscript_guard.gates.review import reading_path

    groups: dict[tuple, list[Decision]] = {}
    for decision in decided:
        entry = decision.offered
        key = (entry["round"], entry["reviewer"], entry["reader"], entry["finding"])
        groups.setdefault(key, []).append(decision)
    return [
        (reading_path(project, number, reviewer, reader), finding, group)
        for (number, reviewer, reader, finding), group in groups.items()
    ]


def accepted_words(
    project, decided: Sequence[Decision], *, named=lambda name: name
) -> dict[str, tuple[Words, ...] | str]:
    """The words of each suggestion accepted in Word, under the paragraph its bookmark is in
    (by the name it has now), for `import` to write where they were found (`write_in`); or,
    for a paragraph, why its accepted words cannot be known exactly, and so are not written.

    The words are the sealed record's, held to the document's digests of them: the document
    carries no words of its own. A suggestion whose bookmark is in no identified paragraph is
    not here, and neither is that paragraph: `import` does not compare it.
    """
    words: dict[str, list[Words]] = {}
    unknown: dict[str, str] = {}
    for path, finding, group in _by_finding(project, decided):
        record = _sealed_finding(path, finding, group)
        for decision in group:
            if decision.state != ACCEPTED or not decision.paragraph:
                continue
            name = named(decision.paragraph)
            if isinstance(record, str):
                unknown.setdefault(name, f"the words are not known: {record}")
                continue
            edit = record["edits"][decision.offered["index"] - 1]
            words.setdefault(name, []).append(
                Words(str(edit["old"]), str(edit["new"]), decision.offered["old"])
            )
    return {**{name: tuple(listed) for name, listed in words.items()}, **unknown}


def _finding_of(path: Path, finding: str, group: Sequence[Decision]) -> dict | str:
    """The finding the document's edits came from, as its sealed record holds it, or why
    it cannot be answered from here."""
    record = _sealed_finding(path, finding, group)
    if isinstance(record, str):
        return record
    answered = (str(record.get(key) or "").strip() for key in ("resolution", "overridden"))
    if any(answered):
        return "it is answered in the record already, and is left as it is"
    return record


def _sealed_finding(path: Path, finding: str, group: Sequence[Decision]) -> dict | str:
    """The finding the document's edits came from, as its sealed record holds it, with each
    edit the document recorded; or why the record does not hold that."""
    from manuscript_guard.contracts._schema import ContractError, read_structured
    from manuscript_guard.gates.review import reading_digest

    try:
        document = read_structured(path) if path.exists() else None
    except ContractError:
        document = None
    if not isinstance(document, dict):
        return "its review record is not there to answer"
    if document.get("reading_sha256") != reading_digest(document):
        return "its review record no longer reads as it was sealed"
    record = next(
        (f for f in document.get("findings") or []
         if isinstance(f, dict) and f.get("id") == finding),
        None,
    )  # fmt: skip
    edits = (record or {}).get("edits") or []

    def same(decision: Decision) -> bool:
        index = decision.offered["index"]
        if not 0 < index <= len(edits):
            return False
        said = comment_of(finding, str(record["severity"]), str(record["finding"]), index,
                          len(edits))  # fmt: skip
        return (
            short_digest(edits[index - 1]["new"]) == decision.offered["new"]
            and short_digest(said) == decision.offered["comment"]
        )

    if record is None or not all(same(d) for d in group):
        return "its finding in the record is not the one the document was made from"
    return record


def _undecidable(group: Sequence[Decision], record: dict, merged: dict, named) -> str:
    """Why what was done in Word with this finding's edits cannot be recorded, if it
    cannot."""
    states = {d.state for d in group}
    if CHANGED in states:
        return (
            "the words of an edit were changed in Word after it was decided, so what was "
            "decided cannot be said; answer it in the record"
        )
    if GONE in states:
        return (
            "an edit's place is gone from the document (its words deleted, or the deletion "
            "accepted and the insertion rejected); answer it in the record"
        )
    for d in group:
        if d.state != ACCEPTED:
            continue
        new = " ".join(record["edits"][d.offered["index"] - 1]["new"].split())
        now = merged.get(named(d.paragraph))
        if now is None or new not in " ".join(now.split()):
            return (
                "an edit was accepted in Word, and import did not merge its paragraph with "
                "it; it stays open until the words are in the source"
            )
    return ""


def _answer(group: Sequence[Decision], record: dict, today) -> tuple[dict | None, str]:
    """The fields the finding gets, and what is said of them."""
    replies = [reply for d in group for reply in d.replies]
    said_back = " ".join(f"{r.author or 'The author'} replied: {r.text}" for r in replies)
    if any(d.state == ACCEPTED for d in group):
        parts = []
        for d in group:
            edit = record["edits"][d.offered["index"] - 1]
            if d.state == ACCEPTED:
                parts.append(f"{_quoted(edit['old'])} now reads {_quoted(edit['new'])}")
            else:
                parts.append(f"the edit to {_quoted(edit['old'])} was refused")
        said = f"Edited in Word as {group[0].offered['author']} suggested: "
        said += "; ".join(parts) + "." + (f" {said_back}" if said_back else "")
        return {"resolution": said, "resolved_on": today}, "accepted"
    if not replies:
        return None, (
            "its edit was refused in Word with no reply to say why, so it stays open: reply "
            "to its comment in Word and import again, or answer it in the record"
        )
    authors = list(dict.fromkeys(r.author for r in replies if r.author))
    fields = {
        "overridden": " ".join(r.text for r in replies),
        **({"overridden_by": ", ".join(authors)} if authors else {}),
        "resolved_on": today,
    }
    return fields, "refused, with the reply as the reason"


__all__ = [
    "ACCEPTED",
    "CHANGED",
    "FOLDER",
    "GONE",
    "PER_READING",
    "REFUSED",
    "Answer",
    "Decision",
    "answers",
    "comment_of",
    "decisions",
    "Edit",
    "Found",
    "Outcome",
    "Placed",
    "SuggestionsError",
    "Words",
    "Written",
    "accepted_words",
    "author_of",
    "document_path",
    "edits_of",
    "pattern_of",
    "found_in",
    "place",
    "refused_words",
    "short_digest",
    "write_in",
    "write_round",
]
