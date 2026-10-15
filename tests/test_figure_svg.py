"""The text and lines of an SVG figure, at the size it prints (`gates/figure_svg.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.gates.figure_svg import Svg, clipped, points_per_unit, read_svg

HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'width="400pt" height="200pt" viewBox="0 0 400 200">'
)


def _svg(tmp_path: Path, body: str, head: str = HEAD) -> Svg:
    path = tmp_path / "figure.svg"
    path.write_text(head + body + "</svg>", encoding="utf-8")
    svg = read_svg(path)
    assert svg is not None
    return svg


@pytest.mark.parametrize(
    ("body", "sizes"),
    [
        ('<text x="1" y="1" font-size="10">a</text>', {"a": 10.0}),
        ('<text x="1" y="1" style="font: italic 8px sans-serif">a</text>', {"a": 8.0}),
        ('<text x="1" y="1" style="font-size: 12pt">a</text>', {"a": 16.0}),
        # SVG's default size where none is set.
        ('<text x="1" y="1">a</text>', {"a": 16.0}),
        ('<g font-size="10"><text x="1" y="1">a</text></g>', {"a": 10.0}),
        ('<g transform="scale(0.5)"><text x="1" y="1" font-size="10">a</text></g>', {"a": 5.0}),
        ('<g transform="matrix(2 0 0 2 0 0)"><g transform="scale(0.25)">'
         '<text x="1" y="1" font-size="10">a</text></g></g>', {"a": 5.0}),
        # A rotation turns a text and keeps its size.
        ('<text x="1" y="1" font-size="10" transform="rotate(-90 1 1)">a</text>', {"a": 10.0}),
        # A sub- or superscript drawn as a smaller tspan.
        ('<text x="1" y="1" font-size="10">CO<tspan font-size="70%">2</tspan></text>',
         {"CO": 10.0, "2": 7.0}),
        ('<text x="1" y="1" font-size="10">a<tspan style="font-size: 0.5em">b</tspan></text>',
         {"a": 10.0, "b": 5.0}),
        # A text drawn through `<use>`, from `<defs>` or a `<symbol>`, and not where defined.
        ('<defs><text id="t" font-size="10">a</text></defs><use xlink:href="#t" '
         'transform="scale(2)"/>', {"a": 20.0}),
        ('<symbol id="s"><text font-size="10">a</text></symbol><use href="#s"/>', {"a": 10.0}),
        ('<text x="1" y="1" font-size="10" display="none">a</text>', {}),
        ('<g style="display: none"><text x="1" y="1">a</text></g>', {}),
    ],
)  # fmt: skip
def test_a_text_s_size_is_carried_through_everything_around_it(
    tmp_path: Path, body: str, sizes: dict[str, float]
) -> None:
    svg = _svg(tmp_path, body)
    assert {mark.text: round(mark.units, 6) for mark in svg.texts} == sizes


@pytest.mark.parametrize(
    ("body", "widths"),
    [
        ('<path d="M0 0L1 1" stroke="black" stroke-width="0.5"/>', [0.5]),
        ('<path d="M0 0L1 1" style="stroke: #000; stroke-width: 0.8"/>', [0.8]),
        # A stroke where none is set is 1 wide; no stroke draws no line.
        ('<line x1="0" y1="0" x2="1" y2="1" stroke="black"/>', [1.0]),
        ('<path d="M0 0L1 1" stroke-width="2"/>', []),
        ('<path d="M0 0L1 1" stroke="none" stroke-width="2"/>', []),
        ('<g stroke="black" stroke-width="0.5"><rect width="1" height="1"/></g>', [0.5]),
        ('<g transform="scale(3)"><path d="M0 0L1 1" stroke="black" stroke-width="0.5"/></g>',
         [1.5]),
        ('<defs><path id="p" d="M0 0L0 3" stroke="black" stroke-width="0.4"/></defs>'
         '<use xlink:href="#p" x="5" y="5"/><use xlink:href="#p" transform="scale(0.5)"/>',
         [0.4, 0.2]),
    ],
)  # fmt: skip
def test_a_line_s_width_is_carried_through_everything_around_it(
    tmp_path: Path, body: str, widths: list[float]
) -> None:
    svg = _svg(tmp_path, body)
    assert [round(mark.units, 6) for mark in svg.lines] == widths


def test_a_figure_prints_its_view_box_at_the_width_it_prints() -> None:
    svg = Svg((), (), (0.0, 0.0, 468.0, 158.4), 468.0, True)
    # 89 mm is 252.3 pt, over 468 units.
    assert points_per_unit(svg, 89) == pytest.approx(89 / 25.4 * 72 / 468)
    assert points_per_unit(svg, None) == 1.0


def test_a_width_without_a_unit_is_read_as_pixels(tmp_path: Path) -> None:
    head = HEAD.replace('width="400pt" height="200pt"', 'width="400" height="200"')
    svg = _svg(tmp_path, "", head)
    assert (svg.width_pt, svg.width_unit) == (300.0, False)
    assert points_per_unit(svg, None) == 0.75


def test_a_figure_without_a_view_box_shows_its_width_and_height(tmp_path: Path) -> None:
    svg = _svg(tmp_path, "", HEAD.replace(' viewBox="0 0 400 200"', ""))
    assert svg.view == pytest.approx((0.0, 0.0, 400 * 4 / 3, 200 * 4 / 3))


@pytest.mark.parametrize(
    ("body", "cut"),
    [
        ('<text x="410" y="50">a</text>', ["a"]),
        ('<text x="50" y="-3">a</text>', ["a"]),
        ('<text x="400" y="200">a</text>', []),
        ('<g transform="translate(300 0)"><text x="150" y="50">a</text></g>', ["a"]),
        # A tspan without a position is drawn on from its text's.
        ('<text x="50" y="50">a<tspan>b</tspan></text>', []),
        ('<text x="50" y="50">a<tspan x="500">b</tspan></text>', ["b"]),
    ],
)
def test_a_text_anchored_outside_the_view_box_is_cut_off(
    tmp_path: Path, body: str, cut: list[str]
) -> None:
    assert [mark.text for mark in clipped(_svg(tmp_path, body))] == cut


def test_a_figure_that_is_not_xml_or_refers_to_itself_is_read_safely(tmp_path: Path) -> None:
    broken = tmp_path / "broken.svg"
    broken.write_text("<svg><text>", encoding="utf-8")
    assert read_svg(broken) is None
    looped = _svg(tmp_path, '<g id="g"><text x="1" y="1">a</text><use href="#g"/></g>')
    assert 1 < len(looped.texts) <= 17
