"""Ordinary sessions: what a co-author does to a document in Word on an ordinary day, and
what the author did to the source in the meantime.

Each review of #116, #119 and #120 measured a set of these against main, to see that a fix
for a wrong write refused nothing main merged. The sets were scripts in a scratch folder and
went with it. They are rebuilt here from the review comments, so the next change to
`import` is measured against them by the suite:

- #116, rounds 1 and 2: twenty sessions on the example, five on a current document and
  fifteen on a stale one. Five of them were refused by the interim five-word rule, which
  the record of what the document printed (`tests/test_printed_record.py`) replaced.
- #119, rounds 1 and 2: sessions on the example without an author change, and on the
  example with a list and a quotation added, each with its lead-in.
- #120, rounds 1 and 2: sessions on the example with two lists, a quotation and a
  definition list, and sentences that read like a caption or a heading elsewhere.

A session says what the co-author did, what the author did, and which of the co-author's
rewordings and moves are held back. Everything else must land in the source, and nothing
else may change in it: a deletion is reported and never applied.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import NamedTuple

import pytest
from test_corruption import _paragraph_runs, _sent_back, _word_joined, _word_paragraph, main_md
from test_roundtrip import (
    _parts,
    _reprinted,
    _tracked_mark,
    _tracked_runs,
    _word_delete,
    _word_paste,
)

pytestmark = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

Change = Callable[[str], str]


class Edit(NamedTuple):
    """One thing the co-author did in Word, and what it should do to the source."""

    change: Change
    #: The source text a rewording replaces, and what replaces it; both empty for an edit
    #: that merges nothing: a deletion, an edit to a block without an identifier.
    was: str = ""
    now: str = ""
    #: For a move, how the paragraph moved opens, and how the one it now stands before does.
    moved: tuple[str, str] | None = None


class Author(NamedTuple):
    """What the author did to the project since the build."""

    change: Callable[[Path], None]
    stale: bool = True


class Session(NamedTuple):
    paper: str
    edits: tuple[str, ...]
    author: str = "nothing"
    #: The rewordings and moves that do not land: refused, or not compared.
    held: tuple[str, ...] = ()
    #: What does not land when the document's record of what it printed is not beside the
    #: build, where that differs: the rules for a document built before the record.
    unrecorded: tuple[str, ...] | None = None


def _folded(text: str) -> str:
    return " ".join(text.split())


def _blocks(text: str) -> list[str]:
    return [_folded(block) for block in re.split(r"\n[ \t]*\n", text) if block.strip()]


def _reworded(old: str, new: str, was: str = "", now: str = "") -> Edit:
    """`old` retyped as `new` in the document; in the source, `was` as `now` where the
    source's own words differ from the document's."""

    def change(xml: str) -> str:
        assert old in xml, old
        return xml.replace(old, new, 1)

    return Edit(change, was or old, now or new)


def _in_word(old: str, new: str) -> Edit:
    """An edit to text that has no identifier, which merges nothing."""

    def change(xml: str) -> str:
        assert old in xml, old
        return xml.replace(old, new, 1)

    return Edit(change)


def _deleted(opening: str, how: str = "word") -> Edit:
    """The paragraph opening so deleted: with Track Changes off, which leaves its bookmark
    in front of the next paragraph ("word"); with its bookmark, as a document edited
    outside Word loses it ("gone"); or with Track Changes on ("tracked")."""

    def change(xml: str) -> str:
        paragraph = _word_paragraph(xml, opening)
        if how == "word":
            return _word_delete(xml, paragraph)
        if how == "gone":
            return xml.replace(paragraph, "", 1)
        props, mark, runs = _parts(paragraph)
        struck = f"<w:p>{_tracked_mark(props, 'del')}{mark}{_tracked_runs(runs, 'del')}</w:p>"
        return xml.replace(paragraph, struck, 1)

    return Edit(change)


def _emptied(opening: str) -> Edit:
    """The paragraph's text cut without its mark: an empty line, the bookmark still on it."""

    def change(xml: str) -> str:
        paragraph = _word_paragraph(xml, opening)
        props, mark, _runs = _parts(paragraph)
        return xml.replace(paragraph, f"<w:p>{props}{mark}</w:p>", 1)

    return Edit(change)


