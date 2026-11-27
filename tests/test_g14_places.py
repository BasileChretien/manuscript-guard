"""G14 asks no definition of a short form found only where none is due (decision 28).

Basile, 2026-11-16, after the real-paper corpus: a short form that stands only on the title
page (title, authors, affiliations), in the statements (acknowledgements, funding,
contributions, competing interests, data availability), in a keywords or Index Terms line,
or in a line a PDF repeats at the top or the foot of most of its pages asks no definition
and counts no use. One the paper's text uses too is asked about as before, its uses in those
places counted for nothing, and a use there before the text defines it is no use before the
definition. "Redefined" and "unused" are as they were.

Each shape is a corpus case written fresh (tex-astro-ga-A1 and -B1, docx-psych-A1, pdf-med-B2,
pdf-educ-A1 and -B2, tex-cs-lg-B2, tex-astro-ga-A2), read by the audit and by `check`.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from manuscript_guard.auditing.undefined import unasked
from manuscript_guard.cli import main
from manuscript_guard.contracts.project import Project
from manuscript_guard.gates import check_language

sys.path.insert(0, str(Path(__file__).parent))
from proof_pdf import typeset  # noqa: E402

# The loopback registries, standing in for Crossref, OpenAlex and PubMed.
from test_audit_sections import registries  # noqa: E402, F401

needs_pdftotext = pytest.mark.skipif(shutil.which("pdftotext") is None,
                                     reason="pdftotext is not installed")  # fmt: skip

#: A paper as Markdown writes one converted from Word: a title page whose second line reads as
#: prose, so that G14's title page (`text/title_page.py`) finds none, ending at the Abstract;
#: a keywords line and an Index Terms line after it; a funding statement and a data
#: availability statement run in from their labels; and the acknowledgements under their
#: heading. UPV and
#: SDR stand on the title page, LLM and KRT in the keywords, MB and the NRC in the
#: acknowledgements, FWO in the funding statement and DANS in the data availability's. The text
#: defines SDR after the title uses it, and uses KRT and QXV undefined.
MARKDOWN = """\
The SDR of exam success at Rouen

This version of the manuscript is under review at a journal.

Ana Martin, Department of Pharmacology, UPV, Rouen, France

# Abstract

We read the exam results of 412 students.

**Keywords:** LLM; KRT; exams

Index Terms\N{EM DASH}LLM, exams

# Introduction

The signal detection ratio (SDR) was computed. The SDR rose.

# Results

The KRT rose, and the QXV fell.

# Discussion

It held.

**Funding:** The FWO paid for the survey.

**Data availability:** The data are held by DANS.

# Acknowledgements

We thank MB for her help, and the NRC for its support.
"""

#: What G14 reports of `MARKDOWN`: KRT once, its keywords use counted for nothing, and QXV.
ASKED = ["KRT is used once in the main text as G14 reads it, and not defined there",
         "QXV is used once in the main text as G14 reads it, and not defined there"]  # fmt: skip
#: The short forms that stand only where no definition is due.
NOT_ASKED = ("UPV", "LLM", "MB", "NRC", "FWO", "DANS", "SDR")


def checked(tmp_path: Path, files: dict[str, str]) -> list[tuple[str, str]]:
    """G14's abbreviation findings as `check` gives them on a manuscript of `files`, its
    question on the short forms never defined as the warning it holds on each (decision 30)."""
    root = tmp_path / "project"
    for name, text in files.items():
        path = root / "manuscript" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    report = check_language(Project(root=root, paper={}, authors=None))
    return sorted((f.code, f.message) for f in unasked(list(report.findings))
                  if f.code.startswith("abbreviation"))  # fmt: skip


def audited(capsys, paper: Path) -> list[tuple[str, str]]:
    """G14's abbreviation findings as the audit gives them, each undefined form its own."""
    assert main(["audit", str(paper), "--json"]) in (0, 1)
    report = json.loads(capsys.readouterr().out)
    found = []
    for finding in report["findings"]:
        if not finding["code"].startswith("abbreviation"):
            continue
        forms = finding.get("forms") or [{"message": finding["message"]}]
        found += [(finding["code"], form["message"]) for form in forms]
    return sorted(found)


