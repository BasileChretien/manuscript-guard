"""The fonts, text and lines of a PDF figure (`gates/figure_pdf.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from generated import pdf_document

from manuscript_guard.gates.figure_pdf import parse_pdf, read_pdf

TYPE3 = b"<< /Type /Font /Subtype /Type3 /BaseFont /ABCDEF+DejaVuSans >>"
HELVETICA = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
TRUETYPE = (b"<< /Type /Font /Subtype /TrueType /BaseFont /Arial /FontDescriptor {n} 0 R >>\n"
            b"endobj\n{n} 0 obj\n<< /Type /FontDescriptor /FontName /Arial /FontFile2 9 0 R >>")
TYPE0 = (b"<< /Type /Font /Subtype /Type0 /BaseFont /Sans /DescendantFonts [{n} 0 R] >>\n"
         b"endobj\n{n} 0 obj\n<< /Type /Font /Subtype /CIDFontType2 /FontDescriptor 30 0 R >>\n"
         b"endobj\n30 0 obj\n<< /Type /FontDescriptor /FontFile2 9 0 R >>")
TYPE0_BARE = (b"<< /Type /Font /Subtype /Type0 /BaseFont /Bare /DescendantFonts [{n} 0 R] >>\n"
              b"endobj\n{n} 0 obj\n<< /Type /Font /Subtype /CIDFontType0 /FontDescriptor 31 0 R"
              b" >>\nendobj\n31 0 obj\n<< /Type /FontDescriptor >>")  # fmt: skip


@pytest.mark.parametrize(
    ("content", "sizes"),
    [
        (b"BT /F1 10 Tf 0 0 Td (a) Tj ET", [10.0]),
        (b"q 0.5 0 0 0.5 0 0 cm BT /F1 10 Tf (a) Tj ET Q", [5.0]),
        (b"BT /F1 1 Tf 8 0 0 8 30 40 Tm (a) Tj ET", [8.0]),
        # A text turned a quarter keeps its size; one under a scale of 2 and 0.5 is half.
        (b"BT /F1 10 Tf 0 1 -1 0 0 0 Tm (a) Tj ET", [10.0]),
        (b"q 2 0 0 0.5 0 0 cm BT /F1 10 Tf (a) Tj ET Q", [5.0]),
        (b"q 2 0 0 2 0 0 cm Q BT /F1 10 Tf (a) Tj ET", [10.0]),
        (b"BT /F1 9 Tf [(a) -100 (b)] TJ (c) ' ET", [9.0, 9.0]),
        # A size set before a q is the size after its Q.
        (b"BT /F1 7 Tf ET q BT /F1 12 Tf ET Q BT (a) Tj ET", [7.0]),
    ],
)
def test_a_text_s_size_is_carried_through_every_transform(content: bytes, sizes: list) -> None:
    figure = parse_pdf(pdf_document(content))
    assert figure is not None
    assert [round(size, 9) for _text, size in figure.texts] == sizes


@pytest.mark.parametrize(
    ("content", "widths"),
    [
        (b"0.5 w 0 0 m 1 1 l S", [0.5]),
        (b"0 0 m 1 1 l S", [1.0]),
        (b"q 3 0 0 3 0 0 cm 0.5 w 0 0 m 1 1 l S Q", [1.5]),
        # A filled path draws no line; one filled and stroked does.
        (b"0.5 w 0 0 m 1 1 l 1 0 l f", []),
        (b"0.5 w 0 0 m 1 1 l 1 0 l B", [0.5]),
        # A hairline, as thin as the printer draws.
        (b"0 w 0 0 m 1 1 l S", [0.0]),
    ],
)
def test_a_line_s_width_is_carried_through_every_transform(content: bytes, widths: list) -> None:
    figure = parse_pdf(pdf_document(content))
    assert figure is not None
    assert [round(width, 9) for width in figure.lines] == widths


def test_a_form_draws_under_its_matrix_and_where_it_is_drawn() -> None:
    document = pdf_document(
        b"q 2 0 0 2 0 0 cm /X1 Do Q",
        forms={"X1": (b"BT /F1 4 Tf (a) Tj ET 0.25 w 0 0 m 1 1 l S", "1.5 0 0 1.5 0 0")},
    )
    figure = parse_pdf(document)
    assert figure is not None
    assert [round(s, 9) for _t, s in figure.texts] == [12.0]
    assert [round(w, 9) for w in figure.lines] == [0.75]


@pytest.mark.parametrize(
    ("fonts", "said"),
    [
        ({"F1": TYPE3}, [("ABCDEF+DejaVuSans", "Type3", True)]),
        ({"F1": HELVETICA}, [("Helvetica", "Type1", False)]),
        ({"F1": TRUETYPE}, [("Arial", "TrueType", True)]),
        ({"F1": TYPE0}, [("Sans", "Type0", True)]),
        ({"F1": TYPE0_BARE}, [("Bare", "Type0", False)]),
    ],
)
def test_each_font_says_whether_it_is_type_3_or_not_in_the_pdf(fonts: dict, said: list) -> None:
    figure = parse_pdf(pdf_document(b"BT /F1 10 Tf (a) Tj ET", fonts))
    assert figure is not None
    assert [(f.name, f.subtype, f.embedded) for f in figure.fonts] == said


def test_a_font_inside_an_object_stream_is_read() -> None:
    figure = parse_pdf(pdf_document(b"BT /F1 10 Tf (a) Tj ET", {"F1": TYPE3}, packed=True))
    assert figure is not None
    assert [(f.name, f.subtype) for f in figure.fonts] == [("ABCDEF+DejaVuSans", "Type3")]


def test_a_page_not_compressed_is_read_and_one_under_another_filter_is_not() -> None:
    plain = parse_pdf(pdf_document(b"BT /F1 10 Tf (a) Tj ET", compress=False))
    assert plain is not None and [s for _t, s in plain.texts] == [10.0]
    # The same text, under a filter that is not read.
    data = b"BT /F1 10 Tf (a) Tj ET".hex().encode() + b">"
    hexed = pdf_document(data, compress=False).replace(
        b"<< /Length %d >>" % len(data), b"<< /Length %d /Filter /ASCIIHexDecode >>" % len(data)
    )
    figure = parse_pdf(hexed)
    assert figure is not None and figure.texts == []


def test_a_page_s_width_is_its_media_box_s_or_its_parents() -> None:
    figure = parse_pdf(pdf_document(b"", width=468))
    assert figure is not None and figure.width_pt == 468


@pytest.mark.parametrize("data", [b"", b"not a PDF", b"%PDF-1.4\n%%EOF\n"])
def test_what_is_not_a_pdf_with_a_page_reads_as_nothing(data: bytes) -> None:
    assert parse_pdf(data) is None


def test_a_figure_that_cannot_be_read_from_disk_reads_as_nothing(tmp_path: Path) -> None:
    assert read_pdf(tmp_path / "gone.pdf") is None


@pytest.mark.parametrize(("fonttype", "subtype"), [(3, "Type3"), (42, "Type0")])
def test_a_figure_matplotlib_saves_is_read_as_it_was_drawn(
    tmp_path: Path, fonttype: int, subtype: str
) -> None:
    """matplotlib's own PDFs: Type 3 fonts unless `pdf.fonttype` is 42 (its default is 3, as
    `rcParamsDefault` says in 3.9), its text at the size set and its lines at the width."""
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with matplotlib.rc_context({"pdf.fonttype": fonttype}):
        figure, axes = plt.subplots(figsize=(3, 2))
        axes.plot([1, 2, 3], [1, 4, 2], lw=0.4)
        axes.set_title("Title", fontsize=6)
        path = tmp_path / "figure.pdf"
        figure.savefig(path)
        plt.close(figure)
    read = read_pdf(path)
    assert read is not None and read.width_pt == 216
    assert [(f.subtype, f.embedded) for f in read.fonts] == [(subtype, True)]
    assert ("Title", 6.0) in [(t, round(s, 6)) for t, s in read.texts]
    assert 0.4 in [round(w, 6) for w in read.lines]
