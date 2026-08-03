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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The ROR was 3.84[@smith2020].", ["3.84"]),
        ("The response rate reached 68%[^1] in the arm.", ["68%"]),
        ("(95% CI 2.10–7.04)[@ref]", ["95%", "2.10–7.04"]),
        ("A total of 41 200[^1] reports.", ["41", "200"]),
        ("Significance was p=0.03{.highlight} throughout.", ["p=0.03"]),
        ("The value {{results.ror.point}} held.", []),
    ],
)
def test_a_number_written_hard_against_a_mask_is_still_read(text: str, expected: list) -> None:
    """The version of this test that used spaces passed while the gate was blind.

    `mask()` writes NUL to preserve offsets, and NUL is not whitespace, so a tokeniser
    splitting on `\\S+` read `3.84[@smith2020]` as one run, saw a NUL in it, and threw the
    whole run away — the visible 3.84 with it. Every one of these cases produced *zero*
    atoms, which is the gate going silent on an ordinary way of writing a citation.
    """
    assert atoms_of(text) == expected


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


@pytest.mark.parametrize(
    "text",
    [
        # `per <digits>` was a shape, not a set of conventional values, so a cohort size
        # written this way was exempted from the gate entirely.
        "The rate was 12 per 83,214 patients treated.",
        "Observed in 4 per 617 exposures.",
        # `<digits>+` matched with the unit optional, so any rounded count was an age band.
        "The trial enrolled 500+ patients across ten centres.",
        "Response was seen in 45+ mg dosing groups.",
        # `<keyword> <digits>` with an unbounded `\d+`: ordinary English word order, needing
        # only a missing comma, filed the count as a category or a timepoint.
        "In the exposed arm 47 hepatic events occurred.",
        "In the pooled cohort 3841 reports were assessed.",
        "Over the study years 1204 reports were received.",
    ],
)
def test_a_widened_rule_does_not_wave_a_real_number_through(text: str) -> None:
    """Each of these classified as convention or structural, and none is either."""
    classifier = Classifier.load()
    found = find_atoms(text, mask(text))
    assert found
    assert all(classifier.classify(a).kind == UNCLASSIFIED for a in found), [
        (a.text, classifier.classify(a).rule) for a in found
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Rates per 100,000 person-years.",
        "Per 1 000 patients treated.",
        "Adults aged 65+ years.",
        "Grade 3 events were rare.",
        "A phase 2 trial of the same agent.",
        "Assessed at day 365 of follow-up.",
        "Randomised to arm 2 of the study.",
    ],
)
def test_narrowing_those_rules_kept_the_cases_they_exist_for(text: str) -> None:
    assert verdict_of(text) in (CONVENTION, STRUCTURAL)


def test_the_abstract_in_front_matter_is_checked_like_any_other_prose() -> None:
    """Front matter was masked whole, so pandoc rendered a title and an abstract that no
    gate had read. The abstract is the most-read part of a paper, and a fabricated ROR and
    cohort size sitting in it were invisible. Machinery in the same block stays masked."""
    text = (
        "---\n"
        'title: "A 3.84-fold excess"\n'
        "lang: en-GB\n"
        "zotero:\n"
        "  client: zotero\n"
        "abstract: |\n"
        "  ROR 3.84 across 41200 reports.\n"
        "---\n"
        "\n"
        "Body.\n"
    )
    assert atoms_of(text) == ["3.84-fold", "3.84", "41200"]


def test_a_citation_rule_needed_only_for_rendered_text_stays_out_of_the_gate() -> None:
    """`author-year-citation` spans a whole parenthetical, and a span accepts every atom in
    it, so in manuscript source `(Smith 2019, n = 412)` filed 412 as structural. Source
    citations are `[@key]` and already masked, so the rule belongs to `audit` alone."""
    text = "In a cohort study (Smith 2019, n = 412) the effect held."
    atoms = find_atoms(text, mask(text))
    assert [Classifier.load().classify(a).kind for a in atoms] == [UNCLASSIFIED, UNCLASSIFIED]
    rendered = Classifier.load(rendered=True)
    assert [rendered.classify(a).kind for a in atoms] == [STRUCTURAL, STRUCTURAL]


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
