"""How an estimate and its confidence interval are read from a sentence, and what is said
of them (`stats/intervals.py`)."""

from __future__ import annotations

import pytest

from manuscript_guard.stats.intervals import (
    ASYMMETRY,
    alpha_of,
    asymmetry,
    p_against,
    reported_intervals,
)


def _one(text: str):
    found = reported_intervals(text)
    assert len(found) == 1, (text, found)
    return found[0]


@pytest.mark.parametrize(
    ("text", "read"),
    [
        ("The odds ratio was 2.6 (95% CI 2.1 to 3.2).",
         ("ratio", "odds ratio", "2.6", "2.1", "3.2", "95", None)),
        ("ROR 2.6, 95% CI 2.1-3.2", ("ratio", "ROR", "2.6", "2.1", "3.2", "95", None)),
        ("HR 0.80; 95% CI: 0.70, 0.91; P < 0.001",
         ("ratio", "HR", "0.80", "0.70", "0.91", "95", ("<", "0.001"))),
        ("aOR = 1.5 [CI 95% 1.1\N{EN DASH}2.0], p = .03",
         ("ratio", "aOR", "1.5", "1.1", "2.0", "95", ("=", ".03"))),
        ("the reporting odds\nratio was 3.21\n(95% confidence interval 2.10 to 4.90)",
         ("ratio", "reporting odds ratio", "3.21", "2.10", "4.90", "95", None)),
        ("RR = 1.50, 90% CI 1.02-2.20, P = 0.07",
         ("ratio", "RR", "1.50", "1.02", "2.20", "90", ("=", "0.07"))),
        ("The mean difference was \N{MINUS SIGN}0.4 (95% CI \N{MINUS SIGN}0.9 to 0.1)",
         ("difference", "mean difference", "\N{MINUS SIGN}0.4", "\N{MINUS SIGN}0.9", "0.1",
          "95", None)),
        ("MD -0.4 (95% CI -0.9 to -0.1), P = 0.01",
         ("difference", "MD", "-0.4", "-0.9", "-0.1", "95", ("=", "0.01"))),
    ],
)  # fmt: skip
def test_an_estimate_and_its_interval_are_read_as_printed(text: str, read: tuple) -> None:
    found = _one(text)
    assert (
        found.kind, found.name, found.estimate, found.low, found.high, found.level, found.p
    ) == read  # fmt: skip


@pytest.mark.parametrize(
    "text",
    [
        # "--" is an en dash in Markdown, or a hyphen and a minus: the sign is not sure.
        "MD -0.4 (95% CI -0.9--0.1)",
        # An upper bound below the lower.
        "OR 2.6 (95% CI 3.2 to 2.1)",
        # No name says what the estimate is, and so what its null is.
        "It was 2.6 (95% CI 2.1 to 3.2)",
        # An interval across a blank line is two paragraphs.
        "OR 2.6\n\n(95% CI 2.1 to 3.2)",
    ],
)
def test_an_interval_whose_reading_is_not_sure_is_not_read(text: str) -> None:
    assert reported_intervals(text) == []


def test_a_ratio_at_the_middle_of_its_interval_within_its_rounding_is_symmetric() -> None:
    """The brief's example: "ROR 2.6, 95% CI 2.1-3.2" has arms that differ by 2.8% of its
    half-width as printed, and by nothing over the values its digits allow."""
    assert asymmetry(_one("ROR 2.6, 95% CI 2.1-3.2")) == 0.0
    held = asymmetry(_one("ROR 2.60000, 95% CI 2.10000-3.20000"))
    assert held is not None and 0.0279 < held < 0.0283


@pytest.mark.parametrize(
    ("text", "far"),
    [
        ("OR 2.6 (95% CI 1.2 to 3.2)", True),
        ("OR 2.80 (95% CI 1.60 to 3.10)", True),
        ("OR 1.9 (95% CI 1.2 to 3.0)", False),
        ("HR 0.80 (95% CI 0.70 to 0.91)", False),
        # Profile-likelihood intervals with three and two events in a group: lopsided as
        # such intervals are, and under the threshold.
        ("OR 2.81 (95% CI 0.79 to 13.13)", False),
        ("OR 2.58 (95% CI 0.54 to 18.30)", False),
    ],
)
def test_a_ratio_away_from_the_middle_of_its_interval_is_asymmetric(text: str, far: bool) -> None:
    share = asymmetry(_one(text))
    assert share is not None and (share > ASYMMETRY) is far, share


