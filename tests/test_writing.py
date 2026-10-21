"""G6 — signs of machine-written prose.

Two things have to hold at once, and they pull against each other. The lint must catch
prose written the way models write, and it must stay quiet on ordinary scientific English.
A check that flags "robust standard errors" gets switched off within a day, and a check
that is switched off guards nothing.

So the suite has a positive half and a negative half, and the negative half is the one that
keeps the gate usable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_writing


def written(project: Path, text: str):
    """Judge exactly this text and nothing else.

    The gate reads every source, so the example's supplement has to go — otherwise its two
    hundred words sit underneath every case here, and the ones about *rates* stop measuring
    what they say they measure.
    """
    import shutil

    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(text, encoding="utf-8")
    projekt, _ = load_project(project)
    return check_writing(projekt)


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


def messages(report) -> str:
    return " | ".join(f.message for f in report.findings)


# Long enough that the density rules engage; deliberately plain.
FILLER = (
    "The database was assembled from spontaneous reports submitted between the study "
    "dates. Reports were included without restriction on age or sex. Duplicate records "
    "were removed by matching on report identifier, and the remaining records were "
    "classified by drug and by reported event. Counts were tabulated and the reporting "
    "odds ratio computed from the resulting contingency table. Intervals were derived "
    "from the standard error of the log odds ratio. No imputation was performed and no "
    "records were excluded after the analysis began. " * 4
)


# ---------------------------------------------------------------- what must be caught


@pytest.mark.parametrize(
    "artefact",
    [
        "See :contentReference[oaicite:3]{index=3} for detail.",
        "This was reported previously [cite: 12].",
        "As of my last training data, no such analysis existed.",
        # Round 2 of #339: the apostrophe a word processor curls.
        "I don\N{RIGHT SINGLE QUOTATION MARK}t have access to the full registry.",
        "Here\N{RIGHT SINGLE QUOTATION MARK}s the revised Methods section.",
        "Certainly! Here is the revised Methods section.",
        "We analysed TODO reports.",
        "The rate was [insert value here] per year.",
    ],
)
def test_model_artefacts_fail(project: Path, artefact: str) -> None:
    """These have no innocent reading and must never reach a submission."""
    report = written(project, f"# Methods\n\n{artefact}\n")
    assert "model-artefact" in codes(report)
    assert not report.ok, "an artefact is a failure, not a warning"


@pytest.mark.parametrize(
    ("phrase", "rule"),
    [
        ("We delve into the mechanisms of injury.", "delve"),
        ("The data form a rich tapestry of exposure patterns.", "tapestry-landscape"),
        ("This is a testament to the value of spontaneous reporting.", "testament"),
        ("It is important to note that reporting is voluntary.", "important-to-note"),
        ("Despite these challenges, the signal persisted.", "despite-challenges"),
        ("These findings pave the way for prospective study.", "paves-the-way"),
        ("In the realm of pharmacovigilance, signals are noisy.", "in-the-realm"),
        ("The ever-evolving regulatory landscape complicates this.", "ever-evolving"),
        ("Reports rose sharply, highlighting the importance of vigilance.", "importance-tail"),
    ],
)
def test_known_tells_are_reported(project: Path, phrase: str, rule: str) -> None:
    report = written(project, f"# Discussion\n\n{phrase}\n")
    assert "ai-phrasing" in codes(report)
    assert rule in messages(report)


#: Two constructions papers by people use too: each was reported wherever it stood, and so
#: in about a quarter of 384 such papers (tools/g6_baseline.py, 2026-10-19). Basile chose to
#: count them by rate instead.
BY_RATE = ("The signal is not only statistical but also clinical. Hepatic metabolism plays a "
           "crucial role in clearance. ")  # fmt: skip


def test_a_construction_counted_by_its_rate_is_no_warning_once(project: Path) -> None:
    # Once in some 2300 words, a paper's length, is under either threshold.
    once = written(project, f"# Discussion\n\n{BY_RATE}\n\n{FILLER * 7}")
    assert "negative-parallelism" not in messages(once)
    assert "plays-a-role" not in messages(once)
    often = written(project, f"# Discussion\n\n{BY_RATE * 5}\n\n{FILLER * 2}")
    assert "ai-cadence" in codes(often)
    for rule in ("negative-parallelism", "plays-a-role"):
        assert any(f.code == "ai-cadence" and f.message.startswith(f"{rule}: ")
                   for f in often.findings), rule  # fmt: skip


def test_a_high_rate_of_ai_vocabulary_is_reported(project: Path) -> None:
    """Each word is ordinary. The rate is the signal."""
    text = (
        "# Discussion\n\nThis crucial and pivotal finding underscores a robust and "
        "comprehensive picture. The intricate interplay of factors highlights a nuanced, "
        "multifaceted landscape. Meticulous analysis showcases compelling and invaluable "
        "insight, fostering a holistic and seamless understanding that enhances and "
        "bolsters the paramount case for vigilance. " * 3
    ) + FILLER  # past the 200-word floor, where a rate starts to mean something
    report = written(project, text)
    assert "ai-cadence" in codes(report)
    assert "ai-vocabulary" in messages(report)


def test_unsupported_appeals_to_authority_are_reported(project: Path) -> None:
    report = written(project, "# Introduction\n\nStudies have shown that reporting is low.\n")
    assert "vague-attribution" in codes(report)


def test_copula_avoidance_is_reported_at_a_high_rate(project: Path) -> None:
    text = (
        "# Discussion\n\nThe database serves as a source of signals. The ratio stands as a "
        "measure of association. The centre functions as a hub. The report serves as a "
        "record. The estimate represents a summary. " * 2
    ) + FILLER
    report = written(project, text)
    assert "copula-avoidance" in messages(report)


# ---------------------------------------------------------------- what must stay quiet


def test_ordinary_scientific_prose_passes(project: Path) -> None:
    report = written(project, f"# Methods\n\n{FILLER}\n")
    assert report.ok
    assert not report.findings, messages(report)


def test_technical_senses_are_not_counted(project: Path) -> None:
    """"Robust standard errors" is not a tell; it is the name of the estimator."""
    text = (
        "# Methods\n\nWe report robust standard errors throughout. A robustness analysis "
        "was pre-specified, and the robust variance estimator was used for clustered "
        "data. " + FILLER
    )
    report = written(project, text)
    assert "ai-vocabulary" not in messages(report)


def test_a_technical_sense_counts_nothing_towards_the_rate() -> None:
    """Held on the count, not the finding: one "robust" under the threshold passed whether
    it was exempt or not, and the plural, "robust standard errors", as people write it, was
    counted (found on papers by people, item 54)."""
    from manuscript_guard.gates.writing import rates

    text = (
        "We report robust standard errors, robust variances and robust estimators, with "
        "robust regressions and robust checks, and one robust analysis. " + FILLER * 3
    )
    assert rates([(Path("main.md"), text)])["ai-vocabulary"] == 0


def test_a_flagged_word_used_once_is_not_reported(project: Path) -> None:
    report = written(project, f"# Discussion\n\nThis is a key limitation. {FILLER}\n")
    assert report.ok, messages(report)


def test_vague_attribution_with_a_citation_is_accepted(project: Path) -> None:
    """In a manuscript the fix is a reference, so a cited claim is not vague."""
    report = written(
        project,
        "# Introduction\n\nStudies have shown that reporting is low "
        "[@fictionalHepaticCohort2021].\n",
    )
    assert "vague-attribution" not in codes(report)


def test_a_structured_abstract_is_not_over_bolded(project: Path) -> None:
    """Journals require those bold labels; counting them would flag their house style."""
    text = (
        "# Abstract\n\n**Background.** Injury is common.\n**Methods.** A disproportionality "
        "analysis.\n**Results.** The ratio was raised.\n**Conclusions.** Caution is "
        "warranted.\n\n# Methods\n\n" + FILLER
    )
    report = written(project, text)
    assert "boldface" not in messages(report)


def test_citations_and_code_are_not_read_as_prose(project: Path) -> None:
    """A citekey containing a flagged word is not the author's cadence."""
    text = (
        "# Discussion\n\nAs reported [@robustCrucialPivotalUnderscore2020] and in "
        "`crucial_pivotal_robust()`. " + FILLER
    )
    report = written(project, text)
    assert "ai-vocabulary" not in messages(report)


