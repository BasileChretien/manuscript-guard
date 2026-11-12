"""G14 — the manuscript's abbreviations agree with themselves.

The same two halves as G6. The gate must report an abbreviation that is used before it is
defined, defined twice, defined for nothing or never defined; and it must stay quiet on a
surname with two capitals, a Roman numeral, a heading in capitals and a contributor's
initials. Every finding is a warning, so a noisy rule here costs nothing at the build and
everything in attention: the quiet half is what keeps the warnings read.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_language
from manuscript_guard.gates.language import _definitions, _file, _hidden, _latex_read, _long_form
from manuscript_guard.policy import DRAFTING, STAGES


def written(
    project: Path,
    text: str,
    *,
    supplement: str | None = None,
    stage: str | None = None,
    **files: str,
):
    """Judge exactly this text, at `stage` where one is given, as `check` gives its own. The
    example's supplement goes unless one is given, and `files` are further main-text files,
    named without their `.md`."""
    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(text, encoding="utf-8")
    for name, body in files.items():
        (project / "manuscript" / f"{name}.md").write_text(body, encoding="utf-8")
    if supplement is not None:
        folder = project / "manuscript" / "supplementary"
        folder.mkdir()
        (folder / "S1.md").write_text(supplement, encoding="utf-8")
    projekt, _ = load_project(project)
    return check_language(projekt, stage)


def configured(project: Path, **settings) -> None:
    path = project / "paper.yaml"
    paper = yaml.safe_load(path.read_text(encoding="utf-8"))
    paper.update(settings)
    path.write_text(yaml.safe_dump(paper, sort_keys=False), encoding="utf-8")


def found(report, code: str | None = None) -> list[str]:
    return [f.message for f in report.findings if code is None or f.code == code]


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


PLAIN = (
    "Reports were included without restriction on age or sex. Duplicate records were "
    "removed by matching on report identifier, and the remaining records were classified "
    "by drug and by reported event."
)


# ---------------------------------------------------------------- what must be caught


def test_an_abbreviation_used_before_its_definition_is_reported(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe ROR was computed for each drug.\n\n"
        "The reporting odds ratio (ROR) compares two groups of reports.\n",
    )
    assert codes(report) == {"abbreviation-used-before-defined"}
    (finding,) = report.findings
    assert finding.line == 3, "reported where it is used, not where it is defined"
    assert "ROR" in finding.message
    assert "manuscript/main.md:5" in finding.message, "and says where the definition is"
    assert finding.hint and finding.context


def test_an_abbreviation_defined_twice_is_reported(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR compares "
        "groups.\n\n# Discussion\n\nThe reporting odds ratio (ROR) was raised.\n",
    )
    assert codes(report) == {"abbreviation-redefined"}
    (finding,) = report.findings
    assert finding.line == 7, "the second definition is the one to remove"
    assert "defined again" in finding.message
    assert "manuscript/main.md:3" in finding.message


@pytest.mark.parametrize(
    ("text", "code", "said"),
    [
        ("The ROR of each drug, the reporting odds ratio (ROR), was computed.",
         "abbreviation-used-before-defined",
         "ROR is used here, and defined later on the same line"),
        ("The reporting odds ratio (ROR) and the reporting odds ratio (ROR) were computed. "
         "The ROR rose.", "abbreviation-redefined",
         "ROR is defined again; it was defined earlier on the same line"),
        ("The reporting odds ratio (ROR) and the relative odds ratio (ROR) were computed. "
         "The ROR rose.", "abbreviation-redefined",
         "ROR is defined as 'relative odds ratio' here and as 'reporting odds ratio' earlier on "
         "the same line"),
    ],
)  # fmt: skip
def test_a_definition_on_the_line_of_its_use_is_said_to_be_on_the_same_line(
    project: Path, text: str, code: str, said: str
) -> None:
    """A use and its definition on one line were told as "defined later at main.tex:158" of
    a finding on line 158, as though it were another place (corpus round, 2026-10-23): the
    same line is said to be the same line, and another is still named by file and line."""
    report = written(project, f"# Methods\n\n{text}\n")
    assert found(report, code) == [said], found(report)

def test_one_short_form_with_two_meanings_names_both(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR compares "
        "groups.\n\nThe relative odds ratio (ROR) was used as a check.\n",
    )
    (message,) = found(report, "abbreviation-redefined")
    assert "relative odds ratio" in message
    assert "reporting odds ratio" in message


def test_a_definition_nothing_uses_is_reported(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed for each drug.\n",
    )
    assert codes(report) == {"abbreviation-unused"}
    (finding,) = report.findings
    assert "reporting odds ratio" in finding.hint, "the hint says what to write instead"


def test_an_abbreviation_never_defined_is_reported_once(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe ROR was computed. The ROR compares groups. A raised ROR is a "
        "signal.\n",
    )
    assert codes(report) == {"abbreviation-undefined"}
    (finding,) = report.findings
    assert "3 times" in finding.message, "one finding for the abbreviation, with its count"
    assert finding.line == 3
    assert "known_abbreviations" in finding.hint


def test_the_main_text_does_not_inherit_from_the_abstract(project: Path) -> None:
    report = written(
        project,
        "# Abstract\n\nThe reporting odds ratio (ROR) was raised; the ROR is not a risk.\n\n"
        "# Methods\n\nThe ROR was computed for each drug.\n",
    )
    (message,) = found(report, "abbreviation-undefined")
    assert "main text" in message
    assert "abstract defines it" in message


def test_the_abstract_does_not_inherit_from_the_main_text(project: Path) -> None:
    report = written(
        project,
        "# Abstract\n\nThe ROR was raised.\n\n"
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR compares groups.\n",
    )
    (message,) = found(report, "abbreviation-undefined")
    assert "in the abstract" in message


def test_a_subsection_of_the_abstract_is_the_abstract(project: Path) -> None:
    """A structured abstract written with headings is still read apart."""
    report = written(
        project,
        "# Abstract\n\n## Results\n\nThe ROR was raised.\n\n"
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR compares groups.\n",
    )
    assert "in the abstract" in " ".join(found(report, "abbreviation-undefined"))


def test_a_supplement_is_held_to_its_own_abbreviations(project: Path) -> None:
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n",
        supplement="# Supplementary methods\n\nThe PRR was computed as a check.\n",
    )
    (message,) = found(report, "abbreviation-undefined")
    assert "PRR" in message and "supplement" in message


# ---------------------------------------------------------------- what counts as a definition


@pytest.mark.parametrize(
    "definition",
    [
        "The reporting odds ratio (ROR) was computed.",
        "The ROR (reporting odds ratio) was computed.",
        "The ROR (the reporting odds ratio) was computed.",
        "The reporting odds ratio (ROR; a measure of disproportionality) was computed.",
        "The reporting odds ratio (*ROR*) was computed.",
        "The reporting odds\nratio (ROR) was computed.",
        "Reporting Odds Ratio (ROR) was computed.",
    ],
)
def test_both_orders_of_a_definition_are_read(project: Path, definition: str) -> None:
    report = written(project, f"# Methods\n\n{definition} The ROR compares groups.\n")
    assert not report.findings, found(report)


def test_a_definition_in_square_brackets_is_read(project: Path) -> None:
    """The form a journal uses inside a parenthesis, where round brackets would nest."""
    configured(project, language={"known_abbreviations": []})
    report = written(
        project,
        "# Results\n\nThe risk was lower with treatment (hazard ratio [HR], 0.75; 95% "
        "confidence interval [CI], 0.60 to 0.94). The HR was stable and the CI was narrow.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "definition",
    [
        # An exercise physiology preprint of the real-paper corpus.
        "We measured endurance (i.e. time to task failure; TTF) in all.",
        "We measured endurance (that is, time to task failure, TTF) in all.",
        "We measured endurance [i.e. time to task failure; TTF] in all.",
        "We measured endurance (i.e. time to task failure; *TTF*) in all.",
    ],
)
def test_a_short_form_closing_a_bracket_after_a_separator_is_defined(
    project: Path, definition: str
) -> None:
    report = written(project, f"# Methods\n\n{definition} The TTF was long.\n")
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "dash",
    [" - ", " \N{EN DASH} ", " \N{EM DASH} ",
     # Pandoc's smart dashes as typed, and a no-break space before the dash, as Word keeps
     # a dash on the line of the word before it.
     " -- ", " --- ", "\N{NO-BREAK SPACE}\N{EN DASH} ", "\N{NO-BREAK SPACE}- "],
)  # fmt: skip
def test_a_short_form_after_a_spaced_dash_is_defined(project: Path, dash: str) -> None:
    """An agricultural-policy preprint of the real-paper corpus: "the Basic Income Support
    for Sustainability - BISS", with no bracket."""
    report = written(
        project,
        f"# Methods\n\nFarmers received the Basic Income Support for Sustainability{dash}"
        "BISS, from the state. The BISS was paid.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "value",
    [", 1.52 (95% CI 1.1-2.0)", ": 1.52 (95% CI 1.1-2.0)",
     " (95% CI 1.1\N{EN DASH}2.0) 1.52", "\N{NO-BREAK SPACE}1.52 (95% CI 1.1-2.0)"],
)  # fmt: skip
def test_a_short_form_after_a_dash_with_a_comma_and_a_number_is_a_statistic(
    project: Path, value: str
) -> None:
    """Rounds 1 and 2 of #623: "older people - OR, 1.52" was read as a second definition of
    OR, as "older people", where it gives the odds ratio's value; so were the value after a
    colon, after an interval in brackets and after a no-break space."""
    configured(project, language={"known_abbreviations": ["CI"]})
    report = written(
        project,
        "# Results\n\nThe odds ratio (OR) was computed. The risk was higher in older people "
        "\N{EN DASH} OR" + value + ".\n",
    )
    assert not report.findings, found(report)


def test_a_short_form_after_a_dash_and_a_comma_before_words_is_defined(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nFarmers joined the Basic Payment Scheme \N{EN DASH} BPS, which pays "
        "farmers. The BPS was paid.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "ending",
    [". It pays farmers.", "; it pays farmers.", ") to pay farmers.", "] to pay farmers.",
     ", which pays farmers.", ",\nwhich pays farmers.", "**. It pays farmers.",
     "\N{RIGHT DOUBLE QUOTATION MARK}, which pays farmers.", "\n\nIt pays farmers.", "",
     # Round 1 of #643: a citation passed over, a colon and a word, a closing spaced dash,
     # and a hard line break, a backslash or two spaces.
     " [@smith2020]. It pays farmers.", " [@smith2020; @jones2021]. It pays farmers.",
     " [12]. It pays farmers.", " [1, 3\N{EN DASH}5]; it pays farmers.", "^3^. It pays farmers.",
     ": farmers received it.", " \N{EN DASH} which pays farmers \N{EN DASH} began.",
     "\\\nIt pays farmers.", "  \nIt pays farmers."],
)  # fmt: skip
def test_a_dash_defines_where_its_short_form_ends_the_clause(project: Path, ending: str) -> None:
    """The author's decision of 2026-11-12: a dash defines where the short form is followed
    by a stop, a semicolon, a closing bracket, a comma or a colon and a word, a closing dash,
    a hard line break, or the end of its paragraph, a closing quote or emphasis mark and a
    citation between them allowed."""
    opening = {")": "(", "]": "[", "*": "**", "\N{RIGHT DOUBLE QUOTATION MARK}":
               "\N{LEFT DOUBLE QUOTATION MARK}"}.get(ending[:1], "")  # fmt: skip
    report = written(
        project,
        f"# Methods\n\nFarmers joined {opening}the Basic Payment Scheme \N{EN DASH} BPS"
        f"{ending}\n\n# Results\n\nThe BPS was paid.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    ("value", "reported"),
    # The final check of #623 (an agricultural-policy preprint of the real-paper corpus
    # led there): an interval in square brackets before the value, "≈", "of", and the
    # value on the next line of the paragraph; a decimal point, a colon and a number, and a
    # bracket of numbers before a number.
    [(" [95% CI 1.1\N{EN DASH}2.0] 1.52", set()), (" \N{ALMOST EQUAL TO} 1.52", set()),
     (" of 1.52", set()), ("\n1.52", set()), (" .52", set()), (": 1.52", set()),
     (" [2] 1.52", set()),
     # Round 2 of #643: a value bound to the results where the number would be, after a
     # space, a colon, a comma, a closing dash or a line break, the binding blanked to two
     # spaces before the line's end; and a number after a closing dash.
     (" {{results.or}}", set()), (": {{results.or}}", set()), (", {{results.or}}", set()),
     (" \N{EN DASH} {{results.or}}", set()), ("\n{{results.or}}", set()),
     (" {{results.or}}\n", set()), (" \N{EN DASH} 1.52", set()),
     # A limit written down in DESIGN.md's Known gaps (rounds 1 and 2 of #643): a comma or
     # a colon and a letter, and a semicolon, end the clause, so these are read as a second
     # definition.
     (", p < 0.001", {"abbreviation-redefined", "abbreviation-unused"}),
     (": p < 0.001", {"abbreviation-redefined", "abbreviation-unused"}),
     ("; 95% CI 1.1\N{EN DASH}2.0", {"abbreviation-redefined", "abbreviation-unused"})],
)  # fmt: skip
def test_a_statistic_after_a_dash_defines_nothing_whatever_its_shape(
    project: Path, value: str, reported: set[str]
) -> None:
    configured(project, language={"known_abbreviations": ["CI"]})
    report = written(
        project,
        "# Results\n\nThe odds ratio (OR) was computed. The risk was higher in older people "
        "\N{EN DASH} OR" + value + " in all.\n",
    )
    assert codes(report) == reported, found(report)


