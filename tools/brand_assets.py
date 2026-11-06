"""Write the brand's drawings, for a light page and a dark one, from brand/source.svg.

    python tools/brand_assets.py          # writes docs/img/brand/*.svg
    python tools/brand_assets.py --png    # and renders the PNGs through a local Chrome or Edge

Each drawing in brand/source.svg is a <symbol> whose colours are tokens, `var(--name)`. This
writes every drawing `DRAWINGS` names as a file of its own, once in each of `PALETTES`, with
the tokens replaced and only the symbols it uses copied in, so that it shows wherever an SVG
shows: on GitHub, on PyPI, in a browser. `tests/test_brand.py` fails while the files differ
from what this writes, and while a villain's colour comes closer than `colour.THRESHOLD` to
one of the guard's for a reader with a colour-vision deficiency.

The PNGs (the social preview GitHub shows when the repository is linked, the emblem at 512
pixels, the favicon at 32) are rendered from the same SVGs by a headless Chrome or Edge. Their
pixels depend on the browser and its fonts, so the test checks only that each is there at its
size. Set MANUSCRIPT_GUARD_BROWSER to the browser's path where it is not found.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "brand" / "source.svg"
OUT = ROOT / "docs" / "img" / "brand"
SVG = "http://www.w3.org/2000/svg"

#: The colours each token stands for. The villain's ember (`v-foe`) and the shadow's lilac
#: (`v-shade`) were chosen with `manuscript_guard.colour` to stay apart from the guard's
#: brass, teal, navy, plates and steel under protanopia, deuteranopia and tritanopia.
PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "g-navy": "#1b2b4b", "g-plate": "#2e4570", "g-steel": "#c3ccd7", "g-brass": "#e6c878",
        "g-teal": "#175f63", "g-teal-dk": "#0f4447", "g-paper": "#f3f1ea", "g-ink": "#2a3346",
        "g-visor": "#0c1424", "g-eye": "#e8f4f2", "g-edge": "#1b2b4b",
        "g-ground": "rgba(27,43,75,0.13)", "v-foe": "#c9502f", "v-shade": "#a39cba",
        "v-ghost": "#e9ecf1", "v-board": "#5b6577", "v-lid": "#c9d0da", "v-nose": "#e3a07e",
        "t-ink": "#1d2840",
    },
    "dark": {
        "g-navy": "#3a5585", "g-plate": "#5070a3", "g-steel": "#c3ccd7", "g-brass": "#e6c878",
        "g-teal": "#1f7479", "g-teal-dk": "#155458", "g-paper": "#e9e6dc", "g-ink": "#2a3346",
        "g-visor": "#070c16", "g-eye": "#e8f4f2", "g-edge": "#0a1120",
        "g-ground": "rgba(0,0,0,0.35)", "v-foe": "#d95b36", "v-shade": "#c6c0db",
        "v-ghost": "#d9dde6", "v-board": "#8a94a6", "v-lid": "#c9d0da", "v-nose": "#e3a07e",
        "t-ink": "#e3e8f0",
    },
}

#: Each drawing written: its file name, its symbol, its size, and what it shows (its title).
DRAWINGS: tuple[tuple[str, str, int, int, str], ...] = (
    ("emblem", "emblem", 200, 200,
     "The manuscript-guard emblem: Vord's helmet, with its {{ }} crest, on a round shield"),
    ("emblem-small", "emblem-small", 32, 32,
     "The manuscript-guard emblem, drawn for 32 pixels and below"),
    ("vord", "guard", 200, 240,
     "Vord, the manuscript-guard mascot: a guard in navy armour with a {{ }} crest on the "
     "helmet, a round shield bearing a page, and a katana held upright at rest"),
    ("stray-number", "stray-number", 120, 120,
     "The Stray Number, a number typed into the text and bound to nothing (G2)"),
    ("forger", "forger", 120, 120, "The Forger, a results file edited by hand (G1)"),
    ("ghost-citation", "ghost-citation", 120, 120,
     "The Ghost Citation, a retracted work still cited (G7)"),
    ("impostor-doi", "impostor-doi", 120, 120,
     "The Impostor DOI, a DOI that names another work than the one cited (G7)"),
    ("plan-rewriter", "plan-rewriter", 120, 120,
     "The Plan Rewriter, a plan changed after the first results with no Deviation (G12)"),
    ("stale-methods", "stale-methods", 120, 120,
     "Stale Methods, an analysis changed since the Methods were read against it (G9)"),
    ("confirmation-bias", "confirmation-bias", 120, 120,
     "Confirmation bias, a shadow that no gate sees"),
    ("data-leakage", "data-leakage", 120, 120,
     "Data leakage, test data seeping into training: a shadow that no gate sees"),
    ("co-author", "co-author", 120, 120, "The co-author, who reads what no gate can"),
)

TAGLINE = "Every number traceable to its source."
#: The social preview's ground and words, on the dark palette.
PREVIEW = {"ground": "#0f1728", "name": "#e9edf3", "tagline": "#e6c878", "line": "#9ba7b9"}
SANS = "Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Consolas, Menlo, monospace"

#: The PNGs `--png` renders, and the size of each.
RENDERED: dict[str, tuple[int, int]] = {
    "social-preview.png": (1280, 640),
    "emblem-512.png": (512, 512),
    "favicon-32.png": (32, 32),
}

_TOKEN = re.compile(r"var\(--([a-z0-9-]+)\)")


def symbols() -> dict[str, ET.Element]:
    """Every drawing of brand/source.svg by its id, in the order the file has them."""
    tree = ET.parse(SOURCE)
    for element in tree.iter():
        element.tag = element.tag.split("}", 1)[-1]
    defs = tree.getroot().find("defs")
    if defs is None:
        raise SystemExit("brand/source.svg has no <defs>")
    return {element.get("id"): element for element in defs if element.get("id")}


def needs(index: dict[str, ET.Element], names: list[str]) -> list[str]:
    """`names` and every drawing they use, in the order brand/source.svg has them."""
    wanted: set[str] = set()
    stack = list(names)
    while stack:
        name = stack.pop()
        if name in wanted:
            continue
        if name not in index:
            raise SystemExit(f"brand/source.svg has no drawing #{name}")
        wanted.add(name)
        stack.extend(
            element.get("href", "")[1:]
            for element in index[name].iter()
            if element.get("href", "").startswith("#")
        )
    return [name for name in index if name in wanted]


def paint(text: str, palette: dict[str, str]) -> str:
    """`text` with each token replaced by its colour in `palette`."""

    def colour(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in palette:
            raise SystemExit(f"brand/source.svg uses var(--{token}), which no palette names")
        return palette[token]

    return _TOKEN.sub(colour, text)


def _defs(index: dict[str, ET.Element], names: list[str]) -> str:
    parts = []
    for name in needs(index, names):
        element = copy.deepcopy(index[name])
        element.tail = None
        ET.indent(element, space="  ", level=2)
        parts.append("    " + ET.tostring(element, encoding="unicode"))
    return "\n".join(parts)


def document(index: dict[str, ET.Element], names: list[str], width: int, height: int,
             title: str, body: str) -> str:
    """A standalone SVG of `body`, with the drawings `names` use and a title."""
    return (
        f'<svg xmlns="{SVG}" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title">\n'
        f'  <title id="title">{escape(title, quote=False)}</title>\n'
        f"  <defs>\n{_defs(index, names)}\n  </defs>\n"
        f"{body}"
        "</svg>\n"
    )


def drawing(index: dict[str, ET.Element], symbol: str, width: int, height: int,
            title: str, palette: dict[str, str]) -> str:
    """One drawing, filling its file, in `palette`."""
    body = f'  <use href="#{symbol}" width="{width}" height="{height}"/>\n'
    return paint(document(index, [symbol], width, height, title, body), palette)


def social_preview(index: dict[str, ET.Element]) -> str:
    """The card GitHub shows where the repository is linked: emblem, name, tagline."""
    body = (
        f'  <rect width="1280" height="640" fill="{PREVIEW["ground"]}"/>\n'
        '  <use href="#emblem" x="100" y="140" width="360" height="360"/>\n'
        f'  <text x="530" y="282" font-family="{SANS}" font-size="74" font-weight="700" '
        f'fill="{PREVIEW["name"]}">manuscript-guard</text>\n'
        f'  <text x="533" y="350" font-family="{SANS}" font-size="36" '
        f'fill="{PREVIEW["tagline"]}">{escape(TAGLINE)}</text>\n'
        f'  <text x="533" y="414" font-family="{SANS}" font-size="26" '
        f'fill="{PREVIEW["line"]}">Open-source checks for scientific manuscripts</text>\n'
        f'  <text x="533" y="458" font-family="{MONO}" font-size="24" '
        f'fill="{PREVIEW["line"]}">pip install manuscript-guard</text>\n'
    )
    title = f"manuscript-guard: {TAGLINE}"
    return paint(document(index, ["emblem"], 1280, 640, title, body), PALETTES["dark"])


def drawings() -> dict[str, str]:
    """Every SVG file this writes, by name."""
    index = symbols()
    made = {}
    for name, symbol, width, height, title in DRAWINGS:
        for shade, palette in PALETTES.items():
            made[f"{name}-{shade}.svg"] = drawing(index, symbol, width, height, title, palette)
    made["favicon.svg"] = drawing(index, "emblem-small", 32, 32, "manuscript-guard",
                                  PALETTES["light"])
    made["social-preview.svg"] = social_preview(index)
    return made


def _sources(index: dict[str, ET.Element]) -> dict[str, str]:
    """The SVG each PNG is rendered from, at the PNG's size."""
    light = PALETTES["light"]
    return {
        "social-preview.png": social_preview(index),
        "emblem-512.png": drawing(index, "emblem", 512, 512, "manuscript-guard", light),
        "favicon-32.png": drawing(index, "emblem-small", 32, 32, "manuscript-guard", light),
    }


