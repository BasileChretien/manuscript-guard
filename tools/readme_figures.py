"""Draw the three pictures the README shows, each for a light and a dark page.

    python tools/readme_figures.py            # writes docs/img/*.svg

`loop` is the path a number takes from the analysis to the document. `check` is what the
command prints when a number has been typed into the manuscript by hand: `CARD` below holds
that text as `manuscript-guard check` printed it on the worked example, and
`tests/test_docs.py` runs the same edit and fails if the tool no longer says it. `demo` is
the same failure animated, then the number bound again and `check` run on the unchanged
example: its first scene is `CARD`, and its last is `CLEAN`, which the same test file holds
to what `check` prints. The paths are written with forward slashes, as on Linux and macOS;
Windows prints backslashes.

The files are committed. Run this after changing `CARD`, `CLEAN`, a palette or a drawing,
or after a gate is added, and commit what it writes: the same test fails while the two
differ. The loop says how many gates there are, counted from the package, so it needs
`manuscript_guard` importable.
"""
from __future__ import annotations

import importlib
import pkgutil
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "img"

#: Colours for a white page and for a dark one, close to those GitHub itself uses, so the
#: pictures sit in the page rather than on it.
PALETTES = {
    "light": {
        "page": "#ffffff", "box": "#f6f8fa", "line": "#d0d7de", "text": "#1f2328",
        "soft": "#59636e", "accent": "#0969da", "accent_box": "#ddf4ff",
        "fail": "#cf222e", "terminal": "#f6f8fa", "prompt": "#1a7f37", "ok": "#1a7f37",
    },
    "dark": {
        "page": "#0d1117", "box": "#161b22", "line": "#3d444d", "text": "#f0f6fc",
        "soft": "#9198a1", "accent": "#4493f8", "accent_box": "#121d2f",
        "fail": "#f85149", "terminal": "#161b22", "prompt": "#3fb950", "ok": "#3fb950",
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


#: What `check` prints on the worked example as it is committed, every number bound: its
#: stage line, the pair of lines of its closing summary on numerical provenance, and its last
#: line, with `...` where lines are left out. Captured where CI runs it, with no Zotero
#: running: on Ubuntu (WSL) under Python 3.13 and matplotlib 3.11.2, `check` run by the test
#: suite's `project` fixture, the example with its analysis run and its figure review stamped
#: (0.2.475, 2026-11-05). The one warning of numerical provenance is G7's
#: `pinning-unchecked`, "Zotero is not running, so citation keys were not checked for
#: pinning": with Zotero open and read, `check` prints one warning fewer in both counts.
#: `tests/test_docs.py` runs `check` on the example with Zotero taken as not running, and
#: fails unless it prints these lines, in this order.
CLEAN: list[tuple[str, str]] = [
    ("text", "stage: drafting (writing the manuscript against results that exist)"),
    ("soft", "  ..."),
    ("text", "  numerical provenance"),
    ("text", "    checked:     G2, G3, G7, G8: 0 failing, 1 warning"),
    ("soft", "  ..."),
    ("ok", "0 failing, 13 warnings"),
]

#: The edit the demo shows, read from `CARD`: the number typed, the binding it replaced, and
#: the line of manuscript/main.md they are on, as the finding quotes it.
TYPED = "4,000"
BINDING = "{{results.cohort.n_reports}}"
QUOTED = next(line for _kind, line in CARD if line.lstrip().startswith("> ")).lstrip()[2:]
LINE = CARD[2][1].split(":")[1]

#: How long one showing of the demo lasts, in seconds, before it starts again.
DEMO_SECONDS = 18.0

#: An animation is CSS inside the SVG, and the static style of each element is where it ends,
#: so a reader who asks for reduced motion sees the number bound and the clean check.
REDUCE = ("@media (prefers-reduced-motion: reduce) {"
          " *, *::before, *::after { animation: none !important; } }")


def _at(seconds: float) -> str:
    value = 100 * seconds / DEMO_SECONDS
    return f"{value:.2f}".rstrip("0").rstrip(".") + "%"


def _keyframes(name: str, stops: list[tuple[float, str]]) -> str:
    """`stops` are (seconds, declarations), the first at 0 and the last at the cycle's end."""
    body = " ".join(f"{_at(seconds)} {{ {rules} }}" for seconds, rules in stops)
    return f"@keyframes {name} {{ {body} }}"


def _shown(name: str, on: float, off: float | None, fade: float = 0.15) -> str:
    """CSS for `.name`: hidden until `on`, then shown until `off`, or to the end."""
    stops = [(0, "opacity: 0"), (on, "opacity: 0"), (on + fade, "opacity: 1")]
    if off is None:
        stops.append((DEMO_SECONDS, "opacity: 1"))
    else:
        stops += [(off, "opacity: 1"), (off + fade, "opacity: 0"), (DEMO_SECONDS, "opacity: 0")]
    static = "" if off is None else " opacity: 0;"
    return (f"{_keyframes(name, stops)}\n.{name} {{{static} "
            f"animation: {name} {DEMO_SECONDS}s linear infinite both; }}")


def _typed(command: str, name: str, colour: str, y: int) -> str:
    """The command, one character after another."""
    letters = "".join(
        f'<tspan class="{name}" style="animation-delay:{0.045 * number:.3f}s">'
        f"{escape(letter)}</tspan>"
        for number, letter in enumerate(command)
    )
    return (f'  <text x="22" y="{y}" fill="{colour}" font-weight="600" '
            f'xml:space="preserve">{letters}</text>')


def _demo_css(palette: dict[str, str]) -> list[str]:
    seconds = DEMO_SECONDS
    every = f"{seconds}s linear infinite both"
    first = [1.9 + 0.12 * number for number in range(len(CARD) - 1)]
    last = [10.5 + 0.1 * number for number in range(len(CLEAN))]
    return [
        f"text {{ font-family: {MONO}; font-size: 13.5px; }} "
        f".cap {{ font-family: {SANS}; font-size: 12.5px; }}",
        # Typing: each character's fill-opacity, shifted by its own delay.
        _keyframes("typed1", [(0, "fill-opacity: 0"), (0.5, "fill-opacity: 0"),
                              (0.51, "fill-opacity: 1"), (0.8 * seconds, "fill-opacity: 1"),
                              (0.8 * seconds + 0.01, "fill-opacity: 0"),
                              (seconds, "fill-opacity: 0")]),
        _keyframes("typed2", [(0, "fill-opacity: 0"), (9.1, "fill-opacity: 0"),
                              (9.11, "fill-opacity: 1"), (seconds, "fill-opacity: 1")]),
        f".typed1 {{ animation: typed1 {every}; }} .typed2 {{ animation: typed2 {every}; }}",
        _keyframes("failing", [(0, "opacity: 1"), (5.0, "opacity: 1"), (5.3, "opacity: .35"),
                               (8.5, "opacity: .35"), (8.7, "opacity: 0"),
                               (seconds, "opacity: 0")]),
        _keyframes("passing", [(0, "opacity: 0"), (8.7, "opacity: 0"), (8.8, "opacity: 1"),
                               (17.2, "opacity: 1"), (17.8, "opacity: 0"),
                               (seconds, "opacity: 0")]),
        _keyframes("pane", [(0, "opacity: 0"), (0.3, "opacity: 1"), (17.2, "opacity: 1"),
                            (17.8, "opacity: 0"), (seconds, "opacity: 0")]),
        f".failing {{ opacity: 0; animation: failing {every}; }} "
        f".passing {{ animation: passing {every}; }} .pane {{ animation: pane {every}; }}",
        _shown("cap1", 0.2, 5.0, fade=0.25), _shown("cap2", 5.2, 8.5, fade=0.25),
        _shown("cap3", 8.8, None, fade=0.25),
        *(_shown(f"a{number}", on, None) for number, on in enumerate(first)),
        *(_shown(f"b{number}", on, None) for number, on in enumerate(last)),
        # The pane: the typed number turns red, its line is replaced, the binding checked.
        _keyframes("flag", [(0, f"fill: {palette['text']}"), (2.1, f"fill: {palette['text']}"),
                            (2.4, f"fill: {palette['fail']}"),
                            (seconds, f"fill: {palette['fail']}")]),
        f".flag {{ animation: flag {every}; }}",
        _shown("typed", 0, 5.8),
        _shown("struck", 5.8, None, fade=0.3),
        _shown("bound", 6.4, None, fade=0.3),
        _keyframes("bind", [(0, f"fill: {palette['accent']}"),
                            (11.7, f"fill: {palette['accent']}"),
                            (12.0, f"fill: {palette['ok']}"), (seconds, f"fill: {palette['ok']}")]),
        f".bind {{ fill: {palette['ok']}; animation: bind {every}; }}",
        REDUCE,
    ]


def demo_svg(palette: dict[str, str]) -> str:
    """`check` failing on the typed number, the number bound, and `check` passing."""
    width, height, step, top = 860, 420, 20, 60

    def row(name: str, number: int, kind: str, line: str) -> str:
        weight = ' font-weight="600"' if kind in ("fail", "ok") else ""
        return (f'  <text class="{name}{number}" x="22" y="{top + step * (number + 1)}" '
                f'fill="{palette[kind]}"{weight} xml:space="preserve">{escape(line)}</text>')

    command = CARD[0][1]
    failing = [_typed(command, "typed1", palette["prompt"], top)] + [
        row("a", number, kind, line) for number, (kind, line) in enumerate(CARD[1:])]
    passing = [_typed(command, "typed2", palette["prompt"], top)] + [
        row("b", number, kind, line) for number, (kind, line) in enumerate(CLEAN)]
    before, after = QUOTED.split(TYPED, 1)
    pane = [
        f'  <text x="22" y="350" fill="{palette["soft"]}">{LINE}</text>',
        f'  <text class="typed" x="60" y="350" fill="{palette["text"]}" '
        f'xml:space="preserve">{escape(before)}<tspan class="flag" font-weight="600">'
        f"{escape(TYPED)}</tspan>{escape(after)}</text>",
        f'  <text class="struck" x="60" y="350" fill="{palette["soft"]}" '
        f'text-decoration="line-through" xml:space="preserve">{escape(QUOTED)}</text>',
        f'  <text class="struck" x="44" y="350" fill="{palette["fail"]}" '
        f'font-weight="600">&#8722;</text>',
        f'  <g class="bound"><text x="22" y="374" fill="{palette["soft"]}">{LINE}</text>'
        f'<text x="44" y="374" fill="{palette["ok"]}" font-weight="600">+</text>'
        f'<text x="60" y="374" fill="{palette["text"]}" xml:space="preserve">'
        f'{escape(before)}<tspan class="bind">{escape(BINDING)}</tspan>{escape(after)}'
        "</text></g>",
    ]
    captions = [
        ("cap1", "A number typed into the manuscript by hand"),
        ("cap2", "The author binds it to the result it came from"),
        ("cap3", f"Checked again, after {TYPED} became {BINDING} in manuscript/main.md:{LINE}"),
    ]
    dots = "".join(
        f'<circle cx="{30 + 18 * n}" cy="20" r="5.5" fill="{palette["line"]}"/>' for n in range(3)
    )
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">',
        "  <title>manuscript-guard check, before and after a number is bound</title>",
        "  <style>",
        *_demo_css(palette),
        "  </style>",
        f'  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" '
        f'fill="{palette["terminal"]}" stroke="{palette["line"]}"/>',
        f"  {dots}",
        *(f'  <text class="cap {name}" x="90" y="24.5" fill="{palette["soft"]}">'
          f"{escape(caption)}</text>" for name, caption in captions),
        '  <g class="failing">', *failing, "  </g>",
        '  <g class="passing">', *passing, "  </g>",
        f'  <line x1="1" y1="300.5" x2="{width - 1}" y2="300.5" stroke="{palette["line"]}"/>',
        f'  <text class="cap" x="22" y="324" fill="{palette["soft"]}">manuscript/main.md</text>',
        '  <g class="pane">', *pane, "  </g>",
        "</svg>",
        "",
    ])