@pytest.mark.parametrize(
    "written_as",
    ["the Basic Payment Scheme \N{EN DASH} BPS was introduced in 2015.",
     "the Basic Payment Scheme \N{EN DASH} BPS\nwas introduced in 2015.",
     "the Basic Payment Scheme \N{EN DASH} BPS \nwas introduced in 2015.",
     # A citation with words in it, a locator or a prefix, is words of the sentence.
     "the Basic Payment Scheme \N{EN DASH} BPS [@ec2013, p. 3].",
     "the Basic Payment Scheme \N{EN DASH} BPS [see @ec2013]."],
)  # fmt: skip
def test_a_dash_definition_that_does_not_end_its_clause_defines_nothing(written_as: str) -> None:
    """A limit written down in DESIGN.md's Known gaps: a short form after a dash with more
    after it than the end of its clause is not read as defined there."""
    read = _file(0, Path("main.md"), f"# Methods\n\n{written_as}\n", [], False)
    assert "BPS" not in [short for _at, short, _long in read.definitions]


@pytest.mark.parametrize(
    "written_as",
    ["the Basic Payment Scheme \N{EN DASH} BPS",
     "| Scheme | n |\n|---|---|\n| the Basic Payment Scheme \N{EN DASH} BPS | 3 |",
     "- the Basic Payment Scheme \N{EN DASH} BPS\n- the Common Agricultural Policy",
     "1. the Basic Payment Scheme \N{EN DASH} BPS\n2. the Common Agricultural Policy",
     "> - the Basic Payment Scheme \N{EN DASH} BPS\n> - the Common Agricultural Policy",
     "- the Basic Payment Scheme \N{EN DASH} BPS [@ec2013]\n- the Common Agricultural Policy"],
)  # fmt: skip
def test_a_dash_defines_at_the_end_of_the_text_a_cell_or_a_list_item(written_as: str) -> None:
    """Round 1 of #643: the end of the text, a table cell's bar and the end of a list item's
    line each end the clause, as the end of a paragraph does."""
    read = _file(0, Path("main.md"), written_as, [], False)
    assert "BPS" in [short for _at, short, _long in read.definitions]


@pytest.mark.parametrize("heading", ["# Methods", "# Abbreviations"])
def test_a_list_written_long_form_first_defines_each_entry(project: Path, heading: str) -> None:
    """Round 1 of #643: in a tight list every item but the last is followed by the next
    item's line, and none of them defined, outside a glossary's heading or under one."""
    report = written(
        project,
        f"{heading}\n\n- Basic Payment Scheme \N{EN DASH} BPS\n- Common Agricultural Policy "
        "\N{EN DASH} CAP\n- Single Area Payment Scheme \N{EN DASH} SAPS\n\n# Results\n\n"
        "The BPS, the CAP and the SAPS were paid.\n",
    )
    assert not report.findings, found(report)


def test_a_dash_defines_in_latex_before_a_citation_in_a_list_and_at_a_line_break(
    tmp_path: Path,
) -> None:
    """Round 1 of #643: LaTeX's `~\\cite{}` is blanked, `\\item` opens a list item's line and
    `\\\\` is left as two spaces before the line's end. A citation with a locator leaves its
    words, a limit written down in DESIGN.md's Known gaps."""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Methods}\n"
        "the Basic Payment Scheme -- BPS~\\cite{ec2013}. It pays.\n\n"
        "\\begin{itemize}\n\\item the Common Agricultural Policy -- CAP\n"
        "\\item the Single Area Payment Scheme -- SAPS\n\\end{itemize}\n\n"
        "the Young Farmer Scheme -- YFS\\\\\nIt pays.\n\n"
        "the Less Favoured Area -- LFA~\\citep[p.~3]{ec2013}. It pays.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    defined = {short for read in _latex_read(tmp_path, None)
               for _at, short, _long in read.definitions}  # fmt: skip
    assert {"BPS", "CAP", "SAPS", "YFS"} <= defined, defined
    assert "LFA" not in defined


@pytest.mark.parametrize(
    ("bound", "longs"),
    [(" \\mg{results.or}", ["odds ratio"]),
     # Round 1 of #662: a tie before the binding is a space, and an anchor prints nothing,
     # so the definition after it stands.
     ("~\\mg{results.or}", ["odds ratio"])],
)  # fmt: skip
def test_a_value_bound_after_a_dash_in_latex_is_a_statistic(
    tmp_path: Path, bound: str, longs: list[str]
) -> None:
    """Round 2 of #643: `\\mg{results.or}` after the short form is blanked as a binding is,
    and gives the odds ratio's value, as a number would."""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Results}\n"
        "The odds ratio (OR) was computed. The risk was higher in older people -- OR"
        f"{bound}. It held.\n\\end{{document}}\n",
        encoding="utf-8",
    )
    read = [long for read in _latex_read(tmp_path, None)
            for _at, short, long in read.definitions if short == "OR"]  # fmt: skip
    assert read == longs, read


def test_an_anchor_after_a_dash_s_short_form_leaves_its_definition_standing(
    tmp_path: Path,
) -> None:
    """Round 1 of #662: `\\mg{method.odds}` prints nothing, so it is no value, and the short
    form before it ends its clause at the stop."""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Methods}\n"
        "Farmers were paid under the Basic Payment Scheme -- BPS \\mg{method.payments}. It "
        "held.\n\\end{document}\n",
        encoding="utf-8",
    )
    assert "BPS" in [short for read in _latex_read(tmp_path, None)
                     for _at, short, _long in read.definitions]  # fmt: skip


@pytest.mark.parametrize(
    ("written_as", "short"),
    [
        # A lazy continuation, unindented, in an item above.
        ("- the Farming Fund\nstill paid\n- the Woodland Grant Scheme \N{EN DASH} WGS\n- the "
         "Woodland Fund", "WGS"),
        # A list straight under a lead-in line: one paragraph to pandoc, its next item's dash
        # after the line break.
        ("The schemes were:\n- Basic Payment Scheme \N{EN DASH} BPS\n- Common Agricultural "
         "Policy \N{EN DASH} CAP", "BPS"),
        # Round 2 of #662: the same with another marker, a next item opening with a digit,
        # and in a block quote; and an item long past the lookback.
        *((f"The schemes were:\n{one} Basic Payment Scheme \N{EN DASH} BPS\n{two} Common "
           "Agricultural Policy \N{EN DASH} CAP", "BPS")
          for one, two in (("*", "*"), ("1.", "2."), ("1)", "2)"))),
        ("The schemes were:\n- Basic Payment Scheme \N{EN DASH} BPS\n- 2015 reform of the CAP",
         "BPS"),
        ("> The schemes were:\n> - Basic Payment Scheme \N{EN DASH} BPS\n> - Common "
         "Agricultural Policy \N{EN DASH} CAP", "BPS"),
        ("1. the Farming Fund\n" + "still paid\n" * 250 + "2. the Woodland Grant Scheme "
         "\N{EN DASH} WGS\n* the Woodland Fund", "WGS"),
        # A binding that prints no value: an anchor, and a pointer.
        ("Farmers were paid under the Basic Payment Scheme \N{EN DASH} BPS "
         "{{method.payments}}.", "BPS"),
        ("Farmers were paid under the Basic Payment Scheme \N{EN DASH} BPS "
         "{{ref.table.payments}}.", "BPS"),
    ],
)
def test_a_dash_defines_under_a_lazy_line_a_lead_in_or_before_a_binding_of_no_value(
    written_as: str, short: str
) -> None:
    """Round 1 of #662: each of these defined before #662, and must still."""
    read = _file(0, Path("main.md"), f"# Methods\n\n{written_as}\n", [], False)
    assert short in [found for _at, found, _long in read.definitions]


def test_a_closing_dash_before_a_bracket_defines_nothing() -> None:
    """A limit written down in DESIGN.md's Known gaps (round 1 of #662): after a closing dash
    a word is asked for, as after a comma, so a bracket there ends no clause."""
    read = _file(0, Path("main.md"), "# Methods\n\nThe Basic Payment Scheme \N{EN DASH} BPS "
                 "\N{EN DASH} (2015 onwards) replaced it.\n", [], False)  # fmt: skip
    assert "BPS" not in [short for _at, short, _long in read.definitions]


@pytest.mark.parametrize(
    "written_as",
    [
        # A list item hard-wrapped, its next line indented or not.
        "- the risk was higher in older people \N{EN DASH} OR\n  1.52 in all.",
        "- the risk was higher in older people \N{EN DASH} OR\n1.52 in all.",
        # A line in the middle of a paragraph that opens as a list item would.
        "Rates rose until\n2020) in older people \N{EN DASH} OR\n- 1.52 in all.",
        "Rates rose in group\n3. in older people \N{EN DASH} OR\n- 1.52 in all.",
    ],
)
def test_a_list_item_goes_on_past_its_line_into_its_continuation(written_as: str) -> None:
    """Round 2 of #643: a list item ends where its line ends only when the next line is no
    continuation of it, and a prose line that opens "2020) " or "3. " is no list item."""
    read = _file(0, Path("main.md"), f"# Results\n\n{written_as}\n", [], False)
    assert "OR" not in [short for _at, short, _long in read.definitions]


def test_a_nested_or_continued_list_item_still_ends_at_its_line() -> None:
    """The items around a nested list, and an item after one with a continuation line,
    end where their lines do."""
    text = ("- the Basic Payment Scheme \N{EN DASH} BPS\n  - the Single Area Payment "
            "\N{EN DASH} SAP\n- the Common Agricultural Policy \N{EN DASH} CAP\n  still paid\n"
            "- the Young Farmer Scheme \N{EN DASH} YFS\n- the Area Payment")  # fmt: skip
    read = _file(0, Path("main.md"), f"# Methods\n\n{text}\n", [], False)
    assert [short for _at, short, _long in read.definitions] == ["BPS", "SAP", "YFS"]


def test_a_dash_short_form_with_words_after_it_is_reported_undefined(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe Basic Payment Scheme \N{EN DASH} BPS was introduced. The BPS "
        "was paid.\n",
    )
    assert codes(report) == {"abbreviation-undefined"}, found(report)


@pytest.mark.parametrize(
    "sentence",
    [
        # The letters of the short form are not before the separator.
        "Signals were sought (see the appendix; PRR) in all. The PRR was raised.",
        # A dash with no space, a hyphenated word; and a statistic after a dash.
        "Signals were sought by proportional reporting-PRR in all. The PRR was raised.",
        "The proportional reporting ratio fell \N{EN DASH} PRR 0.75 in all. The PRR was "
        "raised.",
        # Limits written down in DESIGN.md's Known gaps: the short form before the dash, and
        # a short form in the middle of a bracket.
        "The PRR \N{EN DASH} proportional reporting ratio \N{EN DASH} was sought. The PRR "
        "was raised.",
        "Signals were sought (as before, PRR, i.e. proportional reporting ratio). The PRR "
        "was raised.",
    ],
)
def test_a_bracket_s_end_or_a_dash_defines_only_by_the_letter_rule(
    project: Path, sentence: str
) -> None:
    report = written(project, f"# Methods\n\n{sentence}\n")
    assert codes(report) == {"abbreviation-undefined"}, found(report)
    assert all(f.message.startswith("PRR") for f in report.findings), found(report)


def test_markup_and_punctuation_are_no_part_of_a_long_form(project: Path) -> None:
    """An emphasised first definition and a plain second one are one meaning, and the hint
    quotes the words without their asterisks."""
    report = written(
        project,
        "# Methods\n\nThe *reporting odds ratio* (ROR) was computed. The ROR compares "
        "groups.\n\n# Discussion\n\nThe reporting odds ratio, (ROR) was raised.\n",
    )
    (message,) = found(report, "abbreviation-redefined")
    assert "defined again" in message, "not two meanings"
    unused = written(project, "# Methods\n\nThe **reporting odds ratio** (ROR) was computed.\n")
    (finding,) = unused.findings
    assert "'reporting odds ratio'" in finding.hint


def test_a_short_form_does_not_define_itself_through_its_plural(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nAssociations were expressed as ORs (OR, 95% CI). The OR was raised.\n",
    )
    assert codes(report) == {"abbreviation-undefined"}, found(report)


@pytest.mark.parametrize(
    ("definition", "use"),
    [
        ("Monoclonal antibodies (mAbs) were used.", "Each mAb was tested."),
        ("Monoclonal antibodies (mAbs) were used.", "The mAbs were tested."),
        ("A monoclonal antibody (mAb) was used.", "Two mAbs were tested."),
    ],
)
def test_a_plural_in_lower_case_is_the_singular_s(project: Path, definition: str, use: str) -> None:
    report = written(project, f"# Methods\n\n{definition} {use}\n")
    assert not report.findings, found(report)


def test_neither_a_bracket_nor_a_long_form_crosses_a_blank_line(project: Path) -> None:
    """Two paragraphs are two thoughts: a long form ending one does not define the bracket
    opening the next, and a bracket left open does not close in the next."""
    apart = written(
        project,
        "# Methods\n\nWe computed the reporting odds ratio\n\n(ROR) in each stratum. The ROR "
        "was raised.\n",
    )
    assert codes(apart) == {"abbreviation-undefined"}, found(apart)
    for opened, closed in ("()", "[]"):
        open_bracket = written(
            project,
            f"# Methods\n\nThe reporting odds ratio {opened}ROR;\n\nsee below{closed} was "
            "raised. The ROR was raised.\n",
        )
        assert codes(open_bracket) == {"abbreviation-undefined"}, found(open_bracket)


def test_definitions_are_read_in_the_order_they_stand(project: Path) -> None:
    """Square brackets are found in a second pass, and the first definition is still the
    one that stands first."""
    report = written(
        project,
        "# Results\n\nThe hazard ratio [HR] was 0.75. The HR was stable.\n\n# Discussion\n\n"
        "The hazard ratio (HR) fell.\n",
    )
    (finding,) = report.findings
    assert finding.code == "abbreviation-redefined"
    assert finding.line == 7
    assert "manuscript/main.md:3" in finding.message


def test_used_before_defined_names_the_first_use_and_the_first_definition(
    project: Path,
) -> None:
    report = written(
        project,
        "# Methods\n\nThe ROR was computed.\n\nThe ROR compares groups.\n\nThe reporting odds "
        "ratio (ROR) is a ratio. The ROR was raised.\n\nThe reporting odds ratio (ROR) fell.\n",
    )
    early = next(f for f in report.findings if f.code == "abbreviation-used-before-defined")
    assert early.line == 3
    assert "manuscript/main.md:7" in early.message


