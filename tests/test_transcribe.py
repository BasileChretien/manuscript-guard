"""The checklist transcriber.

Tests build their own .docx rather than relying on the official documents, which are not
committed: they carry their own licences, and a test suite that needs a manual download is
a test suite that does not run.

The shapes exercised here are the ones the real guidelines actually use, and each was found
by running the transcriber against the real thing and watching it get the answer wrong.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
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

# `writestr` given a bare name stamps the entry with the current time, to two seconds, so
# two writes of the same table that straddle a tick differ byte for byte, and a test that
# checksums one write and builds from the next fails now and then.
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


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
    parts = {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": RELS,
        "word/document.xml": document,
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in parts.items():
            archive.writestr(zipfile.ZipInfo(name, FIXED_TIME), data)
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


def test_make_docx_gives_the_same_bytes_across_a_clock_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test above checksums one make_docx write and builds from a second.

    Entries stamped with the clock made the two differ whenever they straddled a two-second
    tick, and the checksum test failed now and then. Here the clock jumps two seconds every
    time zipfile reads it, so going back to stamped entries fails every run.
    """
    import itertools
    import time
    import types

    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)  # Python 3.14 prefers it
    ticks = itertools.count(1_600_000_000, 2)
    clock = types.SimpleNamespace(time=lambda: next(ticks), localtime=time.localtime)
    monkeypatch.setattr(zipfile, "time", clock)

    def stamped(path: Path) -> bytes:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", "<w:document/>")
        return path.read_bytes()

    assert stamped(tmp_path / "s1.zip") != stamped(tmp_path / "s2.zip"), "the clock never ticked"

    rows = [["", "Item No.", "Recommendation"], ["Title", "1", "Identify the study design", ""]]
    first = make_docx(tmp_path / "a.docx", rows).read_bytes()
    second = make_docx(tmp_path / "b.docx", rows).read_bytes()
    assert first == second


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


# ------------------------------------------------ --save-url writes into the project


def test_save_url_never_writes_into_the_installed_package(tmp_path: Path) -> None:
    """`_recipe_paths` falls back to the recipes shipped inside the package.

    `--save-url` wrote back to whatever it returned, so on a normal pip install the command
    edited a file in site-packages: invisible to git, lost on the next upgrade, applied to
    every other project on the machine, and a PermissionError traceback on a system-wide
    install. The shipped copy has to stay exactly as released.
    """
    from manuscript_guard.cli import _record_download_url
    from manuscript_guard.paths import SHIPPED_RECIPES

    shipped = SHIPPED_RECIPES / "RECORD.recipe.yaml"
    before = shipped.read_bytes()

    written, copied = _record_download_url(tmp_path, shipped, "https://example.invalid/new.docx")

    assert shipped.read_bytes() == before, "the installed package was modified"
    assert copied and written.is_relative_to(tmp_path)
    assert "download_url: https://example.invalid/new.docx" in written.read_text(encoding="utf-8")


def test_save_url_keeps_the_licence_reasoning(tmp_path: Path) -> None:
    """A `safe_load`/`safe_dump` round trip drops every comment in the file.

    In these recipes the comments *are* the licence reasoning — which document the terms were
    read from, and why a related licence does not settle the question. Recording a URL is not
    worth losing the argument that says the file may be redistributed at all.
    """
    from manuscript_guard.cli import _record_download_url
    from manuscript_guard.paths import SHIPPED_RECIPES

    shipped = SHIPPED_RECIPES / "RECORD.recipe.yaml"
    original = shipped.read_text(encoding="utf-8")
    comments = [line for line in original.splitlines() if line.lstrip().startswith("#")]
    assert comments, "the fixture recipe no longer carries comments"

    written, _copied = _record_download_url(tmp_path, shipped, "https://example.invalid/new.docx")
    kept = written.read_text(encoding="utf-8")
    for line in comments:
        assert line in kept, f"lost: {line}"
    assert "licence:" in kept and "sha256:" in kept


