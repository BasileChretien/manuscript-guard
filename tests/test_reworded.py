"""`manuscript-guard reworded`: an edit that was meant to change the wording changed nothing
else.

A language pass, by a person, a service or a model, is trusted with the words. What it must
not touch is what the words are about: a binding, a citation, a typed number. `check` cannot
see that, because it reads the manuscript as it is and both `{{results.ror.lower}}` and
`{{results.ror.upper}}` are bindings that resolve. So the text is compared with what it was.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from manuscript_guard.cli import main
from manuscript_guard.findings import FAIL, WARN, Report
from manuscript_guard.reworded import (
    BINDING,
    CITATION,
    MAYBE,
    NO,
    NUMBER,
    SURE,
    compare,
    facts,
)

PATH = Path("manuscript/main.md")

BEFORE = (
    "# Results\n\n"
    "The reporting odds ratio was {{results.ror.point}} (95% CI {{results.ror.lower}} to\n"
    "{{results.ror.upper}}), from 77 reports [@smith2020; @lee2019].\n\n"
    "Of {{results.n.total}} reports, {{results.n.serious}} were serious, as @doe2018 found\n"
    "in 3 of 12 centres.\n"
)


def kinds(text: str) -> list[tuple[str, str]]:
    """Each fact as it is read: a number with "-" before it where a dash is its sign for
    sure, and "?" where it is perhaps one."""
    marks = {SURE: "-", MAYBE: "?", NO: ""}
    return [(fact.kind, marks[fact.minus] + fact.text) for fact in facts(text)]


def told(report: Report) -> list[tuple[str, str]]:
    return [(finding.code, finding.severity) for finding in report.findings]


def said(report: Report) -> str:
    return "\n".join(f"{f.code} {f.line}: {f.message}" for f in report.findings)


# ----------------------------------------------------------------------------- the facts


def test_the_facts_of_a_text_are_its_bindings_citations_and_numbers_in_order() -> None:
    assert kinds(BEFORE) == [
        (BINDING, "results.ror.point"),
        (NUMBER, "95"),
        (BINDING, "results.ror.lower"),
        (BINDING, "results.ror.upper"),
        (NUMBER, "77"),
        (CITATION, "smith2020"),
        (CITATION, "lee2019"),
        (BINDING, "results.n.total"),
        (BINDING, "results.n.serious"),
        (CITATION, "doe2018"),
        (NUMBER, "3"),
        (NUMBER, "12"),
    ]


def test_each_fact_knows_its_line() -> None:
    lines = {fact.text: fact.line for fact in facts(BEFORE)}
    assert lines["results.ror.point"] == 3
    assert lines["lee2019"] == 4
    assert lines["doe2018"] == 6
    assert lines["12"] == 7


@pytest.mark.parametrize(
    ("typed", "read"),
    [
        ("a dose of 1,200 mg", ["1,200"]),
        ("in 12,345,678 records", ["12,345,678"]),
        ("grades 1,2,3 and 1, 2, 3", ["1", "2", "3", "1", "2", "3"]),
        ("a ratio of 3.84", ["3.84"]),
        ("a share of 0,5", ["0", "5"]),  # a decimal comma is not read as one number
        ("COVID-19 and IL-6 through CYP3A4", ["19", "6", "3", "4"]),
        ("on 2019-03-12", ["2019", "03", "12"]),
        ("\N{VULGAR FRACTION ONE HALF} of them", ["\N{VULGAR FRACTION ONE HALF}"]),
        ("three of twelve", []),  # a number in words is not held
        # a number with no nought keeps its point
        ("a P of .05", [".05"]),
        ("in Fig.5 and on p.12", ["5", "12"]),
        ("version 1.2.3", ["1.2", "3"]),
        ("seen in 45%.12 We then", ["45", "12"]),  # a note's number after a sentence
        # raised and lowered figures are figures
        ("P < 5 x 10⁻⁸", ["5", "10", "⁻⁸"]),
        ("10⁶ cells", ["10", "⁶"]),
        ("an IC₅₀ of 3", ["₅₀", "3"]),
    ],
)
def test_a_number_is_read_as_it_is_typed(typed: str, read: list[str]) -> None:
    assert [text for kind, text in kinds(f"It was {typed}.\n") if kind == NUMBER] == read


@pytest.mark.parametrize(
    ("typed", "read"),
    [
        # for sure a sign: nothing stands before the dash that it could join
        ("a change of -0.3", ["-0.3"]),
        ("a change of \N{MINUS SIGN}0.3", ["-0.3"]),
        ("a change of (\N{EN DASH}0.3 to 0.4)", ["-0.3", "0.4"]),
        ("a change of \N{NON-BREAKING HYPHEN}0.3", ["-0.3"]),
        ("a change of \N{FULLWIDTH HYPHEN-MINUS}0.3", ["-0.3"]),
        ("an r of -.30", ["-.30"]),
        ("the pair (0.5,-0.3)", ["0.5", "-0.3"]),
        ("about \N{ALMOST EQUAL TO}-0.3", ["-0.3"]),
        ("down \N{RIGHTWARDS ARROW}-0.3", ["-0.3"]),
        ("a cell |-0.3|", ["-0.3"]),
        ("a range from 5\N{EN DASH}-3", ["5", "-3"]),
        ("a rise of +2.5 points", ["+2.5"]),
        # and after a mark that can only open there
        ("a mean of *-0.3*", ["-0.3"]),
        ("a mean of **-0.3**", ["-0.3"]),
        ("a mean of $-0.3$", ["-0.3"]),
        ("a mean of (*-0.3*)", ["-0.3"]),
        ("a cell |**-0.3**|", ["-0.3"]),
        ("the pair (0.5,*-0.3*)", ["0.5", "-0.3"]),
        ("P < 10^-5^", ["10", "-5"]),
        ("with x~-1~ below", ["-1"]),
        ("quoted as '-3'", ["-3"]),
        ('the vector c("-3","-5")', ["-3", "-5"]),
        # no sign: the dash joins two things
        ("from 1.2-3.4", ["1.2", "3.4"]),
        ("from 80%-93%", ["80", "93"]),
        ("between {{results.low}}-3", ["3"]),
        ("groups (1)-3", ["1", "3"]),
        ("from 37\N{DEGREE SIGN}-39\N{DEGREE SIGN}", ["37", "39"]),
        ("the 5\N{PRIME}\N{EN DASH}3\N{PRIME} direction", ["5", "3"]),
        ("at 50€-100€ a day", ["50", "100"]),
        ("from 5‰-9‰", ["5", "9"]),
        ("pages 1--3", ["1", "3"]),  # the dash pandoc prints for two hyphens
        ("from 0.5-.7", ["0.5", ".7"]),
        # perhaps a sign: after a mark that may close, a product or a power, an "e"
        ("10^3^-10^5^ cells", ["10", "3", "?10", "5"]),
        ("the 5'-3' direction", ["5", "?3"]),
        ("with *n*-1 degrees of freedom", ["?1"]),
        ("with $n$-1 degrees of freedom", ["?1"]),
        ("PM~2.5~-10 was high", ["2.5", "?10"]),
        ("on days **1**-3", ["1", "?3"]),
        ("P < 1e-5", ["1", "?5"]),
        ("in Figures 1E\N{EN DASH}1G", ["1", "?1"]),
        ("tol = 10**-6", ["10", "?6"]),
        ("y = x*-1", ["?1"]),
        ("z <- x^2*y^-1", ["2", "?1"]),
        ("struck ~~-3~~ out", ["?3"]),
        ("pages 12 \N{EN DASH}15", ["12", "?15"]),  # a range with a space on one side
        ("pages 12\n\N{EN DASH}15", ["12", "?15"]),  # or wrapped there
        ("pages 12 --15", ["12", "?15"]),  # or with the two hyphens of a dash
        ("a fall to --3", ["-3"]),
    ],
)
def test_a_dash_before_a_number_is_its_sign_for_sure_perhaps_or_not(
    typed: str, read: list[str]
) -> None:
    assert [text for kind, text in kinds(f"It was {typed}.\n") if kind == NUMBER] == read


def test_what_is_not_printed_holds_no_fact() -> None:
    text = (
        "# Methods\n\n<!-- was {{results.old}} in 14 of 20 [@gone2001] -->\n\n"
        "See <https://example.org/v2/page3> and [the site](https://example.org/2024).\n"
    )
    assert kinds(text) == []


def test_a_listing_is_printed_and_its_numbers_are_held() -> None:
    text = "# Methods\n\n```r\nset.seed(20240115)\nalpha <- 0.05\n```\n"
    assert [text for kind, text in kinds(text) if kind == NUMBER] == ["20240115", "0.05"]


def test_a_binding_is_one_however_it_is_spaced() -> None:
    assert kinds("It was {{ results.ror.point }}.\n") == kinds("It was {{results.ror.point}}.\n")


def test_a_binding_here_is_one_the_gates_call_well_formed() -> None:
    """The bindings are read here by the pattern of `placeholders.parse` and not through
    it. This holds the two to one definition."""
    from manuscript_guard.text.placeholders import parse

    text = (
        "{{results.a}} {{ lit.b.c }} {{table.t1}} {{figure.f}} {{other.x}} {{results.cut}\n"
        "<!-- {{results.hidden}} -->\n\n```\n{{results.listed}}\n```\n"
    )
    held = [fact.text for fact in facts(text) if fact.kind == BINDING]
    assert held == [binding.ref for binding in parse(text)[0]]
    assert held == ["results.a", "lit.b.c", "table.t1", "figure.f", "results.listed"]


def test_a_citation_is_its_key_in_a_group_or_in_the_sentence() -> None:
    group = kinds("It holds [see @smith2020, p. 12; -@lee2019].\n")
    assert group == [(CITATION, "smith2020"), (NUMBER, "12"), (CITATION, "lee2019")]
    assert kinds("As @smith2020 has it.\n") == [(CITATION, "smith2020")]


# ------------------------------------------------------------------------ the comparison


def test_a_text_compared_with_itself_has_nothing_to_report() -> None:
    report = compare(BEFORE, BEFORE, PATH)
    assert not report.findings
    assert report.counts == {
        "reworded_files": 1,
        "reworded_bindings": 5,
        "reworded_citations": 3,
        "reworded_numbers": 4,
    }


def test_a_rewording_around_the_facts_passes() -> None:
    after = (
        "# Results\n\n"
        "We estimated a reporting odds ratio of {{results.ror.point}} (95% CI "
        "{{results.ror.lower}} to {{results.ror.upper}}) on the basis of 77 reports "
        "[@smith2020; @lee2019].\n\n"
        "Among the {{results.n.total}} reports, {{results.n.serious}} were classed as "
        "serious, in line with @doe2018, who found this in 3 of 12 centres.\n"
    )
    assert not compare(BEFORE, after, PATH).findings


@pytest.mark.parametrize(
    ("old", "new", "lost", "added"),
    [
        # one bound for the other: both resolve, so `check` passes it
        ("{{results.ror.upper}})", "{{results.ror.lower}})", "ror.upper", "ror.lower"),
        ("[@smith2020; @lee2019]", "[@smith2020]", "lee2019", None),
        ("[@smith2020; @lee2019]", "[@smith2020; @lee2020]", "lee2019", "lee2020"),
        ("from 77 reports", "from 71 reports", "77", "71"),
        ("in 3 of 12 centres", "in three of 12 centres", "3", None),
        ("in 3 of 12 centres", "in 3 of 12 centres (25%)", None, "25"),
        ("95% CI", "CI", "95", None),
        ("{{results.n.serious}} were serious", "most were serious", "results.n.serious", None),
    ],
)  # fmt: skip
def test_a_fact_that_is_gone_or_new_fails(
    old: str, new: str, lost: str | None, added: str | None
) -> None:
    assert old in BEFORE
    report = compare(BEFORE, BEFORE.replace(old, new), PATH)
    assert not report.ok
    by_code = {finding.code: finding for finding in report.findings}
    expected = (("fact-lost", lost), ("fact-new", added))
    assert set(by_code) == {code for code, name in expected if name}
    assert all(finding.severity == FAIL for finding in report.findings)
    if lost:
        assert lost in by_code["fact-lost"].message
    if added:
        assert added in by_code["fact-new"].message


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("1,200", "1200"),
        ("0.50", "0.5"),
        ("3.84", "3.48"),
        ("0.05", ".05"),
        (".5 mg", "5 mg"),
        ("10⁻⁸", "10⁻⁶"),
        ("an IC₅₀", "an IC₉₀"),
    ],
)
def test_a_number_is_compared_as_typed(old: str, new: str) -> None:
    report = compare(f"It was {old} in all.\n", f"It was {new} in all.\n", PATH)
    assert sorted(told(report)) == [("fact-lost", FAIL), ("fact-new", FAIL)], said(report)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("-0.3", "0.3"),
        ("-.30", ".30"),
        ("(-3)", "(3)"),
        ("a cell |**-0.3**|", "a cell |**0.3**|"),
        ("(0.5,*-0.3*)", "(0.5,*0.3*)"),
        ("10^-5^", "10^5^"),
        ('c("-3")', 'c("3")'),
    ],
)
def test_a_minus_sign_that_is_sure_fails_when_it_goes_or_comes(old: str, new: str) -> None:
    gone = compare(f"It was {old} in all.\n", f"In all, it was {new}.\n", PATH)
    assert told(gone) == [("sign-lost", FAIL)], said(gone)
    assert "has lost its minus sign" in gone.findings[0].message
    come = compare(f"It was {new} in all.\n", f"In all, it was {old}.\n", PATH)
    assert told(come) == [("sign-new", FAIL)], said(come)
    assert come.findings[0].line == 1
    assert "has a minus sign it did not have" in come.findings[0].message


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("1e-5", "1e5"),
        ("10**-6", "10**6"),
        ("x*-1", "x*1"),
        ("2*-0.5", "2*0.5"),
        ("x^2*y^-1", "x^2*y^1"),
        ("~~-3~~", "~~3~~"),
    ],
)
def test_a_dash_that_may_be_a_sign_is_shown_when_it_goes_or_comes(old: str, new: str) -> None:
    """After a product, a power, a mark that may close or the "e" of an exponent, the dash
    is a sign or it is not, and nothing here knows. Said nothing of, a sign went unseen;
    read as a sign, a range retyped was refused. So it is put before a person."""
    gone = compare(f"It was {old} in all.\n", f"In all, it was {new}.\n", PATH)
    assert told(gone) == [("sign-unsure", WARN)], said(gone)
    assert gone.ok and "may have lost a minus sign" in gone.findings[0].message
    come = compare(f"It was {new} in all.\n", f"In all, it was {old}.\n", PATH)
    assert told(come) == [("sign-unsure", WARN)], said(come)
    assert come.ok and "may have gained a minus sign" in come.findings[0].message


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("5 %", "5%"),
        ("(n=12)", "(n = 12)"),
        ("P<0.05", "*P* < 0.05"),
        ("-0.3", "\N{MINUS SIGN}0.3"),
        ("-0.3", "\N{NON-BREAKING HYPHEN}0.3"),
        ("1.2-3.4", "1.2 to 3.4"),
        ("1.2-3.4", "1.2\N{EN DASH}3.4"),
        ("pages 1--3", "pages 1\N{EN DASH}3"),
        ("5mg", "5 mg"),
        ("[@smith2020]", "@smith2020"),
        ("{{results.n}}", "{{ results.n }}"),
        ("12 reports", "12\N{NO-BREAK SPACE}reports"),
        ("50€-100€", "50€ to 100€"),
        ("5‰-9‰", "5‰ to 9‰"),
        # the dash stands as it stood, and is only read another way
        ("a row |A|**-0.3**|", "a row | A | **-0.3** |"),
        ("x*-1", "x * -1"),
        # a line wrapped before a negative number, and unwrapped
        ("a change of\n-0.3", "a change of -0.3"),
        ("0.5\n-0.3", "0.5 -0.3"),
        ("2*-0.5", "2 \N{MULTIPLICATION SIGN} \N{MINUS SIGN}0.5"),
    ],
)
def test_what_a_language_edit_does_to_the_notation_passes(old: str, new: str) -> None:
    report = compare(f"It was {old} in all.\n", f"In all, it was {new}.\n", PATH)
    assert not report.findings, said(report)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("10^3^-10^5^ cells", "10^3^ to 10^5^ cells"),
        ("the 5'-3' direction", "the 5' to 3' direction"),
        ("n-1 degrees", "*n*-1 degrees"),
        ("PM~2.5~-10", "PM~2.5~ to 10"),
        ("days **1**-3", "days **1** to 3"),
        ("$n$-1", "$n$ - 1"),
        ("Figures 1E\N{EN DASH}1G", "Figures 1E to 1G"),
        ("pages 12 \N{EN DASH}15", "pages 12\N{EN DASH}15"),
        ("pages 12 --15", "pages 12\N{EN DASH}15"),
    ],
)
def test_a_range_retyped_where_its_dash_may_be_a_sign_passes_with_a_warning(
    old: str, new: str
) -> None:
    """The first review found each of these refused, and the fix of that let a sign go
    unseen. They pass, and the place is shown."""
    report = compare(f"It was {old} in all.\n", f"In all, it was {new}.\n", PATH)
    assert told(report) == [("sign-unsure", WARN)], said(report)
    assert report.ok


def test_a_sign_lost_beside_the_same_number_kept_is_counted() -> None:
    before = "It fell by -0.3 here.\n\nIt fell by -0.3 there.\n"
    report = compare(before, before.replace("-0.3 there", "0.3 there"), PATH)
    assert told(report) == [("sign-lost", FAIL)]
    assert report.findings[0].message == (
        "the number '0.3' stood as '-0.3' twice before the edit, on lines 1 and 3, and stands "
        "as '-0.3' once now"
    )
    assert report.findings[0].line == 3


@pytest.mark.parametrize(
    ("before", "after", "said_of_it"),
    [
        (
            "We set y = x*-1 here.\n\nWith n-1 degrees of freedom.",
            "We set y = x * -1 here.\n\nWith *n*-1 degrees of freedom.",
            "may have gained a minus sign",
        ),
        (
            "We set y = 2*-1 here.\n\nWith n-1 degrees of freedom.",
            "We set y = 2 \N{MULTIPLICATION SIGN} \N{MINUS SIGN}1 here.\n\n"
            "With *n*-1 degrees of freedom.",
            "may have gained a minus sign",
        ),
        (
            "We set y = x * -1 here.\n\nWith *n*-1 degrees of freedom.",
            "We set y = x*-1 here.\n\nWith n-1 degrees of freedom.",
            "may have lost a minus sign",
        ),
        (
            "It was 2*-10 here.\n\nPM2.5-10 was high.",
            "It was 2 * -10 here.\n\nPM~2.5~-10 was high.",
            "may have gained a minus sign",
        ),
    ],
)
def test_two_edits_of_notation_on_the_same_figures_do_not_make_a_sign(
    before: str, after: str, said_of_it: str
) -> None:
    """The fourth review: each of the two edits passes by itself, a dash that was perhaps a
    sign read as a sure one and a dash that joined read as perhaps one. Together the counts
    are those of a sign that came, and it was refused with "has a minus sign it did not
    have" of a dash that stood on that line before. No place of the number went from no
    dash to a sure sign, so it is shown and passes."""
    report = compare(before + "\n", after + "\n", PATH)
    assert told(report) == [("sign-unsure", WARN)], said(report)
    assert report.ok and said_of_it in report.findings[0].message


def test_three_things_at_once_on_the_same_figures_are_a_limit() -> None:
    """Known gaps, pinned so that a change to either is seen: a sign or an edit of notation
    at one place of a number, an edit of notation at the other, and the two clauses
    changing places with no other fact in either."""
    slope, freedom = "It fell by -1 here.\n", "With n-1 degrees.\n"
    unseen = compare(
        slope + "\n" + freedom, freedom.replace("n-", "*n*-") + "\n" + slope.replace("-", ""), PATH
    )
    assert not unseen.findings, said(unseen)
    spaced, italic = "We set y = x * -1 here.\n", "With *n*-1 degrees.\n"
    refused = compare(
        spaced + "\n" + italic, "With n-1 degrees.\n\n" + spaced.replace(" * ", "*"), PATH
    )
    assert told(refused) == [("sign-lost", FAIL)], said(refused)


def test_a_sure_sign_that_goes_fails_beside_a_dash_that_may_be_one() -> None:
    """The third review: a dash that may be a sign, standing where it stood, was counted
    among the dashes now and answered for a sure sign that went. A slope of -1 made 1 was
    only shown, because the `*n*-1` of a later paragraph had the same figure."""
    beside = "\n\nWith *n*-1 degrees of freedom, in the 5'-3' direction.\n"
    gone = compare("The slope was -1 here." + beside, "The slope was 1 here." + beside, PATH)
    assert told(gone) == [("sign-lost", FAIL)], said(gone)
    assert gone.findings[0].message == (
        "the number '1' has lost its minus sign: '-1' stood on line 1 before the edit"
    )
    come = compare("It moved by 3 units." + beside, "It moved by -3 units." + beside, PATH)
    assert told(come) == [("sign-new", FAIL)], said(come)
    assert come.findings[0].message == (
        "the number '3' has a minus sign it did not have: '-3' stands on line 1"
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            "It fell by -0.3 in the first group and rose by 0.3 in the second.",
            "It fell by 0.3 in the first group and rose by -0.3 in the second.",
        ),
        ("It ranged from -1.96 to 1.96 here.", "It ranged from 1.96 to -1.96 here."),
        # a sure sign gone and a dash that may be one new, on the same figures
        (
            "It was -10 here.\n\nWe plated 10^3^ to 10^5^ cells.",
            "It was 10 here.\n\nWe plated 10^3^-10^5^ cells.",
        ),
        (
            "The slope was 1 here.\n\nWith *n*-1 degrees of freedom.",
            "The slope was -1 here.\n\nWith *n* to 1 degrees of freedom.",
        ),
    ],
)
def test_a_dash_at_another_place_of_the_same_figures_is_shown(before: str, after: str) -> None:
    """Two signs that changed places, or two clauses that did: the figures stand as they
    stood and as many of them have a dash, so only their places tell. The third review
    found nothing said of it, once a number's sign was no part of what is compared."""
    report = compare(before + "\n", after + "\n", PATH)
    assert told(report) == [("sign-moved", WARN)], said(report)
    assert report.ok