def test_a_lower_case_s_is_the_plural_s_only_after_a_plural_long_form() -> None:
    from manuscript_guard.gates.language import _stem

    assert _stem("scFvs", "single-chain variable fragments") == "scFv"
    assert _stem("scFvs", "single-chain variable fragment") == "scFvs"
    assert _stem("RORs", "reporting odds ratio") == "ROR", "after a capital it always is"


def test_a_plural_definition_defines_the_singular(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nIndividual case safety reports (ICSRs) were extracted. Each ICSR "
        "names a drug, and ICSRs naming several were counted once.\n",
    )
    assert not report.findings, found(report)


def test_a_hyphenated_use_is_a_use(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. ROR-based signals were "
        "listed.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    ("sentence", "named"),
    [
        ("Samples were analysed by LC-MS.", "LC-MS"),
        ("Clusters were drawn with t-SNE.", "t-SNE"),
        ("In the KEYNOTE-189 trial, survival was longer.", "KEYNOTE-189"),
        ("Levels of 25-OH-D were measured.", "25-OH-D"),
        ("ROR-based signals were listed.", "ROR"),
        ("Non-ROR signals were listed.", "ROR"),
    ],
)
def test_a_hyphenated_abbreviation_is_reported_whole(
    project: Path, sentence: str, named: str
) -> None:
    """Under the name its definition would use, and once: not `LC` and `MS`. An ordinary
    word joined to it is not part of the name."""
    report = written(project, f"# Methods\n\n{sentence}\n")
    (message,) = found(report, "abbreviation-undefined")
    assert message.split()[0] == named


def test_a_hyphenated_abbreviation_defined_whole_is_used_whole(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nLiquid chromatography-mass spectrometry (LC-MS) was used. LC-MS runs "
        "took an hour.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "text",
    ["The *Licence avec Accès Santé* (L.AS) admits students, and L.AS students were "
     "eligible.",
     "The L.AS (Licence avec Accès Santé) admits students; L.AS students were eligible.",
     "# Abbreviations\n\n- **L.AS**: Licence avec Accès Santé\n\n# Methods\n\nL.AS students "
     "were eligible."],
    ids=["short form in the bracket", "long form in the bracket", "a glossary's entry"],
)  # fmt: skip
def test_a_short_form_a_stop_joins_is_defined_and_used_whole(project: Path, text: str) -> None:
    """The author's paper defines "Licence avec Accès Santé (L.AS)" and uses L.AS eight
    times: read at its stop, it was `AS`, used and never defined. A stop between two parts of
    a word joins them as a hyphen does."""
    report = written(project, f"# Methods\n\n{text}\n")
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    ("sentence", "named"),
    [("Students of L.AS were eligible.", "L.AS"),
     ("The score rose in the KAP.The rest fell.", "KAP"),
     ("The U.S. and the U.K. data, i.e. the KAP cohort.", "KAP"),
     ("The rule follows the GDPR.12 here.", "GDPR"),
     ("The rule follows the GDPR.\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO} here.", "GDPR"),
     ("They were sent to the ICU.A total of 40 came back.", "ICU")],
    ids=["undefined, whole", "a sentence typed on", "initials of a country",
         "a reference number after the stop", "a superscript number after the stop",
         "a sentence typed on that opens with A"],
)  # fmt: skip
def test_a_word_with_a_stop_is_read_by_its_parts(
    project: Path, sentence: str, named: str
) -> None:
    """An undefined short form a stop joins is reported whole, as a hyphenated one is; a
    sentence typed on with no space after an abbreviation leaves the abbreviation alone;
    and "U.S." is no abbreviation, its letters one to a part. A stop before a number joins
    nothing: "GDPR.12" is GDPR with a reference number typed on (round 1 of #612)."""
    report = written(project, f"# Methods\n\n{sentence}\n")
    (message,) = found(report, "abbreviation-undefined")
    assert message.split()[0] == named


@pytest.mark.parametrize(
    "text",
    ["The score rose.ROR (reporting odds ratio) was high. The ROR fell.",
     "Severe acute respiratory syndrome coronavirus 2 (SARS-CoV-2) and SARS-CoV-2.B.1.1.7 "
     "spread.",
     "BA.1 and BA.2 spread."],
    ids=["a definition after a sentence typed on", "a lineage after a defined name",
         "a lineage's number after its stop"],
)  # fmt: skip
def test_a_stop_before_a_number_or_a_definition_reads_as_on_main(
    project: Path, text: str
) -> None:
    """A stop joins two parts only where a letter follows it, and a short form before a
    bracket that defines nothing with a stop in it is tried again from its last stop
    (round 1 of #612): ROR is defined, SARS-CoV-2 is used, and BA is one abbreviation."""
    report = written(project, f"# Methods\n\n{text}\n")
    said = [f.message.split()[0] for f in report.findings]
    assert said == (["BA"] if text.startswith("BA") else []), found(report)


@pytest.mark.parametrize(
    "text",
    [
        "RNA sequencing (RNA-seq) libraries were prepared; RNA-seq reads were aligned.",
        "Non-high-density lipoprotein cholesterol (non-HDL-C) was the outcome. Mean "
        "non-HDL-C fell.",
        "Chromatin immunoprecipitation sequencing (ChIP-seq) was done. ChIP-seq peaks were "
        "called.",
        "Anti-factor Xa activity (anti-FXa) was measured. The anti-FXa level rose.",
    ],
)
def test_a_name_that_holds_an_ordinary_word_is_still_one_name(project: Path, text: str) -> None:
    """Looked for whole before the word is split at `seq` or `non`. Split first, the
    definition was reported as unused and its capitals as undefined."""
    report = written(project, f"# Methods\n\n{text}\n")
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "text",
    [
        "Non-high-density lipoprotein cholesterol (non-HDL-C) was the outcome. Mean "
        "non-HDL-C fell. Non-HDL-C was lower in women.",
        "Anti-factor Xa activity (anti-FXa) was measured. The anti-FXa level rose. Anti-FXa "
        "activity was stable.",
        "We measured non-high-density lipoprotein cholesterol (non-HDL-C) and high-density "
        "lipoprotein cholesterol (HDL-C). HDL-C rose. Non-HDL-C fell.",
    ],
)
def test_a_name_takes_a_capital_at_the_start_of_a_sentence(project: Path, text: str) -> None:
    """`Non-HDL-C` is `non-HDL-C`. Matched only as written, the word was split at `Non`,
    and `HDL-C` was reported as undefined, or `non-HDL-C` as unused."""
    report = written(project, f"# Methods\n\n{text}\n")
    assert not report.findings, found(report)


def test_the_capitals_of_a_name_are_the_name(project: Path) -> None:
    """Only an ordinary word opening the name is lowered: `Rna-seq` is not `RNA-seq`."""
    report = written(
        project,
        "# Methods\n\nRNA sequencing (RNA-seq) libraries were prepared. Rna-seq reads were "
        "aligned.\n",
    )
    assert codes(report) == {"abbreviation-unused"}, found(report)


def test_a_listed_name_takes_a_capital_at_the_start_of_a_sentence(project: Path) -> None:
    """The same for a name the project lists as for one the manuscript defines."""
    text = "# Methods\n\nMean values fell. Non-HDL-C was lower in women.\n"
    (message,) = found(written(project, text))
    assert message.startswith("HDL-C is used once")
    configured(project, language={"known_abbreviations": ["non-HDL-C"]})
    assert not written(project, text).findings


def test_the_plural_of_a_name_takes_the_capital_too(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nPatients not on immune checkpoint inhibitors (non-ICI) were controls. "
        "The non-ICI group was older. Non-ICIs were excluded.\n",
    )
    assert not report.findings, found(report)


def test_a_name_inside_a_longer_word_takes_the_capital_too(project: Path) -> None:
    """Wherever in the word the name opens, not only at its head."""
    report = written(
        project,
        "# Methods\n\nNon-high-density lipoprotein cholesterol (non-HDL-C) was the outcome. "
        "Mean non-HDL-C fell. Post-Non-HDL-C values rose.\n",
    )
    assert not report.findings, found(report)


def test_a_single_letter_opening_a_name_is_not_lowered(project: Path) -> None:
    """A known gap, held so that closing it is a decision: an ordinary word has two letters
    or more, so `T-PA` opening a sentence is not `t-PA`."""
    report = written(
        project,
        "# Methods\n\nTissue plasminogen activator (t-PA) was given. The t-PA dose was fixed. "
        "T-PA was stopped early.\n",
    )
    (message,) = found(report)
    assert message.startswith("T-PA is used once")


def test_the_longest_defined_name_is_the_one_used(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nNon-high-density lipoprotein (non-HDL) and non-high-density "
        "lipoprotein cholesterol (non-HDL-C) were measured. The non-HDL fraction and "
        "non-HDL-C fell.\n",
    )
    assert not report.findings, found(report)


def test_a_name_used_only_among_the_acknowledgements_is_used(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nRNA sequencing (RNA-seq) libraries were prepared.\n\n"
        "# Acknowledgements\n\nWe thank the RNA-seq core.\n",
    )
    assert not report.findings, found(report)


def test_a_subscript_exempts_the_word_it_follows_and_no_other(project: Path) -> None:
    """`CO` here is not `CO~2~`: the subscript further on belongs to another word."""
    report = written(project, "# Methods\n\nCO was measured in air, and H~2~O in water.\n")
    (message,) = found(report, "abbreviation-undefined")
    assert message.startswith("CO is used once")


def test_a_listed_name_that_holds_an_ordinary_word_is_honoured(project: Path) -> None:
    configured(
        project,
        language={"known_abbreviations": ["EMPEROR-Preserved"]},
        reporting_guideline=["DEMO-OBS", "ROBINS-Exposure"],
    )
    report = written(
        project,
        "# Methods\n\nIn EMPEROR-Preserved, events fell. We followed the ROBINS-Exposure "
        "tool.\n",
    )
    assert not report.findings, found(report)


def test_the_plural_of_a_listed_abbreviation_is_listed(project: Path) -> None:
    """Any final `s`, as for a defined one: an inhibitor class ends in a lower-case `i`."""
    text = "# Methods\n\nPARPis and SGLT2is were used, and one HDACi.\n"
    assert len(found(written(project, text), "abbreviation-undefined")) == 3
    configured(project, language={"known_abbreviations": ["PARPi", "SGLT2i", "HDACi"]})
    assert not written(project, text).findings


def test_a_defined_part_of_a_hyphenated_word_is_a_use(project: Path) -> None:
    """`ROR-PRR` with ROR defined: ROR is used, and PRR is what is missing."""
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. ROR-PRR agreement was "
        "good.\n",
    )
    (message,) = found(report)
    assert message.startswith("PRR is used once")


def test_a_hyphenated_name_is_defined_and_used_whole(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe Middle East respiratory syndrome coronavirus (MERS-CoV) was the "
        "comparator. MERS-CoV reports were fewer.\n",
    )
    assert not report.findings, found(report)


def test_a_definition_in_one_file_serves_the_next(project: Path) -> None:
    """`main.md` is printed first, whatever the other files are called."""
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed.\n",
        **{"1_results": "# Results\n\nThe ROR was raised.\n"},
    )
    assert not report.findings, found(report)


def test_a_supplement_inherits_the_main_text(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR compares groups.\n",
        supplement="# Supplementary methods\n\nThe ROR was recomputed by year.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "aside",
    [
        "The median was raised (IQR 2.1 to 4.3) in every stratum.",
        "The ROR (see the odds ratio results) was raised.",
        "The estimate was raised (ROR) throughout.",
        "The ROR (calculated as described in the interval methods) was raised.",
    ],
)
def test_a_bracket_that_defines_nothing_is_not_a_definition(project: Path, aside: str) -> None:
    """Read as a definition, each of these would turn `undefined` into `unused` or hide it."""
    report = written(project, f"# Results\n\n{aside}\n")
    assert codes(report) == {"abbreviation-undefined"}, found(report)


def test_the_long_form_is_matched_letter_by_letter() -> None:
    assert _long_form("ROR", "we computed the reporting odds ratio") == "reporting odds ratio"
    assert _long_form("DILI", "cases of drug-induced liver injury") == "drug-induced liver injury"
    assert _long_form("ROR", "the estimate was high") is None
    assert _long_form("ROR", "the ROR") is None, "a short form does not define itself"


