"""Draw the two pictures the README shows, each for a light and a dark page.

    python tools/readme_figures.py            # writes docs/img/*.svg

`loop` is the path a number takes from the analysis to the document. `check` is what the
command prints when a number has been typed into the manuscript by hand: `CARD` below holds
that text as `manuscript-guard check` printed it on the worked example, and
`tests/test_docs.py` runs the same edit and fails if the tool no longer says it. The paths
are written with forward slashes, as on Linux and macOS; Windows prints backslashes.

The files are committed. Run this after changing `CARD`, a palette or a drawing, and commit
what it writes: the same test fails while the two differ.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "img"

#: Colours for a white page and for a dark one, close to those GitHub itself uses, so the
#: pictures sit in the page rather than on it.
PALETTES = {
    "light": {
        "page": "#ffffff", "box": "#f6f8fa", "line": "#d0d7de", "text": "#1f2328",
        "soft": "#59636e", "accent": "#0969da", "accent_box": "#ddf4ff",
        "fail": "#cf222e", "terminal": "#f6f8fa", "prompt": "#1a7f37",
    },
    "dark": {
        "page": "#0d1117", "box": "#161b22", "line": "#3d444d", "text": "#f0f6fc",
        "soft": "#9198a1", "accent": "#4493f8", "accent_box": "#121d2f",
        "fail": "#f85149", "terminal": "#161b22", "prompt": "#3fb950",
    },
}

SANS = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"

#: What `check` prints on the worked example once the first `{{results.cohort.n_reports}}`
#: of manuscript/main.md has been replaced by the typed number `4,000`. One entry a line:
#: how it is coloured, then the text. The hint is one line of the output, broken here where
#: a terminal 88 columns wide would break it. The warnings that follow it are left out.
CARD: list[tuple[str, str]] = [
    ("prompt", "$ manuscript-guard check"),
    ("text", "stage: drafting (writing the manuscript against results that exist)"),
    ("fail", "  [FAIL] G2 manuscript/main.md:11:17"),
    ("text", "         '4,000' is not bound to any source"),
    ("soft", "         > **Results.** Of 4,000 reports, {{results.case.n_cases}} described"),
    ("soft", "         hint: bind it with {{results.<key>}} or {{lit.<key>}}; if it is a writing"),
    ("soft", "         convention, add it to `conventions:` in paper.yaml with a justification"),
    ("soft", "  ..."),
]


def card_svg(palette: dict[str, str]) -> str:
    """The terminal picture."""
    width, pad, top, step = 860, 22, 46, 21
    height = top + step * len(CARD) + pad - 6
    rows = []
    for number, (kind, line) in enumerate(CARD):
        weight = ' font-weight="600"' if kind in ("fail", "prompt") else ""
        rows.append(
            f'  <text x="{pad}" y="{top + step * number + 14}" fill="{palette[kind]}"{weight} '
            f'xml:space="preserve">{escape(line)}</text>'
        )
    dots = "".join(
        f'<circle cx="{pad + 8 + 18 * n}" cy="20" r="5.5" fill="{palette["line"]}"/>'
        for n in range(3)
    )
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" font-family="{MONO}" font-size="13.5">',
        "  <title>manuscript-guard check refusing a number typed into the manuscript</title>",
        f'  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" '
        f'fill="{palette["terminal"]}" stroke="{palette["line"]}"/>',
        f"  {dots}",
        *rows,
        "</svg>",
        "",
    ])


#: The boxes of the loop: where each stands, its name, and one line under it.
BOXES = {
    "analysis": (20, 60, 150, "Analysis", "Python or R"),
    "results": (205, 60, 150, "results/", "written by the emitter"),
    "manuscript": (390, 60, 150, "Manuscript", "Markdown, {{bindings}}"),
    "check": (575, 60, 130, "check", "fourteen gates"),
    "build": (740, 60, 120, "build", "the .docx"),
    "ledger": (390, 190, 150, "Literature ledger", "value, quote, source"),
    "rules": (575, 190, 130, "Journal, checklist", "retrieved, not built in"),
}
BOX_HEIGHT = 62


def _box(name: str, palette: dict[str, str]) -> str:
    x, y, width, title, under = BOXES[name]
    fill, stroke = (
        (palette["accent_box"], palette["accent"]) if name == "check"
        else (palette["box"], palette["line"])
    )
    middle = x + width / 2
    return (
        f'  <rect x="{x}" y="{y}" width="{width}" height="{BOX_HEIGHT}" rx="8" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>\n'
        f'  <text x="{middle}" y="{y + 27}" text-anchor="middle" font-size="15" '
        f'font-weight="600" fill="{palette["text"]}">{escape(title)}</text>\n'
        f'  <text x="{middle}" y="{y + 46}" text-anchor="middle" font-size="12" '
        f'fill="{palette["soft"]}">{escape(under)}</text>'
    )


def loop_svg(palette: dict[str, str]) -> str:
    """The path of a number, from the analysis to the document and back from Word."""
    width, height = 880, 300
    row = 60 + BOX_HEIGHT / 2

    def right(a: str, b: str) -> str:
        start = BOXES[a][0] + BOXES[a][2]
        return (f'  <line x1="{start + 4}" y1="{row}" x2="{BOXES[b][0] - 8}" y2="{row}" '
                f'stroke="{palette["soft"]}" stroke-width="1.5" marker-end="url(#tip)"/>')

    def up(a: str, b: str) -> str:
        x = BOXES[a][0] + BOXES[a][2] / 2
        return (f'  <line x1="{x}" y1="{BOXES[a][1] - 4}" x2="{x}" '
                f'y2="{BOXES[b][1] + BOX_HEIGHT + 8}" stroke="{palette["soft"]}" '
                f'stroke-width="1.5" marker-end="url(#tip)"/>')

    # A co-author edits the .docx in Word, and `import` brings the edits back to the source.
    back_from = BOXES["build"][0] + BOXES["build"][2] / 2
    back_to = BOXES["manuscript"][0] + BOXES["manuscript"][2] / 2
    back = (
        f'  <path d="M {back_from} 56 V 28 H {back_to} V 50" fill="none" '
        f'stroke="{palette["soft"]}" stroke-width="1.5" stroke-dasharray="5 4" '
        f'marker-end="url(#tip)"/>\n'
        f'  <text x="{(back_from + back_to) / 2}" y="20" text-anchor="middle" font-size="12" '
        f'fill="{palette["soft"]}">import: a co-author&#8217;s Word edits come back</text>'
    )
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" font-family="{SANS}">',
        "  <title>From the analysis to the document: results, manuscript, check, build</title>",
        "  <defs>",
        '    <marker id="tip" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">',
        f'      <path d="M 0 0 L 10 5 L 0 10 z" fill="{palette["soft"]}"/>',
        "    </marker>",
        "  </defs>",
        *(_box(name, palette) for name in BOXES),
        right("analysis", "results"),
        right("results", "manuscript"),
        right("manuscript", "check"),
        right("check", "build"),
        up("ledger", "manuscript"),
        up("rules", "check"),
        back,
        f'  <text x="{width / 2}" y="286" text-anchor="middle" font-size="13" '
        f'fill="{palette["soft"]}">Change the analysis and rebuild: every number follows. '
        "A number that no longer has a source fails the check.</text>",
        "</svg>",
        "",
    ])


def figures() -> dict[str, str]:
    """Every file this writes, by name."""
    drawn = {}
    for name, palette in PALETTES.items():
        drawn[f"loop-{name}.svg"] = loop_svg(palette)
        drawn[f"check-{name}.svg"] = card_svg(palette)
    return drawn


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in figures().items():
        (OUT / name).write_bytes(text.encode("utf-8"))
        print(f"wrote docs/img/{name}")


if __name__ == "__main__":
    main()
