"""Sessions nobody chose: a paper of blocks that read alike, edited in Word in several
places at once, and held to one thing.

**What `import --apply` writes is what the co-author typed, where they typed it.** Every
block of the source afterwards is the block as it was, or the block with the co-author's
own rewording of that block in it. Nothing is deleted, nothing is written into a block the
co-author did not touch, and no block takes another's words.

That is one half of what `tests/test_ordinary_sessions.py` holds, and the half that
matters most: a rewording held back costs the author a paragraph to retype, and a
rewording written into the wrong paragraph is a manuscript that says what nobody wrote.
The sessions there were written by hand from the reviews of #116 to #121, each with the
outcome it must have. These are drawn, so the outcome of each is not known: whether a
rewording lands or is held back is the import's to decide, and is not asserted here.
`tests/test_differential.py` puts the same sessions through the base branch's source,
where a rewording that used to land and is now held back is a difference.

The reviews found the wrong writes on papers "built from four sentences, so that
paragraphs, headings, captions, list items, quotations, line blocks and divs read alike",
with a paragraph deleted in front of a block that reads like it. So that is the paper
here: every block is one of a few sentences with one word of its own, by which the test
knows it again in the source (`tests/readings.py`, the `import` reading).

Each session builds a document with pandoc and imports it, which takes about three
seconds, so a run has few: twelve. `MANUSCRIPT_GUARD_MORE_EXAMPLES` draws more.

Twelve are few enough to hold nothing by accident, so two more things are held here.
What `sessions()` draws at all is asked of two thousand sessions that are only drawn. And
what the twelve are, and where the import wrote among them, is asked of the twelve, which
for that are drawn from a seed written below and not from the property's own source.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable, Iterable
from functools import cache
from typing import Any

import pytest
from generated import SEED, generated, holds, sessions, times
from hypothesis import given
from readings import NOW, READINGS, SAYS, TAGS, WAS, Reading, answer

from manuscript_guard import merge

pytestmark = [
    pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed"),
    pytest.mark.usefixtures("stopped_if_stuck"),
]

Session = dict[str, Any]

#: The seed the property's twelve sessions are drawn from.
#:
#: The other generated tests are seeded by Hypothesis from their own source, docstring
#: included. This one is also held to what its twelve contain, and seeded that way it drew
#: twelve others when one word of it changed, and failed on an import nobody had touched.
#: So the twelve are fixed by this number, by `sessions()` in `tests/generated.py`, by
#: `TAGS` and `SAYS` in `tests/readings.py`, which it draws from, and by the pin of
#: Hypothesis in `pyproject.toml`; and not by a word of this file. When one of those
#: changes, `test_the_twelve_sessions_are_the_ones_the_property_is_for` may fail on twelve
#: other sessions: its message says so, and which numbers are worth trying.
#:
#: How it was chosen: of the numbers 0 to 119, twenty-eight draw twelve with the sessions
#: asked for. Seventeen of those were played through the import, and with four of them it
#: wrote everywhere it is asked to and said of the case of #121 what #121 made it say:
#: 34, 38, 53 and 54. With two more, 37 and 75, it wrote everywhere and never said it.
PINNED = 34
#: How many of the numbers worth trying turned out to have it all, for the message.
_HAS_IT_ALL = "about one in four"


@cache
def _round_trip() -> Reading:
    return READINGS["import"]()


def _blocks(text: str) -> list[str]:
    return [" ".join(block.split()) for block in re.split(r"\n[ \t]*\n", text) if block.strip()]


#: A session played: the session, whether the import wrote anything, and what it said.
Played = tuple[Session, bool, str]
#: The sessions the property played last.
_PLAYED: list[Played] = []


@holds(12, sessions(), pinned=PINNED)
def what_is_written_is_what_was_typed(session: Session) -> None:
    """The property: after the import, every block of the source is the block as it was,
    or the block with the co-author's own rewording of that block."""
    found = answer(_round_trip(), session)
    assert "raised" not in found, (found, session)
    found = found["answer"]
    assert "before" in found, f"the paper did not build: {found}"
    said = found["said"]
    assert "Traceback" not in said, said

    did = dict(session["in_word"])
    was, now = _blocks(found["before"]), _blocks(found["after"])
    _PLAYED.append((session, now != was, said))
    assert len(now) == len(was), (
        f"the source has {len(now)} blocks where there were {len(was)}\n{session}\n{said}\n"
        f"{found['before']}\n{found['after']}"
    )
    for old, new in zip(was, now, strict=True):
        if new == old:
            continue
        tag = next((tag for tag in TAGS if f" {tag} " in f" {old} "), None)
        assert did.get(tag) == "reworded" and new == old.replace(WAS, NOW, 1), (
            f"{old!r} became {new!r}\n{session}\n{said}"
        )


