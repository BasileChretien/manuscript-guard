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


REGISTRY = "https://example.org/registry"

REFERENCE_LINKS = [
    pytest.param(
        "See [the registry][reg] for details.", f"[reg]: {REGISTRY}", "the registry", id="full"
    ),
    pytest.param("See [reg][] for details.", f"[reg]: {REGISTRY}", "reg", id="collapsed"),
    pytest.param("See [reg] for details.", f"[reg]: {REGISTRY}", "reg", id="shortcut"),
    pytest.param(
        "See [reg] for details.",
        f"   [reg]: <{REGISTRY}> 'The registry'",
        "reg",
        id="indented-with-title",
    ),
    pytest.param(
        "See [reg] and [other] for details.",
        f"[other]: https://example.org/other\n[reg]: {REGISTRY} \"The registry\"",
        "reg and other",
        id="several-definitions",
    ),
]


def _docx_part(document: Path, part: str) -> str:
    return zipfile.ZipFile(document).read(part).decode("utf-8")


@needs_pandoc
@pytest.mark.parametrize(("paragraph", "definition", "shown"), REFERENCE_LINKS)
def test_a_link_definition_is_left_for_pandoc_to_read(
    paragraph: str, definition: str, shown: str, tmp_path: Path
) -> None:
    """`[reg]: https://...` standing as its own block defines a reference-style link. With an
    identifier in front of it, pandoc read it as a paragraph instead: every `[text][reg]` in
    the manuscript printed with its brackets, linked to nothing, and the definition itself
    printed as a line of text. On every build, not only in `import`."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text, tag

    source = tmp_path / "a.md"
    source.write_text(tag(f"{paragraph}\n\n{definition}\n", "main.md"), encoding="utf-8")
    document = tmp_path / "a.docx"
    subprocess.run(["pandoc", str(source), "-o", str(document)], check=True)

    assert f'Target="{REGISTRY}"' in _docx_part(document, "word/_rels/document.xml.rels")
    assert "<w:hyperlink" in _docx_part(document, "word/document.xml")
    # The paragraph keeps its identifier and reads as the link's words; the definition
    # reaches the document as nothing at all.
    assert list(paragraph_text(document).values()) == [f"See {shown} for details."]


@needs_pandoc
def test_a_footnote_definition_is_left_for_pandoc_to_read(tmp_path: Path) -> None:
    """The same syntax defines a footnote, and failed the same way: `[^cap]` printed in the
    paragraph, and the note's text printed as a paragraph of its own."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text, tag

    source = tmp_path / "a.md"
    text = "Doses were capped.[^cap]\n\n[^cap]: Capped at 40 mg.\n"
    source.write_text(tag(text, "main.md"), encoding="utf-8")
    document = tmp_path / "a.docx"
    subprocess.run(["pandoc", str(source), "-o", str(document)], check=True)

    assert "Capped at 40 mg." in _docx_part(document, "word/footnotes.xml")
    assert list(paragraph_text(document).values()) == ["Doses were capped."]


#: How pandoc 3.9 reads a block, and what `tag` does with it: a definition in a shape pandoc
#: can read no other way is left alone; prose is marked; and a definition written any other
#: way is marked on purpose, so it prints as text - visibly, where leaving a block unmarked
#: that pandoc prints would lose a co-author's edit to it without a word.
DEFINITION, PROSE, MARKED = "definition", "prose", "marked"

BLOCKS = [
    pytest.param(f"[reg]: {REGISTRY}", DEFINITION, id="link"),
    pytest.param(f"[reg]: {REGISTRY} \"The registry\"", DEFINITION, id="title"),
    pytest.param(f"   [reg]: <{REGISTRY}> (The registry)", DEFINITION, id="angled-title"),
    pytest.param("[^cap]: Capped at 40 mg.", DEFINITION, id="footnote"),
    pytest.param(f"[a]: {REGISTRY}\n[b]: {REGISTRY}/b", DEFINITION, id="several"),
    pytest.param(f"[a]: {REGISTRY}\n[^1]: A note.\n[^2]: Another.", DEFINITION, id="links-notes"),
    pytest.param(f"[]: {REGISTRY}", DEFINITION, id="empty-label"),
    pytest.param("[^@cap]: A note <!-- with `code` $x$", DEFINITION, id="note-with-markup"),
    pytest.param("[^or]: Adjusted, {{results.ror.point}}.", DEFINITION, id="note-with-binding"),
    # An address of several words, run together: pandoc prints nothing of these.
    pytest.param("[Methods]: patients were enrolled.", MARKED, id="prose-shaped"),
    pytest.param("[1]: Smith J, Doe A. A cohort study. Lancet. 2020;395:1.", MARKED, id="refs"),
    # Definitions in a shape pandoc could read another way.
    pytest.param("[^cap]: Capped at 40 mg,\nor 20 mg.", MARKED, id="note-lines"),
    pytest.param(f"[^1]: A note.\n[a]: {REGISTRY}", MARKED, id="link-under-a-note"),
    pytest.param(f"[a [b] c]: {REGISTRY}", MARKED, id="nested-label"),
    pytest.param(f"[mail@example.org]: {REGISTRY}", MARKED, id="at-in-label"),
    pytest.param(f"[Food and Drug\nAdministration]: {REGISTRY}", MARKED, id="wrapped-label"),
    pytest.param(f"[reg]: {REGISTRY} (The registry) {{.external}}", MARKED, id="attributes"),
    pytest.param(f"[reg]: {REGISTRY}\n  'Registry'", MARKED, id="title-below"),
    pytest.param(f"[a\\]b]: {REGISTRY}", MARKED, id="escaped-bracket"),
    # Filled in after `tag` has read the line, a binding's value could make it prose.
    pytest.param(f"[reg]: {REGISTRY}/{{{{lit.agency.url}}}}", MARKED, id="binding-in-link"),
    # Prose: a line pandoc gives up on as a definition, or a line after it that it does not.
    pytest.param(f"[reg]: {REGISTRY}{chr(0xA0)}", PROSE, id="no-break-space-after"),
    pytest.param(f"{chr(0x3000)}[reg]: {REGISTRY}", PROSE, id="wide-space-before"),
    pytest.param(f'[reg]: {REGISTRY} "Registry" {{#NCT01/2020}}', PROSE, id="bad-attributes"),
    pytest.param(
        "[^1]: Adjusted for age.\n[^2]: Adjusted for sex.\n[^3] Adjusted for renal function.",
        PROSE,
        id="note-without-colon",
    ),
    pytest.param("[<!--x]: u\n[^y]: -->", PROSE, id="comment-in-label"),
    pytest.param("[a $x]: u '$'", PROSE, id="maths-in-label"),
    pytest.param("[@*key]: u", PROSE, id="wildcard-citation"),
    # Words after what pandoc takes for a title, or a bracket in the address, make it prose.
    pytest.param("[Methods]: patients (n = 200) were enrolled.", PROSE, id="words-after-title"),
    pytest.param('[Box 1]: Patients described as "frail" were excluded.', PROSE, id="quoted"),
    pytest.param('[Note]: answers were coded "yes", "(blank)"', PROSE, id="two-quotes"),
    pytest.param("[Methods]: see [reg] for the protocol.", PROSE, id="bracket-in-address"),
    pytest.param("[Note]: [see Figure 2] for this.", PROSE, id="address-is-bracketed"),
    pytest.param(f"[reg]: <{REGISTRY}> and more words", PROSE, id="words-after-address"),
    pytest.param(f"[reg]: {REGISTRY}\n(which is public) and more.", PROSE, id="title-then-words"),
    # A first line pandoc swallows, and the paragraph it reads under it.
    pytest.param(
        "[Box 1]: Definitions. Injury was an ALT above three times\nthe upper limit of normal.",
        PROSE,
        id="wrapped-prose",
    ),
    pytest.param(f"[reg]: {REGISTRY}\nIt is public.", PROSE, id="definition-then-prose"),
    pytest.param("See [Methods] here.", PROSE, id="bracket-inside"),
    pytest.param("[Methods] describes the cohort.", PROSE, id="no-colon"),
    pytest.param(f"[reg] : {REGISTRY}", PROSE, id="space-before-colon"),
    # A definition cannot interrupt a paragraph.
    pytest.param(f"See [reg] for details.\n[reg]: {REGISTRY}", PROSE, id="second-line"),
    pytest.param("[@fictionalClassSignal2019]: a cohort of 1,200.", PROSE, id="citation"),
    pytest.param("[see @fictionalClassSignal2019]: a cohort.", PROSE, id="prefixed-citation"),
    pytest.param("[see\n@fictionalClassSignal2019]: a cohort.", PROSE, id="wrapped-citation"),
]


