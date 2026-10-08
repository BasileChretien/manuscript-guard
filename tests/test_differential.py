"""Old against new: the same generated inputs read by the base branch's source and by this one.

Of everything the independent reviews did by hand, this was the commonest and the most
useful: main's module beside the branch's, on thousands of generated inputs, with every
difference either one the change meant or a finding. "The abbreviation reading is not
touched" was a sentence in a pull request until a reviewer ran 1,500 projects through both
trees. Here CI runs it, on the readings of `tests/readings.py` and the inputs of
`tests/generated.py`, and a difference fails.

**Two processes, never one.** The package imports itself by its full name everywhere, so a
second copy loaded beside the first would use the first's modules wherever it imported one,
and the comparison would be of a thing with itself: silent, and always passing. Each side is
a process of its own with one source on its path, and says in its first line which package
it found there. A reader that found another is refused.

**The base is exported, not checked out.** `git archive` writes the base commit's
`src/manuscript_guard` into a temporary folder. No worktree is registered and no ref is
made, so a run that is killed leaves nothing in a repository several sessions share.

**Which commit is the base.** `MANUSCRIPT_GUARD_BASE` names it. For a pull request CI
checks out the merge GitHub made of it into the base branch, and names that merge's first
parent: the commit of the base branch the merge was made on, so that the two sides differ
by the pull request and by nothing else. Named and not found, the run fails, and so does a
name that is set and empty: a job that is there to compare must not pass by having nothing
to compare with. Unset, it is where this branch left `origin/main`, and where that cannot
be told the comparison is skipped; the tests of the comparison itself, below, need no base
and always run.

**A change that is meant.** A pull request that changes what a gate reports differs from
its base, and says so in `tests/data/differential_expected.yaml`: the reading, and why. An
entry counts only in the pull request that adds it, since once it is merged the base has
it too. That reading then lists its differences and passes; every other reading still
fails on one. And an entry for a reading that turns out not to differ fails, so that the
file cannot say more than the change does.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml
from differential import (
    BASE,
    EXPECTED,
    Lost,
    Reader,
    base_commit,
    declared,
    exported,
    first_difference,
    new_entries,
    same_source,
    summarised,
)
from generated import INPUTS, generated, times
from hypothesis import given
from readings import READINGS, Unavailable, why_not

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "src" / "manuscript_guard"

pytestmark = pytest.mark.usefixtures("stopped_if_stuck")

#: How many inputs each reading is compared on. `check` makes a project on disk in each
#: process for every one, and `import` builds a document and imports it.
EXAMPLES = dict.fromkeys(READINGS, 300) | {"check": 20, "import": 15}
#: And how many when the two sides are this same source under two hash seeds.
RESEEDED = dict.fromkeys(READINGS, 40) | {"check": 3, "import": 2}


# ------------------------------------------------------------------------- the two sides


@pytest.fixture(scope="module")
def here() -> Iterator[Reader]:
    """The working tree's source, read in a process of its own."""
    with Reader(REPO / "src") as reader:
        yield reader


@pytest.fixture(scope="module")
def reseeded() -> Iterator[Reader]:
    with Reader(REPO / "src", hash_seed="1") as reader:
        yield reader


class _GaveUp(BaseException):
    """A reader was lost while a generated test was running. Not an `Exception`, and not
    `pytest.fail`: Hypothesis takes either for a failing input and cuts the input down,
    and a lost reader is no finding about the input. Every smaller one would fail the same
    way, a hang would be waited for again at each, and the smallest of them would be named
    as the cause. This goes straight through Hypothesis, and `_unless_lost` makes the
    failure of it."""


def _asked(reader: Reader, name: str, given: Any) -> Any:
    try:
        return reader.ask(name, given)
    except Lost as lost:
        raise _GaveUp(str(lost)) from None


@contextmanager
def _unless_lost() -> Iterator[None]:
    try:
        yield
    except _GaveUp as gave_up:
        pytest.fail(str(gave_up), pytrace=False)


def _unavailable(why: str) -> bool:
    """Whether a reading is missing for want of a program, and not of a name in the source."""
    return why.startswith("Unavailable: ")


