"""`init --from paper.docx`: a paper written in Word, brought into a project.

The documented route was `pandoc paper.docx -t markdown`. On fifteen openly licensed Word
papers it wrote the tables of eight as multiline tables, which `check` refuses at every
stage (`rule-opens-a-block`), and put each title page in the text. These tests build their
own Word documents with pandoc, from Markdown, and hold what `init --from` makes of them.
"""

from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
import yaml

from manuscript_guard import from_word
from manuscript_guard.cli import main
from manuscript_guard.from_word import (
    TITLE_PAGE_WORDS,
    _flatten,
    _names,
    _one_line,
    _pictures,
    _plain_title,
    _without_marks,
    text_of,
)

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

#: A paper as Word holds one: a title, two authors and a date in Word's own styles, an
#: abstract straight after them, an affiliation over the first heading, a table one of whose
#: cells holds two paragraphs, a table with a list in a cell, and a picture.
PAPER = """\
---
title: "Outcomes after a fall"
author:
  - Anne Example
  - Bob Sample
date: 2026-01-02
---

::: {custom-style="Abstract"}
We followed 120 patients.
:::

Department of Things, Somewhere University

# Introduction

Falls are common.

+----------+-------------+------------+
| Group    | Outcome                  |
+==========+=============+============+
| Cases    | first line  | 41         |
|          |             |            |
|          | second para |            |
+----------+-------------+------------+
| Controls | 12          | 17         |
+----------+-------------+------------+

: Table 1. Counts.

+---------+-------------+
| Step    | What        |
+=========+=============+
| One     | - first     |
|         | - second 33 |
+---------+-------------+

![A picture.](pic.png)
"""


def png() -> bytes:
    """A picture of one grey pixel."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        check = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + check

    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"\x00\x80")) + chunk(b"IEND", b""))  # fmt: skip


def word(folder: Path, markdown: str, name: str = "paper.docx") -> Path:
    """A Word document pandoc writes from `markdown`, with the picture it names."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pic.png").write_bytes(png())
    (folder / "paper.md").write_text(markdown, encoding="utf-8")
    subprocess.run(["pandoc", "paper.md", "-o", name], cwd=folder, check=True, timeout=120)
    return folder / name


def findings(capsys, *arguments: str) -> tuple[int, list[dict]]:
    code = main(["check", *arguments, "--json"])
    return code, json.loads(capsys.readouterr().out)["findings"]


@needs_pandoc
def test_a_word_paper_becomes_a_project_whose_tables_check_reads(tmp_path: Path, capsys) -> None:
    paper = word(tmp_path / "word", PAPER)
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(paper)]) == 0
    said = capsys.readouterr().out
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")

    # The table of paragraphs is a pipe table, a cell's two paragraphs joined by a space.
    assert "| Cases    | first line second para | 41  |" in text
    assert "1 written as pipe tables" in said
    # The table with a list in a cell is a grid table, named in what init printed.
    assert "+======" in text and "- second 33" in text
    assert 'table 2 ("Step What One first second 33"): a list in a cell; written as a grid' in said

    # Word's Title, Author, Date and Abstract styles, where the project takes each.
    assert yaml.safe_load((root / "paper.yaml").read_text(encoding="utf-8"))["title"] == (
        "Outcomes after a fall"
    )
    authors = (root / "authors.yaml").read_text(encoding="utf-8")
    assert "  # Anne Example\n  - given: \"\"" in authors and "  # Bob Sample\n" in authors
    assert len(yaml.safe_load(authors)["authors"]) == 2
    assert "# Abstract\n\nWe followed 120 patients." in text

    # The title page is in one comment at the top, with what no file takes.
    comment = text[text.index("<!--") : text.index("-->")]
    assert "Department of Things, Somewhere University" in comment
    assert "Date: 2026-01-02" in comment
    assert text.index("-->") < text.index("# Abstract")

    # The picture is in the project, where the image points.
    pictures = list((root / "manuscript" / "media").iterdir())
    assert len(pictures) == 1 and pictures[0].read_bytes() == png()
    assert f"](manuscript/media/{pictures[0].name})" in text

    code, found = findings(capsys, str(root), "--stage", "drafting")
    assert "rule-opens-a-block" not in {f["code"] for f in found}
    in_tables = {f["context"] for f in found if f["code"] == "hand-authored-table"}
    assert any("| 41" in context for context in in_tables)
    assert any("second 33" in context for context in in_tables)


@needs_pandoc
def test_the_built_document_carries_the_picture(tmp_path: Path, capsys) -> None:
    """The image points at the picture from the project's root, where the build runs pandoc."""
    import zipfile

    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(word(tmp_path / "word", PAPER))]) == 0
    capsys.readouterr()
    assert main(["build", str(root), "--offline", "--skip-checks"]) == 0
    names = zipfile.ZipFile(root / "build" / "manuscript.docx").namelist()
    assert any(name.startswith("word/media/") for name in names)


@needs_pandoc
@pytest.mark.parametrize("english", [None, "en-US"])
def test_a_word_paper_declares_the_english_it_is_given_and_none_unless_told(
    tmp_path: Path, capsys, english: str | None
) -> None:
    root = tmp_path / "project"
    paper = word(tmp_path / "word", PAPER)
    told = ["--english", english] if english else []
    assert main(["init", str(root), "--from", str(paper), *told]) == 0
    assert yaml.safe_load((root / "paper.yaml").read_text(encoding="utf-8")).get(
        "english_variant"
    ) == english


@needs_pandoc
def test_a_title_given_is_taken_and_the_title_paragraph_is_kept(tmp_path: Path, capsys) -> None:
    root = tmp_path / "project"
    paper = word(tmp_path / "word", PAPER)
    assert main(["init", str(root), "--from", str(paper), "--title", "Another title"]) == 0
    assert yaml.safe_load((root / "paper.yaml").read_text(encoding="utf-8"))["title"] == (
        "Another title"
    )
    assert "Title: Outcomes after a fall" in (root / "manuscript" / "main.md").read_text("utf-8")


@needs_pandoc
def test_a_note_on_the_title_is_kept_in_the_comment(tmp_path: Path, capsys) -> None:
    """paper.yaml takes the title as plain text, without its note: a funder or the
    corresponding author named there was written nowhere."""
    markdown = PAPER.replace('title: "Outcomes after a fall"',
                             'title: "Outcomes after a fall^[Funded by Grant X-12.]"')  # fmt: skip
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(word(tmp_path / "word", markdown))]) == 0
    said = capsys.readouterr().out
    assert yaml.safe_load((root / "paper.yaml").read_text(encoding="utf-8"))["title"] == (
        "Outcomes after a fall"
    )
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    comment = text[text.index("<!--") : text.index("-->")]
    assert "Title: Outcomes after a fall" in comment and "Grant X-12" in comment
    assert "the Title paragraph is in the comment too" in said
    # A title with nothing left out is not in the comment.
    plain = (tmp_path / "plain" / "manuscript" / "main.md")
    assert main(["init", str(tmp_path / "plain"), "--from", str(word(tmp_path / "w2", PAPER))]) == 0
    assert "Title:" not in plain.read_text(encoding="utf-8")
    assert "in the comment too" not in capsys.readouterr().out


def _title(*parts: str) -> dict:
    """A Title paragraph as pandoc reads it: `^x^` a superscript, " " a space, else a word."""
    inlines: list = []
    for part in parts:
        if part == " ":
            inlines.append({"t": "Space"})
        elif part.startswith("^") and part.endswith("^"):
            inlines.append({"t": "Superscript", "c": [{"t": "Str", "c": part[1:-1]}]})
        else:
            inlines.append({"t": "Str", "c": part})
    return {"t": "MetaInlines", "c": inlines}


@pytest.mark.parametrize(
    ("parts", "title", "marks"),
    [
        (("a", " ", "fall", "^1^"), "a fall", "1"),
        (("a", " ", "fall", "^1,2^"), "a fall", "1,2"),
        (("a", " ", "fall", "^1^", ",", "^†^"), "a fall", "1,†"),
        (("a", " ", "fall", "^*^", " "), "a fall", "*"),
        (("a", " ", "fall", "^‡^"), "a fall", "‡"),
        (("a", " ", "fall", "^§^"), "a fall", "§"),
        # The title's own superscripts: of a sign that marks no note, or inside it.
        (("CD4", "^+^", " ", "T", " ", "cells"), "CD4+ T cells", ""),
        (("serum", " ", "Na", "^+^"), "serum Na+", ""),
        (("a", "^1^", " ", "fall"), "a1 fall", ""),
        (("a", " ", "fall", "^1a^"), "a fall1a", ""),
        (("a", " ", "fall", ","), "a fall,", ""),
        (("^1^",), "1", ""),
    ],
)
def test_a_footnote_mark_at_the_end_of_the_title_is_no_part_of_it(
        parts: tuple[str, ...], title: str, marks: str) -> None:  # fmt: skip
    value = _title(*parts)
    before = json.dumps(value)
    unmarked, said = _without_marks(value)
    assert (_plain_title(unmarked), said) == (title, marks)
    assert json.dumps(value) == before


