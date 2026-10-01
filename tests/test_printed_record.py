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
        assert kept.get("key", "") == block.key
        # A build puts every identifier at the start of its block, so no place is recorded.
        assert "at" not in kept
    texts = [kept.get("text", "") for kept in record["blocks"]]
    assert any("{{" in text for text in texts) is False, "a value is recorded as it printed"
    assert {"table", "figure"} <= {kept.get("kind", "") for kept in record["blocks"]}
    # Both documents of the build have one, and each names its own, which says whose it is.
    supplement = project / "build" / "supplementary.docx"
    assert printed_of(supplement) not in (None, named)
    assert len(_records(project)) == 2
    other = project / "build" / "records" / f"{printed_of(supplement)}.json"
    described = [record["document"], json.loads(other.read_text(encoding="utf-8"))["document"]]
    assert described == ["manuscript", "supplementary"]


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


def _rewritten(document: Path, part: str, change) -> None:
    """One part of a .docx put through `change`, bytes to bytes."""
    import zipfile

    scratch = document.with_suffix(".rewritten.docx")
    with zipfile.ZipFile(document) as zin, zipfile.ZipFile(scratch, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            zout.writestr(item, change(data) if item.filename == part else data)
    scratch.replace(document)


def _named(document: Path, written: bytes) -> str:
    """`document` made to name `written` as its record: what it takes to hand the import a
    record no build wrote for it. Returns the record's name."""
    from manuscript_guard.roundtrip import printed_of

    name = hashlib.sha256(written).hexdigest()
    was = printed_of(document)
    assert was is not None
    _rewritten(
        document,
        "docProps/custom.xml",
        lambda data: data.replace(was.encode("ascii"), name.encode("ascii")),
    )
    return name


def _reworded(document: Path, was: str, now: str) -> None:
    def change(data: bytes) -> bytes:
        assert was.encode("utf-8") in data
        return data.replace(was.encode("utf-8"), now.encode("utf-8"), 1)

    _rewritten(document, "word/document.xml", change)


def _said(out: str, name: str) -> list[str]:
    return [line for line in out.splitlines() if f"build/records/{name}.json" in line]


@needs_pandoc
@pytest.mark.parametrize("what", ["missing", "altered", "another build's", "the supplement's"])
def test_a_record_that_is_not_there_or_not_the_documents_is_said_and_not_used(
    project: Path, tmp_path: Path, what: str
) -> None:
    """The record is on the machine that built the document. Imported on another, or after
    build/ was cleaned, the document is read by the rules for one built before the record,
    and the import says so in one line naming the file it looked for. A file whose bytes do
    not hash to its name is not the record the document names; one written for other
    sources is not this document's; and nor is the supplement's, which was written for the
    same sources and passed for the paper's until a record said which document it
    describes (round 1 of #121's review)."""
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
    elif what == "another build's":
        record = json.loads(path.read_text(encoding="utf-8"))
        record["source"] = "0" * 64
        written = json.dumps(record).encode("utf-8")
        named = _named(returned, written)
        (path.parent / f"{named}.json").write_bytes(written)
    else:
        named = printed_of(project / "build" / "supplementary.docx")
        _named(returned, (path.parent / f"{named}.json").read_bytes())
    out = _imported(project, returned)
    said = _said(out, named)
    assert len(said) == 1, out
    assert "rules for a document built before" in said[0]


#: Records of the right name and the wrong shape, as only a hand could write them: what is
#: done to the record a build wrote, or the bytes put in its place.
_BY_HAND = {
    "nested past what Python reads": b"[" * 100_000 + b"]" * 100_000,
    "not JSON": b"{not json",
    "a list": lambda record, first: [record],
    "an identifier that is a list": lambda record, first: first.update(id=["x"]),
    "an identifier that is a mapping": lambda record, first: first.update(id={}),
    "an identifier that is empty": lambda record, first: first.update(id=""),
    "a text that is a number": lambda record, first: first.update(text=12),
    "half of a surrogate pair": lambda record, first: first.update(text=chr(0xD800)),
    "blocks that are a mapping": lambda record, first: record.update(blocks={"0": first}),
    "a block that is a list": lambda record, first: record["blocks"].append([first]),
    "a field no build writes": lambda record, first: first.update(names=["x"]),
    "what is not read given as text": lambda record, first: first.update(unread="Wingdings"),
    "a place that is not a number": lambda record, first: first.update(at="3"),
    "a place before the start": lambda record, first: first.update(at=-1),
    "a format that is true": lambda record, first: record.update(
        {"manuscript-guard-printed": True}
    ),
    "a source that is null": lambda record, first: record.update(source=None),
    "no document named": lambda record, first: record.pop("document") and None,
}


@needs_pandoc
@pytest.mark.parametrize("what", list(_BY_HAND))
def test_a_record_written_by_hand_never_stops_the_import(
    project: Path, tmp_path: Path, what: str
) -> None:
    """Round 1 of #121's review. A record's name is in a document anyone may have edited, so
    bytes that hash to it say only that they are the file named. One with a list for an
    identifier ended the import in a traceback where identifiers are looked up, and one
    nested 100,000 deep in `RecursionError`. A record is used only in the shape a build
    writes; anything else is not this document's, said in the one line, and the import goes
    by the rules without it: here, a rewording still merges."""
    from manuscript_guard.roundtrip import printed_of

    document = _build(project)
    path = project / "build" / "records" / f"{printed_of(document)}.json"
    written = _BY_HAND[what]
    if not isinstance(written, bytes):
        record = json.loads(path.read_text(encoding="utf-8"))
        first = next(entry for entry in record["blocks"] if "id" in entry)
        written = json.dumps(written(record, first) or record).encode("utf-8")
    returned = tmp_path / "back.docx"
    shutil.copyfile(document, returned)
    named = _named(returned, written)
    (path.parent / f"{named}.json").write_bytes(written)
    _reworded(returned, "This work received no funding.", "This work received no funds.")

    out = _imported(project, returned)
    assert len(_said(out, named)) == 1, out
    source = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert "This work received no funds." in source, out


@needs_pandoc
def test_a_record_cut_short_is_written_again_by_the_next_build(
    project: Path, tmp_path: Path
) -> None:
    """Round 1 of #121's review. A record is named by its content, and a file already under
    that name was taken to be it. Cut short - a full disk, a copy interrupted - it was left
    as it was by every later build of the same text, and no import of any of them would
    trust it. The file is compared, and written again where it is not the record."""
    from manuscript_guard.roundtrip import printed_of

    named = printed_of(_build(project))
    path = project / "build" / "records" / f"{named}.json"
    whole = path.read_bytes()
    path.write_bytes(whole[: len(whole) // 2])

    document = _build(project)
    assert printed_of(document) == named
    assert path.read_bytes() == whole
    returned = tmp_path / "back.docx"
    shutil.copyfile(document, returned)
    assert "build/records/" not in _imported(project, returned)


@needs_pandoc
def test_a_build_that_cannot_write_its_record_says_so_and_so_does_the_import(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round 1 of #121's review. The record was written under `contextlib.suppress`: where
    it could not be, the build said nothing, the document named no record, and its import
    read it by the older rules without a word. The build warns, for each document, and the
    document names the record that could not be written, so its import says what it looked
    for."""
    from manuscript_guard.cli import main
    from manuscript_guard.roundtrip import printed_of

    records = project / "build" / "records"
    records.parent.mkdir(exist_ok=True)
    records.write_text("a file where the folder goes", encoding="utf-8")

    assert main(["build", str(project), "--offline"]) == 0
    said = capsys.readouterr().out
    assert said.count("could not be written beside it") == 2, said
    assert "manuscript.docx printed could not be written" in said, said
    document = project / "build" / "manuscript.docx"
    named = printed_of(document)
    assert named is not None
    returned = tmp_path / "back.docx"
    shutil.copyfile(document, returned)
    assert len(_said(_imported(project, returned), named)) == 1


def test_records_written_at_once_do_not_get_in_each_other_s_way(tmp_path: Path) -> None:
    """Round 1 of #121's review. Every writer of a record wrote `<name>.json.tmp` first, and
    of 96 started together three failed on that one file (WinError 32). Each writes under a
    name of its own, and one that finds the record already put there by another is done."""
    from concurrent.futures import ThreadPoolExecutor

    from manuscript_guard.roundtrip import _put

    written = b'{"blocks":[]}' * 4096
    path = tmp_path / "records" / f"{hashlib.sha256(written).hexdigest()}.json"
    with ThreadPoolExecutor(max_workers=8) as pool:
        for done in [pool.submit(_put, path, written) for _ in range(96)]:
            done.result()
    assert path.read_bytes() == written
    assert [entry.name for entry in path.parent.iterdir()] == [path.name]


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
