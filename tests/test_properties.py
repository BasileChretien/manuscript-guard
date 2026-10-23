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

import bisect
import dataclasses
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from bisect import bisect_left
from collections import Counter
from decimal import Decimal
from functools import cache, partial
from pathlib import Path
from typing import Any

import pytest
from generated import (
    AGREED,
    CLAIMED,
    CREDITING,
    DATA_IDENTIFIERS,
    DEPOSIT_DOI,
    EDIT_GAPS,
    EDIT_WORDS,
    FILLER,
    FIXED_LINKS,
    FOLDED,
    HELD,
    INPUTS,
    LOOKALIKES,
    LOWERED,
    NOTATED,
    PLACEHOLDERS,
    PROOF_ABBREVIATED,
    PROOF_CORRECTIONS,
    PROOF_EDIT,
    PROOF_TYPOGRAPHY,
    RESIDUE,
    RESIDUE_LOOKALIKES,
    SOURCE_GAPS,
    SOURCE_WORDS,
    STRETCHES,
    TEMPORARY_LINKS,
    TERMS,
    TYPOGRAPHY,
    UNCLAIMED,
    WRITTEN_WORDS,
    alt_texts,
    bindings,
    claim_edits,
    collection_plans,
    commented,
    count_cells,
    credited_plans,
    deposit_statements,
    dictionary_pairs,
    generated,
    holds,
    laid_out,
    latex_bound,
    latex_cited,
    latex_claims,
    latex_declared,
    latex_delimited_uses,
    latex_displays,
    latex_hooked_uses,
    latex_methods,
    latex_model_names,
    latex_planted,
    latex_pointers,
    latex_printed,
    latex_quotations,
    latex_texts,
    latex_trees,
    latex_words,
    latex_writing,
    lines,
    markdown_for_latex,
    mean_tables,
    numbered_displays,
    painted_pdfs,
    painted_svgs,
    passage_files,
    pdf_figures,
    plan_pairs,
    planned_plans,
    printings,
    proofs,
    quotations,
    quoted_references,
    revisions,
    share_tables,
    signs,
    sources,
    suggestion_paragraphs,
    supplements,
    texts,
    typed,
    vector_figures,
    vocabularies,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.database import InMemoryExampleDatabase
from readings import MAIN, PAPER, PEOPLE, READINGS, Unavailable, answer, plain_of

from manuscript_guard import claims as claims_module
from manuscript_guard import reworded as reworded_module
from manuscript_guard.build import blinding, latex_values
from manuscript_guard.build.blinding import names_in, sought
from manuscript_guard.classify import CONVENTION, STRUCTURAL, TERM, UNCLASSIFIED, Classifier
from manuscript_guard.contracts.project import outside_maths
from manuscript_guard.contracts.values import RESULTS, Value, number_in
from manuscript_guard.deposit import counts as deposit_counts
from manuscript_guard.gates import bound_units as bound_units_gate
from manuscript_guard.gates import data_statement
from manuscript_guard.gates import journal_quotes as journal_quotes_gate
from manuscript_guard.gates import language as language_gate
from manuscript_guard.gates import methods as methods_gate
from manuscript_guard.gates import methods_review as methods_review_gate
from manuscript_guard.gates import models as models_gate
from manuscript_guard.gates import numbers as numbers_gate
from manuscript_guard.gates import pointers_latex as pointers_latex_gate
from manuscript_guard.gates import quotations as quotations_gate
from manuscript_guard.gates import recycling as recycling_gate
from manuscript_guard.gates import related as related_gate
from manuscript_guard.gates import related_methods as related_methods_gate
from manuscript_guard.gates import reported as reported_gate
from manuscript_guard.gates import spelling as spelling_gate
from manuscript_guard.gates import vocabulary as vocabulary_gate
from manuscript_guard.gates import writing as writing_gate
from manuscript_guard.gates.language import _file, _hidden
from manuscript_guard.gates.notation import VALUE, _counted
from manuscript_guard.gates.spelling import MANY, _prose, _variants, judge_spelling
from manuscript_guard.gates.vocabulary import (
    Passage,
    capitals_together,
    judge_vocabulary,
    own_words,
)
from manuscript_guard.literature import passages as passages_module
from manuscript_guard.literature import sources as literature_sources
from manuscript_guard.literature.sources import contains, normalise, states_value
from manuscript_guard.markedup import align as markedup_align
from manuscript_guard.markedup import atoms as markedup_atoms
from manuscript_guard.markedup import package as markedup_package
from manuscript_guard.markedup import writer as markedup_writer
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
from manuscript_guard.text.latex import cite as latex_cite
from manuscript_guard.text.latex import mask as latex_mask
from manuscript_guard.text.latex import printed as latex_print
from manuscript_guard.text.latex import structure as latex_structure
from manuscript_guard.text.latex import views as latex_views
from manuscript_guard.text.latex import words as latex_words_view
from manuscript_guard.text.masking import NUL, mask
from manuscript_guard.text.placeholders import parse as parse_bindings
from manuscript_guard.text.sections import (
    chains_at,
    footnote_index,
    heading_index,
    split_sections,
)
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

#: The quotation marks the LaTeX reader writes for ``` `` ``` and `''`.
LEFT_QUOTE, RIGHT_QUOTE = "\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}"


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


# ------------------------------------------------------------------------- the LaTeX reader


@holds(200, latex_texts())
def test_the_latex_mask_keeps_every_character_in_its_place(text: str) -> None:
    """The LaTeX reader keeps the Markdown mask's contract: the same length, every line break
    where it was, and each character itself, a NUL, or what TeX prints for it there (a space,
    a quotation mark, or at an escape's backslash the character it stands for). Past a refusal
    the text is as it was typed, so that nothing the reader did not understand is hidden."""
    reading = latex_mask.read(text)
    masked = reading.masked
    assert len(masked) == len(text), text
    for at, (was, now) in enumerate(zip(text, masked, strict=True)):
        assert (now in "\r\n") == (was in "\r\n"), (at, text)
        # A space only where TeX prints one: a tie, a cell's `&`, or a command's backslash
        # (round 1 of #380: any character could become one, and `4100` read as `41 00`).
        allowed = {was, NUL} | ({" "} if was in " \t~&\\" else set())
        if was == "\\" and at + 1 < len(text):
            allowed.add(text[at + 1])
        allowed |= {"`": {LEFT_QUOTE}, "'": {RIGHT_QUOTE}}.get(was, set())
        assert now in allowed, (at, was, now, text)
    for refusal in reading.refusals:
        assert masked[refusal.offset :] == text[refusal.offset :], (refusal, text)


@holds(100, latex_planted())
def test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else(
    drawn: tuple[str, list[tuple[int, str, bool]]],
) -> None:
    """A number planted in every place LaTeX puts one, among whole pieces, is found where it
    prints and blanked where it does not: in prose, a footnote, a caption, a citation's note,
    maths, a `\\verb` and the title it is read; in a comment, a label, a key, a binding, a URL,
    a listing, an `\\iffalse`, a length, the preamble and after the document it is not."""
    text, planted = drawn
    reading = latex_mask.read(text)
    assert reading.refusals == (), (reading.refusals, text)
    for at, number, read in planted:
        seen = reading.masked[at : at + len(number)]
        if read:
            assert seen == number, (number, seen, text)
        else:
            assert set(seen) == {NUL}, (number, seen, text)


def _an_escaped_percent_opens_a_comment(patch: pytest.MonkeyPatch) -> None:
    symbol = latex_mask._Reader._symbol

    def broken(self, character: str, at: int) -> None:
        if character != "%":
            symbol(self, character, at)
            return
        end = latex_mask._comment_end(self.text, at)
        self._blank(at, end)
        self.pos = end

    patch.setattr(latex_mask._Reader, "_symbol", broken)


def _a_latex_comment_runs_past_its_line(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_comment_end", lambda text, at: len(text))


def _latex_maths_is_blanked_whole(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_maths_keeps", lambda character: False)


def _a_citations_notes_are_blanked(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_note_role", lambda kind: latex_mask.BLANK)


def _a_latex_group_closes_at_the_first_brace(patch: pytest.MonkeyPatch) -> None:
    step = latex_mask._Reader._step

    def broken(self) -> None:
        nested = self.stack and self.stack[-1].kind in ("arg", "opt")
        if self.text[self.pos] == "{" and nested:
            self._keep_or_blank(self.pos, self.pos + 1)
            self.pos += 1
            return
        step(self)

    patch.setattr(latex_mask._Reader, "_step", broken)


def _verb_takes_only_a_bar(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(
        latex_mask, "_verb_delimiter", lambda text, at: "|" if text[at : at + 1] == "|" else ""
    )


def _the_preamble_ends_at_the_first_begin(patch: pytest.MonkeyPatch) -> None:
    environment = latex_mask._Reader._environment

    def broken(self, which: str, at: int, end: int) -> None:
        self.body = True
        environment(self, which, at, end)

    patch.setattr(latex_mask._Reader, "_environment", broken)


def _a_delimited_definition_is_refused(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask._Reader, "_parameter_text", lambda self, at, word: (-1, True))


def _a_parameter_in_a_body_is_one_hash(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_PARAMETER", re.compile(r"#\d"))


def _a_command_let_is_always_defined_again(patch: pytest.MonkeyPatch) -> None:
    def broken(self, defined: str, start: int, name_end: int) -> None:
        self._defines(defined, start)
        self.defining = ""
        self._blank(start, name_end)
        self.pos = name_end

    patch.setattr(latex_mask._Reader, "_let", broken)


def _a_classs_front_matter_is_read(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "FRONT_MATTER", frozenset())


def _an_abstract_in_front_matter_is_passed_over_with_it(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask._Reader, "_entered", lambda self, name, role:
                  latex_mask.BLANK if name in latex_mask.FRONT_MATTER else role)  # fmt: skip


def _front_matter_commands_are_unknown(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "COMMANDS", {name: spec for name, spec in latex_mask.COMMANDS.items()
                                           if name not in latex_mask.FRONT_MATTER_COMMANDS})


def _front_matter_commands_are_defined_again(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_REDEFINABLE", frozenset({"abstract"}))


def _highlights_in_front_matter_are_passed_over(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "READ_IN_FRONT_MATTER", frozenset({"abstract"}))


def _an_author_s_front_matter_command_is_passed_over(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "FRONT_MATTER_COMMANDS", frozenset())


@holds(100, latex_delimited_uses())
def test_a_command_with_delimited_parameters_is_refused_where_it_prints_and_nowhere_else(
    drawn: tuple[str, int],
) -> None:
    """A command defined with `\\def` and delimited parameters, used in the preamble and at
    every place of the body among whole pieces, is refused at the first use whose output
    LaTeX prints, in prose, maths, a caption, a note, an argument printed and a heading, and
    at none before it: a blanked argument, a comment, an `\\iffalse` block, code and another
    definition's body print nothing (2026-10-23)."""
    text, first = drawn
    refusals = latex_mask.read(text).refusals
    assert [(r.code, r.offset) for r in refusals] == [("tex-refused", first)], (refusals, text)
    assert "delimited parameters" in refusals[0].message


@holds(60, latex_hooked_uses())
def test_a_command_with_delimited_parameters_is_refused_in_a_hook_s_body(
    drawn: tuple[str, int],
) -> None:
    """A use of a command defined with delimited parameters in the body of a hook LaTeX runs
    where it stands, `\\AtBeginDocument` and its kin, prints though it stands in the preamble,
    and is refused at the first (round 1 of real templates)."""
    text, first = drawn
    refusals = latex_mask.read(text).refusals
    assert [(r.code, r.offset) for r in refusals] == [("tex-refused", first)], (refusals, text)


def _a_delimited_use_is_refused_wherever_it_stands(patch: pytest.MonkeyPatch) -> None:
    word = latex_mask._Reader._word

    def broken(self, name: str, at: int, end: int) -> None:
        if name in self.delimited:
            self._refuse("tex-refused", at, f"\\{name} has delimited parameters")
            return
        word(self, name, at, end)

    patch.setattr(latex_mask._Reader, "_word", broken)


def _a_delimited_use_is_read_as_an_unknown_command(patch: pytest.MonkeyPatch) -> None:
    definition = latex_mask._Reader._definition

    def broken(self, name: str, at: int, end: int) -> None:
        definition(self, name, at, end)
        self.delimited.clear()

    patch.setattr(latex_mask._Reader, "_definition", broken)


def _a_delimited_use_in_maths_is_let_be(patch: pytest.MonkeyPatch) -> None:
    word = latex_mask._Reader._word

    def broken(self, name: str, at: int, end: int) -> None:
        if name in self.delimited and self._role() == latex_mask.MATHS_READ:
            return
        word(self, name, at, end)

    patch.setattr(latex_mask._Reader, "_word", broken)


def _a_hook_s_body_is_a_definition_s(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask._Reader, "_prints",
                  lambda self: self._reads() and not self.definitions)  # fmt: skip


def _the_spaces_after_a_control_word_delimit(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_SKIPPED", re.compile(r""))


@holds(60, latex_trees())
def test_each_latex_file_starts_under_the_headings_in_force_where_it_is_input(
    drawn: tuple[dict[str, str], dict[str, list[str]], dict[str, list[str]]],
) -> None:
    """A file input under `\\section{Methods}` is read under Methods, and one input after a
    file that opened a section is read under that section, as LaTeX prints them: worked out
    apart from the reader, over manuscripts of a few files that input one another. So is the
    text after each heading (`Source.chain_at`), a heading where an `\\input` ends and a
    chapter under its part among them."""
    files, expected, marks = drawn
    document = latex_structure.read_tree(files)
    found = {source.path: [h.title for h in source.under] for source in document.sources}
    for path, titles in expected.items():
        assert found.get(path) == titles, (path, found, files)
    assert document.refusals == (), document.refusals
    for mark, titles in marks.items():
        (source,) = [s for s in document.sources if f"{mark} " in s.text]
        chain = source.chain_at(source.text.index(f"{mark} "))
        assert [h.title for h in chain] == titles, (mark, source.path, files)


def _an_input_file_starts_under_no_heading(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_structure, "_starts_under", lambda chain: ())


def _a_heading_of_an_input_file_stays_in_it(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_structure, "_resumed", lambda before, after: before)


def _a_heading_where_an_input_ends_comes_before_it(patch: pytest.MonkeyPatch) -> None:
    def broken(self, offset: int):
        events = sorted(
            [(heading.start, heading, ()) for heading in self.reading.headings]
            + [(end, None, after) for end, after in self.resumes],
            key=lambda event: event[0],
        )
        chain = self.under
        for start, heading, after in events:
            if start >= offset:
                break
            chain = latex_structure._folded(chain, heading) if heading is not None else after
        return chain

    patch.setattr(latex_structure.Source, "chain_at", broken)


def _a_chapter_closes_its_part(patch: pytest.MonkeyPatch) -> None:
    patch.setitem(latex_mask.LEVELS, "part", 0)


def _a_subimport_names_its_folder_from_the_entry_files(patch: pytest.MonkeyPatch) -> None:
    target = latex_structure._target

    def broken(entry, put, imported, files):
        if put.via == "subimport":
            put = dataclasses.replace(put, via="import")
        return target(entry, put, imported, files)

    patch.setattr(latex_structure, "_target", broken)


def _an_imported_file_keeps_the_folder_its_importer_was_imported_from(
    patch: pytest.MonkeyPatch,
) -> None:
    target = latex_structure._target

    def broken(entry, put, imported, files):
        found, why, _folder = target(entry, put, imported, files)
        return found, why, imported

    patch.setattr(latex_structure, "_target", broken)


def _an_input_is_not_looked_for_in_the_folder_imported_from(patch: pytest.MonkeyPatch) -> None:
    target = latex_structure._target

    def broken(entry, put, imported, files):
        return target(entry, put, "" if put.via == "input" else imported, files)

    patch.setattr(latex_structure, "_target", broken)


def _an_abstract_in_the_preamble_is_blanked(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "PRINTED_IN_PREAMBLE", latex_mask.PRINTED_IN_PREAMBLE - {"abstract"})


@holds(100, latex_bound())
def test_a_latex_binding_is_read_where_it_prints_as_one_and_nowhere_else(
    drawn: tuple[str, list[tuple[str, str]]],
) -> None:
    """A `\\mg{namespace.key}` planted in every place it stands, among whole pieces, is a
    binding where LaTeX prints it, in prose, a note, a caption, a cell, maths, a definition's
    body and the title, and nothing in a comment, an `\\iffalse` block or the `comment`
    environment. A near spelling, a Markdown binding and a `\\mg` that names no key are each
    something meant for one, and siunitx's milligram is nothing (step 4). The Markdown view
    holds each binding where its command stands, the line breaks where they stand, a binding
    in a typed table is in it and no other is, and a listing names its language (round 1 of
    #400)."""
    text, planted = drawn
    reading = latex_mask.read(text)
    assert reading.refusals == (), (reading.refusals, text)
    source = latex_structure.Source("main.tex", text, reading)
    good, malformed = latex_views.bindings(source)
    expected = {kind: sorted(key for key, was in planted if was == kind)
                for kind in ("bound", "table", "malformed", "listing")}  # fmt: skip
    found = {placeholder.key.rsplit(".", 1)[-1]: placeholder for placeholder in good}
    assert sorted(found) == sorted(expected["bound"] + expected["table"]), text
    keys = sorted("".join(re.findall(r"k\d+", raw)) for raw, _at, _line in malformed)
    assert keys == expected["malformed"], (malformed, text)
    view = latex_views.markdown_view(source, good)
    assert [i for i, c in enumerate(view) if c == "\n"] == [
        i for i, c in enumerate(text) if c == "\n"
    ], text
    assert [(p.ref, p.start, p.end) for p in parse_bindings(view)[0]] == [
        (p.ref, p.start, p.end) for p in good
    ], (view, text)
    tables = latex_views.Tables(reading.tables)
    assert sorted(key for key, p in found.items() if p.start in tables) == expected["table"]
    ((key,),) = [expected["listing"]]
    (listing,) = [found for found in reading.listings if key in text[found.start : found.end]]
    assert listing.language == "r", text


def _a_latex_binding_is_read_wherever_it_is_typed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_views, "_uses", lambda source: latex_views._by_shape(source.text, 0))


def _a_near_spelling_of_the_binding_is_taken_for_nothing(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_near_binding", lambda name: False)


def _a_markdown_binding_in_latex_is_taken_for_nothing(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_MARKDOWN_BINDING", re.compile("(?!)"))


def _siunitx_s_milligram_is_taken_for_a_binding(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "SIUNITX", frozenset())


def _a_bindings_view_is_not_padded_to_its_command(patch: pytest.MonkeyPatch) -> None:
    view = latex_views.markdown_view

    def broken(source, placeholders, blank=" "):
        out = list(view(source, [], blank))
        for p in placeholders:
            written = ("{{" + p.ref + "}}").ljust(p.end - p.start)
            out[p.start : p.end] = written[: p.end - p.start]
        return "".join(out)

    patch.setattr(latex_views, "markdown_view", broken)


def _a_typed_table_is_not_recorded(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "TYPED_TABLES", frozenset())


def _a_listings_language_is_not_read(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_LANGUAGE", re.compile("(?!)"))


def _a_line_break_before_a_bindings_brace_makes_it_malformed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_BINDING",
                  re.compile(r"[ \t]*(?:\[[^\]\n]*\])?[ \t]*\{(?P<inner>[^{}\n]*)\}"))  # fmt: skip


@holds(100, latex_cited())
def test_a_latex_citation_is_read_where_it_prints_and_nowhere_else(
    drawn: tuple[str, list[tuple[str, str]]],
) -> None:
    """A key planted in every citation command LaTeX prints, in prose and a note, alone or
    with others and in a multi-citation, is cited there, narrative where the command prints
    the authors' names; a key in a comment, an `\\iffalse` block or a definition's body is
    cited nowhere (step 5)."""
    text, planted = drawn
    reading = latex_mask.read(text)
    assert reading.refusals == (), (reading.refusals, text)
    source = latex_structure.Source("main.tex", text, reading)
    uses = latex_cite.citations(source, Path("main.tex"))
    assert sorted((use.citekey, use.narrative) for use in uses) == sorted(
        (key, kind == "narrative") for key, kind in planted if kind != "none"
    ), text
    for use in uses:
        assert text[use.start : use.start + len(use.citekey)] == use.citekey, (use, text)


def _a_comment_in_a_key_list_is_a_key(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_key_list", lambda keys: keys)


def _a_long_global_note_hides_its_citations(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_NOTE_REACH", 32)


def _a_preamble_cite_setting_is_refused(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask._Reader, "_unknown_citation",
                  lambda self, name: "cite" in name.lower() and not self.definitions)  # fmt: skip


def _a_citations_keys_are_not_split(patch: pytest.MonkeyPatch) -> None:
    def broken(self, at: int) -> None:
        end = self._group_end(at)
        narrative = latex_mask.CITATIONS[self.command]
        key = self.text[at + 1 : end - 1].strip()
        self.cited.append(latex_mask.Cited(key, at + 1, narrative, self.citation_at, end))

    patch.setattr(latex_mask._Reader, "_cite", broken)


def _a_key_in_a_definitions_body_is_cited(patch: pytest.MonkeyPatch) -> None:
    opened = latex_mask._Reader._open

    def broken(self, kind, spec, at, closer, **options):
        citing = kind == "arg" and spec == "b" and self.command in latex_mask.CITATIONS
        if citing and self.definitions:
            self._cite(at)
        return opened(self, kind, spec, at, closer, **options)

    patch.setattr(latex_mask._Reader, "_open", broken)


def _no_latex_citation_is_narrative(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "CITATIONS", dict.fromkeys(latex_mask.CITATIONS, False))


def _a_multi_citation_reads_its_first_group_only(patch: pytest.MonkeyPatch) -> None:
    for name in ("parencites", "Parencites"):
        patch.setitem(latex_mask.COMMANDS, name, ("(b)", "(b)", "[p]", "[p]", "{b}"))


@holds(100, latex_printed())
def test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it(
    drawn: tuple[str, list[tuple[str, str]]],
) -> None:
    """A word planted in every place a LaTeX document holds one is in the view G4 reads where
    LaTeX prints it, once: a heading's title as its `#` line, prose as prose, a binding as
    `{{...}}`, a citation as `[@...]`; a float's caption, maths, a comment and the preamble's
    title are not in it; and an abstract's text is under Abstract and the text after it is
    not (step 6)."""
    text, planted = drawn
    reading = latex_mask.read(text)
    assert reading.refusals == (), (reading.refusals, text)
    view = latex_print.printed_view([latex_structure.Source("main.tex", text, reading)])
    headings = [line for line in view.splitlines() if line.startswith("#")]
    for key, kind in planted:
        if kind.startswith("heading"):
            assert f"{'#' * int(kind[-1])} {key}" in headings and view.count(key) == 1, view
        elif kind in ("prose", "abstract", "after"):
            assert view.count(key) == 1, (key, view)
        elif kind == "hidden":
            assert key not in view, (key, view)
        else:
            written = {"bound": "{{results.%s}}", "table": "{{table.%s}}", "cited": "[@%s]",
                       "tight": "({{results.%s}})."}  # fmt: skip
            assert written[kind] % key in view, (key, view)
    sections = {section.title: section.body for section in split_sections(view)}
    ((abstract,), (after,)) = ([k for k, kind in planted if kind == which]
                               for which in ("abstract", "after"))  # fmt: skip
    assert abstract in sections["Abstract"] and after not in sections["Abstract"], view
    # A word in prose is in no code span: LaTeX's single quote opens none (round 1 of step 6).
    spans = "".join(re.findall(r"`[^`\n]+`", view))
    assert not [k for k, kind in planted if kind == "prose" and k in spans], view


@holds(60, latex_trees())
def test_latex_s_printed_view_writes_each_file_where_it_is_input(
    drawn: tuple[dict[str, str], dict[str, list[str]], dict[str, list[str]]],
) -> None:
    """A word written after each heading of a manuscript of several files is in the view G4
    reads in the order LaTeX prints it, under the heading LaTeX prints it under: a file input
    is printed where its `\\input` stands, and the text of the file that input it goes on
    after it (step 6)."""
    files, _under, marks = drawn
    document = latex_structure.read_tree(files)
    assert document.refusals == (), document.refusals
    view = latex_print.printed_view([s for s in document.sources if not s.loose])
    order = [int(found) for found in re.findall(r"\bmark(\d+)\b", view)]
    assert order == list(range(1, len(marks) + 1)), view
    for section in split_sections(view):
        for found in re.findall(r"\bmark\d+\b", section.body):
            assert marks[found][-1] == section.title, (found, section.title, view)


def _an_input_file_is_printed_after_its_parent(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_cuts", lambda source: [])


@holds(60, latex_trees())
def test_latex_s_printed_view_places_each_word_at_its_file_and_line(
    drawn: tuple[dict[str, str], dict[str, list[str]], dict[str, list[str]]],
) -> None:
    """A word written after each heading of a manuscript of several files is placed by the
    printed view at the file and the line it is written on, so that a gate reading the view
    as Markdown names the `.tex` line (step 8)."""
    files, _under, marks = drawn
    sources = [source for source in latex_structure.read_tree(files).sources if not source.loose]
    view = latex_print.printed(sources)
    for mark in marks:
        name, typed = next((name, typed) for name, typed in files.items()
                           if re.search(rf"\b{mark}\b", typed))  # fmt: skip
        written = re.search(rf"\b{mark}\b", typed).start()
        source, line = view.place(re.search(rf"\b{mark}\b", view.text).start())
        assert (source.path, line) == (name, typed.count("\n", 0, written) + 1), (mark, files)


def _prose_breaks_its_lines_as_the_view_does(patch: pytest.MonkeyPatch) -> None:
    printed_one = latex_print._printed

    def broken(source, shallowest, child=lambda: [], *args, **kwargs):
        return [(text, of, at, False) for text, of, at, _linear in
                printed_one(source, shallowest, child, *args, **kwargs)]  # fmt: skip

    patch.setattr(latex_print, "_printed", broken)


def _each_stretch_is_placed_at_its_files_start(patch: pytest.MonkeyPatch) -> None:
    printed_one = latex_print._printed

    def broken(source, shallowest, child=lambda: [], *args, **kwargs):
        return [(text, of, 0, linear) for text, of, _at, linear in
                printed_one(source, shallowest, child, *args, **kwargs)]  # fmt: skip

    patch.setattr(latex_print, "_printed", broken)


def _a_typed_reference_list_is_printed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "REFERENCES", "nothing")


def _a_single_quote_opens_a_code_span(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_QUOTE", "`")


def _an_abstract_in_the_preamble_is_not_printed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_printed_ranges",
                  lambda reading: [(max(reading.body_start, 0), len(reading.masked))])  # fmt: skip


@holds(100, latex_words())
def test_latex_s_words_hold_each_word_where_latex_prints_it(
    drawn: tuple[str, list[tuple[str, str]]],
) -> None:
    """A word planted in every place a LaTeX document holds one is in the view G14 reads, at
    its own offset, where LaTeX prints it as prose; it is not in it in maths, code, a figure's
    caption, a comment, a label or the preamble's title; a word an accent command or `\\-`
    splits is not in it and is given as unread, and no other word is; and a count written as
    a subscript after a letter is written as Markdown writes it (step 7)."""
    text, planted = drawn
    reading = latex_mask.read(text)
    assert reading.refusals == (), (reading.refusals, text)
    seen = latex_words_view.words(latex_structure.Source("main.tex", text, reading))
    assert len(seen.text) == len(text), text
    unread = [text[start:end] for start, end in seen.unread]
    for key, kind in planted:
        if kind == "read":
            assert seen.text.count(key) == 1 and seen.text.find(key) == text.find(key), key
        elif kind == "subscript":
            assert f"{key}X~2~" in seen.text, (key, seen.text)
        else:
            assert key not in seen.text, (key, kind, seen.text)
        if kind == "split":
            assert [word for word in unread if key in word], (key, unread)
    assert len(unread) == sum(kind == "split" for _key, kind in planted), unread


def _maths_is_words(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_words_view, "_maths", lambda reading: [])


def _code_is_words(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_words_view, "_code", lambda reading: [])


def _a_figures_caption_is_words(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "FIGURES", frozenset())


def _the_preamble_is_words(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_words_view, "_preamble", lambda reading: [])


def _an_accented_word_is_read_in_pieces(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_words_view, "_split_words", lambda text: [])


def _an_accented_word_is_cut_at_its_accent(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_words_view, "_in_word", lambda char: False)


def _a_subscripts_count_is_maths(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_words_view, "_subscripts", lambda out, text: None)


@holds(60, latex_trees())
def test_g14_reads_a_latex_document_in_the_order_it_prints(
    drawn: tuple[dict[str, str], dict[str, list[str]], dict[str, list[str]]],
) -> None:
    """The stretches G14 reads a LaTeX manuscript of several files in hold a word written
    after each heading in the order LaTeX prints it: a file input is read where its `\\input`
    stands, and the text of the file that input it after it, so that a definition and a use
    are read in the order a reader meets them (step 7)."""
    files, _under, marks = drawn
    document = latex_structure.read_tree(files)
    assert document.refusals == (), document.refusals
    stretches = language_gate._stretches(document.sources)
    read = "".join(source.text[start:end] for source, start, end in stretches)
    order = [int(found) for found in re.findall(r"\bmark(\d+)\b", read)]
    assert order == list(range(1, len(marks) + 1)), read


def _a_file_input_is_read_after_its_parent(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(language_gate, "_input_ends", lambda source: [])


# ------------------------------------------------- G14: what is a definition, what an abbreviation

# Imported here, not at the top, to keep clear of the import block other branches edit.
from generated import bracketed, capitalised  # noqa: E402


@holds(60, bracketed())
def test_a_bracket_defines_where_its_long_form_stands_before_it_and_a_statistic_does_not(
    drawn: tuple[str, list[tuple[int, str, bool]]],
) -> None:
    """G14 reads a definition in both orders, in square brackets, with a separator or a
    citation beside it, nested in a bracket that gives a statistic, and with a long form that
    closes a bracket or holds a whole one. A short form followed by a colon, an equals sign or
    a number is a statistic, and one whose letters are found only inside a bracket its long
    form would open defines nothing, though the words before each spell it."""
    text, planted = drawn
    read = _file(0, Path("main.md"), text, [], False)
    defined = {at: short for at, short, _long in read.definitions}
    for at, short, defines in planted:
        if defines:
            assert defined.get(at) == short, (short, text)
        else:
            assert at not in defined, (short, text)


@holds(60, capitalised())
def test_a_time_of_day_and_a_heading_in_capitals_are_no_abbreviations(
    drawn: tuple[str, list[str]],
) -> None:
    """A time of day, `8:30AM`, `10:00 PM`, and a heading or a table's label typed in capitals
    are not reported as undefined abbreviations, and an abbreviation the manuscript defines is
    used in such a cell; one beside a time of day, in a cell with small letters or in a
    sentence still is reported."""
    text, undefined = drawn
    nothing = language_gate._Known(frozenset(), frozenset())
    report = language_gate._judge([_file(0, Path("main.md"), text, [], False)], nothing, Path("."))
    found = sorted((f.code, f.message.split()[0]) for f in report.findings)
    assert found == [("abbreviation-undefined", short) for short in undefined], text


def _a_statistic_in_brackets_is_a_definition(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(language_gate, "_STATISTIC", re.compile("(?!)"))


def _a_long_form_takes_a_letter_from_inside_a_bracket(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(language_gate, "_inside_a_bracket", lambda before, matched: False)


def _a_long_form_crosses_no_bracket(patch: pytest.MonkeyPatch) -> None:
    def crosses(before: str, matched: list[int]) -> bool:
        return any(char in "()[]" for char in before[matched[-1] : matched[0]])

    patch.setattr(language_gate, "_inside_a_bracket", crosses)


def _a_time_of_day_is_words(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(language_gate, "_CLOCK", re.compile("(?!)"))


def _a_heading_in_capitals_is_words(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(language_gate, "_in_capitals", lambda prose: [])


@holds(60, latex_writing())
def test_g6_judges_a_latex_document_where_it_prints_and_by_its_citations(
    drawn: tuple[str, list[tuple[str, str]]],
) -> None:
    """A claim with no citation, a phrase and a placeholder planted in a LaTeX document are each
    found on their line, and nothing else is: a claim beside a citation command is supported, a
    claim or a phrase in a comment is no text of the paper, and a placeholder in a comment is
    found as typed, as one in a Markdown comment is, and one in a typed reference list as one in
    a cited entry's field is; nothing past the document's end is read, nor a package's name or
    a definition's body in the preamble (step 7)."""
    text, planted = drawn
    sources = latex_structure.read_tree({"main.tex": text}).sources
    read, words, cited = writing_gate._read_latex(Path("m"), [sources])
    rules = writing_gate.load_rules()
    report, totals = writing_gate._judged(read, words, rules, cited=cited)
    for where in writing_gate._typed_lists_of(Path("m"), [sources]):
        report = report.merge(writing_gate._artefacts_elsewhere(rules, where, totals))
    lines = {key: text.count("\n", 0, text.index(key)) + 1 for key, _kind in planted}
    for code, kind in (("vague-attribution", "vague"), ("ai-phrasing", "phrase"),
                       ("model-artefact", "artefact")):  # fmt: skip
        found = sorted(finding.line for finding in report.findings if finding.code == code)
        assert found == sorted(lines[key] for key, was in planted if was == kind), (code, text)


@holds(60, latex_methods())
def test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one(
    drawn: tuple[str, list[tuple[str, str, str]]],
) -> None:
    """Each paragraph of a LaTeX document's Methods that points at no step is open on the line
    of its first word, after a heading glued to it too; each claim points at its step and says
    its words, a binding among them as Markdown writes it; a heading, a typed table, a
    listing, a comment and the Results after the Methods are no open paragraph (step 8)."""
    text, planted = drawn
    source = latex_structure.Source("main.tex", text, latex_mask.read(text))
    view = latex_views.markdown_view(source, latex_views.bindings(source)[0])
    read = methods_gate._latex_read(Path("main.tex"), source, view)
    claims, open_ = methods_gate._anchored_in(read)
    lines = {key: text.count("\n", 0, text.index(key)) + 1 for key, _kind, _said in planted}
    opened = [key for key, kind, _said in planted if kind == "open"]
    assert sorted(p.line for p in open_) == sorted(lines[key] for key in opened), (text, open_)
    for key in opened:
        assert any(key in p.text for p in open_), (key, text, open_)
    for key in (key for key, kind, _said in planted if kind == "none"):
        assert not any(key in p.text for p in open_), (key, text, open_)
    said = [((key,), words) for key, kind, words in planted if kind == "claim"]
    assert [(c.steps, c.text) for c in claims] == said, text


@holds(100, latex_model_names())
def test_a_model_named_in_latex_methods_is_found_where_latex_prints_it(
    planted: tuple[str, list[tuple[int, str]]],
) -> None:
    """A model a LaTeX document's Methods name is found where it stands, with the kind it
    names, as in Markdown: in a command's braces or a footnote too, and not in a comment,
    code, maths, a figure's float, a heading's title, what `\\iffalse` leaves out or the
    Results, nor after a word that makes it another model's (step 8)."""
    text, expected = planted
    source = latex_structure.Source("main.tex", text, latex_mask.read(text))
    found = [(start, kind) for start, _end, kind in models_gate.named_in_latex(source)]
    assert found == expected, text


def _g15_reads_a_latex_heading_s_title(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text.latex.words import words

    patch.setattr(models_gate, "_latex_words",
                  lambda source: words(source).text.replace(latex_mask.NUL, " "))  # fmt: skip


def _g15_reads_all_of_a_latex_file_as_its_methods(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(models_gate, "named_in_latex",
                  lambda source: models_gate._named(models_gate._latex_words(source),
                                                    lambda start: True))  # fmt: skip


def _g15_reads_a_latex_file_in_its_markdown_view(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(models_gate, "_latex_words",
                  lambda source: source.reading.masked.replace(latex_mask.NUL, " "))  # fmt: skip


def _g15_reads_a_latex_file_s_words_with_its_nul(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text.latex.words import words

    patch.setattr(models_gate, "_latex_words", lambda source: words(source).text)


@holds(80, latex_pointers())
def test_a_latex_cross_reference_is_recorded_where_it_prints_and_nowhere_else(
    drawn: tuple[str, list[tuple[str, bool]]],
) -> None:
    """A `\\ref`, `\\autoref`, `\\eqref` or `\\cref` in prose is recorded, from its command
    to its brace; one in a comment, a listing or what `\\iffalse` leaves out is not, nor a
    label or a citation (round 1 of G13 in step 8)."""
    text, planted = drawn
    spans = latex_mask.read(text).pointers
    found = sorted(key for key, _recorded in planted
                   if any(key in text[start:end] for start, end in spans))  # fmt: skip
    assert found == sorted(key for key, recorded in planted if recorded), (text, spans)
    assert all(text[start] == "\\" and text[end - 1] == "}" for start, end in spans), spans


@holds(100, quoted_references())
def test_a_quote_of_a_latex_sentence_holds_a_number_where_its_reference_stands(
    drawn: tuple[str, str, str],
) -> None:
    """A quote copied from the PDF finds the sentence whose source has a cross-reference
    where the quote has its number, with the word before it, and a quote with one word
    changed does not (round 1 of G13 in step 8)."""
    from manuscript_guard.gates.revision import as_quoted, quoted_in

    view, quote, changed = drawn
    assert quoted_in(as_quoted(quote), as_quoted(view)), (quote, view)
    assert not quoted_in(as_quoted(changed), as_quoted(view)), (changed, view)


@holds(60, latex_claims())
def test_a_latex_claim_to_have_followed_a_guideline_is_read_where_it_prints(
    drawn: tuple[str, list[tuple[str, bool]]],
) -> None:
    """A claim in prose or a footnote is read; one in a comment, code, a listing or what
    `\\iffalse` leaves out is no claim (G8r, step 8)."""
    from manuscript_guard.gates import reporting as reporting_gate

    text, planted = drawn
    source = latex_structure.Source("main.tex", text, latex_mask.read(text))
    view = latex_views.markdown_view(source, latex_views.bindings(source)[0])
    named = reporting_gate._claims([(Path("main.tex"), reporting_gate._latex_prose(source, view))])
    assert sorted(named) == sorted(name for name, read in planted if read), text


@holds(60, latex_quotations())
def test_a_latex_quotation_is_read_at_its_line_and_nowhere_else(
    drawn: tuple[str, list[tuple[str, bool]]],
) -> None:
    """A quotation that cites a work, ``...'' or typographic, over a line break or in a
    footnote, is read on the line of the `.tex` its paragraph starts on; one in a comment,
    left out by `\\iffalse` or citing nothing is not (G7, step 8)."""
    from manuscript_guard.gates import quotations as quotations_gate

    text, planted = drawn
    view = latex_print.printed([latex_structure.Source("main.tex", text, latex_mask.read(text))])
    found = quotations_gate.printed_quotations(view)
    read = sorted(key for key, was in planted if was)
    assert sorted(key for key in read if any(key in q.quote for _p, q in found)) == read, found
    assert len(found) == len(read), (found, text)
    for _path, quotation in found:
        (key,) = [key for key in read if key in quotation.quote]
        start = text.rindex("\n\n", 0, text.index(key)) + 2
        # A paragraph that opens under a heading's line is placed at its own line.
        start = text.index("\n", start) + 1 if text.startswith("\\section", start) else start
        assert quotation.line == text.count("\n", 0, start) + 1, (quotation, text)
        assert quotation.keys == ("w",), quotation
        assert "--" not in quotation.quote, quotation
        if "rose" in quotation.quote and "of" in quotation.quote.split():
            assert "\u2013" in quotation.quote and "\u2026" in quotation.quote, quotation
        if "far" in quotation.quote:
            assert quotation.quote.count("\u2014") == 3 and "-" not in quotation.quote, quotation


def _a_quotation_s_line_is_the_printed_view_s(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print.Printed, "place_line",
                  lambda self, line: (self.origins[0][1], line))  # fmt: skip


def _latex_dashes_are_printed_as_typed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_typeset", lambda prose: prose)


def _latex_s_ellipsis_prints_nothing(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "SYMBOLS", {})


def _a_typographic_quotation_mark_opens_no_sentence(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.checking import produce

    patch.setattr(produce, "SENTENCE_END", re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])"))


def _latex_s_en_dash_is_typed_before_its_em_dash(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_typeset",
                  lambda prose: prose.replace("--", "\u2013").replace("---", "\u2014"))  # fmt: skip


def _a_line_is_placed_where_it_starts_blank(patch: pytest.MonkeyPatch) -> None:
    def place_line(self, line):
        self._lines[:] = self._lines or [0, *(at + 1 for at, c in enumerate(self.text)
                                             if c == "\n")]  # fmt: skip
        return self.place(self._lines[min(max(line, 1), len(self._lines)) - 1])

    patch.setattr(latex_print.Printed, "place_line", place_line)


def _no_latex_citation_is_printed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_citations", lambda source: [])


def _g8r_reads_a_latex_file_as_typed(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import reporting as reporting_gate

    patch.setattr(reporting_gate, "_latex_prose", lambda source, view: source.text)


def _g8r_reads_a_latex_file_s_code(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import reporting as reporting_gate

    def prose(source, view):
        return reporting_gate._blanked(view, source.reading.references)

    patch.setattr(reporting_gate, "_latex_prose", prose)


def _g8r_reads_a_typed_reference_list(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import reporting as reporting_gate

    def prose(source, view):
        return reporting_gate._blanked(view, source.reading.code)

    patch.setattr(reporting_gate, "_latex_prose", prose)


def _no_latex_cross_reference_is_recorded(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "POINTERS", frozenset())


def _a_label_is_a_cross_reference(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "POINTERS", latex_mask.POINTERS | {"label"})


def _a_quote_s_number_stands_for_no_reference(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import revision

    patch.setattr(revision, "_REF_SHAPED", re.compile("(?!)"))


def _a_reference_stands_for_its_number_alone(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import revision

    unnamed = (r"(?P<name>(?!))?(?P<opened>\()?[A-Z]?\d+(?:[.:]\d+)*(?P<letter>[A-Za-z]?)"
               r"(?P<closed>\))?")  # fmt: skip
    patch.setattr(revision, "_REF_SHAPED", re.compile(unnamed))


def _a_bracket_typed_round_a_reference_is_its_own(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import revision

    def printed_as(found, pointer):
        options = [re.escape(found.group(0)), re.escape(pointer + found.group("letter")),
                   re.escape(pointer)]  # fmt: skip
        if found.group("name"):
            options.append(re.escape(found.group("name") + " " + pointer))
        return "(?:" + "|".join(options) + ")"

    patch.setattr(revision, "_printed_as", printed_as)


def _g9_keeps_of_its_cuts(patch: pytest.MonkeyPatch, dropped) -> None:
    """G9 with `dropped(source, span)` taken out of what it cuts."""
    kept = methods_gate._cuts
    patch.setattr(methods_gate, "_cuts", lambda source, view: tuple(
        span for span in kept(source, view) if not dropped(source, span)))  # fmt: skip


def _g9_cuts_no_latex_heading(patch: pytest.MonkeyPatch) -> None:
    _g9_keeps_of_its_cuts(patch, lambda source, span: any(
        span == (h.start, h.end) for h in source.reading.headings))  # fmt: skip


def _g9_reads_a_table_set_apart_with_its_paragraph(patch: pytest.MonkeyPatch) -> None:
    _g9_keeps_of_its_cuts(patch, lambda source, span: span in source.reading.tables)


def _g9_reads_an_anchored_float_with_the_paragraph_round_it(patch: pytest.MonkeyPatch) -> None:
    _g9_keeps_of_its_cuts(patch, lambda source, span: span[0] == span[1])


def _g9_reads_a_float_s_words(patch: pytest.MonkeyPatch) -> None:
    kept = methods_gate._unprinted
    patch.setattr(methods_gate, "_unprinted", lambda source, view: tuple(
        span for span in kept(source, view) if span not in source.reading.floats))  # fmt: skip


def _g9_reads_a_table_s_words_inside_a_float(patch: pytest.MonkeyPatch) -> None:
    kept = methods_gate._unprinted
    patch.setattr(methods_gate, "_unprinted", lambda source, view: tuple(
        span for span in kept(source, view) if span not in source.reading.tables))  # fmt: skip


def _g9_reads_no_word_of_a_float_that_holds_an_anchor(patch: pytest.MonkeyPatch) -> None:
    def every(source, view):
        return (*source.reading.tables, *source.reading.floats)

    patch.setattr(methods_gate, "_unprinted", every)


def _g9_ends_a_paragraph_at_a_float(patch: pytest.MonkeyPatch) -> None:
    kept = methods_gate._latex_read

    def read(path, source, view):
        found = kept(path, source, view)
        return dataclasses.replace(
            found, cuts=(*found.cuts, *methods_gate._unprinted(source, view))
        )

    patch.setattr(methods_gate, "_latex_read", read)


def _g9_ends_a_latex_paragraph_at_a_line_of_spaces_in_its_view(
    patch: pytest.MonkeyPatch,
) -> None:
    kept = methods_gate._latex_read
    patch.setattr(methods_gate, "_latex_read", lambda path, source, view: dataclasses.replace(
        kept(path, source, view), typed=None))  # fmt: skip


def _g9_starts_a_typed_paragraph_where_its_first_line_starts(
    patch: pytest.MonkeyPatch,
) -> None:
    patch.setattr(methods_gate, "_printed_from", lambda text, first, last: (
        [(first, last)] if text[first:last].strip() else []))  # fmt: skip


def _g9_starts_a_paragraph_at_the_end_of_its_heading(patch: pytest.MonkeyPatch) -> None:
    def cut(text, span, cut):
        if cut[1] <= span[0] or span[1] <= cut[0]:
            return [span]
        return [(first, last) for first, last in ((span[0], cut[0]), (cut[1], span[1]))
                if text[first:last].strip()]  # fmt: skip

    patch.setattr(methods_gate, "_cut", cut)


def _g9_reads_a_latex_binding_as_its_view_pads_it(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(methods_gate, "_PADDED", re.compile("(?!)"))
def _g6_takes_no_latex_citation(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(writing_gate, "_cited_at", lambda source: [])


def _g6_reads_a_latex_comment_as_prose(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(writing_gate, "_latex_prose", lambda source: source.text)


def _g6_looks_for_a_placeholder_in_the_prose_only(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(writing_gate, "_latex_typed", writing_gate._latex_prose)


def _g6_reads_a_latex_file_whole_as_typed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(writing_gate, "_latex_typed", lambda source: source.text)


def _g6_reads_a_typed_reference_list(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "REFERENCES", "nothing")


def _g6_takes_nocite_for_a_claims_support(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(writing_gate, "_cited_at",
                  lambda source: [found.start for found in source.reading.cited])  # fmt: skip


def _g6_reads_no_typed_reference_list(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(writing_gate, "_typed_lists_of", lambda folder, documents: [])


def _g6_reads_a_definitions_body_in_the_preamble(patch: pytest.MonkeyPatch) -> None:
    class Every:
        def __contains__(self, name: object) -> bool:
            return True

    patch.setattr(latex_mask, "HOOKS", Every())


def _g6_reads_past_the_documents_end(patch: pytest.MonkeyPatch) -> None:
    ended = latex_mask._Reader._end

    def broken(self, name: str, at: int) -> None:
        ended(self, name, at)
        self.body_end = -1

    patch.setattr(latex_mask._Reader, "_end", broken)


def _a_floats_words_are_printed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "FLOATS", frozenset())


def _the_preamble_is_printed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_body", lambda reading: 0)


def _a_headings_title_is_printed_twice(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_title_end", lambda heading: heading.start)


def _an_abstract_runs_on_to_the_next_heading(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_abstracts_closed", lambda reading: [])


def _a_formula_is_printed_as_typed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_formulas", lambda reading, formula="": [])


def _a_spans_bindings_are_not_printed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_bindings_in", lambda placeholders, start, end: "")


def _a_prose_binding_is_printed_with_spaces_round_it(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_binding", lambda placeholder: f" {{{{{placeholder.ref}}}}} ")


def _a_formulas_bindings_are_not_printed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_formula_events", lambda reading, placeholders, formula="":
                  latex_print._formulas(reading, formula))  # fmt: skip


def _a_typed_tables_bindings_are_not_printed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_table_events", lambda reading, placeholders: [
        (start, end, " ") for start, end in (*reading.tables, *reading.references)])  # fmt: skip


@holds(60, latex_declared())
def test_a_latex_preamble_states_its_class_and_bibliography_as_written(
    drawn: tuple[str, dict[str, object]],
) -> None:
    """The class, each of its options, the bibliography style and biblatex's style a preamble
    states are what G4 compares with the journal's profile, and what a comment or an
    `\\iffalse` block names is not (step 6)."""
    text, stated = drawn
    reading = latex_mask.read(text)
    assert reading.refusals == (), (reading.refusals, text)
    declared = list(reading.declared)
    assert [value for kind, value in declared if kind == "class"] == [stated["class"]], text
    assert [value for kind, value in declared if kind == "class_option"] == stated["options"]
    assert [value for kind, value in declared if kind == "bst"] == [stated["bst"]], text
    (options,) = [value for kind, value in declared if kind == "biblatex"]
    assert f"style={stated['style']}" in options, (options, text)


def _a_class_named_in_a_comment_is_stated(patch: pytest.MonkeyPatch) -> None:
    declares = latex_mask._Reader._declares

    def broken(self, name: str, end: int) -> None:
        declares(self, name, end)
        for found in re.finditer(r"\\" + name + r"\{([^{}]*)\}", self.text):
            kind = "class" if name == "documentclass" else "bst"
            self.declared.append((kind, found.group(1)))

    patch.setattr(latex_mask._Reader, "_declares", broken)


def _a_class_s_options_are_one(patch: pytest.MonkeyPatch) -> None:
    declares = latex_mask._Reader._declares

    def broken(self, name: str, end: int) -> None:
        declares(self, name, end)
        options = [value for kind, value in self.declared if kind == "class_option"]
        self.declared = [d for d in self.declared if d[0] != "class_option"]
        if options:
            self.declared.append(("class_option", ",".join(options)))

    patch.setattr(latex_mask._Reader, "_declares", broken)
@holds(100, latex_displays())
def test_a_display_written_for_latex_holds_no_bare_special_and_no_ligature(display: str) -> None:
    """Each of TeX's specials in a display is written escaped, but the no-break space, which is
    written as a tie; and no dash TeX joins from two characters is written, `--`, which before
    a minus sign made an em dash of both, from two hyphens too (step 4b)."""
    written = latex_values.escaped(display, "results.x")
    bare = re.sub(r"\\(?:[A-Za-z]+(?:\{[^{}]*\})?|[#$%&_{},])|\{\}", "", written)
    assert sorted(set(bare) & set("\\{}$&#%_^")) == [], (display, written)
    assert bare.count("~") == display.count("\N{NO-BREAK SPACE}"), (display, written)
    assert "--" not in written, (display, written)


def _a_percent_is_written_bare(patch: pytest.MonkeyPatch) -> None:
    patch.setitem(latex_values._SPECIALS, "%", "%")


def _two_hyphens_are_written_as_typed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_values, "_joins", lambda text, index: False)


def _an_en_dash_is_written_as_a_ligature(patch: pytest.MonkeyPatch) -> None:
    patch.setitem(latex_values._TEXT, "\N{EN DASH}", "--")


def _iffalse_hides_its_else(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_mask, "_CONDITIONALS", re.compile(r"\\(?:if[A-Za-z]*|fi)(?![A-Za-z])"))


def _a_line_break_takes_a_bracket_on_the_next_line(patch: pytest.MonkeyPatch) -> None:
    argument = latex_mask._Reader._argument

    def broken(self) -> bool:
        command, self.command = self.command, "" if self.command == "\\" else self.command
        try:
            return argument(self)
        finally:
            if self.command == "":
                self.command = command

    patch.setattr(latex_mask._Reader, "_argument", broken)


def _an_unknown_command_hides_its_arguments(patch: pytest.MonkeyPatch) -> None:
    word = latex_mask._Reader._word

    def broken(self, name: str, at: int, end: int) -> None:
        word(self, name, at, end)
        if name not in latex_mask.COMMANDS and not self.pending and self.refused is None:
            self.command, self.pending = name, ("{b}",)

    patch.setattr(latex_mask._Reader, "_word", broken)


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


# -------------------------------------------------------------- a statistic quoted whole

#: A sentence that quotes each statistic with what it belongs to, and the interval whole.
_TOGETHER = (
    "The ratio was {{results.or.point}} (95% CI {{results.or.ci_low}} to "
    "{{results.or.ci_high}}; P = {{results.or.p}}), and {{results.female.n}} of "
    "{{results.cohort.n}} ({{results.female.pct}}%) were women."
)
#: A P value after "s.e.", in its estimate's sentence (round 2 of #327).
_AFTER_SE = "Its ratio, {{results.or.point}} (s.e. 0.21), P = {{results.or.p}}."
#: Each kind of statistic in a sentence of its own, without what it belongs to.
_APART = ("Then P was {{results.hr.p}}.", "Men were {{results.male.pct}}%.")


@st.composite
def _quoted_apart(draw: st.DrawFn) -> str:
    """A text that quotes each kind of statistic with what it belongs to, and each again in
    a sentence without it: the planted sentences first, in an order drawn, so that nothing
    drawn after them can put them in a comment it left open."""
    planted = draw(st.permutations([_TOGETHER, _AFTER_SE, *_APART]))
    gaps = [draw(st.sampled_from((" ", "\n", "\n\n"))) for _ in planted[1:]]
    after = zip(gaps, planted[1:], strict=True)
    return planted[0] + "".join(gap + sentence for gap, sentence in after) + "\n\n" + draw(texts())


@holds(200, _quoted_apart())
def test_a_statistic_is_alone_only_in_a_sentence_without_what_it_belongs_to(text: str) -> None:
    """Whatever the sentences around them, a p value and a share are said to be quoted alone
    in the sentence that lacks their estimate or their counts, and in no other, and the
    interval quoted whole once is not reported."""
    from readings import whole_namespace

    from manuscript_guard.gates.numbers import in_sentences, quoted_whole
    from manuscript_guard.text.placeholders import parse

    placeholders, _malformed = parse(text)
    said = quoted_whole([(Path("main.md"), text, in_sentences(placeholders, text))],
                        whole_namespace())  # fmt: skip
    alone = sorted(f.message.split(" is quoted")[0] for f in said.findings)
    assert alone == ["results.hr.p", "the share results.male.pct"], (alone, text)


# ------------------------------------------------------- the label beside an interval or a spread

#: Sentences whose labels are those emitted, each set to catch one way of reading them wrong:
#: a level written "95.0%", two levels in one sentence of which the nearer is the bound's,
#: a label in the sentence before, and a label written after the binding.
_LABELLED_RIGHT = (
    "The ratio was {{results.or.point}} (95% CI {{results.or.ci_low}} to "
    "{{results.or.ci_high}}).",
    "A 90% CI was {{results.or.ci90_low}} to {{results.or.ci90_high}}.",
    "Here 95.0% CI {{results.or.ci_low}} to {{results.or.ci_high}}.",
    "A 90% CI elsewhere, and 95% CI {{results.or.ci_low}} to {{results.or.ci_high}}.",
    "Age was {{results.age.mean}} (SD {{results.age.sd}}) years.",
    "The SE was small. Mean {{results.age.mean}} (\N{PLUS-MINUS SIGN}{{results.age.sd}}).",
    "Weight {{results.age.mean}} \N{PLUS-MINUS SIGN} {{results.age.se}} (standard error).",
    # Round 1 of #327: the stop of "s.d." ended a sentence, so its binding stood alone.
    "Height was {{results.age.mean}} (s.d. {{results.age.sd}}) cm.",
    # Round 2 of #327: where "s.d." ends a sentence, the next one is not labelled by it.
    "Values are summarised as mean and s.d. Uncertainty of the slope was "
    "{{results.age.se}}.",
    "Spread is given as mean \N{PLUS-MINUS SIGN} s.e.m.\n\nAge varied by {{results.age.sd}} years.",
)
#: Sentences whose labels are not those emitted, and what G2 says of each.
_LABELLED_WRONG = (
    ("With 90% CI {{results.or.ci_low}} to {{results.or.ci_high}} it was wide.",
     "results.or.ci_low bounds the 95% interval"),
    ("The CI 95% was {{results.or.ci90_low}} to {{results.or.ci90_high}}.",
     "results.or.ci90_low bounds the 90% interval"),
    ("Age was {{results.age.mean}} (SE {{results.age.sd}}).", "results.age.sd is a standard"),
    ("Height {{results.age.mean}} \N{PLUS-MINUS SIGN} {{results.age.se}} (SD).",
     "results.age.se is a standard"),
    ("HR was {{results.hr.ci_low}} to {{results.hr.ci_high}}.", "the interval of results.hr"),
    ("Its mean {{results.age.mean}} (s.e. {{results.age.sd}}) mg.", "results.age.sd is a standard"),
    ("Then {{results.age.mean}} \N{PLUS-MINUS SIGN} {{results.age.se}} (s.d.).",
     "results.age.se is a standard"),
)  # fmt: skip


@st.composite
def _labelled_apart(draw: st.DrawFn) -> str:
    """A text with each planted sentence, in an order drawn and apart in ways drawn, before
    drawn words: so that nothing drawn after them can put them in a comment it left open."""
    planted = draw(st.permutations([*_LABELLED_RIGHT, *(said for said, _ in _LABELLED_WRONG)]))
    gaps = [draw(st.sampled_from((" ", "\n", "\n\n"))) for _ in planted[1:]]
    after = zip(gaps, planted[1:], strict=True)
    return planted[0] + "".join(gap + sentence for gap, sentence in after) + "\n\n" + draw(texts())


@holds(200, _labelled_apart())
def test_a_label_is_said_where_it_differs_from_what_was_emitted_and_nowhere_else(
    text: str,
) -> None:
    """Item 33: whatever the sentences around them, the level written beside an interval's
    bounds and the label beside a spread are held to what was emitted: a warning for each
    one written otherwise, one asking for the level of an interval that has none, and
    nothing for each written as emitted."""
    from readings import labels_namespace

    from manuscript_guard.gates.labels import labelled
    from manuscript_guard.gates.numbers import in_sentences
    from manuscript_guard.text.placeholders import parse

    placeholders, _malformed = parse(text)
    said = labelled([(Path("main.md"), text, in_sentences(placeholders, text))],
                    labels_namespace())  # fmt: skip
    found = sorted(f.message for f in said.findings)
    assert len(found) == len(_LABELLED_WRONG), (found, text)
    for (_sentence, start), message in zip(sorted(_LABELLED_WRONG, key=lambda w: w[1]), found,
                                           strict=True):  # fmt: skip
        assert message.startswith(start), (message, start, text)


# ------------------------------------------------------- a date of the data, typed or declared

#: Sentences that bind a date and say nothing of it G2 warns of, each set to catch one way of
#: reading them wrong: a dataset's own date, a parameter's, a year computed as a number, a
#: sentence that does not date the data, the words of a binding's key, of the next sentence
#: and of a comment, and a key no value has.
_DATED_RIGHT = (
    "Data were extracted on {{results.dataset.vb.extracted}}.",
    "Reports were retrieved from {{results.param.start}}.",
    "Reports from {{results.cohort.first_year}} were extracted.",
    "Ethics approval was given on {{results.old.extracted}}.",
    "Approval came on {{results.old.extracted}}.",
    "Approval came on {{results.old.label}}. The data were extracted later.",
    "Approval came on {{results.old.extracted}} <!-- extracted -->.",
    "Data were extracted on {{results.none.such}}.",
    # Round 1 of #392: a dictionary's release named by a year, and the words of another
    # binding and of a citation.
    "Codes were obtained from ICD-10 {{results.dictionary.icd_10}}.",
    "Approval came on {{results.old.extracted}} ({{method.extraction}}).",
    "Approval came on {{results.old.label}} [@extracted2020].",
)
#: Sentences that date the data with a date typed into the analysis, and the binding G2
#: names in each.
_DATED_WRONG = (
    ("Data were extracted on {{results.old.extracted}}.", "{{results.old.extracted}}"),
    ("We downloaded the files on {{results.old.label}}.", "{{results.old.label}}"),
    ("Reports up to {{results.old.extracted}} were kept.", "{{results.old.extracted}}"),
    ("The snapshot of {{results.old.label}} held {{results.n}} reports.",
     "{{results.old.label}}"),
    ("Data were\nretrieved on {{results.old.extracted}}.", "{{results.old.extracted}}"),
    # Round 1 of #392: one sentence for each word, so that a rule which drops one fails.
    ("Reports covering {{results.old.label}} were kept.", "{{results.old.label}}"),
    ("The database was locked on {{results.old.extracted}}.", "{{results.old.extracted}}"),
    ("Reports until {{results.old.label}} were read.", "{{results.old.label}}"),
    ("The reports span {{results.old.extracted}} onwards.", "{{results.old.extracted}}"),
    ("Reports through {{results.old.label}} were read.", "{{results.old.label}}"),
    ("A cut-off of {{results.old.extracted}} applied.", "{{results.old.extracted}}"),
    ("A frozen copy of {{results.old.label}} was read.", "{{results.old.label}}"),
    ("Records were accessed on {{results.old.extracted}}.", "{{results.old.extracted}}"),
    ("Records were obtained on {{results.old.label}}.", "{{results.old.label}}"),
    ("Queries run on {{results.old.extracted}} found them.", "{{results.old.extracted}}"),
)  # fmt: skip


@st.composite
def _dated_apart(draw: st.DrawFn) -> str:
    """A text with each planted sentence, in an order drawn and apart in ways drawn, before
    drawn words: so that nothing drawn after them can put them in a comment it left open."""
    planted = draw(st.permutations([*_DATED_RIGHT, *(said for said, _ in _DATED_WRONG)]))
    gaps = [draw(st.sampled_from((" ", "\n", "\n\n"))) for _ in planted[1:]]
    after = zip(gaps, planted[1:], strict=True)
    return planted[0] + "".join(gap + sentence for gap, sentence in after) + "\n\n" + draw(texts())


@holds(200, _dated_apart())
def test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data(
    text: str,
) -> None:
    """Whatever the sentences around them, a date the analysis typed rather than declared
    with `dataset()` is warned of where its sentence says the data were extracted or what
    they cover, once for each such sentence, and nowhere else."""
    from readings import data_dates_namespace

    from manuscript_guard.gates.data_dates import data_dates
    from manuscript_guard.gates.numbers import in_sentences

    placeholders, _malformed = parse_bindings(text)
    said = data_dates([(Path("main.md"), text, in_sentences(placeholders, text))],
                      data_dates_namespace())  # fmt: skip
    found = sorted(f.message.split(" is ")[0] for f in said.findings)
    assert found == sorted(named for _sentence, named in _DATED_WRONG), (found, text)


# ------------------------------------------------------------------- a data statement


@st.composite
def _statements(draw: st.DrawFn) -> tuple[str, list[str]]:
    """Drawn words, and the same with every kind of link put in at places drawn: each
    temporary one, and each link to a fixed version of a repository."""
    text = draw(texts())
    pieces = text.split(" ")
    for link in TEMPORARY_LINKS + FIXED_LINKS:
        pieces.insert(draw(st.integers(0, len(pieces))), link)
    return text, " ".join(pieces)


@holds(100, _statements())
def test_each_identifier_names_data_and_each_temporary_link_is_found(
    drawn: tuple[str, str],
) -> None:
    """Whatever the words around it, each kind of identifier satisfies a journal that asks
    for one, and each temporary link is found, and no link to a fixed version."""
    from manuscript_guard.gates.data_statement import judge_statement

    text, linked = drawn
    policy = {"identifier_required": True}
    for identifier in DATA_IDENTIFIERS:
        said = judge_statement(f"{text} {identifier} {text}", policy, set(), Path("x"))
        assert "data-identifier-missing" not in {f.code for f in said.findings}, identifier
    found = judge_statement(linked, {}, set(), Path("x")).findings
    temporary = sorted(f.message.split("'")[1] for f in found if f.code == "data-link-temporary")
    before = judge_statement(text, {}, set(), Path("x")).findings
    drawn_links = sorted(f.message.split("'")[1] for f in before if f.code == "data-link-temporary")
    assert temporary == sorted(drawn_links + list(TEMPORARY_LINKS)), (temporary, linked)


# ------------------------------------------------------- the deposit a data statement names


@holds(100, deposit_statements())
def test_a_deposit_is_named_by_its_doi_however_written_and_by_no_other(
    drawn: tuple[str, list[str], list[str]],
) -> None:
    """Whatever the words around it, the statement names the deposit wherever its DOI is
    written, bare or in a link, in any case, in brackets or emphasis or before a stop; and a
    DOI that begins as the deposit's and is another names nothing the words did not."""
    from manuscript_guard.gates.data_statement import names_doi

    text, named, others = drawn
    for written in named:
        assert names_doi(written, DEPOSIT_DOI), written
    before = names_doi(text, DEPOSIT_DOI)
    for written in others:
        assert names_doi(written, DEPOSIT_DOI) == before, written


# ------------------------------------------------------------- a count in a deposited table


@holds(100, count_cells())
def test_a_cell_is_read_as_a_count_only_where_it_states_one(
    drawn: list[tuple[str, int | None]],
) -> None:
    """A cell that is a count alone, with its share in brackets or over its denominator, is
    read as that count, whatever the spaces; one with a point, a bound, a label, a range or
    a sign is read as none."""
    from manuscript_guard.deposit.counts import count_in_cell

    for cell, count in drawn:
        assert count_in_cell(cell) == count, cell


# ------------------------------------------------- the data sources a statement names and says


def _written_as(name: str) -> tuple[str, ...]:
    """A source's name as a statement may write it: in capitals, in small letters, its words
    broken across a line, spaced twice or with a space that does not break, in emphasis, and
    followed by a stop."""
    return (
        name.upper(), name.lower(), name.replace(" ", "\n"), name.replace(" ", "  "),
        name.replace(" ", "\N{NO-BREAK SPACE}"), f"*{name}*", f"{name}.",
    )  # fmt: skip


@st.composite
def _placed(draw: st.DrawFn) -> tuple[str, int]:
    text = draw(texts())
    return text, draw(st.integers(0, len(text.split(" "))))


@holds(100, _placed())
def test_a_source_is_named_in_any_writing_of_its_names_and_never_inside_a_word(
    drawn: tuple[str, int],
) -> None:
    """Whatever the words around it, each name of a source, each other name and each way of
    writing them names it, and the same name glued to a longer word does not."""
    from generated import SOURCE_NAMES
    from readings import DATA_SOURCES

    from manuscript_guard.data_sources import named

    text, at = drawn
    pieces = text.split(" ")

    def put(word: str) -> str:
        return " ".join(pieces[:at] + [word] + pieces[at:])

    for source in DATA_SOURCES:
        alone = named(text, source)
        own = [name for name in SOURCE_NAMES if name in (source["name"], *source["also_known_as"])]
        assert own
        for name in own:
            for written in _written_as(name):
                assert named(put(written), source), (written, source["id"])
            for glued in (f"x{name}", f"{name}x", f"{name}2", f"9{name}"):
                assert named(put(glued), source) is alone, (glued, source["id"])


@holds(60, texts(), texts())
def test_a_statement_is_held_to_each_source_s_route_whatever_surrounds_it(
    before: str, after: str
) -> None:
    """Whatever paragraphs come before and after, a sentence that names a source and says the
    data are asked for warns of the source anyone may download and not of the one a committee
    decides on; one that says anyone may have them warns of the second and not the first,
    unless a denial comes before it in its sentence, however far; and the open source said
    open after a denial of something else still excuses an "on request" elsewhere."""
    from generated import ASKED_FOR, DENIALS, OPENLY_HAD
    from readings import DATA_SOURCES

    from manuscript_guard.data_sources import route_differs

    sources = [dict(source) for source in DATA_SOURCES]
    surrounding = route_differs(f"{before}\n\n{after}", sources)

    def differs(sentence: str) -> set[tuple[str, str]]:
        found = route_differs(f"{before}\n\n{sentence}\n\n{after}", sources)
        return set(found) - set(surrounding)

    for asked in ASKED_FOR:
        assert differs(f"Data of the ORA are {asked}.") == {("ora", "on request")}, asked
        assert differs(f"Data of the ENCD are {asked}.") == set(), asked
        # Said openly elsewhere, the open archive's "on request" asks for something else.
        said = f"The ORA is publicly available. Data derived from the ORA are {asked}."
        assert ("ora", "on request") not in differs(said), asked
    for openly in OPENLY_HAD:
        assert differs(f"ENCD data are {openly}.") == {("encd", "publicly")}, openly
        assert differs(f"ORA data are {openly}.") == set(), openly
        for denial in DENIALS:
            assert differs(f"ENCD data {denial} {openly}.") == set(), (denial, openly)
        far = f"None of the ENCD claims, prescriptions, and hospital records are {openly}."
        assert differs(far) == set(), openly
        # Said open after a denial of something else, the open archive excuses an "on
        # request" of its derived data all the same (round 2 of #384).
        excused = (f"No new data were drawn, and the ORA is {openly}. "
                   f"Data derived from the ORA are {ASKED_FOR[0]}.")  # fmt: skip
        assert ("ora", "on request") not in differs(excused), openly


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


# ------------------------------------------------------------- the results a plan promises


@holds(100, planned_plans())
def test_a_planned_result_is_read_from_its_own_item_and_nowhere_else(
    drawn: tuple[str, list[tuple[str, bool]]],
) -> None:
    """Item 37: each key the Planned results section lists, in the order it lists them, as
    the plan writes it, binds it or groups it, its subsections included; and nothing from an
    item with no key, code that is not a key, or prose after the list."""
    from manuscript_guard.gates.design import planned_results

    plan, listed = drawn
    read = planned_results(plan)
    assert read is not None, plan
    assert [(found.key, found.group) for found in read] == listed, plan


# ------------------------------------------------- a registration and its outcomes

# Imported here, not at the top, to keep clear of the import block other branches edit.
from generated import (  # noqa: E402
    NAMED_LOOKALIKES,
    registered_quotes,
    registration_texts,
    retrospective_texts,
)


@holds(100, registration_texts())
def test_a_registration_is_found_where_the_manuscript_gives_it_and_no_lookalike_is(
    drawn: tuple[str, list[tuple[str, str, str | None, str]]],
) -> None:
    """G12 finds a registration's identifier in every way a manuscript gives it, in any case
    and inside a link, and not where the manuscript gives only one with a digit more, a
    letter before it or a longer OSF name."""
    from manuscript_guard.gates import registration as gate
    from manuscript_guard.registrations import Declared, identify

    plain, given = drawn
    for written, kept, _found, text in given:
        registry, identifier = identify(kept)
        entry = Declared(kept, identifier, registry, None, (), False, 0)
        assert gate.named_in(text, entry), (written, text)
        assert not gate.named_in(plain, entry), (kept, plain)


@holds(100, registration_texts())
def test_each_identifier_a_manuscript_gives_is_found_as_written_and_nothing_else(
    drawn: tuple[str, list[tuple[str, str, str | None, str]]],
) -> None:
    """Where paper.yaml lists no registration, G12 names each NCT, ISRCTN, EU PAS and
    PROSPERO number the manuscript gives, as it is written, once for each time; what is one
    only inside a longer word or number is not one."""
    from manuscript_guard import registrations

    plain, given = drawn
    found = registrations.NAMED_IN_TEXT.findall
    assert sorted(found(plain)) == sorted(NAMED_LOOKALIKES), plain
    for written, _kept, named, text in given:
        more = Counter(found(text)) - Counter(found(plain))
        assert sorted(more.elements()) == ([named] if named else []), (written, text)


@holds(150, registered_quotes())
def test_a_registered_outcome_is_found_however_it_was_copied_and_not_with_a_word_changed(
    drawn: tuple[str, str, str],
) -> None:
    """A quote of a registered outcome is found in the registry's record however the author
    copied it, typed, in capitals and wrapped by YAML, the page's ligatures, dashes, curly
    marks and spaces against the keyboard's; with one of its words changed it is not."""
    from manuscript_guard.gates import registration as gate

    record, copied, changed = drawn
    assert gate.fold(copied) in gate.fold(record), (copied, record)
    assert gate.fold(changed) not in gate.fold(record), (changed, record)


@holds(100, retrospective_texts())
def test_a_late_registration_is_said_in_every_way_a_manuscript_says_it_and_no_other(
    drawn: tuple[str, list[str]],
) -> None:
    """A manuscript says the study was registered retrospectively in either order of the
    words, with a line break between them, in capitals; registered prospectively, analysed
    retrospectively, or a retrospective cohort does not say it."""
    from manuscript_guard.gates import registration as gate

    plain, said = drawn
    assert not gate.says_retrospective(plain), plain
    for text in said:
        assert gate.says_retrospective(text), text


def _registration_found_inside_another(monkeypatch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import registration as gate

    def anywhere(text: str, entry: Any) -> bool:
        return entry.id.rsplit("/", 1)[-1].casefold() in text.casefold()

    monkeypatch.setattr(gate, "named_in", anywhere)


def _identifier_read_inside_a_word(monkeypatch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import registrations

    loose = re.compile(
        r"(?i)(?:NCT\d{8}|ISRCTN\d{8}|EU ?PAS ?\d{3,12}|CRD\d{11,12})(?![A-Za-z0-9])"
    )
    monkeypatch.setattr(registrations, "NAMED_IN_TEXT", loose)


def _fold_keeps_case(monkeypatch: pytest.MonkeyPatch) -> None:
    import unicodedata

    from manuscript_guard.gates import registration as gate

    def cased(text: str) -> str:
        text = unicodedata.normalize("NFKC", text).translate(gate._DASHES)
        return " ".join(text.translate(gate._QUOTES).split())

    monkeypatch.setattr(gate, "fold", cased)


def _fold_keeps_dashes(monkeypatch: pytest.MonkeyPatch) -> None:
    import unicodedata

    from manuscript_guard.gates import registration as gate

    def dashed(text: str) -> str:
        text = unicodedata.normalize("NFKC", text).translate(gate._QUOTES)
        return " ".join(text.casefold().split())

    monkeypatch.setattr(gate, "fold", dashed)


def _retrospective_any_regist_word(monkeypatch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import registration as gate

    loose = re.compile(r"(?i)\bretrospectiv\w*\s+regist\w*|\bregist\w*\s+retrospectiv\w*")
    monkeypatch.setattr(gate, "RETROSPECTIVE", loose)


def _retrospective_on_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import registration as gate

    one_line = re.compile(
        r"(?i)\bretrospective(?:ly)? regist(?:ered|ration)\b"
        r"|\bregist(?:ered|ration) (?:was )?retrospective(?:ly)?\b"
    )
    monkeypatch.setattr(gate, "RETROSPECTIVE", one_line)


# ------------------------------------------------------------ the variables a plan names


@holds(100, collection_plans())
def test_a_variable_is_read_from_the_plan_outside_its_deviations_and_nowhere_else(
    drawn: tuple[str, list[str], list[tuple[str, int]], list[tuple[str, int]], int],
) -> None:
    """Each variable the dictionary has, dotted or not, is read where the plan names it in
    backticks, its subsections and a list headed "Planned results and amendments" included,
    at its first mention; each name that reads as a variable's and that the dictionary lacks
    is read the same way, one written in another case among them; and nothing is read from
    the Deviations or the sections under them, from "Changes to the planned results", from
    code, values, a fence or a comment. Of the text drawn after the plan, nothing is
    compared: only that it changes nothing before it."""
    from manuscript_guard.gates.collection import variables_named

    plan, names, used, undefined, last = drawn
    read_used, read_undefined = variables_named(plan, names)
    assert [(n.name, n.line) for n in read_used if n.line <= last] == used, plan
    assert [(n.name, n.line) for n in read_undefined if n.line <= last] == undefined, plan


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
    plans += [(-1, "next sentence"), (-1, "two statistics"), (-1, "middle dot"),
              (-1, "decimal comma"), (-1, "reference after")]  # fmt: skip
    shapes = draw(st.permutations(("e", "x10", "<")))
    sentences: list[tuple[str, tuple[Any, ...] | None]] = []
    for number, (index, plan) in enumerate(draw(st.permutations(plans))):
        if plan == "next sentence":
            s, df, _p = statistic("t", _MODERATE)
            sentences.append((f"t({df[0]}) = {s}. {words().capitalize()} p = .40", None))
            continue
        if plan in ("middle dot", "decimal comma"):
            # A decimal written with a middle dot, in the P, or a comma, in the statistic:
            # not read at all, rather than read as its whole part (round 1 of #285).
            s, df, p = statistic("t", _MODERATE)
            if plan == "middle dot":
                printed = f"{p:.3f}".replace(".", "\N{MIDDLE DOT}")
                sentences.append((f"t({df[0]}) = {s}, p = {printed}", None))
            else:
                sentences.append((f"t({df[0]}) = {s.replace('.', ',')}, p = {p:.3f}", None))
            continue
        if plan == "reference after":
            # A reference set inline after a number that has its point, as text taken from
            # a PDF gives it: the comma is the sentence's, and the test is read (round 1 of
            # #336).
            s, df, p = statistic("t", _MODERATE)
            sign, printed = _printed_p(draw, p, "=")
            first, second = draw(st.integers(1, 99)), draw(st.integers(1, 99))
            sentences.append((f"t({df[0]}) = {s},{first} p {sign} {printed},{second}",
                              (0, "t", s, df, sign, printed, "right")))  # fmt: skip
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


def _a_decimal_comma_is_read_as_a_whole_number(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import reported

    refusal = r"(?(stat_point)|(?![\N{MIDDLE DOT},]\d))"
    assert refusal in reported._STATISTIC.pattern
    pattern = reported._STATISTIC.pattern.replace(refusal, "")
    patch.setattr(reported, "_STATISTIC", re.compile(pattern))


def _a_comma_after_a_point_is_taken_for_a_decimal_comma(patch: pytest.MonkeyPatch) -> None:
    """The rule before round 1 of #336: a comma and a digit after a number refused it, though
    the number had its point already."""
    from manuscript_guard.stats import reported

    refusal = r"(?![\N{MIDDLE DOT},]\d)"
    for name, conditional in (("_STATISTIC", rf"(?(stat_point)|{refusal})"),
                              ("_P", rf"(?(p_point)|(?(power)|{refusal}))")):  # fmt: skip
        expression = getattr(reported, name)
        assert conditional in expression.pattern
        patch.setattr(reported, name, re.compile(expression.pattern.replace(
            conditional, refusal)))  # fmt: skip


def _a_middle_dot_is_read_as_the_end_of_a_p(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import reported

    pattern = reported._P.pattern.replace(r"[\N{MIDDLE DOT},]\d", r"\d")
    assert pattern != reported._P.pattern
    patch.setattr(reported, "_P", re.compile(pattern))


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


# ------------------------------------------------------ an estimate, its interval and its P

#: Each way an estimate and its interval are written, the name first: its kind, and the
#: level it states.
_INTERVAL_FORMS = (
    ("ratio", "OR {e} (95% CI {l} to {u})", "95"),
    ("ratio", "odds ratio was {e} (95% CI, {l}-{u})", "95"),
    ("ratio", "HR = {e}; 95% CI {l}\N{EN DASH}{u}", "95"),
    ("ratio", "RR {e} [95% CI {l}, {u}]", "95"),
    ("ratio", "hazard ratio was\n{e} (95% confidence interval {l} to {u})", "95"),
    ("ratio", "aOR {e} (CI 95% {l}\N{EM DASH}{u})", "95"),
    ("ratio", "risk ratio of {e}, 90% CI {l} to {u}", "90"),
    ("difference", "MD {e} (95% CI {l} to {u})", "95"),
    ("difference", "mean difference was {e} (95% CI {l}, {u})", "95"),
    ("difference", "RD = {e}, 99% CI {l} to {u}", "99"),
)
#: The half-width of a Wald interval at each level, in standard errors.
_Z = {"90": 1.6448536269514722, "95": 1.959963984540054, "99": 2.5758293035489004}
#: How a P is written after its interval.
_P_AFTER = (", P {sign} {p}", "; p {sign} {p}", ", *P* {sign} {p}", " (P {sign} {p})")
#: A P far on the other side of the level: beside an interval that excludes its null, and
#: beside one that includes it.
_AGAINST = {
    True: (("=", "0.40"), ("=", ".62"), (">", "0.20")),
    False: (("<", "0.001"), ("=", "0.003")),
}
#: What a sentence says of an interval that is not the plain one, and of a P.
_NOT_PLAIN_INTERVAL = (
    "by profile likelihood, ", "with an exact interval, ", "by bootstrap, ",
    "in a Bayesian model, ",
)  # fmt: skip
#: The word "difference" before a ratio's name: what a sentence says before the ratio, not
#: of it.
_DIFFERENCE_BEFORE = (
    "there was no difference, ", "with no difference in mortality, ", "the difference: ",
)  # fmt: skip
#: Ratios the reader does not read, whose names a difference before them does not cross;
#: short enough that, without the stop, the gap would reach across them (round 1 of #336).
_UNREAD_RATIOS = ("SMR", "SIR", "ratio of means", "ratios of means")
_NOT_PLAIN_P = (
    "after Bonferroni adjustment, ", "one-sided, ", "with P values adjusted for multiple testing, ",
)  # fmt: skip


@st.composite
def _planted_intervals(draw: st.DrawFn) -> tuple[str, list[tuple[Any, ...]]]:
    """Every way of writing an estimate and its interval: at the middle of its interval
    and away from it, with a P that agrees and one that does not, in a sentence that says
    the interval or the P is not the plain one, and adjusted. A P after a second interval,
    a P for interaction, and one in the next sentence; bounds joined by hyphens after a
    negative one, and bounds the wrong way round. Each with the place it is found at and
    what is said of it."""

    def words() -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))

    def thousandths(low: int, high: int) -> float:
        return draw(st.integers(low, high)) / 1000

    def shown(x: float) -> str:
        return f"{x:.2f}".replace("-", draw(st.sampled_from(("-", "\N{MINUS SIGN}"))))

    def p_of(z: float) -> tuple[str, str]:
        p = math.erfc(abs(z) / math.sqrt(2))
        if p < 0.001:
            return "<", "0.001"
        printed = f"{p:.3f}"
        return "=", draw(st.sampled_from((printed, printed.removeprefix("0"))))

    def sign() -> int:
        return draw(st.sampled_from((-1, 1)))

    def ratio(plan: str, level: str) -> tuple[float, float, float, tuple[str, str] | None]:
        """An estimate, its bounds and its P: a Wald interval on the log scale, one bound
        moved toward the estimate, or one whose P is far on the other side."""
        if plan == "level":
            # At 90%, a P between 0.05 and 0.10 beside an interval that excludes 1.
            h = thousandths(600, 1000)
            log_e = sign() * thousandths(1700, 1900) * h / _Z[level]
        elif plan in ("against", "adjusted", "quiet p"):
            h = thousandths(300, 1000)
            excludes = draw(st.booleans())
            far = h + thousandths(100, 600) if excludes else thousandths(0, int(h * 1000) - 100)
            log_e = sign() * far
            low, high = math.exp(log_e - h), math.exp(log_e + h)
            return math.exp(log_e), low, high, draw(st.sampled_from(_AGAINST[excludes]))
        else:
            h = thousandths(300, 1000)
            log_e = thousandths(-700, 1600)
        low, high = log_e - h, log_e + h
        if plan in ("lopsided", "quiet interval"):
            moved = thousandths(100, 300) * h
            low, high = draw(st.sampled_from(((log_e - moved, high), (low, log_e + moved))))
            return math.exp(log_e), math.exp(low), math.exp(high), None
        return math.exp(log_e), math.exp(low), math.exp(high), p_of(log_e / (h / _Z[level]))

    def difference(plan: str, level: str) -> tuple[float, float, float, tuple[str, str]]:
        """An estimate, its bounds and its P. At the middle, an interval that excludes 0
        and includes 1, so that a difference read against 1 is found."""
        if plan == "symmetric":
            e = thousandths(600, 900)
            h = thousandths(int((1 - e) * 1000) + 50, int(e * 1000) - 50)
            return e, e - h, e + h, p_of(e / (h / _Z[level]))
        h = thousandths(200, 2000)
        excludes = draw(st.booleans())
        far = h + thousandths(100, 1000) if excludes else thousandths(0, int(h * 1000) - 100)
        e = sign() * far
        return e, e - h, e + h, draw(st.sampled_from(_AGAINST[excludes]))

    plans: list[tuple[int, str]] = []
    for index, (kind, _form, level) in enumerate(_INTERVAL_FORMS):
        if kind == "difference":
            plans += [(index, plan) for plan in ("symmetric", "against", "quiet p", "outside")]
        else:
            first = "level" if level == "90" else "symmetric"
            plans += [
                (index, plan)
                for plan in (first, "lopsided", "against", "quiet interval", "quiet p", "adjusted",
                             "outside")
            ]  # fmt: skip
    plans += [(0, plan) for plan in ("next interval", "interaction", "next sentence")]
    plans += [(7, "hyphens"), (0, "reversed"), (0, "after difference"), (0, "unread ratio"),
              (0, "en dash"), (0, "glued ratio")]  # fmt: skip
    sentences: list[tuple[str, tuple[Any, ...] | None]] = []
    for index, plan in draw(st.permutations(plans)):
        kind, form, level = _INTERVAL_FORMS[index]
        if plan == "unread ratio":
            # A difference before a ratio this does not read is not read across its name
            # (round 2 of #300): nothing is found.
            e, low, high, _p = ratio("symmetric", "95")
            name = draw(st.sampled_from(_UNREAD_RATIOS))
            sentences.append((f"No difference, {name} {shown(e)} (95% CI "
                              f"{shown(low)} to {shown(high)}), P = 0.40", None))  # fmt: skip
            continue
        if plan == "glued ratio":
            # An en dash glued to a ratio's name is a dash, not a minus: a ratio is never
            # negative (#336).
            e, low, high, _p = ratio("symmetric", "95")
            e_, low_, high_ = shown(e), shown(low), shown(high)
            sentences.append((f"OR\N{EN DASH}{e_} (95% CI {low_} to {high_})",
                              (0, "ratio", e_, low_, high_, "95", None, "zero", False,
                               False)))  # fmt: skip
            continue
        if plan == "en dash":
            # A minus written as an en dash before the estimate (round 2 of #300).
            e, h = -thousandths(600, 900), thousandths(100, 500)
            e_, low_, high_ = f"\N{EN DASH}{abs(e):.2f}", shown(e - h), shown(e + h)
            sentences.append((f"The mean difference was {e_} (95% CI {low_} to {high_})",
                              (len("The "), "difference", e_, low_, high_, "95", None, None,
                               False, False)))  # fmt: skip
            continue
        if kind == "ratio":
            plain = plan in ("next interval", "outside", "after difference")
            e, low, high, p = ratio("symmetric" if plain else plan, level)
        else:
            e, low, high, p = difference(plan if plan != "hyphens" else "against", level)
        if plan == "outside":
            # A bound transposed past its estimate: the estimate beyond its upper bound.
            past = thousandths(150, 600)
            e = high * (1 + past) if kind == "ratio" else high + past + 0.05
            p = None
        e_, low_, high_ = shown(e), shown(low), shown(high)
        if plan == "hyphens":
            magnitude = abs(high) + 0.1
            low_, high_ = shown(-magnitude - abs(e)), f"{magnitude:.2f}"
            sentences.append((f"MD {shown(-abs(e))} (95% CI {low_}--{high_})", None))
            continue
        if plan == "reversed":
            sentences.append((form.format(e=e_, l=high_, u=low_), None))
            continue
        text = form.format(e=e_, l=low_, u=high_)
        lead = {
            "quiet interval": draw(st.sampled_from(_NOT_PLAIN_INTERVAL)),
            "quiet p": draw(st.sampled_from(_NOT_PLAIN_P)),
            "adjusted": "after adjustment for age and sex, ",
            # A ratio named after the word "difference" is a ratio.
            "after difference": draw(st.sampled_from(_DIFFERENCE_BEFORE)),
        }.get(plan, "")
        said = p
        if plan == "next interval":
            text += f" in men and {shown(e * 0.8)} (95% CI 0.80 to 1.50) in women, P = 0.40"
            said = None
        elif plan == "interaction":
            text += ", P = 0.40 for interaction"
            said = None
        elif plan == "next sentence":
            text += f". {words().capitalize()} P = 0.40"
            said = None
        elif p is not None:
            text += draw(st.sampled_from(_P_AFTER)).format(sign=p[0], p=p[1])
        shape = {"lopsided": "far", "quiet interval": None, "outside": None}.get(plan, "zero")
        against = plan in ("against", "adjusted")
        sentences.append(
            (lead + text, (len(lead), kind, e_, low_, high_, level, said,
                           shape if kind == "ratio" else None, against, plan == "outside"))
        )  # fmt: skip

    parts: list[str] = []
    expected: list[tuple[Any, ...]] = []
    for text, planted in sentences:
        opening = words().capitalize() + " "
        if planted is not None:
            at = len("".join(parts)) + len(opening) + planted[0]
            expected.append((at, *planted[1:]))
        parts.append(f"{opening}{text} {words()}.{draw(st.sampled_from((' ', chr(10))))}")
    return "".join(parts), expected


@holds(100, _planted_intervals())
def test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged(
    planted: tuple[str, list[tuple[Any, ...]]],
) -> None:
    """Each estimate with its interval is found where it stands, its numbers, level and P
    as they are printed, and nothing else is: not bounds whose signs or order cannot be
    read, and not a P that is another one's. A ratio printed from a Wald interval stands at
    the middle of its interval within its rounding, and one with a bound moved toward it
    does not. A P that agrees with its interval about the null is not found, one far on the
    other side of the level is, and neither is judged where the sentence says the interval
    or the P is not the plain one; "adjusted" alone says neither."""
    from manuscript_guard.stats.intervals import (
        ASYMMETRY,
        asymmetry,
        outside_interval,
        p_against,
        reported_intervals,
    )

    text, expected = planted
    found = reported_intervals(text)
    assert [(r.start, r.kind, r.estimate, r.low, r.high, r.level, r.p) for r in found] == [
        planted[:7] for planted in expected
    ], text
    for interval, (*_read, shape, against, outside) in zip(found, expected, strict=True):
        assert outside_interval(interval) is outside, (interval, text)
        share = asymmetry(interval)
        if shape is None:
            assert share is None, (interval, share)
        elif shape == "zero":
            assert share == 0.0, (interval, share)
        else:
            assert share is not None and share > ASYMMETRY, (interval, share)
        assert (p_against(interval) is not None) is against, (interval, text)


def _a_bound_is_read_at_its_printed_value(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import intervals

    def printed(number: str) -> tuple[float, float] | None:
        value = intervals._value(number)
        return None if value is None else (float(value), float(value))

    patch.setattr(intervals, "_box", printed)


def _a_difference_is_held_to_1(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import intervals

    patch.setattr(intervals, "NULL", {"ratio": 1, "difference": 1})


def _every_interval_is_taken_as_95(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import intervals

    patch.setattr(intervals, "alpha_of", lambda level: 0.05)


def _never(patch: pytest.MonkeyPatch, *names: str) -> None:
    from manuscript_guard.stats import intervals

    for name in names:
        patch.setattr(intervals, name, re.compile(r"(?!)"))


def _a_p_is_looked_for_past_the_next_interval(patch: pytest.MonkeyPatch) -> None:
    _never(patch, "_CI_WORD")


def _a_p_for_interaction_is_the_estimate_s(patch: pytest.MonkeyPatch) -> None:
    _never(patch, "_OTHER_P")


def _an_interval_s_p_is_looked_for_past_its_sentence(patch: pytest.MonkeyPatch) -> None:
    _never(patch, "_SENTENCE_END")


def _an_interval_that_is_not_the_plain_one_is_judged(patch: pytest.MonkeyPatch) -> None:
    _never(patch, "_INTERVAL_QUIET")


def _a_p_that_is_not_the_plain_one_is_judged_against_its_interval(
    patch: pytest.MonkeyPatch,
) -> None:
    _never(patch, "_P_QUIET")


def _adjusted_alone_quiets_an_interval(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import intervals

    for name in ("_INTERVAL_QUIET", "_P_QUIET"):
        pattern = getattr(intervals, name)
        patch.setattr(intervals, name, re.compile(pattern.pattern + r"|adjust\w*", pattern.flags))


def _an_estimate_outside_its_interval_is_not_said(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import intervals

    patch.setattr(intervals, "outside_interval", lambda interval: False)


def _a_name_s_words_run_across_another_name(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import intervals

    assert intervals._NOT_A_NAME in intervals._INTERVAL.pattern
    pattern = intervals._INTERVAL.pattern.replace(intervals._NOT_A_NAME, "")
    patch.setattr(intervals, "_INTERVAL", re.compile(pattern))


def _a_difference_runs_across_a_ratio_it_does_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import intervals

    without = rf"(?!{intervals._RATIO}|{intervals._DIFFERENCE})"
    pattern = intervals._INTERVAL.pattern.replace(intervals._NOT_A_NAME, without)
    assert pattern != intervals._INTERVAL.pattern
    patch.setattr(intervals, "_INTERVAL", re.compile(pattern))


def _an_en_dash_glued_to_a_ratio_is_its_minus(patch: pytest.MonkeyPatch) -> None:
    """The rule before #336: "OR–1.9" read as -1.9, outside its own interval."""
    from manuscript_guard.stats import intervals

    patch.setattr(intervals, "_glued", lambda _text, _at: False)


def _an_en_dash_before_an_estimate_is_no_minus(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import intervals

    dash = r"(?:(?<![\d.])\N{EN DASH}(?=\.?\d))?"
    assert dash in intervals._INTERVAL.pattern
    patch.setattr(intervals, "_INTERVAL", re.compile(intervals._INTERVAL.pattern.replace(dash, "")))


def _bounds_that_cannot_be_read_for_sure_are_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import intervals

    patch.setattr(intervals, "_unsure", lambda match: False)


def _an_interval_over_two_lines_is_not_read(patch: pytest.MonkeyPatch) -> None:
    """The line break a space may be is taken out of every place it may stand."""
    from manuscript_guard.stats import intervals

    wrap = "|" + chr(92) + "n(?![ " + chr(92) + "t]*" + chr(92) + "n)"
    assert wrap in intervals._INTERVAL.pattern
    pattern = intervals._INTERVAL.pattern.replace(wrap, "")
    patch.setattr(intervals, "_INTERVAL", re.compile(pattern))


# ---------------------------------------------------------------------- a table's shares


@holds(100, share_tables())
def test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator(
    drawn: tuple[str, list[tuple[Any, ...]]],
) -> None:
    """Item 19: each count and its share in a pipe table is found where it stands, with its
    denominator: its own, its column header's n, or none. A row whose label names a mean or
    a median is not read although it says %, nor one whose "%" is a unit, nor a table in a
    fenced listing, nor a share in a sentence; a characteristic's categories whose shares
    add up to 100 are read with nothing else to say so. A share is off where neither its
    denominator, nor its row's total, nor its categories' total gives it within half a unit
    of its last place, and uncertain where its row's label carries a footnote marker."""
    from manuscript_guard.stats.shares import off, table_shares
    from manuscript_guard.text.tables import markdown_tables

    text, expected = drawn
    found = [share for table in markdown_tables(text) for share in table_shares(table)]
    assert [
        (s.line, s.count, s.percent, s.over, s.uncertain is not None, off(s)) for s in found
    ] == expected, text


def _a_share_is_held_to_its_printed_value(patch: pytest.MonkeyPatch) -> None:
    """Only the share's own tolerance: what adds up to 100 keeps its slack (round 1 of
    #314)."""
    from decimal import Decimal
    from fractions import Fraction

    from manuscript_guard.stats import shares

    def exact(count: int, over: int, percent: str) -> bool:
        return over > 0 and Fraction(100 * count, over) == Fraction(Decimal(percent))

    patch.setattr(shares, "_fits", exact)


def _a_unit_percent_says_shares(patch: pytest.MonkeyPatch) -> None:
    """Both halves: a "%" in a label says shares, and a unit no longer bars its row."""
    from manuscript_guard.stats import shares

    patch.setattr(shares, "_SAYS_SHARES", re.compile("%"))


def _categories_are_held_to_their_column_alone(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import shares

    summed = shares._summed

    def without_totals(rows: list) -> dict:
        return {where: (None, members, whole)
                for where, (_total, members, whole) in summed(rows).items()}  # fmt: skip

    patch.setattr(shares, "_summed", without_totals)


def _a_label_row_with_its_p_value_is_a_header(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import shares

    patch.setattr(shares, "_P_ONLY", re.compile(r"\s*"))


def _a_run_of_categories_takes_in_the_row_after_them(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import shares

    def whole(matches: list) -> int:
        return len(matches) if shares._about_100([m.group("percent") for m in matches]) else 0

    patch.setattr(shares, "_categories", whole)


def _a_label_naming_a_mean_is_read_as_shares(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import shares

    patch.setattr(shares, "_barred", lambda row, column: False)


def _shares_adding_up_to_100_say_nothing(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import shares

    patch.setattr(shares, "_summed", lambda rows: {})


def _a_row_is_never_read_as_shares_of_its_total(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import shares

    patch.setattr(shares, "_row_total", lambda matches: None)


def _a_footnote_marker_is_not_seen(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import shares

    patch.setattr(shares, "_NOTE", re.compile(r"(?!)"))


def _a_header_names_no_denominator(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import shares

    patch.setattr(shares, "_N", re.compile(r"(?!)(?P<n>)"))


def _a_count_with_its_own_denominator_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import shares

    pattern = shares._SHARE.pattern.replace("(?P<over>", "(?P<over>(?!)")
    assert pattern != shares._SHARE.pattern
    patch.setattr(shares, "_SHARE", re.compile(pattern))


def _a_table_in_a_fenced_listing_is_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text import tables

    patch.setattr(tables, "mask", lambda text: text)


# ------------------------------------------------------- a table's means of whole numbers


@holds(100, mean_tables())
def test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n(
    drawn: tuple[str, list[str], list[tuple[Any, ...]]],
) -> None:
    """Item 19.5: in a row whose label holds one the auditor names, at word edges and in any
    case, each mean is found with its column header's n, alone, with its SD in brackets or
    after a plus-minus sign, negative with a minus sign. It can be the mean of n whole
    numbers where some total over n is within half a unit of its last place, either end,
    two places for 2.50; it is not assessable where every mean printed to its places is
    possible for n, for 10 to the power of the places or more and for 80 and 96 at two; and
    it is uncertain where its row's label carries a footnote marker or an n. A row
    not named, a table whose header names no n, a fenced listing and a sentence are not
    read."""
    from manuscript_guard.stats.granularity import possible, table_means
    from manuscript_guard.text.tables import markdown_tables

    text, labels, expected = drawn
    found = [m for table in markdown_tables(text) for m in table_means(table, tuple(labels))]
    assert [
        (m.line, m.mean, m.n, possible(m.mean, m.n), m.uncertain is not None) for m in found
    ] == expected, text


def _a_mean_is_held_to_exactly_its_printed_value(patch: pytest.MonkeyPatch) -> None:
    from fractions import Fraction

    from manuscript_guard.stats import granularity

    def exact(mean: str, count: int) -> tuple[int, int]:
        total = Fraction(granularity.Decimal(mean)) * count
        return (total.numerator, total.numerator) if total.denominator == 1 else (1, 0)

    patch.setattr(granularity, "_totals", exact)


def _a_mean_half_a_unit_from_a_total_is_not_one(patch: pytest.MonkeyPatch) -> None:
    """Neither end of the half unit: a mean rounded either way from a tie is not taken."""
    import math
    from fractions import Fraction

    from manuscript_guard.stats import granularity

    def open_ended(mean: str, count: int) -> tuple[int, int]:
        printed = Fraction(granularity.Decimal(mean))
        half = Fraction(1, 2 * 10 ** granularity.places(mean))
        return math.floor((printed - half) * count) + 1, math.ceil((printed + half) * count) - 1

    patch.setattr(granularity, "_totals", open_ended)


def _a_nought_at_the_end_is_no_place(patch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    from manuscript_guard.stats import granularity

    patch.setattr(granularity, "places",
                  lambda mean: max(0, -Decimal(mean).normalize().as_tuple().exponent))  # fmt: skip


def _every_mean_is_assessable(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import granularity

    patch.setattr(granularity, "assessable", lambda mean, n, items=1: True)


def _a_mean_is_assessable_below_the_power_of_its_places(patch: pytest.MonkeyPatch) -> None:
    """The rule before round 1 of #331: 80 and 96 at two places read as assessable."""
    from manuscript_guard.stats import granularity

    patch.setattr(granularity, "_some_mean_is_none", lambda count, places_: count < 10**places_)


def _a_named_label_is_matched_in_its_case(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import granularity

    patch.setattr(granularity, "names", lambda label, text: label in text)


def _a_named_label_is_matched_inside_a_word(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import granularity

    patch.setattr(granularity, "names", lambda label, text: label.lower() in text.lower())


def _a_mean_s_footnote_marker_is_not_seen(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import granularity

    patch.setattr(granularity, "_NOTE", re.compile(r"(?!)"))


def _a_mean_with_a_minus_sign_or_a_plus_minus_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.stats import granularity

    patch.setattr(granularity, "_MEAN", re.compile(
        r"(?P<mean>-?\d+(?:\.\d+)?)(?:\s*[(\[]\s*\d+(?:\.\d+)?\s*[)\]])?"
    ))  # fmt: skip


def _a_named_row_s_own_n_is_taken(patch: pytest.MonkeyPatch) -> None:
    """A named row's own n is taken for its means: "Pain score (n = 25)" is held to 25."""
    from dataclasses import replace

    from manuscript_guard.stats import granularity

    read = granularity.table_means

    def own(table: Any, labels: tuple[str, ...]) -> list[Any]:
        found = []
        for mean in read(table, labels):
            named = granularity._N.search(mean.label)
            found.append(replace(mean, n=granularity._whole(named.group("n"))) if named else mean)
        return found

    patch.setattr(granularity, "table_means", own)


def _a_named_row_is_never_read_for_its_n(patch: pytest.MonkeyPatch) -> None:
    """The cells of a row a label names are never read for the n they name, so a header
    whose first cell is the scale's name gives none (round 1 of #331)."""
    from dataclasses import replace

    from manuscript_guard.stats import granularity

    read = granularity.table_means

    def blind(table: Any, labels: tuple[str, ...]) -> list[Any]:
        rows = tuple(
            (row[0], *(replace(cell, text=granularity._N.sub("", cell.text)) for cell in row[1:]))
            if row and any(granularity.names(wanted, row[0].text) for wanted in labels)
            else row
            for row in table
        )
        return read(rows, labels)

    patch.setattr(granularity, "table_means", blind)


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


def _under_a_title(text: str, title: str = _TITLE) -> str:
    """The paper with its title as a heading over it, every other heading one level down."""
    lowered = re.sub(r"(?m)^(#+) ", lambda found: "#" + found.group(1) + " ", text)
    return title + lowered


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


#: A heading that holds "methods" and stands where the Methods could, without being named as
#: them: read after a heading that is.
_OTHER_METHODS = ("Limitations of existing methods", "Why earlier methods fall short",
                  "A comparison of methods")  # fmt: skip


@st.composite
def _papers_with_other_methods(draw) -> list[tuple[str, str]]:
    """Every name of the Methods with every heading that only holds the word standing before
    it, at its level, with words drawn for the two."""
    filler = " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))
    return [
        (f"# Introduction\n\n{filler}.\n\n# {other}\n\nBasil {filler}.\n\n# {methods}\n\n"
         f"Coriander {filler}.\n\n# Results\n\n{filler}.\n", methods)  # fmt: skip
        for methods in _THE_METHODS
        for other in _OTHER_METHODS
    ]


@holds(30, _papers_with_other_methods())
def test_the_methods_named_as_such_are_read_before_a_heading_that_only_holds_the_word(
    papers: list[tuple[str, str]],
) -> None:
    """Round 3 of #246: G9 reads the first heading `methods_sections` gives, and a heading
    read as the Methods by its name comes first, wherever "Limitations of existing methods"
    stands. Only a corruption case held the order."""
    for text, _methods in papers:
        read = methods_gate.methods_in(text)
        assert read is not None and "Coriander" in read and "Basil" not in read, (text, read)


@holds(40, supplements())
def test_a_supplement_s_methods_are_the_methods_to_each_gate_that_reads_them(
    drawn: tuple[str, list[tuple[int, bool, bool]]],
) -> None:
    """G9 read the main text's Methods alone, and G2 and G15 knew no supplement's name for
    them: a parameter the supplement's Methods stated was reported absent, a threshold typed
    under "eMethods 1" was a number nothing classified, and a model's kind typed there was
    never read. Each section of a file of the supplement is the Methods to each gate exactly
    where it should be: G9 reads every section whose heading holds "methods" and stands
    under no Results, and each one under it that names a method, each once; G2's threshold
    holds and G15 reads a model named only under a supplement's name of the Methods, or a
    name of a method under one, under no Results. A table under "Supplementary methods" is
    none of theirs (round 1 of #395)."""
    text, sections = drawn
    read = methods_gate.supplement_methods_in(text) or ""
    assert read.count("Coriander") == sum(g9 for _at, g9, _held in sections), (text, read)
    assert "Basil" not in read, (text, read)
    numbers = READINGS["numbers"]()({"text": text})
    held = [atom["rule"] == "significance-threshold" for atom in numbers if atom["text"] == "0.05"]
    assert held == [held for _at, _g9, held in sections], text
    starts = [at for at, _g9, _held in sections]
    named = [bisect.bisect_right(starts, start) - 1 for start, _end, _kind in
             models_gate.named_in_methods(text)]  # fmt: skip
    assert named == [index for index, (_at, _g9, held) in enumerate(sections) if held], text


# ------------------------------------------- a number a summary gives and the paper does not

#: What a paper calls its Results, and what it may call a section that is not them.
_THE_RESULTS = (
    "Results", "3. Results", "**3. Results**", "III. Results", "Results and discussion",
    "Findings", "Results {#sec-results}",
)  # fmt: skip
_NO_RESULTS = ("Comparison with earlier results", "Outcomes")
#: What a paper calls a conclusion, the Lancet's "Summary" at the end of it among them.
_CONCLUSIONS = (
    "Conclusions", "Conclusion", "6. Conclusions", "Concluding remarks",
    "Conclusions and relevance", "Summary and conclusions", "Summary",
)  # fmt: skip
#: A paper's title as a heading over the whole paper, holding the word for the Results.
_RESULTS_TITLE = "# Results of a survey of reports\n\n"


@st.composite
def _papers_with_summaries(draw: st.DrawFn) -> list[tuple[str, str | None, set[str]]]:
    """A paper for each way of writing the Results against each of the abstract, with the
    keys each of them should leave unreported. A key given in the abstract alone (`a`), with
    the Results (`b`), the Methods (`m`) or the Discussion (`d`); in a conclusion under the
    Discussion alone (`c`) or with the Results (`e`); and in a "Summary" under the Results
    (`s`). Every way of writing a conclusion, an abstract structured with headings of its
    own and not, each title a profile may give the abstract, and both layouts, with and
    without the paper's title over it, are in every example."""

    def words() -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))

    conclusions = draw(st.permutations(_CONCLUSIONS))
    papers = []
    for row, results in enumerate((*_THE_RESULTS, *_NO_RESULTS)):
        for column, abstract in enumerate(_THE_ABSTRACT):
            conclusion = conclusions[(row + column) % len(conclusions)]
            structured = draw(st.booleans()) != bool(column % 2)
            given = "{{results.a}} {{results.d}}"
            opening = f"\n\n## Results\n\n{given} " if structured else f"\n\n{given} "
            # A Background and a Methods of the abstract's own, each giving a key there alone
            # (`g`, `t`): the abstract's Methods are not the paper's (round 1 of #272). Not
            # under a "Summary": where no profile names it, it is taken for a title over the
            # paper, which DESIGN.md has among its Known gaps, and the text is drawn once for
            # every title a profile may give the abstract, a "Summary" named or not.
            children = structured and abstract != "Summary"
            if children:
                opening = (f"\n\n## Background\n\n{words()} {{{{results.g}}}}.\n\n## Methods\n\n"
                           f"{words()} {{{{results.t}}}}.{opening}")  # fmt: skip
            text = (
                f"# {abstract}{opening}{words()} {{{{results.b}}}} {{{{results.m}}}}.\n\n"
                f"# Introduction\n\n{words()}.\n\n"
                f"# Methods\n\n{words()} {{{{results.m}}}} {words()}.\n\n"
                f"# {results}\n\n{words()} {{{{results.b}}}} {{{{results.e}}}}.\n\n"
                f"## Summary\n\n{words()} {{{{results.s}}}}.\n\n"
                f"# Discussion\n\n{words()} {{{{results.d}}}}.\n\n"
                f"## {conclusion}\n\n{words()} {{{{results.c}}}} {{{{results.e}}}}.\n"
            )
            reports = results in _THE_RESULTS
            for named in _ABSTRACT_TITLES:
                summary = abstract in _THE_ABSTRACT[:4] or abstract == named
                unreported = {"c"} | (set() if reports else {"e", "s"})
                if summary:
                    unreported |= {"a", "d"} | (set() if reports else {"b"})
                    unreported |= {"g", "t"} if children else set()
                for paper in (text, _under_a_title(text, _RESULTS_TITLE)):
                    papers.append((paper, named, unreported))
    return papers


@holds(20, _papers_with_summaries())
def test_a_number_a_summary_gives_is_found_unreported_whatever_the_headings_are_called(
    papers: list[tuple[str, str | None, set[str]]],
) -> None:
    """A key the Abstract or a conclusion binds, and the Methods and the Results do
    not, is left unreported, and no other: whatever the parts are called, numbered or not,
    an abstract with a "Results" of its own included, and a "Summary" under the Results not
    taken for one, with the paper's title over it all or not."""
    for text, named, unreported in papers:
        given, reported = reported_gate.Walk(named).read(text)
        found = {one.key for one in given if one.key not in reported}
        assert found == unreported, (text, named)
        # And as two files of one paper, the second opening inside the Results the first
        # leaves open: the headings are carried from one file into the next, and what a
        # section of the first was is not taken by one of the second (round 1 of #272).
        cut = text.index("{{results.b}} {{results.e}}")
        walk = reported_gate.Walk(named)
        first, second = walk.read(text[:cut]), walk.read(text[cut:])
        reported = first[1] | second[1]
        found = {one.key for one in first[0] + second[0] if one.key not in reported}
        assert found == unreported, (text[:cut], text[cut:], named)


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


# ---------------------------------------------------------------- a dictionary's release typed

#: Coding dictionaries as the analysis declares them, each with the ways a sentence names
#: it before its release.
_DICTIONARIES = {
    "meddra": ("26.1", ("MedDRA version ", "MedDRA ", "the medDRA, release ")),
    "whodrug": ("Global B3 March 2025", ("WHODrug ", "the WHODrug dictionary, ")),
    "icd_10": ("2019", ("ICD-10 ", "ICD 10 version ")),
    "atc": ("2025", ("the ATC index of ", "ATC/DDD ")),
}


@st.composite
def _typed_releases(draw: st.DrawFn) -> tuple[str, list[tuple[Value, ...]], list[tuple[int, str]]]:
    """Each dictionary's release typed with its name before it, every way it is named,
    and typed with no name before it, with the name inside a longer word ("matched" holds
    "atc"), and with the name too far before it; a sentence to a line, in an order drawn
    each time, with where each is found."""
    declared = [
        Value(key=f"dictionary.{name}", value=release, display=release, origin="results",
              label=True, role="dictionary")
        for name, (release, _named) in _DICTIONARIES.items()
    ]  # fmt: skip

    def words(low: int = 1, high: int = 4) -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=low, max_size=high)))

    plans = []
    for name, (release, named) in _DICTIONARIES.items():
        plans += [(name, release, way, True) for way in named]
        # Round 1 of #287: a release of digits typed with a "v" before it, "MedDRA v26.1".
        if release[0].isdigit():
            plans.append((name, draw(st.sampled_from("vV")) + release, named[0], True))
            # Not with the "v" the end of a word, "MedDRA Rev26.1" (round 1 of #351).
            word = draw(st.sampled_from(("Re", "x", "Ser")))
            plans.append((name, word + draw(st.sampled_from("vV")) + release, named[0], False))
        plans += [
            (name, release, "", False),
            (name, release, "m" + name + "ed ", False),
            (name, release, named[0] + words(25, 25) + " ", False),
        ]
    parts: list[str] = []
    expected: list[tuple[int, str]] = []
    for name, release, before, found in draw(st.permutations(plans)):
        parts.append(words().capitalize() + " " + before)
        if found:
            expected.append((len("".join(parts)), name))
        parts.append(f"{release} {words()}.{chr(10)}")
    return "".join(parts), declared, expected


@holds(150, _typed_releases())
def test_a_dictionary_release_is_found_typed_where_its_name_stands_before_it(
    planted: tuple[str, list[Value], list[tuple[int, str]]],
) -> None:
    """A declared dictionary's release is found typed where the dictionary is named within
    a few words before it on its line, every way it is named. Not where nothing names it,
    where its name is only part of a longer word, or where the name is far before it."""
    text, declared, expected = planted
    found = [
        (start, value.key.removeprefix("dictionary."))
        for start, _end, value in numbers_gate.typed_releases(text, declared)
    ]
    assert found == expected, text


def _a_release_is_typed_wherever_it_stands(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(numbers_gate, "_named_in", lambda words, name: True)


def _a_dictionary_is_named_inside_a_longer_word(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(
        numbers_gate, "_named_in",
        lambda words, name: name in re.sub(r"[^a-z0-9]+", "_", words.lower()),
    )  # fmt: skip


def _releases_read_as(patch: pytest.MonkeyPatch, before: str) -> None:
    """`typed_releases` with `before` in place of what may stand before a release."""

    def read(text: str, dictionaries: list[Value]) -> list:
        found = []
        for value in dictionaries:
            name = value.key.removeprefix("dictionary.")
            pattern = re.compile(before + re.escape(value.display) + r"(?!\w|\.\d)")
            for match in pattern.finditer(text):
                line = text.rfind("\n", 0, match.start()) + 1
                words = text[max(line, match.start() - numbers_gate.NAMED_WITHIN) : match.start()]
                if numbers_gate._named_in(words, name):
                    found.append((match.start(), match.end(), value))
        return sorted(found, key=lambda place: place[0])

    patch.setattr(numbers_gate, "typed_releases", read)


def _a_release_with_a_v_before_it_is_not_read(patch: pytest.MonkeyPatch) -> None:
    _releases_read_as(patch, r"(?<![\w.])")


def _a_v_ending_a_word_is_taken_for_one_before_a_release(patch: pytest.MonkeyPatch) -> None:
    # The real rule, and a "v" that ends a word as well: they differ on "Rev26.1" alone.
    _releases_read_as(patch, r"(?:(?<![\w.])(?:[vV](?=\d))?|(?<=\w)[vV](?=\d))")


def _a_dictionary_is_named_anywhere_before_on_its_line(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(numbers_gate, "NAMED_WITHIN", 10**6)


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
    claims, open_ = methods_gate._anchored_in(methods_gate._Read(Path("main.md"), text))
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


# ------------------------------------------------------------------- a reply to a reviewer

#: Bindings whose keys hold digits, each of the two kinds a reply may use.
_REPLY_BINDINGS = ("{{results.n_2019}}", "{{lit.who.2019.count}}", "{{results.ror_95.low}}")


@st.composite
def _planted_replies(draw: st.DrawFn) -> tuple[str, str]:
    """A reply, and the same with a binding of every kind put in at places drawn, each a
    paragraph of its own. Put inside a sentence, a binding changes what the numbers beside it
    are, as it does in the paper: "95% {{results.n}} CI" is no convention."""
    text = draw(texts(NOTATED))
    pieces = text.split("\n\n")
    for binding in _REPLY_BINDINGS:
        # Never before the first piece, which may be the front matter.
        pieces.insert(draw(st.integers(1, len(pieces))), binding)
    return text, "\n\n".join(pieces)


@holds(200, _planted_replies())
def test_a_binding_in_a_reply_is_never_read_as_a_number(drawn: tuple[str, str]) -> None:
    """Whatever a reply says, a binding put into it adds no unbound number: the letter
    fills it in, as the paper does."""
    from collections import Counter

    from manuscript_guard.classify import Classifier
    from manuscript_guard.gates.numbers import reply_numbers

    text, planted = drawn
    classifier = Classifier.load([], [])

    def loose(written: str) -> Counter[str]:
        said = reply_numbers(written, Path("round-1.yaml"), "w", classifier, {})
        return Counter(f.context for f in said.findings if f.code == "reply-unbound-number")

    assert sum(loose(planted).values()) == sum(loose(text).values()), planted


@st.composite
def _wrapped_sentences(draw: st.DrawFn) -> tuple[str, str]:
    """A sentence, and a text that holds it hard-wrapped, with a word in emphasis and in
    code, before drawn words: after them it could stand in a comment they left open, where
    the paper does not print it."""
    words = draw(st.lists(st.sampled_from(FILLER), min_size=4, max_size=12))
    marked = list(words)
    at = draw(st.integers(0, len(words) - 1))
    marked[at] = draw(st.sampled_from(("*{}*", "**{}**", "`{}`"))).format(marked[at])
    gaps = [draw(st.sampled_from((" ", " ", "\n", "  ", " \n"))) for _ in marked[1:]]
    # A line break and a doubled space in every example, wherever else the draw put them.
    gaps[0], gaps[-1] = "\n", "  "
    wrapped = marked[0] + "".join(gap + word for gap, word in zip(gaps, marked[1:], strict=True))
    around = draw(texts())
    return " ".join(words) + ".", f"{wrapped}.\n\n{around}"


@holds(200, _wrapped_sentences())
def test_a_quote_is_found_however_its_lines_are_wrapped(drawn: tuple[str, str]) -> None:
    """A response quotes the sentence, not its Markdown: a quote of a sentence the paper
    prints is found in it, wrapped across lines and with a word marked, or not."""
    from manuscript_guard.gates.revision import as_quoted

    sentence, text = drawn
    assert as_quoted(sentence) in as_quoted(text), (sentence, text)


# ------------------------------------------------------- a quotation and the work it cites

_OPEN, _CLOSE = "\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}"
#: Each kind of sentence with a quotation, written with `{q}` for the quotation, `{k}` for
#: its citation key and `{o}` `{c}` for curly marks, with whether G7 looks for the
#: quotation: in straight or curly marks, across a line break, of two sentences, with two
#: works cited or a narrative one, and not where it is short, where the citation is in the
#: next sentence, or in a comment.
_QUOTATION_KINDS = (
    ('Reports said "{q}" [@{k}].', True, 1),
    ("Reports said {o}{q}{c} [@{k}].", True, 1),
    ("Reports said {o}{q}\nand more words here{c} [@{k}].", True, 1),
    ("{o}It was low. {q}.{c} [@{k}]", True, 1),
    ("Reports said {o}{q}{c} [@{k}; @{k}x].", True, 2),
    ("As @{k} wrote, {o}{q}{c}.", True, 1),
    ('Reports said "too short" [@{k}].', False, 1),
    ('Reports said "{q}". Later work agreed [@{k}].', False, 1),
    ('Reports said <!-- "{q}" [@{k}] -->.', False, 1),
    # Round 1 of #282: words left out inside the marks are part of what is quoted, and a key
    # may hold a colon.
    ("Reports said {o}{q} [...] and more words here{c} [@{k}].", True, 1),
    ('Reports said "{q}" [@{k}:2].', True, 1),
)


@st.composite
def _planted_quotations(draw: st.DrawFn) -> tuple[str, list[tuple[int, str, tuple[str, ...]]]]:
    """A paragraph of filler sentences around each kind of quotation, in an order drawn each
    time, with the quotations G7 should look for, by the paragraph's line."""
    paragraphs: list[str] = []
    found: list[tuple[int, str, tuple[str, ...]]] = []
    line = 1
    for index, (kind, looked, keys) in enumerate(draw(st.permutations(_QUOTATION_KINDS))):
        words = draw(st.lists(st.sampled_from(FILLER), min_size=4, max_size=8))
        quote = " ".join(words)
        key = f"source{index}"
        before = " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))
        sentence = kind.replace("{q}", quote).replace("{k}", key)
        sentence = sentence.replace("{o}", _OPEN).replace("{c}", _CLOSE)
        paragraph = f"{before.capitalize()}. {sentence}"
        if looked:
            written = quote + (" and more words here" if "and more" in kind else "")
            if "[...]" in kind:
                written = f"{quote} [...] and more words here"
            if kind.startswith("{o}It was low."):
                written = f"It was low. {quote}."
            cited = (key, f"{key}x")[:keys] if ":2]" not in kind else (f"{key}:2",)
            found.append((line, written, cited))
        paragraphs.append(paragraph)
        line += paragraph.count("\n") + 2
    return "\n\n".join(paragraphs), found


@holds(150, _planted_quotations())
def test_a_quotation_is_found_with_the_works_its_sentences_cite_and_no_other(
    planted: tuple[str, list[tuple[int, str, tuple[str, ...]]]],
) -> None:
    """A quotation of four words or more, in straight or curly marks, is taken with
    the works cited in the sentences it spans; not a short one, not one whose citation is in
    the next sentence, and not one in a comment."""
    text, expected = planted
    found = [(q.line, q.quote, q.keys) for q in quotations_gate.quotations_in(text)]
    assert found == expected, text


#: What a writer may put where words of a source are left out or marked, and is no word of it.
_ELISIONS = (" [...] ", " [. . .] ", " [\N{HORIZONTAL ELLIPSIS}] ", " \N{HORIZONTAL ELLIPSIS} ",
             " ... ")  # fmt: skip


@st.composite
def _quotes_of_a_source(draw: st.DrawFn) -> tuple[str, list[tuple[str, bool]]]:
    """A source of words that each stand once, and quotations of it: whole, with words left
    out each way a writer marks it, with a word marked [sic]; and, as none of it, the
    pieces in the other order, a piece the source does not hold, a word left out at a [sic],
    and a piece that opens inside a word. Every kind in each example, from places drawn
    each time."""
    words = [f"w{at:03d}" for at in range(draw(st.integers(14, 40)))]
    start = draw(st.integers(0, len(words) - 12))
    quoted = words[start : start + 10]
    cut, rest = draw(st.integers(2, 4)), draw(st.integers(6, 8))
    head, tail = " ".join(quoted[:cut]), " ".join(quoted[rest:])
    sic = draw(st.integers(1, 8))
    cases = [(" ".join(quoted), True)]
    cases += [(head + elision + tail, True) for elision in _ELISIONS]
    cases += [
        (" ".join(quoted[:sic]) + " [sic] " + " ".join(quoted[sic:]), True),
        (tail + draw(st.sampled_from(_ELISIONS)) + head, False),
        (head + draw(st.sampled_from(_ELISIONS)) + "nowhere " + tail, False),
        # Round 1 of its review: [sic] leaves nothing out, and a piece is words of its own.
        (" ".join(quoted[:sic]) + " [sic] " + " ".join(quoted[sic + 1 :]), False),
        (head + draw(st.sampled_from(_ELISIONS)) + tail[1:], False),
        # Round 2 of its review: one piece beside an elision at an end is words of its own,
        # and is found where the source holds it.
        (draw(st.sampled_from(_ELISIONS)).lstrip() + tail[1:], False),
        (draw(st.sampled_from(_ELISIONS)).lstrip() + tail, True),
    ]
    return " ".join(words), draw(st.permutations(cases))


@holds(100, _quotes_of_a_source())
def test_a_quotation_with_words_left_out_is_found_piece_by_piece(
    drawn: tuple[str, list[tuple[str, bool]]],
) -> None:
    """Round 1 of #282: a quotation with words left out, or one marked [sic], was looked for
    whole, and said not to be in its source. Each piece is the source's, in the order
    quoted, and a piece out of order or not in it is not."""
    source, cases = drawn
    for quote, there in cases:
        assert quotations_gate.quoted_in(source, quote) is there, (source, quote)


@holds(60, passage_files())
def test_a_passage_belongs_to_its_sentence_by_its_words_and_its_work(
    drawn: tuple[dict[str, Any], list[tuple[int, str]]],
) -> None:
    """Basile, 2026-10-20: an entry of `passages.yaml` belongs to the sentences whose words it
    gives and which cite its work, however it is typed and wherever the sentence stands. One
    with a word changed or added belongs to none, and is said to be of a sentence reworded;
    one naming a work the sentence does not cite belongs to none, and is said to be of a
    sentence that no longer cites it (`literature/passages.py`)."""
    given, written = drawn
    found = READINGS["passages"]()(given)
    for (belongs, stale), (n, how) in zip(found, written, strict=True):
        if how in FOLDED:
            assert belongs, (how, given)
            assert all(f"Claim {n}:" in text for _line, text in belongs), (how, belongs)
            assert stale is None, (how, stale)
        else:
            assert belongs == [], (how, belongs)
            assert stale == ("uncited" if how == "work not cited" else "changed"), (how, stale)


@holds(60, credited_plans())
def test_a_study_is_credited_by_a_citation_of_the_plan_and_by_nothing_else(
    drawn: tuple[dict[str, str], dict[str, str]],
) -> None:
    """Basile, 2026-10-21: a method taken from a study of `design/methods_review.yaml` is
    cited in the plan. A citation in a group, with others or a locator, or a narrative one,
    credits the study; its key in a comment, inside a longer key or in an address does not
    (`gates/methods_review.py`)."""
    given, written = drawn
    credited = set(READINGS["plan citations"]()(given))
    for key, how in written.items():
        assert (key in credited) is (how in CREDITING), (key, how, given)


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
def _planted_pointers(draw: st.DrawFn) -> tuple[str, str, set[tuple[str, bool, int]], int]:
    """A main text and a supplement placing tables and figures, and citing each of the main
    text's in order; and pointers planted at what neither carries, one of each kind in
    every example: past the main text's tables, in a list, past the supplement's tables in
    the supplement's own words, past the main text's figures, and one past the supplement's
    figures. The main text's tables and the supplement's are placed by binding only, so they
    are counted; the main text's figures include one placed by hand, so they are not, and a
    pointer past them is not said. The supplement places none to two figures by binding,
    and one or two are sent as files, the fourth part, which paper.yaml declares: a pointer
    to the last of those passes, and one past it is said (round 2 of #256: no example held a
    count of figures). What the counted pointers point at is the third part."""

    def words() -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))

    counts = {
        (False, "table"): draw(st.integers(2, 3)),
        (False, "figure"): draw(st.integers(1, 2)),
        (True, "table"): draw(st.integers(1, 2)),
        (True, "figure"): draw(st.integers(0, 2)),
    }
    as_files = draw(st.integers(1, 2))
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
    last = counts[True, "figure"] + as_files
    for number in (last, last + 1):
        form = draw(st.sampled_from(_SUPPLEMENTARY))
        parts[False].append(f"{words().capitalize()} {form % ('Figure', number)}.\n")
    planted.add(("figure", True, last + 1))
    return "\n".join(parts[False]), "\n".join(parts[True]), planted, as_files


@holds(100, _planted_pointers())
def test_a_pointer_names_what_the_document_carries_or_is_said(
    planted: tuple[str, str, set[tuple[str, bool, int]], int],
) -> None:
    """A pointer to a table or a figure is held to the tables and figures each document
    places, whichever way it places them, and those paper.yaml says go as files: one
    pointing past them is said, a list read whole, and one that points at what is there
    passes, cited in the order it is placed."""
    import tempfile

    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.pointers import check_pointers

    main, supplement, expected, as_files = planted
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "paper.yaml").write_text(
            f"title: A paper\ndisplays:\n  supplementary_figures_as_files: {as_files}\n",
            encoding="utf-8",
        )
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


@holds(100, numbered_displays())
def test_a_ref_prints_the_number_its_display_has_or_is_said(
    drawn: tuple[dict[str, str], dict[tuple[str, int], str], set[tuple[str, str, int]]],
) -> None:
    """Each ref and num binding prints the number the document gives its table or figure:
    counted in the order the files print, which is not the order of their paths, and the
    supplement's apart from the main text's. G2 says of the pointers exactly what was
    planted, a ref to a key nothing places and a num after words that point at another kind
    or at the other document, and nothing of the rest, which cite each display in order."""
    files, prints, planted = drawn
    said = READINGS["pointers"]()({"files": files})
    printed = {(relative, start): shown for relative, start, shown in said["printed"]}
    assert {at: shown for at, shown in printed.items() if shown is not None} == prints, files
    assert sum(shown is None for shown in printed.values()) == 2, (files, printed)
    findings = said["report"]["findings"]
    found = {(f["code"], f["path"].split("manuscript/")[-1], f["line"]) for f in findings}
    assert found == planted, (files, findings)


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


# ------------------------------------------------------------------------- placeholders


@st.composite
def _planted_placeholders(draw: st.DrawFn) -> tuple[str, str]:
    """A text, and the same with a placeholder of every kind G6 reads, the words that are
    one only in the manuscript, and what looks like one and is prose, each put in at a
    place drawn. Every kind in every example."""
    text = draw(texts())
    pieces = text.split(" ")
    for planted in [written for written, _ in PLACEHOLDERS + LOWERED] + list(LOOKALIKES):
        pieces.insert(draw(st.integers(0, len(pieces))), planted)
    return text, " ".join(pieces)


@holds(200, _planted_placeholders())
def test_every_placeholder_is_found_and_nothing_that_looks_like_one(
    drawn: tuple[str, str],
) -> None:
    """Whatever the text, each placeholder put into it is found once, a word in lower case
    only in the manuscript, and nothing that only looks like one is."""
    from collections import Counter

    from manuscript_guard.gates.writing import artefacts_in, load_rules

    text, planted = drawn
    rules = load_rules()
    for manuscript, expected in ((True, PLACEHOLDERS + LOWERED), (False, PLACEHOLDERS)):

        def found(written: str, manuscript: bool = manuscript) -> Counter[str]:
            return Counter(
                match.group(0)
                for rule, match in artefacts_in(rules, written, manuscript=manuscript)
                if rule["id"].startswith("placeholder")
            )

        added = Counter(match for _typed, match in expected)
        assert found(planted) == found(text) + added, (manuscript, planted)
    # A slot that is a cited entry's whole field, `doi = {[DOI]}`, is read as the field is,
    # whole and with nothing around it (round 2 of #262).
    for written, match in PLACEHOLDERS:
        alone = [m.group(0) for rule, m in artefacts_in(rules, written, manuscript=False)
                 if rule["id"].startswith("placeholder")]  # fmt: skip
        assert alone == [match], (written, alone)


# ------------------------------------------------------- words to the reviewers, left in


@st.composite
def _planted_residue(draw: st.DrawFn) -> tuple[str, str]:
    """A text, and the same with every residue G6 reads and everything that reads like one
    and is prose, each put in at a place drawn. Every kind in every example."""
    text = draw(texts())
    pieces = text.split(" ")
    for planted in [written for written, _rule, _found in RESIDUE] + list(RESIDUE_LOOKALIKES):
        pieces.insert(draw(st.integers(0, len(pieces))), planted)
    return text, " ".join(pieces)


@holds(200, _planted_residue())
def test_every_residue_is_found_by_its_rule_and_nothing_that_reads_like_one(
    drawn: tuple[str, str],
) -> None:
    """Whatever the text, each residue put into it is found once, by its rule and with its
    words, a hard wrap read as a space; and nothing that only reads like one is: not a name,
    the contributions, the acknowledgements, a dossier, a retrotransposon, an invitation,
    nor a phrase that a blank line cuts in two."""
    from collections import Counter

    from manuscript_guard.gates.writing import load_rules, residue_in

    text, planted = drawn
    rules = load_rules()

    def found(written: str) -> Counter[tuple[str, str]]:
        return Counter(
            (rule["id"], " ".join(match.group(0).split()))
            for rule, match in residue_in(rules, written)
        )

    added = Counter((rule, words) for _written, rule, words in RESIDUE)
    assert found(planted) == found(text) + added, planted


# ------------------------------------------------------------------------ an em dash typed

#: What G6 counts as an em dash, the character and three hyphens, spaced or not; and what it
#: does not: two hyphens, four, and a line of dashes, a rule or a table's.
_EM_DASHES = ("\N{EM DASH}", "---", " --- ", " \N{EM DASH} ")
_NO_EM_DASHES = ("--", " -- ", "----", "\n\n---\n\n", "\n\n|---|:---:|\n\n", "\n\n--- ---\n\n",
                 "\n\n+---+---+\n\n", " `---` ", "\n\n| a | --- |\n\n")  # fmt: skip


@st.composite
def _dashes_planted(draw: st.DrawFn) -> tuple[str, int]:
    """Words, with every way of writing an em dash and every dash that is none between
    them, in an order drawn each time; and how many em dashes that is."""

    def words() -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))

    pieces = [(dash, 1) for dash in _EM_DASHES] + [(dash, 0) for dash in _NO_EM_DASHES]
    text, count = words(), 0
    for piece, counted in draw(st.permutations(pieces)):
        text += piece + words()
        count += counted
    return text, count


@holds(100, _dashes_planted())
def test_an_em_dash_is_counted_however_it_is_typed(planted: tuple[str, int]) -> None:
    """Known gaps of #339: the em dash's rate counted the character only, and a manuscript
    that types three hyphens, which pandoc prints as one, showed none. Neither two hyphens,
    an en dash, nor a line of dashes is one."""
    from manuscript_guard.gates.writing import _hits, load_rules

    text, count = planted
    rule = next(rule for rule in load_rules().density if rule["id"] == "em-dash")
    assert len(_hits(rule, text)) == count, text


def _em_dash_rule(patch: pytest.MonkeyPatch, **changed) -> None:
    from dataclasses import replace

    from manuscript_guard.gates import writing

    rules = writing.load_rules()
    density = tuple({**rule, **changed} if rule["id"] == "em-dash" else rule
                    for rule in rules.density)  # fmt: skip
    patch.setattr(writing, "load_rules", lambda: replace(rules, density=density))


def _an_em_dash_typed_is_not_counted(patch: pytest.MonkeyPatch) -> None:
    _em_dash_rule(patch, pattern="\N{EM DASH}")


def _a_rule_or_a_table_s_dashes_are_em_dashes(patch: pytest.MonkeyPatch) -> None:
    _em_dash_rule(patch, exempt=[])


def _any_run_of_hyphens_is_an_em_dash(patch: pytest.MonkeyPatch) -> None:
    _em_dash_rule(patch, pattern="\N{EM DASH}|-{2,}")


# ------------------------------------------------------------------- a suggested edit


@st.composite
def _edit_words_planted(
    draw: st.DrawFn,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Every word of `EDIT_WORDS` and every gap of `EDIT_GAPS` at least once, in an order
    drawn each time, with some words drawn again so that a run of them stands twice."""
    words = [*EDIT_WORDS, *draw(st.lists(st.sampled_from(EDIT_WORDS), min_size=2, max_size=6))]
    words = list(draw(st.permutations(words)))
    gaps = [*EDIT_GAPS, *draw(st.lists(st.sampled_from(EDIT_GAPS), min_size=len(words),
                                         max_size=len(words)))]  # fmt: skip
    return words, list(draw(st.permutations(gaps)))[: len(words) - 1]


@holds(100, _edit_words_planted())
def test_an_edit_s_words_are_found_where_they_stand_typed_or_printed_and_nowhere_else(
    planted: tuple[list[tuple[str, str]], list[tuple[str, str]]],
) -> None:
    """`review --suggestions` places an edit where its words are found once, in the source
    as typed and in the document as pandoc printed it. Every run of up to three words is
    looked for, in both, and has to be found at each place that run stands and at no other:
    across a line break, beside a no-break space, typeset, and never inside a longer word."""
    from manuscript_guard.suggestions import found_in

    words, gaps = planted
    for side in (0, 1):
        text, starts, ends = "", [], []
        for index, word in enumerate(words):
            text += gaps[index - 1][side] if index else ""
            starts.append(len(text))
            text += word[side]
            ends.append(len(text))
        for length in (1, 2, 3):
            for first in range(len(words) - length + 1):
                run = [typed for typed, _printed in words[first : first + length]]
                expected = [
                    (starts[at], ends[at + length - 1])
                    for at in range(len(words) - length + 1)
                    if [typed for typed, _printed in words[at : at + length]] == run
                ]
                assert found_in(text, " ".join(run)) == expected, (" ".join(run), text)


def _an_edit_is_found_only_as_typed(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import suggestions

    patch.setattr(suggestions, "_TYPESET", ())


def _an_edit_is_found_inside_longer_words(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import suggestions

    real = suggestions.pattern_of
    edges = ("(?<![^\\W_])", "(?![^\\W_])")
    patch.setattr(suggestions, "pattern_of", lambda old: re.compile(
        real(old).pattern.replace(edges[0], "").replace(edges[1], "")
    ))  # fmt: skip


def _a_line_break_between_an_edit_s_words_is_no_space(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import suggestions

    patch.setattr(suggestions, "_SPACE", "[ \\t\\u00a0]+")


#: The kinds of stretch the merge refuses to rebuild from Word's text once edited: a link's
#: address, a hard line break and a comment are not in Word's text.
_NOT_MERGED = frozenset({"link", "lines", "comment"})


@holds(60, suggestion_paragraphs())
def test_a_suggestion_is_written_where_its_words_are_and_nothing_else_changes(
    paragraph: dict[str, Any],
) -> None:
    """`import` writes a suggestion accepted in Word into the source where its old words
    are (`suggestions.write_in`), then merges against that whatever else the author changed
    in the paragraph. Every run of one or two words of every stretch is written over in
    turn. In prose, in any emphasis, and beside a hard line break it is written, and only
    those words change, in the source and in what Word shows: a comment repeating them is
    not counted. Each value and citation prints where it did, moved along; the merge brings
    the paragraph back as written, and when the author also retyped a word between other
    values, it keeps the stretch the suggestion was written in, markup and all. Inside code,
    a link's text or a comment, or across a hard line break, it is not written: Word shows
    those without their markup, or the write would delete it."""
    from manuscript_guard.roundtrip import align, segments
    from manuscript_guard.suggestions import Words, write_in

    source, printed, words, tokens, renderings = laid_out(paragraph)
    runs = [
        words[at : at + length]
        for length in (1, 2)
        for at in range(len(words) - length + 1)
        if words[at][2] == words[at + length - 1][2]
    ]
    for count, run in enumerate(runs):
        new = WRITTEN_WORDS[count % len(WRITTEN_WORDS)]
        old = " ".join(word for word, *_rest in run)
        written = write_in(source, printed, tokens, [Words(old, new)])
        kind = run[0][1]
        if not STRETCHES[kind][2] or (kind == "lines" and len(run) > 1):
            assert isinstance(written, str), (old, source)
            continue
        assert not isinstance(written, str), (old, written, source)
        (start, _), (shown_start, _) = run[0][3], run[0][4]
        (_, end), (_, shown_end) = run[-1][3], run[-1][4]
        shown_new = " ".join(new.split())
        assert written.source == source[:start] + new + source[end:], (old, source)
        assert written.shown == printed[:shown_start] + shown_new + printed[shown_end:]
        assert [written.shown[a:b] for a, b in written.tokens] == renderings, (old, source)
        alone = align(written.bare, written.shown, written.shown, written.tokens)
        assert alone.rebuilt == written.bare, (old, source)
        # The author retypes a word between other values, in a stretch the merge can rebuild.
        here = run[0][5]
        refused = {word[5] for word in words if word[1] in _NOT_MERGED}
        other = next(
            (word for word in words
             if word[5] not in {here, *refused} and STRETCHES[word[1]][2]),
            None,
        )  # fmt: skip
        if other is None:
            continue
        at, to = other[4]
        if at >= shown_end:
            at, to = (at + len(shown_new) - (shown_end - shown_start),
                      to + len(shown_new) - (shown_end - shown_start))  # fmt: skip
        returned = written.shown[:at] + "zebra" + written.shown[to:]
        merged = align(written.bare, written.shown, returned, written.tokens).rebuilt
        assert merged is not None and "zebra" in merged, (old, other[0], source)
        assert segments(written.bare)[0][here].strip() in merged, (old, other[0], source)


def _a_value_is_not_moved_along_by_the_words_written_before_it(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import suggestions

    patch.setattr(suggestions, "_shifted", lambda spans, after, by: spans)


def _a_suggestion_is_written_inside_code_or_a_link(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import suggestions
    from manuscript_guard.roundtrip import _tokens

    def tokens_only(paragraph: str, start: int, end: int) -> str:
        found = any(token.at < end and start < token.to for token in _tokens(paragraph))
        return "inside a binding or a citation" if found else ""

    patch.setattr(suggestions, "_in_the_way", tokens_only)


def _a_suggestion_is_written_across_a_line_break(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import suggestions

    real = suggestions._in_the_way

    def over_breaks(paragraph: str, start: int, end: int) -> str:
        why = real(paragraph, start, end)
        return "" if "line break" in why else why

    patch.setattr(suggestions, "_in_the_way", over_breaks)


def _words_in_a_comment_are_counted(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import suggestions

    patch.setattr(suggestions, "_uncommented", lambda text: text)


def _emphasis_is_in_the_way_of_a_suggestion(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import suggestions
    from manuscript_guard.roundtrip import _emphasis

    real = suggestions._in_the_way

    def with_emphasis(paragraph: str, start: int, end: int) -> str:
        if any(a < end and start < b for a, b, _width in _emphasis(paragraph)):
            return "inside emphasis"
        return real(paragraph, start, end)

    patch.setattr(suggestions, "_in_the_way", with_emphasis)


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


# ------------------------------------------------------------ how strongly a sentence claims


def test_every_word_planted_as_a_claim_is_read_as_one_and_nothing_else_is() -> None:
    """The edits plant the words of `CLAIMED` and `UNCLAIMED`, which are written in the tests
    so that a rule broken in reading the data file does not draw its own inputs. Here they
    are held to the file: a word planted as a hedge is read as a hedge, and a look-alike or
    a filler word as nothing."""
    for kind, words in CLAIMED.items():
        for word in words:
            (sentence,) = claims_module.sentences(f"Here {word} stands.")
            read = word.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")
            assert sentence.words == ((read, kind),), (word, sentence)
    for word in (*UNCLAIMED, *FILLER):
        (sentence,) = claims_module.sentences(f"Here {word} stands.")
        assert sentence.words == (), (word, sentence)


@holds(30, claim_edits())
def test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands(
    drawn: tuple[str, str, list[tuple[str, int]]],
) -> None:
    """Each sentence an edit changed is compared with what it was, and only those. A hedge,
    a limit, a negation or a word of the ladder that came or went is told on the line the
    sentence stands on now, as a warning; a word made another of its class or rung, a
    look-alike, a sentence added, deleted, moved or rewrapped is told nothing. `reworded`
    tells the same, beside the facts, and passes."""
    before, after, expected = drawn
    found = claims_module.moved(before, after, MAIN)
    said = [(one.code, one.line, one.message) for one in found]
    assert [(one.code, one.line) for one in found] == expected, (before, after, said)
    assert all((one.gate, one.severity, one.path) == ("REWORDED", "warn", MAIN) for one in found)
    report = compare(before, after, MAIN)
    assert [(one.code, one.line) for one in report.findings] == expected, report.findings
    assert report.ok


# ------------------------------------------------------------------- the marked-up copy

#: What shows a change in a line of `readings.shown`.
_CHANGE_MARKS = ("[-", "{+", "~", "\N{PILCROW SIGN}", "style ", "row+ ", "row- ")


@holds(20, revisions())
def test_a_marked_up_copy_shows_each_change_where_it_was_made_and_reads_as_both_documents(
    drawn: tuple[dict[str, list], list[tuple[str, str]]],
) -> None:
    """With every change accepted the copy reads as the revision, and with every one
    rejected as the document sent, by a reading of its XML that owes nothing to the
    package's (`readings.read_plainly`): the words, how they look, the table's rows, the
    figure and the note. And each change shows where it was made, as what it is: a word
    reworded and a number re-run as the one deleted and the other inserted, a word set in
    italics as a change of formatting, a paragraph made a heading as one of style, a cell
    re-run in its cell, a row added as a row, a picture replaced as one paragraph deleted
    and another inserted, a list item deleted, a paragraph inserted, a paragraph moved as
    the same words deleted and inserted; and two paragraphs left alone show nothing."""
    given_, expected = drawn
    found = answer(READINGS["marked up"](), given_)
    assert "raised" not in found, found
    told = found["answer"]
    assert told["accepted"] == plain_of(given_["after"]), told
    assert told["rejected"] == plain_of(given_["before"]), told
    lines = told["shown"]
    for word, holds_ in expected:
        mine = [line for line in lines if word in line]
        assert mine, (word, lines)
        if holds_ == "unchanged":
            assert not [line for line in mine if any(m in line for m in _CHANGE_MARKS)], lines
        elif holds_ == "moved":
            gone = {line[len("\N{PILCROW SIGN}- [-") : -2] for line in lines
                    if line.startswith("\N{PILCROW SIGN}- [-") and line.endswith("-]")}
            came = {line[len("\N{PILCROW SIGN}+ {+") : -2] for line in lines
                    if line.startswith("\N{PILCROW SIGN}+ {+") and line.endswith("+}")}  # fmt: skip
            assert gone & came, lines
        else:
            assert any(holds_ in line for line in mine), (word, holds_, lines)


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


@holds(150, printings())
def test_a_value_an_earlier_output_printed_is_this_one_however_it_was_printed(
    cases: list[dict[str, Any]],
) -> None:
    """G8 holds a value read from an earlier output's text to this paper's. The same number
    is the same however the earlier output printed it, grouped, with a middle dot, a percent
    sign or a minus sign, or to other places; one a unit and a half of the coarser printing
    away is another, printed the same way. Each example holds every way."""
    found = READINGS["printed value"]()(cases)
    assert found == [[True, False]] * len(cases), [
        (case["kind"], case["printed"], case["moved"], case["display"], said)
        for case, said in zip(cases, found, strict=True)
        if said != [True, False]
    ]


# ------------------------------------------------------- a passage of an earlier paper

#: Words of the earlier paper and of nobody else: no filler word, none another reading
#: plants. A run of them stands once in the earlier paper, so nothing else can match it.
_EARLIER_WORDS = tuple(
    f"{start}{end}"
    for start in ("zor", "vel", "quan", "mib", "tesh", "dov", "ral", "kup", "nar", "gim", "sav",
                  "pel", "bru", "hok", "lom", "wib", "fen")  # fmt: skip
    for end in ("ade", "ine", "ost", "eth", "ond", "ix", "um", "orb", "ask", "elp", "aunt")
)  # fmt: skip
#: Words a page sets with a ligature.
_LIGATURED = ("zoruffa", "velifle", "quanflan", "mibaffe", "teshoffin")
#: Words the earlier paper has between the passages a manuscript repeats.
_ITS_OWN = ("plok", "trab", "snarp", "wugle", "blick", "fendo", "crisk")
#: What a manuscript holds of a passage, in the order drawn, each in every example.
_REPEATED_KINDS = (
    "recycled", "short", "quoted", "changed", "listing", "comment", "heading", "statement",
    "results statement", "like a statement", "reference list", "discussion",
)  # fmt: skip
#: The statements a journal asks for, as headings the Methods may hold.
_STATEMENT_HEADINGS = ("Ethics approval", "Funding", "Patient and public involvement")
#: Themes of the Results named as a statement is: the Results' own.
_RESULTS_STATEMENT_HEADINGS = ("Data sharing", "Consent", "Funding and conflicts of interest")
#: The part of the paper each kind's run stands in, where it stands in one.
_PART_PLANTED = {
    "statement": "statement", "results statement": "results", "discussion": "discussion",
}  # fmt: skip
#: Titles that open with a statement's words, or a supplement's prefix, and are the paper's
#: own matter.
_LIKE_A_STATEMENT = (
    "Funding sources of the included trials", "Data sharing in pharmacovigilance",
    "Ethical issues in prescribing", "Online discussion forums", "Online consent",
)  # fmt: skip
#: Words of its own the earlier paper has between two runs: more than a passage may differ
#: by, so that no two runs are one passage.
_APART_BY = recycling_gate.GAP + 2


@st.composite
def _planted_recycling(draw: st.DrawFn) -> tuple[str, str, set[tuple[int, ...]]]:
    """A manuscript of filler words and an earlier paper that share runs of words, one of
    each kind, and what the reading must report of them: by its first and last line, the
    words shared, how many of those are quoted, and the part of the paper it stands in.

    Repeated and reported: a run of twelve words or more, with a citation, a binding, a
    number and a mark of emphasis among its words and its lines wrapped; one in quotation
    marks, all quoted; one with a word changed, all but that word; one in a statement under
    the Methods, as a statement's; one under a theme of the Results named as a statement is,
    as the Results'; one under a title that opens with a statement's words, as no part's;
    one under the Discussion's principal findings, beside its interpretation and its
    conclusions, as the Discussion's. Not reported: a run of eleven, and runs in a listing, a
    comment, a heading and the reference list. The earlier paper sets each run in type: a
    word broken at the end of a line, a ligature, a reference's number."""
    pool = list(draw(st.permutations(_EARLIER_WORDS)))
    text, source, expected = "", "", set()

    def filler(least: int = 1, most: int = 4) -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=least, max_size=most)))

    for kind in draw(st.permutations(_REPEATED_KINDS)):
        size = {"recycled": draw(st.integers(12, 20)), "short": 11,
                "quoted": draw(st.integers(12, 16)), "changed": draw(st.integers(17, 22))
                }.get(kind, 14)  # fmt: skip
        run, pool = pool[:size], pool[size:]
        assert len(run) == size, "too few words of the earlier paper for every kind"
        if kind == "recycled":
            run[draw(st.integers(0, size - 1))] = draw(st.sampled_from(_LIGATURED))
        # The earlier paper: its own words, then the run as a page sets it.
        typeset = list(run)
        for letters, ligature in (
            ("ff", "\N{LATIN SMALL LIGATURE FF}"), ("fi", "\N{LATIN SMALL LIGATURE FI}"),
            ("fl", "\N{LATIN SMALL LIGATURE FL}"),
        ):  # fmt: skip
            typeset = [word.replace(letters, ligature) for word in typeset]
        broken = draw(st.integers(0, size - 1))
        cut = draw(st.integers(1, len(typeset[broken]) - 1))
        typeset[broken] = f"{typeset[broken][:cut]}-\n{typeset[broken][cut:]}"
        numbered = draw(st.integers(0, size - 2))
        typeset[numbered] += draw(st.sampled_from((".12", "12", "\N{SUPERSCRIPT TWO}", " [3]")))
        own = draw(st.lists(st.sampled_from(_ITS_OWN), min_size=_APART_BY, max_size=8))
        source += " ".join(own) + "\n" + " ".join(typeset) + "\n"
        # The manuscript.
        shown = list(run)
        if kind == "changed":
            shown[draw(st.integers(8, size - 9))] = draw(st.sampled_from(FILLER))
        if kind == "recycled":
            for inserted in ("[@other2019]", "{{results.cohort.n}}", "3.4"):
                shown.insert(draw(st.integers(1, len(shown) - 1)), inserted)
            marked = draw(st.integers(0, len(shown) - 1))
            if shown[marked][0].isalpha():
                shown[marked] = f"*{shown[marked]}*"
        joints = [draw(st.sampled_from((" ", " ", "\n"))) for _ in shown[1:]]
        written = shown[0] + "".join(
            joint + word for joint, word in zip(joints, shown[1:], strict=True)
        )
        if kind == "quoted":
            opened, closed = draw(st.sampled_from(
                (('"', '"'), ("\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}"))
            ))  # fmt: skip
            written = f"{opened}{written}{closed}"
        sentence = f"{filler().capitalize()} {written} {filler()}."
        # A part of the paper is closed by a heading that names none, so that the runs after
        # it stand under no part.
        if kind == "listing":
            paragraph = f"```\n{written}\n```"
        elif kind == "comment":
            paragraph = f"{filler().capitalize()} <!-- {written} --> {filler()}."
        elif kind == "heading":
            paragraph = "## " + " ".join(shown)
        elif kind == "statement":
            heading = draw(st.sampled_from(_STATEMENT_HEADINGS))
            paragraph = f"## Methods\n\n### {heading}\n\n{sentence}\n\n## Afterword"
        elif kind == "results statement":
            heading = draw(st.sampled_from(_RESULTS_STATEMENT_HEADINGS))
            paragraph = f"## Results\n\n### {heading}\n\n{sentence}\n\n## Afterword"
        elif kind == "like a statement":
            paragraph = f"## {draw(st.sampled_from(_LIKE_A_STATEMENT))}\n\n{sentence}"
        elif kind == "discussion":
            discussion = draw(st.sampled_from(("Supplementary discussion", "eDiscussion 2",
                                               "eDiscussion", "Discussion")))  # fmt: skip
            paragraph = (
                f"## {discussion}\n\n### Principal findings\n\n{sentence}\n\n### Interpretation\n\n"
                f"{filler().capitalize()}.\n\n### Conclusions\n\n{filler().capitalize()}.\n\n"
                "## Afterword"
            )
        elif kind == "reference list":
            paragraph = f"## References\n\n1. {written}\n\n## Afterword"
        else:
            paragraph = sentence
        if kind not in ("short", "listing", "comment", "heading", "reference list"):
            first = text.count("\n") + paragraph.count("\n", 0, paragraph.index(written)) + 1
            last = first + written.count("\n")
            shared = size - (kind == "changed")
            quoted = shared if kind == "quoted" else 0
            expected.add((first, last, shared, quoted, _PART_PLANTED.get(kind, "")))
        text += paragraph + "\n\n"
    return text, source, expected


@holds(150, _planted_recycling())
def test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set(
    planted: tuple[str, str, set[tuple[int, ...]]],
) -> None:
    """A run of twelve words the earlier paper has is one passage, however the page set it
    and whatever the manuscript put between its words that is no word; a word changed does
    not end it; a quotation is counted as quoted; a statement's is a statement's, under the
    Methods too, and a theme of the Results named as a statement is, or a title that opens
    with a statement's words, is not; the Discussion over its conclusions is the Discussion;
    and eleven words, a listing, a comment, a heading and the reference list are not
    reported."""
    text, source, expected = planted
    found = {
        (p.first_line, p.last_line, p.shared, p.quoted, p.kind)
        for p in recycling_gate.recycled_in(text, source, "earlier")
    }
    assert found == expected, (text, source)


#: Where a LaTeX document repeats a run of an earlier paper, whether G7's text recycling reads
#: it there, the file it is typed in, and whether the run is quoted (step 13): `<>` is the
#: run. A place in `part.tex` is in the file the entry inputs, where a paragraph drawn of
#: `main.tex` stands.
_LATEX_RECYCLED_PLACES = (
    ("<>.\n", True, "main.tex", False),
    ("A note.\\footnote{<>.}\n", True, "main.tex", False),
    ("% <>.\n", False, "main.tex", False),
    ("\\iffalse <>. \\fi\n", False, "main.tex", False),
    ("% a line of comment\n<>.\n", True, "main.tex", False),
    ("<>.\n", True, "part.tex", False),
    ("\\section{Discussion}\n<>.\n", True, "part.tex", False),
    # A caption is compared, and a quotation LaTeX marks with a command is quoted (round 1
    # of step 13).
    ("\\begin{figure}\n\\mg{figure.forest}\n\\caption{<>.}\n\\end{figure}\n", True, "main.tex",
     False),
    ("As \\enquote{<>} put it.\n", True, "main.tex", True),
    ("\\begin{quote}\n<>.\n\\end{quote}\n", True, "part.tex", True),
)  # fmt: skip


@st.composite
def _planted_latex_recycling(draw: st.DrawFn) -> tuple[dict[str, str], str, set[tuple]]:
    """A LaTeX document, `main.tex` and the `part.tex` it inputs, with a run of fourteen words
    of an earlier paper in each place of `_LATEX_RECYCLED_PLACES`, in an order drawn, each its
    own paragraph after words drawn and its lines wrapped as drawn; the earlier paper; and,
    for each run the reading reads, its file, the lines of its first and last words, and
    whether it is quoted."""
    pool = list(draw(st.permutations(_EARLIER_WORDS)))
    pieces: dict[str, list[str]] = {"main.tex": [], "part.tex": []}
    source, runs = "", []
    for index in draw(st.permutations(range(len(_LATEX_RECYCLED_PLACES)))):
        template, read, name, quoted = _LATEX_RECYCLED_PLACES[index]
        run, pool = pool[:14], pool[14:]
        own = draw(st.lists(st.sampled_from(_ITS_OWN), min_size=_APART_BY, max_size=8))
        source += " ".join(own) + "\n" + " ".join(run) + "\n"
        joints = [draw(st.sampled_from((" ", " ", "\n"))) for _ in run[1:]]
        # A comment ends at its line's end: the run it holds is on its one line.
        if template.startswith("%"):
            joints = [" "] * len(joints)
        written = run[0] + "".join(j + w for j, w in zip(joints, run[1:], strict=True))
        filler = " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))
        pieces[name].append(f"\n{filler.capitalize()}.\n\n" + template.replace("<>", written))
        runs.append((run, read, name, quoted))
    main = pieces["main.tex"]
    main.insert(draw(st.integers(0, len(main))), "\n\\input{part}\n")
    texts = {
        "main.tex": "\\documentclass{article}\n\\begin{document}\n" + "".join(main)
        + "\n\\end{document}\n",
        "part.tex": "".join(pieces["part.tex"]),
    }
    expected = set()
    for run, read, name, quoted in runs:
        if read:
            found = re.search(r"\s+".join(run), texts[name])
            assert found is not None, run
            text = texts[name]
            expected.add((name, text.count("\n", 0, found.start()) + 1,
                          text.count("\n", 0, found.end()) + 1, quoted))  # fmt: skip
    return texts, source, expected


@holds(60, _planted_latex_recycling())
def test_a_latex_passage_of_an_earlier_paper_is_placed_at_its_file_and_lines(
    planted: tuple[dict[str, str], str, set[tuple]],
) -> None:
    """G7's text recycling reads a LaTeX document as it prints, and names each passage at
    the file it is typed in and the lines there of its first and last words: in a paragraph,
    in a footnote, past a comment's line, and in the file the entry inputs, under a heading
    of its own too; a run in a comment or left out by `\\iffalse` is not read (step 13). A
    float's caption is read, and a run `\\enquote{}` or a `quote` environment holds is quoted
    (round 1)."""
    texts, source, expected = planted
    view = latex_print.printed(list(latex_structure.read_tree(texts).sources), compared=True)
    read = recycling_gate._read(view.text, None)
    placed = [
        recycling_gate._placed(Path("m"), view, Path("c"), passage)
        for passage in recycling_gate._recycled(read, recycling_gate.words(source), "k")
    ]
    found = {(path.name, p.first_line, p.last_line, p.quoted == p.shared)
             for path, _copy, p in placed}  # fmt: skip
    assert found == expected, (found, expected, texts)


def _a_recycled_passage_s_lines_are_the_printed_view_s(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print.Printed, "place",
                  lambda self, offset: (self.origins[0][1],
                                        self.text.count("\n", 0, offset) + 1))  # fmt: skip


@st.composite
def _planted_latex_pointers(draw: st.DrawFn) -> tuple[dict[str, str], set[tuple]]:
    """A LaTeX document, `main.tex` and the `part.tex` it inputs where a paragraph drawn of
    `main.tex` stands, that numbers tables and figures with captioned floats, each labelled,
    and holds a float with a starred caption only and one `\\ContinuedFloat` continues, which
    number nothing. Its first table is a float that inputs `tab.tex`, which holds its caption,
    and its first figure is two subfigures, whose captions number its parts. It cites each
    numbered display in its order, by a cross-reference to its label or by a pointer typed,
    the first table always by `\\ref`, and the first figure always by `\\ref` to its first
    part's label; and it points, in `part.tex`, at one table more than it numbers. What G2
    says of it: that last pointer, at its file and line (steps 13 and its round 2)."""
    tables, figures = draw(st.integers(1, 3)), draw(st.integers(1, 2))
    kinds = ["table"] * tables + ["figure"] * figures + ["starred", "continued"]
    pieces, seen = [], {"table": 0, "figure": 0}
    for kind in draw(st.permutations(kinds)):
        if kind == "starred":
            pieces.append("\\begin{table}\\caption*{Not numbered.}\\end{table}")
            continue
        if kind == "continued":
            pieces.append("\\begin{figure}\\ContinuedFloat\\caption{Continued.}\\end{figure}")
            continue
        seen[kind] += 1
        label = f"{kind[:3]}{seen[kind]}"
        if (kind, seen[kind]) == ("table", 1):
            pieces.append("\\begin{table}\\input{tab}\\end{table}")
        elif (kind, seen[kind]) == ("figure", 1):
            pieces.append("\\begin{figure}" + "".join(
                f"\\begin{{subfigure}}{{.4\\linewidth}}\\caption{{Part.}}\\label{{{label}{part}}}"
                "\\end{subfigure}" for part in "ab") + f"\\caption{{Both.}}\\label{{{label}}}"
                "\\end{figure}")  # fmt: skip
        else:
            pieces.append(f"\\begin{{{kind}}}\\caption{{The {kind}.}}\\label{{{label}}}"
                          f"\\end{{{kind}}}")  # fmt: skip
    # Each kind's citations in its order, the two kinds interleaved as drawn.
    queues = {"table": list(range(1, tables + 1)), "figure": list(range(1, figures + 1))}
    while queues["table"] or queues["figure"]:
        kind = draw(st.sampled_from([k for k in ("table", "figure") if queues[k]]))
        number = queues[kind].pop(0)
        word = kind.capitalize()
        by_ref = number == 1 or draw(st.booleans())
        part = "a" if (kind, number) == ("figure", 1) else ""
        pieces.append(f"As {word}~\\ref{{{kind[:3]}{number}{part}}} shows." if by_ref
                      else f"As {word}~{number} shows.")  # fmt: skip
    pieces.insert(draw(st.integers(0, len(pieces))), "\\input{part}")
    table = "\\caption{The table.}\\label{tab1}\n\\begin{tabular}{l}x\\end{tabular}\n"
    filler = " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=3)))
    over = f"Table~{tables + 1}"
    part = f"{filler.capitalize()}.\n\nThe rest is in {over}.\n"
    texts = {
        "main.tex": "\\documentclass{article}\n\\begin{document}\n"
        + "".join(f"\n{piece}\n" for piece in pieces) + "\\end{document}\n",
        "part.tex": part,
        "tab.tex": table,
    }
    return texts, {("pointer-to-nothing", "part.tex", part.count("\n", 0, part.index(over)) + 1)}


@holds(60, _planted_latex_pointers())
def test_a_latex_pointer_is_held_to_what_latex_numbers(
    planted: tuple[dict[str, str], set[tuple]],
) -> None:
    """G2 counts the tables and figures a LaTeX document numbers with a float's `\\caption`, a
    starred one numbering nothing; a cross-reference cites the display whose label it names;
    and a pointer to more than the document numbers is said at its file and line, in the
    file the entry inputs too (step 13)."""
    texts, expected = planted
    sources = list(latex_structure.read_tree(texts).sources)
    report = pointers_latex_gate.pointers_in_documents(
        {False: sources, True: []}, Path("m"), dict.fromkeys(pointers_latex_gate.AS_FILES, 0)
    )
    found = {(f.code, f.path.name, f.line) for f in report.findings}
    assert found == expected, (found, expected, texts)


@st.composite
def _planted_latex_legends(draw: st.DrawFn) -> tuple[str, set[int]]:
    """A LaTeX document of floats in an order drawn, each caption of words drawn: figures, a
    table, a figure with a starred caption only, and a figure of two subfigures whose own
    captions are long. What G4 reads as a legend over `_LEGEND_LIMIT` words: the line of each
    figure's caption that is longer, and no other (step 13)."""

    def words(least: int, most: int) -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=least, max_size=most)))

    long = _LEGEND_LIMIT + 3
    floats = [("figure", words(1, _LEGEND_LIMIT * 2)) for _ in range(draw(st.integers(1, 3)))]
    floats += [("table", words(long, long + 4)), ("starred", words(long, long + 4)),
               ("parts", words(long, long + 4))]  # fmt: skip
    lines, expected = ["\\documentclass{article}", "\\begin{document}"], set()
    for kind, said in draw(st.permutations(floats)):
        lines.append(draw(st.sampled_from(("Words first.", ""))))
        if kind == "figure":
            lines += ["\\begin{figure}", f"\\caption{{{said}}}", "\\end{figure}"]
            if len(said.split()) > _LEGEND_LIMIT:
                expected.add(len(lines) - 1)
        elif kind == "table":
            lines += [f"\\begin{{table}}\\caption{{{said}}}\\end{{table}}"]
        elif kind == "starred":
            lines += [f"\\begin{{figure}}\\caption*{{{said}}}\\end{{figure}}"]
        else:
            lines += ["\\begin{figure}",
                      f"\\begin{{subfigure}}{{.4\\linewidth}}\\caption{{{said}}}\\end{{subfigure}}",
                      "\\caption{Two parts.}", "\\end{figure}"]  # fmt: skip
    lines.append("\\end{document}")
    return "\n".join(lines) + "\n", expected


#: The words a legend may have in `_planted_latex_legends`.
_LEGEND_LIMIT = 6


@holds(60, _planted_latex_legends())
def test_a_latex_legend_is_its_figure_s_caption(planted: tuple[str, set[int]]) -> None:
    """G4 reads a figure's legend in the caption LaTeX numbers it by, its words counted as a
    Markdown legend's: not a table's caption, a starred one, nor a subfigure's (step 13)."""
    from manuscript_guard.text.sections import count_words

    text, expected = planted
    sources = list(latex_structure.read_tree({"main.tex": text}).sources)
    found = {line for _path, line, legend in latex_print.captions_in(sources)
             if count_words(legend) > _LEGEND_LIMIT}  # fmt: skip
    assert found == expected, (found, expected, text)


def _a_subfigure_s_caption_numbers_the_float(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_SUBFLOAT", re.compile(r"(?!)"))


def _a_continued_float_numbers_a_display(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_CONTINUED", re.compile(r"(?!)"))


def _a_part_s_label_names_nothing(patch: pytest.MonkeyPatch) -> None:
    named = latex_print._named
    patch.setattr(latex_print, "_named",
                  lambda captions, labels, _parts: named(captions, labels, []))  # fmt: skip


def _a_float_that_inputs_its_caption_is_uncounted(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_holds_input", lambda _source, _start, _end: False)
    patch.setattr(latex_print, "FLOATS", frozenset())


def _a_starred_caption_numbers_a_display(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_NUMBERED", re.compile(r"\\caption\*?(?![A-Za-z])\s*\{"))


class _EveryCommand(frozenset):
    """A set that holds every command, which the broken rule below takes for the pages'."""

    def __contains__(self, _item: object) -> bool:
        return True


def _a_cross_reference_cites_nothing(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(pointers_latex_gate, "_PAGES", _EveryCommand())


def _a_latex_pointer_s_line_is_the_view_s(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print.Printed, "place",
                  lambda self, offset: (self.origins[0][1],
                                        self.text.count("\n", 0, offset) + 1))  # fmt: skip


def _a_caption_is_not_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(latex_print, "_CAPTION", re.compile(r"(?!)"))


def _a_quotation_latex_marks_with_a_command_is_not_quoted(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(recycling_gate, "_MARKED", re.compile(r"(?!)"))


def _a_recycled_passage_ends_on_its_first_line(patch: pytest.MonkeyPatch) -> None:
    placed = recycling_gate._placed

    def first_line_only(folder, where, copy, passage):
        path, copy, passage = placed(folder, where, copy, passage)
        return path, copy, dataclasses.replace(passage, last_line=passage.first_line)

    patch.setattr(recycling_gate, "_placed", first_line_only)


@holds(150, plan_pairs())
def test_a_section_of_two_plans_differs_only_where_its_words_do(
    drawn: tuple[dict[str, str], list[str]],
) -> None:
    """G8 says which sections an earlier plan and this one both have whose words differ. A
    section re-wrapped, put in emphasis, given a comment, written in capitals or numbered is
    the same section saying the same; one with a word added is not; and the plan's own
    Deviations are each paper's and never compared. Each example holds every edit."""
    given, changed = drawn
    assert READINGS["plan sections"]()(given) == changed, given


@holds(150, dictionary_pairs())
def test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise(
    drawn: tuple[dict[str, str], list[list[Any]]],
) -> None:
    """G8 says which variables an earlier data dictionary and this one both have that are
    recorded otherwise, and in which part. A definition re-wrapped or in capitals, codes
    named by their list, inputs in another order, a bound written with a point, a time
    bound quoted or in another zone's notation, a term or a label in capitals is the same
    variable recorded alike; each other edit changes the one part it names, a code dropped
    and a code added among them, and a date made a time is its type alone; a variable one
    dictionary lacks is compared with nothing; and a study period given otherwise is said.
    Each example holds every edit."""
    given, changed = drawn
    assert READINGS["data dictionaries"]()(given) == changed, given


# ------------------------------------------------------------- scripts the gates do not read

#: Characters of each script the gates do not read, from the blocks of Unicode that hold it,
#: its first and last code points among them.
_FOREIGN = {
    "Han": ("\N{CJK UNIFIED IDEOGRAPH-7ED3}", "\N{CJK UNIFIED IDEOGRAPH-3400}",
            chr(0x9FFF), "\N{CJK COMPATIBILITY IDEOGRAPH-F900}"),
    "Hiragana": ("\N{HIRAGANA LETTER A}", "\N{HIRAGANA LETTER SMALL A}",
                 "\N{HIRAGANA DIGRAPH YORI}"),
    "Katakana": ("\N{KATAKANA LETTER A}", "\N{KATAKANA LETTER SMALL KU}",
                 "\N{HALFWIDTH KATAKANA LETTER A}"),
    "Hangul": ("\N{HANGUL SYLLABLE GA}", "\N{HANGUL CHOSEONG KIYEOK}",
               "\N{HANGUL LETTER KIYEOK}"),
}  # fmt: skip


@st.composite
def _planted_scripts(draw: st.DrawFn) -> tuple[str, str, dict[str, int]]:
    """A text, the same with runs of every script the gates do not read put into it at
    places drawn, and how many characters of each went in. Every script in every example."""
    from collections import Counter

    text = draw(texts())
    planted: Counter[str] = Counter()
    runs = []
    for script, characters in _FOREIGN.items():
        run = "".join(draw(st.lists(st.sampled_from(characters), min_size=1, max_size=6)))
        planted[script] += len(run)
        runs.append(run)
    pieces = text.split(" ")
    for run in runs:
        pieces.insert(draw(st.integers(0, len(pieces))), run)
    return text, " ".join(pieces), dict(planted)


@holds(200, _planted_scripts())
def test_every_character_of_a_script_the_gates_do_not_read_is_counted(
    planted: tuple[str, str, dict[str, int]],
) -> None:
    """Whatever the text, a run of Han, Hiragana, Katakana or Hangul put into it adds as many
    characters of that script as it holds, and no other."""
    from manuscript_guard.gates.scripts import scripts_in

    text, with_them, expected = planted
    before, after = scripts_in(text), scripts_in(with_them)
    assert {name: after[name] - before[name] for name in _FOREIGN} == expected, with_them


# ------------------------------------------------------------- the text of a vector figure


@holds(100, vector_figures())
def test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn(
    drawn: tuple[str, dict[str, float], list[float]],
) -> None:
    """G4 holds a vector figure's smallest text and thinnest line to a journal's, at the
    width it prints: each text's height is its size, in units whatever unit it was set in,
    through every transform around it, taken along its upright; and each line's width the
    same, by the transforms' scale. A size not set is SVG's 16, an em or a percent is of
    the size around it, and a text drawn through `<use>` is read where it is used."""
    from manuscript_guard.gates.figure_svg import parse_svg

    document, texts, lines = drawn
    svg = parse_svg(document)
    assert svg is not None, document
    read = {mark.text: mark.units for mark in svg.texts}
    assert read.keys() == texts.keys(), (read, texts)
    for label, units in texts.items():
        assert read[label] == pytest.approx(units, rel=1e-9), (label, read[label], document)
    assert sorted(mark.units for mark in svg.lines) == pytest.approx(lines, rel=1e-9), document


def _transforms_are_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    patch.setattr(figure_svg, "_transform", lambda written: figure_svg.IDENTITY)


def _transforms_are_composed_the_other_way(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    multiply = figure_svg._multiply
    patch.setattr(figure_svg, "_multiply", lambda left, right: multiply(right, left))


def _a_point_is_a_unit(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    patch.setattr(figure_svg, "_UNITS", {**figure_svg._UNITS, "pt": 1.0})


def _an_em_is_of_the_default_size(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    length = figure_svg._length
    default = figure_svg.DEFAULT_FONT_UNITS
    patch.setattr(figure_svg, "_length", lambda value, relative_to: length(value, default))


def _a_use_is_not_followed(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    patch.setattr(figure_svg, "_use", lambda *drawn: None)


def _a_text_is_as_tall_as_a_line_is_wide(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    patch.setattr(figure_svg, "_height", figure_svg._widened)


def _a_size_not_set_is_ten(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    patch.setattr(figure_svg, "DEFAULT_FONT_UNITS", 10.0)


def _a_line_is_not_widened(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    patch.setattr(figure_svg, "_widened", lambda matrix: 1.0)


@holds(100, pdf_figures())
def test_a_pdf_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn(
    drawn: tuple[bytes, list[float], list[float]],
) -> None:
    """A PDF figure's texts and lines as G4 reads them: each text at the size `Tf` sets it,
    through the text matrix and every `cm` around it, and a form's under its `/Matrix`;
    each line stroked at its width through the same, and a filled path no line. What `q`
    saves, `Q` gives back."""
    from manuscript_guard.gates.figure_pdf import parse_pdf

    document, texts, lines = drawn
    figure = parse_pdf(document)
    assert figure is not None
    assert sorted(size for _text, size in figure.texts) == pytest.approx(texts, rel=1e-9)
    assert sorted(figure.lines) == pytest.approx(lines, rel=1e-9)


def _pdf_operations_without(patch: pytest.MonkeyPatch, *dropped: bytes) -> None:
    from manuscript_guard.gates import figure_pdf

    operations = figure_pdf._operations
    patch.setattr(
        figure_pdf,
        "_operations",
        lambda data: ((ops, op) for ops, op in operations(data) if op not in dropped),
    )


def _a_pdf_s_transforms_are_composed_the_other_way(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_pdf

    multiply = figure_pdf._multiply
    patch.setattr(figure_pdf, "_multiply", lambda left, right: multiply(right, left))


def _q_does_not_give_back_what_it_saved(patch: pytest.MonkeyPatch) -> None:
    _pdf_operations_without(patch, b"Q")


def _the_text_matrix_is_not_read(patch: pytest.MonkeyPatch) -> None:
    _pdf_operations_without(patch, b"Tm")


def _a_form_is_drawn_without_its_matrix(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_pdf

    patch.setattr(figure_pdf, "_form_matrix", lambda held, objects: figure_pdf.IDENTITY)


def _a_form_is_not_drawn(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_pdf

    patch.setattr(figure_pdf, "_form", lambda *drawn: None)


def _a_filled_path_is_a_line(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_pdf

    patch.setattr(figure_pdf, "_STROKES", {*figure_pdf._STROKES, b"f"})


def _a_form_draws_with_a_state_of_its_own(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_pdf

    form = figure_pdf._form
    patch.setattr(figure_pdf, "_form", lambda *drawn: form(*drawn[:6], figure_pdf.START))


def _a_page_s_streams_are_drawn_apart(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_pdf

    def apart(streams, resources, objects, figure):
        for data in streams:
            figure_pdf._draw(data, resources, figure_pdf.IDENTITY, objects, figure, 0)

    patch.setattr(figure_pdf, "_draw_page", apart)


def _a_pdf_text_is_as_tall_as_a_line_is_wide(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_pdf

    patch.setattr(figure_pdf, "_height", figure_pdf._widened)


def _a_figure_s_stylesheet_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import svg_style

    patch.setattr(svg_style.Sheet, "declared", lambda self, node: {})


def _a_font_s_first_number_is_its_size(patch: pytest.MonkeyPatch) -> None:
    """The reading before round 1 of #302: a weight, "700", read as the size."""
    from manuscript_guard.gates import figure_svg

    pattern = figure_svg._FONT_SIZE.pattern.replace("|rem|%)|", "|rem|%)?|")
    assert pattern != figure_svg._FONT_SIZE.pattern
    patch.setattr(figure_svg, "_FONT_SIZE", re.compile(pattern, re.IGNORECASE))


# ------------------------------------------------------------- a figure's alternative text


def _descriptions_pandoc_reads(markdown: str) -> list[str]:
    """The description of the one image in each paragraph pandoc reads in `markdown`, its
    words as pandoc reads them, a space between two, and any other inline by its name; a
    paragraph that is not one span holding one image by what it is."""
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        pytest.skip("pandoc is not installed, and the description is the one it reads")
    read = subprocess.run(
        [pandoc, "-f", "markdown", "-t", "json"],
        input=markdown.encode("utf-8"),
        capture_output=True,
        check=True,
        timeout=120,
    )

    def said(inline: dict) -> str:
        kind = inline["t"]
        return inline["c"] if kind == "Str" else " " if kind == "Space" else f"<{kind}>"

    found = []
    for block in json.loads(read.stdout)["blocks"]:
        inlines = block["c"] if block["t"] == "Para" else []
        if len(inlines) == 1 and inlines[0]["t"] == "Span":
            inlines = inlines[0]["c"][1]
        if len(inlines) == 1 and inlines[0]["t"] == "Image":
            found.append("".join(said(inline) for inline in inlines[0]["c"][1]))
        else:
            found.append(f"<{block['t']} of {[inline['t'] for inline in inlines]}>")
    return found


@holds(12, st.lists(alt_texts(), min_size=1, max_size=4))
def test_an_alternative_text_is_the_pictures_description_as_it_was_written(
    written: list[str],
) -> None:
    """What the build writes for a figure's alternative text pandoc reads back as exactly
    that text, its ASCII white space folded to single spaces: no mark in it read as markup,
    no line in it ending the paragraph, and a no-break space kept (round 1 of #387). Several
    figures in one document, as a manuscript places them."""
    from manuscript_guard.build.assemble import FIGURE_SPAN
    from manuscript_guard.gates.figure_alt import as_markdown

    markdown = "\n\n".join(
        f"[![{as_markdown(text)}](figures/f.png)]{{.{FIGURE_SPAN}}}" for text in written
    )
    folded = [re.sub(r"[ \t\r\n\f\v]+", " ", text).strip(" \t\r\n\f\v") for text in written]
    assert _descriptions_pandoc_reads(markdown) == folded


# ------------------------------------------------------------------ the colours a figure paints


@holds(25, painted_svgs())
def test_each_colour_an_svg_figure_paints_is_read_and_its_texts_kept_apart(
    drawn: tuple[str, set[str], set[str]],
) -> None:
    """Each mark's colour as it shows over white, however the figure sets it: an attribute,
    a style, a class, a group's, `inherit`, `currentColor`, through `<use>`, under a group's
    opacity or a fill-opacity, by name, as `rgb()` or `hsl()`; and none for a mark not
    displayed, hidden, painted nothing, or defined and never used. A text's colour is read,
    and kept apart from the marks', a text drawn as glyphs too (round 1 of #398)."""
    from manuscript_guard.gates.figure_svg import parse_svg

    document, marks, texts = drawn
    svg = parse_svg(document)
    assert svg is not None
    assert {paint.colour for paint in svg.paints if not paint.text} == marks, document
    assert {paint.colour for paint in svg.paints if paint.text} == texts, document


@holds(25, painted_pdfs())
def test_each_colour_a_pdf_figure_paints_is_read_and_its_texts_kept_apart(
    drawn: tuple[bytes, set[str], set[str]],
) -> None:
    """Each path filled or stroked in a colour set by `rg`, `g`, `k`, their stroking twins,
    or `sc` and `scn` in a colour space, under a graphics state's opacity, inside `q` and
    `Q`, or by a form drawn in its drawer's colour; nothing for a pattern; a text's colour
    kept apart."""
    from manuscript_guard.gates.figure_pdf import parse_pdf

    data, marks, texts = drawn
    figure = parse_pdf(data)
    assert figure is not None
    assert {paint.colour for paint in figure.paints if not paint.text} == marks, data
    assert {paint.colour for paint in figure.paints if paint.text} == texts, data


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


# ------------------------------------------------------------------- a publisher's proof


def _compared(drawn: dict[str, Any]):
    """What `proof` says of a proof drawn by `proofs`."""
    from manuscript_guard.proof import reading as proof_reading
    from manuscript_guard.proof.compare import compare
    from manuscript_guard.proof.sent import PARAGRAPH, Part, Sent

    parts = tuple(Part(PARAGRAPH, text, label) for label, text in drawn["parts"])
    read = proof_reading._paged("the text as saved", drawn["pages"])
    return compare(Sent(Path("manuscript.docx"), parts, (), None), read)


@holds(60, proofs(planted=False))
def test_a_proof_that_prints_what_was_sent_reads_as_it(drawn: dict[str, Any]) -> None:
    """However the proof wraps and pages the parts, with its running heads, its page
    numbers, its line numbers or none, and words broken at a line's end, it prints what was
    sent: nothing to correct, nothing shown."""
    result = _compared(drawn)
    assert result.changes == ()
    assert result.found == result.total


@holds(60, proofs())
def test_each_change_a_typesetter_makes_is_reported_once_where_it_is(
    drawn: dict[str, Any],
) -> None:
    """One of every change of `PROOF_CORRECTIONS` is a correction of its part, and the part
    the proof leaves out is reported missing, each once and nothing else; the same value set
    otherwise is typography and the word changed a copy-edit, each in its part. A change is
    said to be on the page its line is on, and on that line where the proof numbers them."""
    from manuscript_guard.proof.compare import ADDED, COPY_EDIT, CORRECTION, MOVED
    from manuscript_guard.proof.tokens import TYPOGRAPHY as SET_OTHERWISE

    result = _compared(drawn)
    planted = drawn["planted"]
    wanted = {(what, planted[f"{what} {printed}"][0]) for _s, printed, what in PROOF_CORRECTIONS}
    wanted.add(("missing", planted["missing"][0]))
    found = [(c.what, c.part) for c in result.changes if c.kind == CORRECTION]
    assert sorted(found) == sorted(wanted)
    edits = [(c.part, c.sent, c.printed) for c in result.changes if c.kind == COPY_EDIT]
    abbreviated = [word.split()[-1] for word in PROOF_ABBREVIATED]
    assert sorted(edits) == sorted([(planted[f"copy-edit {PROOF_EDIT[1]}"][0], *PROOF_EDIT),
        (planted[f"abbreviated {PROOF_ABBREVIATED[1]}"][0], *abbreviated)])  # fmt: skip
    shown = sorted(c.part for c in result.changes if c.kind == SET_OTHERWISE)
    assert shown == sorted(planted[f"typography {printed}"][0] for _s, printed in
                           PROOF_TYPOGRAPHY)  # fmt: skip
    assert not [c for c in result.changes if c.kind in (ADDED, MOVED)]
    for change in result.changes:
        if change.kind != CORRECTION or change.what == "missing":
            continue
        printed = next(shown for part, shown in planted.values()
                       if part == change.part).split()[-1]
        number, (page, line) = next((n, at) for n, at in drawn["lines"].items()
                                    if printed in at[1].replace("\N{NO-BREAK SPACE}", " "))
        assert change.page == page, (change, page)
        assert change.line == (number if drawn["numbered"] else None), (change, number)


def _a_decimal_comma_is_the_same_number(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.proof import compare as module
    from manuscript_guard.proof import tokens

    def compared(sent, printed):
        verdict, note = tokens.compare_numbers(sent, printed)
        return (tokens.TYPOGRAPHY, "") if verdict == tokens.DECIMAL_MARK else (verdict, note)

    patch.setattr(module, "compare_numbers", compared)


def _a_sign_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.proof import compare as module
    from manuscript_guard.proof import tokens

    def compared(sent, printed):
        verdict, note = tokens.compare_numbers(sent, printed)
        return (tokens.SAME, "") if verdict == tokens.SIGN else (verdict, note)

    patch.setattr(module, "compare_numbers", compared)


def _a_unit_is_a_word(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.proof import compare as module

    patch.setattr(module, "is_unit", lambda raw: raw in "%<>=")


def _a_unit_of_time_spelt_out_is_a_word(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.proof import compare as module

    patch.setattr(module, "time_units", lambda found: set())


def _a_unit_past_a_hyphen_is_not_beside_its_number(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.proof import compare as module

    patch.setattr(module, "_past_hyphen", lambda found, lo: ())


def _a_unit_of_time_spelt_out_is_a_unit(patch: pytest.MonkeyPatch) -> None:
    # So read, the AMA's "12 wk" for "12 weeks" was a correction (round 2 of #397).
    from manuscript_guard.proof import compare as module
    from manuscript_guard.proof import tokens

    real = module.is_unit
    patch.setattr(module, "is_unit",
                  lambda raw: real(raw) or raw.casefold() in tokens._TIME_WORDS)  # fmt: skip


def _running_heads_are_kept(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.proof import reading

    patch.setattr(reading, "_without_running_lines", lambda pages, taken: pages)


def _a_stretch_is_not_slid_to_a_part(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.proof import align

    patch.setattr(align, "slid", lambda ops, a, b, starts: ops)


def _a_word_broken_at_a_line_end_stays_two(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.proof import compare as module
    from manuscript_guard.proof.tokens import prepared, tokens

    def unjoined(reading, sent):
        return [t for at, line in enumerate(reading.lines)
                for t in tokens(prepared(line.text), at)]  # fmt: skip

    patch.setattr(module, "proof_tokens", unjoined)


def _a_compound_broken_at_a_line_end_loses_its_hyphen(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.proof import compare as module

    real = module.proof_tokens

    def joined(reading, sent):
        return real(reading, [t for t in sent if t.key != "-"])

    patch.setattr(module, "proof_tokens", joined)


def _a_number_split_in_two_is_two(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.proof import compare as module

    patch.setattr(module, "_regrouped", lambda ops, a, b: ops)


# ------------------------------------------------------------- a unit written after a binding

#: What may follow a binding, with the unit read there, or None where none is: a gap of each
#: kind, a power, a slash, a symbol of the list, and words that open with a symbol's letters.
_AFTER_A_BINDING = (
    (" mg", "mg"),
    # Pandoc's escaped space, the entity of a no-break one, a comment, which is not
    # printed, and the hair and figure spaces (round 1 of #279).
    ("\\ mg", "mg"),
    ("&nbsp;mg", "mg"),
    ("&#160;g", "g"),
    ("<!-- the dose --> mg", "mg"),
    ("\N{HAIR SPACE}mg", "mg"),
    ("\N{FIGURE SPACE}mg", "mg"),
    ("&#0160;mg", "mg"),
    # No unit across the words between two comments, nor after a backslash that escapes no
    # space (round 1 of #341).
    ("<!-- a --> and <!-- b --> mg", None),
    ("\\\nmg", None),
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


# ---------------------------------------------- a technical sense, counted towards no rate

#: Technical senses of words the vocabulary rate counts, in the singular and the plural.
_TECHNICAL = (
    "robust standard error", "robust standard errors", "Robust variance", "robust variances",
    "robust estimator", "robust estimators", "robust regression", "robust regressions",
    "robustness check", "robustness checks", "robust analysis", "robust analyses",
    "sandwich robust", "comprehensive cohort", "comprehensive search strategy",
)  # fmt: skip


@st.composite
def _technical_senses(draw: st.DrawFn) -> str:
    """Plain words with every technical sense among them once, in an order and with spaces
    drawn each time."""
    parts = []
    for phrase in draw(st.permutations(_TECHNICAL)):
        words = draw(st.lists(st.sampled_from(FILLER), min_size=12, max_size=20))
        gap = draw(st.sampled_from((" ", "  ", "\n", "\N{NO-BREAK SPACE}")))
        parts.append(" ".join(words) + " " + phrase.replace(" ", gap) + ".")
    return " ".join(parts)


@holds(60, _technical_senses())
def test_a_technical_sense_adds_nothing_to_the_vocabulary_rate(text: str) -> None:
    """Item 54: "robust standard errors" is how papers by people write it, and counted
    towards the rate in the plural. Each technical sense, however cased and spaced, counts
    as the same text with its flagged word replaced by a plain one."""
    plain = re.sub(r"(?i)\b(?:robust|comprehensive)", "plain", text)
    rate = writing_gate.rates([(Path("m.md"), text)])["ai-vocabulary"]
    assert rate == writing_gate.rates([(Path("m.md"), plain)])["ai-vocabulary"], text


# ------------------------------------------------------------ a journal's limit, in its quote

#: Words that write a number up to twenty, as G4 reads them.
_NUMBER_WORDS = journal_quotes_gate._WORDS


@st.composite
def _limits_quoted(draw: st.DrawFn) -> list[tuple[str, int, bool]]:
    """A limit, and its number written into a quote each way a page writes it, and each way
    a quote holds a number or a word that is not it: one of every kind in each example,
    among words drawn each time."""
    value = draw(st.integers(1, 99_999))
    small = draw(st.integers(1, 9))
    group = draw(st.integers(100, 999))

    def among(written: str) -> str:
        before = draw(st.lists(st.sampled_from(FILLER), max_size=3))
        after = draw(st.lists(st.sampled_from(FILLER), max_size=3))
        return " ".join([*before, written, *after])

    cases = [
        (among(str(value)), value, True),
        (among(f"{value:,}"), value, True),
        (among(f"{value:,}".replace(",", " ")), value, True),
        (among(f"{value}-word"), value, True),
        (among(_NUMBER_WORDS[small]), small, True),
        (among(_NUMBER_WORDS[small].capitalize()), small, True),
        (among(f"1{value}"), value, False),
        (among(f"{value}0"), value, False),
        (among(f"{value}.5"), value, False),
        (among(f"{value},000"), value, False),
        (among(f"{_NUMBER_WORDS[small]}fold"), small, False),
        (among(f"{small + 10}"), small, False),
        # The last group of a number written with spaces between its thousands, and a group of
        # three after a number that cannot be one, as a limits table saved as text has it.
        (among(f"{small} {group}"), group, False),
        (among(f"{small}{small} {group}"), group, False),
        (among(f"{value + 1000} {group}"), group, True),
        (among(f"{group + 1} {group}"), group, True),
    ]
    return draw(st.permutations(cases))


@holds(150, _limits_quoted())
def test_a_limit_is_stated_by_its_number_and_by_no_longer_one(
    cases: list[tuple[str, int, bool]],
) -> None:
    """A journal's limit is in its quote as digits, with or without a separator of
    thousands, or as a word up to twenty; not inside a longer number or a longer word."""
    for quote, value, stated in cases:
        assert journal_quotes_gate._states(quote, value) is stated, (quote, value)


@st.composite
def _quotes_on_pages(draw: st.DrawFn) -> list[tuple[str, str, bool]]:
    """A journal's page and a quote of it: the quote there as words of its own, in another
    case, and after itself inside a longer number; and the quote only as the end or the
    start of a longer number or word. One of each in every example, among words drawn."""

    def words() -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))

    quote = f"{draw(st.integers(10, 999))} {draw(st.sampled_from(('words', 'references')))}"
    digit = draw(st.integers(1, 9))
    cases = [
        (f"{words()} {quote} {words()}.", quote, True),
        (f"{words()} {quote.upper()}.", quote, True),
        (f"{words()} {digit}{quote}, then {quote} {words()}.", quote, True),
        (f"{words()} {digit}{quote} {words()}.", quote, False),
        (f"{words()} {quote}s {words()}.", quote, False),
    ]
    return draw(st.permutations(cases))


@holds(100, _quotes_on_pages())
def test_a_quote_is_on_its_page_as_the_words_it_is(cases: list[tuple[str, str, bool]]) -> None:
    """Round 2 of #297: a profile's quote is on its page as words of its own, in any case:
    "50 words" is in "250 words" as characters, and is not what the page says, but a later
    "50 words" on the same page is."""
    for page, quote, there in cases:
        assert journal_quotes_gate._on_page(page, quote) is there, (page, quote)


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
        # Round 2 of #249: a label spaced from its number, an electronic one, and a
        # qualifier with no brackets.
        f"ISBN 10 {spaced[0]}, ISBN 13: {spaced[1]}",
        f"e-ISBN {hyphened[1]}; eISBN: {spaced[1]}",
        f"{hyphened[0]} pbk. {spaced[1]} Hardcover",
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


# ----------------------------------------------------------------- LaTeX out of Markdown

#: The works the generated citations name, for citeproc to format.
_LATEX_OUT_BIB = (
    "@article{smith2020, author = {Smith, Ann}, title = {A study}, journal = {J}, year = {2020}}\n"
    "@article{jones2019, author = {Jones, Ben}, title = {A trial}, journal = {K}, year = {2019}}\n"
)


def _latex_body(markdown: str, *arguments: str) -> str:
    """The body pandoc writes as LaTeX for `markdown`, as `build --latex` asks for it."""
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        pytest.skip("pandoc is not installed, and the LaTeX is the one it writes")
    done = subprocess.run([pandoc, "-f", "markdown", "-t", "latex", "--wrap=preserve",
                           "--no-highlight", *arguments], input=markdown, capture_output=True,
                          text=True, encoding="utf-8", check=True)  # fmt: skip
    return done.stdout


@holds(15, markdown_for_latex())
def test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps(markdown: str) -> None:
    """For ordinary Markdown, which pandoc writes as LaTeX on purpose otherwise than it is
    typed, the comparison `build --latex` refuses on finds nothing, under natbib and under
    citeproc: each thing pandoc moves or LaTeX prints on its own is put right (step 11)."""
    from manuscript_guard.build import latex_out
    from manuscript_guard.text.latex.mask import read

    body = _latex_body(markdown, "--natbib")
    reading = read(body, body=True)
    assert not reading.refusals, (markdown, body, reading.refusals)
    assert latex_out.compare_digits(markdown, body, reading, citeproc=False) is None, (
        markdown, body)
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        bib = Path(folder) / "references.bib"
        bib.write_text(_LATEX_OUT_BIB, encoding="utf-8")
        body = _latex_body(markdown, "--citeproc", f"--bibliography={bib}",
                           "--metadata=link-citations:true")  # fmt: skip
    reading = read(latex_out._without_citeproc_keys(body), body=True)
    assert not reading.refusals, (markdown, body, reading.refusals)
    assert latex_out.compare_digits(markdown, body, reading, citeproc=True) is None, (
        markdown, body)


@holds(15, markdown_for_latex(), st.integers(min_value=0, max_value=10_000))
def test_a_digit_pandoc_wrote_otherwise_is_caught(markdown: str, which: int) -> None:
    """Any digit the reader keeps in pandoc's LaTeX, changed, is a difference: a table's
    caption, a footnote and a cell among them (step 11)."""
    from manuscript_guard.build import latex_out
    from manuscript_guard.text.latex.mask import NUL, read
    body = _latex_body(markdown, "--natbib")
    shown = read(body, body=True).masked.replace(NUL, " ")
    # What the comparison passes over on purpose, as the Markdown reader does: the header a
    # `longtable` repeats, and an address or a DOI.
    passed = [found.span("head") for found in latex_out._REPEATED.finditer(body)]
    passed += latex_out.addresses(body, read(body, body=True))
    kept = [found.start() for found in re.finditer(r"\d", shown)
            if not any(start <= found.start() < end for start, end in passed)]  # fmt: skip
    at = kept[which % len(kept)]
    changed = body[:at] + str((int(body[at]) + 1) % 10) + body[at + 1 :]
    reading = read(changed, body=True)
    assert latex_out.compare_digits(markdown, changed, reading, citeproc=False) is not None, (
        markdown, changed[max(0, at - 60) : at + 20])


# ------------------------------------------------------------- a cited title, as registered

#: British spellings a cited title may have where the registry has the American one.
_BRITISH = ("haemorrhage", "tumour", "behaviour", "randomised", "paediatric", "anaemia",
            "centre", "oestrogen", "leukaemia", "labelled")  # fmt: skip
#: Words a title holds that a careless reading would drop for being short, and others of the
#: same length that a different work's title would hold in their place.
_SHORT = ("CT", "B", "C", "T2", "IV", "UK", "D", "X")
_OTHER_SHORT = ("MR", "A", "E", "T1", "II", "EU", "K", "Y")
#: What G7 is to find the same title in, and what it is to find another title in.
_SAME_TITLE = ("subtitle", "flagged", "typeset", "american", "tagged", "texed")
_OTHER_TITLE = ("short words", "other words")


@st.composite
def _retitled(draw: st.DrawFn) -> tuple[str, list[tuple[str, str, str]]]:
    """A cited title of drawn words with short ones among them and British spellings, and
    one registered title for each way a registry writes the same title, and for each way
    another work's title differs: every kind in every example, so that a rule broken for
    one kind fails whatever the seed. Two kinds mark up part of a word: the registry with
    a tag (`re<sub>ports</sub>`), the entry with a TeX command whose braces the .bib reader
    took away (`re\\textsubscriptports`, or `\\emph ` before a word)."""
    words = draw(st.lists(st.sampled_from(FILLER), min_size=3, max_size=10))
    british = draw(st.lists(st.sampled_from(_BRITISH), min_size=1, max_size=2, unique=True))
    # Short words enough that replacing them all leaves less than the share held: more
    # than 15 in 100 of the title once they are in it.
    short = (len(words) + len(british)) * 15 // 85 + 1
    for word in [*british, *draw(st.lists(st.sampled_from(_SHORT), min_size=short,
                                          max_size=short, unique=True))]:  # fmt: skip
        words.insert(draw(st.integers(0, len(words))), word)
    cited = " ".join(words)
    listed, _with_ize = _variants()
    american = " ".join(listed[w][1] if w in british else w for w in words)
    subtitle = " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))
    swap = dict(zip(_SHORT, _OTHER_SHORT, strict=True))
    other = list(words)
    for at in draw(st.permutations(range(len(words))))[: len(words) * 15 // 85 + 1]:
        other[at] = "zygote" if other[at] != "zygote" else "quorum"
    long = [at for at, word in enumerate(words) if len(word) > 1]
    at = draw(st.sampled_from(long))
    cut = draw(st.integers(1, len(words[at]) - 1))
    tagged, texed = american.split(" "), list(words)
    tagged[at] = f"{tagged[at][:cut]}<sub>{tagged[at][cut:]}</sub>"
    command = draw(st.sampled_from(("\\textsubscript", "\\textsuperscript", "\\emph")))
    texed[at] = f"{texed[at][:cut]}{command}{texed[at][cut:]}"
    registered = {
        "subtitle": f"{american}: {subtitle}",
        "flagged": f"RETRACTED: {american}",
        "typeset": draw(st.sampled_from((str.upper, str.title)))(american).replace(" ", ", ", 1),
        "american": american,
        "tagged": " ".join(tagged),
        "texed": american,
        "short words": " ".join(swap.get(w, w) for w in words),
        "other words": " ".join(other),
    }
    entry = {"texed": " ".join(texed)}
    return cited, [
        (kind, entry.get(kind, cited), registered[kind]) for kind in (*_SAME_TITLE, *_OTHER_TITLE)
    ]


@holds(150, _retitled())
def test_a_cited_title_is_found_in_its_registered_form_and_not_in_another(
    drawn: tuple[str, list[tuple[str, str, str]]],
) -> None:
    """G7 holds a cited title to the registry's: the same title with a subtitle the entry
    left out, the flag a registry puts in front, another case and punctuation, or American
    spelling holds all its words; a title with words of its own in place of more than a
    sixth of them, short ones included, is another work's."""
    from manuscript_guard.gates import lookups

    _cited, registered = drawn
    for kind, cited, title in registered:
        held = lookups.title_held(cited, title)
        if kind in _SAME_TITLE:
            assert held == 1.0, (kind, cited, title, held)
        else:
            assert held is not None and held < lookups.TITLE_HELD, (kind, cited, title, held)


# ------------------------------------------------------------- a family name, as registered

#: Family names a property draws: of letters a folding leaves alone.
_FAMILIES = ("Naranjo", "Busto", "Sellers", "Greenblatt", "Okafor", "Lindqvist", "Tanaka",
             "Moreau", "Kowalski", "Haddad", "Petrov", "Ndiaye")  # fmt: skip
#: A vowel, how TeX accents it in a .bib, and the letter a registry prints.
_ACCENTS = (("e", "{\\'e}", "\N{LATIN SMALL LETTER E WITH ACUTE}"),
            ("a", "{\\`a}", "\N{LATIN SMALL LETTER A WITH GRAVE}"),
            ("o", "{\\^o}", "\N{LATIN SMALL LETTER O WITH CIRCUMFLEX}"),
            ("i", "{\\'i}", "\N{LATIN SMALL LETTER I WITH ACUTE}"))  # fmt: skip
_PARTICLE_FORMS = ("van der", "de", "von", "da", "van")
#: What G7 is to find one person in, and what it is to find another person in.
_SAME_NAME = ("cased", "accented", "particle", "apostrophe", "umlaut", "umlaut without its dots",
              "hyphen", "suffix", "among the given names")
_OTHER_NAME = ("a letter off", "another name", "initials are no name")
_GIVEN = ("George", "Anna", "Maria", "Jose", "Wei", "Amara")


@st.composite
def _renamed(draw: st.DrawFn) -> list[tuple[str, str, str]]:
    """One family name drawn, written for each way a registry writes the same name and for
    each way another person's differs: every kind in every example, so that a rule broken
    for one kind fails whatever the seed."""
    family, second = draw(st.lists(st.sampled_from(_FAMILIES), min_size=2, max_size=2,
                                   unique=True))  # fmt: skip
    vowels = [at for at, c in enumerate(family) if c in "aeio"]
    at = draw(st.sampled_from(vowels))
    plain, tex, printed = next(a for a in _ACCENTS if a[0] == family[at])
    particle = draw(st.sampled_from(_PARTICLE_FORMS))
    cut = draw(st.integers(1, len(family) - 1))
    letter = draw(st.sampled_from([c for c in "zqxj" if c not in family.casefold()]))
    case = draw(st.sampled_from((str.upper, str.lower, str.title)))
    # Not before an "e": without its dots "Süe" is "Sue", which the folding takes for "Sü"
    # transcribed, and reads as another name (DESIGN.md, Known gaps).
    dot = draw(st.sampled_from([i for i in range(1, len(family)) if family[i] != "e"]))
    umlaut = family[:dot] + "\N{LATIN SMALL LETTER U WITH DIAERESIS}" + family[dot:]
    return [
        ("cased", family, case(family)),
        ("accented", family[:at] + tex + family[at + 1 :],
         family[:at] + printed + family[at + 1 :]),
        ("particle", f"{particle} {family}",
         draw(st.sampled_from((family, f"{particle.title()} {family}")))),
        ("apostrophe", f"O'{family}",
         draw(st.sampled_from((f"O{family}", f"O\N{RIGHT SINGLE QUOTATION MARK}{family}")))),
        ("umlaut", umlaut, family[:dot] + "ue" + family[dot:]),
        ("umlaut without its dots", umlaut, family[:dot] + "u" + family[dot:]),
        ("hyphen", f"{family}-{second}", draw(st.sampled_from((f"{family} {second}", second)))),
        ("suffix", f"{family} Jr.", family),
        # A double surname a registry splits, its first part among the given names:
        # Crossref's given "George Davey", family "Smith", for an entry's "Davey, SG".
        ("among the given names", family, second, f"{draw(st.sampled_from(_GIVEN))} {family}"),
        ("a letter off", family, family[:cut] + letter + family[cut + 1 :]),
        ("another name", family, second),
        ("initials are no name", family, second,
         f"{family[0]}. {draw(st.sampled_from(_GIVEN))[0]}."),
    ]  # fmt: skip


@holds(150, _renamed())
def test_a_family_name_is_one_person_s_however_a_registry_writes_it(
    drawn: list[tuple[str, ...]],
) -> None:
    """G7 holds a cited family name to a registry's by Basile's lenient folding (2026-10-20):
    case, accents written in TeX or in Unicode, a particle, an apostrophe, ü for ue, one part
    of a double name, a suffix and the first part of a double surname a registry filed among
    the given names are one person's; a letter that differs, or another name, is another
    person's."""
    from manuscript_guard.gates import authors

    for kind, cited, registered, *forenames in drawn:
        said = authors.same(cited, registered, *forenames)
        assert said is (kind in _SAME_NAME), (kind, cited, registered, forenames)


# ------------------------------------------------------- a title a search found, each way

#: What G7 is to take for the cited title among a search's works, and what it is not.
_SAME_SEARCHED = ("subtitle left out", "flagged", "typeset", "subtitle cited",
                  "subtitle the registry left out")  # fmt: skip
_OTHER_SEARCHED = ("longer title", "other words")


@st.composite
def _searched_titles(draw: st.DrawFn) -> list[tuple[str, str, str]]:
    """A cited title of drawn words, and for each kind a title a search could return: the
    same title as a registry writes it, and another work's that a search finds because it
    holds the words. Every kind in every example."""
    words = draw(st.lists(st.sampled_from(FILLER), min_size=4, max_size=10))
    cited = " ".join(words)
    subtitle = " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=3, max_size=6)))
    before = draw(st.lists(st.sampled_from(FILLER), min_size=len(words),
                           max_size=len(words) + 3))  # fmt: skip
    other = list(words)
    for at in draw(st.permutations(range(len(words))))[: len(words) * 15 // 85 + 1]:
        other[at] = "zygote" if other[at] != "zygote" else "quorum"
    separator = draw(st.sampled_from((": ", " - ", "? ", " \N{EM DASH} ")))
    case = draw(st.sampled_from((str.upper, str.title)))
    return [
        ("subtitle left out", cited, f"{cited}{separator}{subtitle}"),
        ("flagged", cited, f"RETRACTED: {cited}"),
        ("typeset", cited, case(cited).replace(" ", ", ", 1)),
        ("subtitle cited", f"{cited}: {subtitle}", f"{cited}: {subtitle}"),
        # A guideline printed with its task force in its title, which the registry leaves out.
        ("subtitle the registry left out", f"{cited}: {subtitle}", cited),
        ("longer title", cited, " ".join(before) + " " + cited),
        ("other words", cited, " ".join(other)),
    ]


@holds(150, _searched_titles())
def test_a_searched_title_is_the_cited_one_only_each_way(
    drawn: list[tuple[str, str, str]],
) -> None:
    """For a reference with no identifier, G7 takes a work a search found for the cited one
    only where each title holds 85% of the other's words: the registered title's main part
    only, so that a subtitle the entry left out costs nothing; and a longer title that holds
    every cited word, which a search finds and an identifier never names, is another work."""
    from manuscript_guard.gates import lookups, searched

    for kind, cited, registered in drawn:
        alike = searched.alike(cited, [registered])
        if kind in _SAME_SEARCHED:
            assert alike >= lookups.TITLE_HELD, (kind, cited, registered, alike)
        else:
            assert alike < lookups.TITLE_HELD, (kind, cited, registered, alike)


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
                # Round 1 of #288: not only flat calls. An argument that turns it off given
                # inside a nested call turns nothing off, and given after one it does; a
                # comparison, `==`, names no argument.
                for name, values in rule.unless.items():
                    inner = f"g({name}{equals}{values[0]})"
                    plans.append((f"{call}(d, x{equals}{inner})", not (rule.seeded and seeded)))
                    plans.append((f"{call}(g(d, y), {name}{equals}{values[0]})", False))
                if rule.stated:
                    compared = f"{call}(d, {rule.stated} == 7)"
                    plans.append((compared, not (rule.seeded and seeded)))
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
            # And a script that ends inside a call, its bracket open and an argument's value
            # not yet typed: still a call, and its argument not given.
            stated = [rule for rule in rules()[language] if rule.stated and not rule.seeded]
            rule = draw(st.sampled_from(stated or list(rules()[language])))
            call = _called(draw, rule, language)
            text = "\n".join(lines) + "\n"
            lines.append(f"{call}(d, {rule.stated}{equals}" if rule.stated else f"{call}(d,")
            if not (rule.seeded and seeded):
                expected.append((len(text), call))
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


def _arguments_read(patch: pytest.MonkeyPatch, *, depth: int = 1, compared: bool = False) -> None:
    """`_arguments` with its named arguments read at any depth up to `depth`, and a
    comparison, `==`, read as a name given a value where `compared`."""
    from manuscript_guard.gates import figure_estimates

    def read(code, opening):
        arguments, stack, index, given = {}, [")"], opening + 1, False
        while index < len(code) and stack:
            text = code[index].text
            if code[index].kind == "code" and text in figure_estimates._CLOSES:
                stack.append(figure_estimates._CLOSES[text])
            elif code[index].kind == "code" and text == stack[-1]:
                stack.pop()
            elif len(stack) <= depth:
                given = given or len(stack) == 1
                following = code[index + 1 : index + 3]
                if (code[index].kind == "code" and figure_estimates._is_name(text)
                        and following[:1] and following[0].text == "="
                        and (compared or len(following) < 2 or following[1].text != "=")
                        and index + 2 < len(code)):  # fmt: skip
                    arguments[text] = code[index + 2].text
            index += 1
        return arguments, given

    patch.setattr(figure_estimates, "_arguments", read)


def _a_named_argument_of_a_nested_call_is_the_call_s(patch: pytest.MonkeyPatch) -> None:
    _arguments_read(patch, depth=2)


def _a_comparison_names_an_argument(patch: pytest.MonkeyPatch) -> None:
    _arguments_read(patch, compared=True)


def _a_call_left_open_is_no_call(patch: pytest.MonkeyPatch) -> None:
    # A call counted only once its bracket closes, as a pattern `name\(.*?\)` counts one.
    from manuscript_guard.gates import figure_estimates

    found = figure_estimates.calls_in

    def closes(code, at: int) -> bool:
        depth = 0
        for token in code[at:]:
            if token.kind == "code" and token.text in "([{":
                depth += 1
            elif token.kind == "code" and token.text in ")]}":
                depth -= 1
                if depth == 0:
                    return True
        return False

    def closed(tokens):
        code = [token for token in tokens if token.kind not in ("comment", "docstring")]
        at = {token.start: index for index, token in enumerate(code)}
        return [call for call in found(tokens) if closes(code, at[call.start] + 1)]

    patch.setattr(figure_estimates, "calls_in", closed)


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
    # Round 1 of #249: every way a DOI is dressed, in each example.
    a = identifiers_of({"type": "book", "doi": first["doi"]})
    for dressing in _DOI_DRESSINGS:
        dressed = dressing + first["doi"].upper() + "."
        assert identifiers_of({"type": "book", "doi": dressed}) == a, dressed


#: A resolver with its scheme or without, with `www.` or `dx.`, and the scheme with its
#: colon or without.
_DOI_DRESSINGS = ("https://doi.org/", "http://dx.doi.org/", "https://www.doi.org/", "doi.org/",
                  "dx.doi.org/", "www.doi.org/", "doi:", "doi: ", "DOI ", "")  # fmt: skip


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


def _a_reply_is_read_unmasked(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import numbers

    patch.setattr(numbers, "mask", lambda text: text)


def _a_quote_keeps_its_line_breaks(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import revision

    def kept(text: str) -> str:
        return revision._COMMENT.sub(" ", text).replace("*", "").replace("`", "")

    patch.setattr(revision, "as_quoted", kept)


def _a_nought_is_trimmed_off_a_number(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(tokens, "_TRAIL", tokens._TRAIL + "0")


def _katakana_is_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import scripts

    left = {name: span for name, span in scripts.SCRIPTS.items() if name != "Katakana"}
    patch.setattr(scripts, "_ANY", re.compile("[" + "".join(left.values()) + "]"))


def _a_character_of_two_scripts_is_counted_twice(patch: pytest.MonkeyPatch) -> None:
    from collections import Counter

    from manuscript_guard.gates import scripts

    def counted(text: str) -> Counter[str]:
        found: Counter[str] = Counter()
        for character in scripts._ANY.findall(text):
            found.update(name for name, one in scripts._EACH.items() if one.match(character))
        found["Han"] += 1 if found else 0
        return found

    patch.setattr(scripts, "scripts_in", counted)


def _short_words_are_dropped_from_a_title(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import lookups

    words = lookups.title_words
    patch.setattr(
        lookups, "title_words",
        lambda title: None if words(title) is None else [w for w in words(title) if len(w) > 2],
    )  # fmt: skip


def _a_british_title_is_read_as_written(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import lookups

    patch.setattr(lookups, "_variants", lambda: ({}, frozenset()))


def _a_tag_is_read_as_a_space(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import lookups

    class Spaced:
        def sub(self, _with: str, text: str) -> str:
            return re.sub(r"<[^<>]*>", " ", text)

    patch.setattr(lookups, "_TAGS", Spaced())


def _a_tex_command_takes_the_letters_after_it(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import lookups

    patch.setattr(lookups, "_untex", lambda found: "")


def _a_title_is_compared_both_ways(patch: pytest.MonkeyPatch) -> None:
    """The share both titles have of each other, as a search would compare them: a subtitle
    the entry left out then counts against it."""
    from collections import Counter

    from manuscript_guard.gates import lookups

    def held(cited: str, registered: str) -> float | None:
        mine, theirs = lookups.title_words(cited), lookups.title_words(registered)
        if not mine or theirs is None:
            return None
        both = sum((Counter(mine) & Counter(theirs)).values())
        return both / max(len(mine), len(theirs))

    patch.setattr(lookups, "title_held", held)


def _a_family_name_must_agree_whole(patch: pytest.MonkeyPatch) -> None:
    """The strict option Basile did not take: particles and all."""
    from manuscript_guard.gates import authors

    def whole(a: str, b: str, given: str = "") -> bool:
        return authors.name_words(a) == authors.name_words(b)

    patch.setattr(authors, "same", whole)


def _a_given_name_holds_no_part_of_a_family_name(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import authors

    same = authors.same
    patch.setattr(authors, "same", lambda a, b, given="": same(a, b))


def _an_accent_is_a_letter_of_its_own(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import authors

    patch.setattr(authors, "name_words", lambda family: tuple(re.findall(
        r"[^\W\d_]+", family.replace("{", "").replace("}", "").casefold())))  # fmt: skip


def _ue_is_not_u_umlaut(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import authors

    patch.setattr(authors, "_TRANSCRIPTIONS", ())


def _an_apostrophe_parts_a_name(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import authors

    patch.setattr(authors, "_APOSTROPHES", re.compile(r"(?!)"))


def _a_name_a_letter_off_is_the_name(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import authors

    same = authors.same

    def near(a: str, b: str, given: str = "") -> bool:
        x, y = " ".join(authors.name_words(a)), " ".join(authors.name_words(b))
        one_off = len(x) == len(y) and sum(i != j for i, j in zip(x, y, strict=True)) <= 1
        return same(a, b, given) or one_off

    patch.setattr(authors, "same", near)


def _a_searched_title_is_held_one_way(patch: pytest.MonkeyPatch) -> None:
    """The rule G7 holds an identifier's title to."""
    from manuscript_guard.gates import lookups, searched

    patch.setattr(searched, "alike", lambda cited, titles: max(
        (lookups.title_held(cited, t) or 0.0 for t in titles), default=0.0))  # fmt: skip


def _the_whole_registered_title_is_held_back(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import searched

    patch.setattr(searched, "main_title", lambda title: searched._FLAG.sub("", title))


def _a_cited_subtitle_counts_against_it(patch: pytest.MonkeyPatch) -> None:
    """The rule as it stood before the measurement of 2026-10-20 found two guidelines cited
    with the task force the registries leave out."""
    from manuscript_guard.gates import lookups, searched

    def alike(cited: str, titles: list[str]) -> float:
        best = 0.0
        for title in titles:
            there = lookups.title_held(cited, title)
            back = [b for b in (lookups.title_held(searched._FLAG.sub("", title), cited),
                                lookups.title_held(searched.main_title(title), cited))
                    if b is not None]  # fmt: skip
            if there is not None and back:
                best = max(best, min(there, max(back)))
        return best

    patch.setattr(searched, "alike", alike)


def _an_isbn_10_is_not_read_as_its_isbn_13(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import duplicates

    patch.setattr(duplicates, "isbn_13", lambda written: re.sub(r"[\s-]", "", written).upper())


def _an_isbn_s_groups_are_read_as_isbns(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import identifiers

    patch.setattr(
        identifiers, "_isbns",
        lambda field: [p for p in re.split(r"[,;/]|\s(?=\d{3})", field) if p.strip()],
    )  # fmt: skip


def _a_label_without_brackets_sticks_to_its_isbn(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import identifiers

    patch.setattr(identifiers, "_ISBN_ASIDE",
                  re.compile(r"\bISBN(?:-?1[03])?\s*:?|\([^()]*\)", re.IGNORECASE))  # fmt: skip


def _a_doi_s_resolver_is_undressed_only_as_it_was(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import identifiers

    dressing = re.compile(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)
    patch.setattr(identifiers, "_DOI_DRESSING", dressing)


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


def _a_label_is_read_across_sentences(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import labels

    def everything_before(read, stops, bindings, index):
        return read[max(0, bindings[index][0] - 120) : bindings[index][0]]

    patch.setattr(labels, "_before", everything_before)


def _the_first_level_is_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import labels

    def first(before):
        match = labels._LEVEL.search(before)
        return (match.group(1) or match.group(2)) if match else None

    patch.setattr(labels, "_stated_level", first)


def _levels_are_compared_as_written(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import labels

    patch.setattr(labels, "_same_level", lambda stated, recorded: f"{stated}%" == recorded)


def _a_label_after_a_spread_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import labels

    patch.setattr(labels, "_after", lambda *_args: "")


def _an_abbreviations_stop_never_ends_a_sentence(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import labels

    patch.setattr(labels, "_GOES_ON", re.compile(r""))


def _an_abbreviations_stop_ends_a_sentence(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import labels

    patch.setattr(labels, "_ABBREVIATED", re.compile(r"(?!)"))


def _a_level_after_the_letters_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import labels

    before_only = labels._LEVEL.pattern.split("|(?<![\\w-])")[0]
    assert before_only != labels._LEVEL.pattern
    patch.setattr(labels, "_LEVEL", re.compile(before_only))


def _every_sentence_dates_the_data(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "_SAYS", re.compile(r""))


def _no_sentence_dates_the_data(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "_SAYS", re.compile(r"(?!)"))


def _the_words_of_the_whole_text_are_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "_words", lambda read, stops, placeholders: read)


def _a_binding_s_key_is_read_as_its_sentence_s_words(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_dates

    real = data_dates._words

    def with_keys(read, stops, placeholders):
        return real(read, stops, placeholders) + " " + " ".join(p.raw for p in placeholders)

    patch.setattr(data_dates, "_words", with_keys)


def _a_dataset_s_date_is_taken_for_a_typed_one(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "_DECLARED", frozenset({"parameter"}))


def _a_parameter_s_date_is_taken_for_a_typed_one(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "_DECLARED", frozenset({"dataset"}))


def _a_date_only_its_display_writes_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.dates import parse_iso
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "is_typed_date", lambda value: value.role is None
                  and parse_iso(value.value) is not None)  # fmt: skip


def _a_comment_s_words_are_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "blank_comments", lambda text: text)


def _a_dictionary_s_release_is_taken_for_a_typed_date(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "_DECLARED", frozenset({"dataset", "parameter", "software"}))


def _other_bindings_and_citations_are_read_as_words(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "_NOT_WORDS", re.compile(r"(?!)"))


def _the_words_of_a_period_covered_are_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "_SAYS", re.compile(
        r"(?i)\b(?:extract\w*|download\w*|retriev\w*|snapshots?|quer\w*|access\w*|"
        r"obtain\w*|lock\w*|cut[- ]?offs?|froze\w*|freez\w*)\b"))


def _only_the_forms_first_written_are_read(patch: pytest.MonkeyPatch) -> None:
    """The rule as round 1 of #392 found it: `queries`, `obtaining`, `retrieving` unread."""
    from manuscript_guard.gates import data_dates

    patch.setattr(data_dates, "_SAYS", re.compile(
        r"(?i)\b(?:extract(?:s|ed|ing|ion|ions)?|download(?:s|ed|ing)?|retriev(?:e|ed|al)|"
        r"snapshots?|quer(?:y|ied)|accessed|obtained|locked|lock|cut[- ]?off|frozen|freeze|"
        r"cover(?:s|ed|ing|age)?|span(?:s|ned|ning)?|until|through|up\s+to)\b"))


def _every_stop_is_in_one_sentence(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import numbers

    patch.setattr(numbers, "sentence_stops", lambda _read: [])


def _a_stop_after_s_e_ends_a_quote_s_sentence(patch: pytest.MonkeyPatch) -> None:
    """G2's quotes before round 2 of #327: every stop and a space ended a sentence, so a P
    value after "s.e." was cut from its estimate."""
    from manuscript_guard.gates import numbers

    patch.setattr(numbers, "sentence_stops", lambda read: [
        match.start() for match in numbers._SENTENCE_END.finditer(read)])  # fmt: skip


def _a_share_is_held_to_nothing(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import numbers

    original = numbers.quoted_whole

    def lax(files, namespace):
        said = original(files, namespace)
        return numbers.Report(tuple(f for f in said.findings if "share" not in f.message))

    patch.setattr(numbers, "quoted_whole", lax)


def _an_accession_number_is_no_identifier(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_statement

    patch.setattr(data_statement, "IDENTIFIERS", data_statement.IDENTIFIERS[:1])


def _a_release_is_temporary(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import data_statement

    loose = data_statement.TEMPORARY.pattern.replace("/?(?![\\w/-])", "")
    patch.setattr(data_statement, "TEMPORARY", re.compile(loose, re.IGNORECASE))


def _a_denial_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import data_sources

    patch.setattr(data_sources, "NEGATION", re.compile(r"(?!)"))


def _a_denial_is_read_only_beside_its_phrase(patch: pytest.MonkeyPatch) -> None:
    """In the two words before the phrase, as a window of words read it."""
    from manuscript_guard import data_sources

    def near(sentence: str, phrase: re.Pattern[str]) -> bool:
        found = phrase.search(sentence)
        before = " ".join(sentence[: found.start()].split()[-2:]) if found else ""
        return found is not None and data_sources.NEGATION.search(before) is None

    patch.setattr(data_sources, "says", near)


def _an_open_source_said_after_a_denial_excuses_nothing(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import data_sources

    patch.setattr(data_sources, "mentions", data_sources.says)


def _one_way_of_asking_is_not_read(patch: pytest.MonkeyPatch) -> None:
    """"From the corresponding author" and "by contacting" left out."""
    from manuscript_guard import data_sources

    asked = r"\b(?:up)?on\s+(?:an?\s+)?(?:(?:reasonable|justified)\s+)?requests?\b"
    patch.setattr(data_sources, "ON_REQUEST", re.compile(asked, re.IGNORECASE))


def _a_name_is_found_inside_a_word(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import data_sources
    from manuscript_guard.literature.sources import normalise

    patch.setattr(data_sources, "_on_page",
                  lambda page, name: normalise(name).lower()
                  in normalise(page).lower())  # fmt: skip


def _a_name_is_read_as_typed(patch: pytest.MonkeyPatch) -> None:
    """Its words as the record writes them, not folded for spacing or a line break."""
    from manuscript_guard import data_sources

    def found(page: str, name: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", page.lower()) is not None

    patch.setattr(data_sources, "_on_page", found)


def _placeholder_rule(patch: pytest.MonkeyPatch, rule_id: str, change) -> None:
    from dataclasses import replace

    from manuscript_guard.gates import writing

    rules = writing.load_rules()
    artefacts = tuple(
        {**rule, "pattern": change(rule["pattern"])} if rule["id"] == rule_id else rule
        for rule in rules.artefacts
    )
    patch.setattr(writing, "load_rules", lambda: replace(rules, artefacts=artefacts))


def _a_karyotype_is_a_placeholder(patch: pytest.MonkeyPatch) -> None:
    _placeholder_rule(
        patch, "placeholder-word", lambda p: p.replace("(?<!\\b4[5-9],)(?<!\\b4[5-9], )", "")
    )


def _a_word_in_lower_case_is_a_placeholder_anywhere(patch: pytest.MonkeyPatch) -> None:
    _placeholder_rule(patch, "placeholder-word", lambda p: "(?i)" + p)


def _a_links_text_is_a_slot(patch: pytest.MonkeyPatch) -> None:
    # The lookahead that ends the rule, which keeps a link's text and its definition out.
    _placeholder_rule(patch, "placeholder-slot", lambda p: p[: p.rindex("(?!")])


def _filler_ends_only_at_a_stop_a_blank_line_or_the_end(patch: pytest.MonkeyPatch) -> None:
    def without_a_list_item(pattern: str) -> str:
        item = r"[-*+][ \t]|\d+[.)][ \t]|"
        assert item in pattern, "the rule no longer ends at a list item this way"
        return pattern.replace(item, "")

    _placeholder_rule(patch, "placeholder-filler", without_a_list_item)


def _an_instruction_marked_or_linked_is_a_link_s_text(patch: pytest.MonkeyPatch) -> None:
    # The lookahead the slot rule ends with, as the instruction rule had it in round 2 of #262.
    _placeholder_rule(patch, "placeholder", lambda p: p + r"(?![(\[{])")


def _in_the_template_rule(patch: pytest.MonkeyPatch, written: str, broken: str) -> None:
    def change(pattern: str) -> str:
        assert written in pattern, "the template rule no longer reads this way"
        return pattern.replace(written, broken)

    _placeholder_rule(patch, "placeholder-template", change)


def _words_prompt_is_read_without_what_it_asks_for(patch: pytest.MonkeyPatch) -> None:
    # "Click here" alone heads each file PLOS lists under a paper.
    _in_the_template_rule(patch, r"(?:here\s+)?to\s+enter\s+(?:text|a\s+date)\.", r"here\b")


def _any_request_after_in_this_section_is_a_template_s(patch: pytest.MonkeyPatch) -> None:
    # As the rule read it before round 1, and with any verb: a questionnaire asks so too.
    _in_the_template_rule(
        patch,
        r"(?:you\s+can\s+acknowledge\s+any\s+support",
        r"(?:(?:you\s+\w+|please)\s+\w+|you\s+can\s+acknowledge\s+any\s+support",
    )


def _any_quoted_word_after_please_state_is_a_statement(patch: pytest.MonkeyPatch) -> None:
    _in_the_template_rule(patch, r"(?:this\s+research|", r"(?:\w+|this\s+research|")


def _residue_rule(patch: pytest.MonkeyPatch, rule_id: str, change) -> None:
    """The residue rule `rule_id` as `change` makes it, given the rule and returning it."""
    from dataclasses import replace

    from manuscript_guard.gates import writing

    rules = writing.load_rules()
    residue = tuple(change(rule) if rule["id"] == rule_id else rule for rule in rules.residue)
    assert residue != rules.residue, f"{rule_id} is not a residue rule"
    patch.setattr(writing, "load_rules", lambda: replace(rules, residue=residue))


def _the_reviewers_are_one_reviewer(patch: pytest.MonkeyPatch) -> None:
    # The end of a word after "the reviewer", which keeps "the reviewers" out of it.
    def plural_too(rule: dict) -> dict:
        one = r"(?:reviewer|referee|editor(?:-in-chief)?)\b(?!"
        assert one in rule["pattern"], "the rule no longer ends one reviewer this way"
        return {**rule, "pattern": rule["pattern"].replace(one, one[:-5] + "(?!")}

    _residue_rule(patch, "reviewer-answered", plural_too)


def _a_blank_line_ends_no_phrase(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import writing

    patch.setattr(writing, "_paragraphs", lambda text: [(0, len(text))])


def _the_acknowledgements_are_read(patch: pytest.MonkeyPatch) -> None:
    def without_thanks(rule: dict) -> dict:
        return {**rule, "exempt": [e for e in rule["exempt"] if "grateful" not in e]}

    _residue_rule(patch, "earlier-version-unnamed", without_thanks)


def _the_contributions_are_read(patch: pytest.MonkeyPatch) -> None:
    def without_contributions(rule: dict) -> dict:
        return {**rule, "exempt": [e for e in rule["exempt"] if "approv" not in e]}

    _residue_rule(patch, "earlier-version-unnamed", without_contributions)


def _a_dossier_is_a_submission(patch: pytest.MonkeyPatch) -> None:
    def without_its_end(rule: dict) -> dict:
        end = r"(?!\s+(?:to|of|for)\b)"
        assert end in rule["pattern"], "the rule no longer ends a submission this way"
        return {**rule, "pattern": rule["pattern"].replace(end, "")}

    _residue_rule(patch, "earlier-version-unnamed", without_its_end)


def _a_change_is_named_mid_clause(patch: pytest.MonkeyPatch) -> None:
    # The end of a clause the rule waits for, which keeps "included in the SmPC" out.
    def without_the_end(rule: dict) -> dict:
        end = r"(?=\s*(?:[.;:!?)]|$))"
        assert end in rule["pattern"], "the rule no longer waits for the end of a clause"
        return {**rule, "pattern": rule["pattern"].replace(end, "")}

    _residue_rule(patch, "text-edited-unnamed", without_the_end)


def _lines_in_capitals_are_lines(patch: pytest.MonkeyPatch) -> None:
    def in_any_case(rule: dict) -> dict:
        return {**rule, "pattern": "(?i)" + rule["pattern"]}

    _residue_rule(patch, "lines-cited-alone", in_any_case)


def _a_field_wholly_in_brackets_is_read_without_them(patch: pytest.MonkeyPatch) -> None:
    # As `_untranslated` read a cited entry's field, until round 2 of #262.
    from manuscript_guard.gates import writing

    read = writing.artefacts_in

    def unbracketed(rules, text, *, manuscript):
        if not manuscript and text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        return read(rules, text, manuscript=manuscript)

    patch.setattr(writing, "artefacts_in", unbracketed)


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


def _a_planned_item_runs_past_its_paragraph(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import design

    patch.setattr(design, "_BLANK_LINE", re.compile(r"(?!)"))


def _code_with_no_dot_is_a_planned_key(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import design

    undotted = re.compile(r"(?:results\.)?([A-Za-z_][\w-]*(?:\.[\w-]+)*)")
    patch.setattr(design, "_PLANNED_KEY", undotted)


def _a_bound_key_keeps_its_namespace(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import design

    patch.setattr(design, "_PLANNED_KEY", re.compile(r"([A-Za-z_][\w-]*(?:\.[\w-]+)+)"))


def _a_bound_key_needs_a_dot(patch: pytest.MonkeyPatch) -> None:
    """The rule as it stood at b7235875: the prefix gave way to a key with no dot."""
    from manuscript_guard.gates import design

    dotted = re.compile(r"(?:results\.)?([A-Za-z_][\w-]*(?:\.[\w-]+)+)")
    patch.setattr(design, "_PLANNED_KEY", dotted)


def _the_planned_results_subsections_are_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import design

    patch.setattr(design, "subsections", lambda sections, index: [sections[index]])


def _the_deviations_name_variables(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import collection

    patch.setattr(collection, "_deviations", lambda text: [])


def _the_deviations_end_at_their_first_subsection(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import collection

    def own_text_only(text: str) -> list[tuple[int, int]]:
        headings = collection.find_headings(text)
        return [(h.start, headings[i + 1].start if i + 1 < len(headings) else len(text))
                for i, h in enumerate(headings) if collection.is_deviations(h.title)]  # fmt: skip

    patch.setattr(collection, "_deviations", own_text_only)


def _the_plan_s_title_may_be_its_deviations(patch: pytest.MonkeyPatch) -> None:
    """The rule as it stood before round 1: the title was a heading like any other."""
    from manuscript_guard.gates import collection

    def every_heading(text: str) -> list[tuple[int, int]]:
        headings = collection.find_headings(text)
        return [(h.start, next((later.start for later in headings[i + 1:]
                                if later.level <= h.level), len(text)))
                for i, h in enumerate(headings) if collection.is_deviations(h.title)]  # fmt: skip

    patch.setattr(collection, "_deviations", every_heading)


def _the_deviations_run_to_the_next_section(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import collection

    def to_a_section(text: str) -> list[tuple[int, int]]:
        headings = collection.find_headings(text)
        return [(h.start, next((later.start for later in headings[i + 1:]
                                if later.level <= 2), len(text)))
                for i, h in enumerate(headings[1:], 1)
                if collection.is_deviations(h.title)]  # fmt: skip

    patch.setattr(collection, "_deviations", to_a_section)


def _any_heading_with_a_change_s_word_is_the_deviations(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import collection

    patch.setattr(collection, "is_deviations",
                  lambda title: bool(re.search(collection._DEVIATIONS, title)))  # fmt: skip


def _a_heading_that_names_the_planned_results_is_never_the_deviations(
    patch: pytest.MonkeyPatch,
) -> None:
    from manuscript_guard.gates import collection
    from manuscript_guard.gates.design import PLANNED

    patch.setattr(collection, "is_deviations",
                  lambda title: bool(re.search(collection._DEVIATIONS, title))
                  and not re.search(PLANNED, title))  # fmt: skip


def _code_in_brackets_is_a_variable(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import collection

    patch.setattr(collection, "VARIABLE", re.compile(r"[A-Za-z][A-Za-z0-9_():]*"))


def _a_value_in_backticks_is_a_variable(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import collection

    patch.setattr(collection, "LITERALS", frozenset())


def _a_dotted_name_is_never_a_variable(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import collection

    reads_as = collection._reads_as
    patch.setattr(collection, "_reads_as",
                  lambda said, known: None if "." in said else reads_as(said, known))  # fmt: skip


def _a_variable_is_matched_without_its_case(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import collection

    reads_as = collection._reads_as

    def folded(said: str, known) -> str | None:
        if said.casefold() in {name.casefold() for name in known}:
            return "used"
        return reads_as(said, known)

    patch.setattr(collection, "_reads_as", folded)


def _a_variable_is_said_at_its_last_mention(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import collection

    patch.setattr(collection, "_first", lambda found, named: found.update({named.name: named}))


def _fences_and_comments_name_variables(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import collection

    patch.setattr(collection, "mask", lambda text: text)


def _a_variables_name_is_a_word(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(spelling_gate, "_in_an_identifier", lambda text, start, end: False)


def _a_list_of_pointers_is_its_first(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import pointers

    patch.setattr(
        pointers, "_numbers",
        lambda found: [(bool(found["s0"]), int(found["n0"]), found.start("n0"))],
    )  # fmt: skip


def _the_supplement_s_tables_are_the_paper_s(patch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from manuscript_guard.gates import pointers

    read = pointers.pointers_in
    patch.setattr(
        pointers, "pointers_in",
        lambda text, path, *numbers: [
            replace(p, supplementary=False) for p in read(text, path, *numbers)
        ],
    )


def _a_figure_placed_by_hand_is_counted_anyway(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import pointers

    patch.setattr(pointers, "_BY_HAND", {**pointers._BY_HAND, "figure": re.compile(r"(?!)")})


def _a_figure_sent_as_a_file_is_not_counted(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import pointers

    patch.setattr(pointers, "AS_FILES", {key: "unread" for key in pointers.AS_FILES})


def _one_figure_more_is_counted_than_the_supplement_carries(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import pointers

    placed = pointers.placed_in

    def one_more(text: str):
        found = placed(text)
        figures = (("figure", "f0"),) if any(k == "figure" for k, _ in found.bound) else ()
        return type(found)(found.bound + figures, found.by_hand)

    patch.setattr(pointers, "placed_in", one_more)


def _a_bound_pointer_points_where_its_binding_does(patch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from manuscript_guard.crossref import Display
    from manuscript_guard.gates import pointers

    read = pointers.pointers_in

    def as_named(text: str, path: Path, numbers=None):
        found = []
        for pointer in read(text, path, numbers):
            named = numbers.display(pointer.binding) if numbers and pointer.binding else None
            if isinstance(named, Display):
                pointer = replace(pointer, kind=named.kind, supplementary=named.supplementary)
            found.append(pointer)
        return found

    patch.setattr(pointers, "pointers_in", as_named)


def _displays_are_numbered_in_the_order_of_their_paths(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import pointers

    patch.setattr(pointers, "printed_order", lambda paths, supplementary: sorted(paths))


def _the_supplement_s_displays_are_numbered_with_the_paper_s(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import pointers

    patch.setattr(pointers, "is_supplementary", lambda root, path: False)


def _a_caption_is_not_held_to_its_display(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.findings import Report
    from manuscript_guard.gates import pointers

    patch.setattr(pointers, "_captions", lambda *given: Report())


def _a_table_s_caption_is_read_only_under_it(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import pointers

    patch.setattr(pointers, "_BESIDE", {pointers.FIGURE: (1,), pointers.TABLE: (1,)})


def _a_caption_between_two_tables_is_held_to_both(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import pointers

    patch.setattr(pointers, "_NAMES_ONE", all)


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


def _the_methods_are_taken_in_the_order_they_stand(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import journal
    from manuscript_guard.text import section_names

    found = section_names.methods_sections

    def in_order(sections, abstract_title=None):
        return sorted(found(sections, abstract_title), key=lambda section: section.line)

    patch.setattr(methods_gate, "methods_sections", in_order)
    patch.setattr(journal, "methods_sections", in_order)


def _the_methods_name_is_read_as_typed(patch: pytest.MonkeyPatch) -> None:
    # The sort as it was before round 3 of #246: by the title as typed.
    from manuscript_guard.classify import METHODS_SECTIONS
    from manuscript_guard.gates import journal
    from manuscript_guard.text import section_names

    found = section_names.methods_sections

    def as_typed(sections, abstract_title=None):
        standing = sorted(found(sections, abstract_title), key=lambda section: section.line)
        return sorted(standing, key=lambda section: METHODS_SECTIONS.match(section.title) is None)

    patch.setattr(methods_gate, "methods_sections", as_typed)
    patch.setattr(journal, "methods_sections", as_typed)


def _no_supplement_names_the_methods(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard import classify

    patch.setattr(classify, "SUPPLEMENT_METHODS", re.compile(r"(?!)"))


def _a_supplement_s_name_with_words_after_it_is_no_methods(patch: pytest.MonkeyPatch) -> None:
    # The name and its number alone: "eMethods 1. Data source" is not the Methods.
    from manuscript_guard import classify

    was = classify.SUPPLEMENT_METHODS.pattern
    pattern = was.replace(r"(?:[^\w\n][^\n]*)?$", r"\s*$")
    assert pattern != was
    patch.setattr(classify, "SUPPLEMENT_METHODS", re.compile(pattern, re.IGNORECASE))


def _only_the_first_of_a_supplement_s_methods_is_read(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(methods_gate, "supplement_methods_in", methods_gate.methods_in)


def _a_section_under_one_read_is_read_again(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text.sections import split_sections

    def every(text: str, abstract_title: str | None = None) -> str | None:
        found = methods_gate.methods_sections(split_sections(text), abstract_title)
        return "\n\n".join(section.enclosed for section in found) or None

    patch.setattr(methods_gate, "supplement_methods_in", every)


def _a_supplement_s_name_holds_every_section_under_it(patch: pytest.MonkeyPatch) -> None:
    # As first written in #395: under "Supplementary methods", a table was the Methods.
    from manuscript_guard import classify

    def any_title(section) -> bool:
        return any(
            classify.names_supplement_methods(title)
            for title in section
            if not isinstance(title, classify.Unprinted)
        )

    patch.setattr(classify, "_opened_by_the_supplement", any_title)


def _g9_reads_all_under_a_supplement_s_methods(patch: pytest.MonkeyPatch) -> None:
    # As first written in #395: each section found, with everything under it, once.
    from manuscript_guard.text.sections import split_sections

    def enclosed(text: str, abstract_title: str | None = None) -> str | None:
        sections = split_sections(text)
        found = {id(section) for section in methods_gate.methods_sections(sections, abstract_title)}
        read: list[str] = []
        under: int | None = None
        for section in sections:
            if under is not None and section.level > under:
                continue
            under = None
            if id(section) in found:
                read.append(section.enclosed)
                under = section.level
        return "\n\n".join(read) if read else None

    patch.setattr(methods_gate, "supplement_methods_in", enclosed)


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
    patch.setattr(blinding, "_words",
                  lambda piece, flags=0, *, latex=False: real(piece, latex=latex))  # fmt: skip


def _an_initial_needs_no_stop(patch: pytest.MonkeyPatch) -> None:
    def name(given: str, family: str, *, latex: bool = False) -> re.Pattern[str]:
        initial, surname = re.escape(given[0]), blinding._spaced(family)
        return re.compile(
            rf"(?<!\w)(?:{blinding._spaced(given)}\s+{surname}|{initial}(?:\.\s*|\s+)"
            rf"{surname}|{surname},?\s+{initial}[A-Z]?\.?)(?!\w)"
        )

    patch.setattr(blinding, "_name", name)


def _an_apostrophe_is_matched_as_typed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(
        blinding, "_spaced",
        lambda words, *, latex=False: r"\s+".join(re.escape(w) for w in words.split()),
    )


def _a_name_is_not_read_family_name_first(patch: pytest.MonkeyPatch) -> None:
    def name(given: str, family: str, *, latex: bool = False) -> re.Pattern[str]:
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


def _a_class_of_claim_words_is_not_counted(patch: pytest.MonkeyPatch, kind: str) -> None:
    patch.setattr(
        claims_module, "COUNTED", tuple(one for one in claims_module.COUNTED if one != kind)
    )


def _the_ladder_is_read_upside_down(patch: pytest.MonkeyPatch) -> None:
    read = claims_module._ladder
    turned = {claims_module.STRONGER: claims_module.WEAKER}
    turned[claims_module.WEAKER] = claims_module.STRONGER
    def ladder(was: list[int], now: list[int]) -> str:
        return turned.get(read(was, now), claims_module.MOVED)

    patch.setattr(claims_module, "_ladder", ladder)


def _a_ladder_word_that_only_came_or_left_is_a_claim_moved(patch: pytest.MonkeyPatch) -> None:
    read = claims_module._ladder

    def ladder(was: list[int], now: list[int]) -> str:
        both = (Counter(was) - Counter(now)) and (Counter(now) - Counter(was))
        return read(was, now) if both else claims_module.MOVED

    patch.setattr(claims_module, "_ladder", ladder)


def _a_ladder_word_made_another_of_its_rung_is_a_change(patch: pytest.MonkeyPatch) -> None:
    beyond = claims_module._beyond

    def by_word(words: list[Any], other: list[Any], by_rung: bool = False) -> list[Any]:
        return beyond(words, other)

    patch.setattr(claims_module, "_beyond", by_word)


def _a_capital_is_read_anywhere(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(claims_module, "_capital", lambda word, typed, opens: True)


def _a_capital_is_never_read(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(claims_module, "_capital", lambda word, typed, opens: False)


def _a_participle_after_an_article_is_read(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(claims_module, "_ARTICLE", re.compile("(?!)"))


def _a_word_in_a_compound_is_read(patch: pytest.MonkeyPatch) -> None:
    edges = (r"\b", r"\b")
    patch.setattr(claims_module, "lists", cache(lambda: claims_module.read_lists(edges)))


def _inline_code_is_read_as_prose(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(claims_module, "code_spans", lambda read: [])


def _a_comment_is_read_as_prose(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(claims_module, "mask", lambda text: text)


def _a_deleted_stretch_is_left_out(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(markedup_writer._Emitter, "deleted", lambda self, atoms: None)


def _deleted_text_is_written_as_text_kept(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(markedup_writer, "deleted_text", lambda element: element)


def _how_a_word_looks_is_not_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(markedup_atoms, "look", lambda run: "")


def _a_row_is_not_tracked_as_a_row(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(markedup_writer, "_row_change", lambda row, change: None)


def _a_note_is_kept_as_the_revision_has_it(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(markedup_writer.Writer, "_note_merged", lambda self, old, new: None)


def _a_table_is_never_merged_cell_by_cell(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(markedup_writer, "_shape", lambda table: None)


def _a_deleted_picture_points_where_it_pointed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(markedup_package.Carried, "_relationship", lambda self, rid, part: rid)


def _a_style_is_not_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(markedup_writer, "_properties_key", lambda paragraph, package: ())


def _nothing_is_alike_enough_to_be_edited(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(markedup_align, "alike", lambda a, b: 0.0)


def _the_texts_are_lined_up_by_place_alone(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(claims_module, "_chain", lambda anchors: [])


def _a_stop_ends_no_sentence_of_a_claim(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(claims_module, "_STOP", re.compile("(?!)"))


def _a_line_that_opens_a_block_opens_no_sentence(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(claims_module, "_BLOCK", re.compile("(?!)"))


def _block_opens_no_sentence_at(patch: pytest.MonkeyPatch, kind: str, read_as: str) -> None:
    pattern = claims_module._BLOCK.pattern
    assert kind in pattern, pattern
    patch.setattr(claims_module, "_BLOCK", re.compile(pattern.replace(kind, read_as)))


def _the_front_matter_is_read_as_one_line(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(claims_module, "front_matter_end", lambda text: 0)


def _may_is_read_with_a_capital_where_it_opens_a_sentence(patch: pytest.MonkeyPatch) -> None:
    def capital(word: str, typed: str, opens: bool) -> bool:
        return opens and typed[1:] == typed[1:].lower()

    patch.setattr(claims_module, "_capital", capital)


def _the_lowest_rung_kept_is_a_claim_made_weaker(patch: pytest.MonkeyPatch) -> None:
    read = claims_module._ladder

    def ladder(was: list[int], now: list[int]) -> str:
        both = (Counter(was) - Counter(now)) and (Counter(now) - Counter(was))
        if not both and was and now and min(was) == min(now):
            return claims_module.WEAKER
        return read(was, now)

    patch.setattr(claims_module, "_ladder", ladder)


def _a_split_sentence_is_compared_by_place(patch: pytest.MonkeyPatch) -> None:
    stretch = claims_module._stretch

    def by_place(was: list[Any], now: list[Any]) -> list[Any]:
        if not was or not now or len(was) == len(now):
            return stretch(was, now)
        return [((one,), (other,)) for one, other in zip(was, now, strict=False)]

    patch.setattr(claims_module, "_stretch", by_place)


def _a_sentence_added_whole_is_read(patch: pytest.MonkeyPatch) -> None:
    stretch = claims_module._stretch

    def read(was: list[Any], now: list[Any]) -> list[Any]:
        if was and now:
            return stretch(was, now)
        return [((), tuple(now))] if now else []

    patch.setattr(claims_module, "_stretch", read)


def _a_footnote_is_read_where_it_is_defined(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text import sections

    patch.setattr(sections, "footnote_index", lambda text, unreferenced=False: [])


def _a_tables_caption_is_compared_where_pandoc_does_not_write_it(
    patch: pytest.MonkeyPatch,
) -> None:
    from manuscript_guard.build import latex_out

    patch.setattr(latex_out, "_CAPTION", re.compile(r"(?!)"))


def _a_lists_numbers_are_read_as_typed(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text import blocks

    patch.setattr(blocks, "list_items", lambda text: [])


def _a_figures_alternative_text_is_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.build import latex_out

    patch.setattr(latex_out, "_FIGURE", re.compile(r"(?!)(?P<alt>)"))


def _a_footnote_is_read_at_its_first_mark_only(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text import sections

    found = sections.footnote_index
    patch.setattr(sections, "footnote_index", lambda text, unreferenced=False: [
        dataclasses.replace(note, references=note.references[:1])
        for note in found(text, unreferenced=unreferenced)])  # fmt: skip


def _a_bare_address_is_read_in_latex(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text import masking

    patch.setattr(masking, "_URL", re.compile(r"(?!)"))


def _a_yaml_block_is_read_as_text(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text import masking

    patch.setattr(masking, "metadata_blocks", lambda text: [])


def _a_mark_with_no_note_is_read_as_a_mark(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.build import latex_out

    patch.setattr(latex_out, "_NOTE_MARK", re.compile(r"(?!)(?P<label>)"))


def _a_narrative_locator_is_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.build import latex_out

    patch.setattr(latex_out, "_LOCATOR", re.compile(r"(?!)"))


def _a_note_nothing_marks_is_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text import sections

    found = sections.footnote_index
    patch.setattr(sections, "footnote_index", lambda text, unreferenced=False: found(text))


def _a_sign_written_as_a_command_ends_an_address(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.build import latex_out

    patch.setattr(latex_out, "_PRINTED_SIGN", re.compile(r"(?!)"))


def _an_address_takes_in_what_follows_it(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.build import latex_out

    found = latex_out.addresses
    patch.setattr(latex_out, "addresses", lambda body, reading: [
        (start, end + 6) for start, end in found(body, reading)])


def _a_repeated_table_header_is_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.build import latex_out

    patch.setattr(latex_out, "_REPEATED", re.compile(r"(?!)(?P<head>)"))


def _no_difference_in_digits_is_seen(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.build import latex_out

    patch.setattr(latex_out, "compare_digits", lambda *_args, **_kwargs: None)


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

    def claims_in(text: str, *rest: Any) -> Any:
        found, bare = real(text, *rest)
        starts = [start for start, _end in methods_gate._paragraphs(text, *rest)]
        return [
            (steps, max(s for s in starts if s <= start), end, anchor)
            for steps, start, end, anchor in found
        ], bare

    patch.setattr(methods_gate, "claims_in", claims_in)


def _anchors_side_by_side_claim_apart(patch: pytest.MonkeyPatch) -> None:
    real = methods_gate.claims_in

    def claims_in(text: str, *rest: Any) -> Any:
        found, bare = real(text, *rest)
        apart = []
        for steps, start, end, anchor in found:
            apart.append((steps[:1], start, end, anchor))
            apart += [((step,), end, end, anchor) for step in steps[1:]]
        return apart, bare

    patch.setattr(methods_gate, "claims_in", claims_in)


def _a_comment_line_ends_a_paragraph(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.text.masking import blank_comments

    real = methods_gate._paragraphs
    patch.setattr(methods_gate, "_paragraphs",
                  lambda text, *rest: real(blank_comments(text), *rest))  # fmt: skip


def _a_claim_keeps_the_words_of_a_comment(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(methods_gate, "blank_comments", lambda text: text)


def _a_numbered_results_heading_is_no_results(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reported_gate, "names_results", lambda title: title in ("Results", "Findings"))


def _the_abstracts_results_report(patch: pytest.MonkeyPatch) -> None:
    def place(self: reported_gate.Walk) -> object:
        if any(id(section) in self.reports for section in self.chain):
            return reported_gate.REPORTED
        for section in self.chain:
            if section.names_abstract(self.named) or id(section) in self.summaries:
                return section.title
        return None

    patch.setattr(reported_gate.Walk, "_place", place)


def _the_headings_of_a_file_are_not_carried_into_the_next(patch: pytest.MonkeyPatch) -> None:
    real = reported_gate.Walk.read

    def read(self: reported_gate.Walk, text: str) -> tuple[list, set[str]]:
        self.chain.clear()
        return real(self, text)

    patch.setattr(reported_gate.Walk, "read", read)


def _a_title_over_the_paper_is_its_results(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reported_gate.Walk, "_opens", lambda self, section, methods: False)


def _an_abstract_over_a_background_is_a_title_over_the_paper(patch: pytest.MonkeyPatch) -> None:
    # The test a Results heading is put to, over the opening of the paper, put to the
    # abstract as well: the Lancet's "Summary" with no profile, made every abstract's.
    from manuscript_guard.text.sections import subsections

    place = reported_gate.Walk._place

    def titled(self: reported_gate.Walk) -> object:
        for section in self.chain:
            at = next(i for i, kept in enumerate(self.kept) if kept is section)
            below = subsections(self.kept, at)[1:]
            if section.names_abstract(self.named) and any(
                reported_gate._OPENING.match(other.title) for other in below
            ):
                return None
        return place(self)

    patch.setattr(reported_gate.Walk, "_place", titled)


def _the_methods_report_nothing(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(reported_gate, "methods_sections", lambda sections, named=None: [])


def _a_quotation_is_in_straight_marks_only(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(quotations_gate, "_QUOTED", re.compile(r'"([^"\n]+(?:\n[^"\n]+)*)"()'))


def _a_quotation_takes_its_paragraphs_citations(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.checking import produce

    patch.setattr(produce, "_split", lambda flat: [flat])


def _a_quotation_in_a_comment_is_read(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(quotations_gate, "blank_comments", lambda text: text)


def _a_quotation_is_looked_for_whole(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.literature.sources import contains

    patch.setattr(quotations_gate, "quoted_in", contains)


def _the_pieces_of_a_quotation_are_looked_for_anywhere(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.literature.sources import contains

    def anywhere(text: str, quote: str) -> bool:
        pieces = [p for p in quotations_gate._ELIDED.split(quote) if p.strip()]
        return all(contains(text, piece) for piece in pieces)

    patch.setattr(quotations_gate, "quoted_in", anywhere)


def _a_word_broken_at_a_line_end_is_two(patch: pytest.MonkeyPatch) -> None:
    joiners = recycling_gate._JOINERS + recycling_gate._APOSTROPHES
    patch.setattr(recycling_gate, "_WORD", re.compile(rf"[^\W_]+(?:[{joiners}][^\W_]+)*"))


def _words_read(fold: Any, *, numbers: bool = False) -> Any:
    """`recycling.words` with another folding of a word's letters, or keeping its digits."""

    def read(text: str) -> list:
        found = []
        for match in recycling_gate._WORD.finditer(text):
            word = fold(recycling_gate._JOINS.sub("", match.group()))
            while not numbers and word and word[-1].isdigit():
                word = word[:-1]
            if word:
                found.append(recycling_gate.Word(word, match.start(), match.end()))
        return found

    return read


def _a_ligature_is_a_letter_of_its_own(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(recycling_gate, "words", _words_read(str.lower))


def _a_number_is_a_word(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(recycling_gate, "words", _words_read(str.casefold, numbers=True))


def _eleven_shared_words_are_reported(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(recycling_gate, "SHARED", 11)


def _a_quotation_is_recycled_text(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(recycling_gate, "_quoted_spans", lambda seen: [])


def _a_word_changed_ends_the_passage(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(recycling_gate, "GAP", 0)


def _a_heading_is_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(recycling_gate, "find_headings", lambda text: [])


def _a_statement_under_the_methods_is_the_methods(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(recycling_gate, "_part_of", lambda chain: next(
        (part for part in chain if part is not None), recycling_gate.UNNAMED))  # fmt: skip


def _a_heading_opening_with_a_statement_s_word_is_one(patch: pytest.MonkeyPatch) -> None:
    # A statement's heading read by its first words, as rounds 2 and 3 of the review found it
    # read: "Funding sources of the included trials" under the Results was set apart.
    patch.setattr(recycling_gate, "_STATEMENTS",
                  re.compile(recycling_gate._STATEMENT_NAMES, re.IGNORECASE))  # fmt: skip


def _a_theme_of_the_results_is_a_statement(patch: pytest.MonkeyPatch) -> None:
    # Round 4 of the review: "Data sharing" under the Results was read as a statement.
    def part_of(chain: list) -> str:
        if recycling_gate.STATEMENT in chain:
            return recycling_gate.STATEMENT
        return next((part for part in chain if part is not None), recycling_gate.UNNAMED)

    patch.setattr(recycling_gate, "_part_of", part_of)


def _a_statement_is_set_apart(patch: pytest.MonkeyPatch) -> None:
    # What rounds 1 to 4 had, before Basile chose a note: a statement is not compared.
    part_of = recycling_gate._part_of

    def set_apart(chain: list) -> str:
        found = part_of(chain)
        return recycling_gate.SET_APART if found == recycling_gate.STATEMENT else found

    patch.setattr(recycling_gate, "_part_of", set_apart)


def _the_reference_list_is_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(recycling_gate, "_REFERENCES", re.compile(r"(?!)"))


def _the_conclusions_are_a_part_of_their_own(patch: pytest.MonkeyPatch) -> None:
    # Before round 4 of the review: the Discussion over its conclusions was a title.
    patch.setattr(recycling_gate, "_COUNTED_AS", {})


def _a_supplement_s_heading_names_no_part(patch: pytest.MonkeyPatch) -> None:
    # Before round 7 of the review: "Supplementary discussion" named no part.
    patch.setattr(recycling_gate, "_SUPPLEMENT_PART", re.compile(r"(?!)"))


def _a_supplement_s_prefix_comes_off_any_heading(patch: pytest.MonkeyPatch) -> None:
    # Round 7's fix, which round 8 found read "Online discussion forums" as the Discussion.
    patch.setattr(recycling_gate, "_SUPPLEMENT_PART", re.compile(
        r"(?:(?i:supplement(?:ary|al)|online)\s+|e(?=[A-Z][a-z]))(?P<part>.*)"))  # fmt: skip


def _sic_is_a_word_of_the_source(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(quotations_gate, "_SIC", re.compile(r"(?!)"))


def _sic_leaves_words_out(patch: pytest.MonkeyPatch) -> None:
    # As the change first had it: [sic] split the quotation as an elision does.
    pattern = quotations_gate._ELIDED.pattern.replace(r"|\.\.\.)", r"|\.\.\.|\[sic\])")
    assert pattern != quotations_gate._ELIDED.pattern, "the elision rule changed its shape"
    patch.setattr(quotations_gate, "_ELIDED", re.compile(pattern, re.IGNORECASE))
    patch.setattr(quotations_gate, "_SIC", re.compile(r"(?!)"))


def _a_piece_may_stand_inside_a_word(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(quotations_gate, "_as_words", lambda text, piece, at: text.find(piece, at))


def _a_citation_key_stops_at_a_colon(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(quotations_gate, "_KEY", re.compile(r"(?<![\w.])@([A-Za-z](?:[\w.-]*\w)?)"))


def _a_heading_is_part_of_the_paragraph_under_it(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(methods_gate, "_HEADING", re.compile(r"(?!)"))


def _a_unit_is_read_after_a_plain_space_only(patch: pytest.MonkeyPatch) -> None:
    pattern = bound_units_gate._UNIT.pattern.replace(bound_units_gate._GAP, " ?", 1)
    patch.setattr(bound_units_gate, "_UNIT", re.compile(pattern))


def _a_unit_is_read_after_a_space_character_only(patch: pytest.MonkeyPatch) -> None:
    """The gap before round 1 of #279: spaces of three widths, and no escaped space,
    entity, comment, hair or figure space."""
    old = "[ \t\N{NO-BREAK SPACE}\N{THIN SPACE}\N{NARROW NO-BREAK SPACE}]"
    assert bound_units_gate._SPACE in bound_units_gate._UNIT.pattern
    pattern = bound_units_gate._UNIT.pattern.replace(bound_units_gate._SPACE, old)
    patch.setattr(bound_units_gate, "_UNIT", re.compile(pattern))


def _a_comment_in_the_gap_runs_on_to_the_next(patch: pytest.MonkeyPatch) -> None:
    """The comment of round 1 of #279's gap, lazy but free to reach past its own end."""
    comment = r"<!--(?:(?!-->)(?!\n[ \t]*\n)[\s\S])*-->"
    assert comment in bound_units_gate._UNIT.pattern
    pattern = bound_units_gate._UNIT.pattern.replace(comment, r"<!--[\s\S]*?-->")
    patch.setattr(bound_units_gate, "_UNIT", re.compile(pattern))


def _a_unit_is_read_inside_a_longer_word(patch: pytest.MonkeyPatch) -> None:
    pattern = bound_units_gate._UNIT.pattern.rsplit("(?!", 1)[0]
    patch.setattr(bound_units_gate, "_UNIT", re.compile(pattern))


def _a_technical_sense_counts_in_the_plural(patch: pytest.MonkeyPatch) -> None:
    """The exemption before item 54: its nouns in the singular only."""
    import dataclasses

    rules = writing_gate.load_rules()
    old = (r"(?i)\brobust(?:ness)?\s+(?:standard\s+error|variance|estimator|regression|check"
           r"|analysis|analyses)\b")  # fmt: skip
    density = tuple(
        {**rule, "exempt": [old, *rule["exempt"][1:]]} if rule["id"] == "ai-vocabulary" else rule
        for rule in rules.density
    )
    assert density != rules.density
    patch.setattr(writing_gate, "load_rules", lambda: dataclasses.replace(rules, density=density))


def _a_slash_divides_by_symbols_only(patch: pytest.MonkeyPatch) -> None:
    pattern = bound_units_gate._UNIT.pattern.replace(
        r"/[^\W\d_]+", "/(?:" + bound_units_gate._SYMBOL + ")", 1
    )
    patch.setattr(bound_units_gate, "_UNIT", re.compile(pattern))


def _a_limit_is_read_inside_a_longer_number(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(journal_quotes_gate, "_DIGITS", "{}")


def _a_limit_is_read_before_a_decimal(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(journal_quotes_gate, "_DIGITS", r"(?<![0-9.,]){}(?![0-9])")


def _a_limit_has_no_separator_of_thousands(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(journal_quotes_gate, "_forms", lambda value: {str(value)})


def _a_limit_s_word_is_read_inside_a_longer_word(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(journal_quotes_gate, "_WORD", "{}")


def _a_limit_is_read_after_a_space_between_thousands(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(journal_quotes_gate, "_GROUP_BEFORE", re.compile(r"(?!)"))


def _a_group_of_three_before_a_space_is_a_thousand(patch: pytest.MonkeyPatch) -> None:
    # As the rule was before round 4 of #297: "900 150" a thousand and more, not 150.
    patch.setattr(journal_quotes_gate, "_GROUP_BEFORE",
                  re.compile(r"(?:\A|[^0-9.,])[0-9]{1,3} \Z"))  # fmt: skip


def _a_quote_is_on_its_page_as_characters(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.literature.sources import normalise

    def inside(page: str, quote: str) -> bool:
        return normalise(quote).lower() in normalise(page).lower()

    patch.setattr(journal_quotes_gate, "_on_page", inside)


def _a_quote_is_looked_for_once_on_its_page(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.literature.sources import normalise

    def first(page: str, quote: str) -> bool:
        haystack, needle = normalise(page).lower(), normalise(quote).lower()
        at = haystack.find(needle)
        if at < 0:
            return False
        before = haystack[at - 1] if at else ""
        after = haystack[at + len(needle) : at + len(needle) + 1]
        return not (before.isalnum() or after.isalnum())

    patch.setattr(journal_quotes_gate, "_on_page", first)


def _a_claim_keeps_its_line_breaks(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(methods_gate, "_collapsed", lambda text: text.strip(" "))


def _comments_are_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_methods_gate, "_words", lambda text: text.replace("*", "").casefold()
                  .split())  # fmt: skip


def _case_is_compared(patch: pytest.MonkeyPatch) -> None:
    real = related_methods_gate.as_quoted
    patch.setattr(related_methods_gate, "_words", lambda text: real(text).split())


def _a_number_makes_another_heading(patch: pytest.MonkeyPatch) -> None:
    real = related_methods_gate.as_quoted
    patch.setattr(related_methods_gate, "folded_title", lambda title: real(title).casefold())


def _the_deviations_are_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_methods_gate, "_OWN", ())


def _a_heading_that_stands_twice_is_compared_first(patch: pytest.MonkeyPatch) -> None:
    real = related_methods_gate._by_title

    def first_wins(text: str):
        read = real(text)
        read.twice = set()
        return read

    patch.setattr(related_methods_gate, "_by_title", first_wins)


def _what_the_deviations_hold_is_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_methods_gate, "subsections", lambda sections, index: [sections[index]])


def _only_the_first_words_are_compared(patch: pytest.MonkeyPatch) -> None:
    real = related_methods_gate._words
    patch.setattr(related_methods_gate, "_words", lambda text: real(text)[:3])


def _a_definition_is_compared_in_its_case(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_methods_gate, "_text_words", lambda text: text.split())


def _a_definition_keeps_its_line_breaks(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_methods_gate, "_text_words", lambda text: text.casefold().split(" "))


def _only_a_definition_s_first_words_are_compared(patch: pytest.MonkeyPatch) -> None:
    real = related_methods_gate._text_words
    patch.setattr(related_methods_gate, "_text_words", lambda text: real(text)[:3])


def _codes_are_compared_by_their_list_s_name(patch: pytest.MonkeyPatch) -> None:
    real = related_methods_gate._codes_compared

    def by_name(then, now) -> list:
        named = then.code_list != now.code_list
        return real(then, now) + [related_methods_gate.Differs(
            "list of codes", str(then.code_list), str(now.code_list))] * named

    patch.setattr(related_methods_gate, "_codes_compared", by_name)


def _a_label_or_a_term_is_compared_in_its_case(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_methods_gate, "_folded", lambda text: " ".join((text or "").split()))


def _an_ordinal_scale_s_order_is_not_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_methods_gate, "_order_compared", lambda there, here: [])


def _a_bound_is_compared_as_written(patch: pytest.MonkeyPatch) -> None:
    def written(variable, read) -> tuple[str, str]:
        return str(variable.minimum), str(variable.maximum)

    patch.setattr(related_methods_gate, "_bounds", written)


def _a_time_bound_is_compared_as_text(patch: pytest.MonkeyPatch) -> None:
    """The rule of #415 before its first round: a bound no number is the loader's string."""
    patch.setattr(related_methods_gate, "_BOUND_READERS", {})


def _each_bound_is_read_by_its_own_type(patch: pytest.MonkeyPatch) -> None:
    """The rule of #415 after its first round: a date there and a datetime here never equal."""
    real = related_methods_gate._bounds

    def own(variable, read) -> tuple:
        return real(variable, related_methods_gate._BOUND_READERS.get(variable.type, str))

    patch.setattr(related_methods_gate, "_bounds", own)


def _inputs_are_compared_in_their_order(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_methods_gate, "_inputs",
                  lambda variable: ", ".join(variable.derived_from))  # fmt: skip


def _only_a_standard_s_release_is_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_methods_gate, "_STANDARD_PARTS", (("version", False),))


def _the_study_period_is_not_compared(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_methods_gate, "period_compared", lambda then, now: None)


def _a_printed_value_is_text(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_gate, "_printed", lambda text: None)


def _printed_by(pattern: str):
    return lambda patch: patch.setattr(related_gate, "_PRINTED", re.compile(pattern))


_a_digit_before_the_point = _printed_by(
    r"^([-+]?)(\d{1,3}(?:[, ]\d{3})+|\d+)(?:[." + chr(0x00B7) + r"](\d+))?\s?%?$"
)
_no_groups_of_thousands = _printed_by(r"^([-+]?)(\d+)(?:[." + chr(0x00B7) + r"](\d+))?\s?%?$")
_no_middle_dot = _printed_by(r"^([-+]?)(\d{1,3}(?:[, ]\d{3})+|\d+)(?:[.](\d+))?\s?%?$")
_no_percent_sign = _printed_by(r"^([-+]?)(\d{1,3}(?:[, ]\d{3})+|\d+)(?:[." + chr(0x00B7)
                               + r"](\d+))?$")  # fmt: skip


def _no_minus_sign(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(related_gate, "_SPACES", str.maketrans({chr(0x00A0): " ", chr(0x2009): " ",
                                                          chr(0x202F): " "}))  # fmt: skip


def _a_whole_unit_is_the_same(patch: pytest.MonkeyPatch) -> None:
    def within(then, here) -> bool:
        return abs(then[0] - here[0]) <= Decimal(1) / Decimal(10) ** min(then[1], here[1])

    patch.setattr(related_gate, "_within", within)


def _the_finer_printing_decides(patch: pytest.MonkeyPatch) -> None:
    def within(then, here) -> bool:
        return abs(then[0] - here[0]) <= Decimal(5) / Decimal(10) ** (max(then[1], here[1]) + 1)

    patch.setattr(related_gate, "_within", within)


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


def _a_doi_is_named_by_its_letters_anywhere(patch: pytest.MonkeyPatch) -> None:
    """The rule a first reading would write: the DOI's letters anywhere in the statement."""
    patch.setattr(data_statement, "names_doi",
                  lambda text, doi: doi.lower() in text.lower())  # fmt: skip


def _a_doi_is_named_in_its_own_case_only(patch: pytest.MonkeyPatch) -> None:
    real = data_statement._plain_doi
    patch.setattr(data_statement, "_plain_doi", lambda written: real(written).swapcase()
                  if any(c.isupper() for c in written) else real(written))  # fmt: skip


def _a_cell_counts_by_its_first_digits(patch: pytest.MonkeyPatch) -> None:
    def first(text: str) -> int | None:
        found = re.match(r"\s*(\d+)", text)
        return int(found.group(1)) if found else None

    patch.setattr(deposit_counts, "count_in_cell", first)


def _a_share_is_digits_and_a_point(patch: pytest.MonkeyPatch) -> None:
    """The rule as it stood at 45348fe9 (round 1 of #388): a share or a denominator, never
    both, and the share plain digits with a point."""
    old = r"\s*(?P<count>\d+)\s*(?:\(\s*\d+(?:\.\d+)?\s*%?\s*\)|/\s*\d+)?\s*"
    patch.setattr(deposit_counts, "_COUNT_CELL", re.compile(old))


def _a_cell_ends_at_its_brackets(patch: pytest.MonkeyPatch) -> None:
    """The rule as it stood at def0e2f1 (round 2 of #388): no footnote mark, no square
    brackets, and a share with a digit before its point."""
    share = r"[<>]?\s*\d+(?:[.,]\d+)?\s*%?"
    old = rf"\s*(?P<count>\d+)\s*(?:/\s*\d+\s*)?(?:\(\s*{share}\s*\))?\s*"
    patch.setattr(deposit_counts, "_COUNT_CELL", re.compile(old))


def _a_doi_begins_only_after_a_word_boundary(patch: pytest.MonkeyPatch) -> None:
    """The reading as it stood at 45348fe9 (round 1 of #388): the DOIs `_DOI` finds."""
    patch.setattr(data_statement, "_NAMED_DOI", data_statement._DOI)


def _a_cell_counts_before_any_brackets(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(deposit_counts, "_COUNT_CELL",
                  re.compile(r"\s*(?P<count>\d+)\s*(?:\(.*\)|/\s*\d+)?\s*"))  # fmt: skip


def _an_alternative_text_escapes_only_its_brackets(patch: pytest.MonkeyPatch) -> None:
    """Escaped only where a mark would end the description: emphasis, a citation, maths and
    raw HTML in it are read as markup."""
    from manuscript_guard.gates import figure_alt

    patch.setattr(figure_alt, "_PUNCTUATION", re.compile(r"([\[\]\\])"))


def _an_alternative_text_keeps_its_line_breaks(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_alt

    escaped = figure_alt._PUNCTUATION
    patch.setattr(figure_alt, "as_markdown", lambda text: escaped.sub(r"\\\1", text))


def _a_groups_opacity_is_not_carried_down(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    patch.setattr(figure_svg, "_opacity", lambda value, otherwise: otherwise)


def _an_svg_texts_colour_is_a_marks(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    real = figure_svg._paint
    patch.setattr(figure_svg, "_paint", lambda figure, state, which, *, text: real(
        figure, state, which, text=False))  # fmt: skip


def _cmyk_is_read_as_no_colour(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_pdf

    real = figure_pdf._colour
    patch.setattr(figure_pdf, "_colour", lambda operands: None if len(
        [x for x in operands if isinstance(x, (int, float))]) == 4 else real(operands))  # fmt: skip


def _q_restores_no_colour(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_pdf

    real = figure_pdf._operations
    patch.setattr(figure_pdf, "_operations",
                  lambda data: ((ops, op) for ops, op in real(data) if op != b"Q"))  # fmt: skip


def _a_hidden_mark_is_painted(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    real = figure_svg._paint
    patch.setattr(figure_svg, "_paint", lambda figure, state, which, *, text: real(
        figure, {**state, "hidden": False}, which, text=text))  # fmt: skip


def _glyphs_are_marks(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_svg

    patch.setattr(figure_svg, "_drawn_text", lambda node_id: False)


def _a_colour_space_is_not_looked_up(patch: pytest.MonkeyPatch) -> None:
    """A space named in the page's resources taken as unread, as R's pdf() names its ICC
    profile `/sRGB`: every colour of such a figure is lost."""
    from manuscript_guard.gates import figure_pdf

    patch.setattr(figure_pdf, "_readable", lambda resources, name, objects: isinstance(
        name, figure_pdf.Name) and name.name in figure_pdf._READ_SPACES)  # fmt: skip


def _a_graphics_states_opacity_is_not_read(patch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.gates import figure_pdf

    patch.setattr(figure_pdf, "_opacities",
                  lambda resources, name, objects, fill, stroke: (fill, stroke))  # fmt: skip


def _a_passage_is_matched_as_it_is_typed(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(passages_module, "statement_words", lambda sentence: sentence)


def _a_citation_group_is_words_of_the_sentence(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(passages_module, "bracketed", lambda text: iter(()))


def _a_space_before_a_comma_is_a_difference(patch: pytest.MonkeyPatch) -> None:
    # Matches nothing, with the group the substitution puts back.
    patch.setattr(passages_module, "_BEFORE_MARK", re.compile("(?!)( )"))


def _a_binding_spaced_otherwise_is_a_difference(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(passages_module, "PLACEHOLDER", re.compile("(?!)"))


def _a_sentence_is_matched_on_its_opening_words(patch: pytest.MonkeyPatch) -> None:
    folded = passages_module.statement_words
    patch.setattr(passages_module, "statement_words",
                  lambda sentence: " ".join(folded(sentence).split()[:8]))  # fmt: skip


def _a_passage_is_matched_whatever_work_it_names(patch: pytest.MonkeyPatch) -> None:
    def of(self, cited, key, words=None):  # noqa: ANN001, ANN202 - the method it stands for
        found = passages_module.statement_words(cited.text) if words is None else words
        return list(self._by_words.get(found, []))

    patch.setattr(passages_module.Belonging, "of", of)


def _no_reworded_sentence_is_near(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(passages_module, "NEAR", 1.1)


def _a_comment_of_the_plan_credits_its_citations(patch: pytest.MonkeyPatch) -> None:
    patch.setattr(methods_review_gate, "blank_comments", lambda text: text)


def _a_narrative_citation_credits_nothing(patch: pytest.MonkeyPatch) -> None:
    found = methods_review_gate.find_citations
    patch.setattr(methods_review_gate, "find_citations", lambda text, path: [
        use for use in found(text, path) if not use.narrative
    ])  # fmt: skip


def _a_key_credits_the_keys_it_begins(patch: pytest.MonkeyPatch) -> None:
    # A key read up to its last digit: `study3x` as `study3`.
    from dataclasses import replace

    found = methods_review_gate.find_citations
    patch.setattr(methods_review_gate, "find_citations", lambda text, path: [
        replace(use, citekey=re.match(r"[A-Za-z]+[0-9]*", use.citekey)[0])
        for use in found(text, path)
    ])  # fmt: skip


#: A rule broken in one place, and the property that has to fail for it. Each is a way one
#: of these rules has been wrong, or a mutant a review found alive.
BROKEN = {
    "a registration is found inside a longer identifier": (
        _registration_found_inside_another,
        test_a_registration_is_found_where_the_manuscript_gives_it_and_no_lookalike_is,
    ),
    "an identifier is read inside a longer word": (
        _identifier_read_inside_a_word,
        test_each_identifier_a_manuscript_gives_is_found_as_written_and_nothing_else,
    ),
    "a registered outcome keeps its case": (
        _fold_keeps_case,
        test_a_registered_outcome_is_found_however_it_was_copied_and_not_with_a_word_changed,
    ),
    "a registered outcome keeps its dashes": (
        _fold_keeps_dashes,
        test_a_registered_outcome_is_found_however_it_was_copied_and_not_with_a_word_changed,
    ),
    "a registry is read as a registration": (
        _retrospective_any_regist_word,
        test_a_late_registration_is_said_in_every_way_a_manuscript_says_it_and_no_other,
    ),
    "a late registration is said on one line only": (
        _retrospective_on_one_line,
        test_a_late_registration_is_said_in_every_way_a_manuscript_says_it_and_no_other,
    ),
    "every stop ends a sentence, after et al. and Suppl. too": (
        _every_stop_ends_a_sentence,
        test_every_citation_lies_in_the_sentence_of_its_own_clause,
    ),
    "a passage is matched on its sentence as it is typed": (
        _a_passage_is_matched_as_it_is_typed,
        test_a_passage_belongs_to_its_sentence_by_its_words_and_its_work,
    ),
    "a footnote is read where it is defined": (
        _a_footnote_is_read_where_it_is_defined,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a table's caption is compared where pandoc does not write it": (
        _a_tables_caption_is_compared_where_pandoc_does_not_write_it,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a list's numbers are read as typed": (
        _a_lists_numbers_are_read_as_typed,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a figure's alternative text is read": (
        _a_figures_alternative_text_is_read,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a footnote is read at its first mark only": (
        _a_footnote_is_read_at_its_first_mark_only,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a bare address is read in LaTeX": (
        _a_bare_address_is_read_in_latex,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a YAML block is read as text": (
        _a_yaml_block_is_read_as_text,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a mark with no note is read as a mark": (
        _a_mark_with_no_note_is_read_as_a_mark,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a narrative citation's locator is read under citeproc": (
        _a_narrative_locator_is_read,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a note nothing marks is read": (
        _a_note_nothing_marks_is_read,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a sign written as a command ends an address": (
        _a_sign_written_as_a_command_ends_an_address,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "an address takes in what follows it": (
        _an_address_takes_in_what_follows_it,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "a repeated table header is read": (
        _a_repeated_table_header_is_read,
        test_pandocs_latex_prints_the_digits_the_markdown_reader_keeps,
    ),
    "no difference in digits is seen": (
        _no_difference_in_digits_is_seen,
        test_a_digit_pandoc_wrote_otherwise_is_caught,
    ),
    "a citation group is words of the sentence": (
        _a_citation_group_is_words_of_the_sentence,
        test_a_passage_belongs_to_its_sentence_by_its_words_and_its_work,
    ),
    "a binding spaced otherwise is a difference": (
        _a_binding_spaced_otherwise_is_a_difference,
        test_a_passage_belongs_to_its_sentence_by_its_words_and_its_work,
    ),
    "a space before a comma is a difference": (
        _a_space_before_a_comma_is_a_difference,
        test_a_passage_belongs_to_its_sentence_by_its_words_and_its_work,
    ),
    "a sentence is matched on its opening words": (
        _a_sentence_is_matched_on_its_opening_words,
        test_a_passage_belongs_to_its_sentence_by_its_words_and_its_work,
    ),
    "a passage is matched whatever work it names": (
        _a_passage_is_matched_whatever_work_it_names,
        test_a_passage_belongs_to_its_sentence_by_its_words_and_its_work,
    ),
    "no reworded sentence is near its passage's": (
        _no_reworded_sentence_is_near,
        test_a_passage_belongs_to_its_sentence_by_its_words_and_its_work,
    ),
    "a comment of the plan credits its citations": (
        _a_comment_of_the_plan_credits_its_citations,
        test_a_study_is_credited_by_a_citation_of_the_plan_and_by_nothing_else,
    ),
    "a narrative citation credits nothing": (
        _a_narrative_citation_credits_nothing,
        test_a_study_is_credited_by_a_citation_of_the_plan_and_by_nothing_else,
    ),
    "a key credits the keys it begins": (
        _a_key_credits_the_keys_it_begins,
        test_a_study_is_credited_by_a_citation_of_the_plan_and_by_nothing_else,
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
    "in LaTeX, an escaped percent opens a comment": (
        _an_escaped_percent_opens_a_comment,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a comment runs past its line": (
        _a_latex_comment_runs_past_its_line,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, maths is blanked whole": (
        _latex_maths_is_blanked_whole,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a citation's notes are blanked": (
        _a_citations_notes_are_blanked,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a group closes at the first brace": (
        _a_latex_group_closes_at_the_first_brace,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, \\verb takes only | as its delimiter": (
        _verb_takes_only_a_bar,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, the preamble ends at the first \\begin": (
        _the_preamble_ends_at_the_first_begin,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, \\iffalse hides its \\else branch": (
        _iffalse_hides_its_else,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, \\\\ takes a bracket that opens the next line": (
        _a_line_break_takes_a_bracket_on_the_next_line,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, an input file starts under no heading": (
        _an_input_file_starts_under_no_heading,
        test_each_latex_file_starts_under_the_headings_in_force_where_it_is_input,
    ),
    "in LaTeX, a heading of an input file does not reach the text after its \\input": (
        _a_heading_of_an_input_file_stays_in_it,
        test_each_latex_file_starts_under_the_headings_in_force_where_it_is_input,
    ),
    "in LaTeX, a heading where an \\input ends is put before what the input left": (
        _a_heading_where_an_input_ends_comes_before_it,
        test_each_latex_file_starts_under_the_headings_in_force_where_it_is_input,
    ),
    "in LaTeX, a chapter closes its part": (
        _a_chapter_closes_its_part,
        test_each_latex_file_starts_under_the_headings_in_force_where_it_is_input,
    ),
    "in LaTeX, a \\subimport names its folder from the entry file's": (
        _a_subimport_names_its_folder_from_the_entry_files,
        test_each_latex_file_starts_under_the_headings_in_force_where_it_is_input,
    ),
    "in LaTeX, an imported file keeps the folder its importer was imported from": (
        _an_imported_file_keeps_the_folder_its_importer_was_imported_from,
        test_each_latex_file_starts_under_the_headings_in_force_where_it_is_input,
    ),
    "in LaTeX, an \\input is not looked for in the folder imported from": (
        _an_input_is_not_looked_for_in_the_folder_imported_from,
        test_each_latex_file_starts_under_the_headings_in_force_where_it_is_input,
    ),
    "in LaTeX, a definition with delimited parameters is refused": (
        _a_delimited_definition_is_refused,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a parameter in a definition's body is one #": (
        _a_parameter_in_a_body_is_one_hash,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a command let to another is always defined again": (
        _a_command_let_is_always_defined_again,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a class's front matter is read": (
        _a_classs_front_matter_is_read,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, an abstract in the front matter is passed over with it": (
        _an_abstract_in_front_matter_is_passed_over_with_it,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, the front matter's commands are unknown": (
        _front_matter_commands_are_unknown,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a front matter command defined again is refused": (
        _front_matter_commands_are_defined_again,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, highlights in the front matter are passed over": (
        _highlights_in_front_matter_are_passed_over,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a front matter command the author defines is passed over": (
        _an_author_s_front_matter_command_is_passed_over,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a delimited command is refused wherever it stands": (
        _a_delimited_use_is_refused_wherever_it_stands,
        test_a_command_with_delimited_parameters_is_refused_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a delimited command is read as an unknown one": (
        _a_delimited_use_is_read_as_an_unknown_command,
        test_a_command_with_delimited_parameters_is_refused_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a delimited command in maths is let be": (
        _a_delimited_use_in_maths_is_let_be,
        test_a_command_with_delimited_parameters_is_refused_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a delimited command in a hook's body is let be": (
        _a_hook_s_body_is_a_definition_s,
        test_a_command_with_delimited_parameters_is_refused_in_a_hook_s_body,
    ),
    "in LaTeX, the spaces after a control word delimit a definition's parameters": (
        _the_spaces_after_a_control_word_delimit,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, an abstract in the preamble is blanked": (
        _an_abstract_in_the_preamble_is_blanked,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a binding is read wherever it is typed, in a comment too": (
        _a_latex_binding_is_read_wherever_it_is_typed,
        test_a_latex_binding_is_read_where_it_prints_as_one_and_nowhere_else,
    ),
    "in LaTeX, a near spelling of \\mg is taken for nothing": (
        _a_near_spelling_of_the_binding_is_taken_for_nothing,
        test_a_latex_binding_is_read_where_it_prints_as_one_and_nowhere_else,
    ),
    "in LaTeX, a Markdown binding left in a .tex is taken for nothing": (
        _a_markdown_binding_in_latex_is_taken_for_nothing,
        test_a_latex_binding_is_read_where_it_prints_as_one_and_nowhere_else,
    ),
    "in LaTeX, siunitx's milligram is taken for a binding": (
        _siunitx_s_milligram_is_taken_for_a_binding,
        test_a_latex_binding_is_read_where_it_prints_as_one_and_nowhere_else,
    ),
    "in LaTeX, a binding's Markdown view is not padded to its command": (
        _a_bindings_view_is_not_padded_to_its_command,
        test_a_latex_binding_is_read_where_it_prints_as_one_and_nowhere_else,
    ),
    "in LaTeX, a typed table is not recorded": (
        _a_typed_table_is_not_recorded,
        test_a_latex_binding_is_read_where_it_prints_as_one_and_nowhere_else,
    ),
    "in LaTeX, a listing's language is not read": (
        _a_listings_language_is_not_read,
        test_a_latex_binding_is_read_where_it_prints_as_one_and_nowhere_else,
    ),
    "in LaTeX, a line break before a binding's brace makes it malformed": (
        _a_line_break_before_a_bindings_brace_makes_it_malformed,
        test_a_latex_binding_is_read_where_it_prints_as_one_and_nowhere_else,
    ),
    "in LaTeX, a citation's keys are not split at its commas": (
        _a_citations_keys_are_not_split,
        test_a_latex_citation_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a key in a definition's body is cited": (
        _a_key_in_a_definitions_body_is_cited,
        test_a_latex_citation_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, no citation is narrative": (
        _no_latex_citation_is_narrative,
        test_a_latex_citation_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a multi-citation reads its first group only": (
        _a_multi_citation_reads_its_first_group_only,
        test_a_latex_citation_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a comment in a citation's keys is a key": (
        _a_comment_in_a_key_list_is_a_key,
        test_a_latex_citation_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a long global note hides a multi-citation's keys": (
        _a_long_global_note_hides_its_citations,
        test_a_latex_citation_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, natbib's and biblatex's settings in the preamble are refused": (
        _a_preamble_cite_setting_is_refused,
        test_a_latex_citation_is_read_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX's words, maths is words": (
        _maths_is_words,
        test_latex_s_words_hold_each_word_where_latex_prints_it,
    ),
    "in LaTeX's words, code is words": (
        _code_is_words,
        test_latex_s_words_hold_each_word_where_latex_prints_it,
    ),
    "in LaTeX's words, a figure's caption is words": (
        _a_figures_caption_is_words,
        test_latex_s_words_hold_each_word_where_latex_prints_it,
    ),
    "in LaTeX's words, the preamble is words": (
        _the_preamble_is_words,
        test_latex_s_words_hold_each_word_where_latex_prints_it,
    ),
    "in LaTeX's words, an accented word is read in pieces": (
        _an_accented_word_is_read_in_pieces,
        test_latex_s_words_hold_each_word_where_latex_prints_it,
    ),
    "in LaTeX's words, an accented word is cut at its accent": (
        _an_accented_word_is_cut_at_its_accent,
        test_latex_s_words_hold_each_word_where_latex_prints_it,
    ),
    "in LaTeX's words, a subscript's count is maths": (
        _a_subscripts_count_is_maths,
        test_latex_s_words_hold_each_word_where_latex_prints_it,
    ),
    "in LaTeX, a quotation's line is the printed view's": (
        _a_quotation_s_line_is_the_printed_view_s,
        test_a_latex_quotation_is_read_at_its_line_and_nowhere_else,
    ),
    "in LaTeX, a recycled passage's lines are the printed view's": (
        _a_recycled_passage_s_lines_are_the_printed_view_s,
        test_a_latex_passage_of_an_earlier_paper_is_placed_at_its_file_and_lines,
    ),
    "in LaTeX, a recycled passage ends on its first line": (
        _a_recycled_passage_ends_on_its_first_line,
        test_a_latex_passage_of_an_earlier_paper_is_placed_at_its_file_and_lines,
    ),
    "in LaTeX, a starred caption numbers a display": (
        _a_starred_caption_numbers_a_display,
        test_a_latex_pointer_is_held_to_what_latex_numbers,
    ),
    "in LaTeX, a starred caption is a legend": (
        _a_starred_caption_numbers_a_display,
        test_a_latex_legend_is_its_figure_s_caption,
    ),
    "in LaTeX, a subfigure's caption is a legend": (
        _a_subfigure_s_caption_numbers_the_float,
        test_a_latex_legend_is_its_figure_s_caption,
    ),
    "in LaTeX, a continued float numbers a display": (
        _a_continued_float_numbers_a_display,
        test_a_latex_pointer_is_held_to_what_latex_numbers,
    ),
    "in LaTeX, a part's label names nothing": (
        _a_part_s_label_names_nothing,
        test_a_latex_pointer_is_held_to_what_latex_numbers,
    ),
    "in LaTeX, a float that inputs its caption is uncounted": (
        _a_float_that_inputs_its_caption_is_uncounted,
        test_a_latex_pointer_is_held_to_what_latex_numbers,
    ),
    "in LaTeX, a cross-reference cites nothing": (
        _a_cross_reference_cites_nothing,
        test_a_latex_pointer_is_held_to_what_latex_numbers,
    ),
    "in LaTeX, a pointer's line is the printed view's": (
        _a_latex_pointer_s_line_is_the_view_s,
        test_a_latex_pointer_is_held_to_what_latex_numbers,
    ),
    "in LaTeX, a float's caption is not compared with an earlier paper": (
        _a_caption_is_not_compared,
        test_a_latex_passage_of_an_earlier_paper_is_placed_at_its_file_and_lines,
    ),
    "in LaTeX, a quotation marked with a command is not quoted": (
        _a_quotation_latex_marks_with_a_command_is_not_quoted,
        test_a_latex_passage_of_an_earlier_paper_is_placed_at_its_file_and_lines,
    ),
    "in LaTeX's printed view, dashes are printed as typed": (
        _latex_dashes_are_printed_as_typed,
        test_a_latex_quotation_is_read_at_its_line_and_nowhere_else,
    ),
    "in LaTeX, an ellipsis prints nothing": (
        _latex_s_ellipsis_prints_nothing,
        test_a_latex_quotation_is_read_at_its_line_and_nowhere_else,
    ),
    "a typographic quotation mark opens no sentence": (
        _a_typographic_quotation_mark_opens_no_sentence,
        test_a_latex_quotation_is_read_at_its_line_and_nowhere_else,
    ),
    "in LaTeX's printed view, an en dash is typed before an em dash": (
        _latex_s_en_dash_is_typed_before_its_em_dash,
        test_a_latex_quotation_is_read_at_its_line_and_nowhere_else,
    ),
    "in LaTeX's printed view, a line is placed where it starts, blank or not": (
        _a_line_is_placed_where_it_starts_blank,
        test_a_latex_quotation_is_read_at_its_line_and_nowhere_else,
    ),
    "in LaTeX's printed view, no citation is printed": (
        _no_latex_citation_is_printed,
        test_a_latex_quotation_is_read_at_its_line_and_nowhere_else,
    ),
    "in LaTeX, G8r reads a file as typed": (
        _g8r_reads_a_latex_file_as_typed,
        test_a_latex_claim_to_have_followed_a_guideline_is_read_where_it_prints,
    ),
    "in LaTeX, G8r reads a file's code": (
        _g8r_reads_a_latex_file_s_code,
        test_a_latex_claim_to_have_followed_a_guideline_is_read_where_it_prints,
    ),
    "in LaTeX, G8r reads a typed reference list": (
        _g8r_reads_a_typed_reference_list,
        test_a_latex_claim_to_have_followed_a_guideline_is_read_where_it_prints,
    ),
    "in LaTeX, no cross-reference is recorded": (
        _no_latex_cross_reference_is_recorded,
        test_a_latex_cross_reference_is_recorded_where_it_prints_and_nowhere_else,
    ),
    "in LaTeX, a label is a cross-reference": (
        _a_label_is_a_cross_reference,
        test_a_latex_cross_reference_is_recorded_where_it_prints_and_nowhere_else,
    ),
    "a quote's number stands for no cross-reference": (
        _a_quote_s_number_stands_for_no_reference,
        test_a_quote_of_a_latex_sentence_holds_a_number_where_its_reference_stands,
    ),
    "a bracket typed round a cross-reference is taken for its own": (
        _a_bracket_typed_round_a_reference_is_its_own,
        test_a_quote_of_a_latex_sentence_holds_a_number_where_its_reference_stands,
    ),
    "a cross-reference stands for its number alone, not the word before it": (
        _a_reference_stands_for_its_number_alone,
        test_a_quote_of_a_latex_sentence_holds_a_number_where_its_reference_stands,
    ),
    "in LaTeX, G15 reads a heading's title": (
        _g15_reads_a_latex_heading_s_title,
        test_a_model_named_in_latex_methods_is_found_where_latex_prints_it,
    ),
    "in LaTeX, G15 reads all of a file as its Methods": (
        _g15_reads_all_of_a_latex_file_as_its_methods,
        test_a_model_named_in_latex_methods_is_found_where_latex_prints_it,
    ),
    "in LaTeX, G15 reads a file in its Markdown view": (
        _g15_reads_a_latex_file_in_its_markdown_view,
        test_a_model_named_in_latex_methods_is_found_where_latex_prints_it,
    ),
    "in LaTeX, G15 reads a file's words with a NUL where it reads none": (
        _g15_reads_a_latex_file_s_words_with_its_nul,
        test_a_model_named_in_latex_methods_is_found_where_latex_prints_it,
    ),
    "in LaTeX, G9 cuts no heading out of a paragraph": (
        _g9_cuts_no_latex_heading,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G9 reads a table set apart with its paragraph": (
        _g9_reads_a_table_set_apart_with_its_paragraph,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G9 reads an anchored float with the paragraph round it": (
        _g9_reads_an_anchored_float_with_the_paragraph_round_it,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G9 reads a float's words": (
        _g9_reads_a_float_s_words,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G9 reads a table's words inside a float": (
        _g9_reads_a_table_s_words_inside_a_float,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G9 reads no word of a float that holds an anchor": (
        _g9_reads_no_word_of_a_float_that_holds_an_anchor,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G9 ends a paragraph at a float": (
        _g9_ends_a_paragraph_at_a_float,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G9 ends a paragraph at a line of spaces in its view": (
        _g9_ends_a_latex_paragraph_at_a_line_of_spaces_in_its_view,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G9 starts a typed paragraph where its first line starts": (
        _g9_starts_a_typed_paragraph_where_its_first_line_starts,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G9 starts a paragraph glued to its heading at the heading's end": (
        _g9_starts_a_paragraph_at_the_end_of_its_heading,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G9 reads a binding in a claim as the view pads it": (
        _g9_reads_a_latex_binding_as_its_view_pads_it,
        test_g9_reads_a_latex_methods_section_as_it_reads_a_markdown_one,
    ),
    "in LaTeX, G6 takes no citation command for a claim's support": (
        _g6_takes_no_latex_citation,
        test_g6_judges_a_latex_document_where_it_prints_and_by_its_citations,
    ),
    "in LaTeX, G6 reads a file whole as typed, its preamble too": (
        _g6_reads_a_latex_file_whole_as_typed,
        test_g6_judges_a_latex_document_where_it_prints_and_by_its_citations,
    ),
    "in LaTeX, G6 reads a typed reference list": (
        _g6_reads_a_typed_reference_list,
        test_g6_judges_a_latex_document_where_it_prints_and_by_its_citations,
    ),
    "in LaTeX, G6 takes \\nocite for a claim's support": (
        _g6_takes_nocite_for_a_claims_support,
        test_g6_judges_a_latex_document_where_it_prints_and_by_its_citations,
    ),
    "in LaTeX, G6 reads no typed reference list": (
        _g6_reads_no_typed_reference_list,
        test_g6_judges_a_latex_document_where_it_prints_and_by_its_citations,
    ),
    "in LaTeX, G6 reads a definition's body in the preamble": (
        _g6_reads_a_definitions_body_in_the_preamble,
        test_g6_judges_a_latex_document_where_it_prints_and_by_its_citations,
    ),
    "in LaTeX, G6 reads past the document's end": (
        _g6_reads_past_the_documents_end,
        test_g6_judges_a_latex_document_where_it_prints_and_by_its_citations,
    ),
    "in LaTeX, G6 reads a comment as prose": (
        _g6_reads_a_latex_comment_as_prose,
        test_g6_judges_a_latex_document_where_it_prints_and_by_its_citations,
    ),
    "in LaTeX, G6 looks for a placeholder in the prose only": (
        _g6_looks_for_a_placeholder_in_the_prose_only,
        test_g6_judges_a_latex_document_where_it_prints_and_by_its_citations,
    ),
    "in LaTeX, G14 reads a file input after the file that inputs it": (
        _a_file_input_is_read_after_its_parent,
        test_g14_reads_a_latex_document_in_the_order_it_prints,
    ),
    "in LaTeX's printed view, prose breaks its lines as the view does": (
        _prose_breaks_its_lines_as_the_view_does,
        test_latex_s_printed_view_places_each_word_at_its_file_and_line,
    ),
    "in LaTeX's printed view, each stretch is placed at its file's start": (
        _each_stretch_is_placed_at_its_files_start,
        test_latex_s_printed_view_places_each_word_at_its_file_and_line,
    ),
    "in LaTeX's printed view, a file input is printed after the file that inputs it": (
        _an_input_file_is_printed_after_its_parent,
        test_latex_s_printed_view_writes_each_file_where_it_is_input,
    ),
    "in LaTeX's printed view, a typed reference list is printed": (
        _a_typed_reference_list_is_printed,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, a single quote opens a code span": (
        _a_single_quote_opens_a_code_span,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, an abstract in the preamble is not printed": (
        _an_abstract_in_the_preamble_is_not_printed,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, a float's words are printed": (
        _a_floats_words_are_printed,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, the preamble is printed": (
        _the_preamble_is_printed,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, a heading's title is printed twice": (
        _a_headings_title_is_printed_twice,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, an abstract runs on to the next heading": (
        _an_abstract_runs_on_to_the_next_heading,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, a prose binding is printed with spaces round it": (
        _a_prose_binding_is_printed_with_spaces_round_it,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, a formula's bindings are not printed": (
        _a_formulas_bindings_are_not_printed,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, a typed table's bindings are not printed": (
        _a_typed_tables_bindings_are_not_printed,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, a span's bindings are not printed": (
        _a_spans_bindings_are_not_printed,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX's printed view, a formula is printed as typed": (
        _a_formula_is_printed_as_typed,
        test_latex_s_printed_view_holds_what_it_prints_as_markdown_writes_it,
    ),
    "in LaTeX, a class named in a comment is stated": (
        _a_class_named_in_a_comment_is_stated,
        test_a_latex_preamble_states_its_class_and_bibliography_as_written,
    ),
    "in LaTeX, a class's options are one option": (
        _a_class_s_options_are_one,
        test_a_latex_preamble_states_its_class_and_bibliography_as_written,
    ),
    "in a LaTeX values file, a percent sign is written bare": (
        _a_percent_is_written_bare,
        test_a_display_written_for_latex_holds_no_bare_special_and_no_ligature,
    ),
    "in a LaTeX values file, two hyphens are written as typed": (
        _two_hyphens_are_written_as_typed,
        test_a_display_written_for_latex_holds_no_bare_special_and_no_ligature,
    ),
    "in a LaTeX values file, an en dash is written as a ligature": (
        _an_en_dash_is_written_as_a_ligature,
        test_a_display_written_for_latex_holds_no_bare_special_and_no_ligature,
    ),
    "in LaTeX, a command the table lacks hides its arguments": (
        _an_unknown_command_hides_its_arguments,
        test_a_number_in_latex_is_read_where_it_prints_and_nowhere_else,
    ),
    "an alternative text escapes only its brackets": (
        _an_alternative_text_escapes_only_its_brackets,
        test_an_alternative_text_is_the_pictures_description_as_it_was_written,
    ),
    "an alternative text keeps its line breaks": (
        _an_alternative_text_keeps_its_line_breaks,
        test_an_alternative_text_is_the_pictures_description_as_it_was_written,
    ),
    "a group's opacity is not carried down to what it holds": (
        _a_groups_opacity_is_not_carried_down,
        test_each_colour_an_svg_figure_paints_is_read_and_its_texts_kept_apart,
    ),
    "an SVG text's colour is read as a mark's": (
        _an_svg_texts_colour_is_a_marks,
        test_each_colour_an_svg_figure_paints_is_read_and_its_texts_kept_apart,
    ),
    "a CMYK colour is read as no colour": (
        _cmyk_is_read_as_no_colour,
        test_each_colour_a_pdf_figure_paints_is_read_and_its_texts_kept_apart,
    ),
    "a graphics state's opacity is not read": (
        _a_graphics_states_opacity_is_not_read,
        test_each_colour_a_pdf_figure_paints_is_read_and_its_texts_kept_apart,
    ),
    "a colour space the page's resources name is not looked up": (
        _a_colour_space_is_not_looked_up,
        test_each_colour_a_pdf_figure_paints_is_read_and_its_texts_kept_apart,
    ),
    "Q gives back no colour": (
        _q_restores_no_colour,
        test_each_colour_a_pdf_figure_paints_is_read_and_its_texts_kept_apart,
    ),
    "a form paints in its own colour, not its drawer's": (
        _a_form_draws_with_a_state_of_its_own,
        test_each_colour_a_pdf_figure_paints_is_read_and_its_texts_kept_apart,
    ),
    "a mark a hidden group hides is painted": (
        _a_hidden_mark_is_painted,
        test_each_colour_an_svg_figure_paints_is_read_and_its_texts_kept_apart,
    ),
    "a text drawn as glyphs is a mark": (
        _glyphs_are_marks,
        test_each_colour_an_svg_figure_paints_is_read_and_its_texts_kept_apart,
    ),
    "a piece with no word of its own is left alone": (
        _a_wordless_piece_is_left_alone,
        test_every_citation_lies_in_the_sentence_of_its_own_clause,
    ),
    "a numbered Results heading is not the Results": (
        _a_numbered_results_heading_is_no_results,
        test_a_number_a_summary_gives_is_found_unreported_whatever_the_headings_are_called,
    ),
    "the abstract's own Results report": (
        _the_abstracts_results_report,
        test_a_number_a_summary_gives_is_found_unreported_whatever_the_headings_are_called,
    ),
    "the headings of one file are not carried into the next": (
        _the_headings_of_a_file_are_not_carried_into_the_next,
        test_a_number_a_summary_gives_is_found_unreported_whatever_the_headings_are_called,
    ),
    "an abstract with a Background of its own is a title over the paper": (
        _an_abstract_over_a_background_is_a_title_over_the_paper,
        test_a_number_a_summary_gives_is_found_unreported_whatever_the_headings_are_called,
    ),
    "a paper's title over it all is its Results": (
        _a_title_over_the_paper_is_its_results,
        test_a_number_a_summary_gives_is_found_unreported_whatever_the_headings_are_called,
    ),
    "the Methods report nothing": (
        _the_methods_report_nothing,
        test_a_number_a_summary_gives_is_found_unreported_whatever_the_headings_are_called,
    ),
    "a statistic in brackets is read as a definition": (
        _a_statistic_in_brackets_is_a_definition,
        test_a_bracket_defines_where_its_long_form_stands_before_it_and_a_statistic_does_not,
    ),
    "a long form takes a letter from inside a bracket it opens": (
        _a_long_form_takes_a_letter_from_inside_a_bracket,
        test_a_bracket_defines_where_its_long_form_stands_before_it_and_a_statistic_does_not,
    ),
    "a long form crosses no bracket": (
        _a_long_form_crosses_no_bracket,
        test_a_bracket_defines_where_its_long_form_stands_before_it_and_a_statistic_does_not,
    ),
    "a time of day is read as words": (
        _a_time_of_day_is_words,
        test_a_time_of_day_and_a_heading_in_capitals_are_no_abbreviations,
    ),
    "a heading typed in capitals is read as words": (
        _a_heading_in_capitals_is_words,
        test_a_time_of_day_and_a_heading_in_capitals_are_no_abbreviations,
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
    "a statistic written with a decimal comma is read as its whole part": (
        _a_decimal_comma_is_read_as_a_whole_number,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "a comma after a number with its point is taken for a decimal comma": (
        _a_comma_after_a_point_is_taken_for_a_decimal_comma,
        test_a_reported_test_is_found_where_it_stands_and_its_p_judged_by_its_statistic,
    ),
    "a P written with a middle dot is read as its whole part": (
        _a_middle_dot_is_read_as_the_end_of_a_p,
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
    "an interval's bounds are read at their printed values, not over their last digit": (
        _a_bound_is_read_at_its_printed_value,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "a difference's interval is held to 1": (
        _a_difference_is_held_to_1,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "every interval is taken as a 95% one": (
        _every_interval_is_taken_as_95,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "an estimate's P is looked for past the next interval": (
        _a_p_is_looked_for_past_the_next_interval,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "a P for interaction is taken as the estimate's own": (
        _a_p_for_interaction_is_the_estimate_s,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "an estimate's P is looked for past the end of its sentence": (
        _an_interval_s_p_is_looked_for_past_its_sentence,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "a profile, exact or bootstrap interval is judged as a Wald one": (
        _an_interval_that_is_not_the_plain_one_is_judged,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "a P adjusted for multiplicity or one-sided is judged against its interval": (
        _a_p_that_is_not_the_plain_one_is_judged_against_its_interval,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "an adjusted estimate is not judged": (
        _adjusted_alone_quiets_an_interval,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "an estimate outside its own interval is not said": (
        _an_estimate_outside_its_interval_is_not_said,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "the words between a name and its estimate run across another estimate's name": (
        _a_name_s_words_run_across_another_name,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "a difference runs across the name of a ratio the reader does not read": (
        _a_difference_runs_across_a_ratio_it_does_not_read,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "an en dash before an estimate is not its minus": (
        _an_en_dash_before_an_estimate_is_no_minus,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "an en dash glued to a ratio's name is its minus": (
        _an_en_dash_glued_to_a_ratio_is_its_minus,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "bounds joined by hyphens after a negative one, or the wrong way round, are read": (
        _bounds_that_cannot_be_read_for_sure_are_read,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "an interval wrapped onto a second line is not read": (
        _an_interval_over_two_lines_is_not_read,
        test_an_estimate_and_its_interval_are_found_where_they_stand_and_judged,
    ),
    "a mean is held to its printed value, not half a unit either side": (
        _a_mean_is_held_to_exactly_its_printed_value,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "a mean half a unit from a total is not one, rounded either way": (
        _a_mean_half_a_unit_from_a_total_is_not_one,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "a nought at the end of a mean is not a place": (
        _a_nought_at_the_end_is_no_place,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "every mean is assessable, whatever its n": (
        _every_mean_is_assessable,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "a mean is assessable wherever n is under 10 to the power of its places": (
        _a_mean_is_assessable_below_the_power_of_its_places,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "a DOI is named by its letters anywhere in the statement": (
        _a_doi_is_named_by_its_letters_anywhere,
        test_a_deposit_is_named_by_its_doi_however_written_and_by_no_other,
    ),
    "a DOI is named only in the case paper.yaml writes it": (
        _a_doi_is_named_in_its_own_case_only,
        test_a_deposit_is_named_by_its_doi_however_written_and_by_no_other,
    ),
    "a cell counts by the digits it begins with": (
        _a_cell_counts_by_its_first_digits,
        test_a_cell_is_read_as_a_count_only_where_it_states_one,
    ),
    "a cell's share is plain digits and a point, and goes with no denominator": (
        _a_share_is_digits_and_a_point,
        test_a_cell_is_read_as_a_count_only_where_it_states_one,
    ),
    "a cell ends at its round brackets, with no footnote mark": (
        _a_cell_ends_at_its_brackets,
        test_a_cell_is_read_as_a_count_only_where_it_states_one,
    ),
    "a deposit's DOI begins only after a word boundary": (
        _a_doi_begins_only_after_a_word_boundary,
        test_a_deposit_is_named_by_its_doi_however_written_and_by_no_other,
    ),
    "a cell counts before whatever its brackets hold": (
        _a_cell_counts_before_any_brackets,
        test_a_cell_is_read_as_a_count_only_where_it_states_one,
    ),
    "a named label is matched in the case the auditor typed": (
        _a_named_label_is_matched_in_its_case,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "a named label is matched inside a word": (
        _a_named_label_is_matched_inside_a_word,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "a footnote marker on a row of means is not seen": (
        _a_mean_s_footnote_marker_is_not_seen,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "a mean with a minus sign or a plus-minus sign is not read": (
        _a_mean_with_a_minus_sign_or_a_plus_minus_is_not_read,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "a named row's own n is taken for its means": (
        _a_named_row_s_own_n_is_taken,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "a row a label names is never read for its n, though it is the header": (
        _a_named_row_is_never_read_for_its_n,
        test_a_mean_of_whole_numbers_in_a_table_is_held_to_its_column_s_n,
    ),
    "a share is held to its printed value, not half a unit either side": (
        _a_share_is_held_to_its_printed_value,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "a row whose label names a mean or a median is read as shares": (
        _a_label_naming_a_mean_is_read_as_shares,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "a label whose % is a unit says its numbers are shares": (
        _a_unit_percent_says_shares,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "a characteristic's categories are held to their column's n alone": (
        _categories_are_held_to_their_column_alone,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "a characteristic's label row with its P value beside it is read as a header": (
        _a_label_row_with_its_p_value_is_a_header,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "a run of categories takes in the characteristic after them": (
        _a_run_of_categories_takes_in_the_row_after_them,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "categories whose shares add up to 100 are not read as shares": (
        _shares_adding_up_to_100_say_nothing,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "a row's shares are never read as shares of its total": (
        _a_row_is_never_read_as_shares_of_its_total,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "a footnote marker on a row's label is not seen": (
        _a_footnote_marker_is_not_seen,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "a proof's decimal comma is the same number": (
        _a_decimal_comma_is_the_same_number,
        test_each_change_a_typesetter_makes_is_reported_once_where_it_is,
    ),
    "a proof's sign is not read": (
        _a_sign_is_not_read,
        test_each_change_a_typesetter_makes_is_reported_once_where_it_is,
    ),
    "a unit beside a number in a proof is a word": (
        _a_unit_is_a_word,
        test_each_change_a_typesetter_makes_is_reported_once_where_it_is,
    ),
    "a unit of time a proof spells out as another is a word": (
        _a_unit_of_time_spelt_out_is_a_word,
        test_each_change_a_typesetter_makes_is_reported_once_where_it_is,
    ),
    "a unit a proof joins to its number by a hyphen is not beside it": (
        _a_unit_past_a_hyphen_is_not_beside_its_number,
        test_each_change_a_typesetter_makes_is_reported_once_where_it_is,
    ),
    "a unit of time spelt out in a proof is a unit, abbreviated or not": (
        _a_unit_of_time_spelt_out_is_a_unit,
        test_each_change_a_typesetter_makes_is_reported_once_where_it_is,
    ),
    "a stretch the proof leaves out is not slid to a part's start": (
        _a_stretch_is_not_slid_to_a_part,
        test_each_change_a_typesetter_makes_is_reported_once_where_it_is,
    ),
    "a number a proof splits in two is two": (
        _a_number_split_in_two_is_two,
        test_each_change_a_typesetter_makes_is_reported_once_where_it_is,
    ),
    "a proof's running heads are kept": (
        _running_heads_are_kept,
        test_a_proof_that_prints_what_was_sent_reads_as_it,
    ),
    "a word a proof breaks at a line's end stays two": (
        _a_word_broken_at_a_line_end_stays_two,
        test_a_proof_that_prints_what_was_sent_reads_as_it,
    ),
    "a compound a proof breaks at a line's end loses its hyphen": (
        _a_compound_broken_at_a_line_end_loses_its_hyphen,
        test_a_proof_that_prints_what_was_sent_reads_as_it,
    ),
    "a column header's n is not read as its denominator": (
        _a_header_names_no_denominator,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "a count with its own denominator, n/N (%), is not read": (
        _a_count_with_its_own_denominator_is_not_read,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
    ),
    "a table in a fenced listing is read": (
        _a_table_in_a_fenced_listing_is_read,
        test_an_n_percent_in_a_table_is_read_where_it_stands_and_held_to_its_denominator,
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
    "a quotation is in straight marks only": (
        _a_quotation_is_in_straight_marks_only,
        test_a_quotation_is_found_with_the_works_its_sentences_cite_and_no_other,
    ),
    "a quotation takes its paragraph's citations": (
        _a_quotation_takes_its_paragraphs_citations,
        test_a_quotation_is_found_with_the_works_its_sentences_cite_and_no_other,
    ),
    "a citation key stops at a colon": (
        _a_citation_key_stops_at_a_colon,
        test_a_quotation_is_found_with_the_works_its_sentences_cite_and_no_other,
    ),
    "a quotation with words left out is looked for whole": (
        _a_quotation_is_looked_for_whole,
        test_a_quotation_with_words_left_out_is_found_piece_by_piece,
    ),
    "the pieces of a quotation are looked for in any order": (
        _the_pieces_of_a_quotation_are_looked_for_anywhere,
        test_a_quotation_with_words_left_out_is_found_piece_by_piece,
    ),
    "a word an earlier paper breaks at the end of a line is two words": (
        _a_word_broken_at_a_line_end_is_two,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a ligature of an earlier paper is a letter of its own": (
        _a_ligature_is_a_letter_of_its_own,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a number is a word of a passage": (
        _a_number_is_a_word,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "eleven shared words are a passage": (
        _eleven_shared_words_are_reported,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a quotation of an earlier paper is recycled text": (
        _a_quotation_is_recycled_text,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a word changed ends a passage": (
        _a_word_changed_ends_the_passage,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a heading is compared with an earlier paper": (
        _a_heading_is_compared,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a statement under the Methods is compared as the Methods": (
        _a_statement_under_the_methods_is_the_methods,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a theme of the Results named as a statement is, is a statement": (
        _a_theme_of_the_results_is_a_statement,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a statement is set apart and not compared": (
        _a_statement_is_set_apart,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "the reference list is compared with an earlier paper": (
        _the_reference_list_is_compared,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "the conclusions are a part of their own beside the Discussion": (
        _the_conclusions_are_a_part_of_their_own,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a supplement's heading names no part": (
        _a_supplement_s_heading_names_no_part,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a supplement's prefix comes off any heading": (
        _a_supplement_s_prefix_comes_off_any_heading,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "a heading that opens with a statement's words is a statement": (
        _a_heading_opening_with_a_statement_s_word_is_one,
        test_a_passage_of_an_earlier_paper_is_found_where_it_stands_however_it_is_set,
    ),
    "[sic] is taken for a word of the source": (
        _sic_is_a_word_of_the_source,
        test_a_quotation_with_words_left_out_is_found_piece_by_piece,
    ),
    "[sic] is taken for words left out": (
        _sic_leaves_words_out,
        test_a_quotation_with_words_left_out_is_found_piece_by_piece,
    ),
    "a piece of a quotation may stand inside a word": (
        _a_piece_may_stand_inside_a_word,
        test_a_quotation_with_words_left_out_is_found_piece_by_piece,
    ),
    "a quotation in a comment is read": (
        _a_quotation_in_a_comment_is_read,
        test_a_quotation_is_found_with_the_works_its_sentences_cite_and_no_other,
    ),
    "a heading is part of the paragraph under it": (
        _a_heading_is_part_of_the_paragraph_under_it,
        test_an_anchor_claims_the_text_back_to_the_anchor_before_it_or_its_paragraph,
    ),
    "a unit is read after a plain space only": (
        _a_unit_is_read_after_a_plain_space_only,
        test_the_unit_after_a_binding_is_read_however_spaced_and_no_word_is,
    ),
    "a technical sense counts towards the vocabulary rate in the plural": (
        _a_technical_sense_counts_in_the_plural,
        test_a_technical_sense_adds_nothing_to_the_vocabulary_rate,
    ),
    "a comment in the gap runs on to the next": (
        _a_comment_in_the_gap_runs_on_to_the_next,
        test_the_unit_after_a_binding_is_read_however_spaced_and_no_word_is,
    ),
    "a unit is read after a space character only": (
        _a_unit_is_read_after_a_space_character_only,
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
    "a limit is read inside a longer number": (
        _a_limit_is_read_inside_a_longer_number,
        test_a_limit_is_stated_by_its_number_and_by_no_longer_one,
    ),
    "a limit is read before a decimal": (
        _a_limit_is_read_before_a_decimal,
        test_a_limit_is_stated_by_its_number_and_by_no_longer_one,
    ),
    "a limit has no separator of thousands": (
        _a_limit_has_no_separator_of_thousands,
        test_a_limit_is_stated_by_its_number_and_by_no_longer_one,
    ),
    "a limit's word is read inside a longer word": (
        _a_limit_s_word_is_read_inside_a_longer_word,
        test_a_limit_is_stated_by_its_number_and_by_no_longer_one,
    ),
    "a limit is read after a space between thousands": (
        _a_limit_is_read_after_a_space_between_thousands,
        test_a_limit_is_stated_by_its_number_and_by_no_longer_one,
    ),
    "a group of three digits before a space is a thousand": (
        _a_group_of_three_before_a_space_is_a_thousand,
        test_a_limit_is_stated_by_its_number_and_by_no_longer_one,
    ),
    "a quote is on its page as characters": (
        _a_quote_is_on_its_page_as_characters,
        test_a_quote_is_on_its_page_as_the_words_it_is,
    ),
    "a quote is looked for once on its page": (
        _a_quote_is_looked_for_once_on_its_page,
        test_a_quote_is_on_its_page_as_the_words_it_is,
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
    "a comment in a plan's section is compared": (
        _comments_are_compared,
        test_a_section_of_two_plans_differs_only_where_its_words_do,
    ),
    "a plan's section is compared in its case": (
        _case_is_compared,
        test_a_section_of_two_plans_differs_only_where_its_words_do,
    ),
    "a numbered heading names another section": (
        _a_number_makes_another_heading,
        test_a_section_of_two_plans_differs_only_where_its_words_do,
    ),
    "the plans' own Deviations are compared": (
        _the_deviations_are_compared,
        test_a_section_of_two_plans_differs_only_where_its_words_do,
    ),
    "a heading that stands twice is compared by its first": (
        _a_heading_that_stands_twice_is_compared_first,
        test_a_section_of_two_plans_differs_only_where_its_words_do,
    ),
    "what the plans' Deviations hold is compared": (
        _what_the_deviations_hold_is_compared,
        test_a_section_of_two_plans_differs_only_where_its_words_do,
    ),
    "only a section's first words are compared": (
        _only_the_first_words_are_compared,
        test_a_section_of_two_plans_differs_only_where_its_words_do,
    ),
    "a dictionary's definition is compared in its case": (
        _a_definition_is_compared_in_its_case,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "a dictionary's definition keeps its line breaks": (
        _a_definition_keeps_its_line_breaks,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "only a definition's first words are compared": (
        _only_a_definition_s_first_words_are_compared,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "codes are compared by their list's name": (
        _codes_are_compared_by_their_list_s_name,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "a code's label or a standard's term is compared in its case": (
        _a_label_or_a_term_is_compared_in_its_case,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "an ordinal scale's order is not compared": (
        _an_ordinal_scale_s_order_is_not_compared,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "a range's bound is compared as written": (
        _a_bound_is_compared_as_written,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "a range's time bound is compared as text": (
        _a_time_bound_is_compared_as_text,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "a range's bound is read by its own side's type": (
        _each_bound_is_read_by_its_own_type,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "a derived variable's inputs are compared in their order": (
        _inputs_are_compared_in_their_order,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "only a standard's release is compared": (
        _only_a_standard_s_release_is_compared,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "the study period is not compared": (
        _the_study_period_is_not_compared,
        test_a_variable_of_two_data_dictionaries_differs_only_where_it_is_recorded_otherwise,
    ),
    "a printed value is compared as text only": (
        _a_printed_value_is_text,
        test_a_value_an_earlier_output_printed_is_this_one_however_it_was_printed,
    ),
    "a number with no digit before its point is text": (
        _a_digit_before_the_point,
        test_a_value_an_earlier_output_printed_is_this_one_however_it_was_printed,
    ),
    "groups of thousands are not read": (
        _no_groups_of_thousands,
        test_a_value_an_earlier_output_printed_is_this_one_however_it_was_printed,
    ),
    "a middle dot is not a point": (
        _no_middle_dot,
        test_a_value_an_earlier_output_printed_is_this_one_however_it_was_printed,
    ),
    "a percent sign is not read": (
        _no_percent_sign,
        test_a_value_an_earlier_output_printed_is_this_one_however_it_was_printed,
    ),
    "a minus sign is not a minus": (
        _no_minus_sign,
        test_a_value_an_earlier_output_printed_is_this_one_however_it_was_printed,
    ),
    "a whole unit of the coarser printing is the same value": (
        _a_whole_unit_is_the_same,
        test_a_value_an_earlier_output_printed_is_this_one_however_it_was_printed,
    ),
    "the finer printing decides the places": (
        _the_finer_printing_decides,
        test_a_value_an_earlier_output_printed_is_this_one_however_it_was_printed,
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
    "a vector figure's transforms are not read": (
        _transforms_are_not_read,
        test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a vector figure's transforms are composed the other way round": (
        _transforms_are_composed_the_other_way,
        test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a point in a vector figure is read as a unit": (
        _a_point_is_a_unit,
        test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "an em is taken of SVG's default size, not of the size around it": (
        _an_em_is_of_the_default_size,
        test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a text drawn through use is not read": (
        _a_use_is_not_followed,
        test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a text is as tall as a line under the same transforms is wide": (
        _a_text_is_as_tall_as_a_line_is_wide,
        test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a text's size not set is 10": (
        _a_size_not_set_is_ten,
        test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a line is not widened by the transforms around it": (
        _a_line_is_not_widened,
        test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a PDF's transforms are composed the other way round": (
        _a_pdf_s_transforms_are_composed_the_other_way,
        test_a_pdf_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "Q does not give back what q saved": (
        _q_does_not_give_back_what_it_saved,
        test_a_pdf_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a PDF's text matrix is not read": (
        _the_text_matrix_is_not_read,
        test_a_pdf_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a PDF form is drawn without its matrix": (
        _a_form_is_drawn_without_its_matrix,
        test_a_pdf_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a PDF form is not drawn": (
        _a_form_is_not_drawn,
        test_a_pdf_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a filled path in a PDF is a line": (
        _a_filled_path_is_a_line,
        test_a_pdf_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a PDF form draws with a line width and font size of its own": (
        _a_form_draws_with_a_state_of_its_own,
        test_a_pdf_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a page's content streams are drawn apart": (
        _a_page_s_streams_are_drawn_apart,
        test_a_pdf_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a PDF text is as tall as a line under the same transforms is wide": (
        _a_pdf_text_is_as_tall_as_a_line_is_wide,
        test_a_pdf_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "a vector figure's stylesheet is not read": (
        _a_figure_s_stylesheet_is_not_read,
        test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
    ),
    "the first number of a font shorthand is its size": (
        _a_font_s_first_number_is_its_size,
        test_a_vector_figure_s_text_and_lines_are_read_at_the_size_they_are_drawn,
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
    "a dictionary's release is typed wherever it stands, named or not": (
        _a_release_is_typed_wherever_it_stands,
        test_a_dictionary_release_is_found_typed_where_its_name_stands_before_it,
    ),
    "a dictionary is named by a longer word that holds its name": (
        _a_dictionary_is_named_inside_a_longer_word,
        test_a_dictionary_release_is_found_typed_where_its_name_stands_before_it,
    ),
    "a release with a v before it is not read": (
        _a_release_with_a_v_before_it_is_not_read,
        test_a_dictionary_release_is_found_typed_where_its_name_stands_before_it,
    ),
    "a v that ends a word is taken for one before a release": (
        _a_v_ending_a_word_is_taken_for_one_before_a_release,
        test_a_dictionary_release_is_found_typed_where_its_name_stands_before_it,
    ),
    "a dictionary is named anywhere before its release on the line": (
        _a_dictionary_is_named_anywhere_before_on_its_line,
        test_a_dictionary_release_is_found_typed_where_its_name_stands_before_it,
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
    "a binding in a reply is read as a number": (
        _a_reply_is_read_unmasked,
        test_a_binding_in_a_reply_is_never_read_as_a_number,
    ),
    "a quote is looked for with its line breaks": (
        _a_quote_keeps_its_line_breaks,
        test_a_quote_is_found_however_its_lines_are_wrapped,
    ),
    "a nought is trimmed off a number": (
        _a_nought_is_trimmed_off_a_number,
        test_a_number_is_seen_where_it_stands_and_judged_one_way,
    ),
    "Katakana is taken for a script the gates read": (
        _katakana_is_read,
        test_every_character_of_a_script_the_gates_do_not_read_is_counted,
    ),
    "a character is counted more than once": (
        _a_character_of_two_scripts_is_counted_twice,
        test_every_character_of_a_script_the_gates_do_not_read_is_counted,
    ),
    "an ISBN-13 is weighed as an ISBN-10": (
        _an_isbn_13_is_weighed_as_an_isbn_10,
        test_an_isbn_is_valid_by_its_check_digit_and_one_digit_changed_is_not,
    ),
    "short words are dropped from a cited title": (
        _short_words_are_dropped_from_a_title,
        test_a_cited_title_is_found_in_its_registered_form_and_not_in_another,
    ),
    "a British title is read as written": (
        _a_british_title_is_read_as_written,
        test_a_cited_title_is_found_in_its_registered_form_and_not_in_another,
    ),
    "a registry's tag is read as a space": (
        _a_tag_is_read_as_a_space,
        test_a_cited_title_is_found_in_its_registered_form_and_not_in_another,
    ),
    "a TeX command takes the letters after it": (
        _a_tex_command_takes_the_letters_after_it,
        test_a_cited_title_is_found_in_its_registered_form_and_not_in_another,
    ),
    "a cited title is compared both ways": (
        _a_title_is_compared_both_ways,
        test_a_cited_title_is_found_in_its_registered_form_and_not_in_another,
    ),
    "a family name must agree whole, particles and all": (
        _a_family_name_must_agree_whole,
        test_a_family_name_is_one_person_s_however_a_registry_writes_it,
    ),
    "an accent is a letter of its own": (
        _an_accent_is_a_letter_of_its_own,
        test_a_family_name_is_one_person_s_however_a_registry_writes_it,
    ),
    "ue is not u with a diaeresis": (
        _ue_is_not_u_umlaut,
        test_a_family_name_is_one_person_s_however_a_registry_writes_it,
    ),
    "an apostrophe parts a name": (
        _an_apostrophe_parts_a_name,
        test_a_family_name_is_one_person_s_however_a_registry_writes_it,
    ),
    "a name a letter off is the name": (
        _a_name_a_letter_off_is_the_name,
        test_a_family_name_is_one_person_s_however_a_registry_writes_it,
    ),
    "a given name holds no part of a family name": (
        _a_given_name_holds_no_part_of_a_family_name,
        test_a_family_name_is_one_person_s_however_a_registry_writes_it,
    ),
    "a searched title is held one way": (
        _a_searched_title_is_held_one_way,
        test_a_searched_title_is_the_cited_one_only_each_way,
    ),
    "the whole registered title is held back to the cited one": (
        _the_whole_registered_title_is_held_back,
        test_a_searched_title_is_the_cited_one_only_each_way,
    ),
    "a subtitle the registry left out counts against the cited title": (
        _a_cited_subtitle_counts_against_it,
        test_a_searched_title_is_the_cited_one_only_each_way,
    ),
    "an ISBN-10 is not read as its ISBN-13": (
        _an_isbn_10_is_not_read_as_its_isbn_13,
        test_one_work_is_one_work_however_its_identifiers_are_written,
    ),
    "an ISBN's groups are read as ISBNs": (
        _an_isbn_s_groups_are_read_as_isbns,
        test_an_isbn_is_valid_by_its_check_digit_and_one_digit_changed_is_not,
    ),
    "a label without brackets sticks to its ISBN": (
        _a_label_without_brackets_sticks_to_its_isbn,
        test_an_isbn_is_valid_by_its_check_digit_and_one_digit_changed_is_not,
    ),
    "a DOI's resolver is undressed only as it was": (
        _a_doi_s_resolver_is_undressed_only_as_it_was,
        test_one_work_is_one_work_however_its_identifiers_are_written,
    ),
    "a label is read across sentences": (
        _a_label_is_read_across_sentences,
        test_a_label_is_said_where_it_differs_from_what_was_emitted_and_nowhere_else,
    ),
    "every sentence dates the data": (
        _every_sentence_dates_the_data,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "no sentence dates the data": (
        _no_sentence_dates_the_data,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "the words of the whole text are read as a date's sentence": (
        _the_words_of_the_whole_text_are_read,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "a binding's key is read as its sentence's words": (
        _a_binding_s_key_is_read_as_its_sentence_s_words,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "a dataset's date is taken for a typed one": (
        _a_dataset_s_date_is_taken_for_a_typed_one,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "a parameter's date is taken for a typed one": (
        _a_parameter_s_date_is_taken_for_a_typed_one,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "a date only its display writes is not read": (
        _a_date_only_its_display_writes_is_not_read,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "a comment's words date the data": (
        _a_comment_s_words_are_read,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "a dictionary's release is taken for a typed date": (
        _a_dictionary_s_release_is_taken_for_a_typed_date,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "other bindings and citations are read as words": (
        _other_bindings_and_citations_are_read_as_words,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "the words of a period covered are not read": (
        _the_words_of_a_period_covered_are_not_read,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "only the forms first written are read": (
        _only_the_forms_first_written_are_read,
        test_a_date_typed_into_the_analysis_is_warned_where_its_sentence_dates_the_data,
    ),
    "the first level in a sentence is read": (
        _the_first_level_is_read,
        test_a_label_is_said_where_it_differs_from_what_was_emitted_and_nowhere_else,
    ),
    "levels are compared as written": (
        _levels_are_compared_as_written,
        test_a_label_is_said_where_it_differs_from_what_was_emitted_and_nowhere_else,
    ),
    "a label after a spread is not read": (
        _a_label_after_a_spread_is_not_read,
        test_a_label_is_said_where_it_differs_from_what_was_emitted_and_nowhere_else,
    ),
    "an abbreviation's stop never ends a sentence": (
        _an_abbreviations_stop_never_ends_a_sentence,
        test_a_label_is_said_where_it_differs_from_what_was_emitted_and_nowhere_else,
    ),
    "an abbreviation's stop ends a sentence": (
        _an_abbreviations_stop_ends_a_sentence,
        test_a_label_is_said_where_it_differs_from_what_was_emitted_and_nowhere_else,
    ),
    "a level after the letters is not read": (
        _a_level_after_the_letters_is_not_read,
        test_a_label_is_said_where_it_differs_from_what_was_emitted_and_nowhere_else,
    ),
    "every stop is read in one sentence": (
        _every_stop_is_in_one_sentence,
        test_a_statistic_is_alone_only_in_a_sentence_without_what_it_belongs_to,
    ),
    "a stop after s.e. ends a quote's sentence": (
        _a_stop_after_s_e_ends_a_quote_s_sentence,
        test_a_statistic_is_alone_only_in_a_sentence_without_what_it_belongs_to,
    ),
    "a share is held to nothing": (
        _a_share_is_held_to_nothing,
        test_a_statistic_is_alone_only_in_a_sentence_without_what_it_belongs_to,
    ),
    "an accession number is no identifier": (
        _an_accession_number_is_no_identifier,
        test_each_identifier_names_data_and_each_temporary_link_is_found,
    ),
    "a link to a release is temporary": (
        _a_release_is_temporary,
        test_each_identifier_names_data_and_each_temporary_link_is_found,
    ),
    "a denial of openly had is not read": (
        _a_denial_is_not_read,
        test_a_statement_is_held_to_each_source_s_route_whatever_surrounds_it,
    ),
    "a denial is read only beside its phrase": (
        _a_denial_is_read_only_beside_its_phrase,
        test_a_statement_is_held_to_each_source_s_route_whatever_surrounds_it,
    ),
    "an open source said open after a denial excuses nothing": (
        _an_open_source_said_after_a_denial_excuses_nothing,
        test_a_statement_is_held_to_each_source_s_route_whatever_surrounds_it,
    ),
    "asking the corresponding author is not asking": (
        _one_way_of_asking_is_not_read,
        test_a_statement_is_held_to_each_source_s_route_whatever_surrounds_it,
    ),
    "a source is named inside a longer word": (
        _a_name_is_found_inside_a_word,
        test_a_source_is_named_in_any_writing_of_its_names_and_never_inside_a_word,
    ),
    "a source's name is read as typed": (
        _a_name_is_read_as_typed,
        test_a_source_is_named_in_any_writing_of_its_names_and_never_inside_a_word,
    ),
    "a karyotype is read as a placeholder": (
        _a_karyotype_is_a_placeholder,
        test_every_placeholder_is_found_and_nothing_that_looks_like_one,
    ),
    "a word in lower case is a placeholder outside the manuscript": (
        _a_word_in_lower_case_is_a_placeholder_anywhere,
        test_every_placeholder_is_found_and_nothing_that_looks_like_one,
    ),
    "a link's text is read as a slot": (
        _a_links_text_is_a_slot,
        test_every_placeholder_is_found_and_nothing_that_looks_like_one,
    ),
    "an em dash typed as three hyphens is not counted": (
        _an_em_dash_typed_is_not_counted,
        test_an_em_dash_is_counted_however_it_is_typed,
    ),
    "an edit's words are found only as they are typed": (
        _an_edit_is_found_only_as_typed,
        test_an_edit_s_words_are_found_where_they_stand_typed_or_printed_and_nowhere_else,
    ),
    "an edit's words are found inside longer words": (
        _an_edit_is_found_inside_longer_words,
        test_an_edit_s_words_are_found_where_they_stand_typed_or_printed_and_nowhere_else,
    ),
    "a line break between an edit's words is no space": (
        _a_line_break_between_an_edit_s_words_is_no_space,
        test_an_edit_s_words_are_found_where_they_stand_typed_or_printed_and_nowhere_else,
    ),
    "a value is not moved along by the words written before it": (
        _a_value_is_not_moved_along_by_the_words_written_before_it,
        test_a_suggestion_is_written_where_its_words_are_and_nothing_else_changes,
    ),
    "a suggestion is written inside code or a link": (
        _a_suggestion_is_written_inside_code_or_a_link,
        test_a_suggestion_is_written_where_its_words_are_and_nothing_else_changes,
    ),
    "emphasis is in the way of a suggestion": (
        _emphasis_is_in_the_way_of_a_suggestion,
        test_a_suggestion_is_written_where_its_words_are_and_nothing_else_changes,
    ),
    "a suggestion is written across a line break": (
        _a_suggestion_is_written_across_a_line_break,
        test_a_suggestion_is_written_where_its_words_are_and_nothing_else_changes,
    ),
    "words in a comment are counted with the paragraph's": (
        _words_in_a_comment_are_counted,
        test_a_suggestion_is_written_where_its_words_are_and_nothing_else_changes,
    ),
    "a rule's or a table's dashes are em dashes": (
        _a_rule_or_a_table_s_dashes_are_em_dashes,
        test_an_em_dash_is_counted_however_it_is_typed,
    ),
    "any run of hyphens is an em dash": (
        _any_run_of_hyphens_is_an_em_dash,
        test_an_em_dash_is_counted_however_it_is_typed,
    ),
    "filler before a list item is not read": (
        _filler_ends_only_at_a_stop_a_blank_line_or_the_end,
        test_every_placeholder_is_found_and_nothing_that_looks_like_one,
    ),
    "an instruction marked or linked is not read": (
        _an_instruction_marked_or_linked_is_a_link_s_text,
        test_every_placeholder_is_found_and_nothing_that_looks_like_one,
    ),
    "Word's prompt is read without what it asks for": (
        _words_prompt_is_read_without_what_it_asks_for,
        test_every_placeholder_is_found_and_nothing_that_looks_like_one,
    ),
    "any request after 'in this section' is a template's": (
        _any_request_after_in_this_section_is_a_template_s,
        test_every_placeholder_is_found_and_nothing_that_looks_like_one,
    ),
    "any quoted word after 'please state' is a statement offered": (
        _any_quoted_word_after_please_state_is_a_statement,
        test_every_placeholder_is_found_and_nothing_that_looks_like_one,
    ),
    "a cited entry's field wholly in brackets is read without them": (
        _a_field_wholly_in_brackets_is_read_without_them,
        test_every_placeholder_is_found_and_nothing_that_looks_like_one,
    ),
    "the reviewers are read as one reviewer": (
        _the_reviewers_are_one_reviewer,
        test_every_residue_is_found_by_its_rule_and_nothing_that_reads_like_one,
    ),
    "a blank line ends no residue": (
        _a_blank_line_ends_no_phrase,
        test_every_residue_is_found_by_its_rule_and_nothing_that_reads_like_one,
    ),
    "the acknowledgements are read for residue": (
        _the_acknowledgements_are_read,
        test_every_residue_is_found_by_its_rule_and_nothing_that_reads_like_one,
    ),
    "the contributions are read for residue": (
        _the_contributions_are_read,
        test_every_residue_is_found_by_its_rule_and_nothing_that_reads_like_one,
    ),
    "a dossier sent to an agency is a submission": (
        _a_dossier_is_a_submission,
        test_every_residue_is_found_by_its_rule_and_nothing_that_reads_like_one,
    ),
    "lines in capitals are lines": (
        _lines_in_capitals_are_lines,
        test_every_residue_is_found_by_its_rule_and_nothing_that_reads_like_one,
    ),
    "a change is named mid-clause": (
        _a_change_is_named_mid_clause,
        test_every_residue_is_found_by_its_rule_and_nothing_that_reads_like_one,
    ),
    "an argument that turns a figure's estimate off is not read": (
        _an_argument_that_turns_an_estimate_off_is_not_read,
        test_a_call_that_estimates_is_found_unless_it_is_told_not_to,
    ),
    "a named argument of a call nested in a figure's call is its own": (
        _a_named_argument_of_a_nested_call_is_the_call_s,
        test_a_call_that_estimates_is_found_unless_it_is_told_not_to,
    ),
    "a comparison in a figure's call names an argument": (
        _a_comparison_names_an_argument,
        test_a_call_that_estimates_is_found_unless_it_is_told_not_to,
    ),
    "a call whose bracket is left open is no call": (
        _a_call_left_open_is_no_call,
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
    "a planned item runs past its paragraph": (
        _a_planned_item_runs_past_its_paragraph,
        test_a_planned_result_is_read_from_its_own_item_and_nowhere_else,
    ),
    "code with no dot is a planned key": (
        _code_with_no_dot_is_a_planned_key,
        test_a_planned_result_is_read_from_its_own_item_and_nowhere_else,
    ),
    "a bound key keeps its namespace": (
        _a_bound_key_keeps_its_namespace,
        test_a_planned_result_is_read_from_its_own_item_and_nowhere_else,
    ),
    "a bound key needs a dot": (
        _a_bound_key_needs_a_dot,
        test_a_planned_result_is_read_from_its_own_item_and_nowhere_else,
    ),
    "the Planned results' subsections are not read": (
        _the_planned_results_subsections_are_not_read,
        test_a_planned_result_is_read_from_its_own_item_and_nowhere_else,
    ),
    **{
        f"in a plan, {said}": (
            broken,
            test_a_variable_is_read_from_the_plan_outside_its_deviations_and_nowhere_else,
        )
        for said, broken in (
            ("the Deviations name variables", _the_deviations_name_variables),
            ("the Deviations end at their first subsection",
             _the_deviations_end_at_their_first_subsection),
            ("the plan's title may be its Deviations", _the_plan_s_title_may_be_its_deviations),
            ("the Deviations run to the next section", _the_deviations_run_to_the_next_section),
            ("any heading with a change's word is the Deviations",
             _any_heading_with_a_change_s_word_is_the_deviations),
            ("a heading naming the planned results is never the Deviations",
             _a_heading_that_names_the_planned_results_is_never_the_deviations),
            ("code in brackets is a variable", _code_in_brackets_is_a_variable),
            ("a value in backticks is a variable", _a_value_in_backticks_is_a_variable),
            ("a dotted name is never a variable", _a_dotted_name_is_never_a_variable),
            ("a variable is matched without its case", _a_variable_is_matched_without_its_case),
            ("a variable is said at its last mention", _a_variable_is_said_at_its_last_mention),
            ("fences and comments name variables", _fences_and_comments_name_variables),
        )
    },
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
    "a figure sent as a file is not counted": (
        _a_figure_sent_as_a_file_is_not_counted,
        test_a_pointer_names_what_the_document_carries_or_is_said,
    ),
    "a document's figures are counted one too many": (
        _one_figure_more_is_counted_than_the_supplement_carries,
        test_a_pointer_names_what_the_document_carries_or_is_said,
    ),
    "a bound pointer is read as pointing where its binding does": (
        _a_bound_pointer_points_where_its_binding_does,
        test_a_ref_prints_the_number_its_display_has_or_is_said,
    ),
    "tables and figures are numbered in the order of their files' paths": (
        _displays_are_numbered_in_the_order_of_their_paths,
        test_a_ref_prints_the_number_its_display_has_or_is_said,
    ),
    "the supplement's tables are numbered with the paper's": (
        _the_supplement_s_displays_are_numbered_with_the_paper_s,
        test_a_ref_prints_the_number_its_display_has_or_is_said,
    ),
    "a caption is not held to the display it stands beside": (
        _a_caption_is_not_held_to_its_display,
        test_a_ref_prints_the_number_its_display_has_or_is_said,
    ),
    "a table's caption is read only under it": (
        _a_table_s_caption_is_read_only_under_it,
        test_a_ref_prints_the_number_its_display_has_or_is_said,
    ),
    "a caption between two tables is held to both": (
        _a_caption_between_two_tables_is_held_to_both,
        test_a_ref_prints_the_number_its_display_has_or_is_said,
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
    "the Methods are taken in the order they stand, not by name first": (
        _the_methods_are_taken_in_the_order_they_stand,
        test_the_methods_named_as_such_are_read_before_a_heading_that_only_holds_the_word,
    ),
    "the Methods' name is read as typed when they are put first": (
        _the_methods_name_is_read_as_typed,
        test_the_methods_named_as_such_are_read_before_a_heading_that_only_holds_the_word,
    ),
    "no supplement's name of the Methods is a place the Methods are": (
        _no_supplement_names_the_methods,
        test_a_supplement_s_methods_are_the_methods_to_each_gate_that_reads_them,
    ),
    "a supplement's name of the Methods with words after it is not one": (
        _a_supplement_s_name_with_words_after_it_is_no_methods,
        test_a_supplement_s_methods_are_the_methods_to_each_gate_that_reads_them,
    ),
    "only the first of a supplement's Methods is read": (
        _only_the_first_of_a_supplement_s_methods_is_read,
        test_a_supplement_s_methods_are_the_methods_to_each_gate_that_reads_them,
    ),
    "a section of a supplement's Methods under one read is read again": (
        _a_section_under_one_read_is_read_again,
        test_a_supplement_s_methods_are_the_methods_to_each_gate_that_reads_them,
    ),
    "a supplement's name of the Methods holds every section under it": (
        _a_supplement_s_name_holds_every_section_under_it,
        test_a_supplement_s_methods_are_the_methods_to_each_gate_that_reads_them,
    ),
    "G9 reads everything under a supplement's Methods heading": (
        _g9_reads_all_under_a_supplement_s_methods,
        test_a_supplement_s_methods_are_the_methods_to_each_gate_that_reads_them,
    ),
    "a number's sign is no part of it": (
        _a_sign_is_no_part_of_its_number,
        test_a_rewording_passes_and_what_else_an_edit_did_is_found_where_it_stands,
    ),
    **{
        f"no {kind} is counted in a sentence's claim": (
            partial(_a_class_of_claim_words_is_not_counted, kind=kind),
            test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
        )
        for kind in ("hedge", "limit", "negation")
    },
    "the ladder of a claim is read upside down": (
        _the_ladder_is_read_upside_down,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a word of the ladder that only came or left is a claim moved": (
        _a_ladder_word_that_only_came_or_left_is_a_claim_moved,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a word of the ladder made another of its rung is a change": (
        _a_ladder_word_made_another_of_its_rung_is_a_change,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a claim's word with a capital is read anywhere": (
        _a_capital_is_read_anywhere,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a claim's word with a capital is never read": (
        _a_capital_is_never_read,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a participle after an article is read as a claim's word": (
        _a_participle_after_an_article_is_read,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a word in a compound is read as a claim's word": (
        _a_word_in_a_compound_is_read,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "inline code is read for a claim's words": (
        _inline_code_is_read_as_prose,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a comment is read for a claim's words": (
        _a_comment_is_read_as_prose,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    **{
        what: (
            breaking,
            test_a_marked_up_copy_shows_each_change_where_it_was_made_and_reads_as_both_documents,
        )
        for what, breaking in (
            ("a deleted stretch of a paragraph is left out", _a_deleted_stretch_is_left_out),
            ("deleted text is written as text kept", _deleted_text_is_written_as_text_kept),
            ("how a word looks is not compared", _how_a_word_looks_is_not_compared),
            ("a row added is not tracked as a row", _a_row_is_not_tracked_as_a_row),
            ("a note is kept as the revision has it", _a_note_is_kept_as_the_revision_has_it),
            ("a table is never merged cell by cell", _a_table_is_never_merged_cell_by_cell),
            ("a deleted picture points where it did", _a_deleted_picture_points_where_it_pointed),
            ("a paragraph's style is not compared", _a_style_is_not_compared),
            ("no paragraph is alike enough to be edited", _nothing_is_alike_enough_to_be_edited),
        )
    },
    "the sentences of two texts are lined up by place alone": (
        _the_texts_are_lined_up_by_place_alone,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a sentence added whole is read as a claim made": (
        _a_sentence_added_whole_is_read,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a stop ends no sentence whose claim is read": (
        _a_stop_ends_no_sentence_of_a_claim,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a line that opens a block opens no sentence whose claim is read": (
        _a_line_that_opens_a_block_opens_no_sentence,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "an ordered item of a list opens no sentence whose claim is read": (
        partial(_block_opens_no_sentence_at, kind=r"|\d+[.)][ \t]", read_as=""),
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a line of blanked text is no blank line between claims": (
        partial(_block_opens_no_sentence_at, kind=r"[ \t\x00]", read_as=r"[ \t]"),
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "the front matter is read for a claim as one line": (
        _the_front_matter_is_read_as_one_line,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a month that opens a sentence is read as a claim's hedge": (
        _may_is_read_with_a_capital_where_it_opens_a_sentence,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "the lowest rung of a claim kept is read as a claim made weaker": (
        _the_lowest_rung_kept_is_a_claim_made_weaker,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
    ),
    "a sentence split in two is compared for its claim by place": (
        _a_split_sentence_is_compared_by_place,
        test_a_claim_made_stronger_weaker_or_turned_round_is_told_where_it_stands,
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
