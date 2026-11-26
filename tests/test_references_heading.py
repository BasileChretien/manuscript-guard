"""The reference list of the Word document comes under a heading.

pandoc's citeproc puts the list where the manuscript writes `::: {#refs}`, or at the end, and
gives it no heading of its own where the manuscript has a `refs` div; a live build's
bibliography field goes in the same place. A manuscript that ended with its declarations
built into a document whose references read as part of the last statement: the
bisphosphonates paper's Contributors, funding and competing interests, 2026-11-26. The
heading is "References", or what the journal's profile names under `references.heading`, and
none is added where the author wrote one (`build/references_heading.lua`).
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.build import LIVE, OFFLINE, PLAIN, assemble, build_document
from manuscript_guard.build import document as builder
from manuscript_guard.contracts import load_namespace, load_project

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

MODES = (OFFLINE, LIVE, PLAIN)


def _stub_zotero_lua(tmp_path: Path, monkeypatch) -> None:
    """Better BibTeX's zotero.lua asks the running Zotero; a filter that does nothing stands
    in for it, so that the live build's other filters run as they do on a real one."""
    stub = tmp_path / "zotero.lua"
    stub.write_text("return {}\n", encoding="utf-8")
    monkeypatch.setattr(builder, "ensure_zotero_lua", lambda _cache: stub)


def _paragraphs(path: Path) -> list[tuple[str, str]]:
    """Each paragraph of the document as (style, text); a field's paragraph is "FIELD"."""
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    out = []
    for paragraph in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        style = re.search(r'<w:pStyle w:val="([^"]+)"', paragraph)
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph, re.S))
        named = style.group(1) if style else ""
        out.append(("FIELD" if "ZOTERO_BIBL" in paragraph else named, text))
    return out


def _built(project: Path, mode: str, *, supplementary: bool = False) -> list[tuple[str, str]]:
    proj, _ = load_project(project)
    namespace, results, _lit, _ = load_namespace(proj)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok, report.render(project)
    result = build_document(proj, assembled, mode=mode, supplementary=supplementary)
    return _paragraphs(result.output)


def _list_starts(paragraphs: list[tuple[str, str]]) -> int:
    """Where the reference list begins: the bibliography field, or citeproc's first entry."""
    for index, (style, _text) in enumerate(paragraphs):
        if style in ("FIELD", "Bibliography"):
            return index
    raise AssertionError(f"no reference list in {paragraphs}")


def _headings(paragraphs: list[tuple[str, str]]) -> list[str]:
    return [text for style, text in paragraphs if style.startswith("Heading")]


def _with_main(project: Path, old: str, new: str) -> None:
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


@needs_pandoc
@pytest.mark.parametrize("mode", MODES)
def test_the_reference_list_comes_under_a_references_heading(
    project: Path, mode: str, tmp_path: Path, monkeypatch
) -> None:
    _stub_zotero_lua(tmp_path, monkeypatch)
    paragraphs = _built(project, mode)
    start = _list_starts(paragraphs)
    assert paragraphs[start - 1] == ("Heading1", "References"), paragraphs[start - 3 : start + 1]
    assert _headings(paragraphs).count("References") == 1


@needs_pandoc
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "ending, heading",
    [
        ("\n# References\n", "References"),
        # pandoc reads the comment as a block of HTML, which the document does not print.
        ("\n# References\n\n<!-- the list is filled in by the build -->\n", "References"),
        ("\n# Literature cited\n\nThe works are listed in order of citation.\n\n"
         "::: {#refs}\n:::\n", "Literature cited"),
        ("\n# Bibliography\n\n::: {#refs}\n:::\n", "Bibliography"),
        ("\n# 7. References\n\n::: {#refs}\n:::\n\n# Appendix\n\nMore.\n", "7. References"),
    ],  # fmt: skip
)
def test_an_authors_own_heading_over_the_list_is_the_only_one(
    project: Path, mode: str, ending: str, heading: str, tmp_path: Path, monkeypatch
) -> None:
    _stub_zotero_lua(tmp_path, monkeypatch)
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + ending, encoding="utf-8", newline="\n")
    paragraphs = _built(project, mode)
    headings = _headings(paragraphs)
    assert heading in headings
    assert "References" not in [h for h in headings if h != heading], headings
    assert _headings(paragraphs[: _list_starts(paragraphs)])[-1] == heading


