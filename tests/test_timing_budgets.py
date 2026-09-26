"""A test that reads a clock has to say why.

`check_linear` (the `assert_linear` fixture in conftest.py) exists because tests timed each
size once, for a few milliseconds, and a busy runner decided the verdict. Tests of that shape
kept arriving from branches opened before it: #39 merged two after it, and neither the review
nor the suite noticed. This file stops the next one: a test that reads a clock outside the
helper fails here unless `tests/data/timing_budgets.yaml` lists it, as a budget that says
why it is not a ratio and how much headroom it has, or as a timestamp that times nothing.

Like `test_exemptions`, it runs both ways. A clock read nobody listed fails, and so does a
listed entry that no longer reads one, so the list cannot rot into a record of tests that
have changed. It reads the tests' syntax, not their text: a clock mentioned in a docstring
is not a read, and one reached through an alias is.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
LISTED = yaml.safe_load((TESTS / "data" / "timing_budgets.yaml").read_text(encoding="utf-8"))[
    "reads"
]

#: The functions in `time` that read a clock to time with. `sleep` reads none, and the
#: calendar functions (`localtime`, `ctime`, `strftime` and the rest) read one only to the
#: second, when given no time: too coarse for anything a test would time.
CLOCKS = {
    "perf_counter", "perf_counter_ns", "time", "time_ns", "monotonic", "monotonic_ns",
    "process_time", "process_time_ns", "thread_time", "thread_time_ns",
    "clock_gettime", "clock_gettime_ns",
}
#: What `from timeit import *` binds: `timeit.__all__`.
TIMEIT = {"Timer", "timeit", "repeat", "default_timer"}
#: The helper, which is the one place meant to read a clock. It names `time.perf_counter` as
#: its default clock and hands it on; `_seconds` only calls what it is given.
HELPER = {"tests/conftest.py::check_linear"}
KINDS = {"budget", "timestamp"}


def clock_reader(tree: ast.Module) -> Callable[[ast.AST], bool]:
    """Whether a node of `tree` refers to a clock in `time`, or to anything in `timeit`,
    however the module imported them."""
    modules: dict[str, str] = {}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("time", "timeit"):
                    modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module in ("time", "timeit"):
            for alias in node.names:
                if alias.name == "*":
                    names |= CLOCKS if node.module == "time" else TIMEIT
                elif node.module == "timeit" or alias.name in CLOCKS:
                    names.add(alias.asname or alias.name)

    def reads(node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module = modules.get(node.value.id)
            return module == "timeit" or (module == "time" and node.attr in CLOCKS)
        return isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in names

    return reads


def clock_reads(source: str, path: str) -> dict[str, list[int]]:
    """Where `source` reads a clock, as `path::name` of the top-level function or class it is
    in (`<module>` outside one), to the lines. A read is any reference to a clock: a clock
    passed as a default argument times whatever calls it."""
    tree = ast.parse(source)
    reads = clock_reader(tree)
    found: dict[str, list[int]] = {}
    for top in tree.body:
        named = isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        owner = f"{path}::{top.name if named else '<module>'}"
        for node in ast.walk(top):
            if reads(node):
                found.setdefault(owner, []).append(node.lineno)
    return found


def all_clock_reads(root: Path) -> dict[str, list[int]]:
    """Every clock read in the test modules under `root`, keyed as in `clock_reads`."""
    found: dict[str, list[int]] = {}
    for path in sorted((root / "tests").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        found.update(clock_reads(path.read_text(encoding="utf-8"), relative))
    return found


def unlisted(found: dict[str, list[int]], listed: list[dict]) -> list[str]:
    known = {entry["where"] for entry in listed} | HELPER
    return sorted(f"{where} (line {', '.join(map(str, lines))})"
                  for where, lines in found.items() if where not in known)


def stale(found: dict[str, list[int]], listed: list[dict]) -> list[str]:
    return sorted(entry["where"] for entry in listed if entry["where"] not in found)


def budgets_compared(source: str, name: str) -> list[float | str] | None:
    """What the function `name` in `source` compares its timings against: a number, or the
    name of a constant. None if there is no such function.

    A timing is an expression holding a clock read, a call to a function of the module that
    returns one, or a name assigned from either. Only the other side of a comparison with a
    timing counts, so a test that also asserts `line == 24` does not have 24 for a budget. A
    helper that compares nothing and returns a timing, like `timed_check`, answers for what
    its callers compare it against."""
    tree = ast.parse(source)
    reads = clock_reader(tree)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if name not in functions:
        return None
    timers = {
        called
        for called, function in functions.items()
        for node in ast.walk(function)
        if isinstance(node, ast.Return)
        and node.value is not None
        and any(reads(inner) for inner in ast.walk(node.value))
    }

    def compared_in(function: ast.AST) -> list[float | str]:
        timed: set[str] = set()

        def timing(expression: ast.AST) -> bool:
            return any(
                reads(node)
                or (isinstance(node, ast.Name) and node.id in timed)
                or (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in timers
                )
                for node in ast.walk(expression)
            )

        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and timing(node.value):
                timed |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        comparisons = sorted(
            (node for node in ast.walk(function) if isinstance(node, ast.Compare)),
            key=lambda node: (node.lineno, node.col_offset),
        )
        return [
            side.value
            if isinstance(side, ast.Constant) and isinstance(side.value, (int, float))
            else side.id if isinstance(side, ast.Name) else ast.unparse(side)
            for node in comparisons
            if timing(node.left)
            for side in node.comparators
        ]

    compared = compared_in(functions[name])
    if compared or name not in timers:
        return compared
    return [
        value
        for caller in functions.values()
        if any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
            for node in ast.walk(caller)
        )
        for value in compared_in(caller)
    ]


def budget_mismatch(entry: dict, source: str) -> str | None:
    """Why the budget `entry` lists is not the one its test asserts, or None if it is. A
    listed `constant` must be what the timing is compared against, and hold the budget."""
    name = entry["where"].partition("::")[2]
    compared = budgets_compared(source, name)
    if compared is None:
        return "no such function"
    if not compared:
        return "compares no timing against anything"
    expected = entry.get("constant", entry["budget"])
    if any(value != expected for value in compared):
        return f"compares its timing against {compared}, listed as {expected!r}"
    if "constant" in entry:
        values = [
            node.value.value
            for node in ast.parse(source).body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == entry["constant"] for t in node.targets)
            and isinstance(node.value, ast.Constant)
        ]
        if values != [entry["budget"]]:
            return f"{entry['constant']} is {values}, listed as {entry['budget']}"
    return None


# ----------------------------------------------------------------------- the guard itself


@pytest.fixture(scope="module")
def found() -> dict[str, list[int]]:
    """The clock reads in this repository's tests, parsed once for the three tests below."""
    return all_clock_reads(REPO)


