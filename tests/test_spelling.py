"""G14's third reading — one English.

`paper.yaml` says whether the paper is in British or in American spelling, and the gate
reports the words written the other way. Two halves, as for the other readings. It must
find "color" in a British paper wherever a sentence can put it; and it must leave alone a
word both usages write, a name, a quotation, and everything that is not the manuscript's
own prose. The list it reads is derived from VarCon, so the last part of this file holds
the list itself and the script that derives it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_language
from manuscript_guard.gates.spelling import (
    DATA,
    LISTED,
    MANY,
    _opens_a_sentence,
    _variants,
    judge_spelling,
)
from manuscript_guard.gates.vocabulary import Passage

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "derive_spelling_variants.py"


def written(
    project: Path,
    text: str,
    variant: str = "en-GB",
    *,
    accepted: object = None,
    supplement: str | None = None,
    **files: str,
):
    """Judge exactly this text as a paper in `variant`: the example's supplement goes
    unless one is given, and only the findings on spelling are returned with the report."""
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
    paper["english_variant"] = variant
    paper["language"] = {} if accepted is None else {"accepted_spellings": accepted}
    path.write_text(yaml.safe_dump(paper, sort_keys=False), encoding="utf-8")
    projekt, _ = load_project(project)
    report = check_language(projekt)
    return report, tuple(f for f in report.findings if f.code.startswith("spelling-"))


def messages(findings) -> list[str]:
    return [f.message for f in findings]


def reported(findings) -> list[str]:
    """The words the findings are about."""
    return [f.message.split("'")[1] for f in findings if f.code == "spelling-variant"]


# ---------------------------------------------------------------- what must be caught


def test_a_word_in_the_other_spelling_is_reported_once_with_its_count(project: Path) -> None:
    report, found = written(
        project,
        "# Methods\n\nThe color of each sample was noted.\n\n# Results\n\nThe color "
        "changed in one tumor.\n",
    )
    first, second = found
    assert first.code == second.code == "spelling-variant"
    assert first.message == (
        "'color' is the American spelling of 'colour', used 2 times; this paper is in "
        "British English"
    )
    assert first.line == 3, "where it first stands"
    assert "The color of each sample" in first.context
    assert "list that one word under `language: accepted_spellings:`" in first.hint
    assert second.message == (
        "'tumor' is the American spelling of 'tumour', used once; this paper is in "
        "British English"
    )
    assert second.line == 7
    assert report.ok, "a list of words cannot tell a name from a word, so it only advises"
    assert report.counts["spelling_other"] == 3
    assert report.counts["spelling_own"] == 0


@pytest.mark.parametrize(
    ("word", "instead"),
    [
        ("color", "colour"),
        ("center", "centre"),
        ("analyzed", "analysed"),
        ("hemoglobin", "haemoglobin"),
        ("pediatric", "paediatric"),
        ("modeling", "modelling"),
        ("anemia", "anaemia"),
        ("diarrhea", "diarrhoea"),
        ("hemodynamic", "haemodynamic"),  # from a cluster VarCon has not verified
        ("amebiasis", "amoebiasis"),  # and two more forms taken from such clusters
        ("pedodontics", "paedodontics"),
        ("bacteremia", "bacteraemia"),
        ("artifact", "artefact"),
        ("skeptical", "sceptical"),
        ("fulfill", "fulfil"),
    ],
)
def test_a_british_paper_hears_of_an_american_spelling(
    project: Path, word: str, instead: str
) -> None:
    _, found = written(project, f"# Methods\n\nThe {word} one was kept.\n", "en-GB")
    assert messages(found) == [
        f"'{word}' is the American spelling of '{instead}', used once; this paper is in "
        "British English"
    ]


@pytest.mark.parametrize(
    ("word", "instead"),
    [
        ("colour", "color"),
        ("centre", "center"),
        ("analysed", "analyzed"),
        ("organised", "organized"),  # the ending Oxford does not write either
        ("randomisation", "randomization"),
        ("anonymised", "anonymized"),  # from a cluster VarCon has not verified
        ("haemoglobin", "hemoglobin"),
        ("paediatric", "pediatric"),
        ("modelling", "modeling"),
        ("programme", "program"),
        ("sulphate", "sulfate"),
        ("oestradiol", "estradiol"),
        ("amoebiasis", "amebiasis"),
        ("paedomorphosis", "pedomorphosis"),
        ("speciality", "specialty"),
        ("grey", "gray"),
    ],
)
def test_an_american_paper_hears_of_a_british_spelling(
    project: Path, word: str, instead: str
) -> None:
    _, found = written(project, f"# Methods\n\nThe {word} one was kept.\n", "en-US")
    assert messages(found) == [
        f"'{word}' is the British spelling of '{instead}', used once; this paper is in "
        "American English"
    ]


def test_a_word_british_usage_spells_two_ways_is_told_both(project: Path) -> None:
    _, found = written(project, "# Methods\n\nEach patient was anesthetized.\n")
    assert messages(found) == [
        "'anesthetized' is the American spelling of 'anaesthetised' or 'anaesthetized', "
        "used once; this paper is in British English"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "# Methods\n\nColor was recorded twice.\n",  # opens a paragraph
        "# Methods\n\nIt was recorded. Color was not.\n",  # opens a sentence
        "# Methods\n\nWas it recorded? Color was not.\n",
        "# Color and its measurement\n\nNothing else.\n",  # opens a heading
        "# Methods\n\n- Color of the sample\n- size\n",  # opens a list item
        "# Methods\n\nTwo things:\n* Color of the sample\n* size\n",
        "# Methods\n\n1. Color of the sample\n2. size\n",
        "# Methods\n\n1) Color of the sample\n2) size\n",
        "# Methods\n\n| Item | Value |\n|---|---|\n| Color | red |\n",  # opens a table cell
        "# Abstract\n\n**Results:** Color changed in two samples.\n",  # after a label
        "# Methods\n\nIt was recorded. (Color was not.)\n",
        "# Methods\n\nIt was recorded. \N{LEFT DOUBLE QUOTATION MARK}Color was not, they wrote.\n",
        "# Methods\n\nThe *color* was recorded.\n",  # emphasis is still the word
        "# Methods\n\nThe **color** was recorded.\n",
        "# Methods\n\nThe _color_ was recorded.\n",
        "# Methods\n\nThe color-coded chart was recorded.\n",  # one half of a compound
        "# Methods\n\nThe color's hue was recorded.\n",
        "# Methods\n\nThe sample (color: red) was recorded.\n",
        "# Methods\n\nThe value[^n] was high.\n\n[^n]: The color is given here.\n",  # a footnote
    ],
)
def test_a_word_is_found_wherever_a_sentence_puts_it(project: Path, text: str) -> None:
    _, found = written(project, text)
    assert reported(found) == ["color"], text


def test_the_whole_manuscript_is_one_count(project: Path) -> None:
    """The first use is where the reader meets it first, in the order the build prints the
    files, and the count is of them all, the supplement's included."""
    _, found = written(
        project,
        "# Methods\n\nNothing here.\n",
        discussion="# Discussion\n\nThe tumor grew.\n",
        supplement="# Supplementary methods\n\nEach tumor was measured. Tumor size is given.\n",
    )
    (finding,) = found
    assert finding.message.startswith("'tumor' is the American spelling of 'tumour', used 3 ")
    assert finding.path.name == "discussion.md"
    assert finding.line == 3