@needs_pandoc
def test_a_title_s_footnote_mark_is_left_out_of_paper_yaml_and_kept_in_the_comment(
        tmp_path: Path, capsys) -> None:  # fmt: skip
    """`text_of` kept a superscript's text, and "a fall¹" was "a fall1" in paper.yaml and in
    the header the build prints."""
    marked = PAPER.replace('title: "Outcomes after a fall"',
                           'title: "Outcomes after a fall^1^,^†^"')  # fmt: skip
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(word(tmp_path / "word", marked))]) == 0
    said = capsys.readouterr().out
    assert yaml.safe_load((root / "paper.yaml").read_text(encoding="utf-8"))["title"] == (
        "Outcomes after a fall"
    )
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    header = text[: text.index("<!--")]
    assert "Outcomes after a fall" in header and "fall1" not in header
    comment = text[text.index("<!--") : text.index("-->")]
    assert "Title: Outcomes after a fall^1^,^†^" in comment
    assert "the superscript '1,†' at its end was taken for the mark of a note" in said
    # A superscript that is part of the title stays in it.
    kept = PAPER.replace('title: "Outcomes after a fall"', 'title: "CD4^+^ T cells after a fall"')
    other = tmp_path / "other"
    assert main(["init", str(other), "--from", str(word(tmp_path / "w2", kept))]) == 0
    assert yaml.safe_load((other / "paper.yaml").read_text(encoding="utf-8"))["title"] == (
        "CD4+ T cells after a fall"
    )
    assert "taken for the mark of a note" not in capsys.readouterr().out


@pytest.mark.parametrize(("raised", "title", "marks"), [
    ("2", "per m", "2"), ("*", "per m", "*"), ("†", "per m", "†"), ("‡", "per m", "‡"),
    ("§", "per m", "§"), ("¶", "per m", "¶"), ("‖", "per m", "‖"), ("#", "per m", "#"),
    ("+", "per m+", ""), ("a", "per ma", ""),
])  # fmt: skip
def test_digits_or_a_note_s_sign_at_a_title_s_end_are_a_mark(
        raised: str, title: str, marks: str) -> None:  # fmt: skip
    """A known gap (DESIGN.md, Known gaps, "A power at the end of a Word title is taken for a
    note's mark"): a superscript of digits, `*`, `†`, `‡`, `§`, `¶`, `‖` or `#` at the title's
    end is left out of it, a power among them; one of any other sign stays."""
    unmarked, said = _without_marks(_title("per", " ", "m", f"^{raised}^"))
    assert (_plain_title(unmarked), said) == (title, marks)


@needs_pandoc
def test_a_power_at_a_word_title_s_end_is_left_out(
        tmp_path: Path, capsys) -> None:  # fmt: skip
    """A known gap (DESIGN.md, Known gaps, "A power at the end of a Word title is taken for a
    note's mark"): "per m^2^" is "per m" in paper.yaml, `init` names the 2 it left out, and the
    Title paragraph is in the comment as it was."""
    powered = PAPER.replace('title: "Outcomes after a fall"', 'title: "Falls per m^2^"')
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(word(tmp_path / "word", powered))]) == 0
    said = capsys.readouterr().out
    assert yaml.safe_load((root / "paper.yaml").read_text(encoding="utf-8"))["title"] == (
        "Falls per m")
    assert "the superscript '2' at its end was taken for the mark of a note" in said
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert "Title: Falls per m^2^" in text[text.index("<!--") : text.index("-->")]


@needs_pandoc
@pytest.mark.parametrize(("typed", "title", "kept"), [
    ("Outcomes after a fall**^1^**", "Outcomes after a fall1", "Outcomes after a fall**^1^**"),
    ("Outcomes after a fall*^1^*", "Outcomes after a fall1", "Outcomes after a fall*^1^*"),
    ("Outcomes after a fall^1^[]{#bm}", "Outcomes after a fall1",
     "Outcomes after a fall^1^[]{#bm .anchor}"),
    ("Outcomes after a fall^1^", "Outcomes after a fall", "Outcomes after a fall^1^"),
], ids=["in bold", "in italic", "before a bookmark", "alone"])  # fmt: skip
def test_a_word_title_s_mark_inside_a_wrapper_stays_in_the_title(
        tmp_path: Path, capsys, typed: str, title: str, kept: str) -> None:  # fmt: skip
    """A known gap (DESIGN.md, Known gaps, "A Word title's mark inside a wrapper stays in the
    title"): a mark pandoc reads inside bold, or followed by an empty bookmark, is printed as
    part of the title, "a fall1", and taken for no mark; the Title paragraph is in the comment.
    The mark alone is left out."""
    marked = PAPER.replace('title: "Outcomes after a fall"', f'title: "{typed}"')
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(word(tmp_path / "word", marked))]) == 0
    said = capsys.readouterr().out
    assert yaml.safe_load((root / "paper.yaml").read_text(encoding="utf-8"))["title"] == title
    assert f"title: {title!r}, from its Title paragraph" in said
    assert ("taken for the mark of a note" in said) is (title == "Outcomes after a fall")
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert f"Title: {kept}\n" in text[text.index("<!--") : text.index("-->")]


@needs_pandoc
def test_a_title_init_does_not_take_is_refused_with_how_to_give_one(tmp_path: Path, capsys) -> None:
    backslash = chr(92)
    markdown = f"---\ntitle: 'IFN-{backslash * 2}gamma release assays'\n---\n\n# Methods\n\nText.\n"
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(word(tmp_path / "word", markdown))]) == 2
    err = capsys.readouterr().err
    assert f"`{backslash}gamma` stands outside dollar signs" in err
    assert err.rstrip().endswith("; give one with --title")
    assert not (root / "manuscript" / "main.md").exists()


@needs_pandoc
def test_a_long_run_before_the_first_heading_stays_in_the_text(tmp_path: Path, capsys) -> None:
    """An introduction with no heading over it is the paper, not its title page."""
    words = " ".join(["Falls"] * (TITLE_PAGE_WORDS + 1)) + " were 17."
    paper = word(tmp_path / "word", f"{words}\n\n# Methods\n\nWe counted.\n")
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(paper)]) == 0
    assert "so they were left in the text" in capsys.readouterr().out
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert "<!--" not in text and "were 17." in text


@needs_pandoc
@pytest.mark.parametrize("over", [0, 1], ids=["600 words", "601 words"])
def test_init_sets_aside_a_title_page_by_a_count_of_words(
        tmp_path: Path, capsys, over: int) -> None:  # fmt: skip
    """A known gap (DESIGN.md, Known gaps, "What `init --from` sets aside is chosen by a count
    of words"): a short title page and an introduction with no heading over it, 600 words in
    all, are set aside together, and no gate reads the introduction's 17; at 601 words they
    stay in the text, where the 12 of the affiliation is read. `init` says which, and how many
    words."""
    page = "Falls in older patients\n\nAnne Example, Ward 12, Somewhere University\n\n"
    tail = "were 17 in the ward."
    words = TITLE_PAGE_WORDS + over
    filler = " ".join(["Falls"] * (words - len(page.split()) - len(tail.split())))
    paper = word(tmp_path / "word", f"{page}{filler} {tail}\n\n# Methods\n\nWe counted.\n")
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(paper)]) == 0
    said = capsys.readouterr().out
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    code, found = findings(capsys, str(root), "--stage", "drafting")
    read = sorted(f["message"] for f in found if f["code"] == "unclassified-number")
    if over:
        assert (f"title page: the {words} words before the first heading are more than a title "
                f"page holds ({TITLE_PAGE_WORDS}), so they were left in the text") in said
        assert "<!--" not in text
        assert read == ["'12' is not bound to any source", "'17' is not bound to any source"]
    else:
        assert (f"title page: the {words} words before the first heading were set aside in a "
                "comment at the top of main.md") in said
        comment = text[text.index("<!--") : text.index("-->")]
        assert "Ward 12" in comment and "were 17 in the ward." in comment
        assert read == []


@needs_pandoc
def test_a_paper_with_no_heading_sets_nothing_aside(tmp_path: Path, capsys) -> None:
    paper = word(tmp_path / "word", "**Methods**\n\nWe counted 17.\n")
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(paper)]) == 0
    assert "no paragraph is in a heading style" in capsys.readouterr().out
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert "<!--" not in text and "We counted 17." in text


@needs_pandoc
def test_nothing_in_the_title_page_closes_its_comment(tmp_path: Path, capsys) -> None:
    """pandoc escapes the `>` of `-->` in text, and not in code, which a comment ends at."""
    paper = word(tmp_path / "word", "Arrows `a-->b` and 42 there\n\n# Methods\n\nWe counted.\n")
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(paper)]) == 0
    capsys.readouterr()
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert text.count("-->") == 1 and "a--&gt;b" in text
    code, found = findings(capsys, str(root), "--stage", "drafting")
    assert not [f for f in found if f.get("context") and "42" in f["context"]]


def test_a_word_97_document_is_refused_before_anything_is_made(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.doc"
    paper.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(504))
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(paper)]) == 2
    assert "save it as .docx" in capsys.readouterr().err
    assert not root.exists()


def test_a_file_that_is_no_docx_is_refused(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.docx"
    paper.write_text("Not a Word document.", encoding="utf-8")
    assert main(["init", str(tmp_path / "project"), "--from", str(paper)]) == 2
    assert "is not a .docx" in capsys.readouterr().err


def test_a_missing_pandoc_is_said(tmp_path: Path, capsys, monkeypatch) -> None:
    import manuscript_guard.build.document as document

    monkeypatch.setattr(document.shutil, "which", lambda name: None)
    paper = tmp_path / "paper.docx"
    paper.write_bytes(b"PK\x03\x04" + bytes(100))
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(paper)]) == 2
    err = capsys.readouterr().err
    assert "pandoc is not on PATH" in err and "paper.docx" in err
    assert not root.exists()


def test_from_with_latex_is_refused(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.docx"
    paper.write_bytes(b"PK\x03\x04" + bytes(100))
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(paper), "--latex"]) == 2
    assert "a Markdown manuscript" in capsys.readouterr().err
    assert not root.exists()


def test_a_project_with_a_manuscript_is_not_written_over(tmp_path: Path, capsys) -> None:
    root = tmp_path / "project"
    assert main(["init", str(root)]) == 0
    before = (root / "manuscript" / "main.md").read_bytes()
    paper = tmp_path / "paper.docx"
    paper.write_bytes(b"PK\x03\x04" + bytes(100))
    capsys.readouterr()
    assert main(["init", str(root), "--from", str(paper)]) == 2
    assert "nothing was made" in capsys.readouterr().err
    assert (root / "manuscript" / "main.md").read_bytes() == before


