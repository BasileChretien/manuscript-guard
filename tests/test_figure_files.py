"""The size and resolution of a raster, read from its own header with the standard library."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from manuscript_guard.gates.figure_files import Raster, check_file, raster_of


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png(width: int, height: int, dpi: float | None) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    parts = [b"\x89PNG\r\n\x1a\n", _chunk(b"IHDR", ihdr)]
    if dpi is not None:
        per_metre = round(dpi / 0.0254)
        parts.append(_chunk(b"pHYs", struct.pack(">IIB", per_metre, per_metre, 1)))
    parts += [_chunk(b"IDAT", zlib.compress(b"")), _chunk(b"IEND", b"")]
    return b"".join(parts)


def jpeg(width: int, height: int, units: int, density: int) -> bytes:
    app0 = b"JFIF\x00\x01\x02" + bytes([units]) + struct.pack(">HH", density, density) + b"\x00\x00"
    sof0 = b"\x08" + struct.pack(">HH", height, width) + b"\x03" + b"\x01\x22\x00" * 3
    return (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0
            + b"\xff\xc0" + struct.pack(">H", len(sof0) + 2) + sof0 + b"\xff\xd9")  # fmt: skip


def tiff(width: int, height: int, dpi: int, unit: int, order: str = "<") -> bytes:
    """A TIFF with one IFD: width, height, resolution and its unit."""
    entries = [(256, 4, 1, width), (257, 4, 1, height), (282, 5, 1, 0), (296, 3, 1, unit)]
    ifd_at = 8
    rational_at = ifd_at + 2 + 12 * len(entries) + 4
    body = struct.pack(order + "H", len(entries))
    for tag, kind, count, value in entries:
        if kind == 5:
            body += struct.pack(order + "HHII", tag, kind, count, rational_at)
        elif kind == 3:
            body += struct.pack(order + "HHIHH", tag, kind, count, value, 0)
        else:
            body += struct.pack(order + "HHII", tag, kind, count, value)
    body += struct.pack(order + "I", 0) + struct.pack(order + "II", dpi, 1)
    head = (b"II*\x00" if order == "<" else b"MM\x00*") + struct.pack(order + "I", ifd_at)
    return head + body


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (png(1950, 660, 300), Raster(1950, 660, 299.9994)),
        (png(800, 600, None), Raster(800, 600, None)),
        (jpeg(1200, 900, 1, 600), Raster(1200, 900, 600.0)),
        (jpeg(1200, 900, 2, 118), Raster(1200, 900, 118 * 2.54)),
        (jpeg(1200, 900, 0, 1), Raster(1200, 900, None)),
        (tiff(3000, 2000, 600, 2), Raster(3000, 2000, 600.0)),
        (tiff(3000, 2000, 600, 2, ">"), Raster(3000, 2000, 600.0)),
        (tiff(3000, 2000, 236, 3), Raster(3000, 2000, 236 * 2.54)),
    ],
    ids=["png", "png without pHYs", "jpeg dpi", "jpeg dpcm", "jpeg aspect only", "tiff",
         "tiff big-endian", "tiff centimetres"],  # fmt: skip
)
def test_a_raster_is_read_from_its_header(tmp_path: Path, data: bytes, expected: Raster) -> None:
    path = tmp_path / "figure"
    path.write_bytes(data)
    found = raster_of(path)
    assert found is not None
    assert (found.width, found.height) == (expected.width, expected.height)
    if expected.dpi is None:
        assert found.dpi is None
    else:
        assert found.dpi == pytest.approx(expected.dpi, rel=1e-3)


@pytest.mark.parametrize(
    "data",
    [b"", b"<svg/>", b"%PDF-1.7", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"II*\x00\x08",
     png(0, 600, 300), tiff(3000, 0, 600, 2)],  # fmt: skip
    ids=["empty", "svg", "pdf", "png cut short", "jpeg cut short", "tiff cut short",
         "png of no width", "tiff of no height"],  # fmt: skip
)
def test_what_is_not_a_whole_raster_header_is_none(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "figure"
    path.write_bytes(data)
    assert raster_of(path) is None


#: Artwork rules a small figure fails: its pixels, its text and its lines.
_STRICT = {"min_dpi": {"halftone": 300}, "widths_mm": [89], "min_text_pt": 6, "min_line_pt": 1}


def _said(path: Path, rules: dict) -> list[str]:
    return [finding.code for finding in check_file(path, rules, path.with_name("journal.yaml"))]


def test_a_raster_inside_an_svg_a_pdf_or_an_eps_is_not_read_for_its_pixels(
    tmp_path: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A figure file is read for its pixels only where
    it is a PNG, JPEG or TIFF"): a PNG of 100 pixels is too few for 89 mm on its own, and
    passes inside an SVG's `<image>`, a PDF's image or an EPS; an EPS's text at 2 pt and its
    hairline are not read either."""
    import base64

    raster = png(100, 100, 300)
    alone = tmp_path / "alone.png"
    alone.write_bytes(raster)
    assert _said(alone, _STRICT) == ["figure-resolution"]
    inside = tmp_path / "inside.svg"
    inside.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100pt" height="100pt" '
        'viewBox="0 0 100 100"><image width="100" height="100" href="data:image/png;base64,'
        + base64.b64encode(raster).decode("ascii") + '"/></svg>', encoding="utf-8")  # fmt: skip
    pdf = tmp_path / "inside.pdf"
    pdf.write_bytes(
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type "
        b"/Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R "
        b"/MediaBox [0 0 100 100] /Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R"
        b" >>\nendobj\n4 0 obj\n<< /Type /XObject /Subtype /Image /Width 100 /Height 100 "
        b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length 4 >>\nstream\n\x00\x00\x00\x00"
        b"\nendstream\nendobj\n5 0 obj\n<< /Length 30 >>\nstream\nq 100 0 0 100 0 0 cm /Im1 Do"
        b" Q\nendstream\nendobj\n%%EOF\n"
    )
    eps = tmp_path / "inside.eps"
    eps.write_bytes(
        b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 100\n/Helvetica findfont 2 "
        b"scalefont setfont 10 10 moveto (tiny) show\n0.01 setlinewidth 0 0 moveto 100 100 "
        b"lineto stroke\n100 100 8 [1 0 0 1 0 0] {<00>} image\n%%EOF\n"
    )
    for path in (inside, pdf, eps):
        assert _said(path, _STRICT) == [], path.name


