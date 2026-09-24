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
def test_an_edited_number_is_refused_and_named(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure this command exists to prevent. A co-author who 'corrects' a number in
    Word would, on a naive import, replace the binding with their literal - a checked
    manuscript quietly becoming an unchecked one that still passes.

    And named: the design and the module docstring both promise "'3.84' comes from
    results.ror.point", and for a long time this test checked only the exit code while the
    command printed a generic sentence that named neither.
    """
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

    capsys.readouterr()
    assert main(["import", str(returned), str(project)]) == 1
    assert "{{results.ror.point}}" in (project / "manuscript" / "main.md").read_text(
        encoding="utf-8"
    ), "the binding must survive an import that saw the number edited"
    out = capsys.readouterr().out
    assert "'3.84' comes from results.ror.point" in out, out


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
    "yaml whose first key is table": "---\ntable: x\nabstract: |\n  a\n\n  b\n...",
    "a row reading dots": (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n"
        "            ...\n\nApixaban   Bleeding\n\nHeparin    HIT\n---------- ----------"
    ),
    "caption with no space after the colon": (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------\n:Caption."
    ),
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


def test_a_comment_in_a_table_cell_is_not_anchored_to_the_cell(tmp_path: Path) -> None:
    """A reviewer's point anchored to a cell's bookmark would name a block the cell is
    never the whole of; it stays unanchored, like any other comment on a table."""
    from manuscript_guard.docxtext import comment_anchors

    def commented(name: str, text: str, ident: str) -> str:
        return _para(name, text).replace(
            "<w:r>", f'<w:commentRangeStart w:id="{ident}"/><w:r>', 1
        )

    cell = f"<w:tc>{commented('mg-p-a-1', 'Apixaban', '7')}</w:tc>"
    document = _docx_with_body(
        tmp_path / "returned.docx",
        f"<w:tbl><w:tr>{cell}</w:tr></w:tbl>{commented('mg-p-a-3', 'Prose.', '8')}",
    )
    assert comment_anchors(document) == {"8": "mg-p-a-3"}


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
    # Within the Discussion: its last paragraph to its first. Found by their text, not by
    # position: which blocks carry an identifier is a rule that changes, and a position
    # then names a different paragraph.
    last = next(p for p in tagged if "Several limitations" in p)
    first = next(p for p in tagged if "exceeds the class-level" in p)
    moved_xml = xml.replace(last, "", 1).replace(first, last + first, 1)

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
    # Section by section, not `sorted(...)`: a sorted comparison passed while a move shifted
    # a paragraph out of every section between its old place and its new one.
    expected = by_heading(before)
    discussion = expected["# Discussion"]
    moved = next(p for p in discussion if p.startswith("Several limitations"))
    expected["# Discussion"] = [moved] + [p for p in discussion if p is not moved]
    assert by_heading(after) == expected
    assert before.count("{{") == after.count("{{"), "every binding survives a move"


def by_heading(text: str) -> dict[str, list[str]]:
    """Each heading's paragraphs, in order, with their line wrapping ignored."""
    out: dict[str, list[str]] = {}
    current = ""
    for block in blocks(text):
        if block.startswith("#"):
            current = block
            out.setdefault(current, [])
        else:
            out.setdefault(current, []).append(block)
    return out


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


def test_a_number_that_grew_a_digit_is_refused() -> None:
    """Substring search found '3.84' inside '13.84' and merged `1{{results.ror.point}}`.

    And a sign or a comparison glued in front changes the value too - including the en and
    em dashes Word's AutoCorrect makes of a hyphen, which merged as `\u2013{{results.ror.point}}`
    and turned a ratio negative in the next build."""
    source = "The ratio was {{results.ror.point}} overall."
    rendered = "The ratio was 3.84 overall."
    for edited in (
        "13.84", "3.845", "-3.84", "3.84.1",
        "\u20133.84", "\u20143.84", "\u22123.84", "<3.84", "\u22643.84", "~3.84", "\u22483.84",
    ):
        returned = f"The ratio was {edited} overall."
        assert realign(source, rendered, returned) is None, edited


@pytest.mark.parametrize(
    "source",
    [
        "See the [agency report](https://example.org/r) for details.",
        "See the agency report.^[Withdrawn in 2019.] It has details.",
    ],
    ids=["link", "footnote"],
)
def test_a_paragraph_whose_markup_word_cannot_carry_is_refused(source: str) -> None:
    """Word's plain text has the link's words but not its address, and a footnote's
    reference mark but not its text. Merging it over the source deleted both."""
    from manuscript_guard.merge import why
    from manuscript_guard.roundtrip import align

    rendered = "See the agency report for details."
    aligned = align(source, rendered, "See the agency report for more details.")
    assert aligned.rebuilt is None
    assert "a footnote, a link" in why(aligned)[0]


def test_a_value_is_found_in_its_own_place_not_in_the_prose_before_it() -> None:
    """'Table 1 shows 1 events' - the first '1' is prose. Searching for the rendered value
    from the start of the paragraph moved the binding onto the table number and left the
    value behind as a literal."""
    source = "Table 1 shows {{results.x}} events."
    out = realign(source, "Table 1 shows 1 events.", "Table 1 now shows 1 events.")
    assert out == "Table 1 now shows {{results.x}} events."


# ------------------------------------------------ what an import must not do to the source


def built(project: Path) -> Path:
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    return project / "build" / "manuscript.docx"


def rewrite(document: Path, target: Path, change) -> Path:
    """A co-author, simulated: `word/document.xml` passed through `change`, all else kept."""
    with zipfile.ZipFile(document) as zin, zipfile.ZipFile(
        target, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = change(data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)
    return target


def tagged_xml(xml: str) -> list[str]:
    """The `<w:p>` elements that carry a paragraph identifier, in document order."""
    return [p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL) if "mg-p-" in p]


@needs_pandoc
def test_an_edit_to_a_paragraph_without_an_identifier_is_not_called_a_match(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A quotation or a list carries no identifier, and a section is bounded by whatever
    does not. A co-author reworded a quotation and moved the paragraph above it to below it:
    the moved paragraph read as in order once the quotation's text no longer matched, the
    quotation was never compared, and import said "the document matches the manuscript on
    disk" and exited 0 with both edits lost."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    block = (
        "The analysis rests on three steps.\n\n"
        "> Disproportionality is a signal, not a measure of risk.\n\n"
        "A closing paragraph after the quote.\n\n"
    )
    source.write_text(
        source.read_text(encoding="utf-8").replace("# Funding", block + "# Funding", 1),
        encoding="utf-8",
    )
    document = built(project)
    before = source.read_text(encoding="utf-8")

    def edit(xml: str) -> str:
        tagged = tagged_xml(xml)
        moved = next(p for p in tagged if "three steps" in p)
        closing = next(p for p in tagged if "closing paragraph" in p)
        xml = xml.replace(moved, "", 1).replace(closing, moved + closing, 1)
        return xml.replace("not a measure of risk", "never a measure of risk", 1)

    returned = rewrite(document, tmp_path / "quote.docx", edit)
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    out = capsys.readouterr().out
    assert "matches the manuscript" not in out, out
    assert "never a measure of risk" in out, "the changed quotation is named"
    assert source.read_text(encoding="utf-8") == before, "nothing it cannot place is applied"


def blocks(text: str) -> list[str]:
    """Paragraphs, with their line wrapping ignored: a reworded segment comes back unwrapped."""
    return [" ".join(p.split()) for p in text.split("\n\n") if p.strip()]


def closed(text: str) -> bool:
    """Every `{{` in the text opens a binding that is also closed."""
    return text.count("{{") == len(re.findall(r"\{\{[a-z]+\.[a-z0-9_.]+\}\}", text))


@needs_pandoc
def test_a_move_and_a_rewording_in_one_import_both_land(project: Path, tmp_path: Path) -> None:
    """The reorder rewrote the file, then the rewordings were spliced at offsets taken before
    it. What came out was `{{lit.agency.withdrawnWhether the signal extends...`: a binding
    cut in half, a sentence gone, the co-author's edit lost - and `check` passed it."""
    from manuscript_guard.cli import main

    document = built(project)
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")
    rewordings = {
        "We analysed a synthetic": "We examined a synthetic",
        "the single event term": "the only event term",
        "The reporting odds ratio was computed": "The reporting odds ratio was then computed",
    }

    def edit(xml: str) -> str:
        tagged = tagged_xml(xml)
        moved = tagged[5]
        assert "was computed from a 2 x 2 table" in moved and "We analysed" in tagged[3]
        # Within the Methods: its third paragraph to its first. Reworded: the paragraph the
        # move lands on, one inside the span it shifts, and the moved paragraph itself - one
        # of them carrying bindings.
        xml = xml.replace(moved, "", 1).replace(tagged[3], moved + tagged[3], 1)
        for was, now in rewordings.items():
            xml = xml.replace(was, now, 1)
        return xml

    returned = rewrite(document, tmp_path / "moved.docx", edit)
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    after = source.read_text(encoding="utf-8")

    reworded = before
    for was, now in rewordings.items():
        reworded = reworded.replace(was, now)
    expected = by_heading(reworded)
    methods = expected["# Methods"]
    moved = next(p for p in methods if p.startswith("The reporting odds ratio was then"))
    expected["# Methods"] = [moved] + [p for p in methods if p is not moved]
    assert by_heading(after) == expected, "every paragraph, edited, once, in its section"
    assert sorted(re.findall(r"\{\{[^}]*\}\}", after)) == sorted(
        re.findall(r"\{\{[^}]*\}\}", before)
    ), "every binding survives, whole"
    assert closed(after)


@needs_pandoc
def test_a_move_into_another_section_is_reported_not_applied(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Paragraph slots were filled per file in the order Word returned them, and headings are
    not slots. A Discussion paragraph moved to the top of the Introduction shifted every
    section in between by one: each lost its last paragraph to the next, "Whether the signal
    extends..." landed under Methods, and the command said "reordered 1 paragraph(s)". A
    section's paragraph count is not the import's to change, so the move is refused - and the
    rewording elsewhere in the same document still lands."""
    from manuscript_guard.cli import main

    document = built(project)
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")

    def edit(xml: str) -> str:
        tagged = tagged_xml(xml)
        # By its text: which blocks carry an identifier is a rule that changes, and a
        # position then names a different paragraph.
        moved = next(p for p in tagged if "Several limitations" in p)
        xml = xml.replace(moved, "", 1).replace(tagged[1], moved + tagged[1], 1)
        return xml.replace("has not been examined.", "has not yet been examined.", 1)

    returned = rewrite(document, tmp_path / "across.docx", edit)
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    after = source.read_text(encoding="utf-8")
    expected = before.replace("has not been examined.", "has not yet been examined.")
    assert by_heading(after) == by_heading(expected), "every paragraph stays in its section"
    assert "different section" in capsys.readouterr().out


@needs_pandoc
def test_an_untouched_document_with_a_one_paragraph_file_is_unchanged(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A paragraph was "moved into a different file" when neither neighbour came from its own
    file - always true of a file holding one paragraph. An untouched document exited 1."""
    from manuscript_guard.cli import main

    (project / "manuscript" / "notes.md").write_text(
        "# Notes\n\nThe notes hold one paragraph only.\n", encoding="utf-8"
    )
    document = built(project)
    capsys.readouterr()
    assert main(["import", str(document), str(project)]) == 0
    assert "nothing came back" in capsys.readouterr().out


def test_a_paragraph_moved_into_another_file_is_not_applied(tmp_path: Path) -> None:
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    main_md, notes = tmp_path / "main.md", tmp_path / "notes.md"
    main_md.write_text("Main one.\n\nMain two.\n", encoding="utf-8")
    notes.write_text("Notes one.\n\nNotes two.\n", encoding="utf-8")
    known = {
        "m1": (main_md, "Main one.", 0),
        "m2": (main_md, "Main two.", 11),
        "n1": (notes, "Notes one.", 0),
        "n2": (notes, "Notes two.", 12),
    }
    sent = [Block((n,), known[n][1]) for n in known]
    returned = [sent[0], sent[2], sent[1], sent[3]]  # "Notes one." pasted into main's run

    plan = plan_import(known, sent, returned)
    assert plan.misplaced and set(plan.misplaced) <= {"n1", "m2"}
    apply_plan(known, plan)
    assert main_md.read_text(encoding="utf-8") == "Main one.\n\nMain two.\n"
    assert notes.read_text(encoding="utf-8") == "Notes one.\n\nNotes two.\n"


def test_a_deletion_beside_a_move_keeps_every_paragraph_in_its_section(tmp_path: Path) -> None:
    """A paragraph left in place travelled with the paragraph before it in the file - which,
    for the first paragraph of a section, is the last of the section before. Moved, that
    paragraph took it across the heading."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path = tmp_path / "main.md"
    text = "# A\n\nA one.\n\nA two.\n\n# B\n\nB one.\n\nB two.\n"
    path.write_text(text, encoding="utf-8")
    known = {
        name: (path, words, text.index(words))
        for name, words in (("a1", "A one."), ("a2", "A two."), ("b1", "B one."), ("b2", "B two."))
    }
    heading_a, heading_b = Block((), "A"), Block((), "B")
    sent = [heading_a, Block(("a1",), "A one."), Block(("a2",), "A two."), heading_b,
            Block(("b1",), "B one."), Block(("b2",), "B two.")]
    # A's two paragraphs swapped; B's first deleted.
    returned = [heading_a, sent[2], sent[1], heading_b, sent[5]]

    plan = plan_import(known, sent, returned)
    assert plan.gone == ("b1",)
    apply_plan(known, plan)
    expected = "# A\n\nA two.\n\nA one.\n\n# B\n\nB one.\n\nB two.\n"
    assert path.read_text(encoding="utf-8") == expected


def _two_sections(tmp_path: Path):
    """One file: '# Intro' with two paragraphs, then '# Methods' with two."""
    from manuscript_guard.docxtext import Block

    path = tmp_path / "main.md"
    text = "# Intro\n\nIntro one.\n\nIntro two.\n\n# Methods\n\nMethods one.\n\nMethods two.\n"
    path.write_text(text, encoding="utf-8")
    words = {"i1": "Intro one.", "i2": "Intro two.", "m1": "Methods one.", "m2": "Methods two."}
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    blocks_ = {name: Block((name,), w) for name, w in words.items()}
    return path, text, known, blocks_, Block((), "Intro"), Block((), "Methods")


@pytest.mark.parametrize("landing", ["below-the-heading", "after-its-first-paragraph"])
def test_a_move_past_a_heading_is_reported_even_when_the_order_is_unchanged(
    tmp_path: Path, landing: str
) -> None:
    """Dragged from the end of the Introduction to just below the Methods heading, a
    paragraph keeps its place among the tagged paragraphs, so the order diff saw no move and
    the import said "nothing came back". Dragged one further, the diff broke its tie by
    calling the Methods paragraph the moved one, and the report blamed that."""
    from manuscript_guard.merge import apply_plan, plan_import

    path, text, known, b, intro, methods = _two_sections(tmp_path)
    sent = [intro, b["i1"], b["i2"], methods, b["m1"], b["m2"]]
    if landing == "below-the-heading":
        returned = [intro, b["i1"], methods, b["i2"], b["m1"], b["m2"]]
    else:
        returned = [intro, b["i1"], methods, b["m1"], b["i2"], b["m2"]]

    plan = plan_import(known, sent, returned)
    assert plan.misplaced == ("i2",)
    assert not plan.empty
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == text


def test_text_pandoc_renders_between_two_paragraphs_of_a_section_is_no_boundary(
    tmp_path: Path,
) -> None:
    """Only a heading, table or figure between two sections marks where one ends. An untagged
    paragraph inside a section - display maths, say - must not make an untouched document
    look moved."""
    from manuscript_guard.merge import plan_import

    _path, _text, known, b, intro, methods = _two_sections(tmp_path)
    from manuscript_guard.docxtext import Block

    sent = [intro, b["i1"], Block((), "x = 1"), b["i2"], methods, b["m1"], b["m2"]]
    assert plan_import(known, sent, list(sent)).empty


def test_a_figure_reads_as_a_block_of_its_own(tmp_path: Path) -> None:
    """A figure reaches Word as a paragraph holding a picture and no text. Read as an empty
    paragraph, it was no boundary at all, and a move past it went unseen."""
    from manuscript_guard.docxtext import blocks as read

    body = (
        '<w:p><w:bookmarkStart w:id="1" w:name="mg-p-main-1"/><w:bookmarkEnd w:id="1"/>'
        "<w:r><w:t>Alpha.</w:t></w:r></w:p>"
        "<w:p><w:r><w:drawing/></w:r></w:p>"
    )
    document = tmp_path / "figure.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/'
            f'main"><w:body>{body}</w:body></w:document>',
        )
    found = read(document)
    assert [(b.names, b.table) for b in found] == [(("mg-p-main-1",), False), ((), True)]


@pytest.mark.parametrize("dragged", ["beta", "alpha"])
def test_a_move_past_a_figure_is_reported_not_applied(tmp_path: Path, dragged: str) -> None:
    """Dragged below the figure, Beta was dropped with "nothing came back"; Alpha was
    applied as "Beta / Alpha / figure", neither the original order nor the co-author's."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path = tmp_path / "main.md"
    text = "Alpha.\n\nBeta.\n\n{{figure.forest}}\n\nGamma.\n"
    path.write_text(text, encoding="utf-8")
    known = {n: (path, w, text.index(w)) for n, w in (("alpha", "Alpha."), ("beta", "Beta."),
                                                      ("gamma", "Gamma."))}
    b = {n: Block((n,), known[n][1]) for n in known}
    figure = Block(table=True)
    sent = [b["alpha"], b["beta"], figure, b["gamma"]]
    others = [b[n] for n in ("alpha", "beta") if n != dragged]
    returned = [*others, figure, b[dragged], b["gamma"]]

    plan = plan_import(known, sent, returned)
    assert plan.misplaced == (dragged,)
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == text


def test_a_paragraph_that_reaches_word_in_parts_is_not_reworded(tmp_path: Path) -> None:
    """Display maths splits a paragraph: pandoc renders "Before $$y = z$$ after." as three
    Word paragraphs, and only the first carries the identifier. Its rewording was merged over
    the whole source paragraph, deleting the equation and everything after it."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    path = tmp_path / "main.md"
    text = "Alpha text here.\n\nBeta text here.\n"
    path.write_text(text, encoding="utf-8")
    known = {"a": (path, "Alpha text here.", 0), "b": (path, "Beta text here.", 18)}
    tail = Block((), "and the rest of it.")
    sent = [Block(("a",), "Alpha text"), tail, Block(("b",), "Beta text here.")]
    returned = [Block(("a",), "Alpha text, reworded"), tail, sent[2]]
    plan = plan_import(known, sent, returned)
    assert not plan.merged
    assert [refusal.name for refusal in plan.refused] == ["a"]


def test_text_typed_where_a_paragraph_renders_nothing_is_not_merged(tmp_path: Path) -> None:
    """An HTML comment is tagged and reaches Word as an empty line. Text typed on it replaced
    the comment's first half, `<!--` included, and the second half built into the Methods."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path = tmp_path / "main.md"
    comment = "<!--\nA note to self.\n"
    text = f"Before.\n\n{comment}\nStill hidden.\n-->\n"
    path.write_text(text, encoding="utf-8")
    known = {"p": (path, "Before.", 0), "c": (path, comment.strip(), text.index("<!--"))}
    sent = [Block(("p",), "Before."), Block(("c",), "")]
    plan = plan_import(known, sent, [sent[0], Block(("c",), "We also checked it.")])
    assert not plan.merged and [r.name for r in plan.refused] == ["c"]
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize(
    "source",
    ["Before $$y = z$$ and after.", "Before <!-- a note --> and after."],
    ids=["display-maths", "html-comment"],
)
def test_markup_that_word_text_cannot_carry_is_refused(source: str) -> None:
    from manuscript_guard.roundtrip import align

    aligned = align(source, "Before and after.", "Before and just after.")
    assert aligned.rebuilt is None and aligned.markup


def test_a_heading_its_paragraph_already_names_is_still_seen_joined(tmp_path: Path) -> None:
    """"Statistical analysis" above "Statistical analysis used...": joined, the heading's
    text was already in the paragraph, so it was not seen as taken in, and the source read
    "Statistical analysisStatistical analysis used..."."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    path = tmp_path / "main.md"
    body = "Statistical analysis used the reporting odds ratio."
    path.write_text(f"## Statistical analysis\n\n{body}\n", encoding="utf-8")
    known = {"p": (path, body, path.read_text(encoding="utf-8").index(body))}
    heading = Block((), "Statistical analysis")
    sent = [heading, Block(("p",), body)]
    plan = plan_import(known, sent, [Block(("p",), "Statistical analysis" + body)])
    assert not plan.merged
    assert [refusal.name for refusal in plan.refused] == ["p"]


@needs_pandoc
def test_a_heading_joined_into_its_paragraph_is_not_duplicated(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Delete at the end of a heading makes a run-in heading: one paragraph reading
    "MethodsWe analysed...", carrying the paragraph's identifier. It merged as prose, and
    `# Methods` stayed in the file above it."""
    from manuscript_guard.cli import main

    document = built(project)
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")

    def join(xml: str) -> str:
        paragraph = tagged_xml(xml)[3]
        heading = re.search(
            r"<w:p>(?:(?!<w:p>).)*?>Methods</w:t></w:r></w:p>\s*" + re.escape(paragraph),
            xml,
            re.DOTALL,
        )
        assert heading, "the Methods heading sits directly before its first paragraph"
        inner = re.sub(r"^<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?", "", paragraph, flags=re.DOTALL)
        heading_xml = heading.group(0)[: heading.group(0).index(paragraph)].rstrip()
        joined = heading_xml[: -len("</w:p>")] + inner
        return xml.replace(heading.group(0), joined, 1)

    returned = rewrite(document, tmp_path / "runin.docx", join)
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert source.read_text(encoding="utf-8") == before
    assert "heading" in capsys.readouterr().out


@needs_pandoc
def test_a_paragraph_split_in_word_is_not_truncated(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first half keeps the identifier, so the merge replaced the whole source paragraph
    with its first sentence and the rest of it was gone."""
    from manuscript_guard.cli import main

    document = built(project)
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")

    split = (
        'data generator.</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val="BodyText" /></w:pPr>'
        '<w:r><w:t xml:space="preserve">Real work'
    )
    returned = rewrite(
        document,
        tmp_path / "split.docx",
        lambda xml: xml.replace("data generator. Real work", split, 1),
    )
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert source.read_text(encoding="utf-8") == before
    assert "split" in capsys.readouterr().out


@needs_pandoc
@pytest.mark.parametrize("bookmark", ["kept", "lost"])
def test_two_paragraphs_joined_in_word_are_not_duplicated(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], bookmark: str
) -> None:
    """Joined, the first paragraph absorbed the second and was merged with both texts - while
    the second, whose identifier no longer started a paragraph, was reported deleted and left
    in place. The second paragraph's text was in the source twice.

    Word keeps the second paragraph's bookmark when the paragraph mark between them is
    deleted, but not when the join is made by selecting across the boundary and retyping.
    """
    from manuscript_guard.cli import main

    document = built(project)
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")

    def join(xml: str) -> str:
        tagged = tagged_xml(xml)
        first, second = tagged[3], tagged[4]
        inner = re.sub(r"^<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?", "", second, flags=re.DOTALL)
        if bookmark == "lost":
            inner = re.sub(r"<w:bookmark(?:Start|End)\b[^>]*/>", "", inner)
        return xml.replace(second, "", 1).replace(first, first[: -len("</w:p>")] + inner, 1)

    returned = rewrite(document, tmp_path / "joined.docx", join)
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert source.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "joined" in out
    assert "deleted in Word" not in out


@needs_pandoc
@pytest.mark.parametrize("markup", ["tab-in-a-run", "tab-stops", "text-alignment"])
def test_word_layout_markup_never_reaches_the_source(
    project: Path, tmp_path: Path, markup: str
) -> None:
    """`<w:t[^>]*>` also matches `<w:tab/>`, `<w:tabs>` and `<w:textAlignment .../>`, and
    the lazy match then ran to the next `</w:t>` - so a paragraph with a tab in it merged
    `</w:r><w:r><w:t xml:space="preserve">` into the manuscript source."""
    from manuscript_guard.cli import main

    document = built(project)
    source = project / "manuscript" / "main.md"

    def edit(xml: str) -> str:
        paragraph = tagged_xml(xml)[2]
        if markup == "tab-in-a-run":
            changed = paragraph.replace(
                '<w:t xml:space="preserve">Whether', '<w:tab /><w:t xml:space="preserve">Whether'
            )
        elif markup == "tab-stops":
            changed = paragraph.replace(
                "</w:pPr>", '<w:tabs><w:tab w:val="left" w:pos="720" /></w:tabs></w:pPr>', 1
            )
        else:
            changed = paragraph.replace("</w:pPr>", '<w:textAlignment w:val="auto" /></w:pPr>', 1)
        assert changed != paragraph
        changed = changed.replace("has not been examined.", "has not yet been examined.")
        return xml.replace(paragraph, changed, 1)

    returned = rewrite(document, tmp_path / "tabbed.docx", edit)
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    text = source.read_text(encoding="utf-8")
    assert "<w:" not in text and "</w:" not in text
    assert (
        "Whether the signal extends to example-drug specifically has not yet been examined."
        in text
    )


@needs_pandoc
def test_a_number_grown_by_a_digit_in_word_is_refused(project: Path, tmp_path: Path) -> None:
    """3.84 -> 13.84 merged as `1{{results.ror.point}}`. G2 would have caught the stray 1,
    but the merge should never have written it."""
    from manuscript_guard.cli import main

    document = built(project)
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")
    returned = rewrite(
        document,
        tmp_path / "grown.docx",
        lambda xml: re.sub(r"(<w:t[^>]*>[^<]*?)(?<![\d.])3\.84", r"\g<1>13.84", xml, count=1),
    )
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert source.read_text(encoding="utf-8") == before


def _tracked_deletion(paragraph: str) -> str:
    """The paragraph as Word writes it after deleting it with Track Changes on."""
    counter = iter(range(900, 999))
    stamp = 'w:author="A Co-Author" w:date="2026-09-01T00:00:00Z"'

    def deleted(match: re.Match[str]) -> str:
        run = match.group(0).replace("<w:t ", "<w:delText ").replace("</w:t>", "</w:delText>")
        return f'<w:del w:id="{next(counter)}" {stamp}>{run}</w:del>'

    out = re.sub(r"<w:r>.*?</w:r>", deleted, paragraph, flags=re.DOTALL)
    mark = f'<w:rPr><w:del w:id="{next(counter)}" {stamp} /></w:rPr></w:pPr>'
    return out.replace("</w:pPr>", mark, 1)


@needs_pandoc
def test_a_paragraph_deleted_as_a_tracked_change_is_reported_as_deleted(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It came back as an empty paragraph and was refused as 'a number or a citation in this
    paragraph changed' - true of nothing in it, and pointing the author at the analysis."""
    from manuscript_guard.cli import main

    document = built(project)
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")

    def delete(xml: str) -> str:
        paragraph = tagged_xml(xml)[3]
        return xml.replace(paragraph, _tracked_deletion(paragraph), 1)

    returned = rewrite(document, tmp_path / "deleted.docx", delete)
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert source.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "deleted in Word" in out and "We analysed a synthetic" in out
    assert "number or a citation" not in out


@needs_pandoc
def test_an_edited_citation_is_refused_and_named(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from manuscript_guard.cli import main

    document = built(project)
    returned = rewrite(
        document,
        tmp_path / "cited.docx",
        lambda xml: xml.replace("(Fictional and Fictional 2021)", "(Fictional 2021)", 1),
    )
    capsys.readouterr()
    assert main(["import", str(returned), str(project)]) == 1
    out = capsys.readouterr().out
    assert "[@fictionalHepaticCohort2021]" in out, out


def source_of(tmp_path: Path, paragraphs: dict[str, str]) -> tuple[Path, dict]:
    """A one-file manuscript and the identifier table `tagged_paragraphs` would give it."""
    path = tmp_path / "main.md"
    path.write_text("\n\n".join(paragraphs.values()) + "\n", encoding="utf-8")
    known, at = {}, 0
    for name, text in paragraphs.items():
        known[name] = (path, text, at)
        at += len(text) + 2
    return path, known


def test_a_join_that_lost_its_bookmark_and_an_edit_is_still_a_join(tmp_path: Path) -> None:
    """Selecting across the boundary and retyping deletes the second bookmark. Recognised by
    one unbroken run of the second paragraph's words, a single edited word in the middle of
    it split the run, the join went unseen, and the text was in the source twice."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    paragraphs = {
        "a": "Alpha comes first here.",
        "b": "The cohort included adult patients only.",
        "c": "Patients with prior liver disease were excluded from all analyses.",
    }
    path, known = source_of(tmp_path, paragraphs)
    before = path.read_text(encoding="utf-8")
    sent = [Block((name,), text) for name, text in paragraphs.items()]
    joined = paragraphs["b"] + " " + paragraphs["c"].replace("disease", "condition")
    returned = [sent[0], Block(("b",), joined)]

    plan = plan_import(known, sent, returned)
    assert plan.joined == (("b", "c"),)
    assert not plan.merged and not plan.gone
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == before


def test_a_join_is_seen_when_the_first_paragraph_was_reworded_too(tmp_path: Path) -> None:
    """Retyping across the boundary rewords the transition as well. Counting only the words
    the first paragraph gained against its old text let the diff hand the absorbed
    paragraph's common words ("the", "patients", "study") to the old text, and the join
    went unseen."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    paragraphs = {
        "b": "The patients in the study were included for the analysis form.",
        "c": "The patients in the study were also excluded from the cohort for the consent form.",
    }
    _path, known = source_of(tmp_path, paragraphs)
    sent = [Block((name,), text) for name, text in paragraphs.items()]
    joined = (
        "In the study, the patients were included for the analysis form, and the patients "
        "in the study were also excluded from the cohort for the consent form."
    )
    plan = plan_import(known, sent, [Block(("b",), joined)])
    assert plan.joined == (("b", "c"),)
    assert not plan.merged


def test_a_deletion_beside_a_small_rewording_is_not_a_join(tmp_path: Path) -> None:
    """The other side of the same judgement: deleting a paragraph and fixing a word in the
    one before it must still merge the fix."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    paragraphs = {
        "b": "The cohort included adult patients only, recruited over ten years.",
        "c": "Patients with prior liver disease were excluded from all analyses.",
    }
    _path, known = source_of(tmp_path, paragraphs)
    sent = [Block((name,), text) for name, text in paragraphs.items()]
    edited = "The cohort included adult patients only, recruited over a decade."
    plan = plan_import(known, sent, [Block(("b",), edited)])
    assert plan.gone == ("c",) and not plan.joined
    assert plan.merged == {"b": edited}


@pytest.mark.parametrize("bookmark", ["kept", "lost"])
def test_a_move_elsewhere_does_not_land_inside_a_join(tmp_path: Path, bookmark: str) -> None:
    """A paragraph that is not applied - joined, deleted, moved to another file - used to keep
    its slot while the paragraphs around it moved, so another paragraph's move could land
    between two halves of a join. It travels with the paragraph it followed."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    paragraphs = {"a": "Text A here.", "b": "Text B here.", "c": "Text C here."}
    path, known = source_of(tmp_path, paragraphs)
    sent = [Block((name,), text) for name, text in paragraphs.items()]
    names = ("b", "c") if bookmark == "kept" else ("b",)
    returned = [Block(names, "Text B here. Text C here."), sent[0]]

    plan = plan_import(known, sent, returned)
    assert plan.joined == (("b", "c"),)
    apply_plan(known, plan)
    after = blocks(path.read_text(encoding="utf-8"))
    assert after == ["Text B here.", "Text C here.", "Text A here."]


def test_a_deleted_paragraph_stays_after_the_one_it_followed(tmp_path: Path) -> None:
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    paragraphs = {"a": "Text A here.", "b": "Text B here.", "c": "Text C here."}
    path, known = source_of(tmp_path, paragraphs)
    sent = [Block((name,), text) for name, text in paragraphs.items()]

    plan = plan_import(known, sent, [sent[2], sent[0]])
    assert plan.gone == ("b",)
    apply_plan(known, plan)
    after = blocks(path.read_text(encoding="utf-8"))
    assert after == ["Text C here.", "Text A here.", "Text B here."]


def test_a_paragraph_that_came_back_twice_stays_where_it_was(tmp_path: Path) -> None:
    """Its text is refused, and its place must be too: the first copy used to decide where
    the paragraph went, so a copy pasted earlier in the document moved it there."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path = tmp_path / "main.md"
    text = "Alpha one.\n\nBeta two.\n\nGamma three.\n"
    path.write_text(text, encoding="utf-8")
    known = {
        "a": (path, "Alpha one.", 0),
        "b": (path, "Beta two.", 12),
        "c": (path, "Gamma three.", 23),
    }
    sent = [Block(("a",), "Alpha one."), Block(("b",), "Beta two."), Block(("c",), "Gamma three.")]
    returned = [Block(("c",), "Gamma three."), *sent]

    plan = plan_import(known, sent, returned)
    apply_plan(known, plan)
    assert [refusal.name for refusal in plan.refused] == ["c"]
    assert path.read_text(encoding="utf-8") == text


def test_import_without_pandoc_says_so_rather_than_crashing(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Import rebuilds the document to compare against, and died with a BuildError traceback
    when pandoc was missing."""
    import manuscript_guard.build.document as document
    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.review import document_digest

    returned = tmp_path / "back.docx"
    with zipfile.ZipFile(returned, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    stamp_into(returned, document_digest(load_project(project)[0]))

    real = shutil.which
    monkeypatch.setattr(
        document.shutil,
        "which",
        lambda name, *a, **k: None if name == "pandoc" else real(name, *a, **k),
    )
    assert main(["import", str(returned), str(project)]) == 2
    assert "pandoc" in capsys.readouterr().err


def test_respond_from_a_file_that_is_not_a_docx_says_so(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from manuscript_guard.cli import main

    bogus = tmp_path / "reviews.docx"
    bogus.write_text("the reviewers' comments, pasted into a text file", encoding="utf-8")
    assert main(["respond", str(project), "--open", "--from", str(bogus)]) == 2
    assert "reviews.docx" in capsys.readouterr().err
    assert not (project / "revision").exists(), "no round opened from nothing"