def browser() -> str:
    """A Chrome or an Edge to render with."""
    named = os.environ.get("MANUSCRIPT_GUARD_BROWSER")
    if named:
        return named
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge",
                 "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    for path in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ):
        if Path(path).is_file():
            return path
    raise SystemExit("--png needs Chrome or Edge: set MANUSCRIPT_GUARD_BROWSER to its path")


def _stop(process: subprocess.Popen) -> None:
    """End the browser and everything it started, which a headless run can leave behind."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                       capture_output=True, check=False, timeout=30)
    else:
        process.kill()
    process.wait(timeout=30)


def render(program: str, svg: str, width: int, height: int, out: Path) -> None:
    """Write `out`, the PNG a headless browser draws of `svg` in a window of its size."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        page, shot = Path(scratch) / "page.svg", Path(scratch) / "shot.png"
        page.write_text(svg, encoding="utf-8", newline="\n")
        command = [
            program, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={Path(scratch) / 'profile'}",
            "--default-background-color=00000000", f"--window-size={width},{height}",
            f"--screenshot={shot}", page.as_uri(),
        ]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            _wait_for(shot, process)
        finally:
            _stop(process)
        if not shot.is_file():
            raise SystemExit(f"{program} drew no {out.name}")
        shutil.copyfile(shot, out)


def _wait_for(shot: Path, process: subprocess.Popen, limit: float = 60.0) -> None:
    """Until `shot` is written and stops growing. A headless run writes it long before it
    lets go of its last process, if it ever does, so the process is not waited for."""
    deadline, size = time.monotonic() + limit, -1
    while time.monotonic() < deadline:
        now = shot.stat().st_size if shot.is_file() else 0
        if now and now == size:
            return
        if process.poll() is not None and not now:
            return
        size = now
        time.sleep(0.5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--png", action="store_true",
                        help="also render the PNGs, through a local Chrome or Edge")
    arguments = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in drawings().items():
        (OUT / name).write_text(text, encoding="utf-8", newline="\n")
    if arguments.png:
        program = browser()
        for name, svg in _sources(symbols()).items():
            width, height = RENDERED[name]
            render(program, svg, width, height, OUT / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
