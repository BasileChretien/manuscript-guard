"""The brand's drawings are what tools/brand_assets.py makes of brand/source.svg, each says
what it shows, and a villain stays apart from the guard for a reader with a colour-vision
deficiency, by the model G3 holds a figure's colours to."""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

import pytest

from manuscript_guard import colour

REPO = Path(__file__).resolve().parent.parent


def brand_script():
    spec = importlib.util.spec_from_file_location(
        "brand_assets", REPO / "tools" / "brand_assets.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_drawings_are_the_ones_the_script_writes() -> None:
    script = brand_script()
    for name, text in script.drawings().items():
        path = script.OUT / name
        assert path.is_file(), f"docs/img/brand/{name} is missing: run python tools/brand_assets.py"
        assert path.read_text(encoding="utf-8") == text, (
            f"docs/img/brand/{name} is stale: run python tools/brand_assets.py"
        )


def test_nothing_else_is_kept_beside_them() -> None:
    script = brand_script()
    kept = {path.name for path in script.OUT.iterdir()}
    made = set(script.drawings()) | set(script.RENDERED)
    assert kept == made, (
        f"docs/img/brand/ holds {sorted(kept - made)} and lacks {sorted(made - kept)}"
    )


def test_each_drawing_says_what_it_shows_and_leaves_no_colour_unresolved() -> None:
    for name, text in brand_script().drawings().items():
        assert 'role="img"' in text, name
        title = text.split('<title id="title">', 1)[1].split("</title>", 1)[0]
        assert title.strip(), f"{name} has an empty title"
        assert "var(" not in text, f"{name} keeps a colour token"


def test_a_drawing_that_names_no_palette_colour_is_refused() -> None:
    script = brand_script()
    with pytest.raises(SystemExit, match="var\\(--g-gold\\)"):
        script.paint('<path fill="var(--g-gold)"/>', script.PALETTES["light"])


#: The colours that tell a villain from the guard, or a shadow from either.
APART = (
    ("v-foe", "g-brass"), ("v-foe", "g-teal"), ("v-foe", "g-navy"), ("v-foe", "g-plate"),
    ("v-foe", "g-steel"), ("v-shade", "g-teal"), ("v-shade", "v-foe"),
)


def too_close(palette: dict[str, str]) -> list[str]:
    found = []
    for first, second in APART:
        a, b = colour.parse(palette[first])[0], colour.parse(palette[second])[0]
        for way in colour.DEFICIENCIES:
            apart = colour.difference(colour.simulate(a, way), colour.simulate(b, way))
            if apart < colour.THRESHOLD:
                found.append(f"{first} and {second}: {apart:.1f} apart under {way}")
    return found


@pytest.mark.parametrize("shade", ["light", "dark"])
def test_a_villain_stays_apart_from_the_guard_for_every_reader(shade: str) -> None:
    assert too_close(brand_script().PALETTES[shade]) == []


def test_a_villain_that_turns_into_brass_for_some_readers_is_found() -> None:
    # Pink is far from the brass to normal vision, and next to it under tritanopia.
    palette = dict(brand_script().PALETTES["light"], **{"v-foe": "#e4b0c0"})
    assert any(line.startswith("v-foe and g-brass") for line in too_close(palette))


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", head[16:24])


def test_the_rendered_pictures_are_there_at_their_size() -> None:
    script = brand_script()
    for name, size in script.RENDERED.items():
        path = script.OUT / name
        assert path.is_file(), (
            f"docs/img/brand/{name} is missing: run python tools/brand_assets.py --png"
        )
        assert png_size(path) == size, name