def _skip_where_it_cannot_be_made(name: str, *readers: Reader) -> None:
    """Pass over a reading that needs a program this machine lacks, pandoc for the round
    trip. CI has it, pinned, in every job that runs pytest."""
    for reader in readers:
        if _unavailable(reader.absent.get(name, "")):
            pytest.skip(reader.absent[name])


def differences(name: str, old: Reader, new: Reader, examples: int) -> list[tuple[Any, str]]:
    """Every generated input the two read differently, each with where the answers part."""
    found: list[tuple[Any, str]] = []

    @generated(examples)
    @given(INPUTS[name])
    def collect(given: Any) -> None:
        where = first_difference(_asked(old, name, given), _asked(new, name, given))
        if where is not None:
            found.append((given, where))

    with _unless_lost():
        collect()
    return found


def assert_alike(name: str, old: Reader, new: Reader, examples: int, *, sides: str) -> None:
    """Fail on the first input the two read differently, cut down to the smallest."""

    @generated(examples)
    @given(INPUTS[name])
    def alike(given: Any) -> None:
        where = first_difference(_asked(old, name, given), _asked(new, name, given))
        assert where is None, f"{name!r} reads {given!r} differently in {sides}: {where}"

    with _unless_lost():
        alike()


# ----------------------------------------------------------- the comparison is a comparison


def test_the_reader_found_the_source_it_was_given_and_every_reading_in_it(here: Reader) -> None:
    assert here.package == PACKAGE.resolve()
    lacking = {name: why for name, why in here.absent.items() if not _unavailable(why)}
    assert lacking == {}, "a reading of tests/readings.py cannot be found in this source"
    assert here.broken == {}, "a reading of tests/readings.py cannot be made of this source"


def test_a_source_that_is_not_the_one_asked_for_is_refused(tmp_path: Path) -> None:
    """With nothing at the path it was given, Python finds the package wherever else it is
    installed: this checkout in CI, and on a machine with several worktrees, another one.
    Compared against that, a change would be measured against the wrong tree, or against
    itself."""
    (tmp_path / "src").mkdir()
    with pytest.raises(Lost, match="not the source it was given|could not be started"):
        Reader(tmp_path / "src")


@pytest.mark.parametrize("name", sorted(READINGS))
def test_under_another_hash_seed_a_reading_answers_the_same(
    name: str, here: Reader, reseeded: Reader
) -> None:
    """Python orders a set by a seed it draws at each start. A reading that walks one gives
    answers that change from run to run: terms of one length were once tried in an order
    that did. It is also what holds the comparison itself to being exact: two processes on
    one source must not differ, or every difference from the base is in doubt."""
    _skip_where_it_cannot_be_made(name, here, reseeded)
    assert_alike(name, here, reseeded, RESEEDED[name], sides="two processes on this source")


#: One line changed in a copy of the source, and the reading that has to notice. The first
#: is a mutant that the review of #181 found alive: the offset of a quotation's lines losing
#: one character at each line break.
CHANGED = {
    "the offset of a quotation": (
        "gates/vocabulary.py",
        "        offset += len(line) + 1\n",
        "        offset += len(line)\n",
        "own words",
    ),
    "a ligature no longer folded": (
        "literature/sources.py",
        '    "\\N{LATIN SMALL LIGATURE FF}": "ff",\n',
        "",
        "quotation",
    ),
    "a bracket that holds no dollar sign": (
        "text/tex.py",
        '_HOLDS_A_DOLLAR = "`<[@"\n',
        '_HOLDS_A_DOLLAR = "`<@"\n',
        "tex outside maths",
    ),
    "fewer words before one finding": (
        "gates/spelling.py",
        "MANY = 5\n",
        "MANY = 2\n",
        "spelling",
    ),
    "a trailing sign kept on a number": (
        "text/tokens.py",
        "_TRAIL = \")]}>\\\"'",
        "_TRAIL = \"]}>\\\"'",
        "numbers",
    ),
    "an import that writes no rewording": (
        "merge.py",
        "        if replacement != original:\n",
        "        if replacement == original:\n",
        "import",
    ),
    "a sign that is no part of its number": (
        "reworded.py",
        "        held = (\"-\" if sign and sign in _MINUS else sign) + number[\"figures\"]\n",
        "        held = number[\"figures\"]\n",
        "reworded",
    ),
    "a finding that points at another file": (
        "gates/vocabulary.py",
        "                path=passage.path,\n",
        "                path=paper,\n",
        "vocabulary",
    ),
}


