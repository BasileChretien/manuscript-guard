"""`audit` reads a flow printed as a nested list and holds it to its arithmetic, and holds the
Abstract to what the paper reports (Task 3, part 3).

A flow is read from a list's shape alone: its stages at the top, the exclusions of each step
under a stage, the reasons an exclusion totals under it, and the arms under the last stage,
each item giving one count. Markdown, LaTeX and Word lists are read alike. The Abstract's
numbers are looked for in the Methods, the Results, the tables and a supplement, and an
interval or a test that differs from its one counterpart there in a single number fails.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.audit import audit
from manuscript_guard.auditing.abstract import agree, coarser
from manuscript_guard.cli import main
from manuscript_guard.stats.flows import counts_in, flows_in, latex_lists, markdown_lists
from manuscript_guard.text.docx import read_docx_text
from manuscript_guard.text.latex.structure import read_tree
from manuscript_guard.text.masking import mask

BS = chr(92)
NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

FLOW = """\
- Assessed for eligibility (n = 412)
  - Excluded (n = 112)
    - Not meeting inclusion criteria (n = 87)
    - Declined to participate (n = 25)
- Randomised (n = 300)
  - Drug (n = 151)
  - Placebo (n = 149)
"""


def _flows(text: str):
    return flows_in(markdown_lists(text, mask(text)))


# --------------------------------------------------------------------------------- flows


def test_a_flow_that_adds_up_is_read_and_says_nothing() -> None:
    [flow] = _flows("Text.\n\n" + FLOW)
    assert flow.read and flow.problems == () and flow.notes == ()
    assert (flow.stages, flow.exclusions, flow.arms) == ((412, 300), ((112,),), (151, 149))
    assert flow.line == 3


@pytest.mark.parametrize(
    ("changed", "said"),
    [
        ("Randomised (n = 300)",
         "stage 1 (412) less its exclusions (112) is 300, and stage 2 is 290"),
        ("Placebo (n = 149)", "the arms sum to 299, and the last stage is 300"),
        ("Declined to participate (n = 25)",
         "the reasons under 'Excluded' (n = 112) add up to 107"),
    ],
)
def test_a_flow_whose_arithmetic_does_not_hold_is_said(changed: str, said: str) -> None:
    wrong = {"Randomised (n = 300)": "Randomised (n = 290)",
             "Placebo (n = 149)": "Placebo (n = 148)",
             "Declined to participate (n = 25)": "Declined to participate (n = 20)"}[changed]
    [flow] = _flows(FLOW.replace(changed, wrong))
    assert flow.problems == (said,)


def test_exclusions_over_what_a_step_removes_are_read_as_overlapping() -> None:
    """More reasons than records removed is one record excluded for several: a note, and
    the step holds; a single reason over the step cannot be, even overlapping."""
    [flow] = _flows(FLOW.replace("(n = 112)", "(n = 80)"))
    assert flow.problems == ("stage 1 (412) less its exclusions (80) is 332, and stage 2 is 300",
                             "the reasons under 'Excluded' (n = 80) cannot account for it, "
                             "even overlapping: one of them is 87")  # fmt: skip
    overlapping = FLOW.replace("Declined to participate (n = 25)", "Declined (n = 40)")
    [flow] = _flows(overlapping)
    assert flow.problems == ()
    assert flow.notes == ("the reasons under 'Excluded' (n = 112) add up to 127: read as "
                          "overlapping",)  # fmt: skip
    many = "- A (n = 100)\n  - X (n = 30)\n  - Y (n = 30)\n- B (n = 50)\n"
    [flow] = _flows(many)
    assert flow.problems == () and "read as overlapping" in flow.notes[0]
    [flow] = _flows(many.replace("Y (n = 30)", "Y (n = 60)"))
    assert flow.problems == ("the reasons after stage 1 (30, 60) cannot account for the 50 "
                             "excluded, even overlapping",)  # fmt: skip


def test_a_list_whose_items_do_not_each_give_one_count_is_noted_and_not_read() -> None:
    for partial in (FLOW.replace(" (n = 25)", ""), FLOW.replace("(n = 25)", "(n = 25, n = 3)")):
        [flow] = _flows(partial)
        assert not flow.read and flow.problems == ()
        assert "line 4 gives" in flow.notes[0]


def test_what_is_no_flow_is_not_read() -> None:
    """One level, one stage, no counts, a list in a fenced listing, and prose."""
    for text in ("- A (n = 3)\n- B (n = 2)\n", "- A (n = 3)\n  - B (n = 1)\n",
                 "- Stage\n  - Reason\n- Next\n", "```\n" + FLOW + "```\n",
                 "Of 412 assessed (n = 412), 112 were excluded (n = 112).\n"):
        assert _flows(text) == [], text


def test_two_lists_apart_are_two_flows() -> None:
    text = FLOW + "\nA paragraph between them.\n\n" + FLOW.replace("149", "148")
    first, second = _flows(text)
    assert first.problems == () and second.problems != ()


def test_counts_are_read_as_a_flow_prints_them() -> None:
    assert counts_in("Randomised (n = 1,204)") == [1204]
    assert counts_in("N=12; n = 3") == [12, 3]
    assert counts_in("n = 45%, n = 4.5, sn = 3, n = 1,2345") == []


def test_items_under_an_arm_are_said_and_not_read() -> None:
    text = FLOW.replace("  - Drug (n = 151)\n", "  - Drug (n = 151)\n    - Lost (n = 4)\n")
    [flow] = _flows(text)
    assert flow.problems == ()
    assert flow.notes == ("the items under an arm are not read: a step for each arm is not "
                          "read",)  # fmt: skip


def test_a_latex_flow_is_read_from_its_nested_itemize() -> None:
    source = read_tree({"paper.tex": tex(
        "!documentclass{article}\n!begin{document}\n"
        "!begin{itemize}\n  !item Assessed (n = 412) % !item Skipped (n = 9)\n"
        "  !begin{enumerate}\n    !item Excluded (n = 112)\n  !end{enumerate}\n"
        "  !item Randomised (n = 290)\n!end{itemize}\n!end{document}\n")}, "paper.tex").sources[0]
    from manuscript_guard.text.latex.views import bindings, markdown_view

    hidden = markdown_view(source, bindings(source)[0], blank="\x00")
    [flow] = flows_in(latex_lists(source, hidden))
    assert flow.stages == (412, 290) and flow.line == 4
    assert flow.problems == ("stage 1 (412) less its exclusions (112) is 300, and stage 2 is "
                             "290",)  # fmt: skip


def tex(text: str) -> str:
    return text.replace("!", BS)


# --------------------------------------------------------------------------------- Word

NUMBERING = (
    f"<w:numbering {NS}><w:abstractNum w:abstractNumId='0'>"
    + "".join(f"<w:lvl w:ilvl='{n}'><w:numFmt w:val='bullet'/><w:lvlText w:val='-'/></w:lvl>"
              for n in range(3))
    + "</w:abstractNum><w:num w:numId='1'><w:abstractNumId w:val='0'/></w:num></w:numbering>"
)
STYLES = (
    f"<w:styles {NS}>"
    + "".join(f"<w:style w:type='paragraph' w:styleId='Heading{n}'><w:name w:val='heading {n}'/>"
              "</w:style>" for n in (1, 2))
    + "<w:style w:type='paragraph' w:styleId='ListSub'><w:pPr><w:numPr><w:ilvl w:val='1'/>"
    "<w:numId w:val='1'/></w:numPr></w:pPr></w:style></w:styles>"
)


def word(path: Path, paragraphs: list[tuple[str, str]], extra: str = "") -> Path:
    """A .docx of paragraphs, each with its properties: `H1` and `H2` a heading's style, `L0`
    to `L2` a list's level, `S` the style that puts a paragraph at level 1."""
    body = ""
    for text, kind in paragraphs:
        props = {"H1": "<w:pStyle w:val='Heading1'/>", "H2": "<w:pStyle w:val='Heading2'/>",
                 "S": "<w:pStyle w:val='ListSub'/>", "": ""}.get(kind)
        if props is None:
            props = f"<w:numPr><w:ilvl w:val='{kind[1]}'/><w:numId w:val='1'/></w:numPr>"
        run = f"<w:r><w:t xml:space='preserve'>{text}</w:t></w:r>"
        body += f"<w:p><w:pPr>{props}</w:pPr>{run}</w:p>"
    document = f"<?xml version='1.0'?><w:document {NS}><w:body>{body}{extra}</w:body></w:document>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", STYLES)
        archive.writestr("word/numbering.xml", NUMBERING)
    return path


