"""`audit --commented`: a copy of the .docx with each finding as a Word comment at its place
(the author's audit, 2026-11-10: "an interactive" report; option C of the plan he chose)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from generated import word_package

from manuscript_guard.cli import main

PAPER = (
    "<w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr><w:r><w:t>Abstract</w:t></w:r></w:p>"
    "<w:p><w:r><w:t xml:space='preserve'>Of the patients, 412 improved.</w:t></w:r></w:p>"
    "<w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr><w:r><w:t>Results</w:t></w:r></w:p>"
    "<w:p><w:r><w:t xml:space='preserve'>Of the patients, 40 improved.</w:t></w:r></w:p>"
)
STYLES = ("<w:styles xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
          "<w:style w:type='paragraph' w:styleId='Heading1'><w:name w:val='heading 1'/>"
          "</w:style></w:styles>")  # fmt: skip


def docx(path: Path, body: str = PAPER, extra: dict[str, str] | None = None) -> Path:
    parts = {**word_package(body), "word/styles.xml": STYLES, **(extra or {})}
    with zipfile.ZipFile(path, "w") as archive:
        for name, part in parts.items():
            archive.writestr(name, part)
    return path


def test_the_audit_writes_a_copy_with_its_findings_as_comments(tmp_path: Path, capsys) -> None:
    """The Abstract's 412, not found where the paper reports, is a comment over "412", in a copy
    Word can open: the comments part, its relationship and its content type added."""
    from manuscript_guard.docxtext import comment_ranges, word_comments

    paper = docx(tmp_path / "paper.docx")
    given = paper.read_bytes()
    target = tmp_path / "commented.docx"
    assert main(["audit", str(paper), "--commented", str(target)]) == 0
    err = capsys.readouterr().err
    assert f"wrote {target}" in err and "as comments at their places" in err
    comments = {one.identifier: one.text for one in word_comments(target)}
    ranges = comment_ranges(target)
    over = [ranges.get(identifier) for identifier, text in comments.items()
            if text.startswith("Abstract against Results: 412")]  # fmt: skip
    assert over == ["412"], (comments, ranges)
    with zipfile.ZipFile(target) as archive:
        assert "comments.xml" in archive.read("word/_rels/document.xml.rels").decode()
        assert "/word/comments.xml" in archive.read("[Content_Types].xml").decode()
    assert paper.read_bytes() == given


def test_a_document_s_own_comments_are_kept(tmp_path: Path) -> None:
    """A document with comments of its own keeps them, and the audit's take ids after theirs."""
    from manuscript_guard.auditing.commented import Note, write
    from manuscript_guard.docxtext import word_comments

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    theirs = (f'<w:comments xmlns:w="{w}"><w:comment w:id="0" w:author="Ada"><w:p><w:r>'
              "<w:t>Their own.</w:t></w:r></w:p></w:comment></w:comments>")  # fmt: skip
    body = ('<w:p><w:commentRangeStart w:id="0"/><w:r><w:t>Of 40 patients.</w:t></w:r>'
            '<w:commentRangeEnd w:id="0"/><w:r><w:commentReference w:id="0"/></w:r></w:p>')
    package = word_package(body)
    package["[Content_Types].xml"] = package["[Content_Types].xml"].replace(
        "</Types>", '<Override PartName="/word/comments.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.wordprocessingml.comments+xml"/></Types>')
    package["word/_rels/document.xml.rels"] = package["word/_rels/document.xml.rels"].replace(
        "</Relationships>", '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/comments" Target="comments.xml"/></Relationships>')
    source = tmp_path / "paper.docx"
    with zipfile.ZipFile(source, "w") as archive:
        for name, part in {**package, "word/comments.xml": theirs}.items():
            archive.writestr(name, part)
    target = tmp_path / "commented.docx"
    written = write(source, target, [Note("40", "Of 40 patients.", "ours")],
                    date="2026-11-10T00:00:00Z")  # fmt: skip
    assert written.placed == 1 and not written.listed
    said = {one.identifier: (one.author, one.text) for one in word_comments(target)}
    assert said["0"] == ("Ada", "Their own.")
    assert ("manuscript-guard audit", "ours") in said.values()
    with zipfile.ZipFile(target) as archive:
        rels = archive.read("word/_rels/document.xml.rels").decode()
    assert rels.count("relationships/comments") == 1


@pytest.mark.parametrize(("target", "paper", "said"), [
    ("there.docx", "paper.docx", "the file is there already"),
    ("commented.md", "paper.docx", "writes a Word document (.docx)"),
    ("commented.docx", "paper.md", "and paper.md is not one"),
    ("paper.docx", "paper.docx", "the file is there already"),
    ("missing/commented.docx", "paper.docx", "its folder does not exist"),
])  # fmt: skip
def test_a_commented_copy_is_refused_where_it_cannot_be_written(
    tmp_path: Path, capsys, target: str, paper: str, said: str
) -> None:
    """Never over a file there already, which may be a copy the author worked on, nor the
    paper itself; only a .docx, of a .docx."""
    docx(tmp_path / "paper.docx")
    (tmp_path / "paper.md").write_text("# Results\n\nOf 40 patients, 12 improved.\n",
                                       encoding="utf-8")  # fmt: skip
    (tmp_path / "there.docx").write_bytes(b"theirs")
    code = main(["audit", str(tmp_path / paper), "--commented", str(tmp_path / target)])
    assert code == 2
    assert said in capsys.readouterr().err
    assert (tmp_path / "there.docx").read_bytes() == b"theirs"