def test_save_url_edits_the_projects_own_recipe_in_place(tmp_path: Path) -> None:
    """A recipe the project already owns is edited where it is, not copied beside itself."""
    from manuscript_guard.cli import _record_download_url

    local = tmp_path / "profiles" / "reporting" / "recipes" / "LOCAL.recipe.yaml"
    local.parent.mkdir(parents=True)
    local.write_text(
        "schema: manuscript-guard/recipe/1\n\n# why this licence\nmeta:\n"
        '  source_url: "https://example.invalid/page"\n\ndocument: x.docx\n',
        encoding="utf-8",
    )

    written, copied = _record_download_url(tmp_path, local, "https://example.invalid/new.docx")
    assert written == local and not copied
    text = written.read_text(encoding="utf-8")
    assert "# why this licence" in text
    assert "  download_url: https://example.invalid/new.docx" in text, text


def test_save_url_refuses_a_recipe_it_cannot_place_the_url_in(tmp_path: Path) -> None:
    """Rather than append the key at top level, where `meta` is not, and read as recorded."""
    from manuscript_guard.cli import _record_download_url

    local = tmp_path / "profiles" / "reporting" / "recipes" / "ODD.recipe.yaml"
    local.parent.mkdir(parents=True)
    local.write_text("schema: manuscript-guard/recipe/1\ndocument: x.docx\n", encoding="utf-8")

    with pytest.raises(RecipeError):
        _record_download_url(tmp_path, local, "https://example.invalid/new.docx")


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


# ---------------------------------------------------------------- the page, from pdftotext

_ACCENTED = "\n".join(
    left.replace("animals", "naïve animals").ljust(60) + right
    for left, right in zip(_LEFT, _RIGHT, strict=True)
)

# What the pdftotext of Xpdf does with a page: Latin-1, unless it is asked for UTF-8.
_AS_XPDF = f"""
import sys
asked = sys.argv[1:]
utf8 = "-enc" in asked and asked[asked.index("-enc") + 1] == "UTF-8"
sys.stdout.buffer.write({_ACCENTED!a}.encode("utf-8" if utf8 else "latin-1"))
"""
_LATIN1 = "Study design   1   Describe the naïve groups.".encode("latin-1")
_NOT_UTF8 = f"import sys; sys.stdout.buffer.write({_LATIN1!r})"
_FAILS = "import sys; sys.stderr.write('Syntax Error: no xref table'); sys.exit(1)"


