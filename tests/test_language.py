"""G14 — the manuscript's abbreviations agree with themselves.

The same two halves as G6. The gate must report an abbreviation that is used before it is
defined, defined twice, defined for nothing or never defined; and it must stay quiet on a
surname with two capitals, a Roman numeral, a heading in capitals and a contributor's
initials. Every finding is a warning, so a noisy rule here costs nothing at the build and
everything in attention: the quiet half is what keeps the warnings read.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_language
from manuscript_guard.gates.language import _definitions, _long_form, _prose


def written(project: Path, text: str, *, supplement: str | None = None, **files: str):
    """Judge exactly this text. The example's supplement goes unless one is given, and
    `files` are further main-text files, named without their `.md`."""
    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(text, encoding="utf-8")
    for name, body in files.items():
        (project / "manuscript" / f"{name}.md").write_text(body, encoding="utf-8")
    if supplement is not None:
        folder = project / "manuscript" / "supplementary"
        folder.mkdir()
        (folder / "S1.md").write_text(supplement, encoding="utf-8")
    projekt, _ = load_project(project)
    return check_language(projekt)


def configured(project: Path, **settings) -> None:
    path = project / "paper.yaml"
    paper = yaml.safe_load(path.read_text(encoding="utf-8"))
    paper.update(settings)
    path.write_text(yaml.safe_dump(paper, sort_keys=False), encoding="utf-8")


def found(report, code: str | None = None) -> list[str]:
    return [f.message for f in report.findings if code is None or f.code == code]


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


PLAIN = (
    "Reports were included without restriction on age or sex. Duplicate records were "
    "removed by matching on report identifier, and the remaining records were classified "
    "by drug and by reported event."
)


# ---------------------------------------------------------------- what must be caught


def test_an_abbreviation_used_before_its_definition_is_reported(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe ROR was computed for each drug.\n\n"
        "The reporting odds ratio (ROR) compares two groups of reports.\n",
    )
    assert codes(report) == {"abbreviation-used-before-defined"}
    (finding,) = report.findings
    assert finding.line == 3, "reported where it is used, not where it is defined"
    assert "ROR" in finding.message
    assert "manuscript/main.md:5" in finding.message, "and says where the definition is"
    assert finding.hint and finding.context


def test_an_abbreviation_defined_twice_is_reported(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR compares "
        "groups.\n\n# Discussion\n\nThe reporting odds ratio (ROR) was raised.\n",
    )
    assert codes(report) == {"abbreviation-redefined"}
    (finding,) = report.findings
    assert finding.line == 7, "the second definition is the one to remove"
    assert "defined again" in finding.message
    assert "manuscript/main.md:3" in finding.message


def test_one_short_form_with_two_meanings_names_both(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR compares "
        "groups.\n\nThe relative odds ratio (ROR) was used as a check.\n",
    )
    (message,) = found(report, "abbreviation-redefined")
    assert "relative odds ratio" in message
    assert "reporting odds ratio" in message


def test_a_definition_nothing_uses_is_reported(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed for each drug.\n",
    )
    assert codes(report) == {"abbreviation-unused"}
    (finding,) = report.findings
    assert "reporting odds ratio" in finding.hint, "the hint says what to write instead"


def test_an_abbreviation_never_defined_is_reported_once(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe ROR was computed. The ROR compares groups. A raised ROR is a "
        "signal.\n",
    )
    assert codes(report) == {"abbreviation-undefined"}
    (finding,) = report.findings
    assert "3 times" in finding.message, "one finding for the abbreviation, with its count"
    assert finding.line == 3
    assert "known_abbreviations" in finding.hint


def test_the_main_text_does_not_inherit_from_the_abstract(project: Path) -> None:
    report = written(
        project,
        "# Abstract\n\nThe reporting odds ratio (ROR) was raised; the ROR is not a risk.\n\n"
        "# Methods\n\nThe ROR was computed for each drug.\n",
    )
    (message,) = found(report, "abbreviation-undefined")
    assert "main text" in message
    assert "abstract defines it" in message


def test_the_abstract_does_not_inherit_from_the_main_text(project: Path) -> None:
    report = written(
        project,
        "# Abstract\n\nThe ROR was raised.\n\n"
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR compares groups.\n",
    )
    (message,) = found(report, "abbreviation-undefined")
    assert "in the abstract" in message


def test_a_subsection_of_the_abstract_is_the_abstract(project: Path) -> None:
    """A structured abstract written with headings is still read apart."""
    report = written(
        project,
        "# Abstract\n\n## Results\n\nThe ROR was raised.\n\n"
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR compares groups.\n",
    )
    assert "in the abstract" in " ".join(found(report, "abbreviation-undefined"))


def test_a_supplement_is_held_to_its_own_abbreviations(project: Path) -> None:
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n",
        supplement="# Supplementary methods\n\nThe PRR was computed as a check.\n",
    )
    (message,) = found(report, "abbreviation-undefined")
    assert "PRR" in message and "supplement" in message


# ---------------------------------------------------------------- what counts as a definition


@pytest.mark.parametrize(
    "definition",
    [
        "The reporting odds ratio (ROR) was computed.",
        "The ROR (reporting odds ratio) was computed.",
        "The ROR (the reporting odds ratio) was computed.",
        "The reporting odds ratio (ROR; a measure of disproportionality) was computed.",
        "The reporting odds ratio (*ROR*) was computed.",
        "The reporting odds\nratio (ROR) was computed.",
        "Reporting Odds Ratio (ROR) was computed.",
    ],
)
def test_both_orders_of_a_definition_are_read(project: Path, definition: str) -> None:
    report = written(project, f"# Methods\n\n{definition} The ROR compares groups.\n")
    assert not report.findings, found(report)


def test_a_definition_in_square_brackets_is_read(project: Path) -> None:
    """The form a journal uses inside a parenthesis, where round brackets would nest."""
    configured(project, language={"known_abbreviations": []})
    report = written(
        project,
        "# Results\n\nThe risk was lower with treatment (hazard ratio [HR], 0.75; 95% "
        "confidence interval [CI], 0.60 to 0.94). The HR was stable and the CI was narrow.\n",
    )
    assert not report.findings, found(report)


def test_markup_and_punctuation_are_no_part_of_a_long_form(project: Path) -> None:
    """An emphasised first definition and a plain second one are one meaning, and the hint
    quotes the words without their asterisks."""
    report = written(
        project,
        "# Methods\n\nThe *reporting odds ratio* (ROR) was computed. The ROR compares "
        "groups.\n\n# Discussion\n\nThe reporting odds ratio, (ROR) was raised.\n",
    )
    (message,) = found(report, "abbreviation-redefined")
    assert "defined again" in message, "not two meanings"
    unused = written(project, "# Methods\n\nThe **reporting odds ratio** (ROR) was computed.\n")
    (finding,) = unused.findings
    assert "'reporting odds ratio'" in finding.hint


def test_a_short_form_does_not_define_itself_through_its_plural(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nAssociations were expressed as ORs (OR, 95% CI). The OR was raised.\n",
    )
    assert codes(report) == {"abbreviation-undefined"}, found(report)


@pytest.mark.parametrize(
    ("definition", "use"),
    [
        ("Monoclonal antibodies (mAbs) were used.", "Each mAb was tested."),
        ("Monoclonal antibodies (mAbs) were used.", "The mAbs were tested."),
        ("A monoclonal antibody (mAb) was used.", "Two mAbs were tested."),
    ],
)
def test_a_plural_in_lower_case_is_the_singular_s(project: Path, definition: str, use: str) -> None:
    report = written(project, f"# Methods\n\n{definition} {use}\n")
    assert not report.findings, found(report)


def test_neither_a_bracket_nor_a_long_form_crosses_a_blank_line(project: Path) -> None:
    """Two paragraphs are two thoughts: a long form ending one does not define the bracket
    opening the next, and a bracket left open does not close in the next."""
    apart = written(
        project,
        "# Methods\n\nWe computed the reporting odds ratio\n\n(ROR) in each stratum. The ROR "
        "was raised.\n",
    )
    assert codes(apart) == {"abbreviation-undefined"}, found(apart)
    for opened, closed in ("()", "[]"):
        open_bracket = written(
            project,
            f"# Methods\n\nThe reporting odds ratio {opened}ROR;\n\nsee below{closed} was "
            "raised. The ROR was raised.\n",
        )
        assert codes(open_bracket) == {"abbreviation-undefined"}, found(open_bracket)


def test_definitions_are_read_in_the_order_they_stand(project: Path) -> None:
    """Square brackets are found in a second pass, and the first definition is still the
    one that stands first."""
    report = written(
        project,
        "# Results\n\nThe hazard ratio [HR] was 0.75. The HR was stable.\n\n# Discussion\n\n"
        "The hazard ratio (HR) fell.\n",
    )
    (finding,) = report.findings
    assert finding.code == "abbreviation-redefined"
    assert finding.line == 7
    assert "manuscript/main.md:3" in finding.message


def test_used_before_defined_names_the_first_use_and_the_first_definition(
    project: Path,
) -> None:
    report = written(
        project,
        "# Methods\n\nThe ROR was computed.\n\nThe ROR compares groups.\n\nThe reporting odds "
        "ratio (ROR) is a ratio. The ROR was raised.\n\nThe reporting odds ratio (ROR) fell.\n",
    )
    early = next(f for f in report.findings if f.code == "abbreviation-used-before-defined")
    assert early.line == 3
    assert "manuscript/main.md:7" in early.message


def test_a_lower_case_s_is_the_plural_s_only_after_a_plural_long_form() -> None:
    from manuscript_guard.gates.language import _stem

    assert _stem("scFvs", "single-chain variable fragments") == "scFv"
    assert _stem("scFvs", "single-chain variable fragment") == "scFvs"
    assert _stem("RORs", "reporting odds ratio") == "ROR", "after a capital it always is"


def test_a_plural_definition_defines_the_singular(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nIndividual case safety reports (ICSRs) were extracted. Each ICSR "
        "names a drug, and ICSRs naming several were counted once.\n",
    )
    assert not report.findings, found(report)


def test_a_hyphenated_use_is_a_use(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. ROR-based signals were "
        "listed.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    ("sentence", "named"),
    [
        ("Samples were analysed by LC-MS.", "LC-MS"),
        ("Clusters were drawn with t-SNE.", "t-SNE"),
        ("In the KEYNOTE-189 trial, survival was longer.", "KEYNOTE-189"),
        ("Levels of 25-OH-D were measured.", "25-OH-D"),
        ("ROR-based signals were listed.", "ROR"),
        ("Non-ROR signals were listed.", "ROR"),
    ],
)
def test_a_hyphenated_abbreviation_is_reported_whole(
    project: Path, sentence: str, named: str
) -> None:
    """Under the name its definition would use, and once: not `LC` and `MS`. An ordinary
    word joined to it is not part of the name."""
    report = written(project, f"# Methods\n\n{sentence}\n")
    (message,) = found(report, "abbreviation-undefined")
    assert message.split()[0] == named


def test_a_hyphenated_abbreviation_defined_whole_is_used_whole(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nLiquid chromatography-mass spectrometry (LC-MS) was used. LC-MS runs "
        "took an hour.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "text",
    [
        "RNA sequencing (RNA-seq) libraries were prepared; RNA-seq reads were aligned.",
        "Non-high-density lipoprotein cholesterol (non-HDL-C) was the outcome. Mean "
        "non-HDL-C fell.",
        "Chromatin immunoprecipitation sequencing (ChIP-seq) was done. ChIP-seq peaks were "
        "called.",
        "Anti-factor Xa activity (anti-FXa) was measured. The anti-FXa level rose.",
    ],
)
def test_a_name_that_holds_an_ordinary_word_is_still_one_name(project: Path, text: str) -> None:
    """Looked for whole before the word is split at `seq` or `non`. Split first, the
    definition was reported as unused and its capitals as undefined."""
    report = written(project, f"# Methods\n\n{text}\n")
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "text",
    [
        "Non-high-density lipoprotein cholesterol (non-HDL-C) was the outcome. Mean "
        "non-HDL-C fell. Non-HDL-C was lower in women.",
        "Anti-factor Xa activity (anti-FXa) was measured. The anti-FXa level rose. Anti-FXa "
        "activity was stable.",
        "We measured non-high-density lipoprotein cholesterol (non-HDL-C) and high-density "
        "lipoprotein cholesterol (HDL-C). HDL-C rose. Non-HDL-C fell.",
    ],
)
def test_a_name_takes_a_capital_at_the_start_of_a_sentence(project: Path, text: str) -> None:
    """`Non-HDL-C` is `non-HDL-C`. Matched only as written, the word was split at `Non`,
    and `HDL-C` was reported as undefined, or `non-HDL-C` as unused."""
    report = written(project, f"# Methods\n\n{text}\n")
    assert not report.findings, found(report)


def test_the_capitals_of_a_name_are_the_name(project: Path) -> None:
    """Only an ordinary word opening the name is lowered: `Rna-seq` is not `RNA-seq`."""
    report = written(
        project,
        "# Methods\n\nRNA sequencing (RNA-seq) libraries were prepared. Rna-seq reads were "
        "aligned.\n",
    )
    assert codes(report) == {"abbreviation-unused"}, found(report)


def test_a_listed_name_takes_a_capital_at_the_start_of_a_sentence(project: Path) -> None:
    """The same for a name the project lists as for one the manuscript defines."""
    text = "# Methods\n\nMean values fell. Non-HDL-C was lower in women.\n"
    (message,) = found(written(project, text))
    assert message.startswith("HDL-C is used once")
    configured(project, language={"known_abbreviations": ["non-HDL-C"]})
    assert not written(project, text).findings


def test_the_plural_of_a_name_takes_the_capital_too(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nPatients not on immune checkpoint inhibitors (non-ICI) were controls. "
        "The non-ICI group was older. Non-ICIs were excluded.\n",
    )
    assert not report.findings, found(report)


def test_a_name_inside_a_longer_word_takes_the_capital_too(project: Path) -> None:
    """Wherever in the word the name opens, not only at its head."""
    report = written(
        project,
        "# Methods\n\nNon-high-density lipoprotein cholesterol (non-HDL-C) was the outcome. "
        "Mean non-HDL-C fell. Post-Non-HDL-C values rose.\n",
    )
    assert not report.findings, found(report)


def test_a_single_letter_opening_a_name_is_not_lowered(project: Path) -> None:
    """A known gap, held so that closing it is a decision: an ordinary word has two letters
    or more, so `T-PA` opening a sentence is not `t-PA`."""
    report = written(
        project,
        "# Methods\n\nTissue plasminogen activator (t-PA) was given. The t-PA dose was fixed. "
        "T-PA was stopped early.\n",
    )
    (message,) = found(report)
    assert message.startswith("T-PA is used once")


def test_the_longest_defined_name_is_the_one_used(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nNon-high-density lipoprotein (non-HDL) and non-high-density "
        "lipoprotein cholesterol (non-HDL-C) were measured. The non-HDL fraction and "
        "non-HDL-C fell.\n",
    )
    assert not report.findings, found(report)


def test_a_name_used_only_among_the_acknowledgements_is_used(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nRNA sequencing (RNA-seq) libraries were prepared.\n\n"
        "# Acknowledgements\n\nWe thank the RNA-seq core.\n",
    )
    assert not report.findings, found(report)


def test_a_subscript_exempts_the_word_it_follows_and_no_other(project: Path) -> None:
    """`CO` here is not `CO~2~`: the subscript further on belongs to another word."""
    report = written(project, "# Methods\n\nCO was measured in air, and H~2~O in water.\n")
    (message,) = found(report, "abbreviation-undefined")
    assert message.startswith("CO is used once")


def test_a_listed_name_that_holds_an_ordinary_word_is_honoured(project: Path) -> None:
    configured(
        project,
        language={"known_abbreviations": ["EMPEROR-Preserved"]},
        reporting_guideline=["DEMO-OBS", "ROBINS-Exposure"],
    )
    report = written(
        project,
        "# Methods\n\nIn EMPEROR-Preserved, events fell. We followed the ROBINS-Exposure "
        "tool.\n",
    )
    assert not report.findings, found(report)


def test_the_plural_of_a_listed_abbreviation_is_listed(project: Path) -> None:
    """Any final `s`, as for a defined one: an inhibitor class ends in a lower-case `i`."""
    text = "# Methods\n\nPARPis and SGLT2is were used, and one HDACi.\n"
    assert len(found(written(project, text), "abbreviation-undefined")) == 3
    configured(project, language={"known_abbreviations": ["PARPi", "SGLT2i", "HDACi"]})
    assert not written(project, text).findings


def test_a_defined_part_of_a_hyphenated_word_is_a_use(project: Path) -> None:
    """`ROR-PRR` with ROR defined: ROR is used, and PRR is what is missing."""
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. ROR-PRR agreement was "
        "good.\n",
    )
    (message,) = found(report)
    assert message.startswith("PRR is used once")


def test_a_hyphenated_name_is_defined_and_used_whole(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe Middle East respiratory syndrome coronavirus (MERS-CoV) was the "
        "comparator. MERS-CoV reports were fewer.\n",
    )
    assert not report.findings, found(report)


def test_a_definition_in_one_file_serves_the_next(project: Path) -> None:
    """`main.md` is printed first, whatever the other files are called."""
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed.\n",
        **{"1_results": "# Results\n\nThe ROR was raised.\n"},
    )
    assert not report.findings, found(report)


def test_a_supplement_inherits_the_main_text(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe reporting odds ratio (ROR) was computed. The ROR compares groups.\n",
        supplement="# Supplementary methods\n\nThe ROR was recomputed by year.\n",
    )
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "aside",
    [
        "The median was raised (IQR 2.1 to 4.3) in every stratum.",
        "The ROR (see the odds ratio results) was raised.",
        "The estimate was raised (ROR) throughout.",
        "The ROR (calculated as described in the interval methods) was raised.",
    ],
)
def test_a_bracket_that_defines_nothing_is_not_a_definition(project: Path, aside: str) -> None:
    """Read as a definition, each of these would turn `undefined` into `unused` or hide it."""
    report = written(project, f"# Results\n\n{aside}\n")
    assert codes(report) == {"abbreviation-undefined"}, found(report)


def test_the_long_form_is_matched_letter_by_letter() -> None:
    assert _long_form("ROR", "we computed the reporting odds ratio") == "reporting odds ratio"
    assert _long_form("DILI", "cases of drug-induced liver injury") == "drug-induced liver injury"
    assert _long_form("ROR", "the estimate was high") is None
    assert _long_form("ROR", "the ROR") is None, "a short form does not define itself"


# ---------------------------------------------------------------- what must stay quiet


def test_ordinary_prose_has_nothing_to_report(project: Path) -> None:
    report = written(project, f"# Methods\n\n{PLAIN}\n")
    assert not report.findings, found(report)
    assert report.counts["abbreviations_read"] == 0


@pytest.mark.parametrize(
    "sentence",
    [
        "McNemar's test and the DeLong method were used.",
        "Samples were diluted in NaCl by a PhD student.",
        "Patients with type II diabetes in a phase III trial received factor VIII.",
        "DNA was extracted in the USA and the UK.",
        "SARS-CoV-2 and COVID-19 reports were excluded, as were HER2 and CYP3A4 terms.",
        "Reporting follows STROBE and the RECORD-PE extension.",
        "The model is in `ROR_MODEL` and at https://example.org/ROR/API.",
        "As reported [@RORStudyGroup2020], the ratio was raised.",
        "The ratio was {{results.ror.point}} overall.",
        "<!-- ROR to be defined once the Methods are settled -->\n\nThe ratio was raised.",
        "The ratio $ROR = ad/bc$ was computed.",
        "The solution of H2SO4 and NaHCO3 was saturated with CO2, then dried over MgSO4.",
        "CO~2~ and H~2~SO~4~ were bubbled through (NH~4~)~2~SO~4~, with NH~3~ and CH~4~.",
        "The CO\N{SUBSCRIPT TWO} was vented.",
        "Spectra were recorded at 400 MHz and 2 GPa in CDCl3, with 5 MBq of tracer.",
        "The trial is registered as NCT01234567 and the review as CRD42020123456.",
        "Reporting follows TRIPOD for the model and PRISMA for the search.",
        "![The PRR by drug](figures/prr.svg)",
        "![The PRR by drug [@fictionalClassSignal2019]](figures/prr.svg)",
        "![The PRR by drug][prr]\n\n[prr]: figures/prr.svg",
    ],
)
def test_what_is_not_an_abbreviation_is_not_reported(project: Path, sentence: str) -> None:
    report = written(project, f"# Methods\n\n{sentence}\n")
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "sentence",
    [
        "The IC50 was 12 nM.",  # element letters, and a count no formula has
        "The IC~50~ was 12 nM.",  # the same, typeset
        "HSV1 was isolated.",  # nobody writes a count of one
        "KOH was added.",  # a formula with nothing to tell it from an abbreviation
        "HCl was added.",  # the same: no count
        "PCa was diagnosed.",  # prostate cancer, which spells phosphorus and calcium
        "SCr was measured.",  # serum creatinine, which spells sulfur and chromium
        "The ABCDEFGHIJKLMNO score was raised.",  # as long as a short form may be
    ],
)
def test_what_only_looks_exempt_is_still_reported(project: Path, sentence: str) -> None:
    report = written(project, f"# Methods\n\n{sentence}\n")
    assert codes(report) == {"abbreviation-undefined"}, found(report)


def test_a_word_in_capitals_too_long_for_a_short_form_is_not_reported(project: Path) -> None:
    report = written(project, "# Methods\n\nThe ABCDEFGHIJKLMNOP score was raised.\n")
    assert not report.findings, found(report)


def test_an_undefined_abbreviation_is_reported_where_it_is_first_used(project: Path) -> None:
    report = written(
        project,
        "# Methods\n\nThe ROR was computed.\n\nThe ROR compares groups.\n\nA raised ROR is "
        "a signal.\n",
    )
    (finding,) = report.findings
    assert finding.line == 3
    assert "3 times" in finding.message
    assert "in quotes" in finding.hint, "unquoted, YAML reads NO and ON as booleans"


def test_a_project_s_terms_are_names_here_too(project: Path) -> None:
    text = "# Methods\n\nABCB11 expression was raised.\n"
    assert codes(written(project, text)) == {"abbreviation-undefined"}
    configured(project, terms=["ABCB11"])
    assert not written(project, text).findings


def test_a_fenced_listing_is_not_read(project: Path) -> None:
    report = written(
        project, f"# Methods\n\n{PLAIN}\n\n```r\nROR <- (a * d) / (b * c)\n```\n"
    )
    assert not report.findings, found(report)


def test_a_heading_in_capitals_is_not_an_abbreviation(project: Path) -> None:
    report = written(project, f"# METHODS\n\n{PLAIN}\n\nRESULTS\n=======\n\n{PLAIN}\n")
    assert not report.findings, found(report)


@pytest.mark.parametrize(
    "heading",
    [
        "Author contributions",
        "Authors' contributions",
        "Contributors",
        "Acknowledgements",
        "Acknowledgments",
        "Funding",
        "Competing interests",
        "Conflict of interest",
        "Declaration of interests",
        "CRediT authorship contribution statement",
        "Declaration of competing interest",
        "Role of the funding source",
        "Sources of funding",
        "Financial disclosure",
        "Author statement",
    ],
)
def test_initials_and_funders_are_not_abbreviations(project: Path, heading: str) -> None:
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n\n# {heading}\n\nJB and CD analysed the data, funded by "
        "the NIHR and the ANR.\n",
    )
    assert not report.findings, found(report)


def test_a_funder_named_once_with_its_acronym_is_not_unused(project: Path) -> None:
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n\n# Funding\n\nFunded by the Agence Nationale de la "
        "Recherche (ANR).\n",
    )
    assert not report.findings, found(report)


def test_a_file_with_no_heading_continues_the_section_before_it(project: Path) -> None:
    """The build prints the files one after the other, so the funding statement that ends
    `main.md` is still the section when the next file opens without a heading."""
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n\n# Funding\n\nFunded by the ANR.\n",
        **{"2_more": "The NIHR paid for the second year.\n"},
    )
    assert not report.findings, found(report)


def test_a_reference_list_is_not_read(project: Path) -> None:
    report = written(
        project,
        f"# Methods\n\n{PLAIN}\n\n# References\n\n1. Smith J. The ROR in practice. JAMA.\n",
    )
    assert not report.findings, found(report)


def test_a_project_lists_what_it_leaves_undefined(project: Path) -> None:
    text = "# Results\n\nThe median was raised (IQR 2.1 to 4.3) by PCR.\n"
    assert len(found(written(project, text), "abbreviation-undefined")) == 2
    configured(project, language={"known_abbreviations": ["IQR", "PCR"]})
    assert not written(project, text).findings


def test_a_declared_guideline_is_a_name(project: Path) -> None:
    """The project's own guideline is named in its Methods, and is not shipped."""
    text = "# Methods\n\nReporting follows the DEMO-OBS checklist.\n"
    assert not written(project, text).findings