def test_every_clock_read_in_the_tests_is_listed(found: dict[str, list[int]]) -> None:
    """The point of the file. A new test that times something outside the helper fails
    here, and the message says what to do instead."""
    missing = unlisted(found, LISTED)
    assert not missing, (
        "these tests read a clock outside check_linear:\n  " + "\n  ".join(missing) + "\n"
        "Time a claim of linear time with the assert_linear fixture. A budget on a fixed input"
        " belongs in tests/data/timing_budgets.yaml, saying why it is not a ratio and its"
        " measured headroom; a timestamp that times nothing is listed there too."
    )


def test_every_listed_entry_still_reads_a_clock(found: dict[str, list[int]]) -> None:
    """The other direction: an entry for a test that was renamed, removed or converted would
    otherwise sit in the list looking like a budget someone still relies on."""
    gone = stale(found, LISTED)
    assert not gone, "listed, but no longer reading a clock:\n  " + "\n  ".join(gone)


def test_the_helper_is_where_the_guard_looks_for_it(found: dict[str, list[int]]) -> None:
    """If the helper were renamed, its names here would excuse nothing and hide nothing, but
    the next clock read in conftest.py would be read as unlisted for the wrong reason."""
    assert found.keys() >= HELPER, sorted(HELPER - found.keys())


