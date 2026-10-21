"""A LaTeX file's bindings and what the gates read around them (`text/latex/views.py`, and the
scanner's records in `text/latex/mask.py`), step 4 of DESIGN.md's "LaTeX manuscripts". The
generated campaign is in `tests/test_properties.py`; G2 on the example's twin in
`tests/test_latex_twin.py` and `tests/test_corruption.py`."""

from __future__ import annotations

import pytest

from manuscript_guard.gates.bound_units import units_after
from manuscript_guard.text.latex.mask import NUL, _near_binding, read
from manuscript_guard.text.latex.structure import Source
from manuscript_guard.text.latex.views import Tables, bindings, markdown_view
from manuscript_guard.text.placeholders import parse

DOC = "\\documentclass{article}\n\\begin{document}\n"
END = "\\end{document}\n"


def _source(text: str) -> Source:
    return Source("main.tex", text, read(text))


def test_a_binding_is_a_placeholder_with_the_line_and_column_of_the_tex() -> None:
    text = DOC + "Of \\mg{results.n} reports,\n\\mg [w] { figure.forest } here.\n" + END
    good, malformed = bindings(_source(text))
    assert [(p.ref, p.line, p.col, p.raw) for p in good] == [
        ("results.n", 3, 4, "\\mg{results.n}"),
        ("figure.forest", 4, 1, "\\mg [w] { figure.forest }"),
    ]
    assert malformed == []


@pytest.mark.parametrize(
    "typed",
    ["\\Mg{results.n}", "\\mgg{results.n}", "\\gm{results.n}", "{{results.n}}",
     "\\mg{Results.n}", "\\mg{results}", "\\mg results.n"],
)
def test_what_looks_meant_for_a_binding_is_malformed(typed: str) -> None:
    text = DOC + "Of " + typed + " reports.\n" + END
    good, malformed = bindings(_source(text))
    assert good == [] and [raw for raw, _at, _line in malformed] == [typed]


def test_a_command_near_mg_with_no_key_after_it_is_left_alone() -> None:
    assert _near_binding("Mg") and _near_binding("m") and _near_binding("mgx")
    assert not _near_binding("mg") and not _near_binding("emph") and not _near_binding("xy")
    text = DOC + "A \\ng{} and \\mu{x} and \\qty{5}{\\mg}.\n" + END
    assert bindings(_source(text)) == ([], [])


def test_the_markdown_view_holds_each_binding_where_its_command_stands() -> None:
    text = DOC + "Of \\mg{results.n}~reports (95\\% CI).\n" + END
    source = _source(text)
    good, _ = bindings(source)
    view = markdown_view(source, good)
    assert len(view) == len(text) and NUL not in view
    assert view[good[0].start : good[0].end] == "{{ results.n}}"
    assert [p.ref for p in parse(view)[0]] == ["results.n"]
    assert "95%  CI" in view


@pytest.mark.parametrize(
    ("after", "unit"),
    [("~mg", "mg"), ("\\,mg", "mg"), ("\\%", "%"), (" mg/kg", "mg/kg"),
     ("~$\\mu$g", None), ("~\\textmu g", None), ("~\\si{\\micro\\gram}", None)],
)
def test_a_unit_after_a_latex_binding_is_read_only_where_it_is_typed_as_it_prints(
    after: str, unit: str | None
) -> None:
    """`$\\mu$g` prints µg, and its view reads "g": not compared, rather than said to differ
    from the µg emitted (step 4)."""
    text = DOC + "A dose of \\mg{results.dose}" + after + " was given.\n" + END
    source = _source(text)
    good, _ = bindings(source)
    found = units_after(markdown_view(source, good), text)
    assert [w.unit for w in found] == ([unit] if unit else [])


def test_a_typed_table_and_a_listing_are_recorded_where_they_stand() -> None:
    text = (DOC + "\\begin{tabular}{ll}a & 7 \\\\\\end{tabular}\n"
            "\\begin{align}x &= 1\\end{align}\n\\begin{lstlisting}[language=R, caption=x]\n"
            "x <- 55\n\\end{lstlisting}\n" + END)  # fmt: skip
    reading = read(text)
    ((start, end),) = reading.tables
    assert text[start:].startswith("\\begin{tabular}") and text[end:].startswith("\\end{tabular}")
    tables = Tables(reading.tables)
    assert text.index("7") in tables and text.index("x &") not in tables
    (listing,) = reading.listings
    assert listing.language == "r" and text[listing.start : listing.end] == "\nx <- 55\n"


def test_a_file_input_inside_a_table_is_in_it_to_where_it_closes_it() -> None:
    reading = read("3 & 4 \\\\\n\\end{tabular}\nafter 5\n", body=True,
                   environments=("tabular",))  # fmt: skip
    assert reading.tables == ((0, 9),) and reading.refusals == ()


def test_past_a_refusal_a_binding_is_found_by_its_shape() -> None:
    text = DOC + "\\catcode`\\@=11\nOf \\mg{results.n} reports.\n" + END
    source = _source(text)
    assert source.reading.refusals
    good, _ = bindings(source)
    assert [p.ref for p in good] == ["results.n"]