def test_a_known_abbreviation_the_author_defines_is_still_held_to_its_definition(
    project: Path,
) -> None:
    report = written(
        project,
        "# Methods\n\nDNA was extracted.\n\nDeoxyribonucleic acid (DNA) was then stored.\n",
    )
    assert codes(report) == {"abbreviation-used-before-defined"}


@pytest.mark.parametrize(
    "settings",
    [
        {"language": ["CI"]},
        {"language": {"known_abbreviations": "CI"}},
        {"language": {"known_abbreviations": [False, ["CI"], {"a": 1}]}},
        {"terms": 5},
        {"terms": [["a"], {"b": 1}]},
        {"reporting_guideline": [["a"], ["b"]]},
        {"reporting_guideline": [{"a": 1}]},
    ],
)
def test_a_setting_in_the_wrong_shape_does_not_stop_the_gate(
    project: Path, settings: dict
) -> None:
    """The schema reports the setting; G14 still reads the manuscript. A gate that raises
    is a failure, and this one has only warnings to give."""
    configured(project, **settings)
    report = written(project, "# Methods\n\nThe ROR was computed.\n")
    assert codes(report) == {"abbreviation-undefined"}


def test_nothing_here_fails_a_build(project: Path) -> None:
    report = written(
        project,
        "# Abstract\n\nThe ROR was raised.\n\n# Methods\n\nThe PRR was computed. The "
        "reporting odds ratio (ROR) and the reporting odds ratio (ROR) agree.\n",
    )
    assert len(report.findings) >= 3
    assert report.ok, "a reading that can be wrong advises; it does not stop a build"


