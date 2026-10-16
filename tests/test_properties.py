"""What a reading owes the text it reads, held over generated manuscripts.

The independent reviews of this repository checked the same few things of every change to
a rule that reads text, each time by a campaign written for that one round: that nothing
raises, that what is found is where the finding says it is, that what is hidden stays
hidden and nothing else moves, that the order of a list makes no difference, and that a
quotation typed from its source is found in it. These are those checks, kept, on the
generators of `tests/generated.py`. A rule that breaks one fails here, on an input cut down
to the smallest that shows it, with no reviewer to build the campaign.

Two kinds of test, as everywhere in this suite. Most hold an invariant over inputs nobody
chose, and say nothing of what the right answer is. The others plant something at a known
place, a term the paper gave up or a word in the other English, among words that are
nobody's, and hold the gate to finding exactly that, there: those are the ones that fail
when a rule stops finding anything at all.

`tests/test_differential.py` puts the same inputs through the base branch's source and
through this one, which is the third thing the reviews did.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from bisect import bisect_left
from pathlib import Path
from typing import Any

import pytest
from generated import (
    AGREED,
    FILLER,
    HELD,
    INPUTS,
    SOURCE_GAPS,
    SOURCE_WORDS,
    TERMS,
    TYPOGRAPHY,
    bindings,
    commented,
    generated,
    holds,
    lines,
    quotations,
    signs,
    sources,
    texts,
    typed,
    vocabularies,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.database import InMemoryExampleDatabase
from readings import MAIN, PAPER, PEOPLE, READINGS, Unavailable, answer

from manuscript_guard import reworded as reworded_module
from manuscript_guard.build import blinding
from manuscript_guard.build.blinding import names_in, sought
from manuscript_guard.classify import CONVENTION, STRUCTURAL, TERM, UNCLASSIFIED, Classifier
from manuscript_guard.contracts.project import outside_maths
from manuscript_guard.contracts.values import RESULTS, Value, number_in
from manuscript_guard.gates import bound_units as bound_units_gate
from manuscript_guard.gates import language as language_gate
from manuscript_guard.gates import methods as methods_gate
from manuscript_guard.gates import models as models_gate
from manuscript_guard.gates import numbers as numbers_gate
from manuscript_guard.gates import spelling as spelling_gate
from manuscript_guard.gates import vocabulary as vocabulary_gate
from manuscript_guard.gates.language import _file, _hidden
from manuscript_guard.gates.notation import VALUE, _counted
from manuscript_guard.gates.spelling import MANY, _prose, _variants, judge_spelling
from manuscript_guard.gates.vocabulary import (
    Passage,
    capitals_together,
    judge_vocabulary,
    own_words,
)
from manuscript_guard.literature import sources as literature_sources
from manuscript_guard.literature.sources import contains, normalise, states_value
from manuscript_guard.reworded import (
    BINDING,
    CITATION,
    MAYBE,
    NO,
    NUMBER,
    RELATIONS,
    SURE,
    compare,
    facts,
)
from manuscript_guard.text import placeholders, tokens
from manuscript_guard.text.masking import NUL, mask
from manuscript_guard.text.placeholders import parse as parse_bindings
from manuscript_guard.text.sections import chains_at, footnote_index, heading_index
from manuscript_guard.text.tex import tex_outside_maths
from manuscript_guard.text.tokens import DIGIT, find_atoms

REPO = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.usefixtures("stopped_if_stuck")

#: How many pairs of inputs each reading is given. `check` makes a project on disk for each
#: input and takes half a second of it, so it is given few: what it is made of is read by
#: the other readings many times over. `import` builds a document for each and takes three
#: seconds; its sessions have a file of their own, `tests/test_generated_sessions.py`, and
#: here it is only asked twice for the same one.
PAIRS = dict.fromkeys(READINGS, 75) | {"check": 6, "import": 1}


# ---------------------------------------------------------------- the generators themselves


def test_every_reading_is_given_something_and_nothing_is_given_to_no_reading() -> None:
    assert set(INPUTS) == set(READINGS)


def test_the_filler_words_are_nobodys() -> None:
    """A planted term is counted among filler words, so none of them may be a word a gate
    reads for itself: a spelling one English has and the other has not, an abbreviation, or
    the whole of a term some vocabulary here gives up or keeps."""
    listed, with_ize = _variants()
    for word in FILLER:
        assert word.isascii() and word.isalpha() and word.islower(), word
        assert word not in listed and word not in with_ize, word
    plain = {word.rstrip("s") for word in FILLER}
    terms = [*TERMS, *(term for entry in AGREED for term in (entry["use"], *entry["avoid"]))]
    for term in terms:
        words = [word.casefold().rstrip("s") for word in re.split(r"[\s-]+", term)]
        assert not set(words) <= plain, f"{term!r} can be made of filler words"


def _drawn(*, after_importing: str = "") -> str:
    """A digest of the first examples each strategy draws, in a process of its own."""
    code = (
        f"{after_importing}\n"
        "import hashlib, json\n"
        "from hypothesis import given, settings\n"
        "import generated\n"
        "seen = []\n"
        "@settings(max_examples=60, derandomize=True, deadline=None)\n"
        "@given(generated.texts(generated.TERMS), generated.vocabularies(), generated.lines())\n"
        "def draw(text, entries, line):\n"
        "    seen.append([text, entries, line])\n"
        "draw()\n"
        "print(len(seen), hashlib.sha256(json.dumps(seen).encode()).hexdigest())\n"
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith("MANUSCRIPT_")}
    env["PYTHONPATH"] = os.pathsep.join((str(REPO / "src"), str(REPO / "tests")))
    env["PYTHONHASHSEED"] = "0"
    finished = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        timeout=600, cwd=REPO,
    )  # fmt: skip
    assert finished.returncode == 0, finished.stderr
    return finished.stdout.strip()


def test_the_examples_do_not_depend_on_what_is_imported() -> None:
    """Hypothesis draws some values from the constants in whatever local modules are
    imported, so the examples a test drew depended on which tests had run before it: a
    failure in the whole suite did not come back when its test was run alone. With the pool
    emptied (`tests/generated.py`) the examples are the same either way. Sixty of each, in
    two fresh processes, one of which has imported the whole command line first."""
    alone = _drawn()
    assert alone.startswith("60 "), alone
    assert alone == _drawn(after_importing="import manuscript_guard.cli")


def test_a_number_of_examples_that_is_no_number_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed wrongly, `MANUSCRIPT_GUARD_MORE_EXAMPLES` must not mean "as usual": whoever
    set it believes a longer run was made."""
    for typed_wrongly in ("ten", "0", "-3", "2.5"):
        monkeypatch.setenv("MANUSCRIPT_GUARD_MORE_EXAMPLES", typed_wrongly)
        with pytest.raises(ValueError, match="MANUSCRIPT_GUARD_MORE_EXAMPLES"):
            generated(10)
    monkeypatch.setenv("MANUSCRIPT_GUARD_MORE_EXAMPLES", " 3 ")
    monkeypatch.setenv("MANUSCRIPT_GUARD_SEED", "x")
    with pytest.raises(ValueError, match="MANUSCRIPT_GUARD_SEED"):
        generated(10)


_NUMBERS = st.integers(min_value=0, max_value=10**6)


def test_a_pinned_test_draws_the_same_inputs_whatever_it_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A generated test is seeded from its own source, docstring included. One that draws
    few inputs and is held to what they contain drew others when a word of it changed, and
    failed on a rule nobody had touched. `pinned` draws from a number instead: two tests
    that differ in what they say draw alike, where unpinned they draw apart. A seed the
    run names is still the one drawn from."""
    # This test is about what is drawn where the run names no seed, so it starts from
    # none: under a named one the two unpinned tests are one draw.
    monkeypatch.delenv("MANUSCRIPT_GUARD_SEED", raising=False)
    first: list[int] = []
    second: list[int] = []

    def one(number: int) -> None:
        first.append(number)

    def another(number: int) -> None:
        """The same test, said otherwise."""
        second.append(number)

    def draw(**how: Any) -> tuple[list[int], list[int]]:
        first.clear()
        second.clear()
        generated(30, **how)(given(_NUMBERS)(one))()
        generated(30, **how)(given(_NUMBERS)(another))()
        return list(first), list(second)

    by_its_text, by_the_others_text = draw()
    assert by_its_text != by_the_others_text

    of_three, of_three_again = draw(pinned=3)
    assert of_three == of_three_again
    assert len(set(of_three)) > 10, of_three
    of_four, _ = draw(pinned=4)
    assert of_four != of_three

    monkeypatch.setenv("MANUSCRIPT_GUARD_SEED", "4")
    named, _ = draw(pinned=3)
    assert named == of_four


def test_the_tests_of_pinning_pass_under_a_seed_the_run_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`MANUSCRIPT_GUARD_SEED=7 pytest tests/test_properties.py` is how to look harder at a
    change, and the test above failed under it on source nobody had touched: it holds two
    unpinned draws apart, and a named seed makes them one. The two tests here that draw
    under a seed are run again as that command runs them."""
    monkeypatch.setenv("MANUSCRIPT_GUARD_SEED", "7")
    test_a_pinned_test_draws_the_same_inputs_whatever_it_says(monkeypatch)
    monkeypatch.setenv("MANUSCRIPT_GUARD_SEED", "7")
    test_a_pinned_test_plays_nothing_an_earlier_run_left()


def test_a_pinned_test_plays_nothing_an_earlier_run_left() -> None:
    """Hypothesis keeps the inputs a test failed on and plays them first the next time. A
    test held to what its inputs are must not be played one more, a failure of last week's
    at the head of the run. A test given a seed keeps none, which is Hypothesis's doing
    and not this suite's, so it is held here, where a release that changed it would show:
    with somewhere to keep them the smallest input that failed is played first, and
    pinned it is not played at all."""
    seen: list[int] = []
    fails = [True]

    def played(number: int) -> None:
        seen.append(number)
        assert not (fails[0] and number > 1000)

    def after_a_failure(held: Any) -> list[int]:
        fails[0] = True
        with pytest.raises(AssertionError):
            held()
        fails[0] = False
        seen.clear()
        held()
        return list(seen)

    keeping = settings(max_examples=20, deadline=None, database=InMemoryExampleDatabase())
    assert after_a_failure(keeping(given(_NUMBERS)(played)))[0] == 1001
    pinned = after_a_failure(generated(20, pinned=3)(given(_NUMBERS)(played)))
    assert pinned[0] == 0 and 1001 not in pinned, pinned


# ----------------------------------------------------- nothing raises, and nothing is kept


def _check_kept_its_word(found: dict[str, Any]) -> None:
    """`check` runs at the start of a session, before a build and in the submission guard.
    It reads. A file it changed would be a manuscript edited by the tool that says whether
    the manuscript is clean; a gate that did not run would be a clean bill from nobody."""
    assert found["written"] == [], found["written"]
    assert "Traceback" not in found["complained"], found["complained"]
    if found["said"] is None:
        # Settings that cannot be read at all: one sentence, and no report to trust.
        assert found["exit"] == 2, found
        assert found["complained"].startswith("manuscript-guard: <project>"), found
        return
    assert found["exit"] in (0, 1), found
    errored = [f for f in found["said"]["findings"] if f["code"] == "gate-errored"]
    assert not errored, errored


@pytest.mark.parametrize("name", sorted(READINGS))
def test_a_reading_answers_and_answers_the_same_the_second_time(name: str) -> None:
    """A gate that raises is reported as `gate-errored` and reads nothing: every number in
    the manuscript passes it. Each reading is given manuscripts an author might write and
    text nobody would, and has to come back with an answer.

    And with the same answer when it is asked again after another text. A reading that
    keeps something between two texts answers for the last one: the classifier keeps one
    scan, and the spelling list is read once."""
    try:
        read = READINGS[name]()
    except Unavailable as missing:
        pytest.skip(str(missing))

    @generated(PAIRS[name])
    @given(INPUTS[name], INPUTS[name])
    def held(first: Any, second: Any) -> None:
        once, other = answer(read, first), answer(read, second)
        for asked, found in ((first, once), (second, other)):
            assert "raised" not in found, f"{name!r} raised {found['raised']} on {asked!r}"
        assert answer(read, first) == once, (first, second)
        if name == "check":
            _check_kept_its_word(once["answer"])
            _check_kept_its_word(other["answer"])

    held()


# ------------------------------------------------- what is hidden, and what keeps its place


def _in_place(text: str, read: str, name: str, *, fill: str = NUL) -> None:
    assert len(read) == len(text), f"{name}: {len(read)} characters of {len(text)}"
    for at, (was, now) in enumerate(zip(text, read, strict=True)):
        assert now in (was, fill), f"{name}: {was!r} became {now!r} at {at} of {text!r}"
        assert (now == "\n") == (was == "\n"), f"{name}: a line break at {at} of {text!r}"


@holds(200, texts(TERMS), signs())
def test_what_is_hidden_leaves_every_other_character_in_its_place(
    manuscript: str, nobodys: str
) -> None:
    """A finding's line is counted in the text a gate reads, and shown in the file the
    author opens. They agree only while hiding changes no length and moves no line break:
    one character out, and every finding below it points a line away."""
    _hidden_in_place(manuscript)
    _hidden_in_place(nobodys)


def _hidden_in_place(text: str) -> None:
    hidden = _hidden(text)
    _in_place(text, hidden, "hidden")
    _in_place(text, own_words(hidden), "the paper's own words")
    _in_place(text, _prose(hidden), "the prose the spelling is read in")
    file = _file(0, MAIN, text, [], False)
    _in_place(text, file.printed, "the text the vocabulary is read in")
    _in_place(text, file.spelt, "the text the spelling is read in")
    passage = Passage(file.path, file.text, file.printed, file.line_of)
    _in_place(
        text, _counted(passage).replace(VALUE, NUL), "the text the notation is read in"
    )
    _in_place(text, file.prose, "the text the abbreviations are read in", fill=" ")
    masked = mask(text)
    assert len(masked) == len(text)
    assert all(now in (was, NUL) for was, now in zip(text, masked, strict=True)), text


@holds(200, texts(), signs())
def test_what_is_found_in_a_text_lies_in_it_and_in_order(manuscript: str, nobodys: str) -> None:
    """Every scanner hands the next one offsets: where a listing runs, a comment, a span
    of code, a heading. One that hands over a span past the end of the text, or two that
    overlap, has the next one blanking or reading the wrong characters."""
    _found_in_order(manuscript)
    _found_in_order(nobodys)


def _found_in_order(text: str) -> None:
    found = READINGS["spans"]()(text)
    assert 0 <= found["front matter"] <= len(text)
    for fence in found["fences"]:
        body_start, body_end = fence["body"]
        assert 0 <= fence["start"] <= body_start <= body_end <= fence["end"] <= len(text), (
            text,
            fence,
        )
    kinds = {key: value for key, value in found.items() if key not in ("front matter", "fences")}
    kinds["fences"] = [[fence["start"], fence["end"]] for fence in found["fences"]]
    for kind, spans in kinds.items():
        last = 0
        for start, end in spans:
            assert last <= start < end <= len(text), f"{kind}: {spans} in {text!r}"
            last = end
    before = -1
    for heading in heading_index(text):
        assert before < heading.start < max(len(text), 1), (text, heading)
        assert heading.start == 0 or text[heading.start - 1] == "\n", (text, heading)
        before = heading.start


# ------------------------------------------------------- the sentences a co-author is shown


#: Every way a stop can stand before a citation without ending the sentence, and a narrative
#: citation ending one. Each example plants one of each, in an order drawn each time: a kind
#: drawn first, one among several, is under some seeds never drawn.
_CITED = (
    "{words} was described by Okada et al. [@{key}].",
    "{words} went to the U.S. Food and Drug Administration [@{key}].",
    "{words} is listed in Suppl. Table 3 of the protocol [@{key}].",
    "{words} such as e.g. St. John's wort [@{key}].",
    "{words} held in one Ph.D. Thesis on the matter [@{key}].",
    "{words} reached the same conclusion as @{key}.",
)
#: A citation after the paragraph's last stop, which the splitter cuts off and has to join back.
#: Only at the end of a paragraph: written before another sentence, it is read with that one,
#: which DESIGN.md's Known gaps records.
_CITED_LAST = "{words}. [@{key}]"


@st.composite
def _planted_citations(draw: st.DrawFn) -> tuple[str, list[tuple[str, str, str]]]:
    """A paragraph of every kind of cited clause among drawn words, each followed by a sentence
    of its own, and a citation after the last stop; for each: its key, the words of its clause,
    and the sentence after it, if there is one."""
    planted: list[tuple[str, str, str]] = []
    parts: list[str] = []
    for n, form in enumerate(draw(st.permutations(_CITED))):
        words = " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=2, max_size=5)))
        words = words[0].upper() + words[1:]
        after = " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=2, max_size=5)))
        after = after[0].upper() + after[1:] + "."
        key = f"planted{n}"
        clause = form.format(words=words, key=key)
        parts += [clause, after]
        planted.append((key, clause.split("[@")[0].split(" as @")[0].rstrip(" ."), after))
    words = " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=2, max_size=5)))
    words = words[0].upper() + words[1:]
    parts.append(_CITED_LAST.format(words=words, key="plantedlast"))
    planted.append(("plantedlast", words, ""))
    gaps = [draw(st.sampled_from((" ", " ", "\n"))) for _ in parts]
    return "".join(gap + part for gap, part in zip(gaps, parts, strict=True)).strip(), planted


@holds(200, texts(), _planted_citations())
def test_every_citation_lies_in_the_sentence_of_its_own_clause(
    manuscript: str, cited: tuple[str, list[tuple[str, str, str]]]
) -> None:
    """The claim items a co-author checks are the sentences of the manuscript that cite
    something, so the splitter owes them two things.

    **Every citation is in the sentence that carries its own clause, and in no other.** A split
    at a stop that ends nothing ("et al.", "U.S.", "Suppl.") leaves the words of the claim on one
    piece and the citation on another, and the co-author is asked whether a source supports
    "Food and Drug Administration". A splitter that never splits holds the next sentence too.

    **Within a paragraph, only the first piece may carry no word of its own.** A piece with none
    is joined to the piece before it, so nobody is asked about a citation without its claim. The
    first piece is the exception because a paragraph that is nothing but a citation has nothing
    before it to join to; the producer drops that one, which `tests/test_checking.py` holds.
    """
    paragraph, planted = cited
    read = READINGS["checker sentences"]()(manuscript + "\n\n" + paragraph + "\n")

    for key, clause, after in planted:
        holding = [sentence for _line, sentence in read if f"@{key}" in sentence]
        assert len(holding) == 1, f"@{key} is in {len(holding)} sentences: {read}"
        assert " ".join(clause.split()) in holding[0], f"@{key} is apart from its clause: {read}"
        if after:
            assert " ".join(after.split()) not in holding[0], f"@{key} runs on: {holding[0]!r}"

    def wordless(sentence: str) -> bool:
        return not any(
            character.isalpha()
            for character in re.sub(r"@[A-Za-z][\w:.#$%&+?<>~/-]*", "", sentence)
        )

    # Pieces of one paragraph share the line it starts on, which is how they are grouped here.
    by_paragraph: dict[int, list[str]] = {}
    for line, sentence in read:
        by_paragraph.setdefault(line, []).append(sentence)
    for line, pieces in by_paragraph.items():
        for piece in pieces[1:]:
            assert not wordless(piece), f"line {line}: a piece with no claim in it: {piece!r}"