def gate_names() -> set[str]:
    """The gates the package declares: the `GATE` of each module of `manuscript_guard.gates`,
    read as `tests/test_docs.py` reads them for the README's table."""
    import manuscript_guard.gates as package

    found = set()
    for module in pkgutil.iter_modules(package.__path__):
        gate = getattr(importlib.import_module(f"{package.__name__}.{module.name}"), "GATE", None)
        if gate:
            found.add(gate)
    return found


_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen",
)
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def in_words(number: int) -> str:
    """A count from nought to ninety-nine as the prose writes it: "seventeen", "twenty-two"."""
    if not 0 <= number < 100:
        raise ValueError(f"{number} is not a count this writes in words")
    if number < 20:
        return _ONES[number]
    tens, ones = divmod(number, 10)
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


#: The boxes of the loop: where each stands, its name, and one line under it. The widths
#: leave room for a font wider than the one a title was measured in: a Linux page falls back
#: to DejaVu Sans, whose bold is a quarter wider than Segoe UI's.
BOXES = {
    "analysis": (20, 60, 150, "Analysis", "Python or R"),
    "results": (200, 60, 150, "results/", "from the emitter"),
    "manuscript": (380, 60, 150, "Manuscript", "with {{bindings}}"),
    "check": (560, 60, 150, "check", f"{in_words(len(gate_names()))} gates"),
    "build": (740, 60, 120, "build", "the .docx"),
    "ledger": (370, 190, 170, "Literature ledger", "value, quote, source"),
    "rules": (550, 190, 170, "Journal profile", "reporting checklist"),
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
        f'  <text x="{middle}" y="{y + 27}" text-anchor="middle" font-size="14" '
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
        f'fill="{palette["soft"]}">Change the analysis, run it again and rebuild: '
        "every bound number follows.</text>",
        "</svg>",
        "",
    ])


def figures() -> dict[str, str]:
    """Every file this writes, by name."""
    drawn = {}
    for name, palette in PALETTES.items():
        drawn[f"loop-{name}.svg"] = loop_svg(palette)
        drawn[f"check-{name}.svg"] = card_svg(palette)
        drawn[f"demo-{name}.svg"] = demo_svg(palette)
    return drawn


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in figures().items():
        (OUT / name).write_bytes(text.encode("utf-8"))
        print(f"wrote docs/img/{name}")


if __name__ == "__main__":
    main()