def test_the_example_is_read_and_says_what_it_finds(project: Path) -> None:
    """Dogfooding. The example leaves `CI` undefined on purpose and says so in paper.yaml.
    Its Introduction uses ROR without defining it, which is a real slip in the example and
    stays one: its review records are tied to the text they read."""
    projekt, _ = load_project(project)
    report = check_language(projekt)
    assert report.ok
    assert [(f.code, f.line) for f in report.findings] == [("abbreviation-undefined", 23)]
    assert "ROR" in report.findings[0].message


# ---------------------------------------------------------------- a whole manuscript

REALISTIC = """---
title: "DILI with ICIs: a WHO VigiBase study"
---

# Abstract

**Background.** Immune checkpoint inhibitors (ICIs) cause drug-induced liver injury (DILI).
**Methods.** We queried VigiBase, the World Health Organization (WHO) pharmacovigilance
database. **Results.** ICIs were associated with DILI (IC025 1.2). **Conclusions.** DILI
reporting was raised.

# Introduction

Immune checkpoint inhibitors (ICIs) targeting programmed cell death protein 1 (PD-1) or its
ligand (PD-L1) have changed oncology [@smith2020]. Drug-induced liver injury (DILI) is a
known immune-related adverse event (irAE). In the KEYNOTE-189 trial, grade III-IV irAEs
occurred in 10% of patients. The FDA and EMA have issued warnings. We used the Medical
Dictionary for Regulatory Activities (MedDRA) and its Standardised MedDRA Queries (SMQs).

# Methods

VigiBase is maintained by the Uppsala Monitoring Centre (UMC). We computed the information
component (IC) and its 95% credibility interval; IC025 is the lower bound. Analyses used R
version 4.3.1 and SAS. Liver tests included ALT, AST and ALP, expressed as multiples of the
upper limit of normal (ULN). Patients with HBV or HCV infection were flagged. A sensitivity
analysis used the reporting odds ratio (ROR). An mAb was defined as a monoclonal antibody
(mAb). T2DM (type 2 diabetes mellitus) was a covariate. We followed STROBE. Time to onset
(TTO) was the delay between first dose and reaction. A P value < 0.05 was significant. In
Table 2, HRs are shown. See Figure S1 and Appendix A. I.V. administration and IV infusion
were pooled. Elderly (aged >= 65 years) patients were analysed separately. The U.S. reports
were compared with EU reports. OR 2.3 (95% CI 1.2-3.4). Non-ICI drugs were the comparator.
anti-PD-1 and anti-CTLA-4 agents were grouped. The Naranjo scale and RUCAM were applied.

# Results

The SMQ retrieved 1200 reports. The irAE was fatal in 5%. TTO was 42 days. ULN multiples
are in Table 2. The ROR agreed with the IC.

# Discussion

AI/ML methods were not used. COVID-19 vaccination did not confound. ICIs remain useful.
In the USA, the NIH funds such work. The UMC had no role. HBV reactivation was rare.

# Author contributions

BC and CD designed the study. SF supervised.

# Funding

Supported by INSERM and the ANR (grant ANR-21-CE17).
"""


