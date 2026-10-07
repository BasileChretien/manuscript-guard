"""The README and the pages under docs/ are held to the tool they describe.

The README is the first thing a reader meets and the last thing anyone re-reads after a
change. Its tables say which commands and gates exist, its links lead to the pages the long
sections were moved to, and its two pictures quote what `check` prints. Each of those is a
claim, so each is compared here with the thing it is a claim about.
"""

from __future__ import annotations

import argparse
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
PAGES = [README, *sorted(DOCS.glob("*.md"))]

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


def section(name: str) -> str:
    """One `## ` section of the README, without its heading."""
    readme = text_of(README)
    assert f"\n## {name}\n" in readme, f"the README has no section {name!r}"
    return readme.split(f"\n## {name}\n", 1)[1].split("\n## ", 1)[0]


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


def test_the_readme_lists_the_commands_the_tool_has() -> None:
    """`hook` is left out on purpose: an agent tool calls it, an author never does."""
    choices = next(
        action.choices
        for action in build_parser()._actions  # noqa: SLF001 - argparse offers no other way
        if isinstance(action, argparse._SubParsersAction)  # noqa: SLF001
    )
    assert set(first_cells(section("Commands"), "`([a-z-]+)`")) == set(choices) - {"hook"}


def test_the_readme_lists_the_gates_the_tool_has() -> None:
    declared = set()
    for module in pkgutil.iter_modules(manuscript_guard.gates.__path__):
        gate = getattr(
            importlib.import_module(f"manuscript_guard.gates.{module.name}"), "GATE", None
        )
        if gate:
            declared.add(gate)
    listed = first_cells(section("What is checked"), r"(G\d+)")
    assert len(listed) == len(set(listed)), "a gate is listed twice"
    assert set(listed) == declared


# ------------------------------------------------------------------------------ pictures


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
    committed = {path.name for path in (DOCS / "img").glob("*.svg")}
    assert committed == set(drawn)
    for name, text in drawn.items():
        on_disk = (DOCS / "img" / name).read_text(encoding="utf-8")
        assert on_disk == text, f"docs/img/{name} is stale: run python tools/readme_figures.py"
    for name in drawn:
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


def test_the_readme_quotes_what_check_says_of_an_edited_results_file(
    project: Path, capsys
) -> None:
    block = re.search(r"changed by hand:\n\n```text\n(.*?)```", text_of(README), re.DOTALL)
    assert block, "the README no longer quotes that finding"
    results = project / "results" / "01_disproportionality.json"
    text = results.read_text(encoding="utf-8")
    assert '"value": 4000' in text
    results.write_text(text.replace('"value": 4000', '"value": 4100', 1), encoding="utf-8")

    assert main(["check", str(project)]) == 1
    printed = said(capsys.readouterr().out)

    for line in block.group(1).splitlines():
        assert said(line) in printed, f"check no longer prints: {line.strip()}"


# ------------------------------------------------------------------------------ citation


def test_the_citation_file_reads_and_names_no_version() -> None:
    """A version here would be a fifth place for the release number, outside the four that
    `tests/test_version.py` holds equal, and so the one that goes stale."""
    import yaml

    citation = yaml.safe_load((REPO / "CITATION.cff").read_text(encoding="utf-8"))
    for key in ("cff-version", "message", "title", "authors"):
        assert citation.get(key), f"CITATION.cff has no {key}"
    assert "version" not in citation
    assert "CITATION.cff" in text_of(README)