WORD_FLOW = [("Assessed (n = 412)", "L0"), ("Excluded (n = 112)", "S"),
             ("Randomised (n = 300)", "L0"), ("Drug (n = 151)", "L1"),
             ("Placebo (n = 148)", "L1")]  # fmt: skip


def test_a_word_flow_is_read_from_its_list_levels(tmp_path: Path) -> None:
    """A level from the paragraph's own numbering or its style's; a heading's line is no
    item, and ends the list; each heading keeps its level."""
    path = word(tmp_path / "p.docx", [("Participant flow", "H1"), *WORD_FLOW, ("Arms", "H2"),
                                      ("Other (n = 3)", "L0")])  # fmt: skip
    document = read_docx_text(path)
    # The body opens with a line of its own, before the first paragraph's.
    assert document.levels == ((3, 0), (4, 1), (5, 0), (6, 1), (7, 1), (9, 0))
    assert document.heading_levels == ((1, 1), (7, 2))
    report = audit([path], None)
    assert report.flows_read == 1
    assert [d.message for d in report.flows_broken] == [
        "the arms sum to 299, and the last stage is 300"]


def test_counts_in_text_boxes_are_noted_as_a_flow_not_read(tmp_path: Path) -> None:
    box = ("<w:p><w:r><w:drawing><w:txbxContent><w:p><w:r><w:t>Assessed (n = 412)</w:t></w:r>"
           "</w:p><w:p><w:r><w:t>Randomised (n = 300)</w:t></w:r></w:p></w:txbxContent>"
           "</w:drawing></w:r></w:p>")
    report = audit([word(tmp_path / "p.docx", [("Text.", "")], box)], None)
    assert report.flows_read == 0
    assert [(d.line, d.message.split(":")[0]) for d in report.flow_notes] == [
        (0, "its text boxes give 2 counts (n = N), as a flow drawn in boxes does")]


