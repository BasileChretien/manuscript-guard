"""G14's second reading — one term for one thing.

The author declares the terms the paper keeps to, and the gate reports each term given up
that the manuscript still uses. Two halves again. It must find the term in a heading, in a
plural, across a line break and with a capital; and it must leave alone the same letters
inside a longer word, inside the term to use, in a quotation and in a citation key. It
reports only what was declared, so a paper that declares nothing hears nothing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_language
from manuscript_guard.gates.vocabulary import Passage, judge_vocabulary

PARTICIPANTS = [{"use": "participants", "avoid": ["subjects", "patients"]}]


def written(
    project: Path,
    text: str,
    vocabulary: object = PARTICIPANTS,
    *,
    supplement: str | None = None,
    **files: str,
):
    """Judge exactly this text against this vocabulary: the example's supplement goes
    unless one is given, and its abbreviations and its names from the code are not this
    file's subject."""
    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(text, encoding="utf-8")
    for name, body in files.items():
        (project / "manuscript" / f"{name}.md").write_text(body, encoding="utf-8")
    if supplement is not None:
        folder = project / "manuscript" / "supplementary"
        folder.mkdir()
        (folder / "S1.md").write_text(supplement, encoding="utf-8")
    path = project / "paper.yaml"
    paper = yaml.safe_load(path.read_text(encoding="utf-8"))
    paper["language"] = {"vocabulary": vocabulary}
    path.write_text(yaml.safe_dump(paper, sort_keys=False), encoding="utf-8")
    projekt, _ = load_project(project)
    report = check_language(projekt)
    aside = ("abbreviation-", "code-name-in-prose")
    kept = tuple(f for f in report.findings if not f.code.startswith(aside))
    return report, kept


def messages(findings) -> list[str]:
    return [f.message for f in findings]


# ---------------------------------------------------------------- what must be caught


def test_a_term_given_up_is_reported_once_with_its_count(project: Path) -> None:
    report, found = written(
        project,
        "# Methods\n\nParticipants were enrolled at two sites.\n\n# Results\n\nOf the "
        "subjects enrolled, half were women. Older subjects were excluded.\n",
    )
    (finding,) = found
    assert finding.code == "term-avoided"
    assert finding.message == "'subjects' is used 2 times; this paper's term is 'participants'"
    assert finding.line == 7, "where it first appears"
    assert "subjects enrolled" in finding.context
    assert "vocabulary" in finding.hint
    assert report.ok, "a list of words cannot tell two meanings apart, so it only advises"
    assert report.counts["vocabulary_terms"] == 2
    assert report.counts["vocabulary_found"] == 1


@pytest.mark.parametrize(
    "sentence",
    [
        "Subjects were enrolled at two sites.",  # a capital
        "Each subject gave consent.",  # the term as the entry writes it
        "The side effect was mild.",
        "The side-effect was mild.",  # a hyphen between its words
        "The side\neffect was mild.",  # a line break between its words
        "Side effects were mild.",  # the plural of a term written in the singular
        "SIDE EFFECTS were mild.",
    ],
)
def test_a_term_is_found_however_it_is_written(project: Path, sentence: str) -> None:
    vocabulary = [
        {"use": "participant", "avoid": ["subject"]},
        {"use": "adverse reaction", "avoid": ["side effect"]},
    ]
    _, found = written(project, f"# Results\n\n{sentence}\n", vocabulary)
    assert [f.code for f in found] == ["term-avoided"], messages(found)


def test_a_heading_is_read(project: Path) -> None:
    """A heading is the manuscript's wording as much as a sentence is."""
    _, found = written(project, "# Subjects\n\nParticipants were enrolled at two sites.\n")
    (finding,) = found
    assert finding.line == 1


def test_each_term_given_up_is_its_own_finding(project: Path) -> None:
    _, found = written(
        project,
        "# Results\n\nPatients were older than expected. Subjects were enrolled late.\n",
    )
    assert sorted(messages(found)) == [
        "'patients' is used once; this paper's term is 'participants'",
        "'subjects' is used once; this paper's term is 'participants'",
    ]


def test_the_supplement_and_every_file_are_read(project: Path) -> None:
    _, found = written(
        project,
        "# Methods\n\nParticipants were enrolled at two sites.\n",
        supplement="# Supplementary methods\n\nSubjects were followed for a year.\n",
        **{"2_results": "# Results\n\nThe subjects were older than expected.\n"},
    )
    (finding,) = found
    assert "2 times" in finding.message
    assert finding.path.name == "2_results.md", "the paper is read before its supplement"