def test_check_asks_nothing_where_no_definition_is_due(tmp_path: Path) -> None:
    found = checked(tmp_path, {"main.md": MARKDOWN})
    assert [message for code, message in found if code == "abbreviation-undefined"] == ASKED
    assert not [message for _code, message in found
                if message.split()[0] in NOT_ASKED], found  # fmt: skip


def test_the_audit_asks_nothing_where_no_definition_is_due(
    tmp_path: Path, capsys, registries  # noqa: F811
) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(MARKDOWN, encoding="utf-8")
    found = audited(capsys, paper)
    assert [message for code, message in found if code == "abbreviation-undefined"] == ASKED
    assert not [message for _code, message in found
                if message.split()[0] in NOT_ASKED], found  # fmt: skip


def test_a_use_on_the_title_page_is_no_use_before_the_definition(tmp_path: Path) -> None:
    """The title uses SDR, which the Introduction defines: no use before the definition
    (tex-astro-ga-A2's AGN, tex-astro-ga-B1's JWST). A use in the Introduction before it is
    one, as before."""
    found = checked(tmp_path, {"main.md": MARKDOWN})
    assert not [m for code, m in found if code == "abbreviation-used-before-defined"], found
    early = MARKDOWN.replace("The signal detection ratio (SDR) was computed. The SDR rose.",
                             "The SDR was computed. The signal detection ratio (SDR) rose.")
    found = checked(tmp_path / "early", {"main.md": early})
    assert ("abbreviation-used-before-defined",
            "SDR is used here, and defined later on the same line") in found, found


def test_a_short_form_also_used_in_the_text_is_asked_as_before(tmp_path: Path) -> None:
    """Each place's short form, used undefined in the Results too, is asked there, counted
    once: its uses in those places count for nothing."""
    for short in NOT_ASKED[:-1]:
        text = MARKDOWN.replace("and the QXV fell.", f"and the {short} fell.")
        found = checked(tmp_path / short, {"main.md": text})
        assert ("abbreviation-undefined", f"{short} is used once in the main text as G14 "
                "reads it, and not defined there") in found, (short, found)


def test_unused_and_redefined_are_as_before(tmp_path: Path) -> None:
    """A definition the acknowledgements give, of a funder named once, is never unused, as
    before; one the text gives and only the acknowledgements use again is used, as before;
    and one given in the text and again in a statement is given twice, as before."""
    text = MARKDOWN.replace("The KRT rose", "The reporting odds ratio (ROR) and the KRT rose"
                            ).replace("MB for her help", "MB for the ROR").replace(
        "the NRC for its support", "the National Research Council (NRC) for its support "
        "and the signal detection ratio (SDR)")  # fmt: skip
    found = checked(tmp_path, {"main.md": text})
    assert not [m for code, m in found if code == "abbreviation-unused"], found
    assert [m.split()[0] for code, m in found if code == "abbreviation-redefined"] == ["SDR"]


@pytest.mark.parametrize("text, expected", [
    ("The QXZ fell in 412 students.\n\n# Methods\n\nWe read the records.\n",
     ("abbreviation-undefined", "QXZ is used once in the main text as G14 reads it, and not "
      "defined there")),
    ("The QXZ fell.\n\n# Methods\n\nThe quality index (QXZ) was read.\n",
     ("abbreviation-undefined", "QXZ is used 2 times in the main text as G14 reads it, and "
      "not defined there")),
], ids=["used once", "used again under a heading"])  # fmt: skip
def test_with_no_abstract_named_there_is_no_title_page(
    tmp_path: Path, text: str, expected: tuple[str, str]
) -> None:
    """Basile, 2026-11-16, "No title page there": where neither a heading nor a block G14
    reads as naming the Abstract names it, there is no title page, and the text before the
    first heading is read as before (round 1 of #699)."""
    assert checked(tmp_path, {"main.md": text}) == [expected]


