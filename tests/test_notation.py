"""G14's fourth reading: one notation.

A manuscript writes a P value, the sign after it, an interval's two bounds and a percentage
each in one way, and the gate reports the form used less. Two halves, as for the other
readings: it must find "p=0.04" among "P = 0.03" whether the value is typed or bound, and
it must leave alone a gene called p53, an age "<65", a figure's panel "3g" and everything
that is not the manuscript's own prose. One finding is no matter of counting: a number that
runs into its unit is reported wherever it stands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.contracts import load_project
from manuscript_guard.findings import Report
from manuscript_guard.gates import check_language
from manuscript_guard.gates.language import _file
from manuscript_guard.gates.notation import UNITS, judge_notation
from manuscript_guard.gates.vocabulary import Passage

X = "{{results.ror.point}}"
LOW = "{{results.ror.ci_low}}"
HIGH = "{{results.ror.ci_high}}"


def read(*texts: str) -> Report:
    """Judge these files, in this order, as the gate reads them."""
    files = [
        _file(order, Path(f"file{order}.md"), text, [], False)
        for order, text in enumerate(texts)
    ]
    return judge_notation([Passage(f.path, f.text, f.printed, f.line_of) for f in files])


def told(report: Report) -> list[tuple[str, str]]:
    return [(finding.code, finding.message) for finding in report.findings]


def codes(report: Report) -> list[str]:
    return [finding.code for finding in report.findings]


# ---------------------------------------------------------------- what must be caught


def test_a_p_value_written_another_way_is_reported_once_with_both_counts() -> None:
    report = read(
        f"# Results\n\nThe ratio was raised (P = {X}).\n\nIn women it was not (p = {X}), "
        f"nor in men (P = {X}).\n\nOverall p = {X}, and P = {X} in the old.\n"
    )
    (finding,) = report.findings
    assert finding.code == "notation-p-symbol"
    assert finding.message == (
        "the P value is written 'p' 2 times; the manuscript writes 'P' 3 times"
    )
    assert finding.line == 5, "where the other form first stands"
    assert "it was not (p = " in finding.context
    assert "keep the one the manuscript uses most" in finding.hint
    assert report.ok, "a count is a majority and not a rule, so it only advises"
    assert report.counts["notation_p_values"] == 5


@pytest.mark.parametrize(
    ("written", "form"),
    [
        ("p", "p"),
        ("*p*", "*p*"),
        ("_p_", "*p*"),  # either mark is italics
        ("*P*", "*P*"),
        ("**P**", "**P**"),
    ],
)
def test_each_way_of_writing_the_symbol_is_a_form(written: str, form: str) -> None:
    report = read(f"# Results\n\nOnce P = {X} and again P = {X}; then {written} = {X}.\n")
    assert told(report) == [
        (
            "notation-p-symbol",
            f"the P value is written '{form}' once; the manuscript writes 'P' 2 times",
        )
    ]


@pytest.mark.parametrize(
    "sentence",
    [
        f"The p-value was {X}.",  # spelt out, with no sign
        f"A p value of {X} was found.",
        f"It was low (p {X}).",  # the bound value prints its own sign
        f"For trend, p~trend~ = {X}.",  # a subscript between the symbol and the sign
        "It was low (p \\< 0.001).",  # the sign as pandoc escapes it
        "It was low (p <\n0.001).",  # wrapped after the sign
    ],
)
def test_a_p_value_is_found_however_it_is_stated(sentence: str) -> None:
    report = read(f"# Results\n\nFirst P = {X}; second P = {X}.\n\n{sentence}\n")
    assert codes(report) == ["notation-p-symbol"], told(report)
    assert report.counts["notation_p_values"] == 3


def test_the_sign_written_closed_among_spaced_ones_is_reported() -> None:
    report = read(
        f"# Results\n\nOf the reports (n = {X}), some were serious (P = {X}).\n\nFew were "
        f"fatal (n={X}), and the trend held (P < 0.001).\n"
    )
    (finding,) = report.findings
    assert finding.code == "notation-sign-spacing"
    assert finding.message == (
        "the sign after P or n has no space around it once, as in 'n={{\N{HORIZONTAL ELLIPSIS}}}'; "
        "the manuscript writes it with a space on each side of it 3 times, as in "
        "'n = {{\N{HORIZONTAL ELLIPSIS}}}'"
    )
    assert finding.line == 5
    assert report.counts["notation_signs"] == 4


def test_the_sign_written_spaced_among_closed_ones_is_reported() -> None:
    report = read(f"# Results\n\nSome (n=12) and more (n=40, P<0.001); then P = {X}.\n")
    (finding,) = report.findings
    assert finding.message.startswith(
        "the sign after P or n has a space on each side of it once, as in 'P = "
    )
    assert "with no space around it 3 times, as in 'n=12'" in finding.message


@pytest.mark.parametrize(
    "space",
    ["\N{NO-BREAK SPACE}", "\N{THIN SPACE}", "\N{NARROW NO-BREAK SPACE}", "\t"],
)
def test_a_space_of_any_width_is_a_space(space: str) -> None:
    report = read(f"# Results\n\nSome (n = 12) and more (n{space}={space}40).\n")
    assert not report.findings
    report = read(f"# Results\n\nSerious in 5{space}% and fatal in 2{space}%.\n")
    assert not report.findings


def test_a_space_on_one_side_of_the_sign_is_reported_whatever_the_rest_does() -> None:
    report = read("# Results\n\nSome (n= 12) and more (n= 40).\n")
    (finding,) = report.findings
    assert finding.code == "notation-sign-spacing"
    assert finding.message == (
        "the sign after P or n has a space on one side only 2 times, as in 'n= 12'"
    )
    assert "on both sides or on neither" in finding.hint

    report = read("# Results\n\nSome (n = 12), more (n = 40) and the rest (P =0.03).\n")
    assert told(report) == [
        (
            "notation-sign-spacing",
            "the sign after P or n has a space on one side only once, as in 'P =0.03'",
        )
    ]


@pytest.mark.parametrize(
    ("interval", "joined"),
    [
        (f"95% CI {LOW}\N{EN DASH}{HIGH}", "an en dash"),
        (f"95% CI {LOW} \N{EN DASH} {HIGH}", "an en dash"),
        (f"95% CI {LOW}-{HIGH}", "a hyphen"),
        ("95% CI 1.2-3.4", "a hyphen"),
        ("95% CI 1.2 - 3.4", "a hyphen"),
        (f"95% CI {LOW}, {HIGH}", "a comma"),
        (f"95% CI {LOW}; {HIGH}", "a semicolon"),
        (f"95% CI {LOW}\N{EM DASH}{HIGH}", "an em dash"),
        # the dashes as a Markdown author types them: pandoc prints -- as an en dash
        (f"95% CI {LOW}--{HIGH}", "an en dash"),
        ("95% CI 1.2--3.4", "an en dash"),
        ("95% CI 1.2 -- 3.4", "an en dash"),
        ("95% CI 1.2---3.4", "an em dash"),
    ],
)
def test_an_interval_joined_another_way_is_reported(interval: str, joined: str) -> None:
    report = read(
        f"# Results\n\nThe ratio was {X} (95% CI {LOW} to {HIGH}) and, at the other level, "
        f"{X} (90% CI {LOW} to {HIGH}).\n\nIn women it was {X} ({interval}).\n"
    )
    (finding,) = report.findings
    assert finding.code == "notation-interval"
    assert finding.message.startswith(
        f"the two bounds of an interval are joined by {joined} once, as in '"
    )
    assert finding.message.endswith("; the manuscript joins them by 'to' 2 times")
    assert finding.line == 5


@pytest.mark.parametrize(
    "interval",
    [
        "95% CI: 1.2 to 3.4",
        "95% CI, 1.2 to 3.4",
        "95% CI = 1.2 to 3.4",
        "95% CI [1.2 to 3.4]",
        "95% CI (1.2 to 3.4)",
        "CI 95% 1.2 to 3.4",  # the level after the letters
        "95% CIs 1.2 to 3.4",
        "95% CrI 1.2 to 3.4",
        "95% confidence interval of 1.2 to 3.4",
        "95% confidence\ninterval from 1.2 to 3.4",
        "95% credible interval was 1.2 to 3.4",
        # the abbreviation defined between the words and the bounds
        "95% confidence interval [CI], 1.2 to 3.4",
        "95% confidence interval (CI) 1.2 to 3.4",
        "95% CI 1.2% to 3.4%",
        "95% CI 85% to 97%",
        "95% CI 1,200 to 3,400",
        "95% CI .12 to .34",
    ],
)
def test_an_interval_is_found_however_it_is_introduced(interval: str) -> None:
    report = read(f"# Results\n\nFirst (95% CI 1-2), second (95% CI 3-4), third ({interval}).\n")
    assert codes(report) == ["notation-interval"], told(report)
    assert report.counts["notation_intervals"] == 3


@pytest.mark.parametrize(
    "interval",
    [
        "95% CI, \N{MINUS SIGN}4.1 to \N{MINUS SIGN}0.5",
        "95% CI -1.2 to 0.3",
        "95% CI 1.2 to -0.3",
    ],
)
def test_to_before_a_negative_bound_says_nothing_of_the_rest(interval: str) -> None:
    """A house that joins the bounds with a hyphen, as JAMA does, writes "to" where a bound
    is negative, so that the dash is not read as its sign. The first version counted that
    "to" as a second form and reported every trial that gives a ratio and a difference."""
    report = read(
        "# Results\n\nThe hazard ratio was 0.80 (95% CI, 0.69-0.93) and 1.10 (95% CI, "
        f"0.95-1.27).\n\nThe difference was \N{MINUS SIGN}2.3 ({interval}).\n"
    )
    assert not report.findings, told(report)
    assert report.counts["notation_intervals"] == 2


def test_a_negative_bound_joined_by_anything_else_is_counted() -> None:
    report = read("# Results\n\n(95% CI 1 to 2), (95% CI 3 to 4), (95% CI -1.2, 0.3).\n")
    assert codes(report) == ["notation-interval"]
    assert "joined by a comma once" in report.findings[0].message


def test_a_bound_that_is_a_binding_cannot_be_seen_to_be_negative() -> None:
    """Written down in Known gaps: with both bounds bound, the "to" before a negative one
    is counted like any other."""
    report = read(
        f"# Results\n\n(95% CI {LOW}-{HIGH}) and (95% CI {LOW}-{HIGH}).\n\nThe difference "
        f"was {X} (95% CI {LOW} to {HIGH}).\n"
    )
    assert codes(report) == ["notation-interval"]


@pytest.mark.parametrize(
    "sentence",
    [
        "We assumed a confidence interval of 95%, 5% margin of error and 80% power.",
        "With a CI of 95%, 80% power needs 340 participants.",
        "The survey used a CI 95%, 5% margin.",
    ],
)
def test_a_level_of_confidence_is_no_bound(sentence: str) -> None:
    """A level is followed by a comma. Bounds joined by "to" or a dash are bounds,
    whatever their numbers: "(CI 95% to 99%)" under a specificity of 96%."""
    report = read(f"# Methods\n\n{sentence}\n\n# Results\n\nIt was 2 (95% CI 1 to 3).\n")
    assert not report.findings, told(report)
    assert report.counts["notation_intervals"] == 1


def test_a_percent_sign_set_another_way_is_reported() -> None:
    report = read(
        f"# Results\n\nSerious in {X}% of reports and fatal in 2%.\n\nIn men, 5 % were "
        f"serious; 95% of the rest recovered.\n"
    )
    (finding,) = report.findings
    assert finding.code == "notation-percent"
    assert finding.message == (
        "'%' stands after a space once, as in '5 %'; the manuscript sets it against its "
        "number 3 times"
    )
    assert finding.line == 5
    assert report.counts["notation_percents"] == 4


def test_a_number_that_runs_into_its_unit_is_reported_though_the_manuscript_always_does() -> None:
    """No counting here: the SI Brochure sets the space, whatever the manuscript's habit."""
    report = read(
        "# Methods\n\nA dose of 5mg was given.\n\n# Results\n\nThe dose rose to 10mg in "
        f"{X}mL of saline at 37\N{DEGREE SIGN}C, and to 20mg later.\n"
    )
    (finding,) = report.findings
    assert finding.code == "notation-unit"
    assert finding.message == (
        "a number runs into its unit 5 times: '5mg', '10mg', "
        "'{{\N{HORIZONTAL ELLIPSIS}}}mL', '37\N{DEGREE SIGN}C'"
    )
    assert finding.line == 3
    assert "SI Brochure" in finding.hint and "'5 mg'" in finding.hint
    assert report.ok
    assert report.counts["notation_units_closed"] == 5