# ------------------------------------------------------------------ the sentence of a bound


@holds(200, INPUTS["interval order"], signs())
def test_a_sentence_is_looked_up_as_it_was_counted(quoting: str, nobodys: str) -> None:
    """G2 compares the bounds of an interval within one sentence. Which sentence a binding
    is in was a search for sentence ends from the top of the file, stopped at the binding;
    it is looked up now among the sentence ends of the whole file, and has to be the same
    number at every offset. The two searches do not find the same ends: a stop against a
    binding is one for the search that stops there, and none for the one that reads on."""
    _looked_up_as_counted(quoting)
    _looked_up_as_counted(nobodys)


def _looked_up_as_counted(text: str) -> None:
    # Imported here, not at the top, to keep clear of the import block other branches edit.
    from manuscript_guard.gates import numbers as numbers_gate

    ends = [match.start() for match in numbers_gate._SENTENCE_END.finditer(text)]
    for start in range(len(text) + 1):
        counted = sum(1 for _ in numbers_gate._SENTENCE_END.finditer(text, 0, start))
        assert numbers_gate._sentence(text, ends, start) == counted, (text, start)


@holds(200, commented())
def test_a_comment_is_white_space_to_the_order_of_intervals(drawn: tuple[str, str]) -> None:
    """Pandoc drops an HTML comment, and the bindings are read in the text with each
    comment blanked. The sentences an interval's bounds are compared in are read in that
    text too. So what G2 finds in a text with comments typed into it is what it finds, on
    the same lines and in the same order, in that text with white space where each comment
    stood: a stop inside a comment ends no sentence, and one with a comment typed against
    it ends one."""
    typed_with, blanked = drawn
    read = READINGS["interval order"]()
    assert read(typed_with) == read(blanked), (typed_with, blanked)


# ---------------------------------------------------------------------------------- numbers

CLASSIFIER = Classifier.load()


@holds(200, texts(), signs())
def test_a_number_is_seen_where_it_stands_and_judged_one_way(manuscript: str, nobodys: str) -> None:
    """Three things G2 owes every number, in the order it does them.

    It sees it. The core invariant is that no number reaches the page unjudged, and the
    first way to break it is never to see the number: a digit that is not hidden is in an
    atom. The one exception is the run of characters that holds a caret, since an exponent
    on a unit, `m^2^`, is read as no number, and that rule has its own tests.

    It knows where it stands. A number is reported by its line and column and judged by the
    text around its offsets, so an atom whose offsets are not where its text stands is
    judged by somebody else's words. And it holds nothing hidden.

    It judges it one way. `classify` takes the file's scan from its caller or makes one
    itself, and says of the two that both answer alike: G2 passes one, the figure check and
    the audit do not."""
    _seen_and_judged(manuscript)
    _seen_and_judged(nobodys)


def _seen_and_judged(text: str) -> None:
    masked = mask(text)
    atoms = find_atoms(text, masked)
    seen: set[int] = set()
    last = 0
    for atom in atoms:
        assert text[atom.start : atom.end] == atom.text, (text, atom)
        assert NUL not in masked[atom.start : atom.end], (text, atom)
        assert DIGIT.search(atom.text), (text, atom)
        assert not any(character.isspace() for character in atom.text), (text, atom)
        assert last <= atom.start < atom.end, (text, atom)
        last = atom.end
        line_start = text.rfind("\n", 0, atom.start) + 1
        assert atom.line == text.count("\n", 0, atom.start) + 1, (text, atom)
        assert atom.line_start == line_start, (text, atom)
        assert atom.col == atom.start - line_start + 1, (text, atom)
        assert atom.line_start <= atom.start < atom.end <= atom.line_end, (text, atom)
        seen.update(range(atom.start, atom.end))

    for run in re.finditer(r"[^\s\x00]+", masked):
        if "^" in run.group():
            continue
        for at in range(*run.span()):
            assert not DIGIT.match(masked[at]) or at in seen, (text, at, run.group())

    scan = CLASSIFIER.scan(text)
    headings, notes = heading_index(text), footnote_index(text)
    for atom in atoms:
        for chain in chains_at(headings, notes, atom.start):
            with_scan = CLASSIFIER.classify(atom, chain, scan)
            assert with_scan == CLASSIFIER.classify(atom, chain), (text, atom.text)
            assert with_scan.kind in (TERM, STRUCTURAL, CONVENTION, UNCLASSIFIED)


# ------------------------------------------------------------- what the plan's deviations say


@st.composite
def _deviations_twice(draw: st.DrawFn) -> tuple[str, str, str]:
    """A plan whose Deviations section is drawn words, the same plan with them wrapped another
    way, and the same with a word more. The section comes before drawn text: after it, an
    empty footnote or an open fence the draw left would take its heading, as pandoc reads."""
    words = draw(st.lists(st.sampled_from(FILLER), min_size=3, max_size=20))
    wrap = [draw(st.sampled_from((" ", "\n", "  ", " \n"))) for _ in words[1:]]
    # A line break and a doubled space in every example, wherever else the draw put them.
    wrap[0], wrap[-1] = "\n", "  "
    rewrapped = words[0] + "".join(gap + word for gap, word in zip(wrap, words[1:], strict=True))
    after = draw(texts())

    def plan(deviations: str) -> str:
        return f"# Analysis plan\n\n## Deviations from the plan\n\n{deviations}\n\n" \
            f"## Outcome\n\n{after}\n"  # fmt: skip

    said = " ".join(words)
    return plan(said), plan(rewrapped), plan(said + " " + draw(st.sampled_from(FILLER)))


@holds(100, _deviations_twice())
def test_a_deviation_rewrapped_says_what_it_said_and_a_word_more_does_not(
    drawn: tuple[str, str, str],
) -> None:
    """Whatever the plan above it, the Deviations section says the same however its lines
    are wrapped, and something else with a word added."""
    from manuscript_guard.gates.design import deviations_said

    plan, rewrapped, longer = drawn
    assert deviations_said(plan) == deviations_said(rewrapped), rewrapped
    assert deviations_said(plan) != deviations_said(longer), longer


# ------------------------------------------------------------------------------ parameters

#: What an analysis declares in the property below: a threshold, a count, a version, and a
#: parameter that equals the name of a structure. The last equals the 25 of a threshold and
#: of the name of a statistic, `Ω025`, as the 2 above equals the 2 of `I2`.
_DECLARED = (
    Value("param.alpha", 0.05, "0.05", RESULTS, role="parameter", read=True),
    Value("param.signal.min_cases", 3, "3", RESULTS, role="parameter", read=True),
    Value("param.rows", 2, "2", RESULTS, role="parameter", read=True),
    Value("software.r", "4.6.0", "4.6.0", RESULTS, label=True, role="software"),
    Value("param.heterogeneity", 25, "25", RESULTS, role="parameter", read=True),
)

#: In place of a key: a threshold typed in the Methods that no declared parameter equals,
#: which G2 names as `threshold-undeclared`.
_NO_PARAMETER = "a threshold no parameter has"

#: One of every kind G2 reads a typed parameter in, with `|` where its atom starts, the key it
#: states, and whether it is a version, which is read wherever it stands. A threshold is
#: read in the Methods alone, and `2 x 2` is read nowhere, whatever a parameter equals.
#: Nor is the name of a statistic, whose figure is typed against a letter of any alphabet:
#: the threshold beside it is read, in an atom of its own or in the name's.
_TYPED = (
    ("an alpha of |0.05", "param.alpha", False),
    ("p < |.05", "param.alpha", False),
    ("|p<0.05", "param.alpha", False),
    ("at least |3 cases", "param.signal.min_cases", False),
    ("R |4.6.0", "software.r", True),
    ("a |2 x 2 table", None, False),
    ("I2 > |25%", "param.heterogeneity", False),
    ("|I2>25%", "param.heterogeneity", False),
    ("\N{GREEK CAPITAL LETTER OMEGA}025 > |0", _NO_PARAMETER, False),
    ("matched |1:1", _NO_PARAMETER, False),
)

_METHODS_HEADINGS = (
    "# Methods", "# Materials and methods", "# Methods\n\n## Statistical analysis",
    "# 2. Methods", "# Patients and methods",
)  # fmt: skip
_OTHER_HEADINGS = ("# Results", "# Discussion", "# Results\n\n## Sensitivity analyses")


@st.composite
def _planted_choices(draw: st.DrawFn) -> tuple[str, set[tuple[int, int, str]]]:
    """Filler words with every kind of typed parameter planted under a Methods heading and
    again under another one, in an order and among words drawn each time, and where each
    stands that G2 must find."""
    parts: list[str] = []
    found: set[tuple[int, int, str]] = set()

    def filler() -> str:
        words = draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=5))
        return "".join(draw(st.sampled_from((" ", " ", "\n"))) + word for word in words)

    for heading, methods in (
        (draw(st.sampled_from(_METHODS_HEADINGS)), True),
        (draw(st.sampled_from(_OTHER_HEADINGS)), False),
    ):
        parts.append(f"{heading}\n\n{filler().strip().capitalize()}")
        for written, key, version in draw(st.permutations(_TYPED)):
            parts.append(filler() + " ")
            before, _bar, after = written.partition("|")
            parts.append(before)
            if key is not None and (methods or version):
                text = "".join(parts)
                found.add(
                    (text.count("\n") + 1, len(text) - (text.rfind("\n") + 1) + 1, key)
                )
            parts.append(after)
        parts.append(f"{filler()}.\n\n")
    return "".join(parts), found


@holds(150, _planted_choices())
def test_a_typed_parameter_is_found_where_it_stands_and_nowhere_it_does_not(
    planted: tuple[str, set[tuple[int, int, str]]],
) -> None:
    """A threshold the analysis declares is found typed in the Methods, written with or
    without its nought and with or without spaces round its comparison, and a declared
    version wherever it stands. A threshold there that equals no parameter is found as
    one. Nothing else is: not the same threshold in the Results, where it is no convention,
    not the `2` of a `2 x 2` table that equals a parameter, and not the name of a statistic
    whose digits equal one, which the convention accepts with the threshold beside it."""
    text, expected = planted
    headings, notes = heading_index(text), footnote_index(text)
    scan = CLASSIFIER.scan(text)
    chosen = numbers_gate.chosen_rules(CLASSIFIER)
    found = set()
    for atom in find_atoms(text, mask(text)):
        verdict = CLASSIFIER.classify_under(atom, chains_at(headings, notes, atom.start), scan)
        typed = numbers_gate.typed_choice(atom.text, verdict, list(_DECLARED), chosen)
        if typed is not None:
            found.add((atom.line, atom.col, typed.key))
        elif numbers_gate.typed_threshold(atom.text, verdict, chosen):
            found.add((atom.line, atom.col, _NO_PARAMETER))
    assert found == expected, text


# ----------------------------------------------------------- a P and the statistic before it

#: Each way a test is written, and its kind.
_TEST_FORMS = (
    ("t", "t({d1}) = {s}, p {sign} {p}"),
    ("t", "*t*({d1})\N{NO-BREAK SPACE}=\N{NO-BREAK SPACE}{s}, *p* {sign} {p}"),
    ("t", "t = {s}, df = {d1}, P {sign} {p}"),
    ("t", "t({d1}) =\n{s}, p-value {sign} {p}"),
    ("F", "F({d1}, {d2}) = {s}, p {sign} {p}"),
    ("F", "_F_({d1},{d2}) = {s}; P {sign} {p}"),
    ("chi2", "\N{GREEK SMALL LETTER CHI}2({d1}) = {s}, p {sign} {p}"),
    ("chi2", "\N{GREEK SMALL LETTER CHI}^2^({d1}, N = 312) = {s}, *P* {sign} {p}"),
    ("chi2", "chi-square({d1}) = {s}, p {sign}\n{p}"),
    ("z", "z = {s}, P {sign} {p}"),
    ("z", "Z = {s}, p\n{sign} {p}"),
)
#: What a sentence says of a test whose P is not the textbook one.
_NOT_TEXTBOOK = (
    "one-sided, ", "after Bonferroni adjustment, ", "by permutation, ",
    "with Welch's correction, ", "by an exact test, ",
)  # fmt: skip
#: Where each kind's statistic is drawn from, in thousandths, with the degrees of freedom:
#: a P of 0.001 or more, one below 0.0005, and one above 0.2.
_MODERATE = {"t": (300, 3000), "F": (500, 3500), "chi2": (500, 9000), "z": (200, 3000)}
_LARGE = {"t": (5000, 9000), "F": (25000, 60000), "chi2": (40000, 80000), "z": (4000, 6000)}
_SMALL = {"t": (300, 1000), "F": (500, 1200), "chi2": (500, 1500), "z": (200, 1200)}
_DEGREES = {"t": ((20, 200),), "F": ((1, 5), (20, 200)), "chi2": ((1, 10),), "z": ()}
#: What is printed for a P far from the one the statistic gives: for a large statistic,
#: and for a small one.
_FAR = {"large": (("=", ".40"), (">", ".05"), ("=", "0.62")), "small": (("<", ".01"),
        ("=", ".001"))}  # fmt: skip


def _true_p(kind: str, value: float, df: tuple[int, ...]) -> float:
    from manuscript_guard.stats.special import p_chi2, p_f, p_t, p_z

    calls = {"t": p_t, "F": p_f, "chi2": p_chi2, "z": p_z}
    return calls[kind](abs(value), *df)


def _printed_p(draw: st.DrawFn, p: float, shape: str) -> tuple[str, str]:
    """A P as a paper prints the one its statistic gives: to three places, below a
    threshold it is under, or as a power of ten."""
    if shape == "<" and p < 0.05:
        bound = next(t for t in (0.001, 0.01, 0.05) if p < t)
        return "<", draw(st.sampled_from((f"{bound:g}", f"{bound:g}"[1:])))
    if shape in ("e", "x10") and p < 0.001:
        mantissa, exponent = f"{p:.1e}".split("e")
        if shape == "e":
            return "=", f"{p:.1e}"
        times = draw(st.sampled_from(("x", "\N{MULTIPLICATION SIGN}")))
        return "=", f"{mantissa} {times} 10^{int(exponent)}^"
    shown = f"{p:.3f}"
    return "=", draw(st.sampled_from((shown, shown.removeprefix("0"))))


@st.composite
def _reported_tests(draw: st.DrawFn) -> tuple[str, list[tuple[Any, ...]]]:
    """Every way of writing a test, each with a P that follows from its statistic, printed
    every way a paper prints one, with a P that does not, and in a sentence that says the
    test is not the textbook one; a P in the sentence after its statistic's, and two
    statistics before one P. Each with the place it is found at and what is said of it."""

    def words() -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))

    def statistic(kind: str, bounds: dict) -> tuple[str, tuple[str, ...], float]:
        value = draw(st.integers(*bounds[kind])) / 1000 + 0.0003
        printed = f"{value:.{draw(st.sampled_from((1, 2)))}f}"
        if kind in ("t", "z") and draw(st.booleans()):
            printed = draw(st.sampled_from(("-", "\N{MINUS SIGN}"))) + printed
        df = tuple(draw(st.integers(*limits)) for limits in _DEGREES[kind])
        return printed, tuple(map(str, df)), _true_p(kind, value, df)

    plans: list[tuple[int, str]] = []
    for index in range(len(_TEST_FORMS)):
        plans += [(index, kind) for kind in ("moderate", "large", "far", "near", "quiet")]
    plans += [(-1, "next sentence"), (-1, "two statistics")]
    shapes = draw(st.permutations(("e", "x10", "<")))
    sentences: list[tuple[str, tuple[Any, ...] | None]] = []
    for number, (index, plan) in enumerate(draw(st.permutations(plans))):
        if plan == "next sentence":
            s, df, _p = statistic("t", _MODERATE)
            sentences.append((f"t({df[0]}) = {s}. {words().capitalize()} p = .40", None))
            continue
        if plan == "two statistics":
            first, first_df, _p = statistic("t", _MODERATE)
            s, df, _p = statistic("t", _LARGE)
            text = f"t({first_df[0]}) = {first} and t({df[0]}) = {s}, both p < .001"
            offset = text.index(" and ") + len(" and ")
            sentences.append((text, (offset, "t", s, df, "<", ".001", "right")))
            continue
        kind, form = _TEST_FORMS[index]
        bounds = {"moderate": _MODERATE, "near": _SMALL}.get(plan, _LARGE)
        s, df, p = statistic(kind, bounds)
        if plan == "moderate":
            sign, printed = _printed_p(draw, p, draw(st.sampled_from(("=", "<"))))
        elif plan == "large":
            sign, printed = _printed_p(draw, p, shapes[number % len(shapes)])
        else:
            sign, printed = draw(st.sampled_from(_FAR["small" if plan == "near" else "large"]))
        d1, d2 = (*df, "", "")[:2]
        text = form.format(d1=d1, d2=d2, s=s, sign=sign, p=printed)
        lead = draw(st.sampled_from(_NOT_TEXTBOOK)) if plan == "quiet" else ""
        said = {"moderate": "right", "large": "right", "quiet": "quiet"}.get(plan, "far")
        sentences.append((lead + text, (len(lead), kind, s, df, sign, printed, said)))

    parts: list[str] = []
    expected: list[tuple[Any, ...]] = []
    for text, planted in sentences:
        opening = words().capitalize() + " "
        if planted is not None:
            at = len("".join(parts)) + len(opening) + planted[0]
            expected.append((at, *planted[1:]))
        parts.append(f"{opening}{text} {words()}.{draw(st.sampled_from((' ', chr(10))))}")
    return "".join(parts), expected


@holds(100, _reported_tests())
def test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic(
    planted: tuple[str, list[tuple[Any, ...]]],
) -> None:
    """Each test is found where it stands, its statistic, degrees of freedom and P as they
    are printed, and nothing else is: not a P in the next sentence, and not the P of a
    second statistic for the first. A P that follows from its statistic over every value
    their printed digits allow agrees with it, one that does not is found, and a test its
    sentence says is not the textbook one is not judged."""
    from manuscript_guard.stats.reported import judge, reported_tests

    text, expected = planted
    found = reported_tests(text)
    assert [(r.start, r.kind, r.statistic, r.df, r.sign, r.p) for r in found] == [
        planted[:6] for planted in expected
    ], text
    for test, (*_read, said) in zip(found, expected, strict=True):
        verdict = judge(test)
        if said == "quiet":
            assert verdict is None, (test, text)
        else:
            assert verdict is not None and verdict.inconsistent is (said == "far"), (
                test, verdict,
            )  # fmt: skip


