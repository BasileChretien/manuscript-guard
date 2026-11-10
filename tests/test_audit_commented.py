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
    """The Abstract's 412, found nowhere the paper reports, is a comment over "412", in a copy
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
