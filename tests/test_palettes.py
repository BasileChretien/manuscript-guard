"""The palettes shipped with the toolkit, and the helpers that hand them to a figure script.

The data file is derived, never typed: `tools/derive_palettes.py` reads each collection's own
file at a pinned commit. These tests hold the file to its shape, to what the colour check says
of each palette (computed again here), to the R package's copy, to its licences, and the
helpers to the collections' own rules for taking n colours of a palette.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from manuscript_guard import palettes
from manuscript_guard.colour import DEFICIENCIES
from manuscript_guard.palettes import _most

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "src" / "manuscript_guard" / "data"
R_DATA = REPO / "r" / "manuscriptguard" / "inst" / "extdata"
HEX = re.compile(r"#[0-9a-f]{6}")


def _held() -> dict:
    return json.loads((DATA / "palettes.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------- the data


def test_every_palette_is_well_formed() -> None:
    held = _held()
    assert held["schema"] == "manuscript-guard/palettes/1"
    collections = held["collections"]
    assert len(held["palettes"]) >= 250
    for name, entry in held["palettes"].items():
        assert entry["collection"] in collections, name
        assert entry["kind"] in (*palettes.KINDS, None), name
        assert len(entry["colours"]) >= 2 and all(HEX.fullmatch(c) for c in entry["colours"]), name
        if entry.get("order"):
            assert len(entry["order"]) == len(entry["colours"]), name
            assert all(isinstance(rank, int) and rank >= 1 for rank in entry["order"]), name
        for n, codes in (entry.get("by_n") or {}).items():
            assert len(codes) == int(n) and all(HEX.fullmatch(c) for c in codes), (name, n)
        assert entry["claims_cvd"] in (True, False, None), name


def test_every_collection_asked_for_is_there() -> None:
    """Basile, 2026-10-21: the artists' palettes he likes, beside the perceptual and
    colour-blind safe standards."""
    counted: dict[str, int] = {}
    for entry in _held()["palettes"].values():
        counted[entry["collection"]] = counted.get(entry["collection"], 0) + 1
    assert counted == {"MetBrewer": 56, "MoMAColors": 35, "NatParksPalettes": 30,
                       "PNWColors": 14, "wesanderson": 24, "Okabe-Ito": 1, "ColorBrewer": 35,
                       "viridis": 4, "cividis": 1, "Crameri": 60}  # fmt: skip


def test_what_the_check_says_of_each_palette_is_what_it_says_now() -> None:
    """The verdicts are written into the file when it is derived. A change to the colour
    check that changes one has the file derived again, or this fails."""
    for name, entry in _held()["palettes"].items():
        assessed = palettes.assess(entry)
        assert {key: entry[key] for key in assessed} == assessed, name


def test_okabe_and_itos_colours_are_the_published_values() -> None:
    published = ((0, 0, 0), (230, 159, 0), (86, 180, 233), (0, 158, 115), (240, 228, 66),
                 (0, 114, 178), (213, 94, 0), (204, 121, 167))  # fmt: skip
    expected = ["#" + "".join(f"{c:02x}" for c in rgb) for rgb in published]
    assert palettes.colours("okabe-ito") == expected
    found = palettes.palette("okabe-ito")
    assert found.distinct == {"normal": 8, "cvd": 8, "greyscale": 2}


def test_the_r_package_carries_the_same_files() -> None:
    for name in ("palettes.json", "palettes_LICENSES.txt"):
        assert (R_DATA / name).read_bytes() == (DATA / name).read_bytes(), name


def test_each_collections_licence_is_beside_the_data_and_credited() -> None:
    """Every licence that asks for its notice to travel with the colours has it, in the
    collection's own words, and ATTRIBUTION.md names each collection."""
    licences = (DATA / "palettes_LICENSES.txt").read_text(encoding="utf-8")
    for notice in (
        "Copyright (c) 2023 MoMAColors authors",
        "Copyright (c) 2022 Karthik Ram",
        "Copyright (c) 2022 Kevin S. Blake",
        "Copyright (c) 2020 Fabio Crameri",
        "Copyright (c) 2017, Battelle Memorial Institute",
        "Copyright (c) 2002 Cynthia Brewer, Mark Harrower, and The Pennsylvania State",
        "This product includes color specifications and designs developed by Cynthia Brewer",
        "Apache License",
        "Version 2.0, January 2004",
        "mpl-colormaps by Nathaniel Smith & Stefan van der Walt",
        "License: CC0",
        "Okabe M, Ito K.",
        "Permission is hereby granted, free of charge",
    ):
        assert notice in licences, notice
    attribution = (REPO / "ATTRIBUTION.md").read_text(encoding="utf-8")
    for collection in _held()["collections"]:
        assert collection.split("-")[0] in attribution, collection
    assert "palettes_LICENSES.txt" in attribution