def _a_statistic_is_read_at_its_printed_value(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import reported

    patch.setattr(reported, "_range", lambda printed: (float(printed), float(printed)))


def _a_p_is_looked_for_past_its_sentence(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import reported

    patch.setattr(reported, "_SENTENCE_END", re.compile(r"(?!)"))


def _a_p_is_looked_for_past_the_next_statistic(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import reported

    reach = reported._reach
    patch.setattr(
        reported, "_reach", lambda match, following, ends, length: reach(match, None, ends, length)
    )


def _less_than_is_read_as_equal_to(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import reported

    patch.setattr(reported, "_SIGNS", {**reported._SIGNS, "<": "="})


def _a_test_that_is_not_the_textbook_one_is_judged(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import reported

    patch.setattr(reported, "QUIET", re.compile(r"(?!)"))


def _the_degrees_of_freedom_of_f_are_taken_the_other_way(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import reported

    p = reported._p
    patch.setattr(reported, "_p", lambda kind, statistic, df: p(kind, statistic, df[::-1]))


def _a_symbol_in_emphasis_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import reported

    plain = reported._STATISTIC.pattern.replace("[*_]{0,2}", "")
    patch.setattr(reported, "_STATISTIC", re.compile(plain))


def _a_test_over_two_lines_is_not_read(patch: pytest.MonkeyPatch) -> None:
    """A line break inside a test is read as nothing it can match."""
    from manuscript_guard.stats import reported

    for name in ("_STATISTIC", "_P"):
        pattern = getattr(reported, name).pattern.replace(chr(92) + "n", chr(92) + "x01")
        patch.setattr(reported, name, re.compile(pattern))


def _a_power_of_ten_is_read_as_its_mantissa(patch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from manuscript_guard.stats import reported

    p_range = reported._p_range
    cut = re.compile("[eE]| ?[x\N{MULTIPLICATION SIGN}]")
    patch.setattr(
        reported, "_p_range", lambda test: p_range(replace(test, p=cut.split(test.p)[0]))
    )


# ------------------------------------------------------------ a section found by its heading

#: What a paper calls its Methods, as G4 has always read a heading for them: with "methods"
#: in it, numbered, marked or not. And headings that are no Methods.
_THE_METHODS = (
    "Methods", "2. Methods", "2.1 Methods", "II. Methods", "(3) Methods", "2.Methods",
    "**2. Methods**", "Patients and methods", "Materials and methods", "Materials & methods",
    "Methods and analysis", "Statistical methods",
)  # fmt: skip
_NO_METHODS = ("Approach", "Study population", "Analyses", "A method for signal detection",
               "Methodology")  # fmt: skip
#: What a paper calls its abstract, and what a journal's profile may call it.
_THE_ABSTRACT = ("Abstract", "1. Abstract", "Structured abstract", "Summary", "Overview")
_ABSTRACT_TITLES = (None, "Summary", "Overview")
#: A paper's title written as a heading over the whole paper, holding the word.
_TITLE = "# Statistical methods for signal detection\n\n"


def _under_a_title(text: str) -> str:
    """The paper with its title as a heading over it, every other heading one level down."""
    lowered = re.sub(r"(?m)^(#+) ", lambda found: "#" + found.group(1) + " ", text)
    return _TITLE + lowered


@st.composite
def _papers_by_heading(draw: st.DrawFn) -> list[tuple[str, str, str, str | None, bool]]:
    """A paper for every heading above, with the Methods, the abstract and the title the
    profile gives the abstract each named every way, each with and without the paper's title
    as a heading over it, among what is drawn each time: an abstract structured with a
    Methods of its own or not, a subsection under the Methods or not, and words between.
    Every name and both layouts are in every example: a rule broken for one of them is seen
    whatever the seed."""

    def words() -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))

    papers = []
    filler = words()
    for methods in (*_THE_METHODS, *_NO_METHODS):
        for abstract in _THE_ABSTRACT:
            # Drawn once for the pair, and read under each title a profile may give the
            # abstract and in both layouts: so many papers are too large an example drawn
            # one by one.
            own, sub = draw(st.booleans()), draw(st.booleans())
            opening = "\n\n## Methods\n\nBasil " if own else "\n\nBasil "
            under = "\n\n## Statistical analysis\n\n" if sub else " "
            text = (
                f"# {abstract}{opening}{filler}.\n\n# Introduction\n\n{filler}.\n\n"
                f"# {methods}\n\nCoriander {filler}.{under}{filler}.\n\n"
                f"# Results\n\n{filler}.\n"
            )
            for named in _ABSTRACT_TITLES:
                papers.append((text, methods, abstract, named, own))
                papers.append((_under_a_title(text), methods, abstract, named, own))
    return papers


@holds(30, _papers_by_heading())
def test_a_section_g4_counts_present_is_a_section_the_gates_read(
    papers: list[tuple[str, str, str, str | None, bool]],
) -> None:
    """G4 counts a required section present by its heading, and G9 reads the Methods and
    the word count the abstract by theirs. Where they disagreed, G4 passed "2. Methods" and
    G9 compared a wrong parameter with no text, saying nothing. A Methods G4 counts is the
    Methods G9 reads: never the abstract's own, nor the paper's title over it all. An
    abstract G4 counts is the one whose words are counted as the abstract's. An abstract
    nothing names as one ("Overview" with no profile to say so) is a section like any other,
    and its Methods may be the first."""
    from manuscript_guard.classify import rules_out_methods
    from manuscript_guard.gates.journal import _present
    from manuscript_guard.text.sections import measure, split_sections

    for text, methods, abstract, named, own in papers:
        sections = split_sections(text)
        present = _present("Methods", sections, named)
        read = methods_gate.methods_in(text, named)
        is_one = abstract in _THE_ABSTRACT[:3] or abstract == named
        unnamed = own and not is_one and not rules_out_methods(abstract)
        assert present == (methods in _THE_METHODS or unnamed), (text, named)
        assert present == (read is not None), (text, named)
        if read is not None and not unnamed:
            assert "Coriander" in read and "Basil" not in read, (text, read)
        counted = measure(text, named).abstract_words
        assert _present("Abstract", sections, named) == is_one, (text, named)
        assert (counted > 0) == is_one, (text, named, counted)


# --------------------------------------------------------------------------- models named

#: One of every way G15 reads a model named in the Methods, with the kind it names, and
#: one of every place it must not: hidden from the page, inside a longer word, after a word
#: that makes it the name of another model, or in the Results, where `found` is false. A
#: bar stands where the name begins, after a word that leaves it the name it is.
_NAMED = (
    ("logistic regression", "logistic regression", True),
    ("Logistic Regression", "logistic regression", True),
    ("log binomial regression", "log-binomial regression", True),
    ("negative\nbinomial model", "negative binomial regression", True),
    ("probit models", "probit regression", True),
    ("<!-- Poisson regression -->", None, False),
    ("`gamma regression`", None, False),
    ("quasilogistic regression", None, False),
    ("conditional logistic regression", None, False),
    ("Mixed effects\nlogistic models", None, False),
    ("zero-inflated negative binomial model", None, False),
    ("multivariable |logistic regression", "logistic regression", True),
    ("Modified |Poisson regression", "Poisson regression", True),
    ("was conditional. |Logistic models", "logistic regression", True),
    ("was exact\n\n|probit regression", "probit regression", True),
    ("\n\n## Logistic regression\n\n", None, False),
    ("\n\nPoisson models\n--------------\n\n", None, False),
)


@st.composite
def _planted_names(draw: st.DrawFn) -> tuple[str, list[tuple[int, str]]]:
    """Filler words with every way of naming a model planted under a Methods heading, and
    the same names again under the Results, in an order and among words drawn each time."""
    parts: list[str] = []
    found: list[tuple[int, str]] = []

    def filler() -> str:
        words = draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=5))
        return "".join(draw(st.sampled_from((" ", " ", "\n"))) + word for word in words)

    for heading, methods in (
        (draw(st.sampled_from(_METHODS_HEADINGS)), True),
        (draw(st.sampled_from(_OTHER_HEADINGS)), False),
    ):
        parts.append(f"{heading}\n\n{filler().strip().capitalize()}")
        for written, kind, counted in draw(st.permutations(_NAMED)):
            before, _bar, name = written.rpartition("|")
            parts.append(filler() + " " + before)
            if methods and counted:
                found.append((len("".join(parts)), kind))
            parts.append(name)
        parts.append(f"{filler()}.\n\n")
    return "".join(parts), found


@holds(150, _planted_names())
def test_a_model_named_in_the_methods_is_found_where_it_stands_and_nowhere_it_does_not(
    planted: tuple[str, list[tuple[int, str]]],
) -> None:
    """A model named in the Methods is found in any case, with a space, a hyphen or a line
    break between its words, and in the plural, with the kind it names. Nothing is found in
    a comment, in code, inside a longer word, in a heading, ATX or setext, or in the
    Results. Nor directly after a word that makes it the name of another model,
    "conditional" or "mixed effects", while any other word before it, a full stop or a new
    paragraph between, leaves it found."""
    text, expected = planted
    found = [(start, kind) for start, _end, kind in models_gate.named_in_methods(text)]
    assert found == expected, text


# --------------------------------------------------------------------------- Methods claims

#: Every kind of paragraph the claims of `{{method.x}}` are read in. Each example holds one of
#: each, in an order drawn each time: what a property draws first is what Hypothesis varies
#: least, and a kind drawn as one among several is, under some seeds, never drawn at all.
_CLAIM_KINDS = (
    "ends", "inside", "side by side", "comment line", "comment inline", "heading above",
    "bare", "anchor in a comment",
)  # fmt: skip


#: Headings a Methods section is divided by, each still the Methods to `is_methods`.
_SUBHEADINGS = ("## Statistical analysis", "## Definitions", "### Data sources")


@st.composite
def _planted_claims(
    draw: st.DrawFn,
) -> tuple[str, list[tuple[tuple[str, ...], str, int, int]], list[int]]:
    """A Methods section of every kind of paragraph, its words drawn each time, with the
    claims its anchors make (their steps, their words, the lines of the first word and of the
    anchors) and the lines of the paragraphs that point at no step."""
    text = ["# Methods\n\n"]
    claims: list[tuple[tuple[str, ...], str, int, int]] = []
    bare: list[int] = []
    names = (f"step{n}" for n in range(100))

    def at() -> int:
        return "".join(text).count("\n") + 1

    def words() -> str:
        drawn = draw(st.lists(st.sampled_from(FILLER), min_size=2, max_size=6))
        return "".join(
            (draw(st.sampled_from((" ", " ", "\n"))) if n else "") + word
            for n, word in enumerate(drawn)
        )

    def sentence() -> str:
        said = words()
        return said[0].upper() + said[1:] + "."

    def claim(*pieces: str, said: str | None = None) -> None:
        """Write `pieces` as one claim, then its anchors, from the second piece on."""
        first = at()
        text.append(pieces[0])
        anchors = pieces[1:]
        steps = tuple(re.findall(r"method\.([a-z0-9_.]+)", "".join(anchors)))
        line = at() + len(re.match(r"\s*", "".join(anchors)).group().split("\n")) - 1
        text.extend(anchors)
        shown = said if said is not None else pieces[0]
        claims.append((steps, " ".join(shown.split()), first, line))

    def anchor() -> str:
        return f"{{{{method.{next(names)}}}}}"

    for kind in draw(st.permutations(_CLAIM_KINDS)):
        if kind == "ends":
            claim(f"{words()}\n{sentence()}", f"\n{anchor()}")
        elif kind == "inside":
            claim(sentence(), f" {anchor()}")
            first, second = sentence(), anchor()
            text.append(" ")
            claim(first, f" {second}")
        elif kind == "side by side":
            gap = draw(st.sampled_from(("", " ", "\n")))
            claim(sentence(), f"{draw(st.sampled_from((' ', chr(10))))}{anchor()}{gap}{anchor()}")
        elif kind == "comment line":
            before, after = words(), sentence()
            note = f"<!-- {words()} -->"
            claim(f"{before}\n{note}\n{after}", f" {anchor()}", said=f"{before} {after}")
        elif kind == "comment inline":
            before, after = words(), sentence()
            note = f"<!-- {words()} -->"
            claim(f"{before} {note} {after}", f" {anchor()}", said=f"{before} {after}")
        elif kind == "heading above":
            text.append(f"{draw(st.sampled_from(_SUBHEADINGS))}\n")
            claim(sentence(), f" {anchor()}")
        elif kind == "bare":
            bare.append(at())
            text.append(sentence())
        else:
            bare.append(at())
            text.append(f"{sentence()} <!-- {anchor()} -->")
        text.append("\n\n")
    return "".join(text), claims, bare


@holds(150, _planted_claims())
def test_an_anchor_claims_the_text_back_to_the_anchor_before_it_or_its_paragraph(
    planted: tuple[str, list[tuple[tuple[str, ...], str, int, int]], list[int]],
) -> None:
    """An anchor claims what stands before it, back to the anchor before it or the start of
    its paragraph, its spaces and line breaks each read as one space: not past a heading,
    not the words of a comment, and the same text for anchors side by side. A comment on a
    line of its own does not end the paragraph, and an anchor in a comment is none. A
    Methods paragraph with no anchor is one that points at no step."""
    text, expected, bare = planted
    claims, open_ = methods_gate._anchored_in(Path("main.md"), text)
    assert [(c.steps, c.text, c.line, c.anchor_line) for c in claims] == expected, text
    assert [paragraph.line for paragraph in open_] == bare, text


#: Every place an anchor stands in a paragraph. Each example holds one of each, as
#: `_CLAIM_KINDS` says why.
_ANCHOR_PLACES = (
    "a line of its own inside", "a line of its own at the end", "two lines of their own",
    "a line each at the end", "side by side on a line of their own", "the end of a line",
    "inside a line", "under a heading", "over a list", "opening its paragraph",
    "under a heading, no blank line", "nowhere",
)  # fmt: skip


@st.composite
def _anchored_methods(draw: st.DrawFn) -> tuple[str, list[str], list[int]]:
    """A Methods section with an anchor in every place one stands, its words drawn each time;
    the words of each paragraph pandoc is to read in it as printed, in order; and the first
    line of each run of lines of nothing but anchors inside a paragraph, where the run ends
    one. Its lines end as Unix ends them or as Windows does, and the last one may not be
    ended."""
    names = (f"step{n}" for n in range(1000))
    lines: list[str] = ["# Methods"]
    paragraphs: list[str] = []
    inside: list[int] = []

    def sentence() -> str:
        said = " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=2, max_size=5)))
        return said[0].upper() + said[1:] + "."

    def anchor() -> str:
        return f"{{{{method.{next(names)}}}}}"

    def add(*block: str, splits: tuple[int, ...] = ()) -> None:
        """A blank line, then `block`; `splits` are its lines that end a paragraph."""
        lines.append("")
        inside.extend(len(lines) + 1 + at for at in splits)
        lines.extend(block)

    for place in draw(st.permutations(_ANCHOR_PLACES)):
        one, two = sentence(), sentence()
        pad = draw(st.sampled_from(("", " ", "\t", "  ")))
        whole, apart, splits_before = [f"{one} {two}"], [one, two], len(inside)
        if place == "a line of its own inside":
            add(one, f"{pad}{anchor()}{pad}", two, splits=(1,))
        elif place == "a line of its own at the end":
            add(one, two, f"{anchor()}{pad}")
        elif place == "two lines of their own":
            add(one, anchor(), f"{pad}{anchor()}", f"{two} {anchor()}", splits=(1,))
        elif place == "a line each at the end":
            add(one, two, anchor(), f"{pad}{anchor()}{pad}")
        elif place == "side by side on a line of their own":
            add(one, f"{anchor()}{pad}{anchor()}", two, splits=(1,))
        elif place == "the end of a line":
            add(f"{one} {anchor()}", two)
        elif place == "inside a line":
            add(f"{one} {anchor()} {two}")
        elif place == "under a heading":
            add(draw(st.sampled_from(_SUBHEADINGS)))
            add(one, anchor(), two, splits=(1,))
        elif place == "over a list":
            add(one, anchor(), f"- {two}", splits=(1,))
            apart = [one]  # the item is a list's, not a paragraph
        elif place == "opening its paragraph":
            add(anchor(), one, two)
        elif place == "under a heading, no blank line":
            add(draw(st.sampled_from(_SUBHEADINGS)), anchor(), one, two)
        else:
            add(one, two)
        paragraphs += apart if len(inside) > splits_before else whole
    text = "\n".join(lines) + draw(st.sampled_from(("\n", "")))
    return text.replace("\n", draw(st.sampled_from(("\n", "\r\n")))), paragraphs, inside


def _paragraphs_pandoc_reads(markdown: str) -> list[str]:
    """The words of each paragraph pandoc reads in `markdown`, a line break between two as a
    space and anything else that is no word by its name."""
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        pytest.skip("pandoc is not installed, and the paragraphs are the ones it reads")
    read = subprocess.run(
        [pandoc, "-f", "markdown", "-t", "json"],
        input=markdown.encode("utf-8"),
        capture_output=True,
        check=True,
        timeout=120,
    )

    def said(inline: dict) -> str:
        kind = inline["t"]
        return inline["c"] if kind == "Str" else " " if kind in ("Space", "SoftBreak") else kind

    return [
        "".join(said(inline) for inline in block["c"])
        for block in json.loads(read.stdout)["blocks"]
        if block["t"] == "Para"
    ]


@holds(40, _anchored_methods())
def test_an_anchors_own_line_is_warned_where_it_ends_a_paragraph_in_the_document(
    planted: tuple[str, list[str], list[int]],
) -> None:
    """The warning names exactly the lines of nothing but anchors that make pandoc read
    more paragraphs in the text as printed than the source has between its blank lines: one
    inside a paragraph, and not one that opens or ends it, under a heading or not. Pandoc's
    reading is held too, so that the lines the generator says end a paragraph do."""
    text, paragraphs, inside = planted
    assert _paragraphs_pandoc_reads(placeholders.substitute(text, {})) == paragraphs, text
    assert methods_gate.anchor_lines(text) == inside, text


# ------------------------------------------------------------ pointers to tables and figures

#: How a table or a figure is placed: by its binding, or written into the text.
_PLACE = {
    "table": ("{{table.t%d}}", "| Drug | Reports |\n|---|---|\n| A | %d |"),
    "figure": ("{{figure.f%d}}", "![The forest plot %d](f.png)"),
}
#: How a pointer to one is written, as the singular, a list or a range of two.
_WORD = {"table": ("Table", "table"), "figure": ("Figure", "Fig.", "figure")}
_WORDS = {"table": ("Tables", "tables"), "figure": ("Figures", "Figs.")}
_SUPPLEMENTARY = ("%s S%d", "Supplementary %s %d")
_GAPS = (" ", " ", "\N{NO-BREAK SPACE}", "\n")
#: What a finding says a pointer pointed at.
_POINTED = re.compile(r"points at (?P<kind>table|figure) (?P<s>S)?(?P<n>\d+),")


@st.composite
def _planted_pointers(draw: st.DrawFn) -> tuple[str, str, set[tuple[str, bool, int]]]:
    """A main text and a supplement placing tables and figures, and citing each of the main
    text's in order; and pointers planted at what neither carries, one of each kind in
    every example: past the main text's tables, in a list, past the supplement's tables in
    the supplement's own words, and past the figures. The main text's tables and the
    supplement's are placed by binding only, so they are counted; the main text's figures
    include one placed by hand, so they are not, and a pointer past them is not said. What
    the counted pointers point at is the third part."""

    def words() -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))

    counts = {
        (False, "table"): draw(st.integers(2, 3)),
        (False, "figure"): draw(st.integers(1, 2)),
        (True, "table"): draw(st.integers(1, 2)),
        (True, "figure"): draw(st.integers(0, 1)),
    }
    parts: dict[bool, list[str]] = {False: ["# Results\n"], True: ["# Supplementary\n"]}
    for (supplementary, kind), count in counts.items():
        for number in range(1, count + 1):
            # The main text's first figure is placed by hand, so its figures are not
            # counted; every other display is placed by its binding.
            by_hand = number == 1 and kind == "figure" and not supplementary
            placed = _PLACE[kind][by_hand] % number
            if supplementary:
                cite = draw(st.sampled_from(_SUPPLEMENTARY)) % (_WORD[kind][0], number)
            else:
                cite = f"{draw(st.sampled_from(_WORD[kind]))}{draw(st.sampled_from(_GAPS))}{number}"
            parts[supplementary].append(f"{words().capitalize()} in {cite}.\n\n{placed}\n")
    planted: set[tuple[str, bool, int]] = set()
    for kind in ("table", "figure"):
        past = counts[False, kind] + draw(st.integers(1, 40))
        parts[False].append(f"{words().capitalize()} {_WORD[kind][0]} {past}.\n")
        if kind == "table":
            planted.add((kind, False, past))
    listed = counts[False, "table"] + draw(st.integers(1, 3))
    join = draw(st.sampled_from((" and ", ", ", " & ")))
    plural = draw(st.sampled_from(_WORDS["table"]))
    parts[False].append(f"{words().capitalize()} {plural} 1{join}{listed}.\n")
    planted.add(("table", False, listed))
    beyond = counts[True, "table"] + 1
    form = draw(st.sampled_from(_SUPPLEMENTARY))
    parts[False].append(f"{words().capitalize()} {form % ('Table', beyond)}.\n")
    planted.add(("table", True, beyond))
    return "\n".join(parts[False]), "\n".join(parts[True]), planted


@holds(100, _planted_pointers())
def test_a_pointer_names_what_the_document_carries_or_is_said(
    planted: tuple[str, str, set[tuple[str, bool, int]]],
) -> None:
    """A pointer to a table or a figure is held to the tables and figures each document
    places, whichever way it places them: one pointing past them is said, a list read whole,
    and one that points at what is there passes, cited in the order it is placed."""
    import tempfile

    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.pointers import check_pointers

    main, supplement, expected = planted
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "paper.yaml").write_text("title: A paper\n", encoding="utf-8")
        manuscript = root / "manuscript"
        (manuscript / "supplementary").mkdir(parents=True)
        (manuscript / "main.md").write_text(main, encoding="utf-8")
        (manuscript / "supplementary" / "S1.md").write_text(supplement, encoding="utf-8")
        report = check_pointers(load_project(root)[0])
    said = {f.code for f in report.findings}
    assert said <= {"pointer-to-nothing", "pointers-unchecked"}, (main, supplement, said)
    assert "pointers-unchecked" in said, (main, supplement, report.findings)
    named = (_POINTED.search(f.message) for f in report.findings)
    found = {
        (at["kind"], bool(at["s"]), int(at["n"])) for at in named if at is not None
    }
    assert found == expected, (main, supplement, report.findings)