@cache
def _the_run() -> tuple[Played, ...]:
    """The property over its sessions, once for every test that reads what was played."""
    _PLAYED.clear()
    what_is_written_is_what_was_typed()
    return tuple(_PLAYED)


def _as_pinned() -> bool:
    """Whether this run plays the twelve sessions of `PINNED`: not more of them, and not
    those of a seed the run names. What other sessions contain is chance."""
    return times() == 1 and not os.environ.get(SEED, "").strip()


def test_what_an_import_writes_is_what_the_co_author_typed_where_they_typed_it() -> None:
    _the_run()


# ------------------------------------------------------------- what a session has in it

#: The kinds of block the build gives an identifier, which is a bookmark in the document.
IDENTIFIED = ("paragraph", "second paragraph")


def _kinds(session: Session) -> dict[str, str]:
    return {block["tag"]: block["kind"] for block in session["blocks"]}


def _done(session: Session, *, identified: bool) -> set[str]:
    """What the co-author did to the blocks that have an identifier, or to those without."""
    kind = _kinds(session)
    return {how for tag, how in session["in_word"] if (kind[tag] in IDENTIFIED) == identified}


def _left_by_word(session: Session) -> list[tuple[str, bool, str]]:
    """The paragraphs deleted as Word deletes them whose bookmark has a block to stand in
    front of: each is an identified paragraph, "deleted", and the block after it is not
    deleted in the same session. For each: that block's word, whether it has an identifier
    of its own, and what was done to it, "" for nothing.

    "Deleted" alone does not say it. A caption has no bookmark to leave, and the last
    paragraph of a document has nowhere to leave one (`_edited_in_word` in
    `tests/readings.py`), so for those the word stands for the same document as "deleted
    and gone".

    Nor does "the block after, reworded" say what the import makes of it. Where that
    block has no identifier of its own and nothing else is going on, the bookmark left on
    it is the only one it carries, and the import cannot tell the deleted paragraph
    reworded from the text that stood under it: the case #121 was about. Where the block
    is an identified paragraph it carries two, and the import reads two paragraphs joined
    into one. That much is the shape, and is what is asked of the generator.

    The shape does not settle it. The import also reads a join where a second paragraph
    deleted the same way stood in front of the first, since both bookmarks are passed on;
    it can tell which is which where the block is a heading; and it refuses for another
    reason where that block was reworded in the source since the build. So of the sessions
    the import is played on, the case of #121 is asked for by what the import said
    (`_refused_as_in_121`)."""
    kind, did = _kinds(session), dict(session["in_word"])
    order = [block["tag"] for block in session["blocks"]]
    return [
        (after, kind[after] in IDENTIFIED, did.get(after, ""))
        for tag, after in zip(order, order[1:], strict=False)
        if did.get(tag) == "deleted"
        and kind[tag] in IDENTIFIED
        and did.get(after, "reworded") == "reworded"
    ]


def _since(session: Session) -> str:
    return session["since"][0] if session["since"] else ""


def _left_on(session: Session, *, identified: bool) -> list[str]:
    """The reworded blocks of a session that a deleted paragraph's bookmark was left on:
    those with an identifier of their own, or those without."""
    return [
        after
        for after, has_its_own, how in _left_by_word(session)
        if has_its_own == identified and how == "reworded"
    ]