@pytest.mark.parametrize(
    "text",
    [
        "MD 2.6 (95% CI 1.2 to 3.2)",
        "OR 2.6 (95% profile-likelihood CI 1.2 to 3.2)",
        "OR 2.6 (exact 95% CI 1.2 to 3.2)",
        "OR 2.6 (bootstrap 95% CI 1.2 to 3.2)",
        "OR 2.6 (95% CI 0.0 to 3.2)",
    ],
)
def test_an_interval_that_need_not_be_symmetric_is_not_measured(text: str) -> None:
    assert asymmetry(_one(text)) is None


@pytest.mark.parametrize(
    ("text", "against"),
    [
        ("OR 1.9 (95% CI 1.2 to 3.0), P = 0.40", True),
        ("OR 1.9 (95% CI 1.2 to 3.0), P > 0.05", True),
        ("OR 1.9 (95% CI 1.2 to 3.0), P = 0.003", False),
        ("OR 1.9 (95% CI 0.9 to 4.0), P < 0.001", True),
        ("OR 1.9 (95% CI 0.9 to 4.0), P = 0.09", False),
        ("MD 0.4 (95% CI -0.2 to 1.0), P = 0.001", True),
        ("MD 0.4 (95% CI 0.1 to 0.7), P = 0.01", False),
        # At 90%, a P of 0.07 is below one less the level.
        ("RR 1.50 (90% CI 1.05 to 2.14), P = 0.07", False),
        ("RR 1.50 (99% CI 1.05 to 2.14), P = 0.03", True),
        # A bound whose rounding reaches the null, or a P whose rounding reaches the level.
        ("OR 1.9 (95% CI 1.0 to 3.6), P = 0.40", False),
        ("OR 1.9 (95% CI 1.2 to 3.0), P = 0.05", False),
        # "Adjusted" alone is said of the estimate: judged.
        ("The adjusted OR was 1.9 (95% CI 1.2 to 3.0), P = 0.40", True),
    ],
)
def test_an_interval_and_its_p_that_disagree_about_the_null_are_found(
    text: str, against: bool
) -> None:
    assert (p_against(_one(text)) is not None) is against


@pytest.mark.parametrize(
    "text",
    [
        "OR 1.9 (95% CI 1.2 to 3.0), Bonferroni-adjusted P = 0.40",
        "OR 1.9 (95% CI 1.2 to 3.0), P = 0.40 after correction for multiple testing",
        "OR 1.9 (95% CI 1.2 to 3.0), adjusted P = 0.40",
        "OR 1.9 (95% CI 1.2 to 3.0), one-sided P = 0.40",
        "OR 1.9 (95% CI 1.2 to 3.0), exact P = 0.40",
        "OR 1.9 (95% CI 1.2 to 3.0), P = 0.40 for interaction",
        "OR 1.9 (95% CI 1.2 to 3.0), P for trend = 0.40",
        "OR 1.9 (95% CI 1.2 to 3.0). P = 0.40 in the next sentence",
    ],
)
def test_a_p_that_is_not_the_plain_one_or_not_the_estimate_s_is_not_judged(text: str) -> None:
    assert p_against(reported_intervals(text)[0]) is None


def test_a_p_after_another_interval_is_that_one_s() -> None:
    text = "OR 1.9 (95% CI 1.2 to 3.0) in men and 1.1 (95% CI 0.8 to 1.5) in women, P = 0.40"
    assert [found.p for found in reported_intervals(text)] == [None]


@pytest.mark.parametrize(
    ("level", "alpha"), [("95", 0.05), ("", 0.05), ("90", 0.1), ("99.9", 0.001), ("100", None)]
)
def test_one_less_the_level_is_the_alpha(level: str, alpha: float | None) -> None:
    assert alpha_of(level) == alpha


