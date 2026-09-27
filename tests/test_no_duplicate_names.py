"""No module binds the same top-level name twice.

Python keeps the later binding without a word, and ruff's F811 fires only when the first
one was never used. The failure is real, and parallel branches produce it on their own:
#69 and #40 each added an `_unidentified` to merge.py, the later won, and every import
failed; #32 and #77 each defined `_CLAIM` in test_corruption.py, so #32's tests would have
run with #77's string once a use of it moved into a function body. A merge of main that
reintroduces one fails here.

A later assignment that reads the name itself (`X = X + ...`) builds it up in steps and is
allowed. Bindings inside an `if` or `try` at module level (import fallbacks) are not read.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _bound(node: ast.stmt) -> list[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _reads_itself(node: ast.stmt, name: str) -> bool:
    value = getattr(node, "value", None)
    return value is not None and any(
        isinstance(n, ast.Name) and n.id == name for n in ast.walk(value)
    )


def duplicate_names(source: str) -> dict[str, list[int]]:
    """Top-level names bound more than once, with the lines that bind them."""
    lines: dict[str, list[int]] = defaultdict(list)
    for node in ast.parse(source).body:
        for name in _bound(node):
            if lines[name] and _reads_itself(node, name):
                continue
            lines[name].append(node.lineno)
    return {name: at for name, at in lines.items() if len(at) > 1}


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


def test_no_module_binds_a_name_twice() -> None:
    found = {}
    for path in sorted([*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").rglob("*.py")]):
        duplicates = duplicate_names(path.read_text(encoding="utf-8"))
        if duplicates:
            found[str(path.relative_to(ROOT))] = duplicates
    assert found == {}, f"top-level names bound twice (the later one wins silently): {found}"
