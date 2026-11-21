"""Draw the feature map from its source, docs/features.yaml.

    python tools/feature_map.py      # writes docs/features.md and docs/img/features-*.svg

The source lists what the package is meant to do, one entry for each thing it promises, by
the stage of a paper's life it belongs to. This draws two things from it: a page that lists
each entry with what does it and the tests that prove it, and a picture of the stages with
their entries in them, for a light and a dark page. The files are committed, and
`tests/test_features.py` fails while they differ from what this draws, as it fails when an
entry names a command, a gate, a skill, a hook or a test that is not there, or when one of
them is in no entry.

Run it after editing docs/features.yaml, and commit what it writes. It needs
`manuscript_guard` importable, for the groups the commands are listed in.
"""

from __future__ import annotations

import functools
import importlib.util
import posixpath
import re
import textwrap
from html import escape
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "docs" / "features.yaml"
PAGE = "docs/features.md"
PICTURE = "docs/img/features-{}.svg"

#: How a status is said in the page and in the picture's legend.
STATUS_WORDS = {"works": "works", "partial": "works in part", "planned": "planned"}
#: The longest title the picture has room for, in a font a quarter wider than Segoe UI.
TITLE_ROOM = 30

#: The colour of an entry that works only in part: GitHub's own "attention" colours.
ATTENTION = {"light": "#9a6700", "dark": "#d29922"}

WIDTH = 880
MARGIN = 20
GAP = 20
COLUMNS = 3
CARD = (WIDTH - 2 * MARGIN - (COLUMNS - 1) * GAP) // COLUMNS
ROW = 26
PILL = 21