@pytest.mark.parametrize("value", [" = 0.41", "=0.41", " 0.41"])
def test_a_statistic_in_brackets_is_not_a_definition(project: Path, value: str) -> None:
    """A short form followed by an equals sign or a number is a statistic and defines
    nothing, though "and older adults" holds the letters of AOR in order."""
    report = written(
        project,
        "# Results\n\nThe adjusted odds ratio (AOR) was computed for each group. Use was "
        f"lower among the young and older adults (AOR{value}, 95% CI 0.22 to 0.77).\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize("value", [": 0.41", ":0.41", ": {{results.aor}}"])
def test_a_statistic_after_a_colon_is_read_by_its_letters_as_on_main(
    project: Path, value: str
) -> None:
    """Known gap, held where it stands: a short form followed by a colon is read by its
    letters, as any short form is, a statistic or not. "and older adults" holds A, O and R
    in order, so "(AOR: 0.41)" defines AOR a second time, as it did before, and the
    definitions are all its uses."""
    report = written(
        project,
        "# Results\n\nThe adjusted odds ratio (AOR) was computed for each group. Use was "
        f"lower among the young and older adults (AOR{value}, 95% CI 0.22 to 0.77).\n",
    )
    assert codes(report) == {"abbreviation-redefined", "abbreviation-unused"}, found(report)


@pytest.mark.parametrize(
    ("text", "long"),
    [
        ("The reporting odds ratio (ROR: 3.84, 95% CI 2.10 to 7.02) was high.",
         "reporting odds ratio"),
        ("The *reporting odds ratio* (ROR: 3.84) was high.", "reporting odds ratio"),
        ("The estimated glomerular filtration rate (eGFR: ml/min/1.73 m2) fell.",
         "estimated glomerular filtration rate"),
        ("Drug-induced liver injury (DILI: 12 cases) was rare.", "Drug-induced liver injury"),
        ("Type 2 diabetes mellitus (T2DM: 40%) was common.", "Type 2 diabetes mellitus"),
        ("Their reporting odds ratios (RORs: 3.8 and 4.1) were high.",
         "reporting odds ratios"),
        ("The reporting odds ratio (RORs: 3.8 and 4.1) was high in both.",
         "reporting odds ratio"),
        # Letters that are not one per word, read as any long form is.
        ("Creatinine clearance (CrCl: 58 mL/min) was reduced.", "Creatinine clearance"),
        ("The interquartile range (IQR: 3\N{EN DASH}7) was wide.", "interquartile range"),
        ("The Medical Dictionary for Regulatory Activities (MedDRA: 26.0) was used.",
         "Medical Dictionary for Regulatory Activities"),
        # A last word that does not hold the short form's last letter.
        ("The Hamilton Depression Rating Scale (HAM-D: 18) was high.",
         "Hamilton Depression Rating Scale"),
        ("The Charlson Comorbidity Index score (CCI: 2) was low.",
         "Charlson Comorbidity Index score"),
        ("The estimated glomerular filtration rate at baseline (eGFR: 58) was low.",
         "estimated glomerular filtration rate at baseline"),
        ("We estimated the hazard ratio for death (HR: 1.3) in each group.",
         "hazard ratio for death"),
    ],
)  # fmt: skip
def test_a_short_form_before_a_colon_defines_by_its_letters(text: str, long: str) -> None:
    """How pharmacovigilance writes a first estimate: "reporting odds ratio (ROR: 3.84)". A
    short form followed by a colon defines where its letters are found before the bracket,
    as any short form does."""
    short = re.match(r"[^\W_]+(?:-[^\W_]+)*", text[text.index("(") + 1 :])[0]
    definitions = [(found, words) for _at, found, words in _definitions(text)]
    assert definitions == [(short.removesuffix("s"), long)], definitions


@pytest.mark.parametrize(
    "text",
    [
        "Use was lower in the young and older adults (AOR = 0.41).",
        "Use was lower in the young and older adults (AOR 0.41).",
    ],
)
def test_a_statistic_after_an_equals_sign_or_a_number_defines_nothing(text: str) -> None:
    """The letters of AOR are in "and older adults" in order, which is how a definition is
    found; after an equals sign or a number the bracket is a statistic's."""
    assert _definitions(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "Treatment was associated with a higher risk (HR 1.32, 95% CI 1.10 to 1.58).",
        "Treatment was associated with a higher risk (HR = 1.32, 95% CI 1.10 to 1.58).",
        "Exposure carried a reduced risk (RR 0.71).",
        "Use carried higher odds of readmission (OR 1.52).",
        "In the second cohort the odds ratio (OR 1.5) was lower.",
        "The reporting odds ratio (ROR = 3.84) was high.",
        "The reporting odds ratio (ROR 3.84) was high.",
    ],
)
def test_a_short_form_before_a_number_or_an_equals_sign_defines_nothing(text: str) -> None:
    """A statistic's bracket: "a higher risk (HR 1.32, ...)" begins with the letters of HR,
    and is no definition of it. Read as one, it was a second definition after "the hazard
    ratio (HR)", and a definition where there was none."""
    assert _definitions(text) == []


@pytest.mark.parametrize(
    ("text", "codes_found"),
    [
        ("The hazard ratio (HR) was estimated. Treatment was associated with a higher risk "
         "(HR 1.32, 95% CI 1.10 to 1.58).", set()),
        ("Treatment was associated with a higher risk (HR 1.32, 95% CI 1.10 to 1.58). The "
         "HR was stable.", {"abbreviation-undefined"}),
        ("The odds ratios (ORs) were estimated. In the second cohort the odds ratio (OR 1.5) "
         "was lower.", set()),
        ("Creatinine clearance (CrCl: 58 mL/min) was reduced. Creatinine clearance (CrCl) "
         "fell further, and CrCl was lowest at discharge.", {"abbreviation-redefined"}),
        ("The interquartile range (IQR: 3\N{EN DASH}7) was wide. The IQR was narrower "
         "later.", set()),
    ],
)  # fmt: skip
def test_what_a_statistic_s_bracket_leaves_defined(
    project: Path, text: str, codes_found: set[str]
) -> None:
    """A statistic after a number is no second definition, nor a first; a short form after a
    colon whose letters are not one per word is still a definition."""
    report = written(project, f"# Results\n\n{text}\n")
    assert codes(report) == codes_found, found(report)


@pytest.mark.parametrize(
    ("text", "short"),
    [
        ("The Hospital Anxiety and Depression Scale (French version) (HADS) was used.", "HADS"),
        ("The body mass index (in kg/m2) (BMI) was recorded.", "BMI"),
        ("Programmed cell death protein 1 (PD-1) or its ligand (PD-L1) was raised.", "PD-L1"),
    ],
)
def test_a_long_form_steps_back_past_a_bracket_it_would_open(text: str, short: str) -> None:
    """The nearest `S` of HADS is in "version", inside a bracket the long form would open:
    the bracket is passed over and the letter looked for before it, in "Scale"."""
    assert short in [found for _at, found, _long in _definitions(text)]


def test_a_statistic_in_brackets_does_not_stand_in_for_a_definition(project: Path) -> None:
    report = written(
        project,
        "# Results\n\nUse was lower among older adults (AOR 0.41). The AOR was stable.\n",
    )
    assert codes(report) == {"abbreviation-undefined"}, found(report)


@pytest.mark.parametrize(
    "text",
    [
        "A warning score was taken at entry (WSE1) and 40 (12.5%) had a second WSE (WSE2).",
        "A warning score was taken at entry (WSE1) and 40 [12.5%] had a second WSE (WSE2).",
    ],
)
def test_a_long_form_takes_no_letter_from_inside_a_bracket_it_opens(text: str) -> None:
    """The letters of `WSE2` are all there before its bracket, its `2` in a percentage and
    the rest in another short form: the long form would run into an aside."""
    assert "WSE2" not in [short for _at, short, _long in _definitions(text)]
    assert _long_form("WSE2", text[: text.rindex("(")]) is None


@pytest.mark.parametrize(
    ("text", "short", "long"),
    [
        # A short form made from another: the WSE taken after two hours.
        ("The score was taken at entry (WSE1) and after 2 hours (WSE2).", "WSE2",
         "WSE1) and after 2 hours"),
        ("A warning score (WSE) at 15 minutes (WSE1) was taken.", "WSE1",
         "WSE) at 15 minutes"),
        # A whole bracket none of the letters is in.
        ("The adjusted (for sex) relative risk (aRR) was low.", "aRR",
         "adjusted (for sex) relative risk"),
    ],
)  # fmt: skip
def test_a_long_form_may_close_a_bracket_or_hold_a_whole_one(
    text: str, short: str, long: str
) -> None:
    assert (short, long) in [(found, words) for _at, found, words in _definitions(text)]


def test_the_limits_of_the_bracket_rules_are_as_design_md_says() -> None:
    """Known gaps, held where they stand: after a colon, a short form is read by its letters,
    a statistic or not, so words that hold them in order define it; a colon before words is
    read the same way; and a comma makes no statistic."""

    def shorts(text: str) -> list[str]:
        return [short for _at, short, _long in _definitions(text)]

    assert shorts("It was associated with a higher risk (HR: 1.32, 95% CI 1.1 to 1.6).") == ["HR"]
    assert shorts("Use was lower in the young and older adults (AOR: 0.41).") == ["AOR"]
    assert shorts("Use was lower after adjusted odds ratio analysis (AOR: 0.41).") == ["AOR"]
    assert shorts("Physical activity (PA: walking or cycling) was low.") == ["PA"]
    assert shorts("Use was lower in the young and older adults (AOR, 0.41).") == ["AOR"]
    # Past the aside, the 2 of a count before it is a letter like any other.
    assert shorts("Scored at entry (WSE1) and 20 (12%) had a second WSE (WSE2).") == ["WSE2"]


def test_what_follows_the_long_form_may_hold_a_bracket(project: Path) -> None:
    """A citation between the long form and its short form is masked to an empty bracket,
    and the long form's letters do not cross it; a definition nested in a bracket that also
    gives a statistic is read, and so is a short form with a separator after it."""
    report = written(
        project,
        "# Results\n\nThe reporting odds ratio [@smith2020] (ROR) was raised. The ROR was "
        "high (Adjusted odds ratio (AOR): 0.52, 95% CI 0.30 to 0.88), and the AOR was "
        "stable. The proportional reporting ratio (PRR, 2.1) agreed, as the PRR did.\n",
    )
    assert not report.findings, found(report)


# ---------------------------------------------------------------- what must stay quiet


def test_ordinary_prose_has_nothing_to_report(project: Path) -> None:
    report = written(project, f"# Methods\n\n{PLAIN}\n")
    assert not report.findings, found(report)
    assert report.counts["abbreviations_read"] == 0


@pytest.mark.parametrize(
    "sentence",
    [
        "McNemar's test and the DeLong method were used.",
        "Samples were diluted in NaCl by a PhD student.",
        "Patients with type II diabetes in a phase III trial received factor VIII.",
        "DNA was extracted in the USA and the UK.",
        "SARS-CoV-2 and COVID-19 reports were excluded, as were HER2 and CYP3A4 terms.",
        "Reporting follows STROBE and the RECORD-PE extension.",
        "The model is in `ROR_MODEL` and at https://example.org/ROR/API.",
        "As reported [@RORStudyGroup2020], the ratio was raised.",
        "The ratio was {{results.ror.point}} overall.",
        "<!-- ROR to be defined once the Methods are settled -->\n\nThe ratio was raised.",
        "The ratio $ROR = ad/bc$ was computed.",
        "The solution of H2SO4 and NaHCO3 was saturated with CO2, then dried over MgSO4.",
        "CO~2~ and H~2~SO~4~ were bubbled through (NH~4~)~2~SO~4~, with NH~3~ and CH~4~.",
        "The CO\N{SUBSCRIPT TWO} was vented.",
        "Spectra were recorded at 400 MHz and 2 GPa in CDCl3, with 5 MBq of tracer.",
        "The trial is registered as NCT01234567 and the review as CRD42020123456.",
        "Reporting follows TRIPOD for the model and PRISMA for the search.",
        "![The PRR by drug](figures/prr.svg)",
        "![The PRR by drug [@fictionalClassSignal2019]](figures/prr.svg)",
        "![The PRR by drug][prr]\n\n[prr]: figures/prr.svg",
    ],
)
def test_what_is_not_an_abbreviation_is_not_reported(project: Path, sentence: str) -> None:
    report = written(project, f"# Methods\n\n{sentence}\n")
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "sentence",
    [
        "The IC50 was 12 nM.",  # element letters, and a count no formula has
        "The IC~50~ was 12 nM.",  # the same, typeset
        "HSV1 was isolated.",  # nobody writes a count of one
        "KOH was added.",  # a formula with nothing to tell it from an abbreviation
        "HCl was added.",  # the same: no count
        "PCa was diagnosed.",  # prostate cancer, which spells phosphorus and calcium
        "SCr was measured.",  # serum creatinine, which spells sulfur and chromium
        "The ABCDEFGHIJKLMNO score was raised.",  # as long as a short form may be
    ],
)
def test_what_only_looks_exempt_is_still_reported(project: Path, sentence: str) -> None:
    report = written(project, f"# Methods\n\n{sentence}\n")
    assert codes(report) == {"abbreviation-undefined"}, found(report)


def journal_asks(project: Path, rules: dict) -> None:
    """The example's journal profile, with `abbreviations:` set to `rules`."""
    path = project / "profiles" / "journals" / "demo-journal.yaml"
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    profile["abbreviations"] = rules
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")


STATISTICS = "# Results\n\nThe mean (SD) age was 54 (12), and an ANOVA and the RMSE were used.\n"


def test_a_statistical_abbreviation_on_the_list_needs_no_definition(project: Path) -> None:
    assert not written(project, STATISTICS).findings


@pytest.mark.parametrize(
    "sentence",
    [
        "The OR was 2.1 (95% CI 1.2 to 3.4).",  # journals that ask CI expanded: not listed
        "The HR and the IQR were given.",
        "The SE and the SEM were given.",  # SE is status epilepticus, SEM a microscope
    ],
)
def test_what_the_statistical_list_leaves_out_is_still_reported(
    project: Path, sentence: str
) -> None:
    configured(project, language={"known_abbreviations": []})
    report = written(project, f"# Results\n\n{sentence}\n")
    assert codes(report) == {"abbreviation-undefined"}, found(report)


def test_a_journal_that_asks_statistics_defined_has_them_reported(project: Path) -> None:
    journal_asks(project, {"define_statistics": True})
    report = written(project, STATISTICS)
    assert sorted(f.message.split()[0] for f in report.findings) == ["ANOVA", "RMSE", "SD"]


def test_a_journal_names_what_it_asks_defined(project: Path) -> None:
    """The example lists CI in paper.yaml; a journal that names it has it reported, and
    names nothing else."""
    journal_asks(project, {"define": ["CI", "SD"]})
    report = written(project, f"{STATISTICS}\nThe OR was 2.1 (95% CI 1.2 to 3.4).\n")
    assert sorted(f.message.split()[0] for f in report.findings) == ["CI", "OR", "SD"]


GLOSSARY_USES = "# Methods\n\nThe ROR, the PRR, the IC, the EBGM and the SDR were computed.\n"