def test_short_documents_skip_the_rate_checks(project: Path) -> None:
    """A rate over forty words means nothing, and reporting one would be noise."""
    report = written(project, "# Notes\n\nA crucial, pivotal, robust and comprehensive note.\n")
    assert "ai-cadence" not in codes(report)


def test_the_example_manuscript_passes(project: Path) -> None:
    """Dogfooding: the worked example's prose has to clear the gate it ships."""
    projekt, _ = load_project(project)
    report = check_writing(projekt)
    assert report.ok, report.render(project)
    assert report.counts["prose_words"] > 300
    assert report.counts["writing_artefacts"] == 0


def test_findings_say_which_rule_fired(project: Path) -> None:
    """An author arguing with the lint needs to see the rule and the reason."""
    report = written(project, "# Discussion\n\nWe delve into the mechanisms.\n")
    finding = next(f for f in report.findings if f.code == "ai-phrasing")
    assert "delve" in finding.message
    assert finding.hint
    assert finding.context
    assert finding.line == 3


@pytest.mark.parametrize(
    "above",
    [
        "# Discussion\n\n<!--\na note\nover three lines\n-->\n",
        "# Discussion\n\n```r\ncases <- 12\ntotal <- 480\n```\n",
        '---\ntitle: "A study"\nlang: en\n---\n\n# Discussion\n',
    ],
    ids=["comment", "listing", "front-matter"],
)
def test_a_finding_is_on_its_own_line_under_lines_the_gate_does_not_read(
    project: Path, above: str
) -> None:
    """A comment, a listing and the front matter's machinery are blanked before the prose
    rules run, line ends included, and the lines were counted in what was left: a phrase
    under a comment of four lines was reported three lines up, on the comment itself."""
    sentences = {
        "ai-phrasing": "We delve into the mechanisms.",
        "vague-attribution": "Studies have shown that reporting is low.",
        "model-artefact": "We analysed TODO reports.",
    }
    text = above + "".join(f"\n{sentence}\n" for sentence in sentences.values())
    report = written(project, text)
    lines = text.split("\n")
    expected = {code: lines.index(sentence) + 1 for code, sentence in sentences.items()}
    assert sorted(expected.values()) == [8, 10, 12], "each opening is six lines"
    assert {f.code: f.line for f in report.findings} == expected