@pytest.mark.parametrize(
    "written",
    [
        "5mg", "0.5mg", "2.5\N{MICRO SIGN}g", "2.5\N{GREEK SMALL LETTER MU}g", "5mcg",
        "10mL", "10ml", "5mg/kg", "100mg/dL", "24h", "2g", "30min", "5mm", "400nm", "2mM",
        "5cm2", "5cm\N{SUPERSCRIPT TWO}", "5cm^2^", "120mmHg", "37\N{DEGREE SIGN}C",
        "37\N{MASCULINE ORDINAL INDICATOR}C", "50kDa", "150bp", "3kb", "2Gy", "5IU",
        f"{X}mg", f"{X}h",
    ],
)  # fmt: skip
def test_a_unit_is_known_in_each_of_its_spellings(written: str) -> None:
    report = read(f"# Methods\n\nIt was set at {written} throughout.\n")
    assert codes(report) == ["notation-unit"], written


def test_every_unit_listed_is_read() -> None:
    for unit in UNITS:
        report = read(f"# Methods\n\nIt was set at 5{unit} throughout.\n")
        assert codes(report) == ["notation-unit"], unit


def test_forms_used_as_often_show_the_later_one_and_say_so() -> None:
    report = read(f"# Results\n\nFirst P = {X}.\n\nThen p = {X}.\n")
    (finding,) = report.findings
    assert finding.message == (
        "the P value is written 'p' once; the manuscript writes 'P' once"
    )
    assert finding.line == 5
    assert "since they are level" in finding.hint

    report = read(f"# Results\n\nFirst p = {X}.\n\nThen P = {X}.\n")
    (finding,) = report.findings
    assert finding.message.startswith("the P value is written 'P' once")
    assert finding.line == 5