@pytest.mark.parametrize(
    "heading", ["Abbreviations", "List of abbreviations", "GLOSSARY", "Acronyms",
                "List of Acronyms", "Abbreviations:", "[Abbreviations]{.underline}",
                "[[List of abbreviations]{.smallcaps}]{.mark}"],
)  # fmt: skip
def test_a_glossary_defines_its_entries(project: Path, heading: str) -> None:
    """A glossary's title is read as pandoc prints it, a span's words alone: pandoc writes
    an underlined Word heading as `# [Abbreviations]{.underline}`."""
    report = written(
        project,
        f"# {heading}\n\nROR = reporting odds ratio\nPRR: proportional reporting ratio\n\n"
        "- IC \N{EN DASH} information component\n- **EBGM**: empirical Bayes geometric "
        "mean\n\nSDR\n:   signal detection ratio\n\n" + GLOSSARY_USES,
    )
    assert not report.findings, found(report)


def test_a_glossary_in_one_paragraph_defines_each_entry(project: Path) -> None:
    """BMC's "List of abbreviations" runs its entries on in one paragraph, with a semicolon
    between them: each is an entry, and none takes the others into its long form (round 1
    of #446: "ROR is defined as 'reporting odds ratio; PRR: proportional reporting ratio'").
    A semicolon inside a long form, with no short form and sign after it, stays in it."""
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) and the proportional reporting ratio "
        "(PRR) were computed. The ROR and PRR rose.\n\n# Abbreviations\n\nROR: reporting "
        "odds ratio; PRR: proportional reporting ratio; IC: information component; see "
        "Methods\n\n# Results\n\nThe IC was computed for each pair. The IC was raised.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "glossary",
    ["ROR: reporting odds ratio; PRR: proportional\nreporting ratio; IC: information component",
     "ROR: reporting odds ratio; PRR:\nproportional reporting ratio; IC: information component",
     "ROR: reporting odds ratio;\nPRR: proportional reporting ratio; IC: information\ncomponent"],
    ids=["wrapped in a long form", "wrapped after a sign", "wrapped at a semicolon"],
)  # fmt: skip
def test_a_glossary_in_one_wrapped_paragraph_defines_each_entry(
    project: Path, glossary: str
) -> None:
    """The paragraph hard-wrapped in the source is one text: a wrap inside an entry kept the
    entries after it in its long form (round 2 of #446: "PRR is defined as 'proportional
    reporting ratio; IC: information component'", and IC undefined)."""
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) and the proportional reporting ratio "
        "(PRR) were computed. The ROR and PRR rose.\n\n# Abbreviations\n\n" + glossary
        + "\n\n# Results\n\nThe IC was computed for each pair. The IC was raised.\n",
    )
    assert not report.findings, found(report)


def test_a_definition_list_term_after_a_run_on_line_is_an_entry_of_its_own(
    project: Path,
) -> None:
    """A run-on line's paragraph ends at a line that opens an entry, a definition list's
    term among them, which only the `:` line under it makes one (round 3 of #446: asked
    with no line under it, "IC" ran on into PRR's long form, "proportional reporting
    ratio IC", and IC was lost)."""
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) and the proportional reporting ratio "
        "(PRR) were computed. The ROR and PRR rose.\n\n# Abbreviations\n\nROR: reporting "
        "odds ratio; PRR: proportional reporting ratio\nIC\n:   information component\n\n"
        "# Results\n\nThe IC was computed for each pair. The IC was raised.\n",
    )
    assert not report.findings, found(report)


def test_a_wrapped_glossary_entry_is_placed_on_its_own_source_line(project: Path) -> None:
    """The joined paragraph's offsets are the file's: IC's entry, on the second line of a
    wrapped paragraph, is named on that line where the text gives IC another meaning."""
    report = written(
        project,
        "# Abbreviations\n\nROR: reporting odds ratio; PRR: proportional\nreporting ratio; "
        "IC: information component\n\n# Methods\n\nThe ROR and the PRR were computed. The "
        "ROR and PRR rose.\n\n# Results\n\nThe intensive care (IC) unit was used. The IC was "
        "full.\n",
    )
    assert found(report) == [
        "IC is defined as 'intensive care' here and as 'information component' at "
        "manuscript/main.md:4"
    ]


def test_a_glossary_in_a_table_defines_its_entries(project: Path) -> None:
    report = written(
        project,
        "# Abbreviations\n\n| Abbreviation | Meaning |\n|---|---|\n| ROR | reporting odds "
        "ratio |\n| PRR | proportional reporting ratio |\n| IC | information component |\n"
        "| EBGM | empirical Bayes geometric mean |\n| SDR | signal detection ratio |\n\n"
        + GLOSSARY_USES,
    )
    assert not report.findings, found(report)


def test_a_glossary_is_a_definition_where_it_stands(project: Path) -> None:
    """A use above the glossary is used before its definition, as above any definition;
    the glossary's own lines are not uses, so an entry nothing else uses is unused; and
    what it does not list is undefined."""
    report = written(
        project,
        "# Introduction\n\nThe ROR was raised.\n\n# Abbreviations\n\nROR: reporting odds "
        "ratio\nPRR: proportional reporting ratio\n\n# Methods\n\nThe ROR and the SDR were "
        "computed.\n",
    )
    assert sorted((f.code, f.message.split()[0]) for f in report.findings) == [
        ("abbreviation-undefined", "SDR"),
        ("abbreviation-unused", "PRR"),
        ("abbreviation-used-before-defined", "ROR"),
    ]


#: A list of abbreviations as a paper typed in Word has it after its Conclusions, with no
#: title: a sentence, then letters' labels in bold and an item for each entry, an entry with
#: no capital among them (the author's paper, 2026-11-10).
WORD_GLOSSARY = (
    "List of abbreviations and acronyms used in the text, tables, and figures.\n\n"
    "**A--C**\n\n- **AIC**: Akaike Information Criterion\n\n- **CV**: Coefficient of "
    "Variation\n\n**D--I**\n\n- **df**: degrees of freedom\n\n- **EBM**: Evidence-based "
    "medicine\n\n"
)


def test_a_glossary_a_sentence_opens_defines_its_entries(project: Path) -> None:
    """The sentence opens a glossary: its entries are definitions where they stand, its
    lines are not uses, and an entry after the label of letters and the entry with no
    capital is one of them. A use above it is used before its definition, as above any."""
    uses = "# Methods\n\nThe AIC, the CV and the EBM were computed.\n\n"
    after = "# Conclusions\n\nIt worked.\n\n" + WORD_GLOSSARY
    assert not written(project, after + uses.replace("# Methods", "# Appendix")).findings
    report = written(project, uses + after)
    assert sorted((f.code, f.message.split()[0]) for f in report.findings) == [
        ("abbreviation-used-before-defined", "AIC"),
        ("abbreviation-used-before-defined", "CV"),
        ("abbreviation-used-before-defined", "EBM"),
    ]


def test_an_entry_of_the_list_is_said_as_one(project: Path) -> None:
    """The list's entries are said as such (the author's audit, 2026-11-11): a use above an
    entry the text never spells out is to be spelt out where it first appears, not "defined
    later at" the list; an entry nothing else uses is to come out of the list, not to be
    written out in the text. A definition in the text is said as before, its long form as
    typed, an apostrophe and all."""
    report = written(project, "# Methods\n\nThe AIC was computed.\n\n# Conclusions\n\nIt "
                     "worked.\n\n" + WORD_GLOSSARY)  # fmt: skip
    said = {f.message.split()[0]: f for f in report.findings}
    assert said["AIC"].message.startswith(
        "AIC is used here and not spelt out; only the list of abbreviations defines it, at ")
    assert said["AIC"].hint.startswith("spell it out where it first appears")
    assert said["CV"].message == ("CV is in the list of abbreviations and not used in the "
                                  "main text as G14 reads it")
    assert said["CV"].hint.startswith("take it out of the list")
    # Spelt out in the text after the list too: defined later there, as before (review of
    # #634).
    both = written(project, "# Introduction\n\nThe ROR was raised.\n\n# Abbreviations\n\nROR: "
                   "reporting odds ratio\n\n# Methods\n\nThe reporting odds ratio (ROR) was "
                   "computed.\n")  # fmt: skip
    ror = [f.message for f in both.findings if f.code == "abbreviation-used-before-defined"]
    assert ror == ["ROR is used here, and defined later at manuscript/main.md:7"], ror
    text = written(project, "# Methods\n\nThe Centre d'Enseignement Universitaire (CEU) "
                   "met.\n")  # fmt: skip
    assert text.findings[0].hint.startswith(
        "write 'Centre d'Enseignement Universitaire' out and drop the short form")


@pytest.mark.parametrize(
    "after",
    ["The UMC was consulted.", "Note: the UMC was consulted.", "# Declarations\n\nUMC: the "
     "centre was consulted."],
    ids=["a sentence", "a line shaped like an entry", "a heading"],
)  # fmt: skip
def test_a_glossary_a_sentence_opens_ends_with_its_last_entry(project: Path, after: str) -> None:
    """What follows the last entry is text: a sentence, a line that opens like an entry
    with a word for its short form, and a section's first line after a heading, however
    it is shaped."""
    report = written(project, "# Conclusions\n\nIt worked.\n\n" + WORD_GLOSSARY + after
                     + "\n\nThe AIC, the CV and the EBM fell.\n")  # fmt: skip
    assert found(report) == [
        "UMC is used once in the main text as G14 reads it, and not defined there"
    ]


@pytest.mark.parametrize(
    "opening",
    ["Abbreviations were spelt out at first use.", "We list the abbreviations below."],
    ids=["no entry after it", "the word not opening it"],
)  # fmt: skip
def test_a_paragraph_that_names_abbreviations_opens_no_glossary(
    project: Path, opening: str
) -> None:
    """A paragraph opens a glossary only where it opens with the word and an entry follows:
    the line after these is text, and its abbreviation undefined."""
    follows = "UMC: the centre was consulted." if "below" in opening else "The UMC was used."
    report = written(project, f"# Methods\n\n{opening}\n\n{follows}\n")
    assert found(report) == [
        "UMC is used once in the main text as G14 reads it, and not defined there"
    ]


def test_a_glossary_and_a_first_use_define_one_thing_once(project: Path) -> None:
    """A journal that asks for both gets both: the expansion at first use repeats the
    glossary, and is not defined again. A second definition in the text still is, and a
    glossary that means something else is two meanings."""
    glossary = "# Abbreviations\n\nROR: reporting odds ratio\n\n"
    text = "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR was raised.\n"
    assert not written(project, glossary + text).findings
    assert not written(project, text + "\n" + glossary).findings
    again = written(project, glossary + text + "\n# Discussion\n\nThe reporting odds ratio "
                    "(ROR) fell.\n")  # fmt: skip
    (message,) = found(again, "abbreviation-redefined")
    assert "defined again" in message and "main.md:7" in message, message
    other = written(project, "# Abbreviations\n\nROR: relative odds ratio\n\n" + text)
    (message,) = found(other, "abbreviation-redefined")
    assert "relative odds ratio" in message


@pytest.mark.parametrize(
    "caption",
    [
        "Table: Reports by drug; reporting odds ratio (ROR) with its interval.",
        ": Reports by drug; reporting odds ratio (ROR) with its interval.",
        "**Table 2.** Reports by drug; reporting odds ratio (ROR) with its interval.",
        "Figure 1. The reporting odds ratio (ROR) by year.",
    ],
)
def test_a_caption_may_restate_a_definition(project: Path, caption: str) -> None:
    table = "| Drug | Reports |\n|---|---|\n| one | 12 |\n"
    placed = f"{table}\n{caption}\n" if caption.startswith((":", "Table:")) else f"{caption}\n"
    report = written(
        project,
        "# Results\n\nThe reporting odds ratio (ROR) was computed. The ROR was raised.\n\n"
        f"{placed}\nThe ROR fell.\n",
    )
    assert not report.findings, found(report)


def test_a_caption_that_means_something_else_is_still_two_meanings(project: Path) -> None:
    report = written(
        project,
        "# Results\n\nThe reporting odds ratio (ROR) was computed. The ROR was raised.\n\n"
        "Figure 1. The relative odds ratio (ROR) by year.\n",
    )
    (message,) = found(report, "abbreviation-redefined")
    assert "relative odds ratio" in message


def test_a_latex_caption_may_restate_a_definition() -> None:
    """A table's caption is read in LaTeX, so a definition it restates is read there; it
    is not given twice."""
    from manuscript_guard.gates.language import _judge, _Known, _latex_file
    from manuscript_guard.text.latex.structure import read_tree

    tex = (
        "\\documentclass{article}\n\\begin{document}\n\\section{Results}\nThe reporting "
        "odds ratio (ROR) was computed. The ROR was raised.\n\\begin{table}\n\\caption[By "
        "drug]{The reporting odds ratio (ROR) by drug.}\n\\begin{tabular}{l}one \\\\\n"
        "\\end{tabular}\n\\end{table}\n%\\caption{a comment (PRR)}\n\\end{document}\n"
    )
    source = read_tree({"main.tex": tex}).sources[0]
    whole = _latex_file(source, False, None)
    from manuscript_guard.gates.language import _assembled
    from manuscript_guard.text.masking import NUL

    file = _assembled(0, Path("main.tex"), whole.view, whole.words,
                      whole.untitled.replace(NUL, " "), whole.regions, breaks=whole.breaks,
                      typed=tex, captions=whole.captions, glossaries=whole.glossaries)  # fmt: skip
    assert [tex[start:end] for start, end in whole.captions] == [
        "The reporting odds ratio (ROR) by drug."
    ]
    report = _judge([file], _Known(frozenset(), frozenset()), Path("."))
    assert not report.findings, [f.message for f in report.findings]


HEADLESS = (
    "**Abstract**\n\nThe reporting odds ratio (ROR) was raised.\n\n**Methods**\n\n"
    "The reporting odds ratio (ROR) was computed. The ROR and the PRR were raised.\n"
)


def test_a_manuscript_with_no_headings_is_read_as_one_text_and_says_so(project: Path) -> None:
    """Converted from Word with bold lines for headings: nothing tells the abstract from
    the main text, so a definition repeated in each is not reported, and G14 says why once,
    at drafting. A bold line is no heading. What is undefined is still reported."""
    report = written(project, HEADLESS, stage=DRAFTING)
    assert sorted((f.code, f.severity) for f in report.findings) == [
        ("abbreviation-undefined", "warn"),
        ("no-headings", "info"),
    ]
    (note,) = found(report, "no-headings")
    assert "abbreviation-redefined is not reported" in note
    headed = written(project, "# Methods\n\n" + HEADLESS, stage=DRAFTING)
    assert "abbreviation-redefined" in codes(headed)
    assert "no-headings" not in codes(headed)


