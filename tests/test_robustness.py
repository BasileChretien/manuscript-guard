"""`check` has to survive a hostile or merely careless manuscript.

DESIGN says `check` is safe to run on a manuscript someone sent you, and that claim is why
`verify` is a separate command: `check` never executes project code. But "does not execute
code" is not the same as "cannot be made to hang or exhaust memory", and nothing tested the
second half.

A security review found three ways in, all reachable by accident rather than only by malice:

* a document with many fence-opener-shaped lines and no closer made the fence regex
  quadratic — 3,000 lines pushed `check` past a minute;
* a figure sibling of any size was read whole, and so was the build's source stamp;
* a FIFO in `figures/` blocks a read forever on Linux and macOS, which is where CI runs, and
  nothing in the gate runner bounds wall-clock time.

What a hostile input adds to `check` is measured against a plain `check` on the same project,
in the process's own CPU time. It is a tripwire for a hang or a blow-up, not a benchmark,
and not the test that a scan is linear: at these sizes some inputs cost `check` ten times
its plain run while being linear, which leaves no room to tell a quadratic that adds a few
seconds from them. That is `assert_linear`'s job, one scan at a time.
"""

from __future__ import annotations

import functools
import gc
import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

BUDGET_SECONDS = 20.0

#: The most `check` may take on a hostile project, as a multiple of a plain `check` on the
#: same project, both in CPU time. The heaviest linear input here read up to 10.0 (one long
#: run of backticks), and the quadratic one known on main up to 12.3 (nested brackets,
#: `BRACKETED`). A ratio, so the same bound holds on a runner of any speed.
CHECK_OVERHEAD = 30.0
#: By the wall clock, which CPU time does not see: a `check` that waits instead of working,
#: on a read or a network call that takes its time and then returns. A wait under about a
#: minute passes, and one that never ends hangs the suite, as it always did. The first check
#: on a hostile project and the timed one after it took at most 21 s together, on a loaded
#: laptop.
HANG_SECONDS = 60.0
#: A ratio between the bound and twice it is measured again this many times before it
#: fails, each time a plain check then the hostile one, and the lowest pair's ratio stands:
#: a slow spell falls on both runs of a pair, where the best of each could fall in different
#: lulls. One at twice the bound or more fails at once. Unlike `check_linear`, which decides
#: that on a best of three, this is one timed run against the baseline: under host load in a
#: VM, one read 55, within 9% of it, and on Windows twice the cores busy raised them to 19.
CONFIRM = 3


def run_check(project: Path) -> None:
    """One `check` on `project`, untimed."""
    from manuscript_guard.cli import _run_gates

    _run_gates(project, stage="drafting")


def timed_check(project: Path) -> float:
    """The CPU time of one `check` on `project`, with the garbage collector off as
    `check_linear` has it. CPU time is `check`'s own work: not G7 waiting for Zotero to refuse
    its ping, 2 s on Windows and none on Linux, nor another process's."""
    collecting = gc.isenabled()
    gc.disable()
    try:
        started = time.process_time()
        run_check(project)
        return time.process_time() - started
    finally:
        if collecting:
            gc.enable()


@functools.cache
def plain_baseline(plain: Path) -> float:
    """The best of three checks on a plain copy of the example, once for each copy."""
    run_check(plain)  # imports, compiled patterns and first opens, off the clock
    return min(timed_check(plain) for _ in range(3))


