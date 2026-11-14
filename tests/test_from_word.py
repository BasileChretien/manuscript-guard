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