def pdftotext_runs(monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    """Run `script` where pdftotext would run: a real process, given the same arguments."""
    from manuscript_guard.reporting import columns

    real_run = subprocess.run

    def run(command, **options):
        return real_run([sys.executable, "-c", script, *command[1:]], **options)

    monkeypatch.setattr(columns.shutil, "which", lambda name: name)
    monkeypatch.setattr(columns.subprocess, "run", run)


def one_page_pdf(line: bytes) -> bytes:
    """A PDF of one page holding one line of text, small enough to write out here."""
    stream = b"BT /F1 12 Tf 72 720 Td (" + line + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    body = b"%PDF-1.4\n"
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + content + b"\nendobj\n"
    table = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    return body + b"startxref\n%d\n%%%%EOF\n" % table


def test_an_accented_letter_on_the_page_is_read_from_the_pdftotext_of_xpdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page was read as UTF-8 and never asked for in it.

    Poppler writes UTF-8 unasked. The pdftotext of Xpdf, which Git for Windows puts on
    PATH, writes Latin-1, and the first accented letter failed the decode: on Windows
    `page_text` returned None and the caller raised "TypeError: expected string or
    bytes-like object, got 'NoneType'"; elsewhere it was a UnicodeDecodeError. `transcribe`
    reports a RecipeError in a sentence, and this was neither.
    """
    from manuscript_guard.reporting.columns import ColumnRecipe, transcribe_columns

    pdftotext_runs(monkeypatch, _AS_XPDF)
    path = tmp_path / "ARRIVE.pdf"
    path.write_bytes(b"%PDF-1.4")
    recipe = ColumnRecipe(document=path.name, pages=(1,), column_split=60, min_text_words=3)

    items, haystack = transcribe_columns(path, recipe)
    assert [item.id for item in items] == ["1", "2", "11", "12"]
    assert items[1].text == (
        "a. Describe any criteria used for including naïve animals during the experiment."
    )
    assert "including naïve animals" in haystack


@pytest.mark.parametrize(
    ("script", "said"),
    [
        (_NOT_UTF8, "wrote something else for page 2 of ARRIVE.pdf"),
        (_FAILS, "pdftotext failed on ARRIVE.pdf: Syntax Error: no xref table"),
    ],
    ids=["not-utf-8", "failed"],
)
def test_a_page_pdftotext_cannot_give_is_refused_in_a_sentence(
    script: str, said: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A letter that could not be decoded is not replaced: the item it stood in would pass
    the opening-clause check, which reads the same text, and go into the profile."""
    from manuscript_guard.reporting.columns import page_text

    pdftotext_runs(monkeypatch, script)
    path = tmp_path / "ARRIVE.pdf"
    path.write_bytes(b"%PDF-1.4")
    with pytest.raises(RecipeError, match=said):
        page_text(path, 2)


@pytest.mark.parametrize(
    ("raised", "said"),
    [
        (
            subprocess.TimeoutExpired("pdftotext", 120),
            "pdftotext did not finish page 2 of ARRIVE.pdf",
        ),
        (
            OSError("not a valid Win32 application"),
            "pdftotext would not run on ARRIVE.pdf: not a valid Win32 application",
        ),
    ],
    ids=["timed-out", "would-not-start"],
)
def test_a_pdftotext_that_does_not_answer_is_refused_in_a_sentence(
    raised: Exception, said: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither was caught, and neither is a RecipeError, so `transcribe` ended in a
    traceback where every other failure of the page is a sentence."""
    from manuscript_guard.reporting import columns

    def run(*_args, **_options):
        raise raised

    monkeypatch.setattr(columns.shutil, "which", lambda name: name)
    monkeypatch.setattr(columns.subprocess, "run", run)
    path = tmp_path / "ARRIVE.pdf"
    path.write_bytes(b"%PDF-1.4")
    with pytest.raises(RecipeError, match=said):
        columns.page_text(path, 2)


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext is not installed")
def test_a_real_page_with_an_accented_letter_is_read(tmp_path: Path) -> None:
    """By whichever pdftotext this machine has, and with the line ends of none of them."""
    from manuscript_guard.reporting.columns import page_text

    path = tmp_path / "ARRIVE.pdf"
    # In PDF's own octal escapes, \357 is the i with a diaeresis of WinAnsi.
    path.write_bytes(one_page_pdf(rb"Describe the na\357ve and the treated groups."))

    text = page_text(path, 1)
    assert text.splitlines()[0].strip() == "Describe the naïve and the treated groups."
    assert "\r" not in text


# ---------------------------------------------------------------- a scale, as the PDF lays it out

#: An invented rating scale, laid out as `pdftotext -layout` prints one: the rater's
#: instructions, then numbered items, a clarifying line under some titles, and the statements a
#: rater chooses between with the score at the end of the line. Invented rather than copied,
#: because this repository ships recipes and not transcribed checklist text, and because a form
#: of one's own can hold the cases a published one happens not to.
_SCALE = """\
Scale for the Assessment of Imaginary Things - SAIT

Please rate each aspect using categories 0-2. Choose the option which best fits.

1) Clarity of the thing described

The thing is not described.                                                   0

The thing is described in passing.                                            1

The thing is described plainly.                                               2

2) Evidence offered for the thing

(e.g., measurements, where the field has them)

No evidence is offered.                                                       0

Evidence is offered selectively.                                              1

Evidence is offered throughout.                                               2