def test_the_places_of_a_dash_are_named() -> None:
    report = compare(
        "It fell by -0.3 here.\n\nIt rose by 0.3 there.\n",
        "It fell by 0.3 here.\n\nIt rose by -0.3 there.\n",
        PATH,
    )
    (finding,) = report.findings
    assert finding.message == (
        "the dash before the number '0.3' stands at another of its 2 places: before the edit "
        "at the 1st, on line 1, and now at the 2nd, on line 3"
    )
    assert finding.line == 3


def test_a_number_that_came_or_went_with_its_sign_is_counted_by_its_figures() -> None:
    """The count of one text was said of the other text's number: "'-2' stands twice now
    and stood once" of a 2 that stood once."""
    come = compare("It was 2 here.\n", "It was -2 here.\n\nAnd -2 there.\n", PATH)
    assert [finding.message for finding in come.findings] == [
        "the number '2' stands twice now, on lines 1 and 3, and stood once before the edit",
        "the number '2' has a minus sign it did not have: '-2' stands on lines 1 and 3",
    ]
    gone = compare("It was -2 here.\n\nAnd -2 there.\n", "It was 2 here.\n", PATH)
    assert [finding.message for finding in gone.findings] == [
        "the number '2' stood twice before the edit, on lines 1 and 3, and stands once now",
        "the number '2' has lost its minus sign: '-2' stood on lines 1 and 3 before the edit",
    ]