@pytest.mark.skipif(not os.environ.get("MANUSCRIPT_GUARD_PALETTE_SOURCES"),
                    reason="MANUSCRIPT_GUARD_PALETTE_SOURCES names no folder of the "
                    "collections' files")  # fmt: skip
def test_the_data_is_derived_again_byte_for_byte(tmp_path: Path) -> None:
    """With the collections' files at hand (`tools/derive_palettes.py <folder> --fetch`), the
    script writes the shipped files again, byte for byte."""
    import importlib.util
    import sys

    script = REPO / "tools" / "derive_palettes.py"
    spec = importlib.util.spec_from_file_location("derive_palettes", script)
    derive = importlib.util.module_from_spec(spec)
    # A dataclass looks its module up by name as it is made.
    sys.modules["derive_palettes"] = derive
    spec.loader.exec_module(derive)
    folder = Path(os.environ["MANUSCRIPT_GUARD_PALETTE_SOURCES"])
    assert derive.derive(folder).encode("utf-8") == (DATA / "palettes.json").read_bytes()
    assert derive.licences(folder).encode("utf-8") == (
        DATA / "palettes_LICENSES.txt").read_bytes()  # fmt: skip


# ------------------------------------------------------------------- taking n colours


def test_n_colours_of_a_palette_are_those_its_collection_gives() -> None:
    """MetBrewer's rule: the colours whose rank in its order is at most n, in the palette's
    sequence (`met.brewer`'s `palette[[1]][which(palette[[2]] %in% c(1:n))]`)."""
    archambault = palettes.palette("met/Archambault")
    assert archambault.order == (2, 7, 5, 1, 6, 4, 3)
    assert palettes.colours("met/Archambault", 3) == ["#88a0dc", "#ed968c", "#f9d14a"]
    # ColorBrewer's own scheme of n, and its smallest's ends below it.
    assert palettes.colours("brewer/Set2", 3) == ["#66c2a5", "#fc8d62", "#8da0cb"]
    assert palettes.colours("brewer/Set2", 2) == ["#66c2a5", "#8da0cb"]
    # wesanderson's: the first n. A short name is enough where only one palette has it.
    assert palettes.colours("Zissou1", 2) == ["#3b9ab2", "#78b7c5"]
    # A continuous map: n evenly spaced along it, its ends among them.
    viridis = palettes.colours("viridis", 3)
    assert viridis[0] == "#440154" and viridis[-1] == "#fde725"
    assert palettes.colours("okabe-ito", 3, reverse=True) == ["#56b4e9", "#e69f00", "#000000"]


def test_more_colours_than_a_set_has_are_refused_and_a_ramp_interpolates() -> None:
    with pytest.raises(palettes.PaletteError, match="has 5 colours, and 9 were asked for"):
        palettes.colours("wes/Zissou1", 9)
    assert len(palettes.ramp("wes/Zissou1", 9)) == 9
    assert palettes.ramp("wes/Zissou1", 9)[0] == "#3b9ab2"
    with pytest.raises(palettes.PaletteError, match="no palette is called"):
        palettes.colours("no-such-palette")