def test_a_file_that_opens_on_the_abstract_s_bold_line_has_no_title_page(tmp_path: Path) -> None:
    """A file with no heading that opens on "**Abstract**" holds no title page, nor makes one
    of itself for the file after it, in the paper and in the supplement (round 1 of #699)."""
    found = checked(tmp_path, {
        "01_abstract.md": "**Abstract**\n\nThe QXZ fell in 412 students.\n",
        "02_main.md": "# Introduction\n\nWe read the records.\n",
        "supplementary/S1.md": "**Abstract**\n\nThe QXY fell in 12 schools.\n",
        "supplementary/S2.md": "# Methods\n\nWe read the records.\n",
    })  # fmt: skip
    assert sorted(message.split()[0] for code, message in found
                  if code == "abbreviation-undefined") == ["QXY", "QXZ"], found  # fmt: skip


def test_a_bold_or_run_in_abstract_line_ends_a_title_page(tmp_path: Path) -> None:
    """The Abstract named by a bold line or a run-in label, as G14's title page reads one,
    ends a title page as a heading does; its own text is read."""
    title = "The SDR of exams\n\nThis version is under review.\n\nAna Martin, UPV, Rouen\n\n"
    for at, opening in enumerate(("**Abstract**\n\nThe QXZ fell.", "Abstract: The QXZ fell.")):
        text = title + opening + "\n\n# Introduction\n\nWe read the records.\n"
        found = checked(tmp_path / str(at), {"main.md": text})
        assert [m.split()[0] for code, m in found
                if code == "abbreviation-undefined"] == ["QXZ"], (opening, found)  # fmt: skip


def test_a_statement_s_label_in_plain_type_opens_it(tmp_path: Path) -> None:
    """A run-in label of a statement in plain type, as a PDF's text has every one, at a
    paragraph's start and with its colon: "Funding:", "Data Availability Statement:". Not
    a statement's word inside a sentence (round 1 of #699)."""
    text = ("# Introduction\n\nWe read the records.\n\nFunding: The QXF paid for it.\n\n"
            "Data Availability Statement: The QXD holds the data.\n\n"
            "We thank them. Funding: the QXG paid little.\n")  # fmt: skip
    found = checked(tmp_path, {"main.md": text})
    assert [m.split()[0] for code, m in found if code == "abbreviation-undefined"] == ["QXG"]


def test_a_word_that_begins_with_keyword_opens_no_keywords_line(tmp_path: Path) -> None:
    """ "Keyword-based retrieval used the QXZ index." is the Methods' sentence; a keywords
    line is "Keywords", "Key words" or "Index Terms" then a colon, a spaced dash or an em
    dash, at a paragraph's start (round 1 of #699)."""
    text = ("# Methods\n\nKeyword-based retrieval used the QXZ index.\n\n"
            "We read it. Keywords: the QXY was searched.\n\nKeywords - QXW; falls\n")
    found = checked(tmp_path, {"main.md": text})
    assert [m.split()[0] for code, m in found
            if code == "abbreviation-undefined"] == ["QXY", "QXZ"], found  # fmt: skip


LATEX = r"""\documentclass{aastex631}
\begin{document}
\title{The SDR of exam success}
\author{Ana Martin}
\affiliation{UPV, Rouen}
\begin{abstract}
We read the exam results of 412 students.

\textit{Keywords} --- LLM, KRT, exams
\end{abstract}
\section{Introduction}
The signal detection ratio (SDR) was computed. The SDR rose.
\section{Results}
The KRT rose, and the QXV fell.
\begin{acknowledgements}
The NRC supported this work.
\end{acknowledgements}
\acknowledgments
MB acknowledges the FWO.
\end{document}
"""