@pytest.mark.parametrize(("block", "reads"), BLOCKS)
def test_only_a_block_of_definitions_is_left_without_an_identifier(
    block: str, reads: str
) -> None:
    """A paragraph keeps its identifier however it opens: with a bracket, with a citation and
    a colon, or with a line pandoc would swallow as a definition."""
    from manuscript_guard.roundtrip import tag

    tagged = tag(block, "main.md")
    assert (tagged == block) is (reads == DEFINITION), tagged
    assert tagged.lstrip().startswith("[]{#mg-p-") is (reads != DEFINITION), tagged


def _renders_nothing(text: str) -> bool:
    import json
    import subprocess

    read = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(read.stdout)["blocks"] == []


@needs_pandoc
@pytest.mark.parametrize(("block", "reads"), BLOCKS)
def test_what_is_left_unmarked_renders_nothing(block: str, reads: str) -> None:
    """The readings above are pandoc's, and the property that matters is checked on the
    artefact. A block left without an identifier renders nothing, so no paragraph goes
    without one; a marked block renders something, so its identifier reaches Word."""
    from manuscript_guard.roundtrip import tag

    tagged = tag(block, "main.md")
    assert tagged != block or _renders_nothing(block), "a paragraph went without an identifier"
    assert _renders_nothing(block) is (reads != PROSE)
    assert _renders_nothing(tagged) is (reads == DEFINITION)