def test_a_name_two_collections_share_must_be_given_whole() -> None:
    names = [name.split("/")[-1].lower() for name in palettes.names()]
    shared = sorted({name for name in names if names.count(name) > 1})
    if not shared:
        pytest.skip("no two collections share a name")
    with pytest.raises(palettes.PaletteError, match="palettes are called"):
        palettes.palette(shared[0])


def test_matplotlib_gets_a_cycle_and_a_colormap() -> None:
    matplotlib = pytest.importorskip("matplotlib")
    palettes.use("okabe-ito", 3)
    cycle = [entry["color"] for entry in matplotlib.rcParams["axes.prop_cycle"]]
    assert cycle == ["#000000", "#e69f00", "#56b4e9"]
    cmap = palettes.cmap("crameri/batlow")
    assert cmap.N == 256
    assert palettes.cmap("brewer/Set2", 3).N == 3
    matplotlib.rcdefaults()


# ------------------------------------------------------------------- choosing and saying


def test_a_safe_scale_of_n_classes_keeps_n_of_its_colours_apart() -> None:
    """Round 1 of #406: `--safe` judged a sequential palette by its lightness alone, and
    offered Blues for five classes, of which no two stay apart for a reader with
    tritanopia."""
    assert palettes.palette("brewer/Blues").distinct["cvd"] < 5
    five = {p.name for p in palettes.chosen(kind="sequential", colours=5, safe=True)}
    assert "brewer/Blues" not in five
    assert "viridis/viridis" in five, "a continuous map is judged by its lightness"
    assert "brewer/Blues" in {p.name for p in palettes.chosen(kind="sequential", safe=True)}


def test_show_says_every_palettes_lightness() -> None:
    said = "\n".join(palettes.describe(palettes.palette("brewer/Blues"), []))
    assert "its lightness runs one way, and for each deficiency" in said


def test_colorbrewer_below_its_smallest_scheme_gives_both_ends() -> None:
    """Round 1 of #406: two of a diverging scheme were one arm and its pale middle."""
    smallest = palettes.colours("brewer/RdBu", 3)
    assert palettes.colours("brewer/RdBu", 2) == [smallest[0], smallest[-1]]
    assert palettes.colours("brewer/RdBu", 1) == [smallest[0]]


def test_a_collections_own_quirk_is_kept() -> None:
    """MetBrewer's Tsimshian gives rank 1 twice and no rank 2; `met.brewer` gives two
    colours for one, and so does this."""
    assert palettes.palette("met/Tsimshian").order == (6, 1, 7, 4, 1, 5, 3)
    assert len(palettes.colours("met/Tsimshian", 1)) == 2


def test_a_safe_palette_keeps_apart_the_very_colours_asked_for() -> None:
    """Round 2 of #406: `--safe --colours n` asked how many colours stay apart at most, and
    so listed PuOr for seven classes: ten of its colours stay apart for every reader, and
    its scheme of seven does not."""
    assert palettes.palette("brewer/PuOr").distinct["cvd"] == 10
    assert _most([palettes.colours("brewer/PuOr", 7)], DEFICIENCIES) < 7
    seven = {p.name for p in palettes.chosen(kind="diverging", colours=7, safe=True)}
    assert "brewer/PuOr" not in seven
    assert "brewer/PuOr" in {p.name for p in palettes.chosen(kind="diverging", colours=10,
                                                             safe=True)}  # fmt: skip
    for kind in ("qualitative", "sequential", "diverging"):
        for found in palettes.chosen(kind=kind, colours=7, safe=True):
            if not found.continuous:
                codes = palettes.colours(found.name, 7)
                assert _most([codes], DEFICIENCIES) == len(codes), found.name


def test_a_lightness_that_runs_no_way_is_said_without_a_deficiency() -> None:
    """Round 2 of #406: "neither runs one way nor turns once, but not for each deficiency"
    says nothing a reader can use."""
    found = replace(palettes.palette("okabe-ito"), lightness="neither", lightness_kept=False)
    said = "\n".join(palettes.describe(found, []))
    assert "its lightness neither runs one way nor turns once" in said
    assert "for each deficiency" not in said


