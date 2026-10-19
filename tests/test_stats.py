"""The P a statistic gives, and the reading of a reported test.

The reference values were computed once with SciPy 1.13.0, outside the package, which
does not depend on it: `scipy.special.betainc` and `gammaincc`, and the survival functions
of `scipy.stats.t` (doubled), `f`, `chi2` and `norm` (doubled).
"""

from __future__ import annotations

import math

import pytest

from manuscript_guard.stats.reported import judge, reported_tests
from manuscript_guard.stats.special import (
    incomplete_beta,
    p_chi2,
    p_f,
    p_t,
    p_z,
    upper_gamma,
)

CHI = "\N{GREEK SMALL LETTER CHI}"

BETA = [
    (0.5, 0.5, 0.2, 0.2951672353008665),
    (1, 1, 0.37, 0.37),
    (2.5, 0.5, 0.9, 0.48958974456442755),
    (11.5, 0.5, 0.95, 0.282610519275954),
    (0.5, 3, 0.0001, 0.018748750037499998),
    (50, 20, 0.7, 0.3825092483812331),
    (300, 0.5, 0.999, 0.4386542688700909),
    (10, 300, 0.02, 0.09473281144837387),
    (1, 0.5, 0.999999, 0.9989999999999857),
]
GAMMA = [
    (0.5, 0.01, 0.887537083981715),
    (0.5, 3, 0.014305878435429641),
    (1, 1, 0.36787944117144245),
    (2.5, 1.7, 0.6385699231037951),
    (2.5, 40, 8.391825114831597e-16),
    (10, 5, 0.9681719426937951),
    (10, 30, 7.121750862815593e-06),
    (50, 45, 0.7531979655998298),
    (150, 200, 9.678621994933555e-05),
    (0.5, 100, 2.0884875837625688e-45),
]
T = [
    (2.45, 23, 0.022315728160948598),
    (0.5, 5, 0.638298871640929),
    (12.0, 3, 0.0012450158007893358),
    (1.96, 1000, 0.050273184955748715),
    (6.2, 40, 2.4736073955456035e-07),
    (2.0, 1, 0.2951672353008664),
]
F = [
    (3.21, 2, 45, 0.049751930031996475),
    (0.8, 1, 10, 0.3921122204193769),
    (25.0, 3, 100, 3.7571269090922594e-12),
    (4.0, 4, 4, 0.10400000000000002),
]
CHI2 = [
    (4.5, 1, 0.033894853524689295),
    (0.2, 10, 0.9999999233219832),
    (60.0, 3, 5.878230727906921e-13),
    (15.0, 15, 0.4514172112257257),
]
Z = [
    (0.5, 0.6170750774519738),
    (1.96, 0.04999579029644087),
    (3.3, 0.0009668482847675551),
    (6.0, 1.9731752900753896e-09),
]


@pytest.mark.parametrize(("a", "b", "x", "expected"), BETA)
def test_the_incomplete_beta_function_is_scipys(a, b, x, expected) -> None:
    assert math.isclose(incomplete_beta(a, b, x), expected, rel_tol=1e-10)


@pytest.mark.parametrize(("a", "x", "expected"), GAMMA)
def test_the_incomplete_gamma_function_is_scipys(a, x, expected) -> None:
    assert math.isclose(upper_gamma(a, x), expected, rel_tol=1e-10)


@pytest.mark.parametrize(("t", "df", "expected"), T)
def test_the_p_of_t_is_scipys(t, df, expected) -> None:
    assert math.isclose(p_t(t, df), expected, rel_tol=1e-10)
    assert math.isclose(p_t(-t, df), expected, rel_tol=1e-10)


@pytest.mark.parametrize(("f", "d1", "d2", "expected"), F)
def test_the_p_of_f_is_scipys(f, d1, d2, expected) -> None:
    assert math.isclose(p_f(f, d1, d2), expected, rel_tol=1e-10)


@pytest.mark.parametrize(("chi2", "df", "expected"), CHI2)
def test_the_p_of_chi_squared_is_scipys(chi2, df, expected) -> None:
    assert math.isclose(p_chi2(chi2, df), expected, rel_tol=1e-10)


@pytest.mark.parametrize(("z", "expected"), Z)
def test_the_p_of_z_is_scipys(z, expected) -> None:
    assert math.isclose(p_z(z), expected, rel_tol=1e-10)


def test_the_functions_refuse_what_is_not_defined() -> None:
    for call in (
        lambda: incomplete_beta(0, 1, 0.5),
        lambda: incomplete_beta(1, 1, 1.5),
        lambda: upper_gamma(-1, 1),
        lambda: p_t(2, 0),
        lambda: p_f(2, 1, 0),
        lambda: p_chi2(2, 0),
    ):
        with pytest.raises(ValueError):
            call()
    assert incomplete_beta(2, 3, 0.0) == 0.0
    assert incomplete_beta(2, 3, 1.0) == 1.0
    assert upper_gamma(2, 0.0) == 1.0
    assert p_f(0.0, 1, 5) == 1.0


