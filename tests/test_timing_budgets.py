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


def _budget(side: ast.expr) -> float | str:
    """The other side of a comparison with a timing: a number, a name, or its source."""
    if isinstance(side, ast.Constant) and isinstance(side.value, (int, float)):
        return side.value
    return side.id if isinstance(side, ast.Name) else ast.unparse(side)


def _held(
    function: ast.AST, source: Callable[[ast.AST], bool]
) -> tuple[list[float | str], bool]:
    """What `function` holds the timings from `source` to, and whether it returns one.

    A timing is an expression holding a node `source` marks, or a name assigned from one,
    plainly, annotated or added to. Only the other side of a comparison with a timing counts,
    so a test that also asserts `line == 24` does not have 24 for a budget."""
    timed: set[str] = set()

    def timing(expression: ast.AST | None) -> bool:
        return expression is not None and any(
            source(node) or (isinstance(node, ast.Name) and node.id in timed)
            for node in ast.walk(expression)
        )

    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and timing(node.value):
            timed |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        elif (
            isinstance(node, (ast.AnnAssign, ast.AugAssign))
            and isinstance(node.target, ast.Name)
            and timing(node.value)
        ):
            timed.add(node.target.id)
    held: list[float | str] = []
    for node in sorted(
        (node for node in ast.walk(function) if isinstance(node, ast.Compare)),
        key=lambda node: (node.lineno, node.col_offset),
    ):
        if timing(node.left):
            held += [_budget(side) for side in node.comparators]
        elif len(node.comparators) == 1 and timing(node.comparators[0]):
            held.append(_budget(node.left))
    returned = any(
        isinstance(node, ast.Return) and timing(node.value) for node in ast.walk(function)
    )
    return held, returned


def _callers(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    """Every function that can call another, in source order: those at the top level, and
    the methods of the classes there, as `Class.method`."""
    found: list[tuple[str, ast.AST]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            found += [
                (f"{node.name}.{method.name}", method)
                for method in node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    return found


def budgets_compared(source: str, name: str) -> tuple[list[float | str], list[str]] | None:
    """What the timing the function `name` in `source` reads is held to, each a number or the
    name of a constant, and the callers that hold it to nothing the check can read. None if
    there is no such function.

    Only its own clock reads count: a timing it gets from another helper answers to that
    helper's entry. One it returns, like `timed_check`, answers for what every caller holds
    the result to, and theirs when they pass it on in turn. A caller that neither holds it
    nor passes it on, or passes it on to nothing that calls it by name, is named: a timing
    it asserts some way this does not read would otherwise pass unseen."""
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if name not in functions:
        return None
    callers = _callers(tree)
    held, returned = _held(functions[name], clock_reader(tree))
    silent: list[str] = []
    passed_on, seen = [name] if returned else [], {name}
    while passed_on:
        helper = passed_on.pop(0)

        def calls(node: ast.AST, helper: str = helper) -> bool:
            return (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == helper
            )

        called = False
        for caller, function in callers:
            if caller in seen or not any(calls(node) for node in ast.walk(function)):
                continue
            seen.add(caller)
            called = True
            found, returns = _held(function, calls)
            held += found
            if returns and caller in functions:
                passed_on.append(caller)
            elif not found:
                silent.append(caller)
        if not called and helper != name:
            silent.append(helper)
    return held, silent


def budget_mismatch(entry: dict, source: str) -> str | None:
    """Why the budget `entry` lists is not the one its test asserts, or None if it is. A
    listed `constant` must be what the timing is compared against, and hold the budget."""
    name = entry["where"].partition("::")[2]
    found = budgets_compared(source, name)
    if found is None:
        return "no such function"
    compared, silent = found
    if silent:
        return f"{silent[0]} holds its timing to nothing the check can read"
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
# A helper's timing passed on through another that also reads a clock of its own, the way a
# helper can pass on a CPU timing and hold its own wall clock to a backstop.
PASSED_ON = (
    "import time\n"
    "BOUND = 30.0\n"
    "HANG = 60.0\n"
    "def timed():\n"
    "    started = time.process_time()\n"
    "    return time.process_time() - started\n"
    "def overhead():\n"
    "    started = time.perf_counter()\n"
    "    ratio = timed() / timed()\n"
    "    assert time.perf_counter() - started < HANG\n"
    "    if ratio < BOUND:\n"
    "        return ratio\n"
    "    return ratio\n"
    "def test_a():\n"
    "    assert overhead() < BOUND\n"
    "def test_b():\n"
    "    assert overhead() < {b}\n"
)
# One caller holds the helper's timing to the budget; the case adds a second.
HELD_BY_ONE = (
    "import time\n"
    "BUDGET = 20.0\n"
    "def timed():\n"
    "    started = time.perf_counter()\n"
    "    return time.perf_counter() - started\n"
    "def within(value, budget):\n"
    "    assert value < budget\n"
    "def test_a():\n"
    "    elapsed = timed()\n"
    "    assert elapsed < BUDGET\n"
)
HELD_ELSEWHERE = "compares its timing against ['BUDGET', 60], listed as 'BUDGET'"
HELD_TO_NOTHING = "test_b holds its timing to nothing the check can read"


@pytest.mark.parametrize(
    ("caller", "mismatch"),
    [
        pytest.param(
            "def test_b():\n    elapsed: float = timed()\n    assert elapsed < 60\n",
            HELD_ELSEWHERE,
            id="annotated",
        ),
        pytest.param("def test_b():\n    assert 60 > timed()\n", HELD_ELSEWHERE, id="reversed"),
        pytest.param(
            "def test_b():\n    elapsed, _ = timed(), None\n    assert elapsed < 60\n",
            HELD_TO_NOTHING,
            id="unpacked",
        ),
        pytest.param(
            "def test_b():\n    within(timed(), 60)\n", HELD_TO_NOTHING, id="through-a-function"
        ),
        pytest.param(
            "def test_b():\n    print(timed())\n", HELD_TO_NOTHING, id="assertion-dropped"
        ),
        pytest.param(
            "class TestB:\n    def test_b(self):\n        assert timed() < 60\n",
            HELD_ELSEWHERE,
            id="a-method",
        ),
    ],
)
def test_every_caller_holds_a_helpers_timing_to_the_budget(caller: str, mismatch: str) -> None:
    """The second review's forms, each through a helper one test holds correctly. A direct
    test failed on them loudly already; through a helper they passed, pooled with the caller
    that held. Every caller now holds the timing to a number the check can read, or passes
    it on to one that does, or the check says so."""
    entry = {"where": "t.py::timed", "budget": 20.0, "constant": "BUDGET"}
    assert budget_mismatch(entry, HELD_BY_ONE + caller) == mismatch


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
        pytest.param(
            {"where": "t.py::timed", "budget": 30.0, "constant": "BOUND"},
            PASSED_ON.format(b=60),
            "compares its timing against ['BOUND', 'BOUND', 60], listed as 'BOUND'",
            id="a-timing-passed-on-and-held-to-another-number",
        ),
        pytest.param(
            {"where": "t.py::overhead", "budget": 60.0, "constant": "HANG"},
            PASSED_ON.format(b="BOUND"),
            None,
            id="a-function-answers-for-its-own-clock-only",
        ),
        pytest.param(
            {"where": "t.py::test_x", "budget": 2.0},
            "import time\ndef test_x():\n    started = time.perf_counter()\n"
            "    assert time.perf_counter() - started < 2.0\n    total = 0.0\n"
            "    total += time.perf_counter() - started\n    assert total < 60\n",
            "compares its timing against [2.0, 60], listed as 2.0",
            id="a-second-timing-added-up",
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