# ------------------------------------------------------------------ Abstract against Results

PAPER = """\
# A trial

## Abstract

Mortality was 53% (OR 1.52, 95% CI 1.21-1.90), t(48) = 2.10, P = 0.03. Of 412, 99 died.

## Methods

We randomised 412 patients.

## Results

Mortality was 53.3% (OR 1.52, 95% CI 1.21-1.89). We found t(48) = 2.10, P = 0.04.

## Discussion

As 99 died in the other trial.
"""


def test_the_abstract_is_held_to_what_the_paper_reports(tmp_path: Path) -> None:
    (tmp_path / "p.md").write_text(PAPER, encoding="utf-8")
    read = audit([tmp_path / "p.md"], None).abstract
    assert read.compared
    assert [c.message.split(", and")[0] for c in read.conflicts] == [
        "the Abstract gives OR 1.52 (95% CI 1.21 to 1.90)",
        "the Abstract gives t(48) = 2.10, P = 0.03"]
    # 99 is printed in the Discussion only, which is no place the paper reports: asked about
    # (decision 27, part B), and not found where the paper reports.
    assert read.not_found == []
    assert [c.text for c, *_rest in read.only_in] == ["99"]
    assert [c.text for c in read.rounded] == ["53%"]
    assert read.matched == 1  # 412, in the Methods
    assert read.discrimination is not None


def test_numbers_that_agree_as_printed_are_no_conflict(tmp_path: Path) -> None:
    """1.5 against 1.52 and P = 0.03 against P = 0.032 could each be one value printed twice,
    and P < 0.05 holds of 0.04; two counterparts that each differ in one number are none."""
    agreeing = PAPER.replace("1.21-1.90", "1.2-1.9").replace("P = 0.04", "P = 0.032")
    (tmp_path / "a.md").write_text(agreeing, encoding="utf-8")
    assert audit([tmp_path / "a.md"], None).abstract.conflicts == []
    bounded = PAPER.replace("P = 0.03.", "P < 0.05.").replace("1.21-1.90", "1.21-1.89")
    (tmp_path / "b.md").write_text(bounded, encoding="utf-8")
    assert audit([tmp_path / "b.md"], None).abstract.conflicts == []
    twice = PAPER.replace("P = 0.04.", "P = 0.04. Adjusted, OR 1.52 (95% CI 1.21-1.91).")
    twice = twice.replace("t(48) = 2.10, P = 0.03", "")
    (tmp_path / "c.md").write_text(twice, encoding="utf-8")
    assert audit([tmp_path / "c.md"], None).abstract.conflicts == []


INTERVAL_SAID = ("the Abstract gives OR 1.52 (95% CI 1.21 to 1.90), and where the paper reports, "
                 "line 13 gives OR 1.52 (95% CI 1.21 to 1.89)")
TEST_SAID = ("the Abstract gives t(48) = 2.10, P = 0.03, and where the paper reports, line 13 "
             "gives t(48) = 2.10, P = 0.04")


def _said(tmp_path: Path, text: str) -> list[str]:
    (tmp_path / "p.md").write_text(text, encoding="utf-8")
    return [c.message for c in audit([tmp_path / "p.md"], None).abstract.conflicts]