def _changed_copy(case: str, folder: Path) -> Reader:
    """A reader for a copy of this source with the one line of `case` changed."""
    file, old, new, _reading = CHANGED[case]
    return _copy_with(file, old, new, folder)


def _copy_with(file: str, old: str, new: str, folder: Path) -> Reader:
    """A reader for a copy of this source in which `old` of `file` reads `new`."""
    shutil.copytree(
        PACKAGE, folder / "src" / "manuscript_guard", ignore=shutil.ignore_patterns("__pycache__")
    )
    path = folder / "src" / "manuscript_guard" / file
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{file} no longer holds the line this case changes"
    path.write_bytes(text.replace(old, new, 1).encode("utf-8"))
    reader = Reader(folder / "src")
    assert reader.package == (folder / "src" / "manuscript_guard").resolve()
    return reader


@pytest.mark.parametrize("case", sorted(CHANGED))
def test_a_rule_changed_in_a_copy_is_a_difference_in_its_reading(
    case: str, here: Reader, tmp_path: Path
) -> None:
    """The comparison has to fail when the source changes, or it guards nothing. Each case
    changes one line of a copy of this source, and the reading that goes through that line
    must differ from this source's on some generated input; a reading that does not go
    through it must not."""
    reading = CHANGED[case][3]
    _skip_where_it_cannot_be_made(reading, here)
    with _changed_copy(case, tmp_path) as changed:
        # A session of the round trip takes seconds, and one is enough: the first one
        # played is the simplest there is, three paragraphs with the first reworded, and
        # its rewording lands. More of them could not change the result. What the drawn
        # sessions are is held in `tests/test_generated_sessions.py`.
        examples = 1 if reading == "import" else 120
        assert differences(reading, here, changed, examples), f"{reading!r} did not notice"
        untouched = "title" if reading != "tex outside maths" else "quotation"
        assert not differences(untouched, here, changed, 30)


def test_a_version_raised_alone_is_no_difference(here: Reader, tmp_path: Path) -> None:
    """The version is raised on main in a pull request that changes nothing else, after
    every merge that touches the source. That pull request must not have to say it means a
    difference: nothing a reading reports may hold the version."""
    shutil.copytree(
        PACKAGE, tmp_path / "src" / "manuscript_guard", ignore=shutil.ignore_patterns("__pycache__")
    )
    path = tmp_path / "src" / "manuscript_guard" / "__init__.py"
    text = path.read_text(encoding="utf-8")
    (line,) = (line for line in text.splitlines() if line.startswith('__version__ = "'))
    path.write_bytes(text.replace(line, '__version__ = "999.0.0"', 1).encode("utf-8"))
    with Reader(tmp_path / "src") as raised:
        assert_alike("check", here, raised, 4, sides="this source and one of another version")


def compared(name: str, old: Reader, new: Reader, meant: dict[str, str], examples: int) -> None:
    """One reading of the base beside the working tree's, held to what the pull request
    says of it: no difference, or the difference `meant` gives a reason for."""
    if name not in meant:
        assert_alike(name, old, new, examples, sides="the base and the working tree")
        return
    found = differences(name, old, new, examples)
    assert found, (
        f"{EXPECTED.name} says {name!r} will differ from the base, and on "
        f"{examples * times()} generated inputs it does not: take the entry out"
    )
    message = (
        f"{name!r} differs from the base on {len(found)} of {examples * times()} "
        f"generated inputs, as {EXPECTED.name} says it will ({meant[name]}):\n"
        f"{summarised(found)}"
    )
    warnings.warn(message, stacklevel=2)
    _on_the_jobs_page("A change that was meant", message)