@pytest.fixture(scope="module")
def plain_project(built_example: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A plain copy of the example, for the module's hostile checks to be measured against."""
    root = tmp_path_factory.mktemp("plain") / "paper"
    shutil.copytree(built_example, root, ignore=shutil.ignore_patterns("build", "__pycache__"))
    return root


def check_overhead(project: Path, plain: Path) -> float:
    """How many times a plain `check`'s CPU time `check` takes on `project`.

    The first run opens every file of a fresh copy for the first time, which costs Windows
    seconds, so it is off the ratio's clock; it is the one held to `HANG_SECONDS`. One more
    run decides a ratio under the bound, and one at twice the bound or more. One between is
    measured again, a plain check then the hostile one each time, and the lowest pair's
    ratio stands: a slow spell falls on both runs of a pair."""
    started = time.perf_counter()
    run_check(project)
    waited = time.perf_counter() - started
    assert waited < HANG_SECONDS, f"check took {waited:.0f} s by the wall clock"
    overhead = timed_check(project) / plain_baseline(plain)
    if overhead < CHECK_OVERHEAD or overhead / 2 >= CHECK_OVERHEAD:
        return overhead
    pairs = [(timed_check(plain), timed_check(project)) for _ in range(CONFIRM)]
    return min(second / first for first, second in pairs)


# ---------------------------------------------------------------- pathological text


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("stray fence openers", "".join(f"```lang{i}\n" for i in range(3000))),
        ("stray tilde openers", "".join(f"~~~lang{i}\n" for i in range(3000))),
        ("mixed openers, no closers", "".join(f"{'`' * (3 + i % 4)}x\n" for i in range(3000))),
        ("many short lines", "".join(f"Value {i} was observed.\n" for i in range(5000))),
        ("one very long line", "The ratio was " + "1.0 " * 8000 + "overall.\n"),
        ("nested-looking brackets", "[" * 5000 + "9.99" + "]" * 5000 + "\n"),
        ("many citations", " ".join(f"[@key{i}]" for i in range(3000)) + "\n"),
        ("many headings", "".join(f"## Section {i}\n\nProse.\n\n" for i in range(1500))),
        ("setext underlines", "".join(f"Heading {i}\n---\n\nProse.\n\n" for i in range(1500))),
        ("comment openers, no closer", "<!-- " * 5000 + "\n"),
        (
            "unmatched backtick runs",
            " ".join("`" * n + "x" for n in range(1, 400)) + " <!-- x\n",
        ),
        ("one long backtick run", "a " + "`" * 200_000 + " <!-- x\n"),
    ],
    # Explicit ids: pytest builds one from the parameters otherwise, and puts it in
    # PYTEST_CURRENT_TEST — which Windows refuses past 32767 characters, so a 60 KB body
    # turns every case in this table into a collection error rather than a test.
    ids=lambda value: value if isinstance(value, str) and len(value) < 60 else "",
)
def test_check_finishes_on_pathological_prose(
    project: Path, name: str, body: str, plain_project: Path
) -> None:
    """A scan that blows up on prose someone might write, or a wait of a minute or more that
    ends: one that never does hangs the suite."""
    (project / "manuscript" / "pathological.md").write_text(body, encoding="utf-8")
    overhead = check_overhead(project, plain_project)
    assert overhead < CHECK_OVERHEAD, f"{name}: check took {overhead:.1f} times a plain one"


def opener_lines(count: int) -> str:
    return "".join(f"```lang{i}\n" for i in range(count))


def test_the_fence_scanner_is_linear(assert_linear) -> None:
    """Measured directly, because the gate budget is too coarse to see a slide.

    The regex this replaced took 0.24s at 1,000 opener-shaped lines and 6.09s at 4,000 —
    quadratic. The first attempt at handling unterminated fences reintroduced it at 55s for
    8,000.
    """
    from manuscript_guard.text.fences import fenced_spans

    assert_linear(opener_lines, fenced_spans, 50, "the fence scanner")


def test_the_linear_check_refuses_work_too_quick_to_time(assert_linear) -> None:
    """A ratio of microseconds is noise, so a size that never reaches the floor is an error
    in the test, not a pass."""
    with pytest.raises(ValueError, match="too little to time"):
        assert_linear(opener_lines, len, 10, "len")


def narrowing_openers(openers: int) -> str:
    """Unclosed openers, each narrower than the last, with a long listing's worth of lines
    under each."""
    return "".join("`" * (width + 3) + "\n" + "x\n" * 2000 for width in range(openers, 0, -1))


def test_the_fence_scanner_is_linear_when_each_opener_is_narrower(assert_linear) -> None:
    """The shortcut that fixed the test above rejected only openers *wider* than one already
    known to have no closer. Openers each narrower than the last still read to the end of
    the file, and 400 KB of them took 33 seconds: the binding parser now reads fences
    whenever a paper holds `<!--`, so that reached `parse` too.

    Checked twice, like paragraph tagging. That reading, in Python, fails in ten seconds
    from 5 openers and takes three and a half minutes from 25. The same reading done by one
    regex search per opener, at C speed, passes from 5 and fails from 25. It was timed once
    per size at 25 and 200 openers."""
    from manuscript_guard.text.fences import fenced_spans

    for start in (5, 25):
        assert_linear(
            narrowing_openers, fenced_spans, start, f"narrowing fence openers from {start}"
        )


def test_a_long_run_of_backticks_is_read_in_linear_time(assert_linear, monkeypatch) -> None:
    """Code spans were found with a pattern that retried from every position inside a run
    of backticks: one line of 20,000 took seven seconds to read for comments. They are now
    read only on a line holding a mark that could open a comment or raw block. A line
    without one never reached them, and the test passed with that pattern put back, so this
    line holds a comment and the test first checks that it is read for code spans."""
    from manuscript_guard.text import fences

    def backticks(count: int) -> str:
        return "# Results\n\nSee " + "`" * count + " there. <!-- a note -->\n"

    read: list[str] = []
    spans = fences._without_code_spans

    def spy(line: str) -> str:
        read.append(line)
        return spans(line)

    monkeypatch.setattr(fences, "_without_code_spans", spy)
    fences.unclear_fence_lines(backticks(10))
    monkeypatch.undo()
    assert read, "the line is never read for code spans"
    assert_linear(backticks, fences.unclear_fence_lines, 5000, "a long run of backticks")


