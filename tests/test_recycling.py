"""G7: text the manuscript repeats from its authors' earlier papers.

The earlier paper here is invented, as the example's other sources are, listed in
`literature/related.yaml` as sharing authors with this paper, and stored as a cited work's
source is: `literature/sources/<key>.txt`. Each test writes a passage of it into
the example's manuscript, in one part of the paper, and holds the gate to what the norms for
text recycling say of that part.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.findings import INFO, WARN
from manuscript_guard.gates import check_recycling
from manuscript_guard.gates import recycling as recycling_gate
from manuscript_guard.literature import sources

KEY = "fictionalEarlierAnalysis2020"
#: The example's manuscript written in LaTeX.
TWIN = Path(__file__).parent / "data" / "latex" / "manuscript"

#: Methods of the earlier paper: a standard description, 35 words.
DESCRIPTION = (
    "Disproportionality was measured with the reporting odds ratio, contrasting the odds of "
    "reporting the event of interest for the drug of interest with the odds of reporting it "
    "for all other drugs in the database."
)
#: Its Discussion, 25 words; the earlier paper breaks two of them at the end of a line.
CAVEAT = (
    "Spontaneous reports are subject to under-reporting and to stimulated reporting after "
    "regulatory communications, so a disproportionality signal cannot be read as a measure "
    "of risk."
)
#: Its Results, with numbers this paper does not have.
COUNTED = (
    "A total of 1,234 reports of hepatic injury were retrieved, of which 56 concerned the drug "
    "of interest and were sent by health professionals rather than by patients themselves."
)
#: A sentence whose first eleven words and first twelve are written into the manuscript.
READ_TWICE = (
    "Every narrative was read twice by two pharmacists working apart from each other before "
    "a causality category was agreed."
)

#: The earlier paper's Methods as its page sets them: a line ending inside the description,
#: a reference's number after it, a ligature.
_SET_DESCRIPTION = DESCRIPTION.replace("for all other", "for all\nother").replace(
    "database.", "database.12"
)
#: Its Discussion, two words broken at the end of a line.
_SET_CAVEAT = CAVEAT.replace("under-reporting", "under-\nreporting").replace(
    "disproportionality", "dispro-\nportionality"
)
EARLIER = (
    "Hepatic injury reported with a fictional drug: an earlier analysis\n\nMethods\n\n"
    "The database holds spontaneous reports sent by health professionals and by patients.\n"
    f"{_SET_DESCRIPTION}\n"
    "Con\N{LATIN SMALL LIGATURE FI}dence intervals were computed on the logarithmic scale and\n"
    f"back-transformed. Models were adjusted for age and sex. {READ_TWICE}\n\nResults\n\n"
    f"{COUNTED}\n\nDiscussion\n\n{_SET_CAVEAT}\n"
)


def listed(root: Path, **entry: object) -> Path:
    """The earlier paper in `literature/related.yaml`, as an article of the same authors on
    other data unless `entry` says otherwise."""
    output = {"id": "earlier", "kind": "article", "citekey": KEY, "shares": ["authors"],
              "files_unavailable": "an earlier paper on other data, listed for its text"}
    output.update(entry)
    output = {name: value for name, value in output.items() if value is not None}
    path = root / "literature" / "related.yaml"
    document = {"schema": "manuscript-guard/related/1", "outputs": [output]}
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def stored(root: Path, text: str | bytes = EARLIER, suffix: str = ".txt") -> Path:
    """The earlier paper listed in literature/related.yaml, its copy stored, and its entry in
    the references."""
    listed(root)
    copy = root / "literature" / "sources" / f"{KEY}{suffix}"
    if isinstance(text, bytes):
        copy.write_bytes(text)
    else:
        copy.write_text(text, encoding="utf-8")
    bib = root / "literature" / "references.bib"
    bib.write_text(
        bib.read_text(encoding="utf-8")
        + f"\n@article{{{KEY},\n  title = {{Hepatic injury reported with a fictional drug}},\n"
        "  author = {Fictional, Anne},\n  journal = {Journal of Imaginary Pharmacoepidemiology},\n"
        "  year = {2020},\n  volume = {11},\n  pages = {1--9}\n}\n",
        encoding="utf-8",
    )
    return copy


def written(root: Path, paragraph: str, *, before: str) -> int:
    """`paragraph` written into the manuscript at the end of the section before the heading
    `before`; the line it starts on."""
    path = root / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    marker = f"\n# {before}\n"
    assert text.count(marker) == 1, before
    at = text.index(marker)
    path.write_text(text[:at] + f"\n{paragraph}\n" + text[at:], encoding="utf-8")
    return text.count("\n", 0, at) + 2


def found(root: Path, stage: str = "drafting") -> list:
    project, _ = load_project(root)
    return list(check_recycling(project, stage).findings)


def said(root: Path, stage: str = "drafting") -> list[tuple[str, str, int | None]]:
    return [(f.code, f.severity, f.line) for f in found(root, stage)]


# ----------------------------------------------------------------------------- the norms


def test_a_standard_description_cited_in_the_methods_is_a_note_at_every_stage(
    project: Path,
) -> None:
    stored(project)
    line = written(project, f"{DESCRIPTION[:-1]}, as before [@{KEY}].", before="Results")
    for stage in ("drafting", "internal-review", "submission"):
        assert said(project, stage) == [("recycled-methods-cited", INFO, line)], stage
    (finding,) = found(project)
    assert "repeat 35 words of @" + KEY in finding.message
    assert "the Methods, which cite it there" in finding.message
    assert "covering letter" in finding.hint


def test_a_description_in_the_methods_that_does_not_cite_its_paper_warns_from_internal_review(
    project: Path,
) -> None:
    stored(project)
    line = written(project, DESCRIPTION, before="Results")
    assert said(project, "drafting") == [("recycled-text", INFO, line)]
    assert said(project, "internal-review") == [("recycled-text", WARN, line)]
    assert said(project, "submission") == [("recycled-text", WARN, line)]
    (finding,) = found(project, "submission")
    assert "in the Methods" in finding.message
    assert f"cite @{KEY} in this paragraph" in finding.hint


@pytest.mark.parametrize(
    ("written_as", "said_of_it"),
    [
        pytest.param(f"# Supplementary methods\n\n{DESCRIPTION} As before [@{KEY}].",
                     ("recycled-methods-cited", INFO, "in the Methods"),
                     id="cited Supplementary Methods"),
        pytest.param(f"# Supplementary Methods\n\n## S1. Data source\n\n{DESCRIPTION}",
                     ("recycled-text", WARN, "in the Methods"), id="uncited Supplementary Methods"),
        pytest.param(f"# Supplementary discussion\n\n{CAVEAT}",
                     ("recycled-text", WARN, "in the Discussion"),
                     id="a supplementary discussion"),
        pytest.param(f"# eResults\n\n{COUNTED}", ("recycled-text", WARN, "in the Results"),
                     id="JAMA's eResults"),
        pytest.param(f"# eResults 1\n\n{COUNTED}", ("recycled-text", WARN, "in the Results"),
                     id="numbered"),
        pytest.param(f"# Supplementary Results and Discussion\n\n{COUNTED}",
                     ("recycled-text", WARN, "in the Results"), id="two parts"),
        pytest.param(f"# Supplementary findings\n\n{COUNTED}",
                     ("recycled-text", WARN, "in the Results"), id="findings"),
    ],
)  # fmt: skip
def test_the_supplement_is_held_to_the_norms_the_main_text_is(
    project: Path, written_as: str, said_of_it: tuple[str, str, str]
) -> None:
    """Basile, 2026-10-21: the supplement is held to the rules of the main text. Its
    Methods are the Methods, a description reused with its source cited there is a note,
    and one that does not cite it warns from internal-review, as in the main text; its
    Discussion and its Results are the Discussion and the Results, by whatever prefix a
    supplement gives them (round 7 of the review: they named no part)."""
    stored(project)
    path = project / "manuscript" / "supplementary" / "S2_recycled.md"
    path.write_text(written_as + "\n", encoding="utf-8")
    (finding,) = found(project, "internal-review")
    code, severity, part = said_of_it
    assert (finding.code, finding.severity) == (code, severity)
    assert part in finding.message
    assert finding.path.name == "S2_recycled.md"
    assert finding.line == written_as.count("\n") + 1  # the passage is the file's last line


def _as_latex(root: Path) -> Path:
    """The example's manuscript as its LaTeX twin; the entry file."""
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    return root / "manuscript" / "main.tex"


