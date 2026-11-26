"""A journal's page saved from a browser, stored as the profile's page.

A journal's instructions page behind a bot check cannot be fetched by a script or an agent:
BMJ Open's sat behind one when a real paper's profile was filled. The author can open it in
their own browser and save it, as a web page (HTML only) or printed to PDF. `journal --store`
takes that file and writes its text where the profile reads its page, and prints the digest
to record; `journal --reread` takes the same files a year on.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_journal
from manuscript_guard.gates.journal_quotes import page_digest

EXAMPLE = Path(__file__).resolve().parent.parent / "example"
PAGE = Path("profiles") / "journals" / "sources" / "demo-journal.txt"
QUOTE_CODES = {"journal-quote-not-on-page", "journal-limit-not-in-quote"}


@pytest.fixture
def journal_project(tmp_path: Path) -> Path:
    """The example's settings and its journal profile, and nothing else."""
    root = tmp_path / "paper"
    root.mkdir()
    for name in ("paper.yaml", "authors.yaml"):
        shutil.copy2(EXAMPLE / name, root / name)
    shutil.copytree(EXAMPLE / "profiles" / "journals", root / "profiles" / "journals")
    return root


def _page_lines() -> list[str]:
    return (EXAMPLE / PAGE).read_text(encoding="utf-8").splitlines()


def _saved_html(path: Path) -> Path:
    """The example's page as a browser saves it: one element to a paragraph, the text's
    characters as entities where a page writes them so, and what a page carries besides."""
    paragraphs = "".join(
        f"<p class=\"x\">{line.replace('should', 'should&nbsp;')}</p>" for line in _page_lines()
        if line.strip()
    ).replace("&nbsp;", "&#160;", 1)
    path.write_text(
        "<!DOCTYPE html><html><head><title>Instructions for authors</title>"
        "<style>p { margin: 3500px; }</style>"
        "<script>var limit = '<p>should not exceed 9999 words</p>';</script></head><body>"
        "<!-- a comment with > inside it: no more than 12 figures -->"
        f"<nav><ul><li>Home</li><li>Submit</li></ul></nav><main>{paragraphs}</main>"
        "</body></html>",
        encoding="utf-8",
    )
    return path


def _quotes_said(root: Path) -> set[str]:
    project, _ = load_project(root)
    return {f.code for f in check_journal(project).findings} & QUOTE_CODES


def test_a_page_saved_as_html_is_stored_as_its_text(journal_project: Path, capsys) -> None:
    (journal_project / PAGE).unlink()
    saved = _saved_html(journal_project.parent / "Instructions for authors.html")
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 0
    out = capsys.readouterr().out
    stored = (journal_project / PAGE).read_text(encoding="utf-8")
    assert f"page_sha256: {page_digest(stored)}" in out
    assert PAGE.as_posix() in out
    # The page's words, each paragraph a line of its own; nothing it does not show.
    assert "Abstracts should not exceed 300 words." in stored.splitlines()
    assert "Home" in stored.splitlines()
    for hidden in ("9999", "3500px", "12 figures", "<p", "&#160;", "&nbsp;"):
        assert hidden not in stored, hidden
    assert stored.endswith("\n") and "\n\n\n" not in stored and "\r" not in stored
    # Every quote of the profile is on it.
    assert _quotes_said(journal_project) == set()


def _pdf(path: Path) -> Path:
    sys.path.insert(0, str(Path(__file__).parent))
    from proof_pdf import typeset

    path.write_bytes(typeset([line for line in _page_lines() if line.strip()], columns=1,
                             per_column=40))  # fmt: skip
    return path


def _reads_pdfs() -> bool:
    import tempfile

    from manuscript_guard.literature.sources import UnreadableSource, _read_pdf

    with tempfile.TemporaryDirectory() as folder:
        try:
            return "300 words" in _read_pdf(_pdf(Path(folder) / "probe.pdf"), layout=False)
        except UnreadableSource:
            return False