# --------------------------------------------------------------------------------- bindings


@holds(200, texts(), signs(), bindings())
def test_a_binding_is_placed_where_it_stands(manuscript: str, nobodys: str, opened: str) -> None:
    """A binding that does not resolve is reported by its line and column, and a malformed
    one by its line. `parse` looks them up among the starts of the file's lines, and they
    have to be what counting gives: the line feeds before the binding and one more, and the
    characters since the last of them and one more, in a file whose lines Windows ended as
    in any other. The third text has a binding planted where a line begins, since the other
    two seldom hold one and that is where the lookup is out, if it is. What else Python
    ends a line at, a form feed for one, is too seldom drawn before a binding to be held
    here: `tests/test_text.py` names each."""
    for text in (manuscript, nobodys, opened):
        bound, malformed = parse_bindings(text)
        for found in bound:
            line_start = text.rfind("\n", 0, found.start) + 1
            assert found.line == text.count("\n", 0, found.start) + 1, (text, found)
            assert found.col == found.start - line_start + 1, (text, found)
        for raw, offset, line in malformed:
            assert line == text.count("\n", 0, offset) + 1, (text, raw, offset)


# ------------------------------------------------------------------------------- vocabulary


def _judged(text: str, entries: list[dict[str, Any]]):
    file = _file(0, MAIN, text, [], False)
    passage = Passage(file.path, file.text, file.printed, file.line_of)
    return judge_vocabulary([passage], entries, PAPER)


def _words(sentence: list[str]) -> str:
    return " ".join(sentence)


@st.composite
def _rendered(draw: st.DrawFn, term: str, *, joints: tuple[str, ...]) -> str:
    """`term` as the documented rule finds it: a word with two capitals together as it is
    written, any other in any case; a hyphen, a space or one line break between two words;
    the plural `s` where the term is written without one."""
    words = re.split(r"[\s-]+", term)
    shout = draw(st.booleans())
    shown = []
    for word in words:
        if capitals_together(word):
            shown.append(word)
        elif shout:
            shown.append(word.upper())
        else:
            shown.append(draw(st.sampled_from((word, word.capitalize()))))
    text = shown[0]
    for word in shown[1:]:
        text += draw(st.sampled_from(joints)) + word
    last = words[-1]
    held_to_its_capitals = shown[-1] == last and last != last.lower() and last.upper() == last
    if not last.lower().endswith("s") and draw(st.booleans()):
        text += "S" if shout and not held_to_its_capitals else "s"
    return text


#: The entries terms are planted from. Not `Covid-19` given up for `COVID-19`: set in
#: capitals, as a heading sets it, the term given up is the term kept.
_PLANTED = tuple(entry for entry in AGREED if entry["use"] != "COVID-19")


@st.composite
def _planted_terms(draw: st.DrawFn) -> tuple[str, list[dict[str, Any]], dict[str, list[int]]]:
    """A manuscript of filler words with terms a vocabulary gave up planted in it, and
    where each stands that the reading must find: among the paper's own words. The same
    terms are planted where it must not look: in a quotation, in code, in a comment, in a
    link's address, in an image's caption and in the reference list."""
    entries = draw(st.lists(st.sampled_from(_PLANTED), min_size=1, max_size=3, unique_by=str))
    given_up = [term for entry in entries for term in entry["avoid"]]
    kept = [entry["use"] for entry in entries]
    parts: list[str] = []
    stands: dict[str, list[int]] = {}

    def filler(least: int = 1, most: int = 5) -> str:
        return _words(draw(st.lists(st.sampled_from(FILLER), min_size=least, max_size=most)))

    def term(*, joints: tuple[str, ...], counted: bool) -> str:
        chosen = draw(st.sampled_from(given_up))
        marks = draw(st.sampled_from(("", "", "*", "_", "**")))
        shown = draw(_rendered(chosen, joints=joints))
        if counted:
            stands.setdefault(chosen, []).append(len("".join(parts)) + len(marks))
        return marks + shown + marks

    def sentence(*, joints: tuple[str, ...], counted: bool) -> None:
        """Words with, now and then, a term given up, a term kept or an `or` among them."""
        parts.append(filler().capitalize())
        for _ in range(draw(st.integers(0, 3))):
            kind = draw(st.sampled_from(("given up", "given up", "kept", "or", "words")))
            parts.append(" ")
            if kind == "given up":
                parts.append(term(joints=joints, counted=counted))
            elif kind == "kept":
                parts.append(draw(_rendered(draw(st.sampled_from(kept)), joints=joints)))
            elif kind == "or":
                parts.append("or")
            parts.append(" " + filler())
        parts.append(".")

    for _ in range(draw(st.integers(1, 6))):
        kind = draw(
            st.sampled_from(
                ("paragraph", "paragraph", "paragraph", "heading", "item", "quotation", "listing",
                 "comment", "code", "address", "caption")
            )
        )  # fmt: skip
        if kind == "paragraph":
            for line in range(draw(st.integers(1, 3))):
                parts.append("\n" if line else "")
                sentence(joints=(" ", "-", "\n"), counted=True)
        elif kind == "heading":
            parts.append("## ")
            sentence(joints=(" ", "-"), counted=True)
        elif kind == "item":
            parts.append("- ")
            sentence(joints=(" ", "-"), counted=True)
        elif kind == "quotation":
            parts.append("> ")
            sentence(joints=(" ", "-"), counted=False)
        elif kind == "listing":
            parts.append("```\n")
            sentence(joints=(" ", "-"), counted=False)
            parts.append("\n```")
        elif kind == "comment":
            parts.append("<!-- ")
            sentence(joints=(" ", "-"), counted=False)
            parts.append(" -->")
        elif kind == "code":
            hidden = term(joints=(" ",), counted=False)
            parts.append(f"{filler().capitalize()} `{hidden}` {filler()}.")
        elif kind == "address":
            hidden = term(joints=("-",), counted=False).strip("*_")
            parts.append(f"{filler().capitalize()} [{filler()}](https://example.org/{hidden}).")
        else:
            parts.append(f"![{term(joints=(' ',), counted=False)}](figure.png)")
        parts.append("\n\n")
    if draw(st.booleans()):
        parts.append("# References\n\n1. ")
        sentence(joints=(" ", "-"), counted=False)
        parts.append("\n")
    return "".join(parts), entries, stands


@holds(150, _planted_terms())
def test_a_term_given_up_is_found_where_it_stands_and_nowhere_it_does_not(
    planted: tuple[str, list[dict[str, Any]], dict[str, list[int]]],
) -> None:
    """Every match maps back to its place, and what is hidden stays hidden. Each term given
    up is reported once, with the number of times it stands among the paper's own words and
    the line of the first; a term kept is not reported, nor one inside a term kept, nor the
    word "or" for `OR`; and nothing is counted in a quotation, a listing, a comment, code,
    a link's address, an image's caption or the reference list."""
    text, entries, stands = planted
    report = _judged(text, entries)
    assert not [f for f in report.findings if f.code == "vocabulary-conflict"], entries
    kept = {term: entry["use"] for entry in entries for term in entry["avoid"]}
    expected = {
        (
            f"{term!r} is used {'once' if len(places) == 1 else f'{len(places)} times'}; "
            f"this paper's term is {kept[term]!r}",
            text.count("\n", 0, places[0]) + 1,
        )
        for term, places in stands.items()
    }
    found = {(f.message, f.line) for f in report.findings if f.code == "term-avoided"}
    assert found == expected, text
    assert report.counts["vocabulary_found"] == len(stands)
    for finding in report.findings:
        assert finding.path == MAIN and finding.context, finding
        assert " ".join(finding.context.split()) in " ".join(text.split()), (finding, text)


def _as_read(term: str) -> str:
    """A term as two entries that mean the same one write it: in any case, with a hyphen
    or a space between its words, in the singular or the plural."""
    return " ".join(term.casefold().replace("-", " ").split()).removesuffix("s")


_QUOTED = re.compile(r"'([^']*)'")
_HOW_OFTEN = re.compile(r"used (once|\d+ times)")


@holds(200, texts(TERMS), vocabularies(), st.randoms(use_true_random=False))
def test_the_order_of_the_entries_changes_nothing_that_is_found(
    text: str, entries: list[dict[str, Any]], shuffled: Any
) -> None:
    """A vocabulary is a list in a file, and a co-author who adds an entry adds it
    anywhere. Which terms are found, where and how often cannot turn on that, nor which
    terms the entries disagree about. The sentence may, and the test below holds the ways:
    so the terms a finding quotes are compared as they are read, each once."""

    def said(order: list[dict[str, Any]]) -> tuple[list[tuple[Any, ...]], dict[str, int]]:
        report = _judged(text, order)
        told = [
            (f.code, f.line or 0, sorted(set(map(_as_read, _QUOTED.findall(f.message)))),
             _HOW_OFTEN.findall(f.message))
            for f in report.findings
        ]  # fmt: skip
        return sorted(told), report.counts

    other = list(entries)
    shuffled.shuffle(other)
    assert said(entries) == said(other), (text, entries, other)


def test_the_sentence_of_a_conflict_is_worded_by_the_order_of_the_entries() -> None:
    """A known limit, held so that it is known. What the entries disagree about does not
    turn on their order; how it is said does, in three ways the test above found: the
    rivals are listed in the order the entries give them; a term is quoted as the first
    entry to name it wrote it; and of a term kept in the singular and in the plural, the
    one named is the one kept last. Each is one conflict about the same term either way.
    DESIGN.md has it under Known gaps."""

    def sentences(entries: list[dict[str, Any]]) -> list[str]:
        return [f.message for f in _judged("", entries).findings]

    one = {"use": "subject", "avoid": ["participant"]}
    other = {"use": "patient", "avoid": ["participant"]}
    assert sentences([one, other]) == ["'participant' is to give way to 'subject' and 'patient'"]
    assert sentences([other, one]) == ["'participant' is to give way to 'patient' and 'subject'"]

    hyphen = {"use": "in vitro", "avoid": ["in-vitro"]}
    spaced = {"use": "in vitro", "avoid": ["in vitro"]}
    assert sentences([spaced, hyphen]) == ["'in vitro' is a term to use and a term to avoid"]
    assert sentences([hyphen, spaced]) == [
        "'in vitro' is a term to use and 'in-vitro' a term to avoid, and the two are read "
        "as one term"
    ]

    singular = {"use": "subject", "avoid": ["subject"]}
    plural = {"use": "subjects", "avoid": ["subject"]}
    assert sentences([plural, singular]) == ["'subject' is a term to use and a term to avoid"]
    assert sentences([singular, plural]) == [
        "'subjects' is a term to use and 'subject' a term to avoid, and the two are read "
        "as one term"
    ]


# ------------------------------------------------------------- an author in a blind document

#: Each way of writing what names an author of `PEOPLE`, with what the build says it names,
#: and what names nobody. A bar stands where the finding begins, inside a link to the iD.
_PEOPLE_WRITTEN = (
    ("Ada Example", "Ada Example"),
    ("Ada\nExample", "Ada Example"),
    ("Ada\N{NO-BREAK SPACE}Example", "Ada Example"),
    ("A. Example", "Ada Example"),
    ("A.Example", "Ada Example"),
    ("Example, A.", "Ada Example"),
    ("Example, A", "Ada Example"),
    ("Example,\nAB", "Ada Example"),
    ("Sean O'Brien", "Sean O'Brien"),
    ("Sean O\N{RIGHT SINGLE QUOTATION MARK}Brien", "Sean O'Brien"),
    ("S. O\N{RIGHT SINGLE QUOTATION MARK}Brien", "Sean O'Brien"),
    ("Mary Ann van der Berg", "Mary Ann van der Berg"),
    ("Mary\nAnn van der\tBerg", "Mary Ann van der Berg"),
    ("M. van der Berg", "Mary Ann van der Berg"),
    ("van der Berg, M.", "Mary Ann van der Berg"),
    ("https://orcid.org/|0000-0002-1825-0097", "the ORCID iD 0000-0002-1825-0097"),
    ("ADA.EXAMPLE@INVALID.EXAMPLE", "the e-mail address ada.example@invalid.example"),
    ("department of clinical\npharmacology", "Department of Clinical Pharmacology"),
    ("DEPARTMENT OF CLINICAL PHARMACOLOGY", "Department of Clinical Pharmacology"),
    ("Ada Examples", None),
    ("A Example", None),
    ("Example A", None),
    ("Example AB", None),
    ("O\N{RIGHT SINGLE QUOTATION MARK}Brien", None),
    ("Ada Exampel", None),
    ("ada example", None),
    ("Example", None),
    ("Ada", None),
    ("van der Berg", None),
    ("Example University", None),
    ("Springfield", None),
    ("Japan", None),
    ("0000-0002-1825-0098", None),
)


@st.composite
def _planted_people(draw: st.DrawFn) -> tuple[str, list[tuple[str, int]]]:
    """Every way of writing an author above, and every way that names nobody, in an order
    and among words drawn each time, with what the build should find and where."""
    parts: list[str] = []
    found: list[tuple[str, int]] = []
    for written, what in draw(st.permutations(_PEOPLE_WRITTEN)):
        words = draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4))
        parts.append(" ".join(words) + draw(st.sampled_from((" ", "\n", "; "))))
        before, _bar, name = written.rpartition("|")
        parts.append(before)
        if what is not None:
            found.append((what, len("".join(parts))))
        parts.append(name + draw(st.sampled_from((" ", ". ", "\n", ", "))))
    return "".join(parts), sorted(found, key=lambda item: (item[1], item[0]))


@holds(150, _planted_people())
def test_an_author_is_found_in_a_blind_document_however_written_and_no_one_else(
    planted: tuple[str, list[tuple[str, int]]],
) -> None:
    """A name with any space between its words, a line break or a no-break space among
    them; an initial before the family name or after it; an ORCID iD inside its link; an
    e-mail address and an institution in any case. Not a family name or a given name alone,
    a city, a country, two words of an institution, nor a name a letter away."""
    text, expected = planted
    assert names_in(text, sought(PEOPLE)) == expected, text


# --------------------------------------------------------------------------------- spelling

#: Words American usage writes and British does not, which a British paper is told of.
AMERICAN = ("color", "center", "tumor", "fiber", "anemia", "pediatric", "edema", "behavior")
BRITISH = ("colour", "centre", "tumour", "fibre")


def test_the_words_planted_are_the_other_usages() -> None:
    listed, _with_ize = _variants()
    assert all(listed[word][0] == "us" for word in AMERICAN)
    assert all(listed[word][0] == "gb" for word in BRITISH)
    assert len(AMERICAN[:4]) < MANY, "more different words than this and they are one finding"


@st.composite
def _planted_spellings(draw: st.DrawFn) -> tuple[str, list[str], dict[str, list[int]]]:
    """A British paper of filler words with American spellings planted in it, and where
    each stands that the reading must find. The same words are planted where it must not
    look, or must read a name: with a capital inside a sentence, in capitals, inside an
    identifier, a file's name or an address, in markup, in a quotation and in code."""
    words = draw(st.lists(st.sampled_from(AMERICAN), min_size=1, max_size=MANY - 1, unique=True))
    kept = draw(st.lists(st.sampled_from(words), max_size=1))
    parts: list[str] = []
    stands: dict[str, list[int]] = {}

    def filler(least: int = 1, most: int = 4) -> str:
        return _words(draw(st.lists(st.sampled_from(FILLER), min_size=least, max_size=most)))

    def sentence(*, counted: bool) -> None:
        word = draw(st.sampled_from(words))
        kind = draw(
            st.sampled_from(
                ("inside", "inside", "opening", "a name", "capitals", "identifier", "file",
                 "address", "markup", "code", "the paper's", "none")
            )
        )  # fmt: skip
        read = counted and word not in kept

        def here(shown: str) -> str:
            if read:
                stands.setdefault(word, []).append(len("".join(parts)))
            return shown

        if kind == "opening":
            parts.append(here(word.capitalize()) + " " + filler() + ".")
            return
        parts.append(filler().capitalize() + " ")
        if kind == "inside":
            parts.append(here(word))
        elif kind == "a name":
            parts.append(word.capitalize())
        elif kind == "capitals":
            parts.append(word.upper())
        elif kind == "identifier":
            parts.append(draw(st.sampled_from((f"{word}_2", f"{word}2", f"mean_{word}"))))
        elif kind == "file":
            parts.append(f"{word}.csv")
        elif kind == "address":
            parts.append(f"info@{word}-lab.org")
        elif kind == "markup":
            parts.append(f'<span style="{word}:red">{filler()}</span>')
        elif kind == "code":
            parts.append(f"`{word}`")
        elif kind == "the paper's":
            parts.append(draw(st.sampled_from(BRITISH)))
        else:
            parts.append(filler())
        parts.append(" " + filler() + ".")

    for _ in range(draw(st.integers(1, 6))):
        kind = draw(st.sampled_from(("paragraph", "paragraph", "item", "quotation", "listing")))
        if kind == "paragraph":
            for line in range(draw(st.integers(1, 3))):
                parts.append("\n" if line else "")
                sentence(counted=True)
        elif kind == "item":
            parts.append("- ")
            sentence(counted=True)
        elif kind == "quotation":
            parts.append("> ")
            sentence(counted=False)
        else:
            parts.append("```\n")
            sentence(counted=False)
            parts.append("\n```")
        parts.append("\n\n")
    return "".join(parts), kept, stands