def test_a_negative_number_that_is_gone_is_named_with_its_sign() -> None:
    report = compare("It fell by -0.3 here, in 4.\n", "It fell here, in 4.\n", PATH)
    assert [finding.message for finding in report.findings] == [
        "the number '-0.3' is gone: it stood on line 1 before the edit"
    ]


def test_a_fact_that_stood_several_times_is_counted() -> None:
    before = "It was 12 here.\n\nIt was 12 there.\n\nAnd 12 again, of 40.\n"
    report = compare(before, before.replace("12 there", "twelve there"), PATH)
    assert told(report) == [("fact-lost", FAIL)]
    message = report.findings[0].message
    assert "'12'" in message and "3 times" in message and "twice" in message, message


def test_a_line_that_holds_a_fact_twice_is_named_once() -> None:
    before = "It was 12 of 12 here.\n\nAnd 12 there.\n"
    report = compare(before, before.replace("12 there", "a dozen there"), PATH)
    assert report.findings[0].message == (
        "the number '12' stood 3 times before the edit, on lines 1 and 3, and stands "
        "twice now"
    )


def test_a_lost_fact_is_placed_where_it_stood() -> None:
    report = compare(BEFORE, BEFORE.replace("from 77 reports", "from the reports"), PATH)
    (finding,) = report.findings
    assert finding.path == PATH
    assert "line 4" in finding.message, finding.message


