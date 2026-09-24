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
    assert "[]{#mg-p-" in tagged
    assert tagged.count("[]{#mg-p-") == 1, "only the prose paragraph"
    assert "}{{table.baseline}}" not in tagged


FENCE = "`" * 3

#: Blocks a marker would rewrite, or would sit in only part of. The reasons, and pandoc's own
#: verdict on each, are in `tests/test_pandoc_agreement.py`; this copy runs without pandoc.
NOT_PARAGRAPHS = {
    "bullet list": "- item one\n- item two",
    "numbered list": "1. first\n2. second",
    "numbered list in parentheses": "(1) first",
    "capital letters with two spaces": "A.  first",
    "capital roman numerals": "II. first",
    "example list": "(@) first",
    "block quote": "> quoted",
    "line block": "| line one\n| line two",
    "pipe table": "| a | b |\n|---|---|\n| 1 | 2 |",
    "pipe table without edges": "a | b\n--|--\n1 | 2",
    "grid table": "+---+---+\n| a | b |\n+===+===+",
    "table caption": "Table: Cap",
    "definition list": "Term\n: definition",
    "definition": ":   definition",
    "setext heading": "Title\n=====",
    "thematic break": "***",
    "footnote definition": "[^1]: A footnote.",
    "figure": "![A figure](fig.png){width=50%}",
    "indented code": "    code line",
    "html block": "<div>\nhello\n</div>",
    "html comment": "<!-- a note -->",
    "paragraph interrupted by a fence": f"text\n{FENCE}\ncode\n{FENCE}",
    "paragraph interrupted by an html block": "text\n<table>\n</table>",
    "paragraph closing a fenced div": "Inner paragraph here.\n:::",
    "continuation followed by a nested list": "  Matched on:\n  - age\n- Drugs were mapped.",
    "continuation followed by the next item": "   cont\n3. three",
    "figure with brackets two deep": "![Caption^[Source: [@k].]](f.png)",
    "figure with a parenthesis in its path": "![A](fig(1).png)",
    "page break": "\\newpage",
    "latex environment after a paragraph's first line": "text\n\\begin{x}\nrow\n\\end{x}",
    "latex environment opened mid-line": "text \\begin{x}\nrow\n\\end{x} more",
    "latex environment written with a space": "text\n\\begin {table}\nrow\n\\end{table}",
    "display math inside a paragraph": "The model is\n$$\ny = a + bx\n$$\nwhere b is the slope.",
    "a block html tag mid-line": "In women. <div>See the note.</div> Weaker in men.",
    "html block inside a list item's continuation": "  para\n    <div>\n    x\n    </div>",
    "a raw tex argument left open": "The signal \\footnote{In the sensitivity analysis.",
    "a raw tex argument closed": "And in the restricted cohort.} in both periods.",
    "a definition inside a list item's continuation": "  para\n    : def",
    "example list without parentheses": "@good. second",
    "a capital and a period alone": "A.",
    "a valid roman numeral": "mix. up",
}

#: Prose that opens like a block and is not one, to pandoc.
PARAGRAPHS = {
    "an initial": "C. difficile was isolated.",
    "a decimal": "1.5 mg was given.",
    "a negative number": "-5 is below zero.",
    "a plus-minus": "+/- two units.",
    "emphasis": "*Emphasis* opens this.",
    "inline html": "<span>x</span> text.",
    "an autolink": "<https://example.org> is a link.",
    "a dash on a later line": "text\n- not a list",
    "a word made of roman letters": "dim. lights were used.",
    "a less-than before a word": "Values <LOQ were imputed as half the limit.",
    "an inline tag mid-line": "The <em>adjusted</em> estimate was lower.",
    "balanced braces": "The set {a, b} and a binding {{results.ror.point}} were used.",
}


RULED = {
    "three rows": (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------"
    ),
    "caption straight under": (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------\nTable: Caption."
    ),
    "colon caption straight under": (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------\n: Caption."
    ),
    "first column two dashes wide": (
        "-- ---------- ----------\n#  Drug       Signal\n-- ---------- ----------\n"
        "1  Warfarin   Bleeding\n\n2  Apixaban   Bleeding\n\n3  Heparin    HIT\n"
        "-- ---------- ----------"
    ),
    "yaml closed by dots": "---\ntitle: x\nabstract: |\n  a\n\n  b\n...",
}


