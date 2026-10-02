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
        ("The finding is not just statistical but also clinical.", "negative-parallelism"),
        ("It is important to note that reporting is voluntary.", "important-to-note"),
        ("Despite these challenges, the signal persisted.", "despite-challenges"),
        ("Hepatic metabolism plays a crucial role in clearance.", "plays-a-role"),
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
