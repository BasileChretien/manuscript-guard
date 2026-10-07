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
seconds, so a run has few. `MANUSCRIPT_GUARD_MORE_EXAMPLES` draws more.
"""

from __future__ import annotations

import os
import re
import shutil
from functools import cache
from typing import Any

import pytest
from generated import SEED, holds, sessions, times
from hypothesis import event
from readings import NOW, READINGS, SAYS, TAGS, WAS, Reading, answer

from manuscript_guard import merge

pytestmark = [
    pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed"),
    pytest.mark.usefixtures("stopped_if_stuck"),
]


@cache
def _round_trip() -> Reading:
    return READINGS["import"]()


def _blocks(text: str) -> list[str]:
    return [" ".join(block.split()) for block in re.split(r"\n[ \t]*\n", text) if block.strip()]


#: The sessions the property played last, each with whether the import wrote anything.
_PLAYED: list[tuple[dict[str, Any], bool]] = []


@holds(12, sessions())
def what_is_written_is_what_was_typed(session: dict[str, Any]) -> None:
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
    event("something was written" if now != was else "nothing was written")
    event("the source changed since the build" if session["since"] else "the source is as built")
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


def test_what_an_import_writes_is_what_the_co_author_typed_where_they_typed_it() -> None:
    """The property over its twelve sessions, and then the twelve themselves.

    Hypothesis plays the simplest value of a strategy first: three paragraphs, the first
    reworded, nothing changed since. Every check that a broken import is noticed was
    decided by that one session, so the suite held nothing of the other eleven, which are
    the ones the sessions were written for. What they are is held here: every kind of
    block, each thing a co-author does and each thing an author does meanwhile, and among
    the sessions that write something, one with a paragraph deleted and one that had to be
    forced. A generator that stopped drawing any of these fails here and not in silence."""
    _PLAYED.clear()
    what_is_written_is_what_was_typed()
    if times() != 1 or os.environ.get(SEED, "").strip():
        return  # another draw than the one described above; the property is what is held
    _drawn_as_meant(_PLAYED)


def _drawn_as_meant(run: list[tuple[dict[str, Any], bool]]) -> None:
    """Hold the sessions of a run, each with whether the import wrote anything, to what
    the sessions were written for."""
    played = [session for session, _wrote in run]
    wrote = [session for session, wrote in run if wrote]

    def done(session: dict[str, Any]) -> set[str]:
        return {how for _tag, how in session["in_word"]}

    def touched(session: dict[str, Any]) -> set[str]:
        kinds = {block["tag"]: block["kind"] for block in session["blocks"]}
        return {kinds[tag] for tag, _how in session["in_word"]}

    assert {block["kind"] for session in played for block in session["blocks"]} == set(SAYS)
    assert set().union(*map(done, played)) == {"reworded", "deleted", "deleted and gone"}
    assert {session["since"][0] for session in played if session["since"]} == {
        "reworded",
        "removed",
        "added above",
    }
    with_no_identifier = set(SAYS) - {"paragraph", "second paragraph"}
    assert any(touched(session) & with_no_identifier for session in played)
    assert len(wrote) >= 3, "the import wrote in too few sessions to say much of where"
    assert any(done(session) - {"reworded"} for session in wrote), (
        "no session both deletes a block and has a rewording written"
    )
    assert any(session["since"] for session in wrote), "no forced import wrote anything"


#: The first session Hypothesis plays, whatever the seed: the simplest value of `sessions()`.
_SIMPLEST = {
    "blocks": [{"tag": tag, "kind": "paragraph"} for tag in ("alpha", "bravo", "charlie")],
    "in_word": [["alpha", "reworded"]],
    "since": None,
}


def test_a_run_of_the_simplest_session_is_not_what_has_to_be_drawn() -> None:
    """What the check above is for: twelve sessions that are all the simplest one, with a
    rewording written in each, pass every other test of this file and fail it."""
    with pytest.raises(AssertionError):
        _drawn_as_meant([(_SIMPLEST, True)] * 12)


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


def _beside_a_deletion_the_next_paragraph_takes_it(patch: pytest.MonkeyPatch) -> None:
    """Where a paragraph was deleted in Word, whatever is merged is written over the
    paragraph after the one it belongs to. Without a deletion the import is as it should
    be, so the simplest session, which has none, cannot show this."""
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


_ONLY_BESIDE_A_DELETION = "beside a deleted paragraph, a rewording is written over the next one"
#: A way of breaking the import, and the sentence only that wrong write produces.
BROKEN = {
    "a rewording is written over the next paragraph": (_the_next_paragraph_takes_it, "became"),
    "a rewording is written a second time": (_it_is_written_twice, "blocks where there were"),
    _ONLY_BESIDE_A_DELETION: (_beside_a_deletion_the_next_paragraph_takes_it, "became"),
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
    a paragraph was deleted in Word: it passes the simplest session and has to be caught
    by a drawn one."""
    break_it, says = BROKEN[case]
    break_it(monkeypatch)
    _PLAYED.clear()
    with pytest.raises(AssertionError, match=says):
        what_is_written_is_what_was_typed.at_first_failure()
    if case == _ONLY_BESIDE_A_DELETION:
        # The count of sessions played would not say it: the one that fails is played
        # again to be reported.
        (first, _), (failing, _) = _PLAYED[0], _PLAYED[-1]
        assert first == _SIMPLEST, first
        assert failing != first, "the simplest session showed it, so no drawn one had to"
        assert {how for _tag, how in failing["in_word"]} - {"reworded"}, failing


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
