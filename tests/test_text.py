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
    [("Some `code with 42` inline.", ["42"]), ("The odds ratio was `3.84`.", ["3.84"])],
)
def test_inline_code_renders_so_it_is_read_as_prose(text: str, expected: list) -> None:
    """`3.84` in backticks prints as 3.84, and inline code is a word in a sentence.

    Masking it meant a number could be published by wrapping it in punctuation. Fenced
    blocks are a different case — see the fenced-block tests — because a listing's loop
    bounds and indices are code, not claims, and reading them as prose put eleven failures
    on one honest Methods section.

    Word counting still excludes both. That question is "what would a journal count?", not
    "where is a digit not a claim?", and the two were sharing one answer.
    """
    assert atoms_of(text) == expected


FENCE = "`" * 3


def test_a_fenced_block_is_not_read_as_prose() -> None:
    """Its numbers are code, and the prose classifier has no business judging them."""
    assert atoms_of(f"Result:\n\n{FENCE}\nROR 3.84\n{FENCE}\n") == []


@pytest.mark.parametrize(
    ("body", "language", "codes"),
    [
        # A listing's own machinery: a seed, an index, a z-multiplier. Silent.
        ("set.seed(20240115)\nci <- exp(log(r) + c(-1, 1) * 1.96 * se)\n", "r", set()),
        # A number the listing *prints* is a claim, because that is text in the document.
        ('print("ROR 3.84 (95% CI 2.10 to 7.04)")\n', "python", {"code-block-text-number"}),
        # A language with no lexer is said to be unread rather than passed over.
        ("some untagged 4242 block\n", "", {"code-block-unread"}),
    ],
)
def test_a_fenced_block_is_judged_as_code(body: str, language: str, codes: set) -> None:
    from pathlib import Path

    from manuscript_guard.gates.numbers import _fenced_code

    text = f"## Statistical analysis\n\n{FENCE}{language}\n{body}{FENCE}\n"
    report = _fenced_code(Path("main.md"), text, Classifier.load())
    assert {f.code for f in report.findings} == codes


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("About ½ of the cohort was female.", ["½"]),
        ("Groups ④ and ⑧ were pooled.", ["④", "⑧"]),
        # Superscripts stay out: these are units and names, not claims.
        ("The area was 12 m² and R² was high.", ["12"]),
        ("A phase Ⅲ trial.", []),
    ],
)
def test_numbers_that_are_not_ascii_digits(text: str, expected: list) -> None:
    """`\\d` is Unicode Nd, so a vulgar fraction or a circled digit had no digit in it at
    all and the whole atom was dropped. Superscripts and Roman numerals stay excluded on
    purpose — admitting them reports every square metre and every phase Ⅲ trial."""
    assert atoms_of(text) == expected


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


METHODS_AND_RESULTS = """# Paper

## Methods

Significance was set at p < 0.05 throughout, with power of 80%.

### Sensitivity analyses

A stricter p < 0.01 was applied here.

## Results

The association was significant (p < 0.001).

## Discussion

This remained true at p < 0.05.
"""


def test_a_threshold_is_a_convention_in_methods_and_a_finding_elsewhere() -> None:
    """`p < 0.05` means two different things and has the same characters both times.

    Where the paper describes its own method it is the alpha the author chose in advance.
    In the Results it is a finding — and as a convention everywhere, a significance claim
    the analysis never produced walked straight past the gate. A Methods *subsection*
    counts: `### Sensitivity analyses` is still Methods, which is why the section is read
    as a chain of enclosing headings rather than as the nearest one.
    """
    from manuscript_guard.text.sections import section_chain

    classifier = Classifier.load()
    found = {}
    for atom in find_atoms(METHODS_AND_RESULTS, mask(METHODS_AND_RESULTS)):
        chain = section_chain(METHODS_AND_RESULTS, atom.start)
        found[(chain[-1], atom.text)] = classifier.classify(atom, chain).kind

    assert found[("Methods", "0.05")] == CONVENTION
    assert found[("Methods", "80%")] == CONVENTION
    assert found[("Sensitivity analyses", "0.01")] == CONVENTION
    assert found[("Results", "0.001")] == UNCLASSIFIED
    assert found[("Discussion", "0.05")] == UNCLASSIFIED


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The suffix renders. A fabricated interval travelled into the .docx inside one,
        # carrying a citation — which DESIGN calls worse than an unsourced number.
        ("Shown [@key2019, which reported an ROR of 9.99 in 41 200 reports] here.",
         ["9.99", "41", "200"]),
        ("Suppressed [-@key2019, 9204 events] here.", ["9204"]),
        # The prefix was already read; the asymmetry was an accident of anchoring at `[@`.
        ("See [see 9203 reports; @key2019] here.", ["9203"]),
        # The key itself must still go: Better BibTeX keys routinely end in a year.
        ("A plain claim [@smith2020hepatic].", []),
        ("As @smith2020hepatic showed.", []),
    ],
)
def test_a_citation_masks_its_key_not_its_whole_bracket(text: str, expected: list) -> None:
    assert atoms_of(text) == expected