@pytest.mark.parametrize(
    "block",
    [
        lambda count: "<pre>\n" + "<pre " * count,
        lambda count: "\\begin{a}\n" + "\\begin{a}" * count,
        lambda count: "".join(f"\\begin{{e{i}}}\\end{{e{i}}}" for i in range(count)),
    ],
    ids=["tags", "environments", "distinct names"],
)
def test_marks_inside_a_raw_block_are_read_in_linear_time(block, assert_linear) -> None:
    """Inside a raw block, its closer and another of its name were each searched for from
    the last mark to the end of the line, mark by mark: a line of 300,000 characters took
    eighteen seconds. Every mark on a line is now found in one pass."""
    from manuscript_guard.text.fences import unclear_fence_lines

    def raw(count: int) -> str:
        return "# R\n\n" + block(count) + "\n\n```r\nx\n```\n"

    assert_linear(raw, unclear_fence_lines, 4000, "marks inside a raw block")


def test_narrowing_openers_are_read_in_linear_time(assert_linear) -> None:
    """A run of openers each one backtick narrower than the last, with no closer: skipping
    only openers at least as wide as one known unclosed, each read to the end of the text,
    and a hundred over 85 KB took seconds a pass. The widest closer still to come is now
    read from the end once."""
    from manuscript_guard.text.fences import fenced_spans, unclear_fence_lines

    def openers_over(lines: int) -> str:
        return "".join("`" * (103 - i) + "\n" for i in range(100)) + "x\n" * lines

    def read(text: str) -> None:
        fenced_spans(text)
        unclear_fence_lines(text)

    assert_linear(openers_over, read, 10000, "a hundred narrowing openers, by the lines after")


def test_unclosed_attributes_are_read_in_linear_time(assert_linear) -> None:
    """Pandoc reads a fence's `{attributes}` on over lines. Reading them that way too, with a
    backslash before each newline read as an escape, took every opener to the end of the
    text: 8.8 seconds for 2,000 of them and 173 for 8,000. The gates now read an opener's
    attributes on its own line and refuse the rest, so doubling the input must not much
    more than double the time, and the refusal is read in the same pass."""
    from manuscript_guard.text.fences import fenced_spans, unclear_fence_lines

    def attributes(count: int) -> str:
        return (
            "```{k=a\\\n" * count
            + "```{.r\n"
            + ".x k=v\n" * count
            + "".join(f"```{{k='{i}\n" for i in range(count))
        )

    def read(text: str) -> None:
        fenced_spans(text)
        unclear_fence_lines(text)

    assert_linear(attributes, read, 4000, "unclosed attributes")


@pytest.mark.parametrize("value", ["[" * 6000, "- " * 20000], ids=["brackets", "sequences"])
def test_deeply_nested_front_matter_is_not_composed(value: str) -> None:
    """Front matter counts only where pandoc keeps it as metadata, which means reading the
    YAML, and every gate asks. Thousands of nesting levels took the pure-Python loader
    seconds to give up on, so nesting that deep is refused unread: it is nobody's metadata.
    """
    from manuscript_guard.build.assemble import strip_front_matter

    text = f"---\nnote: {value}\n---\n\nBody.\n"
    started = time.perf_counter()
    assert strip_front_matter(text) == (text, "")
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    "block",
    [
        pytest.param("[x]: u {" + "a=b" * 15, id="attribute-that-splits"),
        pytest.param("[x]: a" + " " * 1000 + "b", id="run-of-spaces"),
        pytest.param("[x]: a" + " " * 1000 + "\n b c", id="spaces-then-a-line"),
        pytest.param('[x]: u "' + 'a "b ' * 8000, id="unclosed-quotes"),
        pytest.param('[x]: u "t" {' + 'data-x="1" ' * 24, id="quoted-attributes"),
        pytest.param('[x]: "a\n' * 4000, id="quote-opening-each-line"),
        pytest.param("[x]: u\n" * 8000 + "prose", id="many-definitions"),
    ],
)
def test_a_link_definition_is_recognised_quickly(block: str) -> None:
    """`tag` asks of every block of every file whether it is a link definition, in build,
    check and import. Versions that modelled more of pandoc's grammar were caught in review
    taking seconds to minutes: an attribute that could be split two ways made `{a=ba=b...`
    exponential - 18 of them took a minute and a half - and so did quoted values; optional
    spaces stacked on optional spaces made a run of a thousand take six seconds; and a quote
    opening each line was scanned to the end of the block from every line."""
    from manuscript_guard.roundtrip import tag

    started = time.perf_counter()
    tag(block, "main.md")
    assert time.perf_counter() - started < 2.0


def test_definitions_over_a_paragraph_are_passed_over_in_linear_time(assert_linear) -> None:
    """Each definition passed over looked at the rest of the block for a title on the next
    line by copying it: 40,000 definitions over a paragraph took 42 seconds, where the
    definitions alone took a fifth of one."""
    from manuscript_guard.roundtrip import tag

    assert_linear(
        lambda count: "[x]: u\n" * count + "Prose.",
        lambda text: tag(text, "main.md"),
        5000,
        "passing over definitions above a paragraph",
    )


