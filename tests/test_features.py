"""The feature map, docs/features.yaml, is held to the package it describes.

The map lists what the package is meant to do, one entry for each thing it promises, and
`tools/feature_map.py` draws a page and a picture from it. A list kept by hand goes wrong at
the first change that forgets it, and then misleads the reader and the agent tool it was
written for. So every command, gate, skill and hook must be in an entry, every name an entry
gives must exist, an entry that works names the tests that prove it, and the page and the
picture are the ones the script draws from the file as it stands.
"""

from __future__ import annotations

import argparse
import ast
import copy
import importlib
import importlib.util
import json
import pkgutil
import re
import warnings
from pathlib import Path

import pytest

import manuscript_guard.gates
from manuscript_guard.cli import build_parser

REPO = Path(__file__).resolve().parent.parent

#: What an entry may hold, and what it must.
KEYS = {"id", "stage", "title", "says", "status", "commands", "gates", "skills", "hooks",
        "tests", "docs", "limits"}  # fmt: skip
REQUIRED = {"id", "stage", "title", "says", "status"}
#: The names an entry gives, by the key that gives them.
NAMED = ("commands", "gates", "skills", "hooks")


def feature_map():
    spec = importlib.util.spec_from_file_location(
        "feature_map", REPO / "tools" / "feature_map.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool():
    return feature_map()


@pytest.fixture(scope="module")
def source(tool) -> dict:
    return tool.load()


# ------------------------------------------------------------------- what there is to list


def there_are() -> dict[str, set[str]]:
    """Each command, gate, skill and hook the package and the plugin have."""
    commands = next(
        action.choices
        for action in build_parser()._actions  # noqa: SLF001 - argparse offers no other way
        if isinstance(action, argparse._SubParsersAction)  # noqa: SLF001
    )
    gates = set()
    for module in pkgutil.iter_modules(manuscript_guard.gates.__path__):
        gate = getattr(importlib.import_module(f"manuscript_guard.gates.{module.name}"), "GATE",
                       None)  # fmt: skip
        if gate:
            gates.add(gate)
    config = json.loads((REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    hooks = {hook["command"].split()[-1] for groups in config["hooks"].values()
             for group in groups for hook in group["hooks"]}  # fmt: skip
    skills = {path.parent.name for path in (REPO / "plugin" / "skills").glob("*/SKILL.md")}
    # `hook` is the command the hooks call; an author never does, and the hooks are listed.
    return {"commands": set(commands) - {"hook"}, "gates": gates, "skills": skills,
            "hooks": hooks}  # fmt: skip


def unlisted(source: dict, there: dict[str, set[str]]) -> dict[str, list[str]]:
    """What the package has that no entry names, by kind."""
    named = {kind: {name for entry in source["features"] for name in entry.get(kind, ())}
             for kind in NAMED}  # fmt: skip
    return {kind: sorted(there[kind] - named[kind]) for kind in NAMED
            if there[kind] - named[kind]}  # fmt: skip


def unknown(source: dict, there: dict[str, set[str]]) -> list[str]:
    """Each name an entry gives that the package does not have, as `<id>: <kind> <name>`."""
    return [f"{entry['id']}: {kind} {name}" for entry in source["features"]
            for kind in NAMED for name in entry.get(kind, ())
            if name not in there[kind]]  # fmt: skip


def _is_test(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
        "test"
    )


def defined_tests(folder: Path = REPO / "tests") -> dict[str, set[str]]:
    """Each test file, with the tests pytest collects from it: a function whose name opens
    with `test`, and `Class::test...` for one in a class whose name opens with `Test`. A
    fixture or a helper is no test, whatever it is named after."""
    found = {}
    for path in folder.glob("test_*.py"):
        with warnings.catch_warnings():
            # A test file may hold a string Python warns of; its names are all this reads.
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {node.name for node in tree.body if _is_test(node)}
        names |= {f"{node.name}::{method.name}" for node in tree.body
                  if isinstance(node, ast.ClassDef) and node.name.startswith("Test")
                  for method in node.body if _is_test(method)}  # fmt: skip
        found[f"tests/{path.name}"] = names
    return found


def missing_tests(source: dict, files: dict[str, set[str]]) -> list[str]:
    """Each test an entry names that is not there, and each entry that works with none."""
    missing = []
    for entry in source["features"]:
        if entry["status"] != "planned" and not entry.get("tests"):
            missing.append(f"{entry['id']}: names no test")
        for test in entry.get("tests", ()):
            file, _, name = test.partition("::")
            if file not in files or (name and name not in files[file]):
                missing.append(f"{entry['id']}: {test}")
    return missing


def missing_pages(source: dict, anchor) -> list[str]:
    """Each page an entry names that is not there, or whose heading is not."""
    missing = []
    for entry in source["features"]:
        if "docs" not in entry:
            continue
        file, _, fragment = entry["docs"].partition("#")
        path = REPO / file
        if not path.is_file():
            missing.append(f"{entry['id']}: {entry['docs']}")
            continue
        text = re.sub(r"^```.*?^```", "", path.read_text(encoding="utf-8"),
                      flags=re.MULTILINE | re.DOTALL)  # fmt: skip
        headings = {anchor(h) for h in re.findall(r"^#{1,6}\s+(.*?)\s*$", text, re.MULTILINE)}
        if fragment and fragment not in headings:
            missing.append(f"{entry['id']}: {entry['docs']}")
    return missing


# ---------------------------------------------------------------------------------- tests


def misread(source: dict, tool) -> list[str]:
    """Each way the map does not read as its own header says it should."""
    stages = [stage["id"] for stage in source["stages"]]
    said = ["a stage is listed twice"] if len(stages) != len(set(stages)) else []
    ids = [entry.get("id") for entry in source["features"]]
    twice = sorted({name for name in ids if ids.count(name) > 1})
    said += [f"{name}: the id is used twice" for name in twice]
    for entry in source["features"]:
        where = entry.get("id", "an entry with no id")
        if set(entry) - KEYS:
            said.append(f"{where}: no key {sorted(set(entry) - KEYS)}")
        if REQUIRED - set(entry):
            said.append(f"{where}: lacks {sorted(REQUIRED - set(entry))}")
            continue
        if entry["stage"] not in stages:
            said.append(f"{where}: no stage {entry['stage']}")
        if entry["status"] not in tool.STATUS_WORDS:
            said.append(f"{where}: no status {entry['status']}")
        elif entry["status"] != "works" and not entry.get("limits"):
            said.append(f"{where}: does not say what is missing")
        if len(entry["title"]) > tool.TITLE_ROOM:
            said.append(f"{where}: the picture has no room for its title")
        if not entry["says"].rstrip().endswith("."):
            said.append(f"{where}: says no sentence with its stop")
    said += [f"{stage}: no entry" for stage in stages
             if not any(entry.get("stage") == stage for entry in source["features"])]  # fmt: skip
    return said


def test_each_entry_reads_as_the_map_says(source: dict, tool) -> None:
    assert misread(source, tool) == []


def test_everything_the_package_has_is_in_an_entry(source: dict) -> None:
    assert unlisted(source, there_are()) == {}


def test_every_name_an_entry_gives_is_one_the_package_has(source: dict) -> None:
    assert unknown(source, there_are()) == []


def test_every_test_an_entry_names_is_there(source: dict) -> None:
    assert missing_tests(source, defined_tests()) == []


def test_every_page_an_entry_names_is_there(source: dict, tool) -> None:
    assert missing_pages(source, tool.anchor) == []


def test_the_page_and_the_pictures_are_the_ones_the_script_draws(tool) -> None:
    """They are committed, so an edit of the map that nobody drew would leave the page
    showing the old one."""
    drawn = tool.drawn()
    assert set(drawn) == {"docs/features.md", "docs/img/features-light.svg",
                          "docs/img/features-dark.svg"}  # fmt: skip
    for path, text in drawn.items():
        on_disk = REPO / path
        assert on_disk.is_file(), f"{path} is missing: run python tools/feature_map.py"
        assert on_disk.read_text(encoding="utf-8") == text, (
            f"{path} is stale: run python tools/feature_map.py"
        )


# ------------------------------------------------------- the checks catch what they claim


def without(source: dict, kind: str, name: str) -> dict:
    """The map with `name` taken out of every entry that gives it."""
    changed = copy.deepcopy(source)
    for entry in changed["features"]:
        if name in entry.get(kind, ()):
            entry[kind] = [kept for kept in entry[kind] if kept != name]
    return changed


@pytest.mark.parametrize(("kind", "name"), [
    ("commands", "verify"), ("gates", "G9"), ("skills", "figure-review"), ("hooks", "stop"),
])  # fmt: skip
def test_a_name_no_entry_gives_is_said(source: dict, kind: str, name: str) -> None:
    assert unlisted(without(source, kind, name), there_are()) == {kind: [name]}


def test_a_name_the_package_does_not_have_is_said(source: dict) -> None:
    changed = copy.deepcopy(source)
    changed["features"][0]["commands"] = ["init", "unpack"]
    changed["features"][0]["gates"] = ["G99"]
    first = changed["features"][0]["id"]
    assert unknown(changed, there_are()) == [f"{first}: commands unpack", f"{first}: gates G99"]


def test_a_map_that_does_not_read_is_said(source: dict, tool) -> None:
    changed = copy.deepcopy(source)
    first, second, third, fourth, fifth = changed["features"][:5]
    first["status"] = "done"
    second["owner"] = "someone"
    third["title"] = "A title far too long for the picture to hold"
    fourth["status"] = "partial"
    fifth["says"] = "Says no sentence"
    del fifth["stage"]
    changed["features"].append(copy.deepcopy(first))
    assert misread(changed, tool) == [
        f"{first['id']}: the id is used twice",
        f"{first['id']}: no status done",
        f"{second['id']}: no key ['owner']",
        f"{third['id']}: the picture has no room for its title",
        f"{fourth['id']}: does not say what is missing",
        f"{fifth['id']}: lacks ['stage']",
        f"{first['id']}: no status done",
    ]


def test_a_test_that_is_not_there_is_said(source: dict) -> None:
    files = defined_tests()
    changed = copy.deepcopy(source)
    first, second = changed["features"][:2]
    first["tests"] = ["tests/test_scaffold.py::test_no_such_test", "tests/test_nowhere.py",
                      "tests/test_checking.py::project"]  # a fixture, not a test
    del second["tests"]
    assert missing_tests(changed, files) == [
        f"{first['id']}: tests/test_scaffold.py::test_no_such_test",
        f"{first['id']}: tests/test_nowhere.py",
        f"{first['id']}: tests/test_checking.py::project",
        f"{second['id']}: names no test",
    ]


def test_a_test_is_what_pytest_collects(tmp_path: Path) -> None:
    (tmp_path / "test_kinds.py").write_text(
        "import pytest\n\n"
        "@pytest.fixture\ndef project():\n    pass\n\n"
        "def helper_for_tests():\n    pass\n\n"
        "def test_alone():\n    pass\n\n"
        "async def test_awaited():\n    pass\n\n"
        "class TestGroup:\n    def test_inside(self):\n        pass\n\n"
        "    def helper(self):\n        pass\n\n"
        "class Group:\n    def test_not_collected(self):\n        pass\n",
        encoding="utf-8",
    )
    assert defined_tests(tmp_path) == {
        "tests/test_kinds.py": {"test_alone", "test_awaited", "TestGroup::test_inside"},
    }


def test_a_page_or_heading_that_is_not_there_is_said(source: dict, tool) -> None:
    changed = copy.deepcopy(source)
    first, second = changed["features"][:2]
    first["docs"] = "docs/nowhere.md"
    second["docs"] = "docs/stages.md#no-such-heading"
    assert missing_pages(changed, tool.anchor) == [
        f"{first['id']}: docs/nowhere.md", f"{second['id']}: docs/stages.md#no-such-heading",
    ]


def test_an_edit_of_the_map_changes_what_is_drawn(source: dict, tool) -> None:
    changed = copy.deepcopy(source)
    changed["features"][0]["title"] = "Begin a project"
    drawn = tool.drawn(changed)
    assert all("Begin a project" in text for text in drawn.values())
    assert drawn != tool.drawn(source)
