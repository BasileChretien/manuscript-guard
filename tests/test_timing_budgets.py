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
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
LISTED = yaml.safe_load((TESTS / "data" / "timing_budgets.yaml").read_text(encoding="utf-8"))[
    "reads"
]

#: The functions in `time` that read a clock. `sleep` and the formatting functions do not.
CLOCKS = {
    "perf_counter", "perf_counter_ns", "time", "time_ns", "monotonic", "monotonic_ns",
    "process_time", "process_time_ns", "thread_time", "thread_time_ns",
}
#: The helper, which is the one place meant to read a clock. It names `time.perf_counter` as
#: its default clock and hands it on; `_seconds` only calls what it is given.
HELPER = {"tests/conftest.py::check_linear"}
KINDS = {"budget", "timestamp"}


def clock_reads(source: str, path: str) -> dict[str, list[int]]:
    """Where `source` reads a clock, as `path::name` of the top-level function or class it is
    in (`<module>` outside one), to the lines. A read is any reference to a clock in `time`
    and any use of `timeit`, however imported: a clock passed as a default argument times
    whatever calls it."""
    tree = ast.parse(source)
    modules: dict[str, str] = {}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("time", "timeit"):
                    modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module in ("time", "timeit"):
            for alias in node.names:
                if node.module == "timeit" or alias.name in CLOCKS:
                    names.add(alias.asname or alias.name)

    def reads(node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module = modules.get(node.value.id)
            return module == "timeit" or (module == "time" and node.attr in CLOCKS)
        return isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in names

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
    for path in sorted((root / "tests").glob("*.py")):
        relative = path.relative_to(root).as_posix()
        found.update(clock_reads(path.read_text(encoding="utf-8"), relative))
    return found


def unlisted(found: dict[str, list[int]], listed: list[dict]) -> list[str]:
    known = {entry["where"] for entry in listed} | HELPER
    return sorted(f"{where} (line {', '.join(map(str, lines))})"
                  for where, lines in found.items() if where not in known)


def stale(found: dict[str, list[int]], listed: list[dict]) -> list[str]:
    return sorted(entry["where"] for entry in listed if entry["where"] not in found)


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
    in the test: raised or lowered there, the stated headroom would be about another number.
    It is either a literal compared in the function or a module constant the entry names."""
    path, _, name = entry["where"].partition("::")
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    if "constant" in entry:
        values = [
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == entry["constant"] for t in node.targets)
            and isinstance(node.value, ast.Constant)
        ]
        assert values == [entry["budget"]], f"{entry['where']}: {entry['constant']} = {values}"
        return
    function = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name),
        None,
    )
    assert function is not None, f"{entry['where']}: no such function"
    compared = {
        side.value
        for node in ast.walk(function)
        if isinstance(node, ast.Compare)
        for side in node.comparators
        if isinstance(side, ast.Constant) and isinstance(side.value, (int, float))
    }
    assert entry["budget"] in compared, f"{entry['where']}: compares against {sorted(compared)}"


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
            "import timeit\ndef test_x():\n    timeit.timeit('1')\n", "test_x", id="timeit"
        ),
        pytest.param(
            "from timeit import default_timer\ndef test_x():\n    default_timer()\n",
            "test_x",
            id="timeit-name",
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
    """End to end on a project of its own: a new test of the old shape is reported, and a
    listed entry whose test has gone is reported as stale."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_new.py").write_text(
        "import time\n\n"
        "def test_the_scan_is_linear():\n"
        "    started = time.perf_counter()\n"
        "    small = time.perf_counter() - started\n",
        encoding="utf-8",
    )
    found = all_clock_reads(tmp_path)
    listed = [{"where": "tests/test_old.py::test_gone", "kind": "timestamp", "why": "x"}]
    assert unlisted(found, listed) == ["tests/test_new.py::test_the_scan_is_linear (line 4, 5)"]
    assert stale(found, listed) == ["tests/test_old.py::test_gone"]
