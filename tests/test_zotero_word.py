"""The live build's Word half: Zotero's bibliography field and document preferences.

Better BibTeX's zotero.lua gives a Word document live citations and nothing else: no
`ADDIN ZOTERO_BIBL` field and no ZOTERO_PREF document properties, both of which it writes for
LibreOffice only. An author opening the build in Word found no reference list to update and
a style dialog on the first Refresh. `build/zotero_word.lua` adds both. Checked by hand in
Word 16 with Zotero 9.0.6 on a 57-reference manuscript: Refresh formatted every citation in
the preset style without a dialog, filled the bibliography under the References heading, and
Add/Edit Citation opened on the document.

Also here: the source stamp used to replace the .docx's custom properties whole, erasing the
Zotero preferences after they were written, and a paragraph marker in front of `:::` turned
the `refs` div into literal text.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.build.document import ZOTERO_WORD_LUA, _front_matter
from manuscript_guard.contracts import load_project
from manuscript_guard.roundtrip import stamp_into, stamp_of, tag

PANDOC = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(PANDOC is None, reason="pandoc is not installed")

HEADER = (
    '---\ntitle: "T"\nzotero:\n  client: zotero\n'
    'zotero-word:\n  style: "http://www.zotero.org/styles/apa"\n  locale: en-GB\n'
    '  zotero-version: "9.0.6"\n---\n\n'
)


def run_filter(tmp_path: Path, markdown: str) -> zipfile.ZipFile:
    source = tmp_path / "m.md"
    source.write_text(markdown, encoding="utf-8")
    output = tmp_path / "m.docx"
    subprocess.run(
        [PANDOC, "--standalone", str(source), "-o", str(output), f"--lua-filter={ZOTERO_WORD_LUA}"],
        check=True,
        capture_output=True,
    )
    return zipfile.ZipFile(output)


def custom_properties(archive: zipfile.ZipFile) -> str:
    if "docProps/custom.xml" not in archive.namelist():
        return ""
    return archive.read("docProps/custom.xml").decode("utf-8")


def zotero_prefs(properties: str) -> list[str]:
    return [
        html.unescape(value)
        for value in re.findall(
            r'name="ZOTERO_PREF_\d+"[^>]*>\s*<vt:lpwstr>(.*?)</vt:lpwstr>', properties, re.S
        )
    ]


# ---------------------------------------------------------------- the filter


@needs_pandoc
def test_the_bibliography_field_goes_where_the_manuscript_puts_refs(tmp_path: Path) -> None:
    body = "# Body\n\nText.\n\n# References\n\n::: {#refs}\n:::\n\n# Appendix\n\nMore.\n"
    xml = run_filter(tmp_path, HEADER + body).read("word/document.xml").decode("utf-8")
    assert xml.count("ADDIN ZOTERO_BIBL") == 1
    assert xml.index("References") < xml.index("ZOTERO_BIBL") < xml.index("Appendix")
    assert "CSL_BIBLIOGRAPHY" in xml


@needs_pandoc
def test_without_a_refs_div_the_bibliography_goes_at_the_end(tmp_path: Path) -> None:
    xml = run_filter(tmp_path, HEADER + "# Body\n\nThe last paragraph.\n").read(
        "word/document.xml"
    )
    text = xml.decode("utf-8")
    assert text.index("The last paragraph") < text.index("ZOTERO_BIBL")


@needs_pandoc
def test_the_style_is_written_where_words_zotero_plugin_reads_it(tmp_path: Path) -> None:
    properties = custom_properties(run_filter(tmp_path, HEADER + "Text.\n"))
    chunks = zotero_prefs(properties)
    assert chunks, "no ZOTERO_PREF property"
    assert all(len(chunk) <= 255 for chunk in chunks), "Word keeps at most 255 per property"
    prefs = "".join(chunks)
    assert '<style id="http://www.zotero.org/styles/apa" locale="en-GB"' in prefs
    assert '<pref name="fieldType" value="Field"/>' in prefs
    assert 'zotero-version="9.0.6"' in prefs
    # The filter's own settings do not linger as properties of their own.
    assert not re.search(r'name="zotero(-word)?"', properties)


@needs_pandoc
def test_without_a_style_zotero_asks_as_it_does_for_any_document(tmp_path: Path) -> None:
    archive = run_filter(tmp_path, '---\ntitle: "T"\nzotero-word: {}\n---\n\nText.\n')
    assert not zotero_prefs(custom_properties(archive))
    assert "ZOTERO_BIBL" in archive.read("word/document.xml").decode("utf-8")


def test_the_live_front_matter_names_the_journals_zotero_style(project: Path, monkeypatch) -> None:
    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace(
            'style_name: "Vancouver"', 'style_name: "Vancouver"\n  csl: vancouver'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("manuscript_guard.build.document._zotero_version", lambda: "9.0.6")
    proj, _ = load_project(project)
    live = _front_matter(proj, live=True)
    assert 'style: "http://www.zotero.org/styles/vancouver"' in live
    assert 'zotero-version: "9.0.6"' in live
    assert "zotero-word" not in _front_matter(proj, live=False)


# ---------------------------------------------------------------- the stamp


def minimal_docx(path: Path, custom: str | None) -> Path:
    types = (
        '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
        'package/2006/content-types"></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
        'openxmlformats.org/package/2006/relationships"></Relationships>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", "<w:document/>")
        if custom is not None:
            archive.writestr("docProps/custom.xml", custom)
    return path


def test_stamping_keeps_the_documents_other_custom_properties(tmp_path: Path) -> None:
    existing = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
        'custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/'
        'docPropsVTypes">'
        '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="ZOTERO_PREF_1">'
        "<vt:lpwstr>&lt;data data-version=&quot;3&quot;/&gt;</vt:lpwstr></property>"
        "</Properties>"
    )
    document = minimal_docx(tmp_path / "d.docx", existing)
    stamp_into(document, "a" * 64)
    stamp_into(document, "b" * 64)  # a rebuild re-stamps; it must not stack stamps

    properties = zipfile.ZipFile(document).read("docProps/custom.xml").decode("utf-8")
    names = re.findall(r'name="([^"]+)"', properties)
    assert sorted(names) == ["ZOTERO_PREF_1", "manuscript-guard-source"]
    pids = re.findall(r'pid="(\d+)"', properties)
    assert len(pids) == len(set(pids)) and min(map(int, pids)) == 2
    assert stamp_of(document) == "b" * 64


def test_a_document_without_custom_properties_is_stamped_as_before(tmp_path: Path) -> None:
    document = minimal_docx(tmp_path / "d.docx", None)
    stamp_into(document, "c" * 64)
    assert stamp_of(document) == "c" * 64
    archive = zipfile.ZipFile(document)
    assert "custom.xml" in archive.read("[Content_Types].xml").decode("utf-8")


# ---------------------------------------------------------------- paragraph markers


def test_a_fence_is_not_marked_as_a_paragraph() -> None:
    text = "A paragraph.\n\n::: {#refs}\n:::\n\n```\ncode\n```\n\nAnother paragraph.\n"
    tagged = tag(text, "main.md")
    assert not re.search(r"\[\]\{#mg-p-[^}]+\}(:::|```)", tagged), "a marker landed on a fence"
    assert tagged.count("[]{#mg-p-") == 2, "the two prose paragraphs keep their markers"