def test_a_manuscript_in_the_other_english_gets_one_finding_about_the_setting(
    project: Path,
) -> None:
    """Five spellings of the other usage, used more than the paper's own: the likelier
    mistake is the line in paper.yaml, and one finding about it beats one per word."""
    report, found = written(
        project,
        "# Methods\n\nThe tumor and its color, the anemia and the edema were recorded, and "
        "hemoglobin was measured. The color was recorded twice. We analysed it.\n",
    )
    (finding,) = found
    assert finding.code == "spelling-not-as-declared"
    assert finding.message == (
        "6 words are in American spelling (5 different ones) and 1 in British; paper.yaml "
        "says english_variant: en-GB"
    )
    assert finding.path == project / "paper.yaml"
    assert "set english_variant: en-US" in finding.hint
    assert "color (colour, 2 times), tumor (tumour, once), anemia (anaemia, once)" in (
        finding.hint
    ), "the most used first, then as they come"
    assert " more" not in finding.hint.split("Once")[0]
    assert report.ok
    assert report.counts["spelling_other"] == 6
    assert report.counts["spelling_own"] == 1


def test_that_finding_lists_so_many_words_and_counts_the_rest(project: Path) -> None:
    words = [
        "color", "tumor", "anemia", "edema", "hemoglobin", "center", "fiber", "liter",
        "behavior", "labor", "favor", "odor", "vapor", "rumor",
    ]  # fmt: skip
    assert len(words) == LISTED + 2
    _, found = written(project, "# Methods\n\nWe saw " + ", ".join(words) + ".\n")
    (finding,) = found
    assert "vapor" not in finding.hint and "rumor" not in finding.hint
    assert "odor (odour, once), and 2 more. Once" in finding.hint


def test_that_finding_gives_both_spellings_where_british_usage_has_two(project: Path) -> None:
    _, found = written(
        project,
        "# Methods\n\nWe saw color, tumor, anemia and edema in the anesthetized mice.\n",
    )
    (finding,) = found
    assert "anesthetized (anaesthetised or anaesthetized, once)" in finding.hint


def test_fewer_spellings_than_that_are_reported_each_where_it_stands(project: Path) -> None:
    words = ["color", "tumor", "anemia", "edema", "hemoglobin"]
    assert len(words) == MANY
    text = "# Methods\n\nWe saw " + ", ".join(words[: MANY - 1]) + ".\n"
    _, found = written(project, text)
    assert reported(found) == words[: MANY - 1]


def test_a_paper_mostly_in_its_own_english_hears_of_each_stray_word(project: Path) -> None:
    """As many of the other usage's as of its own is not a paper in the other English."""
    strays = "color, tumor, anemia, edema and hemoglobin"
    own = "The colour, the tumour, the anaemia, the oedema and the haemoglobin agreed."
    _, found = written(project, f"# Methods\n\nWe saw {strays}. {own}\n")
    assert reported(found) == ["color", "tumor", "anemia", "edema", "hemoglobin"]
    _, found = written(project, f"# Methods\n\nWe saw {strays}. The colour agreed.\n")
    assert [f.code for f in found] == ["spelling-not-as-declared"]


def test_a_british_paper_that_writes_both_endings_is_told_once(project: Path) -> None:
    report, found = written(
        project,
        "# Methods\n\nWe summarised the data and randomised the patients. Patients were "
        "randomised by site.\n\n# Results\n\nDoses were standardized.\n",
    )
    (finding,) = found
    assert finding.code == "spelling-mixed"
    assert finding.message == (
        "both endings are used: -ise 3 times ('randomised', 'summarised') and -ize once "
        "('standardized')"
    )
    assert finding.line == 7, "the first word in the ending used less"
    assert "standardized" in finding.context
    assert "Oxford" in finding.hint and "-ize, the ending used less" in finding.hint
    assert report.ok


@pytest.mark.parametrize(
    ("text", "ending"),
    [
        ("We randomised the patients.\n\nDoses were standardized.", "ize"),
        ("Doses were standardized.\n\nWe randomised the patients.", "ise"),
    ],
)
def test_where_the_endings_are_level_the_later_one_is_shown(
    project: Path, text: str, ending: str
) -> None:
    _, found = written(project, f"# Methods\n\n{text}\n")
    (finding,) = found
    assert finding.code == "spelling-mixed"
    assert finding.line == 5, "the second paragraph"
    assert f"the first word in -{ending}" in finding.hint
    assert "since they are level" in finding.hint