def _one(text: str):
    found = reported_tests(text)
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize(
    ("text", "kind", "statistic", "df", "sign", "p"),
    [
        ("Groups differed, t(23) = 2.45, p = .022.", "t", "2.45", ("23",), "=", ".022"),
        ("*F*(2, 45) = 3.21, *P* = 0.050.", "F", "3.21", ("2", "45"), "=", "0.050"),
        (f"a {CHI}2(1, N = 90) = 4.5, p < .05", "chi2", "4.5", ("1",), "<", ".05"),
        (f"a {CHI}\N{SUPERSCRIPT TWO}(1) = 4.5, p = .034", "chi2", "4.5", ("1",), "=", ".034"),
        ("a chi-square(3) = 9.1, p = .03", "chi2", "9.1", ("3",), "=", ".03"),
        ("t = 2.45, df = 23, P = 0.022", "t", "2.45", ("23",), "=", "0.022"),
        ("z = 4.10, P = 4.1e-5 was seen", "z", "4.10", (), "=", "4.1e-5"),
        ("z = 4.10, P = 4.1 x 10^-5^ was seen", "z", "4.10", (), "=", "4.1 x 10^-5^"),
        ("t(23) =\n  2.45, p\n= .022", "t", "2.45", ("23",), "=", ".022"),
        ("t(23) = 2.45, *p*-value \x00< .05", "t", "2.45", ("23",), "<", ".05"),
        ("F(1,234) = 5.6, p = .019", "F", "5.6", ("1", "234"), "=", ".019"),
        ("t(23) = \N{MINUS SIGN}2.45, p = .022", "t", "\N{MINUS SIGN}2.45", ("23",), "=", ".022"),
    ],
)
def test_a_reported_test_is_read_as_it_is_written(text, kind, statistic, df, sign, p) -> None:
    test = _one(text)
    assert (test.kind, test.statistic, test.df, test.sign, test.p) == (
        kind, statistic, df, sign, p,
    )  # fmt: skip
    assert judge(test) is not None
    assert not judge(test).inconsistent


@pytest.mark.parametrize(
    "text",
    [
        "at(3) = 4, p = .5",
        "F = 3.21, p = .05",  # no degrees of freedom
        "t(2, 3) = 3.1, p = .05",  # a t has one
        "t(23) = 2.45. The P was .40",  # the P is in the next sentence
        "t(23) = 2.45\n\np = .40",
        "t(23) = 2.45 and t(30) = 2.10",  # no P at all
    ],
)
def test_what_is_not_a_reported_test_is_not_read_as_one(text) -> None:
    assert reported_tests(text) == []


def test_a_p_is_the_statistic_s_before_it_and_not_the_one_after() -> None:
    """Two statistics and one P: the P is the second's, and the first has none."""
    (test,) = reported_tests("t(23) = 2.45 and t(30) = 2.10, both p < .05.")
    assert (test.statistic, test.df) == ("2.10", ("30",))


@pytest.mark.parametrize(
    ("text", "inconsistent", "decision"),
    [
        ("t(23) = 2.45, p = .022", False, False),
        ("t(23) = 2.45, p = .041", True, False),
        ("t(23) = 2.45, p = .40", True, True),
        ("t(23) = 2.45, p < .05", False, False),
        ("t(23) = 2.45, p < .01", True, False),
        ("t(23) = 1.20, p < .05", True, True),
        ("t(23) = 2.45, p > .05", True, True),
        # Printed to one decimal, 2.1 runs from 2.05 to 2.15, a P of 0.044 to 0.052.
        ("t(30) = 2.1, p = .05", False, False),
        ("z = 1.96, p = .05", False, False),
        # 0.049 is not what 3.21 on (2, 45) gives, 0.0495 to 0.0500, but both are below
        # 0.05: an inconsistency and no decision error.
        ("F(2, 45) = 3.21, p = .049", True, False),
        (f"{CHI}2(1) = 0.5, p < .05", True, True),
    ],
)
def test_a_p_is_judged_over_every_value_its_digits_allow(text, inconsistent, decision) -> None:
    verdict = judge(_one(text))
    assert (verdict.inconsistent, verdict.decision) == (inconsistent, decision)


@pytest.mark.parametrize(
    "said",
    [
        "a one-sided t(23) = 2.45, p = .011",
        "Welch's t(23.4) = 2.45, p = .011",
        "after Bonferroni adjustment, t(23) = 2.45, p = .09",
        "F(1.4, 33.2) = 5.6, p = .09, Greenhouse-Geisser corrected",
        f"{CHI}2(1) = 4.5, p = .06 by Fisher's exact test",
        "a permutation t(23) = 2.45, p = .011",
        # Round 1 of #285: two named procedures were missing.
        "t(23) = 2.45, p = .09 against control by Dunnett's test",
        "Games-Howell t(23.4) = 2.45, p = .09",
    ],
)
def test_a_test_the_sentence_says_is_not_the_textbook_one_is_not_judged(said) -> None:
    test = _one(said)
    assert test.quiet
    assert judge(test) is None