@pytest.mark.parametrize("name", sorted(RULED))
def test_no_marker_inside_a_table_or_yaml_across_blank_lines(name: str) -> None:
    """A multiline table's rows are separated by blank lines, so its middle rows look like
    paragraphs. Marked, the identifier printed into a cell, or became a bookmark on one cell
    that `import` spliced over the whole row."""
    from manuscript_guard.roundtrip import tag

    tagged = tag(f"Before.\n\n{RULED[name]}\n\nAfter.\n", "main.md")
    assert re.findall(r"\[\]\{#mg-p-[^}]+\}(\w+)", tagged) == ["Before", "After"], tagged


def test_a_table_closed_by_its_caption_does_not_hide_what_follows() -> None:
    """A one-row table with its caption straight under it ends at the caption. Read as
    left open, it paired with the next line of dashes - a setext heading - and every
    paragraph in between lost its identifier."""
    from manuscript_guard.roundtrip import tag

    text = (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n"
        "---------- ----------\nTable: One row.\n\nP1.\n\nP2.\n\nMethods\n-------\n\nP3.\n"
    )
    marked = re.findall(r"\[\]\{#mg-p-[^}]+\}(\w+)", tag(text, "main.md"))
    assert marked == ["P1", "P2", "P3"]


def _docx_with_body(path: Path, body: str) -> Path:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.'
        f'openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return path


def _para(name: str, text: str) -> str:
    return (
        f'<w:p><w:bookmarkStart w:id="0" w:name="{name}"/><w:r><w:t>{text}</w:t></w:r>'
        '<w:bookmarkEnd w:id="0"/></w:p>'
    )


def test_a_bookmark_in_a_table_cell_is_not_an_identity(tmp_path: Path) -> None:
    """A cell's bookmark names a cell, and `import` splices over the whole block its
    identifier names: an edit to one cell deleted the rest of the row from the source. Every
    build before identifiers moved off tables put one in each pipe table's first cell, so
    documents already out with co-authors carry them."""
    from manuscript_guard.roundtrip import paragraph_order, paragraph_text

    cell = f"<w:tc>{_para('mg-p-a-1', 'Apixaban')}</w:tc>"
    nested = f"<w:tc><w:tbl><w:tr><w:tc>{_para('mg-p-a-2', 'inner')}</w:tc></w:tr></w:tbl></w:tc>"
    document = _docx_with_body(
        tmp_path / "returned.docx",
        f"<w:tbl><w:tblPr/><w:tr>{cell}{nested}</w:tr></w:tbl>{_para('mg-p-a-3', 'Prose.')}",
    )
    assert paragraph_text(document) == {"mg-p-a-3": "Prose."}
    assert paragraph_order(document) == ["mg-p-a-3"]


def test_paragraphs_joined_by_a_line_pandoc_does_not_call_blank_are_not_marked() -> None:
    """A non-breaking space alone on a line split the text into two blocks, both marked,
    where pandoc reads one paragraph; `import --apply` then wrote the second half twice.
    The halves go unmarked, and nothing after them is renumbered."""
    from manuscript_guard.roundtrip import paragraph_slug, tag

    third = f"mg-p-{paragraph_slug('main.md')}-4"
    for space in (" ", "　", " ", "\f"):
        tagged = tag(f"Para one.\n{space}\nPara two.\n\nPara three.\n", "main.md")
        assert re.findall(r"\[\]\{#(mg-p-[^}]+)\}", tagged) == [third], f"{space!r}: {tagged!r}"
        assert f"[]{{#{third}}}Para three." in tagged