@holds(150, _planted_spellings())
def test_a_word_in_the_other_english_is_found_where_it_stands_and_a_name_is_not(
    planted: tuple[str, list[str], dict[str, list[int]]],
) -> None:
    text, kept, stands = planted
    file = _file(0, MAIN, text, [], False)
    passage = Passage(file.path, file.text, file.printed, file.line_of)
    report = judge_spelling([passage], "en-GB", kept, PAPER)
    listed, _with_ize = _variants()
    expected = {
        (
            f"{word!r} is the American spelling of {listed[word][1]!r}, used "
            f"{'once' if len(places) == 1 else f'{len(places)} times'}; "
            "this paper is in British English",
            text.count("\n", 0, places[0]) + 1,
        )
        for word, places in stands.items()
    }
    assert {(f.message, f.line) for f in report.findings} == expected, (text, kept)
    assert report.counts["spelling_other"] == sum(len(places) for places in stands.values())


# ------------------------------------------------------------------------- a rewording

#: A fact as a finding names it. A number by its figures and the mark after them: its
#: minus sign is named with it only where every one of them has it for sure.
_SHOWN = {BINDING: "{{results.%s}}", CITATION: "@key%s", NUMBER: "%s'"}
_WRITTEN = {
    BINDING: ("{{results.%s}}", "{{ results.%s }}"),
    CITATION: ("[@key%s]", "@key%s", "[see @key%s]"),
}
_TYPED_NUMBERS = ("12", "3.84", "1,200", "-0.5", "95", "0.05", ".05", "-.30")
#: How a number is set in its sentence: bare, in brackets, in emphasis, after an equals
#: sign, which says what a number alone says, after the sign of an estimate, in a cell,
#: after a comma, after a product. In all but the last the dash of a negative one is its
#: sign for sure; after the product it is perhaps one, and stands in both texts. Any other
#: sign of comparison is no setting: it is part of its number (`_COMPARED`).
_SET = (
    "%s", "(%s)", "*%s*", "**%s**", "= %s", "\N{ALMOST EQUAL TO}%s", "|**%s**|", "(a,*%s*)",
    "x*%s",
)  # fmt: skip
#: A sign of comparison, by the sign it is read as, in each of the ways it is typed, and the
#: space between it and its number. A number drawn with one keeps it, and each time the
#: sentence is written the sign is typed and spaced another way: that is a rewording.
_COMPARED = {
    "<": ("<", "\\<", "\N{FULLWIDTH LESS-THAN SIGN}"),
    ">": (">", "\\>"),
    "\N{LESS-THAN OR EQUAL TO}": (
        "\N{LESS-THAN OR EQUAL TO}", "<=", "\N{LESS-THAN OR SLANTED EQUAL TO}",
    ),
    "\N{GREATER-THAN OR EQUAL TO}": ("\N{GREATER-THAN OR EQUAL TO}", ">="),
}  # fmt: skip
_AROUND = ("", " ", "\N{NO-BREAK SPACE}", "\N{THIN SPACE}")
#: A sign turned round, taken off or put on, as typed and as a finding names it, before
#: the edit and after it.
_TURNED = (
    (("< 0.047", "'<0.047'"), ("> 0.047", "'>0.047'")),
    (("<0.047", "'<0.047'"), ("0.047", "'0.047'")),
    (("0.047", "'0.047'"), ("\N{LESS-THAN OR EQUAL TO} 0.047", "'\N{LESS-THAN OR EQUAL TO}0.047'")),
    (("= 47", "'47'"), ("\N{NOT EQUAL TO} 47", "'\N{NOT EQUAL TO}47'")),
    (("= 0.047", "'0.047'"), ("< 0.047", "'<0.047'")),
    ((">= 47", "'\N{GREATER-THAN OR EQUAL TO}47'"), ("> 47", "'>47'")),
    (("\\< 0.047", "'<0.047'"), ("= 0.047", "'0.047'")),
)  # fmt: skip
#: The same sign before the same number, typed and spaced another way: no change.
_RESPACED = (
    ("\N{LESS-THAN OR EQUAL TO} 0.047", "<=0.047"),
    (">= 47", "\N{GREATER-THAN OR EQUAL TO}\N{THIN SPACE}47"),
    ("< 0.047", "\N{NO-BREAK SPACE}<\n0.047"),
    ("\\< 0.047", "<0.047"),
    ("\N{LESS-THAN OR SLANTED EQUAL TO}0.047", "\N{LESS-THAN OR EQUAL TO} 0.047"),
    ("= 0.047", "0.047"),
    ("5 -> 47", "5 \N{RIGHTWARDS ARROW} 47"),
    ("5 -\\> 47", "5 to 47"),
    ("< 0.047", "<\N{HAIR SPACE}0.047"),
)
#: Each of the hyphens typed for a minus sign.
_MINUS_TYPED = ("-", "\N{MINUS SIGN}", "\N{NON-BREAKING HYPHEN}")
#: How the first bound of a range is set: bare, with a per cent sign, a prime or a euro
#: sign, in brackets. Each ends something for sure, so the dash after it joins.
_FIRST_BOUND = ("%s", "%s%%", "%s\N{PRIME}", "%s\N{EURO SIGN}", "(%s)")
_JOINED = ("-", "\N{EN DASH}", " to ")
#: A first bound after which the dash of a range may be a sign: a mark that may close.
_MAY_CLOSE = ("%s'", "*%s*", "**%s**", "x^%s^", "$%s$")
#: What an edit brings that the text before never held.
_UNSEEN = {BINDING: "added", CITATION: "added", NUMBER: "987654"}


@holds(200, texts(HELD), signs())
def test_a_fact_is_where_it_says_and_a_text_is_what_it_was(manuscript: str, nobodys: str) -> None:
    """A finding of `reworded` is placed by the line of a fact, and a fact is compared by
    what was read at its place. And a text holds what it holds: compared with itself it has
    nothing to report, whatever is in it."""
    for text in (manuscript, nobodys):
        folded = text.replace("\r\n", "\n").replace("\r", "\n")
        last = -1
        for fact in facts(text):
            assert last < fact.start < len(folded), (text, fact)
            assert fact.line == folded.count("\n", 0, fact.start) + 1, (text, fact)
            here = folded[fact.start :]
            if fact.kind == BINDING:
                assert here.startswith("{{"), (text, fact)
            elif fact.kind == CITATION:
                assert here.lstrip("-").startswith("@" + fact.text), (text, fact)
            else:
                own = fact.text[len(fact.relation) :]
                signed = fact.minus != NO or own[0] == "+"
                assert not signed or here[0] in reworded_module._MINUS + "+", (text, fact)
                assert here[signed:].startswith(own.lstrip("+")), (text, fact)
            if fact.relation:
                # The sign is typed before the fact, with nothing but its gap between.
                gap = re.compile("(?:" + reworded_module._GAP + r")\Z")
                typed = gap.sub("", folded[: fact.start], count=1)
                forms = [sign for sign, read in RELATIONS.items() if read == fact.relation]
                assert any(typed.endswith(form) for form in forms), (text, fact)
            last = fact.start
        assert not compare(text, text, MAIN).findings, text


@st.composite
def _rewordings(draw: st.DrawFn, did: str) -> tuple[str, str, str, list[str], int]:
    """A text, what an edit made of it, what the edit did besides reword it, which is `did`,
    the facts it did that to as a finding shows them, and the line of the after text it did
    it on.

    Every sentence is written twice, with other words between its facts each time and each
    fact in another of the ways it is written: a number bare, in brackets, in emphasis or
    as a bound of a range, joined each of the ways a range is. That is the rewording, and
    it is free. A comment stands in both, and holds other things in each: a listing in
    the first."""

    def fact() -> tuple[str, str]:
        kind = draw(st.sampled_from((BINDING, CITATION, NUMBER, NUMBER)))
        if kind == NUMBER:
            number = draw(st.sampled_from(_TYPED_NUMBERS))
            if number[0] == "-":
                return kind, number
            return kind, draw(st.sampled_from(("", "", *_COMPARED))) + number
        return kind, f"k{draw(st.integers(1, 4))}"

    sizes = draw(st.lists(st.integers(0, 3), min_size=1, max_size=6))
    before = [[fact() for _ in range(size)] for size in sizes]
    if did == "unsigned":
        before.append([(NUMBER, "-0.5")])
    turnable = [at for at, held in enumerate(before) if held != held[::-1]]
    if did == "turned" and not turnable:
        before.append([(NUMBER, "12"), (BINDING, "k1")])
        turnable = [len(before) - 1]
    if did in ("lost", "changed") and not any(before):
        before.append([fact()])
    holding = [at for at, held in enumerate(before) if held]

    after = [list(held) for held in before]
    shown: list[str] = []
    at = 0
    if did in ("lost", "changed"):
        at = draw(st.sampled_from(holding))
        which = draw(st.integers(0, len(after[at]) - 1))
        kind, text = after[at].pop(which)
        shown.append(_SHOWN[kind] % text.lstrip("-"))
        if did == "changed":
            after[at].insert(which, (kind, _UNSEEN[kind]))
            shown.append(_SHOWN[kind] % _UNSEEN[kind])
    elif did == "new":
        at = draw(st.integers(0, len(after) - 1))
        kind = draw(st.sampled_from((BINDING, CITATION, NUMBER)))
        after[at].insert(draw(st.integers(0, len(after[at]))), (kind, _UNSEEN[kind]))
        shown.append(_SHOWN[kind] % _UNSEEN[kind])
    elif did == "unsigned":
        at = len(after) - 1
        after[at] = [(NUMBER, "0.5")]
        shown += ["'-0.5'", "'0.5'"]
    elif did == "turned":
        at = draw(st.sampled_from(turnable))
        after[at].reverse()

    def filler() -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=3)))

    def written(held: list[tuple[str, str]], sure: bool) -> str:
        parts = [filler().capitalize()]
        at = 0
        while at < len(held):
            kind, text = held[at]
            follows = held[at + 1] if at + 1 < len(held) else ("", "-")
            if (
                kind == follows[0] == NUMBER
                and text[0] not in ("-", ".", *_COMPARED)
                and follows[1][0] not in ("-", ".", *_COMPARED)
                and draw(st.booleans())
            ):
                # Two numbers as the bounds of a range, in one of the ways it is joined.
                # They are read as the two numbers each time: the dash of a range is no sign.
                low = draw(st.sampled_from(_FIRST_BOUND)) % text
                parts.append(low + draw(st.sampled_from(_JOINED)) + follows[1])
                at += 2
            elif kind == NUMBER:
                relation = text[0] if text[0] in _COMPARED else ""
                retyped = text[len(relation) :].replace("-", draw(st.sampled_from(_MINUS_TYPED)))
                if relation:
                    sign = draw(st.sampled_from(_COMPARED[relation]))
                    retyped = sign + draw(st.sampled_from(_AROUND)) + retyped
                parts.append(draw(st.sampled_from(_SET[:-1] if sure else _SET)) % retyped)
                at += 1
            else:
                parts.append(draw(st.sampled_from(_WRITTEN[kind])) % text)
                at += 1
            parts.append(filler())
        return " ".join(parts) + "."

    comment = draw(st.integers(0, len(before)))
    turned = draw(st.sampled_from(_TURNED))
    texts_of = []
    for sentences, hidden in (
        (before, "<!--\n```r\nset.seed(14)\nx <- {{results.gone}} [@gone2001]\n```\n-->"),
        (after, "<!-- now 15 -->"),
    ):
        # Where a sign is to be taken off, every dash of the text before is one for sure.
        # Each sentence is written again for the text after, so one of them that was
        # perhaps a sign could be a sure one there, and the count could not tell that
        # from the sign that went.
        sure = did == "unsigned" and sentences is before
        paragraphs = [written(held, sure) for held in sentences]
        paragraphs.insert(comment, hidden)
        if did == "beside":
            # A sure sign taken off, beside the same figures after a mark that may close.
            sign = "-" if sentences is before else ""
            paragraphs.append(f"{filler().capitalize()} {sign}47 {filler()} *n*-47.")
        if did == "swapped":
            # The same figures with a sign and without, and the sign at the other one after.
            signs = ("-", "") if sentences is before else ("", "-")
            paragraphs.append(f"{filler().capitalize()} {signs[0]}53 {filler()} {signs[1]}53.")
        if did == "both":
            # Two edits of notation on the same figures: a dash that is perhaps a sign
            # read as a sure one, and a dash that joins read as perhaps one.
            forms = ("x*-61", "n-61") if sentences is before else ("x * -61", "*n*-61")
            paragraphs.append(f"{filler().capitalize()} {forms[0]} {filler()} {forms[1]}.")
        if did == "compared":
            # A sign of comparison turned round, taken off or put on.
            typed = turned[0][0] if sentences is before else turned[1][0]
            paragraphs.append(f"{filler().capitalize()} P {typed} {filler()}.")
        if did == "respaced":
            # The same sign typed and spaced another way, which is a language edit: every
            # way of it in every example, so that a rule broken for one is always seen.
            for pair in _RESPACED:
                typed = pair[0] if sentences is before else pair[1]
                paragraphs.append(f"{filler().capitalize()} P {typed} {filler()}.")
        if did == "unsure":
            # A range whose first bound ends on a mark that may close, joined by a dash in
            # the text before and by "to" in the text after: the dash may have been a sign.
            low = draw(st.sampled_from(_MAY_CLOSE)) % 41
            join = "-" if sentences is before else " to "
            paragraphs.append(f"{filler().capitalize()} {low}{join}43 {filler()}.")
        texts_of.append("\n\n".join(paragraphs) + "\n")
    line = 1 + 2 * (at + (comment <= at))
    last = 1 + 2 * (len(after) + 1)
    if did == "compared":
        shown, line = [turned[0][1], turned[1][1]], last
    if did == "unsure":
        shown, line = ["'43'", "may have lost a minus sign"], last
    if did == "beside":
        shown, line = ["'47'", "'-47'", "has lost its minus sign"], last
    if did == "swapped":
        shown, line = ["'53'", "at the 1st", "at the 2nd"], last
    if did == "both":
        shown, line = ["'61'", "may have gained a minus sign"], last
    return texts_of[0], texts_of[1], did, shown, line


#: Everything an edit does that the property plants, one of each in every example. Drawn
#: one to an example, as they were at first, a kind could go undrawn for a whole run: under
#: `MANUSCRIPT_GUARD_SEED=5` no text had its order turned in 200 examples, and under 8 none
#: had a sign taken off beside a dash that may be one, so the rule broken for each of those
#: passed. What Hypothesis draws first in an example it varies least.
_EDITS = (
    "nothing", "lost", "new", "changed", "unsigned", "turned", "unsure", "beside", "swapped",
    "both", "compared", "respaced",
)  # fmt: skip


@holds(40, st.tuples(*(_rewordings(did) for did in _EDITS)))
def test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands(
    drawn: tuple[tuple[str, str, str, list[str], int], ...],
) -> None:
    assert [did for _before, _after, did, _shown, _line in drawn] == list(_EDITS)
    for one in drawn:
        _held_to_its_edit(one)


def _held_to_its_edit(drawn: tuple[str, str, str, list[str], int]) -> None:
    before, after, did, shown, line = drawn
    report = compare(before, after, MAIN)
    said = [(found.code, found.severity, found.line, found.message) for found in report.findings]
    codes = sorted(found.code for found in report.findings)
    if did == "turned":
        assert codes and set(codes) == {"order-changed"}, (before, after, said)
        assert all(found.severity == "warn" for found in report.findings), said
        assert {found.line for found in report.findings} == {line}, (before, after, said)
        assert report.ok
        return
    expected = {
        "nothing": [],
        "lost": ["fact-lost"],
        "new": ["fact-new"],
        "changed": ["fact-lost", "fact-new"],
        "unsigned": ["sign-lost"],
        "unsure": ["sign-unsure"],
        "beside": ["sign-lost"],
        "swapped": ["sign-moved"],
        "both": ["sign-unsure"],
        "compared": ["fact-lost", "fact-new"],
        "respaced": [],
    }[did]
    assert codes == expected, (before, after, did, said)
    assert report.ok == (did in ("nothing", "unsure", "swapped", "both", "respaced"))
    by_code = {found.code: found for found in report.findings}
    if did in ("unsigned", "unsure", "beside", "swapped", "both"):
        (found,) = report.findings
        assert all(what in found.message for what in shown), (before, after, said)
        assert found.line == line, (before, after, said)
        return
    for code, what in zip(expected, shown, strict=True):
        assert what in by_code[code].message, (before, after, said)
    if "fact-new" in by_code:
        assert by_code["fact-new"].line == line, (before, after, said)


# ------------------------------------------------------------ the words beside a quoted value

#: A value a ledger records, as its display is written, one of each kind: a decimal, a whole
#: number, a value with words inside it, and one with letters.
_LEDGER_VALUES = ("2.6", "14", "1 in 4", "IgG4")
#: What stands in a quote and is no word, and words that hold a digit, which are.
_NO_WORDS = ("95%", "2.1-3.2", "(", ")", "3.84", "-", "\N{EN DASH}", "12/40", "100 000")
_DIGIT_WORDS = ("COVID-19", "CYP3A4", "HbA1c", "person-years.")
_QUOTE_GAPS = (" ", "  ", "\n", ", ", "; ", " (", ") ", "\N{NO-BREAK SPACE}")


@st.composite
def _quotes_beside(draw: st.DrawFn) -> list[tuple[str, str, int]]:
    """A quote for each kind of value, of filler words, words with a digit and pieces with
    no letter, in an order drawn each time, with the value among them, and how many words
    stand beside it."""
    quotes = []
    for value in _LEDGER_VALUES:
        words = draw(st.lists(st.sampled_from(FILLER), max_size=6))
        pieces = draw(st.permutations([*words, *_DIGIT_WORDS, *_NO_WORDS, value]))
        gaps = [draw(st.sampled_from(_QUOTE_GAPS)) for _ in pieces]
        quote = "".join(gap + piece for gap, piece in zip(gaps, pieces, strict=True))
        quotes.append((quote, value, len(words) + len(_DIGIT_WORDS)))
    return quotes


@holds(150, _quotes_beside())
def test_the_words_beside_a_quoted_value_are_its_words_and_no_more(
    quotes: list[tuple[str, str, int]],
) -> None:
    """A word is a run between spaces that holds a letter, a digit in it or not; the value is
    taken out first, so "1 in 4" counts no "in"; and a percentage, an interval, a bracket or
    a number alone is no word."""
    for quote, value, count in quotes:
        assert len(literature_sources.words_beside(quote, value)) == count, (quote, value)


# -------------------------------------------------------------------------------- quotations


def test_every_character_a_quotation_is_typed_without_is_drawn_into_a_source() -> None:
    """`TYPOGRAPHY` is what a page holds where a person types something else, and the
    quotation property holds that each is folded. It held it of eleven of the eighteen:
    the other seven were in the table and in no source, so a folding that lost one of
    them passed."""
    drawn = "".join((*SOURCE_WORDS, *SOURCE_GAPS))
    never = [f"U+{ord(character):04X}" for character in TYPOGRAPHY if character not in drawn]
    assert not never, never