def test_check_reads_a_latex_paper_s_places(tmp_path: Path) -> None:
    """The title before the abstract, a keywords line in it, the acknowledgements typed as an
    environment and as AASTeX's `\\acknowledgments` (tex-astro-ga-A1's MB, tex-astro-ga-B1's
    NRC, tex-cs-lg-B2's LLM)."""
    found = checked(tmp_path, {"main.tex": LATEX})
    assert [m for code, m in found if code == "abbreviation-undefined"] == ASKED, found
    assert not [m for _code, m in found if m.split()[0] in NOT_ASKED], found


def test_the_audit_reads_a_latex_paper_s_places(
    tmp_path: Path, capsys, registries  # noqa: F811
) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(LATEX, encoding="utf-8")
    found = audited(capsys, paper)
    assert [m for code, m in found if code == "abbreviation-undefined"] == ASKED, found
    assert not [m for _code, m in found if m.split()[0] in NOT_ASKED], found


def test_a_latex_statement_in_a_comment_is_read_as_before(tmp_path: Path) -> None:
    """`\\acknowledgments` in a comment opens nothing: the text after it is the Results'."""
    text = LATEX.replace("\\acknowledgments\n", "% \\acknowledgments\n")
    found = checked(tmp_path, {"main.tex": text})
    assert ("abbreviation-undefined",
            "MB is used once in the main text as G14 reads it, and not defined there") in found


#: A PDF's text, five pages of eight lines: a title page whose affiliations name VIC and UPV,
#: before the Abstract; and an all-capitals line, the paper's running head, at the top of
#: pages 2 and 4 and at the foot of pages 3 and 5, which no running head on one side of half
#: the pages is, so that it is read as text (`proof.reading`). FORUMS and SOCIAL stand only
#: there; ONLINE is used in the Results too, and asked about, once.
_HEAD = "SOCIAL FORUMS ONLINE"


def _pages() -> list[str]:
    def filler(*words: str) -> list[str]:
        return [f"The {word} was read in full." for word in words]

    page1 = ["Talk in forums: a study", "Ana Martin, Monash University, Clayton, VIC 3800",
             "Paul Girard, UPV, San Sebastian", "Abstract", "We read 412 forums.",
             "Introduction", "Forums matter.", "They were read."]  # fmt: skip
    page2 = [_HEAD, "Methods", *filler("cohort", "record", "survey", "file"),
             "The QXV was read.", "It was read once."]  # fmt: skip
    page3 = ["Results", *filler("sample", "series", "table", "count"),
             "The ONLINE cohort rose.", "It rose twice.", _HEAD]  # fmt: skip
    page4 = [_HEAD, "Discussion", *filler("forum", "thread", "post", "reply"), "It held.",
             "It held again."]  # fmt: skip
    page5 = [*filler("limit", "bias", "gap", "flaw"), "It ends here.", "Nothing more.",
             "The end.", _HEAD]  # fmt: skip
    return [*page1, *page2, *page3, *page4, *page5]


@needs_pdftotext
def test_the_audit_asks_nothing_of_a_pdf_s_title_page_and_running_line(
    tmp_path: Path, capsys, registries  # noqa: F811
) -> None:
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(typeset(_pages(), columns=1, per_column=8))
    found = audited(capsys, paper)
    said = {message.split()[0]: message for code, message in found
            if code == "abbreviation-undefined"}  # fmt: skip
    assert sorted(said) == ["ONLINE", "QXV"], found
    assert said["ONLINE"].startswith("ONLINE is used once in the main text"), said


@needs_pdftotext
def test_a_line_repeated_on_fewer_than_half_the_pages_is_read(
    tmp_path: Path, capsys, registries  # noqa: F811
) -> None:
    """A running line on two of the five pages is read as text, as before (DESIGN.md, Known
    gaps): tex-astro-ga-B2's "MNRAS 000, 1-16 (2025)" on even pages only."""
    lines = _pages()
    for at in sorted((at for at, line in enumerate(lines) if line == _HEAD), reverse=True)[:2]:
        lines[at] = "It was read."
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(typeset(lines, columns=1, per_column=8))
    said = {message.split()[0] for code, message in audited(capsys, paper)
            if code == "abbreviation-undefined"}  # fmt: skip
    assert {"SOCIAL", "FORUMS"} <= said, said


