"""The size and resolution of a raster, read from its own header with the standard library."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from manuscript_guard.gates.figure_files import Raster, raster_of


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


def test_the_example_s_figure_is_read(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    found = raster_of(root / "example" / "figures" / "forest.png")
    assert found is not None and (found.width, found.height) == (1950, 660)
    assert found.dpi == pytest.approx(300, rel=1e-3)