@pytest.mark.parametrize("name", sorted(NOT_PARAGRAPHS))
def test_a_block_that_is_not_a_paragraph_carries_no_marker(name: str) -> None:
    """In front of a list, the marker made it a paragraph: the document printed every list
    as one run-on line with its dashes in it."""
    from manuscript_guard.roundtrip import tag

    text = f"Prose before.\n\n{NOT_PARAGRAPHS[name]}\n\nProse after.\n"
    tagged = tag(text, "main.md")
    assert tagged.count("[]{#mg-p-") == 2, f"{name}: only the prose around it: {tagged!r}"
    assert NOT_PARAGRAPHS[name] in tagged, f"{name} was rewritten"


@pytest.mark.parametrize("name", sorted(PARAGRAPHS))
def test_prose_that_only_looks_like_a_block_keeps_its_marker(name: str) -> None:
    """Leaving a paragraph unmarked is safe and not free: its edits are never compared."""
    from manuscript_guard.roundtrip import tag

    assert tag(PARAGRAPHS[name], "main.md").startswith("[]{#mg-p-"), name


def test_nothing_inside_a_code_block_or_a_comment_is_marked() -> None:
    """A blank line inside either one splits it into blocks that look like paragraphs. The
    marker printed inside the code, or named a paragraph that reaches no document."""
    from manuscript_guard.roundtrip import tag

    text = (
        f"{FENCE}r\nx <- 1\n\ny <- 2\n{FENCE}\n\n"
        "<!--\nA note.\n\nMore of the note.\n-->\n\n"
        "Some prose <!-- opened here\n\nand closed -->\n\n"
        "<!-- one\n\nmore --> text <!-- two, opened where one closed\n\ninside two\n\n-->\n\n"
        "\\begin{figure}\nx\n\nmiddle\n\n\\end{figure}\n\n"
        "Shown below.\n\\begin{table}\nrow\n\nrow\n\\end{table}\n\n"
        "\\begin{itemize}\n\\begin{itemize}\na\n\\end{itemize}\n\nb\n\n\\end{itemize}\n\n"
        "<pre>\ncode\n\nmore\n</pre>\n\n"
        "text\n<pre>\ncode\n\nmore\n</pre>\n\n"
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    Thrombocytopenia\n---------- ----------\n\n"
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------\nTable: Caption.\n\n"
        "-- ---------- ----------\n#  Drug       Signal\n-- ---------- ----------\n"
        "1  Warfarin   Bleeding\n\n2  Apixaban   Bleeding\n\n3  Heparin    HIT\n"
        "-- ---------- ----------\n\n"
        "---\ntitle: x\nabstract: |\n  a\n\n  b\n...\n\n"
        "After.\n"
    )
    tagged = tag(text, "main.md")
    assert tagged.count("[]{#mg-p-") == 1, tagged
    assert re.search(r"\[\]\{#mg-p-[^}]+\}After\.", tagged), "the prose after them keeps its"


def test_tagged_paragraphs_names_what_tag_marks_at_the_right_offsets(project: Path) -> None:
    """`tag` writes the identifiers and `import` splices at the offsets `tagged_paragraphs`
    gives them. Sharing `_blocks` keeps the two lists the same; this pins that down, and
    checks each offset against the file on disk, front matter included, with every kind of
    block in it."""
    from manuscript_guard.build.assemble import strip_front_matter
    from manuscript_guard.contracts import load_project
    from manuscript_guard.roundtrip import tag, tagged_paragraphs

    source = project / "manuscript" / "main.md"
    blocks = "\n\n".join(NOT_PARAGRAPHS.values()) + "\n\n" + "\n\n".join(PARAGRAPHS.values())
    source.write_text(source.read_text(encoding="utf-8") + "\n" + blocks + "\n", "utf-8")

    body, _title = strip_front_matter(source.read_text(encoding="utf-8"))
    written = re.findall(r"\[\]\{#(mg-p-[^}]+)\}", tag(body, "main.md"))
    known = {
        name: entry
        for name, entry in tagged_paragraphs(load_project(project)[0]).items()
        if entry[0] == source
    }
    assert written == sorted(known, key=lambda name: known[name][2])
    raw = source.read_text(encoding="utf-8")
    for _path, text, start in known.values():
        assert raw[start : start + len(text)] == text, "an offset names the wrong text"


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
    tagged = [p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL) if "mg-p-" in p]
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