def test_three_forms_are_two_findings_each_against_the_one_used_most() -> None:
    report = read(
        "# Results\n\n(95% CI 1 to 2), (95% CI 3 to 4), (95% CI 5 to 6).\n\n(95% CI 7-8).\n\n"
        "(95% CI 9, 10) and (95% CI 11, 12).\n"
    )
    assert told(report) == [
        (
            "notation-interval",
            "the two bounds of an interval are joined by a comma 2 times, as in "
            "'CI 9, 10'; the manuscript joins them by 'to' 3 times",
        ),
        (
            "notation-interval",
            "the two bounds of an interval are joined by a hyphen once, as in 'CI 7-8'; "
            "the manuscript joins them by 'to' 3 times",
        ),
    ]


def test_the_whole_manuscript_is_one_count_in_the_order_it_is_read() -> None:
    report = read(
        f"# Methods\n\nThe threshold was P = {X}.\n",
        f"# Results\n\nIt was met (p = {X}) and again (P = {X}).\n",
        f"# Supplement\n\nAnd once more (p = {X}); P = {X}.\n",
    )
    (finding,) = report.findings
    assert finding.message == (
        "the P value is written 'p' 2 times; the manuscript writes 'P' 3 times"
    )
    assert finding.path.name == "file1.md"
    assert finding.line == 3