def _typed_before(entry: Path, heading: str, typed: str) -> int:
    """`typed` written into `entry` before the heading; the line it starts on."""
    text = entry.read_text(encoding="utf-8")
    at = text.index(heading)
    entry.write_text(text[:at] + typed + "\n\n" + text[at:], encoding="utf-8")
    return text.count("\n", 0, at) + 1


def test_a_latex_manuscript_is_compared_as_it_prints_and_placed_at_its_file(
    project: Path,
) -> None:
    """Step 13: G7 reads a LaTeX manuscript's documents as they print, by their parts, and
    names each passage at the `.tex` file and the lines it is typed on: a file the entry
    inputs, and the entry itself past a comment, where the passage's first line is not the
    view's."""
    stored(project)
    entry = _as_latex(project)
    (entry.parent / "reused.tex").write_text(f"{DESCRIPTION}\n", encoding="utf-8")
    _typed_before(entry, "\\section{Results}", "\\input{reused}")
    broken = CAVEAT.replace("so a ", "so a\n")
    line = _typed_before(entry, "\\section{Data availability}", f"% from before\n{broken}") + 1
    found_ = sorted(found(project, "internal-review"), key=lambda f: f.path.name)
    assert [(f.code, f.severity, f.path.name, f.line) for f in found_] == [
        ("recycled-text", WARN, "main.tex", line),
        ("recycled-text", WARN, "reused.tex", 1),
    ]
    assert "in the Discussion" in found_[0].message and f"lines {line}-{line + 1}" in (
        found_[0].message
    )
    assert "in the Methods" in found_[1].message


