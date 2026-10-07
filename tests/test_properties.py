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
from pathlib import Path
from typing import Any

import pytest
from generated import (
    AGREED,
    FILLER,
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

from manuscript_guard.classify import CONVENTION, STRUCTURAL, TERM, UNCLASSIFIED, Classifier
from manuscript_guard.contracts.project import outside_maths
from manuscript_guard.gates import language as language_gate
from manuscript_guard.gates import spelling as spelling_gate
from manuscript_guard.gates import vocabulary as vocabulary_gate
from manuscript_guard.gates.language import _file, _hidden
from manuscript_guard.gates.spelling import MANY, _prose, _variants, judge_spelling
from manuscript_guard.gates.vocabulary import (
    Passage,
    capitals_together,
    judge_vocabulary,
    own_words,
)
from manuscript_guard.literature import sources as literature_sources
from manuscript_guard.literature.sources import contains, normalise, states_value
from manuscript_guard.text import tokens
from manuscript_guard.text.masking import NUL, mask
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


def _a_ligature_is_not_folded(patch: pytest.MonkeyPatch) -> None:
    patch.delitem(literature_sources._EQUIVALENT, "\N{LATIN SMALL LIGATURE FF}")


def _a_value_is_some_characters_of_a_number(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(
        sys.modules[__name__],
        "states_value",
        lambda quote, value: normalise(value).lower() in normalise(quote).lower(),
    )


def _a_nought_is_trimmed_off_a_number(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(tokens, "_TRAIL", tokens._TRAIL + "0")


def _a_variables_name_is_a_word(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(spelling_gate, "_in_an_identifier", lambda text, start, end: False)


#: A rule broken in one place, and the property that has to fail for it. Each is a way one
#: of these rules has been wrong, or a mutant a review found alive.
BROKEN = {
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
    "a ligature is not folded": (
        _a_ligature_is_not_folded,
        test_a_quotation_typed_from_its_source_is_found_and_one_it_does_not_hold_is_not,
    ),
    "a value is some characters of a longer number": (
        _a_value_is_some_characters_of_a_number,
        test_a_value_is_stated_whole_or_not_at_all,
    ),
    "a nought is trimmed off a number": (
        _a_nought_is_trimmed_off_a_number,
        test_a_number_is_seen_where_it_stands_and_judged_one_way,
    ),
    "a variable's name is read as a word": (
        _a_variables_name_is_a_word,
        test_a_word_in_the_other_english_is_found_where_it_stands_and_a_name_is_not,
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