#: Letters to tell lines apart by, since a repeated line's digits are read alike.
_LETTERS = "abcdefghij"


def test_a_pdf_s_repeated_lines_are_those_at_the_edges_of_half_its_pages() -> None:
    """`PdfText.repeated`: the line at an edge, its spaces made one, on half the pages or
    more and on three at least; not one standing amid a page's lines."""
    from manuscript_guard.auditing.pdf import PdfText, Place

    def page(number: int, head: int) -> list[str]:
        lines = [f"line {_LETTERS[number]}{_LETTERS[at]}" for at in range(9)]
        return [*lines[:head], "HEAD  ONE" if number == 1 else "HEAD ONE", *lines[head:]]

    pages = [page(1, 0), page(2, 1), page(3, 9), page(4, 5)]
    texts = [text for page in pages for text in page]
    places = tuple(Place(page, line) for page, lines in enumerate(pages, 1)
                   for line in range(1, len(lines) + 1))  # fmt: skip
    pdf = PdfText(Path("p.pdf"), "pdftotext", 4, "\n".join(texts), places)
    # The three at an edge; not the one amid page 4's lines.
    assert sorted(pdf.repeated) == [1, 12, 30]
    # Three pages of eight are fewer than half.
    assert not PdfText(Path("p.pdf"), "pdftotext", 8, "\n".join(texts), places).repeated


def test_a_running_line_s_page_number_is_read_as_any_number() -> None:
    """ "QXH 2", "QXH 3" ...: a running line that holds the page's number is one line, each
    run of digits read alike; the same shape amid a page's lines is no running line (round 1
    of #699)."""
    from manuscript_guard.auditing.pdf import PdfText, Place

    pages = [[f"line {_LETTERS[page]}{_LETTERS[at]}" for at in range(9)] for page in range(1, 5)]
    pages[0].insert(0, "QXH 1")
    pages[1].insert(0, "QXH 2")
    pages[2].append("QXH 3")
    pages[3].insert(5, "QXH 4")
    texts = [text for page in pages for text in page]
    places = tuple(Place(page, line) for page, lines in enumerate(pages, 1)
                   for line in range(1, len(lines) + 1))  # fmt: skip
    pdf = PdfText(Path("p.pdf"), "pdftotext", 4, "\n".join(texts), places)
    assert sorted(texts[line - 1] for line in pdf.repeated) == ["QXH 1", "QXH 2", "QXH 3"]


def test_a_running_line_with_its_page_number_inside_it_is_one() -> None:
    """ "QXH Journal | Page 3 of 12" at the top of pages 3 to 6: each run of digits read alike,
    in the line's middle too (Basile, 2026-11-16, round 3 of #699)."""
    from manuscript_guard.auditing.pdf import PdfText, Place

    pages = [[f"line {_LETTERS[page]}{_LETTERS[at]}" for at in range(9)] for page in range(6)]
    for page in range(2, 6):
        pages[page].insert(0, f"QXH Journal | Page {page + 1} of 12")
    texts = [text for page in pages for text in page]
    places = tuple(Place(page, line) for page, lines in enumerate(pages, 1)
                   for line in range(1, len(lines) + 1))  # fmt: skip
    pdf = PdfText(Path("p.pdf"), "pdftotext", 6, "\n".join(texts), places)
    assert sorted(texts[line - 1] for line in pdf.repeated) == [
        f"QXH Journal | Page {page} of 12" for page in range(3, 7)]