def test_each_kind_of_notation_is_judged_apart() -> None:
    report = read(
        f"# Results\n\nSerious (n = 12, P = {X}; 95% CI 1 to 2) in 5% at 5 mg.\n\nFatal "
        f"(n=3, p = {X}; 95% CI 3-4) in 2 % at 10mg.\n\nOther (n = 9, P = {X}; 95% CI 5 to "
        "6) in 7%.\n"
    )
    assert sorted(codes(report)) == [
        "notation-interval",
        "notation-p-symbol",
        "notation-percent",
        "notation-sign-spacing",
        "notation-unit",
    ]
    assert {finding.line for finding in report.findings} == {5}


# ---------------------------------------------------------------- what must be left alone


def test_a_manuscript_that_writes_each_thing_one_way_hears_nothing() -> None:
    report = read(
        f"# Abstract\n\nThe ratio was {X} (95% CI {LOW} to {HIGH}; P = {X}).\n\n# Methods\n\n"
        "The threshold was P < 0.05, and doses were 5 mg or 10 mg/kg in 100 mL.\n\n"
        f"# Results\n\nOf the reports (n = {X}), {X}% were serious (P = {X}) and 2% fatal "
        f"(P < 0.001; 95% CI 1.2 to 3.4).\n"
    )
    assert not report.findings, told(report)
    assert report.counts == {
        "notation_p_values": 4,
        "notation_signs": 5,
        "notation_intervals": 2,
        "notation_percents": 4,
        "notation_units_closed": 0,
    }