def test_a_realistic_manuscript_is_reported_as_design_md_says(project: Path) -> None:
    """The measurement behind "every finding is a warning": 22 findings, 20 of them
    abbreviations a copy-editor would query and two of them names, a trial and a package.
    What the list leaves out matters as much: the title, the surnames and product names,
    the numerals, `P`, `R`, the initials and the funders."""
    report = written(project, REALISTIC)
    # The abbreviations only. The example's `paper.yaml` keeps to "hepatic injury", so this
    # text's "liver injury" is a finding of the other reading, held in test_vocabulary.py.
    reported = sorted(
        (f.code.removeprefix("abbreviation-"), f.message.split()[0])
        for f in report.findings
        if f.code.startswith("abbreviation-")
    )
    assert [f.message for f in report.findings if f.code == "term-avoided"] == [
        "'liver injury' is used 2 times; this paper's term is 'hepatic injury'"
    ]
    assert reported == [
        ("undefined", "AI"),
        ("undefined", "ALP"),
        ("undefined", "ALT"),
        ("undefined", "AST"),
        ("undefined", "EMA"),
        ("undefined", "FDA"),
        ("undefined", "HBV"),
        ("undefined", "HCV"),
        ("undefined", "HR"),
        ("undefined", "IC025"),  # in the abstract
        ("undefined", "IC025"),  # and in the main text
        ("undefined", "KEYNOTE-189"),  # a name, not an abbreviation
        ("undefined", "ML"),
        ("undefined", "NIH"),
        ("undefined", "OR"),
        ("undefined", "RUCAM"),
        ("undefined", "SAS"),  # a name, not an abbreviation
        ("unused", "DILI"),  # in the main text; the abstract uses its own
        ("unused", "PD-L1"),
        ("unused", "T2DM"),
        ("unused", "WHO"),  # in the abstract
        ("used-before-defined", "mAb"),
    ]
    assert report.counts["abbreviations_read"] == 31
    assert report.counts["abbreviations_defined"] == 15


