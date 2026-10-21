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


def test_round_1_of_400_a_markdown_binding_as_an_argument_and_a_brace_on_the_next_line() -> None:
    text = DOC + "Of \\emph{{results.n}} and \\mg\n  {results.m} reports.\n" + END
    good, malformed = bindings(_source(text))
    assert [p.ref for p in good] == ["results.m"]
    assert [raw for raw, _at, _line in malformed] == ["{{results.n}}"]
    assert read(DOC + "The command \\verb|\\mg| binds.\n" + END).refusals == ()


def test_round_2_of_400_an_option_list_is_blanked_and_a_value_in_brackets_is_read() -> None:
    """siunitx's `\\qty[round-precision=2]` holds options; the units package's `\\unit[250]`
    holds the value, and a binding there is no siunitx's."""
    masked = read(DOC + "\\qty[round-precision=2]{3.5}{\\mm} and \\unit[250]{mg}.\n" + END).masked
    assert "2" not in masked.replace("250", "") and "3.5" in masked and "250" in masked
    text = DOC + "A dose of \\unit[\\mg{results.dose}]{mg}.\n" + END
    source = _source(text)
    assert source.reading.refusals == ()
    assert [p.ref for p in bindings(source)[0]] == ["results.dose"]


def test_round_2_of_400_a_binding_s_own_markdown_braces_are_said_once() -> None:
    assert len(bindings(_source(DOC + "Of \\mg{{results.x}} reports.\n" + END))[1]) == 1
    # Round 3: in siunitx, where `\\mg` records nothing, the braces are said.
    assert len(bindings(_source(DOC + "Of \\num{\\mg{{results.x}}}.\n" + END))[1]) == 1


def test_round_2_of_400_a_definition_left_without_its_body_blanks_no_later_body() -> None:
    text = (DOC + "\\renewcommand{\\arraystretch}%\n{1.5}\n"
            "\\AtBeginDocument{4123 patients}\n" + END)  # fmt: skip
    assert "4123" in read(text).masked


def test_a_binding_after_a_refusal_raised_behind_it_is_counted_once() -> None:
    """Round 1 of #400: an environment left open is refused at its `\\begin`, behind the
    bindings the scan had read, which were counted again by their shape."""
    text = DOC + "\\begin{figure}\nOf \\mg{results.n} reports.\n"
    source = _source(text)
    assert source.reading.refusals
    assert [p.ref for p in bindings(source)[0]] == ["results.n"]


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
