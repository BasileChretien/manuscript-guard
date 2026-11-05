"""The part of a paragraph `import` shows for an edit: `manuscript_guard.preview`."""

from __future__ import annotations

from manuscript_guard.preview import CONTEXT, MOST, changes, opening

_FILLER = " ".join(f"word{n}" for n in range(40))


def test_a_change_is_shown_with_a_few_words_either_side() -> None:
    was = f"{_FILLER} the old word here {_FILLER}"
    now = f"{_FILLER} the new word here {_FILLER}"
    (shown,), more = changes(was, now)
    assert more == 0
    assert shown == (
        "... word36 word37 word38 word39 the old word here word0 word1 word2 ...",
        "... word36 word37 word38 word39 the new word here word0 word1 word2 ...",
    )


def test_a_binding_or_a_citation_is_never_cut() -> None:
    """Cut by characters, the dry run once ended inside a binding, `{{results.hs.any_ill`.
    A binding, a bracketed citation and a parenthesis, spaces and all, are each one word:
    shown whole or left out."""
    words = ["{{results.a.b}}%", "[@one; @two, p. 4]", "(Fictional 2021)", "plain"] * 3
    was = " ".join([*words, "before", *words])
    now = " ".join([*words, "after", *words])
    (shown,), _more = changes(was, now)
    assert "before" in shown[0] and "after" in shown[1]
    for line in shown:
        inner = line.removeprefix("... ").removesuffix(" ...")
        assert inner.count("{{") == inner.count("}}") == inner.count("%")
        assert inner.count("[") == inner.count("]")
        assert inner.count("(") == inner.count(")")


def test_a_paragraph_rewritten_whole_is_shown_whole() -> None:
    """Every word changed is shown, however many: shown by its two ends, a rewrite hid the
    words between them."""
    was = " ".join(f"old{n}" for n in range(100))
    now = " ".join(f"new{n}" for n in range(100))
    ((removed, added),), _more = changes(was, now)
    assert (removed, added) == (was, now)


def test_no_changed_word_is_left_out_of_a_sentence_copy_edited_word_by_word() -> None:
    """Edits ten words apart or fewer are one stretch, and a stretch over forty words was
    shown by its two ends: an edit in its middle was not printed, nor counted among the
    stretches not shown, and `--apply` wrote it all the same. Every changed word is shown;
    a stretch is never cut in its middle."""
    words = [f"w{n}" for n in range(60)]
    edited = list(words)
    for n in (11, 19, 28, 37, 46):
        edited[n] = f"E{n}"
    ((removed, added),), more = changes(" ".join(words), " ".join(edited))
    assert more == 0
    assert all(f" E{n} " in f" {added} " for n in (11, 19, 28, 37, 46)), added
    assert all(f" w{n} " in f" {removed} " for n in (11, 19, 28, 37, 46)), removed
    assert added.startswith("... w6 ") and added.endswith(" w51 ...")


def test_changes_past_the_most_shown_are_counted() -> None:
    was = " ".join(f"{_FILLER} kept{n}" for n in range(MOST + 2))
    now = " ".join(f"{_FILLER} edited{n}" for n in range(MOST + 2))
    shown, more = changes(was, now)
    assert len(shown) == MOST and more == 2
    assert [added.split()[CONTEXT + 1] for _removed, added in shown] == [
        f"edited{n}" for n in range(MOST)
    ]


def test_nothing_is_shown_where_the_words_are_the_same() -> None:
    """A change of spacing alone, which Word makes, is no change of words."""
    assert changes("one two\nthree", "one  two three") == ([], 0)


def test_the_generated_edits_are_drawn_for_the_context_shown() -> None:
    """`generated.previewed_edits` writes the context down rather than reading it, so that a
    rule broken by changing it does not draw other inputs; the two are held equal here."""
    from generated import PREVIEW_CONTEXT

    assert PREVIEW_CONTEXT == CONTEXT


def test_an_opening_is_cut_between_words() -> None:
    text = "Alpha {{results.a}} [@k; @l] " + _FILLER
    assert opening(text, 3) == "Alpha {{results.a}} [@k; @l] ..."
    assert opening("Short text.") == "Short text."
    assert opening("") == ""
