"""The record of what a built document printed: written beside the build, named by the hash
of its content, and named in turn by the document, which carries nothing else of it.

`import` compares a returned document with a fresh build of the source, and that is not what
the co-author had once the source or its results changed. What each block printed when the
document was built answers the questions the import used to guess at: see
`tests/test_corruption.py` for those.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


def _records(project: Path) -> list[Path]:
    return sorted((project / "build" / "records").glob("*.json"))


def _build(project: Path) -> Path:
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    return project / "build" / "manuscript.docx"


def _imported(project: Path, returned: Path, *flags: str) -> str:
    from manuscript_guard.cli import main

    printed = StringIO()
    with redirect_stdout(printed):
        main(["import", str(returned), str(project), "--apply", *flags])
    return printed.getvalue()


@needs_pandoc
def test_a_build_records_what_each_block_printed_beside_it(project: Path) -> None:
    """One file for each document built, under build/records, named by the SHA-256 of its
    bytes. It holds every block in the document's order: a paragraph with its identifier and
    its text as printed, values and citations as they print; a heading or caption with no
    identifier; a table, figure or equation as a marker with no text. The document carries
    the file's name and none of its text."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.docxtext import blocks
    from manuscript_guard.gates.review import document_digest
    from manuscript_guard.roundtrip import printed_of, stamp_of

    document = _build(project)
    named = printed_of(document)
    assert named is not None
    path = project / "build" / "records" / f"{named}.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == named
    record = json.loads(path.read_text(encoding="utf-8"))
    loaded, _report = load_project(project)
    assert record["source"] == stamp_of(document) == document_digest(loaded)

    read = blocks(document)
    assert len(record["blocks"]) == len(read)
    for kept, block in zip(record["blocks"], read, strict=True):
        assert kept.get("id", "") == (block.names[0] if block.names else "")
        assert kept.get("text", "") == block.text
        assert kept.get("kind", "") == block.kind
    texts = [kept.get("text", "") for kept in record["blocks"]]
    assert any("{{" in text for text in texts) is False, "a value is recorded as it printed"
    assert {"table", "figure"} <= {kept.get("kind", "") for kept in record["blocks"]}
    # Both documents of the build have one, and each names its own.
    supplement = project / "build" / "supplementary.docx"
    assert printed_of(supplement) not in (None, named)
    assert len(_records(project)) == 2


@needs_pandoc
def test_records_of_earlier_builds_are_kept_and_the_same_text_adds_none(project: Path) -> None:
    """A document sent last week must still import exactly, so a build never removes a
    record. Rebuilt from the same sources, the document prints the same and names the same
    record; with a paragraph changed, it names a new one and the old one stays."""
    from manuscript_guard.roundtrip import printed_of

    first = printed_of(_build(project))
    assert printed_of(_build(project)) == first
    assert len(_records(project)) == 2
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("received no funding", "received no external funding", 1), "utf-8")
    second = printed_of(_build(project))
    assert second != first
    assert {first, second} <= {record.stem for record in _records(project)}


@needs_pandoc
def test_an_import_adds_no_record(project: Path, tmp_path: Path) -> None:
    """`import` builds the source twice to compare with, in a scratch folder. Those builds
    were sent to nobody, and recorded, every import would leave two files behind."""
    document = _build(project)
    before = _records(project)
    returned = tmp_path / "back.docx"
    shutil.copyfile(document, returned)
    _imported(project, returned)
    assert _records(project) == before


@needs_pandoc
@pytest.mark.parametrize("what", ["missing", "altered", "another document's"])
def test_a_record_that_is_not_there_or_not_the_documents_is_said_and_not_used(
    project: Path, tmp_path: Path, what: str
) -> None:
    """The record is on the machine that built the document. Imported on another, or after
    build/ was cleaned, the document is read by the rules for one built before the record,
    and the import says so in one line naming the file it looked for. A file whose bytes do
    not hash to its name is not the record the document names, and one built from other
    sources is not this document's: neither is used."""
    from manuscript_guard.roundtrip import printed_of

    document = _build(project)
    named = printed_of(document)
    path = project / "build" / "records" / f"{named}.json"
    returned = tmp_path / "back.docx"
    shutil.copyfile(document, returned)
    if what == "missing":
        shutil.rmtree(path.parent)
    elif what == "altered":
        path.write_text(path.read_text(encoding="utf-8").replace("hepatic", "renal"), "utf-8")
    else:
        record = json.loads(path.read_text(encoding="utf-8"))
        record["source"] = "0" * 64
        path.write_text(json.dumps(record), encoding="utf-8")
    out = _imported(project, returned)
    said = [line for line in out.splitlines() if f"build/records/{named}.json" in line]
    assert len(said) == 1, out
    assert "rules for a document built before" in said[0]


@needs_pandoc
def test_a_record_that_is_there_is_not_mentioned(project: Path, tmp_path: Path) -> None:
    document = _build(project)
    returned = tmp_path / "back.docx"
    shutil.copyfile(document, returned)
    assert "build/records/" not in _imported(project, returned)


def test_a_record_is_looked_for_only_under_a_name_that_is_a_hash(tmp_path: Path) -> None:
    """The name comes from the returned document, which anyone may have written: only 64
    hexadecimal digits are a record's name, and anything else names no file."""
    import zipfile

    from manuscript_guard.roundtrip import _custom_properties, printed_of

    for value, expected in (("a" * 64, "a" * 64), ("../../outside", None), ("A" * 64, None)):
        document = tmp_path / "named.docx"
        with zipfile.ZipFile(document, "w") as archive:
            archive.writestr("docProps/custom.xml", _custom_properties(None, "b" * 64, None, value))
        assert printed_of(document) == expected, value


def test_a_document_built_before_the_record_names_none(tmp_path: Path) -> None:
    import zipfile

    from manuscript_guard.roundtrip import _custom_properties, printed_of

    document = tmp_path / "old.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("docProps/custom.xml", _custom_properties(None, "b" * 64, None))
    assert printed_of(document) is None