@pytest.mark.parametrize(
    ("name", "data", "said"),
    [
        ("figure.png", png(1950, 660, 300), ["figure-shrinks"]),
        ("figure.png", png(1950, 660, None), []),
        ("figure.jpg", jpeg(1950, 660, 1, 300), ["figure-shrinks"]),
        ("figure.jpg", jpeg(1950, 660, 0, 1), []),
    ],
    ids=["png with pHYs", "png without pHYs", "jpeg with dpi", "jpeg aspect only"],
)
def test_a_raster_that_records_no_resolution_is_not_said_to_shrink(
    tmp_path: Path, name: str, data: bytes, said: list[str]
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A figure file is read for its pixels only where
    it is a PNG, JPEG or TIFF"): drawn 165 mm wide at 300 dpi and printed at 89, its 10 pt
    text prints at 5.4; with no `pHYs` chunk, or a JFIF header that records only an aspect,
    how large it was drawn is unknown and nothing is said."""
    path = tmp_path / name
    path.write_bytes(data)
    assert _said(path, {"min_text_pt": 6, "widths_mm": [89]}) == said


@pytest.mark.parametrize(("size", "said"), [(1_040_000, []), (1_050_000, ["figure-file-size"])])
def test_a_megabyte_of_a_figure_file_is_1048576_bytes(
    tmp_path: Path, size: int, said: list[str]
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A figure file is read for its pixels only where
    it is a PNG, JPEG or TIFF"): a file of 1,040,000 bytes is more than a million and passes
    a limit of 1 MB; one of 1,050,000 is over 1,048,576 and is said."""
    raster = png(10, 10, 300)
    path = tmp_path / "figure.png"
    path.write_bytes(raster + b"\x00" * (size - len(raster)))
    assert _said(path, {"max_file_mb": 1}) == said


def test_the_example_s_figure_is_read(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    found = raster_of(root / "example" / "figures" / "forest.png")
    assert found is not None and (found.width, found.height) == (1950, 660)
    assert found.dpi == pytest.approx(300, rel=1e-3)