@pytest.mark.parametrize(
    "opener",
    [
        "Para <!-- open ",
        "\\begin{figure}\n",
        "\\begin{e#}\n",
        "<pre>\n",
        "---\nkey#: ",
        "--\nT\n--\n--\nT\n",
    ],
    ids=[
        "comment",
        "latex environment",
        "latex environments, all different",
        "pre",
        "yaml that never closes",
        "tables that each open straight under the last",
    ],
)
def test_paragraph_tagging_is_linear(assert_linear, opener: str) -> None:
    """A block that opens raw content with no closer used to search to the end of the text,
    once per block: 80,000 of them took 26 seconds, and `check` reaches this through G13.
    Distinct environment names are measured separately because a cache keyed by closing
    string fixed the repeated case and left each new name searching to the end of the text.

    Padded, because with short blocks the per-block work hides the search: at four times
    the input and without the fix the ratio was 13 to 17, and with it about 4.

    Checked twice, because no one start sees both kinds of quadratic. One running in Python,
    like the walk from every table opener that a3d0453 had, fails in seconds from 10 blocks
    and takes minutes from 1,000. One running at C speed, like a `find` to the end of the
    text for each comment's closer, sits on the bound from 10 blocks (15 to 20, failing on
    some runs and not others), so only the start of 1,000 is sure to catch it. A failure in
    the first pass ends the test. It was timed once per size at 4,000 and 16,000 blocks.
    """
    from manuscript_guard.roundtrip import tag

    def blocks(count: int) -> str:
        return "".join(opener.replace("#", str(i)) + "x" * 200 + "\n\n" for i in range(count))

    for start in (10, 1000):
        assert_linear(
            blocks, lambda text: tag(text, "main.md"), start, f"paragraph tagging from {start}"
        )


# The check itself, on a clock that only the job below moves: that it fails a quadratic,
# and how it handles noise. Each test catches a change to the check that the real scans
# above cannot see, because a real machine is neither quadratic nor noisy on cue. A real
# quadratic scan was timed here too, and cost more CI time than it told: the one below is
# exact.


def virtual_job(
    seconds: Callable[[int], float], slow: Callable[[int, int], float] | None = None
) -> tuple[Callable[[], float], Callable[[int], None], list[int]]:
    """A job whose `n` items take `seconds(n)` virtual seconds, times `slow(n, k)` on its
    `k`th call with `n`, counting from 0. Returns the clock, the work, and the sizes it was
    called with."""
    now = [0.0]
    seen: dict[int, int] = {}
    calls: list[int] = []

    def work(n: int) -> None:
        k = seen.get(n, 0)
        seen[n] = k + 1
        calls.append(n)
        now[0] += seconds(n) * (slow(n, k) if slow else 1.0)

    return (lambda: now[0]), work, calls


def same(n: int) -> int:
    return n


def test_one_slow_sample_does_not_fail_a_linear_job(assert_linear) -> None:
    """The first time the larger input runs, it runs ten times slow. Its best of three is
    linear; its mean, its worst, or a single sample reads 32 or more."""
    clock, work, _ = virtual_job(
        lambda n: n * 3e-5, lambda n, k: 10.0 if n == 8000 and k == 0 else 1.0
    )
    assert_linear(same, work, 1000, "a linear job", clock=clock)


def test_a_slow_first_round_is_measured_again_before_it_fails(assert_linear) -> None:
    """All three samples of the larger input run 2.5 times slow, and read 20: a verdict the
    next five samples overturn."""
    clock, work, _ = virtual_job(
        lambda n: n * 3e-5, lambda n, k: 2.5 if n == 8000 and k < 3 else 1.0
    )
    assert_linear(same, work, 1000, "a linear job", clock=clock)


def test_one_slow_sample_at_the_floor_does_not_choose_the_size(assert_linear) -> None:
    """1,000 items take 6 ms, and the first timed run of them 30 ms. The size is chosen on
    the best of three, so the check goes on to 4,000 items (24 ms) rather than stopping at a
    size whose real time is under the floor. The first call, `k` 0, is the untimed warm-up."""
    clock, work, calls = virtual_job(
        lambda n: n * 6e-6, lambda n, k: 5.0 if n == 1000 and k == 1 else 1.0
    )
    assert_linear(same, work, 1000, "a linear job", clock=clock)
    assert max(calls) == 8 * 4000


def test_the_two_sizes_are_timed_in_alternation(assert_linear) -> None:
    """So that a slow spell falls on both; timed one size after the other, a spell that
    covers the larger size's samples reads as a quadratic."""
    clock, work, calls = virtual_job(lambda n: n * 3e-5)
    assert_linear(same, work, 1000, "a linear job", clock=clock)
    first_large = calls.index(8000)
    assert calls[first_large - 1:] == [1000, 8000] * 3


