"""The report as the page and the PDF give it to a reader (`auditing.reader`): no flag, no
`--strict`, no command, which the text the command line prints keeps (the author's audit,
2026-11-11: "This page is still hard to read and not user friendly")."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pypdf

from manuscript_guard import web
from manuscript_guard.auditing.reader import FAILS, excerpt, for_a_reader
from manuscript_guard.cli import main

#: A paper with no outputs given, an abbreviation used and not defined, a reference list, a
#: sentence G6 reads, a participant flow under its heading whose arms do not add up, and a
#: Discussion that claims a cause: the text then names `--against`, `--lookup`, `--strict`
#: and, under `--design`, the design.
PAPER = (
    "# Abstract\n\nOf the patients, 412 improved.\n\n# Methods\n\nThe XYZ panel read every "
    "record, highlighting the importance of the method.\n\n# Results\n\nOf the patients, 40 "
    "improved.\n\n## Participant flow\n\n- Assessed for eligibility (n = 412)\n"
    "  - Excluded (n = 112)\n- Randomised (n = 300)\n  - Drug (n = 151)\n  - Placebo (n = 148)\n"
    "\n# Discussion\n\nThe drug causes the improvement.\n\n# References\n\n1. Smith J. A "
    "study. J Stud. 2020;1:1-2. doi:10.1000/xyz123\n"
)
#: What only a script or its command line needs. `--known` and `--english` are named on
#: purpose beside the page's box for each, and stay.
FLAGS = re.compile(r"--strict|--against|--lookup|--details|init --from|--design|--dry-run|"
                   r"--authors|--whole-numbers|--non-negative")


def test_the_view_the_page_and_the_pdf_draw_names_no_flag(tmp_path: Path, monkeypatch) -> None:
    """The text names the flags a script would give; the view drawn from the very same
    audit, with every place and every section, names none, and still says each thing: what
    each check found, the findings on the words, the other sections and the last line."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "paper.md").write_text(PAPER, encoding="utf-8")
    for given in ([], ["--details"],
                  ["--details", "--design", "observational", "--whole-numbers", "Age",
                   "--non-negative", "Weight"]):
        result = web.view(["audit", "paper.md", *given])
        assert FLAGS.search(result["out"]), "the text names the flags a script gives"
        view = result["view"]
        assert view["strict"] is None
        drawn = json.dumps(view, ensure_ascii=False)
        assert not FLAGS.search(drawn), FLAGS.findall(drawn)
        if "--details" in given:
            # The flow's arms, which --strict counts, said for a reader (round 1 of #631).
            assert FAILS in drawn and "whose faults are counted as errors" in drawn
        checks = dict(view["checks"])
        assert checks["Numbers in the outputs"].startswith("not run: no outputs were given")
        assert "none looked up in the registries" in checks["References"]
        assert [kind for paper in view["words"] for kind in paper["kinds"]]
        assert "give the audit the analysis outputs to compare them with" in view["closing"]


def test_each_reading_for_a_reader_matches_what_the_text_writes() -> None:
    """Each of the text's phrases for a script, as the report writes them, said for a reader;
    a phrase reworded in the report and not here would be left on the page."""
    from manuscript_guard.auditing import report, summary

    said = {
        f"{report.REFERENCES} (not counted by --strict)": report.REFERENCES,
        "Passed over in a folder (a note, not counted by --strict):":
            "Passed over in a folder (a note):",
        f"{report.CAUSAL} (--design cohort; not counted by --strict)":
            f"{report.CAUSAL} (the design given: cohort)",
        "x.docx: 3 findings in 2 kinds; lines are those of the text pandoc converts it to, as "
        "`init --from` writes it": "x.docx: 3 findings in 2 kinds; lines are those of the text "
        "pandoc converts it to",
        "33 entries read; none looked up in the registries (--lookup)":
            "33 entries read; none looked up in the registries",
        "not run: no outputs were given to compare the numbers with (--against)":
            "not run: no outputs were given to compare the numbers with",
        f"and 6 more: {summary.DETAILS} lists every place":
            "and 6 more: the PDF of the report lists every place",
        "FLOWS WHOSE ARITHMETIC DOES NOT HOLD, under a name for a flow (counted by --strict):":
            f"FLOWS WHOSE ARITHMETIC DOES NOT HOLD, under a name for a flow {FAILS}:",
        "1 under a heading, a caption or a paragraph that names a flow, whose faults --strict "
        "counts.": "1 under a heading, a caption or a paragraph that names a flow, whose "
        "faults are counted as errors.",
        "  Point --against at the analysis outputs rather than the raw data if you can.":
            "  Give the analysis outputs rather than the raw data if you can.",
        "  --whole-numbers 'Age': no mean was read in a row whose label holds it":
            "  The label 'Age', given as whole numbers: no mean was read in a row whose label "
            "holds it",
        "Means and SDs of variables that cannot be negative (--non-negative): 2 read in the "
        "rows named": "Means and SDs of variables that cannot be negative: 2 read in the rows "
        "named",
        "  --non-negative 'Age': no mean (SD) was read in a row whose label holds it":
            "  The label 'Age', given as never negative: no mean (SD) was read in a row whose "
            "label holds it",
        "    line 7: --non-negative row 'Ferritin, mean (SE)': not read, as its label names a "
        "standard error": "    line 7: The row 'Ferritin, mean (SE)', given as never negative: "
        "not read, as its label names a standard error",
        "not counted: --dry-run sent nothing, so no registry's author list was read":
            "not counted: nothing was sent, so no registry's author list was read",
        "authors not counted: --authors names them":
            "authors not counted: no authors were given to the audit",
        "not asked (--dry-run): would ask Crossref": "not asked: would ask Crossref",
        "the study is observational (--design), and the word claims a cause":
            "the study is observational, and the word claims a cause",
        "(G14 holds its spelling to the profile's English, or to the one --english chooses)":
            "(G14 holds its spelling to the profile's English, or to the one chosen for the "
            "paper)",
    }  # fmt: skip
    for text, plain in said.items():
        assert for_a_reader(text) == plain
    # What it does not know it leaves as it is.
    assert for_a_reader("XYZ is used once and not defined") == "XYZ is used once and not defined"