def _as_read(monkeypatch, *, title: str | None = None, authors: tuple[str, ...] = (),
             media: tuple = ()) -> None:  # fmt: skip
    """`convert` replaced by one that returns a paper with this title, these authors and these
    pictures, so that what init does with them is tested with no pandoc."""

    def read(path: Path, *, titled: bool = False) -> from_word.Converted:
        return from_word.Converted(
            title=None if titled else title, authors=authors, abstract=False,
            text="# Methods\n\nWe counted.\n", media=media, tables=0, tables_left=(),
            title_page="the document opens on a heading, so nothing was set aside", headings=1,
        )  # fmt: skip

    monkeypatch.setattr(from_word, "convert", read)


@pytest.mark.parametrize(
    ("kept", "given", "title", "authors", "refused"),
    [
        ("paper.yaml", None, "Outcomes after a fall", (), True),
        ("paper.yaml", "Another title", "Outcomes after a fall", (), False),
        ("paper.yaml", None, None, (), False),
        ("authors.yaml", None, None, ("Anne Example",), True),
        ("authors.yaml", None, "Outcomes after a fall", (), False),
    ],
)
def test_a_project_file_is_refused_only_where_the_word_paper_would_fill_it(
        tmp_path: Path, capsys, monkeypatch, kept: str, given: str | None, title: str | None,
        authors: tuple[str, ...], refused: bool) -> None:  # fmt: skip
    """init keeps a file that is there. Where the Word title or names would go into it, it
    would have kept them nowhere; where nothing from the paper goes into it, it is kept."""
    _as_read(monkeypatch, title=title, authors=authors)
    root = tmp_path / "project"
    root.mkdir()
    (root / kept).write_text("mine\n", encoding="utf-8")
    paper = tmp_path / "paper.docx"
    paper.write_bytes(b"PK\x03\x04" + bytes(100))
    asked = ["init", str(root), "--from", str(paper)]
    if given is not None:
        asked += ["--title", given]
    if refused:
        assert main(asked) == 2
        err = capsys.readouterr().err
        assert f"{kept} is already there, and init keeps it" in err and "nothing was made" in err
        assert sorted(path.name for path in root.iterdir()) == [kept]
    else:
        assert main(asked) == 0
        out = capsys.readouterr().out
        assert (root / "manuscript" / "main.md").exists()
        # Nothing said of the kept file is false: init neither made it nor wrote into it.
        assert f"created {root / kept}" not in out
        assert "named in Author paragraphs" not in out
        if kept == "paper.yaml":
            assert "title: none taken from a Title paragraph" in out
    assert (root / kept).read_text(encoding="utf-8") == "mine\n"


@pytest.mark.parametrize(
    ("media", "there"),
    [
        ((("manuscript/media/word/b.png", b"b"),), "manuscript/media/word"),
        ((("manuscript/media/word/b.png", b"b"),), "manuscript"),
        ((("manuscript/media/a.png", b"a"),), "manuscript/media/a.png"),
        ((("manuscript/media/A.png", b"a"), ("manuscript/media/a.png", b"b")), None),
        ((("manuscript/media/a", b"a"), ("manuscript/media/A/b.png", b"b")), None),
    ],
)
def test_a_picture_that_cannot_be_written_is_refused_before_anything_is_made(
        tmp_path: Path, capsys, monkeypatch, media: tuple, there: str | None) -> None:  # fmt: skip
    """The pictures are written after the project is made: an error then was a traceback
    and half a project."""
    _as_read(monkeypatch, media=media)
    root = tmp_path / "project"
    if there is not None:
        (root / there).parent.mkdir(parents=True, exist_ok=True)
        (root / there).write_bytes(b"mine")
    paper = tmp_path / "paper.docx"
    paper.write_bytes(b"PK\x03\x04" + bytes(100))
    assert main(["init", str(root), "--from", str(paper)]) == 2
    assert "nothing was made" in capsys.readouterr().err
    made = sorted(path.relative_to(root).as_posix() for path in root.rglob("*")) if (
        root.exists()) else []  # fmt: skip
    assert made == ([] if there is None else
                    sorted({there, *(p.as_posix() for p in Path(there).parents if p.name)}))


def test_a_picture_pandoc_saved_outside_its_media_folder_is_brought_in_too(
        tmp_path: Path) -> None:  # fmt: skip
    """No image is left pointing into the temporary folder, which is gone once read."""
    folder = tmp_path / "extracted"
    (folder / "media").mkdir(parents=True)
    (folder / "word").mkdir()
    (folder / "media" / "a.png").write_bytes(b"a")
    (folder / "word" / "b.png").write_bytes(b"b")

    def image(target: str) -> dict:
        return {"t": "Image", "c": [_ATTR, [], [target, ""]]}

    images = [image(str(folder / "media" / "a.png")), image(str(folder / "word" / "b.png")),
              image("https://example.org/c.png")]  # fmt: skip
    tree = {"meta": {}, "blocks": [{"t": "Para", "c": images}]}
    assert _pictures(tree, folder) == (
        ("manuscript/media/a.png", b"a"), ("manuscript/media/word/b.png", b"b"))
    assert [one["c"][2][0] for one in images] == [
        "manuscript/media/a.png", "manuscript/media/word/b.png", "https://example.org/c.png"]


# The rewriting of a table, on pandoc's tree as pandoc 3 writes it, with no pandoc.

_ATTR = ["", [], []]
_LEFT = {"t": "AlignDefault"}


def _plain(*words: str) -> list:
    inlines: list = []
    for word_ in words:
        inlines += [{"t": "Space"}, {"t": "Str", "c": word_}] if inlines else [
            {"t": "Str", "c": word_}]
    return [{"t": "Plain", "c": inlines}]


def _cell(blocks: list, down: int = 1, across: int = 1) -> list:
    return [_ATTR, _LEFT, down, across, blocks]


def _table(head: list, body: list, foot: list, columns: int) -> dict:
    specs = [[_LEFT, {"t": "ColWidth", "c": 0.2}] for _ in range(columns)]
    return {"t": "Table", "c": [_ATTR, [None, []], specs, [_ATTR, head], [[_ATTR, 0, [], body]],
                                [_ATTR, foot]]}  # fmt: skip


def _texts(table: dict) -> list[list[str]]:
    rows = table["c"][3][1] + [row for body in table["c"][4] for row in body[3]]
    return [[text_of(cell[4]).strip() for cell in row[1]] for row in rows]


def test_a_merged_cell_keeps_its_text_once_in_its_first_row_and_column() -> None:
    table = _table(
        [[_ATTR, [_cell(_plain("Group")), _cell(_plain("Outcome"), across=2)]]],
        [[_ATTR, [_cell(_plain("Cases"), down=2), _cell(_plain("12")), _cell(_plain("17"))]],
         [_ATTR, [_cell(_plain("13")), _cell(_plain("18"))]]],
        [[_ATTR, [_cell(_plain("Total")), _cell(_plain("25")), _cell(_plain("35"))]]],
        columns=3,
    )  # fmt: skip
    assert _flatten(table) is None
    assert _texts(table) == [["Group", "Outcome", ""], ["Cases", "12", "17"], ["", "13", "18"],
                             ["Total", "25", "35"]]  # fmt: skip
    assert table["c"][5][1] == []


def test_a_second_header_row_becomes_the_first_of_the_body() -> None:
    table = _table(
        [[_ATTR, [_cell(_plain("A")), _cell(_plain("B"))]],
         [_ATTR, [_cell(_plain("n")), _cell(_plain("%"))]]],
        [[_ATTR, [_cell(_plain("3")), _cell(_plain("50"))]]], [], columns=2,
    )  # fmt: skip
    assert _flatten(table) is None
    assert len(table["c"][3][1]) == 1
    assert _texts(table) == [["A", "B"], ["n", "%"], ["3", "50"]]


def test_a_row_wider_than_its_table_is_left_as_it_came() -> None:
    table = _table([], [[_ATTR, [_cell(_plain("1")), _cell(_plain("2"))]]], [], columns=1)
    before = json.dumps(table)
    assert _flatten(table) == "a row with more cells than the table has columns"
    assert json.dumps(table) == before


def test_a_cell_joins_its_breaks_but_not_a_note() -> None:
    note = {"t": "Note", "c": [{"t": "Para", "c": [{"t": "Str", "c": "a"}, {"t": "SoftBreak"},
                                                   {"t": "Str", "c": "b"}]}]}  # fmt: skip
    cell = [{"t": "Para", "c": [{"t": "Strong", "c": [{"t": "Str", "c": "x"},
                                                      {"t": "LineBreak"}, {"t": "Str", "c": "y"}]},
                                note]},
            {"t": "BlockQuote", "c": [{"t": "Para", "c": [{"t": "Str", "c": "z"}]}]}]  # fmt: skip
    joined = _one_line(cell)
    assert joined[0] == {"t": "Strong", "c": [{"t": "Str", "c": "x"}, {"t": "Space"},
                                               {"t": "Str", "c": "y"}]}  # fmt: skip
    assert joined[1] is note
    assert joined[2:] == [{"t": "Space"}, {"t": "Str", "c": "z"}]
    assert _one_line([{"t": "OrderedList", "c": []}]) == "a numbered list"


def _pipe_cells(line: str) -> list[str]:
    """The cells of a row of a pipe table, as plain text."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _audited(capsys, path: Path) -> list[tuple[str, int | None, str]]:
    """What `audit --json` finds in `path`: each finding's code, line and message."""
    capsys.readouterr()
    main(["audit", str(path), "--json"])
    return [(f["code"], f["line"], f["message"])
            for f in json.loads(capsys.readouterr().out)["findings"]]  # fmt: skip