@pytest.mark.parametrize("blank_lines", [1, 3])
def test_an_artefact_that_opens_a_paragraph_is_on_its_own_line(
    project: Path, blank_lines: int
) -> None:
    """The rule for a chat assistant's opening word reads from the start of a line, through
    any blank lines, to the word. The finding was placed where that reading began: on the
    first blank line above the paragraph, not on the sentence."""
    text = "# Methods\n" + "\n" * blank_lines + "Certainly! Here is the revised section.\n"
    report = written(project, text)
    assert [f.line for f in report.findings if f.code == "model-artefact"] == [blank_lines + 2]


def test_a_finding_under_a_comment_still_shows_its_prose(project: Path) -> None:
    """The line is counted in the file; what is shown beside it is still the prose, with
    the comment above it left out, and a phrase in the comment is not a finding."""
    report = written(
        project,
        "# Discussion\n\n<!--\nwe delve into this later\n-->\n\nWe delve into the mechanisms.\n",
    )
    (finding,) = report.findings
    assert finding.line == 7
    assert finding.context == "We delve into the mechanisms."


# ------------------------------------------------- words to the reviewers, left in the paper

#: Each residue that answers one reviewer or the editor, points at this manuscript, or was
#: written by a model to its user, with the rule that must find it. Each warns until
#: submission and fails there.
SAID_TO_ONE = [
    ("As requested by Reviewer 2, we added a sensitivity analysis.", "reviewer-answered"),
    ("As suggested by the reviewer, we now report the median.", "reviewer-answered"),
    ("In response to the reviewer's comment, we clarified the exposure.", "reviewer-answered"),
    ("Following Reviewer 1's suggestion, the forest plot was redrawn.", "reviewer-answered"),
    ("To address the second reviewer\N{RIGHT SINGLE QUOTATION MARK}s concern, we repeated it.",
     "reviewer-answered"),
    ("We thank the reviewer for this helpful comment.", "reviewer-answered"),
    ("We are grateful to the referee for raising this point.", "reviewer-answered"),
    # Round 2 of #377: what round 1's narrowing let through.
    ("We thank the reviewer for bringing this to our attention.", "reviewer-answered"),
    ("We thank Reviewer 2 for their helpful suggestion.", "reviewer-answered"),
    ("We thank the reviewer for bringing this up.", "reviewer-answered"),
    ("At the request of the editor, the abstract was shortened.", "reviewer-answered"),
    ("As the reviewer rightly pointed out, the cohort was small.", "reviewer-answered"),
    ("Reviewer #3 asked whether the dose was recorded.", "reviewer-answered"),
    ("This analysis was suggested by Referee B.", "reviewer-answered"),
    ("In reply to the\nreviewer, we added a table.", "reviewer-answered"),
    ("In our original submission, the cohort was larger.", "earlier-version"),
    ("This revised manuscript reports the median.", "earlier-version"),
    ("Compared with the previous version of this manuscript, Table 2 is new.",
     "earlier-version"),
    ("The definition differs from an earlier draft of our manuscript.", "earlier-version"),
    # Round 1 of #377: a verb of writing far before the noun, and a limitation's "We
    # acknowledge", exempted these as contributions and thanks.
    ("We revised the Methods because our original submission pooled the cohorts.",
     "earlier-version"),
    ("We acknowledge that, compared with the previous version of this manuscript, the sample "
     "is smaller.", "earlier-version"),
    ("We have now clarified the definition of exposure.", "we-have-now"),
    ("We now have added a paragraph on missing data.", "we-have-now"),
    ("We\N{RIGHT SINGLE QUOTATION MARK}ve now toned down the conclusion.", "we-have-now"),
    ("We have expanded the Discussion to cover confounding.", "text-edited"),
    ("We have rephrased the sentence on causality.", "text-edited"),
    ("We have modified the text accordingly.", "text-edited"),
    ("This has now been clarified in the text.", "text-edited"),
    ("The sentence has been amended accordingly.", "text-edited"),
    ("A paragraph has been added to the Limitations.", "text-edited"),
    ("This has now been addressed in the Discussion.", "text-edited"),
    ("This has been clarified in the text of the manuscript.", "text-edited"),
    ("This limitation has now been acknowledged in the revised manuscript.", "text-edited"),
    ("The definition is on page 4, lines 120\N{EN DASH}125.", "lines-cited"),
    ("See lines 245-250 of the revised manuscript.", "lines-cited"),
    ("The revised text is highlighted in yellow.", "changes-marked"),
    ("New sentences are shown in red.", "changes-marked"),
    ("The revised text is shown in a different colour.", "changes-marked"),
    ("All changes are shown in track changes.", "changes-marked"),
    ("Details are given in our response to Reviewer 2.", "reviewer-answered"),
    ("Details are given in our response letter.", "response-letter"),
    ("See the response letter for the full table.", "response-letter"),
    ("Our point-by-point reply to the reviewers explains why.", "response-letter"),
    ("As you requested, the abstract is now shorter.", "model-addressed"),
    ("I have shortened the abstract to two hundred words.", "model-addressed"),
    ("I\N{RIGHT SINGLE QUOTATION MARK}ve rewritten the Discussion to be concise.",
     "model-addressed"),
    ("Below is the revised Introduction:", "model-addressed"),
    ("Per your instructions, the tables were merged.", "model-addressed"),
    ("I have incorporated all your suggestions.", "model-addressed"),
]  # fmt: skip