Sumscore
"""


def test_a_scale_item_carries_its_options_and_its_clarifying_line() -> None:
    from manuscript_guard.reporting.scale import parse_scale

    items = parse_scale(_SCALE, stop_at="Sumscore")
    assert [i.id for i in items] == ["1", "2"]
    assert items[0].topic == "Clarity of the thing described"
    assert items[0].extras["clarification"] == ""
    assert items[1].extras["clarification"] == "(e.g., measurements, where the field has them)"
    assert items[1].extras["statements"] == [
        "No evidence is offered.",
        "Evidence is offered selectively.",
        "Evidence is offered throughout.",
    ]
    assert items[1].extras["scores"] == ["0", "1", "2"]


def test_the_instructions_above_a_scale_are_not_items() -> None:
    """A rater's instructions can be numbered; what makes an item is its scored options."""
    from manuscript_guard.reporting.scale import parse_scale

    text = _SCALE.replace(
        "Please rate each aspect", "3) Read the whole manuscript first\n\nPlease rate each aspect"
    )
    assert [i.id for i in parse_scale(text, stop_at="Sumscore")] == ["1", "2"]


def test_a_statement_that_holds_a_number_keeps_it() -> None:
    """The statements are carried apart from the text for exactly this: taking the scores off a
    joined string would cut a statement at its own number."""
    from manuscript_guard.reporting.scale import parse_scale

    text = _SCALE.replace(
        "Evidence is offered selectively.",
        "At least 2 measurements are offered.   ",
    )
    item = parse_scale(text, stop_at="Sumscore")[1]
    assert "At least 2 measurements are offered." in item.extras["statements"]


def test_a_line_that_is_neither_heading_nor_option_stops_the_transcription() -> None:
    """A statement that wrapped, or a footer, would otherwise be written wrong in silence. This
    is the mistake that lost the parenthetical under two of SANRA's items."""
    from manuscript_guard.reporting.scale import parse_scale
    from manuscript_guard.reporting.transcribe import RecipeError

    wrapped = _SCALE.replace(
        "Evidence is offered throughout.                                               2",
        "Evidence is offered throughout, and in the appendix as well as the      2\nmain text.",
    )
    with pytest.raises(RecipeError, match="wrapped"):
        parse_scale(wrapped, stop_at="Sumscore")


def test_an_item_with_too_few_options_stops_the_transcription() -> None:
    """Dropped silently, an item printed with one option vanished from the profile."""
    from manuscript_guard.reporting.scale import parse_scale
    from manuscript_guard.reporting.transcribe import RecipeError

    thin = _SCALE.replace(
        "Evidence is offered selectively.                                              1\n\n", ""
    ).replace(
        "Evidence is offered throughout.                                               2\n\n", ""
    )
    with pytest.raises(RecipeError, match="fewer than"):
        parse_scale(thin, stop_at="Sumscore")


def test_a_count_the_recipe_states_is_held() -> None:
    from manuscript_guard.reporting.scale import parse_scale
    from manuscript_guard.reporting.transcribe import RecipeError

    with pytest.raises(RecipeError, match="the recipe says every item has 4"):
        parse_scale(_SCALE, options=4, stop_at="Sumscore")


def test_a_second_unscored_line_under_one_item_stops_the_transcription() -> None:
    from manuscript_guard.reporting.scale import parse_scale
    from manuscript_guard.reporting.transcribe import RecipeError

    text = _SCALE.replace(
        "(e.g., measurements, where the field has them)",
        "(e.g., measurements, where the field has them)\n\nand a second unscored line",
    )
    with pytest.raises(RecipeError, match="second unscored line"):
        parse_scale(text, stop_at="Sumscore")