#: One table whose two categories stand one paragraph to a line in a single row, and the
#: same table with a row to each.
STACKED = """\
# Results

+--------+-----+-----------------+
| Sex    | n   | Cases (n = 120) |
+========+=====+=================+
| Male   | 36  | 36 (40.0%)      |
|        |     |                 |
| Female | 24  | 24 (20.0%)      |
+--------+-----+-----------------+

+--------+-----+-----------------+
| Sex    | n   | Cases (n = 120) |
+========+=====+=================+
| Male   | 36  | 36 (40.0%)      |
+--------+-----+-----------------+
| Female | 24  | 24 (20.0%)      |
+--------+-----+-----------------+
"""


@needs_pandoc
def test_a_word_table_s_rows_stacked_in_one_cell_become_one_row(tmp_path: Path, capsys) -> None:
    """A known gap (DESIGN.md, Known gaps, "A Word table's rows stacked in one cell become one
    row"): "Male" over "Female" and "36" over "24" in one row are one row of the pipe table,
    "Male Female" and "36 24", and the audit pairs no count with its share there, where the
    same table with a row to each has its 36 (40.0%) of 120 found off."""
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(word(tmp_path / "word", STACKED))]) == 0
    md = root / "manuscript" / "main.md"
    lines = md.read_text(encoding="utf-8").split("\n")
    rows = [(at, _pipe_cells(line)) for at, line in enumerate(lines, 1)
            if line.startswith("| ") and not line.startswith("| Sex")]  # fmt: skip
    assert [cells for _at, cells in rows] == [
        ["Male Female", "36 24", "36 (40.0%) 24 (20.0%)"],
        ["Male", "36", "36 (40.0%)"], ["Female", "24", "24 (20.0%)"]]  # fmt: skip
    found = [one for one in _audited(capsys, md) if one[0] == "does-not-fit"]
    assert found == [("does-not-fit", rows[1][0],
                      "n (%) 36 (40.0%): 36 of 120 is 30.00%, not 40.0; 40.0% is 36 of 90")]


#: A header whose "Cases (n = 120)" spans two columns, both of whose cells are off from 120.
MERGED_HEADER = """\
# Results

+----------------+-----------------------------+
| Characteristic | Cases (n = 120)             |
+================+==============+==============+
| Male           | 36 (40.0%)   | 60 (40.0%)   |
+----------------+--------------+--------------+
"""


@needs_pandoc
def test_a_merged_header_s_n_is_read_for_its_first_column_alone(tmp_path: Path, capsys) -> None:
    """A known gap (DESIGN.md, Known gaps, "A merged cell's text stands in its first column
    only"): "Cases (n = 120)" over two columns heads the first of them in the pipe table, the
    second's header empty, and the audit holds to 120 the first column's 36 (40.0%) alone: the
    second's 60 (40.0%), as far off, is not read."""
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(word(tmp_path / "word", MERGED_HEADER))]) == 0
    md = root / "manuscript" / "main.md"
    lines = md.read_text(encoding="utf-8").split("\n")
    header = next(line for line in lines if line.startswith("| Characteristic"))
    assert _pipe_cells(header) == ["Characteristic", "Cases (n = 120)", ""]
    row = next(at for at, line in enumerate(lines, 1) if line.startswith("| Male"))
    assert _pipe_cells(lines[row - 1]) == ["Male", "36 (40.0%)", "60 (40.0%)"]
    assert [one for one in _audited(capsys, md) if one[0] == "does-not-fit"] == [
        ("does-not-fit", row, "n (%) 36 (40.0%): 36 of 120 is 30.00%, not 40.0; 40.0% is 36 of 90")]


#: A table with a numbered list in a cell, which `init --from` leaves as a grid table.
LISTED = """\
# Results

+---------+-------------+
| Step    | What        |
+=========+=============+
| One     | 1. first    |
|         | 2. second   |
+---------+-------------+
| Two     | 33          |
+---------+-------------+
"""


@needs_pandoc
def test_a_numbered_list_in_a_grid_table_keeps_its_numbers(
        tmp_path: Path, capsys) -> None:  # fmt: skip
    """A known gap (DESIGN.md, Known gaps, "A table `init --from` leaves as a grid table keeps
    pandoc's numbering"): the list in a cell is written with its numbers, "1.", "2.", and
    `check` reports each as a number typed in a table, as it reports the 33 of the next row."""
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(word(tmp_path / "word", LISTED))]) == 0
    assert "a numbered list in a cell; written as a grid table" in capsys.readouterr().out
    lines = (root / "manuscript" / "main.md").read_text(encoding="utf-8").split("\n")
    at = {word_: next(n for n, line in enumerate(lines, 1) if word_ in line)
          for word_ in ("first", "second", "33")}  # fmt: skip
    assert [lines[at[name] - 1].split("|")[2].split() for name in ("first", "second")] == [
        ["1.", "first"], ["2.", "second"]]
    code, found = findings(capsys, str(root), "--stage", "drafting")
    assert sorted((f["line"], f["message"]) for f in found if f["code"] == "hand-authored-table"
                  ) == [(at["first"], "'1' in a hand-written table row"),
                        (at["second"], "'2' in a hand-written table row"),
                        (at["33"], "'33' in a hand-written table row")]  # fmt: skip


@pytest.mark.parametrize(
    "said",
    ["Anne Example, Bob Sample", "Anne Example and Bob Sample", "Anne Example1", "A. One; B. Two"],
)
def test_an_author_paragraph_that_is_not_one_name_is_set_aside(said: str) -> None:
    entry = {"t": "MetaInlines", "c": [{"t": "Str", "c": said}]}
    assert _names({"t": "MetaList", "c": [entry]}) == ((), [entry])


def test_an_author_paragraph_with_a_superscript_is_set_aside() -> None:
    entry = {"t": "MetaInlines", "c": [{"t": "Str", "c": "Anne"}, {"t": "Superscript", "c": []}]}
    assert _names({"t": "MetaList", "c": [entry]}) == ((), [entry])
    one = {"t": "MetaInlines", "c": [{"t": "Str", "c": "Anne"}, {"t": "Space"},
                                     {"t": "Str", "c": "O'Brien-Smith"}]}  # fmt: skip
    assert _names(one) == (("Anne O'Brien-Smith",), [])


#: An abstract in Word's Abstract style that does not stand straight after the title, author
#: and date paragraphs, where pandoc reads it as metadata: a line of the title page between.
ABSTRACT_LATER = """\
---
title: "Outcomes after a fall"
author:
  - Anne Example
---

Department of Things, Somewhere University

::: {custom-style="Abstract"}
We followed 120 patients.
:::

::: {custom-style="Abstract"}
Of them, 41 fell again.
:::

Corresponding author: Anne Example

# Introduction

Falls are common.
"""


@needs_pandoc
def test_an_abstract_styled_paragraph_before_the_first_heading_is_the_abstract(
    tmp_path: Path, capsys
) -> None:
    """Known gaps: pandoc reads the Abstract style as metadata only straight after the
    Title, Author and Date paragraphs. An abstract elsewhere before the first heading went
    into the comment with the title page, and no gate read its numbers. The paragraphs in
    the Abstract style are the section `# Abstract`; the rest of the title page stays set
    aside."""
    paper = word(tmp_path / "word", ABSTRACT_LATER)
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(paper)]) == 0
    said = capsys.readouterr().out
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    comment = text[text.index("<!--") : text.index("-->")]
    assert "Department of Things" in comment and "Corresponding author" in comment
    assert "120 patients" not in comment and "41 fell" not in comment
    section = "# Abstract\n\nWe followed 120 patients.\n\nOf them, 41 fell again.\n\n# Introduction"
    assert section in text, text
    assert "abstract: from its Abstract paragraphs" in said


@needs_pandoc
def test_an_abstract_styled_paragraph_before_a_title_word_numbers_is_the_abstract(
    tmp_path: Path,
) -> None:
    """Round 1 of #682: where the first heading is made of a title Word numbers, with an
    item of its list before it, an affiliation numbered "1.", the title page ends in that
    list cut where the heading was. The reading with styles was compared whole, and the
    paragraphs in the Abstract style were left in the comment."""
    paper = word(tmp_path / "word", ABSTRACT_LATER.replace(
        "# Introduction\n\nFalls are common.\n",
        "1. Somewhere University\n2. INTRODUCTION\n\nFalls are common.\n"))
    converted = from_word.convert(paper)
    assert converted.typed_headings[:1] == ("INTRODUCTION",)
    comment = converted.text[: converted.text.index("-->")]
    assert "Somewhere University" in comment and "Corresponding author" in comment
    assert "120 patients" not in comment and "41 fell" not in comment
    assert "# Abstract\n\nWe followed 120 patients.\n\nOf them, 41 fell again.\n\n# INTRODUCTION" \
        in converted.text.replace("\r\n", "\n"), converted.text


@needs_pandoc
def test_an_abstract_styled_paragraph_under_a_heading_stays_where_it_is(tmp_path: Path) -> None:
    """Only what is set aside as the title page is looked at: under a heading, a paragraph
    in the Abstract style is in the text already."""
    aside = 'Falls are common.\n\n::: {custom-style="Abstract"}\nAn aside 7.\n:::'
    paper = word(tmp_path / "word", ABSTRACT_LATER.replace("Falls are common.", aside))
    converted = from_word.convert(paper)
    assert converted.text.count("# Abstract") == 1
    assert converted.text.index("An aside 7.") > converted.text.index("# Introduction")


