"""The Claude Code plugin, as another project receives it.

The skills are prose and cannot be tested for being right. What can be tested is that the
parts still agree with each other, and each check below exists because the disagreement
already happened once: a gate's hint sent the author to a skill that did not exist, and the
marketplace manifest carried keys Claude Code refuses, so nobody could install the plugin.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import build_parser
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
        # The description is all an agent sees when deciding whether a skill applies.
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


# The tools through which Claude Code runs a shell command. Each sends it in
# `tool_input.command`, which is where the submission guard reads it.
SHELL_TOOLS = {"Bash", "PowerShell", "Monitor"}


def test_the_submission_guard_is_registered_for_every_tool_that_runs_a_shell_command():
    """Registered for `Bash` alone, the guard never ran on Windows.

    Claude Code and Codex both read a matcher made of letters and `|` as a list of exact
    tool names, so `Bash` is the Bash tool and nothing else. On Windows Claude Code sends an
    agent's commands through the `PowerShell` tool, and where Git Bash is absent it has no
    Bash tool at all: `Copy-Item build\\manuscript.docx` out of a failing project was never
    shown to the guard.
    """
    config = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    (matcher,) = [
        group.get("matcher", "")
        for group in config["hooks"]["PreToolUse"]
        if any(hook["command"].split()[-1] == "guard-submission" for hook in group["hooks"])
    ]
    # Any other character and both tools read the matcher as a regular expression instead.
    assert re.fullmatch(r"[A-Za-z0-9_|]+", matcher), matcher
    assert set(matcher.split("|")) == SHELL_TOOLS


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


# ---------------------------------------------------------------- what the skills tell you to run
#
# A skill is read by a model that then types what it says. A command or option that the CLI
# does not have is a failed call at best, and at worst the model works around it by writing
# the file by hand, which is how a record acquires digests nobody computed.

FENCED = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
INLINE_SPAN = re.compile(r"`([^`]+)`")
MENTION = re.compile(r"(?:manuscript-guard|mguard)\s+(?P<sub>[a-z][a-z-]*)(?P<rest>[^|&;#]*)")
BARE = re.compile(r"^(?P<sub>[a-z][a-z-]*)\s+(?P<rest>--?[A-Za-z].*)$")
OPTION = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")
CONTINUATION = re.compile(r"\\\n\s*")
PLACEHOLDER = re.compile(r"<[^<>\n]*>")


def cli_options() -> dict[str, set[str]]:
    """Every subcommand the CLI has, and every option each one accepts."""
    parser = build_parser()
    (subparsers,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    return {
        name: {opt for action in sub._actions for opt in action.option_strings}
        for name, sub in subparsers.choices.items()
    }


def command_fragments(text: str) -> list[str]:
    """The pieces of a skill that can name a command: each line of a fenced block, with
    backslash continuations joined, and each inline code span, across line breaks."""
    fragments: list[str] = []
    for block in FENCED.findall(text):
        joined = CONTINUATION.sub(" ", block)
        fragments.extend(line.strip() for line in joined.splitlines()[1:-1])
    prose = FENCED.sub("", text)
    fragments.extend(" ".join(span.split()) for span in INLINE_SPAN.findall(prose))
    return fragments


def command_problems(text: str, options: dict[str, set[str]]) -> list[str]:
    """Subcommands and options a skill names that the CLI does not have."""
    found: list[str] = []
    for fragment in command_fragments(text):
        # `<pass|reject>` holds a pipe, which would end the command there and leave every
        # option after it unchecked.
        fragment = PLACEHOLDER.sub("", fragment)
        mentions = [(m["sub"], m["rest"]) for m in MENTION.finditer(fragment)]
        bare = BARE.match(fragment)
        if bare and bare["sub"] in options:
            mentions.append((bare["sub"], bare["rest"]))
        for sub, rest in mentions:
            if sub not in options:
                found.append(f"manuscript-guard {sub}: there is no such subcommand")
                continue
            found.extend(
                f"{sub} {option}: {sub} has no such option"
                for option in OPTION.findall(rest)
                if option not in options[sub]
            )
    return found


def test_every_command_a_skill_tells_you_to_run_exists():
    options = cli_options()
    named = 0
    wrong: dict[str, list[str]] = {}
    for skill in sorted(SKILLS.glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        named += sum(bool(MENTION.search(f)) for f in command_fragments(text))
        if problems := command_problems(text, options):
            wrong[skill.parent.name] = problems
    assert named > 30, "the skills name no commands; the pattern no longer matches"
    assert not wrong, wrong


def test_the_command_check_catches_a_command_or_option_that_does_not_exist():
    text = (
        "Run `manuscript-guard frobnicate`, then\n\n```bash\n"
        "manuscript-guard check --nope        # a comment\n"
        "manuscript-guard audit paper.docx \\\n    --against out/ --nonsense\n"
        "manuscript-guard review --record a --round 2 --verdict pass\n"
        "manuscript-guard review --record a --verdict <pass|reject> --typo x\n```\n\n"
        "and `bind --apply --nothing`, but `bind --apply --only main.md:3` is fine."
    )
    assert command_problems(text, cli_options()) == [
        "check --nope: check has no such option",
        "audit --nonsense: audit has no such option",
        "review --typo: review has no such option",
        "manuscript-guard frobnicate: there is no such subcommand",
        "bind --nothing: bind has no such option",
    ]


def test_the_skills_name_the_commands_that_write_a_record_rather_than_a_hand_computed_digest():
    """A record carries a digest of what was read. `review --record` and `--record-figure`
    fill it in; the skills that describe those records once told the reader to compute it
    and type it, and one told them to write a generated file by hand."""
    review = (SKILLS / "review-panel" / "SKILL.md").read_text(encoding="utf-8")
    assert "--record" in review.split("## 3.")[0], "step 2 does not mention `review --record`"
    figure = (SKILLS / "figure-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "--record-figure" in figure


def test_the_checklist_skill_retrieves_a_checklist_with_the_commands_that_do_it():
    """The skill told the reader to type a profile into `profiles/reporting/`, which the
    plugin's own write guard refuses, and never mentioned `fetch` and `transcribe`, which
    are how a profile is made and what makes it verbatim."""
    text = (SKILLS / "reporting-checklist" / "SKILL.md").read_text(encoding="utf-8")
    for command in ("manuscript-guard fetch", "manuscript-guard transcribe"):
        assert command in text, command
    assert "schema: manuscript-guard/reporting/1" not in text, (
        "the skill shows a generated profile as something to write"
    )


def test_the_checklist_skill_lists_the_guidelines_a_recipe_says_go_together():
    """RECORD-PE holds only its own items. The skill said RECORD and RECORD-PE both extend
    STROBE, so a study following it declared two guidelines and RECORD's items were never
    checked."""
    from manuscript_guard.paths import SHIPPED_RECIPES

    recipe = (SHIPPED_RECIPES / "RECORD-PE.recipe.yaml").read_text(encoding="utf-8")
    assert "list STROBE, RECORD and RECORD-PE together" in recipe
    text = (SKILLS / "reporting-checklist" / "SKILL.md").read_text(encoding="utf-8")
    assert "STROBE, RECORD and RECORD-PE" in text


def test_nothing_in_the_plugin_names_a_path_on_one_machine():
    drive = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
    home = re.compile(r"/Users/|/home/|~/")
    offenders = {}
    for path in sorted(PLUGIN.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        hits = drive.findall(text) + home.findall(text)
        if hits:
            offenders[str(path.relative_to(REPO))] = hits
    assert not offenders, offenders


# ---------------------------------------------------------------- skills any agent can read
#
# The skills are in the open SKILL.md format, and Claude Code is one of several agent tools
# that read it. A sentence that names one of those tools, a tool only it has, or the way it
# packages the skills is wrong for a reader working under another one, who has no such tool
# and may have no plugin at all.

# The frontmatter fields the Agent Skills specification defines (agentskills.io). Any other
# key is one tool's extension, and another tool is free to refuse the file for it.
SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
SPEC_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# Model providers are left out on purpose: a review panel may name the providers its models
# come from, and that is true under any agent tool. So are ChatGPT, Copilot and Cursor, which
# a skill may have to name as what a pasted artefact came from, what a co-author used in
# Word, or where the cursor is. `Claude` alone is in, because in a skill it has meant the
# reader every time it appeared.
AGENT_SPECIFIC = (
    (
        r"\b(?:Claude|Codex|Gemini CLI|Mistral Vibe|Kimi Code)\b",
        "names one agent tool",
    ),
    (
        r"\b(?:NotebookEdit|AskUserQuestion|WebFetch|WebSearch|TodoWrite|ExitPlanMode|"
        r"apply_patch|run_shell_command|write_file|search_replace|activate_skill|"
        r"subagent_type)\b"
        r"|\bmcp__\w+"
        r"|\b(?:[Tt]he|[Yy]our|[Aa]) `?(?:Bash|Read|Write|Edit|Grep|Glob|Task|Agent|Skill|Shell)`?"
        r" tool\b",
        "names a tool only one agent has",
    ),
    (
        r"\b[Pp]lug-?in|/manuscript-guard:|\bslash commands?\b|\b(?:CLAUDE|GEMINI)\.md\b"
        r"|\.claude\b|\bCLAUDE_[A-Z_]+",
        "describes how one agent packages or invokes the skills",
    ),
)

# What the list above would catch by its spelling and is not about the reader's tool: another
# product's plugin, which is how this repository names Zotero's in Word, and a model named in
# prose as a member of a panel. Taken out before the scan.
NOT_THE_READERS_TOOL = re.compile(
    r"\b(?:Zotero|Better BibTeX|Word|[Bb]rowser)(?:'s)?(?: Word| Zotero)? plug-?ins?\b"
    r"|\bAnthropic's Claude\b|\bClaude (?:Opus|Sonnet|Haiku|models?)\b"
    r"|[\w.]-Codex\b"
)


def wording_problems(text: str) -> list[str]:
    """Phrases in a skill that only a reader under one agent tool can act on."""
    # Prose is wrapped, and a name split across two lines is still the name.
    flat = NOT_THE_READERS_TOOL.sub(" ", " ".join(text.split()))
    return [
        f"{match.group(0)!r} {why}"
        for pattern, why in AGENT_SPECIFIC
        for match in re.finditer(pattern, flat)
    ]


def test_every_skill_follows_the_open_skill_format():
    for name in sorted(skill_names()):
        meta = frontmatter(SKILLS / name / "SKILL.md")
        extra = sorted(set(meta) - SPEC_FIELDS)
        assert not extra, f"{name}: {extra} is not a field of the specification"
        # The directory carries the name, and the first test above holds the two equal.
        assert SPEC_NAME.fullmatch(name) and len(name) <= 64, name
        assert isinstance(meta["description"], str) and meta["description"].strip(), name


def test_no_skill_speaks_to_the_reader_of_one_agent_tool_only():
    wrong = {
        skill.parent.name: problems
        for skill in sorted(SKILLS.glob("*/SKILL.md"))
        if (problems := wording_problems(skill.read_text(encoding="utf-8")))
    }
    assert not wrong, wrong


def test_the_wording_check_catches_what_only_one_agent_tool_understands():
    text = (
        "The plugin's hooks need the `PATH` Claude\nCode sees. Use the Claude-in-Chrome tools,\n"
        "call `AskUserQuestion`, `mcp__browser__open`, the Bash tool or The `Task` tool, or\n"
        "type /manuscript-guard:project-setup, a slash command. Read CLAUDE.md and\n"
        ".claude/skills, set CLAUDE_PLUGIN_ROOT, and install the plug-in.\n"
    )
    assert wording_problems(text) == [
        "'Claude' names one agent tool",
        "'Claude' names one agent tool",
        "'AskUserQuestion' names a tool only one agent has",
        "'mcp__browser__open' names a tool only one agent has",
        "'the Bash tool' names a tool only one agent has",
        "'The `Task` tool' names a tool only one agent has",
        "'plugin' describes how one agent packages or invokes the skills",
        "'/manuscript-guard:' describes how one agent packages or invokes the skills",
        "'slash command' describes how one agent packages or invokes the skills",
        "'CLAUDE.md' describes how one agent packages or invokes the skills",
        "'.claude' describes how one agent packages or invokes the skills",
        "'CLAUDE_PLUGIN_ROOT' describes how one agent packages or invokes the skills",
        "'plug-in' describes how one agent packages or invokes the skills",
    ]


def test_the_wording_check_passes_what_is_true_under_any_agent_tool():
    """Each of these was flagged by a scan that matched on spelling alone. The first is this
    repository's own name for what refreshes the citations in Word."""
    text = (
        "Open the document in Word and press Refresh in Word's Zotero plugin. Zotero needs\n"
        "the Better BibTeX plugin, and browser plugins that rewrite a page spoil a saved\n"
        "source. A panel may mix models from OpenAI, Mistral and Anthropic: Anthropic's Claude\n"
        "models, Claude Opus and GPT-5-Codex in prose, `anthropic/claude-opus` as an\n"
        "identifier. `oaicite` is what ChatGPT leaves in pasted text, a co-author may have let\n"
        "Copilot in Word rewrite a paragraph, and Cursor position in Word does not matter.\n"
        "Write the plan, read AGENTS.md, and run it in bash.\n"
    )
    assert wording_problems(text) == []


def test_the_setup_skill_says_what_is_left_without_hooks_and_no_more():
    """It said every build writes `build/` afresh. A build rewrites its own documents and
    leaves the rest of the directory: a response letter edited by hand stays as edited until
    `respond` runs again, and no gate reads it."""
    text = " ".join((SKILLS / "project-setup" / "SKILL.md").read_text(encoding="utf-8").split())
    section = text.split("## 6.")[1].split("## If you are a model")[0]
    assert "afresh" not in section
    assert "`respond` for the letter" in section