def test_a_latex_caption_is_compared_at_its_line(project: Path) -> None:
    """Round 1 of step 13: a float's caption is read as Markdown's legend is, where the view
    the word counts read leaves it out."""
    stored(project)
    entry = _as_latex(project)
    line = _typed_before(entry, "\\section{Discussion}",
                         "\\begin{figure}\n\\caption{" + CAVEAT + "}\n\\end{figure}") + 1
    assert said(project, "internal-review") == [("recycled-text", WARN, line)]


@pytest.mark.parametrize(
    "typed",
    [
        "As \\enquote{" + DESCRIPTION[:-1] + "} \\cite{" + KEY + "}.",
        "\\begin{quote}\n" + DESCRIPTION + "\n\\end{quote}",
        "\\begin{quotation}\n" + DESCRIPTION + " \\cite{" + KEY + "}\n\\end{quotation}",
        # Round 2: csquotes' other forms, and a quotation inside another.
        "\\blockquote{" + DESCRIPTION + "}",
        "\\textquote[{" + KEY + "}][.]{" + DESCRIPTION[:-1] + "}",
        "\\textcquote[12]{" + KEY + "}[.]{" + DESCRIPTION[:-1] + "}",
        "\\foreignblockquote{english}[x]{" + DESCRIPTION + "}",
        "\\enquote{He wrote \\enquote{this} and: " + DESCRIPTION[:-1] + "}.",
        "\\enquote{From \\url{https://ex.org/a%20b}: " + DESCRIPTION[:-1] + "}.",
        # Round 3: an option with a `]` in braces, and a comment that wraps the arguments.
        "\\textquote[{\\cite[p.~3]{" + KEY + "}}][.]{" + DESCRIPTION[:-1] + "}",
        "\\textcquote[12]{" + KEY + "}%\n{" + DESCRIPTION[:-1] + "}",
    ],
)
def test_a_quotation_latex_marks_with_a_command_is_a_quotation(project: Path, typed: str) -> None:
    """Round 1 of step 13: `\\enquote{}` and a quotation environment quote, as Markdown's
    quotation marks and `>` do."""
    stored(project)
    entry = _as_latex(project)
    _typed_before(entry, "\\section{Results}", typed)
    assert [code for code, _severity, _line in said(project, "submission")] == [
        "recycled-quotation"
    ]


def test_a_passage_running_into_a_quotation_shows_no_mark_of_it(project: Path) -> None:
    """Round 2 of step 13: the characters that mark a quotation in the view are no text."""
    stored(project)
    entry = _as_latex(project)
    words = DESCRIPTION.split()
    _typed_before(entry, "\\section{Results}", " ".join(words[:20]) + " \\enquote{"
                  + " ".join(words[20:]) + "}")  # fmt: skip
    [finding] = found(project, "submission")
    assert "\\ue00" not in finding.message and "\ue001" not in finding.message