#: What #121 made the import say of a paragraph it cannot tell from the block under it,
#: up to where it quotes that block.
_UNDER_IT = "or the text that stood under it when the document was sent ('The {tag} reports"


def _refused_as_in_121(session: Session, said: str) -> bool:
    """Whether the import said, of a block of this session that stands as in the case of
    #121, what #121 made it say. Every block of a generated paper begins "The", its own
    word, "reports", and the import quotes the block, so the sentence names which one."""
    return any(
        _UNDER_IT.format(tag=after) in said for after in _left_on(session, identified=False)
    )


#: What the import is taken to have said where only the draw is known: #121's sentence, of
#: every block there is.
_SAID_OF_ALL = " ".join(_UNDER_IT.format(tag=tag) for tag in TAGS)

_LEFT = "a paragraph deleted as Word deletes it, its bookmark left on the block after"
_ON_NO_IDENTIFIER = "the same on a reworded block with no identifier: the shape of #121's case"
_AS_A_JOIN = "the same on a reworded paragraph, which carries two bookmarks then"
_AS_IN_121 = "the case of #121, with the import saying that nothing tells which paragraph it is"

#: What `sessions()` has to draw, each by the name a failure gives it.
DRAWN: dict[str, Callable[[Session], bool]] = {
    **{
        f"a block typed as: {kind}": lambda session, kind=kind: kind in _kinds(session).values()
        for kind in SAYS
    },
    "a paragraph reworded": lambda session: "reworded" in _done(session, identified=True),
    "a paragraph deleted with its bookmark": lambda session: (
        "deleted and gone" in _done(session, identified=True)
    ),
    _LEFT: lambda session: bool(_left_by_word(session)),
    _ON_NO_IDENTIFIER: lambda session: bool(_left_on(session, identified=False)),
    _AS_A_JOIN: lambda session: bool(_left_on(session, identified=True)),
    "a block with no identifier reworded": lambda session: (
        "reworded" in _done(session, identified=False)
    ),
    "a block with no identifier deleted": lambda session: bool(
        _done(session, identified=False) - {"reworded"}
    ),
    "a source left as it was built": lambda session: _since(session) == "",
    "a block reworded in the source since the build": lambda session: (
        _since(session) == "reworded"
    ),
    "a block removed from the source since the build": lambda session: (
        _since(session) == "removed"
    ),
    "a paragraph added to the source since the build": lambda session: (
        _since(session) == "added above"
    ),
}

_DELETED_AND_WRITTEN = "a block deleted, and a rewording written"
_GONE_AND_WRITTEN = "a paragraph deleted with its bookmark, and a rewording written"
_FORCED_AND_WRITTEN = "an import that had to be forced, and wrote"

#: What the twelve sessions the property plays have to have among them, by the same kind
#: of name: of each session, of whether the import wrote anything in it, and of what the
#: import said.
PLAYED: dict[str, Callable[[Session, bool, str], bool]] = {
    _AS_IN_121: lambda session, wrote, said: _refused_as_in_121(session, said),
    _DELETED_AND_WRITTEN: lambda session, wrote, said: (
        wrote and any(how != "reworded" for _tag, how in session["in_word"])
    ),
    _GONE_AND_WRITTEN: lambda session, wrote, said: (
        wrote and "deleted and gone" in _done(session, identified=True)
    ),
    _FORCED_AND_WRITTEN: lambda session, wrote, said: wrote and _since(session) != "",
}
#: In how many of the twelve the import has to write, to say anything of where it writes.
WRITES_IN = 3


def _lacking(asked: dict[str, Callable[..., bool]], run: Iterable[tuple[Any, ...]]) -> list[str]:
    """The names of `asked` that nothing in `run` has."""
    run = list(run)
    return [name for name, has in asked.items() if not any(has(*item) for item in run)]


