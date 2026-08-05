"""What is actually in the file a person opens.

Two defects shipped because the tests asserted an intermediate. The highlight in the
annotated copy never reached the page — the test checked that the character styles were
defined in `styles.xml`, which stayed true while OOXML silently discarded them, because a
run may carry one `w:rStyle` and pandoc's Link writer had already used it. And the annotated
copy contained no tables at all, because only *value* bindings were substituted and
`{{table.baseline}}` printed literally.

Neither failed anything. Both were found by opening the document.

So this file asserts on the artefact: unzip the `.docx`, look at what a reader would see.
It is slower than checking the code that was supposed to produce it, and it is the only kind
of test that could have caught either.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

import pytest

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")


def body(document: Path) -> str:
    return zipfile.ZipFile(document).read("word/document.xml").decode("utf-8")


def visible(document: Path) -> str:
    """Only the text a reader sees, with the markup taken out."""
    return " ".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", body(document), re.DOTALL))


@needs_pandoc
def test_the_built_document_says_what_the_manuscript_says(project: Path) -> None:
    """Every binding resolved, and no placeholder left showing."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    text = visible(project / "build" / "manuscript.docx")

    assert "{{" not in text and "}}" not in text, "a placeholder reached the page"
    assert "[@" not in text, "an unrendered citation reached the page"
    assert "3.84" in text, "the headline estimate is not in the document"
    assert "Write here" not in text, "scaffolding reached the page"


@needs_pandoc
def test_the_built_document_contains_its_tables_and_figure(project: Path) -> None:
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    archive = zipfile.ZipFile(project / "build" / "manuscript.docx")
    assert archive.read("word/document.xml").decode("utf-8").count("<w:tbl>") >= 3
    assert any(name.startswith("word/media/") for name in archive.namelist())


@needs_pandoc
def test_the_annotated_copy_shows_its_colours(project: Path) -> None:
    """The defect this file exists for. Styles were defined and never applied."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline", "--annotated"]) == 0
    xml = body(project / "build" / "manuscript.annotated.docx")

    highlights = re.findall(r'<w:highlight w:val="(\w+)"/>', xml)
    assert len(highlights) > 20, f"only {len(highlights)} numbers are marked"
    assert {"green", "yellow"} <= set(highlights), f"tiers missing: {set(highlights)}"
    assert xml.count("w:tooltip") == len(highlights), "every mark carries its provenance"


@needs_pandoc
def test_the_annotated_copy_is_the_whole_paper(project: Path) -> None:
    """It was missing every table and the figure, which is where a stale number hides."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline", "--annotated"]) == 0
    archive = zipfile.ZipFile(project / "build" / "manuscript.annotated.docx")
    xml = archive.read("word/document.xml").decode("utf-8")

    assert "{{table." not in xml and "{{figure." not in xml
    assert xml.count("<w:tbl>") >= 4, "the tables and the legend"
    assert any(name.startswith("word/media/") for name in archive.namelist())


@needs_pandoc
def test_a_built_document_can_be_brought_back(project: Path) -> None:
    """The round trip depends on two things being *in the file*: the source digest, and an
    identifier on every paragraph. Both are invisible, so nothing else would notice."""
    from manuscript_guard.cli import main
    from manuscript_guard.roundtrip import paragraph_order, stamp_of

    assert main(["build", str(project), "--offline"]) == 0
    document = project / "build" / "manuscript.docx"

    assert stamp_of(document), "no source digest travels with the document"
    order = paragraph_order(document)
    assert len(order) > 5, f"only {len(order)} paragraphs are identifiable"
    assert len(set(order)) == len(order), "identifiers must be unique"


@needs_pandoc
def test_an_unchecked_build_says_so_in_its_name(project: Path) -> None:
    """An unchecked build must not be able to pass for a checked one on disk."""
    from manuscript_guard.cli import main

    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\n99999 loose.\n", encoding="utf-8")
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 0

    built = {p.name for p in (project / "build").glob("*.docx")}
    assert "manuscript.UNCHECKED.docx" in built
    assert "manuscript.docx" not in built