def test_tag_and_tagged_paragraphs_name_the_same_blocks(project: Path) -> None:
    """`tag` marks the document and `tagged_paragraphs` names what `import` looks up. Read
    from the stripped block in one and the raw block in the other, a definition ending in a
    no-break space was marked in the document and unknown on disk."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.roundtrip import tag, tagged_paragraphs

    text = "\n\n".join(param.values[0] for param in BLOCKS) + "\n"
    (project / "manuscript" / "definitions.md").write_text(text, encoding="utf-8")
    loaded, _report = load_project(project)
    known = {
        name
        for name, (path, _text, _start) in tagged_paragraphs(loaded).items()
        if path.name == "definitions.md"
    }
    marked = set(re.findall(r"\[\]\{#(mg-p-[^}]+)\}", tag(text, "definitions.md")))
    assert marked == known
    assert len(marked) == sum(reads != DEFINITION for _block, reads in (p.values for p in BLOCKS))


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
    # Within the Discussion: its last paragraph to its first.
    assert "Several limitations" in tagged[12] and "exceeds the class-level" in tagged[10]
    moved_xml = xml.replace(tagged[12], "", 1).replace(tagged[10], tagged[12] + tagged[10], 1)

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
    ("source", "named"),
    [
        ("See the [agency report](https://example.org/r) for details.", "a link"),
        ("See the agency report.^[Withdrawn in 2019.] It has details.", "a footnote"),
    ],
    ids=["link", "footnote"],
)
def test_a_paragraph_whose_markup_word_cannot_carry_is_refused(source: str, named: str) -> None:
    """Word's plain text has the link's words but not its address, and a footnote's
    reference mark but not its text. Merging it over the source deleted both."""
    from manuscript_guard.merge import why
    from manuscript_guard.roundtrip import align

    rendered = "See the agency report for details."
    aligned = align(source, rendered, "See the agency report for more details.")
    assert aligned.rebuilt is None
    assert named in why(aligned)[0]


def test_a_value_is_found_in_its_own_place_not_in_the_prose_before_it() -> None:
    """'Table 1 shows 1 events' - the first '1' is prose. Searching for the rendered value
    from the start of the paragraph moved the binding onto the table number and left the
    value behind as a literal."""
    source = "Table 1 shows {{results.x}} events."
    out = realign(source, "Table 1 shows 1 events.", "Table 1 now shows 1 events.")
    assert out == "Table 1 now shows {{results.x}} events."


# ------------------------------------------ what Word's text cannot carry back to the source


def test_an_inline_comment_and_footnote_are_not_merged_away() -> None:
    """The reported case. Neither reaches the paragraph's `w:t` text, so rebuilding the
    paragraph from what came back deleted the comment, and nothing said so."""
    from manuscript_guard.merge import why
    from manuscript_guard.roundtrip import align

    source = "Text <!-- keep me --> with a note^[the footnote] here."
    aligned = align(source, "Text with a note here.", "Text with a note there.")
    assert aligned.rebuilt is None
    assert aligned.markup == ("an HTML comment", "a footnote")
    assert "an HTML comment and a footnote" in why(aligned)[0]
    assert "lose them" in why(aligned)[0]


# (source, what its paragraph shows in Word) - each rendered form was read off pandoc's
# output for that source, not assumed.
UNCARRIED = [
    pytest.param("Text <!-- keep me --> here.", "Text here.", "an HTML comment", id="comment"),
    pytest.param("Text with a ref[^1] here.", "Text with a ref here.", "a footnote", id="note-ref"),
    pytest.param(
        'Text <span class="x">inside</span> here.', "Text inside here.", "inline HTML", id="html"
    ),
    pytest.param(r"Raw \ref{fig} here.", "Raw here.", "raw TeX", id="raw-tex"),
    pytest.param("Raw `<b>x</b>`{=html} here.", "Raw here.", "a raw inline", id="raw-attribute"),
    pytest.param(
        "Text [small]{.smallcaps} here.", "Text small here.", "a span with attributes", id="span"
    ),
    pytest.param("See <https://x.org> here.", "See https://x.org here.", "a link", id="autolink"),
    pytest.param("Math $x^2$ here.", "Math here.", "an equation", id="math"),
    pytest.param("Units of 10^9^/L here.", "Units of 109/L here.", "a superscript", id="sup"),
    pytest.param("Water is H~2~O here.", "Water is H2O here.", "a subscript", id="sub"),
    pytest.param("An ![a plot](plot.png) here.", "An here.", "an image", id="image"),
    pytest.param("Text ~~gone~~ here.", "Text gone here.", "struck-through text", id="struck"),
]


@pytest.mark.parametrize(("source", "rendered", "named"), UNCARRIED)
def test_markup_word_text_cannot_carry_refuses_a_rewording(
    source: str, rendered: str, named: str
) -> None:
    """Each reaches Word as something other than its source: nothing at all, or its words
    without the address, the attributes, or the raised 9 that makes 10^9 not 109."""
    from manuscript_guard.roundtrip import align

    aligned = align(source, rendered, rendered.replace("here", "there"))
    assert aligned.rebuilt is None
    assert aligned.markup == (named,)


@pytest.mark.parametrize(("source", "rendered", "named"), UNCARRIED)
def test_markup_in_an_unedited_paragraph_is_left_alone(
    source: str, rendered: str, named: str
) -> None:
    assert realign(source, rendered, rendered) == source


def test_markup_in_an_untouched_stretch_survives_the_merge() -> None:
    """The refusal is per stretch of prose, not per paragraph: a footnote before a binding
    stays where it was when the co-author reworded only the text after it."""
    source = "Readers^[an aside] saw {{results.x}} and more words."
    rendered = "Readers saw 3.84 and more words."
    out = realign(source, rendered, "Readers saw 3.84 and many more words.")
    assert out == "Readers^[an aside] saw {{results.x}} and many more words."


def test_markup_in_the_edited_stretch_refuses_the_merge() -> None:
    from manuscript_guard.roundtrip import align

    source = "Readers^[an aside] saw {{results.x}} and more words."
    rendered = "Readers saw 3.84 and more words."
    aligned = align(source, rendered, "Most readers saw 3.84 and more words.")
    assert aligned.rebuilt is None
    assert aligned.markup == ("a footnote",)


def test_a_binding_inside_a_footnote_belongs_to_the_footnote() -> None:
    """It renders into footnotes.xml, not into the paragraph, so it cannot be aligned as one
    of the paragraph's own tokens - and a comment's binding is never rendered at all."""
    prose, protected = segments("a^[n = {{results.n}}] b {{results.x}} c <!-- {{results.y}} -->")
    assert protected == ["{{results.x}}"]
    assert prose[0] == "a^[n = {{results.n}}] b "


def test_a_binding_inside_inline_code_is_still_a_binding() -> None:
    """Code shows its text, so a binding in it renders into the paragraph like any other."""
    _prose, protected = segments("Run with version `{{results.version}}` today.")
    assert protected == ["{{results.version}}"]


@pytest.mark.parametrize(
    ("source", "rendered", "returned"),
    [
        pytest.param(
            "The **ratio {{results.x}} was** high.",
            "The ratio 3.84 was high.",
            "The ratio 3.84 was very high.",
            id="bold",
        ),
        pytest.param(
            "Run with version `{{results.v}}` today.",
            "Run with version 4.4.1 today.",
            "Run with version 4.4.1 again today.",
            id="code",
        ),
    ],
)
def test_formatting_around_a_binding_is_not_cut_in_half(
    source: str, rendered: str, returned: str
) -> None:
    """The prose either side of a binding each holds one delimiter. Rebuilding the edited
    side from Word's text dropped its delimiter and kept the other: `**ratio {{results.x}}
    was very high.`, and the document printed the asterisks."""
    from manuscript_guard.roundtrip import align

    aligned = align(source, rendered, returned)
    assert aligned.rebuilt is None
    assert aligned.markup == ("one end of an emphasis or code span",)


def test_bold_around_two_bindings_is_not_stretched_over_the_words_between() -> None:
    """The stretch between holds a closing and an opening delimiter, so counting them found
    an even number and let it merge: `**{{results.x}} versus {{results.y}}**`, the co-author's
    word now bold and the author's two bold values one span."""
    from manuscript_guard.roundtrip import align

    source = "The **{{results.x}}** and **{{results.y}}** values differ."
    aligned = align(
        source, "The 3.84 and 7.02 values differ.", "The 3.84 versus 7.02 values differ."
    )
    assert aligned.rebuilt is None
    assert aligned.markup == ("one end of an emphasis or code span",)


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        pytest.param(
            r"Values \<LLOQ and \>ULOQ (n = {{results.n}}) were excluded.",
            "Values <LLOQ and >ULOQ (n = 56) were excluded.",
            "Concentrations <LLOQ and >ULOQ (n = 56) were excluded.",
            r"Concentrations \<LLOQ and >ULOQ (n = {{results.n}}) were excluded.",
            id="escape",
        ),
        pytest.param(
            "Values &lt;LLOQ and &gt;ULOQ (n = {{results.n}}) were excluded.",
            "Values <LLOQ and >ULOQ (n = 56) were excluded.",
            "Concentrations <LLOQ and >ULOQ (n = 56) were excluded.",
            r"Concentrations \<LLOQ and >ULOQ (n = {{results.n}}) were excluded.",
            id="entity",
        ),
        pytest.param(
            r"Carriers of CYP2D6\*4 and CYP2D6\*10 were poor metabolisers.",
            "Carriers of CYP2D6*4 and CYP2D6*10 were poor metabolisers.",
            "Carriers of CYP2D6*4 and CYP2D6*10 were slow metabolisers.",
            r"Carriers of CYP2D6\*4 and CYP2D6\*10 were slow metabolisers.",
            id="genotype",
        ),
        pytest.param(
            r"The adjusted HR\* {{results.x}} was lower.",
            "The adjusted HR* 3.84 was lower.",
            "An adjusted HR* 3.84 was lower.",
            r"An adjusted HR\* {{results.x}} was lower.",
            id="escape-beside-a-binding",
        ),
        pytest.param(
            "The HR {{results.x}}* was lower.",
            "The HR 3.84* was lower.",
            "The HR 3.84* was higher.",
            r"The HR {{results.x}}\* was higher.",
            id="asterisk-after-a-binding",
        ),
        pytest.param(
            r"The \"real-world\" data (95% CI \[1.2-3.4\]; p\<0.05) cost US\$5.",
            "The “real-world” data (95% CI [1.2-3.4]; p<0.05) cost US$5.",
            "The “real-world” data (95% CI [1.2-3.4]; p<0.05) cost only US$5.",
            r"The “real-world” data (95% CI \[1.2-3.4]; p<0.05) cost only US\$5.",
            id="converted-from-word",
        ),
    ],
)
def test_what_word_shows_unescaped_goes_back_reading_the_same(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """Word shows `\\<LLOQ` as "<LLOQ", and written back bare that is an HTML tag: the
    document printed "Concentrations ULOQ". `CYP2D6\\*4` came back as the start of italics.
    Refusing every escape instead refused most of a paper converted from Word by pandoc,
    which escapes as a habit. So Word's text is escaped where Markdown would read it as
    markup, and only there."""
    assert realign(source, rendered, returned) == expected


def test_a_line_break_word_reads_back_as_a_space_is_refused() -> None:
    """A line break reaches Word's text as a space, so nothing in it says a line was broken."""
    from manuscript_guard.roundtrip import align

    aligned = align(
        "Line one  \nline two here.", "Line one line two here.", "Line one line two there."
    )
    assert aligned.rebuilt is None
    assert aligned.markup == ("a line break",)


NO_BREAK = [
    pytest.param(
        "The dose was 5\u00a0mg/kg in all.",
        "The dose was 5\u00a0mg/kg in all.",
        "The dose was 5\u00a0mg/kg in most.",
        "The dose was 5\u00a0mg/kg in most.",
        id="no-break-space",
    ),
    pytest.param(
        "Le seuil\u202f: 5\u202fmg, «\u00a0au plus\u00a0».",
        "Le seuil\u202f: 5\u202fmg, «\u00a0au plus\u00a0».",
        "Le seuil\u202f: 5\u202fmg, «\u00a0au maximum\u00a0».",
        "Le seuil\u202f: 5\u202fmg, «\u00a0au maximum\u00a0».",
        id="french",
    ),
    pytest.param(
        "The ratio was {{results.x}}\u00a0% in all.",
        "The ratio was 3.84\u00a0% in all.",
        "The ratio was 3.84\u00a0% in most.",
        "The ratio was {{results.x}}\u00a0% in most.",
        id="after-a-binding",
    ),
    pytest.param(
        "At p\u00a0=\u00a0{{results.x}} it held.",
        "At p\u00a0=\u00a03.84 it held.",
        "Where p\u00a0=\u00a03.84 it held.",
        "Where p\u00a0=\u00a0{{results.x}} it held.",
        id="before-a-binding",
    ),
    pytest.param(
        r"The dose was 5\ mg in all.",
        "The dose was 5\u00a0mg in all.",
        "The dose was 5\u00a0mg in most.",
        "The dose was 5\u00a0mg in most.",
        id="escaped-space",
    ),
    pytest.param(
        "The dose was 5&nbsp;mg in all.",
        "The dose was 5\u00a0mg in all.",
        "The dose was 5\u00a0mg in most.",
        "The dose was 5\u00a0mg in most.",
        id="entity",
    ),
    pytest.param(
        "Le mot : clair.", "Le mot : clair.", "Le mot\u00a0: clair.", "Le mot\u00a0: clair.",
        id="typed-in-word",
    ),
    pytest.param(
        "Le mot : {{results.x}} ici.",
        "Le mot : 3.84 ici.",
        "Le mot\u00a0: 3.84 ici.",
        "Le mot\u00a0: {{results.x}} ici.",
        id="typed-in-word-beside-a-binding",
    ),
    pytest.param(
        "As Smith et al. 2020 showed, e.g. {{results.x}} was high.",
        "As Smith et al.\u00a02020 showed, e.g.\u00a03.84 was high.",
        "As Smith et al.\u00a02020 showed, e.g.\u00a03.84 was very high.",
        "As Smith et al. 2020 showed, e.g. {{results.x}} was very high.",
        id="pandoc-abbreviation",
    ),
    pytest.param(
        "Smith et al. 2020 found it.",
        "Smith et al.\u00a02020 found it.",
        "Smith et al.\u00a02020 found this.",
        "Smith et al.\u00a02020 found this.",
        id="pandoc-abbreviation-edited",
    ),
    pytest.param(
        "The *mot\u00a0* here gave {{results.x}} in all cases.",
        "The mot\u00a0 here gave 3.84 in all cases.",
        "The mot\u00a0 here gave 3.84 in most cases.",
        "The *mot\u00a0* here gave {{results.x}} in most cases.",
        id="emphasis-beside-it",
    ),
]


@pytest.mark.parametrize(("source", "rendered", "returned", "expected"), NO_BREAK)
def test_a_no_break_space_merges_as_typed(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """Word's text was read with every space made plain, so a no-break space could not come
    back and a stretch holding one was refused. Word's French AutoCorrect puts one before `:`
    and inside « », and authors put one in "5 mg", so a French manuscript refused almost every
    edit. The character comes back now, however the source wrote it: `\\ ` and `&nbsp;` return
    as the character itself, which prints the same.

    Pandoc adds one of its own after an abbreviation it knows ("et al.", "e.g.", "p."), where
    the source has a plain space. That is typesetting, not an edit: a stretch left alone keeps
    the source's space, and an edited one carries pandoc's character, which prints the same."""
    assert realign(source, rendered, returned) == expected


@pytest.mark.parametrize(
    ("source", "rendered"),
    [
        pytest.param(
            "Expression of *BRCA1* in tumours, e.g. breast, was {{results.x}} overall.",
            "Expression of BRCA1 in tumours, e.g.\u00a0breast, was 3.84 overall.",
            id="beside-a-binding",
        ),
        pytest.param(
            "Expression of *BRCA1* in tumours, e.g. breast.",
            "Expression of BRCA1 in tumours, e.g.\u00a0breast.",
            id="plain",
        ),
    ],
)
def test_pandocs_no_break_space_taken_out_in_word_is_no_edit(source: str, rendered: str) -> None:
    """Compared only with what was sent, a stretch whose no-break space after "e.g." came back
    plain read as edited, was rebuilt from Word's text, and lost its italics - for a change
    the next build undoes. It came back as the source reads, so the source is kept."""
    assert realign(source, rendered, rendered.replace("\u00a0", " ")) == source


@needs_pandoc
@pytest.mark.parametrize(("source", "rendered", "returned", "expected"), NO_BREAK)
def test_a_no_break_space_prints_as_it_came_back(
    source: str, rendered: str, returned: str, expected: str, tmp_path: Path
) -> None:
    """The artefact: pandoc prints the source as it was as what the test says Word was sent,
    and the merged source as what came back."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text

    def printed(markdown: str, name: str) -> str:
        path = tmp_path / f"{name}.md"
        path.write_text(
            f"[]{{#mg-p-x-0}}{markdown.replace('{{results.x}}', '3.84')}\n", encoding="utf-8"
        )
        subprocess.run(["pandoc", str(path), "-o", str(tmp_path / f"{name}.docx")], check=True)
        return paragraph_text(tmp_path / f"{name}.docx")["mg-p-x-0"]

    assert printed(source, "sent") == rendered
    assert printed(realign(source, rendered, returned), "merged") == returned


@pytest.mark.parametrize(
    ("source", "rendered", "returned"),
    [
        pytest.param(
            "The ratio was *{{results.x}}* in all cases.",
            "The ratio was 3.84 in all cases.",
            "The ratio was 3.84 in most cases.",
            id="italic-after",
        ),
        pytest.param(
            "The ratio was *{{results.x}}* in all cases.",
            "The ratio was 3.84 in all cases.",
            "The odds ratio was 3.84 in all cases.",
            id="italic-before",
        ),
        pytest.param(
            "Run `{{results.v}}` and `{{results.x}}` today.",
            "Run 4.4.1 and 3.84 today.",
            "Run 4.4.1 or 3.84 today.",
            id="code-around-two",
        ),
        pytest.param(
            "Ratio *{{results.x}}* vs *{{results.y}}* here.",
            "Ratio 3.84 vs 7.02 here.",
            "Ratio 3.84 versus 7.02 here.",
            id="italic-around-two",
        ),
    ],
)
def test_a_span_around_a_binding_is_seen_whatever_its_delimiter(
    source: str, rendered: str, returned: str
) -> None:
    """Read one stretch at a time, a lone `*` beside a binding looked like a character, and
    the stretch between two code spans looked like a code span of its own. Read with the
    bindings in place, each is one end of a span around one."""
    from manuscript_guard.roundtrip import align

    aligned = align(source, rendered, returned)
    assert aligned.rebuilt is None
    assert aligned.markup == ("one end of an emphasis or code span",)


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        pytest.param(
            "Costs ranged from US$5–US${{results.hi}} per patient.",
            "Costs ranged from US$5–US$6.3 per patient.",
            "Costs varied from US$5–US$6.3 per patient.",
            r"Costs varied from US\$5–US\${{results.hi}} per patient.",
            id="one-price-bound",
        ),
        pytest.param(
            "The *main **adjusted** ratio* was {{results.x}} in cases.",
            "The main adjusted ratio was 3.84 in cases.",
            "The main fully adjusted ratio was 3.84 in cases.",
            "The main fully adjusted ratio was {{results.x}} in cases.",
            id="bold-inside-italics",
        ),
        pytest.param(
            "Alpha `a*b` and `c*d` beta gamma.",
            "Alpha a*b and c*d beta gamma.",
            "Alpha a*b and c*d beta delta.",
            r"Alpha a\*b and c\*d beta delta.",
            id="code-comes-back-as-text",
        ),
    ],
)
def test_a_stretch_is_read_with_its_neighbours(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    assert realign(source, rendered, returned) == expected


@pytest.mark.parametrize(
    ("returned", "expected"),
    [
        pytest.param("It was 3.84 % in all.", "It was {{results.x}} % in all.", id="space"),
        pytest.param("It was 3.84%* in all.", r"It was {{results.x}}%\* in all.", id="asterisk"),
    ],
)
def test_an_edit_to_spacing_or_an_asterisk_alone_is_merged(returned: str, expected: str) -> None:
    """Each stretch used to be stripped, and its asterisks dropped, before it was compared, so
    these were judged unchanged: the source was kept and the paragraph reported as merged."""
    assert realign("It was {{results.x}}% in all.", "It was 3.84% in all.", returned) == expected


TYPED_IN_WORD = [
    pytest.param("Costs were $x$ low.", r"Costs were \$x\$ low.", id="math"),
    pytest.param("Ask @admin for it.", r"Ask \@admin for it.", id="citation"),
    pytest.param("Use {{results.x}} here.", r"Use \{\{results.x}} here.", id="binding"),
    pytest.param("1990. The year was bad.", r"1990\. The year was bad.", id="list"),
    pytest.param("A *real* change.", r"A \*real\* change.", id="emphasis"),
    pytest.param(
        "Samples <LLOQ in mg/L and >ULOQ were redone.",
        r"Samples \<LLOQ in mg/L and >ULOQ were redone.",
        id="tag-to-pandoc",
    ),
    pytest.param("Ask @2020 or @_user.", r"Ask \@2020 or \@\_user.", id="odd-citation"),
    pytest.param("See [Methods] here.", r"See \[Methods] here.", id="header-reference"),
    pytest.param("Samples ~~5 and $$x$$.", r"Samples \~\~5 and \$\$x\$\$.", id="doubled"),
    pytest.param("``` not a fence", r"\`\`\` not a fence", id="code-fence"),
    pytest.param("::: not a div", r"\::: not a div", id="div-fence"),
    pytest.param(r"Files in C:\temp\new.", r"Files in C:\\temp\\new.", id="backslash"),
    pytest.param(
        "R&D in data@example.org, p < 0.05.", "R&D in data@example.org, p < 0.05.", id="as-is"
    ),
]


@needs_pandoc
@pytest.mark.parametrize(("returned", "expected"), TYPED_IN_WORD)
def test_what_word_typed_prints_as_typed(returned: str, expected: str, tmp_path: Path) -> None:
    """The artefact, not the escaper's opinion of it. The first escaper asked this module's
    reading of Markdown what needed a backslash, and that reading is not pandoc's: typed
    `<LLOQ in mg/L and >` passed its own read-back and was deleted by pandoc."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text

    merged = realign("Costs were low.", "Costs were low.", returned)
    source = tmp_path / "a.md"
    source.write_text(f"# Methods\n\n[]{{#mg-p-x-0}}{merged}\n", encoding="utf-8")
    subprocess.run(["pandoc", str(source), "-o", str(tmp_path / "a.docx")], check=True)
    printed = paragraph_text(tmp_path / "a.docx")["mg-p-x-0"]
    # Pandoc still typesets a typed `--` as a dash; a hyphen is never escaped.
    assert printed.replace("\u2013", "--") == " ".join(returned.split())


BESIDE_A_TOKEN = [
    pytest.param(
        "Alpha beta [@jones2019] gamma delta.",
        "Alpha beta (Jones 2019) gamma delta.",
        "Alpha beta (Jones 2019)(see Table 2) gamma delta.",
        r"Alpha beta [@jones2019]\(see Table 2) gamma delta.",
        id="parenthesis-after-a-citation",
    ),
    pytest.param(
        "Patients took {{results.drug}} daily with water.",
        "Patients took aspirin daily with water.",
        "Patients took <aspirin daily and >placebo.",
        r"Patients took \<{{results.drug}} daily and >placebo.",
        id="angle-before-a-binding",
    ),
    pytest.param(
        "Alpha beta {{results.drug}} gamma delta.",
        "Alpha beta aspirin gamma delta.",
        "Alpha beta {aspirin gamma delta.",
        "Alpha beta &lbrace;{{results.drug}} gamma delta.",
        id="brace-before-a-binding",
    ),
    pytest.param(
        "Alpha beta {{results.drug}} gamma delta.",
        "Alpha beta aspirin gamma delta.",
        "Alpha beta {{aspirin gamma delta.",
        r"Alpha beta \{&lbrace;{{results.drug}} gamma delta.",
        id="two-braces-before-a-binding",
    ),
    pytest.param(
        "Alpha [@jones2019] and {{results.drug}} gamma.",
        "Alpha (Jones 2019) and aspirin gamma.",
        "Alpha (Jones 2019) {aspirin gamma.",
        "Alpha [@jones2019] &lbrace;{{results.drug}} gamma.",
        id="brace-between-a-citation-and-a-binding",
    ),
    pytest.param(
        "HR [{{results.x}}, {{results.y}}] (p=0.01) overall.",
        "HR [3.84, 7.02] (p=0.01) overall.",
        "HR [3.84, 7.02](p=0.01) overall.",
        r"HR [{{results.x}}, {{results.y}}]\(p=0.01) overall.",
        id="parenthesis-after-a-bracket-inside-an-edit",
    ),
    pytest.param(
        "HR [{{results.x}}] {{results.ci}} overall.",
        "HR [3.84] (1.2-3.4) overall.",
        "HR [3.84](1.2-3.4) overall.",
        r"HR [{{results.x}}\]{{results.ci}} overall.",
        id="bracket-before-a-value-that-opens-a-parenthesis",
    ),
]

#: What the build fills each binding in with, and what Word showed for each citation.
BESIDE_VALUES = {
    "results.drug": "aspirin",
    "results.x": "3.84",
    "results.y": "7.02",
    "results.ci": "(1.2-3.4)",
}
BESIDE_CITED = {"(Jones 2019)": "[@jones2019]"}


@pytest.mark.parametrize(("source", "rendered", "returned", "expected"), BESIDE_A_TOKEN)
def test_text_beside_a_token_is_escaped_for_its_neighbour(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """Each stretch was escaped as if it stood alone. `(see Table 2)` typed straight after a
    citation's `]` made a link of it, and the parenthesis became the link's address; a `<`
    before a binding whose value is a word became the start of a tag. A `]` before a value
    that opens with `(` made a link of the value, which `_reads_as` cannot see: it reads a
    binding as digits.

    Two were refused where they could merge. `\\{` before a binding's own `{{` reads as the
    binding `{{{results.drug}}`, which `check` refuses as malformed; and a `](` formed inside
    an edited stretch, its `[` in the stretch before, was a link."""
    assert realign(source, rendered, returned) == expected


@needs_pandoc
@pytest.mark.parametrize(("source", "rendered", "returned", "expected"), BESIDE_A_TOKEN)
def test_text_beside_a_token_prints_as_typed(
    source: str, rendered: str, returned: str, expected: str, tmp_path: Path
) -> None:
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text
    from manuscript_guard.text.placeholders import substitute

    # Each binding filled in as the build fills it; the citation left for pandoc to read,
    # which without a bibliography prints it as it is written.
    merged = realign(source, rendered, returned)
    assert merged is not None, "refused"
    merged = substitute(merged, BESIDE_VALUES)
    path = tmp_path / "a.md"
    path.write_text(f"[]{{#mg-p-x-0}}{merged}\n", encoding="utf-8")
    subprocess.run(["pandoc", str(path), "-o", str(tmp_path / "a.docx")], check=True)
    printed = paragraph_text(tmp_path / "a.docx")["mg-p-x-0"]
    typed = returned
    for shown, cited in BESIDE_CITED.items():
        typed = typed.replace(shown, cited)
    assert printed == typed


@pytest.mark.parametrize(
    "returned", ["Alpha beta {aspirin gamma delta.", "Alpha beta {{aspirin gamma delta."]
)
def test_a_brace_before_a_binding_leaves_check_nothing_to_refuse(returned: str) -> None:
    """The brace must stay out of the binding and put no number into the prose. `\\{` joined
    the binding's braces, and G2 refused `{{{results.drug}}` as malformed; `&#123;` keeps them
    apart, and G2 refused its 123 as a number bound to no source."""
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.placeholders import parse
    from manuscript_guard.text.tokens import find_atoms

    source = "Alpha beta {{results.drug}} gamma delta."
    merged = realign(source, "Alpha beta aspirin gamma delta.", returned)
    assert merged is not None, "refused"
    placeholders, malformed = parse(merged)
    assert [p.raw for p in placeholders] == ["{{results.drug}}"]
    assert malformed == []
    assert find_atoms(merged, mask(merged)) == []


@pytest.mark.parametrize(
    ("source", "rendered", "returned"),
    [
        pytest.param(
            "See [@jones2019], {{results.ci}} here.",
            "See (Jones 2019), (1.2-3.4) here.",
            "See (Jones 2019)(1.2-3.4) here.",
            id="citation-then-value",
        ),
        pytest.param(
            "CI {{results.br}} is {{results.ci}} here.",
            "CI [1.2; 3.4] is (1.2-3.4) here.",
            "CI [1.2; 3.4](1.2-3.4) here.",
            id="value-then-value",
        ),
    ],
)
def test_text_deleted_from_between_two_tokens_is_refused(
    source: str, rendered: str, returned: str
) -> None:
    """Everything between two tokens deleted in Word left nothing to escape, and they merged
    touching: `[@jones2019]{{results.ci}}` printed "See @jones2019 here.", the interval a
    link's address. And two tokens with nothing between them cannot be lined up, so every
    later edit to the paragraph was refused."""
    from manuscript_guard.merge import why
    from manuscript_guard.roundtrip import align

    aligned = align(source, rendered, returned)
    assert aligned.rebuilt is None
    assert aligned.touching
    assert "would touch" in why(aligned)[0]


@pytest.mark.parametrize(
    ("source", "named"),
    [
        ("See [@jones2019], as noted^[A note.] {{results.ci}} here.", "a footnote"),
        ("See [@jones2019], as noted <!-- aside --> {{results.ci}} here.", "an HTML comment"),
    ],
    ids=["footnote", "comment"],
)
def test_markup_deleted_from_between_two_tokens_is_named(source: str, named: str) -> None:
    """The deleted stretch held a footnote, and the refusal said only that the tokens would
    touch: an author who kept a space, as it advised, was refused again for the footnote."""
    from manuscript_guard.merge import why
    from manuscript_guard.roundtrip import align

    rendered = "See (Jones 2019), as noted (1.2-3.4) here."
    aligned = align(source, rendered, "See (Jones 2019)(1.2-3.4) here.")
    assert aligned.rebuilt is None
    assert aligned.markup == (named,)
    assert named in why(aligned)[0]


def test_a_space_left_between_two_tokens_still_merges() -> None:
    """A space keeps them apart for pandoc, so this is a clean edit and merges. The paragraph
    cannot be lined up after it, which DESIGN.md records."""
    out = realign(
        "See [@jones2019], {{results.ci}} here.",
        "See (Jones 2019), (1.2-3.4) here.",
        "See (Jones 2019) (1.2-3.4) here.",
    )
    assert out == "See [@jones2019] {{results.ci}} here."


@pytest.mark.parametrize(("returned", "expected"), TYPED_IN_WORD)
def test_markdown_typed_in_word_goes_back_as_text(returned: str, expected: str) -> None:
    """A co-author types text, not Markdown. Put into the source as it was, `@admin` became a
    citation and `{{results.x}}` a binding - a number the co-author typed, entering the
    manuscript as though the analysis had produced it."""
    source = "Costs were low."
    assert realign(source, source, returned) == expected


def test_an_escape_in_a_stretch_left_alone_is_kept() -> None:
    source = r"The adjusted HR\* {{results.x}} was lower."
    rendered = "The adjusted HR* 3.84 was lower."
    out = realign(source, rendered, "The adjusted HR* 3.84 was much lower.")
    assert out == r"The adjusted HR\* {{results.x}} was much lower."


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        pytest.param(
            "Levels <LOD were imputed as LOD/2 and >ULOQ excluded.",
            "Levels <LOD were imputed as LOD/2 and >ULOQ excluded.",
            "Levels <LOD were imputed as LOD/2 and >ULOQ dropped.",
            r"Levels \<LOD were imputed as LOD/2 and >ULOQ dropped.",
            id="angle-brackets",
        ),
        pytest.param(
            "Levels <LOD (n = {{results.n}}) were imputed as LOD/2 and >ULOQ excluded.",
            "Levels <LOD (n = 56) were imputed as LOD/2 and >ULOQ excluded.",
            "Levels <LOD (n = 56) were imputed as LOD/2 and >ULOQ dropped.",
            "Levels <LOD (n = {{results.n}}) were imputed as LOD/2 and >ULOQ dropped.",
            id="angle-brackets-and-a-binding",
        ),
        pytest.param(
            "Costs ranged from US${{results.lo}} to US${{results.hi}} per patient.",
            "Costs ranged from US$2.1 to US$6.3 per patient.",
            "Costs varied from US$2.1 to US$6.3 per patient.",
            r"Costs varied from US\${{results.lo}} to US${{results.hi}} per patient.",
            id="dollars-and-bindings",
        ),
    ],
)
def test_prose_that_only_looks_like_markup_still_merges(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """Pandoc prints these as text - `<LOD ... LOD/2 and >` is not a tag, and a dollar before
    a number does not close an equation - so reading them as markup refused a clean edit."""
    assert realign(source, rendered, returned) == expected


def test_emphasis_inside_one_stretch_is_only_formatting() -> None:
    """Bold wholly inside an edited stretch is lost with it, which is the known cost - both
    delimiters go, so nothing is left unpaired."""
    source = "The ratio {{results.x}} was **very** high."
    out = realign(source, "The ratio 3.84 was very high.", "The ratio 3.84 was very, very high.")
    assert out == "The ratio {{results.x}} was very, very high."


@pytest.mark.parametrize(
    "source",
    ["As @smith2020 showed, rates rose.", "Rates rose [see @smith2020, p. 4]."],
    ids=["narrative", "prefixed"],
)
def test_a_citation_that_is_not_protected_is_refused_not_flattened(source: str) -> None:
    """Only `[@key]` is a token here, so these read in Word as "Smith (2020)". Rebuilding
    from Word's text turned the citation into that text, and the reference left the
    bibliography. Refused now, because the source does not read as what Word shows."""
    from manuscript_guard.roundtrip import align

    rendered = source.replace("@smith2020", "Smith (2020)").replace("[", "(").replace("]", ")")
    aligned = align(source, rendered, rendered.replace("rose", "climbed"))
    assert aligned.rebuilt is None
    assert aligned.unaligned


def test_an_email_address_is_prose() -> None:
    source = "Write to data@example.org for access."
    out = realign(source, source, "Write to data@example.org for the data.")
    assert out == "Write to data@example.org for the data."


def test_prices_in_dollars_are_prose() -> None:
    """Pandoc's dollar rule, not any pair of dollars: "US$ 5" and "$5 and $10" are text, so
    the source is not refused as an equation. What comes back is escaped all the same."""
    source = "It cost US$ 5, or $5 and $10 elsewhere."
    out = realign(source, source, "It cost US$ 5, or $5 and $10 abroad.")
    assert out == r"It cost US\$ 5, or \$5 and \$10 abroad."


def test_smart_punctuation_alone_does_not_refuse_a_plain_paragraph() -> None:
    """Pandoc curls quotes and turns `--` into a dash. That is typesetting, not something
    lost, and refusing on it would refuse most paragraphs."""
    source = "It's \"fine\" -- here..."
    rendered = "It’s “fine” – here…"
    returned = "It’s “fine” – there…"
    assert realign(source, rendered, returned) == returned


def test_a_paragraph_whose_text_word_does_not_show_is_refused() -> None:
    """The backstop for whatever `_INLINE` does not name. If the source does not read as
    what Word shows, something in it did not reach Word as text, and rebuilding the
    paragraph from Word's text would lose it."""
    from manuscript_guard.roundtrip import align

    aligned = align("Alpha beta gamma.", "Alpha gamma.", "Alpha gamma delta.")
    assert aligned.rebuilt is None
    assert aligned.unaligned


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
        moved = tagged[12]
        assert "Several limitations" in moved
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


def test_a_no_break_space_typed_in_word_is_an_edit(tmp_path: Path) -> None:
    """Compared with its spaces made plain, a paragraph whose only change was a no-break space
    read as untouched, and the co-author's typography was dropped with nothing reported."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    _path, known = source_of(tmp_path, {"a": "Le mot : clair."})
    sent, returned = [Block(("a",), "Le mot : clair.")], [Block(("a",), "Le mot\u00a0: clair.")]
    plan = plan_import(known, sent, returned)
    assert plan.merged == {"a": "Le mot\u00a0: clair."}


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "named"),
    [
        pytest.param(
            "See the note[^missing] for how the cohort was defined.",
            "See the note[^missing] for how the cohort was defined.",
            "See the note for how the cohort was defined.",
            ("a footnote",),
            id="footnote-without-a-definition",
        ),
        pytest.param(
            "See ![Forest plot](nowhere.png) for the estimates.",
            "See Forest plot for the estimates.",
            "See for the estimates.",
            ("an image",),
            id="image-without-a-file",
        ),
        pytest.param(
            "The ratio was {{results.x}} in all adults.[^missing]",
            "The ratio was 3.84 in all adults.[^missing]",
            "The ratio was 3.84 in all adults.",
            ("a footnote",),
            id="after-a-binding",
        ),
        pytest.param(
            "[^missing] The ratio was {{results.x}} in all adults.",
            "[^missing] The ratio was 3.84 in all adults.",
            "The ratio was 3.84 in all adults.",
            ("a footnote",),
            id="before-a-binding",
        ),
    ],
)
def test_an_edit_that_matches_a_wrong_reading_of_the_source_is_refused(
    source: str, rendered: str, returned: str, named: tuple[str, ...]
) -> None:
    """Keeping the source whenever Word's text read as the source does was meant for pandoc's
    no-break space taken out again. But the reading is wrong where pandoc prints as text what
    it takes for markup - a footnote reference with no note, an image with no file - and a
    co-author deleting that text matched the reading: the source was kept, the edit dropped,
    and import said "nothing came back". The reading counts only where it agrees with what
    was sent."""
    from manuscript_guard.roundtrip import align

    aligned = align(source, rendered, returned)
    assert aligned.rebuilt is None
    assert aligned.markup == named


def test_pandocs_no_break_space_taken_out_in_word_is_not_reported(tmp_path: Path) -> None:
    """A paragraph whose only change undoes pandoc's typesetting has nothing to merge, and
    reporting it as merged made a dry run exit 1 asking for an `--apply` that did nothing."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    source = "See *this*, e.g. here."
    _path, known = source_of(tmp_path, {"a": source})
    sent = [Block(("a",), "See this, e.g.\u00a0here.")]
    plan = plan_import(known, sent, [Block(("a",), "See this, e.g. here.")])
    assert plan.empty


def test_word_text_keeps_a_no_break_space_and_collapses_layout(tmp_path: Path) -> None:
    """A tab, a line break and a run of spaces are layout, and read as one space. A no-break
    space is a character somebody chose, and is read as the character it is."""
    from manuscript_guard.docxtext import blocks

    main = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (
        f'<w:document xmlns:w="{main}"><w:body><w:p>'
        '<w:bookmarkStart w:id="0" w:name="mg-p-x-0"/><w:r>'
        '<w:t xml:space="preserve">5\u00a0mg  and\u202f:</w:t><w:tab/>'
        '<w:t xml:space="preserve"> «\u00a0x\u2007y\u00a0» \n end</w:t>'
        "</w:r></w:p></w:body></w:document>"
    )
    document = tmp_path / "a.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", xml)
    assert [b.text for b in blocks(document)] == ["5\u00a0mg and\u202f: «\u00a0x\u2007y\u00a0» end"]


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


# ------------------------------------------- end to end: markup a rewording must not delete


def with_paragraphs(project: Path, *paragraphs: str) -> None:
    """Paragraphs added to the example's Discussion, before the document is built."""
    path = project / "manuscript" / "main.md"
    anchor = "# Data availability"
    extra = "".join(f"{p}\n\n" for p in paragraphs)
    path.write_text(path.read_text(encoding="utf-8").replace(anchor, extra + anchor, 1), "utf-8")


@needs_pandoc
def test_import_keeps_an_inline_comment_and_footnote(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end, the way it was found: a co-author rewords a paragraph carrying an inline
    comment and a footnote. `import --apply` exited 0 and the source lost the comment."""
    from manuscript_guard.cli import main

    paragraph = "Text <!-- keep me --> with a marker^[the footnote] beside it."
    with_paragraphs(project, paragraph)
    returned = edit_docx(built(project), tmp_path / "back.docx", {"beside it.": "near it."})

    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    out = capsys.readouterr().out
    text = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert paragraph in text, "the paragraph, comment and footnote included, is untouched"
    assert "an HTML comment and a footnote" in out, out


@needs_pandoc
def test_import_merges_around_a_footnote_it_can_leave_alone(
    project: Path, tmp_path: Path
) -> None:
    """The refusal costs only the stretch that holds the footnote: an edit on the other side
    of a binding merges, and the footnote stays where it was."""
    from manuscript_guard.cli import main

    with_paragraphs(
        project, "Readers^[an aside] will find a ratio of {{results.ror.point}} in a second look."
    )
    returned = edit_docx(
        built(project), tmp_path / "back.docx", {"in a second look.": "in a closer look."}
    )

    assert main(["import", str(returned), str(project), "--apply"]) == 0
    text = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert (
        "Readers^[an aside] will find a ratio of {{results.ror.point}} in a closer look." in text
    )


@needs_pandoc
def test_import_does_not_flatten_a_narrative_citation(project: Path, tmp_path: Path) -> None:
    """Word shows `@key` as the author and year. Rebuilt from that, the citation became
    plain text, and the reference left the bibliography with nothing reported."""
    from manuscript_guard.cli import main

    paragraph = "As @fictionalClassSignal2019 reported, the signal was plain."
    with_paragraphs(project, paragraph)
    returned = edit_docx(
        built(project), tmp_path / "back.docx", {"the signal was plain.": "the signal was clear."}
    )

    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert paragraph in (project / "manuscript" / "main.md").read_text(encoding="utf-8")


# -------------------------------------------- end to end: a no-break space comes back as typed


@needs_pandoc
@pytest.mark.parametrize(
    ("paragraph", "was", "now", "expected"),
    [
        pytest.param(
            "Patients received {{results.ror.point}}\u00a0mg daily in the first week.",
            "in the first week.",
            "in the second week.",
            "Patients received {{results.ror.point}}\u00a0mg daily in the second week.",
            id="dose",
        ),
        pytest.param(
            "Le rapport vaut {{results.ror.point}}\u00a0: «\u202fnet\u202f» selon nous.",
            "selon nous.",
            "à notre avis.",
            "Le rapport vaut {{results.ror.point}}\u00a0: «\u202fnet\u202f» à notre avis.",
            id="french-beside-a-binding",
        ),
        pytest.param(
            "Le mot : clair dans le texte.",
            "Le mot : clair",
            "Le mot\u00a0: clair",
            "Le mot\u00a0: clair dans le texte.",
            id="typed-in-word",
        ),
        pytest.param(
            "As Smith et al. reported, e.g. in {{results.ror.point}} of such cohorts.",
            "of such cohorts.",
            "of most such cohorts.",
            "As Smith et al. reported, e.g. in {{results.ror.point}} of most such cohorts.",
            id="pandoc-abbreviation",
        ),
    ],
)
def test_import_carries_a_no_break_space(
    project: Path, tmp_path: Path, paragraph: str, was: str, now: str, expected: str
) -> None:
    """End to end, the way it was found: a paragraph with "5 mg" or a French "mot :" is
    reworded in Word, and `import --apply` refused it, because Word's text was read with the
    no-break space made plain and merging would have lost it."""
    from manuscript_guard.cli import main

    with_paragraphs(project, paragraph)
    returned = edit_docx(built(project), tmp_path / "back.docx", {was: now})

    assert main(["import", str(returned), str(project), "--apply"]) == 0
    assert expected in (project / "manuscript" / "main.md").read_text(encoding="utf-8")


@needs_pandoc
def test_import_does_not_drop_an_edit_to_text_the_reading_hides(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end, the way the review found it: `[^missing]` prints as text, the co-author
    deletes it, and import exited 0 with "nothing came back"."""
    from manuscript_guard.cli import main

    paragraph = "See the note[^missing] for how the cohort was defined."
    with_paragraphs(project, paragraph)
    returned = edit_docx(built(project), tmp_path / "back.docx", {"note[^missing]": "note"})

    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert "a footnote" in capsys.readouterr().out
    assert paragraph in (project / "manuscript" / "main.md").read_text(encoding="utf-8")


@needs_pandoc
def test_import_leaves_a_link_definition_where_it_was(project: Path, tmp_path: Path) -> None:
    """A definition has no identifier and reaches Word as nothing, so `import` never splices
    into it: a rewording of the paragraph after it merges into that paragraph alone, and the
    next build still links."""
    from manuscript_guard.cli import main

    definition = f"[reg]: {REGISTRY}"
    with_paragraphs(project, "See [the registry][reg] for details.", definition, "It is public.")
    returned = edit_docx(built(project), tmp_path / "back.docx", {"It is public.": "It is open."})

    assert main(["import", str(returned), str(project), "--apply"]) == 0
    text = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert f"for details.\n\n{definition}\n\nIt is open.\n" in text
    assert f'Target="{REGISTRY}"' in _docx_part(built(project), "word/_rels/document.xml.rels")


@needs_pandoc
@pytest.mark.parametrize(
    ("paragraph", "was", "now"),
    [
        pytest.param(
            "[Note]: patients (all adults) were enrolled.",
            "enrolled.",
            "recruited.",
            id="words-after-title",
        ),
        pytest.param(
            "[Box 1]: Definitions. Injury was an ALT above three times\n"
            "the upper limit of normal.",
            "limit of normal.",
            "limit of normal (ULN).",
            id="first-line-swallowed",
        ),
        # Not `[Methods]`: the example has that heading, and `[Methods]` is a link to it.
        pytest.param("[Aim]: to estimate the risk.", "the risk.", "its risk.", id="swallowed"),
    ],
)
def test_import_merges_prose_that_only_opens_like_a_definition(
    project: Path, tmp_path: Path, paragraph: str, was: str, now: str
) -> None:
    """End to end, the way two rounds of review found it. Each of these was taken for a
    definition and left without an identifier - where pandoc prints it, or would print the
    lines under the first - and a co-author's edit to it was dropped while `import` said
    nothing came back."""
    from manuscript_guard.cli import main

    with_paragraphs(project, paragraph)
    returned = edit_docx(built(project), tmp_path / "back.docx", {was: now})

    assert main(["import", str(returned), str(project), "--apply"]) == 0
    assert now in (project / "manuscript" / "main.md").read_text(encoding="utf-8")
