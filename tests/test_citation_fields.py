"""A Zotero citation field known by what its code cites, and read in place of its words."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.citationfields import citation_of
from manuscript_guard.docxtext import blocks


def _code(items: list[dict], **extra) -> str:
    data = {"citationID": "abc", "properties": {"formattedCitation": "(A 2020)"},
            "citationItems": items, **extra}  # fmt: skip
    return " ADDIN ZOTERO_ITEM CSL_CITATION " + json.dumps(data) + "   "


ITEM = {"id": 7, "uris": ["http://zotero.org/users/local/a1b2/items/ABCD1234"],
        "itemData": {"title": "Hepatic injury"}}  # fmt: skip


def test_a_citation_is_known_by_its_items_and_their_locators() -> None:
    found = citation_of(_code([ITEM]))
    assert found is not None and found.formatted == "(A 2020)"
    assert json.loads(found.identity) == [{"items": ["ABCD1234"]}]
    with_page = citation_of(_code([{**ITEM, "locator": "33", "label": "page"}]))
    assert with_page is not None and with_page.identity != found.identity


@pytest.mark.parametrize(
    "refreshed",
    [
        # A library synced since: Zotero writes its URI anew, and the key stays.
        {**ITEM, "uris": ["http://zotero.org/users/123/items/ABCD1234"]},
        # Written by Zotero before 5.
        {"uri": ["http://zotero.org/users/1/items/ABCD1234"]},
        # Another machine's item ID, and the item's data brought up to date.
        {**ITEM, "id": 99, "itemData": {"title": "Hepatic injury, corrected"}},
    ],
)
def test_what_a_refresh_or_a_sync_changes_is_not_what_is_cited(refreshed: dict) -> None:
    before, after = citation_of(_code([ITEM])), citation_of(_code([refreshed], citationID="z"))
    assert before is not None and after is not None and before.identity == after.identity


@pytest.mark.parametrize(
    "code",
    [
        " PAGE ",
        " ADDIN ZOTERO_BIBL {} CSL_BIBLIOGRAPHY ",
        " ADDIN ZOTERO_ITEM CSL_CITATION {not json} ",
        " ADDIN ZOTERO_ITEM CSL_CITATION [] ",
        _code([]),
        _code(["a"]),
        _code([{"id": 1}]),
        _code([{"uris": [3]}]),
    ],
)
def test_a_code_that_is_not_a_readable_citation_is_none(code: str) -> None:
    assert citation_of(code) is None


# ------------------------------------------------------------------ the reading

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx(folder: Path, body: str) -> Path:
    path = folder / "doc.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        document = f"<w:document {W}><w:body>{body}</w:body></w:document>"
        archive.writestr("word/document.xml", document)
    return path


def _field(code: str, shown: str) -> str:
    half = len(code) // 2
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f"<w:r><w:instrText>{code[:half]}</w:instrText></w:r>"
        f"<w:r><w:instrText>{code[half:]}</w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"{shown}"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def _run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def _read(folder: Path, inside: str, fields=None) -> str:
    mark = '<w:bookmarkStart w:id="0" w:name="mg-p-a-1"/><w:bookmarkEnd w:id="0"/>'
    body = f"<w:p>{mark}{inside}</w:p>"
    return blocks(_docx(folder, body), fields=fields)[0].text


def test_a_field_is_read_by_its_code_where_the_reading_knows_it(tmp_path: Path) -> None:
    inside = _run("As shown ") + _field("CODE", _run("[2]")) + _run(".")
    assert _read(tmp_path, inside) == "As shown [2]."
    seen: list[str] = []

    def known(code: str) -> str | None:
        seen.append(code)
        return "[@a]" if code == "CODE" else None

    assert _read(tmp_path, inside, known) == "As shown [@a]."
    assert seen == ["CODE"], "the code is read whole, across every instrText run"
    assert _read(tmp_path, inside, lambda code: None) == "As shown [2]."


def test_nothing_shown_in_a_field_read_by_its_code_is_read(tmp_path: Path) -> None:
    """Its words, whatever they hold: another field, an insertion tracked in them."""
    shown = (
        _run("[")
        + _field("INNER", _run("2"))
        + '<w:ins w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z">'
        + _run(", 3")
        + "</w:ins>"
        + _run("]")
    )
    inside = _field("CODE", shown) + _run(" after")
    assert _read(tmp_path, inside, lambda code: "[@a]" if code == "CODE" else "x") == "[@a] after"


def test_a_field_deleted_in_word_is_not_read(tmp_path: Path) -> None:
    deleted = (
        '<w:del w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z">'
        + _field("CODE", _run("[2]"))
        + "</w:del>"
    )
    assert _read(tmp_path, _run("Before") + deleted + _run(" after"), lambda c: "[@a]") == (
        "Before after"
    )


# ------------------------------------------------------------- a citation inserted in Word


@pytest.mark.parametrize(
    ("code", "named"),
    [
        (_code([ITEM]), ["Hepatic injury"]),
        (" ADDIN CSL_CITATION " + json.dumps({"citationItems": [{"itemData": {
            "author": [{"literal": "WHO"}], "issued": {"raw": "2019-05"}, "title": "T"}}]}),
         ['WHO 2019, "T"']),
        (" ADDIN ZOTERO_ITEM CSL_CITATION {not json} ", ["a work it does not name"]),
        (" ADDIN EN.CITE &lt;EndNote&gt;&lt;Cite&gt;&lt;Author&gt;Smith, J&lt;/Author&gt;"
         "&lt;Year&gt;2020&lt;/Year&gt;&lt;/Cite&gt;&lt;/EndNote&gt;", ["Smith 2020"]),
        (" ADDIN EN.CITE.DATA ", ["a work it does not name"]),
        ("MENDELEY_CITATION_v3_not-base64!", ["a work it does not name"]),
    ],
)  # fmt: skip
def test_a_citation_inserted_in_word_names_what_it_can(code: str, named: list[str]) -> None:
    from manuscript_guard.citationfields import inserted

    works = inserted(code)
    assert works is not None
    shown = [str(work) for work in works]
    assert all(any(part in said for said in shown) for part in named), shown


@pytest.mark.parametrize("code", [" PAGE ", " HYPERLINK \"https://example.org\" ", "a tag"])
def test_a_field_or_tag_that_is_no_citation_is_none(code: str) -> None:
    from manuscript_guard.citationfields import inserted

    assert inserted(code) is None


@pytest.mark.parametrize(
    ("work", "fields", "key"),
    [
        ({"title": "COVID-19\u30ef\u30af\u30c1\u30f3\u63a5\u7a2e\u5f8c\u306e\u5fc3\u7b4b\u708e"},
         {"title": "COVID-19\u60a3\u8005\u306b\u304a\u3051\u308b\u7814\u7a76"}, None),
        ({"title": "Editorial", "year": "2021", "author": "Smith"},
         {"title": "{Editorial}", "year": "2019", "author": "Smith, J"}, None),
        ({"title": "Editorial", "year": "2021", "author": "Smith"},
         {"title": "{Editorial}", "year": "2021", "author": "Jones, A and Smith, J"}, None),
        ({"title": "A study, of hepatic injury", "year": "2021", "author": "Fictional"},
         {"title": "A {Study} of Hepatic Injury", "year": "2021", "author": "Fictional, Anne"},
         "k"),
        ({"doi": "https://doi.org/10.1/ABC"}, {"doi": "10.1/abc", "title": "x"}, "k"),
        # Round 2 of #298: an entry with no DOI is found by its title, year and author.
        ({"doi": "10.1/abc", "title": "A study of hepatic injury", "year": "2021",
          "author": "Fictional"},
         {"title": "A {Study} of Hepatic Injury", "year": "2021", "author": "Fictional, Anne"},
         "k"),
        ({"doi": "10.1/abc", "title": "A study of hepatic injury"},
         {"doi": "10.1/xyz", "title": "A study of hepatic injury"}, None),
    ],
)  # fmt: skip
def test_a_work_cited_in_word_is_matched_to_a_key_only_when_it_is_that_work(
    work: dict, fields: dict, key: str | None
) -> None:
    """Round 1 of #298: titles compared in Latin letters alone made two works one."""
    from manuscript_guard.citationfields import Work
    from manuscript_guard.cli import _said_inserted

    said = _said_inserted(Work(**work), {"k": fields})
    assert ("[@k]" in said) is (key is not None), said