def test_an_empty_listing_after_an_unclosed_quotation_ends_the_reading() -> None:
    """Round 4 of step 13: an empty listing in the spans a scan passes over stopped the scan
    where it stood, and `check` did not end."""
    from manuscript_guard.text.latex import mask, printed, structure

    text = ("\\documentclass{article}\n\\begin{document}\n% \\enquote{\n"
            "\\begin{verbatim}\\end{verbatim}\nWords.\n\\end{document}\n")  # fmt: skip
    source = structure.Source("main.tex", text, mask.read(text))
    assert "Words." in printed.printed([source], compared=True).text


def test_a_brace_in_code_does_not_close_a_quotation(project: Path) -> None:
    """Round 3 of step 13: `\\verb|{|` prints a brace, and opens no group, so the quotation
    ends where its own brace does and the paragraph after it is not quoted."""
    stored(project)
    entry = _as_latex(project)
    line = _typed_before(entry, "\\section{Results}", "\\blockquote{type \\verb|{| to open}\n\n"
                         + DESCRIPTION + " \\emph{x}") + 2  # fmt: skip
    assert said(project, "internal-review") == [("recycled-text", WARN, line)]


def test_a_subfigure_s_caption_and_one_with_an_address_are_compared(project: Path) -> None:
    """Round 2 of step 13: `\\subcaption`, and a `%` an address holds, which ends no group."""
    stored(project)
    entry = _as_latex(project)
    line = _typed_before(entry, "\\section{Discussion}",
                         "\\begin{figure}\n\\subcaption{" + CAVEAT + "}\n\\end{figure}") + 1
    second = _typed_before(entry, "\\section{Data availability}",
                           "\\begin{figure}\n\\caption{See \\url{https://ex.org/a%20b}. "
                           + DESCRIPTION + "}\n\\end{figure}") + 1  # fmt: skip
    assert sorted(said(project, "internal-review")) == [
        ("recycled-text", WARN, line), ("recycled-text", WARN, second)
    ]


def test_a_latex_file_nothing_inputs_is_compared_on_its_own(project: Path) -> None:
    """Round 1 of step 13: a supplement with no `main.tex` is files nothing inputs, which G2
    reads on their own, and so does G7."""
    stored(project)
    _as_latex(project)
    folder = project / "manuscript" / "supplementary"
    shutil.rmtree(folder)
    folder.mkdir()
    (folder / "methods.tex").write_text(f"Words first.\n\n{DESCRIPTION}\n", encoding="utf-8")
    [finding] = found(project, "internal-review")
    assert (finding.code, finding.path, finding.line) == (
        "recycled-text", folder / "methods.tex", 3
    )


def test_a_latex_description_that_cites_its_paper_is_a_note(project: Path) -> None:
    """A `\\cite` is the citation G7 reads, as `[@key]` is in Markdown (step 13)."""
    stored(project)
    entry = _as_latex(project)
    line = _typed_before(entry, "\\section{Results}", f"{DESCRIPTION[:-1]}, as before "
                         f"\\cite{{{KEY}}}.")  # fmt: skip
    assert said(project, "submission") == [("recycled-methods-cited", INFO, line)]


def test_a_heading_that_only_opens_like_a_supplement_s_part_names_none() -> None:
    """Round 8 of the review: "Online discussion forums" under the Methods was read as the
    Discussion, which unnamed the Methods, and a cited description warned."""
    text = (
        f"## Methods\n\n### Data source\n\n{DESCRIPTION} As before [@{KEY}].\n\n"
        f"### Online discussion forums\n\nWords.\n\n### Online consent\n\n{CAVEAT}\n\n"
        "### Statistical methods\n\nWords.\n"
    )
    found = [(p.kind, p.cited) for p in recycling_gate.recycled_in(text, EARLIER, KEY)]
    assert found == [("methods", True), ("methods", False)]


def test_a_citation_in_another_paragraph_does_not_cite_the_passage(project: Path) -> None:
    """The norms ask for the citation where the words are reused: the paragraph."""
    stored(project)
    line = written(project, f"As before [@{KEY}].\n\n{DESCRIPTION}", before="Results")
    assert said(project, "submission") == [("recycled-text", WARN, line + 2)]