#: Each residue that a paper about peer review also writes of the papers it studied, with
#: its rule. Each warns at every stage.
SAID_TO_ANY = [
    ("In response to the reviewers' comments, a sensitivity analysis was added.",
     "reviewers-answered"),
    ("As suggested by one of the reviewers, the radiograph lacked detail.",
     "reviewers-answered"),
    ("Following reviewer comments, the scale was shortened.", "reviewers-answered"),
    ("The reviewer's comment concerned the dose.", "reviewers-answered"),
    ("We thank the reviewers for raising this point.", "reviewers-answered"),
    ("As requested, we added the dates.", "as-requested"),
    ("The revised manuscript reports the median.", "earlier-version-unnamed"),
    ("In the original submission, the cohort was larger.", "earlier-version-unnamed"),
    ("In the previous version of the manuscript, Table 2 was longer.",
     "earlier-version-unnamed"),
    ("The definition was moved (lines 120\N{EN DASH}125).", "lines-cited-alone"),
    # Round 1 of #377: a change named with no part of this manuscript, which a regulatory
    # or a guideline's update writes of itself too.
    ("This has now been clarified.", "text-edited-unnamed"),
    ("These points have now been discussed.", "text-edited-unnamed"),
    ("In this update, we have revised the section on renal dosing.", "text-edited-unnamed"),
    ("Tracked changes were accepted before it was sent.", "tracked-changes"),
    ("The response letter lists every change.", "response-letter-unnamed"),
    ("A point-by-point response accompanies this paper.", "response-letter-unnamed"),
]  # fmt: skip

