"""The checklist transcriber.

Tests build their own .docx rather than relying on the official documents, which are not
committed: they carry their own licences, and a test suite that needs a manual download is
a test suite that does not run.

The shapes exercised here are the ones the real guidelines actually use, and each was found
by running the transcriber against the real thing and watching it get the answer wrong.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import yaml

from manuscript_guard.reporting import Recipe, RecipeError, build_profile, transcribe, verify

_MAIN = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_OFFICE_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"

CONTENT_TYPES = f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="{_MAIN}"/>
</Types>"""

RELS = f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="{_OFFICE_DOC}" Target="word/document.xml"/>
</Relationships>"""

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(path: Path, rows: list[list[str]], split_runs: bool = False) -> Path:
    """A .docx with one table. `split_runs` chops each cell across several w:t elements,
    the way Word does when formatting or spell-check state changes mid-sentence."""

    def runs(text: str) -> str:
        if not split_runs or len(text) < 8:
            return f"<w:r><w:t xml:space='preserve'>{text}</w:t></w:r>"
        mid = len(text) // 2
        return (
            f"<w:r><w:t xml:space='preserve'>{text[:mid]}</w:t></w:r>"
            f"<w:r><w:t xml:space='preserve'>{text[mid:]}</w:t></w:r>"
        )

    body = []
    for row in rows:
        cells = "".join(f"<w:tc><w:p>{runs(c)}</w:p></w:tc>" for c in row)
        body.append(f"<w:tr>{cells}</w:tr>")
    document = (
        f"<?xml version='1.0' encoding='UTF-8'?><w:document {NS}><w:body>"
        f"<w:tbl>{''.join(body)}</w:tbl></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", RELS)
        archive.writestr("word/document.xml", document)
    return path


# ---------------------------------------------------------------- shapes


def test_a_plain_topic_id_text_table(tmp_path: Path) -> None:
    path = make_docx(
        tmp_path / "a.docx",
        [
            ["Section and Topic", "Item #", "Checklist item", "Location"],
            ["TITLE", ""],
            ["Title", "1", "Identify the report as a systematic review.", ""],
            ["Rationale", "3", "Describe the rationale for the review.", ""],
        ],
    )
    items = transcribe(path, Recipe("X", "a.docx", text_column=2, id_column=1, topic_column=0))
    assert [i.id for i in items] == ["1", "3"]
    assert items[0].section == "TITLE"
    assert items[1].text == "Describe the rationale for the review."


def test_continuation_rows_become_sub_items(tmp_path: Path) -> None:
    """STROBE writes item 1 as two rows, the second with only the text cell filled.

    Reading that row as a section heading silently drops every sub-item — the transcriber
    did exactly that at first, and produced 22 items where the document has 34.
    """
    path = make_docx(
        tmp_path / "s.docx",
        [
            ["", "Item No.", "Recommendation", "Page No."],
            ["Title and abstract", "1", "(a) Indicate the study design in the title", ""],
            ["", "", "(b) Provide an informative and balanced abstract summary", ""],
            ["Introduction", ""],
            ["Background", "2", "Explain the scientific background and rationale", ""],
        ],
    )
    recipe = Recipe(
        "S",
        "s.docx",
        text_column=2,
        id_column=1,
        topic_column=0,
        carry_id=True,
        subitem_letters=True,
    )
    items = transcribe(path, recipe)
    assert [i.id for i in items] == ["1a", "1b", "2"]
    assert items[1].text.startswith("Provide an informative")
    assert "(b)" not in items[1].text


def test_a_footnote_marker_is_stripped_from_an_identifier(tmp_path: Path) -> None:
    path = make_docx(
        tmp_path / "f.docx",
        [
            ["", "Item No.", "Recommendation"],
            ["Funding", "15*", "Give the source of funding and the role of the funders", ""],
        ],
    )
    items = transcribe(path, Recipe("F", "f.docx", text_column=2, id_column=1, topic_column=0))
    assert items[0].id == "15"


def test_identifier_and_topic_in_one_cell(tmp_path: Path) -> None:
    """CONSORT writes "1a. Title" in a single cell."""
    path = make_docx(
        tmp_path / "c.docx",
        [
            ["", "Item Description", "Location"],
            ["Title and Abstract", "", ""],
            ["1a. Title", "Identification as a randomised trial.", ""],
        ],
    )
    items = transcribe(path, Recipe("C", "c.docx", text_column=1, topic_column=0, id_in_topic=True))
    assert items[0].id == "1a"
    assert items[0].topic == "Title"


def test_several_self_naming_items_in_one_cell_are_split(tmp_path: Path) -> None:
    """RECORD packs three extension items into a single cell.

    Emitting only the first loses two thirds of the checklist, which is what happened
    before this was handled: RECORD came out with 8 items instead of 13.
    """
    path = make_docx(
        tmp_path / "r.docx",
        [
            ["", "Item No.", "STROBE items", "Loc", "RECORD items", "Loc"],
            [
                "Participants",
                "6",
                "Give the eligibility criteria",
                "",
                "RECORD 6.1: The methods of study population selection should be listed. "
                "RECORD 6.2: Any validation studies should be referenced. "
                "RECORD 6.3: A flow diagram may be provided.",
                "",
            ],
        ],
    )
    items = transcribe(path, Recipe("R", "r.docx", text_column=4, topic_column=0, named_id=True))
    assert [i.id for i in items] == ["6.1", "6.2", "6.3"]
    assert items[2].text == "A flow diagram may be provided."


def test_dotted_sub_identifiers_are_kept_whole(tmp_path: Path) -> None:
    """RECORD-PE numbers items 7.1.a, 7.1.b — not 1.a, which would collide across rows."""
    path = make_docx(
        tmp_path / "pe.docx",
        [
            ["Item No", "STROBE items", "RECORD items", "RECORD-PE items"],
            [
                "7",
                "Clearly define outcomes",
                "—",
                "7.1.a: Describe how the drug exposure definition was developed. "
                "7.1.b: Specify the data sources for drug exposure information.",
            ],
        ],
    )
    items = transcribe(path, Recipe("PE", "pe.docx", text_column=3, named_id=True))
    assert [i.id for i in items] == ["7.1.a", "7.1.b"]


def test_an_em_dash_is_not_an_item(tmp_path: Path) -> None:
    path = make_docx(
        tmp_path / "d.docx",
        [
            ["Item No", "STROBE items", "RECORD-PE items"],
            ["2", "Explain the scientific background", "—"],
        ],
    )
    with pytest.raises(RecipeError, match="matched no items"):
        transcribe(path, Recipe("D", "d.docx", text_column=2, named_id=True))


def test_only_the_named_tables_are_read(tmp_path: Path) -> None:
    path = tmp_path / "two.docx"
    make_docx(path, [["How to use this checklist"], ["Some preamble text here."]])
    # A second table cannot be added by the helper, so assert the selector rejects instead.
    with pytest.raises(RecipeError):
        transcribe(path, Recipe("T", "two.docx", text_column=1, tables=(5,)))


# ---------------------------------------------------------------- verification


def test_verification_passes_when_runs_are_split_mid_word(tmp_path: Path) -> None:
    """Word splits runs anywhere. Joining them with a space breaks true transcriptions."""
    path = make_docx(
        tmp_path / "v.docx",
        [
            ["", "Item No.", "Recommendation"],
            ["Title", "1", "Indicate the study’s design with a commonly used term", ""],
        ],
        split_runs=True,
    )
    items = transcribe(path, Recipe("V", "v.docx", text_column=2, id_column=1, topic_column=0))
    assert verify(items, path) == []


def test_verification_catches_a_drifted_transcription(tmp_path: Path) -> None:
    path = make_docx(
        tmp_path / "w.docx",
        [["", "Item No.", "Recommendation"], ["Title", "1", "Indicate the study design", ""]],
    )
    items = transcribe(path, Recipe("W", "w.docx", text_column=2, id_column=1, topic_column=0))
    items[0].text = "Indicate the study design clearly"
    assert verify(items, path) == ["1"]


# ---------------------------------------------------------------- recipes and profiles


def test_a_recipe_needs_its_provenance(tmp_path: Path) -> None:
    recipe = tmp_path / "X.recipe.yaml"
    recipe.write_text(
        yaml.safe_dump({"meta": {"name": "X"}, "document": "x.docx", "text_column": 1}),
        encoding="utf-8",
    )
    with pytest.raises(RecipeError, match="meta.source_url is required"):
        build_profile(recipe, tmp_path, tmp_path)


def test_a_missing_document_says_where_to_get_it(tmp_path: Path) -> None:
    recipe = tmp_path / "X.recipe.yaml"
    recipe.write_text(
        yaml.safe_dump(
            {
                "meta": {
                    "name": "X",
                    "source_url": "https://example.invalid/x",
                    "retrieved_on": "2026-08-03",
                    "licence": "unknown",
                },
                "document": "absent.docx",
                "text_column": 1,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError, match="https://example.invalid/x"):
        build_profile(recipe, tmp_path, tmp_path)


def test_a_built_profile_records_its_source_and_licence(tmp_path: Path) -> None:
    make_docx(
        tmp_path / "x.docx",
        [["", "Item No.", "Recommendation"], ["Title", "1", "Identify the study design", ""]],
    )
    recipe = tmp_path / "X.recipe.yaml"
    recipe.write_text(
        yaml.safe_dump(
            {
                "meta": {
                    "name": "X",
                    "source_url": "https://example.invalid/x",
                    "retrieved_on": "2026-08-03",
                    "licence": "CC BY 4.0",
                },
                "document": "x.docx",
                "text_column": 2,
                "id_column": 1,
                "topic_column": 0,
            }
        ),
        encoding="utf-8",
    )
    path, count, unverified = build_profile(recipe, tmp_path, tmp_path / "out")
    assert count == 1 and unverified == []
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert profile["source_url"] == "https://example.invalid/x"
    assert profile["licence"] == "CC BY 4.0"
    assert profile["source_file"] == "sources/x.docx"
    assert "Do not edit by hand" in path.read_text(encoding="utf-8")


def test_an_unknown_recipe_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RecipeError, match="unknown recipe keys: wibble"):
        Recipe.from_dict({"name": "X", "document": "x.docx", "text_column": 1, "wibble": True})


def _recipe_with(tmp_path: Path, **extra) -> Path:
    make_docx(
        tmp_path / "x.docx",
        [["", "Item No.", "Recommendation"], ["Title", "1", "Identify the study design", ""]],
    )
    recipe = tmp_path / "X.recipe.yaml"
    meta = {
        "name": "X",
        "source_url": "https://example.invalid/x",
        "retrieved_on": "2026-08-03",
        "licence": "CC BY 4.0",
        **extra,
    }
    recipe.write_text(
        yaml.safe_dump(
            {
                "meta": meta,
                "document": "x.docx",
                "text_column": 2,
                "id_column": 1,
                "topic_column": 0,
            }
        ),
        encoding="utf-8",
    )
    return recipe


def test_a_changed_document_stops_the_transcription(tmp_path: Path) -> None:
    """A revised checklist can move columns, so the recipe may silently stop fitting."""
    recipe = _recipe_with(tmp_path, sha256="0" * 64)
    with pytest.raises(RecipeError, match="not the document this recipe was written for"):
        build_profile(recipe, tmp_path, tmp_path / "out")


def test_a_changed_document_can_be_overridden_deliberately(tmp_path: Path) -> None:
    recipe = _recipe_with(tmp_path, sha256="0" * 64)
    _path, count, _unverified = build_profile(
        recipe, tmp_path, tmp_path / "out", allow_changed=True
    )
    assert count == 1


def test_a_matching_checksum_passes(tmp_path: Path) -> None:
    import hashlib

    make_docx(
        tmp_path / "x.docx",
        [["", "Item No.", "Recommendation"], ["Title", "1", "Identify the study design", ""]],
    )
    digest = hashlib.sha256((tmp_path / "x.docx").read_bytes()).hexdigest()
    recipe = _recipe_with(tmp_path, sha256=digest)
    _path, count, _unverified = build_profile(recipe, tmp_path, tmp_path / "out")
    assert count == 1


def test_the_licence_notice_names_the_source_and_terms() -> None:
    from manuscript_guard.reporting.fetch import licence_notice

    notice = licence_notice(
        {
            "name": "X",
            "long_name": "Example guideline",
            "source_url": "https://example.invalid/x",
            "licence": "CC BY-NC",
            "licence_url": "https://example.invalid/terms",
        }
    )
    assert "CC BY-NC" in notice
    assert "https://example.invalid/x" in notice
    assert "https://example.invalid/terms" in notice
    assert "redistributes none of it" in notice


@pytest.mark.parametrize(
    ("payload", "suffix"),
    [
        (b"<!DOCTYPE html>\n<html><body>Not found</body></html>", ".docx"),
        (b"<html>landing page</html>", ".pdf"),
        (b"\x89PNG\r\n", ".docx"),
    ],
)
def test_a_landing_page_is_not_saved_as_a_document(
    tmp_path: Path, payload: bytes, suffix: str
) -> None:
    """Several checklist "download" links are HTML: a redirect, a viewer wrapper, a 404.

    Two of the URLs found for real guidelines behaved exactly this way. Saved under a .docx
    name they fail much later and confusingly, so the fetcher checks the magic bytes.
    """
    from manuscript_guard.reporting.fetch import FetchError, _reject_wrong_type

    with pytest.raises(FetchError, match="not " + suffix.replace(".", r"\.")):
        _reject_wrong_type("https://example.invalid/x", tmp_path / f"doc{suffix}", payload)


@pytest.mark.parametrize(
    ("payload", "suffix"),
    [(b"PK\x03\x04rest", ".docx"), (b"%PDF-1.7 rest", ".pdf"), (b"anything", ".txt")],
)
def test_a_real_document_passes_the_type_check(tmp_path: Path, payload: bytes, suffix: str) -> None:
    from manuscript_guard.reporting.fetch import _reject_wrong_type

    _reject_wrong_type("https://example.invalid/x", tmp_path / f"doc{suffix}", payload)


def test_fetch_does_not_overwrite_without_being_told(tmp_path: Path) -> None:
    """Re-fetching must not quietly replace a document the recipe was checksummed against."""
    from manuscript_guard.reporting.fetch import fetch_document

    existing = tmp_path / "doc.docx"
    existing.write_bytes(b"original content")
    result = fetch_document("https://example.invalid/never-called", existing)
    assert result.bytes_written == 0
    assert existing.read_bytes() == b"original content"


# ---------------------------------------------------------------- column-laid-out pages

# Two sets printed side by side, as ARRIVE 2.0 does, with a topic wrapping into the left
# margin of a continuation line — the case that makes naive concatenation produce
# "exclusion the experiment ...".
_LEFT = [
    "The ARRIVE Essential 10",
    "Study design   1    For each experiment, provide details:",
    "                    a. The groups being compared.",
    "Inclusion and  2    a. Describe any criteria used for",
    "exclusion              including animals during the",
    "criteria               experiment.",
]
_RIGHT = [
    "The Recommended Set",
    "Abstract      11   Provide an accurate summary of the",
    "                   research objectives and key methods.",
    "Background    12   Include sufficient scientific background",
    "                   to understand the rationale.",
    "",
]
_PAGE = "\n".join(left.ljust(60) + right for left, right in zip(_LEFT, _RIGHT, strict=True))


def test_columns_are_cut_apart() -> None:
    from manuscript_guard.reporting.columns import split_columns

    left, right = split_columns(_PAGE, 60)
    assert "Essential 10" in left and "Recommended Set" not in left
    assert "Recommended Set" in right and "Essential 10" not in right


def test_a_wrapped_topic_does_not_leak_into_the_item_text() -> None:
    from manuscript_guard.reporting.columns import parse_column, split_columns

    left, _right = split_columns(_PAGE, 60)
    items = parse_column(left, min_text_words=3)
    assert [i.id for i in items] == ["1", "2"]
    assert items[1].topic == "Inclusion and exclusion criteria"
    assert "exclusion" not in items[1].text
    assert items[1].text == (
        "a. Describe any criteria used for including animals during the experiment."
    )


def test_both_columns_are_read() -> None:
    from manuscript_guard.reporting.columns import parse_column, split_columns

    left, right = split_columns(_PAGE, 60)
    ids = [i.id for i in parse_column(left, 3)] + [i.id for i in parse_column(right, 3)]
    assert ids == ["1", "2", "11", "12"]


def test_only_the_opening_clause_is_verified_for_columns() -> None:
    """The weaker guarantee is deliberate, and the helper says which words it checks."""
    from manuscript_guard.reporting.columns import opening

    text = "a. Describe any criteria used for including animals during the experiment."
    assert opening(text) == "a. Describe any criteria used for including animals"
