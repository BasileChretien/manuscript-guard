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
    (pytest's defaults, which pyproject.toml keeps). A helper is no test."""
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
    """Each name that is not a test there is: a file under `tests/`, `::`, and a function
    of it, less a parametrised case's `[...]`."""
    known: dict[Path, set[str]] = {}
    missing = []
    for name in names:
        path, _, test = name.partition("::")
        file = repo / path
        if path.startswith("tests/") and path.endswith(".py") and file.is_file():
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
    )
    names, garbled = pins_of(gaps)
    assert garbled == ["Pinned by test_here."]
    assert unfound(names, tmp_path) == [
        "tests/test_a.py::test_hare", "tests/test_b.py::test_here", "test_a.py::test_here",
        "tests/test_a.py::helper", "tests/test_a.py::TestGroup::helper",
        "tests/test_a.py::Group::test_in_it",
    ]  # fmt: skip


def test_every_test_a_known_gap_is_pinned_by_is_there() -> None:
    """An open entry of DESIGN.md's Known gaps, or a point under one, that a test holds ends
    in `Pinned by` and the names of the tests that hold the limit as it is written. A test
    renamed or deleted would leave the entry trusted on the word of a test that no longer
    runs. That every entry ends in this or in `Accepted.` is not held yet: the triage of
    2026-11-09 tags them a group at a time."""
    names, garbled = pins_of(open_gaps(text_of(DESIGN)))
    assert garbled == [], "a Pinned by names its tests in backticks, path::name"
    assert names, "no open entry names a test: has the form of the tag changed?"
    assert unfound(names, REPO) == []


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
