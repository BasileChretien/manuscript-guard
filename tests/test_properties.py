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
import os
import re
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
from readings import MAIN, PAPER, READINGS, Unavailable, answer

from manuscript_guard import reworded as reworded_module
from manuscript_guard.classify import CONVENTION, STRUCTURAL, TERM, UNCLASSIFIED, Classifier
from manuscript_guard.contracts.project import outside_maths
from manuscript_guard.gates import language as language_gate
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
    SURE,
    compare,
    facts,
)
from manuscript_guard.text import tokens
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


# --------------------------------------------------------------------------------- bindings


@holds(200, texts(), signs())
def test_a_binding_is_placed_where_it_stands(manuscript: str, nobodys: str) -> None:
    """A binding that does not resolve is reported by its line and column, and a malformed
    one by its line. `parse` looks them up among the starts of the file's lines, and they
    have to be what counting gives: the line feeds before the binding and one more, and the
    characters since the last of them and one more, in a file whose lines Windows ended as
    in any other. What else Python ends a line at, a form feed for one, is too seldom drawn
    before a binding to be held here: `tests/test_text.py` names each."""
    for text in (manuscript, nobodys):
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
#: How a number is set in its sentence: bare, in brackets, in emphasis, after a sign, in
#: a cell, after a comma, after a product. In all but the last the dash of a negative one
#: is its sign for sure; after the product it is perhaps one, and stands in both texts.
_SET = (
    "%s", "(%s)", "*%s*", "**%s**", "= %s", "\N{ALMOST EQUAL TO}%s", "|**%s**|", "(a,*%s*)",
    "x*%s",
)  # fmt: skip
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
                signed = fact.minus != NO or fact.text[0] == "+"
                assert not signed or here[0] in reworded_module._MINUS + "+", (text, fact)
                assert here[signed:].startswith(fact.text.lstrip("+")), (text, fact)
            last = fact.start
        assert not compare(text, text, MAIN).findings, text


@st.composite
def _rewordings(draw: st.DrawFn) -> tuple[str, str, str, list[str], int]:
    """A text, what an edit made of it, what the edit did besides reword it, the facts it
    did that to as a finding shows them, and the line of the after text it did it on.

    Every sentence is written twice, with other words between its facts each time and each
    fact in another of the ways it is written: a number bare, in brackets, in emphasis or
    as a bound of a range, joined each of the ways a range is. That is the rewording, and
    it is free. A comment stands in both, and holds other things in each: a listing in
    the first."""
    did = draw(
        st.sampled_from(
            ("nothing", "nothing", "lost", "new", "changed", "unsigned", "turned", "unsure",
             "beside", "swapped", "both")
        )
    )

    def fact() -> tuple[str, str]:
        kind = draw(st.sampled_from((BINDING, CITATION, NUMBER, NUMBER)))
        if kind == NUMBER:
            return kind, draw(st.sampled_from(_TYPED_NUMBERS))
        return kind, f"k{draw(st.integers(1, 4))}"

    sizes = draw(st.lists(st.integers(0, 3), min_size=1, max_size=6))
    before = [[fact() for _ in range(size)] for size in sizes]
    if did == "unsigned":
        before.append([(NUMBER, "-0.5")])
    turnable = [at for at, held in enumerate(before) if held != held[::-1]]
    if did == "turned" and not turnable:
        before.append([(NUMBER, "12"), (BINDING, "k1")])
        turnable = [len(before) - 1]
    holding = [at for at, held in enumerate(before) if held]
    if did in ("lost", "changed") and not holding:
        did = "nothing"

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
                and text[0] not in "-."
                and follows[1][0] not in "-."
                and draw(st.booleans())
            ):
                # Two numbers as the bounds of a range, in one of the ways it is joined.
                # They are read as the two numbers each time: the dash of a range is no sign.
                low = draw(st.sampled_from(_FIRST_BOUND)) % text
                parts.append(low + draw(st.sampled_from(_JOINED)) + follows[1])
                at += 2
            elif kind == NUMBER:
                retyped = text.replace("-", draw(st.sampled_from(_MINUS_TYPED)))
                parts.append(draw(st.sampled_from(_SET[:-1] if sure else _SET)) % retyped)
                at += 1
            else:
                parts.append(draw(st.sampled_from(_WRITTEN[kind])) % text)
                at += 1
            parts.append(filler())
        return " ".join(parts) + "."

    comment = draw(st.integers(0, len(before)))
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
        if did == "unsure":
            # A range whose first bound ends on a mark that may close, joined by a dash in
            # the text before and by "to" in the text after: the dash may have been a sign.
            low = draw(st.sampled_from(_MAY_CLOSE)) % 41
            join = "-" if sentences is before else " to "
            paragraphs.append(f"{filler().capitalize()} {low}{join}43 {filler()}.")
        texts_of.append("\n\n".join(paragraphs) + "\n")
    line = 1 + 2 * (at + (comment <= at))
    last = 1 + 2 * (len(after) + 1)
    if did == "unsure":
        shown, line = ["'43'", "may have lost a minus sign"], last
    if did == "beside":
        shown, line = ["'47'", "'-47'", "has lost its minus sign"], last
    if did == "swapped":
        shown, line = ["'53'", "at the 1st", "at the 2nd"], last
    if did == "both":
        shown, line = ["'61'", "may have gained a minus sign"], last
    return texts_of[0], texts_of[1], did, shown, line


@holds(200, _rewordings())
def test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands(
    drawn: tuple[str, str, str, list[str], int],
) -> None:
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
    }[did]
    assert codes == expected, (before, after, did, said)
    assert report.ok == (did in ("nothing", "unsure", "swapped", "both"))
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


def _a_stop_against_a_binding_ends_no_sentence(patch: pytest.MonkeyPatch) -> None:
    from bisect import bisect_left

    from manuscript_guard.gates import numbers as numbers_gate

    patch.setattr(numbers_gate, "_sentence", lambda text, ends, start: bisect_left(ends, start))


def _a_nought_is_trimmed_off_a_number(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(tokens, "_TRAIL", tokens._TRAIL + "0")


def _a_variables_name_is_a_word(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(spelling_gate, "_in_an_identifier", lambda text, start, end: False)


def _a_sign_is_no_part_of_its_number(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "_sign", lambda text, at: NO)


def _the_order_is_not_looked_at(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "_reordered", lambda before, after: [])


def _a_comment_holds_facts(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reworded_module, "blank_comments", lambda text: text)


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
    "a nought is trimmed off a number": (
        _a_nought_is_trimmed_off_a_number,
        test_a_number_is_seen_where_it_stands_and_judged_one_way,
    ),
    "a variable's name is read as a word": (
        _a_variables_name_is_a_word,
        test_a_word_in_the_other_english_is_found_where_it_stands_and_a_name_is_not,
    ),
    "a number's sign is no part of it": (
        _a_sign_is_no_part_of_its_number,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    "the order of the facts is not looked at": (
        _the_order_is_not_looked_at,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
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
