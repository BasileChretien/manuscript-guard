"""G14 on a LaTeX manuscript, step 7 of DESIGN.md's "LaTeX manuscripts": the words view
(`text/latex/words.py`), and the abbreviations, terms and spelling read through it in the
order the document prints."""

from __future__ import annotations

import shutil
import unicodedata
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_language
from manuscript_guard.text.latex.mask import NUL
from manuscript_guard.text.latex.structure import read_tree
from manuscript_guard.text.latex.words import words

OPEN = "\\documentclass{article}\n\\begin{document}\n"
CLOSE = "\\end{document}\n"


def _words(text: str):
    (source,) = read_tree({"main.tex": text}).sources
    return words(source)


def _read(seen) -> str:
    return " ".join(seen.text.replace(NUL, " ").split())


def _latex(project: Path, files: dict[str, str], **paper) -> object:
    """Judge exactly these `.tex` files: the example's Markdown goes, and `paper` is set in
    paper.yaml."""
    folder = project / "manuscript"
    shutil.rmtree(folder)
    folder.mkdir()
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
    path = project / "paper.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document.update(paper)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return check_language(load_project(project)[0])


# ---------------------------------------------------------------- the view


def test_the_words_view_keeps_the_prose_and_hides_what_g14_does_not_read() -> None:
    text = (
        "\\documentclass{article}\n\\title{A title word}\n"
        "\\abstract{The abstract word.}\n\\begin{document}\n\\maketitle\n"
        "\\section{Heading word}\nProse word, \\emph{stressed word}\\footnote{Note word.}.\n"
        "A formula $x + y$ and \\[ z = 1 \\] and \\texttt{code word} and \\verb|verb|.\n"
        "\\begin{figure}\\caption{Caption word}\\end{figure}\n% comment word\n"
        "\\begin{table}\\caption{Table word}\\end{table}\n" + CLOSE
    )
    seen = _words(text)
    assert len(seen.text) == len(text)
    assert [i for i, c in enumerate(seen.text) if c == "\n"] == [
        i for i, c in enumerate(text) if c == "\n"
    ]
    read = _read(seen)
    for kept in ("The abstract word.", "Heading word", "Prose word,", "stressed word",
                 "Note word.", "Table word"):  # fmt: skip
        assert kept in read, (kept, read)
    for hidden in ("title", "formula x", "z", "code word", "verb", "Caption", "comment"):
        assert f" {hidden}" not in f" {read}", (hidden, read)
    assert seen.unread == ()


def test_a_word_holding_an_accent_command_is_read_as_latex_prints_it() -> None:
    """Each accent command is the accented letter, a letter typed as a command that letter,
    and `\\-` nothing, the word written from where it starts with NUL after it (Known gaps,
    2026-10-27: each word was hidden and said unread). An accent over no letter is still
    unread; one in a comment or maths is not read at all."""
    text = (
        OPEN + "caf\\'e na\\\"{\\i}ve {\\\"u}ber co\\-operate "
        "Stra\\ss e r\\'esum\\'e\\c{c}a \\emph{Chr\\'etien} caf\\'{}e plain.\n"
        "% caf\\'e in a comment\n$\\'e$\n" + CLOSE
    )
    seen = _words(text)
    assert [text[start:end] for start, end in seen.unread] == ["caf\\'{}e"]
    assert _read(seen) == ("caf\N{LATIN SMALL LETTER E WITH ACUTE} "
                           "na\N{LATIN SMALL LETTER I WITH DIAERESIS}ve "
                           "\N{LATIN SMALL LETTER U WITH DIAERESIS}ber cooperate "
                           "Stra\N{LATIN SMALL LETTER SHARP S}e "
                           "r\N{LATIN SMALL LETTER E WITH ACUTE}sum"
                           "\N{LATIN SMALL LETTER E WITH ACUTE}"
                           "\N{LATIN SMALL LETTER C WITH CEDILLA}a "
                           "Chr\N{LATIN SMALL LETTER E WITH ACUTE}tien plain."), _read(seen)
    assert len(seen.text) == len(text)
    start = text.index("caf\\'e")
    assert seen.text[start : start + 6] == "caf\N{LATIN SMALL LETTER E WITH ACUTE}" + NUL * 2