@needs_pandoc
def test_an_abstract_style_stays_set_aside_where_readings_differ(
        tmp_path: Path, monkeypatch) -> None:  # fmt: skip
    """A known gap (DESIGN.md, Known gaps, "`init --from` finds an abstract on the title page
    by its style alone"): where the reading with styles is not the ordinary one block for
    block, the paragraphs in the Abstract style stay in the comment with the title page, and
    what `init` prints says nothing of them. Where the two agree, they are the Abstract."""
    paper = word(tmp_path / "word", ABSTRACT_LATER)
    agreed = from_word.convert(paper)
    assert agreed.abstract and "# Abstract\n\nWe followed 120 patients." in (
        agreed.text.replace("\r\n", "\n"))
    read = from_word._styled_run
    monkeypatch.setattr(from_word, "_styled_run",
                        lambda path: [*read(path), ({"t": "Para", "c": []}, None)])
    differed = from_word.convert(paper)
    assert not differed.abstract and "# Abstract" not in differed.text
    comment = differed.text[: differed.text.index("-->")]
    assert "We followed 120 patients." in comment and "Of them, 41 fell again." in comment
    assert "abstract" not in from_word.what_was_done(paper, differed).lower()


@needs_pandoc
@pytest.mark.parametrize(("abstract", "made"), [
    ('::: {custom-style="Summary"}\nWe followed 120 patients.\n:::', False),
    ("**Abstract**\n\nWe followed 120 patients.", True),
    ("Abstract\n\nWe followed 120 patients.", True),
    ("Abstract: We followed 120 patients.", True),
], ids=["in another style", "under a line in bold", "under a plain line", "on a run-in label"])
def test_an_abstract_in_another_style_stays_in_the_comment(
        tmp_path: Path, capsys, abstract: str, made: bool) -> None:  # fmt: skip
    """A known gap (DESIGN.md, Known gaps, "`init --from` finds an abstract on the title page
    by its style alone"): an abstract in a style other than Abstract stays in the comment, and
    no gate reads its 120; under a line "Abstract" alone, in bold or not, or opening on a
    run-in "Abstract:", in a paper with a heading style, that line is made its heading, and
    `check` reads the 120."""
    markdown = (f"Falls in older patients\n\nDepartment of Things, Somewhere University\n\n"
                f"{abstract}\n\n# Introduction\n\nFalls are common.\n")
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(word(tmp_path / "word", markdown))]) == 0
    said = capsys.readouterr().out
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    comment = text[text.index("<!--") : text.index("-->")]
    assert "Department of Things" in comment
    assert ("We followed 120 patients." in comment) is not made
    assert ("# Abstract\n\nWe followed 120 patients.\n\n# Introduction" in text) is made
    assert ("were made headings, as the audit reads them: Abstract" in said) is made
    assert "abstract: from its Abstract paragraphs" not in said
    code, found = findings(capsys, str(root), "--stage", "drafting")
    assert [f["message"] for f in found if f["code"] == "unclassified-number"] == (
        ["'120' is not bound to any source"] if made else [])


def _restyled(docx: Path, name: str, change) -> Path:
    """A copy of `docx` beside it named `name`, each part's bytes `change(part, data)`, and
    without the parts for which it gives None."""
    import zipfile

    out = docx.with_name(name)
    with zipfile.ZipFile(docx) as source, zipfile.ZipFile(out, "w") as made:
        for info in source.infolist():
            data = change(info.filename, source.read(info.filename))
            if data is not None:
                made.writestr(info, data)
    return out


#: pandoc's writer defines an Abstract style in every .docx it makes, as Word does not.
_ABSTRACT_STYLE = rb'<w:style [^>]*w:styleId="Abstract"[^>]*>.*?</w:style>'


def _styles(change):
    """`change` applied to the styles part alone."""
    return lambda part, data: change(data) if part == "word/styles.xml" else data


#: The styles part of a Word paper, each way it can say what a paragraph in the Abstract
#: style is in, with whether a style is named Abstract by it.
STYLE_PARTS = {
    "as pandoc writes it": (_styles(lambda d: d), True),
    "with no styles part": (lambda part, data: None if part == "word/styles.xml" else data,
                            False),
    "with the style renamed": (_styles(lambda d: d.replace(
        b'<w:name w:val="Abstract"', b'<w:name w:val="Summary"')), False),
    "with the style's name left out": (_styles(lambda d: re.sub(
        rb'(w:styleId="Abstract"[^>]*>)\s*<w:name w:val="Abstract"\s*/>', rb"\1", d)), True),
    "with the name in lower case": (_styles(lambda d: d.replace(
        b'<w:name w:val="Abstract"', b'<w:name w:val="abstract"')), True),
    "with another id": (lambda part, data: data.replace(b'w:styleId="Abstract"', b'w:styleId="Zz9"')
                        if part == "word/styles.xml" else data.replace(
                            b'w:val="Abstract"', b'w:val="Zz9"')
                        if part == "word/document.xml" else data, True),
    "with the style undefined": (_styles(lambda d: re.sub(_ABSTRACT_STYLE, b"", d, flags=re.S)),
                                 False),
    # Word's "Strict Open XML Document": pandoc reads the `w:` prefix in another namespace
    # (round 1 of #752).
    "in Strict Open XML": (lambda part, data: data.replace(
        b"http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        b"http://purl.oclc.org/ooxml/wordprocessingml/main") if part.endswith(".xml") else data,
        True),
}


@needs_pandoc
@pytest.mark.parametrize("variant", list(STYLE_PARTS))
def test_a_style_is_named_abstract_wherever_pandoc_reads_a_paragraph_in_it(
        tmp_path: Path, variant: str) -> None:  # fmt: skip
    """Where no style is named Abstract, the reading with styles is not made
    (`from_word._names_the_abstract_style`): which holds only where pandoc's reading with
    styles then puts no paragraph in the Abstract style. Held here for each way the styles
    part can say it, against the pandoc that runs: one that read the styles otherwise fails
    it."""
    change, named = STYLE_PARTS[variant]
    paper = _restyled(word(tmp_path / "word", ABSTRACT_LATER), "variant.docx", change)
    tree = json.loads(subprocess.run(
        ["pandoc", str(paper), "-f", "docx+styles", "-t", "json"], capture_output=True,
        check=True, timeout=120).stdout)  # fmt: skip
    styled = [from_word._custom_style(block) for block in tree["blocks"]]
    assert (from_word.ABSTRACT_STYLE in styled) <= from_word._names_the_abstract_style(paper)
    assert from_word._names_the_abstract_style(paper) is named
    if from_word.ABSTRACT_STYLE in styled:
        # As main lifted it: round 1 of #752 found a Strict paper's left on the title page.
        converted = from_word.convert(paper)
        assert converted.abstract and "We followed 120 patients." not in (
            converted.text[: converted.text.index("-->")])


@needs_pandoc
def test_a_paper_with_no_abstract_style_is_read_once(tmp_path: Path, monkeypatch) -> None:
    """A Word paper with a title page and no style named Abstract, as Word papers have
    none, was read by pandoc twice, the second time with its styles to find paragraphs in the
    Abstract style there, which it has none of: a quarter of the time the 50 Word papers of
    the robustness sweep of 2026-11-21 took to convert, 25 s of a book's 80. It is read once,
    and converted as it was."""
    markdown = "".join(line for line in ABSTRACT_LATER.splitlines(keepends=True)
                       if not line.startswith(":::"))  # fmt: skip
    written = word(tmp_path / "word", markdown)
    paper = _restyled(written, "plain.docx", STYLE_PARTS["with the style undefined"][0])
    read = from_word._pandoc
    readings: list[str] = []

    def counted(arguments: list[str], given: str | None, path: Path) -> str:
        if given is None:
            readings.append(arguments[arguments.index("-f") + 1])
        return read(arguments, given, path)

    monkeypatch.setattr(from_word, "_pandoc", counted)
    once = from_word.convert(paper)
    assert readings == ["docx"]
    comment = once.text[: once.text.index("-->")]
    assert "Department of Things" in comment and "We followed 120 patients." in comment
    monkeypatch.setattr(from_word, "_names_the_abstract_style", lambda path: True)
    assert from_word.convert(paper) == once
    assert readings == ["docx", "docx", "docx+styles"]


#: A Word paper with no heading style, its section titles typed in bold, one of them also
#: underlined, as many are: a title page, an abstract of one paragraph, the main text under
#: "Background", a glossary, a "Declarations" over its statements and a reference list. And
#: what only looks like such a title: a bold title that names no section, a bold word that
#: opens a sentence, a section's name in bold inside a list item, and one in italics that
#: opens a sentence.
TITLED_IN_BOLD = """\
A study of falls

Anne MARTINEAU, Paul LEFEBVRE, PharmD, MSc

1\\. University of Exampleton, UNIEX, CEMX

**Abstract**

We followed 120 patients for a year.

**[Background]{.underline}**

Falls are common.

**Our cohort**

**Methods** were those of the protocol.

- **Results**

*Discussion* was planned.

**Methods**

We read the records.

**Results**

Of 120 patients, 41 fell.

**List of abbreviations**

ROR: reporting odds ratio

**Declarations**

**Authors' contributions**

AM and PL wrote it.

**References**

1\\. Doe J. A title. BMJ. 2020;1:2.
"""


def _headings(text: str) -> list[str]:
    return [line.rstrip("\r") for line in text.split("\n") if line.startswith("#")]


@needs_pandoc
def test_a_word_paper_titled_in_bold_has_its_sections_made_headings(tmp_path: Path) -> None:
    """With no paragraph in a heading style, a paragraph wholly in bold, underlined too or
    not, whose words are a section's name is made a heading, and the title page before the
    first is set aside: read as paragraphs, the title page, the glossary, the statements and
    the reference list were prose to every gate. A bold title that names no section, a bold
    word opening a sentence, a name inside a list item and one in italics opening a sentence
    stay text."""
    converted = from_word.convert(word(tmp_path / "word", TITLED_IN_BOLD))
    quote = "\N{RIGHT SINGLE QUOTATION MARK}"
    titles = ("Abstract", "Background", "Methods", "Results", "List of abbreviations",
              "Declarations", f"Authors{quote} contributions", "References")  # fmt: skip
    assert converted.typed_headings == titles
    # Pandoc writes the apostrophe straight, and escaped, in Markdown.
    assert [line.replace("\\", "") for line in _headings(converted.text)] == [
        f"# {title.replace(quote, chr(39))}" for title in titles]
    body = converted.text[converted.text.index("-->") :]
    assert "UNIEX" not in body and "**Our cohort**" in body and "*Discussion* was planned" in body
    assert "**Methods** were those" in body and "**Results**" in body
    assert converted.title_page.startswith("no paragraph is in a heading style, so the 8 ")


@needs_pandoc
def test_a_structured_abstract_titled_in_bold_is_the_abstracts(tmp_path: Path) -> None:
    """Its parts' titles straight under the Abstract's, with no words between, are the
    Abstract's, up to the main text's second "Background", as BMC's journals set them."""
    paper = ("**Abstract**\n\n**Background**\n\nFalls.\n\n**Methods**\n\nRecords.\n\n"
             "**Results**\n\n41 fell.\n\n**Background**\n\nFalls are common.\n\n"
             "**Methods**\n\nWe read them.\n\n**Results**\n\nOf 120, 41 fell.\n")  # fmt: skip
    converted = from_word.convert(word(tmp_path / "word", paper))
    assert _headings(converted.text) == [
        "# Abstract", "## Background", "## Methods", "## Results", "# Background",
        "# Methods", "# Results"]  # fmt: skip


#: A picture as pandoc writes one in a paragraph, its file `media/pic.png` (`_package`).
PICTURE = (
    '<w:r><w:drawing><wp:inline><wp:extent cx="12700" cy="12700"/><wp:docPr id="10" '
    'name="Picture"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/'
    'drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="11" name="Picture"/>'
    '<pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rPic"/><a:stretch>'
    '<a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
    '<a:ext cx="12700" cy="12700"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
    '</pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'
)


def _package(path: Path, body: str, styles: str, numbering: str = "") -> Path:
    """A .docx of `body`, `styles` and `numbering`, a `word/numbering.xml` where it is
    given, with the parts pandoc needs to find them, and the picture `PICTURE` points to."""
    import zipfile

    w = " ".join(f'xmlns:{prefix}="{space}"' for prefix, space in (
        ("w", "http://schemas.openxmlformats.org/wordprocessingml/2006/main"),
        ("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"),
        ("a", "http://schemas.openxmlformats.org/drawingml/2006/main"),
        ("pic", "http://schemas.openxmlformats.org/drawingml/2006/picture"),
        ("wp", "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing")))
    relations = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package = "http://schemas.openxmlformats.org/package/2006/relationships"
    main = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            f'<Override PartName="/word/document.xml" ContentType="{main}.document.main+xml"/>'
            f'<Override PartName="/word/styles.xml" ContentType="{main}.styles+xml"/>'
            + (f'<Override PartName="/word/numbering.xml" ContentType="{main}.numbering+xml"/>'
               if numbering else "") + "</Types>"))
        archive.writestr("_rels/.rels", (
            f'<Relationships xmlns="{package}"><Relationship Id="r1" '
            f'Type="{relations}/officeDocument" Target="word/document.xml"/></Relationships>'))
        numbered = (f'<Relationship Id="rNum" Type="{relations}/numbering" '
                    'Target="numbering.xml"/>' if numbering else "")  # fmt: skip
        archive.writestr("word/_rels/document.xml.rels", (
            f'<Relationships xmlns="{package}"><Relationship Id="r1" '
            f'Type="{relations}/styles" Target="styles.xml"/><Relationship Id="rPic" '
            f'Type="{relations}/image" Target="media/pic.png"/>{numbered}</Relationships>'))
        archive.writestr("word/media/pic.png", png())
        archive.writestr("word/document.xml",
                         f"<w:document {w}><w:body>{body}</w:body></w:document>")
        archive.writestr("word/styles.xml", f"<w:styles {w}>{styles}</w:styles>")
        if numbering:
            archive.writestr("word/numbering.xml", numbering)
    return path