@pytest.mark.parametrize(
    ("share", "fails"), [(0.2, True), (0.15, True), (0.13, False), (0.1, False)]
)
def test_the_bound_fails_a_quadratic_part_of_a_seventh(
    assert_linear, share: float, fails: bool
) -> None:
    """The check has to fail the regression it exists for, not just pass what is linear. A
    job whose quadratic part is `share` of its time on the smaller input reads 8 + 56 *
    share, and a seventh reads 16: a fifth (19.2) and 0.15 (16.4) fail, 0.13 (15.28) and a
    tenth (13.6) pass, which puts the bound between 15.28 and 16.4."""

    def seconds(n: int) -> float:
        return 0.024 * ((1 - share) * n / 1000 + share * (n / 1000) ** 2)

    clock, work, _ = virtual_job(seconds)
    if fails:
        with pytest.raises(AssertionError, match=f"took {8 + 56 * share:.1f}x the time"):
            assert_linear(same, work, 1000, "a job", clock=clock)
    else:
        assert_linear(same, work, 1000, "a job", clock=clock)


def test_the_garbage_collector_is_off_while_timing_and_on_after(assert_linear) -> None:
    """Off for every timed sample, and on again afterwards, even when the work raises in the
    middle of one: left off, it would stay off for the rest of the session."""
    import gc

    clock, work, _ = virtual_job(lambda n: n * 3e-5)
    collecting: list[bool] = []

    def watched(n: int) -> None:
        collecting.append(gc.isenabled())
        work(n)

    def fails_once_timed(n: int) -> None:
        collecting.append(gc.isenabled())
        if len(collecting) > 1:
            raise RuntimeError("the job failed")

    try:
        assert_linear(same, watched, 1000, "a linear job", clock=clock)
        # The first call is the warm-up, off the clock.
        assert collecting[0] and not any(collecting[1:])
        assert gc.isenabled()
        collecting.clear()
        with pytest.raises(RuntimeError, match="the job failed"):
            assert_linear(same, fails_once_timed, 1000, "a job that fails", clock=clock)
        assert collecting == [True, False]
        assert gc.isenabled()
    finally:
        gc.enable()


@pytest.mark.parametrize(
    "line",
    [
        "<!-- never closed\n", "Prose\n## Methods\n", "- item\n> quote\n| row |\n", "<div>\n",
        "<>" * 25,
    ],
    ids=[
        "unclosed comments", "paragraph and heading", "list quote row", "html divs",
        "one line of tags",
    ],
)
def test_the_heading_scan_is_linear(line: str, assert_linear) -> None:
    """`<!--.*?-->` read to the end of the text for every comment that never closed: 19 s
    for 20,000 such lines, and the heading scan runs once per file in G2, `explain` and the
    classifier's heading rules alike."""
    from manuscript_guard.text.blocks import find_headings

    def lines(count: int) -> str:
        return line * count

    assert_linear(lines, find_headings, 2000, "the heading scan")


@pytest.mark.parametrize(
    "line",
    ["# a" + " " * 3000 + "x\n", ":" * 3000 + " x y\n", "::: a" + ":" * 10000 + " y\n"],
    ids=["heading line of spaces", "line of colons", "colons after a div's class"],
)
def test_one_long_line_does_not_stall_the_heading_scan(line: str) -> None:
    """Two patterns backtracked on one line: the ATX heading's title and closing hashes, and
    a div fence's colons and class. A heading line holding 2,000 spaces took 67 s, and 1,000
    colons 20 s, in a command that reads every line of a file someone sent."""
    from manuscript_guard.text.blocks import find_headings, heading_shaped

    started = time.perf_counter()
    find_headings(line)
    heading_shaped([line])
    assert time.perf_counter() - started < 2.0