@needs_pandoc
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("label", ["References", "Literaturverzeichnis", "References and notes"])
@pytest.mark.parametrize("div", ["\n::: {#refs}\n:::\n", ""], ids=["div", "no div"])
def test_a_list_under_a_bold_label_gets_no_heading(
    project: Path, mode: str, label: str, div: str, tmp_path: Path, monkeypatch
) -> None:
    """A paper brought in from Word heads its list with a paragraph in bold, of whatever
    words, as a heading heads it whatever its words: before the `refs` div, or last where the
    list is put at the end."""
    _stub_zotero_lua(tmp_path, monkeypatch)
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8") + f"\n**{label}**\n{div}"
    path.write_text(text, encoding="utf-8", newline="\n")
    paragraphs = _built(project, mode)
    start = _list_starts(paragraphs)
    assert paragraphs[start - 1][1] == label
    assert "References" not in _headings(paragraphs)


@needs_pandoc
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("after", ["", "\n<!-- the list is filled in by the build -->\n"],
                         ids=["bare", "comment"])  # fmt: skip
def test_an_empty_reference_heading_before_later_files_takes_the_list(
    project: Path, mode: str, after: str, tmp_path: Path, monkeypatch
) -> None:
    """With no `refs` div, citeproc and the bibliography field go at the end of the document,
    after every file printed after main.md: an author's heading of the list with nothing under
    it, wherever it stands, is where the list goes, and no heading is added."""
    _stub_zotero_lua(tmp_path, monkeypatch)
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8") + "\n# References\n" + after
    path.write_text(text, encoding="utf-8", newline="\n")
    (project / "manuscript" / "zz_appendix.md").write_text(
        "# Appendix\n\nMore of the work.\n", encoding="utf-8", newline="\n"
    )
    paragraphs = _built(project, mode)
    start = _list_starts(paragraphs)
    assert _headings(paragraphs).count("References") == 1
    assert _headings(paragraphs[:start])[-1] == "References"
    assert "Appendix" in _headings(paragraphs[start:])


@needs_pandoc
@pytest.mark.parametrize(
    "heading", ["7.1 References", "6.2. References", "A. References", "VI. References",
                "(7) References", "7) References", "iv) Bibliography"],
)  # fmt: skip
def test_a_numbered_heading_of_the_list_is_read_by_its_words(
    project: Path, heading: str
) -> None:
    """The section the list stands in is a reference list's however its heading is numbered."""
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8") + (
        f"\n# {heading}\n\nIn the order they are cited.\n\n::: {{#refs}}\n:::\n"
    )
    path.write_text(text, encoding="utf-8", newline="\n")
    paragraphs = _built(project, OFFLINE)
    headings = _headings(paragraphs)
    assert _headings(paragraphs[: _list_starts(paragraphs)])[-1] == heading
    assert "References" not in headings