def test_items_that_do_not_run_from_one_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page listed twice, or an item lost, reads as a gap in the numbering."""
    from manuscript_guard.reporting import columns
    from manuscript_guard.reporting.scale import ScaleRecipe, transcribe_scale
    from manuscript_guard.reporting.transcribe import RecipeError

    monkeypatch.setattr(columns, "page_text", lambda _path, _page: _SCALE)
    with pytest.raises(RecipeError, match="without a gap"):
        transcribe_scale(
            tmp_path / "x.pdf",
            ScaleRecipe(document="x.pdf", pages=(1, 2), stop_at="Sumscore"),
        )


def test_a_document_with_no_scored_items_does_not_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recipe that does not fit says so, where a wrong one would transcribe prose."""
    from manuscript_guard.reporting import columns
    from manuscript_guard.reporting.scale import ScaleRecipe, transcribe_scale
    from manuscript_guard.reporting.transcribe import RecipeError

    monkeypatch.setattr(
        columns,
        "page_text",
        lambda _path, _page: "A page of prose. 1) a number in a sentence, nothing scored.",
    )
    with pytest.raises(RecipeError, match="does not fit"):
        transcribe_scale(tmp_path / "x.pdf", ScaleRecipe(document="x.pdf", pages=(1,)))


def test_a_scale_profile_says_it_has_no_independent_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pdf-scale branch of build_profile, which no test reached: the kind, the recorded
    sentence and the options all come from here, and a profile that claimed a verbatim check
    was what hid the dropped lines."""
    import yaml

    from manuscript_guard.reporting import columns
    from manuscript_guard.reporting.build import build_profile
    from manuscript_guard.reporting.scale import VERIFICATION_BOTH

    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "SAIT.pdf").write_bytes(b"%PDF-1.4 not read, page_text is replaced")
    recipe = tmp_path / "SAIT.recipe.yaml"
    recipe.write_text(
        "schema: manuscript-guard/recipe/1\n"
        "meta:\n"
        "  name: SAIT\n"
        "  long_name: Scale for the Assessment of Imaginary Things\n"
        "  applies_to: Imaginary things; an appraisal scale, not a reporting guideline\n"
        "  source_url: https://example.invalid/sait\n"
        "  retrieved_on: 2026-10-08\n"
        "  licence: invented for this test\n"
        "document: SAIT.pdf\n"
        "format: pdf-scale\n"
        "pages: [1]\n"
        "items: 2\n"
        "options: 3\n"
        "stop_at: Sumscore\n"
        "text_column: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(columns, "page_text", lambda _path, _page: _SCALE)

    path, count, unverified = build_profile(recipe, sources, tmp_path / "out")
    assert (count, unverified) == (2, [])
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert profile["kind"] == "scale", "the pack tells a scale from a checklist by this"
    # The whole sentence, not a phrase all four of them share: this recipe states both counts.
    assert profile["verification"] == VERIFICATION_BOTH
    assert profile["items"][1]["clarification"].startswith("(e.g., measurements")
    assert profile["items"][1]["options"][2] == {
        "score": "2",
        "statement": "Evidence is offered throughout.",
    }


def test_the_verification_sentence_names_the_counts_the_recipe_states() -> None:
    """One string for every recipe said "with the item counts the recipe states" of a recipe
    that stated none; the two that replaced it said "no count" of a recipe that states one. The
    profile's own account of what was done has been wrong twice, so the choice is held here:
    each of the four says something the other three do not."""
    from manuscript_guard.reporting.scale import verification_for

    said = {
        (6, 3): verification_for(6, 3),
        (6, None): verification_for(6, None),
        (None, 3): verification_for(None, 3),
        (None, None): verification_for(None, None),
    }
    assert len(set(said.values())) == 4, "two combinations cannot share a sentence"

    assert "held to the item and option counts" in said[(6, 3)]
    assert "may not be caught" not in said[(6, 3)]

    assert "to no option count" in said[(6, None)]
    assert "dropped or invented option may not be caught" in said[(6, None)]

    assert "to no item count" in said[(None, 3)]
    assert "scale read short may not be caught" in said[(None, 3)]

    assert "held to no item or option count" in said[(None, None)]

    # Every one of them says what no scale profile may leave out.
    for sentence in said.values():
        assert "no check independent of the reader" in sentence
        assert sentence.startswith("read line by line from the published form")


def test_the_shipped_scale_recipe_takes_the_sentence_for_both_counts() -> None:
    """The only recipe that ships with a `pdf-scale` layout states both counts, so a profile
    built from it must not carry a sentence that says a count is missing."""
    from manuscript_guard.paths import SHIPPED_RECIPES
    from manuscript_guard.reporting.build import load_recipe
    from manuscript_guard.reporting.scale import VERIFICATION_BOTH, verification_for

    # Through the loader, not by reading the file: the counts are top-level keys that the loader
    # lifts into its layout, and a test that re-implements that can agree with itself while
    # disagreeing with the build.
    layouts = {}
    for path in sorted(SHIPPED_RECIPES.glob("*.recipe.yaml")):
        _recipe, meta = load_recipe(path)
        layout = meta.get("_layout") or {}
        if layout.get("format") == "pdf-scale":
            layouts[path.name] = layout
    assert layouts, "no shipped recipe uses the scale reader; this test guards nothing"
    for name, layout in layouts.items():
        chosen = verification_for(layout.get("items"), layout.get("options"))
        assert chosen == VERIFICATION_BOTH, f"{name} no longer states both counts"


def test_the_profile_carries_the_sentence_for_its_recipes_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What `build_profile` writes, not what `verification_for` returns.

    Round 1 of #219 found the hole: with the call in `build.py`'s scale branch changed to pass
    no counts — so that every scale profile, SANRA's included, said "held to no item or option
    count" — every test in this file passed, and so did the submission, contracts and compliance
    files. Passing the two arguments the wrong way round passed too. That is #211's finding 8
    closed on the function and left open on the call, which is the half that writes the file.
    """
    import yaml

    from manuscript_guard.reporting import columns
    from manuscript_guard.reporting.build import build_profile
    from manuscript_guard.reporting.scale import (
        VERIFICATION_BOTH,
        VERIFICATION_ITEMS_ONLY,
        VERIFICATION_NEITHER,
        VERIFICATION_OPTIONS_ONLY,
    )

    monkeypatch.setattr(columns, "page_text", lambda _path, _page: _SCALE)

    def written(counts: str, where: str) -> str:
        """The `verification` of a profile built from a recipe stating these counts."""
        root = tmp_path / where
        sources = root / "sources"
        sources.mkdir(parents=True)
        (sources / "SAIT.pdf").write_bytes(b"%PDF-1.4 not read, page_text is replaced")
        recipe = root / "SAIT.recipe.yaml"
        recipe.write_text(
            "schema: manuscript-guard/recipe/1\n"
            "meta:\n"
            "  name: SAIT\n"
            "  long_name: Scale for the Assessment of Imaginary Things\n"
            "  applies_to: Imaginary things; an appraisal scale\n"
            "  source_url: https://example.invalid/sait\n"
            "  retrieved_on: 2026-10-08\n"
            "  licence: invented for this test\n"
            "document: SAIT.pdf\n"
            "format: pdf-scale\n"
            "pages: [1]\n"
            f"{counts}"
            "stop_at: Sumscore\n"
            "text_column: 0\n",
            encoding="utf-8",
        )
        path, count, _unverified = build_profile(recipe, sources, root / "out")
        assert count == 2, "the stand-in form has two items however the recipe is written"
        return yaml.safe_load(path.read_text(encoding="utf-8"))["verification"]

    assert written("items: 2\noptions: 3\n", "both") == VERIFICATION_BOTH
    assert written("items: 2\n", "items") == VERIFICATION_ITEMS_ONLY
    assert written("options: 3\n", "options") == VERIFICATION_OPTIONS_ONLY
    assert written("", "neither") == VERIFICATION_NEITHER


