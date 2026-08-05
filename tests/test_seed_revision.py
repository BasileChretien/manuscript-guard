"""Seeding a revision round from the reviewer's own file.

A journal usually sends a PDF or an email and the points get typed in, which is where a
point quietly becomes the easier point next to it. When the reviewer commented in a document
this tool built, their words *and* the place they were about are already in the file.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

import pytest
import yaml

from manuscript_guard.roundtrip import comments_in

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")

COMMENTS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "{bodies}</w:comments>"
)
ONE = (
    '<w:comment w:id="{id}" w:author="{author}" w:date="2026-08-04T10:00:00Z">'
    "<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:comment>"
)
TYPE = (
    '<Override PartName="/word/comments.xml" ContentType="application/'
    'vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
)


def commented(source: Path, target: Path, notes: list[tuple[str, str]]) -> Path:
    """A returned document with comments anchored to its first identified paragraphs."""
    xml = zipfile.ZipFile(source).read("word/document.xml").decode("utf-8")
    paras = [p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL) if "mg-p-main-" in p]
    assert len(paras) >= len(notes), "the example needs enough identified paragraphs"

    bodies = []
    for index, (author, text) in enumerate(notes):
        para = paras[index]
        marked = para.replace("<w:r>", f'<w:commentRangeStart w:id="{index}"/><w:r>', 1)
        marked = marked.replace("</w:p>", f'<w:commentRangeEnd w:id="{index}"/></w:p>', 1)
        xml = xml.replace(para, marked, 1)
        bodies.append(ONE.format(id=index, author=author, text=text))

    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w") as zout:
        for item in zin.infolist():
            if item.filename == "word/comments.xml":
                continue
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = xml.encode("utf-8")
            elif item.filename == "[Content_Types].xml":
                data = data.decode("utf-8").replace("</Types>", TYPE + "</Types>").encode("utf-8")
            zout.writestr(item, data)
        zout.writestr("word/comments.xml", COMMENTS.format(bodies="".join(bodies)))
    return target


def built(project: Path) -> Path:
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    return project / "build" / "manuscript.docx"


@needs_pandoc
def test_a_comment_knows_which_paragraph_it_is_about(project: Path, tmp_path: Path) -> None:
    """The anchor lives in document.xml while the text lives in comments.xml, and a point is
    about a *place* in the paper. Losing that on the way in is work the author redoes."""
    returned = commented(built(project), tmp_path / "back.docx", [("Reviewer 2", "Unclear.")])
    found = comments_in(returned)

    assert len(found) == 1
    assert found[0].author == "Reviewer 2"
    assert found[0].text == "Unclear."
    assert found[0].where.startswith("mg-p-main-")


@needs_pandoc
def test_a_round_is_seeded_from_the_comments(project: Path, tmp_path: Path) -> None:
    from manuscript_guard.cli import main

    returned = commented(
        built(project),
        tmp_path / "back.docx",
        [
            ("Reviewer 2", "The case definition is not stated."),
            ("Reviewer 2", "Report the absolute counts."),
            ("Editor", "Please shorten the Discussion."),
        ],
    )
    assert main(["respond", str(project), "--open", "--from", str(returned)]) == 0

    document = yaml.safe_load((project / "revision" / "round-1.yaml").read_text(encoding="utf-8"))
    reviewers = {r["id"]: r for r in document["reviewers"]}
    assert set(reviewers) == {"editor", "reviewer-2"}
    assert [p["id"] for p in reviewers["reviewer-2"]["points"]] == ["2.1", "2.2"]
    assert reviewers["reviewer-2"]["points"][0]["comment"] == "The case definition is not stated."
    assert all(p["where"].startswith("mg-p-main-") for p in reviewers["reviewer-2"]["points"])
    assert all(p["response"] == "" for r in document["reviewers"] for p in r["points"])


@needs_pandoc
def test_a_seeded_round_records_the_paragraphs_as_they_stood(project: Path, tmp_path: Path) -> None:
    """Without a per-paragraph baseline, an anchored point can only be checked against the
    whole file it sits in - and a paper's Methods is one file."""
    from manuscript_guard.cli import main

    returned = commented(built(project), tmp_path / "back.docx", [("Reviewer 2", "Unclear.")])
    assert main(["respond", str(project), "--open", "--from", str(returned)]) == 0

    document = yaml.safe_load((project / "revision" / "round-1.yaml").read_text(encoding="utf-8"))
    baseline = document["submitted_paragraphs"]
    assert baseline, "no paragraph baseline was recorded"
    anchored = document["reviewers"][0]["points"][0]["where"]
    assert anchored in baseline


@needs_pandoc
def test_a_document_with_no_comments_still_opens_a_round(project: Path, tmp_path: Path) -> None:
    """A journal that sent a PDF is the common case; the round still has to start."""
    from manuscript_guard.cli import main

    plain = shutil.copy(built(project), tmp_path / "plain.docx")
    assert main(["respond", str(project), "--open", "--from", str(plain)]) == 0

    document = yaml.safe_load((project / "revision" / "round-1.yaml").read_text(encoding="utf-8"))
    assert document["reviewers"][0]["points"][0]["comment"].startswith("No comments found")


@needs_pandoc
def test_the_seeded_round_validates(project: Path, tmp_path: Path) -> None:
    """Whatever the seeding produces has to satisfy the contract, or G13 refuses it."""
    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates import check_revision

    returned = commented(
        built(project), tmp_path / "back.docx", [("Reviewer 2", "The definition is unclear.")]
    )
    assert main(["respond", str(project), "--open", "--from", str(returned)]) == 0

    projekt, _ = load_project(project)
    report = check_revision(projekt, submission=True)
    codes = {f.code for f in report.findings}
    assert "schema-violation" not in codes, report.render(project)
    # Unanswered, because nobody has answered it yet - which is the correct state.
    assert codes == {"point-unanswered"}, codes