@holds(150, sources(), signs())
def test_a_source_read_twice_is_read_as_it_was_the_first_time(source: str, nobodys: str) -> None:
    """A source is folded when it is stored and again when a quotation is looked for in
    it. Folded twice it is what it was folded once, or the second reading finds less."""
    for text in (source, nobodys):
        assert normalise(normalise(text)) == normalise(text), text


#: The words of a source that a page sets otherwise than a person types them.
_SET_IN_TYPE = tuple(word for word in SOURCE_WORDS if typed(word) != word)


@holds(150, quotations())
def test_a_quotation_typed_from_its_source_is_found_and_one_it_does_not_hold_is_not(
    drawn: tuple[str, str],
) -> None:
    """The literature chain says a quotation is in its source or is not. A true one that is
    refused for a ligature or a dash teaches the author to stop recording quotations; a
    false one that is accepted is a misquotation with a check mark on it."""
    source, quote = drawn
    assert contains(source, quote), (source, quote)
    assert contains(source, typed(quote)), (source, typed(quote))
    assert not contains(source, f"{typed(quote)} similar"), (source, quote)
    # A word set in type is in few of the quotations drawn, and under some seeds one of
    # them is in none of a run's: with seeds 1 and 3, of twelve tried, a folding that had
    # lost the ligature of "effect" passed. So each is put after every source drawn, and
    # looked for there as it is typed.
    for word in _SET_IN_TYPE:
        assert contains(f"{source} {word}", typed(word)), (source, word)


_WHOLE_NUMBER = re.compile(r"\d+(?:\.\d+)?")


@holds(150, quotations())
def test_a_value_is_stated_whole_or_not_at_all(drawn: tuple[str, str]) -> None:
    """`3.4` is not stated by a quotation that says `13.42`: a value is found as a whole
    number, never as some of the characters of a longer one. And a value the quotation is
    said to state has its characters in it."""
    _source, quote = drawn
    words = typed(quote).split()
    for word in words:
        if not _WHOLE_NUMBER.fullmatch(word):
            continue
        assert states_value(quote, word), (quote, word)
        cut = word[1:]
        if cut and cut not in words:
            assert not states_value(quote, cut), (quote, cut)
    for value in ("3.4", "13.42", "14", "0.42", "412", "CI", "effect"):
        if states_value(quote, value):
            assert contains(quote, value), (quote, value)


# ------------------------------------------------------- a quote its source nearly holds

#: The words a quote is drawn from: none of them is a word of the filler around it, so the
#: quote is found where it was put and nowhere else.
_QUOTE_WORDS = (
    "hepatic", "injury", "incidence", "crude", "reported", "signal", "ratio", "class",
    "drug", "liver", "renal", "rash", "fever", "dose", "trial", "arm", "risk", "rate",
)  # fmt: skip
#: What a quote's word was retyped as.
_RETYPED = ("kidney", "cardiac", "monthly", "severe")
#: Each way a source holds a quote nearly.
_NEARLY = (
    "numbers", "words", "header", "split", "symbol", "retyped", "first retyped", "too far",
)  # fmt: skip