@pytest.mark.parametrize("stage", [None, *(stage for stage in STAGES if stage != DRAFTING)])
def test_no_headings_is_said_at_drafting_only(project: Path, stage: str | None) -> None:
    """Basile, 2026-10-23: "No headings: a note once, at drafting". At any other stage, and
    where no stage is given, the paper is still read as one text, and nothing says so."""
    report = written(project, HEADLESS, stage=stage)
    assert sorted(f.code for f in report.findings) == ["abbreviation-undefined"], found(report)


def test_a_headless_supplement_says_nothing(project: Path) -> None:
    report = written(
        project, f"# Methods\n\n{PLAIN}\n", supplement="Supplementary text with no heading.\n"
    )
    assert not report.findings, found(report)


def test_a_clock_time_is_not_an_abbreviation(project: Path) -> None:
    """`11:00AM` is read as the words `11` and `00AM`, and `10:00 PM` has `PM` in it: both
    are the time of day."""
    report = written(
        project,
        "# Methods\n\nVisits ran from 8:30AM to 5:45PM. Doses were given at 10:00 PM, at "
        "12:30:15PM or at 7:15\nAM.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "sentence",
    [
        "The PM was high at 10:00.",  # particulate matter, with a time of day near it
        "The dose was given at 9 AM.",  # a time with no minutes: a known gap
    ],
)
def test_what_is_near_a_clock_time_is_still_read(project: Path, sentence: str) -> None:
    report = written(project, f"# Methods\n\n{sentence}\n")
    assert codes(report) == {"abbreviation-undefined"}, found(report)


def test_a_heading_typed_in_capitals_is_not_an_abbreviation(project: Path) -> None:
    """A manuscript converted from Word has its headings as bold paragraphs, often in
    capitals, and its tables' column labels in a header row: none of their words is an
    abbreviation. A grid table's header cell may run over two lines."""
    report = written(
        project,
        f"**TITLE PAGE**\n\nA study of reports.\n\n**ABSTRACT**\n\n{PLAIN}\n\n"
        "**MATERIALS AND\nMETHODS**\n\n__RESULTS__\n\n"
        "| GROUP | MODEL 1 |\n|---|---|\n| women | 3 |\n\n"
        "+-------+----+\n| MODEL | N  |\n| 1     |    |\n+=======+====+\n| men   | 3  |\n"
        "+-------+----+\n"
        f"\n# Discussion\n\n{PLAIN}\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    ("text", "reported"),
    [
        # A table's body: a baseline table's conditions are abbreviations.
        ("| Group | n |\n|---|---|\n| COPD | 12 |\n| CKD | 4 |\n", ["CKD", "COPD"]),
        ("+-------+----+\n| Group | n  |\n+=======+====+\n| COPD  | 3  |\n+-------+----+\n",
         ["COPD"]),
        # A list item and a plain paragraph in capitals.
        ("- COPD\n- CKD\n", ["CKD", "COPD"]),
        ("ICU\n", ["ICU"]),
        # A paragraph only partly bold.
        ("**ICU** stays were short.\n", ["ICU"]),
        # A header cell over two lines, read as one cell, which has small letters.
        ("+---------------+----+\n| Patients with | n  |\n| COPD          |    |\n"
         "+===============+====+\n| 3             | 4  |\n+---------------+----+\n",
         ["COPD"]),
    ],
)  # fmt: skip
def test_what_is_not_a_heading_in_capitals_is_still_read(
    project: Path, text: str, reported: list[str]
) -> None:
    report = written(project, f"# Results\n\n{text}")
    assert sorted(f.message.split()[0] for f in report.findings) == reported, found(report)


def test_a_cell_or_a_line_with_small_letters_is_still_read(project: Path) -> None:
    report = written(
        project,
        "# Results\n\n| Group | n |\n|---|---|\n| ICU stay | 12 |\n\nThe PRR was raised.\n",
    )
    assert sorted(f.message.split()[0] for f in report.findings) == ["ICU", "PRR"]


def test_a_defined_abbreviation_in_a_cell_in_capitals_is_a_use(project: Path) -> None:
    """The cell is not hidden: the abbreviation in it is used. What nobody defined goes
    unreported there, `HIV` here, which is a known gap."""
    report = written(
        project,
        "# Results\n\nThe relative risk (RR) was computed.\n\n| RR | HIV |\n|---|---|\n"
        "| 1.2 | 3 |\n",
    )
    assert not report.findings, found(report)


def test_a_word_in_capitals_too_long_for_a_short_form_is_not_reported(project: Path) -> None:
    report = written(project, "# Methods\n\nThe ABCDEFGHIJKLMNOP score was raised.\n")
    assert not report.findings, found(report)


def test_an_undefined_abbreviation_is_reported_where_it_is_first_used(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe ROR was computed.\n\nThe ROR compares groups.\n\nA raised ROR is "
        "a signal.\n",
    )
    (finding,) = report.findings
    assert finding.line == 3
    assert "3 times" in finding.message
    assert "in quotes" in finding.hint, "unquoted, YAML reads NO and ON as booleans"


def test_a_project_s_terms_are_names_here_too(project: Path) -> None:
    text = "# Methods\n\nABCB11 expression was raised.\n"
    assert codes(written(project, text)) == {"abbreviation-undefined"}
    configured(project, terms=["ABCB11"])
    assert not written(project, text).findings


def test_a_fenced_listing_is_not_read(project: Path) -> None:
    report = written(
        project, f"# Methods\n\n{PLAIN}\n\n```r\nROR <- (a * d) / (b * c)\n```\n"
    )
    assert not report.findings, found(report)


def test_a_heading_in_capitals_is_not_an_abbreviation(project: Path) -> None:
    report = written(project, f"# METHODS\n\n{PLAIN}\n\nRESULTS\n=======\n\n{PLAIN}\n")
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "line", ["2. DISCUSSION", "ABSTRACT", "1. INTRODUCTION", "1\\. INTRODUCTION",
             "MATERIALS AND METHODS:", "IV. RESULTS"],
)  # fmt: skip
def test_a_section_s_name_on_a_plain_line_in_capitals_is_not_an_abbreviation(
    project: Path, line: str
) -> None:
    """A paper typed in Word has its headings as plain paragraphs in capitals, "2.
    DISCUSSION", and the name was reported as an undefined abbreviation (the real-paper
    corpus). A line that is only a section's name, numbered or not, is a heading."""
    report = written(project, f"# Methods\n\n{PLAIN}\n\n{line}\n\n{PLAIN}\n")
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    ("line", "reported"),
    [("2. ICU", ["ICU"]), ("DISCUSSION ICU", ["DISCUSSION", "ICU"]),
     ("The DISCUSSION was short.", ["DISCUSSION"])],
)  # fmt: skip
def test_a_line_that_is_more_than_a_section_s_name_is_still_read(
    project: Path, line: str, reported: list[str]
) -> None:
    report = written(project, f"# Methods\n\n{PLAIN}\n\n{line}\n")
    assert sorted(f.message.split()[0] for f in report.findings) == reported, found(report)


@pytest.mark.parametrize(
    "heading",
    [
        "Author contributions",
        "Authors' contributions",
        "Contributors",
        "Acknowledgements",
        "Acknowledgments",
        "Funding",
        "Competing interests",
        "Conflict of interest",
        "Declaration of interests",
        "CRediT authorship contribution statement",
        "Declaration of competing interest",
        "Role of the funding source",
        "Sources of funding",
        "Financial disclosure",
        "Author statement",
    ],
)
def test_initials_and_funders_are_not_abbreviations(project: Path, heading: str) -> None:
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n\n# {heading}\n\nJB and CD analysed the data, funded by "
        "the NIHR and the ANR.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "label", ["**Authors\\' contributions**", "**Author contributions:**", "__Funding__",
              "**Acknowledgements.**", "**Competing interests**:"],
)  # fmt: skip
def test_initials_after_a_bold_statement_label_are_not_abbreviations(
    project: Path, label: str
) -> None:
    """A Word paper runs its statements on from a bold label, under one Declarations
    heading or none: "**Authors' contributions** JMD, BC and CD designed the study". Its
    initials and funders were reported as abbreviations, one finding each; they are people
    and institutions as under a heading that names the statement. The label alone over its
    paragraph does the same, unless a heading stands under it; and the paragraph after a
    statement is the paper's again."""
    statement = "JB and CD analysed the data, funded by the NIHR and the ANR."
    report = written(project, f"# Methods\n\n{PLAIN}\n\n# Declarations\n\n{label} {statement}\n")
    assert not report.findings, found(report)
    alone = written(project, f"# Methods\n\n{PLAIN}\n\n# Declarations\n\n{label}\n\n{statement}\n")
    assert not alone.findings, found(alone)
    after = written(project, f"# Methods\n\n{PLAIN}\n\n{label} {statement}\n\nThe EMA agreed.\n")
    assert [f.message.split()[0] for f in after.findings] == ["EMA"], found(after)
    headed = written(project, f"# Methods\n\n{PLAIN}\n\n{label}\n\n# Results\n\n{statement}\n")
    assert sorted(f.message.split()[0] for f in headed.findings) == ["ANR", "CD", "JB", "NIHR"]


@pytest.mark.parametrize(
    "statement",
    ["# Authors' contributions\n\nJMD, BC and CD designed the study at UNICAEN.",
     "**Authors\\' contributions** JMD, BC and CD designed the study at UNICAEN.",
     "# CRediT authorship contribution statement\n\nJ-MD: methodology. BC and CD: analysis, "
     "at UNICAEN."],
    ids=["under a heading", "after a bold label", "CRediT, an initial with a hyphen"],
)  # fmt: skip
def test_the_initials_a_contributions_statement_names_are_people_everywhere(
    project: Path, statement: str
) -> None:
    """The author's paper says "by a single author (CD)" in its Methods, and its
    contributions statement names CD with the others: CD was reported undefined there. The
    initials a contributions statement names, two to four capitals, are people in a
    bracket that holds only such initials; "J-MD" is taken whole and as "JMD", and not as
    an `MD`, which is still reported. Anywhere else they are read as abbreviations (Basile,
    2026-11-10): BC in a sentence, and in a bracket with an institution or a mark. A
    longer word of capitals in the statement, an institution, is still reported where the
    text uses it, and so are the capitals of the acknowledgements and the funding."""
    hyphened = "J-MD; " if "J-MD" in statement else ""
    methods = (f"# Methods\n\nInterviews were run by a single author (CD), checked ({hyphened}"
               "JMD and CD) and coded [CD & JMD], with the CEMU and the ANR (MD). BC ran "
               "the site (UNICAEN, BC) and (BC?).\n\n")  # fmt: skip
    rest = "\n\n# Acknowledgements\n\nWe thank the CEMU.\n\n# Funding\n\nThe ANR paid.\n"
    report = written(project, methods + statement + rest)
    said = sorted(f.message.split()[0] for f in report.findings)
    assert said == ["ANR", "BC", "CEMU", "MD", "UNICAEN"], found(report)


def test_jama_s_additional_contributions_name_no_initials(project: Path) -> None:
    """JAMA's acknowledgements are titled "Additional contributions", and their capitals are
    institutions: an undefined "(NIH)" elsewhere is still reported (round 2 of #611)."""
    report = written(project, "# Methods\n\nThe data came from one centre (NIH).\n\n"
                     "## Additional contributions\n\nWe thank the staff of the NIH.\n")  # fmt: skip
    assert found(report) == [
        "NIH is used once in the main text as G14 reads it, and not defined there"
    ]


def test_what_a_bold_label_cannot_tell_apart(project: Path) -> None:
    """The limits DESIGN.md's Known gaps write down, as written: a label is told from a
    sentence's first words by what follows it, so a statement that goes on in a small letter
    is read as prose, a simple table whose first header cell names a statement is read as
    one, and bold words before a hard line break or a no-break space are a label. A bold word
    that goes on into its sentence across a line break pandoc prints as a space is that
    sentence's, as on its line: it was taken for a label, its paragraph's capitals left
    unreported."""

    def reported(text: str) -> list[str]:
        report = written(project, f"# Methods\n\n{PLAIN}\n\n{text}\n")
        return sorted(f.message.split()[0] for f in report.findings)

    assert reported("**Funding** this study was funded by the NIHR.") == ["NIHR"]
    assert reported("**Funding:** this study was funded by the NIHR.") == []
    assert reported("**Funding** of the NHS fell.") == ["NHS"]
    # A line break pandoc prints as a space, with one space or tab before it or none; a hard
    # one, two spaces or a backslash, leaves the bold words on a line of their own, a label.
    assert reported("**Funding**\nof the NHS fell.") == ["NHS"]
    assert reported("**Funding** \nof the NHS fell.") == ["NHS"]
    assert reported("**Funding**\t\nof the NHS fell.") == ["NHS"]
    assert reported("**Funding**  \nof the NHS fell.") == []
    assert reported("**Funding**\\\nof the NHS fell.") == []
    assert reported("**Funding**\nThe NIHR paid.") == []
    # Only a space or a tab is read past on the label's line: after a no-break space, the
    # bold words are a label.
    assert reported(f"**Funding**{chr(0xA0)}the NIHR paid.") == []
    table = "{}   Count\n------------------   -----\nNIHR                 3\n"
    assert reported(table.format("Source            ")) == ["NIHR"]
    assert reported(table.format("**Funding source**")) == []


def test_a_funder_named_once_with_its_acronym_is_not_unused(project: Path) -> None:
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n\n# Funding\n\nFunded by the Agence Nationale de la "
        "Recherche (ANR).\n",
    )
    assert not report.findings, found(report)