def test_sessions_draws_every_session_the_property_is_for() -> None:
    """What `sessions()` draws, asked of the generator and not of the twelve the import
    is played on. Two thousand sessions are drawn and nothing is built, so it does not
    hang on one draw: under each of thirty seeds tried, the rarest thing here, the shape
    of #121's case, was drawn twelve times or more. Six hundred were not enough for that
    one: under one seed of thirty they had it once.

    A generator that stopped drawing one of these would leave the property passing on
    sessions that cannot show what it is for, which is how it stood when every check that
    a broken import is noticed was decided by the simplest session alone."""
    drawn: list[tuple[Session]] = []

    @generated(2000)
    @given(sessions())
    def collect(session: Session) -> None:
        drawn.append((session,))

    collect()
    lacking = _lacking(DRAWN, drawn)
    assert not lacking, f"of {len(drawn)} sessions drawn, none has: {lacking}"


def test_the_twelve_sessions_are_the_ones_the_property_is_for() -> None:
    """The twelve sessions the import is played on, and where it wrote among them.

    Hypothesis plays the simplest value of a strategy first: three paragraphs, the first
    reworded, nothing changed since. A run of twelve like it would pass the property and
    say nothing. So the twelve are held to having the session the reviews of #121 found
    wrong writes on, a paragraph deleted in Word in front of a reworded block that has no
    identifier of its own, with the import saying of it what #121 made it say; and to the
    import having written beside a deletion, beside a paragraph that went with its
    bookmark, and when it was forced."""
    if not _as_pinned():
        pytest.skip("another draw than the twelve of PINNED: what it has in it is chance")
    run = _the_run()
    # The seed and nothing in the property's text: another test, drawn from it, draws them.
    assert [session for session, _wrote, _said in run] == _twelve_of(PINNED)
    amiss = _amiss(run)
    if amiss:
        pytest.fail(amiss)


def _amiss(run: Iterable[Played], *, among: Iterable[int] | None = None) -> str:
    """What a run of the pinned twelve lacks, as the message the test fails with, or
    nothing where the twelve have what is asked and the import wrote in enough of them.
    `among` are the numbers looked through for ones worth pinning: the next forty."""
    run = list(run)
    lacking = _lacking(PLAYED, run)
    wrote = sum(1 for _session, wrote, _said in run if wrote)
    if not lacking and wrote >= WRITES_IN:
        return ""
    among = range(PINNED + 1, PINNED + 41) if among is None else among
    return (
        f"the twelve sessions of seed {PINNED} lack: {lacking}; the import wrote in "
        f"{wrote} of them, and {WRITES_IN} is the least.\n"
        "The twelve are fixed by PINNED in this file, by sessions() in tests/generated.py, "
        "by TAGS and SAYS in tests/readings.py, which it draws from, and by the pin of "
        "Hypothesis in pyproject.toml. If one of those has changed, these are twelve other "
        "sessions and nothing is wrong with the import: set PINNED to a number whose "
        "twelve have all of this again. By the draw alone these have the sessions asked "
        f"for: {_worth_trying(among)}. Where the import then writes is a run of this test "
        f"for each, and {_HAS_IT_ALL} of them has it all. If none of those has changed, the "
        "import no longer writes where it wrote or no longer says of the case of #121 what "
        "it said, or _edited_in_word in tests/readings.py no longer edits the document as "
        "it did."
    )


def _twelve_of(number: int) -> list[Session]:
    """The twelve sessions a seed draws, with nothing played."""
    drawn: list[Session] = []

    @generated(12, pinned=number)
    @given(sessions())
    def collect(session: Session) -> None:
        drawn.append(session)

    collect()
    return drawn


def _worth_trying(seeds: Iterable[int]) -> list[int]:
    """The seeds whose twelve have, by the draw alone, the sessions `PLAYED` asks for:
    every session is counted as one the import wrote in, and said #121's sentence of.
    Whether it does is a run of the property, which takes most of a minute, and this
    takes a moment."""
    return [
        number
        for number in seeds
        if not _lacking(PLAYED, [(s, True, _SAID_OF_ALL) for s in _twelve_of(number)])
    ]