def test_endings_level_across_two_files_show_the_later_file_s(project: Path) -> None:
    """Later in the manuscript, which is another file here: an offset alone, counted from
    the top of each file, would not say so."""
    _, found = written(
        project,
        "# Methods\n\nNothing here, for some lines.\n\nAt last, we randomised the patients.\n",
        results="# Results\n\nDoses were standardized.\n",
    )
    (finding,) = found
    assert finding.code == "spelling-mixed"
    assert finding.path.name == "results.md"
    assert "the first word in -ize" in finding.hint


def test_an_ending_in_ize_is_not_evidence_of_british_spelling(project: Path) -> None:
    """Oxford writes it and so does every American, so it is counted for neither: a paper
    in American spelling is not made British by its "randomized"."""
    report, found = written(
        project,
        "# Methods\n\nWe saw color, tumor, anemia, edema and hemoglobin. We randomized, "
        "standardized, organized, summarized and categorized them.\n",
    )
    assert [f.code for f in found] == ["spelling-not-as-declared"]
    assert report.counts["spelling_own"] == 0


def test_the_two_endings_are_counted_across_files(project: Path) -> None:
    _, found = written(
        project,
        "# Methods\n\nWe randomised the patients.\n",
        results="# Results\n\nDoses were standardized and then harmonized.\n",
    )
    (finding,) = found
    assert finding.code == "spelling-mixed"
    assert finding.path.name == "main.md", "-ise is used less, and it is in the first file"


# ---------------------------------------------------------------- what must be left alone


@pytest.mark.parametrize(
    "text",
    [
        "We randomised the patients and summarised the data in colour.",  # -ise throughout
        "We randomized the patients and summarized the data in colour.",  # Oxford spelling
        "We analysed and randomized: Oxford writes analyse, and so does everybody British.",
    ],
)
def test_a_british_paper_that_keeps_to_one_ending_hears_nothing(
    project: Path, text: str
) -> None:
    _, found = written(project, f"# Methods\n\n{text}\n")
    assert not found


def test_an_american_paper_is_not_told_its_endings_are_mixed(project: Path) -> None:
    """It has one ending to write, so a word in the other is the other usage's."""
    _, found = written(
        project, "# Methods\n\nWe randomised the patients and standardized doses.\n", "en-US"
    )
    assert [f.code for f in found] == ["spelling-variant"]
    assert reported(found) == ["randomised"]


@pytest.mark.parametrize(
    "sentence",
    [
        "The program ran and the meter was read.",  # one sense of each is British too
        "The fetus was exposed to sulfur and to magnesium sulfate.",  # IUPAC's, and medicine's
        "Judgment was reserved on the aging cohort.",
        "Estradiol and diethylstilbestrol were given.",  # the International Nonproprietary Names
        "Each specialty was recorded, and rigors were common.",  # British medicine's own words
        "Smith et al. measured the micelle and the protein hydrolysate.",
        "The macule, the papule and the venule were described.",
        "Homeostasis was maintained and the fetor was noted.",
        "We focused on the license holders and on current practice.",
        "The disk was read, the draft was checked and the inquiry was closed.",
        "The math is given in the appendix.",  # a row VarCon has not verified
        # the soil's words, from another root than the child's: never "paedogenic"
        "Pedogenic carbonate and slow pedogenesis were described by the pedologist.",
        "Hematite and stilbestrol were weighed.",  # the mineral's name, and the drug's
    ],
)
def test_a_word_british_usage_also_writes_is_not_american(project: Path, sentence: str) -> None:
    _, found = written(project, f"# Methods\n\n{sentence}\n", "en-GB")
    assert not found, messages(found)


@pytest.mark.parametrize(
    "sentence",
    [
        "The catalogue, the dialogue and the analogue were kept.",
        "Towards the end, whilst the cohort aged, archaeology was not our subject.",
        "The larvae, the fossae and the micellae were counted.",  # Latin plurals, not spellings
        "Surprisal was computed for each token, and expertise was assessed.",
        "We exercise care, advertise the trial, comprise three sites and supervise them.",
        "The protein hydrolysate was added and the caecilian was observed.",
        "Aerogenic bacteria were cultured on the premises.",
        "Acknowledgement is made of the ageing cohort.",
        "Participants were recruited through flyers, and the adaptor protein was knocked down.",
        # a variant in both usages is the spelling of neither
        "By the Sobolev imbedding theorem the map is compact, and a useable fraction remained.",
        "Flash vacuum pyrolyses were run, and the pourer was calibrated.",  # two wrong pairings
        "Entamoeba histolytica and an Endamoeba were cultured.",  # a genus is Latin
        "Blaise Pascal showed it, and the cloth was cut weftwise.",
    ],
)
def test_a_word_american_usage_also_writes_is_not_british(project: Path, sentence: str) -> None:
    _, found = written(project, f"# Methods\n\n{sentence}\n", "en-US")
    assert not found, messages(found)


@pytest.mark.parametrize(
    ("variant", "sentence"),
    [
        ("en-GB", "The World Health Organization and the Centers for Disease Control agreed."),
        ("en-GB", "Imaging was by Color Doppler at the Mayo Medical Center."),
        ("en-GB", "It appeared in the Journal of Tumor Biology and in Pediatrics."),
        ("en-GB", "The Department of Labor and Pearl Harbor are names."),
        ("en-US", "The Centre for Evidence-Based Medicine and the Royal College of Paediatrics."),
        ("en-US", "A MedDRA Standardised Query was used, as the Medical Dictionary calls it."),
        ("en-US", "The National Institute for Health and Care Excellence Programme Board met."),
    ],
)
def test_a_name_keeps_its_spelling(project: Path, variant: str, sentence: str) -> None:
    """A capital that no sentence asks for is a name's, and a name is written as its owner
    writes it, in any paper."""
    _, found = written(project, f"# Methods\n\n{sentence}\n", variant)
    assert not found, messages(found)


def test_a_word_in_capitals_is_not_read(project: Path) -> None:
    _, found = written(project, "# TUMOR RESPONSE\n\nThe COLOR channel and the TUMOR arm.\n")
    assert not found