@pytest.mark.parametrize(
    "text", ["As shown [@key2019, p. 33].", "Reported [@other2020, pp. 12-19]."]
)
def test_a_citation_locator_is_structural(text: str) -> None:
    """Reading the bracket means meeting the one thing legitimately written in it."""
    classifier = Classifier.load()
    found = find_atoms(text, mask(text))
    assert found
    assert all(classifier.classify(a).kind == STRUCTURAL for a in found)


FENCE = "`" * 3
SPOOFS = {
    "fenced code comment": (
        f"## Methods\n\nAlpha set.\n\n{FENCE}python\n# Methods\nx = 1\n{FENCE}\n\n"
        "## Results\n\nSignificant (p < 0.05).\n"
    ),
    "html comment": "## Results\n\n<!--\n## Methods\n-->\n\nSignificant (p < 0.05).\n",
}


@pytest.mark.parametrize("name", sorted(SPOOFS))
def test_a_heading_cannot_be_forged_from_code_or_a_comment(name: str) -> None:
    """`#` is a comment character, and headings are found by scanning for it.

    Once fenced code stopped being masked — correctly, since it renders — an ordinary
    Python comment became a level-1 heading, which *popped* the real `## Methods` so that
    `## Results` nested underneath it. `is_methods` looks at the whole chain, so a threshold
    in the Results was accepted as the alpha chosen in advance. No attacker needed. The HTML
    comment version is worse: invisible in the rendered document.
    """
    from manuscript_guard.text.sections import section_chain

    text = SPOOFS[name]
    classifier = Classifier.load()
    atom = next(a for a in find_atoms(text, mask(text)) if a.text == "0.05")
    chain = section_chain(text, atom.start)
    assert "Methods" not in chain
    assert classifier.classify(atom, chain).kind == UNCLASSIFIED


@pytest.mark.parametrize(
    "heading", ["Protocol deviations", "Design of the sub-study", "Methods used by others"]
)
def test_a_heading_that_merely_starts_like_methods_is_not_methods(heading: str) -> None:
    """The match ended in `\\b`, so it was a prefix match: an ordinary Results subsection
    called "Protocol deviations" re-admitted every threshold rule underneath it."""
    from manuscript_guard.classify import is_methods

    assert not is_methods((heading,))


@pytest.mark.parametrize(
    "heading",
    ["Methods", "Materials and Methods", "2. Methods", "Statistical analysis", "Study design"],
)
def test_a_real_methods_heading_still_is_one(heading: str) -> None:
    from manuscript_guard.classify import is_methods

    assert is_methods((heading,))


def test_a_caller_with_no_sections_keeps_every_rule() -> None:
    """Figure text and the audit have no headings, and a `p < 0.05` in a legend is a
    legend convention. Passing no section must not silently tighten those callers."""
    text = "Marked * where p < 0.05."
    atom = find_atoms(text, mask(text))[0]
    assert Classifier.load().classify(atom).kind == CONVENTION


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


def test_a_missing_closing_brace_is_malformed_not_invisible() -> None:
    """`{{results.x}` needed `}}` to be recognised at all.

    So it was neither a binding nor malformed: it travelled into the built document as
    literal text, in the place where a number was supposed to be. That is the worst outcome
    available for a binding, and it needed one typo.
    """
    good, bad = parse("The ratio was {{results.ror.point} in the cohort.")
    assert good == []
    assert [raw for raw, _o, _l in bad] == ["{{results.ror.point}"]


def test_an_ordinary_brace_is_not_mistaken_for_a_binding() -> None:
    assert parse("A set { 1, 2 } and a stray {{ here.") == ([], [])


def test_block_namespaces_are_recognised_but_not_values() -> None:
    good, _ = parse("{{table.baseline}} {{figure.forest}}")
    assert [p.ref for p in good] == ["table.baseline", "figure.forest"]
    assert not any(p.is_value for p in good)


def test_substitute_replaces_only_known_refs() -> None:
    out = substitute("a={{results.a}} b={{results.b}}", {"results.a": "12"})
    assert out == "a=12 b={{results.b}}"


# ------------------------------------------------------ a hint that names what you wrote


def hint_for(text: str, atom_text: str) -> str:
    from manuscript_guard.gates.numbers import _hint_for
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.tokens import find_atoms

    atom = next(a for a in find_atoms(text, mask(text)) if a.text == atom_text)
    return _hint_for(atom)


def test_a_date_is_told_to_bind_as_one_placeholder() -> None:
    """"Bind it with {{results.<key>}}" is true of every unbound number and useful for
    almost none of them. An author who has just written a study period does not think of a
    date as a result, and the tokenizer splits it into three atoms besides.
    """
    hint = hint_for("Reports received between 1 January 2015 and 31 December 2022.", "2015")
    assert "one placeholder" in hint
    assert "period.start" in hint


def test_a_design_parameter_is_told_where_it_comes_from() -> None:
    hint = hint_for("The risk window was 30 days after the index prescription.", "30")
    assert "design parameter" in hint
    assert "cannot drift" in hint


def test_an_ordinary_number_still_gets_the_ordinary_hint() -> None:
    hint = hint_for("The exposed arm held 412 patients.", "412")
    assert "conventions:" in hint
    assert "design parameter" not in hint