def test_the_section_chain_is_looked_up_not_rebuilt(assert_linear) -> None:
    """`chain_at` walked every heading before a number, for every number: 4,000 headings and
    12,000 numbers took 50 s in G2, and every line shaped like a heading is now an entry.
    The index is built off the clock; only the lookups are timed."""
    from manuscript_guard.text.sections import chain_at, heading_index

    def parts(count: int) -> tuple[list, range]:
        text = "".join(f"## Part {i}\n\nValues 1, 2 and 3.\n\n" for i in range(count))
        return heading_index(text), range(0, len(text), max(1, len(text) // (3 * count)))

    def look_up(given: tuple[list, range]) -> None:
        index, offsets = given
        for offset in offsets:
            chain_at(index, offset)

    assert_linear(parts, look_up, 250, "the section chain at every offset")


@pytest.mark.parametrize(
    "tail",
    [" *_" * 3000 + " x", " " * 9000 + "x"],
    ids=["emphasis marks", "spaces"],
)
def test_a_long_heading_title_does_not_stall_the_methods_check(tail: str) -> None:
    """`is_methods` reads every title in a number's chain, for every number and every rule
    that holds only in Methods. The patterns that trimmed a title's emphasis and attribute
    block backtracked from every character of a run of spaces or marks: a heading ending in
    1,000 ` *_` over five numbers took G2 36 s."""
    from manuscript_guard.classify import is_methods

    started = time.perf_counter()
    is_methods(("Outcomes" + tail, "Methods"))
    assert time.perf_counter() - started < 0.5


@pytest.mark.parametrize(
    "text",
    [" " * 20000, " " * 20000 + "x", "     \n" * 400, " |" * 10000 + "x"],
    ids=["one line of spaces", "spaces then a letter", "lines of spaces", "spaces and pipes"],
)
def test_table_alignment_row_does_not_stall_on_whitespace(text: str) -> None:
    """`table-alignment-row` was `^\\s*\\|?[\\s:|-]+\\|[\\s:|-]*$`. Its three pieces could all
    take the same spaces, and `\\s` took line breaks too, so the scan backtracked over every
    way of sharing them out: one line of 20,000 spaces took about 7 s, and 400 lines holding
    only spaces about 9 s. `check` scans every manuscript file with every rule.

    Whitespace alone, which this rule stalled on. Other rules stalled on a keyword followed by
    a long run of spaces: see the test below."""
    from manuscript_guard.classify import Classifier

    classifier = Classifier.load()
    started = time.perf_counter()
    classifier.scan(text)
    assert time.perf_counter() - started < 2.0


# A word a rule reads, a long run of spaces, and a character the rule does not take. Each rule
# here had neighbouring pieces that could take the same spaces, `\s*[-–]?\s*` say, and the scan
# backtracked through every way of sharing them out. The runs are sized so the old patterns took
# 4 to 60 seconds each. Scanned with every rule, the rewrites take under 0.1 s, and 0.3 s for
# "A-" repeated, where each of 28 rules looks at every one of 20,000 word boundaries.
SPACES = " " * 16000
STALLS = {
    # Six optional words, each after its own `\s*`: faster than the fourth power of the run.
    # 80 spaces took 3.7 s, which a fast runner could pass; 100 took 12 s.
    "checklist-item": "STROBE" + " " * 100 + "x",
    "age-band": "age" + " " * 800 + "x",
    "time-label": "day" + SPACES + "x",
    "cross-reference": "Table" + SPACES + "x",
    "categorical-label": "grade" + SPACES + "x",
    "significance-threshold": "p" + SPACES + "x",
    "alpha-level": "alpha" + SPACES + "x",
    "target-power": "power" + SPACES + "x",
    "coding-system-code": "MedDRA" + SPACES + "x",
    "balance-criterion": "caliper" + SPACES + "x",
    # How pandoc's own Markdown writer pads a table's cells: 9 s.
    "a padded table": ("| STROBE" + " " * 50 + "| Title and abstract | 1 |\n") * 20,
    # `(?:[A-Z]{1,2}\d*)*` split a run of capitals every way it could: exponential.
    "alphanumeric-identifier": "A12" + "AB" * 16 + "_",
    # Audit only. A name was taken from every capital after a hyphen, to the end of the run.
    "author-year-citation": "A-" * 10000,
    "author-year-citation, spaces": "Smith et al." + SPACES + "x",
    # Audit only. The prefix before a `[` was tried from every letter of a run.
    "numbered-citation": "a" * 20000,
}


@pytest.mark.parametrize("rendered", [False, True], ids=["source", "rendered"])
@pytest.mark.parametrize("text", list(STALLS.values()), ids=list(STALLS))
def test_the_rule_scan_does_not_stall_on_a_word_and_spaces(text: str, rendered: bool) -> None:
    """Every manuscript file is scanned with every rule, so one rule that backtracks stalls
    `check`. Rendered, for the audit, the scan also runs the audit-only rules."""
    from manuscript_guard.classify import Classifier

    classifier = Classifier.load(rendered=rendered)
    started = time.perf_counter()
    classifier.scan(text)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"the scan took {elapsed:.1f} s"


# ---------------------------------------------------------------- hostile files


def test_an_enormous_source_stamp_is_not_read_whole(project: Path, plain_project: Path) -> None:
    """`build/*.docx.source.sha256` is read by G1 and had no size cap.

    A digest line is 80 bytes. Anything larger is not a digest, and reading it whole is a
    free memory lever in a command that is supposed to be safe on someone else's project.
    """
    from manuscript_guard.build.document import SOURCE_STAMP

    build = project / "build"
    build.mkdir(exist_ok=True)
    (build / "manuscript.docx").write_bytes(b"PK\x03\x04not really a docx")
    (build / f"manuscript.docx{SOURCE_STAMP}").write_text("0" * (8 * 1024 * 1024), encoding="utf-8")

    overhead = check_overhead(project, plain_project)
    assert overhead < CHECK_OVERHEAD, f"check took {overhead:.1f} times a plain one"


def test_a_figure_stem_with_glob_characters_still_finds_its_siblings(project: Path) -> None:
    """`content_digest` globbed on the stem, and a stem is a filename.

    `forest[1].svg` made `Path.glob` match nothing at all — not even the figure itself — so
    the raster sibling was silently dropped from the review digest. That is exactly the gap
    the multi-format digest was added to close, reopened for any figure whose name contains
    a bracket, which is an ordinary thing to write.
    """
    from manuscript_guard.gates.figures import content_digest

    figures = project / "figures"
    for suffix in (".svg", ".png"):
        (figures / f"panel[a]{suffix}").write_bytes((figures / f"forest{suffix}").read_bytes())

    before = content_digest(figures / "panel[a].svg")
    png = figures / "panel[a].png"
    png.write_bytes(png.read_bytes() + b"retouched")
    assert content_digest(figures / "panel[a].svg") != before, (
        "the raster sibling was not part of the digest, so replacing it changed nothing"
    )


@pytest.mark.skipif(os.name == "nt", reason="FIFOs do not exist on Windows")
def test_a_fifo_in_the_figures_directory_does_not_hang_check(
    project: Path, plain_project: Path
) -> None:
    """Nothing bounds wall-clock time in the gate runner, so a blocking read is forever.

    CI runs Ubuntu and macOS, where an unprivileged `mkfifo` in `figures/` was enough.
    """
    os.mkfifo(project / "figures" / "trap.svg")
    overhead = check_overhead(project, plain_project)
    assert overhead < CHECK_OVERHEAD, f"check took {overhead:.1f} times a plain one"


def test_an_enormous_figure_sibling_is_not_read_whole(project: Path) -> None:
    from manuscript_guard.gates.figures import content_digest

    figures = project / "figures"
    (figures / "forest.tif").write_bytes(b"\x00" * (16 * 1024 * 1024))
    started = time.perf_counter()
    content_digest(figures / "forest.svg")
    assert time.perf_counter() - started < BUDGET_SECONDS


# ------------------------------------------------------- running somebody else's analysis


def test_a_junction_is_not_followed_when_staging_a_copy(tmp_path: Path) -> None:
    """`symlinks=True` does not cover a Windows directory junction.

    `os.path.islink` is False for one, so `copytree` walked straight into it and re-copied
    the tree at every level until the OS gave up - reachable by any unprivileged
    `mklink /J`, while the comment in verify.py claimed it had been fixed.

    Written against `st_reparse_tag` rather than `os.path.isjunction`, which arrived in
    Python 3.12: this project supports 3.10, and the first version of the fix returned early
    there. CI caught it on windows-latest/3.10 - the guard was inert on a third of the
    supported matrix while DESIGN said junctions were skipped.
    """
    import subprocess

    from manuscript_guard.verify import _skip

    if sys.platform != "win32":
        pytest.skip("a junction is a Windows construct; copytree handles the symlink case")

    root = tmp_path / "paper"
    (root / "analysis").mkdir(parents=True)
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root / "loop"), str(root)],
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("could not create a junction")

    assert "loop" in _skip(str(root), [entry.name for entry in root.iterdir()])
    assert "analysis" not in _skip(str(root), [entry.name for entry in root.iterdir()])