@pytest.mark.parametrize(
    ("text", "outside"),
    [
        ("The odds ratio was 2.6 (95% CI 2.1 to 2.3)", True),
        ("OR 3.50 (95% CI 1.60 to 3.10)", True),
        ("MD 1.4 (95% CI 0.2 to 0.9)", True),
        ("MD -1.4 (95% CI -0.9 to -0.2)", True),
        ("OR 2.3 (95% CI 2.1 to 2.3)", False),
        ("OR 2.6 (95% CI 2.1 to 3.2)", False),
    ],
)
def test_an_estimate_outside_its_own_interval_is_found(text: str, outside: bool) -> None:
    """Round 1 of #300: the most lopsided interval of all, a bound transposed past its
    estimate, was the one not measured."""
    from manuscript_guard.stats.intervals import outside_interval

    assert outside_interval(_one(text)) is outside


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("No difference in mortality, HR 0.83 (95% CI 0.65 to 1.05), P = 0.13.", "HR"),
        ("There was no significant difference, OR 1.2 (95% CI 0.9 to 1.6), P = 0.20.", "OR"),
        ("The difference, RR 1.5 (95% CI 1.1 to 2.0)", "RR"),
    ],
)
def test_a_ratio_named_after_the_word_difference_is_read_as_a_ratio(text: str, name: str) -> None:
    """Round 1 of #300: a bare "difference" took the gap after it across the ratio's name,
    and the ratio was judged against 0."""
    found = _one(text)
    assert (found.kind, found.name) == ("ratio", name)
    assert p_against(found) is None


@pytest.mark.parametrize(
    "text",
    [
        "No difference in mortality, SMR 1.4 (95% CI 1.1 to 1.8), P = 0.40.",
        "No difference in incidence, SIR 1.4 (95% CI 1.1 to 1.8), P = 0.40.",
        "No difference, ratio of means 1.4 (95% CI 1.1 to 1.8), P = 0.40.",
        # Names too long to stand within the gap: no difference reaches across them anyway
        # (round 1 of #336).
        "No difference: the standardised mortality ratio was 1.4 (95% CI 1.1 to 1.8), P = 0.40.",
        "No difference, a ratio of geometric means of 1.4 (95% CI 1.1 to 1.8), P = 0.40.",
    ],
)
def test_a_difference_is_not_read_across_a_ratio_it_does_not_judge(text: str) -> None:
    """Round 2 of #300: a bare "difference" took the gap after it across an SMR, which is
    no ratio this reads (its exact interval need not be symmetric on the log scale), and
    judged the SMR against 0. The name stops the gap, and nothing is read."""
    assert reported_intervals(text) == []


def test_a_minus_written_as_an_en_dash_before_an_estimate_is_read() -> None:
    """Round 2 of #300: "–1.4" lost its en dash to the words before it, and 1.4 was said to
    lie outside its own interval, -2.0 to -0.8. Round 1 of #336: a ratio is never negative,
    so before its estimate an en dash is a dash, and "OR–1.9" was read as -1.9, outside 1.2
    to 3.0; round 2: before a difference's it is still its minus, "MD–0.4"."""
    from manuscript_guard.stats.intervals import outside_interval

    found = _one("The mean difference was \N{EN DASH}1.4 (95% CI -2.0 to -0.8).")
    assert found.estimate == "\N{EN DASH}1.4" and not outside_interval(found)
    glued = _one("OR\N{EN DASH}1.9 (95% CI 1.2 to 3.0).")
    assert glued.estimate == "1.9" and not outside_interval(glued)
    minus = _one("MD\N{EN DASH}0.4 (95% CI -0.8 to -0.1).")
    assert minus.estimate == "\N{EN DASH}0.4" and not outside_interval(minus)


@pytest.mark.parametrize(
    ("text", "said"),
    [
        # A P in a later clause is taken as the estimate's, the search stopping only at
        # another interval's name.
        ("The OR was 1.9 (95% CI 1.2-3.0) but not in women (OR 1.1, P = 0.40).", True),
        # "HR" for heart rate is read as a hazard ratio, held to 1.
        ("HR 72 (95% CI 68 to 76), P = 0.40.", True),
        # An interval with no level printed is taken as 95%: as a 90% interval this agrees.
        ("The ratio, OR 1.9 (CI 1.2 to 3.0), P = 0.07.", True),
        # A difference between two hazard ratios is read as a hazard ratio.
        ("The difference in hazard ratios between arms was 0.3 (95% CI -0.1 to 0.7), "
         "P = 0.40.", True),
        # A word saying the P is another's, within 40 characters after it, stands it down,
        # and so does one between the interval and the P (round 1 of #336).
        ("OR 1.9 (95% CI 1.2 to 3.0), P = 0.40, with no heterogeneity.", False),
        ("OR 1.9 (95% CI 1.2 to 3.0) for interaction, P = 0.40.", False),
    ],
)  # fmt: skip
def test_what_the_interval_reader_gets_wrong_is_pinned(text: str, said: bool) -> None:
    """Known gaps, pinned (rounds 1 and 2 of #300): each is said, or not, as written in
    DESIGN.md, so that a change to any of them is seen."""
    assert (p_against(_one(text)) is not None) is said