@pytest.mark.parametrize(
    "block",
    [
        f"See `p={X}` and `n=3` and `5mg` in the script.",
        "```\np=0.05\nn=3\ndose <- '5mg'\n95% CI 1-2\n5 %\n```",
        f"$p={X}$ and $$n=3$$",
        f"<!-- p={X}, n=3, 5mg, 5 %, 95% CI 1-2 -->",
        f"> The authors wrote p={X} (n=3; 95% CI 1-2) in 5 % at 5mg.",
        f"![A figure, p={X}, n=3, 5mg](figures/x.png)",
    ],
)
def test_what_is_not_the_paper_s_prose_is_not_read(block: str) -> None:
    report = read(
        f"# Results\n\nSerious (n = 12, P = {X}; 95% CI 1 to 2) in 5% at 5 mg.\n\n{block}\n\n"
        f"Other (n = 9, P = {X}; 95% CI 5 to 6) in 7%.\n"
    )
    assert not report.findings, told(report)
    assert report.counts["notation_p_values"] == 2


def test_the_front_matter_and_the_reference_list_are_not_read() -> None:
    report = read(
        f"---\ntitle: A study with p=0.05 and 5mg\n---\n\n# Results\n\nIt held (P = {X}).\n\n"
        "# References\n\nSmith J. A trial of 5mg (p=0.04, n=3). J Exampl. 2020;5 %.\n"
    )
    assert not report.findings, told(report)


def test_a_capital_that_opens_a_sentence_is_the_sentence_s() -> None:
    """ "P values were two-sided." in a paper that writes p: nobody opens a sentence in
    lower case, so the capital says nothing of the paper's notation."""
    report = read(
        f"# Methods\n\nP values were two-sided. The p value of each test is given.\n\n"
        f"# Results\n\nIt held (p = {X}).\n"
    )
    assert not report.findings, told(report)
    assert report.counts["notation_p_values"] == 2


def test_a_capital_that_opens_a_sentence_is_the_sentence_s_with_a_sign_after_it_too() -> None:
    """ "P < 0.05 was considered significant." is the commonest sentence of a Methods
    section. Its capital is the sentence's; its spacing is still the manuscript's."""
    report = read(
        "# Methods\n\nP < 0.05 was considered statistically significant.\n\n"
        f"# Results\n\nIt held (p = {X}) and again (p = {X}).\n"
    )
    assert not report.findings, told(report)
    assert report.counts["notation_p_values"] == 2
    assert report.counts["notation_signs"] == 3

    report = read(
        "# Methods\n\nP<0.05 was considered statistically significant.\n\n"
        f"# Results\n\nIt held (p = {X}) and again (p = {X}).\n"
    )
    assert codes(report) == ["notation-sign-spacing"]


@pytest.mark.parametrize(
    "sentence",
    [
        "Plateau pressure was limited (P~plat~ < 30 cmH~2~O).",
        "Ventilation was set for a P~CO2~ = 40 mmHg.",
        "Lipophilicity was high (log P = 3.2).",
        "The model was fitted with P = 10 predictors.",
        "The order was P = 2 and the lag P = 1.5.",
        "Pressure was kept at P = 10-15 mmHg.",  # a range, and no power of ten
        # ten to a power above nought is no P value either
        "Pressure rose to P = 10^3^ Pa.",
        "Pressure rose to P = 10\N{SUPERSCRIPT THREE} Pa.",
        "Pressure rose to P = 10<sup>3</sup> Pa.",
    ],
)
def test_a_p_with_a_value_above_one_is_no_p_value(sentence: str) -> None:
    """A pressure, a partition coefficient, a number of predictors. A P value is never
    above 1, so these are told apart; a proportion, "p = 0.5", cannot be."""
    report = read(f"# Results\n\nIt held (p = {X}) and again (p = {X}).\n\n{sentence}\n")
    assert not report.findings, told(report)
    assert report.counts["notation_p_values"] == 2
    assert report.counts["notation_signs"] == 2


@pytest.mark.parametrize(
    "stated",
    [
        "= 1", "= 1.0", "= 1.00", "= 0.99", "= .99", "= 0.05", "< 0.001", "> 0.99",
        # the figures are above 1 and the value is not: a power of ten follows them
        "= 3.2 x 10-9", "= 3.2 \N{MULTIPLICATION SIGN} 10^-9^", "= 5e-8", "< 1.2E-10",
        # and ten itself to a negative power, as a threshold is stated in genetics
        "< 10^-5^", "< 10^\N{MINUS SIGN}8^", "< 10\N{SUPERSCRIPT MINUS}\N{SUPERSCRIPT EIGHT}",
        "< 10<sup>-5</sup>",
    ],
)  # fmt: skip
def test_a_p_value_of_one_or_less_is_one(stated: str) -> None:
    report = read(f"# Results\n\nIt held (p = {X}) and again (p = {X}).\n\nThen P {stated}.\n")
    assert codes(report) == ["notation-p-symbol"], stated


