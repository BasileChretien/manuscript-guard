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
        "<div hidden>Cookie settings 7</div><template><p>Accept 8</p></template>"
        "<noscript>Enable JavaScript 9</noscript>"
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
    for hidden in ("9999", "3500px", "12 figures", "<p", "&#160;", "&nbsp;", "Cookie", "Accept",
                   "JavaScript", "Instructions for authors"):
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
        # A real Cloudflare challenge: its words are in the title, a <noscript> and hidden
        # elements, none of which a browser shows as the page.
        ("challenge.html",
         "<html><head><title>Just a moment...</title></head><body>"
         "<noscript>Enable JavaScript and cookies to continue</noscript>"
         "<div hidden><p>Verifying you are human</p></div>"
         "<template><p>Checking your browser</p></template>"
         "<div style='display: none'>Ray ID 8f</div><span style=\"visibility:hidden\">x</span>"
         "<script>challenge()</script></body></html>", "no text"),
        ("page.docx", b"PK\x03\x04\x14\x00\x08\x00\xff\xfe\x00", "UTF-8"),
    ],
)  # fmt: skip
def test_a_file_with_no_page_in_it_is_refused(
    journal_project: Path, capsys, name: str, content, said: str
) -> None:
    (journal_project / PAGE).unlink()
    saved = journal_project.parent / name
    if isinstance(content, bytes):
        saved.write_bytes(content)
    else:
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


@pytest.mark.parametrize(
    ("change", "page"),
    [
        (lambda d: d.update(page_file="../outside/page.txt"), None),
        (lambda d: d.update(page_file="OUTSIDE"), None),
        (lambda d: d.update(sharing={"page_file": "../sharing.txt", "source_url": "x"}),
         "../sharing.txt"),
    ],
    ids=["page_file above the project", "page_file absolute", "a block's page_file"],
)  # fmt: skip
def test_a_page_is_never_stored_outside_the_project(
    journal_project: Path, capsys, change, page: str | None
) -> None:
    """A page was only ever read from where the profile names it; once it is written there,
    a `page_file` or a journal named out of the project must not take the write with it."""
    import yaml

    outside = journal_project.parent / "absolute-page.txt"
    profile = journal_project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    change(document)
    if document.get("page_file") == "OUTSIDE":
        document["page_file"] = str(outside)
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    before = sorted(path for path in journal_project.parent.rglob("*") if path.is_file())
    saved = _saved_html(journal_project.parent / "page.html")
    before.append(saved)
    argv = ["journal", str(journal_project), "--store", str(saved), "--replace"]
    assert main([*argv, *(["--page", page] if page else [])]) == 2
    assert "outside the project" in capsys.readouterr().err
    after = sorted(path for path in journal_project.parent.rglob("*") if path.is_file())
    assert after == sorted(before)


def test_a_journal_named_out_of_the_project_stores_nothing(journal_project: Path, capsys) -> None:
    paper = journal_project / "paper.yaml"
    paper.write_text(paper.read_text(encoding="utf-8").replace(
        "target_journal: demo-journal", "target_journal: ../../../../escaped"), encoding="utf-8")
    saved = _saved_html(journal_project.parent / "page.html")
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 2
    assert "outside the project" in capsys.readouterr().err
    assert not list(journal_project.parent.parent.rglob("escaped.txt"))


def test_inline_markup_joins_and_only_blocks_break_a_line(journal_project: Path) -> None:
    """A link, a bold letter or a span inside a sentence is the sentence, as the browser shows
    it and as the author copies a quote from it."""
    from manuscript_guard.gates.journal_quotes import page_text

    saved = journal_project.parent / "page.html"
    saved.write_text(
        "<html><body><p>Follow the <a href='x'>ICMJE recommendations</a>.</p>"
        "<p><b>W</b>ord count<br>no more than <span class='n'>4000</span> words</p>"
        "<ul><li>Title<li>Abstract</ul><table><tr><td>Figures</td><td>6</td></tr></table>"
        "</body></html>",
        encoding="utf-8",
    )
    assert page_text(saved).splitlines() == [
        "Follow the ICMJE recommendations.", "Word count", "no more than 4000 words",
        "Title", "Abstract", "Figures", "6",
    ]


