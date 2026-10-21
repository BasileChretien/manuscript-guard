"""Colour as a reader with a colour-vision deficiency sees it, and as grey prints it.

Each part of `manuscript_guard.colour` against values published or computed by another
implementation: CIEDE2000 against the 34 pairs Sharma, Wu and Dalal publish with their
paper, and the simulation against colorspacious, which implements Machado et al. (2009) on
its own.
"""

from __future__ import annotations

import math

import pytest

from manuscript_guard import colour

#: Sharma, Wu and Dalal (2005), Table 1: two CIELAB colours and their CIEDE2000 difference,
#: as the authors' data file gives them (ciede2000testdata.txt, fetched 2026-10-21 from
#: https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/).
SHARMA_2005 = (
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0010), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0011), 7.2195),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0012), 7.2195),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0009, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0010, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0011, -2.4900), 4.7461),
    ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
    ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
    ((50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    ((36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    ((90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
    ((6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
)


@pytest.mark.parametrize(("first", "second", "expected"), SHARMA_2005)
def test_ciede2000_is_the_published_difference_both_ways(first, second, expected) -> None:
    """To the four decimals the data file prints, whichever colour comes first: the pairs
    were chosen by its authors to catch the mistakes implementations make, the mean hue
    across 0 degrees, the hue difference of a grey, and the rotation term."""
    assert colour.ciede2000(first, second) == pytest.approx(expected, abs=1e-4)
    assert colour.ciede2000(second, first) == pytest.approx(expected, abs=1e-4)


#: What colorspacious 1.1.2 makes of four colours at full severity, each deficiency in turn:
#: `cspace_convert(rgb, {"name": "sRGB1+CVD", "cvd_type": "deuteranomaly", "severity":
#: 100}, "sRGB1")` clipped to [0, 1], computed 2026-10-21. Its matrices are Machado's too,
#: applied to linear RGB, and its code is its own.
COLORSPACIOUS = (
    ("#d62728", [(0.3802, 0.340738, 0.146155), (0.546495, 0.487877, 0.120379),
                 (0.925549, 0.0, 0.166688)]),
    ("#2ca02c", [(0.641139, 0.567375, 0.096475), (0.589173, 0.531791, 0.218604),
                 (0.001811, 0.608832, 0.537899)]),
    ("#0072b2", [(0.324406, 0.457122, 0.708545), (0.230261, 0.401993, 0.693347),
                 (0.0, 0.508866, 0.538707)]),
    ("#cc79a7", [(0.500002, 0.544745, 0.661405), (0.582287, 0.597837, 0.646448),
                 (0.840278, 0.470405, 0.539543)]),
)  # fmt: skip


@pytest.mark.parametrize(("code", "seen"), COLORSPACIOUS)
def test_the_simulation_is_machados_as_another_implementation_applies_it(code, seen) -> None:
    rgb = colour.parse(code)[0]
    for deficiency, expected in zip(colour.DEFICIENCIES, seen, strict=True):
        assert colour.simulate(rgb, deficiency) == pytest.approx(expected, abs=1e-6), deficiency


def test_each_matrix_is_the_authors_and_leaves_a_grey_grey() -> None:
    """Machado's matrices keep white white, each row summing to one, so a grey is the same
    grey to every reader: black text, white paper and a grey line are never confused by a
    deficiency, only by their lightness."""
    for deficiency, matrix in colour.MACHADO_2009.items():
        for row in matrix:
            assert sum(row) == pytest.approx(1.0, abs=2e-6), deficiency
        for level in (0.0, 0.2, 0.5, 0.8, 1.0):
            assert colour.simulate((level,) * 3, deficiency) == pytest.approx((level,) * 3)
    # As the authors' page prints them, Table 1, severity 1.0.
    assert colour.MACHADO_2009["deuteranopia"][0] == (0.367322, 0.860646, -0.227968)
    assert colour.MACHADO_2009["tritanopia"][2] == (0.004733, 0.691367, 0.303900)


def test_grey_keeps_the_relative_luminance() -> None:
    """Grey is the grey of the same Y: pure green is far lighter than pure blue."""
    green = colour.simulate((0.0, 1.0, 0.0), colour.GREYSCALE)
    blue = colour.simulate((0.0, 0.0, 1.0), colour.GREYSCALE)
    assert green[0] == green[1] == green[2]
    assert colour.to_linear(green[0]) == pytest.approx(0.7151522)
    assert colour.to_linear(blue[0]) == pytest.approx(0.0721750)


def test_lab_of_srgb_white_and_black() -> None:
    assert colour.lab((1.0, 1.0, 1.0)) == pytest.approx((100.0, 0.0, 0.0), abs=1e-3)
    assert colour.lab((0.0, 0.0, 0.0)) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


@pytest.mark.parametrize(
    ("written", "parsed"),
    [
        ("#1F77B4", ((31 / 255, 119 / 255, 180 / 255), 1.0)),
        ("#abc", ((0xAA / 255, 0xBB / 255, 0xCC / 255), 1.0)),
        ("#abc8", ((0xAA / 255, 0xBB / 255, 0xCC / 255), 0x88 / 255)),
        ("#1f77b480", ((31 / 255, 119 / 255, 180 / 255), 0x80 / 255)),
        ("rgb(31, 119, 180)", ((31 / 255, 119 / 255, 180 / 255), 1.0)),
        ("RGBA(0,0,0,0.5)", ((0.0, 0.0, 0.0), 0.5)),
        ("rgb(100% 50% 0% / 25%)", ((1.0, 0.5, 0.0), 0.25)),
        (" Steelblue ", ((0x46 / 255, 0x82 / 255, 0xB4 / 255), 1.0)),
        ("none", None),
        ("transparent", None),
        ("url(#gradient)", None),
        ("currentColor", None),
        ("#12", None),
        ("rgb(1, 2)", None),
    ],
)
def test_a_colour_is_read_as_css_and_svg_write_it(written: str, parsed) -> None:
    found = colour.parse(written)
    if parsed is None:
        assert found is None
    else:
        assert found[0] == pytest.approx(parsed[0]) and found[1] == pytest.approx(parsed[1])


def test_a_colour_painted_half_transparent_is_paler() -> None:
    assert colour.over_white((0.0, 0.0, 0.0), 0.5) == (0.5, 0.5, 0.5)
    assert colour.hex_of(colour.over_white((1.0, 0.0, 0.0), 0.25)) == "#ffbfbf"


def test_matplotlibs_red_and_green_are_one_colour_with_deuteranopia() -> None:
    """The pair every guide warns of: tab:red and tab:green, 72 apart to normal vision, are
    under 5 apart for a reader with deuteranopia, and blue and orange stay apart."""
    found = colour.confusions([colour.parse("#d62728")[0], colour.parse("#2ca02c")[0]],
                              seen=colour.DEFICIENCIES)  # fmt: skip
    assert [(c.first, c.second, c.seen) for c in found] == [
        ("#2ca02c", "#d62728", "deuteranopia")
    ]
    assert found[0].normal > 70 and found[0].after < 5
    apart = [colour.parse("#1f77b4")[0], colour.parse("#ff7f0e")[0]]
    assert colour.confusions(apart, seen=colour.DEFICIENCIES) == []


def test_okabe_and_itos_palette_stays_apart_for_every_deficiency() -> None:
    """The palette drawn for readers with a colour-vision deficiency (Okabe and Ito, Color
    Universal Design, 2008) has no pair any of the three makes one, and several that grey
    does, since it was not drawn for grey."""
    okabe_ito = ("#000000", "#e69f00", "#56b4e9", "#009e73", "#f0e442", "#0072b2", "#d55e00",
                 "#cc79a7")  # fmt: skip
    rgbs = [colour.parse(code)[0] for code in okabe_ito]
    assert colour.confusions(rgbs, seen=colour.DEFICIENCIES) == []
    assert ("#56b4e9", "#e69f00") in {
        (c.first, c.second) for c in colour.confusions(rgbs, seen=(colour.GREYSCALE,))
    }


def test_a_pair_already_close_to_normal_vision_is_not_a_deficiencys_doing() -> None:
    """Two shades of one sequential ramp are close to everyone; saying so under each
    deficiency would be a false alarm on every heat map."""
    shades = [colour.parse("#3182bd")[0], colour.parse("#3a88c2")[0]]
    assert colour.difference(*shades) < colour.THRESHOLD
    assert colour.confusions(shades) == []


def test_the_threshold_is_where_the_design_says() -> None:
    assert colour.THRESHOLD == 10.0
    assert math.isclose(colour.difference((1.0, 1.0, 1.0), (0.0, 0.0, 0.0)), 100.0, abs_tol=1e-3)


def _ramp(first: str, last: str, steps: int) -> list[colour.RGB]:
    start, end = colour.parse(first)[0], colour.parse(last)[0]
    return [
        tuple(start[c] + (end[c] - start[c]) * i / (steps - 1) for c in range(3))
        for i in range(steps)
    ]


def test_a_continuous_scale_is_found_by_the_chain_of_its_shades() -> None:
    """Round 1 of #398: a scale drawn in many shades, as ggplot2 colours points by a
    continuous variable or matplotlib a scatter by a colormap, has neighbours just over the
    threshold apart, which grey or a deficiency brings under it. Colours chained within the
    threshold, three or more, are found as a scale, for the gate to leave the figure
    uncompared (Basile, 2026-10-21)."""
    ramp = _ramp("#132b43", "#56b1f7", 64)
    assert colour.scales(ramp) == {colour.hex_of(rgb) for rgb in ramp}
    assert colour.confusions(ramp) != [], "compared, a scale's shades fall under it"
    matplotlib = pytest.importorskip("matplotlib")
    viridis = [tuple(rgba[:3]) for rgba in matplotlib.colormaps["viridis"](range(256))]
    assert len(colour.scales(viridis)) > 250


def test_a_figures_greys_and_series_are_no_scale() -> None:
    """A panel's grey background, its white grid, a light strip and a legend's frame chain
    within the threshold; were they a scale, every default ggplot2 and matplotlib figure
    would go uncompared. Greys are no shades: no grey is ever said to be confused."""
    ggplot2 = ("#ebebeb", "#ffffff", "#d9d9d9", "#f2f2f2", "#333333", "#4d4d4d", "#f8766d",
               "#00ba38", "#619cff")  # fmt: skip
    matplotlib = ("#000000", "#2ca02c", "#bcd6e8", "#d62728", "#d6d6d6", "#ffffff", "#b0b0b0",
                  "#cccccc")  # fmt: skip
    for figure in (ggplot2, matplotlib):
        assert colour.scales([colour.parse(code)[0] for code in figure]) == set(), figure
    greys = [colour.parse(code)[0] for code in ("#000000", "#4d4d4d", "#b0b0b0", "#ffffff")]
    assert colour.confusions(greys) == []


def test_every_pair_is_compared_where_the_caller_asks() -> None:
    red, green = colour.parse("#d62728")[0], colour.parse("#2ca02c")[0]
    found = colour.confusions([*_ramp("#132b43", "#56b1f7", 64), red, green],
                              seen=colour.DEFICIENCIES)  # fmt: skip
    assert ("#2ca02c", "#d62728", "deuteranopia") in {(c.first, c.second, c.seen) for c in found}


def test_a_series_near_a_shade_is_in_the_scale_it_chains_to() -> None:
    """Round 2 of #398: tab:red within the threshold of a shade of a heat map in reds is
    chained into that scale, which is why a figure with a scale is not compared rather than
    compared without its scale."""
    red = colour.parse("#d62728")[0]
    assert "#d62728" in colour.scales([*_ramp("#fcbba1", "#d62728", 64), red])
