"""Where a finding's sentence stands in the paper, the part its key's digest is taken in
(`keys.part_of`): the Abstract under its heading, a structured Abstract's own parts, a
heading's name alone on a line, and the supplement by its file. Apart from
`tests/test_finding_keys.py`, which keeps to 800 lines."""

from __future__ import annotations

from pathlib import Path

from manuscript_guard import keys
from manuscript_guard.keys import Keyed


def test_the_part_is_the_abstract_under_its_heading_and_the_supplement_by_its_file() -> None:
    text = ("# Abstract\n\nOne. Two.\n\n# Methods\n\nThree.\n\nABSTRACT\n\nFour.\n\n"
            "INTRODUCTION\n\nFive.\n")  # fmt: skip
    assert keys.part_of(text, text.index("Two")) == keys.ABSTRACT
    assert keys.part_of(text, text.index("Three")) == keys.MAIN
    assert keys.part_of(text, text.index("Four")) == keys.ABSTRACT
    assert keys.part_of(text, text.index("Five")) == keys.MAIN
    assert keys.part_of(text, text.index("Three"), supplementary=True) == keys.SUPPLEMENT
    tex = "\\begin{abstract}One.\\end{abstract}\\section{Methods}Two."
    assert keys.part_of(tex, tex.index("One")) == keys.ABSTRACT
    assert keys.part_of(tex, tex.index("Two")) == keys.MAIN
    assert keys.in_supplement(Path("p/manuscript/supplementary/S1.md"))
    assert not keys.in_supplement(Path("supplementary/manuscript/main.md"))


def test_a_structured_abstracts_own_headings_keep_its_sentences_in_it() -> None:
    """A line alone ends the Abstract only where it is the Introduction, the Discussion or
    the References, or names again what stood alone in it already: a structured Abstract's
    Background and Results go on in it. So one sentence word for word in the Abstract and in
    the Results is two keys, neither numbered (the follow-up's review)."""
    markdown = ("# Abstract\n\n**Results**\n\nThe rate was 4.7 in all.\n\n# Results\n\n"
                "The rate was 4.7 in all.\n")  # fmt: skip
    word = ("Abstract\n\nBackground\n\nWe asked.\n\nResults\n\nThe rate was 4.7 in all.\n\n"
            "Introduction\n\nWe ask again.\n\nResults\n\nThe rate was 4.7 in all.\n")  # fmt: skip
    for text in (markdown, word):
        first, last = text.index("The rate"), text.rindex("The rate")
        assert keys.part_of(text, first) == keys.ABSTRACT, text
        assert keys.part_of(text, last) == keys.MAIN, text
        found = keys.assign([Keyed("G2", "unclassified-number", "4.7",
                                   keys.placed(text, at), at) for at in (first, last)])  # fmt: skip
        assert len(set(found)) == 2 and not any("#" in one for one in found), found
    assert keys.part_of(word, word.index("We ask again")) == keys.MAIN


#: A structured Abstract run into the paper's own sections, and the same with one of its
#: ranked parts renamed to a part no rank names (round 1 of #709).
STRUCTURED = ("Abstract\nIMPORTANCE\nIt matters.\nRESULTS\nIt worked.\nMethods\nWe did it.\n"
              "Results\nThe effect was large.\nDiscussion\nIt mattered.\n")  # fmt: skip


def _parts(text: str, *starts: str) -> list[str]:
    return [keys.part_of(text, text.index(start)) for start in starts]


def test_a_structured_abstract_ends_where_its_own_order_starts_again() -> None:
    """An Abstract whose first block is a line alone is structured: a line alone ends it
    where its name ranks no later than the last of its own parts met (Background, Methods,
    Results, Conclusions), and the Introduction, the Discussion and the References always
    do. Its RESULTS, then the paper's Methods, so end it there. An Abstract whose first
    block is a sentence ends at any line alone (round 1 of #709)."""
    assert _parts(STRUCTURED, "It worked", "We did it", "The effect", "It mattered") == [
        keys.ABSTRACT, keys.MAIN, keys.MAIN, keys.MAIN]
    plain = ("Abstract\nWe studied things.\nMethods\nWe did it.\nResults\nIt worked.\n"
             "Discussion\nIt matters.\n")  # fmt: skip
    assert _parts(plain, "We studied", "We did it", "It worked", "It matters") == [
        keys.ABSTRACT, keys.MAIN, keys.MAIN, keys.MAIN]
    # A singular is its plural's part, and "Materials and Methods" is one of them.
    folded = ("Abstract\nBackground\nWe asked.\nMaterials and Methods\nWe counted.\n"
              "Conclusions\nIt held.\nConclusion\nIt held again.\n")  # fmt: skip
    assert _parts(folded, "We counted", "It held.", "It held again") == [
        keys.ABSTRACT, keys.ABSTRACT, keys.MAIN]