#: The first session Hypothesis plays, whatever the seed: the simplest value of `sessions()`.
_SIMPLEST = {
    "blocks": [{"tag": tag, "kind": "paragraph"} for tag in ("alpha", "bravo", "charlie")],
    "in_word": [["alpha", "reworded"]],
    "since": None,
}
#: A session with a paragraph deleted in Word in front of a reworded line block, which has
#: the shape of #121's case, another gone with its bookmark, and a source changed since.
_BUSY = {
    "blocks": [
        {"tag": "alpha", "kind": "second paragraph"},
        {"tag": "bravo", "kind": "lines"},
        {"tag": "charlie", "kind": "second paragraph"},
        {"tag": "delta", "kind": "heading"},
    ],
    "in_word": [["alpha", "deleted"], ["bravo", "reworded"], ["charlie", "deleted and gone"]],
    "since": ["removed", "delta"],
}


def test_each_thing_asked_of_the_sessions_is_named_when_it_is_missing() -> None:
    """The two checks above pass when nothing is lacking, so each thing they ask has to
    be seen lacking, by its name. The first form of this check was tested with twelve
    copies of the simplest session and any failure at all, which reached its first line."""
    in_the_simplest = {
        "a block typed as: paragraph",
        "a paragraph reworded",
        "a source left as it was built",
    }
    assert set(_lacking(DRAWN, [(_SIMPLEST,)] * 12)) == set(DRAWN) - in_the_simplest
    assert in_the_simplest <= set(_lacking(DRAWN, [(_BUSY,)]))

    assert _lacking(PLAYED, [(_SIMPLEST, True, _SAID_OF_ALL)] * 12) == list(PLAYED)
    assert _lacking(PLAYED, [(_BUSY, True, _SAID_OF_ALL)]) == []
    # The same session with nothing written: what is asked of where the import wrote is
    # lacking, and the rest is not.
    assert _lacking(PLAYED, [(_BUSY, False, _SAID_OF_ALL)]) == [
        _DELETED_AND_WRITTEN,
        _GONE_AND_WRITTEN,
        _FORCED_AND_WRITTEN,
    ]
    # And with the shape of #121's case but not its sentence, or the sentence of another
    # block than the one the bookmark was left on: twelve that passed under #121's name
    # without the import ever saying it are what two of the six seeds first listed were.
    of_bravo, of_delta = (_UNDER_IT.format(tag=tag) for tag in ("bravo", "delta"))
    assert _lacking(PLAYED, [(_BUSY, True, "deleted in Word, left in place here")]) == [
        _AS_IN_121
    ]
    assert _lacking(PLAYED, [(_BUSY, True, f"NOT merged: {of_delta} of')")]) == [_AS_IN_121]
    assert _lacking(PLAYED, [(_BUSY, True, f"NOT merged: {of_bravo} of')")]) == []
    # A deletion that leaves no bookmark is not the one asked for, though it is drawn
    # under the same word: of a caption, which has none; of the last block, which has
    # nowhere to leave it; and in front of a block that is deleted with it.
    for kinds, in_word in (
        (("paragraph", "caption", "paragraph"), [["bravo", "deleted"]]),
        (("paragraph", "paragraph"), [["bravo", "deleted"]]),
        (
            ("paragraph", "paragraph", "paragraph"),
            [["alpha", "deleted"], ["bravo", "deleted and gone"]],
        ),
    ):
        blocks = [{"tag": tag, "kind": kind} for tag, kind in zip(TAGS, kinds, strict=False)]
        in_name_only = {"blocks": blocks, "in_word": in_word, "since": None}
        assert _LEFT in _lacking(DRAWN, [(in_name_only,)]), in_name_only
    # A bookmark left on an identified paragraph is two paragraphs joined, and has not
    # the shape of #121's case, which it was counted as; one left on a line block has, and
    # is no join.
    joined = {
        "blocks": [{"tag": tag, "kind": "paragraph"} for tag in TAGS[:3]],
        "in_word": [["alpha", "deleted"], ["bravo", "reworded"]],
        "since": None,
    }
    assert _AS_IN_121 in _lacking(PLAYED, [(joined, True, _SAID_OF_ALL)])
    both = {_ON_NO_IDENTIFIER, _AS_A_JOIN}
    assert both & set(_lacking(DRAWN, [(joined,)])) == {_ON_NO_IDENTIFIER}
    assert both & set(_lacking(DRAWN, [(_BUSY,)])) == {_AS_A_JOIN}


