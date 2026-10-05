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
    unless one is given, and its abbreviations are not this file's subject."""
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
    kept = tuple(f for f in report.findings if not f.code.startswith("abbreviation-"))
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
        "Data are in `subjects.csv`, read by `load_subjects()`.",
        "As reported [@subjectsAndPatients2020], recall was low.",
        "See https://example.org/subjects for the protocol.",
        "<!-- subjects or participants? decide before submission -->\n\nRecall was low.",
        "> We called them subjects, and the patients objected.\n\nRecall was low.",
        "![Flow of subjects through the study](figures/flow.svg)",
        "The count $n_{subjects}$ was fixed in advance.",
        "The count was {{results.cohort.n_reports}} reports.",
    ],
)
def test_the_letters_of_a_term_elsewhere_are_not_the_term(project: Path, sentence: str) -> None:
    _, found = written(project, f"# Methods\n\n{sentence}\n")
    assert not found, messages(found)


def test_a_fenced_listing_and_a_reference_list_are_not_read(project: Path) -> None:
    _, found = written(
        project,
        "# Methods\n\nParticipants were enrolled.\n\n```r\nsubjects <- read.csv(path)\n```\n\n"
        "# References\n\n1. Smith J. Human subjects in research. Lancet.\n",
    )
    assert not found, messages(found)


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


# ---------------------------------------------------------------- entries that disagree


def test_a_term_both_used_and_given_up_is_reported_and_not_looked_for(project: Path) -> None:
    vocabulary = [
        {"use": "participants", "avoid": ["subjects"]},
        {"use": "subjects", "avoid": ["volunteers"]},
    ]
    _, found = written(
        project, "# Results\n\nSubjects and volunteers were enrolled.\n", vocabulary
    )
    by_code = {f.code: f for f in found}
    assert set(by_code) == {"vocabulary-conflict", "term-avoided"}
    assert "'subjects' is a term to use and a term to avoid" in by_code[
        "vocabulary-conflict"
    ].message
    assert by_code["vocabulary-conflict"].path.name == "paper.yaml"
    assert "'volunteers'" in by_code["term-avoided"].message, "the rest is still read"


def test_a_term_given_up_for_two_others_is_reported_and_not_looked_for(project: Path) -> None:
    vocabulary = [
        {"use": "participants", "avoid": ["subjects"]},
        {"use": "patients", "avoid": ["subjects"]},
    ]
    _, found = written(project, "# Results\n\nSubjects were enrolled.\n", vocabulary)
    (finding,) = found
    assert finding.code == "vocabulary-conflict"
    assert "'participants'" in finding.message and "'patients'" in finding.message


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