def test_the_build_and_git_trees_are_still_skipped(tmp_path: Path) -> None:
    from manuscript_guard.verify import _skip

    for name in ("build", ".git", "analysis", "results"):
        (tmp_path / name).mkdir()
    names = [entry.name for entry in tmp_path.iterdir()]
    assert _skip(str(tmp_path), names) == {"build", ".git"}


def test_something_that_cannot_be_stated_is_copied_rather_than_dropped(tmp_path: Path) -> None:
    """Silent omission is the failure this whole command exists to avoid.

    Treating an unreadable entry as a junction would drop a real directory out of the
    verified copy without saying so. `copytree` cannot walk it either, so it raises and the
    run reports that it could not stage a copy — which is the loud failure we want.
    """
    from manuscript_guard.verify import _skip

    assert _skip(str(tmp_path), ["does-not-exist"]) == set()


def test_a_verified_script_cannot_tell_it_is_being_verified(tmp_path: Path) -> None:
    """PYTHONDONTWRITEBYTECODE was set here for tidiness and was a backdoor in miniature.

    It is readable by the script being checked and is not set in an ordinary run, so two
    lines made an analysis honest under verification and dishonest everywhere else - the
    same reason MANUSCRIPT_GUARD_VERIFY was removed.
    """
    import inspect

    from manuscript_guard import verify as module

    source = inspect.getsource(module.verify)
    assert "PYTHONDONTWRITEBYTECODE" not in source.split("miniature")[-1].split("env =")[-1]
    assert "env = dict(os.environ)" in source


def test_a_script_that_never_exits_is_killed_with_its_children(tmp_path: Path) -> None:
    """`subprocess.run(timeout=)` kills the direct child only, and an analysis is usually a
    launcher. The grandchild kept the scratch directory alive and cleanup then failed."""
    import subprocess

    from manuscript_guard import verify as module

    script = tmp_path / "spin.py"
    script.write_text("import time\nwhile True:\n    time.sleep(0.1)\n", encoding="utf-8")
    original = module.TIMEOUT
    module.TIMEOUT = 2
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            module._run(script, tmp_path, dict(os.environ))
    finally:
        module.TIMEOUT = original


