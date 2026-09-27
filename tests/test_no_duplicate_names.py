"""No module binds the same top-level name twice.

Python keeps the later binding without a word, and ruff's F811 fires only when the first
one was never used. The failure is real, and parallel branches produce it on their own:
#69 and #40 each added an `_unidentified` to merge.py, the later won, and every import
failed; #32 and #77 each defined `_CLAIM` in test_corruption.py, so #32's tests would have
run with #77's string once a use of it moved into a function body. A merge of main that
reintroduces one fails here.

Imports count too: one that rebinds a name defined above it, or two that bind one name from
different modules, is the same failure. Imports that bind the same object (`import a.b` and
`import a.c` both bind the package `a`; the same `from m import y` twice) do not collide.

A later assignment that reads the name itself (`X = X + ...`) builds it up in steps and is
allowed, as are `@overload` stubs. Bindings inside an `if` or `try` at module level (import
fallbacks) are not read.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _is_overload(node: ast.stmt) -> bool:
    """`@overload` stubs are meant to share a name with the function they describe."""
    return any(
        (isinstance(d, ast.Name) and d.id == "overload")
        or (isinstance(d, ast.Attribute) and d.attr == "overload")
        for d in getattr(node, "decorator_list", [])
    )


Origin = tuple | None


def _bound(node: ast.stmt) -> list[tuple[str, Origin]]:
    """The names a statement binds, each with where its value comes from.

    An import's origin says what it binds: `import a.b` and `import a.c` both bind `a` to
    the package `a`, and the same `from m import y` twice binds the same object, so equal
    origins do not collide. A def, a class or an assignment has no origin: each is a new
    value, and a second one replaces the first.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_overload(node):
        return []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [(node.name, None)]
    if isinstance(node, ast.Assign):
        return [(t.id, None) for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [(node.target.id, None)]
    if isinstance(node, ast.Import):
        return [
            (a.asname, ("module", a.name)) if a.asname
            else (a.name.split(".")[0], ("module", a.name.split(".")[0]))
            for a in node.names
        ]
    if isinstance(node, ast.ImportFrom) and node.module != "__future__":
        return [
            (a.asname or a.name, ("from", node.level, node.module, a.name))
            for a in node.names
            if a.name != "*"
        ]
    return []


def _reads_itself(node: ast.stmt, name: str) -> bool:
    value = getattr(node, "value", None)
    return value is not None and any(
        isinstance(n, ast.Name) and n.id == name for n in ast.walk(value)
    )


def duplicate_names(source: str) -> dict[str, list[int]]:
    """Top-level names bound more than once to different values, with the binding lines."""
    bindings: dict[str, list[tuple[int, Origin]]] = defaultdict(list)
    for node in ast.parse(source).body:
        for name, origin in _bound(node):
            if bindings[name] and origin is None and _reads_itself(node, name):
                continue
            bindings[name].append((node.lineno, origin))
    return {
        name: [line for line, _ in found]
        for name, found in bindings.items()
        if len(found) > 1 and (None in {o for _, o in found} or len({o for _, o in found}) > 1)
    }


def test_the_scan_catches_a_second_binding() -> None:
    source = (
        "def helper():\n    return 1\n\n"
        "CLAIM = 'a'\n\n"
        "def helper(known, plan):\n    return 2\n\n"
        "CLAIM = 'b'\n"
    )
    assert duplicate_names(source) == {"helper": [1, 6], "CLAIM": [4, 9]}


def test_the_scan_allows_a_name_built_up_in_steps() -> None:
    source = "PARTS = ['a']\nPARTS = PARTS + ['b']\nNAMES: list[str] = []\n"
    assert duplicate_names(source) == {}


def test_the_scan_allows_overload_stubs() -> None:
    source = (
        "import typing\nfrom typing import overload\n\n"
        "@overload\ndef read(x: int) -> int: ...\n\n"
        "@typing.overload\ndef read(x: str) -> str: ...\n\n"
        "def read(x):\n    return x\n"
    )
    assert duplicate_names(source) == {}


def test_the_scan_catches_an_import_that_rebinds_a_def() -> None:
    source = "def quote(text):\n    return text\n\nfrom shlex import quote\n"
    assert duplicate_names(source) == {"quote": [1, 4]}


def test_the_scan_catches_two_imports_of_one_name_from_different_modules() -> None:
    source = "from json import loads\nfrom tomllib import loads\nimport json as loads\n"
    assert duplicate_names(source) == {"loads": [1, 2, 3]}


def test_the_scan_allows_imports_that_bind_the_same_object() -> None:
    source = (
        "from __future__ import annotations\n"
        "import urllib.error\nimport urllib.request\nimport urllib\n"
        "from pathlib import Path\nfrom pathlib import Path\n"
        "from os import *\n"
    )
    assert duplicate_names(source) == {}


def test_the_scan_catches_a_package_import_rebound_by_an_assignment() -> None:
    source = "import urllib.request\nurllib = None\n"
    assert duplicate_names(source) == {"urllib": [1, 2]}


def test_no_module_binds_a_name_twice() -> None:
    found = {}
    for path in sorted([*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").rglob("*.py")]):
        duplicates = duplicate_names(path.read_text(encoding="utf-8"))
        if duplicates:
            found[str(path.relative_to(ROOT))] = duplicates
    assert found == {}, f"top-level names bound twice (the later one wins silently): {found}"