#: What the residue rules must not take: most are sentences of papers by people, from the
#: corpus `tools/g6_baseline.py` reads, cut down; the rest are the commonest ways a
#: pharmacology or epidemiology paper writes the same words. Names; the authors' own words
#: for their methods; contributions; acknowledgements; a journal's notices; and prose.
NOT_SAID_TO_ANYONE = [
    "Perioperative risk was scored with the Revised Cardiac Risk Index.",
    "Pulmonary embolism was assessed with the revised Geneva score.",
    "Patients fulfilled the 1987 ACR revised criteria.",
    "Depression was measured with the Clinical Interview Schedule-Revised (CIS-R).",
    "Diagnoses were coded with the International Classification of Diseases, 10th revision.",
    "The study followed the Declaration of Helsinki of 1975, as revised in 2008.",
    "Reads were aligned with the revised Cambridge Reference Sequence.",
    "Risk was estimated with the revised Framingham Stroke Risk Profile.",
    "The REVISION trial will report next year.",
    "Revision of the femoral component was rare.",
    "In the revised protocol, we asked participants for permission.",
    "Our revised estimate of the mating rate was higher.",
    "The final revised version contains fifteen statements.",
    "In the original version, items were rated on a five-point scale.",
    "The previous version of MedDRA coded this term differently.",
    "The previous version of this review included twelve trials.",
    "This is an update of a review first published in 2015.",
    "In this update, we included five new trials.",
    "This updated meta-analysis adds three trials.",
    "We corrected for multiple comparisons.",
    "The original study enrolled children.",
    "Previous studies reported a lower rate.",
    "This original article reports a cohort.",
    "The original submission of the dossier to the agency was rejected.",
    "HJ drafted the initial manuscript.",
    "JL revised the original manuscript.",
    "RW wrote the first draft of the manuscript, and all authors contributed to revisions.",
    "All authors read and approved the final manuscript.",
    "All authors approved the revised manuscript.",
    "All authors approved this version of the manuscript.",
    "All authors contributed to the article and approved the submitted version.",
    "YG critically revised the manuscript for important intellectual content.",
    "EGB made major revisions to the first draft.",
    "Writing \N{EN DASH} original draft: LC.",
    "We thank two anonymous reviewers for their helpful and constructive comments.",
    "We are grateful for the comments from reviewers on earlier drafts of this manuscript.",
    "We thank Dr. Smith for comments on an earlier version of this manuscript.",
    "The authors are grateful to Dr. Simon and Dr. Sampaio for their critical review in the "
    "original manuscript.",
    "We thank the handling editor, subject editor, and two anonymous reviewers for their "
    "constructive and helpful comments.",
    "We thank the Editor and an anonymous reviewer for their helpful comments.",
    "We thank the reviewer for the helpful comments.",
    "We thank X and Y for their comments on a previous draft of this paper.",
    "The views are not necessarily those of the publisher, the editors and the reviewers.",
    "Academic Editor: Yaacov Barak",
    "A copy of the consent is available for review by the Editor-in-Chief of this journal.",
    "The handling editor declared a shared affiliation with the authors at the time of review.",
    "This review was written at the invitation of the editor.",
    "This commentary was written in response to the editor's invitation.",
    "To address this concern, we used an active comparator.",
    "To address this issue, we estimated the extent of misclassification.",
    "To avoid confusion, we refer to the second cohort as the validation set.",
    "In response to treatment, the rash resolved.",
    "In response to our survey, most respondents felt less able to influence policy.",
    "In response to this experience, we added text to the preparation task.",
    "Two studies published during the revision of this manuscript asked the same question.",
    "In the present manuscript, we show that the cells form a barrier.",
    "After we posted a preprint of an earlier version of this paper, two groups wrote to us.",
    "Using this technique, we now report a novel coactivator.",
    "We now investigated invasion of the wild-type strain.",
    "Risk groups were defined as recommended by the European Centre for Disease Prevention "
    "and Control.",
    "The species grouped as suggested by its morphology.",
    "As proposed by Gauthier et al., the genus was nested within the family.",
    "Two reviewers independently screened titles and abstracts.",
    "Disagreements were resolved by a third reviewer.",
    "Reviewer 1 and Reviewer 2 independently extracted the data.",
    "Discrepancies noted by the second reviewer were discussed.",
    "Disagreements were resolved as decided by the third reviewer.",
    "The reviewers remark that controlled studies do not exist.",
    "The quotation is from the interview guide (p. 59).",
    "Line 1: hydroxylase; M: marker.",
    "The global methylation (LINE 1) remained stable.",
    "Vectors were propagated in the E1-complementing cell line 293.",
    "First-line therapy was metformin.",
    "In the first round of the Delphi survey, forty experts responded.",
    "The first mailing comprises a cover letter and a questionnaire.",
    "The receptor binding domain was highlighted in yellow.",
    "Amino acid changes are highlighted in red.",
    "We have expanded on previous work by modelling the dose.",
    "We have rewritten the package in C++.",
    "We have clarified the role of CYP3A4 in this interaction.",
    "We have now shown that the effect persists.",
    "In this guideline, we have included statements on renal dosing.",
    "These have been discussed in the Introduction.",
    "\N{LEFT DOUBLE QUOTATION MARK}I have too much work to do,\N{RIGHT DOUBLE QUOTATION MARK} "
    "one nurse said.",
    "\N{LEFT DOUBLE QUOTATION MARK}I have seen too many patients die."
    "\N{RIGHT DOUBLE QUOTATION MARK}",
    "Has your daughter started her periods yet?",
    "as suggested by\n\nReviewer 2 independently, a heading and a paragraph.",
    # Round 1 of #377: a thanks that names what was pointed out, regulatory prose, a
    # translation, a Delphi panel's drafts, an instrument's wording, a psycholinguistic
    # study's stimuli, and the ICMJE's approval.
    "We thank the referee for pointing out an error in the variance estimator.",
    "We thank the editor for highlighting the need for this review.",
    "We thank the referee for the suggestion to use the bootstrap.",
    "This has now been included in the SmPC.",
    "These issues have now been addressed in the ICH E9(R1) addendum.",
    "We have adapted the wording of the items to Japanese.",
    "Our initial draft comprised 45 items.",
    "This revised draft was circulated for the second round.",
    "Items whose revised wording is shown in Table 3 were kept.",
    "New sentences were written by two authors.",
    "All authors approve this version of the manuscript.",
    "All authors provided final approval of this version of the manuscript.",
    # Round 2 of #377: a contribution's other words, and a label's text.
    "All authors contributed to the writing and revision of this version of the manuscript.",
    "All authors approved the content of this version of the manuscript.",
    "A new section has been added to the text of the SmPC.",
    "We thank the guest editor for bringing this collection together.",
    "This has been updated in the revised text of the SmPC.",
]  # fmt: skip