@functools.cache
def _figures():
    """The README's figure script, for its palettes and its fonts: one look for both."""
    spec = importlib.util.spec_from_file_location(
        "readme_figures", Path(__file__).with_name("readme_figures.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load(path: Path = SOURCE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def by_stage(source: dict) -> list[tuple[dict, list[dict]]]:
    """Each stage with its entries, in the order the file gives both."""
    return [
        (stage, [entry for entry in source["features"] if entry["stage"] == stage["id"]])
        for stage in source["stages"]
    ]


def counts(source: dict) -> dict[str, int]:
    found = dict.fromkeys(STATUS_WORDS, 0)
    for entry in source["features"]:
        found[entry["status"]] += 1
    return found


def _work(number: int) -> str:
    return "works" if number == 1 else "work"


# ------------------------------------------------------------------------------ the page


def _from_page(target: str) -> str:
    """A path from the repository's root, as a link from a page under docs/."""
    file, _, fragment = target.partition("#")
    link = posixpath.relpath(file, "docs")
    return f"{link}#{fragment}" if fragment else link


def anchor(heading: str) -> str:
    """The anchor GitHub gives a heading: lower case, punctuation gone, spaces to hyphens."""
    kept = re.sub(r"[^\w\- ]", "", heading.replace("`", "").lower())
    return kept.replace(" ", "-")


def _command_groups() -> dict[str, str]:
    """Each command's group on docs/commands.md, as the anchor that leads to it."""
    from manuscript_guard.cli import COMMAND_GROUPS

    return {name: anchor(heading) for heading, names in COMMAND_GROUPS for name in names}


def _done_by(entry: dict, groups: dict[str, str]) -> str:
    parts = [f"[`{name}`](commands.md#{groups[name]})" for name in entry.get("commands", ())]
    parts += [f"[{gate}](gates.md)" for gate in entry.get("gates", ())]
    parts += [f"skill [`{name}`](agent-tools.md)" for name in entry.get("skills", ())]
    parts += [f"hook `{name}`" for name in entry.get("hooks", ())]
    return ", ".join(parts) or "&mdash;"


def _proved_by(entry: dict) -> str:
    shown = []
    for test in entry.get("tests", ()):
        file, _, name = test.partition("::")
        label = Path(file).name + (f"::{name}" if name else "")
        shown.append(f"[`{label}`]({_from_page(file)})")
    return "<br>".join(shown) or "&mdash;"


def _row(entry: dict, groups: dict[str, str]) -> str:
    title = entry["title"]
    if "docs" in entry:
        title = f"[{title}]({_from_page(entry['docs'])})"
    says = " ".join(entry["says"].split())
    if "limits" in entry:
        says += f" *{' '.join(entry['limits'].split())}*"
    cells = [f"**{title}**", says, STATUS_WORDS[entry["status"]], _done_by(entry, groups),
             _proved_by(entry)]  # fmt: skip
    return "| " + " | ".join(cells) + " |"


def alt_text(source: dict) -> str:
    found = counts(source)
    stages = ", ".join(stage["title"] for stage in source["stages"])
    return (
        f"The stages of a paper, and other people's papers beside them ({stages}), each "
        f"with the features that belong to it: {found['works']} {_work(found['works'])}, "
        f"{found['partial']} {_work(found['partial'])} in part and {found['planned']} "
        "are planned."
    )


def page(source: dict) -> str:
    groups = _command_groups()
    found = counts(source)
    lines = [
        "# Features",
        "",
        "<!-- Drawn by tools/feature_map.py from docs/features.yaml: edit that file and run",
        "     the script, never this page. -->",
        "",
        "Everything manuscript-guard is meant to do, by the stage of a paper it belongs to:",
        "one entry for each thing it promises, what does it, and the tests that prove it.",
        f"Of the {len(source['features'])} entries, {found['works']} {_work(found['works'])}, "
        f"{found['partial']} {_work(found['partial'])} in part, and {found['planned']} are "
        "planned.",
        "",
        "The source is [features.yaml](features.yaml), which an agent tool reads before it",
        "changes a feature. `python tools/feature_map.py` draws this page and its picture from",
        "it, and `tests/test_features.py` holds them to the package: every command, gate,",
        "skill and hook is in an entry, and every test an entry names is there.",
        "",
        "<picture>",
        '  <source media="(prefers-color-scheme: dark)" srcset="img/features-dark.svg">',
        f'  <img src="img/features-light.svg" width="{WIDTH}"',
        f'       alt="{escape(alt_text(source), quote=False)}">',
        "</picture>",
    ]
    for stage, entries in by_stage(source):
        lines += ["", f"## {stage['title']}", "", " ".join(stage["says"].split()), "",
                  "| Feature | What it does | Status | Done by | Proved by |",
                  "|---|---|---|---|---|",
                  *(_row(entry, groups) for entry in entries)]  # fmt: skip
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- the picture


def _marker(x: float, y: float, status: str, colour: str, page_colour: str) -> str:
    """A full disc for an entry that works, a half one for one in part, a ring for one
    planned: told apart by shape, not by colour alone."""
    ring = (f'<circle cx="{x}" cy="{y}" r="4.5" fill="{page_colour}" stroke="{colour}" '
            'stroke-width="1.5"/>')  # fmt: skip
    if status == "works":
        return f'<circle cx="{x}" cy="{y}" r="4.5" fill="{colour}"/>'
    if status == "partial":
        half = f'<path d="M {x} {y - 4.5} A 4.5 4.5 0 0 0 {x} {y + 4.5} Z" fill="{colour}"/>'
        return ring + half
    return ring


def _colour(status: str, palette: dict[str, str], name: str) -> str:
    return {"works": palette["ok"], "partial": ATTENTION[name], "planned": palette["soft"]}[status]


def _pill(entry: dict, x: float, y: float, palette: dict[str, str], name: str) -> str:
    status = entry["status"]
    colour = _colour(status, palette, name)
    stroke = palette["line"] if status == "works" else colour
    dash = ' stroke-dasharray="4 3"' if status == "planned" else ""
    text = palette["soft"] if status == "planned" else palette["text"]
    return (
        f'  <rect x="{x}" y="{y}" width="{CARD - 16}" height="{PILL}" rx="5" '
        f'fill="{palette["page"]}" stroke="{stroke}" stroke-width="1"{dash}/>\n'
        f"  {_marker(x + 12, y + PILL / 2, status, colour, palette['page'])}\n"
        f'  <text x="{x + 24}" y="{y + 15}" font-size="12" fill="{text}">'
        f"{escape(entry['title'])}</text>"
    )


def _header_lines(stage: dict) -> list[str]:
    return textwrap.wrap(" ".join(stage["says"].split()), width=42)


def _card(number: int | None, stage: dict, entries: list[dict], x: float, y: float,
          height: float, palette: dict[str, str], name: str) -> list[str]:  # fmt: skip
    title = f"{number} &#183; {escape(stage['title'])}" if number else escape(stage["title"])
    parts = [
        f'  <rect x="{x}" y="{y}" width="{CARD}" height="{height}" rx="8" '
        f'fill="{palette["box"]}" stroke="{palette["line"]}" stroke-width="1.5"/>',
        f'  <text x="{x + 12}" y="{y + 24}" font-size="15" font-weight="600" '
        f'fill="{palette["text"]}">{title}</text>',
    ]
    lines = _header_lines(stage)
    for index, line in enumerate(lines):
        parts.append(f'  <text x="{x + 12}" y="{y + 42 + 15 * index}" font-size="11.5" '
                     f'fill="{palette["soft"]}">{escape(line)}</text>')  # fmt: skip
    top = y + 42 + 15 * len(lines)
    parts += [_pill(entry, x + 8, top + ROW * index, palette, name)
              for index, entry in enumerate(entries)]  # fmt: skip
    return parts


def _card_height(stage: dict, entries: list[dict]) -> float:
    return 42 + 15 * len(_header_lines(stage)) + ROW * len(entries) + 6


def _legend(palette: dict[str, str], name: str, found: dict[str, int]) -> list[str]:
    parts, x = [], MARGIN
    for status, words in STATUS_WORDS.items():
        colour = _colour(status, palette, name)
        parts.append(f"  {_marker(x + 5, 22, status, colour, palette['page'])}")
        label = f"{words} ({found[status]})"
        parts.append(f'  <text x="{x + 16}" y="26" font-size="12.5" '
                     f'fill="{palette["soft"]}">{escape(label)}</text>')  # fmt: skip
        x += 30 + 7 * len(label)
    return parts


def picture(source: dict, name: str) -> str:
    palette = _figures().PALETTES[name]
    stages = by_stage(source)
    rows = [stages[start:start + COLUMNS] for start in range(0, len(stages), COLUMNS)]
    body, y = [], 44
    numbered = len(stages) - 1  # the last stage stands beside the others, unnumbered
    for row_index, row in enumerate(rows):
        height = max(_card_height(stage, entries) for stage, entries in row)
        for column, (stage, entries) in enumerate(row):
            index = row_index * COLUMNS + column
            number = index + 1 if index < numbered else None
            x = MARGIN + column * (CARD + GAP)
            body += _card(number, stage, entries, x, y, height, palette, name)
        y += height + GAP
    height = y - GAP + MARGIN
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
        f'width="{WIDTH}" height="{height}" role="img" font-family="{_figures().SANS}">',
        f"  <title>{escape(alt_text(source), quote=False)}</title>",
        f'  <rect width="{WIDTH}" height="{height}" fill="{palette["page"]}"/>',
        *_legend(palette, name, counts(source)),
        *body,
        "</svg>",
        "",
    ])


def drawn(source: dict | None = None) -> dict[str, str]:
    """Every file this writes, by its path from the repository's root."""
    source = source or load()
    files = {PAGE: page(source)}
    for name in _figures().PALETTES:
        files[PICTURE.format(name)] = picture(source, name)
    return files


def main() -> None:
    for path, text in drawn().items():
        (REPO / path).write_bytes(text.encode("utf-8"))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