def against_the_base(
    name: str, new: Reader, old: Reader, meant: dict[str, str], examples: int
) -> None:
    """One reading of the working tree held to the base's, whatever the base can do.

    A reading the base does not have is passed over, and that is written on the job's
    page as well as among the skips. A reading the base has and cannot make is a
    comparison that was not made: it fails, unless the pull request says it changed what
    the reading goes through, and then it passes with that said. Any other is compared."""
    _skip_where_it_cannot_be_made(name, new, old)
    if name in old.broken:
        message = (
            f"the base cannot make the reading {name!r} ({old.broken[name]}), so nothing "
            "was compared"
        )
        assert name in meant, (
            f"{message}. If this pull request changed what the reading goes through, say "
            f"so in {EXPECTED.name}; if not, the base cannot be read here"
        )
        message += f", as {EXPECTED.name} says ({meant[name]})"
        warnings.warn(message, stacklevel=2)
        _on_the_jobs_page("A reading that could not be compared", message)
        return
    if name in old.absent:
        assert name not in meant, f"{name!r} is said to differ, and the base has no such reading"
        message = f"the base has no reading {name!r}: {old.absent[name]}"
        _on_the_jobs_page("A reading with no base", message)
        pytest.skip(message)
    compared(name, old, new, meant, examples)


def must_have_a_reading(old: Reader) -> None:
    """A base that can be asked for none of the readings is no base: every comparison
    would be passed over, and the run would be green for having compared nothing."""
    without = {**old.absent, **old.broken}
    assert set(READINGS) - set(without), (
        f"the base has none of the readings, so nothing would be compared: {without}"
    )


def _on_the_jobs_page(heading: str, said: str) -> None:
    """Write to the page GitHub makes of a job, where whoever reviews the change will
    look: a skip or a warning is one line among the run's hundreds."""
    page = os.environ.get("GITHUB_STEP_SUMMARY")
    if page:
        with open(page, "a", encoding="utf-8") as summary:
            summary.write(f"### {heading}\n\n```\n{said}\n```\n\n")


def test_what_stops_a_reading_being_made_is_told_apart() -> None:
    """A source may have no answer for a reading because the reading is newer than the
    source, or needs a program that is not installed: that is passed over. Anything else
    that stops it is not the same thing, and was taken for it: a helper that takes other
    arguments now, a dependency the base cannot import under what is installed for the
    working tree. Passed over, those readings were not compared and the job was green."""
    newer = ModuleNotFoundError(
        "No module named 'manuscript_guard.gates.spelling'", name="manuscript_guard.gates.spelling"
    )
    renamed = ImportError(
        "cannot import name 'own_words' from 'manuscript_guard.gates.vocabulary'",
        name="manuscript_guard.gates.vocabulary",
    )
    assert why_not(newer) == why_not(renamed) == "absent"
    assert why_not(Unavailable("pandoc is not installed")) == "absent"
    assert why_not(ModuleNotFoundError("No module named 'jsonschema'", name="jsonschema")) == (
        "broken"
    )
    assert why_not(TypeError("_file() missing 1 required positional argument")) == "broken"
    assert why_not(AttributeError("module has no attribute")) == "broken"


#: The helper three readings go through, given one argument more: what a pull request does
#: that changes it, with `tests/readings.py` brought up to date in the same pull request.
_ANOTHER_ARGUMENT = (
    "gates/language.py",
    "def _file(order: int, path: Path, text: str, chain: list[Section], supplementary: bool)"
    " -> _File:\n",
    "def _file(order: int, path: Path, text: str, chain: list[Section], supplementary: bool,"
    " kind: str) -> _File:\n",
)


