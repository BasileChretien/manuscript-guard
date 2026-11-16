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
    read = _file(0, Path("main.md"), f"{sentence}\n", [], False)
    defined = {found for _at, found, _long in read.definitions}
    assert short in defined, (kind, read.definitions)


@pytest.mark.parametrize(("kind", "sentence", "short"), NOT_DEFINING)
def test_each_shape_defines_nothing_where_its_words_do_not_match(
    kind: str, sentence: str, short: str
) -> None:
    read = _file(0, Path("main.md"), f"{sentence}\n", [], False)
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


def test_a_note_that_defines_again_is_a_second_definition(project: Path) -> None:
    """Known gaps, held where it stands (docx-sport-A2, docx-psych-A3): a table's note that
    is not read as a caption defines as a sentence does, so where the text defined the form
    first it is defined again, and a long form worded otherwise is a second meaning. A
    caption may restate; whether such a note may is the author's to decide."""
    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(
        "# Methods\n\nWe used the Beck Depression Inventory (BDI) and the Cigarette Dependence "
        "Scale (CDS).\n\n# Results\n\n| Score | n |\n|---|---|\n| 12 | 40 |\n\n*Note.* BDI = Beck "
        "Depression Inventory; CDS = Cigarette Dependence Score.\n\nThe BDI and the CDS were "
        "low.\n", encoding="utf-8")
    report = check_language(load_project(project)[0])
    found = sorted((f.code, f.message.split()[0]) for f in report.findings)
    assert found == [("abbreviation-redefined", "BDI"), ("abbreviation-redefined", "CDS")], found


def test_a_colon_that_introduces_words_with_the_letters_defines() -> None:
    """Known gaps, held where it stands (docx-educ-B1): a colon before words that begin with
    the short form's letters is read as a definition, though it introduces them; so is a
    label in capitals before a sentence that holds its letters in order."""
    for text, short in (("the latest of the TVMs: Teacher Video Modules Plus (TVM-P)", "TVM"),
                        ("NOTE: Never Omit The End", "NOTE")):  # fmt: skip
        read = _file(0, Path("main.md"), f"{text}\n", [], False)
        assert short in [found for _at, found, _long in read.definitions], (text, read.definitions)


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
    return _undefined([f.message for f in report.findings if f.code == "abbreviation-undefined"])


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
