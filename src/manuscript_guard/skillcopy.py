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
import stat
import tempfile
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



def way_forward(why: str, *, shared: bool) -> str:
    """What can be done about a folder that was left, said with it: a refusal that names no
    way forward is met by someone who has edited nothing. `shared` is the folder in the
    user's home, which holds their other skills; a project's own folder does not, and there
    `--project` is the option already given."""
    if why == CHANGED:
        return "to take this release's, delete the folder and run the command again"
    if shared:
        return "`--project` copies the skills into the project instead, where nothing else is"
    return (
        "move it away, or delete it if it is this skill and its stamp was lost, and run the "
        "command again"
    )


class SkillsMissing(Exception):
    """This copy of the tool has no skills to give."""


class StampUnreadable(Exception):
    """A stamp is there, and this release cannot read it. Nothing in its folder is touched:
    it may be a later release's, and writing a new one over it would make every folder
    there someone else's for good."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"{path} is not a stamp this release can read, so nothing in {path.parent} was "
            f"touched. If it is from a later release of manuscript-guard, upgrade this one. "
            f"If it is damaged, delete it together with the skill folders it was for, and "
            f"run the command again."
        )
        self.path = path


@dataclass(frozen=True)
class Copied:
    """What one copy did, by skill."""

    folder: Path
    written: tuple[str, ...]
    unchanged: tuple[str, ...]
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


#: What a skill's folder may be called, by the Agent Skills specification. A name in a stamp
#: is used as a path, so it is held to this: one lower-case folder name and nothing else.
_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def read_stamp(folder: Path) -> dict | None:
    """The stamp in a folder, or None where there is none.

    A stamp that is there and cannot be trusted raises `StampUnreadable`. It says which
    folders may be removed, so it is believed whole or not at all: another schema, a missing
    field, or a name that is not a skill's (a path, an upper-case twin of a real name) each
    make the whole of it unreadable.
    """
    path = Path(folder) / STAMP
    if not path.exists() and not path.is_symlink():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise StampUnreadable(path) from exc
    if (
        not isinstance(document, dict)
        or document.get("schema") != SCHEMA
        or not isinstance(document.get("version"), str)
        or not isinstance(document.get("skills"), dict)
    ):
        raise StampUnreadable(path)
    for name, files in document["skills"].items():
        if not _SKILL_NAME.fullmatch(name) or not isinstance(files, dict):
            raise StampUnreadable(path)
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in files.items()):
            raise StampUnreadable(path)
    return document


def _digests(skill: Path) -> dict[str, str]:
    """Each file of a skill, with a digest of its text.

    CRLF is read as LF. A copy committed with a project comes back from git on Windows with
    the other line endings, and is the same copy.
    """
    return {
        path.relative_to(skill).as_posix(): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        for path in sorted(skill.rglob("*"))
        if path.is_file()
    }


def _is_link(path: Path) -> bool:
    """A symbolic link, or on Windows a junction, which `is_symlink` does not report."""
    if path.is_symlink():
        return True
    try:
        tag = os.lstat(path).st_reparse_tag
    except (OSError, AttributeError):  # no such attribute anywhere but on Windows
        return False
    return tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None)


def _holds(target: Path, text: dict[str, str]) -> bool:
    """Whether a real folder is there and holds exactly this text."""
    return not _is_link(target) and target.is_dir() and _digests(target) == text


def _why_left(target: Path, recorded: object) -> str | None:
    """Why what stands where a skill goes may not be replaced, or None where it may.

    `recorded` is what the stamp says was copied there.
    """
    if not target.exists() and not _is_link(target):
        return None
    if recorded is None or _is_link(target) or not target.is_dir():
        return NOT_OURS
    return None if _digests(target) == recorded else CHANGED


def _write_stamp(folder: Path, skills: dict[str, dict[str, str]]) -> None:
    document = {"schema": SCHEMA, "version": __version__, "skills": skills}
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    partial = folder / (STAMP + ".partial")
    partial.write_text(text, encoding="utf-8", newline="\n")
    os.replace(partial, folder / STAMP)


def _swap(target: Path, source: Path | None) -> None:
    """Put a copy of `source` where `target` is, or with no source take `target` away.

    Through a folder made for the purpose beside it, so that nothing that was already there
    is touched and no half-copied folder ever stands under a skill's name. What is there is
    moved aside whole before anything is removed. A folder that cannot be moved, as one in
    use on Windows cannot, is then left whole, where removing it file by file left it
    emptied.
    """
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".partial", dir=target.parent)
    )
    try:
        if source is not None:
            shutil.copytree(source, staging / "new")
        old = staging / "old"
        if target.exists():
            os.replace(target, old)
        if source is not None:
            try:
                os.replace(staging / "new", target)
            except OSError:
                if old.exists():
                    os.replace(old, target)
                raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def install(folder: Path) -> Copied:
    """Copy every skill into `folder`, replacing only what an earlier copy wrote there.

    A folder that already holds the text of the skill that is coming is left as it is and
    recorded, whatever the stamp says of it: nothing would change, and writing it again
    would write over a folder that may be the user's own, or still carry the line endings
    git gave it.

    The stamp is written last. A copy that stops before then leaves each skill either as it
    was, which the old stamp still describes, or as this release has it, which the next
    copy recognises, so the next copy finishes it.
    """
    source = shipped()
    names = sorted(path.parent.name for path in source.glob("*/SKILL.md"))
    if not names:
        raise SkillsMissing(f"no skills in {source}; this copy of manuscript-guard has none")

    folder = Path(folder)
    ours = (read_stamp(folder) or {}).get("skills", {})
    folder.mkdir(parents=True, exist_ok=True)

    recorded: dict[str, dict[str, str]] = {}
    written: list[str] = []
    unchanged: list[str] = []
    removed: list[str] = []
    left: list[tuple[str, str]] = []

    for name in names:
        target = folder / name
        coming = _digests(source / name)
        if _holds(target, coming):
            recorded[name] = coming
            unchanged.append(name)
            continue
        why = _why_left(target, ours.get(name))
        if why:
            left.append((name, why))
            if name in ours:
                recorded[name] = ours[name]
            continue
        _swap(target, source / name)
        recorded[name] = coming
        written.append(name)

    # A skill an earlier release copied and this one no longer has.
    for name in sorted(set(ours) - set(names)):
        target = folder / name
        why = _why_left(target, ours[name])
        if why:
            left.append((name, why))
            recorded[name] = ours[name]
        elif target.exists():
            _swap(target, None)
            removed.append(name)

    _write_stamp(folder, recorded)
    return Copied(folder, tuple(written), tuple(unchanged), tuple(removed), tuple(left))


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
        try:
            stamp = read_stamp(folder)
        except StampUnreadable:
            # Said by `install-skills`, which is where it can be acted on. Here it must not
            # cost the other folder its line.
            continue
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