@pytest.mark.parametrize(
    "sentence",
    [
        "Expression of p53 and of P2Y12 was measured.",
        "P-glycoprotein and p-cresol were assayed.",
        "P. aeruginosa was isolated in Phase 2.",
        "The probability (P) and the proportion (p) are defined above.",
        "Group P and group p differed.",
    ],
)
def test_a_letter_p_that_states_no_value_is_not_a_p_value(sentence: str) -> None:
    report = read(f"# Results\n\nIt held (P = {X}) and again (P = {X}).\n\n{sentence}\n")
    assert not report.findings, told(report)
    assert report.counts["notation_p_values"] == 2


@pytest.mark.parametrize(
    "sentence",
    [
        "Patients aged <65 years with ALT >3 times the limit were excluded.",  # no P, no n
        "The n-3 fatty acids and the N-terminal fragment were measured.",
        "A BMI>30 and an eGFR<60 were recorded.",
    ],
)
def test_a_comparison_that_is_not_a_statistic_s_is_not_read(sentence: str) -> None:
    report = read(f"# Results\n\nIt held (n = 12, P = {X}).\n\n{sentence}\n")
    assert not report.findings, told(report)
    assert report.counts["notation_signs"] == 2


@pytest.mark.parametrize(
    "sentence",
    [
        "Doses of 5 mg, 10 mL and 2 g were given at 37 \N{DEGREE SIGN}C for 24 h.",
        "A 5-mg dose and a 24-h collection were used.",  # joined to make an adjective
        "As 1L therapy, in their 30s, grade 3A, on 5G networks, over 5m, with 10K steps.",
        "In 2D and 3D cultures, H2O and CO2, CD4 and CD8, p38 and IL6 were used.",
        "At 8am and 5pm, on the 5th and 22nd, in the 1990s.",
        "See Figure 3g and Table 2h.",
        "See Figures 2g and 3h, and Fig. 4a, 4g and 5h.",
        "Panel 2g shows the dose; Supplementary Figure S3h shows the time.",
        "The angle was 30\N{DEGREE SIGN} and the isotope 131I.",
        # a panel named in lower case, on a wrapped line, after an abbreviation's full stop
        "As shown in figure 3g and in table 2h.",
        "The effect is shown in Figure\n3g and in Figures 2f and\n3h.",
        "Compare Fig. 2f vs. 2g.",
        # a relative centrifugal force is written closed: 12,000 g would be twelve kilograms
        "Samples were centrifuged at 12,000g for 10 min and the pellet was kept.",
        "The lysate was spun at 800g, and after centrifugation at 3000g it was frozen.",
        "Cells were pelleted at 300g.",
        # by its size, with no word of centrifuging before it
        "The supernatant was cleared at 16,000g for 20 min.",
        "After 10 min at 12,000g, the pellet was resuspended.",
        "The lysate was cleared at 100,000g.",
        # a compound of a series, by the word before it or by its bold type
        "Compounds 3g and 4h were inactive, and the product 5g was not isolated.",
        "The most potent was **3g**, followed by **4h** and *5g*.",
        "Analogue 7g, derivative 8h and intermediate 9g were prepared (Scheme 2, entry 4g).",
    ],
)
def test_what_only_looks_like_a_number_and_its_unit_is_left_alone(sentence: str) -> None:
    report = read(f"# Methods\n\n{sentence}\n")
    assert not report.findings, told(report)


