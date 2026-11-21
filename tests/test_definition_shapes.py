"""G14 reads four more shapes as a definition (decision 29, the author, 2026-11-16).

The corpus run on 0223ca005 had judges mark 41 undefined short forms false because the paper
defined them in a shape G14 did not read. Each shape only says where a long form and a short
form stand; whether they are one is the letter rule G14 already has (`_long_form`), so a
short form whose words do not match stays undefined in each shape:

* a short form first in its brackets before a word or a whole number, "changing-look AGNs (CL
  AGNs)", "(ESM 1)", and each short form of a bracket that lists them, "(CAP, CAP-T)";
* "X = long form" and "X: long form", a table's note among them, pair by pair, with short
  forms a slash joins paired with the long form's parts;
* "known as X", "referred to as X", "commonly referred to as X", "called X", "hereafter X";
* a LaTeX citation's optional argument opening with the short form after its long form,
  `\\citep[SDSS DR15;][]{key}`, `\\citet[][BC03]{key}`, and pandoc's `[SDSS; @key]`;
* a definition in a heading.

Each case is written fresh, its corpus paper named in a comment. Each is held in `check`, a
project's Markdown and LaTeX, and in `audit`, a .docx, a PDF, Markdown and LaTeX, where the
reader holds the shape: a PDF has no headings but its sections' names, and only LaTeX has a
citation command.
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.auditing.undefined import unasked
from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_language
from manuscript_guard.gates.language import _file, _latex_read

sys.path.insert(0, str(Path(__file__).parent))
from generated import word_package  # noqa: E402
from proof_pdf import typeset  # noqa: E402

#: Each shape in prose, as (kind, sentence, short form), the sentence defining the short
#: form. The corpus paper each stands for is named beside it.
DEFINING = (
    # tex-astro-ga-A2: a word after the short form in its bracket.
    ("a word after it", "We followed the rapidly varying quasars (RV quasars).", "RV"),
    # docx-socio-B2: the act's own word after it.
    ("a word after it", "The Fair Housing Records Act (FHR Act) applied.", "FHR"),
    # docx-med-B3: a number after it, and nothing else.
    ("a number after it", "The Online Supplementary Appendix (OSA 2) lists them.", "OSA"),
    # docx-educ-B1: each short form of a bracket that lists them.
    ("a list", "We used the Teacher Video Modules (TVM, VM).", "TVM"),
    ("a list", "We used the Student Video Lessons (SVL, VL).", "VL"),
    # docx-med-A3, docx-sport-A2: a table's note, an equals sign with a space or none.
    ("an equals sign", "Note. GDS = Geriatric Depression Scale; HAQ= Health Assessment "
     "Questionnaire.", "HAQ"),
    # pdf-med-A1's shape, with a long form of two words.
    ("a colon", "Countries: MMQ: Memory Mood Questionnaire, given to all.", "MMQ"),
    # docx-pharm-epi-B1: short forms a slash joins, paired with the long form's parts.
    ("a slash", "RA/NRA = risk/non-risk allele.", "NRA"),
    # tex-astro-ga-A1, tex-qbio-pe-A1: known as, referred to as, called, hereafter.
    ("known as", "We read the ratio of far to near flux, known as FNR.", "FNR"),
    ("referred to as", "We modelled the latent bias components, commonly referred to as "
     "LBC terms.", "LBC"),
    ("called", "We used a gait balance scale, called GBS, in all.", "GBS"),
    ("hereafter", "We used the Deep Field Survey (hereafter DFS) throughout.", "DFS"),
    # docx-sport-A3: a definition in a heading.
    ("a heading", "## Grip strength and electromyography (EMG)", "EMG"),
)  # fmt: skip

#: The same shapes with words that do not hold the short form's letters, or a long form
#: that is not the words after the sign whole: each short form stays undefined.
NOT_DEFINING = (
    ("a word after it", "We followed the bright quasars (QV quasars).", "QV"),
    ("a number after it", "The online files (XSA 2) list them.", "XSA"),
    ("a list", "We used the Teacher Video Modules (TVM, QZ).", "QZ"),
    ("an equals sign", "Note. PSQ = the sleep score.", "PSQ"),
    # docx-med-B1: a word before the long form's letters, "DCDQ = Little Developmental ...".
    ("an equals sign", "Note. DCQ = Small Developmental Coordination Questionnaire.", "DCQ"),
    # pdf-med-A1: one word after a colon, as a country's code, is not a long form.
    ("a colon", "Countries: KN: Kenya.", "KN"),
    ("a slash", "XA/YNA = effect allele.", "YNA"),
    ("a slash", "XA/YNA = effect allele.", "XA"),
    ("known as", "We read the main survey, known as XQZ.", "XQZ"),
    ("called", "We used a scale called WTB in all.", "WTB"),
    ("a heading", "## Grip strength (EGX)", "EGX"),
)  # fmt: skip

#: A LaTeX citation's optional argument: the prenote, and the postnote where the prenote is
#: empty (tex-astro-ga-A1), and one whose letters the words before do not hold.
CITED = (
    ("We used the Wide Infrared Sky Explorer \\citep[WISE;][]{wright2010}.", "WISE", True),
    ("We used the Deep Lens Survey Data Release 3 \\citep[DLS DR3;][]{dls}.", "DLS", True),
    ("We fitted the Population Model of 2024 \\citet[][PM24]{pm}.", "PM24", True),
    ("We used the survey \\citep[XYS;][]{xys}.", "XYS", False),
)
#: The word after a note's short form is a use of its own, and DR3 is defined nowhere.
CITED_UNDEFINED = {"DR3"}


def _uses(shorts: list[str]) -> str:
    """A sentence that uses each short form again."""
    return "Later, " + ", ".join(shorts) + " were read again."


def _markdown(pieces: list[str], shorts: list[str]) -> str:
    body = "\n\n".join(pieces)
    return f"# Methods\n\n{body}\n\n# Results\n\n{_uses(shorts)}\n"


def _undefined(messages: list[str]) -> set[str]:
    return {message.split()[0] for message in messages}


def _all_shapes() -> tuple[list[str], list[str], set[str]]:
    pieces = [sentence for _kind, sentence, _short in (*DEFINING, *NOT_DEFINING)]
    shorts = [short for _kind, _sentence, short in (*DEFINING, *NOT_DEFINING)]
    return pieces, shorts, {short for _kind, _sentence, short in NOT_DEFINING}


# ---------------------------------------------------------------------- each shape alone


@pytest.mark.parametrize(("kind", "sentence", "short"), DEFINING)
def test_each_shape_defines_where_its_words_hold_the_short_form(
    kind: str, sentence: str, short: str
) -> None:
    read = _file(0, Path("main.md"), f"# Methods\n\n{sentence}\n", [], False)
    defined = {found for _at, found, _long in read.definitions}
    assert short in defined, (kind, read.definitions)


@pytest.mark.parametrize(("kind", "sentence", "short"), NOT_DEFINING)
def test_each_shape_defines_nothing_where_its_words_do_not_match(
    kind: str, sentence: str, short: str
) -> None:
    read = _file(0, Path("main.md"), f"# Methods\n\n{sentence}\n", [], False)
    assert short not in {found for _at, found, _long in read.definitions}, (kind, read.definitions)


def test_a_bracket_list_reads_each_short_form_against_the_one_long_form() -> None:
    """docx-educ-B1: each short form of "(CAP, CAP-T, CAP-TV)" is read against the words
    before the bracket on its own, and one whose letters are not in them is not defined."""
    read = _file(0, Path("main.md"), "the Content Acquisition Podcasts (CAP, CAP-T, CAP-TV)\n",
                 [], False)  # fmt: skip
    assert [(short, long) for _at, short, long in read.definitions] == [
        ("CAP", "Content Acquisition Podcasts"), ("CAP-T", "Content Acquisition Podcasts")]


def test_a_slash_pairs_each_short_form_with_its_part_of_the_long_form() -> None:
    """docx-pharm-epi-B1: "EA/NEA = effect/non-effect allele" defines EA as "effect allele"
    and NEA as "non-effect allele", each at its own place."""
    text = "EA/NEA = effect/non-effect allele\n"
    read = _file(0, Path("main.md"), text, [], False)
    assert sorted(read.definitions) == [(0, "EA", "effect allele"),
                                        (3, "NEA", "non-effect allele")]  # fmt: skip


def test_a_statistic_after_a_short_form_is_still_none() -> None:
    """A number with a decimal point, or a number and more, gives a statistic in each new
    shape as in the bracket: "(HR 1.32, ...)", "(MDD 40 mg)", "OR = 1.52", "OR: 1.52"."""
    for text in ("a higher risk (HR 1.32, 95% CI 1.10 to 1.58)", "the mean daily dose (MDD 40 mg)",
                 "the odds ratio OR = 1.52 in all", "the odds ratio OR: 1.52 in all",
                 "older adults (AOR = {{results.aor}})"):  # fmt: skip
        read = _file(0, Path("main.md"), f"{text}\n", [], False)
        assert read.definitions == [], (text, read.definitions)


def test_pandoc_s_citation_prefix_is_read_as_a_square_bracket() -> None:
    """G14 reads `[SDSS; @key]` as it reads "[SDSS]", the citation's key masked; and
    `[SDSS DR15; @key]` now, as a bracket whose short form a word follows."""
    for prefix in ("SDSS", "SDSS DR15"):
        read = _file(0, Path("main.md"), f"the Sloan Digital Sky Survey [{prefix}; @york2000]\n",
                     [], False)  # fmt: skip
        assert [short for _at, short, _long in read.definitions] == ["SDSS"], prefix


def _judged(project: Path, text: str) -> list[tuple[str, str]]:
    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(text, encoding="utf-8")
    report = check_language(load_project(project)[0])
    # G14's question on the short forms never defined as the warning it holds on each.
    return sorted((f.code, f.message.split()[0]) for f in unasked(list(report.findings)))


def test_a_note_that_repeats_the_text_s_definition_restates_it(project: Path) -> None:
    """Basile, 2026-11-16 ("As a restatement"; docx-sport-A2, docx-psych-A3): journals ask a
    table to define its own short forms, so a note's "X = long form" that repeats the text's
    definition restates it, as a caption does. Since 2026-11-21 ("Table stands alone") a
    table's note is compared with nothing in the text, so one whose long form differs from
    the text's, "Score" for "Scale", is no second meaning either; the same note standing in
    the text, under no table, still is."""
    methods = ("# Methods\n\nWe used the Beck Depression Inventory (BDI) and the Cigarette "
               "Dependence Scale (CDS).\n\n# Results\n\n")  # fmt: skip
    note = ("*Note.* BDI = Beck Depression Inventory; CDS = Cigarette Dependence Score.\n\nThe "
            "BDI and the CDS were low.\n")  # fmt: skip
    found = _judged(project, f"{methods}| Score | n |\n|---|---|\n| 12 | 40 |\n\n{note}")
    assert found == [], found
    found = _judged(project, f"{methods}The scores were read.\n\n{note}")
    assert found == [("abbreviation-redefined", "CDS")], found


def test_a_heading_that_the_text_defines_again_is_restated(project: Path) -> None:
    """A heading's definition, which the text then gives again, as many journals want it
    whatever the heading says, is no second definition (round 1 of #698)."""
    found = _judged(project, "# Methods\n\n## Reporting odds ratio (ROR)\n\nThe reporting "
                             "odds ratio (ROR) was computed, and the ROR was high.\n")
    assert found == [], found


@pytest.mark.parametrize("text", [
    "# Methods\n\n## Statistical analysis (SA)\n\nThe SA was run.",
    # docx-sport-A3: a subheading under a subsection of the Methods.
    "# Materials and Methods\n\n## Apparatus\n\n### Grip and electromyography (EMG)\n\nThe EMG "
    "was read."])  # fmt: skip
def test_a_heading_under_a_named_section_defines(project: Path, text: str) -> None:
    assert _judged(project, f"{text}\n") == []


def test_a_title_in_the_second_file_of_a_paper_defines_nothing(project: Path) -> None:
    """Round 5 of #698: a title page alone in `main.md`, the title a heading opening the
    next file, defines nothing there; the text's definition is the only one."""
    title = "# Reporting odds ratio (ROR) in older adults\n\n## Introduction\n\n"
    for said, found in (("The reporting odds ratio (ROR) was computed, and the ROR was high.",
                         []), ("The ROR was computed.", [("abbreviation-undefined", "ROR")])):
        (project / "manuscript" / "01-main.md").write_text(f"{title}{said}\n", encoding="utf-8")
        assert _judged(project, "Authors: A. Author\n") == found


@pytest.mark.parametrize("title", [
    # The paper's title typed as a heading of the Introduction's level, or above the
    # Abstract or the Introduction (round 1 of #698).
    "# Reporting odds ratio (ROR) in older adults\n\n# Introduction",
    "# Reporting odds ratio (ROR) in older adults\n\n# Abstract\n\nIt was read.\n\n# Background",
    "# Reporting odds ratio (ROR) in older adults\n\n## Introduction",
    # Round 5: a title under a heading that names no section, "Original article".
    "# Original article\n\n## Reporting odds ratio (ROR) in older adults\n\n### Introduction",
])  # fmt: skip
def test_the_paper_s_title_typed_as_a_heading_defines_nothing(project: Path, title: str) -> None:
    """The title is no section's heading in the main text: a short form it defines is still
    undefined in the text, and one the text defines is not defined again."""
    used = "The ROR was computed, and the ROR was high."
    assert ("abbreviation-undefined", "ROR") in _judged(project, f"{title}\n\n{used}\n")
    defined = "The reporting odds ratio (ROR) was computed, and the ROR was high."
    found = _judged(project, f"{title}\n\n{defined}\n")
    assert "ROR" not in [short for _code, short in found], found


def test_a_heading_in_the_abstract_defines_nothing_for_it(project: Path) -> None:
    """A heading defines only where it is a section's heading in the main text's scope."""
    found = _judged(project, "# Abstract\n\n## Grip strength and electromyography (EMG)\n\nThe "
                             "EMG was high.\n\n# Methods\n\nThe grip was read.\n")
    assert ("abbreviation-undefined", "EMG") in found, found


@pytest.mark.parametrize("note", [
    "ESR = erythrocyte sedimentation rate\nValues are medians", "*Note.* mRNA = messenger RNA\n"
    "Not adjusted.", "*Note.* ECG = electrocardiogram\nChanges graded.",
    "*Note.* BDI = Beck Depression\nInventory."])  # fmt: skip
def test_a_note_whose_long_form_runs_onto_the_next_line_defines_nothing(note: str) -> None:
    """Basile, 2026-11-16, "Wrapped note defines nothing" (rounds 1 to 3 of #698): a wrapped
    long form cannot be told from a sentence after it, so it is refused, not guessed."""
    assert _file(0, Path("main.md"), f"{note}\n", [], False).definitions == []


@pytest.mark.parametrize("note", ["*Note.* ESR = erythrocyte sedimentation rate.\nValues.",
                                  "Values are medians.\nESR = erythrocyte sedimentation rate",
                                  # A new block on the next line ends it (round 4 of #698).
                                  "- ESR = erythrocyte sedimentation rate\n- BDI = Beck Depression",
                                  "*Note.* ESR = erythrocyte sedimentation rate\n| 1 | 2 |"])
def test_a_note_ended_on_its_line_defines(note: str, tmp_path: Path) -> None:
    read = _file(0, Path("main.md"), f"{note}\n\nThe ESR held.\n", [], False)
    assert [short for _at, short, _long in read.definitions][:1] == ["ESR"], read.definitions
    (tmp_path / "main.tex").write_text(_latex(
        "\\begin{tablenotes}\n\\item ESR = erythrocyte sedimentation rate\n\\item BDI = Beck "
        "Depression Inventory\\\\\nPDW = platelet distribution width\n\\end{tablenotes}\n"),
        encoding="utf-8")  # fmt: skip
    assert [short for read in _latex_read(tmp_path, None) for _at, short, _long
            in read.definitions] == ["ESR", "BDI", "PDW"]  # fmt: skip


def test_a_wrapped_note_beside_the_text_s_definition_says_nothing(project: Path) -> None:
    assert _judged(project, "# Methods\n\nWe used the Beck Depression Inventory (BDI).\n\n# "
                            "Results\n\n| Score | n |\n|---|---|\n| 12 | 40 |\n\n*Note.* BDI = "
                            "Beck Depression\nInventory.\n\nThe BDI was low.\n") == []


def test_a_pdf_s_note_wrapped_line_by_line_restates(tmp_path: Path, capsys) -> None:
    """The same note in a PDF, a line of it to a line of the page (round 2 of #698)."""
    from manuscript_guard.cli import main

    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext is not installed")
    lines = ["A study of things", "Methods", "We used the Beck Depression Inventory (BDI).",
             "Results", "Note. BDI = Beck Depression", "Inventory.", "The BDI was low."]
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(typeset(lines, columns=1, per_column=40, head="Journal of Things",
                              foot="Page", first_page=1))  # fmt: skip
    assert main(["audit", str(paper), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    said = [f["message"] for f in report["findings"] if f["code"].startswith("abbreviation-")]
    assert not [message for message in said if "BDI" in message], said


def test_a_heading_defines_in_the_supplement(project: Path) -> None:
    """Every feature covers the supplement: a heading's definition counts in its main text as
    in the paper's (round 2 of #698)."""
    folder = project / "manuscript" / "supplementary"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    (folder / "S1.md").write_text("# Methods\n\n## Grip strength and electromyography (EMG)\n\n"
                                  "The EMG was read.\n", encoding="utf-8")  # fmt: skip
    report = check_language(load_project(project)[0])
    found = unasked(list(report.findings))
    assert not [f.message for f in found if f.message.startswith("EMG ")], [
        f.message for f in found]


def test_a_heading_with_no_named_section_over_it_defines_nothing(tmp_path: Path) -> None:
    """Basile, 2026-11-16, "Only under a named section": a heading defines only under one
    that names a section; "\\section{Data from the Sloan Sky Survey (SSS)}" with nothing
    over it defines nothing, as before #698, and neither does a title."""
    (tmp_path / "sections").mkdir()
    (tmp_path / "main.tex").write_text(_latex("\\section{Introduction}\nWe read it.\n\n"
                                              "\\input{sections/data}\n"), encoding="utf-8")
    (tmp_path / "sections" / "data.tex").write_text(
        "\\section{Data from the Sloan Sky Survey (SSS)}\n\\subsection{Background}\n"
        "The SSS was read.\n", encoding="utf-8")
    assert not [one for read in _latex_read(tmp_path, None) for one in read.definitions]
    root = tmp_path / "front"
    root.mkdir()
    (root / "main.tex").write_text(_latex("\\input{front}\n\\input{body}\n"), encoding="utf-8")
    (root / "front.tex").write_text("\\section*{Proton pump inhibitor (PPI) use in older "
                                    "adults}\n\\section{Introduction}\n", encoding="utf-8")
    (root / "body.tex").write_text("The PPI was read.\n", encoding="utf-8")
    assert not [one for read in _latex_read(root, None) for one in read.definitions]


@pytest.mark.parametrize("label", ["RESULT:", "**RESULT:**", "Result:"])
def test_a_section_s_name_before_a_colon_is_a_label(label: str) -> None:
    """A name on the closed list of section names before a colon (`SECTION_NAMES`), a
    structured abstract's label, is never a short form, though the words after it hold its
    letters (round 1 of #698)."""
    read = _file(0, Path("main.md"), f"{label} Rates Eased Slowly Until Late Testing.\n", [],
                 False)  # fmt: skip
    assert read.definitions == [], read.definitions


def test_a_bracket_s_short_form_before_a_typed_citation_defines() -> None:
    """The readers agree (round 1 of #698): what pandoc's `[SDSS DR15; @york2000]` defines, the
    .docx or PDF of the same paper prints "(SDSS DR15; York et al., 2000)", an author-year
    citation after the separator as the typed-citation reading knows one; other words after
    it are no citation."""
    for text, defined in (("the Sloan Sky Survey (SSS DR2; York et al., 2000)", ["SSS"]),
                          ("the Sloan Sky Survey (SSS DR2; York, 2000; Lee, 2001)", ["SSS"]),
                          ("the Sloan Sky Survey (SSS DR2; see the appendix)", []),
                          ("the Sloan Sky Survey (SSS DR2; 12)", [])):  # fmt: skip
        read = _file(0, Path("main.md"), f"{text}\n", [], False)
        assert [short for _at, short, _long in read.definitions] == defined, text


def test_a_line_break_in_a_bracket_is_a_space() -> None:
    """A PDF wraps "(CL\\nAGNs)", which the .docx of the paper holds on one line (round 1 of
    #698)."""
    read = _file(0, Path("main.md"), "the changing-look AGNs (CL\nAGNs) rose\n", [], False)
    assert [short for _at, short, _long in read.definitions] == ["CL"], read.definitions


def test_a_colon_that_introduces_words_with_the_letters_defines() -> None:
    """Known gaps, held where it stands (docx-educ-B1): a colon before words that begin with
    the short form's letters is read as a definition, though it introduces them, where no
    bracket after them defines a short form of its own; so is a label in capitals before a
    sentence that holds its letters in order."""
    for text, short in (("the latest of the TVMs: Teacher Video Modules Plus (see below)", "TVM"),
                        ("NOTE: Never Omit The End", "NOTE")):  # fmt: skip
        read = _file(0, Path("main.md"), f"{text}\n", [], False)
        assert short in [found for _at, found, _long in read.definitions], (text, read.definitions)


@pytest.mark.parametrize(
    ("text", "defined"),
    [("the latest of the TVMs: Teacher Video Modules Plus (TVM-P)",
      [("TVM-P", "Teacher Video Modules Plus")]),
     ("the latest of the TVMs: Teacher Video Modules (TVM, TVM-S)",
      [("TVM", "Teacher Video Modules"), ("TVM-S", "Teacher Video Modules")]),
     ("Note. GDS = Geriatric Depression Scale (GDS) and more",
      [("GDS", "Geriatric Depression Scale")]),
     ("the latest of the TVMs: Teacher Video Modules Plus [TVM-P]",
      [("TVM-P", "Teacher Video Modules Plus")]),
     # A bracket after the words that defines nothing leaves the pair as it was.
     ("the TVMs: Teacher Video Modules (2019)", [("TVM", "Teacher Video Modules")])],
)  # fmt: skip
def test_a_bracket_after_a_colon_pair_s_long_form_wins(
    text: str, defined: list[tuple[str, str]]
) -> None:
    """docx-educ-B1, closed (Basile, 2026-11-21, "Bracket wins"): where a bracket defines a
    short form right after its long form, alone or in a list, round or square, that
    definition wins over a colon pair or an equals sign's the same words could make, which
    defined CAP a second time beside CAP-PD."""
    read = _file(0, Path("main.md"), f"{text}\n", [], False)
    assert sorted((short, long) for _at, short, long in read.definitions) == sorted(defined)


def test_a_slash_in_a_bracket_pairs_nothing() -> None:
    """Known gaps (pdf-med-B2): short forms a slash joins are paired only after a sign, so
    "depersonalisation/derealisation (DP/DR)" defines neither; nor does a bracket whose list
    holds more than short forms, "(i.e., CAP-PD, CAP-T)"."""
    for text in ("the depersonalisation/derealisation (DP/DR)",
                 "the Content Acquisition Podcasts Teacher (i.e., CAP-PD, CAP-T)"):  # fmt: skip
        read = _file(0, Path("main.md"), f"{text}\n", [], False)
        assert read.definitions == [], (text, read.definitions)


def _latex(body: str) -> str:
    return f"\\documentclass{{article}}\n\\begin{{document}}\n{body}\n\\end{{document}}\n"


@pytest.mark.parametrize(("sentence", "short", "defines"), CITED)
def test_a_latex_citation_s_optional_argument_defines_after_its_long_form(
    tmp_path: Path, sentence: str, short: str, defines: bool
) -> None:
    (tmp_path / "main.tex").write_text(_latex(f"\\section{{Methods}}\n{sentence}\n"),
                                       encoding="utf-8")  # fmt: skip
    defined = {found for read in _latex_read(tmp_path, None)
               for _at, found, _long in read.definitions}  # fmt: skip
    assert (short in defined) is defines, defined


def test_a_citation_whose_note_follows_other_words_defines_nothing(tmp_path: Path) -> None:
    """The note has to open with the short form, as a bracket does: `\\citep[see WISE][]`
    defines nothing."""
    (tmp_path / "main.tex").write_text(_latex(
        "\\section{Methods}\nWe used the Wide Infrared Sky Explorer \\citep[see WISE][]{w}.\n"),
        encoding="utf-8")  # fmt: skip
    defined = {found for read in _latex_read(tmp_path, None)
               for _at, found, _long in read.definitions}  # fmt: skip
    assert "WISE" not in defined, defined


def test_a_latex_heading_defines(tmp_path: Path) -> None:
    """docx-sport-A3's shape in LaTeX: `\\subsection{Force and electromyography (EMG)}`."""
    (tmp_path / "main.tex").write_text(_latex(
        "\\section{Methods}\n\\subsection{Grip strength and electromyography (EMG)}\n"
        "The EMG was read.\n"), encoding="utf-8")
    defined = [found for read in _latex_read(tmp_path, None)
               for _at, found, _long in read.definitions]  # fmt: skip
    assert defined == ["EMG"], defined


# ---------------------------------------------------------------------------- check


def _check(project: Path) -> set[str]:
    report = check_language(load_project(project)[0])
    return _undefined([f.message for f in unasked(list(report.findings))
                       if f.code == "abbreviation-undefined"])


def test_check_reads_each_shape_in_a_markdown_project(project: Path) -> None:
    pieces, shorts, undefined = _all_shapes()
    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(_markdown(pieces, shorts), encoding="utf-8")
    assert _check(project) == undefined


def _latex_body(pieces: list[str], shorts: list[str]) -> str:
    """The pieces as LaTeX: a Markdown heading a `\\subsection`, the rest a paragraph."""
    written = [f"\\subsection{{{piece[3:]}}}" if piece.startswith("## ") else piece
               for piece in pieces]  # fmt: skip
    cited = [sentence for sentence, _short, _defines in CITED]
    body = "\n\n".join([*written, *cited])
    return f"\\section{{Methods}}\n{body}\n\n\\section{{Results}}\n{_uses(shorts)}\n"


def _latex_shapes() -> tuple[str, set[str]]:
    pieces, shorts, undefined = _all_shapes()
    shorts += [short for _sentence, short, _defines in CITED]
    undefined |= {short for _sentence, short, defines in CITED if not defines} | CITED_UNDEFINED
    return _latex(_latex_body(pieces, shorts)), undefined


def test_check_reads_each_shape_in_a_latex_project(project: Path) -> None:
    text, undefined = _latex_shapes()
    shutil.rmtree(project / "manuscript")
    (project / "manuscript").mkdir()
    (project / "manuscript" / "main.tex").write_text(text, encoding="utf-8")
    assert _check(project) == undefined


# ---------------------------------------------------------------------------- audit


def _audited(paper: Path, capsys) -> set[str]:
    from manuscript_guard.cli import main

    assert main(["audit", str(paper), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    listed = [f for f in report["findings"] if f["code"] == "abbreviation-undefined"]
    return {form["form"] for finding in listed for form in finding.get("forms", ())}


def test_the_audit_reads_each_shape_in_markdown(tmp_path: Path, capsys) -> None:
    pieces, shorts, undefined = _all_shapes()
    paper = tmp_path / "paper.md"
    paper.write_text(_markdown(pieces, shorts), encoding="utf-8")
    assert _audited(paper, capsys) == undefined


def test_the_audit_reads_each_shape_in_latex(tmp_path: Path, capsys) -> None:
    text, undefined = _latex_shapes()
    paper = tmp_path / "main.tex"
    paper.write_text(text, encoding="utf-8")
    assert _audited(paper, capsys) == undefined


NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
STYLES = ('<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
          '</w:style><w:style w:type="paragraph" w:styleId="Heading2">'
          '<w:name w:val="heading 2"/></w:style>')  # fmt: skip


def _paragraph(text: str, style: str = "") -> str:
    styled = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;")
    return f'<w:p>{styled}<w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>'


def _docx(path: Path, paragraphs: list[str]) -> Path:
    parts = {**word_package("".join(paragraphs)),
             "word/styles.xml": f"<w:styles {NS}>{STYLES}</w:styles>"}  # fmt: skip
    with zipfile.ZipFile(path, "w") as archive:
        for name, part in parts.items():
            archive.writestr(name, part)
    return path


def test_the_audit_reads_each_shape_in_a_docx(tmp_path: Path, capsys) -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc is not installed")
    pieces, shorts, undefined = _all_shapes()
    paragraphs = [_paragraph("Methods", "Heading1")]
    for piece in pieces:
        heading = piece.startswith("## ")
        paragraphs.append(_paragraph(piece[3:] if heading else piece,
                                     "Heading2" if heading else ""))  # fmt: skip
    paragraphs += [_paragraph("Results", "Heading1"), _paragraph(_uses(shorts))]
    assert _audited(_docx(tmp_path / "paper.docx", paragraphs), capsys) == undefined


def test_the_audit_reads_each_shape_but_a_heading_in_a_pdf(tmp_path: Path, capsys) -> None:
    """A PDF's headings are its sections' names (`auditing.pdf.HEADINGS`), so a heading's
    definition is a line of text there, read as one: the heading shape is left out."""
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext is not installed")
    kept = [each for each in (*DEFINING, *NOT_DEFINING) if each[0] != "a heading"]
    pieces = [sentence for _kind, sentence, _short in kept]
    shorts = [short for _kind, _sentence, short in kept]
    undefined = {short for kind, _sentence, short in NOT_DEFINING if kind != "a heading"}
    lines = ["A study of things", "Methods", *pieces, "Results", _uses(shorts)]
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(typeset(lines, columns=1, per_column=40, head="Journal of Things",
                              foot="Page", first_page=1))  # fmt: skip
    assert _audited(paper, capsys) == undefined
