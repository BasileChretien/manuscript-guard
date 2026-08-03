"""Unit tests for the parts the corruption harness exercises only indirectly.

Masking is where a checker like this most easily goes wrong in the dangerous direction: a
region masked by mistake hides real claims and the gate goes quiet. These tests pin both
sides — what must be ignored, and what must never be.
"""

from __future__ import annotations

import pytest

from manuscript_guard.classify import CONVENTION, STRUCTURAL, TERM, UNCLASSIFIED, Classifier
from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import parse, substitute
from manuscript_guard.text.tokens import find_atoms


def atoms_of(text: str) -> list[str]:
    return [a.text for a in find_atoms(text, mask(text))]


def verdict_of(text: str) -> str:
    classifier = Classifier.load()
    found = find_atoms(text, mask(text))
    assert found, f"no atom found in {text!r}"
    return classifier.classify(found[0]).kind


# ---------------------------------------------------------------- masking


@pytest.mark.parametrize(
    "text",
    [
        "---\nyear: 2019\n---\n\nBody.",
        "Some `code with 42` inline.",
        "```\nx <- 42\n```\n",
        "<!-- a note about 42 -->",
        "See <https://example.org/10.1000/abc123>.",
        "A claim [@smith2020hepatic].",
        "As @smith2020hepatic showed.",
        "A [link](https://example.org/page/42).",
        "A binding {{results.cohort.n_total}}.",
        "A footnote[^note42].",
    ],
)
def test_masked_regions_yield_no_atoms(text: str) -> None:
    assert atoms_of(text) == []


def test_prose_around_a_masked_region_is_still_read() -> None:
    """The dangerous failure is over-masking, so check the neighbours survive."""
    assert atoms_of("We found 37 cases [@smith2020] in 2019.") == ["37", "2019"]


def test_a_year_in_prose_is_not_exempt() -> None:
    """A study period is data and belongs in results, so a bare year must be reported."""
    assert verdict_of("Recruitment ran until 2019.") == UNCLASSIFIED


# ---------------------------------------------------------------- tokenising


def test_atoms_keep_digit_bearing_names_whole() -> None:
    assert atoms_of("Both CYP3A4 and COVID-19 were considered.") == ["CYP3A4", "COVID-19"]


def test_surrounding_punctuation_is_trimmed() -> None:
    assert atoms_of("The value was (12.4%), then fell.") == ["12.4%"]


def test_words_without_digits_are_not_atoms() -> None:
    assert atoms_of("No numbers here at all.") == []


# ---------------------------------------------------------------- classifying


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Both CYP2C19 phenotypes.", TERM),
        ("Reported for COVID-19.", TERM),
        ("Shown in Table 2.", STRUCTURAL),
        ("See Figure 1 and Supplementary Table 3.", STRUCTURAL),
        ("Grade 3 events were rare.", STRUCTURAL),
        ("At day 30 after exposure.", STRUCTURAL),
        ("30-day mortality was assessed.", STRUCTURAL),
        ("Significance was set at p < 0.05.", CONVENTION),
        ("Reported with 95% CI.", CONVENTION),
        ("A 95% confidence interval was used.", CONVENTION),
        ("Rates per 100 000 person-years.", CONVENTION),
        ("A 2 x 2 contingency table.", CONVENTION),
        ("The odds ratio was 3.42.", UNCLASSIFIED),
        ("There were 128 reports.", UNCLASSIFIED),
        ("Mortality reached 12.4%.", UNCLASSIFIED),
    ],
)
def test_classification(text: str, expected: str) -> None:
    assert verdict_of(text) == expected


@pytest.mark.parametrize("text", ["p < 0.37", "p < 0.5", "an 89% CI", "power of 63%"])
def test_conventions_are_pinned_to_conventional_values(text: str) -> None:
    assert verdict_of(f"We report {text} here.") == UNCLASSIFIED


def test_project_terms_extend_the_shipped_list() -> None:
    classifier = Classifier.load(extra_terms=("widget-7",))
    atom = find_atoms("The widget-7 device.", mask("The widget-7 device."))[0]
    assert classifier.classify(atom).kind == TERM


# ---------------------------------------------------------------- placeholders


def test_parse_finds_bindings_and_flags_malformed() -> None:
    good, bad = parse("{{results.a.b}} and {{lit.c}} and {{oops}} and {{Results.D}}")
    assert [p.ref for p in good] == ["results.a.b", "lit.c"]
    assert {raw for raw, _o, _l in bad} == {"{{oops}}", "{{Results.D}}"}


def test_block_namespaces_are_recognised_but_not_values() -> None:
    good, _ = parse("{{table.baseline}} {{figure.forest}}")
    assert [p.ref for p in good] == ["table.baseline", "figure.forest"]
    assert not any(p.is_value for p in good)


def test_substitute_replaces_only_known_refs() -> None:
    out = substitute("a={{results.a}} b={{results.b}}", {"results.a": "12"})
    assert out == "a=12 b={{results.b}}"
