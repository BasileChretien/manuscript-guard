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

The budget here is deliberately loose. It is not a benchmark; it is a tripwire for a change
that turns a linear scan into a quadratic one, which has now happened twice in this file's
subject matter.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

BUDGET_SECONDS = 20.0


def timed_check(project: Path) -> float:
    from manuscript_guard.cli import _run_gates

    started = time.perf_counter()
    _run_gates(project, stage="drafting")
    return time.perf_counter() - started


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
    ],
    # Explicit ids: pytest builds one from the parameters otherwise, and puts it in
    # PYTEST_CURRENT_TEST — which Windows refuses past 32767 characters, so a 60 KB body
    # turns every case in this table into a collection error rather than a test.
    ids=lambda value: value if isinstance(value, str) and len(value) < 60 else "",
)
def test_check_finishes_on_pathological_prose(project: Path, name: str, body: str) -> None:
    """The specific regression this catches: a linear scan quietly becoming quadratic."""
    (project / "manuscript" / "pathological.md").write_text(body, encoding="utf-8")
    elapsed = timed_check(project)
    assert elapsed < BUDGET_SECONDS, f"{name}: check took {elapsed:.1f}s"


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


def test_definitions_over_a_paragraph_are_passed_over_in_linear_time() -> None:
    """Each definition passed over looked at the rest of the block for a title on the next
    line by copying it: 40,000 definitions over a paragraph took 42 seconds, where the
    definitions alone took a fifth of one."""
    from manuscript_guard.roundtrip import tag

    def measure(count: int) -> float:
        text = "[x]: u\n" * count + "Prose."
        started = time.perf_counter()
        tag(text, "main.md")
        return time.perf_counter() - started

    small = max(measure(10000), 1e-4)
    large = measure(40000)
    assert large / small < 12, f"4x the input took {large / small:.1f}x the time; not linear"


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


# ---------------------------------------------------------------- hostile files


def test_an_enormous_source_stamp_is_not_read_whole(project: Path) -> None:
    """`build/*.docx.source.sha256` is read by G1 and had no size cap.

    A digest line is 80 bytes. Anything larger is not a digest, and reading it whole is a
    free memory lever in a command that is supposed to be safe on someone else's project.
    """
    from manuscript_guard.build.document import SOURCE_STAMP

    build = project / "build"
    build.mkdir(exist_ok=True)
    (build / "manuscript.docx").write_bytes(b"PK\x03\x04not really a docx")
    (build / f"manuscript.docx{SOURCE_STAMP}").write_text("0" * (8 * 1024 * 1024), encoding="utf-8")

    elapsed = timed_check(project)
    assert elapsed < BUDGET_SECONDS


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
def test_a_fifo_in_the_figures_directory_does_not_hang_check(project: Path) -> None:
    """Nothing bounds wall-clock time in the gate runner, so a blocking read is forever.

    CI runs Ubuntu and macOS, where an unprivileged `mkfifo` in `figures/` was enough.
    """
    os.mkfifo(project / "figures" / "trap.svg")
    elapsed = timed_check(project)
    assert elapsed < BUDGET_SECONDS


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
