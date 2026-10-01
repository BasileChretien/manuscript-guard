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

And no function assigns to the name of a function it calls. An assignment anywhere in a
function makes the name local to all of it, so `why = "..."` in one branch of `plan_import`
turned every `why(aligned)` there into `UnboundLocalError`, and `as_sent = [...]` under a
helper `def as_sent` made the helper a list for the code below it. Each ran clean through
ruff, and through every test that did not reach the call.
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


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _own(function: ast.AST, inside: tuple = _SCOPES):
    """Every node of a function's body that is in its own scope: not in a function, lambda or
    class written inside it, nor, for what it binds, in a comprehension, whose variables are
    the comprehension's."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, inside):
            stack.extend(ast.iter_child_nodes(node))


def shadowed_calls(source: str) -> dict[str, list[str]]:
    """For each function, by name and line, the functions it calls and also assigns to: one
    defined inside it, or at the top of its module."""
    tree = ast.parse(source)
    defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    found: dict[str, list[str]] = {}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        nested = {
            node.name
            for node in _own(function)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assigned = {
            node.id
            for node in _own(function, (*_SCOPES, *_COMPREHENSIONS))
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        }
        called = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        shadowed = sorted(assigned & called & (nested | defined))
        if shadowed:
            found[f"{function.name}:{function.lineno}"] = shadowed
    return found


def test_the_scan_catches_a_helper_assigned_over() -> None:
    source = (
        "def why(aligned):\n    return ()\n\n"
        "def plan(blocks):\n"
        "    def as_sent(name):\n        return name\n"
        "    for block in blocks:\n"
        "        if block:\n            why = 'refused'\n"
        "        as_sent = list(blocks)\n"
        "    return why(blocks), as_sent(blocks)\n"
    )
    assert shadowed_calls(source) == {"plan:4": ["as_sent", "why"]}


def test_the_scan_allows_a_local_that_is_not_called_and_a_comprehension_variable() -> None:
    source = (
        "def texts(blocks):\n    return blocks\n\n"
        "def read(blocks):\n"
        "    texts = [b for b in blocks]\n"
        "    return [texts for texts in blocks], texts\n\n"
        "def other(blocks):\n    return texts(blocks)\n"
    )
    assert shadowed_calls(source) == {}


def test_no_function_assigns_to_a_function_it_calls() -> None:
    found = {}
    for path in sorted([*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").rglob("*.py")]):
        shadowed = shadowed_calls(path.read_text(encoding="utf-8"))
        if shadowed:
            found[str(path.relative_to(ROOT))] = shadowed
    assert found == {}, f"a function assigns to the name of a function it calls: {found}"


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
