"""Copying the skills to a folder an agent tool reads.

Claude Code and Codex install the skills as a plugin, from the repository. Other agent tools
have no such route here and read a folder of skills instead. `.agents/skills`, in a project
and in the user's home, is the one that Codex, Gemini CLI, Mistral Vibe and Kimi Code CLI all
read. This module copies the skills there and remembers what it copied.

**One source.** The skills live in `plugin/skills` in the repository and nowhere else. The
wheel takes those files as `manuscript_guard/skills` when it is built (pyproject.toml,
force-include), so what is copied is what the release was built with, and the repository
holds no second copy to drift from the first.

**A copy goes stale.** `pip install --upgrade` renews the tool and leaves the copy. So each
folder gets a stamp naming the release and a digest of every file, and `check` and `build`
say when a stamp they find names another release.

**Nothing that is not this tool's is touched.** `~/.agents/skills` is shared with every other
skill the user has. The stamp is how a second copy knows what it may replace: a folder it
did not write, or one changed since it wrote it, is left as it is and named.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard import __version__

#: Beside the skills, in the folder they were copied to.
STAMP = ".manuscript-guard.json"
SCHEMA = "manuscript-guard/skills/1"

#: The folder in the user's home, for a machine where it is somewhere else, and for the test
#: suite, which must not read whatever the person running it has installed.
USER_FOLDER_VARIABLE = "MANUSCRIPT_GUARD_USER_SKILLS"

NOT_OURS = "was already there and is not from manuscript-guard"
CHANGED = "was changed since manuscript-guard copied it"


class SkillsMissing(Exception):
    """This copy of the tool has no skills to give."""


@dataclass(frozen=True)
class Copied:
    """What one copy did, by skill."""

    folder: Path
    written: tuple[str, ...]
    removed: tuple[str, ...]
    left: tuple[tuple[str, str], ...]


def shipped() -> Path:
    """Where this copy of the tool keeps the skills.

    Installed, they are in the package. In a checkout they are where the plugin has them,
    because the package directory under `src/` deliberately holds no copy.
    """
    packaged = Path(__file__).parent / "skills"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[2] / "plugin" / "skills"


def user_folder() -> Path:
    named = os.environ.get(USER_FOLDER_VARIABLE, "").strip()
    return Path(named) if named else Path.home() / ".agents" / "skills"


def project_folder(root: Path) -> Path:
    return Path(root) / ".agents" / "skills"


def read_stamp(folder: Path) -> dict | None:
    """The stamp in a folder, or None where there is none this tool can read."""
    try:
        document = json.loads((folder / STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        return None
    if not isinstance(document.get("version"), str) or not isinstance(
        document.get("skills"), dict
    ):
        return None
    return document


def _digests(skill: Path) -> dict[str, str]:
    return {
        path.relative_to(skill).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(skill.rglob("*"))
        if path.is_file()
    }


def _why_left(target: Path, recorded: object) -> str | None:
    """Why a folder that is in the way may not be replaced, or None where it may."""
    if not target.exists() and not target.is_symlink():
        return None
    if recorded is None or target.is_symlink() or not target.is_dir():
        return NOT_OURS
    return None if _digests(target) == recorded else CHANGED


def _write_stamp(folder: Path, skills: dict[str, dict[str, str]]) -> None:
    document = {"schema": SCHEMA, "version": __version__, "skills": skills}
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    partial = folder / (STAMP + ".partial")
    partial.write_text(text, encoding="utf-8", newline="\n")
    os.replace(partial, folder / STAMP)


def install(folder: Path) -> Copied:
    """Copy every skill into `folder`, replacing only what an earlier copy wrote there."""
    source = shipped()
    names = sorted(path.parent.name for path in source.glob("*/SKILL.md"))
    if not names:
        raise SkillsMissing(f"no skills in {source}; this copy of manuscript-guard has none")

    folder = Path(folder)
    ours = (read_stamp(folder) or {}).get("skills", {})
    folder.mkdir(parents=True, exist_ok=True)

    recorded: dict[str, dict[str, str]] = {}
    written: list[str] = []
    removed: list[str] = []
    left: list[tuple[str, str]] = []

    for name in names:
        target = folder / name
        why = _why_left(target, ours.get(name))
        if why:
            left.append((name, why))
            if name in ours:
                recorded[name] = ours[name]
            continue
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source / name, target)
        recorded[name] = _digests(target)
        written.append(name)

    # A skill an earlier release copied and this one no longer has.
    for name in sorted(set(ours) - set(names)):
        target = folder / name
        why = _why_left(target, ours[name])
        if why:
            left.append((name, why))
            recorded[name] = ours[name]
        elif target.exists():
            shutil.rmtree(target)
            removed.append(name)

    _write_stamp(folder, recorded)
    return Copied(folder, tuple(written), tuple(removed), tuple(left))


def _numbers(version: str) -> tuple[int, ...] | None:
    """`0.2.400` as (0, 2, 400); None for anything that is not plain dotted digits."""
    if not re.fullmatch(r"\d{1,9}(?:\.\d{1,9})*", version.strip()):
        return None
    return tuple(int(part) for part in version.strip().split("."))


def stale_notice(root: Path | None) -> str | None:
    """A line for each copy of the skills that is from another release than this tool.

    It looks in two places only: the project's `.agents/skills` and the user's. A copy made
    with `--dir` somewhere else is not found, and neither is a plugin, which its own agent
    tool keeps.
    """
    from manuscript_guard.hooks import UPGRADE_COMMAND

    here = _numbers(__version__)
    places = [(user_folder(), "")]
    if root is not None:
        places.insert(0, (project_folder(root), " --project"))

    lines: list[str] = []
    for folder, flag in places:
        stamp = read_stamp(folder)
        if stamp is None:
            continue
        copy = _numbers(stamp["version"])
        if copy is None or here is None or copy == here:
            continue
        said = stamp["version"].strip()
        if copy < here:
            lines.append(
                f"manuscript-guard: the skills in {folder} are from {said} and this tool is "
                f"{__version__}. Copy the current ones with "
                f"`manuscript-guard install-skills{flag}`."
            )
        else:
            lines.append(
                f"manuscript-guard: the skills in {folder} are from {said}, newer than this "
                f"tool ({__version__}), so a skill may name a command it lacks. Upgrade the "
                f"tool with: {UPGRADE_COMMAND}."
            )
    return "\n".join(lines) or None