def _moved(opening: str, before: str, how: str) -> Edit:
    """The paragraph opening so cut and pasted in front of the one opening `before`."""

    def change(xml: str) -> str:
        return _word_paste(
            xml, [_word_paragraph(xml, opening)], _word_paragraph(xml, before), how
        )

    return Edit(change, moved=(opening, before) if how == "tracked-move" else None)


def _split(opening: str, at: str) -> Edit:
    """Enter pressed in the paragraph before the sentence opening `at`."""

    def change(xml: str) -> str:
        paragraph = _word_paragraph(xml, opening)
        props, _mark, _runs = _parts(paragraph)
        cut = paragraph.index(at)
        closed = "</w:t></w:r></w:p>"
        opened = f'<w:p>{props}<w:r><w:t xml:space="preserve">'
        halves = paragraph[:cut].rstrip() + closed + opened + paragraph[cut:]
        return xml.replace(paragraph, halves, 1)

    return Edit(change)


def _joined(first: str, second: str) -> Edit:
    return Edit(_word_joined(first, second))


def _restyled(opening: str, properties: str) -> Edit:
    """The paragraph given other paragraph properties: a style, or a list's numbering."""

    def change(xml: str) -> str:
        paragraph = _word_paragraph(xml, opening)
        _props, mark, runs = _parts(paragraph)
        return xml.replace(paragraph, f"<w:p><w:pPr>{properties}</w:pPr>{mark}{runs}</w:p>", 1)

    return Edit(change)


def _item_added(after: str, text: str) -> Edit:
    """A list item typed under the one reading `after`."""

    def change(xml: str) -> str:
        item = next(p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL) if after in p)
        return xml.replace(item, item + item.replace(after, text), 1)

    return Edit(change)


def _item_deleted(text: str) -> Edit:
    def change(xml: str) -> str:
        item = next(p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL) if text in p)
        return xml.replace(item, "", 1)

    return Edit(change)


def _pasted_into(opening: str, into: str) -> Edit:
    """The paragraph cut whole with Track Changes off and pasted onto the end of another."""

    def change(xml: str) -> str:
        paragraph = _word_paragraph(xml, opening)
        runs = _paragraph_runs(paragraph)
        xml = _word_delete(xml, paragraph)
        target = _word_paragraph(xml, into)
        space = '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        return xml.replace(target, target[: -len("</w:p>")] + space + runs + "</w:p>", 1)

    return Edit(change)


# ------------------------------------------------------------------------------ the papers

_LIST = """\
Reports were left out of the analysis for either of two reasons:

- no date of onset was recorded
- no drug name was recorded

Reports left out were counted and are not described further.
"""
_QUOTE = """\
The agency's last review put the question plainly:

> The signal for the class has not been examined for its individual members.
"""
_STEPS = """\
Screening followed these steps:

1. Reports were screened by one reader.

   Screening was repeated by a second reader, who was unaware of the first result.

2. Disagreements were settled by discussion.

The abbreviations used in the tables are these:

ROR
:   reporting odds ratio

CI
:   confidence interval
"""
_CALLOUT = "Table 3 shows the contingency table underlying the reporting odds ratio."


def _with(text: str, anchor: str, added: str) -> str:
    assert anchor in text, anchor
    return text.replace(anchor, f"{added}\n{anchor}", 1)