@needs_pandoc
@pytest.mark.parametrize("mode", MODES)
def test_a_list_under_another_heading_gets_its_own(
    project: Path, mode: str, tmp_path: Path, monkeypatch
) -> None:
    """A `refs` div with prose before it in a section of another name is not headed by that
    section's heading."""
    _stub_zotero_lua(tmp_path, monkeypatch)
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8") + "\nThe last words.\n\n::: {#refs}\n:::\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    paragraphs = _built(project, mode)
    start = _list_starts(paragraphs)
    assert paragraphs[start - 1] == ("Heading1", "References")


@needs_pandoc
@pytest.mark.parametrize("mode", MODES)
def test_a_list_inside_another_block_gets_no_heading(
    project: Path, mode: str, tmp_path: Path, monkeypatch
) -> None:
    """Known gaps: a `refs` div inside another block is the author's arrangement."""
    _stub_zotero_lua(tmp_path, monkeypatch)
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8") + "\n:::: {.endmatter}\n::: {#refs}\n:::\n::::\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    paragraphs = _built(project, mode)
    _list_starts(paragraphs)
    assert "References" not in _headings(paragraphs)


@needs_pandoc
@pytest.mark.parametrize("mode", MODES)
def test_a_document_that_cites_nothing_has_no_references_heading(
    project: Path, mode: str, tmp_path: Path, monkeypatch
) -> None:
    _stub_zotero_lua(tmp_path, monkeypatch)
    supplement = project / "manuscript" / "supplementary"
    assert not any("@" in p.read_text(encoding="utf-8") for p in supplement.glob("*.md"))
    paragraphs = _built(project, mode, supplementary=True)
    assert "References" not in _headings(paragraphs)


@needs_pandoc
@pytest.mark.parametrize("mode", MODES)
def test_the_supplements_reference_list_comes_under_a_heading(
    project: Path, mode: str, tmp_path: Path, monkeypatch
) -> None:
    _stub_zotero_lua(tmp_path, monkeypatch)
    first = sorted((project / "manuscript" / "supplementary").glob("*.md"))[0]
    first.write_text(
        first.read_text(encoding="utf-8") + "\nAs described before [@fictionalClassSignal2019].\n",
        encoding="utf-8",
        newline="\n",
    )
    paragraphs = _built(project, mode, supplementary=True)
    start = _list_starts(paragraphs)
    assert paragraphs[start - 1] == ("Heading1", "References")


@needs_pandoc
@pytest.mark.parametrize("mode", MODES)
def test_the_journal_profile_names_the_heading(
    project: Path, mode: str, tmp_path: Path, monkeypatch
) -> None:
    _stub_zotero_lua(tmp_path, monkeypatch)
    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    text = profile.read_text(encoding="utf-8")
    assert 'references:\n  style_name: "Vancouver"' in text
    profile.write_text(
        text.replace('references:\n  style_name: "Vancouver"',
                     'references:\n  heading: "Literature & notes"\n  style_name: "Vancouver"'),
        encoding="utf-8",
        newline="\n",
    )  # fmt: skip
    paragraphs = _built(project, mode)
    start = _list_starts(paragraphs)
    assert paragraphs[start - 1] == ("Heading1", "Literature &amp; notes")
    assert "References" not in _headings(paragraphs)


def test_the_profiles_heading_is_the_one_the_build_uses(project: Path) -> None:
    proj, _ = load_project(project)
    assert builder.references_heading(proj) == "References"
    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    text = profile.read_text(encoding="utf-8").replace(
        'references:\n  style_name: "Vancouver"',
        'references:\n  heading: "  Reference list "\n  style_name: "Vancouver"',
    )
    profile.write_text(text, encoding="utf-8", newline="\n")
    proj, _ = load_project(project)
    assert builder.references_heading(proj) == "Reference list"


def test_a_profile_with_a_heading_is_valid(project: Path) -> None:
    from manuscript_guard.contracts._schema import read_structured, validate

    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    text = profile.read_text(encoding="utf-8").replace(
        'references:\n  style_name: "Vancouver"',
        'references:\n  heading: "References"\n  style_name: "Vancouver"',
    )
    profile.write_text(text, encoding="utf-8", newline="\n")
    report = validate(read_structured(profile), "journal", profile)
    assert report.ok, report.render(project)


# ---------------------------------------------------------------- the round trip


def _returned(project: Path, tmp_path: Path, replacements: dict[str, str] | None = None) -> Path:
    built = project / "build" / "manuscript.docx"
    target = tmp_path / "back.docx"
    shutil.copy(built, target)
    if replacements:
        scratch = tmp_path / "back.t.docx"
        with zipfile.ZipFile(target) as zin, zipfile.ZipFile(scratch, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    xml = data.decode("utf-8")
                    for was, now in replacements.items():
                        assert was in xml
                        xml = xml.replace(was, now)
                    data = xml.encode("utf-8")
                zout.writestr(item, data)
        scratch.replace(target)
    return target


@needs_pandoc
def test_a_document_with_the_heading_comes_back_with_no_edit(
    project: Path, tmp_path: Path, capsys
) -> None:
    """`import` compares the returned document with a build of the source, which has the
    heading too: it is no edit, and nothing is written."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    before = source.read_bytes()
    assert main(["build", str(project), "--offline"]) == 0
    capsys.readouterr()
    assert main(["import", str(_returned(project, tmp_path)), str(project), "--apply"]) == 0
    said = capsys.readouterr().out
    assert "References" not in said, said
    assert source.read_bytes() == before


@needs_pandoc
def test_a_document_built_before_the_heading_comes_back_with_no_edit(
    project: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    """A document a co-author holds from an earlier release has no heading over its list,
    and the build compared with now has one: the heading is the build's, never the source's,
    and nothing is written."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    before = source.read_bytes()
    with monkeypatch.context() as patched:
        patched.setattr(builder, "_references_filter", lambda _project: [])
        assert main(["build", str(project), "--offline"]) == 0
    assert "References" not in _headings(_paragraphs(project / "build" / "manuscript.docx"))
    capsys.readouterr()
    assert main(["import", str(_returned(project, tmp_path)), str(project), "--apply"]) == 0
    said = capsys.readouterr().out
    assert "References" not in said, said
    assert source.read_bytes() == before


@needs_pandoc
@pytest.mark.parametrize("typed", ["Reference list", "References (to be updated)"])
def test_the_heading_changed_in_word_is_said_and_not_written_into_the_source(
    project: Path, tmp_path: Path, capsys, typed: str
) -> None:
    """The heading is no paragraph of the source, so what a co-author types into it has
    nowhere to go: it is not merged as text, and import says so, and where the heading's
    words come from."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    before = source.read_bytes()
    assert main(["build", str(project), "--offline"]) == 0
    returned = _returned(project, tmp_path, {">References<": f">{typed}<"})
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    said = capsys.readouterr().out
    assert f'came back as "{typed}"' in said, said
    assert "nothing of it is applied" in said and "references.heading" in said, said
    assert source.read_bytes() == before


@needs_pandoc
@pytest.mark.parametrize("form", ["tracked", "highlighted"])
def test_the_marked_up_copy_does_not_mark_the_builds_heading(
    project: Path, tmp_path: Path, monkeypatch, form: str
) -> None:
    """The copy marked against a document the journal received, built before the heading,
    shows nothing inserted: the heading is the build's, and is kept in the copy as it is."""
    from manuscript_guard.markedup import write

    proj, _ = load_project(project)
    namespace, results, _lit, _ = load_namespace(proj)
    assembled, _ = assemble(proj, namespace, results)
    old, new = tmp_path / "received.docx", tmp_path / "revision.docx"
    with monkeypatch.context() as patched:
        patched.setattr(builder, "_references_filter", lambda _project: [])
        build_document(proj, assembled, mode=OFFLINE, output=old, stamp=False)
    build_document(proj, assembled, mode=OFFLINE, output=new, stamp=False)
    assert "References" not in _headings(_paragraphs(old))
    made = write(old, new, tmp_path / "marked.docx", date="2026-11-26", form=form)
    assert "blocks inserted" not in made.counts, made.counts
    xml = zipfile.ZipFile(made.path).read("word/document.xml").decode("utf-8")
    heading = next(p for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
                   if 'w:name="mg-references"' in p)  # fmt: skip
    assert "References" in "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", heading, re.S))
    assert "<w:ins " not in heading and "w:highlight" not in heading, heading


def test_the_builds_heading_is_not_read_back(tmp_path: Path) -> None:
    """`docxtext.blocks` passes over the paragraph that carries the heading's bookmark, and
    reads a heading of the same words without it."""
    from manuscript_guard.docxtext import BUILT_HEADING, blocks

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def paragraph(text: str, bookmark: str | None = None) -> str:
        mark = (f'<w:bookmarkStart w:id="1" w:name="{bookmark}"/>' if bookmark else "")
        end = '<w:bookmarkEnd w:id="1"/>' if bookmark else ""
        return f"<w:p>{mark}<w:r><w:t>{text}</w:t></w:r>{end}</w:p>"

    def write(document: Path, body: str) -> Path:
        with zipfile.ZipFile(document, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                'package/2006/content-types"><Default Extension="xml" '
                'ContentType="application/xml"/></Types>',
            )
            archive.writestr(
                "word/document.xml",
                f'<?xml version="1.0"?><w:document {w}><w:body>{body}</w:body></w:document>',
            )
        return document

    body = (paragraph("Last words.") + paragraph("References", BUILT_HEADING)
            + paragraph("1. Doe J. 2019."))  # fmt: skip
    read = [b.text for b in blocks(write(tmp_path / "built.docx", body))]
    assert read == ["Last words.", "1. Doe J. 2019."]
    plain = body.replace(BUILT_HEADING, "_Ref1")
    read = [b.text for b in blocks(write(tmp_path / "typed.docx", plain))]
    assert read == ["Last words.", "References", "1. Doe J. 2019."]