@pytest.mark.parametrize("command", ["Erd\\H{e}s", "\\'{x}", "\\t{o}", "\\v{J}"])
def test_an_accent_with_no_composed_letter_keeps_every_place_of_the_file(command: str) -> None:
    """Where Unicode has no letter composed of the two, an accent command is a letter and a
    combining mark, and both were written at the command's backslash: the view of the file
    was a character longer from there on, and every number after it was read one place off.
    The mark goes in the place after the letter."""
    from manuscript_guard.text.latex.mask import read
    from manuscript_guard.text.latex.words import accented

    text = f"We thank {command} for 412 cases.\n"
    out = accented(text, read(text).masked)
    assert len(out) == len(text)
    at = text.index("412")
    assert out[at : at + 3] == "412"
    start = text.index("\\")
    assert out[start].isalpha() and unicodedata.combining(out[start + 1])


def test_a_count_written_as_a_subscript_reads_as_markdown_writes_it() -> None:
    """`CO$_2$` is `CO~2~`, so that G14 reads a formula as one; a subscript in maths, or after
    no letter, is maths."""
    text = OPEN + "CO$_2$ and NO\\textsubscript{2} and H$_{12}$ but $x_2$ and 5$_2$.\n" + CLOSE
    read = _read(_words(text))
    assert read == "CO~2~ and NO~2~ and H~12~ but and 5 .", read


# ---------------------------------------------------------------- G14 through it


PARTICIPANTS = {"vocabulary": [{"use": "participants", "avoid": ["subjects"]}]}


def test_a_term_given_up_is_found_where_latex_prints_it_and_nowhere_else(project: Path) -> None:
    report = _latex(project, {"main.tex": OPEN + (
        "\\section{Methods}\nParticipants were enrolled.\n"
        "% subjects in a comment\n$subjects$ in maths, \\texttt{subjects} as code,\n"
        "\\label{subjects} as a label.\n\\section{Results}\nOf the \\emph{subjects}, half.\n"
    ) + CLOSE}, language=PARTICIPANTS)  # fmt: skip
    (found,) = [f for f in report.findings if f.code == "term-avoided"]
    assert found.message == "'subjects' is used once; this paper's term is 'participants'"
    assert found.line == 9 and found.path.name == "main.tex"
    assert "Of the subjects , half." in found.context


def test_a_spelling_is_found_in_a_latex_file_and_not_in_its_comments(project: Path) -> None:
    report = _latex(project, {"main.tex": OPEN + (
        "\\section{Results}\nThe color changed.\n% the color in a comment\n"
    ) + CLOSE}, english_variant="en-GB", language={})  # fmt: skip
    (found,) = [f for f in report.findings if f.code == "spelling-variant"]
    assert found.message.startswith("'color' is the American spelling of 'colour', used once")
    assert found.line == 4


def test_a_document_of_several_files_is_read_in_the_order_it_prints(project: Path) -> None:
    """A definition in a file input before the entry file's next words is read before them,
    and a use in a file input before the entry file's definition is read before that."""
    defined_first = _latex(project, {
        "main.tex": OPEN + "\\section{Introduction}\n\\input{intro}\nThe ROR rose.\n" + CLOSE,
        "intro.tex": "The reporting odds ratio (ROR) is used.\n",
    })  # fmt: skip
    assert not [f for f in defined_first.findings if f.code.startswith("abbreviation-")]
    used_first = _latex(project, {
        "main.tex": OPEN + "\\section{Introduction}\n\\input{intro}\n"
        "The reporting odds ratio (ROR) is used. The ROR rose.\n" + CLOSE,
        "intro.tex": "The ROR comes first.\n",
    })  # fmt: skip
    (found,) = [f for f in used_first.findings if f.code.startswith("abbreviation-")]
    assert found.code == "abbreviation-used-before-defined"
    assert found.path.name == "intro.tex" and "defined later at manuscript/main.tex:5" in (
        found.message
    )


