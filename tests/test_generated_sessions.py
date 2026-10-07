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
What `sessions()` draws at all is asked of six hundred sessions that are only drawn. And
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
#: So the twelve are fixed by this number, by `sessions()` in `tests/generated.py` and by
#: the pin of Hypothesis in `pyproject.toml`, and by nothing else. When one of those
#: changes, `test_the_twelve_sessions_are_the_ones_the_property_is_for` may fail on twelve
#: other sessions: its message says so, and which numbers are worth trying.
#:
#: How it was chosen: of the numbers 0 to 59, twenty-five draw twelve with the sessions
#: asked for. Ten of those were played through the import, and with two of them, 5 and
#: 22, it wrote everywhere it is asked to.
PINNED = 5


@cache
def _round_trip() -> Reading:
    return READINGS["import"]()


def _blocks(text: str) -> list[str]:
    return [" ".join(block.split()) for block in re.split(r"\n[ \t]*\n", text) if block.strip()]


#: The sessions the property played last, each with whether the import wrote anything.
_PLAYED: list[tuple[Session, bool]] = []


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
    _PLAYED.append((session, now != was))
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
def _the_run() -> tuple[tuple[Session, bool], ...]:
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


def _left_by_word(session: Session) -> list[str]:
    """The paragraphs deleted as Word deletes them whose bookmark has a block to stand in
    front of: each is an identified paragraph, "deleted", and the block after it is not
    deleted in the same session. For each, what was done to that block, "" for nothing.

    "Deleted" alone does not say it. A caption has no bookmark to leave, and the last
    paragraph of a document has nowhere to leave one (`_edited_in_word` in
    `tests/readings.py`), so for those the word stands for the same document as "deleted
    and gone"."""
    kind, did = _kinds(session), dict(session["in_word"])
    order = [block["tag"] for block in session["blocks"]]
    return [
        did.get(after, "")
        for tag, after in zip(order, order[1:], strict=False)
        if did.get(tag) == "deleted"
        and kind[tag] in IDENTIFIED
        and did.get(after, "reworded") == "reworded"
    ]


def _since(session: Session) -> str:
    return session["since"][0] if session["since"] else ""


_LEFT = "a paragraph deleted as Word deletes it, its bookmark left on the block after"
_LEFT_ON_A_REWORDING = "the same with the block after reworded, which is the session of #121"

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
    _LEFT_ON_A_REWORDING: lambda session: "reworded" in _left_by_word(session),
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
#: of name: of each session, and of whether the import wrote anything in it.
PLAYED: dict[str, Callable[[Session, bool], bool]] = {
    _LEFT: lambda session, wrote: bool(_left_by_word(session)),
    _LEFT_ON_A_REWORDING: lambda session, wrote: "reworded" in _left_by_word(session),
    _DELETED_AND_WRITTEN: lambda session, wrote: (
        wrote and any(how != "reworded" for _tag, how in session["in_word"])
    ),
    _GONE_AND_WRITTEN: lambda session, wrote: (
        wrote and "deleted and gone" in _done(session, identified=True)
    ),
    _FORCED_AND_WRITTEN: lambda session, wrote: wrote and _since(session) != "",
}
#: In how many of the twelve the import has to write, to say anything of where it writes.
WRITES_IN = 3


def _lacking(asked: dict[str, Callable[..., bool]], run: Iterable[tuple[Any, ...]]) -> list[str]:
    """The names of `asked` that nothing in `run` has."""
    run = list(run)
    return [name for name, has in asked.items() if not any(has(*item) for item in run)]


def test_sessions_draws_every_session_the_property_is_for() -> None:
    """What `sessions()` draws, asked of the generator and not of the twelve the import
    is played on. Six hundred sessions are drawn and nothing is built, so it does not
    hang on one draw: under each of fifty seeds tried, the rarest thing here, the session
    of #121, was drawn five times or more, and everything else twenty-four times or more.

    A generator that stopped drawing one of these would leave the property passing on
    sessions that cannot show what it is for, which is how it stood when every check that
    a broken import is noticed was decided by the simplest session alone."""
    drawn: list[tuple[Session]] = []

    @generated(600)
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
    say nothing. So the twelve are held to having the session the reviews found wrong
    writes on, a paragraph deleted in Word in front of a block that reads like it, and to
    the import having written beside a deletion, beside a paragraph that went with its
    bookmark, and when it was forced."""
    if not _as_pinned():
        pytest.skip("another draw than the twelve of PINNED: what it has in it is chance")
    run = _the_run()
    # The seed and nothing in the property's text: another test, drawn from it, draws them.
    assert [session for session, _wrote in run] == _twelve_of(PINNED)
    assert _worth_trying([PINNED]) == [PINNED]
    lacking = _lacking(PLAYED, run)
    wrote = sum(1 for _session, wrote in run if wrote)
    if lacking or wrote < WRITES_IN:
        pytest.fail(
            f"the twelve sessions of seed {PINNED} lack: {lacking}; the import wrote in "
            f"{wrote} of them, and {WRITES_IN} is the least.\n"
            "The twelve are fixed by PINNED in this file, by sessions() in "
            "tests/generated.py and by the pin of Hypothesis in pyproject.toml. If one of "
            "those has changed, these are twelve other sessions and nothing is wrong with "
            "the import: set PINNED to a number whose twelve have all of this again. By "
            "the draw alone these of the next forty have the sessions asked for: "
            f"{_worth_trying(range(PINNED + 1, PINNED + 41))}. Where the import then writes "
            "is a run of this test for each, and about one in five of them has it all. If "
            "none of the three has changed, the import no longer writes where it wrote."
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
    every session is counted as one the import wrote in. Whether it does is a run of the
    property, which takes most of a minute, and this takes a moment."""
    return [
        number
        for number in seeds
        if not _lacking(PLAYED, [(session, True) for session in _twelve_of(number)])
    ]


#: The first session Hypothesis plays, whatever the seed: the simplest value of `sessions()`.
_SIMPLEST = {
    "blocks": [{"tag": tag, "kind": "paragraph"} for tag in ("alpha", "bravo", "charlie")],
    "in_word": [["alpha", "reworded"]],
    "since": None,
}
#: A session with a paragraph deleted in Word in front of a reworded block, another gone
#: with its bookmark, and a source changed since the build.
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
    assert set(_lacking(DRAWN, [(_SIMPLEST,)] * 600)) == set(DRAWN) - in_the_simplest
    assert in_the_simplest <= set(_lacking(DRAWN, [(_BUSY,)]))

    assert _lacking(PLAYED, [(_SIMPLEST, True)] * 12) == list(PLAYED)
    assert _lacking(PLAYED, [(_BUSY, True)]) == []
    # The same session with nothing written: what is asked of the import is lacking, and
    # what is asked of the draw is not.
    assert _lacking(PLAYED, [(_BUSY, False)]) == [
        _DELETED_AND_WRITTEN,
        _GONE_AND_WRITTEN,
        _FORCED_AND_WRITTEN,
    ]
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
        assert _LEFT in _lacking(PLAYED, [(in_name_only, True)]), in_name_only
        assert _LEFT in _lacking(DRAWN, [(in_name_only,)]), in_name_only


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
        (first, _), (failing, _) = _PLAYED[0], _PLAYED[-1]
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