def test_only_the_first_word_of_a_heading_in_title_case_is_read(project: Path) -> None:
    """The limit of taking a capital for a name's, written down in Known gaps: "Color" here
    is a word of the heading, and it is read as "Color Doppler" is."""
    _, found = written(project, "# Tumor Response and Color Change\n\nNothing else.\n")
    assert reported(found) == ["tumor"]


@pytest.mark.parametrize(
    "text",
    [
        "See `color` in the script.",
        "As reported [@color2020; @tumor-study].",
        "The value was {{results.color}}.",
        'The <span class="color">value</span> was high.',
        "See https://example.org/color/tumor for the data.",
        "<!-- the color is to be checked -->\n\nThe value was high.",
        "```\ncolor = tumor\n```\n\nThe value was high.",
        "The variables tumor_size and color2 were recoded, with x_color and 3color.",
        "![The value](figures/color.png)",
        # CSS and HTML are written in American, in any paper
        '<span style="color:red">The value</span> was high.',
        '<div class="color">\n\nThe value was high.\n\n</div>',
        "See [the figure][color-ref].\n\n[color-ref]: https://example.org/x",
        # a block of attributes that opens with a key, which the masking leaves
        '![The value](figures/x.png){fig-align="center" width=80%}',
        'The [value]{style="text-align: center; color: red"} was high.',
        '::: {style="text-align: center"}\nThe value was high.\n:::',
        "Write to info@color-lab.org or to center@example.org, or read color.csv.",
        # a word after a backslash: a macro named for a word, a folder in a path
        "\\providecommand{\\center}{c}\n\nThe value was high.",
        "Outputs are written to C:\\\\study\\\\color\\\\results.csv.",
    ],
)
def test_what_is_not_the_paper_s_prose_is_not_read(project: Path, text: str) -> None:
    _, found = written(project, f"# Methods\n\n{text}\n")
    assert not found, messages(found)


def test_braces_that_hold_no_key_are_prose(project: Path) -> None:
    _, found = written(project, "# Methods\n\nThe set {color, tumor} was recorded.\n")
    assert reported(found) == ["color", "tumor"]


def test_the_front_matter_is_not_read(project: Path) -> None:
    _, found = written(
        project, "---\ntitle: The color of tumors\n---\n\n# Methods\n\nNothing here.\n"
    )
    assert not found


def test_a_quotation_keeps_its_author_s_spelling(project: Path) -> None:
    _, found = written(
        project,
        "# Methods\n\nThe guideline says:\n\n> The color of the tumor is to be recorded.\n\n"
        "We recorded the colour.\n",
    )
    assert not found


def test_the_reference_list_is_not_read(project: Path) -> None:
    _, found = written(
        project,
        "# Methods\n\nNothing here.\n\n# References\n\nSmith J. Color and behavior in the "
        "tumor. J Color Res. 2020.\n",
    )
    assert not found


def test_a_spelling_the_project_keeps_is_not_reported(project: Path) -> None:
    text = "# Methods\n\nThe artifact was removed and the color was noted. Artifacts recur.\n"
    _, found = written(project, text)
    assert reported(found) == ["artifact", "color", "artifacts"]
    _, found = written(project, text, accepted=["Artifact", "artifacts"])
    assert reported(found) == ["color"], "in any case, and each form is listed"


def test_a_spelling_the_project_keeps_is_out_of_the_count_of_endings(project: Path) -> None:
    text = "# Methods\n\nWe randomised the patients. They were cognizant of the risk.\n"
    _, found = written(project, text)
    assert [f.code for f in found] == ["spelling-mixed"]
    _, found = written(project, text, accepted=["cognizant"])
    assert not found


@pytest.mark.parametrize("accepted", ["color", {"color": True}, 5, [5, None, ["color"]]])
def test_a_setting_in_the_wrong_shape_is_the_schema_s_and_does_not_stop_the_gate(
    project: Path, accepted: object
) -> None:
    _, found = written(project, "# Methods\n\nThe color was noted.\n", accepted=accepted)
    assert reported(found) == ["color"]
    _, contract = load_project(project)
    refused = [f.message for f in contract.failures]
    assert any("language/accepted_spellings" in message for message in refused), refused


def test_one_entry_written_wrongly_does_not_take_the_others_with_it(project: Path) -> None:
    _, found = written(
        project,
        "# Methods\n\nThe color of the tumor was noted.\n",
        accepted=[5, "color"],
    )
    assert reported(found) == ["tumor"]
    assert load_project(project)[0].accepted_spellings == ("color",)


def test_the_schema_takes_the_setting(project: Path) -> None:
    written(project, "# Methods\n\nNothing here.\n", accepted=["specialty", "Color"])
    projekt, contract = load_project(project)
    assert projekt.accepted_spellings == ("specialty", "Color")
    assert contract.ok, messages(contract.findings)


@pytest.mark.parametrize("entry", ["Labor Department", "color-coded", "color2"])
def test_the_schema_reports_an_entry_that_is_not_one_word(project: Path, entry: str) -> None:
    """Only a word can be kept, since only words are read: an entry that is a whole name
    would never match, and the author would not know why the warning stayed."""
    _, found = written(
        project, "# Methods\n\nLabor Department figures were color-coded.\n", accepted=[entry]
    )
    assert reported(found) == ["labor", "color"]
    _, contract = load_project(project)
    refused = [f.message for f in contract.failures]
    assert any("language/accepted_spellings/0" in message for message in refused), refused


@pytest.mark.parametrize("variant", ["en-AU", "en-gb", "", 5, None, ["en-GB"], {"a": "en-GB"}])
def test_another_english_is_not_judged(variant: object) -> None:
    """The schema lets a paper be en-GB or en-US. Called with anything else, a list or a
    mapping included, the reading has no list to hold the paper to: it says nothing, and
    it does not raise."""
    text = "The color and the colour."
    passages = [Passage(Path("main.md"), text, text, lambda offset: 1)]
    report = judge_spelling(passages, variant, (), Path("paper.yaml"))
    assert not report.findings
    assert report.counts == {"spelling_own": 0, "spelling_other": 0}


