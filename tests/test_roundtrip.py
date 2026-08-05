"""Bringing a co-author's Word edits back without losing the bindings.

The document is a build artefact and never edited - which is right, and on its own unusable,
because co-authors edit in Word. What the round trip is allowed to carry is the whole
question, and these tests are about what it refuses.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.roundtrip import (
    comments_in,
    realign,
    segments,
    stamp_into,
    stamp_of,
)

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")


def edit_docx(source: Path, target: Path, replacements: dict[str, str]) -> Path:
    """A co-author, simulated: text changed in the .docx itself."""
    shutil.copy(source, target)
    scratch = target.with_suffix(".t.docx")
    with zipfile.ZipFile(target) as zin, zipfile.ZipFile(scratch, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = data.decode("utf-8")
                for was, now in replacements.items():
                    xml = xml.replace(was, now)
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    scratch.replace(target)
    return target


@needs_pandoc
def test_a_built_document_carries_its_source_digest(project: Path) -> None:
    """A sidecar cannot survive being emailed, and the returned document is exactly the case
    where the question matters."""
    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.review import document_digest

    assert main(["build", str(project), "--offline"]) == 0
    projekt, _ = load_project(project)
    assert stamp_of(project / "build" / "manuscript.docx") == document_digest(projekt)


def test_a_stamp_survives_a_rewrite(tmp_path: Path, project: Path) -> None:
    from manuscript_guard.cli import main

    if not PANDOC:
        pytest.skip("pandoc is not installed")
    assert main(["build", str(project), "--offline"]) == 0
    document = project / "build" / "manuscript.docx"
    stamp_into(document, "b" * 64)
    assert stamp_of(document) == "b" * 64
    with zipfile.ZipFile(document) as archive:
        assert "word/document.xml" in archive.namelist(), "still a valid docx"


@needs_pandoc
def test_an_edited_number_is_refused_and_named(project: Path, tmp_path: Path) -> None:
    """The failure this command exists to prevent. A co-author who 'corrects' a number in
    Word would, on a naive import, replace the binding with their literal - a checked
    manuscript quietly becoming an unchecked one that still passes."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = edit_docx(
        project / "build" / "manuscript.docx", tmp_path / "back.docx", {}
    )
    scratch = returned.with_suffix(".t.docx")
    with zipfile.ZipFile(returned) as zin, zipfile.ZipFile(scratch, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = re.sub(
                    r"(<w:t[^>]*>[^<]*?)3\.84", r"\g<1>4.02", data.decode("utf-8"), count=1
                )
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    scratch.replace(returned)

    assert main(["import", str(returned), str(project)]) == 1
    assert "{{results.ror.point}}" in (project / "manuscript" / "main.md").read_text(
        encoding="utf-8"
    ), "the binding must survive an import that saw the number edited"


@needs_pandoc
def test_a_prose_edit_merges(project: Path, tmp_path: Path) -> None:
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = edit_docx(
        project / "build" / "manuscript.docx",
        tmp_path / "back.docx",
        {"This work received no funding.": "This work received no external funding."},
    )
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    assert "no external funding" in (project / "manuscript" / "main.md").read_text(
        encoding="utf-8"
    )


@needs_pandoc
def test_a_document_built_from_older_source_is_refused(project: Path, tmp_path: Path) -> None:
    """Merging edits made against text that has since changed is how a correction lands on
    the wrong sentence."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = shutil.copy(project / "build" / "manuscript.docx", tmp_path / "old.docx")

    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\nA later paragraph.\n", encoding="utf-8")

    assert main(["import", str(returned), str(project)]) == 1


def test_an_unstamped_document_is_refused(project: Path, tmp_path: Path) -> None:
    """Only a document this tool built can be imported: nothing else records which text the
    edits were made against."""
    from manuscript_guard.cli import main

    plain = tmp_path / "stranger.docx"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    assert main(["import", str(plain), str(project)]) == 1


def test_a_document_with_no_comments_reports_none(project: Path) -> None:
    from manuscript_guard.cli import main

    if not PANDOC:
        pytest.skip("pandoc is not installed")
    assert main(["build", str(project), "--offline"]) == 0
    assert comments_in(project / "build" / "manuscript.docx") == []


def test_moves_reports_only_what_actually_moved() -> None:
    """One paragraph moved shifts every paragraph after it. Reporting all of them is true
    and useless to a reader trying to see what their co-author did."""
    from manuscript_guard.roundtrip import moves

    before = ["a", "b", "c", "d", "e"]
    after = ["d", "a", "b", "c", "e"]
    moved = moves(before, after)
    assert [name for name, _w, _n in moved] == ["d"]


def test_moves_is_silent_when_the_order_is_unchanged() -> None:
    from manuscript_guard.roundtrip import moves

    assert moves(["a", "b", "c"], ["a", "b", "c"]) == []


def test_every_ordinary_paragraph_is_tagged_and_headings_are_not() -> None:
    """`[]{#id}# Methods` is not a heading, and a placeholder alone becomes a table."""
    from manuscript_guard.roundtrip import tag

    tagged = tag("# Methods\n\nSome prose here.\n\n{{table.baseline}}\n", "main")
    assert tagged.startswith("# Methods")
    assert "[]{#mg-p-main-" in tagged
    assert tagged.count("[]{#mg-p-main-") == 1, "only the prose paragraph"
    assert "]{#mg-p-main-4}{{table.baseline}}" not in tagged


@needs_pandoc
def test_a_moved_paragraph_is_reordered_in_the_source(project: Path, tmp_path: Path) -> None:
    """A move needs no content from Word - the text is already on disk - so it is safe for
    exactly the paragraphs the content merge has to refuse."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")

    document = project / "build" / "manuscript.docx"
    xml = zipfile.ZipFile(document).read("word/document.xml").decode("utf-8")
    tagged = [p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL) if "mg-p-main-" in p]
    assert len(tagged) > 5, "the example must have several tagged paragraphs"
    moved_xml = xml.replace(tagged[-3], "", 1).replace(tagged[3], tagged[-3] + tagged[3], 1)

    returned = tmp_path / "moved.docx"
    with zipfile.ZipFile(document) as zin, zipfile.ZipFile(returned, "w") as zout:
        for item in zin.infolist():
            data = (
                moved_xml.encode("utf-8")
                if item.filename == "word/document.xml"
                else zin.read(item.filename)
            )
            zout.writestr(item, data)

    assert main(["import", str(returned), str(project), "--apply"]) == 0
    after = source.read_text(encoding="utf-8")
    was = [p.strip() for p in before.split("\n\n") if p.strip()]
    now = [p.strip() for p in after.split("\n\n") if p.strip()]
    assert sorted(was) == sorted(now), "nothing gained or lost"
    assert was != now, "the order must have changed"
    assert before.count("{{") == after.count("{{"), "every binding survives a move"