def test_a_sentence_of_the_discussion_warns_whether_it_cites_its_paper_or_not(
    project: Path,
) -> None:
    """COPE: overlap in the discussion is unlikely to be acceptable, cited or not."""
    stored(project)
    line = written(project, f"{CAVEAT} [@{KEY}]", before="Data availability")
    assert said(project, "internal-review") == [("recycled-text", WARN, line)]
    (finding,) = found(project, "internal-review")
    assert "repeat 25 words" in finding.message
    assert "in the Discussion" in finding.message
    assert f"line {EARLIER.count(chr(10), 0, EARLIER.index('Spontaneous')) + 1} of {KEY}.txt" in (
        finding.message
    )
    assert "write it afresh" in finding.hint


def test_results_written_again_with_new_numbers_are_still_the_same_words(project: Path) -> None:
    """A number is no word, so the sentence is found with this paper's numbers in it."""
    stored(project)
    sentence = COUNTED.replace("1,234", "2,048").replace("56", "77")
    line = written(project, sentence, before="Discussion")
    assert said(project, "internal-review") == [("recycled-text", WARN, line)]
    assert "in the Results" in found(project)[0].message


def test_a_word_changed_does_not_hide_the_sentence_it_is_in(project: Path) -> None:
    """TRRP: a synonym put in to disguise recycled text is no rewriting."""
    stored(project)
    sentence = CAVEAT.replace("stimulated", "prompted")
    written(project, sentence, before="Data availability")
    (finding,) = found(project, "internal-review")
    assert finding.code == "recycled-text" and "repeat 24 words" in finding.message


def test_a_quotation_of_the_earlier_paper_is_shown_apart(project: Path) -> None:
    stored(project)
    quoted = f'We wrote then that "{CAVEAT[:-1]}" [@{KEY}].'
    line = written(project, quoted, before="Data availability")
    assert said(project, "submission") == [("recycled-quotation", INFO, line)]


def test_a_quotation_and_a_recycled_sentence_on_one_line_are_two_passages(project: Path) -> None:
    """Round 1 of the review: passages were told apart by their lines, and the sentence
    after the quotation on the same line was lost."""
    stored(project)
    line = written(project, f'We wrote that "{CAVEAT[:-1]}" [@{KEY}]. Here, too, {READ_TWICE}',
                   before="Data availability")  # fmt: skip
    assert said(project, "submission") == [
        ("recycled-quotation", INFO, line), ("recycled-text", WARN, line)
    ]


def test_twelve_words_are_reported_and_eleven_are_not(project: Path) -> None:
    stored(project)
    words = READ_TWICE.split()
    eleven, twelve = " ".join(words[:11]), " ".join(words[:12])
    written(project, f"Unlike then, {eleven} on the same day.", before="Data availability")
    assert said(project) == []
    line = written(project, f"Unlike then, {twelve} on the same day.", before="Data availability")
    assert said(project) == [("recycled-text", INFO, line)]


def test_a_common_phrase_is_not_recycled_text(project: Path) -> None:
    """"Adjusted for age and sex" is in both, and in most papers."""
    stored(project)
    written(project, "Estimates were adjusted for age and sex throughout.", before="Results")
    assert said(project, "submission") == []


def test_the_example_shares_no_passage_with_the_earlier_paper(project: Path) -> None:
    stored(project)
    project_, _ = load_project(project)
    report = check_recycling(project_, "submission")
    assert report.findings == ()
    assert report.counts == {"earlier_outputs_compared": 1, "recycled_passages": 0}


# ---------------------------------------------------------------- what is not compared


@pytest.mark.parametrize(
    ("written_as", "before"),
    [
        pytest.param(f"## {CAVEAT}", "Data availability", id="a heading"),
        pytest.param(f"```\n{CAVEAT}\n```", "Data availability", id="a listing"),
        pytest.param(f"<!-- {CAVEAT} -->", "Data availability", id="a comment"),
        pytest.param(f"| {CAVEAT} |\n|---|", "Data availability", id="a table"),
        pytest.param(f"# References\n\n1. {CAVEAT}", "Funding", id="the reference list"),
    ],
)
def test_what_a_similarity_check_is_not_asked_about_is_not_compared(
    project: Path, written_as: str, before: str
) -> None:
    stored(project)
    written(project, written_as, before=before)
    assert said(project, "submission") == []