def test_twelve_other_sessions_fail_with_the_whole_message() -> None:
    """After a redraw the twelve most often lack a session by the draw alone. The first
    form of the test then stopped at a bare assertion that stood in front of its message,
    and no test ran either way of failing. Both give the whole message: what is lacking,
    everything that fixes the twelve, and the numbers worth pinning in place of this one."""
    few = range(PINNED, PINNED + 3)
    simplest, busy = (_SIMPLEST, True, _SAID_OF_ALL), (_BUSY, True, _SAID_OF_ALL)
    lacking_a_session = _amiss([simplest] * 12, among=few)
    written_in_too_few = _amiss([busy] + [(_SIMPLEST, False, "")] * 11, among=few)
    for said in (lacking_a_session, written_in_too_few):
        for named in ("PINNED", "sessions()", "TAGS", "SAYS", "pin of Hypothesis"):
            assert named in said, (named, said)
        assert "twelve other sessions" in said and "_edited_in_word" in said, said
        assert f"asked for: {_worth_trying(few)}." in said, said
    assert _AS_IN_121 in lacking_a_session and "wrote in 12 of them" in lacking_a_session
    assert "lack: [];" in written_in_too_few and "wrote in 1 of them" in written_in_too_few
    assert _amiss([busy] * WRITES_IN, among=few) == ""
    # The numbers the message gives are the helper's, and were held to nothing but
    # themselves. The number pinned is one of them, the next is not, and left to itself
    # the message looks through the forty after the one pinned.
    if _as_pinned():
        assert PINNED in _worth_trying(few) and PINNED + 1 not in _worth_trying(few)
        after = _worth_trying(range(PINNED + 1, PINNED + 41))
        assert after and f"asked for: {after}." in _amiss([simplest] * 12)


def test_a_document_only_saved_changes_nothing_and_one_rewording_lands() -> None:
    """The two sessions every other one is measured from, written out. A document that
    comes back as it was sent leaves the source alone. And the plainest edit there is, one
    word in one paragraph of a paper nobody else touched, lands: the property above would
    hold of an import that wrote nothing at all, and this is what says it writes."""
    blocks = [
        {"tag": "alpha", "kind": "paragraph"},
        {"tag": "bravo", "kind": "heading"},
        {"tag": "charlie", "kind": "paragraph"},
    ]
    saved = answer(_round_trip(), {"blocks": blocks, "in_word": [], "since": None})["answer"]
    assert saved["after"] == saved["before"], saved["said"]

    reworded = {"blocks": blocks, "in_word": [["charlie", "reworded"]], "since": None}
    found = answer(_round_trip(), reworded)["answer"]
    was = "The charlie reports of hepatic injury were counted once in each group."
    assert was in found["before"]
    assert found["after"] == found["before"].replace(was, was.replace(WAS, NOW)), found["said"]


# ----------------------------------------------- the property fails when the import is broken


def _the_next_paragraph_takes_it(patch: pytest.MonkeyPatch) -> None:
    """Whatever is merged is written over the paragraph after the one it belongs to."""
    real = merge._edits

    def edits(known: dict, plan: Any, occupants: list) -> list[tuple]:
        slots = sorted(known.values(), key=lambda paragraph: paragraph[2])
        shifted = []
        for start, _end, replacement, name in real(known, plan, occupants):
            at = next(index for index, slot in enumerate(slots) if slot[2] == start)
            _path, original, begin = slots[(at + 1) % len(slots)]
            shifted.append((begin, begin + len(original), replacement, name))
        return sorted(shifted)

    patch.setattr(merge, "_edits", edits)