@pytest.mark.parametrize(
    "declared",
    ['<meta charset="windows-1252">',
     '<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">'],
)  # fmt: skip
def test_a_page_s_declared_charset_is_read(journal_project: Path, declared: str) -> None:
    from manuscript_guard.gates.journal_quotes import page_text

    saved = journal_project.parent / "page.html"
    saved.write_bytes(f"<html><head>{declared}</head><body><p>R".encode("ascii")
                      + "ésumé of the café".encode("cp1252") + b"</p></body></html>")
    assert page_text(saved) == "Résumé of the café\n"


def test_a_page_read_again_may_be_any_utf8_file(journal_project: Path, capsys) -> None:
    """`--reread` read any UTF-8 file, whatever its name, and still does."""
    again = journal_project.parent / "bmj-open-2026.11.26"
    again.write_bytes((journal_project / PAGE).read_bytes())
    assert main(["journal", str(journal_project), "--reread", str(again)]) == 0
    assert "word for word" in capsys.readouterr().out


def test_the_adopting_command_can_be_pasted(
    journal_project: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """From another folder, and for a file whose name has a space in it."""
    monkeypatch.chdir(journal_project.parent)
    (journal_project / PAGE).unlink()
    saved = _saved_html(journal_project.parent / "Instructions for authors.html")
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 0
    capsys.readouterr()
    saved.write_text(saved.read_text(encoding="utf-8").replace("300 words", "250 words"),
                     encoding="utf-8")  # fmt: skip
    assert main(["journal", str(journal_project), "--reread", str(saved)]) == 1
    out = capsys.readouterr().out
    root = load_project(journal_project)[0].root
    assert f'journal "{root}" --store "{saved}" --replace' in out
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 2
    err = capsys.readouterr().err
    assert f'journal "{root}" --reread "{saved}"' in err
    assert f'journal "{root}" --store "{saved}" --replace' in err


def test_a_store_refused_with_a_template_starts_no_profile(journal_project: Path, capsys) -> None:
    """The page is stored first: refused, nothing is written, and the same command can be run
    again once the page is saved right."""
    empty = journal_project.parent / "blocked.html"
    empty.write_text("<html><head><title>Just a moment...</title></head></html>",
                     encoding="utf-8")  # fmt: skip
    profile = journal_project / "profiles" / "journals" / "bmj-open.yaml"
    argv = ["journal", str(journal_project), "--template", "bmj-open", "--store"]
    assert main([*argv, str(empty)]) == 2
    assert not profile.exists()
    capsys.readouterr()
    assert main([*argv, str(_saved_html(journal_project.parent / "page.html"))]) == 0
    assert profile.is_file()


def test_a_profile_that_cannot_be_read_is_said(journal_project: Path, capsys) -> None:
    """Its `page_file` cannot be read either, so the page is not stored where it may not be."""
    profile = journal_project / "profiles" / "journals" / "demo-journal.yaml"
    profile.write_text("limits: [\n", encoding="utf-8")
    (journal_project / PAGE).unlink()
    saved = _saved_html(journal_project.parent / "page.html")
    assert main(["journal", str(journal_project), "--store", str(saved)]) == 2
    assert "demo-journal.yaml" in capsys.readouterr().err
    assert not (journal_project / PAGE).exists()


def test_a_page_that_cannot_be_written_is_said_so(journal_project: Path, capsys) -> None:
    (journal_project / PAGE).unlink()
    (journal_project / PAGE).mkdir()
    saved = _saved_html(journal_project.parent / "page.html")
    assert main(["journal", str(journal_project), "--store", str(saved), "--replace"]) == 2
    err = capsys.readouterr().err
    assert "could not be written" in err and "cannot be read" not in err