@pytest.mark.parametrize(
    ("heading", "before"),
    [
        pytest.param("## Ethics approval", "Results", id="ethics, under the Methods"),
        pytest.param("## Patient and public involvement", "Results",
                     id="patient involvement, under the Methods (BMJ)"),
        pytest.param("# Role of the funding source", "Competing interests", id="the Lancet's"),
        pytest.param("# CRediT authorship contribution statement", "Competing interests",
                     id="Elsevier's"),
        pytest.param("# Transparency", "Competing interests", id="the BMJ's"),
        pytest.param("# CRediT author statement", "Competing interests",
                     id="the one the submission pack writes"),
        pytest.param("## Funding", "Data availability", id="under the Discussion"),
        pytest.param("## Funding", "Introduction", id="under the abstract"),
        pytest.param("## Ethics approval and consent to participate", "Results",
                     id="BMC's, under the Methods"),
        pytest.param("# Funding", "Competing interests", id="at the end"),
        pytest.param("# Declaration of generative AI and AI-assisted technologies in the "
                     "writing process", "Competing interests", id="Elsevier's on AI"),
        pytest.param("# Availability of data and material", "Competing interests",
                     id="Springer's"),
        pytest.param("# Conflicts of interest/Competing interests", "Data availability",
                     id="two names and a slash"),
        pytest.param("# Funding/Support", "Competing interests", id="JAMA's funding"),
        pytest.param("# Role of the Funder/Sponsor", "Competing interests", id="JAMA's funder"),
        pytest.param("# Conflict of Interest Disclosures", "Data availability", id="JAMA's"),
        pytest.param("# Disclosure of interest", "Data availability", id="a disclosure"),
        pytest.param("# Ethical statement", "Competing interests", id="an ethical statement"),
        pytest.param("# Funding, competing interests, and data availability",
                     "Competing interests", id="a serial comma"),
        pytest.param("# Acknowledgements[^1]", "Competing interests", id="a footnote's mark"),
        pytest.param("# Statements and Declarations", "Competing interests", id="Springer's"),
        pytest.param("# Additional Contributions", "Competing interests", id="JAMA's thanks"),
        pytest.param("# Article Information", "Competing interests", id="JAMA's back matter"),
    ],
)  # fmt: skip
def test_a_statement_is_compared_and_noted_wherever_its_heading_stands(
    project: Path, heading: str, before: str
) -> None:
    """Basile, 2026-10-21, after four rounds of the review: a statement's words, the same as
    in the earlier paper, are compared and noted, never warned of and never set apart. Read
    as the Methods', "Ethics approval" warned (round 1); set apart, a heading read wrong hid
    recycled text (rounds 2 to 4)."""
    stored(project)
    line = written(project, f"{heading}\n\n{CAVEAT}", before=before)
    for stage in ("drafting", "submission"):
        assert said(project, stage) == [("recycled-statement", INFO, line + 2)]


def test_a_title_that_opens_with_a_statement_s_word_is_the_paper_s_own_matter() -> None:
    """Round 3 of the review: a commentary titled "Data sharing in pharmacovigilance", over
    an Introduction and parts no heading names, was set apart whole."""
    text = (
        "# Data sharing in pharmacovigilance\n\n## Introduction\n\n"
        f"{CAVEAT}\n\n## Current practice\n\nWords.\n\n## Funding\n\nNone.\n"
    )
    (found,) = recycling_gate.recycled_in(text, EARLIER, KEY)
    assert (found.kind, found.first_line, found.shared) == ("introduction", 5, 25)


def test_a_title_named_as_one_part_over_others_names_none() -> None:
    """A title named "Background" over a Background, the Methods and the Results names none
    of them."""
    text = (
        "# Background rates of liver injury\n\n## Background\n\nWords.\n\n## Methods\n\n"
        f"Words.\n\n## Results\n\n{CAVEAT}\n"
    )
    (found,) = recycling_gate.recycled_in(text, EARLIER, KEY)
    assert found.kind == "results"


def test_the_discussion_over_its_interpretation_and_conclusions_is_the_discussion() -> None:
    """Round 4 of the review: the Discussion over "Interpretation" and "Conclusions" was
    taken for a title over two parts, and a passage under "Principal findings" was told it
    stood under no heading, with the Introduction's advice."""
    text = (
        f"# Discussion\n\n## Principal findings\n\n{CAVEAT}\n\n## Interpretation\n\nWords.\n\n"
        "## Conclusions\n\nWords.\n"
    )
    (found,) = recycling_gate.recycled_in(text, EARLIER, KEY)
    assert found.kind == "discussion"