@st.composite
def _nearly_quoted(draw: st.DrawFn) -> list[tuple[str, str, str, tuple[Any, ...]]]:
    """A source for each way it can hold a quote nearly: numbers or words between two of
    its words, one of its words split by a hyphen at the end of a line, a symbol for a
    space between two, one of its words retyped, its first retyped, and words between two
    of them past the gap allowed. Each with the quote, the kind, and what is to be said of
    it: the words, and the line it is on."""
    from manuscript_guard.literature.placement import GAP

    def filler(least: int, most: int) -> list[str]:
        return draw(st.lists(st.sampled_from(FILLER), min_size=least, max_size=most))

    def lines(words: list[str]) -> str:
        return "".join(w + draw(st.sampled_from((" ", " ", "\n"))) for w in words)

    cases = []
    for kind in draw(st.permutations(_NEARLY)):
        words = draw(st.lists(st.sampled_from(_QUOTE_WORDS), min_size=6, max_size=9, unique=True))
        n = len(words)
        # Where the source or the quote differs: in its second half, so that the reading
        # from its first word is the longest.
        at = draw(st.integers(max(2, n // 2), n - 2))
        quote = " ".join(words)
        held = list(words)
        joins = [draw(st.sampled_from((" ", " ", "\n"))) for _ in range(n - 1)] + [" "]
        which = at
        if kind == "numbers":
            joins[at] = draw(st.sampled_from(("\n12\n", " 41 42 ", "\n7\n8\n")))
            expected: tuple[Any, ...] = (" ".join(joins[at].split()), words[at], words[at + 1])
        elif kind in ("words", "too far"):
            between = " ".join(filler(*((1, 4) if kind == "words" else (GAP + 1, GAP + 3))))
            joins[at] = draw(st.sampled_from((" ", "\n"))) + between + " "
            expected = (between, words[at], words[at + 1])
        elif kind == "header":
            # A header that holds the quote's next word, which is not its last: one
            # interruption, and the word in it is not the quote's (round 1 of #301).
            at = which = min(at, n - 3)
            between = " ".join([*filler(1, 3), words[at + 1], *filler(1, 3)])
            joins[at] = draw(st.sampled_from((" ", "\n"))) + between + " "
            expected = (between, words[at], words[at + 1])
        elif kind == "split":
            which = draw(st.sampled_from([i for i, w in enumerate(words) if len(w) >= 4]))
            cut = draw(st.integers(2, len(words[which]) - 2))
            held[which] = words[which][:cut] + "-\n" + words[which][cut:]
            expected = (words[which][:cut], words[which][cut:])
        elif kind == "symbol":
            joins[at] = draw(st.sampled_from(("\N{MIDDLE DOT}", "/", " & ")))
            expected = (words[at], joins[at], words[at + 1])
        elif kind == "retyped":
            changed = list(words)
            changed[at] = draw(st.sampled_from(_RETYPED))
            quote = " ".join(changed)
            expected = (at, words[at - 1], changed[at])
        else:
            changed = [draw(st.sampled_from(_RETYPED)), *words[1:]]
            quote = " ".join(changed)
            expected = (changed[0],)
        before = lines(filler(1, 12))
        source = before + "".join(w + j for w, j in zip(held, joins, strict=True))
        source += lines(filler(1, 8))
        # The line it is on: what the source puts in starts there; a split word's first
        # half is there; a symbol follows the word before it.
        offset = len(before) + sum(
            len(w) + len(j) for w, j in zip(held[:which], joins[:which], strict=True)
        )
        if kind in ("numbers", "words", "header", "too far", "symbol"):
            offset += len(held[at])
        if kind in ("numbers", "words", "header", "too far"):
            offset += len(joins[at]) - len(joins[at].lstrip())
        cases.append((source, quote, kind, (*expected, source.count("\n", 0, offset) + 1)))
    return cases


@holds(100, _nearly_quoted())
def test_a_quote_its_source_nearly_holds_is_said_to_and_where(
    cases: list[tuple[str, str, str, tuple[Any, ...]]],
) -> None:
    """G7 fails a quote that is not in its source exactly, and says what the source holds of
    it: its words in order with numbers between two of them, or words, or with one of them
    split by a hyphen, or a symbol where the quote has a space; its words up to one retyped;
    all but a first word retyped. Each on the line of the source it is on. Words further
    apart than the gap allowed are not the quote."""
    from manuscript_guard.literature.placement import place, said

    for source, quote, kind, expected in cases:
        assert not contains(source, quote), (kind, source, quote)
        placement = place(source, quote)
        assert placement is not None, (kind, source, quote)
        told = said(placement)
        line = expected[-1]
        if kind in ("numbers", "words", "header"):
            between, before, after = expected[:3]
            shown = f"the source has '{between}' between '{before}' and '{after}' (line {line})"
            assert shown in told, (kind, told, source)
            assert ("numbers, such as" in told) is (kind == "numbers"), (kind, told)
        elif kind == "split":
            first, second = expected[:2]
            assert told == (
                f"its words are all there in order; '{first}' and '{second}' are one word, "
                f"split by a hyphen (line {line})"
            ), (told, source)
        elif kind == "symbol":
            before, symbol, after = expected[:3]
            shown = f"between '{before}' and '{after}' (line {line}) the source has '{symbol}'"
            assert shown in told, (told, source)
        elif kind in ("retyped", "too far"):
            found = expected[0] if kind == "retyped" else quote.split().index(expected[2])
            opening = f"{found} of its {len(quote.split())} words are there in order"
            assert told.startswith(opening), (kind, told, source)
            if kind == "retyped":
                assert f"after '{expected[1]}' the quote has '{expected[2]}'" in told, told
        else:
            assert f"its first word, '{expected[0]}', is not before them" in told, (told, source)


def _the_words_of_a_quote_are_never_apart(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.literature import placement

    patch.setattr(placement, "GAP", 0)


def _a_word_split_by_a_hyphen_is_two(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.literature import placement

    patch.setattr(placement, "_split_at", lambda source, tokens, k, word: False)


def _numbers_between_two_words_are_words(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.literature import placement

    patch.setattr(placement.Break, "numbers", property(lambda self: False))


def _a_quote_is_read_from_its_first_word_only(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.literature import placement

    patch.setattr(placement, "STARTS", 1)


def _a_source_s_lines_are_counted_from_0(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.literature import placement

    patch.setattr(placement, "_line", lambda source, at: source.count("\n", 0, at))


def _each_word_is_found_where_it_first_is(patch: pytest.MonkeyPatch) -> None:
    """The reading as it was before round 1 of #301: each word at its first occurrence."""
    from manuscript_guard.literature import placement

    def first_found(source, tokens, words, first, at):
        found, splits = [at], []
        k = at + 1
        if tokens[at].word != words[first]:
            splits.append(at)
            k = at + 2
        for word in words[first + 1 :]:
            for m in range(k, min(k + placement.GAP + 1, len(tokens))):
                if tokens[m].word == word or placement._split_at(source, tokens, m, word):
                    split = tokens[m].word != word
                    found.append(m)
                    splits += [m] if split else []
                    k = m + 1 + split
                    break
            else:
                break
        return found, splits

    patch.setattr(placement, "_walk", first_found)


def _what_differs_is_looked_for_at_the_ends_only(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.literature import placement

    patch.setattr(placement, "_within", lambda *drawn: None)


# ------------------------------------------------------------- a unit written after a binding

#: What may follow a binding, with the unit read there, or None where none is: a gap of each
#: kind, a power, a slash, a symbol of the list, and words that open with a symbol's letters.
_AFTER_A_BINDING = (
    (" mg", "mg"),
    ("\N{NO-BREAK SPACE}\N{MICRO SIGN}g/kg", "\N{MICRO SIGN}g/kg"),
    ("\N{THIN SPACE}\N{GREEK SMALL LETTER MU}g", "\N{GREEK SMALL LETTER MU}g"),
    ("%", "%"),
    (" \N{PER MILLE SIGN}", "\N{PER MILLE SIGN}"),
    ("\nmmol/L", "mmol/L"),
    (" cm\N{SUPERSCRIPT TWO}", "cm\N{SUPERSCRIPT TWO}"),
    (" min-1", "min-1"),
    (" \N{DEGREE SIGN}C", "\N{DEGREE SIGN}C"),
    (" mg/kg/day", "mg/kg/day"),
    (" minutes", None),
    (" mgs", None),
    (" group", None),
    (" hours", None),
    ("\n\nmg", None),
    (" and 5 mg", None),
    (" cases", None),
)


@st.composite
def _units_planted(draw: st.DrawFn) -> tuple[str, list[tuple[str, int, str]]]:
    """A binding before each way of writing what follows it, in an order and among words
    drawn each time, with the unit that should be read after each."""
    parts: list[str] = []
    found: list[tuple[str, int, str]] = []
    for index, (after, unit) in enumerate(draw(st.permutations(_AFTER_A_BINDING))):
        words = draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4))
        parts.append(" ".join(words) + draw(st.sampled_from((" ", "\n", "; "))))
        key = f"k{index}"
        if unit is not None:
            found.append((key, len("".join(parts)), unit))
        parts.append(f"{{{{results.{key}}}}}" + after + draw(st.sampled_from((". ", ", ", "; "))))
    return "".join(parts), found


@holds(150, _units_planted())
def test_the_unit_after_a_binding_is_read_however_spaced_and_no_word_is(
    planted: tuple[str, list[tuple[str, int, str]]],
) -> None:
    """A symbol after any space, a no-break or thin space or one line break, with its power
    or a slash and what it divides by; not a word that opens with a symbol's letters, not a
    unit after a blank line, and not one after another word."""
    text, expected = planted
    found = [(w.key, w.start, w.unit) for w in bound_units_gate.units_after(text)]
    assert found == expected, text


# ---------------------------------------------------------------------- an ISBN's check digit


@st.composite
def _isbns(draw: st.DrawFn) -> tuple[list[str], list[str]]:
    """An ISBN-10 and an ISBN-13 with their check digits worked out here, cut into groups
    where drawn, and written in fields every way a field holds them: each with hyphens, each
    with spaces, both in one field parted by a space in either order, and both with labels,
    a qualifier and a semicolon. And each with one digit changed. An ISBN-10 that opens
    with 978 or 979 is not drawn (DESIGN.md, Known gaps)."""
    ten = draw(
        st.lists(st.integers(0, 9), min_size=9, max_size=9).filter(
            lambda digits: digits[:3] not in ([9, 7, 8], [9, 7, 9])
        )
    )
    check = (11 - sum((10 - at) * d for at, d in enumerate(ten)) % 11) % 11
    isbn10 = "".join(map(str, ten)) + ("X" if check == 10 else str(check))
    thirteen = [9, 7, draw(st.sampled_from((8, 9)))] + draw(
        st.lists(st.integers(0, 9), min_size=9, max_size=9)
    )
    check = (10 - sum(d * (1 if at % 2 == 0 else 3) for at, d in enumerate(thirteen)) % 10) % 10
    isbn13 = "".join(map(str, thirteen)) + str(check)
    hyphened, spaced, changed = [], [], []
    for isbn in (isbn10, isbn13):
        cuts = sorted(draw(st.sets(st.integers(1, len(isbn) - 1), min_size=1, max_size=4)))
        pieces = [isbn[a:b] for a, b in zip([0, *cuts], [*cuts, len(isbn)], strict=True)]
        at = draw(st.integers(0, len(isbn) - 2))
        changed.append(
            isbn[:at] + str((int(isbn[at]) + draw(st.integers(1, 9))) % 10) + isbn[at + 1 :]
        )
        hyphened.append("-".join(pieces))
        spaced.append(" ".join(pieces))
    fields = [
        *hyphened,
        *spaced,
        f"{spaced[0]} {spaced[1]}",
        f"{spaced[1]} {spaced[0]}",
        f"ISBN-10: {spaced[0]}; ISBN-13: {hyphened[1]} (pbk.)",
    ]
    return fields, changed


@holds(300, _isbns())
def test_an_isbn_is_valid_by_its_check_digit_and_one_digit_changed_is_not(
    drawn: tuple[list[str], list[str]],
) -> None:
    """G7 reads an ISBN field however it holds its numbers, and both forms catch any one
    digit changed: an ISBN-10 with any check digit, X included, and an ISBN-13 with the
    weights 1 and 3."""
    from manuscript_guard.gates.identifiers import problems

    fields, changed = drawn
    for field in fields:
        assert problems("k", {"type": "misc", "isbn": field}) == [], field
    for field in changed:
        found = problems("k", {"type": "misc", "isbn": field})
        assert [code for code, _said in found] == ["identifier-malformed"], (field, found)


# ------------------------------------------------------------- a figure that estimates itself

_FIGURE_FILLER = {
    "python": ("x = 1", "fig, ax = plt.subplots()", "values = frame['y']", "ax.set_xlabel('Dose')"),
    "r": ("x <- 1", "p <- ggplot(d, aes(x, y))", "theme_set(theme_bw())", "d$z <- d$x + 1"),
}
_SEED_CALLS = {"python": ("np.random.seed(7)", "rng = np.random.default_rng(7)"),
               "r": ("set.seed(7)",)}  # fmt: skip


def _called(draw: st.DrawFn, rule, language: str) -> str:
    """A name a script calls one of the rule's calls by."""
    if rule.prefixes:
        prefix = draw(st.sampled_from(rule.prefixes))
        return prefix + ("choice" if prefix == "random." else "normal")
    name = draw(st.sampled_from(rule.names))
    if language == "r":
        return name
    return draw(st.sampled_from(("sns.", "frame.", "frame.y."))) + name


@st.composite
def _figure_scripts(draw: st.DrawFn) -> list[tuple[str, str, list[tuple[int, str]]]]:
    """A script in each language, seeded and not, with every call that estimates written
    bare, told not to by each argument that does, with its seed or divisor given and given
    as nothing, and in a comment and a string; in an order drawn each time, with where each
    is found."""
    from manuscript_guard.gates.figure_estimates import rules

    scripts = []
    for language in ("python", "r"):
        equals = "=" if language == "python" else " = "
        nothing = draw(st.sampled_from(("None",) if language == "python" else ("NA", "NULL")))
        for seeded in (False, True):
            plans: list[tuple[str, bool]] = []
            for rule in rules()[language]:
                call = _called(draw, rule, language)
                plans.append((f"{call}(d)", not (rule.seeded and seeded)))
                for name, values in rule.unless.items():
                    plans.append((f"{call}(d, {name}{equals}{values[0]})", False))
                if rule.stated:
                    plans.append((f"{call}(d, {rule.stated}{equals}7)", False))
                    plans.append(
                        (f"{call}(d, {rule.stated}{equals}{nothing})", not (rule.seeded and seeded))
                    )
                plans.append((f"# {call}(d)", False))
                plans.append((f'label = "{call}(d)"', False))
            lines = [draw(st.sampled_from(_FIGURE_FILLER[language]))]
            if seeded:
                lines.append(draw(st.sampled_from(_SEED_CALLS[language])))
            text, expected = "", []
            for line, found in draw(st.permutations(plans)):
                lines.append(draw(st.sampled_from(_FIGURE_FILLER[language])))
                text = "\n".join(lines) + "\n"
                if found:
                    expected.append((len(text), line.split("(")[0]))
                lines.append(line)
            scripts.append((language, "\n".join(lines) + "\n", expected))
    return scripts


@holds(100, _figure_scripts())
def test_a_call_that_estimates_is_found_unless_it_is_told_not_to(
    scripts: list[tuple[str, str, list[tuple[int, str]]]],
) -> None:
    """Each call that estimates, samples, draws at random or drops rows is found where it
    stands, in Python and R. Not where an argument turns it off or a seed or divisor is
    given, not where a seed set in the script settles a random one, and not in a comment or
    a string. A seed given as nothing ("None", "NA") settles nothing."""
    from manuscript_guard.gates.figure_estimates import estimates_in

    for language, text, expected in scripts:
        found = [(e.call.start, e.call.name) for e in estimates_in(text, language)]
        assert found == expected, (language, text)


def _an_argument_that_turns_an_estimate_off_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_estimates

    arguments = figure_estimates._arguments
    patch.setattr(figure_estimates, "_arguments", lambda code, at: ({}, arguments(code, at)[1]))


def _a_call_is_known_only_by_the_last_part_of_its_name(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_estimates

    patch.setattr(figure_estimates, "named", lambda name, names: name.split(".")[-1] in names)


def _a_seed_in_the_script_settles_nothing(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_estimates

    patch.setattr(figure_estimates, "SEEDS", {"python": (), "r": ()})


def _a_seed_given_as_nothing_is_taken_for_one(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_estimates

    patch.setattr(figure_estimates, "NOT_GIVEN", (None,))


# ------------------------------------------------------------- one work under two keys


@st.composite
def _one_work_two_ways(draw: st.DrawFn) -> tuple[dict[str, str], dict[str, str]]:
    """Two entries naming one work, each identifier written another way in the second:
    a DOI dressed and in other case, a PMID with leading noughts, a PMCID in lower case,
    and an ISBN-10 beside the ISBN-13 it is. Every kind in every example."""
    ends = st.text("abcdefghij0123456789", min_size=1, max_size=4)
    suffix = draw(ends) + draw(st.text("abcdefghij0123456789.-/", max_size=8)) + draw(ends)
    doi = f"10.{draw(st.integers(1000, 99999))}/{suffix}"
    ten = draw(
        st.lists(st.integers(0, 9), min_size=9, max_size=9).filter(
            lambda digits: digits[:3] not in ([9, 7, 8], [9, 7, 9])
        )
    )
    check = (11 - sum((10 - at) * d for at, d in enumerate(ten)) % 11) % 11
    isbn10 = "".join(map(str, ten)) + ("X" if check == 10 else str(check))
    # Worked out here, not by the code under test: 978, the first nine, a new check digit.
    body = [9, 7, 8, *ten]
    isbn13 = "".join(map(str, body)) + str(
        (10 - sum(d * (1 if at % 2 == 0 else 3) for at, d in enumerate(body)) % 10) % 10
    )
    pmid = draw(st.integers(1, 10**6))  # nine digits at most, its noughts included
    pmcid = draw(st.integers(1, 10**8))
    first = {"doi": doi, "pmid": str(pmid), "pmcid": f"PMC{pmcid}", "isbn": isbn13}
    second = {
        "doi": draw(st.sampled_from(("https://doi.org/", "doi:", ""))) + doi.upper() + ".",
        "pmid": "0" * draw(st.integers(1, 2)) + str(pmid),
        "pmcid": f"pmc{pmcid}",
        "isbn": "-".join([isbn10[:1], isbn10[1:4], isbn10[4:9], isbn10[9:]]),
    }
    return first, second


@holds(200, _one_work_two_ways())
def test_one_work_is_one_work_however_its_identifiers_are_written(
    drawn: tuple[dict[str, str], dict[str, str]],
) -> None:
    from manuscript_guard.gates.duplicates import identifiers_of

    first, second = drawn
    for kind in ("doi", "pmid", "pmcid", "isbn"):
        a = identifiers_of({"type": "book", kind: first[kind]})
        b = identifiers_of({"type": "book", kind: second[kind]})
        assert a and a == b, (kind, first[kind], second[kind], a, b)


# --------------------------------------------------------------------------------------- TeX


@holds(200, lines())
def test_what_the_title_rule_reports_stands_in_the_line(line: str) -> None:
    """The finding quotes the command the document would be printed without, and names the
    sign past which no maths was read. Both are in the line, the sign before the command;
    and a line with no backslash and no `&` has nothing to report, since neither a command
    nor a character reference can be written without one."""
    found = tex_outside_maths(line)
    if "\\" not in line and "&" not in line:
        assert found is None, line
    if found is None:
        return
    assert found.command.startswith("&" if found.reference else "\\"), (line, found)
    assert found.command in line, (line, found)
    assert found.unread in ("", "digit", "space", "open", "paired"), (line, found)
    if found.after:
        assert found.after in "`<[@~^", (line, found)
        assert found.after in line[: line.rindex(found.command)], (line, found)


@holds(200, lines())
def test_the_sentence_and_the_rule_agree_on_whether_there_is_anything_to_say(line: str) -> None:
    """`check` prints the sentence and `init` refuses a title by the rule. One that spoke
    where the other was silent would refuse a title `check` passes, or pass one it fails."""
    silent = tex_outside_maths(line) is None
    assert (outside_maths(line) is None) == silent, line
    assert (outside_maths(line, keyword=True) is None) == silent, line


# ------------------------------------------------- a property fails when its rule is broken


def _a_quotation_is_the_papers_own(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(vocabulary_gate, "_quotations", lambda printed: [])


def _hiding_takes_the_line_break(patch: pytest.MonkeyPatch) -> None:
    def hide(text: str, spans: Any) -> str:
        chars = list(text)
        for start, end in spans:
            chars[start:end] = NUL * (end - start)
        return "".join(chars)

    patch.setattr(language_gate, "_hide", hide)


def _every_finding_is_on_line_one(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(language_gate._File, "line_of", lambda self, offset: 1)


def _a_binding_that_opens_a_line_is_on_the_line_before(patch: pytest.MonkeyPatch) -> None:
    patch.setattr("manuscript_guard.text.placeholders.bisect_right", bisect_left)


def _a_ligature_is_not_folded(patch: pytest.MonkeyPatch) -> None:
    patch.delitem(literature_sources._EQUIVALENT, "\N{LATIN SMALL LIGATURE FF}")


def _a_value_is_some_characters_of_a_number(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(
        sys.modules[__name__],
        "states_value",
        lambda quote, value: normalise(value).lower() in normalise(quote).lower(),
    )


def _a_comment_is_read_for_its_stops(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import numbers as numbers_gate

    patch.setattr(numbers_gate, "blank_comments", lambda text: text)


def _a_stop_against_a_binding_ends_no_sentence(patch: pytest.MonkeyPatch) -> None:
    from bisect import bisect_left

    from manuscript_guard.gates import numbers as numbers_gate

    patch.setattr(numbers_gate, "_sentence", lambda text, ends, start: bisect_left(ends, start))


def _names_with(**changes: Any):
    """`models._names` rebuilt with one of its readings taken away."""
    import functools

    @functools.cache
    def names() -> re.Pattern[str]:
        listed = sorted(
            {name for entry in models_gate.engines() for name in entry.synonyms},
            key=len, reverse=True,
        )  # fmt: skip
        if changes.get("as_written"):
            words = [re.escape(name) for name in listed]
        else:
            words = [r"[\s-]+".join(map(re.escape, re.split(r"[\s-]+", n))) for n in listed]
        plural = changes.get("plural", "s?")
        return re.compile(
            r"(?<![\w-])(?:" + "|".join(words) + ")" + plural + r"(?![\w-])",
            changes.get("flags", re.IGNORECASE),
        )

    return names


def _a_model_is_named_in_one_case(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(models_gate, "_names", _names_with(flags=0))


def _a_hyphen_is_no_space_in_a_models_name(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(models_gate, "_names", _names_with(as_written=True))


def _a_model_is_never_named_in_the_plural(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(models_gate, "_names", _names_with(plural=""))


def _a_model_named_anywhere_is_named_in_the_methods(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(models_gate, "is_methods", lambda chain: True)


def _a_model_named_in_a_comment_is_named(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(models_gate, "_hidden", lambda text: text)


def _no_word_before_a_name_makes_it_another_model(patch: pytest.MonkeyPatch) -> None:
    """The rule as #233 merged it: "conditional logistic regression" was the fitted kind."""
    patch.setattr(models_gate, "_other_model", lambda hidden, start: False)


def _any_word_before_a_name_makes_it_another_model(patch: pytest.MonkeyPatch) -> None:
    def other(hidden: str, start: int) -> bool:
        return re.search(r"\w[^\S\n]+\Z", hidden[:start]) is not None

    patch.setattr(models_gate, "_other_model", other)


def _a_model_named_in_a_heading_is_named(patch: pytest.MonkeyPatch) -> None:
    """The rule before headings were left alone: a heading was read as the text is."""
    patch.setattr(models_gate, "_heading_lines", lambda text, headings: [])


def _a_new_paragraph_is_a_space_before_a_models_name(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(models_gate, "_BETWEEN", r"[\s.]+")


def _any_convention_is_a_threshold(patch: pytest.MonkeyPatch) -> None:
    def every(classifier: Classifier) -> frozenset[str]:
        return frozenset(rule.id for rule in classifier.conventions)

    patch.setattr(numbers_gate, "chosen_rules", every)


def _the_figure_is_read_with_what_is_before_it(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(numbers_gate, "stated_number", number_in)


def _a_figure_without_its_nought_is_not_read(patch: pytest.MonkeyPatch) -> None:
    def stated(text: str) -> float | None:
        at = re.search(r"\d|\.\d", text)
        return None if at is None else number_in(text[at.start() :])

    patch.setattr(numbers_gate, "stated_number", stated)


def _the_digits_of_a_name_are_its_figure(patch: pytest.MonkeyPatch) -> None:
    def own(text: str) -> str | None:
        at = re.search(r"\d|\.\d", text)
        return None if at is None else text[at.start() :]

    patch.setattr(numbers_gate, "own_figure", own)


def _an_atom_that_opens_with_a_name_states_nothing(patch: pytest.MonkeyPatch) -> None:
    def own(text: str) -> str | None:
        at = re.search(r"\d|\.\d", text)
        if at is None or text[: at.start()][-1:].isalpha():
            return None
        return text[at.start() :]

    patch.setattr(numbers_gate, "own_figure", own)


def _only_a_latin_letter_makes_a_name(patch: pytest.MonkeyPatch) -> None:
    def own(text: str) -> str | None:
        for figure in re.finditer(r"\d[\d.,]*|\.\d+", text):
            if not re.fullmatch(r"[A-Za-z]", text[: figure.start()][-1:]):
                return text[figure.start() :]
        return None

    patch.setattr(numbers_gate, "own_figure", own)


def _a_name_is_a_threshold_like_the_figure_beside_it(patch: pytest.MonkeyPatch) -> None:
    def threshold(text: str, verdict: Any, chosen: frozenset[str]) -> bool:
        return verdict.kind == CONVENTION and verdict.rule in chosen

    patch.setattr(numbers_gate, "typed_threshold", threshold)


def _a_nought_is_trimmed_off_a_number(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(tokens, "_TRAIL", tokens._TRAIL + "0")


def _an_isbn_10_is_not_read_as_its_isbn_13(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import duplicates

    patch.setattr(duplicates, "isbn_13", lambda written: re.sub(r"[\s-]", "", written).upper())


def _an_isbn_s_groups_are_read_as_isbns(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import identifiers

    patch.setattr(
        identifiers, "_isbns",
        lambda field: [p for p in re.split(r"[,;/]|\s(?=\d{3})", field) if p.strip()],
    )  # fmt: skip


def _an_isbn_13_is_weighed_as_an_isbn_10(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import identifiers

    def valid(written: str) -> bool:
        digits = re.sub(r"[\s-]", "", written).upper()
        if not re.fullmatch(r"\d{9}[\dX]|\d{13}", digits):
            return False
        weights = range(len(digits), 0, -1)
        total = sum(w * (10 if d == "X" else int(d)) for w, d in zip(weights, digits, strict=True))
        return total % 11 == 0

    patch.setattr(identifiers, "isbn_valid", valid)


def _a_deviation_is_read_with_its_line_breaks(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import design

    def as_typed(text: str) -> str:
        pattern = dict((name, rule) for name, rule, _ in design.REQUIRED)["deviations"]
        sections = design._plan_sections(text)
        return "".join(
            part.body
            for index, section in enumerate(sections)
            if re.search(pattern, section.title)
            for part in design.subsections(sections, index)
        )

    patch.setattr(design, "deviations_said", as_typed)


def _a_variables_name_is_a_word(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(spelling_gate, "_in_an_identifier", lambda text, start, end: False)


def _a_list_of_pointers_is_its_first(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import pointers

    patch.setattr(pointers, "_numbers", lambda found: [(bool(found["s0"]), int(found["n0"]))])


def _the_supplement_s_tables_are_the_paper_s(patch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from manuscript_guard.gates import pointers

    read = pointers.pointers_in
    patch.setattr(
        pointers, "pointers_in",
        lambda text, path: [replace(p, supplementary=False) for p in read(text, path)],
    )


def _a_figure_placed_by_hand_is_counted_anyway(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import pointers

    patch.setattr(pointers, "_BY_HAND", {**pointers._BY_HAND, "figure": re.compile(r"(?!)")})


def _the_methods_are_read_by_their_old_name(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text import section_names

    old = re.compile(r"^\s*(?:materials and )?methods\b", re.IGNORECASE)
    patch.setattr(section_names, "names_methods", lambda title: bool(old.match(title)))


def _methods_found_without_the_paper_s_structure(patch: pytest.MonkeyPatch, keep: str) -> None:
    """`methods_sections` with one of its two tests of place left out: `keep` says which
    stays, "above" (nothing over it names another part) or "below" (nothing under it does)."""
    from manuscript_guard.classify import rules_out_methods
    from manuscript_guard.gates import journal
    from manuscript_guard.text import section_names

    def found(sections, abstract_title=None):
        out, chain = [], []
        for index, section in enumerate(sections):
            while chain and chain[-1].level >= section.level:
                chain.pop()
            above = list(chain)
            chain.append(section)
            if not section_names.names_methods(section.title):
                continue
            if keep == "above" and any(
                s.names_abstract(abstract_title) or rules_out_methods(s.title) for s in above
            ):
                continue
            below = []
            for later in sections[index + 1 :]:
                if later.level <= section.level:
                    break
                below.append(later)
            if keep == "below" and any(rules_out_methods(s.title) for s in below):
                continue
            out.append(section)
        return out

    patch.setattr(methods_gate, "methods_sections", found)
    patch.setattr(journal, "methods_sections", found)


def _a_title_over_the_paper_is_its_methods(patch: pytest.MonkeyPatch) -> None:
    _methods_found_without_the_paper_s_structure(patch, "above")


def _the_abstract_s_methods_are_the_paper_s(patch: pytest.MonkeyPatch) -> None:
    _methods_found_without_the_paper_s_structure(patch, "below")


def _a_profile_s_abstract_title_is_not_counted(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text import sections

    patch.setattr(sections.Section, "names_abstract", lambda self, named: self.is_abstract)


def _a_sign_is_no_part_of_its_number(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "_sign", lambda text, at: NO)


def _a_sign_of_comparison_is_no_part_of_its_number(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "_compared", lambda text, at, typed: "")


def _a_sign_of_comparison_is_compared_as_typed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "RELATIONS", {sign: sign for sign in RELATIONS})


def _an_arrow_s_head_is_a_sign(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "_ARROW_TAIL", "")


def _an_equals_sign_is_a_sign(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "RELATIONS", {**RELATIONS, "=": "="})


def _a_sign_of_comparison_is_read_only_against_its_number(patch: pytest.MonkeyPatch) -> None:
    pattern = reworded_module._NUMBER.pattern.replace(reworded_module._GAP, "", 1)
    patch.setattr(reworded_module, "_NUMBER", re.compile(pattern))


def _the_order_is_not_looked_at(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "_reordered", lambda before, after: [])


def _a_comment_holds_facts(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "blank_comments", lambda text: text)


def _a_name_is_one_space_apart(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(blinding, "_SPACE", " ")


def _an_institution_is_in_its_own_case(patch: pytest.MonkeyPatch) -> None:
    real = blinding._words
    patch.setattr(blinding, "_words", lambda piece, flags=0: real(piece))


def _an_initial_needs_no_stop(patch: pytest.MonkeyPatch) -> None:
    def name(given: str, family: str) -> re.Pattern[str]:
        initial, surname = re.escape(given[0]), blinding._spaced(family)
        return re.compile(
            rf"(?<!\w)(?:{blinding._spaced(given)}\s+{surname}|{initial}(?:\.\s*|\s+)"
            rf"{surname}|{surname},?\s+{initial}[A-Z]?\.?)(?!\w)"
        )

    patch.setattr(blinding, "_name", name)


def _an_apostrophe_is_matched_as_typed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(
        blinding, "_spaced", lambda words: r"\s+".join(re.escape(w) for w in words.split())
    )


def _a_name_is_not_read_family_name_first(patch: pytest.MonkeyPatch) -> None:
    def name(given: str, family: str) -> re.Pattern[str]:
        initial, surname = re.escape(given[0]), blinding._spaced(family)
        return re.compile(
            rf"(?<!\w)(?:{blinding._spaced(given)}\s+{surname}|{initial}\.\s*{surname})(?!\w)"
        )

    patch.setattr(blinding, "_name", name)


def _every_dash_before_a_figure_is_its_sign(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "_sign", lambda text, at: SURE)


def _a_dash_that_may_be_a_sign_says_nothing(patch: pytest.MonkeyPatch) -> None:
    read = reworded_module._sign
    patch.setattr(
        reworded_module, "_sign", lambda text, at: NO if read(text, at) == MAYBE else read(text, at)
    )


def _an_old_dash_answers_for_a_sign_that_went(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "_newly", lambda now, before: now)


def _a_sign_is_new_by_the_counts_alone(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "_at_a_place", lambda was, now, then, here: True)


def _the_places_of_a_dash_are_not_compared(patch: pytest.MonkeyPatch) -> None:
    compared = reworded_module._sign_warning

    def unmoved(figures: str, was: Any, now: Any, placed: Any, path: Any) -> Any:
        found = compared(figures, was, now, placed, path)
        return None if found is not None and found.code == "sign-moved" else found

    patch.setattr(reworded_module, "_sign_warning", unmoved)


def _a_listing_in_a_comment_is_put_back(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "html_comments", lambda text, fences=None: [])


def _every_stop_ends_a_sentence(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.checking import produce

    patch.setattr(produce, "_ends_a_sentence", lambda before: True)


def _no_stop_ends_a_sentence(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.checking import produce

    patch.setattr(produce, "_ends_a_sentence", lambda before: False)


def _a_stop_inside_a_word_can_end_a_sentence(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.checking import produce

    def ends(before: str) -> bool:
        found = produce.LAST_WORD.search(before)
        if found is None:
            return True
        word = found.group(1).rstrip(".").lower()
        return not (word in produce.NOT_AN_END or len(word) == 1)

    patch.setattr(produce, "_ends_a_sentence", ends)


def _no_abbreviation_is_known(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.checking import produce

    patch.setattr(produce, "NOT_AN_END", frozenset())


def _a_wordless_piece_is_left_alone(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.checking import produce

    def split(flat: str) -> list[str]:
        pieces, at = [], 0
        for found in produce.SENTENCE_END.finditer(flat):
            if produce._ends_a_sentence(flat[: found.start()]):
                pieces.append(flat[at : found.start()].strip())
                at = found.end()
        return [piece for piece in [*pieces, flat[at:].strip()] if piece]

    patch.setattr(produce, "_split", split)
def _a_claim_runs_back_to_its_paragraph(patch: pytest.MonkeyPatch) -> None:
    real = methods_gate.claims_in

    def claims_in(text: str) -> Any:
        found, bare = real(text)
        starts = [start for start, _end in methods_gate._paragraphs(text)]
        return [
            (steps, max(s for s in starts if s <= start), end, anchor)
            for steps, start, end, anchor in found
        ], bare

    patch.setattr(methods_gate, "claims_in", claims_in)


def _anchors_side_by_side_claim_apart(patch: pytest.MonkeyPatch) -> None:
    real = methods_gate.claims_in

    def claims_in(text: str) -> Any:
        found, bare = real(text)
        apart = []
        for steps, start, end, anchor in found:
            apart.append((steps[:1], start, end, anchor))
            apart += [((step,), end, end, anchor) for step in steps[1:]]
        return apart, bare

    patch.setattr(methods_gate, "claims_in", claims_in)


def _a_comment_line_ends_a_paragraph(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text.masking import blank_comments

    real = methods_gate._paragraphs
    patch.setattr(methods_gate, "_paragraphs", lambda text: real(blank_comments(text)))


def _a_claim_keeps_the_words_of_a_comment(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(methods_gate, "blank_comments", lambda text: text)


def _a_heading_is_part_of_the_paragraph_under_it(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(methods_gate, "_HEADING", re.compile(r"(?!)"))


def _a_unit_is_read_after_a_plain_space_only(patch: pytest.MonkeyPatch) -> None:
    pattern = bound_units_gate._UNIT.pattern.replace(bound_units_gate._GAP, " ?", 1)
    patch.setattr(bound_units_gate, "_UNIT", re.compile(pattern))


def _a_unit_is_read_inside_a_longer_word(patch: pytest.MonkeyPatch) -> None:
    pattern = bound_units_gate._UNIT.pattern.rsplit("(?!", 1)[0]
    patch.setattr(bound_units_gate, "_UNIT", re.compile(pattern))


def _a_slash_divides_by_symbols_only(patch: pytest.MonkeyPatch) -> None:
    pattern = bound_units_gate._UNIT.pattern.replace(
        r"/[^\W\d_]+", "/(?:" + bound_units_gate._SYMBOL + ")", 1
    )
    patch.setattr(bound_units_gate, "_UNIT", re.compile(pattern))


def _a_claim_keeps_its_line_breaks(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(methods_gate, "_collapsed", lambda text: text.strip(" "))


def _a_word_with_a_digit_is_no_word(patch: pytest.MonkeyPatch) -> None:
    real = literature_sources.words_beside
    patch.setattr(
        literature_sources,
        "words_beside",
        lambda quote, display: [w for w in real(quote, display) if not any(c.isdigit() for c in w)],
    )


def _the_value_is_left_in_the_quote(patch: pytest.MonkeyPatch) -> None:
    real = literature_sources.words_beside
    patch.setattr(literature_sources, "words_beside", lambda quote, display: real(quote, ""))


def _an_anchor_in_a_comment_is_an_anchor(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(placeholders, "_without_comments", lambda text: text)


def _the_line_below_an_anchors_line_is_not_looked_at(patch: pytest.MonkeyPatch) -> None:
    real = methods_gate._inside
    patch.setattr(methods_gate, "_inside", lambda above, below: real(above, "a line"))


def _the_line_above_an_anchors_line_is_not_looked_at(patch: pytest.MonkeyPatch) -> None:
    real = methods_gate._inside
    patch.setattr(methods_gate, "_inside", lambda above, below: real("a line", below))


def _each_anchors_line_is_its_own_run(patch: pytest.MonkeyPatch) -> None:
    """The rule as it stood at 43739a94: the line directly below counts, whatever it holds."""
    patch.setattr(methods_gate, "_runs", lambda numbers: [(number, number) for number in numbers])


#: A rule broken in one place, and the property that has to fail for it. Each is a way one
#: of these rules has been wrong, or a mutant a review found alive.
BROKEN = {
    "every stop ends a sentence, after et al. and Suppl. too": (
        _every_stop_ends_a_sentence,
        test_every_citation_lies_in_the_sentence_of_its_own_clause,
    ),
    "no stop ends a sentence": (
        _no_stop_ends_a_sentence,
        test_every_citation_lies_in_the_sentence_of_its_own_clause,
    ),
    "a stop inside a word, as in U.S., can end a sentence": (
        _a_stop_inside_a_word_can_end_a_sentence,
        test_every_citation_lies_in_the_sentence_of_its_own_clause,
    ),
    "no abbreviation is known": (
        _no_abbreviation_is_known,
        test_every_citation_lies_in_the_sentence_of_its_own_clause,
    ),
    "a piece with no word of its own is left alone": (
        _a_wordless_piece_is_left_alone,
        test_every_citation_lies_in_the_sentence_of_its_own_clause,
    ),
    "a statistic is read at its printed value, not over what its last digit allows": (
        _a_statistic_is_read_at_its_printed_value,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "a statistic's P is looked for past the end of its sentence": (
        _a_p_is_looked_for_past_its_sentence,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "a statistic's P is looked for past the next statistic": (
        _a_p_is_looked_for_past_the_next_statistic,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "a P below a bound is read as equal to it": (
        _less_than_is_read_as_equal_to,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "a test its sentence calls one-sided or adjusted is judged as two-sided": (
        _a_test_that_is_not_the_textbook_one_is_judged,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "an F's two degrees of freedom are taken the other way round": (
        _the_degrees_of_freedom_of_f_are_taken_the_other_way,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "a statistic's symbol in emphasis is not read": (
        _a_symbol_in_emphasis_is_not_read,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "a test wrapped onto a second line is not read": (
        _a_test_over_two_lines_is_not_read,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "a P written as a power of ten is read as its mantissa": (
        _a_power_of_ten_is_read_as_its_mantissa,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "a claim runs back to the start of its paragraph, past the anchor before it": (
        _a_claim_runs_back_to_its_paragraph,
        test_an_anchor_claims_the_text_back_to_the_anchor_before_it_or_its_paragraph,
    ),
    "anchors side by side claim apart": (
        _anchors_side_by_side_claim_apart,
        test_an_anchor_claims_the_text_back_to_the_anchor_before_it_or_its_paragraph,
    ),
    "a comment on a line of its own ends a paragraph": (
        _a_comment_line_ends_a_paragraph,
        test_an_anchor_claims_the_text_back_to_the_anchor_before_it_or_its_paragraph,
    ),
    "a claim keeps the words of a comment inside it": (
        _a_claim_keeps_the_words_of_a_comment,
        test_an_anchor_claims_the_text_back_to_the_anchor_before_it_or_its_paragraph,
    ),
    "a heading is part of the paragraph under it": (
        _a_heading_is_part_of_the_paragraph_under_it,
        test_an_anchor_claims_the_text_back_to_the_anchor_before_it_or_its_paragraph,
    ),
    "a unit is read after a plain space only": (
        _a_unit_is_read_after_a_plain_space_only,
        test_the_unit_after_a_binding_is_read_however_spaced_and_no_word_is,
    ),
    "a unit is read inside a longer word": (
        _a_unit_is_read_inside_a_longer_word,
        test_the_unit_after_a_binding_is_read_however_spaced_and_no_word_is,
    ),
    "a slash divides by the list's symbols only": (
        _a_slash_divides_by_symbols_only,
        test_the_unit_after_a_binding_is_read_however_spaced_and_no_word_is,
    ),
    "a claim keeps its line breaks": (
        _a_claim_keeps_its_line_breaks,
        test_an_anchor_claims_the_text_back_to_the_anchor_before_it_or_its_paragraph,
    ),
    "a word with a digit in it is no word": (
        _a_word_with_a_digit_is_no_word,
        test_the_words_beside_a_quoted_value_are_its_words_and_no_more,
    ),
    "the value is left in the quote": (
        _the_value_is_left_in_the_quote,
        test_the_words_beside_a_quoted_value_are_its_words_and_no_more,
    ),
    "an anchor in a comment is an anchor": (
        _an_anchor_in_a_comment_is_an_anchor,
        test_an_anchor_claims_the_text_back_to_the_anchor_before_it_or_its_paragraph,
    ),
    "the line below an anchor's own line is not looked at": (
        _the_line_below_an_anchors_line_is_not_looked_at,
        test_an_anchors_own_line_is_warned_where_it_ends_a_paragraph_in_the_document,
    ),
    "the line above an anchor's own line is not looked at": (
        _the_line_above_an_anchors_line_is_not_looked_at,
        test_an_anchors_own_line_is_warned_where_it_ends_a_paragraph_in_the_document,
    ),
    "the line directly below an anchor's own line counts, though it holds only anchors": (
        _each_anchors_line_is_its_own_run,
        test_an_anchors_own_line_is_warned_where_it_ends_a_paragraph_in_the_document,
    ),
    "the words of a quote may never be apart": (
        _the_words_of_a_quote_are_never_apart,
        test_a_quote_its_source_nearly_holds_is_said_to_and_where,
    ),
    "a word split by a hyphen is read as two": (
        _a_word_split_by_a_hyphen_is_two,
        test_a_quote_its_source_nearly_holds_is_said_to_and_where,
    ),
    "numbers between two words of a quote are said to be words": (
        _numbers_between_two_words_are_words,
        test_a_quote_its_source_nearly_holds_is_said_to_and_where,
    ),
    "a quote is read from its first word only": (
        _a_quote_is_read_from_its_first_word_only,
        test_a_quote_its_source_nearly_holds_is_said_to_and_where,
    ),
    "a source's lines are counted from 0": (
        _a_source_s_lines_are_counted_from_0,
        test_a_quote_its_source_nearly_holds_is_said_to_and_where,
    ),
    "each word of a quote is found where it first is": (
        _each_word_is_found_where_it_first_is,
        test_a_quote_its_source_nearly_holds_is_said_to_and_where,
    ),
    "what differs is looked for only before and after a quote": (
        _what_differs_is_looked_for_at_the_ends_only,
        test_a_quote_its_source_nearly_holds_is_said_to_and_where,
    ),
    "a quotation is read as the paper's own words": (
        _a_quotation_is_the_papers_own,
        test_a_term_given_up_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "hiding takes the line break with it": (
        _hiding_takes_the_line_break,
        test_what_is_hidden_leaves_every_other_character_in_its_place,
    ),
    "every finding is on line 1": (
        _every_finding_is_on_line_one,
        test_a_term_given_up_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "a binding that opens a line is put on the line before": (
        _a_binding_that_opens_a_line_is_on_the_line_before,
        test_a_binding_is_placed_where_it_stands,
    ),
    "a ligature is not folded": (
        _a_ligature_is_not_folded,
        test_a_quotation_typed_from_its_source_is_found_and_one_it_does_not_hold_is_not,
    ),
    "a value is some characters of a longer number": (
        _a_value_is_some_characters_of_a_number,
        test_a_value_is_stated_whole_or_not_at_all,
    ),
    "a stop against a binding ends no sentence": (
        _a_stop_against_a_binding_ends_no_sentence,
        test_a_sentence_is_looked_up_as_it_was_counted,
    ),
    "a comment is read for its stops": (
        _a_comment_is_read_for_its_stops,
        test_a_comment_is_white_space_to_the_order_of_intervals,
    ),
    "a model is named in one case only": (
        _a_model_is_named_in_one_case,
        test_a_model_named_in_the_methods_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "a hyphen is no space in a model's name": (
        _a_hyphen_is_no_space_in_a_models_name,
        test_a_model_named_in_the_methods_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "a model is never named in the plural": (
        _a_model_is_never_named_in_the_plural,
        test_a_model_named_in_the_methods_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "a model named anywhere is named in the Methods": (
        _a_model_named_anywhere_is_named_in_the_methods,
        test_a_model_named_in_the_methods_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "a model named in a comment is named": (
        _a_model_named_in_a_comment_is_named,
        test_a_model_named_in_the_methods_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "no word before a model's name makes it another model": (
        _no_word_before_a_name_makes_it_another_model,
        test_a_model_named_in_the_methods_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "any word before a model's name makes it another model": (
        _any_word_before_a_name_makes_it_another_model,
        test_a_model_named_in_the_methods_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "a model named in a heading is named": (
        _a_model_named_in_a_heading_is_named,
        test_a_model_named_in_the_methods_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "a full stop or a new paragraph is a space before a model's name": (
        _a_new_paragraph_is_a_space_before_a_models_name,
        test_a_model_named_in_the_methods_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "a parameter is matched by any convention": (
        _any_convention_is_a_threshold,
        test_a_typed_parameter_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "the figure of a typed parameter is read with what is typed before it": (
        _the_figure_is_read_with_what_is_before_it,
        test_a_typed_parameter_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "a typed parameter written without its nought is not read": (
        _a_figure_without_its_nought_is_not_read,
        test_a_typed_parameter_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "the digits in the name of a statistic are read as its figure": (
        _the_digits_of_a_name_are_its_figure,
        test_a_typed_parameter_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "an atom that opens with the name of a statistic states no number": (
        _an_atom_that_opens_with_a_name_states_nothing,
        test_a_typed_parameter_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "only a letter of the Latin alphabet makes a figure part of a name": (
        _only_a_latin_letter_makes_a_name,
        test_a_typed_parameter_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "the name of a statistic is a threshold like the figure beside it": (
        _a_name_is_a_threshold_like_the_figure_beside_it,
        test_a_typed_parameter_is_found_where_it_stands_and_nowhere_it_does_not,
    ),
    "a nought is trimmed off a number": (
        _a_nought_is_trimmed_off_a_number,
        test_a_number_is_seen_where_it_stands_and_judged_one_way,
    ),
    "an ISBN-13 is weighed as an ISBN-10": (
        _an_isbn_13_is_weighed_as_an_isbn_10,
        test_an_isbn_is_valid_by_its_check_digit_and_one_digit_changed_is_not,
    ),
    "an ISBN-10 is not read as its ISBN-13": (
        _an_isbn_10_is_not_read_as_its_isbn_13,
        test_one_work_is_one_work_however_its_identifiers_are_written,
    ),
    "an ISBN's groups are read as ISBNs": (
        _an_isbn_s_groups_are_read_as_isbns,
        test_an_isbn_is_valid_by_its_check_digit_and_one_digit_changed_is_not,
    ),
    "an argument that turns a figure's estimate off is not read": (
        _an_argument_that_turns_an_estimate_off_is_not_read,
        test_a_call_that_estimates_is_found_unless_it_is_told_not_to,
    ),
    "a call that estimates is known only by the last part of its name": (
        _a_call_is_known_only_by_the_last_part_of_its_name,
        test_a_call_that_estimates_is_found_unless_it_is_told_not_to,
    ),
    "a seed set in a figure's script settles nothing": (
        _a_seed_in_the_script_settles_nothing,
        test_a_call_that_estimates_is_found_unless_it_is_told_not_to,
    ),
    "a seed given as None or NA is taken for a seed": (
        _a_seed_given_as_nothing_is_taken_for_one,
        test_a_call_that_estimates_is_found_unless_it_is_told_not_to,
    ),
    "a deviation is read with its line breaks": (
        _a_deviation_is_read_with_its_line_breaks,
        test_a_deviation_rewrapped_says_what_it_said_and_a_word_more_does_not,
    ),
    "a variable's name is read as a word": (
        _a_variables_name_is_a_word,
        test_a_word_in_the_other_english_is_found_where_it_stands_and_a_name_is_not,
    ),
    "a list of tables is read as its first": (
        _a_list_of_pointers_is_its_first,
        test_a_pointer_names_what_the_document_carries_or_is_said,
    ),
    "the supplement's tables are counted as the paper's": (
        _the_supplement_s_tables_are_the_paper_s,
        test_a_pointer_names_what_the_document_carries_or_is_said,
    ),
    "a figure placed by hand is counted anyway": (
        _a_figure_placed_by_hand_is_counted_anyway,
        test_a_pointer_names_what_the_document_carries_or_is_said,
    ),
    "the Methods are read by the name G9 had for them": (
        _the_methods_are_read_by_their_old_name,
        test_a_section_g4_counts_present_is_a_section_the_gates_read,
    ),
    "the abstract a profile names is not counted as one": (
        _a_profile_s_abstract_title_is_not_counted,
        test_a_section_g4_counts_present_is_a_section_the_gates_read,
    ),
    "a paper's title over it all is its Methods": (
        _a_title_over_the_paper_is_its_methods,
        test_a_section_g4_counts_present_is_a_section_the_gates_read,
    ),
    "the abstract's own Methods are the paper's": (
        _the_abstract_s_methods_are_the_paper_s,
        test_a_section_g4_counts_present_is_a_section_the_gates_read,
    ),
    "a number's sign is no part of it": (
        _a_sign_is_no_part_of_its_number,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "a sign of comparison is no part of its number": (
        _a_sign_of_comparison_is_no_part_of_its_number,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "a sign of comparison is compared as it is typed": (
        _a_sign_of_comparison_is_compared_as_typed,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "an arrow's head is read as a sign": (
        _an_arrow_s_head_is_a_sign,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "an equals sign is read as a sign": (
        _an_equals_sign_is_a_sign,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "a sign of comparison is read only hard against its number": (
        _a_sign_of_comparison_is_read_only_against_its_number,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "the order of the facts is not looked at": (
        _the_order_is_not_looked_at,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "a name's words are one space apart": (
        _a_name_is_one_space_apart,
        test_an_author_is_found_in_a_blind_document_however_written_and_no_one_else,
    ),
    "an institution is found in its own case only": (
        _an_institution_is_in_its_own_case,
        test_an_author_is_found_in_a_blind_document_however_written_and_no_one_else,
    ),
    "an initial needs no stop": (
        _an_initial_needs_no_stop,
        test_an_author_is_found_in_a_blind_document_however_written_and_no_one_else,
    ),
    "an apostrophe is matched as it is typed": (
        _an_apostrophe_is_matched_as_typed,
        test_an_author_is_found_in_a_blind_document_however_written_and_no_one_else,
    ),
    "a name is not read with the family name first": (
        _a_name_is_not_read_family_name_first,
        test_an_author_is_found_in_a_blind_document_however_written_and_no_one_else,
    ),
    "every dash before a figure is its sign": (
        _every_dash_before_a_figure_is_its_sign,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "a dash that may be a sign says nothing when it goes": (
        _a_dash_that_may_be_a_sign_says_nothing,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "a dash that stood and may be a sign answers for a sure one that went": (
        _an_old_dash_answers_for_a_sign_that_went,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "a sign is new or gone by the counts alone, whatever its places say": (
        _a_sign_is_new_by_the_counts_alone,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "the places of a number's dashes are not compared": (
        _the_places_of_a_dash_are_not_compared,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "a listing in a comment is put back with the rest": (
        _a_listing_in_a_comment_is_put_back,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "what a comment holds is held to its place": (
        _a_comment_holds_facts,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_a_property_fails_when_the_rule_it_holds_is_broken(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A property that passes on a broken rule holds nothing, and the generators decide
    whether it does: a term never planted in a quotation would let the reading of
    quotations go. Each case breaks one rule in place and runs the property that is there
    for it, which has to fail on an assertion of its own."""
    break_it, held = BROKEN[case]
    break_it(monkeypatch)
    try:
        held.at_first_failure()
    except AssertionError:
        return
    except Exception as raised:
        # Several assertions failed: Hypothesis reports them together.
        failed = getattr(raised, "exceptions", ())
        assert failed and all(isinstance(one, AssertionError) for one in failed), raised
        return
    pytest.fail(f"with {case}, the property still holds", pytrace=False)


# ------------------------------------------------------------- how two answers are compared


def test_the_digest_of_an_answer_is_of_its_content() -> None:
    """Two answers are compared as JSON. A tuple and a list, which is what a pipe makes of
    a tuple, are one answer; so are two dictionaries whose keys were set in another order."""

    def digest(value: Any) -> str:
        return hashlib.sha256(repr(answer(lambda given: given, value)).encode()).hexdigest()

    assert digest({"b": (1, 2), "a": None}) == digest({"a": None, "b": [1, 2]})
    assert digest([1, 2]) != digest([2, 1])
    assert answer(lambda given: 1 / given, 0) == {"raised": "ZeroDivisionError: division by zero"}
    # What the command line raises when it refuses its arguments. It is no `Exception`, and
    # let through it ended the process that was answering, for a base whose command line
    # lacks an option a reading passes.
    assert answer(sys.exit, 2) == {"raised": "SystemExit: 2"}
