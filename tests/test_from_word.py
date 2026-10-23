"""`init --from paper.docx`: a paper written in Word, brought into a project.

The documented route was `pandoc paper.docx -t markdown`. On fifteen openly licensed Word
papers it wrote the tables of eight as multiline tables, which `check` refuses at every
stage (`rule-opens-a-block`), and put each title page in the text. These tests build their
own Word documents with pandoc, from Markdown, and hold what `init --from` makes of them.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.from_word import (
    TITLE_PAGE_WORDS,
    _flatten,
    _names,
    _one_line,
    _pictures,
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


@pytest.mark.parametrize("kept", ["paper.yaml", "authors.yaml"])
def test_a_project_file_the_word_paper_fills_is_not_kept_silently(tmp_path: Path, capsys,
                                                                   kept: str) -> None:  # fmt: skip
    """init keeps a file that is there, and would have said the Word title or names were
    written into it."""
    root = tmp_path / "project"
    root.mkdir()
    (root / kept).write_text("mine\n", encoding="utf-8")
    paper = tmp_path / "paper.docx"
    paper.write_bytes(b"PK\x03\x04" + bytes(100))
    assert main(["init", str(root), "--from", str(paper)]) == 2
    err = capsys.readouterr().err
    assert f"{kept} is already there" in err and "nothing was made" in err
    assert sorted(path.name for path in root.iterdir()) == [kept]
    assert (root / kept).read_text(encoding="utf-8") == "mine\n"


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