@pytest.mark.parametrize(
    "heading",
    ["## Funding sources of the included trials", "## Data sharing", "## Consent"],
)
def test_a_heading_of_the_results_is_the_results_whatever_it_is_called(
    project: Path, heading: str
) -> None:
    """Rounds 2 and 4 of the review: a theme of the Results named with a statement's words,
    in a review of trials or a qualitative study, was set apart, and recycled Results went
    unreported. Under the Results it is the Results."""
    stored(project)
    line = written(project, f"{heading}\n\n{CAVEAT}", before="Discussion")
    assert said(project, "submission") == [("recycled-text", WARN, line + 2)]


def test_the_methods_with_a_statement_and_statistical_methods_are_the_methods(
    project: Path,
) -> None:
    """Round 2 of the review: a statement's heading counted as a part of the paper, so the
    Methods over it and over "Statistical methods" were taken for a title over the paper,
    and a cited description under them warned as under no heading."""
    stored(project)
    line = written(
        project,
        f"## Study population\n\n{DESCRIPTION} As before [@{KEY}].\n\n"
        "## Statistical methods\n\nA model was fitted.\n\n## Ethics approval\n\nIt was approved.",
        before="Results",
    )
    assert said(project, "submission") == [("recycled-methods-cited", INFO, line + 2)]


def test_a_title_over_the_paper_names_no_part_of_it(project: Path) -> None:
    """A heading over the Methods and the Results is the paper's title: the sentence under
    its Discussion is in the Discussion, not in a "Background" it opens with."""
    stored(project)
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    text = "# Background rates of hepatic injury\n\n" + text.replace("\n# ", "\n## ")
    under = text.replace("\n## Data availability\n", f"\n{CAVEAT}\n\n## Data availability\n")
    path.write_text(under, encoding="utf-8")
    (finding,) = found(project)
    assert "in the Discussion" in finding.message


# -------------------------------------------------------------- the copy and its reading


def test_an_earlier_output_with_no_stored_copy_is_said_not_to_be_compared(project: Path) -> None:
    stored(project).unlink()
    (finding,) = found(project)
    assert (finding.code, finding.severity) == ("earlier-output-not-compared", INFO)
    assert f"earlier ({KEY})" in finding.message and "sent nowhere" in finding.hint


def test_a_project_that_declares_no_earlier_output_reads_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(_path: Path) -> str:
        raise AssertionError("read a copy")

    monkeypatch.setattr(recycling_gate, "read_in_reading_order", never)
    project_, _ = load_project(project)
    report = check_recycling(project_, "submission")
    assert report.findings == () and report.counts == {}


def test_an_earlier_output_with_no_citation_key_is_said_not_to_be_compared(
    project: Path,
) -> None:
    stored(project)
    path = listed(project, citekey=None, title="An abstract at a meeting, 2019")
    (finding,) = found(project)
    assert (finding.code, finding.path, finding.line) == ("earlier-output-not-compared", path, 3)
    assert "no citation key" in finding.message


def test_an_output_of_other_authors_is_not_compared(project: Path) -> None:
    """Text recycling is the reuse of one's own words: an output of the same data by other
    authors is G8's to hold to its numbers, and not this check's."""
    stored(project)
    listed(project, shares=["data"], files_unavailable=None)
    written(project, CAVEAT, before="Data availability")
    project_, _ = load_project(project)
    report = check_recycling(project_, "submission")
    assert report.findings == () and report.counts == {}


@pytest.mark.parametrize("kind", ["preprint", "abstract", "protocol"])
def test_an_earlier_version_of_this_study_is_one_note_however_much_is_repeated(
    project: Path, kind: str
) -> None:
    """Basile, 2026-10-21: reuse of one's own preprint or abstract is accepted where it is
    disclosed (TRRP), so it is one note for the output, never a warning per passage."""
    stored(project)
    path = listed(project, kind=kind, shares=["data", "study", "authors"])
    first = written(project, DESCRIPTION, before="Results")
    written(project, CAVEAT, before="Data availability")
    for stage in ("drafting", "submission"):
        (finding,) = found(project, stage)
        assert (finding.code, finding.severity) == ("recycled-earlier-version", INFO)
        assert (finding.path, finding.line) == (path, 3)
        assert f"2 passages, 60 words in all, repeat the {kind} @{KEY}" in finding.message
        assert f"the first at main.md:{first} (line " in finding.message
        assert "covering letter" in finding.hint
    project_, _ = load_project(project)
    assert check_recycling(project_).counts["recycled_passages"] == 2


