"""The README and the pages under docs/ are held to the tool they describe.

The README is the first thing a reader meets and the last thing anyone re-reads after a
change. It and the pages its long tables were moved to say which commands and gates exist,
its links lead to those pages, and its pictures quote what `check` prints. Each of those is
a claim, so each is compared here with the thing it is a claim about.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import pkgutil
import re
from pathlib import Path

import pytest

import manuscript_guard.gates
from manuscript_guard.cli import build_parser, main

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
DOCS = REPO / "docs"
#: The tables the README sums up, each on a page of its own.
COMMANDS = DOCS / "commands.md"
GATES = DOCS / "gates.md"
#: The security policy is read on GitHub beside the README, and its links are held the same way;
#: so is the file an agent tool other than Claude Code reads first.
PAGES = [README, REPO / "SECURITY.md", REPO / "AGENTS.md", *sorted(DOCS.glob("*.md"))]

LINK = re.compile(r"\]\(([^)\s]+)\)")
SOURCE = re.compile(r'\b(?:src|srcset)="([^"]+)"')
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.MULTILINE)
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def anchor(heading: str) -> str:
    """The anchor GitHub gives a heading: lower case, punctuation gone, spaces to hyphens."""
    kept = re.sub(r"[^\w\- ]", "", heading.replace("`", "").lower())
    return kept.replace(" ", "-")


def anchors_of(path: Path) -> set[str]:
    return {anchor(heading) for heading in HEADING.findall(FENCE.sub("", text_of(path)))}


def section(name: str, page: Path = README, level: int = 2) -> str:
    """One section of a page, without its heading: from the heading of that level, `## name`
    by default, to the next heading of that level or above. A page's own title, `# name`, is
    level 1, and its section is the whole page. A line of a listing is no heading."""
    text = "\n" + FENCE.sub("", text_of(page))
    heading = f"\n{'#' * level} {name}\n"
    assert heading in text, f"{page.name} has no section {name!r}"
    after = text.split(heading, 1)[1]
    return re.split(rf"^#{{1,{level}}} ", after, maxsplit=1, flags=re.MULTILINE)[0]


def test_a_section_runs_to_the_next_heading_of_its_level(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "# Title\n\nintro\n\n## One\n\na\n\n### Under\n\nb\n\n```bash\n# a comment\n```\n"
        "\n## Two\n\nc\n",
        encoding="utf-8",
    )
    assert "b" in section("One", page) and "c" not in section("One", page)
    assert section("Two", page).strip() == "c"
    assert "a comment" not in section("Title", page, level=1)
    assert section("Title", page, level=1).rstrip().endswith("c")


def first_cells(table: str, cell: str) -> list[str]:
    """The first cell of each row of a table, where it reads as `cell` does."""
    return re.findall(rf"^\| {cell} \|", table, re.MULTILINE)


# --------------------------------------------------------------------------------- links


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.relative_to(REPO).as_posix())
def test_every_link_and_picture_leads_somewhere(page: Path) -> None:
    """A section moved to docs/ leaves links behind it, and a renamed heading breaks one
    without a word."""
    text = FENCE.sub("", text_of(page))
    targets = [*LINK.findall(text), *SOURCE.findall(text)]
    assert targets, f"{page.name} links to nothing; the pattern no longer matches"
    for target in targets:
        if re.match(r"[a-z]+:", target):
            continue  # another site; not this repository's to hold
        file, _, fragment = target.partition("#")
        found = (page.parent / file).resolve() if file else page
        assert found.exists(), f"{page.name}: {target} leads to no file"
        assert found.is_relative_to(REPO), f"{page.name}: {target} leaves the repository"
        if fragment:
            assert found.suffix == ".md", f"{page.name}: {target} names a place in a non-page"
            assert fragment in anchors_of(found), f"{page.name}: {target} names no heading"


def test_the_readme_leads_to_every_page_under_docs() -> None:
    linked = {
        (README.parent / target.partition("#")[0]).resolve()
        for target in LINK.findall(text_of(README))
        if not re.match(r"[a-z]+:", target)
    }
    unlinked = [page.name for page in DOCS.glob("*.md") if page.resolve() not in linked]
    assert not unlinked, f"no link in the README leads to: {unlinked}"


# -------------------------------------------------------------------------------- tables


def test_the_commands_page_lists_the_commands_the_tool_has() -> None:
    """`hook` is left out on purpose: an agent tool calls it, an author never does."""
    choices = next(
        action.choices
        for action in build_parser()._actions  # noqa: SLF001 - argparse offers no other way
        if isinstance(action, argparse._SubParsersAction)  # noqa: SLF001
    )
    listed = first_cells(section("Commands", COMMANDS, level=1), "`([a-z-]+)`")
    assert set(listed) == set(choices) - {"hook"}


def test_no_page_sends_a_reader_to_the_readme_for_the_commands() -> None:
    """The commands left the README for their own page, where the README now names a few of
    them; a sentence that still says they are listed there sends its reader to a summary,
    and the link test passes it, since the README is there (round 1 of #550)."""
    stale = [
        f"{page.name}: {sentence}"
        for page in DOCS.glob("*.md")
        for sentence in re.split(r"(?<=[.:])\s+", " ".join(FENCE.sub("", text_of(page)).split()))
        if re.search(r"\bcommands\b[^.]*\]\(\.\./README\.md(?:#[\w-]*)?\)", sentence)
    ]
    assert stale == [], stale


def test_the_commands_page_groups_the_commands_as_the_help_does() -> None:
    """One `## ` heading per group of `manuscript-guard --help`, in its order, each over a
    table of that group's commands in the order the help lists them."""
    from manuscript_guard.cli import COMMAND_GROUPS

    commands = section("Commands", COMMANDS, level=1)
    headings = re.findall(r"^## (.+)$", commands, re.MULTILINE)
    assert headings == [heading for heading, _ in COMMAND_GROUPS]
    tables = re.split(r"^## .+$", commands, flags=re.MULTILINE)[1:]
    for (heading, names), table in zip(COMMAND_GROUPS, tables, strict=True):
        assert first_cells(table, "`([a-z-]+)`") == list(names), heading


def test_the_readme_sums_up_each_group_of_commands() -> None:
    """One item per group, in the help's order, leading to that group on the commands page;
    each command it names in passing is one of that group's."""
    from manuscript_guard.cli import COMMAND_GROUPS

    items = re.findall(r"^- (.*(?:\n  .*)*)", section("Commands"), re.MULTILINE)
    assert len(items) == len(COMMAND_GROUPS), items
    for item, (heading, names) in zip(items, COMMAND_GROUPS, strict=True):
        led = re.match(r"\*\*\[(.+?)\]\(docs/commands\.md#([\w-]+)\):\*\*", item)
        assert led, f"the README's item does not lead to its group: {item[:60]}"
        assert led.groups() == (heading, anchor(heading)), led.groups()
        named = re.findall(r"`([a-z-]+)`", item[led.end():])
        assert named, heading
        assert set(named) <= set(names), f"{heading}: {sorted(set(named) - set(names))}"


def declared_gates() -> set[str]:
    declared = set()
    for module in pkgutil.iter_modules(manuscript_guard.gates.__path__):
        gate = getattr(
            importlib.import_module(f"manuscript_guard.gates.{module.name}"), "GATE", None
        )
        if gate:
            declared.add(gate)
    return declared


def test_the_gates_page_lists_the_gates_the_tool_has() -> None:
    listed = first_cells(section("What is checked", GATES, level=1), r"(G\d+)")
    assert len(listed) == len(set(listed)), "a gate is listed twice"
    assert set(listed) == declared_gates()


def test_the_readme_sorts_the_gates_as_check_ends_by_grouping_them() -> None:
    """The README's summary is the table of what `check` groups its last lines by, each
    group with its gates, in its order; a gate in no group is named in the words after it."""
    from manuscript_guard.assurance import DIMENSIONS

    summary = section("What is checked")
    table = re.search(r"^\| What it is about \| Gates \|\n\|---\|---\|\n((?:\|.*\n)+)", summary,
                      re.MULTILINE)  # fmt: skip
    assert table, "the README no longer sums the gates up in a table"
    rows = [cells(row) for row in table.group(1).splitlines()]
    assert rows == [[dimension.name, ", ".join(dimension.gates)] for dimension in DIMENSIONS]
    grouped = {gate for dimension in DIMENSIONS for gate in dimension.gates}
    after = summary[table.end():]
    for gate in sorted(declared_gates() - grouped):
        assert re.search(rf"\b{gate}\b", after), f"the README does not say where {gate} is"


#: The pages that say in words how many gates or hooks there are.
#: The landing page says its count of gates too.
COUNTED = [README, DOCS / "agent-tools.md", GATES, REPO / "web" / "landing" / "index.html"]
COUNT = re.compile(r"\b([a-z]+(?:-[a-z]+)?)\s+(gates|hooks)\b")


def cells(row: str) -> list[str]:
    """A row's cells, split on each pipe that is not escaped or inside a code span."""
    kept = CODE.sub(lambda span: span.group().replace("|", "\0"), row.replace("\\|", "\0"))
    return [cell.strip().replace("\0", "|") for cell in kept.strip().strip("|").split("|")]


def hooks_cells(text: str) -> list[str]:
    """Each cell under a table's "Hooks" heading, as "five, once you have trusted them"; a
    row short of that column gives an empty cell."""
    found = []
    for table in re.findall(r"(?:^\|.*\n?)+", FENCE.sub("", text), re.MULTILINE):
        lines = table.splitlines()
        if len(lines) < 3:
            continue
        header, _rule, *rows = lines
        if "Hooks" in cells(header):
            column = cells(header).index("Hooks")
            found += [(cells(row) + [""] * column)[column] for row in rows]
    return found


@pytest.mark.parametrize(
    ("table", "hooks"),
    [
        ("| | Skills | Hooks |\n|---|---|---|\n| A | plugin | five |\n", ["five"]),
        ("| | Skills | Hooks |\n|---|---|---|\n| A | copy |\n", [""]),
        ("| | Reads | Hooks |\n|---|---|---|\n| A | `a|b` | four |\n", ["four"]),
        ("| | Reads | Hooks |\n|---|---|---|\n| A | a \\| b | four |\n", ["four"]),
    ],
)
def test_a_hooks_cell_is_read_in_its_column(table: str, hooks: list[str]) -> None:
    assert hooks_cells(table) == hooks


def test_a_count_of_gates_or_hooks_is_the_number_there_are() -> None:
    """A count written out goes stale in silence: the README said "fifteen gates", and "four"
    in the Hooks column of its table, long after there were more. Each "<number> gates" and
    "<number> hooks" of these pages, a line break between the two words or not, and the
    number each cell of a Hooks column opens with, is held to the gates the package declares
    and the hooks the plugin registers. A Hooks cell's number is read as the count of all of
    them, so a row for a tool that runs only some would fail here and need words of its own.
    A count written any other way is not read here. The picture's count is the script's, and
    the test of the pictures holds that."""
    import json

    words = {figures_script().in_words(number): number for number in range(100)}
    config = json.loads((REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    hooks = sum(len(group["hooks"]) for groups in config["hooks"].values() for group in groups)
    there_are = {"gates": len(declared_gates()), "hooks": hooks}
    counted = {"prose": 0, "cells": 0}
    for page in COUNTED:
        text = text_of(page)
        for word, noun in COUNT.findall(text.lower()):
            if word in words:
                counted["prose"] += 1
                assert words[word] == there_are[noun], (
                    f"{page.name} says {word} {noun}; there are {there_are[noun]}"
                )
        for cell in hooks_cells(text):
            word = re.match(r"[a-z-]*", cell.lower()).group()
            if word in words:
                counted["cells"] += 1
                assert words[word] == hooks, (
                    f"{page.name}'s Hooks column says {cell!r}; there are {hooks}"
                )
    assert all(counted.values()), f"a pattern no longer matches anything: {counted}"


# ------------------------------------------------------------------------------ pictures

#: The pages a reader sees pictures on: the README, the docs and the character sheet.
SHOWN = [*PAGES, REPO / "brand" / "README.md"]


def test_every_html_picture_on_the_pages_has_alternative_text() -> None:
    """Empty for a drawing whose name is written beside it, as the villains' are; but
    present, so that a screen reader does not read out the file's name instead. A Markdown
    picture always has its alternative text, if empty, so only HTML ones are read."""
    seen = 0
    for page in SHOWN:
        for tag in re.findall(r"<img\b[^>]*>", text_of(page)):
            seen += 1
            assert re.search(r'\salt="', tag), f"{page.name}: a picture with no alt: {tag}"
    assert seen


def test_every_animated_picture_holds_still_for_a_reader_who_turns_motion_off() -> None:
    animated = [path for path in sorted((DOCS / "img").rglob("*.svg"))
                if "@keyframes" in path.read_text(encoding="utf-8")]  # fmt: skip
    assert animated, "no animated picture found; the pattern no longer matches"
    # Which elements the rule reaches is held for the banner by tests/test_brand.py.
    still = re.compile(r"prefers-reduced-motion:\s*reduce\)\s*\{[^@]*?animation:\s*none")
    for path in animated:
        assert still.search(path.read_text(encoding="utf-8")), (
            f"{path.relative_to(REPO).as_posix()} moves for a reader who asked for less motion"
        )


def brand_script():
    spec = importlib.util.spec_from_file_location(
        "brand_assets", REPO / "tools" / "brand_assets.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def picture_alt(text: str, source: str) -> str:
    found = re.search(rf'<img\b[^>]*\ssrc="{re.escape(source)}"[^>]*?\salt="([^"]*)"', text)
    assert found, f"no picture {source} with alternative text"
    return " ".join(found.group(1).split())


def test_the_readme_describes_the_banner_as_the_character_sheet_does() -> None:
    sheet = text_of(REPO / "brand" / "README.md")
    assert picture_alt(text_of(README), "docs/img/brand/banner-light.svg") == picture_alt(
        sheet, "../docs/img/brand/banner-light.svg"
    )


def test_the_readmes_villains_are_named_with_the_gates_the_banner_gives_them() -> None:
    """The row of drawings above "What it catches": each column's drawing, and under it its
    name and gate, are the banner's cast in its order."""
    lines = text_of(README).splitlines()
    (at,) = [n for n, line in enumerate(lines) if "docs/img/brand/stray-number-light.svg" in line]
    drawn = [re.search(r"docs/img/brand/([a-z-]+)-light\.svg", cell).group(1)
             for cell in cells(lines[at])]  # fmt: skip
    under = [re.fullmatch(r"(.+), (G\d+)", cell).groups() for cell in cells(lines[at + 2])]
    script = brand_script()
    names = {name: title.split(",")[0] for name, _, _, _, title in script.DRAWINGS}
    assert [(names[one], gate) for one, gate in script.CAST] == under
    assert list(zip(drawn, [gate for _, gate in under], strict=True)) == list(script.CAST)


def figures_script():
    spec = importlib.util.spec_from_file_location(
        "readme_figures", REPO / "tools" / "readme_figures.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_pictures_are_the_ones_the_script_draws() -> None:
    """They are committed, so a change to the script that nobody ran would leave the README
    showing the old ones."""
    drawn = figures_script().figures()
    assert drawn
    # A picture drawn by hand may sit beside these; only the script's own are compared.
    for name, text in drawn.items():
        path = DOCS / "img" / name
        assert path.is_file(), f"docs/img/{name} is missing: run python tools/readme_figures.py"
        on_disk = path.read_text(encoding="utf-8")
        assert on_disk == text, f"docs/img/{name} is stale: run python tools/readme_figures.py"
        assert f"docs/img/{name}" in text_of(README), f"the README does not show {name}"


def said(output: str) -> str:
    """What `check` printed, as one line, with the path separators of Linux and macOS."""
    return " ".join(output.replace("\\", "/").split())


def test_the_terminal_picture_says_what_check_says(project: Path, capsys) -> None:
    """The picture quotes a failure. Type the number the same way, and `check` has to say
    every line of it, or the README is showing something the tool no longer prints."""
    card = figures_script().CARD
    manuscript = project / "manuscript" / "main.md"
    text = manuscript.read_text(encoding="utf-8")
    assert "{{results.cohort.n_reports}}" in text
    manuscript.write_text(
        text.replace("{{results.cohort.n_reports}}", "4,000", 1), encoding="utf-8"
    )

    assert main(["check", str(project)]) == 1
    printed = said(capsys.readouterr().out)

    quoted = [line for _kind, line in card if not line.startswith("$") and line.strip() != "..."]
    assert quoted[0].startswith("stage: ")
    assert said(quoted[0]) in printed
    finding = said(" ".join(quoted[1:]))
    assert finding.startswith("[FAIL] G2 manuscript/main.md:")
    assert finding in printed, "check no longer prints the finding the picture shows"


#: The alternative text the README gives the demo.
DEMO_ALT = re.compile(r'<img src="docs/img/demo-light\.svg"[^>]*?\salt="([^"]*)"')


def test_the_demo_ends_with_what_check_says_once_the_number_is_bound(
    project: Path, capsys, monkeypatch
) -> None:
    """The demo opens on `CARD`, binds the number again and runs `check` on the example as it
    is. The line it rewrites is the one the finding quotes, put back as the manuscript has
    it, and every line of its last scene but a `...` is printed, in that order: two lines
    with no `...` between them on two lines one after the other, and the last one last. The
    README's alternative text for the demo says the finding and each of those lines, so a
    reader who cannot see the picture is told what it shows now.

    The demo was captured where CI runs, with no Zotero, and G7 then warns that citation keys
    were not checked for pinning. Zotero is taken as not running here too, so the test says
    the same on a machine where it is open."""
    monkeypatch.setattr("manuscript_guard.gates.citations.available", lambda: False)
    script = figures_script()
    assert script.CARD[2][1].endswith(f"manuscript/main.md:{script.LINE}:17")
    lines = (project / "manuscript" / "main.md").read_text(encoding="utf-8").splitlines()
    bound = script.QUOTED.replace(script.TYPED, script.BINDING, 1)
    assert lines[int(script.LINE) - 1].startswith(bound), "the demo rewrites another line"

    assert main(["check", str(project)]) == 0
    printed = [said(line) for line in capsys.readouterr().out.splitlines()]

    scene = [said(line) for _kind, line in script.CLEAN]
    shown = [line for line in scene if line != "..."]
    assert shown[0].startswith("stage: ") and shown[-1].startswith("0 failing")
    at, adjacent = 0, False
    for line in scene:
        if line == "...":
            adjacent = False
            continue
        if adjacent:
            assert printed[at] == line, f"check prints {printed[at]!r} where the demo has {line!r}"
        else:
            assert line in printed[at:], f"check no longer prints, where the demo shows: {line}"
        at = printed.index(line, at) + 1
        adjacent = True
    assert printed[-1] == shown[-1], "the demo's last line is not the last line check prints"

    alt = DEMO_ALT.search(text_of(README))
    assert alt, "the README shows the demo with no alternative text"
    for line in [said(script.CARD[2][1]), said(script.CARD[3][1]), *shown]:
        assert says(said(alt.group(1)), line), f"the demo's alternative text does not say: {line}"


def says(text: str, line: str) -> bool:
    """Whether `text` says `line` whole: not "10 failing" for "0 failing", nor "1 warnings"
    for "1 warning" (round 2 of #532: the check was a substring test)."""
    return re.search(rf"(?<!\w){re.escape(line)}(?!\w)", text) is not None


def test_a_line_of_the_demo_is_said_only_whole() -> None:
    assert says("check says 0 failing, 13 warnings.", "0 failing, 13 warnings")
    assert not says("check says 10 failing, 13 warnings.", "0 failing, 13 warnings")
    assert not says("G8: 0 failing, 1 warnings", "G8: 0 failing, 1 warning")


def test_the_readme_quotes_what_check_says_of_an_edited_results_file(
    project: Path, capsys
) -> None:
    """The lines the README quotes are printed, in that order, and where it leaves one out it
    says so with `...`: that is the only line the block may drop."""
    block = re.search(
        r"changed by hand\..*?\n\n```text\n(.*?)```", text_of(README), re.DOTALL
    )
    assert block, "the README no longer quotes that finding"
    quoted = [said(line) for line in block.group(1).splitlines()]
    assert len(quoted) >= 3 and quoted[0].startswith("[FAIL] G1 "), quoted
    results = project / "results" / "01_disproportionality.json"
    text = results.read_text(encoding="utf-8")
    assert '"value": 4000' in text
    results.write_text(text.replace('"value": 4000', '"value": 4100', 1), encoding="utf-8")

    assert main(["check", str(project)]) == 1
    printed = [said(line) for line in capsys.readouterr().out.splitlines()]

    assert quoted[0] in printed, f"check no longer prints: {quoted[0]}"
    at = printed.index(quoted[0])
    for line in quoted[1:]:
        if line == "...":
            at += 1  # one line of the output, left out and marked
            continue
        at += 1
        assert printed[at] == line, f"after the line before it, check prints: {printed[at]}"


# ---------------------------------------------------------------------------- Known gaps

DESIGN = REPO / "DESIGN.md"
#: An entry of DESIGN.md's Known gaps below this line is closed.
CLOSED_SINCE = "Closed since, and why each mattered (an open gap goes above this line):"
#: The tag of a limit a test holds: the tests' names in backticks, "`a`, `b` and `c`".
PINNED = re.compile(r"Pinned by ((?:`[^`]+`(?:, | and )?)+)\.")
CODE_SPAN = re.compile(r"`([^`]+)`")


def open_gaps(text: str) -> str:
    """The lines of the lists of DESIGN.md's Known gaps, down to the "Closed since" line."""
    start = text.index("\n## Known gaps\n")
    end = text.index(f"\n{CLOSED_SINCE}\n", start)
    lines = text[start:end].splitlines()
    return "\n".join(line for line in lines if line.startswith(("- ", " ")))


def pins_of(gaps: str) -> tuple[list[str], list[str]]:
    """The tests each `Pinned by` names, in order, and each `Pinned by` that names none in
    backticks. A tag may break across lines, so the lines are read as one."""
    flat = " ".join(gaps.split())
    names, garbled = [], []
    for at in re.finditer(r"\bPinned by\b", flat):
        pin = PINNED.match(flat, at.start())
        if pin is None:
            garbled.append(re.match(r"[^.]*\.?", flat[at.start():]).group(0))
        else:
            names.extend(CODE_SPAN.findall(pin.group(1)))
    return names, garbled


def defined_in(path: Path) -> set[str]:
    """The tests pytest collects from a file, by the name it gives each after `::`: a
    function whose name starts `test`, and such a method of a class whose name starts `Test`
    (pytest's defaults, which pyproject.toml keeps). A helper is no test. Not read as pytest
    reads them: a class inside a class, a `Test` class with an `__init__`, and a
    `unittest.TestCase` named otherwise. No pin names any of these."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)

    def tests(body: list[ast.stmt]) -> set[str]:
        return {f.name for f in body if isinstance(f, functions) and f.name.startswith("test")}

    names = tests(tree.body)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            names |= {f"{node.name}::{name}" for name in tests(node.body)}
    return names


def unfound(names: list[str], repo: Path) -> list[str]:
    """Each name that is not a test there is: a file under `tests/` that pytest reads
    (`test_*.py` or `*_test.py`), `::`, and a test of it, less a parametrised case's
    `[...]`."""
    known: dict[Path, set[str]] = {}
    missing = []
    for name in names:
        path, _, test = name.partition("::")
        file = repo / path
        collected = re.fullmatch(r"test_\w*\.py|\w*_test\.py", Path(path).name)
        if path.startswith("tests/") and collected and file.is_file():
            if file not in known:
                known[file] = defined_in(file)
            if re.sub(r"\[.*\]$", "", test) in known[file]:
                continue
        missing.append(name)
    return missing


def test_the_open_gaps_are_the_lists_above_the_closed_line() -> None:
    """A paragraph between the lists says what a group is, and is no entry; what stands
    below the "Closed since" line is closed."""
    text = (
        "# D\n\n## Known gaps\n\nRecorded because. Pinned by `tests/x.py::test_x`.\n\n"
        "- **Open.** Pinned by `tests/a.py::test_a`.\n  more\n\nA group.\n\n"
        f"- **Also open.**\n\n{CLOSED_SINCE}\n\n- **Closed.** Pinned by `tests/b.py::test_b`.\n"
    )
    assert open_gaps(text) == (
        "- **Open.** Pinned by `tests/a.py::test_a`.\n  more\n- **Also open.**"
    )


def test_a_pin_is_found_only_where_it_names_a_test_there_is(tmp_path: Path) -> None:
    """A name with a typo, a file that is not there, a name with no path, a function or a
    class pytest does not collect, and a pin with no backticks are each told apart from a
    test that is there, a class's or one case of a parametrised test among them, wherever
    the lines of an entry break."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_here():\n    pass\n\n\nclass TestGroup:\n    def test_in_it(self):\n"
        "        pass\n\n    def helper(self):\n        pass\n\n\ndef helper():\n    pass\n\n\n"
        "class Group:\n    def test_in_it(self):\n        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "helper.py").write_text("def test_here():\n    pass\n", "utf-8")
    gaps = (
        "- **One.** Text. Pinned by `tests/test_a.py::test_here`.\n"
        "  - Two. Pinned by `tests/test_a.py::test_here` and\n"
        "    `tests/test_a.py::test_hare`.\n"
        "  - Three. Pinned by `tests/test_a.py::TestGroup::test_in_it`,\n"
        "    `tests/test_b.py::test_here` and `tests/test_a.py::test_here[a case]`.\n"
        "- **Four.** Pinned by `test_a.py::test_here`.\n"
        "- **Five.** Pinned by test_here.\n"
        "- **Six.** Pinned by `tests/test_a.py::helper`, `tests/test_a.py::TestGroup::helper`\n"
        "  and `tests/test_a.py::Group::test_in_it`.\n"
        "- **Seven.** Pinned by `tests/helper.py::test_here`.\n"
    )
    names, garbled = pins_of(gaps)
    assert garbled == ["Pinned by test_here."]
    assert unfound(names, tmp_path) == [
        "tests/test_a.py::test_hare", "tests/test_b.py::test_here", "test_a.py::test_here",
        "tests/test_a.py::helper", "tests/test_a.py::TestGroup::helper",
        "tests/test_a.py::Group::test_in_it", "tests/helper.py::test_here",
    ]  # fmt: skip


def test_every_test_a_known_gap_is_pinned_by_is_there() -> None:
    """An open entry of DESIGN.md's Known gaps, or a point under one, that a test holds ends
    in `Pinned by` and the names of the tests that hold the limit as it is written. A test
    renamed or deleted would leave the entry trusted on the word of a test that no longer
    runs."""
    names, garbled = pins_of(open_gaps(text_of(DESIGN)))
    assert garbled == [], "a Pinned by names its tests in backticks, path::name"
    assert names, "no open entry names a test: has the form of the tag changed?"
    assert unfound(names, REPO) == []


def known_gap_items(text: str) -> list[dict[str, list]]:
    """The open entries of DESIGN.md's Known gaps as written, each with its own lines and
    its points, each point with its own lines, its points and what it goes on to say after
    them at its own indent. An entry's own lines run to its first point, past blank lines; a
    point's, and a point's point's, to the next one, a blank line or a line indented less. A
    group's paragraph and what an entry goes on to say after its points, blank line or not,
    are no item's. A line that is none of these is refused, not passed over."""
    start = text.index("\n## Known gaps\n")
    end = text.index(f"\n{CLOSED_SINCE}\n", start)
    entries: list[dict[str, list]] = []
    entry = point = part = None
    blank, paragraph = True, False
    first = text.count("\n", 0, start) + 3  # the line of the text after the heading's
    for number, line in enumerate(text[start:end].splitlines()[2:], first):
        depth = len(line) - len(line.lstrip(" "))
        marker = line[depth:].startswith("- ")
        stray = marker and (depth not in (0, 2, 4) or depth == 4 and point is None)
        if not line.strip():
            point = part = None
        elif line[depth] == "\t" or stray:
            raise ValueError(f"cannot place line {number}: {line!r}")
        elif depth == 0 and marker:
            entry, point, part, paragraph = {"own": [line], "points": []}, None, None, False
            entries.append(entry)
        elif depth == 0 and (blank or paragraph):  # a group's paragraph
            entry, point, part, paragraph = None, None, None, True
        elif entry is not None and depth == 2 and marker:
            point, part = {"own": [line], "parts": [], "after": []}, None
            entry["points"].append(point)
        elif point is not None and depth == 4 and marker:
            part = [line]
            point["parts"].append(part)
        elif part is not None and depth >= 6:
            part.append(line)
        elif point is not None and (depth == 4 or depth > 4 and not point["parts"]):
            point["after" if point["parts"] else "own"].append(line)
            part = None
        elif entry is not None and depth >= 2 and (point is None or depth == 2):
            if not entry["points"]:  # else what the entry goes on to say after its points
                entry["own"].append(line)
            point = part = None
        else:
            raise ValueError(f"cannot place line {number}: {line!r}")
        blank = not line.strip()
    return entries


def own_texts(text: str) -> list[tuple[str, str]]:
    """Each open item of DESIGN.md's Known gaps: its first line, and its own text on one
    line. The items are the entries, their points, and a point's own points where the
    point's text stops before them; where it goes on after them, what it says there ends
    its own text, and they are its parts, no items of their own (`known_gap_items`)."""
    def flat(lines: list[str]) -> str:
        return " ".join(" ".join(lines).split())

    items = []
    for entry in known_gap_items(text):
        items.append((entry["own"][0].strip(), flat(entry["own"])))
        for point in entry["points"]:
            items.append((point["own"][0].strip(), flat(point["own"] + point["after"])))
            if not point["after"]:
                items.extend((part[0].strip(), flat(part)) for part in point["parts"])
    return items


def tagged(own: str) -> bool:
    """Whether an item's own text ends in `Accepted.` or in a whole `Pinned by` tag, each
    read as a word, as `pins_of` reads the tag."""
    if re.search(r"(?<!\S)Accepted\.\Z", own):
        return True
    starts = [at.start() for at in re.finditer(r"\bPinned by\b", own)]
    pin = PINNED.match(own, starts[-1]) if starts else None
    return pin is not None and pin.end() == len(own)


def test_an_item_s_own_text_stops_at_its_first_point_or_its_paragraph() -> None:
    """An entry's lead text and each point's lines are told apart. A point's own points are
    items of their own where its text stops before them, and are covered by its tag where
    its text goes on after them. A point stops at a blank line, and neither a group's
    paragraph nor what an entry says after its points counts as an item; so a tag is looked
    for where the preamble of Known gaps says it stands, and only a whole tag counts."""
    text = (
        "# D\n\n## Known gaps\n\nWhat the tags\nmean. Accepted.\n\n"
        "- **One.** Its lead\n  text, two lines.\n\n  A second paragraph. Accepted.\n"
        "  - A point\n    of two lines. Pinned by `tests/a.py::test_a`.\n"
        "  - A point tagged before its points. Accepted.\n"
        "    - a tagged one. Accepted.\n    - an untagged one.\n"
        "  - A point with no tag:\n    - a tagged one. Accepted.\n"
        "  - A point whose text goes on:\n    - a part,\n    - another part,\n"
        "    and after them. Pinned by `tests/a.py::test_a`.\n"
        "  - A point cut\n    by a blank line.\n\n    Accepted.\n\n"
        "  - A point ended by a line indented less.\n"
        "  What the entry goes on to say. Accepted.\n\nA group,\nof two lines.\n\n"
        "- **Two.** Accepted. And more.\n"
        "- **Three.** Pinned by `tests/a.py::test_a` and\n  `tests/b.py::test_b`.\n"
        "- **Four.** Pinned by test_a.\n"
        "- **Five.** Pinned by `tests/a.py::test_a`. And more.\n"
        "- **Six.** UnPinned by `tests/a.py::test_a`.\n- **Seven.** NotAccepted.\n"
        f"\n{CLOSED_SINCE}\n\n- **Closed.**\n"
    )
    assert own_texts(text) == [
        ("- **One.** Its lead",
         "- **One.** Its lead text, two lines. A second paragraph. Accepted."),
        ("- A point", "- A point of two lines. Pinned by `tests/a.py::test_a`."),
        ("- A point tagged before its points. Accepted.",
         "- A point tagged before its points. Accepted."),
        ("- a tagged one. Accepted.", "- a tagged one. Accepted."),
        ("- an untagged one.", "- an untagged one."),
        ("- A point with no tag:", "- A point with no tag:"),
        ("- a tagged one. Accepted.", "- a tagged one. Accepted."),
        ("- A point whose text goes on:",
         "- A point whose text goes on: and after them. Pinned by `tests/a.py::test_a`."),
        ("- A point cut", "- A point cut by a blank line."),
        ("- A point ended by a line indented less.", "- A point ended by a line indented less."),
        ("- **Two.** Accepted. And more.", "- **Two.** Accepted. And more."),
        ("- **Three.** Pinned by `tests/a.py::test_a` and",
         "- **Three.** Pinned by `tests/a.py::test_a` and `tests/b.py::test_b`."),
        ("- **Four.** Pinned by test_a.", "- **Four.** Pinned by test_a."),
        ("- **Five.** Pinned by `tests/a.py::test_a`. And more.",
         "- **Five.** Pinned by `tests/a.py::test_a`. And more."),
        ("- **Six.** UnPinned by `tests/a.py::test_a`.",
         "- **Six.** UnPinned by `tests/a.py::test_a`."),
        ("- **Seven.** NotAccepted.", "- **Seven.** NotAccepted."),
    ]  # fmt: skip
    assert [tagged(own) for _, own in own_texts(text)] == [
        True, True, True, True, False, False, True, True, False, False,
        False, True, False, False, False, False,
    ]  # fmt: skip


@pytest.mark.parametrize("lines", [
    "- **A.** x.\nat the margin, straight after it. Accepted.\n",
    "- **A.** x.\n\t- a point indented by a tab. Accepted.\n",
    "- **A.** x.\n   - a point indented by three spaces. Accepted.\n",
    "- **A.** x.\n  - a point\n   that goes on at three. Accepted.\n",
    "- **A.** x.\n  - a point:\n    - and its point\n     indented by five. Accepted.\n",
    "A group.\n\n  - a point under no entry. Accepted.\n",
    "- **A.** x.\n  - a point:\n    - its point\n      - and a point of that. Accepted.\n",
    "- **A.** x, untagged\n    - a point four deep under no point. Accepted.\n",
    "- **A.** x. Accepted.\n  - a point. Accepted.\n\n    - four deep past a blank line\n",
], ids=["lazy", "tab", "three spaces", "point at three", "five spaces", "no entry",
        "six deep", "four deep", "four deep past a blank"])  # fmt: skip
def test_a_line_of_known_gaps_the_reading_cannot_place_is_refused(lines: str) -> None:
    """A line the reading of items cannot give to an item, a group's paragraph or what an
    entry says after its points fails the test that reads them, rather than being passed
    over with the tag it may hold."""
    text = f"# D\n\n## Known gaps\n\nWhat the tags mean.\n\n{lines}\n{CLOSED_SINCE}\n"
    with pytest.raises(ValueError, match="cannot place line"):
        own_texts(text)


def test_every_open_known_gap_ends_in_accepted_or_pinned_by() -> None:
    """Every open item of DESIGN.md's Known gaps (an entry, a point under one, and a point's
    point where the point's text stops before it) ends its own text in `Accepted.` (a limit
    that stays as written) or in `Pinned by` and the tests that hold it as written (Basile,
    2026-11-09; every item was sorted by 2026-11-21). An item with neither is a limit nobody
    has decided on, which is how a gate comes to be trusted beyond it."""
    untagged = [first for first, own in own_texts(text_of(DESIGN)) if not tagged(own)]
    assert not untagged, (
        "end each of these items of Known gaps in `Accepted.` or in Pinned by and the tests "
        "that hold it (DESIGN.md, the preamble of Known gaps):\n" + "\n".join(untagged)
    )


# ------------------------------------------------------------------------------ citation


def test_the_agents_file_points_to_the_rules_and_keeps_no_copy() -> None:
    """Codex and other agent tools read AGENTS.md and never see CLAUDE.md, where the rules
    are, the one about the version line among them. AGENTS.md points there; a second copy of
    the rules would go stale beside the first."""
    agents = text_of(REPO / "AGENTS.md")
    assert "](CLAUDE.md)" in agents
    assert len(agents.splitlines()) <= 12, "AGENTS.md points to CLAUDE.md; it holds no rules"


def test_the_citation_file_reads_and_names_no_version() -> None:
    """A version here would be a fifth place for the release number, outside the four that
    `tests/test_version.py` holds equal, and so the one that goes stale."""
    import yaml

    citation = yaml.safe_load((REPO / "CITATION.cff").read_text(encoding="utf-8"))
    for key in ("cff-version", "message", "title", "authors"):
        assert citation.get(key), f"CITATION.cff has no {key}"
    assert "version" not in citation
    assert "CITATION.cff" in text_of(README)


def _folded(text: str) -> str:
    """A YAML block scalar and a JSON string compare equal once the line breaks are spaces."""
    return " ".join(text.split())


def test_the_zenodo_file_says_what_the_citation_file_says() -> None:
    """Zenodo's GitHub integration reads `.zenodo.json` for each release. It repeats what
    CITATION.cff says, and the two are held equal so that neither is edited alone. It names no
    version and no date: Zenodo takes both from the release."""
    import json

    import yaml

    citation = yaml.safe_load((REPO / "CITATION.cff").read_text(encoding="utf-8"))
    record = json.loads((REPO / ".zenodo.json").read_text(encoding="utf-8"))
    assert record["upload_type"] == "software"
    assert record["title"] == citation["title"]
    assert _folded(record["description"]) == _folded(citation["abstract"])
    assert record["keywords"] == citation["keywords"]
    # Zenodo names licences by their SPDX identifier in small letters.
    assert record["license"] == citation["license"].lower()
    people = [
        (f"{who['family-names']}, {who['given-names']}", who["orcid"].rsplit("/", 1)[-1],
         _folded(who["affiliation"]))
        for who in citation["authors"]
    ]  # fmt: skip
    assert [
        (who["name"], who["orcid"], _folded(who["affiliation"])) for who in record["creators"]
    ] == people
    assert "version" not in record and "publication_date" not in record
    assert record["related_identifiers"] == [
        {"identifier": citation["repository-code"], "relation": "isSupplementTo",
         "resource_type": "software", "scheme": "url"}
    ]  # fmt: skip


def test_the_funding_file_leads_to_the_funding_page() -> None:
    """GitHub's Sponsor button reads `.github/FUNDING.yml`; its link to the page in the
    repository has to name a page that is there."""
    import yaml

    funding = yaml.safe_load((REPO / ".github" / "FUNDING.yml").read_text(encoding="utf-8"))
    assert funding["github"] == ["BasileChretien"]
    citation = yaml.safe_load((REPO / "CITATION.cff").read_text(encoding="utf-8"))
    page = (DOCS / "funding.md").resolve()
    assert page.exists()
    assert funding["custom"] == [f"{citation['repository-code']}/blob/main/docs/funding.md"]


# ----------------------------------------------------------------------------------- PyPI

#: A target that leads somewhere from any page: it names a scheme, or a place on the page.
ABSOLUTE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:|#")
#: The forms read, beside the two the build rewrites, which are `](target)` and one `src` or
#: `srcset`: a link that carries a title; one written as a reference, with its target on the
#: line of its label (a footnote opens the same way and has no target); an `href`; and each
#: picture of a `srcset` after the first. An attribute is read as the README writes one, in
#: lower case and between double quotes: in single quotes, in capitals or with no quotes it
#: is not seen here, and the build does not rewrite it either.
TITLED = re.compile(r"\]\(\s*<?([^)\s>]+)")
DEFINED = re.compile(r"^ {0,3}\[(?!\^)[^\]\n]+\]:[ \t]*<?([^\s>]+)", re.MULTILINE)
ATTRIBUTE = re.compile(r'(?<![\w-])(?:href|src)="([^"]*)"')
SET = re.compile(r'(?<![\w-])srcset="([^"]*)"')
#: Text shown as code within a line: between two runs of backticks of one length.
CODE = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)")


def relative_targets(markdown: str) -> list[str]:
    """Each target in the text, in the forms read above, that is dead on a page with nothing
    beside it. What is shown as code is no target."""
    text = CODE.sub("", FENCE.sub("", markdown))
    pictures = [one.split() for found in SET.findall(text) for one in found.split(",")]
    several = [picture[0] for picture in pictures if picture]
    targets = TITLED.findall(text) + DEFINED.findall(text) + ATTRIBUTE.findall(text) + several
    return [target for target in targets if not ABSOLUTE.match(target)]


@pytest.mark.parametrize(
    ("markdown", "dead"),
    [
        ("see [the page](docs/install.md).", ["docs/install.md"]),
        ('see [the page](docs/install.md "Installing").', ["docs/install.md"]),
        ("see [the page][install].\n\n[install]: docs/install.md\n", ["docs/install.md"]),
        ('<a href="docs/install.md">the page</a>', ["docs/install.md"]),
        ('<img src="docs/img/loop-light.svg" alt="">', ["docs/img/loop-light.svg"]),
        (
            '<source srcset="https://example.org/a.svg 1x, docs/img/b.svg 2x">',
            ["docs/img/b.svg"],
        ),
        ("[a](https://example.org/x), [b](#status), [c](mailto:someone@example.org)", []),
        ('[a]: https://example.org/x\n<a href="#status">b</a>', []),
        ("```\n[in a listing](docs/install.md)\n```\n", []),
        # What is no target, and stood to fail the test of the description: a footnote, whose
        # line opens as a reference's does, and a link shown as code.
        ("A claim.[^1]\n\n[^1]: See the design notes.\n", []),
        ('A link with a title is written `[text](file.md "Title")`.', []),
        ("In two backticks, ``[text](file.md) and a ` too``, it is code as well.", []),
        ('<img data-src="lazy.png" src="https://example.org/a.png">', []),
    ],
)
def test_a_relative_target_is_found_in_each_form_read(markdown: str, dead: list[str]) -> None:
    assert relative_targets(markdown) == dead


def test_the_description_pypi_shows_has_no_link_that_leads_nowhere(tmp_path: Path) -> None:
    """PyPI shows the README on a page with nothing beside it, so a relative link or picture
    is dead there. The build points each at the repository, at the tag of the version built.
    Built with the hatchling and the plugin that are installed, so it needs no network."""
    import subprocess
    import sys
    import zipfile

    pytest.importorskip("hatchling")
    pytest.importorskip("hatch_fancy_pypi_readme")
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(REPO), "--no-deps", "--no-build-isolation",
         "-q", "-w", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert built.returncode == 0, built.stdout + built.stderr
    (wheel,) = tmp_path.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        (name,) = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        metadata = archive.read(name).decode("utf-8")
    header, _, description = metadata.partition("\n\n")
    assert "Description-Content-Type: text/markdown" in header
    version = re.search(r"^Version: (\S+)$", header, re.MULTILINE).group(1)

    # What each target of the README has to have become: one that names a scheme, or a place
    # on the page itself, as it was; a relative one, the same path in the repository at the
    # release's tag, as a page for a link and as the file for a picture.
    page = f"https://github.com/BasileChretien/manuscript-guard/blob/v{version}/"
    file = f"https://raw.githubusercontent.com/BasileChretien/manuscript-guard/v{version}/"

    def becomes(target: str, at: str) -> str:
        return target if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:|#", target) else at + target

    in_readme = FENCE.sub("", text_of(README))
    in_description = FENCE.sub("", description)
    links, pictures = LINK.findall(in_readme), SOURCE.findall(in_readme)
    assert any(not re.match(r"[a-z]+:|#", link) for link in links), "no relative link to test"
    assert pictures, "the README shows no picture; the pattern no longer matches"
    assert LINK.findall(in_description) == [becomes(link, page) for link in links]
    assert SOURCE.findall(in_description) == [becomes(picture, file) for picture in pictures]
    # The build rewrites two forms and sees no other, so a target written any other way
    # arrives as it was: one that is relative fails here, and has to be written out in full.
    assert relative_targets(description) == []


#: The documents that sum up which guidelines bar commercial use.
LICENCE_SUMMARIES = [
    REPO / "ATTRIBUTION.md",
    REPO / "docs" / "principles.md",
    REPO / "plugin" / "skills" / "reporting-checklist" / "SKILL.md",
]
#: Counts in words, as a licence summary may give them.
COUNT_WORDS = {"one": 1, "two": 2, "both": 2, "three": 3, "four": 4, "five": 5, "six": 6}
#: How a licence that bars commercial use begins, in a recipe or in a cell of ATTRIBUTION.md's
#: table, bold or not. What follows may mention other copies under other licences.
NON_COMMERCIAL = re.compile(
    r"(?i)[*\s]*(?:CC BY-NC|Creative Commons Attribution[- ]Non[- ]?Commercial)"
)


def is_non_commercial(licence: str) -> bool:
    """Whether a recipe's licence, or a licence cell of ATTRIBUTION.md's table, bars
    commercial use, read from its leading term."""
    return bool(NON_COMMERCIAL.match(licence))


def non_commercial_rows(attribution: str) -> list[str]:
    """The guidelines that the table under ATTRIBUTION.md's "Licence findings" gives a
    non-commercial licence."""
    section = attribution.split("## Licence findings", 1)[1].split("\n## ", 1)[0]
    return [
        name
        for name, cell in re.findall(r"(?m)^\| ([^|]+?) \| ([^|]*)", section)
        if is_non_commercial(cell)
    ]


def is_covered(recipe: str, rows: list[str]) -> bool:
    """Whether a recipe is the guideline of one of the rows, or a variant named after it
    (READUS-PV-abstracts after READUS-PV)."""
    names = [row.replace(" ", "-") for row in rows]
    return any(recipe == name or recipe.startswith(name + "-") for name in names)


def summary_problems(text: str, rows: list[str]) -> list[str]:
    """What a document's summary of the non-commercial licences gets wrong. Each sentence
    outside a table that speaks of non-commercial use, in any spelling, names every guideline
    of the rows, and a count in words that it gives is theirs."""
    sentences = [
        sentence
        for paragraph in re.split(r"\n\s*\n", text)
        if not paragraph.lstrip().startswith("|")
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", " ".join(paragraph.split()))
        if re.search(r"(?i)\bnon[- ]?commercial", sentence)
    ]
    if not sentences:
        return ["no summary of the non-commercial licences"]
    problems = []
    for sentence in sentences:
        problems += [f"does not name {row}: {sentence}" for row in rows if row not in sentence]
        problems += [
            f"says {word}, not {len(rows)}: {sentence}"
            for word in re.findall(r"(?i)\b(" + "|".join(COUNT_WORDS) + r")\b", sentence)
            if COUNT_WORDS[word.lower()] != len(rows)
        ]
    return problems


TWO = ["READUS-PV", "CARE 2013"]
THREE = ["READUS-PV", "CARE 2013", "MDAR"]


@pytest.mark.parametrize(
    ("text", "rows", "wrong"),
    [
        ("Two of them, READUS-PV and CARE 2013, are non-commercial.", TWO, False),
        ("Both, READUS-PV and CARE 2013, are non-commercial.", TWO, False),
        ("NON-COMMERCIAL: READUS-PV and CARE 2013. See the table.", TWO, False),
        # Round 2 of #845: a summary in another spelling was not read, nor a count written
        # other than as "two of", and a count elsewhere in the paragraph was.
        ("READUS-PV and CARE 2013 are non-commercial.\n\nNoncommercial: READUS-PV.", TWO, True),
        ("Non-commercial: READUS-PV.\n\nREADUS-PV and CARE 2013 are non-commercial.", TWO, True),
        ("The two below, READUS-PV, CARE 2013 and MDAR, are non-commercial.", THREE, True),
        ("Three guidelines, READUS-PV and CARE 2013, are non-commercial.", TWO, True),
        ("One of the sites was down. READUS-PV and CARE 2013 are non-commercial.", TWO, False),
        ("| READUS-PV | **CC BY-NC** - non-commercial |\n\nREADUS-PV and CARE 2013 are "
         "non-commercial.", TWO, False),
    ],
)  # fmt: skip
def test_a_licence_summary_is_read_in_every_spelling_and_count(
    text: str, rows: list[str], wrong: bool
) -> None:
    assert bool(summary_problems(text, rows)) is wrong, summary_problems(text, rows)


@pytest.mark.parametrize(
    ("licence", "restricted"),
    [
        ("CC BY-NC-ND 3.0, non-commercial and no derivatives", True),
        ("CC BY-NC, see the READUS-PV recipe", True),
        ("Creative Commons Attribution-NonCommercial 4.0 International", True),
        # Round 2 of #845: a CC BY licence that mentions a CC BY-NC copy is CC BY.
        ("CC BY 4.0, via The BMJ's copy. One copy is CC BY-NC.", False),
        ("NOT STATED for this PDF", False),
    ],
)
def test_a_licence_is_non_commercial_by_its_leading_term(licence: str, restricted: bool) -> None:
    assert is_non_commercial(licence) is restricted


def test_a_row_covers_its_guideline_and_its_variants_only() -> None:
    """Round 2 of #845: a row named "TRIPOD" covered "TRIPOD+AI"."""
    assert is_covered("CARE-2013", ["CARE 2013"])
    assert is_covered("READUS-PV-abstracts", ["READUS-PV"])
    assert not is_covered("TRIPOD+AI", ["TRIPOD"])
    assert not is_covered("READUS-PVX", ["READUS-PV"])


def test_the_licence_summaries_name_every_non_commercial_guideline() -> None:
    """Round 1 of #845: CARE 2013 shipped under CC BY-NC-ND as a second non-commercial
    guideline, and ATTRIBUTION.md, docs/principles.md and the reporting-checklist skill still
    said there was one, READUS-PV. Every shipped recipe with a non-commercial licence has its
    row in ATTRIBUTION.md's table, and each summary names every such row."""
    from manuscript_guard.paths import SHIPPED_RECIPES
    from manuscript_guard.reporting import load_recipe

    rows = non_commercial_rows(text_of(REPO / "ATTRIBUTION.md"))
    restricted = [
        path.name.split(".recipe")[0]
        for path in sorted(SHIPPED_RECIPES.glob("*.recipe.yaml"))
        if is_non_commercial(load_recipe(path)[1]["licence"])
    ]
    assert restricted, "no shipped recipe is non-commercial; the test reads nothing"
    assert [name for name in restricted if not is_covered(name, rows)] == []
    for path in LICENCE_SUMMARIES:
        assert summary_problems(text_of(path), rows) == [], path.name


# ------------------------------------------------------------- the recipes the pages list

#: The pages that list the shipped recipes or count them, each read as it writes them.
RECIPE_PAGES = {
    "skill": REPO / "plugin" / "skills" / "reporting-checklist" / "SKILL.md",
    "guidelines": DOCS / "guidelines.md",
    "attribution": REPO / "ATTRIBUTION.md",
    "principles": DOCS / "principles.md",
}
#: Each count of them, with the page it is on and the recipes it counts.
RECIPE_COUNTS = (
    ("attribution", r"\bAll ([a-z-]+) recipes\b", "all"),
    ("principles", r"\bRecipes ship for ([a-z-]+) checklists\b", "checklists"),
)


def shipped_recipes() -> dict[str, str]:
    """Each shipped recipe's name, with the format it reads its document in."""
    from manuscript_guard.paths import SHIPPED_RECIPES
    from manuscript_guard.reporting import load_recipe

    found = {}
    for path in sorted(SHIPPED_RECIPES.glob("*.recipe.yaml")):
        _recipe, meta = load_recipe(path)
        found[meta["name"]] = meta["_layout"].get("format") or "docx-table"
    return found


def table_recipes(guidelines: str) -> list[str]:
    """The recipes the first column of docs/guidelines.md's Reporting checklists table
    names, several to a cell, each without the year some carry: "CONSORT (2025)"."""
    table = guidelines.split("\n## Reporting checklists\n", 1)[-1].split("\n\n```", 1)[0]
    cells = re.findall(r"^\| ([^|]+?) \|", table, re.MULTILINE)
    return [re.sub(r"\s*\([^()]*\)$", "", name)
            for cell in cells if cell != "Recipe" for name in cell.split(", ")]  # fmt: skip


def recipe_problems(pages: dict[str, str], recipes: dict[str, str]) -> list[str]:
    """What the pages say of the recipes that the recipes are not: the skill's list of their
    names, the names of docs/guidelines.md's table, the count of all of them in
    ATTRIBUTION.md, and in docs/principles.md the count of the checklists, the recipes that
    are not a rating scale."""
    words = {figures_script().in_words(number): number for number in range(100)}
    counts = {"all": len(recipes),
              "checklists": sum(kind != "pdf-scale" for kind in recipes.values())}  # fmt: skip
    problems = []

    def against(where: str, named: list[str]) -> None:
        problems.extend(f"{where} does not name {name}"
                        for name in sorted(set(recipes) - set(named)))  # fmt: skip
        problems.extend(f"{where} names {name}, which no recipe is"
                        for name in sorted(set(named) - set(recipes)))  # fmt: skip

    listed = re.search(r"Recipes ship for (.+?)\. Name", " ".join(pages["skill"].split()))
    against("the skill", [] if listed is None else
            [name for part in listed.group(1).split(", ") for name in part.split(" and ")])
    against("docs/guidelines.md", table_recipes(pages["guidelines"]))
    for page, pattern, counted in RECIPE_COUNTS:
        said = re.search(pattern, " ".join(pages[page].split()))
        if said is None:
            problems.append(f"{page} no longer counts them as {pattern!r} reads")
        elif words.get(said.group(1)) != counts[counted]:
            problems.append(f"{page} says {said.group(1)}; there are {counts[counted]}")
    return problems


def test_the_pages_name_and_count_the_recipes_that_ship() -> None:
    """Round 1 of #851: PROCESS 2023 was added by hand to each list and count of the
    recipes, with nothing to fail where one was left out, as the licence summaries have."""
    recipes = shipped_recipes()
    assert "PROCESS-2023" in recipes and recipes["SANRA"] == "pdf-scale", recipes
    pages = {name: text_of(path) for name, path in RECIPE_PAGES.items()}
    assert recipe_problems(pages, recipes) == []


def test_a_page_that_leaves_a_recipe_out_or_miscounts_them_is_told_so() -> None:
    """Each of the four is read: a name left out of the skill's list and of the table, and a
    count one short on each page, is a problem each."""
    recipes = shipped_recipes()
    pages = {name: text_of(path) for name, path in RECIPE_PAGES.items()}
    words = [figures_script().in_words(number) for number in range(100)]
    every = len(recipes)
    checklists = sum(kind != "pdf-scale" for kind in recipes.values())
    stale = {
        "skill": pages["skill"].replace("PROCESS-2023, ", ""),
        "guidelines": pages["guidelines"].replace("| PROCESS-2023 | case series in surgery |\n",
                                                  ""),
        "attribution": pages["attribution"].replace(f"All {words[every]} recipes",
                                                    f"All {words[every - 1]} recipes"),
        "principles": pages["principles"].replace(f"ship for {words[checklists]} checklists",
                                                  f"ship for {words[checklists - 1]} checklists"),
    }  # fmt: skip
    assert all(stale[name] != pages[name] for name in pages), "a page no longer reads as written"
    assert recipe_problems(stale, recipes) == [
        "the skill does not name PROCESS-2023",
        "docs/guidelines.md does not name PROCESS-2023",
        f"attribution says {words[every - 1]}; there are {every}",
        f"principles says {words[checklists - 1]}; there are {checklists}",
    ]
