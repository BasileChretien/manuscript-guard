"""The agent tool's own deny rules for the vault's folder, printed by `vault init` and, after a
y/N at a terminal, written into Claude Code's local settings.

A hook on Read, Grep and Glob would start a Python process on every read, for every user of
the plugin, vault or none; the agent tool's own rules cost nothing and are enforced by the
tool. They are a second layer, not the separation: by Claude Code's documentation (DESIGN.md
quotes it) a Read or Edit deny rule covers its file tools and the file commands it recognises
in a shell, and not a script that opens the file itself.

The spelling is Claude Code's, from its permissions page (read 2026-10-30): `//path` is an
absolute path from the root of the file system, a single `/` anchors at the settings file, and
on Windows a path is put in POSIX form before it is matched, `C:\\Users\\alice` being
`/c/Users/alice`. The patterns are gitignore's, so a folder whose path holds a character such
a pattern reads (`*`, `?`, `[`, `]`, `\\`) or a bracket the rule's own syntax reads is not
spelt: the rules are not printed for it, and `--agent-settings` refuses.
"""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

#: Where Claude Code reads a project's local settings, from the folder a session starts in.
SETTINGS = Path(".claude") / "settings.local.json"
#: Characters a gitignore pattern or a permission rule reads as something other than itself.
_UNSPELLABLE = frozenset("*?[]\\()")


class Unspellable(ValueError):
    """The folder's path cannot be written as a rule that matches it exactly."""


def rule_path(folder: PurePath | str, *, windows: bool | None = None) -> str:
    """The folder as a Claude Code rule spells an absolute path: `//c/Users/x/vault` for
    `C:\\Users\\x\\vault`, `//home/x/vault` for `/home/x/vault`. `windows` is this machine's
    unless given."""
    if os.name == "nt" if windows is None else windows:
        path = PureWindowsPath(folder)
        # A share (`\\host\share`) has no letter, and the page says nothing of how one is
        # matched.
        if len(path.drive) != 2 or path.drive[1] != ":" or not path.root:
            raise Unspellable(f"{folder} is not an absolute path on a drive with a letter")
        parts = [path.drive[0].lower(), *path.parts[1:]]
    else:
        path = PurePosixPath(folder)
        if not path.is_absolute():
            raise Unspellable(f"{folder} is not an absolute path")
        parts = list(path.parts[1:])
    bad = sorted({c for part in parts for c in part if c in _UNSPELLABLE})
    if bad:
        raise Unspellable(
            f"{folder} holds {' '.join(bad)}, which a rule reads as a pattern, so no rule "
            "can name the folder exactly"
        )
    return "//" + "/".join(parts)


def rules(folder: PurePath | str, *, windows: bool | None = None) -> list[str]:
    """Claude Code's deny rules for the folder and everything under it, for its file tools
    that read and those that edit (a `Read` rule also stops Write, not NotebookEdit)."""
    spelt = rule_path(folder, windows=windows)
    return [f"Read({spelt})", f"Read({spelt}/**)", f"Edit({spelt})", f"Edit({spelt}/**)"]


def merged(settings: Path, added: list[str]) -> tuple[dict, list[str]]:
    """The settings file with the rules added to `permissions.deny`, and those it lacked. A
    file that is not a JSON object, or whose `permissions.deny` is not a list, is refused."""
    document: object = {}
    if settings.exists():
        try:
            document = json.loads(settings.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, RecursionError) as exc:
            raise ValueError(f"{settings} cannot be read as JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{settings} does not hold a JSON object")
    permissions = document.get("permissions", {})
    deny = permissions.get("deny", []) if isinstance(permissions, dict) else None
    if not isinstance(deny, list):
        raise ValueError(f"{settings}: permissions.deny is not a list")
    missing = [rule for rule in added if rule not in deny]
    return {**document, "permissions": {**permissions, "deny": [*deny, *missing]}}, missing


def write(settings: Path, document: dict) -> None:
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_bytes((json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode())