def test_safe_palettes_are_those_every_reader_can_read_for_that_use() -> None:
    qualitative = palettes.chosen(kind="qualitative", colours=4, safe=True)
    assert all((p.distinct["cvd"] or 0) >= 4 for p in qualitative if not p.continuous)
    names = {p.name for p in qualitative}
    assert "okabe-ito" in names and "brewer/Set2" not in names  # Set2: 3 for every reader
    sequential = palettes.chosen(kind="sequential", safe=True)
    assert {"viridis/viridis", "cividis/cividis", "crameri/batlow"} <= {p.name for p in sequential}
    assert all(p.lightness == "monotone" and p.lightness_kept for p in sequential)
    # An artist's palette, which states no kind, is offered for a scale where its lightness
    # runs one way.
    assert any(p.collection == "MetBrewer" for p in sequential)


def test_an_artists_palette_the_check_does_not_pass_is_said_to_be_so() -> None:
    """MetBrewer calls Archambault colour-blind friendly; at 10 apart in CIEDE2000 three of
    its colours stay apart for every reader. Both are said, and neither hides the other."""
    found = palettes.palette("met/Archambault")
    assert found.claims_cvd is True and found.distinct["cvd"] == 3
    lines = palettes.describe(found, palettes.colours("met/Archambault"))
    said = "\n".join(lines)
    assert "3 for every colour-vision deficiency" in said
    assert "calls it colour-blind friendly" in said and "CC0-1.0" in said
    assert 'mg_palette("met/Archambault", n)' in said