def _written(tmp_path: Path, body: str, notes: list, **package) -> tuple:
    from manuscript_guard.auditing.commented import write
    from manuscript_guard.docxtext import comment_ranges, word_comments

    source = tmp_path / "paper.docx"
    parts = word_package(body)
    parts.update(package)
    with zipfile.ZipFile(source, "w") as archive:
        for name, part in parts.items():
            archive.writestr(name, part)
    target = tmp_path / "commented.docx"
    written = write(source, target, notes, date="2026-11-10T00:00:00Z")
    ranges = comment_ranges(target)
    return written, {one.text: ranges.get(one.identifier) for one in word_comments(target)}


CELL = "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>12</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"


def test_a_number_quoted_bare_is_not_put_inside_a_longer_one(tmp_path: Path) -> None:
    """A table's last cell is quoted as the number alone, "12": it was put on the 12 of
    "2012" earlier in the text (round 1 of #617)."""
    from manuscript_guard.auditing.commented import Note

    body = "<w:p><w:r><w:t>In 2012 we began.</w:t></w:r></w:p>" + CELL
    written, said = _written(tmp_path, body, [Note("12", "12", "the cell")])
    assert written.placed == 1 and said["the cell"] == "12"


def test_a_number_quoted_bare_that_two_paragraphs_hold_is_listed_with_its_place(
    tmp_path: Path,
) -> None:
    """Nothing tells apart "12" in "followed for 12 months" and a cell "12": the finding is
    listed with the place the report gives it rather than put on the first."""
    from manuscript_guard.auditing.commented import Note

    body = "<w:p><w:r><w:t>They were followed for 12 months.</w:t></w:r></w:p>" + CELL
    note = Note("12", "12", "Numbers in the outputs: 12 is in no output given",
                "Results, paragraph 2 (a table)")  # fmt: skip
    written, said = _written(tmp_path, body, [note])
    assert written.placed == 0 and written.listed == (note,)
    listing = next(text for text in said if "no place in the text" in text)
    assert "Results, paragraph 2 (a table): Numbers in the outputs: 12" in listing


@pytest.mark.parametrize(("message", "context", "words"), [
    ("5 in the Abstract is not found in the tables or any section but the Introduction, the "
     "Discussion and a conclusion",
     "Of 5 patients", "5"),
    ("AS is used 8 times in the main text", "the AS group", "AS"),
    ("the P value is written 'p' in italics once", "where p was", "p"),
    # A message that opens with a plain word names no word of the quote.
    ("the two bounds of an interval are joined by a hyphen", "the two bounds", ""),
])  # fmt: skip
def test_a_finding_s_own_words_are_a_number_an_abbreviation_or_what_it_quotes(
    message: str, context: str, words: str
) -> None:
    from manuscript_guard.auditing.commented import words_of

    assert words_of(message, context) == words


@pytest.mark.parametrize("rels", [
    # A part with nothing in it, as one empty element.
    '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.'
    'openxmlformats.org/package/2006/relationships"/>',
])  # fmt: skip
def test_an_empty_relationships_part_is_given_the_comments(tmp_path: Path, rels: str) -> None:
    from manuscript_guard.auditing.commented import Note

    body = "<w:p><w:r><w:t>Of 40 patients.</w:t></w:r></w:p>"
    written, said = _written(tmp_path, body, [Note("40", "Of 40 patients.", "ours")],
                             **{"word/_rels/document.xml.rels": rels})  # fmt: skip
    assert written.placed == 1 and said["ours"] == "40"


def test_a_copy_is_never_written_over_a_file_made_while_the_audit_ran(tmp_path: Path) -> None:
    """That FILE is not there is checked before the audit, which can take minutes: a file
    made since is not written over (round 1 of #617)."""
    from manuscript_guard.auditing.commented import CommentedError, Note, write

    source = tmp_path / "paper.docx"
    with zipfile.ZipFile(source, "w") as archive:
        for name, part in word_package("<w:p><w:r><w:t>Of 40.</w:t></w:r></w:p>").items():
            archive.writestr(name, part)
    target = tmp_path / "commented.docx"
    target.write_bytes(b"theirs")
    with pytest.raises(CommentedError, match="is there already"):
        write(source, target, [Note("40", "Of 40.", "ours")], date="2026-11-10T00:00:00Z")
    assert target.read_bytes() == b"theirs"
    empty = tmp_path / "empty.docx"
    with zipfile.ZipFile(empty, "w") as archive:
        for name, part in word_package("").items():
            archive.writestr(name, part)
    with pytest.raises(CommentedError, match="no paragraph"):
        write(empty, tmp_path / "out.docx", [Note("", "", "listed")], date="2026-11-10T00:00:00Z")


def test_a_finding_on_no_file_is_listed_and_one_on_another_is_not(tmp_path: Path) -> None:
    """A paper the audit could not read is a finding on no file: listed on the document. One
    on another file is that file's (round 1 of #617)."""
    from manuscript_guard.audit import audit
    from manuscript_guard.auditing.commented import notes_of

    paper = docx(tmp_path / "paper.docx")
    (tmp_path / "broken.docx").write_bytes(b"not a zip")
    report = audit([paper, tmp_path / "broken.docx"], None)
    notes = notes_of(report, paper)
    unread = [note for note in notes if "broken.docx" in note.comment]
    assert unread and all(not note.words and not note.around for note in unread)