def test_output_from_a_verified_script_is_capped(tmp_path: Path) -> None:
    """A script printing steadily filled this process's memory, because the reader was here."""
    import os as _os

    from manuscript_guard.verify import OUTPUT_CAP, _run

    script = tmp_path / "loud.py"
    script.write_text(
        "import sys\nsys.stdout.write('x' * (4 << 20))\n", encoding="utf-8"
    )
    finished = _run(script, tmp_path, dict(_os.environ))
    assert finished.returncode == 0
    assert len(finished.stdout) <= OUTPUT_CAP


def test_an_interrupted_stamp_does_not_leave_an_empty_one(tmp_path: Path) -> None:
    """`write_text` truncates first, so a build interrupted mid-write left an empty stamp -
    which reads as a digest of nothing, so the next check calls a good document stale."""
    import inspect

    from manuscript_guard.build import document

    source = inspect.getsource(document._stamp_source)
    assert "os.replace(pending, stamp)" in source


def notes_each_referenced_once(count: int) -> str:
    """`count` paragraphs, each referencing a note of its own, and the notes' definitions."""
    return "".join(f"Text {i}.[^n{i}]\n\n" for i in range(count)) + "".join(
        f"[^n{i}]: Note {i}\n    with more.\n\n" for i in range(count)
    )


def test_footnotes_are_indexed_in_linear_time(assert_linear) -> None:
    """Each footnote's references, and each number's note, are found by bisection: read
    against every definition in turn, a paper of many notes took time in their square. From
    500 notes that reading fails in seconds; from 2,000, where it was once timed once per
    size, it takes two and a half minutes."""
    from manuscript_guard.text.sections import chains_at, footnote_index, heading_index

    def index(text: str) -> None:
        notes = footnote_index(text)
        headings = heading_index(text)
        for note in notes[:: max(1, len(notes) // 100)]:
            chains_at(headings, notes, note.start)

    assert_linear(notes_each_referenced_once, index, 500, "indexing footnotes")


def test_a_note_referenced_many_times_is_judged_in_linear_time(assert_linear) -> None:
    """A number in a note was judged once per reference: a note with a thousand references
    and a thousand numbers took two minutes. Its sections are judged once each now. The note
    is indexed off the clock, and only judging its numbers is timed. From 100 numbers the
    old judging fails in seconds; from 500, where it was once timed once per size, it takes
    six minutes."""
    from manuscript_guard.text.sections import chains_at, footnote_index, heading_index

    def one_note(count: int) -> tuple[list, list, range]:
        paragraphs = "Text.[^n]\n\n" * (count // 10)
        text = (
            "".join(f"# S{i}\n\n{paragraphs}" for i in range(10))
            + "[^n]: "
            + " ".join(f"{i}.5" for i in range(count))
            + "\n"
        )
        notes, headings = footnote_index(text), heading_index(text)
        note = notes[0]
        step = max(1, (note.end - note.start) // count)
        return headings, notes, range(note.start, note.end, step)

    def judge(given: tuple[list, list, range]) -> None:
        headings, notes, offsets = given
        for offset in offsets:
            chains_at(headings, notes, offset)

    assert_linear(one_note, judge, 100, "judging a note referenced many times")


def test_a_note_referenced_from_many_sections_is_judged_in_linear_time(assert_linear) -> None:
    """The fix-only review of #77: deduplicated by chain, a note referenced from a thousand
    sections, holding a thousand numbers, was judged a million times, and took two minutes
    where main took two seconds. A number's verdict turns on its section only through
    whether it is Methods, so each note keeps a chain of each kind at most. The note is
    indexed and scanned off the clock, and only judging its numbers is timed."""
    from manuscript_guard.classify import Classifier
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.sections import chains_at, footnote_index, heading_index
    from manuscript_guard.text.tokens import find_atoms

    classifier = Classifier.load()

    def one_note(count: int) -> tuple:
        text = (
            "".join(f"# Results {i}\n\nText.[^n]\n\n" for i in range(count))
            + "# Methods\n\nText.[^n]\n\n[^n]: "
            + " ".join(f"{i}.5" for i in range(count))
            + "\n"
        )
        notes, headings = footnote_index(text), heading_index(text)
        atoms = [
            atom for atom in find_atoms(text, mask(text)) if notes[0].start <= atom.start
        ]
        return headings, notes, atoms, classifier.scan(text)

    def judge(given: tuple) -> None:
        headings, notes, atoms, scan = given
        for atom in atoms:
            classifier.classify_under(atom, chains_at(headings, notes, atom.start), scan)

    assert_linear(one_note, judge, 50, "judging a note referenced from many sections")