def test_a_finding_counts_the_whole_manuscript_and_stands_at_the_first_printed_use(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14's vocabulary is a list of words"): the count
    is of the whole manuscript, and the place is the first use in the order the files are
    printed: `main.md` first and the rest by name, then the supplement. Read by path,
    `0_intro.md` would come before `main.md`, and the supplement before `z_results.md`."""
    _, found = written(
        project,
        "# Methods\n\nNothing here.\n\nThe subjects came.\n",
        supplement="# Supplementary methods\n\nThe subjects stayed.\n",
        **{"0_intro": "# Introduction\n\nSubjects were asked.\n"},
    )
    (finding,) = found
    assert finding.message == "'subjects' is used 3 times; this paper's term is 'participants'"
    assert (finding.path.name, finding.line) == ("main.md", 5)
    (project / "manuscript" / "0_intro.md").unlink()
    _, found = written(
        project,
        "# Methods\n\nNothing here.\n",
        supplement="# Supplementary methods\n\nThe subjects stayed.\n",
        z_results="# Results\n\nOne.\n\nThe subjects came.\n",
    )
    (finding,) = found
    assert "used 2 times" in finding.message
    assert (finding.path.name, finding.line) == ("z_results.md", 5)


# ---------------------------------------------------------------- what must stay quiet


def test_a_paper_that_declares_nothing_hears_nothing(project: Path) -> None:
    report, found = written(project, "# Results\n\nSubjects and patients were enrolled.\n", [])
    assert not found
    assert report.counts["vocabulary_terms"] == 0


@pytest.mark.parametrize(
    "sentence",
    [
        "Participants gave subjective ratings, and outpatients were excluded.",
        "The estimate is subject to bias.",  # the entry is the plural, and this is not it
        "Data are in `subjects.csv`, read by `load subjects`.",
        "As reported [@subjects; @doe2020-subjects], recall was low.",
        "See https://example.org/subjects for the protocol.",
        "<!-- subjects or participants? decide before submission -->\n\nRecall was low.",
        "> We called them subjects, and the patients objected.\n\nRecall was low.",
        "   > Indented, and still a quotation: the subjects objected.\n\nRecall was low.",
        "![Flow of subjects through the study](figures/flow.svg)",
        "The count $n_{subjects}$ was fixed in advance.",
        "The count was {{results.subjects.n}} reports.",
    ],
)
def test_the_letters_of_a_term_elsewhere_are_not_the_term(project: Path, sentence: str) -> None:
    """Each of these holds the term itself, in a place the manuscript does not speak."""
    _, found = written(project, f"# Methods\n\n{sentence}\n")
    assert not found, messages(found)


def test_a_term_ends_where_its_word_ends(project: Path) -> None:
    """`subject` is not found in `subjective`, though it opens it."""
    _, found = written(
        project,
        "# Methods\n\nThe ratings were subjective.\n",
        [{"use": "participant", "avoid": ["subject"]}],
    )
    assert not found, messages(found)


# ---------------------------------------------------------------- abbreviations as terms

LONG_FORMS = [
    {"use": "odds ratio", "avoid": ["OR"]},
    {"use": "World Health Organization", "avoid": ["WHO"]},
    {"use": "United States", "avoid": ["US", "USA"]},
    {"use": "acute lymphoblastic leukaemia", "avoid": ["ALL"]},
    {"use": "information technology", "avoid": ["IT"]},
]


def test_an_abbreviation_given_up_is_not_the_word_it_spells(project: Path) -> None:
    """Preferring a long form to its abbreviation must not report "or", "who", "us", "all"
    and "its": a term written with two capitals together is matched as written."""
    _, found = written(
        project,
        "# Methods\n\nReports were classified by two of us, or by a third reviewer who was "
        "blind to the drug. The World Health Organization categories were used, and all "
        "cases in the United States were kept. It allowed us to compare the odds ratio, and "
        "its interval, between groups.\n",
        LONG_FORMS,
    )
    assert not found, messages(found)


def test_an_abbreviation_given_up_is_found_as_written_and_in_the_plural(project: Path) -> None:
    _, found = written(
        project,
        "# Results\n\nThe OR was 2.1, and the ORs of the WHO regions were pooled.\n",
        LONG_FORMS,
    )
    assert sorted(messages(found)) == [
        "'OR' is used 2 times; this paper's term is 'odds ratio'",
        "'WHO' is used once; this paper's term is 'World Health Organization'",
    ]


def test_only_the_abbreviation_in_a_term_is_held_to_its_capitals(project: Path) -> None:
    """Word by word. "Phase II trials" opening a sentence and "Phase II Trials" in a
    heading are the term; held to its capitals from end to end, only the entry's own
    spelling was found."""
    vocabulary = [
        {"use": "phase 2 trial", "avoid": ["phase II trial"]},
        {"use": "hepatitis B", "avoid": ["chronic HBV infection"]},
    ]
    _, found = written(
        project,
        "# Results\n\nPhase II trials were pooled. Each phase II trial was read twice.\n\n"
        "## Phase II Trials by Region\n\nChronic HBV infection was an exclusion.\n",
        vocabulary,
    )
    assert sorted(messages(found)) == [
        "'chronic HBV infection' is used once; this paper's term is 'hepatitis B'",
        "'phase II trial' is used 3 times; this paper's term is 'phase 2 trial'",
    ]
    _, found = written(project, "# Results\n\nEach phase ii trial was read.\n", vocabulary)
    assert not found, "the numeral is held to its capitals"


def test_a_word_in_capitals_is_the_word_and_its_plural(project: Path) -> None:
    """A heading set in capitals: `SUBJECTS` is "subject" in the plural."""
    _, found = written(
        project,
        "# SUBJECTS\n\nEach SUBJECT gave consent.\n",
        [{"use": "participant", "avoid": ["subject"]}],
    )
    (finding,) = found
    assert "used 2 times" in finding.message


def test_two_capitalisations_of_an_abbreviation_are_two_terms(project: Path) -> None:
    """`Covid-19` can be given up for `COVID-19`: with two capitals together, a term is
    its capitals."""
    report, found = written(
        project,
        "# Methods\n\nCovid-19 reports were excluded, as were COVID-19 vaccines.\n",
        [{"use": "COVID-19", "avoid": ["Covid-19"]}],
    )
    assert messages(found) == ["'Covid-19' is used once; this paper's term is 'COVID-19'"]


@pytest.mark.parametrize(
    ("use", "avoid"), [("SARS-CoV-2", "SARS-Cov-2"), ("HbA1c", "Hba1c"), ("IgG", "igg")]
)
def test_a_capital_inside_a_word_with_no_two_together_cannot_be_declared(
    project: Path, use: str, avoid: str
) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14's vocabulary is a list of words"): `CoV`,
    `IgG` and `HbA1c` are found in any case, so `SARS-Cov-2` given up for `SARS-CoV-2` is a
    conflict, as `Hba1c` for `HbA1c` is; only `SARS` is held to its capitals."""
    _, found = written(project, "# Methods\n\nNone.\n", [{"use": use, "avoid": [avoid]}])
    assert messages(found) == [
        f"{use!r} is a term to use and {avoid!r} a term to avoid, and the two are read as one "
        "term"
    ]
    _, found = written(
        project,
        "# Methods\n\nSars-CoV-2, SARS-COV-2, IGG and HBA1C were tested.\n",
        [{"use": "the virus", "avoid": ["SARS-CoV-2"]}, {"use": "antibody", "avoid": ["IgG"]},
         {"use": "glycated haemoglobin", "avoid": ["HbA1c"]}],
    )  # fmt: skip
    assert sorted(messages(found)) == [
        "'HbA1c' is used once; this paper's term is 'glycated haemoglobin'",
        "'IgG' is used once; this paper's term is 'antibody'",
        "'SARS-CoV-2' is used once; this paper's term is 'the virus'",
    ], "SARS is held to its capitals, and the others are found in any case"


@pytest.mark.parametrize(
    ("term", "sentence"),
    [
        ("CYP2D6*4", "The CYP2D6*4 allele was typed."),
        ("HLA-B*57:01", "Carriers of HLA-B*57:01 were excluded."),
        ("R_0", "The R_0 was 2.4."),
        ("n_eff", "The n_eff was small."),
    ],
)
def test_a_term_with_a_mark_inside_it_is_found_as_written(
    project: Path, term: str, sentence: str
) -> None:
    """An asterisk or an underscore inside a word is the word. Split there, the term was
    read as its parts and never found."""
    _, found = written(
        project, f"# Results\n\n{sentence}\n", [{"use": "the plain name", "avoid": [term]}]
    )
    assert messages(found) == [f"{term!r} is used once; this paper's term is 'the plain name'"]


def test_a_term_is_found_in_a_name_with_an_underscore_not_set_as_code(project: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14's vocabulary is a list of words"): the
    underscore is taken for a mark of emphasis, so "subjects" is found in `n_subjects`
    written in the prose; set as code, the name is not read."""
    _, found = written(project, "# Methods\n\nThe variable n_subjects was kept.\n")
    assert messages(found) == ["'subjects' is used once; this paper's term is 'participants'"]
    _, found = written(project, "# Methods\n\nThe variable `n_subjects` was kept.\n")
    assert not found, messages(found)


def test_a_mark_is_found_as_the_entry_writes_it_and_taken_off_its_end(project: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14's vocabulary is a list of words"): a
    manuscript writes `CYP2D6\\*4` with a backslash, so pandoc does not read emphasis there,
    and only an entry with the backslash too finds it. A mark at the end of an entry's word
    is taken off it: `n_` is read as "n", and `_id` as "id"."""
    text = "# Methods\n\nCarriers of CYP2D6\\*4 were few.\n"
    _, found = written(project, text, [{"use": "poor metaboliser", "avoid": ["CYP2D6*4"]}])
    assert not found, messages(found)
    _, found = written(project, text, [{"use": "poor metaboliser", "avoid": ["CYP2D6\\*4"]}])
    assert messages(found) == [
        "'CYP2D6\\\\*4' is used once; this paper's term is 'poor metaboliser'"
    ]
    for entry, word in (("n_", "n"), ("_id", "id")):
        _, found = written(
            project, f"# Methods\n\nThe {word} was kept.\n", [{"use": "it", "avoid": [entry]}]
        )
        assert messages(found) == [f"{entry!r} is used once; this paper's term is 'it'"]


# ---------------------------------------------------------------- what joins a term's words

SIDE_EFFECT = [{"use": "adverse reaction", "avoid": ["side effect"]}]


@pytest.mark.parametrize(
    "text",
    [
        "It had one side\n\neffect sizes were small.",  # a paragraph break
        "- the affected side\n- effect size",  # two list items
        "The left side -- effect modification aside -- was used.",  # a dash
        "On the left side---effect modification aside---it was used.",
        "The side `x` effect was mild.",  # inline code between them
        "The side {{results.cohort.n_reports}} effect was mild.",  # a binding
        "The side $x$ effect was mild.",  # an equation
        "The side ![a caption](figures/f.png) effect was mild.",  # an image
        "The side\n\n```\ncode\n```\n\neffect was mild.",  # a whole listing
        "One side\n\n> quoted words\n\neffect sizes were small.",  # a whole quotation
        "The side. Effect sizes were small.",  # the end of a sentence
    ],
)
def test_two_words_that_are_not_side_by_side_are_not_a_term(project: Path, text: str) -> None:
    _, found = written(project, f"# Methods\n\n{text}\n", SIDE_EFFECT)
    assert not found, messages(found)


def test_a_heading_does_not_run_on_into_its_paragraph(project: Path) -> None:
    _, found = written(
        project, "# The other side\n\nEffect sizes were small.\n", SIDE_EFFECT
    )
    assert not found, messages(found)


def test_a_heading_with_no_blank_line_under_it_runs_into_its_paragraph(project: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14's vocabulary is a list of words"):
    `# The other side` over `Effect sizes were small.` on the next line reports "side
    effect"; with the blank line between them it does not."""
    _, found = written(project, "# The other side\nEffect sizes were small.\n", SIDE_EFFECT)
    assert messages(found) == [
        "'side effect' is used once; this paper's term is 'adverse reaction'"
    ]
    assert found[0].line == 1
    _, found = written(project, "# The other side\n\nEffect sizes were small.\n", SIDE_EFFECT)
    assert not found, messages(found)


@pytest.mark.parametrize(
    "text",
    [
        "The side *effect* was mild.",  # emphasis after the joint
        "The **side** **effect** was mild.",  # and on both sides of it
        "- the side\n  effect was mild",  # a line break, then a list item's indentation
        "The side  \neffect was mild.",  # blanks, then the line break
        "The side\t\n\teffect was mild.",
    ],
)
def test_two_words_side_by_side_are_the_term_however_the_line_is_set(
    project: Path, text: str
) -> None:
    _, found = written(project, f"# Methods\n\n{text}\n", SIDE_EFFECT)
    assert [f.code for f in found] == ["term-avoided"], messages(found)


@pytest.mark.parametrize(
    "sentence",
    [
        "After _in vitro_ fertilisation, the _subjects_ were followed.",
        "After __in vitro fertilisation__, the __subjects__ were followed.",
        "After *in vitro* fertilisation, the *subjects* were followed.",
        "After ***in vitro*** fertilisation, the **subjects** were followed.",
    ],
)
def test_emphasis_does_not_hide_a_term(project: Path, sentence: str) -> None:
    """pandoc prints each of these as the plain words."""
    vocabulary = [
        {"use": "IVF", "avoid": ["in vitro fertilisation"]},
        {"use": "participants", "avoid": ["subjects"]},
    ]
    _, found = written(project, f"# Methods\n\n{sentence}\n", vocabulary)
    assert sorted(messages(found)) == [
        "'in vitro fertilisation' is used once; this paper's term is 'IVF'",
        "'subjects' is used once; this paper's term is 'participants'",
    ]


def test_a_line_of_a_paragraph_that_opens_with_a_greater_than_sign_is_read(
    project: Path,
) -> None:
    """A quotation opens after a blank line. Without one, `>` is the sign in "ALT > 3
    times the limit", wrapped to the start of a line."""
    _, found = written(
        project,
        "# Methods\n\nWe enrolled people with ALT\n> 3 times the limit, and subjects with "
        "none.\n",
    )
    assert messages(found) == ["'subjects' is used once; this paper's term is 'participants'"]


@pytest.mark.parametrize(
    "text",
    [
        "> The subjects objected.\n> So did other subjects.\n",  # at the top, two lines
        "Recall was low.\n\n> One line.\n> The subjects objected on the next.\n",
        "## Patient voices\n> The subjects objected to the word.\n",  # under a heading
        "Voices\n------\n> The subjects objected to the word.\n",  # under a setext heading
        "Recall was low.\n\n---\n> The subjects objected to the word.\n",  # under a rule
        "::: box\n> The subjects objected to the word.\n:::\n",  # in a fenced div
        "<!-- a note -->\n> The subjects objected to the word.\n",  # after a hidden line
        "```\ncode\n```\n> The subjects objected to the word.\n",
        "Recall was low.\n   \n> The subjects objected to the word.\n",  # after a line of spaces
        "Recall was low.\n\n***\n> The subjects objected to the word.\n",  # a rule of asterisks
        "Voices\n======\n> The subjects objected to the word.\n",  # a first-level setext heading
        "::: box\nInside.\n:::\n> The subjects objected to the word.\n",  # after a div closes
        "Recall was low.\n\n___\n> The subjects objected to the word.\n",  # a rule of underscores
        "Recall was low.\n\n* * *\n> The subjects objected to the word.\n",  # blanks inside a rule
        # Far enough down the file that an offset one short for each line would show:
        # eight lines above, and the word has eight letters.
        "One.\nTwo.\nThree.\nFour.\nFive.\nSix.\nSeven.\n\n> They called themselves subjects\n",
    ],
)
def test_a_quotation_is_left_alone_wherever_a_block_can_open(project: Path, text: str) -> None:
    _, found = written(project, text)
    assert not found, messages(found)


def test_a_row_of_a_table_that_opens_with_a_greater_than_sign_is_read(project: Path) -> None:
    """The rule under a simple table's header is hyphens with blanks between, and its first
    row is a row. Taken for a rule that ends a block, it made "> 65 years" a quotation."""
    _, found = written(
        project,
        "# Results\n\nAge         Group\n----------  ------------\n> 65 years  12 subjects\n"
        "< 65 years  30 subjects\n",
    )
    (finding,) = found
    assert "used 2 times" in finding.message
    assert finding.line == 5


def test_a_form_feed_does_not_end_a_line(project: Path) -> None:
    """Only a newline does. Split as `str.splitlines` splits, the line after a form feed
    looked like the first of a block, and its `>` like a quotation."""
    _, found = written(
        project,
        "# Methods\n\nWe enrolled people with ALT\f\n> 3 times the limit, and subjects with "
        "none.\n",
    )
    assert [f.code for f in found] == ["term-avoided"]


def test_the_context_of_a_finding_is_the_text_as_written(project: Path) -> None:
    _, found = written(
        project, "# Results\n\nOf {{results.cohort.n_reports}} subjects, half were women.\n"
    )
    (finding,) = found
    assert "{{results.cohort.n_reports}} subjects" in finding.context


def test_a_fenced_listing_and_a_reference_list_are_not_read(project: Path) -> None:
    _, found = written(
        project,
        "# Methods\n\nParticipants were enrolled.\n\n```r\nsubjects <- read.csv(path)\n```\n\n"
        "# References\n\n1. Smith J. Human subjects in research. Lancet.\n",
    )
    assert not found, messages(found)


def test_paper_yaml_s_titles_and_generated_displays_are_not_read(project: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14's vocabulary is a list of words"): the
    title, the short title and the keywords come from `paper.yaml` and are not read, so the
    example's "liver damage" given up could be a keyword; nor are the tables and figures
    generated from results, here the baseline table's "Female" and its caption's "drug
    group", and the forest plot. A table typed into the manuscript is read, with its
    caption."""
    path = project / "paper.yaml"
    paper = yaml.safe_load(path.read_text(encoding="utf-8"))
    paper.update(title="Liver damage in drug group females", short_title="Liver damage",
                 keywords=["liver damage", "Female"])  # fmt: skip
    path.write_text(yaml.safe_dump(paper, sort_keys=False), encoding="utf-8")
    vocabulary = [
        {"use": "hepatic injury", "avoid": ["liver damage"]},
        {"use": "women", "avoid": ["Female"]},
        {"use": "exposure group", "avoid": ["drug group"]},
        {"use": "forest chart", "avoid": ["forest plot"]},
    ]
    _, found = written(
        project, "# Results\n\n{{table.baseline}}\n\n{{figure.forest}}\n", vocabulary
    )
    assert not found, messages(found)
    _, found = written(
        project,
        "# Results\n\n| Group | n |\n|---|---|\n| Female | 2 |\n\nTable: Reports by drug group.\n",
        vocabulary,
    )
    assert [(f.message, f.line) for f in found] == [
        ("'Female' is used once; this paper's term is 'women'", 5),
        ("'drug group' is used once; this paper's term is 'exposure group'", 7),
    ]


def test_a_term_to_avoid_inside_the_term_to_use_is_not_found_there(project: Path) -> None:
    """The longer term is read first, so the shorter inside it is not a finding; alone,
    it is."""
    vocabulary = [{"use": "adverse drug reaction", "avoid": ["drug reaction", "side effect"]}]
    _, found = written(
        project,
        "# Results\n\nEach adverse drug reaction was coded. Adverse drug reactions were "
        "common.\n",
        vocabulary,
    )
    assert not found, messages(found)
    _, found = written(
        project,
        "# Results\n\nEach adverse drug reaction was coded. One drug reaction was fatal.\n",
        vocabulary,
    )
    assert messages(found) == [
        "'drug reaction' is used once; this paper's term is 'adverse drug reaction'"
    ]


def test_a_term_to_avoid_that_opens_the_term_to_use_is_not_found_there(project: Path) -> None:
    """Two terms that start at the same word: the longer is read."""
    vocabulary = [{"use": "liver injury score", "avoid": ["liver injury"]}]
    _, found = written(project, "# Results\n\nThe liver injury score was high.\n", vocabulary)
    assert not found, messages(found)
    _, found = written(project, "# Results\n\nLiver injury was common.\n", vocabulary)
    assert [f.code for f in found] == ["term-avoided"]


def test_a_term_to_avoid_that_overlaps_a_term_to_use_before_it_is_not_found(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14's vocabulary is a list of words"): with
    "drug reaction" kept, "reaction time" given up is not found in "drug reaction time";
    alone, or with no term to use over it, it is."""
    reaction_time = {"use": "latency", "avoid": ["reaction time"]}
    vocabulary = [{"use": "drug reaction", "avoid": ["adverse thing"]}, reaction_time]
    said = ["'reaction time' is used once; this paper's term is 'latency'"]
    _, found = written(project, "# Results\n\nThe drug reaction time was long.\n", vocabulary)
    assert not found, messages(found)
    _, found = written(project, "# Results\n\nThe reaction time was long.\n", vocabulary)
    assert messages(found) == said
    _, found = written(
        project, "# Results\n\nThe drug reaction time was long.\n", [reaction_time]
    )
    assert messages(found) == said


def test_reading_resumes_after_the_reference_list(project: Path) -> None:
    """A section that follows the references, figure legends or an appendix, is the
    manuscript's own again."""
    _, found = written(
        project,
        "# Methods\n\nParticipants were enrolled.\n\n# References\n\n1. Smith J. Human "
        "subjects in research. Lancet.\n\n# Figure legends\n\nFigure 1. Flow of subjects.\n",
    )
    (finding,) = found
    assert finding.line == 11


def test_the_supplement_s_reference_list_is_not_read(project: Path) -> None:
    _, found = written(
        project,
        "# Methods\n\nParticipants were enrolled.\n",
        supplement="# Supplementary methods\n\nParticipants were followed.\n\n"
        "# References\n\n1. Smith J. Human subjects in research. Lancet.\n",
    )
    assert not found, messages(found)


def test_a_term_written_in_the_plural_is_not_its_singular(project: Path) -> None:
    """The way to keep "subject to bias" out of the report: give up `subjects`, not
    `subject`."""
    _, plural = written(project, "# Results\n\nThe estimate is subject to bias.\n")
    assert not plural
    _, singular = written(
        project,
        "# Results\n\nThe estimate is subject to bias.\n",
        [{"use": "participant", "avoid": ["subject"]}],
    )
    assert [f.code for f in singular] == ["term-avoided"]


def test_only_a_plural_in_s_is_folded_onto_a_term(project: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14's vocabulary is a list of words"): only the
    plural in `s` is folded, and only onto a term written without one: "study" does not
    find "studies", nor "analysis" "analyses", nor "persons" "person"."""
    vocabulary = [
        {"use": "trial", "avoid": ["study"]},
        {"use": "test", "avoid": ["analysis"]},
        {"use": "people", "avoid": ["persons"]},
    ]
    report, found = written(
        project, "# Methods\n\nThe studies were read, the analyses run and a person seen.\n",
        vocabulary,
    )
    assert not found, messages(found)
    assert report.counts["vocabulary_found"] == 0
    _, found = written(project, "# Methods\n\nThe studys were read.\n", vocabulary)
    assert messages(found) == ["'study' is used once; this paper's term is 'trial'"]


# ---------------------------------------------------------------- entries that disagree


def test_a_term_both_used_and_given_up_is_reported_and_not_looked_for(project: Path) -> None:
    vocabulary = [
        {"use": "participants", "avoid": ["subjects"]},
        {"use": "subjects", "avoid": ["volunteers"]},
    ]
    _, found = written(
        project, "# Results\n\nSubjects and volunteers were enrolled.\n", vocabulary
    )
    assert sorted(f.code for f in found) == ["term-avoided", "vocabulary-conflict"], (
        "one of each: the disputed term is not looked for"
    )
    by_code = {f.code: f for f in found}
    assert by_code["vocabulary-conflict"].message == (
        "'subjects' is a term to use and a term to avoid"
    )
    assert by_code["vocabulary-conflict"].path.name == "paper.yaml"
    assert "'volunteers'" in by_code["term-avoided"].message, "the rest is still read"


def test_a_conflict_is_a_warning_too(project: Path) -> None:
    vocabulary = [{"use": "participants", "avoid": ["participants"]}]
    report, found = written(project, "# Results\n\nParticipants were enrolled.\n", vocabulary)
    assert [f.code for f in found] == ["vocabulary-conflict"]
    assert found[0].severity == "warn"
    assert report.ok


def test_a_term_given_up_for_two_others_is_a_conflict(project: Path) -> None:
    vocabulary = [
        {"use": "participants", "avoid": ["subjects"]},
        {"use": "patients", "avoid": ["subjects"]},
    ]
    _, found = written(project, "# Results\n\nSubjects were enrolled.\n", vocabulary)
    (finding,) = found
    assert finding.message == "'subjects' is to give way to 'participants' and 'patients'"


@pytest.mark.parametrize(
    ("vocabulary", "text", "expected"),
    [
        (
            [
                {"use": "participant", "avoid": ["subject"]},
                {"use": "participants", "avoid": ["subjects"]},
            ],
            "A subject withdrew. Two subjects were lost to follow-up.",
            [
                "'subject' is used once; this paper's term is 'participant'",
                "'subjects' is used once; this paper's term is 'participants'",
            ],
        ),
        (
            [
                {"use": "odds ratio", "avoid": ["OR"]},
                {"use": "odds ratios", "avoid": ["ORs"]},
            ],
            "The OR was 2.1. Both ORs were pooled.",
            [
                "'OR' is used once; this paper's term is 'odds ratio'",
                "'ORs' is used once; this paper's term is 'odds ratios'",
            ],
        ),
        (
            [{"use": "participants", "avoid": ["subject", "subjects"]}],
            "A subject withdrew. Two subjects were lost to follow-up.",
            [
                "'subject' is used once; this paper's term is 'participants'",
                "'subjects' is used once; this paper's term is 'participants'",
            ],
        ),
    ],
)
def test_a_singular_and_a_plural_for_the_same_pair_of_words_agree(
    project: Path, vocabulary: list, text: str, expected: list
) -> None:
    """The entries an author most naturally writes: one for the singular, one for the
    plural. The terms they give way to are one term to the reading, so there is nothing
    to disagree about, and both words are looked for."""
    _, found = written(project, f"# Results\n\n{text}\n", vocabulary)
    assert sorted(messages(found)) == expected


def test_one_word_given_up_for_a_singular_and_its_plural_is_no_conflict(project: Path) -> None:
    """The other half of the same rule: "participant" and "participants" are one term to
    use, so a word given up for both has one term to give way to."""
    vocabulary = [
        {"use": "participant", "avoid": ["subject"]},
        {"use": "participants", "avoid": ["subject"]},
    ]
    _, found = written(project, "# Results\n\nA subject withdrew.\n", vocabulary)
    assert messages(found) == ["'subject' is used once; this paper's term is 'participant'"]


def test_an_abbreviation_s_plural_is_not_the_word_it_spells(project: Path) -> None:
    """`CIs` is two confidence intervals, though "cis" is in the vocabulary too."""
    vocabulary = [
        {"use": "confidence interval", "avoid": ["CI"]},
        {"use": "trans", "avoid": ["cis"]},
    ]
    _, found = written(
        project, "# Results\n\nBoth CIs were wide. The CI was wide.\n", vocabulary
    )
    assert messages(found) == ["'CI' is used 2 times; this paper's term is 'confidence interval'"]


def test_a_greek_abbreviation_is_found_in_the_plural(project: Path) -> None:
    """Its lower case ends in a final sigma and its plural's does not, so the letters are
    compared with case folded away, which knows the two for one letter."""
    term = (
        "\N{GREEK CAPITAL LETTER OMICRON}\N{GREEK CAPITAL LETTER DELTA}"
        "\N{GREEK CAPITAL LETTER OMICRON}\N{GREEK CAPITAL LETTER SIGMA}"
    )
    _, found = written(
        project,
        f"# Results\n\nOne {term} and two {term}s.\n",
        [{"use": "road", "avoid": [term]}],
    )
    (finding,) = found
    assert "used 2 times" in finding.message


def test_a_match_no_term_claims_is_passed_over(project: Path) -> None:
    """The search takes the micro sign and the Greek mu for one letter in any case, and
    the comparison that follows keeps them apart. So a match can be nobody's: it is not
    reported, and nothing raises."""
    micro, mu = "\N{MICRO SIGN}g", "\N{GREEK SMALL LETTER MU}g"
    vocabulary = [{"use": "micrograms", "avoid": [micro]}]
    _, found = written(project, f"# Methods\n\nThe dose was 5 {mu} daily.\n", vocabulary)
    assert not found
    _, found = written(
        project,
        f"# Methods\n\nThe dose was 5 {mu} daily and 2 {micro} at night.\n",
        vocabulary,
    )
    (finding,) = found
    assert "is used once" in finding.message, "the one typed as the entry types it"


@pytest.mark.parametrize(
    ("entry", "typed"),
    [
        ("caf\N{LATIN SMALL LETTER E WITH ACUTE}", "cafe\N{COMBINING ACUTE ACCENT}"),
        ("cafe\N{COMBINING ACUTE ACCENT}", "caf\N{LATIN SMALL LETTER E WITH ACUTE}"),
        ("\N{MICRO SIGN}g", "\N{GREEK SMALL LETTER MU}g"),
        ("\N{GREEK SMALL LETTER MU}g", "\N{MICRO SIGN}g"),
    ],
)
def test_a_letter_typed_another_way_is_not_the_term(
    project: Path, entry: str, typed: str
) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14's vocabulary is a list of words"): a term
    typed with an accent as one character does not find the word typed as a letter and a
    combining accent, nor the micro sign the Greek mu, either way round; typed as the entry
    types it, it is found."""
    vocabulary = [{"use": "the word", "avoid": [entry]}]
    _, found = written(project, f"# Methods\n\nThe {typed} was open.\n", vocabulary)
    assert not found, messages(found)
    _, found = written(project, f"# Methods\n\nThe {entry} was open.\n", vocabulary)
    assert messages(found) == [f"{entry!r} is used once; this paper's term is 'the word'"]


def test_the_schema_reports_a_term_with_no_letter_in_it(project: Path) -> None:
    path = project / "paper.yaml"
    paper = yaml.safe_load(path.read_text(encoding="utf-8"))
    paper["language"] = {"vocabulary": [{"use": "--", "avoid": ["subjects", "+/-"]}]}
    path.write_text(yaml.safe_dump(paper, sort_keys=False), encoding="utf-8")
    _, contract = load_project(project)
    refused = sorted(f.message for f in contract.failures)
    assert any("language/vocabulary/0/use" in message for message in refused), refused
    assert any("language/vocabulary/0/avoid/1" in message for message in refused), refused


def test_a_term_given_up_for_several_others_names_them_all(project: Path) -> None:
    vocabulary = [
        {"use": "participants", "avoid": ["subjects"]},
        {"use": "patients", "avoid": ["subjects"]},
        {"use": "volunteers", "avoid": ["subjects"]},
    ]
    _, found = written(project, "# Results\n\nSubjects were enrolled.\n", vocabulary)
    (finding,) = found
    assert finding.code == "vocabulary-conflict"
    assert finding.message == (
        "'subjects' is to give way to 'participants', 'patients' and 'volunteers'"
    )


def test_two_spellings_of_one_term_are_a_conflict_that_says_so(project: Path) -> None:
    """A hyphen and a space are read as one, so hyphenation cannot be declared, and the
    message has to say why two entries that look different collide."""
    vocabulary = [{"use": "follow-up", "avoid": ["follow up", "followup"]}]
    _, found = written(project, "# Results\n\nThe followup was short.\n", vocabulary)
    by_code = {f.code: f for f in found}
    assert by_code["vocabulary-conflict"].message == (
        "'follow-up' is a term to use and 'follow up' a term to avoid, and the two are read "
        "as one term"
    )
    assert "a hyphen, a space" in by_code["vocabulary-conflict"].hint
    assert "'followup'" in by_code["term-avoided"].message, "one word is another term"


def test_an_en_dash_or_a_non_breaking_hyphen_does_not_join_a_term_s_words(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "G14's vocabulary is a list of words"): a hyphen
    and a space between a term's words are read as one, and an en dash or a non-breaking
    hyphen between two words is not read as joining them."""
    for joined in ("side\N{EN DASH}effect", "side\N{NON-BREAKING HYPHEN}effect"):
        _, found = written(project, f"# Methods\n\nThe {joined} was mild.\n", SIDE_EFFECT)
        assert not found, (joined, messages(found))
    _, found = written(
        project, "# Methods\n\nThe side-effect was mild; the side effect was not.\n", SIDE_EFFECT
    )
    assert messages(found) == ["'side effect' is used 2 times; this paper's term is "
                               "'adverse reaction'"]  # fmt: skip


def test_the_plural_of_a_term_to_use_cannot_be_given_up(project: Path) -> None:
    """`subject` is found as `subjects` too, so an entry that gives `subjects` up for
    something else disagrees with it."""
    vocabulary = [
        {"use": "subject", "avoid": ["person"]},
        {"use": "participants", "avoid": ["subjects"]},
    ]
    _, found = written(project, "# Results\n\nA subject and two subjects.\n", vocabulary)
    assert [f.code for f in found] == ["vocabulary-conflict"]
    assert "'subject' is a term to use and 'subjects' a term to avoid" in found[0].message


def test_a_singular_and_its_plural_given_up_for_different_terms_disagree(project: Path) -> None:
    vocabulary = [
        {"use": "participant", "avoid": ["subject"]},
        {"use": "patients", "avoid": ["subjects"]},
    ]
    _, found = written(project, "# Results\n\nTwo subjects were enrolled.\n", vocabulary)
    assert [f.code for f in found] == ["vocabulary-conflict"]
    assert "'subject' and 'subjects' are read as one term" in found[0].message


def test_a_term_with_no_letter_in_it_is_passed_over(project: Path) -> None:
    """The schema refuses one. The reading is also asked directly, as a caller with entries
    of its own would ask it, and must not raise on them."""
    from manuscript_guard.gates.vocabulary import Passage, judge_vocabulary

    text = "Subjects were enrolled -- all of them."
    passage = Passage(Path("main.md"), text, text, lambda offset: 1)
    entries = [
        {"use": "--", "avoid": ["subjects"]},
        {"use": "participants", "avoid": ["  ", "*_*", "subjects"]},
    ]
    report = judge_vocabulary([passage], entries, Path("paper.yaml"))
    assert [f.message for f in report.findings] == [
        "'subjects' is used once; this paper's term is 'participants'"
    ]


def test_the_same_term_given_up_twice_for_one_term_is_no_conflict(project: Path) -> None:
    vocabulary = [
        {"use": "participants", "avoid": ["subjects"]},
        {"use": "Participants", "avoid": ["Subjects", "patients"]},
    ]
    _, found = written(project, "# Results\n\nSubjects were enrolled.\n", vocabulary)
    assert [f.code for f in found] == ["term-avoided"]


@pytest.mark.parametrize(
    "vocabulary",
    [
        "participants",
        {"use": "participants", "avoid": ["subjects"]},
        [5, None, "participants", ["subjects"]],
        [{"use": "participants"}],
        [{"use": "participants", "avoid": "subjects"}],
        [{"use": "participants", "avoid": []}],
        [{"use": True, "avoid": [False]}],
        [{"use": "participants", "avoid": ["subjects"], "because": "typo of why"}],
        [{"use": "--", "avoid": ["subjects"]}],
        [{"use": "participants", "avoid": ["subjects", "  "]}],
    ],
)
def test_an_entry_in_the_wrong_shape_is_the_schema_s_and_does_not_stop_the_gate(
    project: Path, vocabulary: object
) -> None:
    report, found = written(project, "# Results\n\nSubjects were enrolled.\n", vocabulary)
    assert not found, "nothing is looked for under an entry the schema refuses"
    assert report.counts["vocabulary_terms"] == 0


def test_one_entry_written_wrongly_does_not_take_the_others_with_it(project: Path) -> None:
    vocabulary = [{"use": "participants"}, {"use": "adverse reaction", "avoid": ["side effect"]}]
    _, found = written(project, "# Results\n\nSubjects reported a side effect.\n", vocabulary)
    assert messages(found) == [
        "'side effect' is used once; this paper's term is 'adverse reaction'"
    ]


def test_a_term_given_up_is_found_in_an_acknowledgement_too(project: Path) -> None:
    """The spelling is not read in the contributions, acknowledgements, funding and
    competing-interests sections, whose wording is other people's. A term the author gave
    up is the author's wherever it stands, so this reading keeps them."""
    _, found = written(
        project,
        "# Methods\n\nNothing here.\n\n# Acknowledgements\n\nWe thank the subjects of the study."
        "\n\n# Funding\n\nNo subjects were paid.\n",
    )
    assert messages(found) == ["'subjects' is used 2 times; this paper's term is 'participants'"]


def test_the_example_keeps_to_its_own_vocabulary(project: Path) -> None:
    """Dogfooding: the example declares a vocabulary and its text has to keep to it."""
    projekt, _ = load_project(project)
    assert projekt.vocabulary, "the example shows the setting"
    report = check_language(projekt)
    assert not [f for f in report.findings if not f.code.startswith("abbreviation-")]
    assert report.counts["vocabulary_terms"] >= 1


# ---------------------------------------------------------------- reading at any size


def test_many_terms_and_many_uses_are_read_in_linear_time(assert_linear) -> None:
    vocabulary = [
        {"use": f"term{n}a", "avoid": [f"term{n}b", f"word{n} given up"]} for n in range(40)
    ]

    def manuscript(count: int) -> list[Passage]:
        text = "The term7b and the word9 given up were used; term3a was kept. " * count
        return [Passage(Path("main.md"), text, text, lambda offset: 1)]

    def judge(passages: list[Passage]) -> None:
        report = judge_vocabulary(passages, vocabulary, Path("paper.yaml"))
        assert report.counts["vocabulary_found"] == 2

    assert_linear(manuscript, judge, 500, "the vocabulary, by use")