def test_a_new_fact_is_placed_where_it_stands() -> None:
    report = compare(BEFORE, BEFORE.replace("12 centres", "12 centres [@new2024]"), PATH)
    (finding,) = report.findings
    assert (finding.code, finding.line) == ("fact-new", 7)


def test_the_same_facts_in_another_order_warn_and_pass() -> None:
    after = BEFORE.replace(
        "Of {{results.n.total}} reports, {{results.n.serious}} were serious",
        "{{results.n.serious}} of the {{results.n.total}} reports were serious",
    )
    report = compare(BEFORE, after, PATH)
    assert told(report) == [("order-changed", WARN)]
    assert report.ok
    (finding,) = report.findings
    assert finding.line == 6
    assert "{{results.n.total}}, {{results.n.serious}}" in finding.message
    assert "{{results.n.serious}}, {{results.n.total}}" in finding.message


def test_two_values_swapped_are_put_before_the_author() -> None:
    """Both are bindings that resolve, and both stand in the sentence still. G2 reports
    this where the two were emitted as the bounds of one interval; for two counts, or two
    bounds emitted apart, this warning is all there is."""
    after = BEFORE.replace(
        "{{results.ror.lower}} to\n{{results.ror.upper}}",
        "{{results.ror.upper}} to\n{{results.ror.lower}}",
    )
    report = compare(BEFORE, after, PATH)
    assert told(report) == [("order-changed", WARN)], said(report)


