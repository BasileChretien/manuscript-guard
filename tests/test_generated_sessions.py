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

import re
import shutil
from functools import cache
from typing import Any

import pytest
from generated import holds, sessions
from hypothesis import event
from readings import NOW, READINGS, TAGS, WAS, Reading, answer

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


@holds(12, sessions())
def test_what_an_import_writes_is_what_the_co_author_typed_where_they_typed_it(
    session: dict[str, Any],
) -> None:
    found = answer(_round_trip(), session)
    assert "raised" not in found, (found, session)
    found = found["answer"]
    assert "before" in found, f"the paper did not build: {found}"
    said = found["said"]
    assert "Traceback" not in said, said

    did = dict(session["in_word"])
    was, now = _blocks(found["before"]), _blocks(found["after"])
    event("something was written" if now != was else "nothing was written")
    event("the source changed since the build" if session["since"] else "the source is as built")
    assert len(now) == len(was), f"{session}\n{said}\n{found['before']}\n{found['after']}"
    for old, new in zip(was, now, strict=True):
        if new == old:
            continue
        tag = next((tag for tag in TAGS if f" {tag} " in f" {old} "), None)
        assert did.get(tag) == "reworded" and new == old.replace(WAS, NOW, 1), (
            f"{old!r} became {new!r}\n{session}\n{said}"
        )


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


BROKEN = {
    "a rewording is written over the next paragraph": _the_next_paragraph_takes_it,
    "a rewording is written a second time": _it_is_written_twice,
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_the_property_fails_when_an_import_writes_what_it_should_not(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sessions decide whether the property can fail: one in which nothing is ever
    merged would let any import through. Each case makes `import` write wrongly, and some
    session of the twelve has to show it."""
    BROKEN[case](monkeypatch)
    held = test_what_an_import_writes_is_what_the_co_author_typed_where_they_typed_it
    with pytest.raises(AssertionError, match="became|assert"):
        held.at_first_failure()