def test_the_palettes_command_lists_filters_and_shows(capsys) -> None:
    from manuscript_guard.cli import main

    assert main(["palettes", "--kind", "qualitative", "--colours", "4", "--safe"]) == 0
    listed = capsys.readouterr().out
    assert "okabe-ito" in listed and "brewer/Set2" not in listed
    assert main(["palettes", "--show", "okabe-ito", "--colours", "3"]) == 0
    shown = capsys.readouterr().out
    assert "#000000, #e69f00, #56b4e9" in shown and "8 for every colour-vision" in shown
    assert main(["palettes", "--show", "okabe-ito", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["distinct"]["cvd"] == 8
    assert main(["palettes", "--show", "no-such"]) == 2
    assert main(["palettes", "--collection", "nobody"]) == 1


def test_a_figure_is_sized_to_the_journal(project: Path) -> None:
    """The journal's narrowest width, its text no smaller than its least or 7 pt, its lines
    no thinner, and fonts kept as text and embedded, as G3 and G4 read them."""
    import yaml

    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["figures"] = {"source_url": "https://journal.example/artwork",
                           "read_on": "2026-10-21", "confirmed": True, "widths_mm": [89, 183],
                           "min_text_pt": 8, "min_line_pt": 0.75}  # fmt: skip
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    style = palettes.figure_style(project)
    assert style["figure.figsize"][0] == pytest.approx(89 / 25.4)
    assert style["font.size"] == 8 and style["xtick.labelsize"] == 8
    assert style["axes.linewidth"] == 0.75 and style["pdf.fonttype"] == 42
    assert style["svg.fonttype"] == "none"
    assert palettes.figure_style(project, width="double")["figure.figsize"][0] == pytest.approx(
        183 / 25.4)  # fmt: skip
    assert palettes.figure_style(project, width=120, size=9)["font.size"] == 9
    document["figures"]["min_text_pt"] = 5
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert palettes.figure_style(project)["font.size"] == palettes.TEXT_PT


# ------------------------------------------------------------------------------------- R


def _rscript() -> str | None:
    found = shutil.which("Rscript")
    if found:
        return found
    candidates = sorted(Path("C:/Program Files/R").glob("R-*/bin/x64/Rscript.exe"), reverse=True)
    return str(candidates[0]) if candidates else None


def test_r_gives_the_colours_python_gives(tmp_path: Path) -> None:
    rscript = _rscript()
    if rscript is None:
        pytest.skip("R is not installed")
    # A project whose journal prints text of 8 pt and lines of 0.75 pt at the least, for
    # mg_theme to read.
    root = tmp_path / "paper"
    (root / "profiles" / "journals").mkdir(parents=True)
    (root / "paper.yaml").write_text("target_journal: demo\n", encoding="utf-8")
    (root / "profiles" / "journals" / "demo.yaml").write_text(
        "figures: {min_text_pt: 8, min_line_pt: 0.75, widths_mm: [89, 183]}\n", encoding="utf-8"
    )
    script = tmp_path / "palettes.R"
    script.write_text(
        'if (!requireNamespace("jsonlite", quietly = TRUE)) quit(status = 3)\n'
        f'source("{(REPO / "r/manuscriptguard/R/emit.R").as_posix()}")\n'
        f'source("{(REPO / "r/manuscriptguard/R/palettes.R").as_posix()}")\n'
        f'options(manuscriptguard.palettes = "{(DATA / "palettes.json").as_posix()}")\n'
        'out <- list(\n'
        '  archambault = mg_palette("met/Archambault", 3),\n'
        '  set2 = mg_palette("brewer/Set2", 3),\n'
        '  zissou = mg_palette("Zissou1", 2),\n'
        '  okabe = mg_palette("okabe-ito", 3, reverse = TRUE),\n'
        '  ramp = mg_palette("wes/Zissou1", 9, type = "continuous"),\n'
        '  rows = nrow(mg_palettes())\n'
        ')\n'
        'if (requireNamespace("ggplot2", quietly = TRUE)) {\n'
        '  library(ggplot2)\n'
        '  d <- data.frame(x = 1:3, y = 1:3, g = c("a", "b", "c"))\n'
        '  p <- ggplot(d, aes(x, y, colour = g)) + geom_point() + scale_colour_mg("okabe-ito")\n'
        '  out$scale <- unique(ggplot_build(p)$data[[1]]$colour)\n'
        f'  root <- "{root.as_posix()}"\n'
        '  theme <- mg_theme(root)\n'
        '  out$axis <- calc_element("axis.text.x", theme)$size\n'
        '  out$legend <- calc_element("legend.text", theme)$size\n'
        '  out$line <- calc_element("axis.line.x", theme + theme(axis.line = element_line()))'
        '$linewidth * .pt * 72 / 96\n'
        '  boxed <- mg_theme(root, base = theme_bw)\n'
        '  out$border <- calc_element("panel.border", boxed)$linewidth * .pt * 72 / 96\n'
        '}\n'
        'cat(jsonlite::toJSON(out, auto_unbox = TRUE))\n',
        encoding="utf-8",
    )
    done = subprocess.run([rscript, str(script)], capture_output=True, text=True, timeout=300)
    if done.returncode == 3:
        pytest.skip("jsonlite is not installed for R")
    assert done.returncode == 0, done.stderr
    said = json.loads(done.stdout)
    assert said["archambault"] == palettes.colours("met/Archambault", 3)
    assert said["set2"] == palettes.colours("brewer/Set2", 3)
    assert said["zissou"] == palettes.colours("Zissou1", 2)
    assert said["okabe"] == palettes.colours("okabe-ito", 3, reverse=True)
    assert said["rows"] == len(palettes.names())
    # Along a ramp, R's colorRampPalette and Python's step alike, to a unit where a channel
    # falls on a half.
    for ours, theirs in zip(palettes.ramp("wes/Zissou1", 9), said["ramp"], strict=True):
        assert all(abs(int(ours[i : i + 2], 16) - int(theirs[i : i + 2], 16)) <= 1
                   for i in (1, 3, 5)), (ours, theirs)  # fmt: skip
    if "scale" in said:
        assert said["scale"] == palettes.colours("okabe-ito", 3)
        # Round 1 of #406: every text at the journal's size, not 0.8 of it, and lines drawn
        # at the width asked, not three quarters of it.
        assert said["axis"] == 8 and said["legend"] == 8
        assert abs(said["line"] - 0.75) < 1e-6
        # Round 2: a panel's border is a line too, which theme_bw drew at its own width.
        assert abs(said["border"] - 0.75) < 1e-6