def test_each_place_where_the_order_changed_is_told_by_itself() -> None:
    after = BEFORE.replace(
        "{{results.ror.lower}} to\n{{results.ror.upper}}",
        "{{results.ror.upper}} to\n{{results.ror.lower}}",
    ).replace("in 3 of 12 centres", "in 12 centres, of which 3")
    report = compare(BEFORE, after, PATH)
    assert told(report) == [("order-changed", WARN), ("order-changed", WARN)]
    assert [finding.line for finding in report.findings] == [3, 7]
    assert "'12', '3'" in report.findings[1].message


def test_the_order_is_not_told_while_a_fact_is_gone() -> None:
    """With a fact lost there is no saying which of the rest moved. The loss is told, and
    the order when the loss is settled."""
    after = BEFORE.replace(
        "{{results.ror.lower}} to\n{{results.ror.upper}}",
        "{{results.ror.upper}} to\n{{results.ror.lower}}",
    ).replace("from 77 reports", "from the reports")
    assert told(compare(BEFORE, after, PATH)) == [("fact-lost", FAIL)]


def test_a_change_inside_a_comment_is_no_change() -> None:
    before = "It held.\n\n<!-- checked against 14 reports [@old2001] -->\n"
    after = "It held.\n\n<!-- checked against 15 reports -->\n"
    assert not compare(before, after, PATH).findings