def test_digits_inside_a_line_are_its_own() -> None:
    """A supplement whose pages each end on their figure's caption, "Figure S1. ROC of the
    GBM model, fold 1", "Figure S2 ... fold 2": no running line, a line with a caption's shape
    never one (round 3 of #699)."""
    from manuscript_guard.auditing.pdf import PdfText, Place

    pages = [[*(f"line {_LETTERS[page]}{_LETTERS[at]}" for at in range(9)),
              f"Figure S{page}. ROC of the GBM model, fold {page}"] for page in range(1, 5)]
    texts = [text for page in pages for text in page]
    places = tuple(Place(page, line) for page, lines in enumerate(pages, 1)
                   for line in range(1, len(lines) + 1))  # fmt: skip
    assert not PdfText(Path("p.pdf"), "pdftotext", 4, "\n".join(texts), places).repeated


# --------------------------------------------- the limits of round 1's reading (round 3 of #699)


def test_a_statement_s_name_in_plain_type_opens_one_wherever_it_stands(tmp_path: Path) -> None:
    """A label in plain type that names a statement opens one at any paragraph's start, in the
    paper's own text too: a Methods' "Data access: ..." and a Discussion's "Funding: ..."
    ask nothing (DESIGN.md, Known gaps; rounds 2 and 3 of #699 tried narrower rules and were
    put back)."""
    text = ("# Methods\n\nData access: records came from the QXS.\n\n# Discussion\n\n"
            "Funding: the QXG study paid little.\n\nIt held.\n")  # fmt: skip
    assert checked(tmp_path, {"main.md": text}) == []


def test_a_keywords_line_is_read_at_a_paragraph_s_start_only(tmp_path: Path) -> None:
    """A keywords line on the line after the Abstract's last, one line break between, is read
    as the Abstract's text; a paragraph of prose that opens on "keywords:" is a keywords line
    (DESIGN.md, Known gaps)."""
    found = checked(tmp_path, {"main.md": "# Abstract\n\nWe read records.\nKeywords: QXK; falls"
                                          "\n\n# Methods\n\nIt held.\n"})  # fmt: skip
    assert [m.split()[0] for code, m in found] == ["QXK"], found
    found = checked(tmp_path / "prose", {"main.md": "# Methods\n\nkeywords: the QXA terms came "
                                                    "first, and the rest after.\n"})  # fmt: skip
    assert found == [], found


def test_the_first_opening_block_alone_decides_the_title_page(tmp_path: Path) -> None:
    """The first block that opens the paper decides: "**Key points**" before the heading that
    names the Abstract leaves no title page, and a protocol's "**Abstract**" under a
    supplement's first heading makes one of all before it (DESIGN.md, Known gaps)."""
    text = ("The SDR of exams\n\nThis version is under review.\n\nAna Martin, UPV, Rouen\n\n"
            "**Key points**\n\nThe exams rose.\n\n# Abstract\n\nWe read records.\n")
    found = checked(tmp_path, {"main.md": text})
    assert [m.split()[0] for code, m in found] == ["SDR", "UPV"], found
    found = checked(tmp_path / "supplement", {
        "main.md": "# Introduction\n\nWe read the records.\n",
        "supplementary/S1.md": "# Supplementary Table S1\n\nThe QXT rose.\n\n**Abstract**\n\n"
                               "Protocol text.\n"})  # fmt: skip
    assert found == [], found


def test_mdpi_s_abbreviations_before_the_references(tmp_path: Path) -> None:
    """MDPI's order: the statements in plain type after the Conclusions, then "Abbreviations:"
    with its list, then the references. Each statement asks nothing; the list's lines define
    as a list's do, so a short form the text uses before only the list spells it out is
    reported as such (DESIGN.md, Known gaps)."""
    text = ("# Introduction\n\nThe QXL rose.\n\n# Conclusions\n\nIt held.\n\n"
            "Funding: The QXF paid for it.\n\nAbbreviations: The following abbreviations are "
            "used in this manuscript:\n\nQXL: quality index\n\n# References\n\nA. 2020.\n")
    assert checked(tmp_path, {"main.md": text}) == [(
        "abbreviation-used-before-defined", "QXL is used here and not spelt out; only the list "
        "of abbreviations defines it, at manuscript/main.md:13")]