def test_a_context_is_quoted_without_markdowns_marks() -> None:
    """A .docx's converted text marks bold and italics as Markdown does; the page and the PDF
    quote the words as the document prints them. A name from code keeps its underscores, a
    code span is quoted as typed, a star that marks nothing stays, an emphasis inside another
    goes too, and the ends are not marked as cut, which only the gate could say (round 1 of
    #631)."""
    assert excerpt("s) - **CBL**: Case-based learning - **CEMU**: Centre d") == (
        "s) - CBL: Case-based learning - CEMU: Centre d")
    assert excerpt("the *p* value and _et al._ here") == "the p value and et al. here"
    assert excerpt("set code_names_kept in it") == "set code_names_kept in it"
    assert excerpt("2 * 3 = 6, and 4*5") == "2 * 3 = 6, and 4*5"
    assert excerpt("the `__init__` method and **`x_y`**") == "the `__init__` method and `x_y`"
    assert excerpt("*a **b** c* d") == "a b c d"
    assert excerpt("well, broadly, briefly") == "well, broadly, briefly"


def test_a_quote_cut_inside_a_code_span_keeps_the_marks_after_it() -> None:
    """A limit (DESIGN.md, Known gaps): a context the gate cut inside a code span has a lone
    backtick, which pairs with the next, and the marks between them stay (round 2 of #631).
    A label that holds both kinds of quote is said for a reader all the same."""
    assert excerpt("x_y` and **b** and `z`") == "x_y` and **b** and `z`"
    label = "a'b\"c"
    assert for_a_reader(f"  --whole-numbers {label!r}: no mean was read in a row") == (
        f"  The label {label!r}, given as whole numbers: no mean was read in a row")


def test_the_pdf_names_no_flag_nor_a_checks_code(tmp_path: Path, capsys) -> None:
    """The PDF is for a reader: no line on what --strict counts, no paper's name over its
    findings where it is the only paper, and a kind's heading without the check's code."""
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER, encoding="utf-8")
    target = tmp_path / "report.pdf"
    assert main(["audit", str(paper), "--pdf", str(target)]) == 0
    capsys.readouterr()
    reader = pypdf.PdfReader(io.BytesIO(target.read_bytes()), strict=True)
    text = " ".join("".join(page.extract_text() for page in reader.pages).split())
    assert not FLAGS.search(text), FLAGS.findall(text)
    titles = [item.title for item in reader.outline if not isinstance(item, list)]
    nested = [item.title for items in reader.outline if isinstance(items, list)
              for item in items if not isinstance(item, list)]  # fmt: skip
    assert "Writing and language" in titles
    assert nested and not any(re.search(r"\(G\d+, \d+\)", title) for title in nested), nested


def test_the_pdf_names_the_paper_where_several_were_audited(tmp_path: Path, capsys) -> None:
    """Where several papers were audited, the findings are headed with their paper's name,
    though only one of them has any: no place under the heading names the paper again
    (round 1 of #631)."""
    (tmp_path / "a.md").write_text(PAPER, encoding="utf-8")
    (tmp_path / "b.md").write_text("# Results\n\nOf the patients, 40 improved.\n", encoding="utf-8")
    target = tmp_path / "report.pdf"
    assert main(["audit", str(tmp_path / "a.md"), str(tmp_path / "b.md"), "--pdf",
                 str(target)]) == 0  # fmt: skip
    capsys.readouterr()
    reader = pypdf.PdfReader(io.BytesIO(target.read_bytes()), strict=True)
    titles = [item.title for item in reader.outline if not isinstance(item, list)]
    assert "Writing and language: a.md" in titles, titles