def test_a_statement_split_across_a_page_break_loses_its_second_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pinned limit, not a wish. Every line above the first heading of a page is passed over —
    that is where a form prints its title and the rater's instructions — so the second line of a
    statement that wraps across the break is lost, where the same wrap on one page is refused.

    This is the one shape in which the loss is also silent: the score sits on the statement's own
    first line, and the statement is its item's last, so the item still has its three options and
    neither count notices. A wrap earlier in the item leaves it an option short and the counts
    refuse it. Nothing shipped reaches any of this: SANRA's recipe reads one page. If this test
    fails because the reading changed, Known gaps is what to correct."""
    from manuscript_guard.reporting import columns
    from manuscript_guard.reporting.scale import ScaleRecipe, transcribe_scale

    wrapped = "Evidence is offered throughout, and in the appendix as well as the"
    first = _SCALE.replace("Evidence is offered throughout.", wrapped).replace("\nSumscore\n", "")
    assert wrapped in first and "Sumscore" not in first
    pages = {1: first, 2: "main text.\n\nSumscore\n"}
    monkeypatch.setattr(columns, "page_text", lambda _path, page: pages[page])

    items, _read = transcribe_scale(
        tmp_path / "x.pdf",
        ScaleRecipe(document="x.pdf", pages=(1, 2), items=2, options=3, stop_at="Sumscore"),
    )
    assert [item.id for item in items] == ["1", "2"]
    assert items[1].extras["statements"][2] == wrapped, (
        "the pinned shape is a statement written short, with no word said about it; if this now "
        "holds the whole statement the limit has been closed and Known gaps should say so"
    )


def test_a_stop_at_line_before_the_last_item_is_caught_only_by_the_item_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pinned limit, recorded under "What each count can see" in DESIGN.md's Known gaps. A form
    that prints its `stop_at` word twice ends the reading at the first, and only `items` notices
    that the scale came out short. This is what the item count buys, and it is the whole of what
    it buys."""
    from manuscript_guard.reporting import columns
    from manuscript_guard.reporting.scale import ScaleRecipe, transcribe_scale
    from manuscript_guard.reporting.transcribe import RecipeError

    second = "2) Evidence offered for the thing"
    early = _SCALE.replace(second, f"Sumscore\n\n{second}")
    assert early.count("Sumscore") == 2
    monkeypatch.setattr(columns, "page_text", lambda _path, _page: early)

    with pytest.raises(RecipeError, match="1 items read, and the recipe says the form has 2"):
        transcribe_scale(
            tmp_path / "x.pdf",
            ScaleRecipe(document="x.pdf", pages=(1,), items=2, options=3, stop_at="Sumscore"),
        )

    # With no item count, the short scale is written and nothing says so.
    items, _read = transcribe_scale(
        tmp_path / "x.pdf",
        ScaleRecipe(document="x.pdf", pages=(1,), options=3, stop_at="Sumscore"),
    )
    assert [item.id for item in items] == ["1"]


def test_a_last_item_alone_on_a_second_page_is_refused_not_passed_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"Until the scale has started" began again on every page, so an item printed alone at the
    top of a second page was read as one of the rater's numbered instructions and passed over in
    silence, while the profile said every line had been placed. It is refused now, which is what
    this test's name says."""
    from manuscript_guard.reporting import columns
    from manuscript_guard.reporting.scale import ScaleRecipe, transcribe_scale
    from manuscript_guard.reporting.transcribe import RecipeError

    second = """\
3) A last item, carried over

The thing is not described.                                                   0
"""
    # Pages 3 and 7, not 1 and 2: the message must carry the page the recipe names, and with
    # (1, 2) a number counted from the start of the list reads the same as the page itself.
    pages = {3: _SCALE, 7: second}
    monkeypatch.setattr(columns, "page_text", lambda _path, page: pages[page])
    with pytest.raises(RecipeError, match=r"x\.pdf, page 7: line \d+: .*fewer than"):
        transcribe_scale(
            tmp_path / "x.pdf",
            ScaleRecipe(document="x.pdf", pages=(3, 7), stop_at="Sumscore"),
        )