def test_a_conflict_needs_a_unique_counterpart(tmp_path: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "The Abstract is held to the Results by weak
    membership"): where two intervals of the same estimate and level, or two tests of the
    same kind, degrees of freedom and statistic, could be the counterpart, none is said; with
    one of each, both are."""
    assert _said(tmp_path, PAPER) == [INTERVAL_SAID, TEST_SAID]
    two_intervals = PAPER.replace("We found t(48)", "Else, OR 1.52 (95% CI 1.21-1.88). We found "
                                  "t(48)")  # fmt: skip
    assert _said(tmp_path, two_intervals) == [TEST_SAID]
    two_tests = PAPER.replace("P = 0.04.", "P = 0.04. Then t(48) = 2.10, P = 0.05.")
    assert _said(tmp_path, two_tests) == [INTERVAL_SAID]


@pytest.mark.parametrize(("abstract", "results", "paired"), [
    ("aOR", "OR", False), ("adj. OR", "OR", False), ("OR", "aOR", False),
    ("Adjusted OR", "OR", True),
])  # fmt: skip
def test_an_estimate_named_another_way_has_no_counterpart(
    tmp_path: Path, abstract: str, results: str, paired: bool
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The Abstract is held to the Results by weak
    membership"): an estimate is paired by its name, so "aOR" or "adj. OR" against "OR" has
    no counterpart and its conflict is not said; "Adjusted OR" is an OR, and it is."""
    text = PAPER.replace("(OR 1.52, 95% CI 1.21-1.90)", f"({abstract} 1.52, 95% CI 1.21-1.90)")
    text = text.replace("(OR 1.52, 95% CI 1.21-1.89)", f"({results} 1.52, 95% CI 1.21-1.89)")
    assert _said(tmp_path, text) == ([INTERVAL_SAID, TEST_SAID] if paired else [TEST_SAID])


def test_where_the_true_counterpart_is_unreadable_a_near_one_is_said_to_conflict(
    tmp_path: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The Abstract is held to the Results by weak
    membership"): the Results' own interval, joined by hyphens after a negative bound, cannot
    be read, and another of the same name and level agreeing in two numbers, the women's, is
    said to conflict in its third; read, the true one agrees, and nothing is said."""
    text = ("# A trial\n\n## Abstract\n\nThe mean difference was -0.50 (95% CI -0.90 to -0.10)."
            "\n\n## Methods\n\nWe randomised 412 patients.\n\n## Results\n\nOverall, the mean "
            "difference was -0.50 (95% CI TRUE). In women, the mean difference was -0.50 (95% "
            "CI -0.90 to -0.20).\n\n## Discussion\n\nNothing.\n")  # fmt: skip
    (tmp_path / "p.md").write_text(text.replace("TRUE", "-0.90--0.10"), encoding="utf-8")
    [conflict] = audit([tmp_path / "p.md"], None).abstract.conflicts
    assert (conflict.line, conflict.message) == (5, (
        "the Abstract gives mean difference -0.50 (95% CI -0.90 to -0.10), and where the "
        "paper reports, line 13 gives mean difference -0.50 (95% CI -0.90 to -0.20)"))
    (tmp_path / "p.md").write_text(text.replace("TRUE", "-0.90 to -0.10"), encoding="utf-8")
    assert audit([tmp_path / "p.md"], None).abstract.conflicts == []


def test_a_supplement_and_a_table_are_where_the_paper_reports(tmp_path: Path) -> None:
    paper = PAPER.replace("As 99 died", "| Died | 99 |\n|---|---|\n| x | 1 |\n\nAs 9 died")
    (tmp_path / "p.md").write_text(paper.replace("99 died.", "99 died, 77 lived."),
                                   encoding="utf-8")  # fmt: skip
    (tmp_path / "supplement.md").write_text("Of the cohort, 77 lived.\n", encoding="utf-8")
    read = audit([tmp_path / "p.md", tmp_path / "supplement.md"], None).abstract
    assert read.not_found == []


def test_a_table_in_the_abstract_reports_and_a_word_footnote_is_searched_nowhere(
    tmp_path: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The Abstract is held to the Results by weak
    membership"): a table's lines are where the paper reports wherever it stands, the
    Abstract included, and a Word document's footnotes are a note's lines, searched under no
    heading, the Results not even where they are the body's last."""
    text = ("# T\n\n## Abstract\n\nOf 412, 99 died.\n\nTABLE\n\n## Methods\n\nWe randomised 412 "
            "patients.\n\n## Results\n\nNone.\n\n## Discussion\n\nDISCUSSION\n")  # fmt: skip
    table = "| Died | 99 |\n|---|---|\n| x | 1 |"
    (tmp_path / "a.md").write_text(text.replace("TABLE", table).replace("DISCUSSION", "None."),
                                   encoding="utf-8")  # fmt: skip
    read = audit([tmp_path / "a.md"], None).abstract
    assert (read.matched, read.not_found, read.only_in) == (2, [], [])
    # The other side: the same row as prose of the Discussion is no place the paper reports.
    (tmp_path / "b.md").write_text(text.replace("TABLE", "").replace("DISCUSSION", "As 99 died."),
                                   encoding="utf-8")  # fmt: skip
    read = audit([tmp_path / "b.md"], None).abstract
    assert read.matched == 1 and [c.text for c, *_rest in read.only_in] == ["99"]
    notes = (f"<?xml version='1.0'?><w:footnotes {NS}><w:footnote w:id='1'><w:p><w:r>"
             "<w:t>Of them 99 died.</w:t></w:r></w:p></w:footnote></w:footnotes>")
    body = [("Abstract", "H1"), ("Of 412, 99 died.", ""), ("Methods", "H1"),
            ("We randomised 412.", ""), ("Results", "H1"), ("None.", "")]  # fmt: skip
    for last in ([], [("Discussion", "H1"), ("Nothing.", "")]):
        path = word(tmp_path / f"p{len(last)}.docx", body + last)
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("word/footnotes.xml", notes)
        read = audit([path], None).abstract
        assert read.matched == 1 and [c.text for c in read.not_found] == ["99"], last
        assert read.only_in == []
    # The other side: the same sentence in the body under the Results is found there.
    path = word(tmp_path / "body.docx", [*body[:5], ("Of them 99 died.", "")])
    read = audit([path], None).abstract
    assert (read.matched, read.not_found) == (2, [])


@pytest.mark.parametrize(
    ("paper", "why"),
    [
        (PAPER.replace("## Abstract", "## Summary of the trial"), "names the Abstract"),
        (PAPER.replace("## Results", "## Findings that matter").replace("Findings", "Data"),
         "Results heading"),
    ],
)
def test_without_an_abstract_or_results_nothing_is_compared(
    tmp_path: Path, paper: str, why: str
) -> None:
    (tmp_path / "p.md").write_text(paper, encoding="utf-8")
    read = audit([tmp_path / "p.md"], None).abstract
    assert not read.compared and why in read.why_not
    assert read.conflicts == read.not_found == []


@pytest.mark.parametrize("paper", [PAPER.replace("## Abstract", "## Summary"),
                                   PAPER.replace("## Abstract\n\n", "")],
                         ids=["summary", "no heading"])  # fmt: skip
def test_an_abstract_under_summary_or_no_heading_is_not_found(tmp_path: Path, paper: str) -> None:
    """A known gap (DESIGN.md, Known gaps, "The Abstract is held to the Results by weak
    membership"): an Abstract under no heading that names it, or under "Summary", is not
    found, and nothing is compared; under "Abstract" its two conflicts are said."""
    (tmp_path / "p.md").write_text(paper, encoding="utf-8")
    read = audit([tmp_path / "p.md"], None).abstract
    assert not read.compared and read.why_not == "no file has a heading that names the Abstract"
    assert read.conflicts == read.not_found == read.only_in == [] and read.matched == 0
    (tmp_path / "p.md").write_text(PAPER, encoding="utf-8")
    assert len(audit([tmp_path / "p.md"], None).abstract.conflicts) == 2


def test_a_word_abstract_is_placed_by_its_heading_levels(tmp_path: Path) -> None:
    """The structured abstract's own Results, a level below it, are the Abstract's."""
    path = word(tmp_path / "p.docx", [
        ("Abstract", "H1"), ("Results", "H2"), ("The OR was 1.52 (95% CI 1.21-1.90).", ""),
        ("Methods", "H1"), ("We did it.", ""), ("Results", "H1"),
        ("The OR was 1.52 (95% CI 1.21-1.89).", "")])  # fmt: skip
    [conflict] = audit([path], None).abstract.conflicts
    assert conflict.line == 4 and "line 8 gives" in conflict.message


def test_numbers_agree_where_one_value_prints_as_both() -> None:
    assert agree("1.5", "1.52") and agree("53", "53.3") and agree("0.03", "0.035")
    assert not agree("1.90", "1.89") and not agree("0.03", "0.04") and not agree("53", "53.6")
    assert coarser("53.3") == {("53", 0)}
    assert coarser("0.725") == {("0.72", 2), ("0.73", 2), ("0.7", 1), ("1", 0)}
    assert coarser("12") == set()


def test_strict_counts_a_broken_flow_and_a_conflict_and_not_a_number_not_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean = PAPER.replace("1.21-1.90", "1.21-1.89").replace("P = 0.03", "P = 0.04")
    (tmp_path / "clean.md").write_text(clean, encoding="utf-8")
    assert main(["audit", str(tmp_path / "clean.md"), "--strict"]) == 0
    capsys.readouterr()
    (tmp_path / "p.md").write_text(PAPER, encoding="utf-8")
    assert main(["audit", str(tmp_path / "p.md"), "--strict", "--json"]) == 1
    said = json.loads(capsys.readouterr().out)
    counted = sorted({f["code"] for f in said["findings"] if f["counted"]})
    assert counted == ["abstract-conflict"]
    # The Discussion's 99 is asked about (decision 27, part B); given nowhere, it is not
    # found, and --strict counts neither.
    assert said["counts"]["abstract_not_found"] == 0
    assert said["counts"]["abstract_asked_only_in"] == 1
    assert said["counts"]["abstract_matched_as_rounding"] == 1
    assert said["abstract_compared"] and said["what_an_abstract_match_is_worth"]
    (tmp_path / "n.md").write_text(PAPER.replace("As 99 died", "As 98 died"), encoding="utf-8")
    assert main(["audit", str(tmp_path / "n.md"), "--strict", "--json"]) == 1
    said = json.loads(capsys.readouterr().out)
    assert sorted({f["code"] for f in said["findings"] if f["counted"]}) == ["abstract-conflict"]
    assert said["counts"]["abstract_not_found"] == 1
    flow = "\n## Participant flow\n\n" + FLOW.replace("149", "148")
    (tmp_path / "f.md").write_text(clean + flow, encoding="utf-8")
    assert main(["audit", str(tmp_path / "f.md"), "--strict"]) == 1
    out = capsys.readouterr().out
    assert "FLOWS WHOSE ARITHMETIC DOES NOT HOLD, under a name for a flow" in out
    assert "=== Abstract against Results ===" in out


# ----------------------------------------------------------------- what names a flow

SUBGROUPS = "- Men (n = 200)\n  - Smokers (n = 50)\n- Women (n = 180)\n  - Smokers (n = 40)\n"


@pytest.mark.parametrize(
    ("before", "named"),
    [
        ("## Participant flow\n\nAs follows.\n\n", True),
        ("## Results\n\nFigure 1: flow of participants.\n\n", True),
        ("## Results\n\nThe selection of the study population.\n\n", True),
        ("## Subgroups\n\nAs follows.\n\n", False),
        ("## CONSORT\n\n## Subgroups\n\n", False),
    ],
)
def test_a_flow_counts_where_its_heading_or_the_paragraph_before_it_names_one(
    before: str, named: bool
) -> None:
    """Basile, 2026-10-29: a broken flow counts under a heading, or after a caption or a
    paragraph, that names a flow; the nearest heading above is the one read."""
    [flow] = _flows(before + SUBGROUPS)
    assert flow.problems and flow.named is named


def test_a_subgroup_list_is_a_note_and_the_same_list_named_a_flow_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paper = tmp_path / "p.md"
    paper.write_text("# Results\n\n" + SUBGROUPS, encoding="utf-8")
    report = audit([paper], None)
    assert report.flows_broken == [] and report.flows_named == 0
    assert report.flow_notes[0].message.endswith("names a flow, so it is not counted")
    assert main(["audit", str(paper), "--strict"]) == 0
    paper.write_text("# Participant flow\n\n" + SUBGROUPS, encoding="utf-8")
    assert main(["audit", str(paper), "--strict"]) == 1
    capsys.readouterr()


def test_a_latex_and_a_word_list_are_named_by_their_heading_or_caption(tmp_path: Path) -> None:
    source = read_tree({"paper.tex": tex(
        "!documentclass{article}\n!begin{document}\n!section{Participant flow}\n\nText.\n\n"
        "!begin{itemize}\n!item A (n = 9)\n!begin{itemize}\n!item B (n = 1)\n!end{itemize}\n"
        "!item C (n = 7)\n!end{itemize}\n!section{Subgroups}\n!begin{itemize}\n!item A (n = 9)"
        "\n!begin{itemize}\n!item B (n = 1)\n!end{itemize}\n!item C (n = 7)\n!end{itemize}\n"
        "!end{document}\n")}, "paper.tex").sources[0]
    from manuscript_guard.text.latex.views import bindings, markdown_view

    hidden = markdown_view(source, bindings(source)[0], blank="\x00")
    assert [f.named for f in flows_in(latex_lists(source, hidden))] == [True, False]
    paragraphs = [("Results", "H1"), ("Figure 2. CONSORT diagram", ""), *WORD_FLOW,
                  ("Results by sex", "H1"), *WORD_FLOW]
    report = audit([word(tmp_path / "p.docx", paragraphs)], None)
    assert (report.flows_read, report.flows_named, len(report.flows_broken)) == (2, 1, 1)


# ------------------------------------------------------------------ review round 1 of #472

CONSORT = """## CONSORT diagram

- Assessed for eligibility (n = 400)
  - Excluded (n = 100)
- Randomised (n = 300)
  - Drug (n = 151)
  - Placebo (n = 149)
- Analysed (n = 290)
  - Drug (n = 145)
  - Placebo (n = 145)
"""


def test_items_that_add_up_to_their_stage_are_a_breakdown_and_no_exclusions() -> None:
    """Arms randomised mid-flow, a review's sources: items under a stage that is not the
    last and add up to it exactly are noted as a breakdown; the step after it lists no
    exclusion, so a fall is noted and nothing fails."""
    [flow] = _flows(CONSORT)
    assert flow.problems == () and flow.named
    assert flow.exclusions == ((100,), ())
    assert flow.notes == (
        "the items under stage 2 (300) add up to it: read as a breakdown of it, not as its "
        "exclusions",
        "stage 3 (290) is 10 fewer than stage 2 (300), and no exclusion is listed")
    prisma = ("## PRISMA flow chart\n\n- Identified (n = 520)\n  - Databases (n = 500)\n"
              "  - Registers (n = 20)\n- Screened (n = 400)\n  - Excluded (n = 300)\n"
              "- Included (n = 100)\n")
    [flow] = _flows(prisma)
    assert flow.problems == () and "breakdown" in flow.notes[0]


def test_a_step_that_lists_no_exclusion_is_held_only_to_not_growing() -> None:
    funnel = ("## Study population\n\n- Screened (n = 1,000)\n- Eligible (n = 800)\n"
              "- Enrolled (n = 600)\n  - A (n = 300)\n  - B (n = 300)\n")
    [flow] = _flows(funnel)
    assert flow.problems == ()
    assert [note.split(",")[0] for note in flow.notes] == [
        "stage 2 (800) is 200 fewer than stage 1 (1000)",
        "stage 3 (600) is 200 fewer than stage 2 (800)"]
    [flow] = _flows(funnel.replace("Eligible (n = 800)", "Eligible (n = 1,200)"))
    assert flow.problems == ("stage 2 (1200) is larger than stage 1 (1000)",)


@pytest.mark.parametrize("space", [" ", chr(0xA0), chr(0x202F)])
def test_thousands_parted_by_a_space_are_one_count(space: str) -> None:
    assert counts_in(f"Assessed (n = 12{space}345)") == [12345]
    assert counts_in("n = 412 30 days later") == []


def test_a_latex_abstract_on_the_line_of_its_end_is_compared(tmp_path: Path) -> None:
    """The heading that closes an abstract stands on `!end{abstract}`'s line, and the last
    sentence before it on that line was placed nowhere; so was Results text before a
    `!section` on its line."""
    (tmp_path / "p.tex").write_text(tex(
        "!documentclass{article}\n!begin{document}\n!begin{abstract}\n"
        "The OR was 1.52 (95!% CI 1.21--1.90).!end{abstract}\n!section{Methods}\nWe did.\n"
        "!section{Results}\nThe OR was 1.52 (95!% CI 1.21--1.89).!section{Discussion}\n"
        "Nothing.\n!end{document}\n"), encoding="utf-8")
    [conflict] = audit([tmp_path / "p.tex"], None).abstract.conflicts
    assert conflict.line == 4 and "line 8 gives" in conflict.message


def test_an_introduction_s_interval_on_the_results_heading_s_line_is_read_as_reported(
    tmp_path: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The Abstract is held to the Results by weak
    membership"): a `.tex` line keeps its first place where the paper reports, so another
    trial's interval in the Introduction, on the line of the `\\section{Results}` after it,
    is the Abstract's counterpart and its conflict is said; on a line of its own it is the
    Introduction's, and nothing is."""
    text = ("!documentclass{article}\n!begin{document}\n!begin{abstract}\nThe OR was 1.52 (95!% "
            "CI 1.21--1.90).\n!end{abstract}\n!section{Introduction}\nAnother trial gave OR 1.52 "
            "(95!% CI 1.21--1.89).BREAK!section{Results}\nWe found 77 deaths.\n"
            "!section{Discussion}\nNothing.\n!end{document}\n")  # fmt: skip
    (tmp_path / "p.tex").write_text(tex(text.replace("BREAK", "")), encoding="utf-8")
    [conflict] = audit([tmp_path / "p.tex"], None).abstract.conflicts
    assert (conflict.line, conflict.message) == (4, (
        "the Abstract gives OR 1.52 (95% CI 1.21 to 1.90), and where the paper reports, line 7 "
        "gives OR 1.52 (95% CI 1.21 to 1.89)"))
    (tmp_path / "p.tex").write_text(tex(text.replace("BREAK", "\n")), encoding="utf-8")
    assert audit([tmp_path / "p.tex"], None).abstract.conflicts == []


def test_any_heading_over_a_list_may_name_it_a_flow() -> None:
    [flow] = _flows("## Participant flow\n\n### Trial A\n\n- A (n = 9)\n  - B (n = 1)\n"
                    "- C (n = 7)\n")
    assert flow.named
    [flow] = _flows("## Participant flow\n\n## Trial A\n\n- A (n = 9)\n  - B (n = 1)\n"
                    "- C (n = 7)\n")
    assert not flow.named


def test_another_kind_of_marker_after_a_blank_line_starts_another_list() -> None:
    text = "- A (n = 9)\n  - B (n = 1)\n- C (n = 8)\n\n1. D (n = 9)\n   - E (n = 1)\n2. F (n = 7)\n"
    first, second = _flows(text)
    assert first.stages == (9, 8) and second.stages == (9, 7)


def test_flow_alone_names_no_flow() -> None:
    for heading in ("Blood flow", "Flow cytometry"):
        [flow] = _flows(f"## {heading}\n\n- A (n = 9)\n  - B (n = 1)\n- C (n = 7)\n")
        assert not flow.named, heading
    for heading in ("Flow chart", "Flow diagram", "Participant flow", "PRISMA flowchart",
                    "Patient flow", "Study flow", "Subjects flow", "Trial profile",
                    "Flow of patients through the trial"):
        [flow] = _flows(f"## {heading}\n\n- A (n = 9)\n  - B (n = 1)\n- C (n = 7)\n")
        assert flow.named, heading


def test_each_file_is_placed_by_its_own_headings(tmp_path: Path) -> None:
    """Round 2 of #472 took back round 1's carry, which guessed a supplement by its name: a
    file with no Abstract is reported whole, a split paper's Discussion too (Known gaps)."""
    (tmp_path / "1.md").write_text("# P\n\n## Abstract\n\nIt was 812.5 and 733.1.\n\n"
                                   "## Methods\n\nNone.\n\n## Discussion\n\nIt was 733.1.\n",
                                   encoding="utf-8")  # fmt: skip
    (tmp_path / "2.md").write_text("## Discussion\n\nIt was 812.5.\n", encoding="utf-8")
    (tmp_path / "3.md").write_text("## Results\n\nNone.\n", encoding="utf-8")
    read = audit([tmp_path / name for name in ("1.md", "2.md", "3.md")], None).abstract
    # 733.1 stands only in 1.md's Discussion: asked about (decision 27, part B).
    assert read.not_found == [] and read.matched == 1
    assert [c.text for c, *_rest in read.only_in] == ["733.1"]


def test_a_single_item_under_a_stage_is_an_exclusion_whatever_it_counts() -> None:
    """Round 2 of #472: the stage's count copied into its one exclusion is no breakdown."""
    [flow] = _flows("## CONSORT diagram\n\n- Assessed (n = 412)\n  - Excluded (n = 412)\n"
                    "- Randomised (n = 300)\n")
    assert flow.problems == ("the reasons after stage 1 (412) cannot account for the 112 "
                             "excluded, even overlapping",)  # fmt: skip
    assert not any("breakdown" in note for note in flow.notes)


def test_items_under_a_breakdowns_part_are_noted() -> None:
    text = CONSORT.replace("  - Drug (n = 151)\n", "  - Drug (n = 151)\n    - Lost (n = 3)\n", 1)
    [flow] = _flows(text)
    assert flow.problems == ()
    assert "the items under a part of stage 2's breakdown are not read" in flow.notes


def test_a_heading_of_the_first_level_names_a_list_title_or_section(tmp_path: Path) -> None:
    """The fix-only round of #472 took back round 2's title rule: a LaTeX section "Participants
    and methods" over a broken flow under "Outcomes" names it, and --strict fails it; a
    Markdown title "# ... in participants" names every list below it too (Known gaps)."""
    (tmp_path / "p.tex").write_text(tex(
        "!documentclass{article}\n!begin{document}\n!section{Participants and methods}\n\n"
        "!subsection{Statistical methods}\n\nNone.\n\n!subsection{Outcomes}\n\n!begin{itemize}\n"
        "!item A (n = 9)\n!begin{itemize}\n!item B (n = 1)\n!end{itemize}\n!item C (n = 7)\n"
        "!end{itemize}\n!end{document}\n"), encoding="utf-8")
    assert main(["audit", str(tmp_path / "p.tex"), "--strict"]) == 1
    title = "# A trial in participants with diabetes\n\n## Abstract\n\nIt was.\n\n"
    [flow] = _flows(title + "## Results\n\n- A (n = 9)\n  - B (n = 1)\n- C (n = 7)\n")
    assert flow.named


def test_an_ordered_marker_or_another_delimiter_starts_another_list_and_a_bullet_does_not(
) -> None:
    """As pandoc 3.9 reads them, with no blank line between: "1." under "-" items, and "1)"
    under "1." items, start new lists; "*" under "-" goes on with the list."""
    text = "- A (n = 9)\n  - B (n = 1)\n- C (n = 8)\n1. D (n = 9)\n   - E (n = 1)\n2. F (n = 7)\n"
    first, second = _flows(text)
    assert first.stages == (9, 8) and second.stages == (9, 7)
    first, second = _flows("1. A (n = 9)\n   - B (n = 1)\n2. C (n = 8)\n"
                           "1) D (n = 9)\n   - E (n = 1)\n2) F (n = 7)\n")
    assert first.stages == (9, 8) and second.stages == (9, 7)
    [flow] = _flows("- A (n = 9)\n  - B (n = 1)\n* C (n = 8)\n")
    assert flow.stages == (9, 8)