@needs_pandoc
def test_the_audit_and_init_take_the_same_typed_titles(tmp_path: Path) -> None:
    """The audit reads a .docx itself, and `init --from` through pandoc: a title typed alone
    on its line is a heading to both, in bold by its run, by its character style or by none,
    in plain capitals, numbered as typed, in a bold paragraph style or with bold turned off;
    with its first line indented or hanging as far as it is indented; and one half in bold
    with other words, in a table's cell, in a link, in a caption beside a table, "Table
    Caption" as pandoc writes one or Word's "caption", indented from the left, which pandoc
    reads as a block quote, or beside a picture, to neither.
    Read otherwise, the audit's sections and G14's would be different ones; this test found
    pandoc reads no style's base, and sets a caption beside a table as the table's by the
    style's name, not its id."""
    from generated import BOLD_PARAGRAPH_STYLES, BOLD_PARAGRAPHS

    from manuscript_guard.text.docx import read_docx_text, typed_heading_levels

    table = "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    shapes = {kind: (shape, kind not in ("half", "in a cell", "in a link"))
              for kind, (shape, _bold) in BOLD_PARAGRAPHS.items()}  # fmt: skip
    plain = "<w:p><w:r><w:t>{}</w:t></w:r></w:p>"
    shapes |= {
        "plain capitals": (plain, True),
        "numbered as typed": (plain.replace("{}", "2. {}"), True),
        "a table's caption before it": (
            '<w:p><w:pPr><w:pStyle w:val="TC"/></w:pPr><w:r><w:t>{}</w:t></w:r></w:p>' + table,
            False),
        "Word's caption after a table": (
            table + '<w:p><w:pPr><w:pStyle w:val="Legende"/></w:pPr><w:r><w:t>{}</w:t></w:r>'
            "</w:p>", False),
        # pandoc 3.9.0.2 reads a paragraph indented from the left more than it hangs as a
        # block quote, and one holding a picture as an image beside words.
        "indented from the left": (plain.replace("<w:p>", '<w:p><w:pPr><w:ind w:left="720"/>'
                                                 "</w:pPr>"), False),
        "hanging as far as indented": (plain.replace(
            "<w:p>", '<w:p><w:pPr><w:ind w:left="720" w:hanging="720"/></w:pPr>'), True),
        "first line indented": (plain.replace(
            "<w:p>", '<w:p><w:pPr><w:ind w:firstLine="720"/></w:pPr>'), True),
        "with a picture": (plain.replace("<w:p>", "<w:p>" + PICTURE), False),
    }  # fmt: skip
    styles = BOLD_PARAGRAPH_STYLES + (
        '<w:style w:type="paragraph" w:styleId="TC"><w:name w:val="Table Caption"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Legende"><w:name w:val="caption"/></w:style>')
    names = ("Abstract", "Introduction", "Methods", "Results", "Discussion", "Conclusions",
             "Funding", "References", "Acknowledgements", "Limitations", "Abbreviations",
             "Appendix", "Declarations", "Ethics", "Tables", "Figures",
             "Supplementary material")  # fmt: skip
    typed = [(shape, heading, name.upper() if kind == "plain capitals" else name)
             for (kind, (shape, heading)), name in zip(shapes.items(), names, strict=True)]
    body = "".join(f"{shape.format(name)}<w:p><w:r><w:t>Words {at}.</w:t></w:r></w:p>"
                   for at, (shape, _heading, name) in enumerate(typed))  # fmt: skip
    paper = _package(tmp_path / "paper.docx", body, styles)
    expected = tuple(("2. " if "2. {}" in shape else "") + name
                     for shape, heading, name in typed if heading)  # fmt: skip
    converted = from_word.convert(paper)
    assert converted.typed_headings == expected
    assert converted.headings == len(expected)
    document = read_docx_text(paper)
    lines = document.body.split("\n")
    assert tuple(lines[at] for at, _level in typed_heading_levels(document)) == expected


#: Word's heading styles at levels 1 to 4, as pandoc reads them by their names.
_HEADING_STYLES = "".join(
    f'<w:style w:type="paragraph" w:styleId="Heading{n}"><w:name w:val="heading {n}"/>'
    "</w:style>" for n in (1, 2, 3, 4))  # fmt: skip


def _styled(text: str, level: int) -> str:
    return (f'<w:p><w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr><w:r><w:t>{text}</w:t>'
            "</w:r></w:p>")  # fmt: skip


def _paragraph(text: str, bold: bool = False) -> str:
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:p><w:r>{props}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


#: The shapes of `test_the_audit_and_init_set_the_same_heading_styles_aside` whose styles
#: both readers keep.
#: Headings of one sentence's words, after the first typed title (round 2 of #688).
_SENTENCE_HEADINGS = ("Strengths and limitations of this study", "What this study adds",
                      "Association between exposure and outcome",
                      "Data were collected in the clinic", "Early vs. Late Initiation",
                      "Smith et al. Revisited")  # fmt: skip
_STYLES_KEPT = ("no Results", "a styled Methods", "APA subheadings", "a styled header row",
                "a styled Methods cell first", "an empty styled paragraph",
                *_SENTENCE_HEADINGS)  # fmt: skip
#: A table's header row in Heading 3, "Methods | Findings | Notes" to the audit's lines.
_STYLED_ROW = "".join(f"<w:tc>{_styled(name, 3)}</w:tc>" for name in ("Methods", "Findings",
                                                                      "Notes"))  # fmt: skip