def test_a_file_with_no_heading_continues_the_section_before_it(project: Path) -> None:
    """The build prints the files one after the other, so the funding statement that ends
    `main.md` is still the section when the next file opens without a heading."""
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n\n# Funding\n\nFunded by the ANR.\n",
        **{"2_more": "The NIHR paid for the second year.\n"},
    )
    assert not report.findings, found(report)


def test_a_reference_list_is_not_read(project: Path) -> None:
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n\n# References\n\n1. Smith J. The ROR in practice. JAMA.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "title",
    [
        # Headings the audit knew and the sections did not.
        "# Literature cited",
        "# Reference list",
        # Word's conversion: a title in a block quote, numbered, a colon after it; and one
        # with a bookmark on it, a link (corpus papers converted from Word).
        "> **11. REFERENCES**:",
        "[**References**](#_Ref89712232)",
        # Read already, kept read.
        "References",
        "**References**",
        "**\\\nReferences**",
    ],
)
def test_a_reference_list_under_each_title_word_writes_is_not_read(
    project: Path, title: str
) -> None:
    """The journals' names and the capitals in the titles of a list under one of these were
    reported as undefined abbreviations on real papers (`NHANES`, `BMJ`)."""
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n\n{title}\n\nSmith J. The NHANES data. BMJ. 2020;1:1-2.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "heading", ["## Reference list screening", "## Literature cited by the trials"],
)  # fmt: skip
def test_a_heading_that_only_opens_with_a_list_s_title_is_read(
    project: Path, heading: str
) -> None:
    """Round 1 of #623: "Reference list screening", a systematic review's subsection, was
    taken for the reference list by its opening words, and its prose was not read."""
    report = written(project, f"# Methods\n\n{heading}\n\nThe NHANES data were read.\n")
    assert sorted(f.message.split()[0] for f in report.findings) == ["NHANES"], found(report)


@pytest.mark.parametrize(
    "line",
    ["[**References**](#_Ref89712232) were read by two pharmacists.",
     "> References were read by two pharmacists."],
)  # fmt: skip
def test_a_link_or_a_quote_in_a_sentence_opens_no_reference_list(
    project: Path, line: str
) -> None:
    report = written(project, f"# Methods\n\n{line}\n\nThe NHANES data were used.\n")
    assert sorted(f.message.split()[0] for f in report.findings) == ["NHANES"], found(report)


def test_a_project_lists_what_it_leaves_undefined(project: Path) -> None:
    text = "# Results\n\nThe median was raised (IQR 2.1 to 4.3) by PCR.\n"
    assert len(found(written(project, text), "abbreviation-undefined")) == 2
    configured(project, language={"known_abbreviations": ["IQR", "PCR"]})
    assert not written(project, text).findings


def test_a_declared_guideline_is_a_name(project: Path) -> None:
    """The project's own guideline is named in its Methods, and is not shipped."""
    text = "# Methods\n\nReporting follows the DEMO-OBS checklist.\n"
    assert not written(project, text).findings


def test_a_known_abbreviation_the_author_defines_is_still_held_to_its_definition(
    project: Path,
) -> None:
    report = written(
        project,
        "# Methods\n\nDNA was extracted.\n\nDeoxyribonucleic acid (DNA) was then stored.\n",
    )
    assert codes(report) == {"abbreviation-used-before-defined"}


@pytest.mark.parametrize(
    "settings",
    [
        {"language": ["CI"]},
        {"language": {"known_abbreviations": "CI"}},
        {"language": {"known_abbreviations": [False, ["CI"], {"a": 1}]}},
        {"terms": 5},
        {"terms": [["a"], {"b": 1}]},
        {"reporting_guideline": [["a"], ["b"]]},
        {"reporting_guideline": [{"a": 1}]},
    ],
)
def test_a_setting_in_the_wrong_shape_does_not_stop_the_gate(
    project: Path, settings: dict
) -> None:
    """The schema reports the setting; G14 still reads the manuscript. A gate that raises
    is a failure, and this one has only warnings to give."""
    configured(project, **settings)
    report = written(project, "# Methods\n\nThe ROR was computed.\n")
    assert codes(report) == {"abbreviation-undefined"}


def test_nothing_here_fails_a_build(project: Path) -> None:
    report = written(
        project,
        "# Abstract\n\nThe ROR was raised.\n\n# Methods\n\nThe PRR was computed. The "
        "reporting odds ratio (ROR) and the reporting odds ratio (ROR) agree.\n",
    )
    assert len(report.findings) >= 3
    assert report.ok, "a reading that can be wrong advises; it does not stop a build"


def test_the_example_is_read_and_says_what_it_finds(project: Path) -> None:
    """Dogfooding. The example leaves `CI` undefined on purpose and says so in paper.yaml.
    Its Introduction uses ROR without defining it, which is a real slip in the example and
    stays one: its review records are tied to the text they read."""
    projekt, _ = load_project(project)
    report = check_language(projekt)
    assert report.ok
    assert [(f.code, f.line) for f in report.findings] == [("abbreviation-undefined", 23)]
    assert "ROR" in report.findings[0].message


# ---------------------------------------------------------------- a whole manuscript

REALISTIC = """---
title: "DILI with ICIs: a WHO VigiBase study"
---

# Abstract

**Background.** Immune checkpoint inhibitors (ICIs) cause drug-induced liver injury (DILI).
**Methods.** We queried VigiBase, the World Health Organization (WHO) pharmacovigilance
database. **Results.** ICIs were associated with DILI (IC025 1.2). **Conclusions.** DILI
reporting was raised.

# Introduction

Immune checkpoint inhibitors (ICIs) targeting programmed cell death protein 1 (PD-1) or its
ligand (PD-L1) have changed oncology [@smith2020]. Drug-induced liver injury (DILI) is a
known immune-related adverse event (irAE). In the KEYNOTE-189 trial, grade III-IV irAEs
occurred in 10% of patients. The FDA and EMA have issued warnings. We used the Medical
Dictionary for Regulatory Activities (MedDRA) and its Standardised MedDRA Queries (SMQs).

# Methods

VigiBase is maintained by the Uppsala Monitoring Centre (UMC). We computed the information
component (IC) and its 95% credibility interval; IC025 is the lower bound. Analyses used R
version 4.3.1 and SAS. Liver tests included ALT, AST and ALP, expressed as multiples of the
upper limit of normal (ULN). Patients with HBV or HCV infection were flagged. A sensitivity
analysis used the reporting odds ratio (ROR). An mAb was defined as a monoclonal antibody
(mAb). T2DM (type 2 diabetes mellitus) was a covariate. We followed STROBE. Time to onset
(TTO) was the delay between first dose and reaction. A P value < 0.05 was significant. In
Table 2, HRs are shown. See Figure S1 and Appendix A. I.V. administration and IV infusion
were pooled. Elderly (aged >= 65 years) patients were analysed separately. The U.S. reports
were compared with EU reports. OR 2.3 (95% CI 1.2-3.4). Non-ICI drugs were the comparator.
anti-PD-1 and anti-CTLA-4 agents were grouped. The Naranjo scale and RUCAM were applied.

# Results

The SMQ retrieved 1200 reports. The irAE was fatal in 5%. TTO was 42 days. ULN multiples
are in Table 2. The ROR agreed with the IC.

# Discussion

AI/ML methods were not used. COVID-19 vaccination did not confound. ICIs remain useful.
In the USA, the NIH funds such work. The UMC had no role. HBV reactivation was rare.

# Author contributions

BC and CD designed the study. SF supervised.

# Funding

Supported by INSERM and the ANR (grant ANR-21-CE17).
"""


def test_a_realistic_manuscript_is_reported_as_design_md_says(project: Path) -> None:
    """The measurement behind "every finding is a warning": 22 findings, 20 of them
    abbreviations a copy-editor would query and two of them names, a trial and a package.
    What the list leaves out matters as much: the title, the surnames and product names,
    the numerals, `P`, `R`, the initials and the funders."""
    report = written(project, REALISTIC)
    # The abbreviations only. The example's `paper.yaml` keeps to "hepatic injury", so this
    # text's "liver injury" is a finding of the other reading, held in test_vocabulary.py.
    reported = sorted(
        (f.code.removeprefix("abbreviation-"), f.message.split()[0])
        for f in report.findings
        if f.code.startswith("abbreviation-")
    )
    assert [f.message for f in report.findings if f.code == "term-avoided"] == [
        "'liver injury' is used 2 times; this paper's term is 'hepatic injury'"
    ]
    assert reported == [
        ("undefined", "AI"),
        ("undefined", "ALP"),
        ("undefined", "ALT"),
        ("undefined", "AST"),
        ("undefined", "EMA"),
        ("undefined", "FDA"),
        ("undefined", "HBV"),
        ("undefined", "HCV"),
        ("undefined", "HR"),
        ("undefined", "IC025"),  # in the abstract
        ("undefined", "IC025"),  # and in the main text
        ("undefined", "KEYNOTE-189"),  # a name, not an abbreviation
        ("undefined", "ML"),
        ("undefined", "NIH"),
        ("undefined", "OR"),
        ("undefined", "RUCAM"),
        ("undefined", "SAS"),  # a name, not an abbreviation
        ("unused", "DILI"),  # in the main text; the abstract uses its own
        ("unused", "PD-L1"),
        ("unused", "T2DM"),
        ("unused", "WHO"),  # in the abstract
        ("used-before-defined", "mAb"),
    ]
    assert report.counts["abbreviations_read"] == 31
    assert report.counts["abbreviations_defined"] == 15


# ---------------------------------------------------------------- one reading, two texts


def test_what_is_hidden_is_a_space_to_the_abbreviations_and_keeps_its_lines(
    project: Path,
) -> None:
    """A file is read once and each half of the gate takes its text from that reading.
    The vocabulary's keeps what is hidden as NUL. The abbreviations' has a space there, as
    it always had: with the NUL left in, a long form beside inline code is another long
    form, and a second definition "two meanings". Both keep every line break, or the line
    of a finding below is wrong: a listing's, which `mask` hides, and those of the front
    matter, of an equation set over three lines and of the reference list, which this
    module hides itself."""
    from manuscript_guard.gates.language import _file

    last = "The HR fell, and the PRR rose."
    text = (
        '---\ntitle: "A title"\nsubtitle: over three lines\n---\n\n'
        "# Methods\n\nThe hazard ratio (HR) was used. The hazard ratio `hr` (HR) was high.\n\n"
        "```\ncode\nmore code\n```\n\n$$\nx = y\n$$\n\n"
        f"{last}\n\n# References\n\n1. Smith J.\n2. Jones K.\n"
    )
    file = _file(0, Path("main.md"), text, [], False)
    assert "\x00" not in file.prose
    assert "\x00" in file.printed
    for reading in (file.prose, file.printed, file.spelt, _hidden(text)):
        assert len(reading) == len(text)
        assert [at for at, char in enumerate(reading) if char == "\n"] == file.breaks
    assert "Smith" not in file.printed, "the reference list is hidden from the vocabulary"

    report = written(project, text)
    (message,) = found(report, "abbreviation-redefined")
    assert "defined again" in message, "one meaning, not two"
    (undefined,) = [f for f in report.findings if f.code == "abbreviation-undefined"]
    assert undefined.line == text.split("\n").index(last) + 1, "below all that is hidden"


# ---------------------------------------------------------------- reading at any size


def test_unclosed_brackets_are_read_in_linear_time(assert_linear) -> None:
    def brackets(count: int) -> str:
        return "The ratio (ROR was raised " * count

    assert_linear(brackets, _definitions, 2000, "the definition scan, by unclosed bracket")


def test_unclosed_images_are_read_in_linear_time(assert_linear) -> None:
    def images(count: int) -> str:
        return "![" * count

    assert_linear(images, _hidden, 2000, "the reading of a file, by `![`")


def test_many_findings_are_made_in_linear_time(assert_linear) -> None:
    """One finding for each repeated definition, each with its line and its context: the
    line was counted from the top of the file each time, and the report copied."""
    from manuscript_guard.gates.language import _file, _judge, _Known

    nothing = _Known(frozenset(), frozenset())

    def repeated(count: int) -> list:
        text = "# Methods\n\n" + "The reporting odds ratio (ROR) was raised.\n" * count
        return [_file(0, Path("main.md"), text, [], False)]

    def judge(files: list) -> None:
        report = _judge(files, nothing, Path("."))
        # Each definition after the first is a redefinition, and nothing uses the first.
        assert len(report.findings) == len(files[0].definitions)

    assert_linear(repeated, judge, 500, "the findings, by repeated definition")


def test_many_statements_and_headings_are_read_in_linear_time(assert_linear) -> None:
    """Each statement run on from a bold label was set apart by scanning every region, and
    each label alone looked at every heading: a file of many was read in the square of its
    length (round 1 of #596)."""
    from manuscript_guard.gates.language import _file

    def labelled(count: int) -> str:
        return "# Methods\n\n**Funding:** the NIH.\n\n**Funding**\n\nThe NIH.\n\n" * count

    assert_linear(labelled, lambda text: _file(0, Path("main.md"), text, [], False), 300,
                  "the statements run on from a label, by statement and heading")  # fmt: skip


def test_a_statement_in_crlf_text_ends_with_its_paragraph() -> None:
    """A blank line written CRLF ends a paragraph too: else the first statement ran on to
    the end of the file and every abbreviation after it went unreported (round 1 of #596)."""
    from manuscript_guard.gates.language import _run_in_statements, _views

    text = "**Funding:** NIH.\r\n\r\nThe WHO data were used.\r\n"
    hidden, _code = _views(text)
    assert _run_in_statements(hidden, []) == [(0, text.index("\n"))]


def test_a_long_hyphenated_word_is_read_in_linear_time(assert_linear) -> None:
    from manuscript_guard.gates.language import _forms, _Known

    nothing = _Known(frozenset(), frozenset())

    def chained(count: int) -> str:
        return "-".join(["AB"] * count)

    # From 50 parts: reading every stretch of the word whole is cubic, and from 2,000 a
    # return of it would not fail this test but stall it for hours.
    assert_linear(chained, lambda token: _forms(token, set(), nothing), 50, "one word, by hyphen")


# ------------------------------------------------------------------- the title page