# ------------------------------------------- alignment inside a paragraph with bindings


def test_a_rewording_keeps_every_binding() -> None:
    """The move the paragraph-level merge could not make.

    Splicing returned text into a paragraph carrying a binding would replace it with the
    literal it rendered to. Aligning on the rendered forms rebuilds the paragraph from the
    source's tokens and the co-author's words instead.
    """
    source = "The ratio was {{results.ror.point}} overall [@smith2020]."
    rendered = "The ratio was 3.84 overall (Smith 2020)."
    out = realign(source, rendered, "The ratio was notably 3.84 overall (Smith 2020).")
    assert out == "The ratio was notably {{results.ror.point}} overall [@smith2020]."


def test_an_edited_number_refuses_the_whole_paragraph() -> None:
    source = "The ratio was {{results.ror.point}} overall."
    assert realign(source, "The ratio was 3.84 overall.", "The ratio was 4.02 overall.") is None


def test_a_removed_citation_refuses_the_paragraph() -> None:
    """A citation's rendering depends on a CSL style this code never sees. It is located by
    the gap between the prose segments, so it is protected without being understood."""
    source = "The ratio was high [@smith2020]."
    assert realign(source, "The ratio was high (Smith 2020).", "The ratio was high.") is None


def test_transposed_bounds_are_refused() -> None:
    """Sequential search is what catches this: the bounds come back out of order."""
    source = "({{results.ror.ci_low}} to {{results.ror.ci_high}})"
    assert realign(source, "(2.10 to 7.02)", "(7.02 to 2.10)") is None


def test_two_bindings_that_render_the_same_are_paired_in_order() -> None:
    """The collision case again: searching sequentially pairs them up rather than matching
    both to the first occurrence."""
    source = "{{results.a}} and {{results.b}}"
    out = realign(source, "1 and 1", "1 and, notably, 1")
    assert out == "{{results.a}} and, notably, {{results.b}}"


def test_unchanged_prose_keeps_its_own_markdown() -> None:
    """Word text loses inline formatting, so only an edited segment is taken from it."""
    source = "The **striking** ratio was {{results.ror.point}} here."
    out = realign(source, "The striking ratio was 3.84 here.", "The striking ratio was 3.84 there.")
    assert out is not None
    assert "**striking**" in out, "the untouched segment keeps its emphasis"
    assert "there" in out


def test_segments_splits_prose_from_what_the_author_does_not_own() -> None:
    prose, protected = segments("a {{results.x}} b [@key] c")
    assert protected == ["{{results.x}}", "[@key]"]
    assert len(prose) == len(protected) + 1