@pytest.mark.parametrize("variant", [["en-GB"], {"a": "en-GB"}, 5, None])
def test_an_english_in_the_wrong_shape_does_not_take_the_gate_s_other_readings_with_it(
    project: Path, variant: object
) -> None:
    """The schema reports the setting. The first version looked a list up in a table, the
    gate raised, and the abbreviations and the vocabulary went unreported with it."""
    report, found = written(project, "# Methods\n\nThe ROR and the color were noted.\n", variant)
    assert not found
    assert [f.code for f in report.findings] == ["abbreviation-undefined"]


def test_the_reading_asked_directly_takes_what_it_is_given() -> None:
    """A caller with a list of its own, and something in it that is no word."""
    text = "The color of the tumor."
    passages = [Passage(Path("main.md"), text, text, lambda offset: 1)]
    report = judge_spelling(passages, "en-GB", (5, None, "Color"), Path("paper.yaml"))
    assert reported(report.findings) == ["tumor"]


def test_the_example_is_in_the_english_it_declares(project: Path) -> None:
    """Dogfooding. "MedDRA Standardised Query" is in it, and is a name."""
    projekt, _ = load_project(project)
    report = check_language(projekt)
    assert not [f for f in report.findings if f.code.startswith("spelling-")]
    assert report.counts["spelling_own"] >= 1
    assert report.counts["spelling_other"] == 0


@pytest.mark.parametrize(
    ("heading", "variant", "sentence"),
    [
        (
            "Author contributions",
            "en-GB",
            "Conceptualization: AB. Formal analysis: CD. Visualization: EF.",
        ),
        (
            "CRediT authorship contribution statement",
            "en-GB",
            "AB: Conceptualization, Visualization. CD: Formal analysis, Organization.",
        ),
        (
            "Funding",
            "en-US",
            "This project has received funding from the European Union's Horizon 2020 "
            "research and innovation programme under grant agreement No 101000000.",
        ),
        (
            "Role of the funding source",
            "en-US",
            "The funder's programme office had no part in the analysis.",
        ),
        (
            "Acknowledgements",
            "en-US",
            "We thank the staff of the centre and the paediatric nurses of the programme.",
        ),
        ("Acknowledgments", "en-GB", "We thank the center's staff for the color charts."),
        (
            "Declaration of competing interests",
            "en-GB",
            "AB has received honoraria from a tumor program of the manufacturer.",
        ),
    ],
)
def test_a_section_whose_wording_is_somebody_else_s_is_not_read(
    project: Path, heading: str, variant: str, sentence: str
) -> None:
    """The role names of a contributions statement are the CRediT taxonomy's, a funding
    statement is worded by the funder, and an acknowledgement names people's institutions.
    Read like the rest, the first gave a British paper in -ise a `spelling-mixed` for
    "Conceptualization", and the second an American one a finding for "programme"."""
    own = {
        "en-GB": "We randomised the patients and recorded the colour.",
        "en-US": "We randomized the patients and recorded the color.",
    }[variant]
    _, found = written(project, f"# Methods\n\n{own}\n\n# {heading}\n\n{sentence}\n", variant)
    assert not found, messages(found)


def test_what_stands_in_such_a_section_is_out_of_the_count_and_the_next_is_read(
    project: Path,
) -> None:
    report, found = written(
        project,
        "# Methods\n\nThe color was noted.\n\n# Acknowledgements\n\nWe thank the color "
        "laboratory. Its color charts were lent to us.\n\n# Appendix\n\nThe color chart is "
        "reproduced here.\n",
    )
    (finding,) = found
    assert finding.message.startswith("'color' is the American spelling of 'colour', used 2 ")
    assert finding.line == 3
    assert report.counts["spelling_other"] == 2


def test_a_subsection_of_such_a_section_is_left_out_with_it(project: Path) -> None:
    _, found = written(
        project,
        "# Funding\n\n## Grants\n\nThe programme was funded.\n\n# Data\n\nThe programme "
        "data are public.\n",
        "en-US",
    )
    (finding,) = found
    assert finding.message.startswith("'programme' is the British spelling of 'program', used once")
    assert finding.line == 9


def test_a_slip_in_such_a_section_is_the_price(project: Path) -> None:
    """Written down in Known gaps: the author's own "color" in an acknowledgement passes,
    and so does a whole section of the paper proper whose title holds one of the words."""
    _, found = written(
        project,
        "# Methods\n\nNothing here.\n\n# Funding of primary care\n\nThe color of money.\n",
    )
    assert not found


# ---------------------------------------------------------------- where a sentence opens


@pytest.mark.parametrize(
    ("before", "opens"),
    [
        ("", True),  # the start of the text
        ("It was. ", True),
        ("It was.\n", True),
        ("It was! ", True),
        ("the ", False),
        ("the\n", False),  # a line wrapped inside a sentence
        ("no full stop\n\n", True),  # a new paragraph
        ("no full stop\n  \n", True),
        ("- ", True),
        ("text\n- ", True),
        ("text\n* ", True),
        ("text\n+ ", True),
        ("text\n  - ", True),
        ("text\n        - ", True),  # a list inside a list
        ("text\n" + " " * 40 + "- ", True),  # and deeper than most
        ("no full stop\n\n            ", True),
        ("It was. [", True),
        ("text\n12. ", True),
        ("text\n2) ", True),
        ("# ", True),
        ("text\n### ", True),
        ("| ", True),
        ("| a | ", True),
        ("**Results:** ", True),
        ("Results: ", True),
        ("It was. (", True),
        ("It was. *", True),
        ('a "', False),
        ("a - ", False),  # a dash inside a sentence, not a list item
        ("a 2) ", False),
        ("the **", False),
        ("x\x00", False),  # after something hidden, nothing is known
        ("x" + " " * 400, False),  # further back than the search goes
    ],
)
def test_where_a_capital_is_the_sentence_s(before: str, opens: bool) -> None:
    text = before + "Color was noted."
    assert _opens_a_sentence(text, len(before)) is opens, repr(before)


# ---------------------------------------------------------------- reading at any size