def test_a_listing_inside_a_comment_holds_no_fact() -> None:
    """A text returned without its comments is a rewording. The listing was put back with
    the others, comment or no, and its seed and the year in a key were told gone."""
    listing = "```r\nset.seed(20240115)\nx <- {{results.old}} [@gone2001]\n```"
    before = f"# Methods\n\nIt held.\n\n<!--\n{listing}\n-->\n\nIt was 12 in all.\n"
    assert kinds(before) == [(NUMBER, "12")]
    assert not compare(before, "# Methods\n\nIt held.\n\nIt was 12 in all.\n", PATH).findings
    assert not compare(before, before.replace("20240115", "7"), PATH).findings


def test_a_listing_under_a_key_that_is_not_printed_holds_no_fact() -> None:
    before = (
        "---\ntitle: A study of 40 centres\nheader-includes: |\n  ```{=latex}\n"
        "  documentclass[12pt]\n  ```\n---\n\nIt held in 3 of 4.\n"
    )
    assert [text for _kind, text in kinds(before)] == ["40", "3", "4"]
    assert not compare(before, before.replace("12pt", "6pt"), PATH).findings
    assert compare(before, before.replace("40 centres", "41 centres"), PATH).findings


def test_a_change_inside_a_listing_is_one() -> None:
    before = "# Methods\n\n```r\nset.seed(20240115)\n```\n"
    report = compare(before, before.replace("20240115", "20240116"), PATH)
    assert sorted(told(report)) == [("fact-lost", FAIL), ("fact-new", FAIL)]