def test_every_entry_says_why_and_every_budget_its_headroom() -> None:
    for entry in LISTED:
        where = entry["where"]
        assert entry.get("kind") in KINDS, f"{where}: kind must be one of {sorted(KINDS)}"
        assert str(entry.get("why", "")).strip(), f"{where}: no reason given"
        if entry["kind"] == "budget":
            assert isinstance(entry.get("budget"), (int, float)) and entry["budget"] > 0, where
            assert str(entry.get("headroom", "")).strip(), f"{where}: no measured headroom"


@pytest.mark.parametrize(
    "entry", [e for e in LISTED if e["kind"] == "budget"], ids=lambda e: e["where"]
)
def test_a_listed_budget_is_the_one_its_test_asserts(entry: dict) -> None:
    """The headroom is stated against the budget, so the budget in the list has to be the one
    the test holds its timing to: raised or lowered there, the stated headroom would be about
    another number."""
    path = entry["where"].partition("::")[0]
    mismatch = budget_mismatch(entry, (REPO / path).read_text(encoding="utf-8"))
    assert mismatch is None, f"{entry['where']}: {mismatch}"


# ------------------------------------------------- that the guard catches what it claims


@pytest.mark.parametrize(
    ("source", "owner"),
    [
        pytest.param("import time\ndef test_x():\n    time.perf_counter()\n", "test_x", id="plain"),
        pytest.param(
            "import time as clock\ndef test_x():\n    clock.monotonic()\n", "test_x", id="aliased"
        ),
        pytest.param(
            "from time import perf_counter as tick\ndef test_x():\n    tick()\n",
            "test_x",
            id="imported-name",
        ),
        pytest.param(
            "def test_x():\n    import time\n    time.time_ns()\n", "test_x", id="local-import"
        ),
        pytest.param(
            "import time\ndef test_x():\n    time.clock_gettime(time.CLOCK_MONOTONIC)\n",
            "test_x",
            id="clock-gettime",
        ),
        pytest.param(
            "from time import *\ndef test_x():\n    monotonic()\n", "test_x", id="star-import"
        ),
        pytest.param(
            "import timeit\ndef test_x():\n    timeit.timeit('1')\n", "test_x", id="timeit"
        ),
        pytest.param(
            "from timeit import default_timer\ndef test_x():\n    default_timer()\n",
            "test_x",
            id="timeit-name",
        ),
        pytest.param(
            "from timeit import *\ndef test_x():\n    repeat('1')\n", "test_x", id="timeit-star"
        ),
        pytest.param(
            "import time\ndef test_x():\n    def measure():\n        return time.time()\n"
            "    measure()\n",
            "test_x",
            id="nested-function",
        ),
        pytest.param(
            "import time\ndef helper(clock=time.perf_counter):\n    return clock()\n",
            "helper",
            id="default-argument",
        ),
        pytest.param(
            "import time\nclass TestX:\n    def test_y(self):\n        time.process_time()\n",
            "TestX",
            id="method",
        ),
        pytest.param("import time\nSTART = time.monotonic()\n", "<module>", id="module-level"),
    ],
)
def test_the_scanner_finds_a_clock_read_however_it_is_written(source: str, owner: str) -> None:
    assert list(clock_reads(source, "tests/test_x.py")) == [f"tests/test_x.py::{owner}"]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import time\ndef test_x():\n    time.sleep(0.01)\n", id="sleep"),
        pytest.param(
            'def test_x():\n    """Uses time.perf_counter() once."""\n', id="docstring"
        ),
        pytest.param("def test_x():\n    assert 'time.monotonic()'\n", id="string"),
        pytest.param(
            "import datetime\ndef test_x():\n    datetime.date(2020, 1, 1)\n", id="date"
        ),
    ],
)
def test_the_scanner_passes_what_reads_no_clock(source: str) -> None:
    assert clock_reads(source, "tests/test_x.py") == {}