@pytest.mark.parametrize(
    "sentence",
    [
        "See Figure 3. A dose of 2g was given.",  # the figure is another sentence's
        "The compound was given. A dose of 2g followed.",
        "After centrifugation the pellet was dried. It weighed 2g.",
        "A dose of **2 g** or of 3g was given.",  # the marks are not around it
        "The dose was 24h apart, by 5mg steps.",  # no word of these, and no force in mg
        "Samples were centrifuged for 10min.",  # only g is a force
        # a word of a series that is here a word of ordinary prose
        "Each compound was incubated for 24h.",
        "The medicinal product was given every 8h.",
        "At study entry, patients had fasted for 8h.",
        "An intermediate dose of 2g was used.",
        "Rats weighing 250g were used.",  # three figures are a weight
        # and so are four: a birth weight is no force
        "Birth weight was below 2500g in 12 infants.",
        "Infants under 1500g were excluded.",
        # four figures with no word of centrifuging before them: Known gaps
        "The supernatant was cleared at 3000g for 20 min.",
    ],
)
def test_a_unit_is_a_unit_outside_those_sentences(sentence: str) -> None:
    report = read(f"# Methods\n\n{sentence}\n")
    assert codes(report) == ["notation-unit"], told(report)


@pytest.mark.parametrize(
    "sentence",
    [
        "The cardiac index (CI) was 2 to 3 in most.",
        "Confidence intervals were computed by the Wald method, 95% throughout.",
        "The CI was narrow.",
    ],
)
def test_the_letters_of_an_interval_with_no_bounds_after_them_are_not_one(sentence: str) -> None:
    report = read(f"# Results\n\nIt was 2 (95% CI 1-3).\n\n{sentence}\n")
    assert not report.findings, told(report)
    assert report.counts["notation_intervals"] == 1


def test_a_binding_in_a_listing_is_no_number() -> None:
    report = read(f"# Results\n\nIt held (P = {X}).\n\nSee `p={X}`.\n\n```\nn={X}\n```\n")
    assert report.counts["notation_p_values"] == 1
    assert report.counts["notation_signs"] == 1


def test_a_binding_alone_says_nothing() -> None:
    report = read(f"# Results\n\n{X}\n\n{{{{tables.baseline}}}}\n\nThe ratio was {X}.\n")
    assert not report.findings
    assert not any(report.counts.values())


# ---------------------------------------------------------------- through the gate


def written(project: Path, text: str) -> tuple[Report, tuple]:
    import shutil

    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(text, encoding="utf-8")
    report = check_language(load_project(project)[0])
    return report, tuple(f for f in report.findings if f.code.startswith("notation-"))


def test_the_gate_gives_this_reading_with_the_others(project: Path) -> None:
    report, found = written(
        project,
        f"# Results\n\nIt held (P = {X}) and again (P = {X}).\n\nAnd once (p = {X}) at 5mg.\n",
    )
    assert [f.code for f in found] == ["notation-p-symbol", "notation-unit"]
    assert all(f.gate == "G14" and f.path == project / "manuscript" / "main.md" for f in found)
    assert all(f.line == 5 for f in found)
    assert report.ok
    assert report.counts["notation_p_values"] == 3


def test_it_is_read_in_an_acknowledgement_too(project: Path) -> None:
    """The spelling is not read in the sections whose wording is somebody else's. A P
    value is the author's wherever it stands."""
    _, found = written(
        project,
        f"# Results\n\nIt held (P = {X}) and again (P = {X}).\n\n# Acknowledgements\n\nWe "
        f"thank the reviewer who asked for the test (p = {X}).\n",
    )
    assert [f.code for f in found] == ["notation-p-symbol"]


def test_the_example_writes_each_thing_one_way(project: Path) -> None:
    """Dogfooding: its intervals are joined by "to", in the paper and in its supplement."""
    report = check_language(load_project(project)[0])
    assert not [f for f in report.findings if f.code.startswith("notation-")]
    assert report.counts["notation_intervals"] >= 3
    assert report.counts["notation_units_closed"] == 0


# ---------------------------------------------------------------- reading at any size


def passage(text: str) -> list[Passage]:
    return [Passage(Path("main.md"), text, text, lambda offset: 1)]


def test_a_long_manuscript_is_read_in_linear_time(assert_linear) -> None:
    def manuscript(count: int) -> list[Passage]:
        return passage(
            "Serious (n = 12, P = 0.03; 95% CI 1 to 2) in 5% at 5 mg; fatal (n=3, p=0.04; "
            "95% CI 3-4) in 2 % at 10mg.\n\n" * count
        )

    def judge(passages: list[Passage]) -> None:
        assert len(judge_notation(passages).findings) == 5

    assert_linear(manuscript, judge, 200, "the notation, by length")