def test_the_line_ends_of_windows_are_no_change() -> None:
    assert not compare(BEFORE, BEFORE.replace("\n", "\r\n"), PATH).findings


def test_a_long_manuscript_is_compared_in_linear_time(
    assert_linear: Callable[..., None],
) -> None:
    """Every sentence turned round, which is the most an order can change: a comparison
    that lined the two texts up fact by fact would take the square of this."""

    def texts(size: int) -> tuple[str, str]:
        before = "".join(
            f"It was {n} of 7 [@key{n}] in {{{{results.k{n}}}}}.\n\n" for n in range(size)
        )
        after = "".join(
            f"In {{{{results.k{n}}}}} [@key{n}] it was 7 of {n}.\n\n" for n in range(size)
        )
        return before, after

    def work(given: tuple[str, str]) -> object:
        return compare(*given, PATH)

    assert_linear(texts, work, 200, "the comparison, by sentences turned round")


def test_a_number_that_stands_everywhere_is_compared_in_linear_time(
    assert_linear: Callable[..., None],
) -> None:
    """One number on every line and one of them gone: the lines it stood on are listed up
    to a few and counted past that, not written out."""

    def texts(size: int) -> tuple[str, str]:
        before = "It was 7 in all.\n" * size
        return before, before.replace("7", "seven", 1)

    def work(given: tuple[str, str]) -> object:
        report = compare(*given, PATH)
        assert [finding.code for finding in report.findings] == ["fact-lost"]
        assert len(report.findings[0].message) < 400
        return report

    assert_linear(texts, work, 2000, "the comparison, by one number repeated")


# ------------------------------------------------------------------------ the command

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

#: The file watcher is off: on a machine that turns it on, git in a repository made a
#: moment ago can wait for ever.
GIT = ("git", "-c", "core.fsmonitor=false", "-c", "user.name=A", "-c", "user.email=a@example.org")


def git(root: Path, *args: str) -> None:
    """Git, for the fixture's own commits, with the system's and the user's configuration
    kept out: a signing key or a folder of hooks of whoever runs the suite has no place in
    a commit made here."""
    nobodys = root.parent / "nobodys.gitconfig"
    nobodys.touch()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(nobodys), "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(
        [*GIT, *args], cwd=root, check=True, capture_output=True, timeout=60, env=env
    )