#: A title page as pandoc writes a Word paper's, its title a heading in the Title style's
#: place: authors in capitals with their degrees and marks, French affiliations in a
#: numbered list with their units and institutions, a note, the corresponding author.
FRENCH_TITLE_PAGE = (
    "# Pharmacology exam success in second-year medical students\n\n"
    "Ana MARTIN\\*^1^, Paul GIRARD, PharmD, MSc\\*^2,3^, Lea ROUX, MD, PhD^4^\n\n"
    "1.  Université Caen Normandie, UNICAEN, CEMU, F-14000 Caen, France\n\n"
    "2.  Normandie Univ, UNICAEN, INSERM U1237, UMR-S 1237, PhIND, Institut Blood and Brain "
    "\\@ Caen-Normandie (BB\\@C), GIP Cyceron, F-14000 Caen, France\n\n"
    "3.  Nagoya University Graduate School of Medicine, Department of International Medical "
    "Education, Nagoya, Japan.\n\n"
    "4.  Department of Pharmacology, CHU de Caen Normandie, F-14000 Caen, France\n\n"
    "\\*: These authors equally contributed to this work\n\n"
    "**Corresponding author**\n\n"
    "Dr. Lea ROUX, MD, PhD\n\n"
    "Pharmacology Department, CHU de Caen Normandie, 14033 Caen, France\n\n"
    "Email: <lea.roux@example.org>\n\n"
    "ORCID: 0000-0002-1825-0097\n\n"
)
BODY = (
    "# Introduction\n\nThe reporting odds ratio (ROR) was computed for each drug.\n\n"
    "# Methods\n\nThe ROR was compared between groups.\n"
)


def _named(report) -> set[str]:
    return {f.message.split()[0] for f in report.findings}


def test_a_title_page_like_the_author_s_gives_no_finding(project: Path) -> None:
    """The author's audit, 2026-11-12: a title page's departments, units and institutions,
    "INSERM U1237", "UMR-S", "CHU de Caen Normandie", "PhIND", "GIP Cyceron", and its
    authors' names in capitals were each an undefined abbreviation. The title page ends at
    the Abstract, and from there the paper is read as before."""
    text = FRENCH_TITLE_PAGE + "# Abstract\n\nThe NIH paid for it.\n\n" + BODY
    report = written(project, text)
    assert _named(report) == {"NIH"}, found(report)
    (finding,) = report.findings
    assert finding.line == text[: text.index("The NIH")].count("\n") + 1


@pytest.mark.parametrize("opening", ["# Introduction", "**Background**", "## 1. Main text"])
def test_without_an_abstract_the_title_page_ends_at_the_first_section(
    project: Path, opening: str
) -> None:
    """A paper with no abstract, a research letter, has its title page end at the first
    heading that names a section of the paper, and at a paragraph in bold that does."""
    text = FRENCH_TITLE_PAGE + opening + "\n\nThe CHU paid for it.\n"
    assert _named(written(project, text)) == {"CHU"}


@pytest.mark.parametrize(
    "salutation", ["Dear Editor,", "To the Editor:", "Sir,", "Dear Sir or Madam,"]
)
def test_a_letter_s_title_page_ends_at_its_salutation(project: Path, salutation: str) -> None:
    """A letter has no heading at all: its title page ends where the letter opens."""
    text = (
        "Pharmacology exam success\n\nAna Martin and Paul Girard\n\n"
        "Department of Pharmacology, CHU de Rouen, UNICAEN, Rouen, France\n\n"
        f"{salutation}\n\nWe read the report on the NIH survey with interest.\n"
    )
    assert _named(written(project, text)) == {"NIH"}


def test_a_title_page_ends_where_running_prose_begins(project: Path) -> None:
    """With no heading and no salutation, the title page ends at the first paragraph of
    prose, where it has two lines only a title page holds."""
    text = (
        "Pharmacology exam success\n\nAna MARTIN, MD^1^\n\n"
        "^1^ Department of Pharmacology, CHU de Rouen, Rouen, France\n\n"
        "We read the report on the NIH survey with interest.\n"
    )
    assert _named(written(project, text)) == {"NIH"}


def test_one_line_of_a_title_page_before_prose_is_read(project: Path) -> None:
    """Where prose ends it, one line only a title page holds is not enough: the opening is
    read whole, its CHU reported (DESIGN.md, Known gaps)."""
    text = (
        "Pharmacology exam success\n\nAna MARTIN\n\n"
        "Department of Pharmacology, CHU de Rouen, Rouen, France\n\n"
        "We read the report on the NIH survey with interest.\n"
    )
    assert {"CHU", "MARTIN", "NIH"} <= _named(written(project, text))


LISTS_ON_THE_TITLE_PAGE = [
    "Abbreviations: Food and Drug Administration (FDA); World Health Organization (WHO)",
    "**Abbreviations:**\n\nFDA: Food and Drug Administration\n\nWHO: World Health Organization",
    "**Abbreviations:** FDA: Food and Drug Administration\n\nWHO: World Health Organization",
    "Abbreviations: FDA, Food and Drug Administration; WHO, World Health Organization",
]


@pytest.mark.parametrize("listed", [*LISTS_ON_THE_TITLE_PAGE[:2], "Abréviations : Agence "
                                    "nationale de sécurité du médicament (ANSM)"])  # fmt: skip
def test_a_list_of_abbreviations_on_the_title_page_is_read(project: Path, listed: str) -> None:
    """A journal may ask for the list on the title page (Pediatrics): it ends the title page
    and defines its entries, as it did before the title page was set aside (round 1 of
    #654)."""
    text = (
        "Pharmacology exam success\n\nAna MARTIN\n\n"
        "Department of Pharmacology, CHU de Rouen, Rouen, France\n\n"
        f"{listed}\n\n# Introduction\n\nThe "
        + " and the ".join(re.findall(r"\b[A-Z]{3,}\b", listed)) + " paid for it.\n"
    )
    report = written(project, text)
    assert _named(report) == set(), found(report)


@pytest.mark.parametrize("listed", LISTS_ON_THE_TITLE_PAGE)
def test_a_list_on_the_title_page_is_read_as_with_no_title_page(listed: str) -> None:
    """Whatever G14 makes of a list of abbreviations, it makes the same of one on the title
    page: an entry on the label's own line is no entry in either (DESIGN.md, Known gaps)."""
    from manuscript_guard.gates.language import _file, _judge, _Known

    nothing = _Known(frozenset(), frozenset())
    opening = ("Pharmacology exam success\n\nAna MARTIN\n\n"
               "Department of Pharmacology, CHU de Rouen, Rouen, France\n\n")  # fmt: skip
    text = f"{opening}{listed}\n\n# Introduction\n\nThe FDA and the WHO paid for it.\n"

    def read(opens: bool) -> list[tuple[str, str]]:
        report = _judge([_file(0, Path("main.md"), text, [], False, opens=opens)], nothing,
                        Path("."))  # fmt: skip
        return sorted((f.code, f.message.split()[0]) for f in report.findings
                      if f.message.split()[0] in ("FDA", "WHO"))  # fmt: skip

    assert read(True) == read(False)


def test_a_short_form_only_the_title_page_uses_again_is_said_so(project: Path) -> None:
    """Defined in the text and used again only on the title page, a short form is unused,
    and its hint says the title page's use was not counted (round 1 of #654)."""
    text = (
        "Pharmacology exam success\n\nAna MARTIN\n\n"
        "Department of Pharmacology, CHU de Rouen, Rouen, France\n\n# Introduction\n\n"
        "The Centre Hospitalier Universitaire (CHU) paid for it.\n\n"
        "The Food and Drug Administration (FDA) approved it.\n"
    )
    hints = {f.message.split()[0]: f.hint for f in written(project, text).findings}
    assert hints.keys() == {"CHU", "FDA"}
    assert "the title page uses it" in hints["CHU"]
    assert "title page" not in hints["FDA"]


def test_the_title_page_uses_an_entry_of_the_list_of_abbreviations(project: Path) -> None:
    """The list of abbreviations covers the title page's units and institutions too: an
    entry only the title page uses is used (Basile, 2026-11-12, "Yes, count it"). An entry
    nothing uses is still the list's to drop."""
    text = (
        "Pharmacology exam success\n\nAna MARTIN\n\n"
        "Department of Pharmacology, CHU de Rouen, UNICAEN, Rouen, France\n\n"
        "# Introduction\n\nNothing.\n\n# Abbreviations\n\n"
        "UNICAEN: Université de Caen Normandie\n\nFDA: Food and Drug Administration\n"
    )
    report = written(project, text)
    assert sorted((f.code, f.message.split()[0]) for f in report.findings) == [
        ("abbreviation-unused", "FDA")], found(report)
    (finding,) = report.findings
    assert "title page" not in finding.hint


def test_a_title_typed_as_a_heading_uses_an_entry_of_its_text_s_list(project: Path) -> None:
    """A title typed as a heading is the title page's too, and uses the paper's entry; the
    supplement's title page uses none of the paper's (round 2 of #654)."""
    page = "# Drug safety in the {} year\n\nAna MARTIN\n\nDepartment of Pharmacology, Rouen\n\n"
    listed = "# Abbreviations\n\nPACES: first year of health studies\n"
    report = written(project, page.format("PACES") + "# Introduction\n\nNone.\n\n" + listed)
    assert _named(report) == set(), found(report)
    report = written(project, "# Introduction\n\nNone.\n\n" + listed,
                     supplement=page.format("PACES") + "# Methods\n\nNone.\n")  # fmt: skip
    assert _named(report) == {"PACES"}, found(report)


def test_a_french_letter_s_title_page_is_not_read(project: Path) -> None:
    """A letter in French: its service and department, its salutation (round 1 of #654)."""
    text = (
        "Succès à l'examen de pharmacologie\n\nAna MARTIN et Paul GIRARD\n\n"
        "Service de Pharmacologie, Département de Pharmacologie, Caen, France\n\n"
        "Madame, Monsieur,\n\nNous avons lu le rapport du CHU avec intérêt.\n"
    )
    assert _named(written(project, text)) == {"CHU"}


def test_prose_wrapped_over_lines_is_read_as_one_paragraph(project: Path) -> None:
    """An opening paragraph wrapped over several lines is one block: read a line at a time,
    its lines that name a department and a faculty were a title page's, and hid its CHU
    (round 1 of #654)."""
    text = (
        "Teaching pharmacology to second-year students\n"
        "at the Department of Pharmacology, CHU de Rouen,\n"
        "and the Faculty of Medicine, Université de Rouen,\n"
        "was reviewed in 2021 and we found that it\n"
        "was less used than the faculty.\n\n# Introduction\n\nNothing.\n"
    )
    assert _named(written(project, text)) == {"CHU"}


def test_nothing_on_the_title_page_defines_or_uses(project: Path) -> None:
    """INSERM spelt out on the title page does not define the text's INSERM, and the
    title page's UNICAEN is no use of the text's definition."""
    text = (
        "Pharmacology exam success\n\nAna MARTIN^1^\n\n"
        "^1^ Institut national de la santé et de la recherche médicale (INSERM), UNICAEN, "
        "Caen, France\n\n# Abstract\n\nNone.\n\n# Introduction\n\n"
        "The INSERM paid for it, and the University of Caen (UNICAEN) hosted it.\n"
    )
    report = written(project, text)
    assert sorted((f.code, f.message.split()[0]) for f in report.findings) == [
        ("abbreviation-undefined", "INSERM"), ("abbreviation-unused", "UNICAEN")]


@pytest.mark.parametrize(
    "opening",
    [
        # Opening prose that names a university, with no title page above it.
        "Students of the University of Rouen sat the CHU exam in 2021.\n\n",
        "Pharmacology exam success\n\nWe taught at the University of Rouen, France, in 2021, "
        "with the CHU.\n\n",
        # A title alone, and a paper that opens on its Introduction.
        "Teaching at the CHU of Rouen University Hospital\n\n",
        "",
        # A Markdown paper whose title is in its front matter.
        "---\ntitle: Exam success\nauthor: Ana Martin\n---\n\n",
    ],
)
def test_a_paper_with_no_title_page_is_read_whole(project: Path, opening: str) -> None:
    text = opening + "# Introduction\n\nThe CHU paid for it.\n"
    assert _named(written(project, text)) == {"CHU"}


def test_a_title_page_over_600_words_is_read(project: Path) -> None:
    """Six hundred words is more than a title page holds, as `init --from` counts one: a
    longer run is read, as the paper's own text may be."""
    affiliations = "".join(f"^{at}^ Department of Pharmacology, CHU de Rouen, Rouen, France\n\n"
                           for at in range(1, 80))  # fmt: skip
    text = f"Exam success\n\nAna MARTIN^1^\n\n{affiliations}# Abstract\n\nNone.\n"
    assert "CHU" in _named(written(project, text))


def test_the_supplement_s_title_page_is_not_read(project: Path) -> None:
    """The supplement opens on a title page of its own as often as the paper does."""
    supplement = FRENCH_TITLE_PAGE + "# Supplementary methods\n\nThe NIH paid for it.\n"
    report = written(project, "# Methods\n\nNothing.\n", supplement=supplement)
    assert _named(report) == {"NIH"}, found(report)


def test_only_the_first_file_of_the_paper_may_open_on_a_title_page(project: Path) -> None:
    """A second file of the paper continues it, and is read whole."""
    report = written(project, FRENCH_TITLE_PAGE + "# Abstract\n\nNone.\n",
                     zz_more=FRENCH_TITLE_PAGE + "# Methods\n\nNone.\n")  # fmt: skip
    assert "UNICAEN" in _named(report)


def test_the_title_page_is_found_in_linear_time(assert_linear) -> None:
    from manuscript_guard.text.blocks import find_headings
    from manuscript_guard.text.title_page import title_page_end

    def lines(count: int) -> str:
        return "Title\n\n" + "Department of X, CHU de Rouen\n\n" * count + "# Abstract\n"

    assert_linear(lines, lambda text: title_page_end(text, find_headings(text)), 200,
                  "the title page, by line")  # fmt: skip