@needs_pandoc
@pytest.mark.parametrize("shape", ["authors and a note", "two paragraphs of prose",
                                   "a styled cell on the title page", *_STYLES_KEPT])
def test_the_audit_and_init_set_the_same_heading_styles_aside(tmp_path: Path, shape: str) -> None:
    """Where no paragraph in a heading style names a section alone, each is a stray line, on
    the title page before the first typed title or a paragraph of prose (Basile,
    2026-11-15, "Only stray lines"), and the typed titles can be placed and name an Abstract
    and a Results, both readers set the styles aside and take the typed titles for headings:
    styles on the authors' line and a note (docx-psych-A1 of the real-paper corpus), on two
    paragraphs of prose (docx-med-A2), on a title page's table's cell too, which both count
    among the paragraphs they say were in a heading style. `init --from` makes each styled
    paragraph a paragraph of its own words. With no Results among the titles, beside a
    styled "Methods", a header row "Methods | Findings | Notes" in Heading 3, read by its
    cells' own words, the same row before the Abstract, or APA's subheadings in Heading 2
    under typed titles, both read the styles, and `init --from` keeps "## Participants"
    (round 1 of #688); and so they do beside an empty paragraph in a heading style, which
    pandoc 3.9.0.2 keeps as an empty heading, or a heading of one sentence's words after the
    first typed title, "Strengths and limitations of this study": prose there is two
    sentences, as docx-med-A2's paragraphs are (round 2)."""
    from manuscript_guard.audit import audit
    from manuscript_guard.text.docx import read_docx_text, typed_heading_levels
    from manuscript_guard.text.docx_abstract import placed_headings

    prose = ("Falls are common in older patients. Many are harmed.",
             "Some of them die. We read why.")  # fmt: skip
    results = "Outcomes" if shape == "no Results" else "Results"
    methods = (_styled("Methods", 1) if shape == "a styled Methods"
               else _paragraph("Methods", True))  # fmt: skip
    if shape == "an empty styled paragraph":
        methods = '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr></w:p>' + methods
    if shape in _SENTENCE_HEADINGS:
        methods = _styled(shape, 2) + methods
    authors = (_styled("Ana Martin, Paul Girard", 4) + _styled("Both wrote it equally.", 4)
               if shape != "two paragraphs of prose" else _paragraph("Ana Martin, Paul Girard"))
    if shape == "a styled cell on the title page":
        authors += (f"<w:tbl><w:tr><w:tc>{_styled('Department of Medicine, Caen', 3)}</w:tc>"
                    "</w:tr></w:tbl>")  # fmt: skip
    if shape == "a styled Methods cell first":
        authors += f"<w:tbl><w:tr>{_STYLED_ROW}</w:tr></w:tbl>"
    introduction = (_paragraph(prose[0]) + _paragraph(prose[1]) if shape != "two paragraphs "
                    "of prose" else _styled(prose[0], 2) + _styled(prose[1], 2))  # fmt: skip
    records = _paragraph("We read 412 records.")
    if shape == "APA subheadings":
        records = (_styled("Participants", 2) + records + _styled("Measures", 2)
                   + _paragraph("Falls were counted.") + _styled("Statistical analysis", 2)
                   + _paragraph("We used odds ratios."))  # fmt: skip
    table = ""
    if shape == "a styled header row":
        table = (f"<w:tbl><w:tr>{_STYLED_ROW}</w:tr><w:tr><w:tc>{_paragraph('1')}</w:tc>"
                 "</w:tr></w:tbl>")  # fmt: skip
    body = (authors + _paragraph("Abstract", True) + _paragraph("Of 412 patients, 77 fell.")
            + _paragraph("Introduction", True) + introduction + methods + records
            + _paragraph(results, True) + _paragraph("Of 412 patients, 77 fell.") + table
            + _paragraph("Discussion", True) + _paragraph("It was so."))  # fmt: skip
    paper = _package(tmp_path / "paper.docx", body, _HEADING_STYLES)
    converted = from_word.convert(paper)
    document = read_docx_text(paper)
    lines = document.body.split("\n")
    if shape in _STYLES_KEPT:
        assert converted.typed_headings == ()
        assert document.heading_levels != ()
        # A styled cell places to the audit beside a heading outside a table, and pandoc keeps
        # it in its cell (#678): the rest are the same headings.
        assert converted.headings == len([heading for heading in placed_headings(document)
                                          if heading.line not in document.cells])  # fmt: skip
        if shape == "APA subheadings" or shape in _SENTENCE_HEADINGS:
            kept = "Participants" if shape == "APA subheadings" else shape
            assert f"## {kept}" in _headings(converted.text), converted.text
            assert kept in [heading.title for heading in placed_headings(document)]
        return
    titles = ("Abstract", "Introduction", "Methods", "Results", "Discussion")
    assert converted.typed_headings == titles
    assert _headings(converted.text) == [f"# {title}" for title in titles]
    assert document.heading_levels == ()
    assert tuple(lines[at] for at, _level in typed_heading_levels(document)) == titles
    styled = [lines[at] for at in sorted(document.headings)]
    # Each styled paragraph is a paragraph of its own words, in the text or the title page;
    # a cell's stays in its table.
    written = {line.rstrip("\r") for line in converted.text.split("\n")}
    assert {lines[at] for at in document.headings - document.cells} <= written, converted.text
    # Both count the same paragraphs in a heading style, a cell's among them.
    count = 3 if shape == "a styled cell on the title page" else 2
    assert len(styled) == count
    said = f"none of its {count} paragraphs in a heading style names a section alone"
    assert said in converted.title_page, converted.title_page
    (read,) = audit([paper], []).headings
    assert said in read, read


def test_a_heading_in_a_note_is_not_read_for_the_styles_set_aside() -> None:
    """`init --from` reads a paper's headings for the rule in its body alone, as the audit
    reads its paragraphs in a heading style (round 2 of #688): a heading "Methods" in a
    note's text keeps nothing from being set aside."""
    from generated import stray_styled_blocks

    paper = [("styled", "Ana Martin, Paul Girard", 4), *(
        item for name in ("Abstract", "Introduction", "Results", "Discussion")
        for item in (("title", name, True), ("words", "Of 412 fell.")))]
    blocks = stray_styled_blocks(paper)
    note = {"t": "Note", "c": [{"t": "Header", "c": [1, ["", [], []], [
        {"t": "Str", "c": "Methods"}]]}]}  # fmt: skip
    blocks[2]["c"].append(note)
    made = from_word.stray_headers_set_aside(json.loads(json.dumps(blocks)))
    assert made is not None and made[1] == 1


@needs_pandoc
def test_the_audit_and_init_take_the_same_titles_word_numbers(tmp_path: Path) -> None:
    """A title Word numbers as a list's item is a heading to both readers where pandoc reads
    it as the lone item of a numbered list in no other (Basile, 2026-11-14): by its own
    numbering or its style's, at any level, in capitals with a colon, in bold, after an
    empty paragraph, indented in List Paragraph as Word indents an item, with a subtitle its
    style numbers "1.1." beside it, which pandoc reads as an item beside it, and named by a
    numbering pandoc reads no level of, a paragraph to it. One with an item under it or a
    paragraph pandoc joins to it, one Word bullets, a list's sentence, "Results of the
    survey", and the subtitle are a heading to neither.
    What the audit places is what `init --from` makes, at the same levels, its name alone."""
    from generated import NUMBERED_STYLES, TYPED_PARAGRAPH_NUMBERING, numbered

    from manuscript_guard.text.docx import read_docx_text, typed_heading_levels

    styled = '<w:p><w:pPr><w:pStyle w:val="{}"/></w:pPr><w:r><w:t>{{}}</w:t></w:r></w:p>'
    shapes = {
        "own numbering": (numbered(), True),
        "a level deeper": (numbered(1), True),
        "by its style": (styled.format("NumTitle"), True),
        "in bold": (numbered().replace("<w:r>", "<w:r><w:rPr><w:b/></w:rPr>"), True),
        "after an empty paragraph": ("<w:p/>" + numbered(), True),
        "a subtitle beside it": (styled.format("NumTitle") + styled.format("NumSub").format(
            "Study design"), True),
        "a numbering of no level": (numbered(0, 77), True),
        "an item under it": (numbered() + numbered(1).format("Participants"), False),
        "a paragraph joined": (numbered() + numbered(0, 0).format("Our aims."), False),
        "bulleted": (numbered(0, 2), False),
        "a sentence": (numbered().format("Results were clear."), False),
        "a name opening an item": (numbered().format("Results of the survey"), False),
        # Round 1 of #682: an item indented as Word indents one, in List Paragraph.
        "indented, in List Paragraph": (numbered(style="ListParagraph", indent=True), True),
    }  # fmt: skip
    names = ("INTRODUCTION:", "Methods", "Results", "Discussion", "Conclusions", "Funding",
             "Ethics", "Limitations", "Declarations", "Appendix", "Abbreviations",
             "References", "Acknowledgements")  # fmt: skip
    body, expected = "", []
    for (kind, (shape, heading)), name in zip(shapes.items(), names, strict=True):
        body += (shape.format(name) if "{}" in shape else shape) + (
            f"<w:p><w:r><w:t>Words of {kind}.</w:t></w:r></w:p>")  # fmt: skip
        if heading:
            expected.append(name.rstrip(":"))
    paper = _package(tmp_path / "paper.docx", body, NUMBERED_STYLES, TYPED_PARAGRAPH_NUMBERING)
    converted = from_word.convert(paper)
    assert converted.typed_headings == tuple(expected)
    made = [line for line in converted.text.splitlines() if line.startswith("#")]
    document = read_docx_text(paper)
    lines = document.body.split("\n")
    placed = typed_heading_levels(document)
    assert tuple(lines[at].rstrip(":") for at, _level in placed) == tuple(expected)
    assert ["#" * level + " " + lines[at].rstrip(":") for at, level in placed] == made
    # The items no heading was made of are still a list's, numbered where pandoc had them.
    assert "Results were clear." in converted.text and "Participants" in converted.text


