"""The Claude Code plugin, as another project receives it.

The skills are prose and cannot be tested for being right. What can be tested is that the
parts still agree with each other, and each check below exists because the disagreement
already happened once: a gate's hint sent the author to a skill that did not exist, and the
marketplace manifest carried keys Claude Code refuses, so nobody could install the plugin.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from manuscript_guard.hooks import HANDLERS

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugin"
SKILLS = PLUGIN / "skills"
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"

# "the review-panel skill", "the `journal-profile` skill", "the x and y-z skills". Hints are
# split across lines as adjacent string literals, which is exactly how the broken one hid,
# so in Python source the literals are joined first. "X and Y skills" catches only Y.
SKILL_MENTION = re.compile(r"`?\b([a-z]+(?:-[a-z]+)+)`? skills?\b")
ADJACENT_LITERALS = re.compile(r"[\"']\s*\n\s*[rbfuRBFU]*[\"']")


def skill_names() -> set[str]:
    return {path.parent.name for path in SKILLS.glob("*/SKILL.md")}


def frontmatter(path: Path) -> dict:
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
    assert match, f"{path.relative_to(REPO)} has no frontmatter"
    return yaml.safe_load(match.group(1))


def test_every_skill_names_itself_and_says_when_it_applies():
    assert skill_names(), "no skills found; the plugin layout has moved"
    for name in sorted(skill_names()):
        meta = frontmatter(SKILLS / name / "SKILL.md")
        assert meta.get("name") == name, f"{name}/SKILL.md calls itself {meta.get('name')!r}"
        description = meta.get("description") or ""
        # The description is all Claude sees when deciding whether a skill applies.
        assert "Use " in description, f"{name}: the description never says when to use it"
        assert len(description) <= 1024, f"{name}: description too long to be loaded"


def test_every_skill_the_project_points_to_exists():
    sources = [
        *(REPO / "src").rglob("*.py"),
        *(REPO / "example").rglob("*.yaml"),
        *(REPO / "example").rglob("*.md"),
        *SKILLS.glob("*/SKILL.md"),
        REPO / "README.md",
        REPO / "DESIGN.md",
        REPO / "CLAUDE.md",
    ]
    named: dict[str, Path] = {}
    for path in sources:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            text = ADJACENT_LITERALS.sub("", text)
        for name in SKILL_MENTION.findall(text):
            named.setdefault(name, path)
    assert named, "no skill is named anywhere; the pattern no longer matches"
    missing = {name: str(path.relative_to(REPO)) for name, path in named.items()
               if name not in skill_names()}
    assert not missing, f"these name skills that do not exist: {missing}"


def test_every_link_between_skills_resolves_inside_the_plugin():
    # Installing copies plugin/ alone into Claude Code's cache, so a link that climbs out of
    # it resolves here and is dead for every user.
    plugin = PLUGIN.resolve()
    for skill in SKILLS.glob("*/SKILL.md"):
        for target in re.findall(r"\]\((\.\./[^)#]+)\)", skill.read_text(encoding="utf-8")):
            resolved = (skill.parent / target).resolve()
            where = f"{skill.parent.name} -> {target}"
            assert resolved.is_file(), where
            assert resolved.is_relative_to(plugin), f"{where} leaves plugin/"


def test_the_readme_lists_exactly_the_skills_that_ship():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    section = readme.split("### The Claude Code plugin", 1)[1].split("\n## ", 1)[0]
    listed = set(re.findall(r"^\| `([a-z-]+)` \|", section, re.MULTILINE))
    assert listed == skill_names()


def test_every_hook_the_plugin_registers_has_a_handler():
    config = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for groups in config["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]
    assert commands
    scripts = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    for command in commands:
        executable, handler = command.split()
        assert re.search(rf"^{re.escape(executable)}\s*=", scripts, re.MULTILINE), executable
        # An unknown handler exits 0 in silence, by design, so a typo here would guard nothing.
        assert handler in HANDLERS, f"{command!r} reaches no handler"


def test_the_marketplace_installs_the_plugin_it_describes():
    market = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    (entry,) = [plugin for plugin in market["plugins"] if plugin["name"] == manifest["name"]]
    assert (REPO / entry["source"]).resolve() == PLUGIN.resolve()
    # An update compares versions, so two that disagree install one and report the other.
    assert entry.get("version") == manifest["version"]


# Skipped where Claude Code is absent. CI's plugin-manifests job installs it and runs the
# same validation, so the check that motivated this file does run on every pull request.
@pytest.mark.skipif(shutil.which("claude") is None, reason="Claude Code is not installed")
@pytest.mark.parametrize("target", [REPO, PLUGIN], ids=["marketplace", "plugin"])
def test_claude_code_accepts_the_manifest(target):
    result = subprocess.run(
        [shutil.which("claude"), "plugin", "validate", str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