def test_an_abstract_input_inside_its_environment_is_read_apart(project: Path) -> None:
    report = _latex(project, {
        "main.tex": OPEN + "\\begin{abstract}\n\\input{abstract}\n\\end{abstract}\n"
        "Before the first section the ROR rose.\n\\section{Results}\nThe ROR rose.\n" + CLOSE,
        "abstract.tex": "The reporting odds ratio (ROR) rose. The ROR rose.\n",
    })  # fmt: skip
    (found,) = [f for f in report.findings if f.code.startswith("abbreviation-")]
    assert found.message == (
        "ROR is used 2 times in the main text and not defined there; the abstract defines it, "
        "and is read apart from the paper"
    )
    assert found.line == 6


def test_a_reference_list_typed_in_latex_is_not_read(project: Path) -> None:
    report = _latex(project, {"main.tex": OPEN + (
        "\\section{Results}\nThe ratio rose.\n\\begin{thebibliography}{9}\n"
        "\\bibitem{a} Smith J. A colour study. JAMA. 2020.\n"
        "\\bibitem{b} M{\\\"u}ller J, Garc{\\'i}a P. A study. 2021.\n\\end{thebibliography}\n"
    ) + CLOSE}, english_variant="en-US", language={})  # fmt: skip
    # Nor are its accented names words G14 says it skipped (round 1 of step 7).
    assert not [f for f in report.findings if f.code in ("abbreviation-undefined",
                                                         "spelling-variant",
                                                         "tex-words-not-read")]  # fmt: skip


def test_g14_reads_a_file_input_whatever_the_case_of_its_suffix() -> None:
    """`Methods.TEX` is text, read where its `\\input` stands (round 1 of step 7: it was taken
    for a package, and the file after it was read in its place)."""
    from manuscript_guard.gates.language import _stretches

    files = {"main.tex": OPEN + "One.\n\\input{Methods.TEX}\nTwo.\n" + CLOSE,
             "Methods.TEX": "Inside.\n"}  # fmt: skip
    read = "".join(source.text[start:end]
                   for source, start, end in _stretches(read_tree(files).sources))  # fmt: skip
    assert read.index("One.") < read.index("Inside.") < read.index("Two."), read


def test_g14_says_once_a_file_how_many_words_it_did_not_read(project: Path) -> None:
    """Only a word whose accent marks no letter is unread since 2026-10-27; a word an accent
    command or `\\-` splits is read as LaTeX prints it."""
    report = _latex(project, {
        "main.tex": OPEN + "\\section{Results}\nThe caf\\'{}e and caf\\'e was\n"
        "\\input{more}\nna\\\"{}ive.\n" + CLOSE,
        "more.tex": "A co\\'{}operate and co\\-operate word.\n",
    })  # fmt: skip
    found = sorted((f for f in report.findings if f.code == "tex-words-not-read"),
                   key=lambda f: f.path.name)  # fmt: skip
    assert [(f.path.name, f.line, f.message) for f in found] == [
        ("main.tex", 4, "2 words here hold an accent command over no letter, and G14 does "
                        "not read them: the first is \"caf\\\\'{}e\""),
        ("more.tex", 1, "1 word here holds an accent command over no letter, and G14 does "
                        "not read it: the first is \"co\\\\'{}operate\""),
    ]  # fmt: skip
    assert all(f.severity == "warn" for f in found)
    # The message named `\-` long after a word it splits was read (round 1 of #452).
    assert not any("\\-" in f.message or "hyphenation" in f.hint for f in found)