@needs_pandoc
@pytest.mark.parametrize("shape", ["typed", "numbered by Word", "in bold"])
def test_the_audit_and_init_take_result_in_the_singular_alike(tmp_path: Path, shape: str) -> None:
    """"Result", the Results in the singular (Basile, 2026-11-15), is a typed title to both
    readers, at the same level: "RESULT:" typed, as a title Word numbers in List Paragraph
    and in bold (docx-med-A3 of the real-paper corpus), and "Result:" in bold (docx-med-A2).
    "Result of the survey" after it is text to both."""
    from generated import NUMBERED_STYLES, TYPED_PARAGRAPH_NUMBERING, numbered

    from manuscript_guard.text.docx import read_docx_text, typed_heading_levels

    plain = "<w:p><w:r><w:t>{}</w:t></w:r></w:p>"
    title, name = {
        "typed": (plain.format("RESULT:"), "RESULT"),
        "numbered by Word": (numbered(style="ListParagraph", indent=True).replace(
            "<w:r>", "<w:r><w:rPr><w:b/></w:rPr>").format("RESULT:"), "RESULT"),
        "in bold": ("<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Result:</w:t></w:r></w:p>", "Result"),
    }[shape]  # fmt: skip
    body = "".join((plain.format("ABSTRACT"), plain.format("We read 412 records."),
                    plain.format("METHODS"), plain.format("We read them."), title,
                    plain.format("Of 412, 77 had it."), plain.format("Result of the survey"),
                    plain.format("DISCUSSION"), plain.format("It was so.")))  # fmt: skip
    paper = _package(tmp_path / "paper.docx", body, NUMBERED_STYLES, TYPED_PARAGRAPH_NUMBERING)
    converted = from_word.convert(paper)
    expected = ("ABSTRACT", "METHODS", name, "DISCUSSION")
    assert converted.typed_headings == expected
    document = read_docx_text(paper)
    lines = document.body.split("\n")
    placed = typed_heading_levels(document)
    assert tuple(lines[at].rstrip(":") for at, _level in placed) == expected
    made = [line for line in converted.text.splitlines() if line.startswith("#")]
    assert ["#" * level + " " + lines[at].rstrip(":") for at, level in placed] == made
    assert "Result of the survey" in converted.text


def test_a_title_word_numbers_splits_its_list_there() -> None:
    """A numbered list's item that is a title is made a heading where it stands: the items
    before it stay a list, numbered as they were, and the items after it another, numbered
    on from where they stood. A title the bold fallback leaves out stays in its list, which
    is as it was."""
    from generated import _listed, _str

    blocks = [_listed([_str("Our"), {"t": "Space"}, _str("aims.")], [_str("Methods")],
                      [_str("More.")], [_str("Results")], start=4),
              {"t": "Para", "c": [_str("We read.")]}]
    made, titles = from_word.typed_headings(json.loads(json.dumps(blocks)))
    assert titles == ("Methods", "Results")
    assert [block["t"] for block in made] == ["OrderedList", "Header", "OrderedList", "Header",
                                              "Para"]  # fmt: skip
    assert [block["c"][0][0] for block in made if block["t"] == "OrderedList"] == [4, 6]
    # Typed twice, the titles are placed by those in bold, and a plain one stays an item.
    bold = {"t": "Para", "c": [{"t": "Strong", "c": [_str("Introduction")]}]}
    twice = [bold, {"t": "Para", "c": [_str("Text.")]},
             {"t": "Para", "c": [{"t": "Strong", "c": [_str("Results")]}]},
             {"t": "Para", "c": [_str("Text.")]}, json.loads(json.dumps(blocks[0]))]
    made, titles = from_word.typed_headings(twice)
    assert titles == ("Introduction", "Results")
    assert made[-1] == blocks[0]


@needs_pandoc
def test_a_short_paper_with_only_a_late_bold_title_keeps_its_text(tmp_path: Path) -> None:
    """A research letter with no heading but a bold "References" after its text: its text is
    no title page, and is not set aside where no gate reads it (round 1 of #598). A title's
    number is kept in its heading."""
    paper = ("Of 412 patients, 77 had the event.\n\nIt was rare.\n\n**References**\n\n"
             "1\\. Doe J. A title. BMJ. 2020;1:2.\n")  # fmt: skip
    converted = from_word.convert(word(tmp_path / "letter", paper))
    assert "<!--" not in converted.text and "77 had the event" in converted.text
    assert "the first, References, opens no paper" in converted.title_page
    numbered = from_word.convert(word(tmp_path / "numbered", "**1. Abstract**\n\nWe read.\n\n"
                                      "**2. Methods**\n\nRecords.\n"))  # fmt: skip
    assert [line.replace("\\", "") for line in _headings(numbered.text)] == [
        "# 1. Abstract", "# 2. Methods"]
    # The Lancet's "Summary" opens a paper, and its title page is set aside (round 2).
    lancet = from_word.convert(word(tmp_path / "lancet", "Jane Doe, Caen.\n\n**Summary**\n\n"
                                    "We read.\n\n**Introduction**\n\nText.\n"))  # fmt: skip
    assert "Jane Doe" not in lancet.text[lancet.text.index("-->") :]


#: A Word paper with no heading style whose titles are typed as plain paragraphs, as the
#: real-paper corpus had them (2026-11-11): "ABSTRACT" in capitals, numbered titles in
#: capitals, a section's name as a table's caption and in a list's item, and a sentence that
#: opens with "Results".
TYPED_TITLES = """\
A study of things

ABSTRACT

We followed 120 patients.

1\\. INTRODUCTION

Falls are common.

| Group | n |
|---|---|
| A | 4 |

: RESULTS

- RESULTS

Results were clear.

3\\. RESULTS

Of 120, 41 fell.
"""


@needs_pandoc
def test_a_word_paper_with_typed_titles_has_them_made_headings(tmp_path: Path) -> None:
    """A title typed alone on its line, in no bold, is a heading to `init --from` and to the
    audit alike: "ABSTRACT", "1. INTRODUCTION", "3. RESULTS". A sentence that opens with
    "Results", a list's item and a table's caption stay what they are. What `init` prints
    counts the headings it made, where it said "headings: 0" after making 14 (PsyArXiv
    fyxeq_v2 of the real-paper corpus)."""
    from manuscript_guard.text.docx import read_docx_text, typed_heading_levels

    paper = word(tmp_path / "word", TYPED_TITLES)
    converted = from_word.convert(paper)
    assert converted.typed_headings == ("ABSTRACT", "1. INTRODUCTION", "3. RESULTS")
    assert [line.replace("\\", "") for line in _headings(converted.text)] == [
        "# ABSTRACT", "# 1. INTRODUCTION", "# 3. RESULTS"]
    body = converted.text[converted.text.index("-->") :]
    assert "Results were clear." in body and "- RESULTS" in body and ": RESULTS" in body
    assert "  headings: 3" in from_word.what_was_done(paper, converted).split("\n")
    # Round 3 of #641: a section's name typed twice, the titles in bold are made headings, as
    # the audit places them.
    twice = word(tmp_path / "twice", "**Abstract**\n\nWe read.\n\n**Introduction**\n\nText.\n\n"
                 "**Methods**\n\nWe read.\n\n**Results**\n\nIt was.\n\n**Discussion**\n\n"
                 "RESULTS\n\nIt was too.\n\n**References**\n\nDoe J.\n")  # fmt: skip
    assert from_word.convert(twice).typed_headings == (
        "Abstract", "Introduction", "Methods", "Results", "Discussion", "References")
    document = read_docx_text(paper)
    lines = document.body.split("\n")
    assert [lines[at] for at, _level in typed_heading_levels(document)] == [
        "ABSTRACT", "1. INTRODUCTION", "3. RESULTS"]


@pytest.mark.parametrize("again", [
    [{"t": "Str", "c": "ABSTRACT"}],
    [{"t": "Str", "c": "3."}, {"t": "Space"}, {"t": "Str", "c": "RESULTS"}],
    [{"t": "Emph", "c": [{"t": "Str", "c": "Methods"}]}],
], ids=["capitals", "numbered", "italics"])
def test_a_name_typed_twice_keeps_the_bold_titles(again: list) -> None:
    """A section's name typed twice, in bold and in another shape, keeps the titles from
    being placed, and those in bold alone are made headings, as the audit places them."""
    from generated import TYPED_BLOCKS

    opening = {"t": "Para", "c": [{"t": "Strong", "c": [{"t": "Str", "c": "Introduction"}]}]}
    titles = [TYPED_BLOCKS[kind][0] for kind in ("in a span", "in bold", "underlined around")]
    words = {"t": "Para", "c": [{"t": "Str", "c": "Words."}]}
    blocks = [json.loads(json.dumps(one)) for block in [titles[0], opening, *titles[1:],
              {"t": "Para", "c": again}] for one in (block, words)]  # fmt: skip
    assert from_word.typed_headings(blocks)[1] == ("Abstract", "Introduction", "Methods",
                                                   "Results")  # fmt: skip


@needs_pandoc
def test_titles_in_bold_are_text_where_a_heading_style_is_used(tmp_path: Path) -> None:
    """A document that uses Word's heading styles is read by them alone: a bold line in it is
    a paragraph, as before."""
    converted = from_word.convert(word(tmp_path / "word", "# Introduction\n\nText.\n\n"
                                       "**Methods**\n\nWe read them.\n"))  # fmt: skip
    assert _headings(converted.text) == ["# Introduction"]
    assert converted.typed_headings == ()
    assert "**Methods**" in converted.text