def test_a_p_judged_at_the_level_the_analysis_declares() -> None:
    test = _one("t(23) = 1.90, p = .03")  # gives 0.070
    assert judge(test, 0.05).decision
    assert judge(test, 0.10).inconsistent and not judge(test, 0.10).decision


@pytest.mark.parametrize(
    "text",
    [
        # Round 1 of #285: a decimal written with a middle dot or a comma was read as its
        # whole part, "p<0·0001" as a P of 0, and the test was reported.
        "t(23) = 2\N{MIDDLE DOT}45, p = 0\N{MIDDLE DOT}022",
        "t(23) = 2.45, p < 0\N{MIDDLE DOT}0001",
        "t(23) = 2,45, p = 0,022",
        "t(23) = 2.45, p = 0,022",
    ],
)
def test_a_decimal_point_that_is_no_full_stop_is_not_read(text) -> None:
    assert reported_tests(text) == []


@pytest.mark.parametrize(
    ("text", "statistic", "p"),
    [
        # Round 1 of #336: a number with its point already is no decimal-comma number, and a
        # comma and a digit after it, a reference set inline in text from a PDF, left the
        # test unread.
        ("t(23) = 2.45, p = 0.40,12 and later.", "2.45", "0.40"),
        ("t(23) = 2.45,12 p = 0.40.", "2.45", "0.40"),
        # A middle dot before a power of ten is a times sign, and a comma after the power
        # is the sentence's (round 2 of #336: nothing held the second).
        ("t(23) = 6.10, p = 4\N{MIDDLE DOT}10^-6^.", "6.10", "4\N{MIDDLE DOT}10^-6^"),
        ("t(23) = 6.10, p = 4\N{MIDDLE DOT}10^-6^,12 and later.", "6.10",
         "4\N{MIDDLE DOT}10^-6^"),
    ],
)
def test_a_comma_after_a_number_with_its_point_is_the_sentence_s(text, statistic, p) -> None:
    [found] = reported_tests(text)
    assert (found.statistic, found.p) == (statistic, p)


def test_a_point_that_groups_thousands_in_a_decimal_comma_paper_is_read_as_a_point() -> None:
    """A Known gap (round 2 of #336): in a paper that writes its decimals with a comma, a
    point groups thousands, and "1.234,5" is read as 1.234. Such a paper writes its P with a
    comma too, which is not read, so a test is formed only where its P has a point."""
    assert [t.statistic for t in reported_tests("χ2(1) = 1.234,5, p = .40")] == ["1.234"]


def test_a_p_cut_off_by_the_reach_is_not_read() -> None:
    """Round 1 of #285: the P was looked for up to `REACH` characters on, and one whose
    digits ran past that point was read cut, "0.0412" as "0.04"."""
    from manuscript_guard.stats.reported import REACH

    stat = "t(23) = 2.45, "
    text = stat + "a" * (REACH - 11) + " p = 0.0412 later."
    # The reach ends just after "0.04", inside the P's digits.
    assert text.index("p = 0.04") + len("p = 0.04") == len("t(23) = 2.45") + REACH
    assert reported_tests(text) == []


@pytest.mark.parametrize("point", ["\N{MIDDLE DOT}", ","])
def test_a_p_cut_before_its_middle_dot_or_comma_is_not_read(point: str) -> None:
    """Round 1 of #336: cut at the reach, "p = 0" was read, and read again whole it was no
    P at all, since its point is not read; the check of the cut raised."""
    from manuscript_guard.stats.reported import REACH

    text = "t(23) = 2.45, " + "a" * (REACH - 8) + f" p = 0{point}022 later."
    assert text.index("p = 0") + len("p = 0") == len("t(23) = 2.45") + REACH
    assert reported_tests(text) == []


def test_a_p_above_1_is_not_judged() -> None:
    """Round 1 of #285: "P = 2" gave a range from 1.95 down to 1."""
    assert judge(_one("t(23) = 2.45, p = 2")) is None


def test_a_p_that_cannot_be_computed_is_not_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1 of #285: a series that did not converge escaped, and the gate errored."""
    from manuscript_guard.stats import reported
    from manuscript_guard.stats.special import NotConverged

    def never(*_args):
        raise NotConverged("a continued fraction did not converge")

    monkeypatch.setattr(reported, "_p", never)
    assert judge(_one("t(23) = 2.45, p = .022")) is None


def test_a_p_written_before_its_statistic_is_read_as_the_next_one_s() -> None:
    """A known gap, pinned (round 1 of #285, in Known gaps): a statistic takes the next P in
    its sentence, so where each P stands before its own statistic the first statistic is
    judged with the second's P."""
    found = reported_tests("P = .022 (t(23) = 2.45); P = .40 (t(30) = 0.85).")
    assert [(test.statistic, test.p) for test in found] == [("2.45", ".40")]


def test_adjusted_said_of_anything_stands_a_test_down() -> None:
    """A known gap, pinned (round 1 of #285, in Known gaps): "adjusted for age" says the
    P is not the textbook one, though a Wald z of an adjusted model is."""
    assert _one("Adjusted for age, z = 2.10, P = .40").quiet == "Adjusted"