# ---------------------------------------------------------------- reading at any size


def test_unclosed_brackets_are_read_in_linear_time(assert_linear) -> None:
    def brackets(count: int) -> str:
        return "The ratio (ROR was raised " * count

    assert_linear(brackets, _definitions, 2000, "the definition scan, by unclosed bracket")


def test_unclosed_images_are_read_in_linear_time(assert_linear) -> None:
    def images(count: int) -> str:
        return "![" * count

    assert_linear(images, lambda text: _prose(text, []), 2000, "the prose reading, by `![`")


def test_many_findings_are_made_in_linear_time(assert_linear) -> None:
    """One finding for each repeated definition, each with its line and its context: the
    line was counted from the top of the file each time, and the report copied."""
    from manuscript_guard.gates.language import _file, _judge, _Known

    nothing = _Known(frozenset(), frozenset())

    def repeated(count: int) -> list:
        text = "# Methods\n\n" + "The reporting odds ratio (ROR) was raised.\n" * count
        return [_file(0, Path("main.md"), text, [], False)]

    def judge(files: list) -> None:
        report = _judge(files, nothing, Path("."))
        # Each definition after the first is a redefinition, and nothing uses the first.
        assert len(report.findings) == len(files[0].definitions)

    assert_linear(repeated, judge, 500, "the findings, by repeated definition")


def test_a_long_hyphenated_word_is_read_in_linear_time(assert_linear) -> None:
    from manuscript_guard.gates.language import _forms, _Known

    nothing = _Known(frozenset(), frozenset())

    def chained(count: int) -> str:
        return "-".join(["AB"] * count)

    # From 50 parts: reading every stretch of the word whole is cubic, and from 2,000 a
    # return of it would not fail this test but stall it for hours.
    assert_linear(chained, lambda token: _forms(token, set(), nothing), 50, "one word, by hyphen")