@pytest.mark.skipif(not _reads_pdfs(), reason="neither pdftotext nor pypdf reads a PDF here")
def test_a_page_printed_to_pdf_is_stored_as_its_text(journal_project: Path, capsys) -> None:
    (journal_project / PAGE).unlink()
    saved = _pdf(journal_project.parent / "instructions.pdf")
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 0
    stored = (journal_project / PAGE).read_text(encoding="utf-8")
    assert f"page_sha256: {page_digest(stored)}" in capsys.readouterr().out
    assert _quotes_said(journal_project) == set()


def test_a_different_page_stored_is_replaced_only_when_asked(
    journal_project: Path, capsys
) -> None:
    """The stored page is the one every quote is held to: another takes its place after the
    author has read the two against each other (`--reread`), and says so (`--replace`)."""
    before = (journal_project / PAGE).read_bytes()
    saved = _saved_html(journal_project.parent / "page.html")
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 2
    err = capsys.readouterr().err
    assert "--reread" in err and "--replace" in err
    assert (journal_project / PAGE).read_bytes() == before
    assert main(["journal", str(journal_project), "--store", str(saved), "--replace"]) == 0
    capsys.readouterr()
    stored = (journal_project / PAGE).read_bytes()
    assert stored != before
    # The same page again is no change, and needs no --replace.
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 0
    assert "unchanged" in capsys.readouterr().out
    assert (journal_project / PAGE).read_bytes() == stored


def test_a_page_read_again_may_be_a_saved_html_page(journal_project: Path, capsys) -> None:
    (journal_project / PAGE).unlink()
    saved = _saved_html(journal_project.parent / "page.html")
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 0
    capsys.readouterr()
    assert main(["journal", str(journal_project), "--reread", str(saved)]) == 0
    assert "word for word" in capsys.readouterr().out
    saved.write_text(saved.read_text(encoding="utf-8").replace("300 words", "250 words"),
                     encoding="utf-8")  # fmt: skip
    assert main(["journal", str(journal_project), "--reread", str(saved)]) == 1
    out = capsys.readouterr().out
    assert "+Abstracts should not exceed 250 words." in out
    assert "NOT on the page    limits.abstract_words" in out


def test_a_new_journal_s_page_is_stored_with_its_template(journal_project: Path, capsys) -> None:
    """Before a profile exists: the page is stored for the slug the template starts."""
    saved = _saved_html(journal_project.parent / "page.html")
    assert main(["journal", str(journal_project), "--template", "bmj-open",
                 "--store", str(saved)]) == 0  # fmt: skip
    out = capsys.readouterr().out
    stored = journal_project / "profiles" / "journals" / "sources" / "bmj-open.txt"
    assert (journal_project / "profiles" / "journals" / "bmj-open.yaml").is_file()
    assert f"page_sha256: {page_digest(stored.read_text(encoding='utf-8'))}" in out


@pytest.mark.parametrize(
    ("name", "content", "said"),
    [
        # What a bot check hands a script, or a PDF of scanned images: no words to hold a
        # rule to.
        ("blocked.html", "<html><head><script>challenge()</script></head><body></body></html>",
         "no text"),
        ("page.docx", "PK", "no reader"),
    ],
)  # fmt: skip
def test_a_file_with_no_page_in_it_is_refused(
    journal_project: Path, capsys, name: str, content: str, said: str
) -> None:
    (journal_project / PAGE).unlink()
    saved = journal_project.parent / name
    saved.write_text(content, encoding="utf-8")
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 2
    assert said in capsys.readouterr().err
    assert not (journal_project / PAGE).exists()


def test_a_page_is_stored_for_a_journal_named(journal_project: Path, capsys) -> None:
    """With no target journal and no template, there is no profile to store a page for."""
    paper = journal_project / "paper.yaml"
    paper.write_text(paper.read_text(encoding="utf-8").replace(
        "target_journal: demo-journal", "# target_journal: demo-journal"), encoding="utf-8")
    saved = _saved_html(journal_project.parent / "page.html")
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 2
    assert "--template" in capsys.readouterr().err