def _residue(text: str) -> list[str]:
    from manuscript_guard.gates.writing import load_rules, residue_in

    return [rule["id"] for rule, _match in residue_in(load_rules(), text)]


@pytest.mark.parametrize(("sentence", "rule"), SAID_TO_ONE + SAID_TO_ANY)
def test_words_to_the_reviewers_are_found_once(sentence: str, rule: str) -> None:
    assert _residue(sentence) == [rule]


@pytest.mark.parametrize("sentence", NOT_SAID_TO_ANYONE)
def test_what_reads_like_words_to_the_reviewers_and_is_prose_passes(sentence: str) -> None:
    assert _residue(sentence) == []


def test_a_contribution_s_words_before_an_earlier_version_hide_it() -> None:
    """A limit (Known gaps): the words a contribution puts between its verb and the noun
    exempt a residue that has them, since "approved the content of this version of the
    manuscript" has them too."""
    assert _residue("We revised the content of our original manuscript to add a year.") == []


def test_which_residue_fails_at_submission_is_marked() -> None:
    from manuscript_guard.gates.writing import load_rules

    marked = {rule["id"] for rule in load_rules().residue if rule.get("self_reference")}
    assert marked == {rule for _sentence, rule in SAID_TO_ONE}
    assert marked.isdisjoint(rule for _sentence, rule in SAID_TO_ANY)