def test_a_long_manuscript_is_read_in_linear_time(assert_linear) -> None:
    def manuscript(count: int) -> list[Passage]:
        text = (
            "The color of the Tumor was noted. Color and tumor_size differ; we organised "
            "and standardized the data.\n\n> A quotation in color.\n\n"
        ) * count
        return [Passage(Path("main.md"), text, text, lambda offset: 1)]

    def judge(passages: list[Passage]) -> None:
        report = judge_spelling(passages, "en-GB", (), Path("paper.yaml"))
        assert {f.code for f in report.findings} == {"spelling-variant", "spelling-mixed"}

    assert_linear(manuscript, judge, 200, "the spelling, by length")


def test_one_long_line_of_capitals_is_read_in_linear_time(assert_linear) -> None:
    """Every word here asks where its sentence opens, and none finds a line break."""

    def manuscript(count: int) -> list[Passage]:
        text = "Color " * count
        return [Passage(Path("main.md"), text, text, lambda offset: 1)]

    def judge(passages: list[Passage]) -> None:
        report = judge_spelling(passages, "en-GB", (), Path("paper.yaml"))
        assert report.counts["spelling_other"] == 1, "only the first opens a sentence"

    assert_linear(manuscript, judge, 2000, "the spelling, on one line")


@pytest.mark.parametrize("opener", ['<span style="', "{fig-align=", "][", "[label]: "])
def test_a_line_of_markup_left_open_is_read_in_linear_time(assert_linear, opener: str) -> None:
    """Each kind of markup this reading hides, opened again and again on one line and never
    closed. The first version also hid LaTeX commands, and read such a line of them from
    each one to the end: 96 KB took seven seconds."""

    def manuscript(count: int) -> list[Passage]:
        text = "See " + (opener + "color ") * count
        return [Passage(Path("main.md"), text, text, lambda offset: 1)]

    def judge(passages: list[Passage]) -> None:
        judge_spelling(passages, "en-GB", (), Path("paper.yaml"))

    assert_linear(manuscript, judge, 2000, f"the spelling, on a line of {opener!r}")


# ---------------------------------------------------------------- the list itself


def rows() -> list[tuple[str, str, str]]:
    lines = [
        line
        for line in DATA.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#")
    ]
    assert lines[0] == ""
    assert lines[1] == "word\tkind\tinstead"
    return [tuple(line.split("\t")) for line in lines[2:]]


def test_the_list_is_well_formed() -> None:
    raw = DATA.read_bytes()
    assert b"\r" not in raw, "LF, whatever the checkout"
    assert raw.endswith(b"\n")
    assert raw.isascii()
    listed = rows()
    assert all(len(row) == 3 for row in listed)
    words = [word for word, _, _ in listed]
    assert words == sorted(set(words)), "sorted, and each word once"
    for word, kind, instead in listed:
        assert re.fullmatch(r"[a-z]{4,}", word), word
        assert kind in {"us", "gb", "ise"}, word
        assert re.fullmatch(r"[a-z]+(?:/[a-z]+)?", instead), word
        assert word not in instead.split("/"), word


def test_the_list_agrees_with_itself() -> None:
    """What a row says to write instead is never a word the same usage is told off for."""
    kinds = {word: kind for word, kind, _ in rows()}
    for word, kind, instead in rows():
        for spelling in instead.split("/"):
            other = kinds.get(spelling)
            if kind == "us":
                assert other != "us", (word, spelling)
            else:
                assert other is None or other == "us", (word, spelling)
        if kind == "ise":
            assert [(a, b) for a, b in zip(word, instead, strict=True) if a != b] == [
                ("s", "z")
            ], word


@pytest.mark.parametrize(
    ("word", "row"),
    [
        ("color", ("us", "colour")),
        ("colour", ("gb", "color")),
        ("analyze", ("us", "analyse")),
        ("analyse", ("gb", "analyze")),
        ("organise", ("ise", "organize")),
        ("randomisation", ("ise", "randomization")),
        ("hemodynamic", ("us", "haemodynamic")),
        ("amebiasis", ("us", "amoebiasis")),
        ("paedodontics", ("gb", "pedodontics")),
        ("anesthetize", ("us", "anaesthetise/anaesthetize")),
        ("sulphate", ("gb", "sulfate")),
    ],
)
def test_the_list_holds_what_it_should(word: str, row: tuple[str, str]) -> None:
    words, with_ize = _variants()
    assert words[word] == row
    assert "organize" in with_ize and "randomization" in with_ize


@pytest.mark.parametrize(
    "word",
    [
        "organize", "program", "meter", "fetus", "sulfur", "sulfate", "judgment", "aging",
        "gray", "license", "practice", "focused", "specialty", "rigor", "estradiol",
        "hydrolysate", "et", "ax", "mom", "micelle", "macule", "diene", "raphe", "prev",
        "surprisal", "expertise", "advertise", "exercise", "larvae", "fossae", "homeostasis",
        "flyer", "adaptor", "pedogenic", "pedology", "pedologist", "entamoeba", "hematite",
        "stilbestrol", "imbedding", "useable", "focussed", "pyrolyses", "pourer", "blaise",
        "weftwise", "caulkings",
    ],
)  # fmt: skip
def test_the_list_leaves_out_what_it_should(word: str) -> None:
    words, _ = _variants()
    assert word not in words


def test_the_list_carries_its_source_s_notices() -> None:
    """VarCon's terms: the copyright and permission notices travel with every copy, and a
    modified version is marked as one."""
    head = DATA.read_text(encoding="utf-8").split("\nword\tkind\tinstead\n")[0]
    for line in (
        "THIS IS A MODIFIED VERSION",
        "Copyright 2000-2020 by Kevin Atkinson (kevina@gnu.org) and Benjamin Titze",
        "Copyright 2000-2019 by Kevin Atkinson",
        "Copyright 2016 by Benjamin Titze",
        "Copyright 1993, Geoff Kuenning, Granada Hills, CA",
        "Permission to use, copy, modify, distribute and sell this array",
        "3. All modifications to the source code must be clearly marked as such.",
        "THIS SOFTWARE IS PROVIDED BY GEOFF KUENNING AND CONTRIBUTORS",
    ):
        assert line in head, line
    attribution = (REPO / "ATTRIBUTION.md").read_text(encoding="utf-8")
    notices = head[head.index("# Copyright 2000-2020") :]
    said = " ".join(re.sub(r"(?m)^[#>] ?", "", attribution).split())
    assert " ".join(re.sub(r"(?m)^# ?", "", notices).split()) in said, (
        "the supporting documentation repeats the notices, word for word"
    )
    assert "modified version" in attribution
    # In a fence. As a quotation, Markdown took the licence's numbered clauses for a list
    # and renumbered them: clause 5 was printed as 4, under a note that 4 was removed.
    assert "\n```text\nCopyright 2000-2020 by Kevin Atkinson" in attribution
    assert "SUCH DAMAGE.\n```\n" in attribution