def test_an_abstract_is_structured_only_where_it_opens_on_a_part_it_names() -> None:
    """An Abstract is structured only where its first line is shaped as a heading and names
    one of its ranked parts or what a structured Abstract opens on: a hard-wrapped
    sentence's first line, as a PDF's text gives it, is no heading, nor is BMC's inline
    "Background: ..." (round 2 of #709: the PDF's Background, Methods and Results were kept
    in the Abstract)."""
    wrapped = ("Abstract\nWe studied the effect of the new drug on\nblood pressure in 120 "
               "adults. It fell.\nBackground\nDrugs matter.\nMethods\nWe did it.\nResults\n"
               "It worked.\n")  # fmt: skip
    assert _parts(wrapped, "We studied", "Drugs matter", "It worked") == [
        keys.ABSTRACT, keys.MAIN, keys.MAIN]
    nature = ("Abstract\nThe drug lowers pressure. Here we show how.\nResults\nIt worked.\n"
              "Discussion\nIt matters.\nMethods\nWe did it.\n")  # fmt: skip
    assert _parts(nature, "Here we show", "It worked", "We did it") == [
        keys.ABSTRACT, keys.MAIN, keys.MAIN]
    inline = ("Abstract\nBackground: Drugs matter for many patients with\nheart disease. We "
              "asked why.\nResults\nIt worked.\nConclusions\nIt holds.\n")  # fmt: skip
    assert _parts(inline, "heart disease", "It worked") == [keys.ABSTRACT, keys.MAIN]


def test_a_compound_opener_makes_an_abstract_structured() -> None:
    """A structured Abstract may open on a compound, "Background and Purpose" as Stroke
    prints it: it stays the Abstract through its own Methods and Results (the scoped check of
    #709)."""
    stroke = ("Abstract\nBackground and Purpose\nStroke matters.\nMethods\nWe did it.\n"
              "Results\nIt worked.\nConclusions\nIt holds.\nIntroduction\nMore.\n")  # fmt: skip
    assert _parts(stroke, "Stroke", "We did", "It worked", "It holds", "More.") == [
        keys.ABSTRACT, keys.ABSTRACT, keys.ABSTRACT, keys.ABSTRACT, keys.MAIN]
    for opener in ("Background and Aims", "Aims and Objectives", "Purpose of Review"):
        text = stroke.replace("Background and Purpose", opener)
        assert _parts(text, "We did", "It worked") == [keys.ABSTRACT, keys.ABSTRACT], opener


def test_a_structured_abstract_renamed_moves_where_it_ends() -> None:
    """The limit of DESIGN.md's Known gaps, held as it is: with RESULTS renamed FINDINGS,
    which no rank names, the paper's own Methods and Results rank later than every part the
    Abstract named, and stay in its part until the Discussion. A structured Abstract with
    only its Background, run straight into the paper's Methods, keeps them too. The corpus
    gate runs one paper unchanged between two commits, so neither moves a key it compares."""
    renamed = STRUCTURED.replace("RESULTS", "FINDINGS")
    assert _parts(renamed, "It worked", "We did it", "The effect", "It mattered") == [
        keys.ABSTRACT, keys.ABSTRACT, keys.ABSTRACT, keys.MAIN]
    short = "Abstract\nBackground\nWe asked.\nMethods\nWe did it.\nReferences\n1. A.\n"
    assert _parts(short, "We asked", "We did it", "1. A.") == [
        keys.ABSTRACT, keys.ABSTRACT, keys.MAIN]


def test_a_word_alone_in_lower_case_is_no_heading() -> None:
    """A heading's name alone on a line is one with a capital or in capitals: "results." or
    "references." a hard-wrapped Abstract leaves alone on a line keeps the Abstract's part,
    so re-wrapping it moves no key; "references." ends an Abstract wherever it stands, and
    read in any case it took the rest of this one away (the follow-up's reviews)."""
    for word in ("results", "references"):
        wrapped = (f"# Abstract\n\nWe report the\n{word}.\nThe rate was 4.7 in all of the\n"
                   "patients.\n\n# Methods\n\nWe counted.\n")  # fmt: skip
        flowing = wrapped.replace(f"the\n{word}.\nThe", f"the {word}. The", 1)
        for text in (wrapped, flowing):
            assert keys.part_of(text, text.index("The rate")) == keys.ABSTRACT, text
        assert keys.placed(wrapped, wrapped.index("The rate")) == keys.placed(
            flowing, flowing.index("The rate"))  # fmt: skip
    assert keys.part_of("Abstract\n\nOne.\n\nRESULTS\n\nTwo.\n\nINTRODUCTION\n\nThree.",
                        40) == keys.MAIN  # fmt: skip