# ------------------------------------------------ a Word paper's bold headings (2026-11-27)


def test_a_short_paragraph_wholly_in_bold_owes_no_definition_and_is_a_use(tmp_path: Path) -> None:
    """Decision D5 (docx-educ-B1): a heading typed in Word as a paragraph in bold, "**QPS**"
    over the sentence that defines it, owes no definition, as a heading made with a style
    does, and is still a use, so a form used again only there is not unused. A paragraph in
    bold longer than 150 characters, and a word in bold inside a sentence, are text."""
    long = ("**The QPS results of each of the classes of the second year of the study were read "
            "again by a second reader who did not know which class each of them came from**")
    assert len(long) > 150
    text = ("# Methods\n\n**QPS**\n\nThe quiet play scale (QPS) was read. The QPS rose.\n\n"
            "The quiet zone time (QZT) was set.\n\n**QZT**\n\n# Results\n\nIt held.\n")
    assert checked(tmp_path, {"main.md": text}) == []
    # A limit written down in DESIGN.md's Known gaps: a short sentence in bold is a heading.
    text = ("# Methods\n\n**The QPS rose.**\n\nThe quiet play scale (QPS) was read. The QPS "
            "rose.\n")  # fmt: skip
    assert checked(tmp_path, {"main.md": text}) == []
    for early in (long, "The **QPS** rose in the first class."):
        text = (f"# Methods\n\n{early}\n\nThe quiet play scale (QPS) was read. The QPS "
                "rose.\n")
        assert [code for code, _message in checked(tmp_path, {"main.md": text})] == [
            "abbreviation-used-before-defined"], early


# ------------------------------------------- a citation's author typed as text (2026-11-27)


def test_a_citation_s_author_owes_no_definition_and_is_a_use(tmp_path: Path) -> None:
    """docx-pharm-epi-A1: "(Kaye et al. 2009, NIH 2016a, NIH 2016b)", author-year citations a
    comma divides, and "(QXW, 2016)" name their authors, which owe no definition there: NIH
    defined later says nothing of them. A form defined and then cited only as an author,
    "(APA, 2020)", is used. "the NIH 2016 guidelines" in a sentence still owes one."""
    text = ("# Introduction\n\nRules were set (Kaye et al. 2009, NIH 2016a, NIH 2016b), and "
            "kept (QXW, 2016).\n\n# Methods\n\nThe National Institutes of Health (NIH) paid. "
            "The NIH rose. The American Psychological Association (APA) set the style (APA, "
            "2020).\n")
    assert checked(tmp_path, {"main.md": text}) == []
    text = ("# Introduction\n\nThe NIH 2016 guidelines were kept.\n\n# Methods\n\nThe National "
            "Institutes of Health (NIH) paid. The NIH rose.\n")
    assert [code for code, _message in checked(tmp_path, {"main.md": text})] == [
        "abbreviation-used-before-defined"]
    # Round 1 of #838: a bracket of years that is no list of citations owes a definition.
    for bracket in ("(NIH 1850, 2010)", "(NIH-10 2019, DSM-5 2013)",
                    "(Kaye 2009, NIH 2016 and 2017)"):
        text = (f"# Introduction\n\nRanges held {bracket}.\n\n# Methods\n\nThe National "
                "Institutes of Health (NIH) paid. The NIH rose.\n")
        assert "abbreviation-used-before-defined" in [
            code for code, _message in checked(tmp_path, {"main.md": text})], bracket
    text = ("# Introduction\n\nRules were set (AERA, 2014; APA, 2020).\n\n# Methods\n\nThe "
            "American Educational Research Association (AERA) set them. The AERA held.\n")
    assert checked(tmp_path, {"main.md": text}) == []