def test_the_journal_s_policy_is_given_with_each_passage(project: Path) -> None:
    stored(project)
    written(project, CAVEAT, before="Data availability")
    policy = "Text from the authors' earlier work may be reused only in the Methods."
    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["text_recycling"] = "Methods only"
    document.setdefault("quotes", {})["text_recycling"] = policy
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    (finding,) = found(project)
    assert policy in finding.hint


def test_a_page_of_html_loses_its_tags_and_keeps_its_lines(tmp_path: Path) -> None:
    page = tmp_path / "paper.html"
    page.write_text("<p>One\n<b\n>two</b> &amp; three</p>\n<script>\nx\n</script>four",
                    encoding="utf-8")  # fmt: skip
    read = sources.read_in_reading_order(page)
    assert read.split() == ["One", "two", "&", "three", "four"]
    assert read.count("\n") == page.read_text(encoding="utf-8").count("\n")


def _pdftotext_writing(monkeypatch: pytest.MonkeyPatch, output: str) -> list[list[str]]:
    """A program that writes `output` where pdftotext would run; the commands asked for."""
    real_run = subprocess.run
    child = [sys.executable, "-c", f"import sys; sys.stdout.buffer.write({output.encode()!r})"]
    commands: list[list[str]] = []

    def run(command, **options):
        commands.append([str(part) for part in command])
        return real_run(child, **options)

    monkeypatch.setattr(sources.shutil, "which", lambda name: name)
    monkeypatch.setattr(sources.subprocess, "run", run)
    return commands


def test_a_pdf_is_read_in_reading_order_and_a_passage_is_found_on_its_page(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored(project, b"%PDF-1.4 not read here", suffix=".pdf")
    commands = _pdftotext_writing(monkeypatch, f"Title\n\fMethods\n\f{CAVEAT}\n\f")
    written(project, CAVEAT, before="Data availability")
    (finding,) = found(project)
    assert f"page 3 of {KEY}.pdf" in finding.message
    assert commands and "-layout" not in commands[0]


def test_an_unreadable_copy_is_said_not_to_be_compared_with_why(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored(project, b"%PDF-1.4 not read here", suffix=".pdf")
    monkeypatch.setattr(sources.shutil, "which", lambda name: None)
    monkeypatch.setitem(sys.modules, "pypdf", None)
    (finding,) = found(project)
    assert finding.code == "earlier-output-not-compared"
    assert "cannot read PDFs" in finding.message


def _two_columns(left: str, right: str) -> bytes:
    """A PDF of one page set in two columns, a few words to the line, left then right."""

    def column(x: int, text: str) -> bytes:
        words, lines = text.split(), []
        while words:
            lines.append(" ".join(words[:5]))
            words = words[5:]
        shown = b" ".join(b"(" + line.encode("latin-1") + b") Tj 0 -14 Td" for line in lines)
        return b"BT /F1 10 Tf %d 720 Td 14 TL " % x + shown + b" ET"

    stream = column(60, left) + b"\n" + column(320, right)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    body, offsets = b"%PDF-1.4\n", []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + content + b"\nendobj\n"
    table = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    return body + b"startxref\n%d\n%%%%EOF\n" % table


@pytest.mark.skipif(
    not shutil.which("pdftotext") and importlib.util.find_spec("pypdf") is None,
    reason="neither pdftotext nor pypdf is installed",
)
def test_a_sentence_of_one_column_is_found_beside_another_column(project: Path) -> None:
    """Laid out, each line of the page holds a line of each column, and the Discussion's
    sentence in the right-hand column is cut every five words."""
    left = "Nothing in this column of the earlier paper is in the manuscript at all, not a word"
    stored(project, _two_columns(left, CAVEAT), suffix=".pdf")
    written(project, CAVEAT, before="Data availability")
    (finding,) = found(project)
    assert finding.code == "recycled-text" and "repeat 25 words" in finding.message
    assert f"page 1 of {KEY}.pdf" in finding.message