def _residue_said(project: Path, text: str, *, submission: bool) -> list[tuple[str, int]]:
    import shutil

    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(text, encoding="utf-8")
    projekt, _ = load_project(project)
    report = check_writing(projekt, submission=submission)
    return [(f.severity, f.line) for f in report.findings if f.code == "revision-residue"]


def test_a_residue_warns_while_drafting_and_fails_at_submission(project: Path) -> None:
    """Basile, 2026-10-20: the words that answer one reviewer fail at submission and warn
    before it; those a paper about peer review writes too warn at every stage."""
    text = (
        "# Methods\n\nAs requested by Reviewer 2, we added a sensitivity analysis.\n\n"
        "The revised manuscript reports the median.\n"
    )
    assert _residue_said(project, text, submission=False) == [("warn", 3), ("warn", 5)]
    assert _residue_said(project, text, submission=True) == [("fail", 3), ("warn", 5)]


def test_a_residue_in_a_comment_or_a_listing_is_not_read(project: Path) -> None:
    """A comment is the author's note to themself and is never printed; a listing is code."""
    text = (
        "# Methods\n\n<!-- As requested by Reviewer 2, we added this. -->\n\n"
        "```\n# in response to the reviewer's comment\n```\n\nThe cohort was small.\n"
    )
    assert _residue_said(project, text, submission=True) == []


def test_an_artefact_is_not_said_again_as_a_residue(project: Path) -> None:
    """"Here is the revised Methods" fails as the assistant's voice already."""
    report = written(project, "# Methods\n\nHere is the revised Methods section.\n")
    assert [f.code for f in report.findings] == ["model-artefact"]


def test_check_fails_at_submission_on_a_residue_and_counts_it(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "# Data availability",
            "We have now clarified the definition of exposure.\n\n# Data availability",
            1,
        ),
        encoding="utf-8",
    )
    drafting, _project, _stage, _deferred = _run_gates(project, stage="drafting")
    submitted, _project, _stage, _deferred = _run_gates(project, stage="submission")
    said = {
        stage: [f.severity for f in report.findings if f.code == "revision-residue"]
        for stage, report in (("drafting", drafting), ("submission", submitted))
    }
    assert said == {"drafting": ["warn"], "submission": ["fail"]}
    assert submitted.counts["writing_residue"] == 1