@pytest.fixture
def paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project in git with one commit, and the session standing in it."""
    root = tmp_path / "paper"
    (root / "manuscript" / "supplementary").mkdir(parents=True)
    (root / "paper.yaml").write_text("title: A paper\nstage: drafting\n", encoding="utf-8")
    (root / "manuscript" / "main.md").write_text(BEFORE, encoding="utf-8")
    (root / "manuscript" / "supplementary" / "s1.md").write_text(
        "# Supplement\n\nIt was {{results.extra}} in 4 centres.\n", encoding="utf-8"
    )
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the text before")
    monkeypatch.chdir(root)
    return root


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), encoding="utf-8")


@needs_git
def test_a_manuscript_as_it_was_committed_passes(
    paper: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["reworded"]) == 0
    out = capsys.readouterr().out
    assert "2 files" in out and "6 bindings, 3 citations and 5 numbers" in out, out


@needs_git
def test_an_edit_of_the_wording_passes(paper: Path, capsys: pytest.CaptureFixture[str]) -> None:
    edit(paper / "manuscript" / "main.md", "The reporting odds ratio was", "We estimated")
    assert main(["reworded"]) == 0
    assert "0 failing, 0 warnings" in capsys.readouterr().out


@needs_git
def test_an_edit_of_a_binding_fails_and_names_the_place(
    paper: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edit(paper / "manuscript" / "main.md", "{{results.ror.upper}})", "{{results.ror.lower}})")
    assert main(["reworded"]) == 1
    out = capsys.readouterr().out
    assert "the binding {{results.ror.upper}} is gone: it stood on line 4" in out, out
    assert "the binding {{results.ror.lower}} stands twice now, on lines 3 and 4" in out, out
    assert "main.md:4" in out, out
    assert "2 failing, 0 warnings" in out


@needs_git
def test_an_edit_in_the_supplement_is_read_too(paper: Path) -> None:
    edit(paper / "manuscript" / "supplementary" / "s1.md", "4 centres", "5 centres")
    assert main(["reworded"]) == 1


@needs_git
def test_a_change_of_order_alone_warns_and_passes(
    paper: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edit(paper / "manuscript" / "main.md", "in 3 of 12 centres", "in 12 centres, of which 3")
    assert main(["reworded"]) == 0
    assert "0 failing, 1 warning" in capsys.readouterr().out


@needs_git
def test_one_file_can_be_named(paper: Path) -> None:
    edit(paper / "manuscript" / "supplementary" / "s1.md", "4 centres", "5 centres")
    assert main(["reworded", "manuscript/main.md"]) == 0
    assert main(["reworded", "manuscript/supplementary/s1.md"]) == 1


@needs_git
def test_the_project_can_be_named_from_elsewhere(
    paper: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edit(paper / "manuscript" / "main.md", "77 reports", "78 reports")
    monkeypatch.chdir(tmp_path)
    assert main(["reworded", str(paper)]) == 1


@needs_git
def test_another_commit_can_be_named(paper: Path) -> None:
    edit(paper / "manuscript" / "main.md", "77 reports", "78 reports")
    git(paper, "commit", "-q", "-a", "-m", "a change that was meant")
    assert main(["reworded"]) == 0
    assert main(["reworded", "--since", "HEAD~1"]) == 1


@needs_git
def test_a_file_that_is_new_or_gone_fails(paper: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (paper / "manuscript" / "extra.md").write_text("It was 9 in all.\n", encoding="utf-8")
    (paper / "manuscript" / "supplementary" / "s1.md").unlink()
    assert main(["reworded"]) == 1
    out = capsys.readouterr().out
    assert "extra.md\n         this file is new since HEAD, and 1 binding, citation or" in out
    assert "s1.md\n         this file is gone, and 2 bindings, citations and numbers" in out, out


@needs_git
def test_a_new_file_that_holds_no_fact_is_only_told(
    paper: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (paper / "manuscript" / "notes.md").write_text("Words alone.\n", encoding="utf-8")
    assert main(["reworded"]) == 0
    out = capsys.readouterr().out
    assert "it holds no binding, citation or number" in out and "1 warning" in out, out


@needs_git
def test_a_folder_of_drafts_is_not_read(paper: Path) -> None:
    drafts = paper / "manuscript" / "_drafts"
    drafts.mkdir()
    (drafts / "old.md").write_text("It was 9 in all.\n", encoding="utf-8")
    assert main(["reworded"]) == 0


@needs_git
def test_a_revision_git_does_not_know_is_refused(
    paper: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["reworded", "--since", "no-such-branch"]) == 2
    assert "no-such-branch" in capsys.readouterr().err


@needs_git
def test_a_revision_that_is_an_option_is_refused(
    paper: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["reworded", "--since=--output=x"]) == 2
    assert not (paper / "x").exists()
    assert "--output=x" in capsys.readouterr().err


@needs_git
def test_json_is_the_report(paper: Path, capsys: pytest.CaptureFixture[str]) -> None:
    edit(paper / "manuscript" / "main.md", "77 reports", "78 reports")
    assert main(["reworded", "--json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert sorted(finding["code"] for finding in findings) == ["fact-lost", "fact-new"]


def test_outside_git_the_command_says_what_it_needs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "paper"
    (root / "manuscript").mkdir(parents=True)
    (root / "paper.yaml").write_text("title: A paper\n", encoding="utf-8")
    (root / "manuscript" / "main.md").write_text(BEFORE, encoding="utf-8")
    monkeypatch.chdir(root)
    # A folder under the system's temporary one may itself lie in somebody's repository.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert main(["reworded"]) == 2
    err = capsys.readouterr().err
    assert "--before" in err and "git" in err, err


@needs_git
def test_a_manuscript_folder_outside_the_project_is_refused_in_a_sentence(
    paper: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (paper / "paper.yaml").write_text(
        f"title: A paper\npaths:\n  manuscript: {elsewhere.as_posix()}\n", encoding="utf-8"
    )
    assert main(["reworded"]) == 2
    assert "is not under the project" in capsys.readouterr().err


def test_a_copy_of_the_text_before_can_be_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old, new = tmp_path / "before.md", tmp_path / "after.md"
    old.write_text(BEFORE, encoding="utf-8")
    new.write_text(BEFORE.replace("77 reports", "78 reports"), encoding="utf-8")
    assert main(["reworded", str(new), "--before", str(old)]) == 1
    assert "after.md:4" in capsys.readouterr().out
    assert main(["reworded", str(old), "--before", str(old)]) == 0


def test_a_copy_of_the_text_before_is_for_one_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = tmp_path / "before.md"
    old.write_text(BEFORE, encoding="utf-8")
    assert main(["reworded", "--before", str(old)]) == 2
    assert main(["reworded", str(old), str(old), "--before", str(old)]) == 2
    assert "one file" in capsys.readouterr().err


def test_a_file_that_is_not_there_is_said(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = tmp_path / "before.md"
    old.write_text(BEFORE, encoding="utf-8")
    assert main(["reworded", str(tmp_path / "none.md"), "--before", str(old)]) == 2
    assert "none.md" in capsys.readouterr().err