# ---------------------------------------------------------------- the script that derives it


@pytest.fixture(scope="module")
def derive():
    spec = importlib.util.spec_from_file_location("derive_spelling_variants", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass looks its module up while it is defined
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def test_the_committed_list_is_the_script_s(derive) -> None:
    """Its notice and its source are the script's, to the byte: nobody edited the head of
    the file by hand, and the script was not changed without deriving the list again."""
    committed = DATA.read_text(encoding="utf-8")
    assert committed.startswith(derive.render([]))
    assert derive.SOURCE["sha256"] in committed and derive.SOURCE["commit"] in committed
    assert derive.render([tuple(row) for row in rows()]) == committed


def test_the_list_is_what_the_script_derives_from_varcon(derive) -> None:
    """With the pinned varcon.txt at hand, named in MANUSCRIPT_GUARD_VARCON: the committed
    list is the script's output, byte for byte. The source is not in the repository, so
    without it this is skipped, and the test above holds what can be held."""
    source = os.environ.get("MANUSCRIPT_GUARD_VARCON")
    if not source:
        pytest.skip("MANUSCRIPT_GUARD_VARCON does not name a copy of varcon.txt")
    data = Path(source).read_bytes()
    assert hashlib.sha256(data).hexdigest() == derive.SOURCE["sha256"]
    derived = derive.render(derive.derive(derive.read(data.decode("latin-1"))))
    assert derived.encode("utf-8") == DATA.read_bytes()


def test_every_word_the_script_leaves_out_would_have_had_a_row(
    derive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the pinned source at hand. A word in `EVERYWHERE` that takes no row out of the
    list says VarCon was wrong where the list never was: two such stood there once."""
    source = os.environ.get("MANUSCRIPT_GUARD_VARCON")
    if not source:
        pytest.skip("MANUSCRIPT_GUARD_VARCON does not name a copy of varcon.txt")
    lines = derive.read(Path(source).read_bytes().decode("latin-1"))
    left_out = set(derive.EVERYWHERE)
    monkeypatch.setattr(derive, "EVERYWHERE", {})
    with_them = {word for word, _, _ in derive.derive(lines)}
    assert sorted(left_out - with_them) == []


def test_a_line_of_varcon_is_read_as_its_readme_says(derive) -> None:
    line = derive.read_line("A Cv: acknowledgment / Av B C: acknowledgement", 35)
    assert line.preferred == {
        "A": "acknowledgment",
        "B": "acknowledgement",
        "Z": "acknowledgement",
    }, "with no Z on the line, B stands for Z"
    assert line.accepted["A"] == {"acknowledgment", "acknowledgement"}
    assert line.accepted["B"] == {"acknowledgement"}

    line = derive.read_line("A Z: organize / B: organise | <V>", 10)
    assert line.preferred == {"A": "organize", "B": "organise", "Z": "organize"}
    assert line.accepted["Z"] == {"organize"}, "a Z on the line, so B does not stand for it"

    caulk = "A B: caulk / Av: calk / AV Bv 1: caulking / AV 2: calking | <N> :3"
    line = derive.read_line(caulk, 35)
    assert line.accepted["A"] == {"caulk", "calk"}, "a seldom-used variant is not accepted"
    assert line.accepted["B"] == {"caulk", "caulking"}

    assert derive.read_line("C: colour / D: colour", 10) is None, "no American or British tag"


VARCON = """\
## A sample in VarCon's format.
# color <verified> (level 10)
A: color / B: colour
A: colors / B: colours

# organize <verified> (level 10)
A Z: organize / B: organise
A Z: organization / B: organisation

# meter <verified> (level 20)
A: meter / B: metre | unit
A B: meter | instrument

# analyze <verified> (level 20)
A: analyze / B: analyse

# ax <verified> (level 20)
A: ax / B: axe

# specialty <verified> (level 20)
A: specialty / B: speciality

# sulfate <verified> (level 50)
A: sulfate / B: sulphate

# et (level 70)
A: et / B: aet

# micelle (level 70)
A: micelle / B: micellae

# hemodynamic (level 80)
A: hemodynamic / B: haemodynamic

# anonymize (level 80)
A Z: anonymize / B: anonymise

# readvertize (level 80)
A Z: readvertize / B: readvertise

# surprizal (level 80)
A Z: surprizal / B: surprisal

# hydrolyze <verified> (level 60)
A Z: hydrolyzable / B: hydrolysable

# zzzz <verified> (level 95)
A: zzzor / B: zzzour
A B: fiber / B: fibre

# fiber <verified> (level 20)
A: fiber / B: fibre

# judgment <verified> (level 10)
A B.: judgment / B: judgement

# mold <verified> (level 35)
A: mold / B: mould

# anonymization (level 80)
A Z: anonymization / B: anonymisation

# bacteremia (level 80)
A: bacteremia / B: bacteraemia

# pedogenesis (level 70)
A: pedogenesis / B: paedogenesis

# anesthetize <verified> (level 40)
A: anesthetize / B: anaesthetise / Z: anaesthetize

# liter <verified> (level 20)
A: liter / B: litre # the unit, and a comment

# Cesarean <verified> (level 50)
A: Cesarean / B: Caesarean

# maneuver <verified> (level 35)
A: maneuver / Bv: manoeuver / B: manoeuvre

# embed <verified> (level 35)
A B: embedding / AV Bv: imbedding
A B: fetus / Bv: foetus

# adapter <verified> (level 35)
A Bv: adapter / AV B: adaptor

# surprize (level 80)
A Z: surprize / B: surprise

# mize (level 70)
A Z: mize / B: mise

# weftwize (level 80)
A Z: weftwize / B: weftwise

# gray <verified> (level 10)
A Cv: gray / AV B C: grey

# amebiasis (level 70)
A: amebiasis / B: amoebiasis
"""


def test_the_script_takes_the_rows_it_says_it_takes(derive) -> None:
    derived = {word: (kind, instead) for word, kind, instead in derive.derive(derive.read(VARCON))}
    assert derived == {
        "color": ("us", "colour"),
        "colors": ("us", "colours"),
        "colour": ("gb", "color"),
        "colours": ("gb", "colors"),
        # the British -ise of a word Oxford writes with -ize; the -ize spelling has no row
        "organise": ("ise", "organize"),
        "organisation": ("ise", "organization"),
        # "meter" is accepted in British usage on another line, so only "metre" has a row
        "metre": ("gb", "meter"),
        "analyze": ("us", "analyse"),
        "analyse": ("gb", "analyze"),
        # "ax" and "axe" are too short for a row
        # science writes "specialty" and "sulfate" in both; the British spellings stay
        "speciality": ("gb", "specialty"),
        "sulphate": ("gb", "sulfate"),
        # from clusters nobody verified: a combining form, and a verb in -ise
        "hemodynamic": ("us", "haemodynamic"),
        "haemodynamic": ("gb", "hemodynamic"),
        "anonymise": ("ise", "anonymize"),
        # -yse is not an ending British usage chooses, so this is plain British
        "hydrolysable": ("gb", "hydrolyzable"),
        # above level 80 a cluster writes no row, and its line still accepts "fiber" in
        # British usage, which is why "fiber" has none
        "fibre": ("gb", "fiber"),
        # "judgment" is equal in British usage (`B.`), so it has no row
        "judgement": ("gb", "judgment"),
        "mold": ("us", "mould"),  # four letters are enough
        "mould": ("gb", "mold"),
        # more from clusters nobody verified: the noun of a verb in -ise, and -aemia.
        # "pedogenesis" is the soil's word and is named in EVERYWHERE, so it has no row;
        # "paedogenesis", the zoologist's, is British
        "paedogenesis": ("gb", "pedogenesis"),
        "anonymisation": ("ise", "anonymization"),
        "bacteremia": ("us", "bacteraemia"),
        "bacteraemia": ("gb", "bacteremia"),
        # Oxford's spelling is neither of the others: both are offered, and both are British
        "anesthetize": ("us", "anaesthetise/anaesthetize"),
        "anaesthetise": ("gb", "anesthetize"),
        "anaesthetize": ("gb", "anesthetize"),
        "liter": ("us", "litre"),  # the comment after the line is no part of the word
        "litre": ("gb", "liter"),
        # what to write is the preferred spelling, not the first the usage accepts
        "maneuver": ("us", "manoeuvre"),
        "manoeuver": ("gb", "maneuver"),
        "manoeuvre": ("gb", "maneuver"),
        # "imbedding" is a variant in both usages and so the spelling of neither; "foetus"
        # has no American tag and is British. "Caesarean" has a capital, "adaptor" is in
        # EVERYWHERE, and "surprise", "mise" and "weftwise" are no verbs in -ize
        "foetus": ("gb", "fetus"),
        # "grey" is tagged for both usages and they prefer different spellings, so it is
        # British: the rule above is for a word both have as a variant of the same one.
        # In this sample no other line accepts "gray" in British usage, as VarCon's do
        "gray": ("us", "grey"),
        "grey": ("gb", "gray"),
        # from a cluster nobody verified, through the form amoeb-
        "amebiasis": ("us", "amoebiasis"),
        "amoebiasis": ("gb", "amebiasis"),
    }


def test_the_words_the_script_leaves_out_are_these(derive) -> None:
    """The table by name, so that a word cannot leave it, or join it, unseen where the
    source is not at hand to derive the list again: on CI. With the source, the test
    above also holds that each of them takes a row out."""
    assert sorted(derive.EVERYWHERE) == [
        "acknowledgment", "acknowledgments", "adaptor", "adaptors", "blaise",
        "diethylstilbestrol", "endamoeba", "endamoebae", "endamoebas", "entamoeba",
        "entamoebae", "entamoebas", "estradiol", "estradiols", "estriol", "estriols",
        "estrone", "estrones", "flyer", "flyers", "hematite", "hematites", "hematitic",
        "pedogeneses", "pedogenesis", "pedogenetic", "pedogenic", "pedological",
        "pedologist", "pedologists", "porer", "pourer", "pyrolyses", "rigor", "rigors",
        "scaped", "specialties", "specialty", "stilbestrol", "stilbestrols",
    ]  # fmt: skip
    assert all(derive.EVERYWHERE.values()), "each with its reason"
    assert sorted(derive.DIGRAPHS) == [
        "aemi", "aetiol", "amoeb", "anaesth", "coeli", "gynaec", "haem", "oedem",
        "oesoph", "oestr", "paed", "palaeo", "pnoea", "rrhoea",
    ]  # fmt: skip


def test_the_script_refuses_a_source_that_is_not_the_pinned_one(
    derive, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "varcon.txt"
    source.write_bytes(VARCON.encode("latin-1"))
    target = tmp_path / "spelling_variants.tsv"
    monkeypatch.setattr(derive, "TARGET", target)
    assert derive.main(["derive", str(source)]) == 1
    assert "is not the pinned source" in capsys.readouterr().err
    assert not target.exists()

    monkeypatch.setitem(
        derive.SOURCE, "sha256", hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assert derive.main(["derive", str(source)]) == 0
    written_rows = target.read_bytes()
    assert b"\r" not in written_rows
    assert b"colour\tgb\tcolor\n" in written_rows
    assert derive.main(["derive"]) == 2, "no source named"