def _paper(root: Path, name: str) -> None:
    """The example, with what each review added to it before the build."""
    path = main_md(root)
    text = path.read_text(encoding="utf-8")
    if name in ("lists", "kinds"):
        text = _with(text, "Reporting follows the checklist", _LIST)
        text = _with(text, "Several limitations follow", _QUOTE)
    if name == "kinds":
        text = _with(text, "Reporting follows the checklist", _STEPS)
    if name == "callout":
        text = _with(text, "Reporting of hepatic injury was disproportionate", f"{_CALLOUT}\n")
    path.write_text(text, encoding="utf-8")


@pytest.fixture(scope="module")
def papers(built_example: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Each paper built once, with its record beside it; a session works on a copy."""
    from manuscript_guard.cli import main

    built = {}
    for name in ("example", "lists", "kinds", "callout"):
        root = tmp_path_factory.mktemp(name) / "paper"
        shutil.copytree(built_example, root, ignore=shutil.ignore_patterns("build"))
        _paper(root, name)
        assert main(["build", str(root), "--offline", "--skip-checks"]) == 0, name
        built[name] = root
    return built


# ------------------------------------------------------------- what the author did since

_GONE = "Whether the signal extends to example-drug specifically has not been examined."


def _source(old: str, new: str) -> Author:
    def change(root: Path) -> None:
        path = main_md(root)
        text = path.read_text(encoding="utf-8")
        assert old in text, old
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    return Author(change)


AUTHORS = {
    "nothing": Author(lambda root: None, stale=False),
    "edited another": _source("No real patient data were used", "No patient data were used"),
    "re-ran": Author(lambda root: _reprinted(root, 4100)),
    "added a paragraph": _source(
        "# Introduction\n\n", "# Introduction\n\nA paragraph added after the build.\n\n"
    ),
    "added to the Methods": _source(
        "Reporting follows the checklist",
        "A paragraph added to the Methods after the build.\n\nReporting follows the checklist",
    ),
    "edited the one deleted": _source(_GONE, _GONE.replace("has not been", "has never been")),
    "dropped the one deleted": _source(f"{_GONE}\n\n", ""),
    "reworded Funding": _source("received no funding", "received no specific funding"),
    "reworded a paragraph": _source(
        "Hepatic injury is the single event term used by the data generator.",
        "Hepatic injury is the only event term the data generator uses.",
    ),
    "edited the list": _source("- no drug name was recorded", "- the drug was not named"),
    "edited the quotation": _source("individual members", "single members"),
}

# ------------------------------------------------------------- what the co-author did

_SEX = "Reports were included without restriction on age or sex."
_BIAS = "bias, and the denominator is unknown."
_RATE = "nothing in these data supports a rate"
_ITEM = '<w:numPr><w:ilvl w:val="0" /><w:numId w:val="1001" /></w:numPr>'
_HEPATIC = "Hepatic injury is the single event term used by the data generator."
_LEFT_OUT = "Reports left out were counted and are not described further."
_REASONS = "Reports were left out of the analysis for either of two reasons:"
_PLAINLY = "The agency's last review put the question plainly:"
_SECOND = "Screening was repeated by a second reader, who was unaware of the first result."
_STEPS_LEAD = "Screening followed these steps:"
_NOT_INCIDENCE = "Disproportionality is not incidence, and"

EDITS = {
    # Rewordings of a paragraph with an identifier.
    "typo": _reworded("received no funding", "received no external funding"),
    "reword": _reworded(_SEX, "No restriction on age or sex was applied to the reports."),
    "cut": _reworded(_BIAS, "bias."),
    "clause": _reworded(
        _RATE, _RATE + ", which a count of reports alone can never do, however large"
    ),
    "year": _reworded("None declared.", "None declared in 2019."),
    "reword hepatic": _reworded(_HEPATIC, _HEPATIC.replace("single", "only")),
    "rewrite hepatic": _reworded(_HEPATIC, "The generator emits one event term, hepatic injury."),
    "rewrite gone": _reworded(_GONE, "Nobody has examined whether the signal extends to it."),
    "rewrite left out": _reworded(_LEFT_OUT, "We counted what was left out and say no more."),
    "reword left out": _reworded(_LEFT_OUT, _LEFT_OUT.replace("counted", "tallied")),
    "reword reasons": _reworded(_REASONS, _REASONS.replace("either of two", "one of two")),
    "rewrite reasons": _reworded(_REASONS, "Two things led us to leave a report out:"),
    "rewrite plainly": _reworded(
        _PLAINLY.replace("'", "\N{RIGHT SINGLE QUOTATION MARK}"),
        "In its last review the agency was plain:",
        _PLAINLY,
    ),
    "rewrite second": _reworded(_SECOND, "A second reader, blind to the first, screened again."),
    "reword second": _reworded(_SECOND, _SECOND.replace("unaware", "not told")),
    "reword steps lead": _reworded(_STEPS_LEAD, "Screening followed two steps:"),
    "reword callout": _reworded(_CALLOUT, _CALLOUT.replace("shows", "gives")),
    # Deletions, moves, splits and joins.
    "delete": _deleted("Whether the signal extends"),
    "delete gone": _deleted("Whether the signal extends", "gone"),
    "delete tracked": _deleted("Whether the signal extends", "tracked"),
    "delete analysed": _deleted("We analysed a synthetic"),
    "delete hepatic": _deleted("Hepatic injury is the single"),
    "delete two": Edit(
        lambda xml: _deleted("None declared.").change(_deleted("This work received").change(xml))
    ),
    "delete left out": _deleted("Reports left out were counted"),
    "delete reasons": _deleted("Reports were left out of the analysis"),
    "delete plainly": _deleted("last review put the question plainly"),
    "delete second": _deleted("Screening was repeated"),
    "delete steps lead": _deleted("Screening followed these steps"),
    "delete abbreviations": _deleted("The abbreviations used"),
    "empty": _emptied("Whether the signal extends"),
    "move": _moved(_NOT_INCIDENCE, "The reporting odds ratio observed", "tracked-move"),
    "move untracked": _moved(_NOT_INCIDENCE, "The reporting odds ratio observed", "untracked"),
    "heading deleted": _item_deleted(">Competing interests<"),
    "split": _split("The reporting odds ratio was computed", "Confidence intervals were derived"),
    "join": _joined("Hepatic injury is the single", "The reporting odds ratio was computed"),
    "join analysed": _joined("We analysed a synthetic", "Hepatic injury is the single"),
    "paste gone": _pasted_into("Whether the signal extends", "None declared."),
    # Edits to blocks without an identifier.
    "heading": _in_word(">Methods<", ">Methods and data<"),
    "heading two": _in_word(">Funding<", ">Funding sources<"),
    "caption": _in_word(
        "Contingency table underlying the reporting odds ratio.",
        "Contingency table underlying the reporting odds ratio for example-drug.",
    ),
    "item": _in_word("no date of onset was recorded", "the date of onset was missing"),
    "item two": _in_word("no drug name was recorded", "the drug was not named in the report"),
    "item added": _item_added("no drug name was recorded", "the report was a duplicate"),
    "item deleted": _item_deleted("no drug name was recorded"),
    "quotation": _in_word("has not been examined for its", "was never examined for its"),
    "term": _in_word(">ROR<", ">ROR, the ratio<"),
    "definition": _in_word("reporting odds ratio<", "the reporting odds ratio<"),
    "step": _in_word("Disagreements were settled by discussion.", "Disagreements were discussed."),
    # A paragraph given another kind of paragraph's properties.
    "as item": _restyled("Reports left out were counted", _ITEM),
    "as quotation": _restyled("Reports left out were counted", '<w:pStyle w:val="BlockText" />'),
    "as heading": _restyled("Reports left out were counted", '<w:pStyle w:val="Heading2" />'),
    "as term": _restyled("Reports left out were counted", '<w:pStyle w:val="DefinitionTerm" />'),
    "as compact": _restyled("Reports left out were counted", '<w:pStyle w:val="Compact" />'),
    "as own style": _restyled("Reports left out were counted", '<w:pStyle w:val="ZuluOwn" />'),
}

SESSIONS = {
    # ---- #116: twenty sessions on the example, five current and fifteen stale.
    "116 a word fixed": Session("example", ("typo",)),
    "116 a sentence reworded and a clause cut": Session("example", ("reword", "cut")),
    "116 a paragraph deleted": Session("example", ("delete",)),
    "116 a paragraph moved": Session("example", ("move",)),
    "116 everything at once": Session(
        "example", ("typo", "reword", "cut", "delete gone", "move")
    ),
    "116 three edits, another paragraph edited": Session(
        "example", ("typo", "reword", "cut"), "edited another"
    ),
    "116 a deletion and a rewording, another edited": Session(
        "example", ("delete", "reword"), "edited another"
    ),
    "116 a move and a fix, another edited": Session(
        "example", ("move", "typo"), "edited another"
    ),
    "116 three edits, re-run": Session("example", ("typo", "reword", "cut"), "re-ran"),
    "116 a deletion and a rewording, re-run": Session("example", ("delete", "reword"), "re-ran"),
    "116 a move and a fix, re-run": Session("example", ("move", "typo"), "re-ran"),
    "116 a deletion and a fix, re-run": Session("example", ("delete", "typo"), "re-ran"),
    "116 three edits, a paragraph added": Session(
        "example", ("typo", "reword", "cut"), "added a paragraph"
    ),
    "116 a deletion and a rewording, a paragraph added": Session(
        "example", ("delete", "reword"), "added a paragraph"
    ),
    "116 a move, a paragraph added": Session("example", ("move",), "added a paragraph"),
    # The five the interim five-word rule refused: the co-author deleted a paragraph the
    # author had changed or dropped, and reworded another so that it gained six words, or
    # added a clause to one. The record says what the deleted one printed, and they merge.
    # With the paragraph dropped from the .md, the one directly under it is not followed,
    # and its rewording is not compared, as on main.
    "116 both changed one, left on the next, three edits": Session(
        "example",
        ("delete", "typo", "reword", "cut"),
        "edited the one deleted",
        unrecorded=("reword",),
    ),
    "116 both changed one, gone, three edits": Session(
        "example",
        ("delete gone", "typo", "reword", "cut"),
        "edited the one deleted",
        unrecorded=("reword",),
    ),
    "116 both changed one, a rewording": Session(
        "example", ("delete", "reword"), "edited the one deleted", unrecorded=("reword",)
    ),
    "116 the author dropped it, gone, four edits": Session(
        "example",
        ("delete gone", "typo", "reword", "cut", "clause"),
        "dropped the one deleted",
        held=("reword",),
        unrecorded=("reword", "clause"),
    ),
    "116 the author dropped it, a clause": Session(
        "example", ("delete", "clause"), "dropped the one deleted", unrecorded=("clause",)
    ),
    # ---- #119 round 1: the example, mostly with no author change.
    "119 typo fixes": Session("example", ("typo", "year")),
    "119 an untracked deletion": Session("example", ("delete analysed",)),
    # The deleted paragraph's identifier stands in front of the reworded one's: the two are
    # reported as a join, and neither is written.
    "119 an untracked deletion, the next reworded": Session(
        "example", ("delete analysed", "reword hepatic"), held=("reword hepatic",)
    ),
    "119 a tracked deletion": Session("example", ("delete tracked", "clause")),
    "119 an emptied line": Session("example", ("empty", "clause")),
    "119 a split": Session("example", ("split", "typo")),
    "119 a join": Session("example", ("join", "clause")),
    "119 a join, the first half edited": Session("example", ("join analysed", "typo")),
    "119 an untracked move": Session("example", ("move untracked", "typo")),
    "119 a tracked move": Session("example", ("move", "clause")),
    "119 a re-run with a deletion": Session("example", ("delete", "clause"), "re-ran"),
    "119 a re-run with a join": Session("example", ("join", "typo"), "re-ran"),
    # A paragraph reworded beside a heading, list item or quotation edited in the same round
    # is refused for the new text beside it, here and in the sessions below that hold one.
    "119 several edits": Session(
        "example", ("typo", "clause", "reword", "delete", "heading"), held=("reword",)
    ),
    "119 several edits and a move": Session("example", ("cut", "clause", "move", "delete two")),
    "119 several edits, the Methods added to": Session(
        "example", ("typo", "clause", "delete"), "added to the Methods"
    ),
    "119 a deletion, Funding reworded": Session(
        "example", ("delete", "clause"), "reworded Funding"
    ),
    # Round 1's finding, as sessions: a paragraph deleted, joined or moved in front of one
    # the author reworded, with a clause or a year added elsewhere.
    "119 deleted before one the author reworded, a clause": Session(
        "example", ("delete analysed", "clause"), "reworded a paragraph"
    ),
    "119 deleted before one the author reworded, a year": Session(
        "example", ("delete analysed", "year"), "reworded a paragraph"
    ),
    "119 joined with one the author reworded, a clause": Session(
        "example", ("join analysed", "clause"), "reworded a paragraph"
    ),
    # ---- #119 round 2: the example with a list and a quotation, each with its lead-in.
    "119 lists: a typo": Session("lists", ("typo",)),
    "119 lists: a clause": Session("lists", ("clause",)),
    "119 lists: a split": Session("lists", ("split", "typo")),
    "119 lists: two joins": Session("lists", ("join", "join analysed", "clause")),
    "119 lists: an untracked move": Session("lists", ("move untracked", "typo")),
    "119 lists: a tracked move": Session("lists", ("move", "typo")),
    "119 lists: an untracked deletion": Session("lists", ("delete", "typo")),
    "119 lists: a tracked deletion": Session("lists", ("delete tracked", "typo")),
    "119 lists: two paragraphs deleted": Session("lists", ("delete two", "clause")),
    "119 lists: the paragraph after the list deleted": Session(
        "lists", ("delete left out", "clause")
    ),
    "119 lists: the list's lead-in deleted": Session("lists", ("delete reasons", "clause")),
    "119 lists: the lead-in deleted, the first item edited": Session(
        "lists", ("delete reasons", "item", "clause")
    ),
    "119 lists: the quotation's lead-in deleted, the quotation edited": Session(
        "lists", ("delete plainly", "quotation", "clause"), held=("clause",)
    ),
    "119 lists: an item edited": Session("lists", ("item", "typo")),
    "119 lists: an item added": Session("lists", ("item added", "typo")),
    "119 lists: an item deleted": Session("lists", ("item deleted", "typo")),
    "119 lists: the quotation edited": Session("lists", ("quotation", "typo")),
    "119 lists: the lead-in and an item edited": Session("lists", ("reword reasons", "item two")),
    "119 lists: given the list's numbering, edited": Session(
        "lists", ("as item", "reword left out")
    ),
    "119 lists: given the quotation's style, edited": Session(
        "lists", ("as quotation", "reword left out")
    ),
    "119 lists: a clause, the list edited in the .md": Session(
        "lists", ("clause",), "edited the list"
    ),
    "119 lists: a clause, the quotation edited in the .md": Session(
        "lists", ("clause",), "edited the quotation"
    ),
    "119 lists: deleted before one the author reworded": Session(
        "lists", ("delete analysed", "clause"), "reworded a paragraph"
    ),
    "119 lists: joined with one the author reworded": Session(
        "lists", ("join analysed", "clause"), "reworded a paragraph"
    ),
    "119 lists: the lead-in deleted, a paragraph reworded by the author": Session(
        "lists", ("delete reasons", "clause"), "reworded a paragraph"
    ),
    "119 lists: the one the author reworded deleted": Session(
        "lists", ("delete hepatic", "clause"), "reworded a paragraph", unrecorded=("clause",)
    ),
    # ---- #120 round 1: the example with two lists, a quotation and a definition list.
    "120 kinds: a typo": Session("kinds", ("typo",)),
    "120 kinds: a clause": Session("kinds", ("clause",)),
    "120 kinds: a first paragraph rewritten": Session("kinds", ("rewrite gone",)),
    "120 kinds: a body paragraph rewritten": Session("kinds", ("rewrite hepatic",)),
    "120 kinds: the lead-ins rewritten": Session("kinds", ("rewrite reasons", "rewrite plainly")),
    "120 kinds: the paragraph after the list rewritten": Session("kinds", ("rewrite left out",)),
    "120 kinds: the further paragraph rewritten": Session("kinds", ("rewrite second",)),
    "120 kinds: two items edited": Session("kinds", ("item", "item two", "typo")),
    "120 kinds: the quotation edited": Session("kinds", ("quotation", "typo")),
    "120 kinds: a term and a definition edited": Session("kinds", ("term", "definition", "typo")),
    "120 kinds: the further paragraph deleted": Session("kinds", ("delete second", "clause")),
    "120 kinds: the further paragraph deleted, the next item edited": Session(
        "kinds", ("delete second", "step", "clause")
    ),
    "120 kinds: the steps' lead-in deleted": Session("kinds", ("delete steps lead", "clause")),
    "120 kinds: the lead-in to the terms deleted, a term edited": Session(
        "kinds", ("delete abbreviations", "term", "clause")
    ),
    "120 kinds: the list's lead-in deleted, an item edited": Session(
        "kinds", ("delete reasons", "item", "clause")
    ),
    "120 kinds: the quotation's lead-in deleted": Session("kinds", ("delete plainly", "clause")),
    # Nothing of a paste is written: the paragraph it went into is refused.
    "120 kinds: a paragraph cut into another": Session("kinds", ("paste gone",)),
    # A paragraph given another kind's properties and rewritten was reported deleted, since
    # nothing told it from a block of that kind. Nothing that stood under it is gone, so
    # with the record it is the paragraph, and its rewording merges.
    "120 kinds: an item's numbering, lightly edited": Session(
        "kinds", ("as item", "reword left out")
    ),
    "120 kinds: an item's numbering, rewritten": Session(
        "kinds", ("as item", "rewrite left out"), unrecorded=("rewrite left out",)
    ),
    "120 kinds: a quotation's style, lightly edited": Session(
        "kinds", ("as quotation", "reword left out")
    ),
    "120 kinds: a quotation's style, rewritten": Session(
        "kinds", ("as quotation", "rewrite left out"), unrecorded=("rewrite left out",)
    ),
    "120 kinds: a heading's style, lightly edited": Session(
        "kinds", ("as heading", "reword left out")
    ),
    "120 kinds: a heading's style, rewritten": Session(
        "kinds", ("as heading", "rewrite left out"), unrecorded=("rewrite left out",)
    ),
    "120 kinds: a term's style, lightly edited": Session("kinds", ("as term", "reword left out")),
    "120 kinds: a term's style, rewritten": Session(
        "kinds", ("as term", "rewrite left out"), unrecorded=("rewrite left out",)
    ),
    "120 kinds: the compact style, rewritten": Session(
        "kinds", ("as compact", "rewrite left out")
    ),
    "120 kinds: a style the build does not use, rewritten": Session(
        "kinds", ("as own style", "rewrite left out")
    ),
    "120 kinds: the further paragraph reworded, lightly": Session("kinds", ("reword second",)),
    "120 kinds: a lead-in reworded, its list edited": Session(
        "kinds", ("reword steps lead", "step")
    ),
    # ---- #120 round 2: a sentence that reads like a caption elsewhere, and the example.
    "120 five rewordings": Session("example", ("typo", "reword", "cut", "clause", "year")),
    "120 five rewordings, headings and a caption edited": Session(
        "example",
        ("typo", "reword", "cut", "clause", "year", "heading", "heading two", "caption"),
        held=("typo", "reword"),
    ),
    "120 a heading deleted": Session("example", ("typo", "clause", "heading deleted")),
    "120 the call-out reworded, the caption left alone": Session("callout", ("reword callout",)),
    "120 the call-out reworded, its caption edited": Session(
        "callout", ("reword callout", "caption")
    ),
    "120 the call-out reworded, its caption edited, re-run": Session(
        "callout", ("reword callout", "caption"), "re-ran"
    ),
    "120 lists: items deleted, the lead-in rewritten": Session(
        "lists", ("item deleted", "rewrite reasons")
    ),
    "120 lists: five rewordings, the list and the quotation edited": Session(
        "lists", ("typo", "reword", "cut", "clause", "item", "quotation"), held=("cut",)
    ),
}


def run(
    session: Session, papers: dict[str, Path], tmp_path: Path, recorded: bool = True
) -> tuple[str, str, str]:
    """The session played out: the source before the import, after it, and what was said.
    Without the document's record of what it printed, unless `recorded`."""
    from manuscript_guard.cli import main

    root = tmp_path / "paper"
    shutil.copytree(papers[session.paper], root)
    if not recorded:
        shutil.rmtree(root / "build" / "records")

    def change(xml: str) -> str:
        for name in session.edits:
            xml = EDITS[name].change(xml)
        return xml

    document = next(p.name for p in (root / "build").glob("manuscript*.docx"))
    returned = _sent_back(root, tmp_path, change, document=document)
    author = AUTHORS[session.author]
    author.change(root)
    before = main_md(root).read_text(encoding="utf-8")
    printed = StringIO()
    with redirect_stdout(printed):
        main(["import", str(returned), str(root), "--apply", *["--force"][: author.stale]])
    return before, main_md(root).read_text(encoding="utf-8"), printed.getvalue()


def expected(session: Session, before: str) -> list[str]:
    """The source's blocks with every edit that is not held applied, and nothing else."""
    blocks = _blocks(before)
    for name in session.edits:
        edit = EDITS[name]
        if name in session.held:
            continue
        if edit.was:
            was, now = _folded(edit.was), _folded(edit.now)
            at = next(i for i, block in enumerate(blocks) if was in block)
            blocks[at] = blocks[at].replace(was, now, 1)
        if edit.moved:
            opening, before_it = edit.moved
            moved = blocks.pop(next(i for i, b in enumerate(blocks) if b.startswith(opening)))
            blocks.insert(next(i for i, b in enumerate(blocks) if b.startswith(before_it)), moved)
    return blocks


@pytest.mark.parametrize("name", list(SESSIONS))
def test_an_ordinary_session_lands_what_it_should_and_nothing_else(
    papers: dict[str, Path], tmp_path: Path, name: str
) -> None:
    session = SESSIONS[name]
    before, after, out = run(session, papers, tmp_path)
    assert _blocks(after) == expected(session, before), out


@pytest.mark.parametrize(
    "name", [name for name, session in SESSIONS.items() if session.unrecorded is not None]
)
def test_without_its_record_a_session_is_read_by_the_rules_before_it(
    papers: dict[str, Path], tmp_path: Path, name: str
) -> None:
    """The sessions that differ where the record of what the document printed is not
    beside the build: imported on another machine, or with build/ cleaned. Each holds back
    what main held back before the record, and the import says the record is missing."""
    session = SESSIONS[name]
    session = session._replace(held=session.unrecorded or ())
    before, after, out = run(session, papers, tmp_path, recorded=False)
    assert _blocks(after) == expected(session, before), out
    assert "records/" in out