def test_a_base_that_cannot_make_a_reading_fails_unless_the_change_says_so(
    here: Reader, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The base here is a copy whose `_file` takes an argument this suite's readings do
    not give. It cannot make the three readings that go through it, and that is not the
    base lacking them: nothing was compared, so the run fails, unless the pull request
    says in `differential_expected.yaml` that it changed what those readings go through.
    A reading that does not go through `_file` is compared as ever."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    with _copy_with(*_ANOTHER_ARGUMENT, tmp_path) as base:
        assert set(base.broken) == {"vocabulary", "spelling", "abbreviations"}, base.broken
        assert all(why.startswith("TypeError: ") for why in base.broken.values()), base.broken
        assert not [why for why in base.absent.values() if not _unavailable(why)], base.absent
        with pytest.raises(AssertionError, match="the base cannot make the reading 'vocabulary'"):
            against_the_base("vocabulary", here, base, {}, 10)
        meant = {"vocabulary": "a file is read with its kind now"}
        with pytest.warns(UserWarning, match="cannot make the reading 'vocabulary'") as said:
            against_the_base("vocabulary", here, base, meant, 10)
        assert "a file is read with its kind now" in str(said[0].message)
        against_the_base("title", here, base, {}, 10)


def test_a_reading_passed_over_is_said_on_the_jobs_page(
    here: Reader, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reading the base does not have is skipped, and a skip is a line among hundreds.
    It is also written where a meant change is: on the page GitHub makes of the job."""
    page = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(page))
    lacks = "ImportError: cannot import name 'mask' from 'manuscript_guard.text.masking'"
    older = _worker(tmp_path, _hello(absent={"mask": lacks}) + "for line in sys.stdin:\n    pass\n")
    with Reader(REPO / "src", worker=older) as base:
        with pytest.raises(pytest.skip.Exception, match="the base has no reading 'mask'"):
            against_the_base("mask", here, base, {}, 5)
        with pytest.raises(AssertionError, match="is said to differ, and the base has no such"):
            against_the_base("mask", here, base, {"mask": "it is new"}, 5)
    assert "the base has no reading 'mask'" in page.read_text(encoding="utf-8")
    assert lacks in page.read_text(encoding="utf-8")


def test_a_base_with_none_of_the_readings_is_no_base(tmp_path: Path) -> None:
    """Every reading passed over is a comparison of nothing, and it was a green one."""
    lacks = dict.fromkeys(READINGS, "ImportError: cannot import name")
    nothing = _worker(tmp_path, _hello(absent=lacks) + "for line in sys.stdin:\n    pass\n")
    with (
        Reader(REPO / "src", worker=nothing) as base,
        pytest.raises(AssertionError, match="the base has none of the readings"),
    ):
        must_have_a_reading(base)
    with Reader(REPO / "src", worker=_worker(tmp_path, _HELLO + "sys.stdin.read()\n")) as base:
        must_have_a_reading(base)


def test_a_change_that_is_meant_passes_and_says_what_differs_and_any_other_fails(
    here: Reader, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The three ways a reading can stand to what the pull request says of it. The base
    here is a copy of this source that makes one finding of two misspelt words where this
    source makes it of five."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    with _changed_copy("fewer words before one finding", tmp_path) as base:
        with pytest.raises(AssertionError, match="'spelling' reads .* differently in the base"):
            compared("spelling", base, here, {}, 120)
        with pytest.warns(UserWarning, match="'spelling' differs from the base on") as said:
            compared("spelling", base, here, {"spelling": "one finding for five words"}, 120)
        assert "one finding for five words" in str(said[0].message)
        assert " at answer.findings" in str(said[0].message)
        with pytest.raises(AssertionError, match="it does not: take the entry out"):
            compared("title", base, here, {"title": "nothing, in truth"}, 30)


# ------------------------------------------------------------------ a reader that is lost


#: How a stand-in for the worker begins: by saying, as the real one does, which package it
#: found, and here that it is the one asked for.
def _hello(*, absent: dict[str, str]) -> str:
    return (
        "import json, sys\n"
        f"found = {{'package': {str(PACKAGE.resolve())!r}, 'absent': {absent!r}}}\n"
        "print(json.dumps(found), flush=True)\n"
    )


_HELLO = _hello(absent={})


def _worker(folder: Path, body: str) -> Path:
    path = folder / "worker.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_reader_that_stops_answering_is_stopped(tmp_path: Path) -> None:
    """A reading that hangs in the base must not hang the job. The reader is given a time
    to answer in, and is ended when it has not.

    That time is for an answer, not for the interpreter to start: this stand-in takes three
    seconds to say it is there and is given two to answer in. Held to two for its start
    as well, the reader was lost before it was asked anything wherever Python was slow to
    come up, which on a busy machine it is."""
    slow_to_start = "import time\ntime.sleep(3)\n"
    silent = _worker(tmp_path, slow_to_start + _HELLO + "for line in sys.stdin:\n    pass\n")
    reader = Reader(REPO / "src", worker=silent, within=2)
    with pytest.raises(Lost, match="no answer within 2 seconds"):
        reader.ask("mask", "a text")
    assert reader.process.poll() is not None, "the process was left running"
    with pytest.raises(Lost, match="no answer within 2 seconds"):
        reader.ask("mask", "another")


def test_a_reader_that_dies_says_what_it_printed(tmp_path: Path) -> None:
    broken = _worker(tmp_path, "import sys\nsys.exit('the base cannot be imported')\n")
    with pytest.raises(Lost, match="the base cannot be imported"):
        Reader(REPO / "src", worker=broken)


def test_a_lost_reader_ends_the_test_without_cutting_the_input_down(tmp_path: Path) -> None:
    """One input, asked once. Cut down, a hang would be waited for again at each smaller
    input, and the smallest input of all would be named as what hangs."""
    counting = _worker(
        tmp_path, _HELLO + "sys.stdin.readline()\nsys.exit('gone after one question')\n"
    )
    reader = Reader(REPO / "src", worker=counting, within=30)
    asked: list[Any] = []

    @generated(50)
    @given(INPUTS["mask"])
    def held(given: str) -> None:
        asked.append(given)
        _asked(reader, "mask", given)

    with pytest.raises(pytest.fail.Exception, match="gone after one question"), _unless_lost():
        held()
    assert len(asked) == 1, asked


# ------------------------------------------------------------------- where two answers part


def test_where_two_answers_part_is_named() -> None:
    same = {"answer": {"findings": [["G14", "term-avoided", 3]], "counts": {"found": 1}}}
    assert first_difference(same, same) is None
    other = {"answer": {"findings": [["G14", "term-avoided", 4]], "counts": {"found": 1}}}
    assert first_difference(same, other) == "answer.findings[0][2]: 3 in the first, 4 in the second"
    longer = {"answer": {"findings": [*same["answer"]["findings"], ["G2"]], "counts": {"found": 1}}}
    assert "answer.findings: 1 in the first, 2 in the second" in first_difference(same, longer)
    raised = {"raised": "KeyError: 'use'"}
    assert first_difference(same, raised) == (
        "the first answered and the second raised KeyError: 'use'"
    )
    assert "absent" not in first_difference({"answer": 1}, {"answer": "1"})
    fewer = {"answer": {"findings": [], "counts": {"found": 1}}}
    more = {"answer": {"findings": [], "counts": {"found": 1, "spelling_own": 0}}}
    assert first_difference(fewer, more) == "answer.counts: only the second has 'spelling_own'"
    long = first_difference({"answer": "a" * 1000}, {"answer": "b" * 1000})
    assert len(long) < 500 and "(1002 characters)" in long


# ----------------------------------------------------------------- a change that is meant


def test_the_differences_of_a_meant_change_are_told_by_kind() -> None:
    """A reviewer reads a meant change against what its author said of it. A list of five
    hundred inputs is no help; how many part where, and the shortest of each, is."""
    found = [
        ({"text": "a long text with subjects in it"}, "answer.findings[0].hint: 'x' in the first"),
        ({"text": "subjects"}, "answer.findings[3].hint: 'x' in the first"),
        ({"text": "> subjects"}, "answer.counts.vocabulary_found: 0 in the first, 1 in the second"),
    ]
    assert summarised(found).splitlines() == [
        "2 at answer.findings[#].hint, the shortest of them {'text': 'subjects'}",
        "      answer.findings[3].hint: 'x' in the first",
        "1 at answer.counts.vocabulary_found, the shortest of them {'text': '> subjects'}",
        "      answer.counts.vocabulary_found: 0 in the first, 1 in the second",
    ]


def test_an_entry_counts_only_in_the_pull_request_that_adds_it() -> None:
    """Merged, an entry is in the base too, and must stop excusing anything: the next
    change to that reading is a new change. And the same reading can be declared again,
    for another reason."""
    was = declared("expected:\n  - reading: vocabulary\n    why: the first change\n")
    now = declared(
        "expected:\n  - reading: vocabulary\n    why: the first change\n"
        "  - reading: spelling\n    why: |\n      a list\n      brought up to date\n"
    )
    assert new_entries(now, was) == {"spelling": "a list brought up to date"}
    assert new_entries(now, now) == {}
    assert new_entries(now, []) == {
        "vocabulary": "the first change",
        "spelling": "a list brought up to date",
    }
    again = declared("expected:\n  - reading: vocabulary\n    why: a second change\n")
    assert new_entries(again, was) == {"vocabulary": "a second change"}
    assert declared("expected: []\n") == [] == declared("# nothing\n")


@pytest.mark.parametrize(
    "written",
    [
        "expected:\n  - reading: vocabulary\n",
        "expected:\n  - reading: vocabulary\n    why: ''\n",
        "expected:\n  - why: no reading named\n",
        "expected:\n  - vocabulary\n",
        "expected: vocabulary\n",
        "expected:\n  - reading: vocabulary\n    why: one\n    also: this\n",
        "expected:\n  - reading: vocabulary\n    why: one\n  - reading: vocabulary\n    why: two\n",
    ],
    ids=["no why", "an empty why", "no reading", "a word", "no list", "a third key", "twice"],
)
def test_an_entry_that_does_not_say_what_and_why_is_refused(written: str) -> None:
    with pytest.raises(ValueError, match="differential_expected.yaml"):
        declared(written)


def test_the_declarations_name_readings_this_suite_has() -> None:
    for entry in declared(EXPECTED.read_text(encoding="utf-8")):
        assert entry.reading in READINGS, f"{EXPECTED.name} names no reading: {entry.reading!r}"


# ----------------------------------------------------------------------------- the base


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *arguments],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )  # fmt: skip


needs_git = pytest.mark.skipif(
    shutil.which("git") is None or _git("rev-parse", "HEAD").returncode != 0,
    reason="not a git checkout",
)


@needs_git
def test_the_export_of_a_commit_is_that_commits_package(tmp_path: Path) -> None:
    source = exported("HEAD", tmp_path / "base")
    at_head = _git("show", "HEAD:src/manuscript_guard/__init__.py").stdout
    assert (source / "manuscript_guard" / "__init__.py").read_text(encoding="utf-8") == at_head
    listed = _git("ls-tree", "-r", "--name-only", "HEAD", "src/manuscript_guard").stdout.split()
    found = {p.relative_to(source.parent).as_posix() for p in source.rglob("*") if p.is_file()}
    assert found == set(listed)
    assert same_source(source, source)
    (source / "manuscript_guard" / "__init__.py").write_text(at_head + "\n", encoding="utf-8")
    assert not same_source(source, exported("HEAD", tmp_path / "again"))


@needs_git
def test_a_base_that_is_named_and_not_found_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A job that sets the base is there to compare. Skipping where the commit was not
    fetched would be a green check for a comparison that never ran."""
    monkeypatch.setenv(BASE, "0000000000000000000000000000000000000001")
    with pytest.raises(LookupError, match=BASE):
        base_commit()
    monkeypatch.setenv(BASE, "HEAD")
    assert base_commit() == _git("rev-parse", "HEAD").stdout.strip()
    # Named, and the name is empty: what a workflow's expression leaves when it finds
    # nothing. Read as not named, the comparison was skipped and the job was green.
    for nothing in ("", "  "):
        monkeypatch.setenv(BASE, nothing)
        with pytest.raises(LookupError, match=f"{BASE} is set and names no commit"):
            base_commit()


@needs_git
# What 3.12 and 3.13 say of an extraction with no filter, which is this test's subject.
@pytest.mark.filterwarnings("ignore:Python 3.14 will, by default, filter:DeprecationWarning")
def test_the_export_asks_nothing_of_python_that_3_10_11_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`tarfile` took its extraction filters in 3.10.12, and 3.10.11 is the last 3.10 with
    an installer: it is what CI's Windows and macOS jobs run. There `extractall` has no
    `filter` to be given, and the export raised. This is `tarfile` as 3.10.11 has it."""
    real = tarfile.TarFile.extractall

    def extractall(self, path=".", members=None, *, numeric_owner=False):  # noqa: ANN001
        return real(self, path, members, numeric_owner=numeric_owner)

    monkeypatch.setattr(tarfile.TarFile, "extractall", extractall)
    monkeypatch.delattr(tarfile, "data_filter", raising=False)
    source = exported("HEAD", tmp_path / "base")
    at_head = _git("show", "HEAD:src/manuscript_guard/__init__.py").stdout
    assert (source / "manuscript_guard" / "__init__.py").read_text(encoding="utf-8") == at_head


def test_the_job_compares_with_the_commit_the_merge_was_made_on() -> None:
    """For a pull request GitHub checks out a merge of it into the base branch as that
    branch stands. The commit to compare with is that merge's first parent. It is not
    `pull_request.base.sha`: GitHub stores that with the pull request and does not move it
    when the base branch moves, so once main had merged anything the job compared an older
    main with the merge. Everything main took in since then counted as this pull request's
    change, and an entry another pull request had declared and merged excused its reading
    here too (#83's stored base was four commits of main behind the merge its last run
    checked out).

    The first parent is the base only of that merge. So the job may not be told to check
    out anything else, and has to fetch at least two commits deep."""
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    job = workflow["jobs"]["old-against-new"]
    _names_the_merges_first_parent(job)

    def checked_out(**given: Any) -> dict[str, Any]:
        """The job with its checkout step given these settings in place of its own."""
        steps = [
            {**step, "with": given} if "actions/checkout" in step.get("uses", "") else step
            for step in job["steps"]
        ]
        return {**job, "steps": steps}

    # `HEAD^1` is the base only while `HEAD` is the merge GitHub made. Told to check out
    # the pull request's own head, the job would compare its last commit with the one
    # before, and pass where an earlier commit changed a reading.
    with pytest.raises(AssertionError, match="not GitHub's merge"):
        _names_the_merges_first_parent(
            checked_out(**{"fetch-depth": 2, "ref": "${{ github.event.pull_request.head.sha }}"})
        )
    # One commit deep, the first parent is not there to be named.
    for shallow in ({"fetch-depth": 1}, {}):
        with pytest.raises(AssertionError, match="first parent is not fetched"):
            _names_the_merges_first_parent(checked_out(**shallow))
    # Deeper is as good, and so is the whole history.
    _names_the_merges_first_parent(checked_out(**{"fetch-depth": 0}))
    _names_the_merges_first_parent(checked_out(**{"fetch-depth": 50}))


def _names_the_merges_first_parent(job: dict[str, Any]) -> None:
    named = job["env"][BASE]
    assert "base.sha" not in named, named
    assert "github.event_name == 'pull_request' && 'HEAD^1'" in named, named
    checkout = next(step for step in job["steps"] if "actions/checkout" in step.get("uses", ""))
    given = checkout.get("with", {})
    assert "ref" not in given, "what is checked out is not GitHub's merge, so HEAD^1 is no base"
    depth = given.get("fetch-depth", 1)
    assert depth == 0 or depth >= 2, "the merge's first parent is not fetched"


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Reader, dict[str, str]]]:
    """The base branch's source in a process of its own, and the differences this pull
    request declares."""
    if shutil.which("git") is None or _git("rev-parse", "HEAD").returncode != 0:
        pytest.skip("not a git checkout, so there is no base to compare with")
    commit = base_commit()
    if commit is None:
        pytest.skip(f"{BASE} is not set and origin/main is not here, so there is no base")
    source = exported(commit, tmp_path_factory.mktemp("base"))
    at_base = _git("show", f"{commit}:{EXPECTED.relative_to(REPO).as_posix()}")
    meant = new_entries(
        declared(EXPECTED.read_text(encoding="utf-8")),
        declared(at_base.stdout) if at_base.returncode == 0 else [],
    )
    if same_source(source, REPO / "src"):
        assert not meant, (
            f"{EXPECTED.name} says {sorted(meant)} will differ from the base, and "
            "src/manuscript_guard is as the base has it"
        )
        pytest.skip(f"src/manuscript_guard is as {commit[:12]} has it: nothing to compare")
    with Reader(source) as reader:
        must_have_a_reading(reader)
        yield reader, meant


@pytest.mark.parametrize("name", sorted(READINGS))
def test_the_working_tree_reads_as_the_base_does(
    name: str, here: Reader, base: tuple[Reader, dict[str, str]]
) -> None:
    old, meant = base
    against_the_base(name, here, old, meant, EXAMPLES[name])