@pytest.mark.parametrize(
    "piece",
    ["1,", "P = ", "*P", "n =", "95% CI 1 to", "95% CI ", "5 ", "5m", "p-value ", "CI 1,"],
)
def test_a_line_that_never_ends_what_it_starts_is_read_in_linear_time(
    assert_linear, piece: str
) -> None:
    def manuscript(count: int) -> list[Passage]:
        return passage(piece * count)

    def judge(passages: list[Passage]) -> None:
        judge_notation(passages)

    assert_linear(manuscript, judge, 2000, f"the notation, on a line of {piece!r}")


def test_an_interval_whose_first_bound_is_a_level_s_number_is_an_interval() -> None:
    report = read(
        "# Results\n\nSensitivity was 90% (CI 85%-94%) and 88% (CI 80%-93%).\n\nSpecificity "
        "was 96% (CI 95% to 99%).\n"
    )
    assert codes(report) == ["notation-interval"]
    assert report.counts["notation_intervals"] == 3


def test_a_first_bound_in_percent_is_no_level() -> None:
    """In "(95% CI 80%-93%; 12 studies)" the 80% is the first bound. It was taken for a
    level stated after the letters, "-93" for a bound and the semicolon for the join, so
    a manuscript that joined every interval with a hyphen was told of a semicolon."""
    report = read(
        "# Results\n\nSensitivity was 87% (95% CI 80%-93%; 12 studies) and specificity "
        "91% (95% CI 85%-95%).\n\nThe ratio was 1.5 (95% CI 1.2-1.9).\n"
    )
    assert not report.findings, told(report)
    assert report.counts["notation_intervals"] == 3


def test_a_level_after_the_letters_is_one_before_a_negative_bound() -> None:
    """The level is refused only where the sign stands against its percent sign."""
    report = read(
        "# Results\n\nIt rose by 0.2 (CI 95% 0.1 to 0.3) and by 0.4 (CI 95% 0.2 to 0.6)."
        "\n\nThe difference was 0.1 (CI 95% -0.3, 0.4).\n"
    )
    assert codes(report) == ["notation-interval"]
    assert "a comma once" in report.findings[0].message, told(report)


def test_a_number_too_long_to_be_one_is_read_and_nothing_raises() -> None:
    """Python refuses to make a number of more than 4,300 digits. The first fix of the
    value above 1 asked it to, and a `P = ` before 4,301 sevens made the gate raise,
    taking the abbreviations, the terms and the spelling with it."""
    long = "7" * 5000
    report = read(f"# Results\n\nIt held (p = {X}) and again (p = {X}).\n\nThen P = {long}.\n")
    assert not report.findings, "above 1, so no P value"
    report = read(f"# Results\n\nIt held (p = {X}) and again (p = {X}).\n\nThen P = 0.{long}.\n")
    assert codes(report) == ["notation-p-symbol"]
    report = read(f"# Methods\n\nA dose of {long}g and {long}mg in {long}% of {long} to {long}.\n")
    assert codes(report) == ["notation-unit"], "the g is a force by its size; the mg is not"


@pytest.mark.parametrize(
    ("opening", "closing"),
    [
        ("The 95% CI", "is shown in the table."),
        ("The 95% confidence", "interval is shown."),
        ("The 95% CI:", "1.2 to"),
        ("It held (P", "< 0.05"),
        ("Of these (n", "= 12"),
        ("Serious in 5", "% of reports"),
    ],
)
def test_one_long_run_of_spaces_is_read_in_linear_time(
    assert_linear, opening: str, closing: str
) -> None:
    """A cell of a table padded to its column, or a line nobody ended. The first version
    had three gaps in a row after the letters of an interval, which shared a run of
    spaces out among themselves in every way: 800 spaces after "CI" took 24 seconds."""

    def manuscript(count: int) -> list[Passage]:
        return passage(opening + " " * count + closing)

    def judge(passages: list[Passage]) -> None:
        judge_notation(passages)

    assert_linear(manuscript, judge, 20000, f"the notation, on spaces after {opening!r}")


def test_a_line_of_bindings_is_read_in_linear_time(assert_linear) -> None:
    def manuscript(count: int) -> list[Passage]:
        text = "P = {{results.a}} " * count
        file = _file(0, Path("main.md"), text, [], False)
        return [Passage(file.path, file.text, file.printed, file.line_of)]

    def judge(passages: list[Passage]) -> None:
        assert judge_notation(passages).counts["notation_p_values"] > 0

    assert_linear(manuscript, judge, 500, "the notation, on a line of bindings")