def test_an_unlisted_timing_test_fails_the_guard(tmp_path: Path) -> None:
    """End to end on a project of its own: a new test of the old shape is reported, one in a
    subdirectory too, and a listed entry whose test has gone is reported as stale."""
    (tmp_path / "tests" / "deeper").mkdir(parents=True)
    (tmp_path / "tests" / "test_new.py").write_text(
        "import time\n\n"
        "def test_the_scan_is_linear():\n"
        "    started = time.perf_counter()\n"
        "    small = time.perf_counter() - started\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "deeper" / "test_deep.py").write_text(
        "import time\n\ndef test_deep():\n    time.monotonic()\n", encoding="utf-8"
    )
    found = all_clock_reads(tmp_path)
    listed = [{"where": "tests/test_old.py::test_gone", "kind": "timestamp", "why": "x"}]
    assert unlisted(found, listed) == [
        "tests/deeper/test_deep.py::test_deep (line 4)",
        "tests/test_new.py::test_the_scan_is_linear (line 4, 5)",
    ]
    assert stale(found, listed) == ["tests/test_old.py::test_gone"]


HELPED = (
    "import time\n"
    "BUDGET = 20.0\n"
    "def timed():\n"
    "    started = time.perf_counter()\n"
    "    return time.perf_counter() - started\n"
    "def test_a():\n"
    "    elapsed = timed()\n"
    "    assert elapsed < BUDGET\n"
    "def test_b():\n"
    "    assert timed() < {b}\n"
)


@pytest.mark.parametrize(
    ("entry", "source", "mismatch"),
    [
        pytest.param(
            {"where": "t.py::test_x", "budget": 24},
            "import time\ndef test_x():\n    started = time.perf_counter()\n    line = find()\n"
            "    assert time.perf_counter() - started < 5\n    assert line == 24\n",
            "compares its timing against [5], listed as 24",
            id="another-number-compared-is-not-the-budget",
        ),
        pytest.param(
            {"where": "t.py::test_x", "budget": 20.0, "constant": "BUDGET"},
            "import time\nBUDGET = 20.0\ndef test_x():\n    started = time.perf_counter()\n"
            "    assert time.perf_counter() - started < 60\n",
            "compares its timing against [60], listed as 'BUDGET'",
            id="a-listed-constant-the-test-does-not-use",
        ),
        pytest.param(
            {"where": "t.py::timed", "budget": 20.0, "constant": "BUDGET"},
            HELPED.format(b=60),
            "compares its timing against ['BUDGET', 60], listed as 'BUDGET'",
            id="a-helper-one-caller-holds-to-another-number",
        ),
        pytest.param(
            {"where": "t.py::timed", "budget": 30.0, "constant": "BUDGET"},
            HELPED.format(b="BUDGET"),
            "BUDGET is [20.0], listed as 30.0",
            id="the-constant-holds-another-number",
        ),
        pytest.param(
            {"where": "t.py::test_x", "budget": 1.0},
            "import time\ndef test_x():\n    started = time.perf_counter()\n    work()\n",
            "compares no timing against anything",
            id="nothing-compared",
        ),
        pytest.param(
            {"where": "t.py::test_gone", "budget": 1.0},
            "def test_x():\n    pass\n",
            "no such function",
            id="no-such-function",
        ),
        pytest.param(
            {"where": "t.py::timed", "budget": 20.0, "constant": "BUDGET"},
            HELPED.format(b="BUDGET"),
            None,
            id="a-helper-every-caller-holds-to-the-constant",
        ),
    ],
)
def test_the_budget_check_reads_what_the_timing_is_held_to(
    entry: dict, source: str, mismatch: str | None
) -> None:
    """Each way a listed budget can part from the one its test holds a timing to, as a
    review found: a number compared with something else, a constant listed but not used,
    and a helper whose callers each hold its timing to a number of their own."""
    assert budget_mismatch(entry, source) == mismatch