def _it_is_written_twice(patch: pytest.MonkeyPatch) -> None:
    """Whatever is merged is written where it belongs, and again at the end of the file."""
    real = merge._spliced

    def spliced(text: str, edits: list[tuple]) -> str:
        again = "".join(f"\n{replacement}\n" for _start, _end, replacement, _name in edits)
        return real(text, edits) + again

    patch.setattr(merge, "_spliced", spliced)


def _where_a_paragraph_is_gone_the_next_takes_it(patch: pytest.MonkeyPatch) -> None:
    """Where an identified paragraph did not come back at all, whatever is merged is
    written over the paragraph after the one it belongs to. `plan.gone` is what says so:
    in a drawn session, a paragraph "deleted and gone", or deleted as the last block.
    Where every identifier came back the import is as it should be, so the simplest
    session, which deletes nothing, cannot show this."""
    real = merge._edits

    def edits(known: dict, plan: Any, occupants: list) -> list[tuple]:
        found = real(known, plan, occupants)
        if not plan.gone:
            return found
        slots = sorted(known.values(), key=lambda paragraph: paragraph[2])
        shifted = []
        for start, _end, replacement, name in found:
            at = next(index for index, slot in enumerate(slots) if slot[2] == start)
            _path, original, begin = slots[(at + 1) % len(slots)]
            shifted.append((begin, begin + len(original), replacement, name))
        return sorted(shifted)

    patch.setattr(merge, "_edits", edits)


_ONLY_WHERE_ONE_IS_GONE = "where a paragraph is gone, a rewording is written over the next one"
#: A way of breaking the import, and the sentence only that wrong write produces.
BROKEN = {
    "a rewording is written over the next paragraph": (_the_next_paragraph_takes_it, "became"),
    "a rewording is written a second time": (_it_is_written_twice, "blocks where there were"),
    _ONLY_WHERE_ONE_IS_GONE: (_where_a_paragraph_is_gone_the_next_takes_it, "became"),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_the_property_fails_when_an_import_writes_what_it_should_not(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sessions decide whether the property can fail: one in which nothing is ever
    merged would let any import through. Each case makes `import` write wrongly, and some
    session of the twelve has to show it, by the sentence that wrong write produces.

    The first two are shown by the first session played, which is the simplest there is,
    so they hold nothing of the eleven that are drawn. The third writes wrongly only where
    an identified paragraph did not come back: it passes the simplest session and has to
    be caught by a drawn one. Whether twelve other sessions have one that can is chance,
    so under another draw than the pinned one that case is passed over."""
    if case == _ONLY_WHERE_ONE_IS_GONE and not _as_pinned():
        pytest.skip("another draw than the twelve of PINNED: none of it may show this")
    break_it, says = BROKEN[case]
    break_it(monkeypatch)
    _PLAYED.clear()
    with pytest.raises(AssertionError, match=says):
        what_is_written_is_what_was_typed.at_first_failure()
    if case == _ONLY_WHERE_ONE_IS_GONE:
        # The count of sessions played would not say it: the one that fails is played
        # again to be reported.
        (first, _, _), (failing, _, _) = _PLAYED[0], _PLAYED[-1]
        assert first == _SIMPLEST, first
        assert failing != first, "the simplest session showed it, so no drawn one had to"
        assert _done(failing, identified=True) - {"reworded"}, failing


def test_an_import_that_raises_is_not_taken_for_one_that_writes_wrongly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cases above reach into `merge.py` by private names. When one of those takes
    other arguments, the stand-in raises inside the import, the property fails on that,
    and a test that matched any failing assertion stayed green while showing nothing about
    wrong writes. An import that raises fails the property, and with none of the sentences
    a wrong write is known by."""

    def edits(known: dict, plan: Any) -> list[tuple]:  # one argument fewer than it is given
        return []

    monkeypatch.setattr(merge, "_edits", edits)
    with pytest.raises(AssertionError) as failed:
        what_is_written_is_what_was_typed.at_first_failure()
    assert "TypeError" in str(failed.value), failed.value
    for _break_it, says in BROKEN.values():
        assert not re.search(says, str(failed.value)), says
