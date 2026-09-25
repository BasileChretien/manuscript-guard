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
    assert archive.read("word/document.xml").decode("utf-8").count("<w:tbl>") >= 2
    assert any(name.startswith("word/media/") for name in archive.namelist())

    # The third is the code list, which the example places in its supplement. Asserted here
    # rather than only in the CLI tests: a table that reached neither document would satisfy
    # a count of two in the paper, and this file exists to check what a reader receives.
    supplement = zipfile.ZipFile(project / "build" / "supplementary.docx")
    assert supplement.read("word/document.xml").decode("utf-8").count("<w:tbl>") >= 1


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


BLOCKS = """\
The analysis rests on three steps:

- Reports were deduplicated by case identifier.
- Suspected drugs were mapped to active ingredients.
- Events were coded to preferred terms.

The order of work was fixed in advance:

1. The protocol was registered.
2. The data were extracted.
3. The analysis was run once.

> Disproportionality is a signal, not a measure of risk.

"""


def paragraphs(xml: str) -> list[tuple[str, str]]:
    """Every paragraph as (its markup, the text a reader sees in it)."""
    return [
        (p, "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.DOTALL)))
        for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL)
    ]


def list_format(archive: zipfile.ZipFile, markup: str) -> str | None:
    """`bullet` or `decimal` for a list paragraph, None for anything else."""
    num = re.search(r'<w:numId w:val="(\d+)"', markup)
    if num is None:
        return None
    numbering = archive.read("word/numbering.xml").decode("utf-8")
    abstract = re.search(
        rf'<w:num w:numId="{num.group(1)}"[^>]*>\s*<w:abstractNumId w:val="(\d+)"', numbering
    )
    assert abstract, f"numId {num.group(1)} is not defined in numbering.xml"
    level = re.search(
        rf'<w:abstractNum [^>]*w:abstractNumId="{abstract.group(1)}".*?'
        r'<w:lvl w:ilvl="0".*?<w:numFmt w:val="(\w+)"',
        numbering,
        re.DOTALL,
    )
    return level.group(1) if level else None


@needs_pandoc
def test_lists_and_quotes_reach_the_page_as_lists_and_quotes(project: Path) -> None:
    """The paragraph identifier used to go in front of every block, and in front of a list
    it stopped being a list: pandoc read `[]{#mg-p-...}- item one` as a paragraph, so every
    list in a manuscript came out as one run-on paragraph with its dashes and numbers in it.
    A block quote became a paragraph opening with ">". Nothing reported either."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    text = source.read_text(encoding="utf-8")
    source.write_text(text.replace("# Funding", BLOCKS + "# Funding", 1), encoding="utf-8")

    assert main(["build", str(project), "--offline"]) == 0
    document = project / "build" / "manuscript.docx"
    archive = zipfile.ZipFile(document)
    found = paragraphs(archive.read("word/document.xml").decode("utf-8"))

    items = {
        "Reports were deduplicated by case identifier.": "bullet",
        "Suspected drugs were mapped to active ingredients.": "bullet",
        "Events were coded to preferred terms.": "bullet",
        "The protocol was registered.": "decimal",
        "The data were extracted.": "decimal",
        "The analysis was run once.": "decimal",
    }
    for item, kind in items.items():
        holding = [(markup, seen) for markup, seen in found if item in seen]
        assert len(holding) == 1, f"{item!r} is in {len(holding)} paragraphs"
        markup, seen = holding[0]
        assert seen == item, f"{item!r} shares its paragraph: {seen!r}"
        assert list_format(archive, markup) == kind, f"{item!r} is not a {kind} list item"

    quote = [markup for markup, seen in found if "not a measure of risk" in seen]
    assert len(quote) == 1
    assert '<w:pStyle w:val="BlockText"' in quote[0], "the quotation is not a block quote"

    for _markup, seen in found:
        assert not re.match(r"\s*(?:[-*+>]|\d+[.)])\s", seen), f"a marker printed: {seen!r}"

    # The paragraphs around the blocks are still ordinary paragraphs, and still identified.
    lead = [markup for markup, seen in found if seen == "The analysis rests on three steps:"]
    assert len(lead) == 1 and "mg-p-" in lead[0], "the paragraph before a list lost its id"


@needs_pandoc
def test_every_identifier_in_the_documents_is_one_import_knows(project: Path) -> None:
    """`tag` writes the identifiers and `tagged_paragraphs` is what `import` looks them up
    in. If the two disagree about which blocks are paragraphs, an identifier in the file
    names nothing on disk, or a paragraph on disk is never compared."""
    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_project
    from manuscript_guard.roundtrip import paragraph_order, tagged_paragraphs

    source = project / "manuscript" / "main.md"
    text = source.read_text(encoding="utf-8")
    source.write_text(text.replace("# Funding", BLOCKS + "# Funding", 1), encoding="utf-8")

    assert main(["build", str(project), "--offline"]) == 0
    built = paragraph_order(project / "build" / "manuscript.docx") + paragraph_order(
        project / "build" / "supplementary.docx"
    )
    known = tagged_paragraphs(load_project(project)[0])

    assert len(built) == len(set(built)), "identifiers must be unique"
    assert set(built) == set(known)


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


@needs_pandoc
@pytest.mark.parametrize("annotated", [False, True], ids=["as-sent", "annotated"])
def test_a_built_document_carries_no_path_from_the_machine_that_built_it(
    project: Path, annotated: bool
) -> None:
    """The document goes to co-authors, and it carried the builder's home directory twice.

    Pandoc writes every metadata field it does not recognise into docProps/custom.xml, and
    `--bibliography` is metadata, so an offline build shipped the absolute path of
    references.bib as a property called `bibliography`. The figure did the same thing in
    `word/document.xml`: it was linked by absolute path, and pandoc records the link as the
    picture's description. Both name the user's account and folder layout, and neither is
    visible in Word unless somebody goes looking.
    """
    from manuscript_guard.cli import main

    command = ["build", str(project), "--offline"] + (["--annotated"] if annotated else [])
    assert main(command) == 0
    names = ["manuscript.annotated.docx"] if annotated else [
        "manuscript.docx",
        "supplementary.docx",
    ]
    local = {str(project), project.as_posix(), str(Path.home()), Path.home().as_posix()}
    for name in names:
        with zipfile.ZipFile(project / "build" / name) as archive:
            for member in archive.namelist():
                if not member.endswith((".xml", ".rels")):
                    continue
                text = archive.read(member).decode("utf-8", errors="replace")
                leaked = sorted(path for path in local if path in text)
                assert not leaked, f"{name}:{member} carries {leaked}"
