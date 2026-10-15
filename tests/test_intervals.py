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
