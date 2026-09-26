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
    segments,
    stamp_into,
    stamp_of,
    tag,
)

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")


def guessed(source: str, rendered: str) -> list[tuple[int, int]] | None:
    """Token extents found the way import once guessed them: each stretch of prose located in
    the rendered text, the tokens being what lies between.

    A test fixture, for the plain strings these unit tests use, where the guess is right.
    Import itself reads the extents from a build with every token bookmarked, because the
    guess is wrong in general - "(Smith et al. 2020)." ending a paragraph was cut at "al.".
    Pandoc's no-break space after "e.g." reads as the source's space, one for one, so the
    spans found are spans of `rendered` itself.
    """
    from manuscript_guard.roundtrip import _read

    rendered = rendered.replace("\u00a0", " ")
    flat = [shown.strip().replace("\u00a0", " ") for shown in _read(source).shown]
    spans: list[tuple[int, int]] = []
    cursor = 0
    if flat[0]:
        at = rendered.find(flat[0])
        if at < 0:
            return None
        cursor = at + len(flat[0])
    for index in range(1, len(flat)):
        piece = flat[index]
        if piece:
            at = rendered.find(piece, cursor)
            if at < 0:
                return None
            start, end, cursor = cursor, at, at + len(piece)
        elif index == len(flat) - 1:
            start, end, cursor = cursor, len(rendered), len(rendered)
        else:
            return None
        while start < end and rendered[start].isspace():
            start += 1
        while end > start and rendered[end - 1].isspace():
            end -= 1
        if start == end:
            return None
        spans.append((start, end))
    return spans


def align(source: str, rendered: str, returned: str, tokens=None, abbreviations=frozenset()):
    """`roundtrip.align`, with the token extents guessed when a test gives none."""
    from manuscript_guard.roundtrip import align as real

    extents = guessed(source, rendered) if tokens is None else tokens
    return real(source, rendered, returned, extents, abbreviations)


def realign(
    source: str, rendered: str, returned: str, tokens=None, abbreviations=frozenset()
) -> str | None:
    return align(source, rendered, returned, tokens, abbreviations).rebuilt


#: Abbreviations from pandoc 3.9's default list, which is what `import` passes when nobody
#: has a list of their own: the no-break space pandoc puts after one is written back as the
#: space it makes one of again.
ABBREVIATIONS = frozenset({"e.g.", "i.e.", "al.", "p.", "pp.", "vs.", "No.", "cf.", "fig."})


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


# ---------------------------------------------------------------- what an identifier named


def with_record(document: Path, change) -> Path:
    """The document with its record of paragraphs rewritten: `change` takes the property
    elements holding it, as one string, and returns their replacement."""
    scratch = document.with_suffix(".p.docx")
    with zipfile.ZipFile(document) as zin, zipfile.ZipFile(scratch, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "docProps/custom.xml":
                xml = data.decode("utf-8")
                ours = re.compile(
                    r'<property\b[^>]*name="manuscript-guard-paragraphs-\d+"[^>]*>.*?</property>',
                    re.DOTALL,
                )
                found = "".join(ours.findall(xml))
                xml = ours.sub("", xml)
                xml = xml.replace("</Properties>", change(found) + "</Properties>")
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    scratch.replace(document)
    return document


def unrecorded(document: Path) -> Path:
    """The document as a release from before paragraphs were recorded built it."""
    return with_record(document, lambda found: "")


FUNDING = {"This work received no funding.": "This work received no external funding."}


@needs_pandoc
def test_a_built_document_records_what_each_identifier_names(project: Path) -> None:
    """Its own paragraphs, in its order, and not the supplement's; split over properties
    short enough that Word does not cut them when it saves."""
    import hashlib

    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_project
    from manuscript_guard.roundtrip import paragraph_order, paragraphs_of, tagged_paragraphs

    assert main(["build", str(project), "--offline"]) == 0
    document = project / "build" / "manuscript.docx"
    known = tagged_paragraphs(load_project(project)[0])
    recorded = paragraphs_of(document)
    assert list(recorded) == [name for name in paragraph_order(document) if name in known]
    assert len(recorded) < len(known), "the supplement's paragraphs are in its own document"
    assert all(
        value.partition(".")[0] == hashlib.sha256(known[name][1].encode()).hexdigest()[:8]
        for name, value in recorded.items()
    )
    xml = zipfile.ZipFile(document).read("docProps/custom.xml").decode("utf-8")
    values = re.findall(r'name="manuscript-guard-paragraphs-\d+"[^>]*><vt:lpwstr>([^<]*)<', xml)
    assert len(values) > 1 and all(len(value) < 255 for value in values)


def test_a_restamp_replaces_the_record_rather_than_adding_to_it(tmp_path: Path) -> None:
    from manuscript_guard.roundtrip import paragraphs_of

    document = tmp_path / "d.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("_rels/.rels", "<Relationships></Relationships>")
    many = {f"mg-p-main-{2 * i}": f"{i:08x}.abcdef" for i in range(60)}
    stamp_into(document, "a" * 64, many)
    stamp_into(document, "b" * 64, {"mg-p-main-2": "0123abcd.456789"})
    assert set(paragraphs_of(document)) == {"mg-p-main-2"}
    assert stamp_of(document) == "b" * 64


@needs_pandoc
def test_an_edit_is_not_merged_where_the_identifier_now_names_other_text(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Whatever made an identifier name other text, a source edited since the build or a
    release that numbers paragraphs by other rules, the edit made under it belongs to a
    paragraph that is not there now. It is named and left, even with --force."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = edit_docx(project / "build" / "manuscript.docx", tmp_path / "back.docx", FUNDING)
    funding = next(n for n, text in _texts(project).items() if text.startswith("This work"))
    index = funding.rpartition("-")[2]
    ours, _, before = _recorded(returned)[funding].partition(".")
    # The record says the funding identifier named some other text at the build.
    with_record(
        returned,
        lambda found: re.sub(
            rf"(?<=[:,]){index}\.{ours}\.{before}(?=[,<])", f"{index}.00000000.{before}", found
        ),
    )
    source = (project / "manuscript" / "main.md").read_text(encoding="utf-8")

    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply", "--force"]) == 1
    assert (project / "manuscript" / "main.md").read_text(encoding="utf-8") == source
    assert "were not compared" in capsys.readouterr().out


def _recorded(document: Path) -> dict[str, str]:
    from manuscript_guard.roundtrip import paragraphs_of

    return paragraphs_of(document) or {}


def _texts(project: Path) -> dict[str, str]:
    from manuscript_guard.contracts import load_project
    from manuscript_guard.roundtrip import tagged_paragraphs

    known = tagged_paragraphs(load_project(project)[0])
    return {name: text for name, (_path, text, _start) in known.items()}


@needs_pandoc
def test_a_paragraph_tagged_now_and_not_at_the_build_is_not_reported_deleted(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A release that tags more kinds of block gives the source identifiers the document
    never carried. Walked as the manuscript's paragraphs, each read as deleted in Word, and
    the author was told to delete it from the source."""
    from manuscript_guard import roundtrip
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = project / "build" / "manuscript.docx"
    # From now on a paragraph that is only a table or a figure is tagged; at the build it
    # was not.
    was = roundtrip._untagged
    monkeypatch.setattr(
        roundtrip,
        "_untagged",
        lambda text: was(text) and not re.fullmatch(r"\{\{(?:table|figure)\.[^}]*\}\}", text),
    )
    capsys.readouterr()
    main(["import", str(returned), str(project)])
    assert "deleted in Word" not in capsys.readouterr().out


@needs_pandoc
def test_an_unrecorded_document_whose_numbering_did_not_change_still_imports(
    project: Path, tmp_path: Path
) -> None:
    """A document built before paragraphs were recorded carries no record. Its source
    reading the same under the old rules as the new is the ordinary case, and it merges as
    it did."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = edit_docx(project / "build" / "manuscript.docx", tmp_path / "back.docx", FUNDING)
    unrecorded(returned)
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    assert "no external funding" in (project / "manuscript" / "main.md").read_text(
        encoding="utf-8"
    )


@needs_pandoc
def test_an_unrecorded_document_built_from_other_text_is_refused_even_with_force(
    project: Path, tmp_path: Path
) -> None:
    """Whether an unrecorded document was numbered as its source is now can only be asked
    of the text it was built from. Asked of the source as edited since, a forced import
    wrote four paragraphs' text over their neighbours; the plan shows what an edit becomes
    and not what it replaces, so checking every hunk could not have caught it."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = edit_docx(project / "build" / "manuscript.docx", tmp_path / "back.docx", FUNDING)
    unrecorded(returned)
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\nA later paragraph.\n", "utf-8")
    source = path.read_text(encoding="utf-8")

    assert main(["import", str(returned), str(project), "--apply", "--force"]) == 1
    assert path.read_text(encoding="utf-8") == source
    assert main(["respond", str(project), "--open", "--from", str(returned), "--force"]) == 1


@needs_pandoc
def test_a_paragraph_whose_identifier_the_manuscript_no_longer_gives_is_named(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A release that tags fewer kinds of block leaves the document carrying an identifier
    the manuscript no longer gives. The import walks the manuscript's identifiers, so one
    of these was skipped without a word: an edit in it went nowhere, the import said nothing
    came back, and it exited 0."""
    from manuscript_guard import roundtrip
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = edit_docx(project / "build" / "manuscript.docx", tmp_path / "back.docx", FUNDING)
    was = roundtrip._untagged
    monkeypatch.setattr(
        roundtrip, "_untagged", lambda text: was(text) or text.startswith("This work received")
    )
    capsys.readouterr()
    assert main(["import", str(returned), str(project)]) == 1
    out = capsys.readouterr().out
    assert "were not compared" in out
    assert "nothing came back" not in out


@needs_pandoc
def test_an_unrecorded_document_is_judged_by_the_files_it_carries(
    project: Path, tmp_path: Path
) -> None:
    """An identifier names its file. A supplement whose front matter is read differently now
    says nothing about the numbering of the main text's document, and refusing it for that
    blocked every unrecorded main document in a project with such a supplement."""
    from manuscript_guard.cli import main

    supplement = project / "manuscript" / "supplementary" / "S1_code_lists.md"
    supplement.write_text(
        "---\ntitle: S1\n...\n\n" + supplement.read_text(encoding="utf-8"), "utf-8"
    )
    assert main(["build", str(project), "--offline"]) == 0
    returned = edit_docx(project / "build" / "manuscript.docx", tmp_path / "back.docx", FUNDING)
    unrecorded(returned)
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    assert "no external funding" in (project / "manuscript" / "main.md").read_text(
        encoding="utf-8"
    )


@needs_pandoc
def test_a_comment_on_a_paragraph_whose_identifier_moved_opens_no_anchor(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Anchored to whatever paragraph sits there now, the point's revision was checked
    against the wrong one, and a paragraph nobody revised could pass."""
    import yaml
    from test_seed_revision import commented

    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = commented(
        project / "build" / "manuscript.docx", tmp_path / "back.docx", [("Reviewer 2", "Why?")]
    )
    # Every identifier the record covers now names other text.
    with_record(returned, lambda found: re.sub(r"\.[0-9a-f]{8}", ".00000000", found))
    capsys.readouterr()
    assert main(["respond", str(project), "--open", "--from", str(returned)]) == 0
    document = yaml.safe_load((project / "revision" / "round-1.yaml").read_text(encoding="utf-8"))
    assert not any(p.get("where") for r in document["reviewers"] for p in r["points"])
    assert "recorded without one" in capsys.readouterr().out


def _without_paragraph(document: Path, target: Path, identifier: str) -> Path:
    """The document with the Word paragraph carrying `identifier` deleted outright."""
    with zipfile.ZipFile(document) as zin, zipfile.ZipFile(target, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = data.decode("utf-8")
                gone = next(
                    p
                    for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL)
                    if f'w:name="{identifier}"' in p
                )
                data = xml.replace(gone, "", 1).encode("utf-8")
            zout.writestr(item, data)
    return target


@needs_pandoc
def test_a_paragraph_the_source_changed_and_word_deleted_is_named(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the identifiers that came back were asked about, so a paragraph whose identifier
    was no longer trusted, deleted in Word, left no trace: `import --force` said nothing came
    back and exited 0. Main reports the deletion."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    whether = next(n for n, text in _texts(project).items() if text.startswith("Whether"))
    returned = _without_paragraph(
        project / "build" / "manuscript.docx", tmp_path / "back.docx", whether
    )
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("been examined.", "been examined before.", 1),
        encoding="utf-8",
    )

    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply", "--force"]) == 1
    out = capsys.readouterr().out
    assert whether in out
    assert "nothing came back" not in out


@needs_pandoc
def test_an_empty_paragraph_under_an_identifier_no_longer_given_is_not_reported(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Releases before 0.2.45 put an identifier in front of an HTML comment standing alone,
    and the document carried an empty paragraph under it. Returned untouched, such a document
    had it named as not compared, and the import exited 1."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    slug = next(iter(_texts(project))).removeprefix("mg-p-").rpartition("-")[0]
    empty = (
        f'<w:p><w:bookmarkStart w:id="990" w:name="mg-p-{slug}-999"/>'
        f'<w:bookmarkEnd w:id="990"/></w:p>'
    )
    returned = tmp_path / "back.docx"
    with zipfile.ZipFile(project / "build" / "manuscript.docx") as zin, zipfile.ZipFile(
        returned, "w"
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = data.decode("utf-8")
                at = xml.index("</w:p>") + len("</w:p>")
                data = (xml[:at] + empty + xml[at:]).encode("utf-8")
            zout.writestr(item, data)
    unrecorded(returned)

    capsys.readouterr()
    assert main(["import", str(returned), str(project)]) == 0
    assert "nothing came back" in capsys.readouterr().out


#: A paragraph that is only a value, which releases before 0.2.49 gave no identifier.
LONE_VALUE = "{{results.ror.point}}"


def _with_lone_value(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "# Methods\n", f"{LONE_VALUE}\n\n# Methods\n", 1
        ),
        encoding="utf-8",
    )


@needs_pandoc
def test_a_value_paragraph_an_unrecorded_document_never_carried_is_not_reported_deleted(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """0.2.49 gave a paragraph that is only a value an identifier. A document built before
    then never carried it, and returned untouched had it reported deleted in Word."""
    from manuscript_guard import roundtrip
    from manuscript_guard.cli import main

    _with_lone_value(project)
    was = roundtrip._untagged
    with monkeypatch.context() as patched:
        patched.setattr(
            roundtrip,
            "_untagged",
            lambda block: was(block) or re.fullmatch(r"\{\{[^}]*\}\}", block.strip()) is not None,
        )
        assert main(["build", str(project), "--offline"]) == 0
    returned = unrecorded(project / "build" / "manuscript.docx")

    capsys.readouterr()
    main(["import", str(returned), str(project)])
    assert "deleted in Word" not in capsys.readouterr().out


@needs_pandoc
def test_a_value_paragraph_deleted_in_an_unrecorded_document_is_still_named(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Built by 0.2.49, an unrecorded document did carry it, and a co-author could delete
    it. Not knowing which release built it, the import cannot drop the report."""
    from manuscript_guard.cli import main

    _with_lone_value(project)
    assert main(["build", str(project), "--offline"]) == 0
    value = next(n for n, text in _texts(project).items() if text == LONE_VALUE)
    returned = _without_paragraph(
        project / "build" / "manuscript.docx", tmp_path / "back.docx", value
    )
    unrecorded(returned)

    capsys.readouterr()
    assert main(["import", str(returned), str(project)]) == 1
    assert "nothing came back" not in capsys.readouterr().out


@needs_pandoc
def test_an_old_supplement_does_not_lack_the_papers_value_paragraph(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The supplement is imported on its own, and a value paragraph of the paper was never
    meant to be in it: asked about everywhere, an untouched supplement from before the
    record named the paper's value paragraph as not in it, and the import exited 1."""
    from manuscript_guard.cli import main

    _with_lone_value(project)
    assert main(["build", str(project), "--offline"]) == 0
    returned = tmp_path / "supplementary.docx"
    shutil.copy(project / "build" / "supplementary.docx", returned)
    unrecorded(returned)

    capsys.readouterr()
    assert main(["import", str(returned), str(project)]) == 0
    assert "only a value" not in capsys.readouterr().out


@needs_pandoc
def test_a_comment_on_a_value_paragraph_an_unrecorded_document_carries_keeps_its_anchor(
    project: Path, tmp_path: Path
) -> None:
    """`import` compares a paragraph that is only a value when the document carries it;
    `respond --open` dropped the anchor of a comment on one, saying its identifier no longer
    named the text commented on."""
    import yaml
    from test_seed_revision import commented

    from manuscript_guard.cli import main

    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "# Abstract\n\n", f"# Abstract\n\n{LONE_VALUE}\n\n", 1
        ),
        encoding="utf-8",
    )
    assert main(["build", str(project), "--offline"]) == 0
    value = next(n for n, text in _texts(project).items() if text == LONE_VALUE)
    returned = commented(
        project / "build" / "manuscript.docx", tmp_path / "back.docx", [("Reviewer 2", "Why?")]
    )
    unrecorded(returned)

    assert main(["respond", str(project), "--open", "--from", str(returned)]) == 0
    document = yaml.safe_load((project / "revision" / "round-1.yaml").read_text(encoding="utf-8"))
    assert [p.get("where") for r in document["reviewers"] for p in r["points"]] == [value]


def test_a_paragraph_in_parts_is_refused_beside_one_not_compared(tmp_path: Path) -> None:
    """Whether a paragraph reached Word in parts was judged by the section of the identified
    paragraph after it, and one left out of the comparison had none: the rewording of the
    first part merged, and the rest of the paragraph would have been deleted."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    path = tmp_path / "main.md"
    path.write_text("Alpha text here.\n\nBeta.\n", encoding="utf-8")
    every = {"a": (path, "Alpha text here.", 0), "b": (path, "Beta.", 18)}
    sent = [Block(("a",), "Alpha text here."), Block((), "y = z"), Block(("b",), "Beta.")]
    returned = [Block(("a",), "Alpha text here, reworded."), sent[1], sent[2]]

    plan = plan_import({"a": every["a"]}, sent, returned, every=every)
    assert not plan.merged
    assert [refusal.name for refusal in plan.refused] == ["a"]


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
    """`[]{#id}# Methods` is not a heading, and a table placeholder alone becomes a table."""
    tagged = tag("# Methods\n\nSome prose here.\n\n{{table.baseline}}\n", "main")
    assert tagged.startswith("# Methods")
    assert "[]{#mg-p-" in tagged
    assert tagged.count("[]{#mg-p-") == 1, "only the prose paragraph"
    assert "}{{table.baseline}}" not in tagged


REGISTRY = "https://example.org/registry"

#: (paragraph, its definitions, what the paragraph prints as)
REFERENCE_LINKS = [
    pytest.param(
        "See [the registry][reg] for details.",
        f"[reg]: {REGISTRY}",
        "See the registry for details.",
        id="full",
    ),
    pytest.param(
        "See [reg][] for details.", f"[reg]: {REGISTRY}", "See reg for details.", id="collapsed"
    ),
    pytest.param(
        "See [reg] for details.", f"[reg]: {REGISTRY}", "See reg for details.", id="shortcut"
    ),
    pytest.param(
        "See [reg] for details.",
        f"   [reg]: <{REGISTRY}> 'The registry'",
        "See reg for details.",
        id="indented-with-title",
    ),
    pytest.param(
        "See [reg] and [other] for details.",
        f"[other]: https://example.org/other\n[reg]: {REGISTRY} \"The registry\"",
        "See reg and other for details.",
        id="several-definitions",
    ),
    # A binding beside the link, so the marked build is not the plain one again.
    pytest.param(
        "See [the registry][reg] for {{results.ror.point}} details.",
        f"[reg]: {REGISTRY}",
        "See the registry for {{results.ror.point}} details.",
        id="beside-a-binding",
    ),
]


def _docx_part(document: Path, part: str) -> str:
    return zipfile.ZipFile(document).read(part).decode("utf-8")


#: The plain build, and the marked one `import` compares with: both go through `_untagged`.
BUILDS = pytest.mark.parametrize("mark", [False, True], ids=["plain", "marked"])


@needs_pandoc
@BUILDS
@pytest.mark.parametrize(("paragraph", "definition", "printed"), REFERENCE_LINKS)
def test_a_link_definition_is_left_for_pandoc_to_read(
    paragraph: str, definition: str, printed: str, mark: bool, tmp_path: Path
) -> None:
    """`[reg]: https://...` standing as its own block defines a reference-style link. With an
    identifier in front of it, pandoc read it as a paragraph instead: every `[text][reg]` in
    the manuscript printed with its brackets, linked to nothing, and the definition itself
    printed as a line of text. On every build, not only in `import`."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text, tag

    source = tmp_path / "a.md"
    text = f"{paragraph}\n\n{definition}\n"
    source.write_text(tag(text, "main.md", mark=mark), encoding="utf-8")
    document = tmp_path / "a.docx"
    subprocess.run(["pandoc", str(source), "-o", str(document)], check=True)

    assert f'Target="{REGISTRY}"' in _docx_part(document, "word/_rels/document.xml.rels")
    assert "<w:hyperlink" in _docx_part(document, "word/document.xml")
    # The paragraph keeps its identifier and reads as the link's words; the definition
    # reaches the document as nothing at all.
    assert list(paragraph_text(document).values()) == [printed]
    if mark and "{{" in paragraph:
        from manuscript_guard.docxtext import TOKEN

        assert f'w:name="{TOKEN}' in _docx_part(document, "word/document.xml")


@needs_pandoc
@BUILDS
def test_a_footnote_definition_is_left_for_pandoc_to_read(mark: bool, tmp_path: Path) -> None:
    """The same syntax defines a footnote, and failed the same way: `[^cap]` printed in the
    paragraph, and the note's text printed as a paragraph of its own."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text, tag

    source = tmp_path / "a.md"
    text = "Doses were capped.[^cap]\n\n[^cap]: Capped at 40 mg.\n"
    source.write_text(tag(text, "main.md", mark=mark), encoding="utf-8")
    document = tmp_path / "a.docx"
    subprocess.run(["pandoc", str(source), "-o", str(document)], check=True)

    assert "Capped at 40 mg." in _docx_part(document, "word/footnotes.xml")
    assert list(paragraph_text(document).values()) == ["Doses were capped."]


@needs_pandoc
@BUILDS
@pytest.mark.parametrize(
    "wrap",
    [
        pytest.param("\nevery participant.", id="plain"),
        pytest.param("\n    every participant.", id="indented"),
        pytest.param("\nin the first cohort,\nand in every participant.", id="three-lines"),
    ],
)
def test_a_wrapped_footnote_is_left_for_pandoc_to_read(
    mark: bool, wrap: str, tmp_path: Path
) -> None:
    """Round ten: a footnote hard-wrapped over its lines works on main, where #25 leaves any
    block opening `[label]:` alone, and this rule marked it for its second line, so it
    printed as text, and `[^cap]` with it, on every build. Pandoc takes the lines under a
    footnote's label into the note, and so does the rule now."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text, tag

    source = tmp_path / "a.md"
    text = f"Doses were capped.[^cap]\n\n[^cap]: Capped at 40 mg in{wrap}\n\nAfter.\n"
    source.write_text(tag(text, "main.md", mark=mark), encoding="utf-8")
    document = tmp_path / "a.docx"
    subprocess.run(["pandoc", str(source), "-o", str(document)], check=True)

    assert "every participant." in _docx_part(document, "word/footnotes.xml")
    assert list(paragraph_text(document).values()) == ["Doses were capped.", "After."]


@needs_pandoc
def test_a_comment_opened_in_a_note_hides_nothing_after_it() -> None:
    """Round ten, on main too: `_blocks` followed a `<!--` in a footnote's text to the next
    `-->`, and left every paragraph in between unmarked, while pandoc reads a note's text by
    itself and printed them all. A strict definition is not read for raw content now."""
    import json
    import subprocess

    from manuscript_guard.roundtrip import tag

    text = (
        "Doses were capped.[^cap]\n\n[^cap]: Capped per protocol <!-- check the dose\n\n"
        "The first result paragraph.\n\nA later one, with a comment <!-- ok --> in it.\n"
    )
    read = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=tag(text, "main.md"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    paragraphs = [json.dumps(b) for b in json.loads(read.stdout)["blocks"] if b["t"] == "Para"]
    assert len(paragraphs) == 3
    assert all("mg-p-" in paragraph for paragraph in paragraphs)


@needs_pandoc
@pytest.mark.parametrize(
    "note",
    [
        pytest.param("[^cap]: Capped at 40 mg.\n[^b c] was a draft label.", id="spaced-label"),
        pytest.param("[^cap]: Capped at 40 mg.\n[^ b]: was a draft label.", id="spaced-caret"),
        pytest.param("[^cap]: Capped at 40 mg.\n\t[^b]: after a tab.", id="tab"),
        pytest.param("[^cap]: Capped at 40 mg.\n    [^b]: indented four.", id="indented"),
        pytest.param("[^cap]: Capped at 40 mg.\n[^] with no label.", id="empty-label"),
        pytest.param("[^cap]: Capped at 40 mg.\n[^b[c] with a bracket.", id="bracket"),
        pytest.param("[^cap]: Capped at 40 mg.\n[^^] with a caret.", id="caret"),
        pytest.param("[^cap]: Capped at 40 mg in\nrenal impairment,\n~ 0.3 mg/kg.", id="tilde"),
        pytest.param("[^cap]: Capped at 40 mg in\nrenal impairment,\n: 0.3 mg/kg.", id="colon"),
    ],
)
def test_a_note_takes_in_every_line_pandoc_takes_in(note: str, tmp_path: Path) -> None:
    """Round eleven: pandoc ends a note only at a line opening a note's marker - `[^`, then
    no space, tab, caret or bracket, then `]` - and a definition list's `:` or `~` changes a
    note only directly under its label. The rule refused more, so each of these notes was
    marked, and printed as text with `[^cap]`, where it works on main."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text, tag

    source = tmp_path / "a.md"
    text = f"Doses were capped.[^cap]\n\n{note}\n\nAfter.\n"
    source.write_text(tag(text, "main.md"), encoding="utf-8")
    document = tmp_path / "a.docx"
    subprocess.run(["pandoc", str(source), "-o", str(document)], check=True)

    assert "Capped at 40 mg" in _docx_part(document, "word/footnotes.xml")
    assert list(paragraph_text(document).values()) == ["Doses were capped.", "After."]


@needs_pandoc
@pytest.mark.parametrize(
    "line",
    [
        pytest.param("[^b] was typed after it.", id="marker"),
        pytest.param("   [^b] was typed after it.", id="indented-three"),
        pytest.param("[^b`c] was typed after it.", id="backtick"),
        pytest.param("[^b]\twas typed after it.", id="tab-after"),
        pytest.param(f"[^b{chr(0xA0)}c] was typed after it.", id="no-break-space"),
    ],
)
def test_a_line_that_ends_a_note_is_not_taken_into_it(line: str) -> None:
    """Pandoc ends a note at a line opening a note's marker, with a colon or without, and
    prints that line in the body. It must reach the document with an identifier."""
    import json
    import subprocess

    from manuscript_guard.roundtrip import tag

    text = f"Doses were capped.[^cap]\n\n[^cap]: Capped at 40 mg.\n{line}\n\nAfter.\n"
    read = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=tag(text, "main.md"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    paragraphs = [json.dumps(b) for b in json.loads(read.stdout)["blocks"] if b["t"] == "Para"]
    assert any('"typed"' in paragraph for paragraph in paragraphs)
    assert all("mg-p-" in paragraph for paragraph in paragraphs)


@needs_pandoc
@pytest.mark.parametrize(
    "note",
    [
        pytest.param("[^cap]: Capped per protocol <!-- check the dose\n:::", id="div-fence-last"),
        pytest.param("[^cap]: Capped per protocol\n:::\n<!-- check the dose", id="div-fence"),
        pytest.param("[^cap]: Capped per protocol <!-- check the dose\n:", id="bare-colon"),
        pytest.param("[^cap]: Capped per protocol\n~\n<pre>", id="bare-tilde"),
    ],
)
def test_a_note_over_a_line_it_may_end_at_hides_nothing_after_it(note: str) -> None:
    """Round eleven, found refusing these lines: a `:::` line is more of a note outside a
    fenced div, and a bare `:` or `~` under the label makes it a term. Either way pandoc
    reads a `<!--` or a `<pre>` there by itself. Refused, the block was read for raw content,
    and the opener hid the paragraphs below, which pandoc prints."""
    import json
    import subprocess

    from manuscript_guard.roundtrip import tag

    text = (
        f"Doses were capped.[^cap]\n\n{note}\n\n"
        "The first result paragraph.\n\nA later one, closing --> it.\n\nThe last.\n"
    )
    read = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=tag(text, "main.md"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    paragraphs = [json.dumps(b) for b in json.loads(read.stdout)["blocks"] if b["t"] == "Para"]
    assert len(paragraphs) == 4
    assert all("mg-p-" in paragraph for paragraph in paragraphs)


@needs_pandoc
def test_a_comment_opened_in_a_link_title_hides_nothing_after_it() -> None:
    """Round eleven's gap: a strict link's title is read by itself too. A `<!--` in it opens
    nothing beyond the definition."""
    import json
    import subprocess

    from manuscript_guard.roundtrip import tag

    text = (
        f"See [the registry][reg].\n\n[reg]: {REGISTRY} \"Registry <!-- draft\"\n\n"
        "The first result paragraph.\n\nA later one, with a comment <!-- ok --> in it.\n"
    )
    read = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=tag(text, "main.md"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    paragraphs = [json.dumps(b) for b in json.loads(read.stdout)["blocks"] if b["t"] == "Para"]
    assert len(paragraphs) == 3
    assert all("mg-p-" in paragraph for paragraph in paragraphs)


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
    # A footnote's label decides it: pandoc takes the lines under it into the note.
    pytest.param("[^cap]: Capped at 40 mg,\nor 20 mg.", DEFINITION, id="note-lines"),
    pytest.param("[^cap]: Capped at 40 mg,\n    or 20 mg.", DEFINITION, id="note-indented-lines"),
    pytest.param("[^cap]: Capped at 40 mg:\n- or 20 mg.", DEFINITION, id="note-with-a-dash-line"),
    # Definitions in a shape pandoc could read another way.
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


@BUILDS
@pytest.mark.parametrize(("block", "reads"), BLOCKS)
def test_only_a_block_of_definitions_is_left_without_an_identifier(
    block: str, reads: str, mark: bool
) -> None:
    """A paragraph keeps its identifier however it opens: with a bracket, with a citation and
    a colon, or with a line pandoc would swallow as a definition."""
    from manuscript_guard.roundtrip import tag

    tagged = tag(block, "main.md", mark=mark)
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


@pytest.mark.parametrize(
    "space",
    [chr(0xA0), chr(0x3000), chr(12), chr(0x2028)],
    ids=["no-break", "full-width", "form-feed", "line-separator"],
)
def test_a_definition_under_a_line_pandoc_does_not_take_for_blank_is_no_definition(
    space: str,
) -> None:
    """A line holding only a no-break or full-width space, or a form feed, separates blocks
    in `tag` and not to pandoc, which reads it and the definition under it as a paragraph.
    `_blocks` leaves both sides of such a line unmarked on its own account; the definition
    rule must not be what does it, or it would still do it if that rule were relaxed."""
    from manuscript_guard.roundtrip import _definitions

    assert not _definitions(f"[reg]: {REGISTRY}", f"\n\n{space}\n", "\n\nIt")
    assert _definitions(f"[reg]: {REGISTRY}", "\n\n", "\n\nIt")


@needs_pandoc
@pytest.mark.parametrize(
    "space", [chr(0xA0), chr(0x3000), chr(12)], ids=["no-break", "full-width", "form-feed"]
)
def test_a_definition_under_an_empty_line_below_a_line_of_spaces_is_left_alone(
    space: str, tmp_path: Path
) -> None:
    """Only the line directly above counts. With such a line and then an empty one, the
    definition starts a block to pandoc; judged by the whole run, it was marked, printed as
    text, and its link resolved nowhere."""
    import subprocess

    from manuscript_guard.roundtrip import tag

    text = f"See [reg] for details.\n\n{space}\n\n[reg]: {REGISTRY}\n"
    tagged = tag(text, "main.md")
    assert tagged.endswith(f"\n\n[reg]: {REGISTRY}\n"), tagged
    source = tmp_path / "a.md"
    source.write_text(tagged, encoding="utf-8")
    subprocess.run(["pandoc", str(source), "-o", str(tmp_path / "a.docx")], check=True)
    rels = _docx_part(tmp_path / "a.docx", "word/_rels/document.xml.rels")
    assert f'Target="{REGISTRY}"' in rels


@needs_pandoc
@pytest.mark.parametrize(
    ("between", "runs_on"),
    [
        pytest.param(f"\n{chr(0xA0)}\n", True, id="no-break"),
        pytest.param(f"\n{chr(0x3000)}\n", True, id="full-width"),
        pytest.param(f"\n{chr(12)}\n", True, id="form-feed"),
        pytest.param(f"\n\n    {chr(0xA0)}\n", True, id="indented-no-break"),
        pytest.param(f"\n\n\t{chr(0x3000)}\n", True, id="tab-full-width"),
        pytest.param(f"\n\n{chr(0xA0)}\n", False, id="blank-then-no-break"),
        pytest.param(f"\n\n   {chr(0xA0)}\n", False, id="blank-then-three-spaces"),
        pytest.param(f"\n\n    {chr(0xA0)}\n\n", False, id="indented-no-break-between-blanks"),
    ],
)
def test_no_identifier_goes_into_a_note_over_a_line_pandoc_does_not_take_for_blank(
    between: str, runs_on: bool
) -> None:
    """A note runs on through every line pandoc does not take for blank, and past a blank
    line into an indented one. Under a line holding only a no-break or full-width space -
    directly, or indented after a blank line - the next paragraph went into the footnote,
    and its identifier with it, where `import` never looks. `_blocks` leaves both sides of
    such a line unmarked; the note rule declines such a note on its own account too."""
    import json
    import subprocess

    from manuscript_guard.roundtrip import _around, _definitions, tag

    text = f"Doses were capped.[^cap]\n\n[^cap]: Capped at 40 mg.{between}It was rare.\n"
    pieces = re.split(r"(\n\s*\n)", text)
    note = next(i for i, piece in enumerate(pieces) if piece.startswith("[^cap]"))
    assert _definitions(pieces[note], *_around(pieces, note)) is not runs_on
    read = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=tag(text, "main.md"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    blocks = json.loads(read.stdout)["blocks"]
    notes: list[dict] = []

    def gather(node: object) -> None:
        if isinstance(node, dict):
            if node.get("t") == "Note":
                notes.append(node)
            for value in node.values():
                gather(value)
        elif isinstance(node, list):
            for value in node:
                gather(value)

    gather(blocks)
    assert not any("mg-p-" in json.dumps(note) for note in notes), "an identifier went in"
    # Where the rule says the note ends, pandoc must agree: the paragraph stays in the body.
    assert runs_on or not any("rare" in json.dumps(note) for note in notes)


@needs_pandoc
@pytest.mark.parametrize(
    "indented",
    [
        pytest.param(f"    {chr(0x200B)}", id="zero-width-space"),
        pytest.param(f"\t{chr(0x2060)}", id="tab-word-joiner"),
        pytest.param(f"  \t{chr(0xFEFF)}", id="spaces-tab-byte-order-mark"),
        pytest.param(f"    {chr(0xAD)}", id="soft-hyphen"),
        pytest.param("    More about it.\n", id="second-paragraph"),
    ],
)
def test_a_note_over_an_indented_block_prints_as_text(indented: str) -> None:
    """After a blank line, a line indented four columns is the note's next paragraph, and
    the unindented lines under it are more of it. A zero-width character is no whitespace
    to Python, so a line holding only one, indented, opened the next block; the note went
    unmarked, and the paragraph under that line left the body for the footnote with nothing
    to show. The note is now marked, and prints as text. Visible, not mended: pandoc sets
    the indented line apart as code, and a paragraph straight under it has no identifier.
    A note of several paragraphs is marked the same way."""
    import json
    import subprocess

    from manuscript_guard.roundtrip import tag

    text = f"Doses were capped.[^cap]\n\n[^cap]: Capped at 40 mg.\n\n{indented}\nIt was rare.\n"
    tagged = tag(text, "main.md")
    assert re.search(r"\[\]\{#mg-p-[^}]+\}\[\^cap\]:", tagged)
    read = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=tagged,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    shown = read.stdout
    assert '"t":"Note"' not in shown.replace(" ", "")
    paragraphs = [json.dumps(b) for b in json.loads(shown)["blocks"] if b["t"] == "Para"]
    assert any("Capped" in paragraph and "mg-p-" in paragraph for paragraph in paragraphs)
    assert any("rare" in paragraph for paragraph in paragraphs)


@needs_pandoc
@pytest.mark.parametrize(
    "between",
    [
        pytest.param("\n\n", id="empty-line"),
        pytest.param("\n\n   ", id="next-indented-three"),
        pytest.param("\n  \n\n", id="spaces-then-empty"),
        pytest.param("\n\n\t\n", id="tab-only-line"),
    ],
)
def test_a_note_a_blank_line_ends_is_left_alone(between: str) -> None:
    """The direction whose failure is silent, judged by pandoc: a note left unmarked must be
    a note, and what follows it must stay in the body with its identifier. A blank line ends
    a note unless the line after it is indented four columns."""
    import json
    import subprocess

    from manuscript_guard.roundtrip import tag

    text = f"Doses were capped.[^cap]\n\n[^cap]: Capped at 40 mg.{between}It was rare.\n"
    tagged = tag(text, "main.md")
    assert "\n\n[^cap]: Capped at 40 mg." in tagged
    read = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=tagged,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    blocks = json.loads(read.stdout)["blocks"]
    notes: list[str] = []

    def gather(node: object) -> None:
        if isinstance(node, dict):
            if node.get("t") == "Note":
                notes.append(json.dumps(node))
            for value in node.values():
                gather(value)
        elif isinstance(node, list):
            for value in node:
                gather(value)

    gather(blocks)
    assert any("Capped" in note for note in notes)
    assert not any("rare" in note for note in notes)
    paragraphs = [json.dumps(b) for b in blocks if b["t"] == "Para"]
    assert any("rare" in paragraph and "mg-p-" in paragraph for paragraph in paragraphs)


@needs_pandoc
@pytest.mark.parametrize("lead", ["\t", "    "], ids=["tab", "four-spaces"])
def test_a_note_ending_a_file_does_not_take_in_the_next_file(project: Path, lead: str) -> None:
    """Review of #64: `tag` judges a note by the end of its own file, where nothing follows,
    and the build joined the files with blank lines alone. A note ending one file then took
    in the next file's first paragraph when that opened indented, and a co-author's edit to
    it was dropped with nothing said. An empty div between files ends it; the paragraph is
    code to pandoc then, as any block opening indented is."""
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text(encoding="utf-8").replace("None declared.", "None declared.[^end]")
    main_md.write_text(f"{text.rstrip()}\n\n[^end]: A closing note.\n", encoding="utf-8")
    (project / "manuscript" / "zz_extra.md").write_text(
        f"{lead}Extra paragraph from the next file.\n", encoding="utf-8"
    )

    document = built(project)
    notes = _docx_part(document, "word/footnotes.xml")
    assert "A closing note." in notes
    assert "Extra paragraph" not in notes
    assert "Extra paragraph" in _docx_part(document, "word/document.xml")


@needs_pandoc
def test_a_comment_left_open_hides_nothing_past_its_file(project: Path) -> None:
    """Round nine: the files were first joined with a comment, and its `-->` closed a `<!--`
    left open earlier in the file, so every paragraph after it in that file vanished from
    the document, with nothing reported. Joined by an empty div, they print, the stray
    `<!--` with them, as they did before."""
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text(encoding="utf-8").rstrip()
    main_md.write_text(
        f"{text}\n\nPara two <!-- to check later\n\nPara three stays.\n", encoding="utf-8"
    )
    (project / "manuscript" / "zz_extra.md").write_text("Next file.\n", encoding="utf-8")

    body = _docx_part(built(project), "word/document.xml")
    assert "Para three stays." in body
    assert "Next file." in body


def test_tag_and_tagged_paragraphs_name_the_same_blocks(project: Path) -> None:
    """`tag` marks the document and `tagged_paragraphs` names what `import` looks up. Read
    from the stripped block in one and the raw block in the other, a definition ending in a
    no-break space was marked in the document and unknown on disk; so it would be if one
    of them stopped asking what stands above a definition."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.roundtrip import tag, tagged_paragraphs

    text = "\n\n".join(param.values[0] for param in BLOCKS)
    text += f"\n\n{chr(0x3000)}\n\n[later]: {REGISTRY}"
    text += f"\n\n{chr(0x3000)}\n[late]: {REGISTRY}"
    text += f"\n\n[^runs]: A note.\n{chr(0xA0)}\nIt runs on.\n"
    text += f"\n\n[^deep]: A note.\n\n    {chr(0xA0)}\nIt runs on."
    text += f"\n\n[^zero]: A note.\n\n    {chr(0x200B)}\nIt runs on."
    text += f"\n\n[^ends]: A note.\n\n{chr(0xA0)}\nIt starts afresh.\n"
    (project / "manuscript" / "definitions.md").write_text(text, encoding="utf-8")
    loaded, _report = load_project(project)
    known = {
        name
        for name, (path, _text, _start) in tagged_paragraphs(loaded).items()
        if path.name == "definitions.md"
    }
    tagged = tag(text, "definitions.md")
    marked = set(re.findall(r"\[\]\{#(mg-p-[^}]+)\}", tagged))
    assert marked == known
    # Every block of `BLOCKS` is marked as it is on its own - a `<!--` in one note's text hid
    # sixteen blocks after it - but the last, beside the full-width space that follows it;
    # and of the notes after, only the one over an indented zero-width space.
    alone = sum(reads != DEFINITION for _block, reads in (p.values for p in BLOCKS))
    last = BLOCKS[-1].values[0]
    assert len(marked) == alone - (tag(last, "definitions.md") != last) + 1
    # Beside a line pandoc does not take for blank nothing is marked, the definitions and
    # notes there included; the note over a blank line and an indented zero-width space runs
    # on into it, and is marked.
    for untouched in ("[later]", "[late]", "[^runs]", "[^deep]", "[^ends]"):
        assert f"}}{untouched}" not in tagged, untouched
    assert re.search(r"\[\]\{#mg-p-[^}]+\}\[\^zero\]", tagged)


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
    "yaml opening on a comment": "---\n# a comment\nkey: value\n\nother: value\n...",
    "yaml opening on a quoted key": '---\n"key": value\n\nother: value\n...',
    "yaml closing in the middle of a block": (
        "---\ntitle: x\n\nsubtitle: y\n\nabstract: z\n---\nPara A right after."
    ),
    "yaml closing on dots in the middle of a block": (
        "---\ntitle: x\n\nsubtitle: y\n\nabstract: z\n...\nPara A right after."
    ),
    "yaml that is not a mapping, which pandoc reads as prose": (
        "---\n# Afterword\n\nThe signal was strong.\n\nIt held, and then\n..."
    ),
    "yaml with an impossible date": "---\ndate: 2026-02-30\n\nnote: revised\n...",
    "yaml example inside a comment before real yaml": (
        "<!--\n---\nk: v\n\nj: w\n-->\n\n---\ntitle: x\n\nsubtitle: y\n..."
    ),
    "yaml pandoc gives up on, stopping on a later yaml opener": (
        "---\nText under.\n\n------\n\nMore.\n\n---\ntitle: x\n\nsubtitle: y\n..."
    ),
    "yaml given up on whose stop of dots opens a block": (
        "---\n- item\n\n...\nMore.\n\nAfter the list.\n\n---\ntitle: x\n..."
    ),
    "a rule over text, then a headed table's underline with rows under it": (
        "---\nText under.\n\nPara A.\n\n  Drug     Signal\n--------  --------\n"
        "Warfarin  Bleeding\n\nAfter the table.\n\nMethods\n-------"
    ),
    "yaml given up on, stopping on a yaml opener, then a later rule": (
        "---\nText under.\n\nPara A.\n\n---\ntitle: x\n...\n\nPara C.\n\n-----"
    ),
    "a rule over text, then a line of two dashes": "---\nText under.\n\nPara A.\n\n--",
    "a one-block headless table with its caption straight under, then a setext heading": (
        "----------  ----------\nWarfarin    Bleeding\nApixaban    Bleeding\n"
        "----------  ----------\nTable: Signals.\n\nWe found two.\n\nBoth bleed.\n\n"
        "Discussion\n----------"
    ),
    "first column one dash wide": (
        "- ---------- ----------\n#  Drug       Signal\n- ---------- ----------\n"
        "1  Warfarin   Bleeding\n\n2  Apixaban   Bleeding\n\n3  Heparin    HIT\n"
        "- ---------- ----------"
    ),
    "headless, first column one dash wide": (
        "-   ----------  ----------\na   Warfarin    Bleeding\n\nb   Apixaban    Bleeding\n\n"
        "c   Heparin     HIT\n-   ----------  ----------"
    ),
    "a table opened by two dashes, then a setext heading": (
        "--\nA note.\n\nPara A.\n\nMethods\n-------"
    ),
    "a multiline table with a paragraph straight under its closing rule": (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------\nListed above."
    ),
    "yaml longer than four thousand characters": (
        "---\ntitle: x\nabstract: |\n  " + "\n\n  ".join(["word " * 300] * 4) + "\n..."
    ),
    "yaml example inside a code fence before real yaml": (
        f"{FENCE}\n\n---\nk: v\n\nj: w\n{FENCE}\n\n---\ntitle: x\n\nsubtitle: y\n..."
    ),
    "a table whose header has a colon, with a row of dots": (
        "---\nRatio (a:b)    Value\n-------------- -----\nFirst          1.2\n\n"
        "Second         2.3\n...\n\nThird          3.4\n\nFourth         4.5\n"
        "--------------------"
    ),
    "a table whose header starts with a hash, with a row of dots": (
        "---\n# of reports   Value\n-------------- -----\nFirst          1.2\n\n"
        "Second         2.3\n...\n\nThird          3.4\n\nFourth         4.5\n"
        "--------------------"
    ),
    "a row reading dots": (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n"
        "            ...\n\nApixaban   Bleeding\n\nHeparin    HIT\n---------- ----------"
    ),
    "a top rule over a line holding only a no-break space": (
        "----------  ----------\n\N{NO-BREAK SPACE}\n----------  ----------\n"
        "Warfarin    Bleeding\n\nApixaban    Bleeding\n\nHeparin     HIT\n"
        "----------  ----------"
    ),
    "a table, a line of dashes that opens nothing, then text": (
        "----------  ----------\nWarfarin    Bleeding\n\nApixaban    Bleeding\n\n"
        "Heparin     HIT\n----------  ----------\n----------\nText after."
    ),
    **{
        f"a table straight under {name}": (
            f"{above}\n----------  ----------\nWarfarin    Bleeding\n\nApixaban    Bleeding\n\n"
            f"Heparin     HIT\n----------  ----------{closer}"
        )
        for name, above, closer in (
            ("a div fence", "::: {#tbl-a}", "\n:::"),
            ("an ATX heading", "## Table 1", ""),
            ("an HTML comment", "<!-- the signals -->", ""),
            ("a div tag", '<div class="x">', "\n</div>"),
            ("a setext heading", "Table 1\n=======", ""),
            ("a setext heading underlined with dashes", "Table 1\n-------", ""),
            ("a code block", f"{FENCE}\ncode\n{FENCE}", ""),
            ("a yaml block", "---\ntitle: x\n---", ""),
            ("a pipe table", "| a | b |\n|---|---|\n| 1 | 2 |", ""),
            ("a yaml block closed by dots", "---\ntitle: x\n...", ""),
            ("a comment's closing line", "<!-- a\nnote -->", ""),
            ("the end of an environment", "\\begin{landscape}\n\\end{landscape}", ""),
            ("a grid table", "+---+---+\n| a | b |\n+---+---+", ""),
            ("a pipe table without outer pipes", "a | b\n--|--\n1 | 2", ""),
            ("a heading of seven hashes", "####### x", ""),
        )
    },
    # A single run of dashes opens a table here too, where under a heading it is a setext
    # underline.
    **{
        f"a one-column table straight under {name}": (
            f"{above}\n----------\nWarfarin\n\nApixaban\n\nHeparin\n----------{closer}"
        )
        for name, above, closer in (
            ("a div tag", '<div class="x">', "\n</div>"),
            ("a comment's closing line", "<!-- a\nnote -->", ""),
            ("the end of an environment", "\\begin{landscape}\n\\end{landscape}", ""),
            ("a pipe table without outer pipes", "a | b\n--|--\n1 | 2", ""),
            ("a code block", f"{FENCE}\ncode\n{FENCE}", ""),
        )
    },
    "a table opening in the block where another ends, under a heading": (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n---------- ----------\n## Table 2\n----------  ----------\n"
        "Rivaroxaban Bleeding\n\nEdoxaban    Bleeding\n\nDabigatran  Bleeding\n"
        "----------  ----------"
    ),
    "two table divs back to back": (
        "::: {#tbl-a}\n----------  ----------\nWarfarin    Bleeding\n\nApixaban    Bleeding\n"
        "----------  ----------\n:::\n::: {#tbl-b}\n----------  ----------\nHeparin     HIT\n\n"
        "Edoxaban    Bleeding\n\nDabigatran  Bleeding\n----------  ----------\n:::"
    ),
    "a table opening in the block where another ends, under a comment": (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n---------- ----------\n<!-- next -->\n----------  ----------\n"
        "Heparin     HIT\n\nEdoxaban    Bleeding\n\nDabigatran  Bleeding\n"
        "----------  ----------"
    ),
    "a table straight under yaml that holds a blank line": (
        "---\ntitle: x\n\nsubtitle: y\n---\n----------  ----------\nWarfarin    Bleeding\n\n"
        "Apixaban    Bleeding\n\nHeparin     HIT\n----------  ----------"
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
    assert re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tagged) == ["Before.", "After."], tagged


def test_yaml_closed_in_its_own_block_hides_nothing_after_it() -> None:
    """A YAML block that ends in the block it opened has nothing after it to hide. Read as
    left open, it fell back to the next line of dashes, and the paragraphs up to a setext
    heading lost their identifiers."""
    from manuscript_guard.roundtrip import tag

    text = "Intro.\n\n---\ntitle: x\n...\n\nPara one.\n\nPara two.\n\nMethods\n-------\n\nP3.\n"
    marked = re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tag(text, "main.md"))
    assert marked == ["Intro.", "Para", "Para", "P3."]
    # Nothing but a comment, or a null, is empty metadata to pandoc, not something it gives
    # up on.
    for body in ("# a private note", "null", "~"):
        note = f"Intro.\n\n---\n{body}\n...\n\nPara one.\n\nPara two.\n\nResults\n-------\n"
        marked = re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tag(note + "\nAfter.\n", "main.md"))
        assert marked == ["Intro.", "Para", "Para", "After."], body


def test_a_no_break_space_line_away_from_a_rule_does_not_stretch_a_table() -> None:
    """Only a no-break-space line straight under a block's last line is text after it. One
    further down counted too, and a paragraph pandoc reads as a paragraph lost its
    identifier to a table that had already ended."""
    from manuscript_guard.roundtrip import tag

    text = (
        "Intro.\n\n----------  ----------\nWarfarin    Bleeding\n----------  ----------\n\n"
        " \nPara A.\n\nPara B.\n\nHead\n----\n\nEnd.\n"
    )
    marked = re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tag(text, "main.md"))
    assert "Para" in marked and "End." in marked, marked


def test_a_line_of_dashes_under_prose_or_a_list_item_opens_no_table() -> None:
    """Mid-block, pandoc opens a table straight under a heading or a fence, but not under
    prose, a list item, a quote, a definition, a caption, a TeX command, an image or a
    one-line reference definition, and not under a heading or a one-line comment when the
    dashes are a single run: that is a setext underline. The rows after such a line are
    paragraphs to pandoc, and keep their identifiers."""
    from manuscript_guard.roundtrip import tag

    two_runs, one_run = "----------  ----------", "----------"
    for above, rule in (
        ("Some text.", two_runs),
        ("P(A|B) was high.", two_runs),
        ("- item", two_runs),
        ("> quoted", two_runs),
        ("Term\n:   definition", two_runs),
        ("Table: Signals.", two_runs),
        ("\\newpage", two_runs),
        ("![Figure](f.png)", two_runs),
        ("[a]: https://example.org", two_runs),
        ("## Title", one_run),
        ("<!-- a note -->", one_run),
    ):
        text = (
            f"Intro.\n\n{above}\n{rule}\nWarfarin    Bleeding\n\n"
            f"Apixaban    Bleeding\n\nHeparin     HIT\n{rule}\n\nAfter.\n"
        )
        marked = re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tag(text, "main.md"))
        assert "Apixaban" in marked, (above, marked)


def test_a_span_ending_in_a_table_s_first_block_still_hides_its_rows() -> None:
    """A line taken for a table's opener that pandoc does not read as one starts a span
    pandoc does not have. Run on to the next table, it ended on that table's header
    underline, and the block it ended in was read only for tables opening further down it,
    not on its own first line: the real table went unfollowed and its rows were marked.
    The block a span ends in is now read as any block is, below its first line when it
    starts inside code. DESIGN.md lists the layouts this still misses."""
    from manuscript_guard.roundtrip import tag

    headed = (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------"
    )
    for before in (
        "|x| was large.\n----------  ----------\nText.",
        "Text\n...\n----------  ----------\nMore.",
        "Results <!-- to check -->\n-----------------------------\nWe found three signals.",
        "The flow was A -->\n----------  ----------\nx  y",
        "Text\n++\n----------\nMore.",
    ):
        # The table under a caption, or straight under the close of code with a blank
        # line in it, where the block the span ends in starts inside the code.
        for between in ("Table: Signals.\n\n", f"{FENCE}r\nx <- 1\n\ny <- 2\n{FENCE}\n"):
            text = f"Intro.\n\n{before}\n\n{between}{headed}\n\nAfter.\n"
            marked = re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tag(text, "main.md"))
            assert "Apixaban" not in marked and "Heparin" not in marked, (before, marked)


def test_code_that_looks_like_an_opener_hides_nothing_after_its_close() -> None:
    """A block that starts inside code is read for tables opening below its first line,
    not on it: that line is code, and read as an opener it hid the paragraphs after the
    code down to the next line of dashes. A code line further down that looks like one
    still counts, which only hides more."""
    from manuscript_guard.roundtrip import tag

    text = (
        f"Intro.\n\n{FENCE}yaml\n\n---\n- a\n{FENCE}\nNote under the code.\n\nPara A.\n\n"
        "Para B.\n\n----------  ----------\nrow a  row b\n----------  ----------\n\nAfter.\n"
    )
    marked = re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tag(text, "main.md"))
    assert marked.count("Para") == 2, marked


def test_a_rule_with_a_blank_line_under_it_opens_nothing() -> None:
    """A table and a YAML block both need text straight under their first line, so a line
    of dashes with a blank line under it is a rule to pandoc. Taken for an opener, a lone
    `---` hid every paragraph up to the next line of dashes, and put a marker into the rows
    of a table after it; straight under a table, it chained into the next table."""
    from manuscript_guard.roundtrip import tag

    table = (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------"
    )
    for rule in ("---", "----------", "- - -"):
        for after in ("Methods\n-------", table):
            text = f"Intro.\n\n{rule}\n\nPara A.\n\nPara B.\n\n{after}\n\nEnd.\n"
            marked = re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tag(text, "main.md"))
            assert marked == ["Intro.", "Para", "Para", "End."], (rule, after, marked)
    text = (
        "Intro.\n\n----------  ----------\nWarfarin    Bleeding\n----------  ----------\n"
        f"----------\n\nPara A.\n\n{table}\n\nEnd.\n"
    )
    marked = re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tag(text, "main.md"))
    assert marked == ["Intro.", "Para", "End."], marked


def test_yaml_after_a_blank_first_line_is_recognised() -> None:
    """Pandoc skips blank lines before a file's first block; the check read the blank line
    as the block's first line, never saw the `---`, and marked a paragraph of the YAML."""
    from manuscript_guard.roundtrip import tag

    tagged = tag("\n---\ntitle: x\n\nabstract: y\n...\n\nIntro.\n", "main.md")
    assert re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tagged) == ["Intro."], tagged


def test_deeply_nested_yaml_does_not_crash_the_tagger() -> None:
    """With nothing capping how much YAML is read, the C loader overflowed the stack on
    thousands of nesting levels and took the interpreter down with no message."""
    from manuscript_guard.roundtrip import tag

    for body in ("note: " + "[" * 6000, "- " * 20000):
        tagged = tag(f"Intro.\n\n---\n{body}\n...\n\nAfter.\n", "main.md")
        assert tagged.count("[]{#mg-p-") == 2


def test_a_table_closed_by_its_caption_does_not_hide_what_follows() -> None:
    """A one-row table with its caption straight under it ends at the caption. Read as
    left open, it paired with the next line of dashes - a setext heading - and every
    paragraph in between lost its identifier."""
    from manuscript_guard.roundtrip import tag

    text = (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n"
        "---------- ----------\nTable: One row.\n\nP1.\n\nP2.\n\nMethods\n-------\n\nP3.\n"
    )
    marked = re.findall(r"\[\]\{#mg-p-[^}]+\}(\S*)", tag(text, "main.md"))
    assert marked == ["P1.", "P2.", "P3."]


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


def _identified(text: str) -> dict[str, bool]:
    """For each of the words Alpha to Omega that pandoc prints in the body of `tag(text)`,
    whether the paragraph holding it carries an identifier. A word inside raw content, which
    prints nothing, is left out."""
    import json
    import subprocess

    from manuscript_guard.roundtrip import tag

    read = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=tag(text, "main.md"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    found: dict[str, bool] = {}
    for block in json.loads(read.stdout)["blocks"]:
        if block["t"] not in ("Para", "Plain"):
            continue
        printed = json.dumps([i for i in block["c"] if i["t"] != "RawInline"])
        for word in ("Alpha", "Beta", "Gamma", "Omega"):
            if word in printed:
                found[word] = "mg-p-" in json.dumps(block)
    return found


BACKSLASH = chr(92)
RAW_OPENERS = [
    pytest.param("<!--", "-->", id="comment"),
    pytest.param(BACKSLASH + "begin{x}", BACKSLASH + "end{x}", id="tex"),
    pytest.param("<pre>", "</pre>", id="pre"),
]


@needs_pandoc
@pytest.mark.parametrize("escapes", [1, 3])
@pytest.mark.parametrize(("opener", "closer"), RAW_OPENERS)
def test_an_escaped_raw_opener_opens_nothing(opener: str, closer: str, escapes: int) -> None:
    """After an odd number of backslashes, `<!--`, `\\begin{x}` or `<pre>` is text to pandoc,
    which prints it; `import` writes a `<!--` typed in Word so. `_blocks` took it for an
    opener all the same, and its paragraph and every one up to the closer went without an
    identifier, so a co-author's edit to them was not compared. On main too."""
    text = (
        f"Alpha {BACKSLASH * escapes}{opener} opens.\n\nBeta in between.\n\n"
        f"Gamma follows.\n\n{closer}\n\nOmega.\n"
    )
    assert _identified(text) == dict.fromkeys(("Alpha", "Beta", "Gamma", "Omega"), True)


@needs_pandoc
@pytest.mark.parametrize("escapes", [0, 2])
@pytest.mark.parametrize(("opener", "closer"), RAW_OPENERS)
def test_a_raw_opener_after_escaped_backslashes_still_opens(
    opener: str, closer: str, escapes: int
) -> None:
    """After an even number, the backslashes escape each other and the opener opens: what
    pandoc hides is not marked, and what follows the closer is."""
    text = (
        f"Alpha {BACKSLASH * escapes}{opener} opens.\n\nBeta in between.\n\n"
        f"Gamma follows.\n\n{closer}\n\nOmega.\n"
    )
    found = _identified(text)
    assert "Beta" not in found and found["Omega"]


@needs_pandoc
def test_an_escaped_tex_closer_closes_nothing() -> None:
    """`\\\\end{x}` is a line break and the word "end" to LaTeX, so it closes no environment,
    and pandoc reads the `\\begin{x}` above it as text. `_blocks` paired the two, and the
    paragraphs between went without an identifier."""
    text = (
        f"Alpha {BACKSLASH}begin{{x}} opens.\n\nBeta in between.\n\n"
        f"Gamma {BACKSLASH * 2}end{{x}} here.\n\nOmega.\n"
    )
    found = _identified(text)
    assert found["Beta"] and found["Gamma"] and found["Omega"]


@needs_pandoc
@pytest.mark.parametrize("escapes", [0, 1, 2])
def test_an_escaped_comment_closer_still_closes(escapes: int) -> None:
    """Inside a comment pandoc reads no escapes: `\\-->` closes it, whatever stands before."""
    text = (
        f"Alpha <!-- opens.\n\nBeta in between.\n\n"
        f"Gamma {BACKSLASH * escapes}--> here.\n\nOmega.\n"
    )
    found = _identified(text)
    assert "Beta" not in found and found["Omega"]


@needs_pandoc
@pytest.mark.parametrize("escapes", [1, 3])
@pytest.mark.parametrize(
    "markup",
    ["<div>", '<div class="x">', "</div>", "<table>", BACKSLASH + "begin{x}"],
    ids=["div", "div-with-class", "div-closer", "table", "tex"],
)
def test_an_escaped_block_tag_leaves_its_paragraph_one(markup: str, escapes: int) -> None:
    """Mid-line, a block-level tag or a LaTeX environment ends a paragraph, so a paragraph
    holding one is left unmarked. Escaped, it is text, and the paragraph is one: `import`
    writes a `<div>` typed in Word so, and the paragraph lost its identifier."""
    text = f"Alpha {BACKSLASH * escapes}{markup} mid-line.\n\nOmega.\n"
    assert _identified(text) == {"Alpha": True, "Omega": True}


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


def unmark(marked: str) -> tuple[str, list[tuple[int, int]]]:
    """A rendering with each token ⟦marked⟧, as the comparison build reports it: the plain
    text, and where each token sits in it."""
    plain: list[str] = []
    spans: list[tuple[int, int]] = []
    at = 0
    for part in re.split(r"(⟦[^⟧]*⟧)", marked):
        if part.startswith("⟦"):
            spans.append((at, at + len(part) - 2))
            part = part[1:-1]
        plain.append(part)
        at += len(part)
    return "".join(plain), spans


def merged(source: str, marked: str, returned: str) -> str | None:
    return merged_alignment(source, marked, returned).rebuilt


def merged_alignment(source: str, marked: str, returned: str):
    """`align`, given a rendering with each token ⟦marked⟧."""
    plain, spans = unmark(marked)
    return align(source, plain, returned, spans)


def test_a_rewording_keeps_every_binding() -> None:
    """The move the paragraph-level merge could not make.

    Splicing returned text into a paragraph carrying a binding would replace it with the
    literal it rendered to. Aligning on the rendered forms rebuilds the paragraph from the
    source's tokens and the co-author's words instead.
    """
    source = "The ratio was {{results.ror.point}} overall [@smith2020]."
    rendered = "The ratio was ⟦3.84⟧ overall ⟦(Smith 2020)⟧."
    out = merged(source, rendered, "The ratio was notably 3.84 overall (Smith 2020).")
    assert out == "The ratio was notably {{results.ror.point}} overall [@smith2020]."


def test_an_edited_number_refuses_the_whole_paragraph() -> None:
    source = "The ratio was {{results.ror.point}} overall."
    assert merged(source, "The ratio was ⟦3.84⟧ overall.", "The ratio was 4.02 overall.") is None


def test_a_removed_citation_refuses_the_paragraph() -> None:
    source = "The ratio was high [@smith2020]."
    assert merged(source, "The ratio was high ⟦(Smith 2020)⟧.", "The ratio was high.") is None


def test_transposed_bounds_are_refused() -> None:
    """Alignment is in order, so bounds that come back swapped cannot both be placed."""
    source = "({{results.ror.ci_low}} to {{results.ror.ci_high}})"
    assert merged(source, "(⟦2.10⟧ to ⟦7.02⟧)", "(7.02 to 2.10)") is None


def test_two_bindings_that_render_the_same_are_paired_in_order() -> None:
    """The collision case again: alignment pairs them up in order rather than matching
    both to the first occurrence."""
    source = "{{results.a}} and {{results.b}}"
    out = merged(source, "⟦1⟧ and ⟦1⟧", "1 and, notably, 1")
    assert out == "{{results.a}} and, notably, {{results.b}}"


def test_unchanged_prose_keeps_its_own_markdown() -> None:
    """Word text loses inline formatting, so only an edited segment is taken from it."""
    source = "The **striking** ratio was {{results.ror.point}} here."
    out = merged(
        source, "The striking ratio was ⟦3.84⟧ here.", "The striking ratio was 3.84 there."
    )
    assert out is not None
    assert "**striking**" in out, "the untouched segment keeps its emphasis"
    assert "there" in out


def test_segments_splits_prose_from_what_the_author_does_not_own() -> None:
    prose, protected = segments("a {{results.x}} b [@key] c @other d")
    assert protected == ["{{results.x}}", "[@key]", "@other"]
    assert len(prose) == len(protected) + 1


def test_a_number_that_grew_a_digit_is_refused() -> None:
    """Substring search found '3.84' inside '13.84' and merged `1{{results.ror.point}}`.

    And a sign or a comparison glued in front changes the value too - including the en and
    em dashes Word's AutoCorrect makes of a hyphen, which merged as `–{{results.ror.point}}`
    and turned a ratio negative in the next build."""
    source = "The ratio was {{results.ror.point}} overall."
    for edited in (
        "13.84", "3.845", "-3.84", "3.84.1",
        "–3.84", "—3.84", "−3.84", "<3.84", "≤3.84", "~3.84", "≈3.84",
    ):
        returned = f"The ratio was {edited} overall."
        assert merged(source, "The ratio was ⟦3.84⟧ overall.", returned) is None, edited


@pytest.mark.parametrize(
    ("source", "named"),
    [
        ("See the [agency report](https://example.org/r) for details.", "a link"),
        ("See the agency report.^[Withdrawn in 2019.] It has details.", "a footnote"),
        ("See the agency report, $n = 3$, for details.", "an equation"),
    ],
    ids=["link", "footnote", "math"],
)
def test_a_paragraph_whose_markup_word_cannot_carry_is_refused(source: str, named: str) -> None:
    """Word's plain text has the link's words but not its address, a footnote's
    reference mark but not its text, and none of an equation. Merging it over the source
    deleted them."""
    from manuscript_guard.merge import why

    rendered = "See the agency report for details."
    aligned = align(source, rendered, "See the agency report for more details.", [])
    assert aligned.rebuilt is None
    assert named in why(aligned)[0]


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        pytest.param(
            "The drug's ratio was {{results.x}} here.",
            "The drug’s ratio was ⟦3.84⟧ here.",
            "The drug’s ratio was 3.84 there.",
            "The drug's ratio was {{results.x}} there.",
            id="apostrophe",
        ),
        pytest.param(
            'The so-called "signal" was {{results.x}} here.',
            "The so-called “signal” was ⟦3.84⟧ here.",
            "The so-called “signal” was 3.84 there.",
            'The so-called "signal" was {{results.x}} there.',
            id="double-quotes",
        ),
        pytest.param(
            "Rates -- and odds --- were {{results.x}} here.",
            "Rates – and odds — were ⟦3.84⟧ here.",
            "Rates – and odds — were 3.84 there.",
            "Rates -- and odds --- were {{results.x}} there.",
            id="dashes",
        ),
        pytest.param(
            "Odds... were {{results.x}} here.",
            "Odds… were ⟦3.84⟧ here.",
            "Odds… were 3.84 there.",
            "Odds... were {{results.x}} there.",
            id="ellipsis",
        ),
        pytest.param(
            "Run with `--offline_mode`, the ratio was {{results.x}} here.",
            "Run with --offline_mode, the ratio was ⟦3.84⟧ here.",
            "Run with --offline_mode, the ratio was 3.84 there.",
            "Run with `--offline_mode`, the ratio was {{results.x}} there.",
            id="code",
        ),
        pytest.param(
            "Per m^2^ and H~2~O, the \\*raw\\* ratio was {{results.x}} here.",
            "Per m2 and H2O, the *raw* ratio was ⟦3.84⟧ here.",
            "Per m2 and H2O, the *raw* ratio was 3.84 there.",
            "Per m^2^ and H~2~O, the \\*raw\\* ratio was {{results.x}} there.",
            id="other-markup",
        ),
        pytest.param(
            "The drug's ratio was {{results.x}} here.",
            "The drug’s ratio was ⟦3.84⟧ here.",
            "The drug's ratio was 3.84 there.",
            "The drug's ratio was {{results.x}} there.",
            id="a-quote-retyped-straight-is-not-an-edit",
        ),
    ],
)
def test_how_pandoc_renders_prose_does_not_stop_a_rewording(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """Pandoc typesets prose - `drug's` reaches Word as `drug’s`, `--` as an en dash - and
    renders its markup. The source's prose was looked for verbatim in the rendered text, so a
    paragraph with a binding and an apostrophe was refused as "could not be lined up". With
    the tokens' extents known, prose is only ever compared with rendered prose."""
    assert merged(source, rendered, returned) == expected


def test_a_value_is_found_in_its_own_place_not_in_the_prose_before_it() -> None:
    """'Table 1 shows 1 events' - the first '1' is prose. Searching for the rendered value
    from the start of the paragraph moved the binding onto the table number and left the
    value behind as a literal."""
    source = "Table 1 shows {{results.x}} events."
    out = merged(source, "Table 1 shows ⟦1⟧ events.", "Table 1 now shows 1 events.")
    assert out == "Table 1 now shows {{results.x}} events."


def test_a_citation_ending_a_paragraph_keeps_its_own_full_stop() -> None:
    """'(Smith et al. 2020).' - the source's last prose piece is '.', and searching for it
    found the one after 'al', so the rest of the citation became prose and merged as
    `[@smith2020]. 2020).`"""
    source = "Earlier work agreed on this point [@smith2020]."
    out = merged(
        source,
        "Earlier work agreed on this point ⟦(Smith et al. 2020)⟧.",
        "Earlier studies agreed on this point (Smith et al. 2020).",
    )
    assert out == "Earlier studies agreed on this point [@smith2020]."


def test_a_value_ending_a_sentence_is_not_cut_at_its_decimal_point() -> None:
    """The same search found the final '.' inside '3.84' and refused the paragraph as
    "'3' comes from results.ror.point" - a value that had not changed, cut in half."""
    source = "The reporting odds ratio was {{results.ror.point}}."
    out = merged(
        source, "The reporting odds ratio was ⟦3.84⟧.", "The odds ratio was 3.84."
    )
    assert out == "The odds ratio was {{results.ror.point}}."


def test_an_edit_inside_a_citation_is_refused_not_merged_as_prose() -> None:
    """'Both (Smith and Jones 2020) and (Lee 2021)': the prose ' and ' was found inside the
    first citation, so a co-author's 'and' -> '&' in the citation merged as prose, between
    the two citations."""
    from manuscript_guard.merge import why

    source = "Both [@a] and [@b] agree."
    plain, spans = unmark("Both ⟦(Smith and Jones 2020)⟧ and ⟦(Lee 2021)⟧ agree.")
    aligned = align(source, plain, "Both (Smith & Jones 2020) and (Lee 2021) agree.", spans)
    assert aligned.rebuilt is None
    assert "[@a]" in " ".join(why(aligned))


def test_a_narrative_citation_is_protected_like_any_other() -> None:
    """`@smith2020` without brackets was not protected at all: in a paragraph with no other
    binding, a rewording merged it back as the plain text "Smith (2020)"."""
    source = "As @smith2020 found, this holds."
    rendered = "As ⟦Smith (2020)⟧ found, this holds."
    assert merged(source, rendered, "As Smith (2020) found, this clearly holds.") == (
        "As @smith2020 found, this clearly holds."
    )
    assert merged(source, rendered, "As Smith (2021) found, this holds.") is None


def test_two_tokens_with_nothing_between_them_are_refused_as_unaligned() -> None:
    """Their extents are known in the build, but Word's text has no seam between '1' and
    '2'. Refused, and not as "'1' comes from results.a", which would say a value that had
    not changed was changed."""

    aligned = align("Values {{results.a}}{{results.b}} here.", "Values 12 here.",
                    "Values 12 there.", [(7, 8), (8, 9)])
    assert aligned.rebuilt is None
    assert aligned.unaligned and not aligned.changed


def test_a_citation_is_its_own_brackets_and_no_more() -> None:
    """The citation pattern started at the first `[` with an `@` before the next `]`, so the
    prose "[low, high) were rescaled as in" became part of a citation token."""
    assert segments("Scores in [low, high) were rescaled as in [@key].")[1] == ["[@key]"]
    assert segments("Nested [see [@smith2020]] here.")[1] == ["[@smith2020]"]


def test_a_citation_keeps_the_brackets_inside_it() -> None:
    """The narrowed pattern could not contain `[`, so `[@key, p. 3 [emphasis added]]`
    matched nothing and an edit merged the citation back as plain text."""
    assert segments("Quoted [@key, p. 3 [emphasis added]] as {{results.a}}.")[1] == [
        "[@key, p. 3 [emphasis added]]",
        "{{results.a}}",
    ]
    assert segments("Per [@who2021, Annex \\[2\\]] here.")[1] == ["[@who2021, Annex \\[2\\]]"]
    assert segments("As @key [p. 33] says, it was {{results.a}}.")[1] == [
        "@key [p. 33]",
        "{{results.a}}",
    ]


@pytest.mark.parametrize(
    "citation",
    [
        "[@2019who]",
        "[@_underkey]",
        "[@Élodie2020]",
        "[@{10.1000/xyz}]",
        "[see @{https://ex.org/a?b=c&d=e}, p. 4]",
        "@2019who",
        "@Élodie2020",
        "@{10.1000/xyz}",
    ],
)
def test_a_key_pandoc_reads_is_a_citation_here_too(citation: str) -> None:
    """Keys were read as starting with an ASCII letter, and pandoc also reads a digit, an
    underscore, any letter and a key in braces. `[@2019who]` stayed in the prose, and a
    rewording beside it merged the citation back as its rendered text."""
    assert segments(f"Rates rose {citation} in all.")[1] == [citation]


@pytest.mark.parametrize(
    ("paragraph", "expected"),
    [
        pytest.param(
            "As shown [@key, table {{results.t}}], it was {{results.x}} here.",
            ["[@key, table {{results.t}}]", "{{results.x}}"],
            id="binding-inside-a-citation",
        ),
        pytest.param(
            "As @key [table {{results.t}}] shows, it was {{results.x}} here.",
            ["@key [table {{results.t}}]", "{{results.x}}"],
            id="binding-in-a-locator",
        ),
        pytest.param(
            "As @key\n[p. 33] says, it was {{results.x}} here.",
            ["@key\n[p. 33]", "{{results.x}}"],
            id="locator-on-the-next-line",
        ),
        pytest.param(
            "As @a [@b] and @c [see @d, p. 4] say, it was {{results.x}}.",
            ["@a [@b]", "@c [see @d, p. 4]", "{{results.x}}"],
            id="narrative-and-bracketed-read-as-one",
        ),
        pytest.param(
            "Run `fit(@cohort)` or <https://www.npmjs.com/package/@zfish/ror> on {{results.x}}.",
            ["{{results.x}}"],
            id="code-and-autolink",
        ),
        pytest.param(
            "Version `v{{results.version}}` was used.",
            ["{{results.version}}"],
            id="binding-in-code",
        ),
    ],
)
def test_tokens_are_what_pandoc_reads_as_one(paragraph: str, expected: list[str]) -> None:
    """A binding inside a citation dropped the citation, which then stayed in the prose and
    refused every edit; `@a [@b]` is one citation to pandoc and was two tokens here, and a
    key in code or an autolink was a token that marking broke. Each refused its paragraph
    for good."""
    assert segments(paragraph)[1] == expected


def test_a_citation_holding_a_binding_takes_a_rewording() -> None:
    source = "As shown [@key, table {{results.t}}], it was {{results.x}} in zebrafish."
    out = merged(
        source,
        "As shown ⟦(Key 2019, table 10)⟧, it was ⟦3.84⟧ in zebrafish.",
        "As shown (Key 2019, table 10), it was 3.84 in all zebrafish.",
    )
    assert out == source.replace("in zebrafish", "in all zebrafish")


@pytest.mark.parametrize(
    ("source", "rendered", "returned"),
    [
        pytest.param(
            "As detailed in [Methods], the ratio was {{results.x}} in zebrafish.",
            "As detailed in Methods, the ratio was ⟦3.84⟧ in zebrafish.",
            "As described in Methods, the ratio was 3.84 in zebrafish.",
            id="header-reference",
        ),
        pytest.param(
            "Values <LLOQ in mg/L and >ULOQ (n = {{results.n}}) were redone.",
            "Values ULOQ (n = ⟦56⟧) were redone.",
            "Values ULOQ only (n = 56) were redone.",
            id="tag-to-pandoc",
        ),
        pytest.param(
            "As per @@key, the ratio was {{results.x}} here.",
            "As per @Key (2019), the ratio was ⟦3.84⟧ here.",
            "As in @Key (2019), the ratio was 3.84 here.",
            id="citation-after-an-at",
        ),
        pytest.param(
            "As per a_@key, the ratio was {{results.x}} here.",
            "As per a_Key (2019), the ratio was ⟦3.84⟧ here.",
            "As in a_Key (2019), the ratio was 3.84 here.",
            id="citation-after-an-underscore",
        ),
    ],
)
def test_an_edited_stretch_the_build_printed_differently_is_refused(
    source: str, rendered: str, returned: str
) -> None:
    """Rebuilt from Word's text, these deleted the link to the heading, the text pandoc read
    as a tag, or the citation. A paragraph with no token was already checked this way; one
    with a token was not, once its extents stopped being found by looking for its prose."""
    assert merged(source, rendered, returned) is None


@pytest.mark.parametrize(
    ("source", "rendered", "returned"),
    [
        pytest.param(
            "It was clear in this cohort. @key reported {{results.x}} here.",
            "It was clear in this cohort. ⟦Key (2019)⟧ reported ⟦3.84⟧ here.",
            "It was clear in the whole cohort.Key (2019) reported 3.84 here.",
            id="full-stop-before-a-key",
        ),
        pytest.param(
            "Both [@a] [@b] found {{results.x}} here.",
            "Both ⟦(A 2019)⟧ ⟦(B 2021)⟧ found ⟦3.84⟧ here.",
            "Both (A 2019)(B 2021) found 3.84 here.",
            id="citations-left-touching",
        ),
        pytest.param(
            "As @a and [@b] found, it was {{results.x}} here.",
            "As ⟦A (2019)⟧ and ⟦(B 2021)⟧ found, it was ⟦3.84⟧ here.",
            "As A (2019) (B 2021) found, it was 3.84 here.",
            id="key-then-bracket-read-as-one",
        ),
        pytest.param(
            "As @a: {{results.x}} was the ratio.",
            "As ⟦A (2019)⟧: ⟦3.84⟧ was the ratio.",
            "As A (2019):3.84 was the ratio.",
            id="key-running-into-a-number",
        ),
        pytest.param(
            "As @a found, it was {{results.x}} here.",
            "As ⟦A (2019)⟧ found, it was ⟦3.84⟧ here.",
            "As A (2019)s found, it was 3.84 here.",
            id="key-running-into-a-word",
        ),
        pytest.param(
            "As @a reported, it was {{results.x}} here.",
            "As ⟦A (2019)⟧ reported, it was ⟦3.84⟧ here.",
            "As A (2019)// reported, it was 3.84 here.",
            id="key-running-into-slashes",
        ),
        pytest.param(
            "As @a reported, it was {{results.x}} here.",
            "As ⟦A (2019)⟧ reported, it was ⟦3.84⟧ here.",
            "As A (2019):/ reported, it was 3.84 here.",
            id="key-running-into-a-colon-and-slash",
        ),
        pytest.param(
            "As @a reported, it was {{results.x}} overall.",
            "As ⟦A (2019)⟧ reported, it was ⟦[pooled]⟧ overall.",
            "As A (2019) [pooled] overall.",
            id="value-read-as-a-locator",
        ),
        pytest.param(
            "As @{10.1000/xyz} reported, it was {{results.x}} overall.",
            "As ⟦X (2019)⟧ reported, it was ⟦[pooled]⟧ overall.",
            "As X (2019) [pooled] overall.",
            id="value-read-as-a-braced-key's-locator",
        ),
        pytest.param(
            "As @a reported, it was {{results.x}} overall.",
            "As ⟦A (2019)⟧ reported, it was ⟦[pooled]⟧ overall.",
            "As A (2019)\t[pooled] overall.",
            id="value-read-as-a-locator-after-a-tab",
        ),
    ],
)
def test_an_edit_that_makes_pandoc_read_a_token_differently_is_refused(
    source: str, rendered: str, returned: str
) -> None:
    """Pandoc reads no citation in `.@key`, reads `[@a][@b]` as a link, `@a [@b]` as one
    citation and `@a:3.84` as the key `a:3.84`. Each edit merged, because the read-back found
    as many tokens as before, and the next build printed a raw key or a garbled citation."""
    assert merged(source, rendered, returned) is None


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        pytest.param(
            "As @a [p. 3] reported, it was {{results.x}} overall.",
            "As ⟦A (2019, 3)⟧ reported, it was ⟦moderate⟧ overall.",
            "As A (2019, 3):moderate overall.",
            "As @a [p. 3]:{{results.x}} overall.",
            id="colon-after-a-key-with-its-locator",
        ),
        pytest.param(
            "As @a [p. 3] reported, it was {{results.x}} overall.",
            "As ⟦A (2019, 3)⟧ reported, it was ⟦[pooled]⟧ overall.",
            "As A (2019, 3) [pooled] overall.",
            "As @a [p. 3] {{results.x}} overall.",
            id="bracketed-value-after-a-key-with-its-locator",
        ),
        pytest.param(
            "As @a reported, it was {{results.x}} overall.",
            "As ⟦A (2019)⟧ reported, it was ⟦[pooled]⟧ overall.",
            "As A (2019)\u00a0[pooled] overall.",
            "As @a\u00a0{{results.x}} overall.",
            id="bracketed-value-after-a-no-break-space",
        ),
    ],
)
def test_an_edit_pandoc_reads_as_word_shows_it_merges(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """The checks above were broader than pandoc, and refused these. A key that has its
    locator ends at the `]`, so nothing after it reads on into the key, and a second bracket
    is no locator: pandoc takes one. Nor is a bracket after a no-break space: pandoc reads a
    locator only after spaces, a tab or one line break."""
    assert merged(source, rendered, returned) == expected


def test_part_of_a_citation_ending_a_paragraph_deleted_is_a_changed_citation() -> None:
    """Cut at "al." by the guessed extents, the citation lost " 2020)" and the rebuild equalled
    the source, so import reported nothing at all."""
    source = "Prior work agreed [@smith2020]."
    plain, spans = unmark("Prior work agreed ⟦(Smith et al. 2020)⟧.")
    aligned = align(source, plain, "Prior work agreed (Smith et al..", spans)
    assert aligned.rebuilt is None
    assert aligned.changed == (("(Smith et al. 2020)", "[@smith2020]"),)


#: Prose that is also inside a token beside it. The extents were once guessed by looking for
#: each stretch of the source's prose, stripped, in the rendered text, where it was first
#: found: the "-" of " - " as the first date's own hyphen, "." as the one after "al", "and"
#: as the one inside the citation. Every edit here was refused on that guess, and each one
#: merges. Pandoc's citeproc prints a plain space after "al."; the U+00A0 case stands for a
#: citation style that prints a no-break space there, which Word's text keeps.
INSIDE_A_TOKEN = [
    pytest.param(
        "The study ran {{results.start}} - {{results.end}} in total.",
        "The study ran ⟦2015-01-01⟧ - ⟦2024-12-31⟧ in total.",
        "The study covered 2015-01-01 - 2024-12-31 in total.",
        "The study covered {{results.start}} - {{results.end}} in total.",
        id="hyphen-in-a-date",
    ),
    pytest.param(
        "The study ran {{results.start}} - {{results.end}} in total.",
        "The study ran ⟦2015-01-01⟧ - ⟦2024-12-31⟧ in total.",
        "The study ran 2015-01-01 to 2024-12-31 in total.",
        "The study ran {{results.start}} to {{results.end}} in total.",
        id="the-hyphen-between-them-edited",
    ),
    pytest.param(
        "Rates of {{results.ci}} - {{results.n}} overall.",
        "Rates of ⟦(1.2-3.4)⟧ - ⟦3.84⟧ overall.",
        "Rates of (1.2-3.4) - 3.84 overall today.",
        "Rates of {{results.ci}} - {{results.n}} overall today.",
        id="hyphen-in-an-interval",
    ),
    pytest.param(
        "Risk rose, as reported [@smith2020].",
        "Risk rose, as reported ⟦(Smith et al. 2020)⟧.",
        "Risk increased, as reported (Smith et al. 2020).",
        "Risk increased, as reported [@smith2020].",
        id="full-stop-in-a-citation",
    ),
    pytest.param(
        "Risk rose, as reported [@smith2020].",
        "Risk rose, as reported ⟦(Smith et al.\u00a02020)⟧.",
        "Risk increased, as reported (Smith et al.\u00a02020).",
        "Risk increased, as reported [@smith2020].",
        id="full-stop-in-a-citation-no-break-space",
    ),
    pytest.param(
        "Risk rose in two cohorts [@lee2021] and {{results.x}} overall.",
        "Risk rose in two cohorts ⟦(Lee, Park, and Kim 2021)⟧ and ⟦3.84⟧ overall.",
        "Risk rose in two cohorts (Lee, Park, and Kim 2021) & 3.84 overall.",
        "Risk rose in two cohorts [@lee2021] & {{results.x}} overall.",
        id="and-beside-a-citation-edited",
    ),
]

#: Edits to a token whose guessed edges were wrong, each named whole.
INSIDE_CHANGED = [
    pytest.param(
        "Risk rose in two cohorts [@lee2021] and {{results.x}} overall.",
        "Risk rose in two cohorts ⟦(Lee, Park, and Kim 2021)⟧ and ⟦3.84⟧ overall.",
        "Risk rose in two cohorts (Lee, Park, & Kim 2021) and 3.84 overall.",
        (("(Lee, Park, and Kim 2021)", "[@lee2021]"),),
        id="and-in-a-citation-edited",
    ),
    pytest.param(
        "The study ran {{results.start}} - {{results.end}} in total.",
        "The study ran ⟦2015-01-01⟧ - ⟦2024-12-31⟧ in total.",
        "The study ran 2015-01-01 - 2024-12-30 in total.",
        (("2024-12-31", "{{results.end}}"),),
        id="a-date-changed",
    ),
]

#: What the build fills each binding in with.
INSIDE_VALUES = {
    "results.start": "2015-01-01",
    "results.end": "2024-12-31",
    "results.ci": "(1.2-3.4)",
    "results.n": "3.84",
    "results.x": "3.84",
}


@pytest.mark.parametrize(("source", "marked", "returned", "expected"), INSIDE_A_TOKEN)
def test_prose_found_inside_a_token_leaves_its_edges_alone(
    source: str, marked: str, returned: str, expected: str
) -> None:
    """Guessed, the first date ended at "2015" and the second began at "01-01", the interval
    ended at "(1.2", the citation at "al", and "(Lee, Park," was the whole citation. Each
    edit was refused, as a value that changed or a rebuild that did not read as typed."""
    assert merged(source, marked, returned) == expected


@pytest.mark.parametrize(("source", "marked", "returned", "changed"), INSIDE_CHANGED)
def test_a_changed_token_is_named_whole(
    source: str, marked: str, returned: str, changed: tuple
) -> None:
    """Guessed, the citation ended at "Park," and the "&" typed inside it merged as prose:
    `[@lee2021] & {{results.x}}`, which drops the co-author's edit to the citation and prints
    an "&" where they left "and". A changed date was named by what lay between the guessed
    edges: "'01-01 - 2024-12-31' comes from results.end"."""
    plain, spans = unmark(marked)
    aligned = align(source, plain, returned, spans)
    assert aligned.rebuilt is None
    assert aligned.changed == changed


#: Just enough of a citation style to print the citations above as they are shown. The
#: Chicago style pandoc 3.9 ships puts "et al." after the first of three authors, so "and"
#: is not in it.
INSIDE_CSL = """<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0">
  <info><title>Test</title><id>test</id><updated>2026-01-01T00:00:00+00:00</updated></info>
  <citation et-al-min="4" et-al-use-first="1">
    <layout prefix="(" suffix=")" delimiter="; ">
      <group delimiter=" ">
        <names variable="author">
          <name form="short" and="text" delimiter=", " delimiter-precedes-last="always"/>
        </names>
        <date variable="issued"><date-part name="year"/></date>
      </group>
    </layout>
  </citation>
</style>
"""
INSIDE_REFERENCES = [
    {
        "id": "smith2020",
        "type": "article-journal",
        "author": [{"family": name} for name in ("Smith", "Brown", "Green", "White")],
        "issued": {"date-parts": [[2020]]},
    },
    {
        "id": "lee2021",
        "type": "article-journal",
        "author": [{"family": name} for name in ("Lee", "Park", "Kim")],
        "issued": {"date-parts": [[2021]]},
    },
]


def cited_build(markdown: str, folder: Path) -> list:
    """`markdown` built with its citations rendered, and read back as import reads Word."""
    import json
    import subprocess

    from manuscript_guard.roundtrip import read_blocks

    folder.mkdir(parents=True, exist_ok=True)
    style, references = folder / "style.csl", folder / "references.json"
    style.write_text(INSIDE_CSL, encoding="utf-8")
    references.write_text(json.dumps(INSIDE_REFERENCES), encoding="utf-8")
    path, document = folder / "a.md", folder / "a.docx"
    path.write_text(markdown, encoding="utf-8")
    subprocess.run(
        ["pandoc", str(path), "--citeproc", f"--bibliography={references}", f"--csl={style}",
         "-o", str(document)],
        check=True,
    )
    return [block for block in read_blocks(document) if block.names]


@pytest.fixture(scope="module")
def inside_built(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Each source above built as import builds it, once plain and once with every token
    bookmarked, and the paragraph as the marked build reads it. Marking must change nothing
    a co-author sees, or the extents describe text that was never sent."""
    from manuscript_guard.roundtrip import tag
    from manuscript_guard.text.placeholders import substitute

    cases = INSIDE_A_TOKEN + INSIDE_CHANGED
    sources = list(dict.fromkeys(case.values[0] for case in cases))
    text = "\n\n".join(sources) + "\n"
    folder = tmp_path_factory.mktemp("inside")
    plain = cited_build(substitute(tag(text, "main.md"), INSIDE_VALUES), folder / "plain")
    marked = cited_build(
        substitute(tag(text, "main.md", mark=True), INSIDE_VALUES), folder / "marked"
    )
    assert len(plain) == len(marked) == len(sources)
    for sent, block in zip(plain, marked, strict=True):
        assert sent.names == block.names
        assert sent.text == block.text, "marking changed the text"
    return dict(zip(sources, marked, strict=True))


@needs_pandoc
@pytest.mark.parametrize(
    ("source", "marked", "returned", "expected"),
    [case for case in INSIDE_A_TOKEN if "no-break" not in case.id],
)
def test_prose_found_inside_a_token_merges_from_a_marked_build(
    source: str,
    marked: str,
    returned: str,
    expected: str,
    inside_built: dict,
    tmp_path: Path,
) -> None:
    """End to end: the extents are the marked build's, not written out by hand, and the
    merge, built again, prints what the co-author typed. The no-break-space case is not
    here: citeproc prints a plain space after "al." in a citation."""
    from manuscript_guard.text.placeholders import substitute

    block = inside_built[source]
    assert (block.text, list(block.tokens)) == unmark(marked)
    out = realign(source, block.text, returned, block.tokens)
    assert out == expected
    rebuilt = cited_build(f"[]{{#mg-p-x-0}}{substitute(out, INSIDE_VALUES)}\n", tmp_path)
    assert [paragraph.text for paragraph in rebuilt] == [returned]


@needs_pandoc
@pytest.mark.parametrize(("source", "marked", "returned", "changed"), INSIDE_CHANGED)
def test_a_changed_token_is_named_whole_from_a_marked_build(
    source: str, marked: str, returned: str, changed: tuple, inside_built: dict
) -> None:
    block = inside_built[source]
    assert (block.text, list(block.tokens)) == unmark(marked)
    aligned = align(source, block.text, returned, block.tokens)
    assert aligned.rebuilt is None
    assert aligned.changed == changed


@pytest.mark.parametrize(
    ("paragraph", "expected"),
    [
        pytest.param(
            "As @key[p. 3] found, it was {{results.x}}.",
            ["@key[p. 3]", "{{results.x}}"],
            id="locator-without-a-space",
        ),
        pytest.param(
            "As @key [the protocol](https://example.org) says, it was {{results.x}}.",
            ["@key", "{{results.x}}"],
            id="link-after-a-key",
        ),
        pytest.param(
            "See [@key](https://example.org) and [@key]{.smallcaps}: {{results.x}}.",
            ["{{results.x}}"],
            id="link-and-span-around-a-key",
        ),
        pytest.param(
            "See [the thread](https://mastodon.social/@someone); it was {{results.x}}.",
            ["{{results.x}}"],
            id="at-sign-in-a-link-address",
        ),
        pytest.param(
            "As @key::a found, it was {{results.x}}.",
            ["@key", "{{results.x}}"],
            id="doubled-punctuation-ends-a-key",
        ),
    ],
)
def test_links_and_keys_are_read_as_pandoc_reads_them(
    paragraph: str, expected: list[str]
) -> None:
    """Each was a token pandoc did not read as one, or not all of one, so marking changed
    the build and the paragraph could never take a rewording."""
    assert segments(paragraph)[1] == expected


def test_a_rewording_beside_code_holding_an_at_sign_merges() -> None:
    source = "Run `fit(@cohort)` first; the ratio was {{results.x}} in zebrafish."
    out = merged(
        source,
        "Run fit(@cohort) first; the ratio was ⟦3.84⟧ in zebrafish.",
        "Run fit(@cohort) first; the ratio was 3.84 in all zebrafish.",
    )
    assert out == source.replace("in zebrafish", "in all zebrafish")


def test_a_citation_with_a_key_starting_with_a_digit_survives_a_rewording() -> None:
    source = "Rates rose [@2019who] in all regions."
    out = merged(source, "Rates rose ⟦(WHO 2019)⟧ in all regions.",
                 "Rates climbed (WHO 2019) in all regions.")
    assert out == "Rates climbed [@2019who] in all regions."


def test_a_citation_nothing_protected_refuses_the_paragraph() -> None:
    """Whatever the token patterns miss, a key left in the prose must not be merged over:
    Word's text has the citation's rendering, not the key."""

    aligned = align(
        "Quoted [@key, p. 3 and more.",
        "Quoted [Key (2019), p. 3 and more.",
        "Quoted [Key (2019), p. 3 and then more.",
        [],
    )
    assert aligned.rebuilt is None


def test_tokens_are_marked_without_adding_brackets() -> None:
    """Wrapped in `[...]{#id}`, a token next to an unbalanced bracket let pandoc pair the
    brackets differently: the text read the same, the extent lost its first character, and
    a rewording wrote the `[` twice."""
    from manuscript_guard.roundtrip import tag

    marked = tag("Scores in [low, high) and {{results.a}} [@key].\n", "main.md", mark=True)
    assert "[[" not in marked and "]{#mg-t-" not in marked
    assert marked.count("{=openxml}") == 4, "a start and an end for each of two tokens"


@pytest.mark.parametrize(
    ("source", "rendered", "returned"),
    [
        ("The value [{{results.x}}]{.smallcaps} here.", "The value ⟦3⟧ here.",
         "The new value 3 here."),
        ("It was ~~{{results.x}}~~ gone.", "It was ⟦3⟧ gone.", "It was 3 now gone."),
        ("Per m^{{results.x}}^ units.", "Per m⟦3⟧ units.", "Per m3 square units."),
        ("Per m<sup>{{results.x}}</sup> units.", "Per m⟦3⟧ units.", "Per m3 square units."),
        ("It was **{{results.x}}** high.", "It was ⟦3⟧ high.", "It was 3 very high."),
    ],
    ids=["span", "strikeout", "superscript", "html", "strong"],
)
def test_formatting_that_wraps_a_token_is_not_left_half_open(
    source: str, rendered: str, returned: str
) -> None:
    """An edited segment is taken from Word without its markdown, and the untouched segment
    on the other side of the token kept its delimiter: `The new value {{x}}]{.smallcaps}`."""
    from manuscript_guard.merge import why

    plain, spans = unmark(rendered)
    aligned = align(source, plain, returned, spans)
    assert aligned.rebuilt is None
    assert aligned.markup or aligned.misread, why(aligned)


@pytest.mark.parametrize(
    ("source", "rendered", "returned"),
    [
        (
            "Significant values are marked * in Table 2; the ratio was *{{results.x}}* overall.",
            "Significant values are marked * in Table 2; the ratio was ⟦3⟧ overall.",
            "Significant results are marked * in Table 2; the ratio was 3 overall.",
        ),
        (
            "Of 2 * 3 cells, *{{results.x}}* were empty.",
            "Of 2 * 3 cells, ⟦3⟧ were empty.",
            "Of the 2 * 3 cells, 3 were empty.",
        ),
    ],
    ids=["marked-with-a-star", "times"],
)
def test_a_literal_marker_does_not_shift_the_pairs_after_it(
    source: str, rendered: str, returned: str
) -> None:
    """Markers were paired in order, so a literal `*` earlier in the paragraph paired with
    the italics' opening one, and `*{{x}}*` merged as `{{x}}* overall`."""
    assert merged(source, rendered, returned) is None


# ------------------------------------------ what Word's text cannot carry back to the source


def test_an_inline_comment_and_footnote_are_not_merged_away() -> None:
    """The reported case. Neither reaches the paragraph's `w:t` text, so rebuilding the
    paragraph from what came back deleted the comment, and nothing said so."""
    from manuscript_guard.merge import why

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

    aligned = align(source, rendered, rendered.replace("here", "there"))
    assert aligned.rebuilt is None
    assert aligned.markup == (named,)


TYPESET_IN_CODE = "code with `--`, `...` or a quote in it"


@pytest.mark.parametrize(
    ("source", "rendered", "returned"),
    [
        pytest.param(
            "Run it with `--offline` and the ratio was {{results.x}} overall.",
            "Run it with --offline and the ratio was ⟦3.84⟧ overall.",
            "Start it with --offline and the ratio was 3.84 overall.",
            id="dashes-beside-a-binding",
        ),
        pytest.param(
            "A comment is opened with `<!--` in the source files.",
            "A comment is opened with <!-- in the source files.",
            "A comment is started with <!-- in the source files.",
            id="comment-marker",
        ),
        pytest.param(
            'Quote it as `"exact"` in the query.',
            'Quote it as "exact" in the query.',
            'Write it as "exact" in the query.',
            id="quotes",
        ),
        pytest.param(
            "Then `wait...` returns {{results.x}} values.",
            "Then wait... returns ⟦3.84⟧ values.",
            "Then wait... gives 3.84 values.",
            id="dots",
        ),
        pytest.param(
            "The flag ``it's`` is {{results.x}} long.",
            "The flag it's is ⟦3.84⟧ long.",
            "A flag it's is 3.84 long.",
            id="apostrophe-in-double-ticks",
        ),
    ],
)
def test_code_pandoc_would_typeset_as_prose_refuses_a_rewording(
    source: str, rendered: str, returned: str
) -> None:
    """Rebuilt from Word's text, code comes back as prose, and pandoc typesets what code
    kept literal: `--offline` printed as "–offline", `<!--` as "<!–", `"exact"` with curly
    quotes. The rewording is refused and the code named, as other markup Word's text cannot
    carry is."""
    aligned = merged_alignment(source, rendered, returned)
    assert aligned.rebuilt is None
    assert aligned.markup == (TYPESET_IN_CODE,)


def test_code_nothing_would_typeset_still_merges_as_text() -> None:
    """Only its formatting is lost, the known cost of an edited stretch; it prints the same."""
    source = "Fitted with `lme4` in R, the ratio was {{results.x}} overall."
    out = merged(
        source,
        "Fitted with lme4 in R, the ratio was ⟦3.84⟧ overall.",
        "Fitted using lme4 in R, the ratio was 3.84 overall.",
    )
    assert out == "Fitted using lme4 in R, the ratio was {{results.x}} overall."


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        pytest.param(
            "Run it with `--offline` and the ratio was {{results.x}} overall.",
            "Run it with --offline and the ratio was ⟦3.84⟧ overall.",
            "Run it and the ratio was 3.84 overall.",
            "Run it and the ratio was {{results.x}} overall.",
            id="beside-a-binding",
        ),
        pytest.param(
            "A comment is opened with `<!--` in the source files.",
            "A comment is opened with <!-- in the source files.",
            "A comment is opened in the source files.",
            "A comment is opened in the source files.",
            id="plain-paragraph",
        ),
    ],
)
def test_code_the_edit_deleted_does_not_refuse_it(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """With the code gone from Word's text, nothing is left for pandoc to typeset, and the
    refusal named code that Word no longer showed."""
    assert merged(source, rendered, returned) == expected


def test_code_in_a_stretch_left_alone_is_kept() -> None:
    source = "Run it with `--offline`: the ratio was {{results.x}} overall."
    out = merged(
        source,
        "Run it with --offline: the ratio was ⟦3.84⟧ overall.",
        "Run it with --offline: the ratio was 3.84 in all.",
    )
    assert out == "Run it with `--offline`: the ratio was {{results.x}} in all."


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

    aligned = align(source, rendered, returned)
    assert aligned.rebuilt is None
    assert aligned.markup == ("one end of an emphasis or code span",)


def test_bold_around_two_bindings_is_not_stretched_over_the_words_between() -> None:
    """The stretch between holds a closing and an opening delimiter, so counting them found
    an even number and let it merge: `**{{results.x}} versus {{results.y}}**`, the co-author's
    word now bold and the author's two bold values one span."""

    source = "The **{{results.x}}** and **{{results.y}}** values differ."
    aligned = align(
        source, "The 3.84 and 7.02 values differ.", "The 3.84 versus 7.02 values differ."
    )
    assert aligned.rebuilt is None
    assert aligned.markup == ("one end of an emphasis or code span",)


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        (
            "The effect was 95% CI [{{results.a}}, {{results.b}}], a strong signal.",
            "The effect was 95% CI [⟦1⟧, ⟦2⟧], a strong signal.",
            "The effect was 95% CI [1, 2], a very strong signal.",
            "The effect was 95% CI [{{results.a}}, {{results.b}}], a very strong signal.",
        ),
        (
            "About ~{{results.a}} reports and ~200 controls.",
            "About ~⟦3⟧ reports and ~200 controls.",
            "About ~3 reports and ~200 matched controls.",
            "About ~{{results.a}} reports and \\~200 matched controls.",
        ),
    ],
    ids=["interval", "approximately"],
)
def test_literal_brackets_and_tildes_are_not_formatting(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """An APA interval and an approximate value were refused as formatting that wraps a
    number. Brackets are markup only when a span or a link follows them."""
    assert merged(source, rendered, returned) == expected


def test_quotes_from_word_are_straightened_for_pandoc_to_curl() -> None:
    """Word's closing `’` beside the source's opening `'` made pandoc read the opening one
    as an apostrophe: `’a ratio of 3.84’`."""
    source = "The agency called it 'a ratio of {{results.x}}' in its review."
    out = merged(
        source,
        "The agency called it ‘a ratio of ⟦3⟧’ in its review.",
        "The agency called it ‘a ratio of 3’ in its last review.",
    )
    assert out == "The agency called it 'a ratio of {{results.x}}' in its last review."


def test_an_elision_opens_no_quotation() -> None:
    """Pandoc printed `'Tis` as ’Tis, so nothing was open; straightening the co-author's
    "keepers’" made pandoc pair the two, and print ‘Tis."""
    source = "'Tis true that {{results.x}} keepers agreed."
    out = merged(
        source,
        "’Tis true that ⟦3⟧ keepers agreed.",
        "’Tis true that 3 keepers’ union agreed.",
    )
    assert out == "'Tis true that {{results.x}} keepers’ union agreed."


def test_a_quote_opened_right_before_a_token_is_closed_straight_too() -> None:
    source = "The agency called it '{{results.x}} to one' in its review."
    out = merged(
        source,
        "The agency called it ‘⟦3⟧ to one’ in its review.",
        "The agency called it ‘3 to one’ in its last review.",
    )
    assert out == "The agency called it '{{results.x}} to one' in its last review."


@pytest.mark.parametrize(
    ("source", "rendered", "returned"),
    [
        pytest.param(
            "Das Amt nannte es „ein Signal“ in {{results.n}} Fällen.",
            "Das Amt nannte es „ein Signal“ in ⟦12⟧ Fällen.",
            "Das Amt nannte es „ein klares Signal“ in 12 Fällen.",
            id="german",
        ),
        pytest.param(
            "Rates of {{results.x}} rose in the 1990s.",
            "Rates of ⟦3⟧ rose in the 1990s.",
            "Rates of 3 rose in the ’90s, rock ’n’ roll aside.",
            id="apostrophes",
        ),
        pytest.param(
            "Das Amt nannte es ein Signal.",
            "Das Amt nannte es ein Signal.",
            "Das Amt nannte es „ein Signal“ im ’90er-Stil.",
            id="german-plain",
        ),
    ],
)
def test_quotes_from_word_are_kept_as_word_shows_them(
    source: str, rendered: str, returned: str
) -> None:
    """Straightening every quote from Word, for pandoc to curl again, turned „ein Signal“
    into “ein Signal” and the ’90s into ‘90s: pandoc curls a straight quote the English
    way, and reads one before a word as opening a quotation."""
    plain = returned.replace("12", "{{results.n}}").replace("3 rose", "{{results.x}} rose")
    assert merged(source, rendered, returned) == plain


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        pytest.param(
            "Rates of {{results.x}} rose among 'em, as the agency's 'review' said.",
            "Rates of ⟦3.84⟧ rose among ‘em, as the agency’s ’review’ said.",
            "Rates of 3.84 rose among ’em, as the agency’s ‘review’ said.",
            "Rates of {{results.x}} rose among ’em, as the agency’s ‘review’ said.",
            id="turned-the-right-way-round",
        ),
    ],
)
def test_a_correction_to_quotes_alone_is_an_edit(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """Stretches compared quotes as quotes, so a co-author turning ‘em the right way round
    left a stretch that read as untouched: the source was kept, and import said nothing had
    come back. Word does not change a character nobody typed, so any difference is an edit."""
    assert merged(source, rendered, returned) == expected


def test_only_the_quote_closing_a_kept_straight_one_is_straightened() -> None:
    """The apostrophe of "patients'" opens nothing, so the ’90s after it stays as typed."""
    source = "The patients' {{results.n}} visits rose."
    out = merged(
        source,
        "The patients’ ⟦12⟧ visits rose.",
        "The patients’ 12 visits rose, the ’90s aside.",
    )
    assert out == "The patients' {{results.n}} visits rose, the ’90s aside."


def test_formatting_that_wraps_a_token_is_kept_when_that_side_is_untouched() -> None:
    source = "It was **{{results.x}}** high, and {{results.y}} was low."
    out = merged(
        source, "It was ⟦3⟧ high, and ⟦4⟧ was low.", "It was 3 high, and 4 was very low."
    )
    assert out == "It was **{{results.x}}** high, and {{results.y}} was very low."


@needs_pandoc
def test_prose_before_a_stray_bracket_and_a_citation_merges_once(
    project: Path, tmp_path: Path
) -> None:
    """End to end, as the review ran it: the edit before "[low, high)" merged as
    `All scores in [[low, high) ...`."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    added = (
        "Scores in [low, high) were rescaled as in [@fictionalClassSignal2019], giving "
        "{{results.ror.point}}."
    )
    source.write_text(
        source.read_text(encoding="utf-8") + "\n\n# Scales\n\n" + added + "\n", encoding="utf-8"
    )
    document = built(project)
    returned = rewrite(
        document,
        tmp_path / "bracket.docx",
        lambda xml: xml.replace("Scores in [low", "All scores in [low", 1),
    )
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    after = source.read_text(encoding="utf-8")
    printed = after.replace("\\[", "[")  # Word's text is written back escaped
    assert printed.count("All scores in [low, high) were rescaled") == 1
    assert "[[" not in printed and closed(after)


def test_inline_maths_wrapped_across_a_line_is_refused() -> None:
    """pandoc reads `$p <\\n0.05$` as one equation, which Word holds as OMML, not text."""

    aligned = align("We required $p <\n0.05$ throughout.", "We required throughout.",
                    "We always required throughout.", [])
    assert aligned.rebuilt is None and aligned.markup


def test_a_private_use_character_survives_being_read(tmp_path: Path) -> None:
    """The token markers were U+E000 and U+E001 inside the text, so a genuine one - pasted
    from a PDF, say - vanished from every document read."""
    from manuscript_guard.docxtext import blocks as read

    document = tmp_path / "glyph.docx"
    body = (
        '<w:p><w:bookmarkStart w:id="1" w:name="mg-p-main-1"/><w:bookmarkEnd w:id="1"/>'
        "<w:r><w:t>Glyph x here.</w:t></w:r></w:p>"
    )
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/'
            f'main"><w:body>{body}</w:body></w:document>',
        )
    assert read(document)[0].text == "Glyph x here."


def test_an_email_address_is_not_a_citation() -> None:
    prose, protected = segments("Write to data@example.org for access.")
    assert protected == []


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        pytest.param(
            r"Values \<LLOQ and \>ULOQ (n = {{results.n}}) were excluded.",
            "Values <LLOQ and >ULOQ (n = 56) were excluded.",
            "Concentrations <LLOQ and >ULOQ (n = 56) were excluded.",
            r"Concentrations \<LLOQ and \>ULOQ (n = {{results.n}}) were excluded.",
            id="escape",
        ),
        pytest.param(
            "Values &lt;LLOQ and &gt;ULOQ (n = {{results.n}}) were excluded.",
            "Values <LLOQ and >ULOQ (n = 56) were excluded.",
            "Concentrations <LLOQ and >ULOQ (n = 56) were excluded.",
            r"Concentrations \<LLOQ and \>ULOQ (n = {{results.n}}) were excluded.",
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
        "Smith et al. 2020 found this.",
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
    the source's space, and an edited one writes pandoc's back as a space, which pandoc makes
    one of again."""
    assert realign(source, rendered, returned, abbreviations=ABBREVIATIONS) == expected


ABBREVIATED = [
    pytest.param(
        "It was high, e.g. {{results.x}} in all.",
        "It was high, e.g.\u00a03.84 in all.",
        "It was very high, e.g.\u00a03.84 in all.",
        "It was very high, e.g. {{results.x}} in all.",
        id="before-a-binding",
    ),
    pytest.param(
        "Some cohorts (e.g. adults) were small.",
        "Some cohorts (e.g.\u00a0adults) were small.",
        "Some cohorts (e.g.\u00a0older adults) were small.",
        "Some cohorts (e.g. older adults) were small.",
        id="after-a-parenthesis",
    ),
    pytest.param(
        "The ratio was {{results.x}} vs. none in all cases.",
        "The ratio was 3.84 vs.\u00a0none in all cases.",
        "The ratio was 3.84 vs.\u00a0none in most cases.",
        "The ratio was {{results.x}} vs. none in most cases.",
        id="after-a-binding",
    ),
    pytest.param(
        "As shown, e.g. [@smith2020] here.",
        "As shown, e.g. (Smith 2020) here.",
        "As seen, e.g.\u00a0(Smith 2020) here.",
        "As seen, e.g.\u00a0[@smith2020] here.",
        id="before-a-citation",
    ),
    pytest.param(
        "See Fig. 1 for the rest.",
        "See Fig. 1 for the rest.",
        "See Fig.\u00a01 for the others.",
        "See Fig.\u00a01 for the others.",
        id="not-an-abbreviation",
    ),
    pytest.param(
        "A xe.g. word here.",
        "A xe.g. word here.",
        "A xe.g.\u00a0word there.",
        "A xe.g.\u00a0word there.",
        id="inside-a-word",
    ),
    pytest.param(
        "p. 4 shows it.",
        "p.\u00a04 shows it.",
        "p.\u00a04 shows this.",
        "p\\.\u00a04 shows this.",
        id="escaped-at-the-opening",
    ),
    pytest.param(
        "Values {{results.x}}vs. none here.",
        "Values 3.84vs. none here.",
        "Values 3.84vs.\u00a0none there.",
        "Values {{results.x}}vs.\u00a0none there.",
        id="glued-to-a-binding",
    ),
    pytest.param(
        "Some cohorts (e.g. adults) were small.",
        "Some cohorts (e.g.\u00a0adults) were small.",
        "Some cohorts (e.g.\u00a0 older adults) were small.",
        "Some cohorts (e.g.\u00a0 older adults) were small.",
        id="followed-by-a-space",
    ),
    pytest.param(
        "Mail it to desk@p. 4 of the form.",
        "Mail it to desk@p. 4 of the form.",
        "Send it to desk@p.\u00a04 of the form.",
        "Send it to desk@p.\u00a04 of the form.",
        id="after-an-at-sign",
    ),
    pytest.param(
        "See \\@p. 4 here.",
        "See @p.\u00a04 here.",
        "See @p.\u00a04 there.",
        "See \\@p. 4 there.",
        id="after-an-escaped-at-sign",
    ),
    pytest.param(
        "Mail it to desk@lab-p. 4 of the form.",
        "Mail it to desk@lab-p. 4 of the form.",
        "Send it to desk@lab-p.\u00a04 of the form.",
        "Send it to desk@lab-p.\u00a04 of the form.",
        id="after-an-example-label",
    ),
    pytest.param(
        "Write to {{results.c}}-p. 4 please.",
        "Write to desk@lab-p. 4 please.",
        "Write to desk@lab-p.\u00a04 thanks.",
        "Write to {{results.c}}-p.\u00a04 thanks.",
        id="run-on-from-a-binding",
    ),
]


@pytest.mark.parametrize(("source", "rendered", "returned", "expected"), ABBREVIATED)
def test_pandocs_own_no_break_space_is_written_back_as_a_space(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """An edited stretch is Word's text, and pandoc's no-break space after "e.g." went into the
    .md as a character nobody can see: a diff showed the line changed there, and a search for
    "et al. 2020" missed it. It is written back as a space where pandoc makes one of it again:
    after a whole word on pandoc's list, with something other than a citation after it. It is
    kept where pandoc would not: before a citation, after a word not on the list, or where
    escaping the opening's full stop splits the word."""
    assert realign(source, rendered, returned, abbreviations=ABBREVIATIONS) == expected


@needs_pandoc
@pytest.mark.parametrize(("source", "rendered", "returned", "expected"), ABBREVIATED)
def test_pandocs_own_no_break_space_written_back_prints_the_same(
    source: str, rendered: str, returned: str, expected: str, tmp_path: Path
) -> None:
    """The artefact: the source as it was prints as what the test says Word was sent, and the
    merged source prints exactly what came back, no-break spaces included."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text

    def printed(markdown: str, name: str) -> str:
        # The citation stays one for pandoc, which puts no no-break space before it; without
        # citeproc it prints as its key, read here as the test's rendering of it.
        path = tmp_path / f"{name}.md"
        filled = markdown.replace("{{results.x}}", "3.84").replace("{{results.c}}", "desk@lab")
        path.write_text(f"[]{{#mg-p-x-0}}{filled}\n", encoding="utf-8")
        subprocess.run(["pandoc", str(path), "-o", str(tmp_path / f"{name}.docx")], check=True)
        text = paragraph_text(tmp_path / f"{name}.docx")["mg-p-x-0"]
        return text.replace("[@smith2020]", "(Smith 2020)")

    assert printed(source, "sent") == rendered
    assert printed(expected, "merged") == returned


def test_writing_back_a_no_break_space_is_linear_in_a_long_word(assert_linear) -> None:
    """Looking for a bare `@` in the word before the abbreviation searched the text before it
    with `\\S*\\Z`, which rescans a long run from every place in it: with a URL of 8,000
    characters ahead of a few "e.g.", `align` took 16 seconds. Timed as the URL grows, from
    1,600 characters: the linear scan is quick enough that CI runners found 51,200 (a start
    of 50 at the check's largest growth, when that was 1024) too little to time. A rescan
    put back fails from 1,600 at the same size as from 50, in 14 to 20 s, and the largest
    size is now 6.6 million characters."""
    from manuscript_guard.roundtrip import _respaced

    def with_url(length: int) -> str:
        return f"See https://example.org/{'a' * length} and e.g.\u00a0this."

    def respace(text: str) -> None:
        _respaced(text, ABBREVIATIONS, lead=True, binding_next=False)

    assert_linear(with_url, respace, 1600, "writing back a no-break space, by URL length")


@needs_pandoc
def test_import_reads_the_abbreviations_pandoc_itself_uses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user's own list when pandoc's data directory has one, which pandoc reads instead of
    its default, and read as pandoc reads it. Taken from the default, or with each line
    stripped, a no-break space the co-author typed after a word the user's pandoc does not
    treat as an abbreviation - `e.g. ` with a stray space is not `e.g.` to pandoc - came back
    as a plain space, and the next build printed it so. Read as text, a lone carriage return
    ended a line, where pandoc drops it and joins `vs.` and `q.v.` into one."""
    import subprocess

    from manuscript_guard.build import document

    (tmp_path / "pandoc").mkdir()
    listed = "\ufeffcf.\r\ne.g. \r\nvs.\rq.v.\n\n"
    (tmp_path / "pandoc" / "abbreviations").write_bytes(listed.encode("utf-8"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    native = subprocess.run(
        ["pandoc", "-t", "native"],
        input="See cf. this, e.g. that, vs. them, q.v. it.",
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    assert "cf.\\160this" in native, native
    assert all(f'"{word}"' in native for word in ("e.g.", "vs.", "q.v.")), native
    assert document.abbreviations() == {"cf.", "e.g. ", "vs.q.v."}


@needs_pandoc
def test_pandocs_default_abbreviations_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a list of the user's own, pandoc's default. Isolated from the machine's own
    data directory, which may hold a list."""
    from manuscript_guard.build import document

    (tmp_path / "pandoc").mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert document.abbreviations() >= ABBREVIATIONS


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
    merged = realign(source, rendered, returned, abbreviations=ABBREVIATIONS)
    assert merged == expected
    assert printed(merged, "merged") == returned


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
    pytest.param("Its \u2018real\u2019 cost, they\u2019re sure.",
                 "Its \u2018real\u2019 cost, they\u2019re sure.", id="quotes"),
    pytest.param("Im \u201aSinne\u2018 des \u201eGesetzes\u201c, seit den \u201990ern.",
                 "Im \u201aSinne\u2018 des \u201eGesetzes\u201c, seit den \u201990ern.",
                 id="german-quotes"),
    pytest.param("Use {{results.x}} here.", r"Use \{\{results.x}} here.", id="binding"),
    pytest.param("1990. The year was bad.", r"1990\. The year was bad.", id="list"),
    pytest.param("A *real* change.", r"A \*real\* change.", id="emphasis"),
    pytest.param(
        "Samples <LLOQ in mg/L and >ULOQ were redone.",
        r"Samples \<LLOQ in mg/L and \>ULOQ were redone.",
        id="tag-to-pandoc",
    ),
    pytest.param("Age > 65 and p > 0.05.", "Age > 65 and p > 0.05.", id="nothing-to-close"),
    pytest.param(
        "Set at p < 0.05, <18 years and ROR > 2.",
        "Set at p < 0.05, <18 years and ROR > 2.",
        id="nothing-a-tag-opens-with",
    ),
    pytest.param("Values <µg/L and >ULOQ.", r"Values \<µg/L and \>ULOQ.", id="tag-in-any-script"),
    pytest.param(
        "Values <LOD were imputed => no change.",
        r"Values \<LOD were imputed =&gt; no change.",
        id="equals-inside-a-would-be-tag",
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
        r"Patients took \<{{results.drug}} daily and \>placebo.",
        id="angle-before-a-binding",
    ),
    pytest.param(
        "Samples <LLOQ in {{results.unit}} and ULOQ were redone.",
        "Samples <LLOQ in mg/L and ULOQ were redone.",
        "Samples <LLOQ in mg/L and >ULOQ were redone.",
        r"Samples <LLOQ in {{results.unit}} and \>ULOQ were redone.",
        id="angle-kept-and-a-word-for-a-value",
    ),
    pytest.param(
        "Levels {{results.cut}} were imputed and excluded.",
        "Levels <LOD were imputed and excluded.",
        "Levels <LOD were imputed and >ULOQ excluded.",
        r"Levels {{results.cut}} were imputed and \>ULOQ excluded.",
        id="angle-from-a-value",
    ),
    pytest.param(
        "Values {{results.drug}} ok and >ULOQ excluded.",
        "Values aspirin ok and >ULOQ excluded.",
        "Values <µg aspirin ok and >ULOQ excluded.",
        r"Values \<µg {{results.drug}} ok and >ULOQ excluded.",
        id="angle-before-a-letter-of-any-script",
    ),
    pytest.param(
        "At p < 0.05, {{results.x}} signals had ROR > 2 overall.",
        "At p < 0.05, 3.84 signals had ROR > 2 overall.",
        "At p < 0.05, 3.84 signals had ROR > 2 in all.",
        "At p < 0.05, {{results.x}} signals had ROR > 2 in all.",
        id="comparison-that-opens-nothing",
    ),
    pytest.param(
        "Values <LOD in {{results.unit}} were imputed.",
        "Values <LOD in mg/L were imputed.",
        "Values <LOD in mg/L were imputed => no change.",
        "Values <LOD in {{results.unit}} were imputed =&gt; no change.",
        id="equals-before-the-angle",
    ),
    pytest.param(
        "Levels {{results.cut}} were imputed.",
        "Levels <LOD were imputed.",
        "Levels <LOD were imputed => no change.",
        "Levels {{results.cut}} were imputed =&gt; no change.",
        id="equals-after-an-angle-from-a-value",
    ),
    pytest.param(
        "Values <LOD in {{results.unit}} and HR={{results.hr}} were redone.",
        "Values <LOD in mg/L and HR=2.1 were redone.",
        "Values <LOD in mg/L and HR=2.1>1 were redone.",
        "Values <LOD in {{results.unit}} and HR={{results.hr}}&gt;1 were redone.",
        id="equals-kept-before-a-value",
    ),
    pytest.param(
        "Values <LOD in {{results.unit}} were imputed.",
        "Values <LOD in mg/L were imputed.",
        "Values <LOD in mg/L were imputed at dose=5\u00a0mg>1 only.",
        "Values <LOD in {{results.unit}} were imputed at dose=5\u00a0mg&gt;1 only.",
        id="equals-then-a-no-break-space",
    ),
    pytest.param(
        "Values <LOD in {{results.unit}} had HR=[@smith2019] here.",
        "Values <LOD in mg/L had HR=(Smith 2019) here.",
        "Values <LOD in mg/L had HR=(Smith 2019)>1 here.",
        "Values <LOD in {{results.unit}} had HR=[@smith2019]&gt;1 here.",
        id="equals-then-a-citation",
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
    "results.unit": "mg/L",
    "results.cut": "<LOD",
    "results.hr": "2.1",
    "results.x": "3.84",
    "results.y": "7.02",
    "results.ci": "(1.2-3.4)",
}
BESIDE_CITED = {"(Jones 2019)": "[@jones2019]", "(Smith 2019)": "[@smith2019]"}


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
    an edited stretch, its `[` in the stretch before, was a link.

    A `>` was never escaped. After a `<` the source kept bare, or one a binding's value
    brought, a `>` typed in Word closed a tag around a value that is a word, and pandoc
    deleted everything in between. `_reads_as` saw text, because it fills a binding with
    digits and a digit is not an attribute name. Escaped after any `<`, the `>` of `ROR > 2`
    became `\\>` after `p < 0.05`, and G2 no longer read the threshold; only a `<` a tag can
    open with counts, and that is any letter: `<µg` was left bare, and opened one."""
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


@needs_pandoc
def test_a_quote_after_an_equals_keeps_the_next_paragraph(tmp_path: Path) -> None:
    """A straight quote after an `=` opens a quoted attribute value, which runs on past the
    paragraph's end and its neighbour's identifier: the tag opened by `<LOD` closed at the
    `>` of the next paragraph, and "Values 0.5 in all." was all that printed of the two."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text

    returned = "Values <LOD in mg/L were set to label='low."
    merged = realign(
        "Values <LOD in {{results.unit}} were set to low.",
        "Values <LOD in mg/L were set to low.",
        returned,
    )
    assert merged == r"Values <LOD in {{results.unit}} were set to label=\'low."
    path = tmp_path / "a.md"
    body = merged.replace("{{results.unit}}", "mg/L")
    path.write_text(
        f"[]{{#mg-p-x-0}}{body}\n\n[]{{#mg-p-x-2}}Cohen's d was >0.5 in all.\n", encoding="utf-8"
    )
    subprocess.run(["pandoc", str(path), "-o", str(tmp_path / "a.docx")], check=True)
    printed = paragraph_text(tmp_path / "a.docx")
    assert printed["mg-p-x-0"] == returned
    assert printed["mg-p-x-2"] == "Cohen’s d was >0.5 in all."


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        pytest.param(
            "Costs were low.",
            "Costs were low.",
            "Models were fitted with <LOD handled by family='binomial' as usual.",
            r"Models were fitted with \<LOD handled by family='binomial' as usual.",
            id="whole-paragraph",
        ),
        pytest.param(
            "Models of {{results.x}} were fitted.",
            "Models of 3.84 were fitted.",
            "Models of 3.84 were fitted with <LOD handled by family='binomial'.",
            r"Models of {{results.x}} were fitted with \<LOD handled by family='binomial'.",
            id="beside-a-binding",
        ),
    ],
)
def test_a_quote_after_an_equals_is_left_alone_after_words_own_angle(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """Word's own `<` is escaped and opens no tag, so a quote after an `=` beside it needs no
    backslash. Escaped for it all the same, the quote printed straight where pandoc curled
    its partner: `family='binomial’`, where `‘binomial’` had printed before."""
    assert realign(source, rendered, returned) == expected


@needs_pandoc
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "Values <LOD in {{results.unit}} were coded='HR {{results.x}} or LOD' in all.",
            r"Values <LOD in {{results.unit}} were coded='HR {{results.x}} or LOD=\' in all.",
            id="the-sources-quote-opens-a-value",
        ),
        pytest.param(
            "Values 'HR <LOD in {{results.unit}} or {{results.x}} LOD' in all.",
            r"Values 'HR <LOD in {{results.unit}} or {{results.x}} LOD=\' in all.",
            id="the-sources-quote-stands-before-the-angle",
        ),
    ],
)
def test_a_closing_quote_after_an_equals_keeps_every_word(
    source: str, expected: str, tmp_path: Path
) -> None:
    """A `’` that closes a quotation opened by a straight `'` kept from the source is written
    straight, so that pandoc pairs the two. Straight after an `=`, after a `<` of the source's,
    it could open an attribute's value; left curly, it closed nothing, and a value the
    source's own `='` had opened ran on into the next paragraph: "Values 0.5 in all." was all
    that printed of the two. Written straight and escaped, it does neither."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text

    values = {"results.unit": "mg/L", "results.x": "3.84"}
    rendered = source.replace("'", "‘", 1).replace("'", "’")
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    returned = rendered.replace("LOD’", "LOD=’")
    # Where each token's rendering sits, as the bookmarked build gives it to `import`.
    extents = [(rendered.index(shown), rendered.index(shown) + 4) for shown in ("mg/L", "3.84")]
    merged = realign(source, rendered, returned, extents)
    assert merged == expected
    body = merged
    for key, value in values.items():
        body = body.replace("{{" + key + "}}", value)
    path = tmp_path / "a.md"
    path.write_text(
        f"[]{{#mg-p-x-0}}{body}\n\n[]{{#mg-p-x-2}}Cohen's d was >0.5 in all.\n", encoding="utf-8"
    )
    subprocess.run(["pandoc", str(path), "-o", str(tmp_path / "a.docx")], check=True)
    printed = paragraph_text(tmp_path / "a.docx")
    # Every word, whichever way its quotes turned.
    straight = str.maketrans({"‘": "'", "’": "'"})
    assert printed["mg-p-x-0"].translate(straight) == returned.translate(straight)
    assert printed["mg-p-x-2"] == "Cohen’s d was >0.5 in all."


@needs_pandoc
def test_pandocs_space_after_an_abbreviation_keeps_the_tag_shut(tmp_path: Path) -> None:
    """The `>` is decided on Word's text, where pandoc's space after "e.g." is a no-break one
    and part of the value; it is then written back as a plain space, which ends the value
    sooner. So the decision can only have been more careful than it needed to be."""
    import subprocess

    from manuscript_guard.roundtrip import paragraph_text

    returned = "Values <LOD in mg/L were imputed at dose=e.g.\N{NO-BREAK SPACE}5>1 only."
    merged = realign(
        "Values <LOD in {{results.unit}} were imputed.",
        "Values <LOD in mg/L were imputed.",
        returned,
        abbreviations=frozenset({"e.g."}),
    )
    assert merged == "Values <LOD in {{results.unit}} were imputed at dose=e.g. 5&gt;1 only."
    path = tmp_path / "a.md"
    body = merged.replace("{{results.unit}}", "mg/L")
    path.write_text(f"[]{{#mg-p-x-0}}{body}\n", encoding="utf-8")
    subprocess.run(["pandoc", str(path), "-o", str(tmp_path / "a.docx")], check=True)
    assert paragraph_text(tmp_path / "a.docx")["mg-p-x-0"] == returned


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
            r"Levels \<LOD were imputed as LOD/2 and \>ULOQ dropped.",
            id="angle-brackets",
        ),
        pytest.param(
            "Levels <LOD (n = {{results.n}}) were imputed as LOD/2 and >ULOQ excluded.",
            "Levels <LOD (n = 56) were imputed as LOD/2 and >ULOQ excluded.",
            "Levels <LOD (n = 56) were imputed as LOD/2 and >ULOQ dropped.",
            r"Levels <LOD (n = {{results.n}}) were imputed as LOD/2 and \>ULOQ dropped.",
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
    ("source", "rendered"),
    [
        ("As @smith2020 showed, rates rose.", "As ⟦Smith (2020)⟧ showed, rates rose."),
        # Its extent is given, not guessed: guessing found the final "." inside "p. 4".
        ("Rates rose [see @smith2020, p. 4].", "Rates rose ⟦(see Smith (2020), p. 4)⟧."),
    ],
    ids=["narrative", "prefixed"],
)
def test_a_narrative_or_prefixed_citation_is_protected_not_flattened(
    source: str, rendered: str
) -> None:
    """These read in Word as "Smith (2020)". When only `[@key]` was a token, rebuilding from
    Word's text turned the citation into that text and the reference left the bibliography;
    that was then refused. Both are tokens now, and a rewording keeps the key."""
    returned = unmark(rendered)[0].replace("rose", "climbed")
    assert merged(source, rendered, returned) == source.replace("rose", "climbed")


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

    aligned = align("Alpha beta gamma.", "Alpha gamma.", "Alpha gamma delta.")
    assert aligned.rebuilt is None
    assert aligned.unaligned


# ------------------------------------------- a paragraph that is only its binding keeps its name


def test_a_paragraph_that_is_only_a_value_is_tagged() -> None:
    """`tag` took every placeholder standing alone for a table or a figure and gave it no
    identifier. A value alone is a paragraph that prints a number, and a Word edit to it was
    never compared: nothing named it, so nothing could come back."""
    lone = ["{{results.ror.point}}", "{{lit.agency.withdrawn}}", "{{table.cases}}", "{{figure.a}}"]
    tagged = tag("\n\n".join(lone), "main.md").split("\n\n")
    assert [p.startswith("[]{#mg-p-") for p in tagged] == [True, True, False, False]


@pytest.mark.parametrize(
    ("source", "rendered", "returned", "expected"),
    [
        pytest.param(
            "The final ratio was {{results.ror.point}} overall.",
            "The final ratio was 3.84 overall.",
            "3.84",
            "{{results.ror.point}}",
            id="value",
        ),
        pytest.param(
            "As shown [@jones2019] before.",
            "As shown (Jones 2019) before.",
            "(Jones 2019)",
            "[@jones2019]",
            id="citation",
        ),
    ],
)
def test_a_paragraph_cut_down_to_its_token_keeps_its_identifier(
    source: str, rendered: str, returned: str, expected: str
) -> None:
    """A co-author deleted everything but the number. It merged as `{{results.ror.point}}`
    alone and `check` passed, but the next build gave the paragraph no identifier, so its
    next edit in Word was skipped with "nothing came back"."""
    merged = realign(source, rendered, returned)
    assert merged == expected
    assert tag(merged, "main.md").startswith("[]{#mg-p-"), "the next build names it"


def test_a_rewording_that_leaves_only_a_misspelt_placeholder_is_refused_and_named() -> None:
    """`tag` gives no identifier to a misspelt placeholder standing alone, and one reaches
    Word as its own text in a document built with `--skip-checks`. Cut down to it, the
    paragraph would build with no identifier, and no later edit to it could come back. The
    refusal said it would build as a table or a figure, which it would not."""
    from manuscript_guard.merge import why

    source = "Value {{result.ror.point}} here."
    aligned = align(source, source, "{{result.ror.point}}")
    assert aligned.rebuilt is None
    assert aligned.alone == "{{result.ror.point}}"
    reason = why(aligned)[0]
    assert "{{result.ror.point}}" in reason
    assert "misspelt placeholder" in reason


def test_a_heading_typed_at_the_start_of_a_paragraph_with_a_binding_is_text() -> None:
    """The first stretch was escaped before the paragraph was stripped, so a `#` behind a
    space was not at the start of anything, stayed bare, and opened the merged paragraph as
    a heading."""
    merged = realign("Ratio {{results.x}} here.", "Ratio 3.84 here.", " # x 3.84")
    assert merged == r"\# x {{results.x}}"
    assert tag(merged, "main.md").startswith("[]{#mg-p-")


@pytest.mark.parametrize(
    "returned",
    ["{{results.x}}", "{{table.cases}}", "# Results", "::: note", "``` code", "~~~"],
    ids=["value", "table", "heading", "div-fence", "code-fence", "tilde-fence"],
)
def test_a_plain_paragraph_retyped_in_word_keeps_its_identifier(returned: str) -> None:
    """A paragraph without bindings is replaced whole by Word's text, and `tag` gives no
    identifier to a heading, a fence, or a table or figure standing alone. Each, typed in
    Word, is escaped into text, so the paragraph still has one at the next build."""
    merged = realign("Costs were low.", "Costs were low.", returned)
    assert merged is not None
    assert tag(merged, "main.md").startswith("[]{#mg-p-"), merged


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


@needs_pandoc
def test_reordered_list_items_are_not_called_a_match(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Counted as a bag of texts, list items swapped in Word were all still there, and
    import said the document matched while the reorder went nowhere."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    block = "- First, the reports.\n- Second, the drugs.\n- Third, the events.\n\n"
    source.write_text(
        source.read_text(encoding="utf-8").replace("# Funding", block + "# Funding", 1),
        encoding="utf-8",
    )
    document = built(project)
    before = source.read_text(encoding="utf-8")

    def edit(xml: str) -> str:
        items = [
            p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL)
            if "First, the reports." in p or "Third, the events." in p
        ]
        first, third = items
        return xml.replace(first, "\0", 1).replace(third, first, 1).replace("\0", third, 1)

    returned = rewrite(document, tmp_path / "swapped.docx", edit)
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    out = capsys.readouterr().out
    assert "matches the manuscript" not in out, out
    assert "order" in out, out
    named = "~ First, the reports." in out or "~ Third, the events." in out
    assert named, "the reordered items are named, not only counted"
    assert source.read_text(encoding="utf-8") == before


@needs_pandoc
def test_a_deleted_paragraph_without_an_identifier_is_named(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Counted but not named, a deleted heading printed a heading with nothing under it."""
    from manuscript_guard.cli import main

    document = built(project)

    def edit(xml: str) -> str:
        heading = next(
            p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL) if ">Funding<" in p
        )
        return xml.replace(heading, "", 1)

    returned = rewrite(document, tmp_path / "no-heading.docx", edit)
    capsys.readouterr()
    assert main(["import", str(returned), str(project)]) == 1
    assert "- Funding" in capsys.readouterr().out


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
    figure = Block(kind="figure")
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


# ------------------------------------------------- what no move may carry anything across


@pytest.mark.parametrize("dragged", ["into-it", "out-past-it"])
def test_a_move_beside_a_comment_across_a_blank_line_leaves_the_comment_whole(
    tmp_path: Path, dragged: str
) -> None:
    """An HTML comment with a blank line in it is two paragraphs of source. The first is
    tagged and reaches Word as an empty line; the second never reaches Word at all. The first
    was a slot like any other, so a move around it moved half a comment: a paragraph dragged
    below the empty line landed inside the comment and vanished from the build, and one
    dragged above it put the comment's halves the wrong way round and printed them."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    paragraphs = {
        "a": "Alpha comes first.",
        "b": "Beta comes second.",
        "c1": "<!--\nA note to self,",
        "c2": "carried on past a blank line.\n-->",
        "d": "Delta comes last.",
    }
    path, known = source_of(tmp_path, paragraphs)
    before = path.read_text(encoding="utf-8")
    b = {name: Block((name,), paragraphs[name]) for name in ("a", "b", "d")}
    empty = Block(("c1",), "")
    sent = [b["a"], b["b"], empty, b["d"]]
    if dragged == "into-it":
        returned, crossed = [b["a"], empty, b["b"], b["d"]], "b"
    else:
        returned, crossed = [b["a"], b["b"], b["d"], empty], "d"

    plan = plan_import(known, sent, returned)
    assert plan.misplaced == (crossed,)
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == before


def test_a_paragraph_a_comment_runs_on_from_is_neither_moved_nor_merged(tmp_path: Path) -> None:
    """A comment opened inside a paragraph and closed past a blank line takes the next
    paragraph of source into itself. Moved, the opening travelled and the closing stayed, so
    whatever landed in its slot was swallowed by the comment."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    paragraphs = {
        "a": "Alpha comes first.",
        "b": "Beta opens a note <!-- that runs on",
        "c": "past a blank line --> and Beta ends.",
        "d": "Delta comes last.",
    }
    path, known = source_of(tmp_path, paragraphs)
    before = path.read_text(encoding="utf-8")
    alpha, delta = Block(("a",), paragraphs["a"]), Block(("d",), paragraphs["d"])
    beta = Block(("b",), "Beta opens a note and Beta ends.")
    sent = [alpha, beta, delta]

    moved = plan_import(known, sent, [beta, alpha, delta])
    assert moved.misplaced == ("a",)
    apply_plan(known, moved)
    assert path.read_text(encoding="utf-8") == before

    reworded = plan_import(known, sent, [alpha, Block(("b",), "Beta now ends."), delta])
    assert not reworded.merged and [r.name for r in reworded.refused] == ["b"]


def _fenced(tmp_path: Path):
    """A div whose last paragraph runs straight on into the closing fence."""
    from manuscript_guard.docxtext import Block

    paragraphs = {
        "open": "::: {.note}\nAlpha, first inside the div.",
        "z": "Zeta, last inside the div.\n:::",
        "o": "Omega, after the div.",
    }
    path, known = source_of(tmp_path, paragraphs)
    del known["open"]  # it opens with a fence, so it carries no identifier
    sent = [
        Block((), "Alpha, first inside the div."),
        Block(("z",), "Zeta, last inside the div."),
        Block(("o",), "Omega, after the div."),
    ]
    return path, known, sent


def test_the_last_paragraph_of_a_div_is_not_reworded_over_its_closing_fence(
    tmp_path: Path,
) -> None:
    """With no blank line before it, the `:::` closing a div is part of the div's last
    paragraph of source, and Word shows only the paragraph. A rewording was written over both,
    and on the next build the div ran to the end of the document."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path, known, sent = _fenced(tmp_path)
    before = path.read_text(encoding="utf-8")
    returned = [sent[0], Block(("z",), "Zeta, now the last one inside the div."), sent[2]]

    plan = plan_import(known, sent, returned)
    assert not plan.merged
    assert [r.name for r in plan.refused] == ["z"]
    assert any("fence" in line for line in plan.refused[0].why)
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == before


def test_no_move_carries_a_fence_line_with_it(tmp_path: Path) -> None:
    """The closing fence travelled with the paragraph it is glued to, so a paragraph moved
    across it changed which paragraphs the div holds."""
    from manuscript_guard.merge import apply_plan, plan_import

    path, known, sent = _fenced(tmp_path)
    before = path.read_text(encoding="utf-8")

    plan = plan_import(known, sent, [sent[0], sent[2], sent[1]])
    assert plan.misplaced == ("o",)
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == before


def _held_between_headings(tmp_path: Path):
    """'# A' holding a div whose last paragraph runs into its fence, then a comment across a
    blank line; '# B' holding two paragraphs."""
    from manuscript_guard.docxtext import Block

    path = tmp_path / "main.md"
    text = (
        "# A\n\n::: {.note}\nAlpha, inside the div.\n\nZeta, last inside the div.\n:::\n\n"
        "<!--\nA note,\n\ncarried on.\n-->\n\n# B\n\nBeta one.\n\nBeta two.\n"
    )
    path.write_text(text, encoding="utf-8")
    words = {
        "z": "Zeta, last inside the div.\n:::",
        "c1": "<!--\nA note,",
        "c2": "carried on.\n-->",
        "b1": "Beta one.",
        "b2": "Beta two.",
    }
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    b = {
        "z": Block(("z",), "Zeta, last inside the div."),
        "c1": Block(("c1",), ""),
        "b1": Block(("b1",), "Beta one."),
        "b2": Block(("b2",), "Beta two."),
    }
    heading_a, heading_b = Block((), "A"), Block((), "B")
    alpha = Block((), "Alpha, inside the div.")
    sent = [heading_a, alpha, b["z"], b["c1"], heading_b, b["b1"], b["b2"]]
    return path, text, known, b, heading_a, alpha, heading_b, sent


@pytest.mark.parametrize(
    "dragged", ["fenced-below-the-next-heading", "fenced-to-the-end", "empty-line-elsewhere"]
)
def test_a_paragraph_held_in_place_that_was_dragged_is_reported(
    tmp_path: Path, dragged: str
) -> None:
    """A paragraph held in place took part in the ordering as an anonymous anchor, and was
    dropped from the moves as well. Dragged past a heading, it was dropped without a word:
    "nothing came back", exit 0. Dragged to the end of the next section, the paragraph it
    passed was reported as reordered, and nothing was written."""
    from manuscript_guard.merge import apply_plan, plan_import

    path, text, known, b, heading_a, alpha, heading_b, sent = _held_between_headings(tmp_path)
    if dragged == "fenced-below-the-next-heading":
        returned, crossed = [heading_a, alpha, b["c1"], heading_b, b["z"], b["b1"], b["b2"]], "z"
    elif dragged == "fenced-to-the-end":
        returned, crossed = [heading_a, alpha, b["c1"], heading_b, b["b1"], b["b2"], b["z"]], "z"
    else:
        returned, crossed = [heading_a, alpha, b["z"], heading_b, b["b1"], b["c1"], b["b2"]], "c1"

    plan = plan_import(known, sent, returned)
    assert plan.misplaced == (crossed,)
    assert not plan.moved, "nothing is reported as reordered that will not be"
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == text


def test_a_split_beside_a_paragraph_held_in_place_is_still_refused(tmp_path: Path) -> None:
    """A paragraph that reaches Word in parts was recognised by untagged text between it and
    the next paragraph of its section. A paragraph held in place is a section of its own, so a
    one-line comment after it hid the split, and a rewording of the first part deleted the
    rest: a definition, or a box written as an HTML div."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    paragraphs = {"a": "Alpha text here and the rest of it.", "c": "<!-- a note -->"}
    path, known = source_of(tmp_path, paragraphs)
    before = path.read_text(encoding="utf-8")
    sent = [Block(("a",), "Alpha text here"), Block((), "and the rest of it."), Block(("c",), "")]
    returned = [Block(("a",), "Alpha text here, reworded"), sent[1], sent[2]]

    plan = plan_import(known, sent, returned)
    assert not plan.merged and [r.name for r in plan.refused] == ["a"]
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == before


def test_a_comment_whose_continuation_opens_with_a_heading_is_not_split_by_a_move(
    tmp_path: Path,
) -> None:
    """A paragraph opening a comment was held only when the part of the comment after the
    blank line was the very next paragraph of source. A heading inside the comment came
    between them, and swapping the paragraph with the one before it wrote that one inside the
    comment, exit 0."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path = tmp_path / "main.md"
    text = (
        "# Intro\n\nFirst paragraph.\n\nSecond paragraph. <!-- an earlier draft:\n\n"
        "## Earlier background\n\nIt read differently.\n-->\n\n# Methods\n\nMethods one.\n"
    )
    path.write_text(text, encoding="utf-8")
    words = {
        "p1": "First paragraph.",
        "p2": "Second paragraph. <!-- an earlier draft:",
        "hidden": "It read differently.\n-->",
        "m1": "Methods one.",
    }
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    intro, methods = Block((), "Intro"), Block((), "Methods")
    p1, p2 = Block(("p1",), "First paragraph."), Block(("p2",), "Second paragraph.")
    m1 = Block(("m1",), "Methods one.")

    plan = plan_import(known, [intro, p1, p2, methods, m1], [intro, p2, p1, methods, m1])
    assert plan.misplaced == ("p1",)
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize(
    "glued",
    [
        "Zeta, last inside the box.\n</div>",
        "Zeta, last inside the minipage.\n\\end{minipage}",
        "Odds ratio\n:   The odds of the event among the exposed.",
        "A heading written underlined\n============================",
    ],
    ids=["html-block", "latex-environment", "definition", "setext-heading"],
)
def test_a_line_that_opens_or_closes_a_block_is_never_merged_or_moved_away(
    tmp_path: Path, glued: str
) -> None:
    """Only `:::` and code fences were recognised. A `</div>` written directly under a
    box's last paragraph was deleted with a rewording of it, and the box ran to the end of the
    document, exit 0; so would a LaTeX environment's end, a definition, or a heading's
    underline, all of which Word shows apart from the paragraph."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path, known = source_of(tmp_path, {"z": glued, "o": "Omega, after it."})
    before = path.read_text(encoding="utf-8")
    first = glued.split("\n")[0]
    sent = [Block(("z",), first), Block(("o",), "Omega, after it.")]

    reworded = plan_import(known, sent, [Block(("z",), first + " Indeed."), sent[1]])
    assert not reworded.merged and [r.name for r in reworded.refused] == ["z"]
    moved = plan_import(known, sent, [sent[1], sent[0]])
    assert moved.misplaced == ("o",)
    apply_plan(known, moved)
    assert path.read_text(encoding="utf-8") == before


WORDML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DRAWINGML = "http://schemas.openxmlformats.org/drawingml/2006/main"
OMML = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def word_document(path: Path, body: str, pictures: dict[str, bytes] | None = None) -> Path:
    """A minimal .docx: `body`, and each picture stored under its relationship id."""
    pictures = pictures or {}
    rels = "".join(
        f'<Relationship Id="{rid}" Type="{RELS}/image" Target="media/{rid}.png"/>'
        for rid in pictures
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{WORDML}" xmlns:r="{RELS}" xmlns:a="{DRAWINGML}" '
            f'xmlns:m="{OMML}">'
            f"<w:body>{body}</w:body></w:document>",
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            f'relationships">{rels}</Relationships>',
        )
        for rid, data in pictures.items():
            archive.writestr(f"word/media/{rid}.png", data)
    return path


def _picture(rid: str) -> str:
    return f'<w:p><w:r><w:drawing><a:blip r:embed="{rid}"/></w:drawing></w:r></w:p>'


def test_a_figure_is_known_by_its_picture_and_a_table_by_what_it_holds(tmp_path: Path) -> None:
    """Tables and figures were one kind, told apart by position alone and only while their
    total was unchanged. A figure is known by the picture it shows, which survives Word
    renaming the file inside the package; a picture pasted in is a different one."""
    from manuscript_guard.docxtext import blocks as read

    table = "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>426</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    sent = read(
        word_document(tmp_path / "sent.docx", _picture("rId7") + table, {"rId7": b"forest"})
    )
    # Saved by Word, which renumbers and renames what the package holds; a picture pasted in.
    back = read(
        word_document(
            tmp_path / "back.docx",
            _picture("rId3") + _picture("rId4") + table,
            {"rId3": b"a pasted photograph", "rId4": b"forest"},
        )
    )

    assert [b.kind for b in sent] == ["figure", "table"]
    assert [b.kind for b in back] == ["figure", "figure", "table"]
    assert all(b.table for b in back), "neither is prose"
    assert back[1].key == sent[0].key != back[0].key
    assert back[2].key == sent[1].key


def _figure_and_table(tmp_path: Path):
    """'Alpha.', a table, 'Beta.' and 'Gamma.', a figure, 'Delta.': three sections."""
    from manuscript_guard.docxtext import Block

    path = tmp_path / "main.md"
    text = "Alpha.\n\n{{table.t}}\n\nBeta.\n\nGamma.\n\n{{figure.f}}\n\nDelta.\n"
    path.write_text(text, encoding="utf-8")
    words = {"alpha": "Alpha.", "beta": "Beta.", "gamma": "Gamma.", "delta": "Delta."}
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    b = {name: Block((name,), w) for name, w in words.items()}
    return path, text, known, b, Block(kind="table", key="t"), Block(kind="figure", key="f")


@pytest.mark.parametrize("change", ["a-table-deleted", "a-picture-pasted"])
def test_a_move_past_a_figure_is_seen_when_the_tables_and_figures_changed(
    tmp_path: Path, change: str
) -> None:
    """Tables and figures were matched by position only while their total was unchanged. A
    co-author who deleted a table or pasted in any picture turned every one of them off, and a
    paragraph dragged below a figure, which keeps its place among the paragraphs, came back
    as "nothing came back"."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path, text, known, b, table, figure = _figure_and_table(tmp_path)
    sent = [b["alpha"], table, b["beta"], b["gamma"], figure, b["delta"]]
    dragged = [b["beta"], figure, b["gamma"], b["delta"]]  # Gamma below the figure
    if change == "a-table-deleted":
        returned = [b["alpha"], *dragged]
    else:
        returned = [b["alpha"], Block(kind="figure", key="pasted"), table, *dragged]

    plan = plan_import(known, sent, returned)
    assert plan.misplaced == ("gamma",)
    assert plan.lost == (("table",) if change == "a-table-deleted" else ())
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == text


def test_a_figure_word_stored_differently_is_still_that_figure(tmp_path: Path) -> None:
    """A picture Word re-encoded no longer matches by what it holds. With as many figures back
    as were sent, it is still that figure, by its place among them."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    _path, _text, known, b, table, _figure = _figure_and_table(tmp_path)
    figure, stored = Block(kind="figure", key="f"), Block(kind="figure", key="re-encoded")
    sent = [b["alpha"], table, b["beta"], b["gamma"], figure, b["delta"]]
    untouched = [b["alpha"], table, b["beta"], b["gamma"], stored, b["delta"]]
    assert plan_import(known, sent, untouched).empty

    dragged = [b["alpha"], table, b["beta"], stored, b["gamma"], b["delta"]]
    assert plan_import(known, sent, dragged).misplaced == ("gamma",)


def test_a_table_or_figure_that_did_not_come_back_is_reported(tmp_path: Path) -> None:
    """A deleted table is an edit the import does not apply, and every move past it goes
    unseen. It said "nothing came back"."""
    from manuscript_guard.merge import plan_import

    _path, _text, known, b, table, figure = _figure_and_table(tmp_path)
    sent = [b["alpha"], table, b["beta"], b["gamma"], figure, b["delta"]]
    plan = plan_import(known, sent, [b["alpha"], b["beta"], b["gamma"], figure, b["delta"]])
    assert plan.lost == ("table",)
    assert not plan.empty


def _two_headed_sections(tmp_path: Path):
    """'# Results': 'Alpha.', a captioned table, 'Beta.' and a figure; '# Funding': 'Gamma.'."""
    from manuscript_guard.docxtext import Block

    path = tmp_path / "main.md"
    text = (
        "# Results\n\nAlpha.\n\n{{table.t}}\n\nBeta.\n\n{{figure.f}}\n\n"
        "# Funding\n\nGamma.\n"
    )
    path.write_text(text, encoding="utf-8")
    words = {"alpha": "Alpha.", "beta": "Beta.", "gamma": "Gamma."}
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    b = {name: Block((name,), w) for name, w in words.items()}
    b.update(
        results=Block((), "Results"),
        caption=Block((), "Table 1: counts."),
        table=Block(kind="table", key="t"),
        figure=Block(kind="figure", key="f"),
        funding=Block((), "Funding"),
    )
    order = ["results", "alpha", "caption", "table", "beta", "figure", "funding", "gamma"]
    return path, text, known, b, [b[n] for n in order]


@pytest.mark.parametrize("deleted", ["table", "figure"])
def test_a_deletion_is_reported_when_another_of_its_kind_is_pasted_elsewhere(
    tmp_path: Path, deleted: str
) -> None:
    """With as many of a kind back as were sent, the unmatched were paired by their place
    among that kind, wherever they were. A table deleted from the Results and another pasted
    into the Funding were taken for one table, and the deletion said "nothing came back"."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    _path, _text, known, b, sent = _two_headed_sections(tmp_path)
    pasted = Block(kind=deleted, key="pasted from elsewhere")
    returned = [block for block in sent if block is not b[deleted]] + [pasted]
    plan = plan_import(known, sent, returned)
    assert plan.lost == (deleted,)


def test_a_figure_stored_anew_is_found_in_its_place_when_a_photograph_is_pasted_elsewhere(
    tmp_path: Path,
) -> None:
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    _path, _text, known, b, sent = _two_headed_sections(tmp_path)
    stored = Block(kind="figure", key="re-encoded")
    photo = Block(kind="figure", key="photo")
    head = [b["results"], b["alpha"], b["caption"], b["table"]]
    tail = [b["funding"], photo, b["gamma"]]
    assert not plan_import(known, sent, [*head, b["beta"], stored, *tail]).lost

    # Beta dragged below the figure, which only its place identifies.
    dragged = [*head, stored, b["beta"], *tail]
    assert plan_import(known, sent, dragged).misplaced == ("beta",)


@pytest.mark.parametrize("moved", ["table", "figure", "heading"])
def test_a_heading_table_or_figure_moved_in_word_is_reported(tmp_path: Path, moved: str) -> None:
    """A table or figure dragged elsewhere, or a heading dragged past another, was the anchor
    the ordering dropped, and it named nobody: "nothing came back", exit 0. None of them moves
    in the .md."""
    from manuscript_guard.merge import plan_import

    _path, _text, known, b, sent = _two_headed_sections(tmp_path)
    name = {"table": "table", "figure": "figure", "heading": "results"}[moved]
    returned = [block for block in sent if block is not b[name]] + [b[name]]

    plan = plan_import(known, sent, returned)
    expected = {"table": ("table", ""), "figure": ("figure", ""), "heading": ("text", "Results")}
    assert plan.strayed == (expected[moved],)
    assert not plan.misplaced and not plan.empty


@pytest.mark.parametrize("method", [98, 14], ids=["unsupported", "corrupt-lzma"])
def test_a_picture_that_cannot_be_read_leaves_its_figure_unkeyed(
    tmp_path: Path, method: int
) -> None:
    """Reading pictures to know figures apart crashed the import with a traceback on a part
    stored with a compression Python cannot read, where the import had never read one; then,
    once that was caught, on an LZMA part whose data is corrupt."""
    import struct

    from manuscript_guard.docxtext import blocks as read

    # An LZMA header zipfile accepts, then data the decompressor rejects as corrupt.
    picture = b"\x09\x04\x05\x00\x5d\x00\x00\x10\x00" + b"\xff" * 32
    document = word_document(tmp_path / "odd.docx", _picture("rId7"), {"rId7": picture})
    data = bytearray(document.read_bytes())
    name = b"word/media/rId7.png"
    local = data.find(b"PK\x03\x04")
    while data[local + 30 : local + 30 + len(name)] != name:
        local = data.find(b"PK\x03\x04", local + 1)
    central = data.find(b"PK\x01\x02")
    while data[central + 46 : central + 46 + len(name)] != name:
        central = data.find(b"PK\x01\x02", central + 1)
    # 98 is PPMd, which zipfile cannot read; 14 is LZMA, which the stored bytes are not.
    data[local + 8 : local + 10] = struct.pack("<H", method)
    data[central + 10 : central + 12] = struct.pack("<H", method)
    document.write_bytes(bytes(data))

    assert [(b.kind, b.key) for b in read(document)] == [("figure", "")]


def _two_outcomes(tmp_path: Path):
    """Methods and Results, each with an '## Outcome' subsection."""
    from manuscript_guard.docxtext import Block

    path = tmp_path / "main.md"
    text = (
        "# Methods\n\nMethods one.\n\n## Outcome\n\nMethods two.\n\n"
        "# Results\n\nResults one.\n\n## Outcome\n\nResults two.\n"
    )
    path.write_text(text, encoding="utf-8")
    words = {"m1": "Methods one.", "m2": "Methods two.", "r1": "Results one.", "r2": "Results two."}
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    b = {name: Block((name,), w) for name, w in words.items()}
    for heading in ("Methods", "Results"):
        b[heading] = Block((), heading)
    b["o1"], b["o2"] = Block((), "Outcome"), Block((), "Outcome")
    sent = [b[n] for n in ("Methods", "m1", "o1", "m2", "Results", "r1", "o2", "r2")]
    return path, text, known, b, sent


@pytest.mark.parametrize("change", ["renamed", "deleted", "renamed-and-a-drag", "pasted-copy"])
def test_two_headings_with_the_same_text_are_each_matched_with_their_own(
    tmp_path: Path, change: str
) -> None:
    """Headings were matched by their text, first come first served. With two "Outcome"
    subheadings, renaming or deleting the first made the second stand in for it, and the
    second was reported as having moved; a real move in the same document went unnamed."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    _path, _text, known, b, sent = _two_outcomes(tmp_path)
    renamed = [block if block is not b["o1"] else Block((), "Outcomes") for block in sent]
    if change == "renamed":
        returned, misplaced = renamed, ()
    elif change == "deleted":
        returned, misplaced = [block for block in sent if block is not b["o1"]], ()
    elif change == "renamed-and-a-drag":
        at = renamed.index(b["o2"])
        returned = renamed[:at] + [b["r2"], b["o2"]]  # Results two above its own subheading
        misplaced = ("r2",)
    else:
        returned, misplaced = [*sent[:2], Block((), "Results"), *sent[2:]], ()

    plan = plan_import(known, sent, returned)
    assert plan.strayed == ()
    assert plan.misplaced == misplaced


def test_a_paragraph_with_display_maths_is_held_where_it_ends_its_section(
    tmp_path: Path,
) -> None:
    """Display maths splits a paragraph in Word, and only its first part carries the
    identifier. Ending its section, it was not recognised: its first part dragged to the top
    was applied, moving the equation and the rest of the paragraph that Word had left behind."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path = tmp_path / "main.md"
    text = (
        "# Intro\n\nFirst paragraph.\n\nSecond, using\n$$x = y$$\nas the measure.\n\n"
        "# Methods\n\nMethods one.\n"
    )
    path.write_text(text, encoding="utf-8")
    words = {
        "p1": "First paragraph.",
        "p2": "Second, using\n$$x = y$$\nas the measure.",
        "m1": "Methods one.",
    }
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    intro, methods = Block((), "Intro"), Block((), "Methods")
    p1, p2 = Block(("p1",), "First paragraph."), Block(("p2",), "Second, using")
    # The equation is a paragraph of its own in Word, with no text a reader of `w:t` sees.
    parts = [Block(kind="equation", key="x=y"), Block((), "as the measure.")]
    m1 = Block(("m1",), "Methods one.")
    sent = [intro, p1, p2, *parts, methods, m1]

    plan = plan_import(known, sent, [intro, p2, p1, *parts, methods, m1])
    assert plan.misplaced and not plan.moved
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == text


def test_a_display_equation_is_a_block_of_its_own(tmp_path: Path) -> None:
    """Word keeps display maths as OMML, which has no `w:t`, so the equation's paragraph was
    read as an empty untagged block: neither a boundary nor anything a report could name."""
    from manuscript_guard.docxtext import blocks as read

    equation = (
        "<w:p><m:oMathPara><m:oMath><m:r><m:t>x</m:t></m:r><m:r><m:t>=y</m:t></m:r>"
        "</m:oMath></m:oMathPara></w:p>"
    )
    other = equation.replace("=y", "=z")
    found = read(word_document(tmp_path / "maths.docx", equation + equation + other))
    assert [b.kind for b in found] == ["equation"] * 3
    assert found[0].key == found[1].key != found[2].key


def _deleted(inner: str) -> str:
    """A paragraph whose content and mark were deleted with Track Changes on."""
    mark = '<w:pPr><w:rPr><w:del w:id="91" w:author="A"/></w:rPr></w:pPr>'
    return f'<w:p>{mark}<w:del w:id="92" w:author="A">{inner}</w:del></w:p>'


@pytest.mark.parametrize("what", ["figure", "equation", "equation-run-by-run", "table"])
def test_a_table_figure_or_equation_deleted_with_track_changes_is_gone(
    tmp_path: Path, what: str
) -> None:
    """Deleted with Track Changes on, a figure still counted as a picture, an equation's text
    was read from inside `w:del`, and a table's deleted rows were still read, so each came
    back as if untouched and the deletion said "nothing came back"."""
    from manuscript_guard.docxtext import blocks as read

    before = (
        '<w:p><w:bookmarkStart w:id="1" w:name="mg-p-main-1"/><w:r><w:t>Before.</w:t></w:r></w:p>'
    )
    drawing = '<w:r><w:drawing><a:blip r:embed="rId7"/></w:drawing></w:r>'
    maths = "<m:oMathPara><m:oMath><m:r><m:t>x=y</m:t></m:r></m:oMath></m:oMathPara>"
    deleted_row = (
        '<w:tr><w:trPr><w:del w:id="93" w:author="A"/></w:trPr>'
        '<w:tc><w:p><w:r><w:delText>426</w:delText></w:r></w:p></w:tc></w:tr>'
    )
    # Word itself deletes an equation run by run, inside an `m:oMath` it leaves in place.
    by_run = maths.replace("<m:r>", '<w:del w:id="97" w:author="A"><m:r>').replace(
        "</m:r>", "</m:r></w:del>"
    )
    body = {
        "figure": _deleted(drawing),
        "equation": _deleted(maths),
        "equation-run-by-run": f"<w:p>{by_run}</w:p>",
        "table": f"<w:tbl>{deleted_row}</w:tbl>",
    }[what]
    found = read(word_document(tmp_path / "tracked.docx", before + body, {"rId7": b"forest"}))
    assert not [b for b in found if b.table], found


def test_a_figure_moved_with_track_changes_is_where_it_was_moved_to(tmp_path: Path) -> None:
    """A tracked move leaves the picture at its old place inside `w:moveFrom` and puts it at
    the new one inside `w:moveTo`. Both were read as figures, and the move was not seen."""
    from manuscript_guard.docxtext import blocks as read

    text = '<w:p><w:bookmarkStart w:id="1" w:name="mg-p-main-1"/><w:r><w:t>Text.</w:t></w:r></w:p>'
    drawing = '<w:r><w:drawing><a:blip r:embed="rId7"/></w:drawing></w:r>'
    away = (
        '<w:p><w:pPr><w:rPr><w:moveFrom w:id="94" w:author="A"/></w:rPr></w:pPr>'
        f'<w:moveFrom w:id="95" w:author="A">{drawing}</w:moveFrom></w:p>'
    )
    arrived = f'<w:p><w:moveTo w:id="96" w:author="A">{drawing}</w:moveTo></w:p>'
    found = read(word_document(tmp_path / "moved.docx", away + text + arrived, {"rId7": b"forest"}))
    assert [b.kind or b.text for b in found] == ["Text.", "figure"]


def _display_maths(tmp_path: Path):
    """'# A': 'Alpha.', a paragraph with display maths in it, 'Omega.'; '# B': 'Beta.'."""
    from manuscript_guard.docxtext import Block

    path = tmp_path / "main.md"
    text = (
        "# A\n\nAlpha.\n\nThe ratio is\n$$x = y$$\nwhere x counts.\n\nOmega.\n\n"
        "# B\n\nBeta.\n"
    )
    path.write_text(text, encoding="utf-8")
    words = {
        "alpha": "Alpha.",
        "p": "The ratio is\n$$x = y$$\nwhere x counts.",
        "omega": "Omega.",
        "beta": "Beta.",
    }
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    b = {name: Block((name,), w) for name, w in words.items()}
    b["p"] = Block(("p",), "The ratio is")
    b.update(
        a=Block((), "A"),
        equation=Block(kind="equation", key="x=y"),
        tail=Block((), "where x counts."),
        B=Block((), "B"),
    )
    order = ["a", "alpha", "p", "equation", "tail", "omega", "B", "beta"]
    return path, text, known, b, [b[n] for n in order]


@pytest.mark.parametrize("change", ["equation-dragged", "equation-deleted", "part-below-it"])
def test_a_display_equation_moved_or_deleted_in_word_is_reported(
    tmp_path: Path, change: str
) -> None:
    """Dragged into another section or deleted, the equation came back as "nothing came
    back", exit 0; so did the first part of its paragraph dragged below it."""
    from manuscript_guard.merge import apply_plan, plan_import

    path, text, known, b, sent = _display_maths(tmp_path)
    if change == "equation-dragged":
        returned = [block for block in sent if block is not b["equation"]] + [b["equation"]]
    elif change == "equation-deleted":
        returned = [block for block in sent if block is not b["equation"]]
    else:
        at = sent.index(b["p"])
        returned = [*sent[:at], b["equation"], b["p"], *sent[at + 2 :]]

    plan = plan_import(known, sent, returned)
    assert not plan.empty
    if change == "equation-dragged":
        assert plan.strayed == (("equation", ""),)
    elif change == "equation-deleted":
        assert plan.lost == ("equation",)
    else:
        assert plan.misplaced == ("p",)
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == text


@needs_pandoc
def test_a_display_equation_dragged_elsewhere_in_a_real_build_is_reported(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end, because the unit tests gave the equation block text a real build does not
    have: dragged alone into the Introduction, the equation came back as "nothing came
    back", exit 0."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    maths = (
        "The ratio itself is\n$$\\mathrm{ROR} = \\frac{a d}{b c}$$\n"
        "where a to d are counts.\n\n"
    )
    text = source.read_text(encoding="utf-8")
    anchor = "Reporting follows the checklist"
    source.write_text(text.replace(anchor, maths + anchor, 1), encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    document = built(project)

    def edit(xml: str) -> str:
        equation = re.search(r"<w:p>(?:(?!<w:p>).)*?<m:oMathPara>.*?</w:p>", xml, re.DOTALL)
        assert equation, "display maths reaches Word as a paragraph of its own"
        tagged = tagged_xml(xml)
        xml = xml.replace(equation.group(0), "", 1)
        return xml.replace(tagged[1], tagged[1] + equation.group(0), 1)

    returned = rewrite(document, tmp_path / "equation.docx", edit)
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert source.read_text(encoding="utf-8") == before
    assert "an equation" in capsys.readouterr().out


def test_a_dragged_heading_that_shares_its_text_is_still_reported(tmp_path: Path) -> None:
    """Paired as a sequence, a dragged heading drops out of the sequence; paired afterwards
    only when its text was unique, a dragged "Outcome" with another "Outcome" in the paper
    was paired with nothing, and the drag came back as "nothing came back"."""
    from manuscript_guard.merge import plan_import

    _path, _text, known, b, sent = _two_outcomes(tmp_path)
    returned = [b["o1"], *[block for block in sent if block is not b["o1"]]]
    plan = plan_import(known, sent, returned)
    assert plan.strayed == (("text", "Outcome"),)
    assert not plan.misplaced


def test_dollars_or_a_comment_opener_inside_code_hold_nothing(tmp_path: Path) -> None:
    """The source was searched for `$$` and `<!--` as written, so a paragraph explaining them
    in inline code was held in place: its rewording refused as display maths or as an open
    comment, and a move past it refused.

    Whether the rewording merges is the rewording's own business, and not asserted here: a
    code span holding `--` comes back from Word as plain text, which the next build
    typesets as a dash."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import _IN_PARTS, _RUNS_ON, plan_import

    paragraphs = {
        "maths": "Display maths goes between `$$` signs.",
        "comment": "An HTML comment opens with `<!--` and a note.",
        "plain": "A plain paragraph after them.",
    }
    _path, known = source_of(tmp_path, paragraphs)
    shown = {name: text.replace("`", "") for name, text in paragraphs.items()}
    sent = [Block((name,), shown[name]) for name in paragraphs]

    reworded = [Block(b.names, b.text.replace(".", ", as ever.")) for b in sent]
    plan = plan_import(known, sent, reworded)
    assert not [r for r in plan.refused if {_IN_PARTS, _RUNS_ON} & set(r.why)]

    moved = plan_import(known, sent, [sent[2], sent[0], sent[1]])
    assert not moved.misplaced and moved.moved


@pytest.mark.parametrize(
    "para",
    [
        "Models were fitted with `glmer` from\n$$y = X b$$\nusing the `nlme`{.r} package.",
        "Units ~~ $$x = y$$ ~~ after.",
        "See `a` here <!-- a note `b`{.x}",
        "Commands are quoted in backticks (\\`); the estimate is $$x = u / w$$ as in `metafor`.",
        "Commands are quoted in backticks (\\`). <!-- an earlier draft, which quoted `grep`:",
        "Files were written under C:\\\\`data` here. <!-- an earlier draft, which quoted `grep`:",
        "Each field had a backtick before it, as in \\``onset`.\n"
        "<!-- an earlier draft, which quoted `grep`:",
        "A so-called ``crude'' ratio came from `ror.\n<!-- an earlier draft, which quoted `grep`:",
    ],
    ids=[
        "maths-after-a-code-span",
        "maths-inside-strikeout",
        "comment-after-code-spans",
        "maths-after-an-escaped-backtick",
        "comment-after-an-escaped-backtick",
        "comment-after-an-escaped-backslash",
        "comment-after-a-code-span-behind-an-escaped-backtick",
        "comment-after-a-double-backtick-that-never-closes",
    ],
)
def test_display_maths_or_an_open_comment_is_found_past_code_and_strikeout(
    tmp_path: Path, para: str
) -> None:
    """Read with the rewording's scan, `$$` or `<!--` could be swallowed by what it took for
    one long code span with attributes, or for struck-through text, and the paragraph was
    not held: its first part dragged up was applied, carrying the equation along."""
    from manuscript_guard.merge import _held_in_place

    _path, known = source_of(tmp_path, {"p": para})
    assert _held_in_place(known, {"p": para.split("\n")[0]}).get("p") in ("in-parts", "runs-on")


def test_an_equation_after_a_paragraph_in_the_document_as_sent_holds_that_paragraph(
    tmp_path: Path,
) -> None:
    """Display maths was only found by reading the source, and every reading of Markdown
    short of pandoc's can miss one: an escaped backtick opened what was taken for a code
    span, which swallowed the `$$`. The document as sent says it outright: an equation
    directly after a paragraph is part of that paragraph, even at the end of its section."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path = tmp_path / "main.md"
    text = "# A\n\nFirst paragraph.\n\nSecond, however it is written.\n\n# B\n\nBeta.\n"
    path.write_text(text, encoding="utf-8")
    words = {"p1": "First paragraph.", "p2": "Second, however it is written.", "b": "Beta."}
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    heading_a, heading_b = Block((), "A"), Block((), "B")
    p1, p2 = Block(("p1",), "First paragraph."), Block(("p2",), "Second,")
    equation, tail = Block(kind="equation", key="x=y"), Block((), "however it is written.")
    beta = Block(("b",), "Beta.")
    sent = [heading_a, p1, p2, equation, tail, heading_b, beta]

    plan = plan_import(known, sent, [heading_a, p2, p1, equation, tail, heading_b, beta])
    assert plan.misplaced and not plan.moved
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == text


def test_pandocs_no_break_space_taken_out_of_a_held_paragraph_is_no_edit(tmp_path: Path) -> None:
    """Pandoc puts a no-break space after "e.g.", and Word's text shows it. Taken out again,
    the next build puts it back, so an ordinary paragraph merges as nothing; a paragraph held
    for the fence under it was refused instead, exit 1."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    nbsp = chr(0xA0)
    paragraphs = {"z": "Zeta, e.g. this one, last inside the div.\n:::", "o": "Omega."}
    _path, known = source_of(tmp_path, paragraphs)
    was = f"Zeta, e.g.{nbsp}this one, last inside the div."
    sent = [Block(("z",), was), Block(("o",), "Omega.")]
    returned = [Block(("z",), was.replace(nbsp, " ")), sent[1]]
    plan = plan_import(known, sent, returned)
    assert plan.empty, plan.refused


@pytest.mark.parametrize("held", [True, False], ids=["held", "ordinary"])
def test_a_no_break_space_the_author_wrote_is_an_edit_when_taken_out(
    tmp_path: Path, held: bool
) -> None:
    """Every no-break space turned into a plain space was taken for pandoc's own and dropped,
    exit 0 and "nothing came back", including one the author had written (`\\ `, a literal
    one or `&nbsp;`): the next build put it back, and the co-author's change was lost. Only
    a source with no no-break space of its own can have had one put in by pandoc."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    nbsp = chr(0xA0)
    text = "Zeta cites Hy's\\ law for the liver, last inside the div."
    paragraphs = {"z": text + ("\n:::" if held else ""), "o": "Omega."}
    _path, known = source_of(tmp_path, paragraphs)
    was = "Zeta cites Hy's" + nbsp + "law for the liver, last inside the div."
    sent = [Block(("z",), was), Block(("o",), "Omega.")]
    plan = plan_import(known, sent, [Block(("z",), was.replace(nbsp, " ")), sent[1]])
    assert not plan.empty
    assert ("z" in plan.merged) != held


@pytest.mark.parametrize("written", ["&NonBreakingSpace;", "&#0160;"], ids=["named", "padded"])
def test_every_spelling_of_a_no_break_space_the_author_wrote_is_theirs(
    tmp_path: Path, written: str
) -> None:
    """Pandoc reads `&NonBreakingSpace;` and `&#0160;` as no-break spaces too, and neither was
    on the list of ones an author can write: replaced with a plain space in a held paragraph,
    the change was taken for pandoc's own and dropped, exit 0 and "nothing came back"."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    nbsp = chr(0xA0)
    text = f"Zeta cites Hy's{written}law for the liver, last inside the div."
    _path, known = source_of(tmp_path, {"z": text + "\n:::", "o": "Omega."})
    was = "Zeta cites Hy's" + nbsp + "law for the liver, last inside the div."
    sent = [Block(("z",), was), Block(("o",), "Omega.")]
    plan = plan_import(known, sent, [Block(("z",), was.replace(nbsp, " ")), sent[1]])
    assert not plan.empty
    assert "z" not in plan.merged


def test_an_edit_after_the_equation_is_not_dropped_with_an_undone_no_break_space(
    tmp_path: Path,
) -> None:
    """A paragraph with display maths reaches Word in parts and is held. The co-author took out
    the no-break space pandoc put after "e.g." in the first part, and reworded the part after
    the equation. The first part was judged pandoc's typesetting undone and skipped, and
    the rewording after the equation was dropped: exit 0, "nothing came back"."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    nbsp = chr(0xA0)
    source = (
        "The ratio, e.g. for the class, is\n$$\\mathrm{ROR} = \\frac{a d}{b c}$$\n"
        "where the cells are counts of reports."
    )
    _path, known = source_of(tmp_path, {"p": source, "o": "Omega."})
    first = f"The ratio, e.g.{nbsp}for the class, is"
    equation = Block(kind="equation", key="ROR=ad/bc")
    tail = "where the cells are counts of reports."
    sent = [Block(("p",), first), equation, Block((), tail), Block(("o",), "Omega.")]
    returned = [
        Block(("p",), first.replace(nbsp, " ")),
        equation,
        Block((), tail.replace("counts of", "counts of case")),
        Block(("o",), "Omega."),
    ]
    plan = plan_import(known, sent, returned)
    assert not plan.empty
    assert "p" in [r.name for r in plan.refused]


def test_a_split_around_an_equation_moved_between_its_halves_is_refused(
    tmp_path: Path,
) -> None:
    """An equation from further down, cut and pasted between the halves of a paragraph split
    in Word, still matches itself, and the search for new text beside the paragraph stopped
    there: the paragraph was merged as its first half, the rest gone from the source."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    paragraphs = {
        "p": "First half here. Second half here.",
        "q": "Another paragraph.",
        "r": "A last one.",
    }
    _path, known = source_of(tmp_path, paragraphs)
    b = {name: Block((name,), text) for name, text in paragraphs.items()}
    equation = Block(kind="equation", key="x=y")
    sent = [b["p"], b["q"], equation, b["r"]]
    returned = [
        Block(("p",), "First half here."),
        equation,
        Block((), "Second half here."),
        b["q"],
        b["r"],
    ]
    plan = plan_import(known, sent, returned)
    assert "p" not in plan.merged
    assert "p" in [r.name for r in plan.refused]


@pytest.mark.parametrize("inserted", ["equation", "figure"])
def test_a_split_around_an_inserted_equation_or_picture_is_refused(
    tmp_path: Path, inserted: str
) -> None:
    """A paragraph split in two with a new equation or a pasted picture between its halves
    was merged as its first half: the split was recognised by new text beside the paragraph,
    and the search for it stopped at the first block that was not prose."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    paragraphs = {"p": "First half here. Second half here.", "q": "Another paragraph."}
    _path, known = source_of(tmp_path, paragraphs)
    sent = [Block((name,), text) for name, text in paragraphs.items()]
    returned = [
        Block(("p",), "First half here."),
        Block(kind=inserted, key="new"),
        Block((), "Second half here."),
        sent[1],
    ]
    plan = plan_import(known, sent, returned)
    assert not plan.merged
    assert [r.name for r in plan.refused] == ["p"]


def test_a_held_paragraph_dragged_past_two_that_were_swapped_is_the_one_named(
    tmp_path: Path,
) -> None:
    """A held paragraph weighed exactly as much as the two it passed when the diff called one
    of them moved, and the tie named the two."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    path = tmp_path / "main.md"
    text = "# A\n\nA one.\n\nA two.\n\n<!-- a note -->\n\n# B\n\nB one.\n"
    path.write_text(text, encoding="utf-8")
    words = {"a1": "A one.", "a2": "A two.", "c": "<!-- a note -->", "b1": "B one."}
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    b = {name: Block((name,), "" if name == "c" else w) for name, w in words.items()}
    heading_a, heading_b = Block((), "A"), Block((), "B")
    sent = [heading_a, b["a1"], b["a2"], b["c"], heading_b, b["b1"]]
    returned = [heading_a, b["c"], b["a2"], b["a1"], heading_b, b["b1"]]

    plan = plan_import(known, sent, returned)
    assert plan.misplaced == ("c",)


def test_a_held_paragraph_dragged_below_two_the_diff_calls_moved_is_the_one_named(
    tmp_path: Path,
) -> None:
    """The mirror of the case above: dragged down past two paragraphs that were also
    swapped, the held paragraph (5) outweighed the two the diff called moved (2 + 2)."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    paragraphs = {
        "z": "Zeta, last inside the div.\n:::",
        "a": "Alpha after the div.",
        "b": "Beta after the div.",
    }
    _path, known = source_of(tmp_path, paragraphs)
    b = {
        "z": Block(("z",), "Zeta, last inside the div."),
        "a": Block(("a",), paragraphs["a"]),
        "b": Block(("b",), paragraphs["b"]),
    }
    plan = plan_import(known, [b["z"], b["a"], b["b"]], [b["b"], b["a"], b["z"]])
    assert plan.misplaced == ("z",)


def test_a_held_paragraph_dragged_past_several_is_the_one_named(tmp_path: Path) -> None:
    """A held paragraph outweighed every other paragraph together, so the Methods' empty
    comment line dragged to the top of the Methods reported the four paragraphs it passed."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    path = tmp_path / "main.md"
    text = "# A\n\nA one.\n\nA two.\n\nA three.\n\n<!-- a note -->\n\n# B\n\nB one.\n"
    path.write_text(text, encoding="utf-8")
    words = {"a1": "A one.", "a2": "A two.", "a3": "A three.", "c": "<!-- a note -->",
             "b1": "B one."}
    known = {name: (path, w, text.index(w)) for name, w in words.items()}
    b = {name: Block((name,), "" if name == "c" else w) for name, w in words.items()}
    heading_a, heading_b = Block((), "A"), Block((), "B")
    sent = [heading_a, b["a1"], b["a2"], b["a3"], b["c"], heading_b, b["b1"]]
    returned = [heading_a, b["c"], b["a1"], b["a2"], b["a3"], heading_b, b["b1"]]

    plan = plan_import(known, sent, returned)
    assert plan.misplaced == ("c",)
    apply_plan(known, plan)
    assert path.read_text(encoding="utf-8") == text


@needs_pandoc
def test_a_move_to_the_end_of_the_methods_does_not_land_inside_its_comment(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end on the example, whose Methods end with a comment that spans a blank line.
    Dragged below the comment's empty line, "The reporting odds ratio was computed..." was
    written inside the comment and the rebuilt document no longer contained it, exit 0.

    Held in place at first, the comment's first line was a section of its own and the move
    was refused. The comment now carries no identifier at all, so it is not a slot, and the
    move is applied within the Methods, above the comment, as Word shows it."""
    from manuscript_guard.cli import main

    document = built(project)
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")

    def edit(xml: str) -> str:
        moved = tagged_xml(xml)[5]
        assert "was computed from a 2 x 2 table" in moved
        results = re.search(r"<w:p>(?:(?!<w:p>).)*?>Results</w:t></w:r></w:p>", xml, re.DOTALL)
        assert results, "the Results heading"
        # The last thing in the Methods, just above the next heading: below the empty line.
        return xml.replace(moved, "", 1).replace(results.group(0), moved + results.group(0), 1)

    returned = rewrite(document, tmp_path / "comment.docx", edit)
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    after = source.read_text(encoding="utf-8")
    comment = re.search(r"<!--.*?-->", before, re.DOTALL).group(0)
    assert comment in after, "the comment is whole"
    outside = re.sub(r"<!--.*?-->", "", after, flags=re.DOTALL)
    assert "was computed" in outside, "the moved paragraph is outside the comment"
    # Last in the Methods, as Word has it: after the paragraph it passed, before the comment.
    methods = after[after.index("# Methods") : after.index("# Results")]
    assert methods.index("Reporting follows") < methods.index("was computed from a 2 x 2")
    assert methods.index("was computed from a 2 x 2") < methods.index("<!--")
    assert "reordered 1 paragraph" in capsys.readouterr().out


@needs_pandoc
def test_a_rewording_of_a_div_s_last_paragraph_keeps_the_div_closed(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end: the closing `:::` glued to the div's last paragraph was deleted with the
    rewording, and the div ran to the end of the document on the next build, exit 0.

    Held in place at first, and its rewording refused naming the fence. That paragraph now
    carries no identifier at all, so the rewording is listed with the other paragraphs
    without one, not applied, and the div stays closed."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    div = "::: {.note}\nAlpha one inside the div.\n\nZeta two inside the div, last.\n:::\n\n"
    heading = "# Data availability"
    source.write_text(
        source.read_text(encoding="utf-8").replace(heading, div + heading, 1), encoding="utf-8"
    )
    before = source.read_text(encoding="utf-8")
    document = built(project)
    returned = rewrite(
        document,
        tmp_path / "div.docx",
        lambda xml: xml.replace("Zeta two inside the div, last.", "Zeta two, reworded, last.", 1),
    )
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert source.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "without an identifier" in out and "+ Zeta two, reworded, last." in out


def repackage(document: Path, target: Path, changes: dict, added: dict[str, bytes]) -> Path:
    """A co-author, simulated at the package level: each named part passed through its change,
    and new parts added, as Word does when a picture is pasted in."""
    with zipfile.ZipFile(document) as zin, zipfile.ZipFile(
        target, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in changes:
                data = changes[item.filename](data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)
        for name, data in added.items():
            zout.writestr(name, data)
    return target


@needs_pandoc
def test_a_move_past_a_figure_is_reported_after_a_picture_is_pasted_in(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end: with a picture pasted into the Introduction, a Discussion paragraph dragged
    below the figure beside it came back as "nothing came back", exit 0."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    text = source.read_text(encoding="utf-8").replace("\n\n{{figure.forest}}", "", 1)
    first = "reporting period.\n"
    source.write_text(text.replace(first, first + "\n{{figure.forest}}\n", 1), encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    document = built(project)

    def edit(xml: str) -> str:
        tagged = tagged_xml(xml)
        moved = next(p for p in tagged if "exceeds the class-level estimate" in p)
        figure = re.search(r"<w:p>(?:(?!<w:p>).)*?<w:drawing>.*?</w:p>", xml, re.DOTALL).group(0)
        assert xml.index(moved) < xml.index(figure) < xml.index(tagged[tagged.index(moved) + 1])
        pasted = re.sub(r'r:embed="[^"]*"', 'r:embed="rIdPasted"', figure)
        xml = xml.replace(moved, "", 1).replace(figure, figure + moved, 1)
        return xml.replace(tagged[1], tagged[1] + pasted, 1)

    def rels(xml: str) -> str:
        return xml.replace(
            "</Relationships>",
            f'<Relationship Id="rIdPasted" Type="{RELS}/image" Target="media/pasted.png" />'
            "</Relationships>",
        )

    returned = repackage(
        document,
        tmp_path / "pasted.docx",
        {"word/document.xml": edit, "word/_rels/document.xml.rels": rels},
        {"word/media/pasted.png": b"\x89PNG\r\n\x1a\n a photograph of the ward"},
    )
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert source.read_text(encoding="utf-8") == before
    assert "different section" in capsys.readouterr().out


@pytest.mark.parametrize(
    "source",
    ["Before $$y = z$$ and after.", "Before <!-- a note --> and after."],
    ids=["display-maths", "html-comment"],
)
def test_markup_that_word_text_cannot_carry_is_refused(source: str) -> None:

    aligned = align(source, "Before and after.", "Before and just after.", [])
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
def test_a_rewording_merges_in_a_paragraph_pandoc_typeset(project: Path, tmp_path: Path) -> None:
    """End to end, through pandoc's own smart punctuation rather than a guess at it."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    typeset = "restriction on age or sex -- the generator's only rule."
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "restriction on age or sex.", typeset, 1
        ),
        encoding="utf-8",
    )
    document = built(project)
    returned = rewrite(
        document,
        tmp_path / "typeset.docx",
        lambda xml: xml.replace("Reports were included", "Reports were all included", 1),
    )
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    after = source.read_text(encoding="utf-8")
    assert "Reports were all included" in after
    assert "{{results.cohort.n_years}}" in after
    assert closed(after)


MARKUP = {
    "apostrophe": "The drug's ratio was {{results.ror.point}} overall.",
    "quotes": 'The so-called "signal" was {{results.ror.point}}.',
    "dashes": "Rates -- and odds --- were {{results.ror.point}} here.",
    "ellipsis": "Odds... were {{results.ror.point}} here.",
    "emphasis": "The *striking* and **strong** ratio was {{results.ror.point}}.",
    "code": "Run with `--offline_mode`, the ratio was {{results.ror.point}}.",
    # A token against the code's closing backtick. The bookmark's own backtick joined it, and
    # pandoc wrote the code into the document as raw XML: with `<` or `&` in it, the marked
    # build was not a readable .docx, and import stopped for the whole manuscript.
    "after-code": "Filtered on `age<limit`{{results.ror.point}} as planned.",
    "citation-after-code": "As in `x&y`[@fictionalClassSignal2019] it was {{results.ror.point}}.",
    "code-opening-the-paragraph": "`age<limit`{{results.ror.point}} was the cut-off ratio.",
    "after-double-backtick-code": "Filtered on ``a`b<c``{{results.ror.point}} as planned.",
    "escape": "The ratio \\*was\\* {{results.ror.point}} here.",
    "super-and-subscript": "Per m^2^ of H~2~O, the ratio was {{results.ror.point}}.",
    "intraword-underscore": "The file_name ratio was {{results.ror.point}}.",
    "abbreviations": "As Dr. Smith noted, e.g. here, the ratio was {{results.ror.point}}.",
    "narrative-citation": "As @fictionalClassSignal2019 found, it was {{results.ror.point}}.",
    "prefixed-citation": "It was {{results.ror.point}} [see @fictionalClassSignal2019, p. 3].",
    "span": "The [ratio]{.smallcaps} was {{results.ror.point}}.",
    "strikeout": "The ~~old~~ ratio was {{results.ror.point}}.",
    "citations-in-a-row": "Both [@fictionalClassSignal2019], [@fictionalHepaticCohort2021] "
    "agree on {{results.ror.point}}.",
    "value-ends-it": "The reporting odds ratio was {{results.ror.point}}.",
    "bracket-inside-citation": "Quoted [@fictionalClassSignal2019, p. 3 [emphasis added]] as "
    "{{results.ror.point}}.",
    "narrative-with-locator": "As @fictionalClassSignal2019 [p. 3] found, it was "
    "{{results.ror.point}}.",
    "interval": "The interval was [{{results.ror.ci_low}}, {{results.ror.ci_high}}] here.",
    "binding-inside-citation": "As shown [@fictionalClassSignal2019, table "
    "{{results.cohort.n_years}}], it was {{results.ror.point}}.",
    "narrative-then-bracketed": "As @fictionalClassSignal2019 [@fictionalHepaticCohort2021] "
    "found, it was {{results.ror.point}}.",
    "locator-on-the-next-line": "As @fictionalClassSignal2019\n[p. 3] found, it was "
    "{{results.ror.point}}.",
    "at-sign-in-code": "Run `fit(@cohort)` and the ratio was {{results.ror.point}}.",
    "narrative-then-suppressed": "As @fictionalClassSignal2019 [-@fictionalHepaticCohort2021] "
    "found, it was {{results.ror.point}}.",
    "locator-without-a-space": "As @fictionalClassSignal2019[p. 3] found, it was "
    "{{results.ror.point}}.",
    "link-after-a-key": "As @fictionalClassSignal2019 [the protocol](https://example.org) "
    "says, it was {{results.ror.point}}.",
    "at-sign-in-a-link-address": "See [the thread](https://mastodon.social/@someone); it was "
    "{{results.ror.point}}.",
}


@needs_pandoc
def test_every_way_pandoc_renders_prose_still_takes_a_rewording(project: Path) -> None:
    """Asserted on pandoc's own output rather than on a guess at it.

    The token extents come from a second build with every binding and citation bookmarked,
    so two things must hold for each paragraph: marking changed nothing a co-author sees,
    and a rewording merges with every token back in the source.
    """
    from manuscript_guard.build import OFFLINE, assemble, build_document
    from manuscript_guard.contracts import load_namespace, load_project
    from manuscript_guard.roundtrip import align, read_blocks, tagged_paragraphs

    main_md = project / "manuscript" / "main.md"
    main_md.write_text(
        main_md.read_text(encoding="utf-8") + "\n\n# More\n\n" + "\n\n".join(MARKUP.values()),
        encoding="utf-8",
    )
    projekt, _ = load_project(project)
    namespace, results, _lit, _r = load_namespace(projekt)
    plain = project / "build" / "plain.docx"
    marked = project / "build" / "marked.docx"
    build_document(projekt, assemble(projekt, namespace, results)[0], mode=OFFLINE, output=plain)
    build_document(
        projekt, assemble(projekt, namespace, results, mark=True)[0], mode=OFFLINE, output=marked
    )
    sent = {b.names[0]: b for b in read_blocks(plain) if b.names}
    extents = {b.names[0]: b for b in read_blocks(marked) if b.names}
    assert sent.keys() == extents.keys()

    by_source = {entry[1]: name for name, entry in tagged_paragraphs(projekt).items()}
    for label, source in MARKUP.items():
        name = by_source[source]
        assert extents[name].text == sent[name].text, f"{label}: marking changed the text"
        rendered = sent[name].text
        aligned = align(source, rendered, rendered + " Indeed.", extents[name].tokens)
        assert aligned.rebuilt is not None, f"{label}: {aligned}"
        assert aligned.rebuilt.startswith(source[:-1]), f"{label}: {aligned.rebuilt}"
        # An edit at the start, where the markup is: what the build printed of that stretch
        # is checked against the source, and typesetting alone must not fail that check.
        opened = align(source, rendered, "Indeed. " + rendered, extents[name].tokens)
        assert not opened.unaligned, f"{label}: an edit at the start was refused as unread"
    for name, block in sent.items():
        assert extents[name].text == block.text, f"marking changed {block.text[:60]!r}"


@needs_pandoc
def test_a_value_ending_a_sentence_takes_a_rewording_end_to_end(
    project: Path, tmp_path: Path
) -> None:
    """Guessing the extents, the final "." was found inside "3.84" and the paragraph was
    refused as "'3' comes from results.ror.point" - a value nobody had changed."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    sentence = "The odds ratio for bleeding was {{results.ror.point}}."
    source.write_text(
        source.read_text(encoding="utf-8") + "\n\n# Bleeding\n\n" + sentence + "\n",
        encoding="utf-8",
    )
    returned = rewrite(
        built(project),
        tmp_path / "bleeding.docx",
        lambda xml: xml.replace("for bleeding was", "for major bleeding was", 1),
    )
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    after = source.read_text(encoding="utf-8")
    assert "The odds ratio for major bleeding was {{results.ror.point}}." in after


@needs_pandoc
def test_a_token_straight_after_inline_code_leaves_import_working(
    project: Path, tmp_path: Path
) -> None:
    """The bookmark's backtick joined the code's closing one, pandoc wrote `age<65` into the
    marked build as raw XML, and that build was not a readable .docx: `import` exited 2 over
    an internal file the author had never seen, for every paragraph of the manuscript."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    sentence = "Cases were filtered on `dose<limit`{{results.ror.point}} as the protocol planned."
    source.write_text(
        source.read_text(encoding="utf-8") + "\n\n# Filters\n\n" + sentence + "\n",
        encoding="utf-8",
    )
    document = built(project)
    assert main(["import", str(document), str(project)]) == 0
    returned = rewrite(
        document,
        tmp_path / "filters.docx",
        lambda xml: xml.replace("the protocol planned", "the protocol first planned", 1),
    )
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    after = source.read_text(encoding="utf-8")
    assert "`dose<limit`{{results.ror.point}} as the protocol first planned." in after


@needs_pandoc
def test_a_binding_inside_inline_code_is_left_unmarked(project: Path) -> None:
    """Pandoc reads no bookmark inside code: marked there, the raw spans broke the code open
    and printed their own syntax. The binding is left unmarked, so a rewording of its
    paragraph is refused, as one whose extents cannot be read is."""
    from manuscript_guard.build import OFFLINE, assemble, build_document
    from manuscript_guard.contracts import load_namespace, load_project
    from manuscript_guard.roundtrip import align, read_blocks, tag, tagged_paragraphs

    sentence = "Coded as `n < {{results.ror.point}}` in the script."
    assert "{=openxml}" not in tag(sentence + "\n", "main.md", mark=True)
    main_md = project / "manuscript" / "main.md"
    main_md.write_text(
        main_md.read_text(encoding="utf-8") + "\n\n# Code\n\n" + sentence + "\n",
        encoding="utf-8",
    )
    projekt, _ = load_project(project)
    namespace, results, _lit, _r = load_namespace(projekt)
    plain = project / "build" / "plain.docx"
    marked = project / "build" / "marked.docx"
    build_document(projekt, assemble(projekt, namespace, results)[0], mode=OFFLINE, output=plain)
    build_document(
        projekt, assemble(projekt, namespace, results, mark=True)[0], mode=OFFLINE, output=marked
    )
    name = {entry[1]: n for n, entry in tagged_paragraphs(projekt).items()}[sentence]
    sent = {b.names[0]: b for b in read_blocks(plain) if b.names}[name]
    extents = {b.names[0]: b for b in read_blocks(marked) if b.names}[name]
    assert extents.text == sent.text and extents.tokens == ()
    assert align(sentence, sent.text, sent.text + " Indeed.", extents.tokens).rebuilt is None


@needs_pandoc
def test_an_unreadable_marked_build_refuses_rather_than_stopping(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Whatever else can make pandoc write a marked build that will not open, it is the
    build import reads token positions from, not the document the co-author returned. Now
    the run carries on without the positions: a reworded paragraph holding a binding or a
    citation is refused, one without is merged, and the report says why."""
    from manuscript_guard import roundtrip
    from manuscript_guard.cli import main

    reader = roundtrip.read_blocks

    def unreadable(document: Path):
        if document.name == "reference-tokens.docx":
            raise roundtrip.RoundTripError(f"{document.name} is not a readable .docx: broken")
        return reader(document)

    source = project / "manuscript" / "main.md"
    with_token = "The odds ratio for bleeding was {{results.ror.point}} in the end."
    without = "Bleeding was the event that mattered most here."
    source.write_text(
        source.read_text(encoding="utf-8") + f"\n\n# Bleeding\n\n{with_token}\n\n{without}\n",
        encoding="utf-8",
    )
    returned = rewrite(
        built(project),
        tmp_path / "bleeding.docx",
        lambda xml: xml.replace("in the end", "at the end", 1).replace(
            "mattered most here", "mattered most of all here", 1
        ),
    )
    monkeypatch.setattr(roundtrip, "read_blocks", unreadable)
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    report = capsys.readouterr()
    assert "binding or citation" in report.err + report.out
    after = source.read_text(encoding="utf-8")
    assert with_token in after, "a paragraph with a token was merged without its extents"
    assert "Bleeding was the event that mattered most of all here." in after


@needs_pandoc
def test_a_link_to_a_heading_beside_a_binding_is_not_deleted_end_to_end(
    project: Path, tmp_path: Path
) -> None:
    """`[Bleeding]` is a link to the heading, and Word's text holds only its words: an edit
    beside it wrote the paragraph back without the link, with exit 0."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    sentence = "As detailed in [Bleeding], the ratio was {{results.ror.point}} overall."
    source.write_text(
        source.read_text(encoding="utf-8") + "\n\n# Bleeding\n\n" + sentence + "\n",
        encoding="utf-8",
    )
    returned = rewrite(
        built(project),
        tmp_path / "bleeding.docx",
        lambda xml: xml.replace("As detailed in", "As described in", 1),
    )
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert sentence in source.read_text(encoding="utf-8")


@needs_pandoc
def test_a_full_stop_typed_against_a_citation_does_not_print_its_key_end_to_end(
    project: Path, tmp_path: Path
) -> None:
    """With the space after a full stop deleted in Word, the citation merged as
    `cohort.@fictionalClassSignal2019`, which pandoc prints as the key, and `check` passed."""
    from manuscript_guard.cli import main
    from manuscript_guard.roundtrip import paragraph_text

    source = project / "manuscript" / "main.md"
    sentence = (
        "The signal was clear in this cohort. @fictionalClassSignal2019 reported a ratio of "
        "{{results.ror.point}}."
    )
    source.write_text(
        source.read_text(encoding="utf-8") + "\n\n# Bleeding\n\n" + sentence + "\n",
        encoding="utf-8",
    )
    returned = rewrite(
        built(project),
        tmp_path / "bleeding.docx",
        # The space after the full stop is a run of its own.
        lambda xml: xml.replace(
            'clear in this cohort.</w:t></w:r><w:r><w:t xml:space="preserve"> </w:t>',
            'clear in the whole cohort.</w:t></w:r><w:r><w:t xml:space="preserve"></w:t>',
            1,
        ),
    )
    assert "whole cohort." in "".join(paragraph_text(returned).values())
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert sentence in source.read_text(encoding="utf-8")


@needs_pandoc
def test_a_citation_after_et_al_takes_a_rewording_end_to_end(
    project: Path, tmp_path: Path
) -> None:
    """Marked, the citation after "et al." got pandoc's no-break space where the plain build
    has a plain one, so the extents were distrusted and every edit to the paragraph was
    refused as "could not be told apart from its prose"."""
    from manuscript_guard.cli import main

    source = project / "manuscript" / "main.md"
    sentence = "Smith et al. [@fictionalHepaticCohort2021] found a ratio of {{results.ror.point}}."
    source.write_text(
        source.read_text(encoding="utf-8") + "\n\n# Bleeding\n\n" + sentence + "\n",
        encoding="utf-8",
    )
    returned = rewrite(
        built(project),
        tmp_path / "bleeding.docx",
        lambda xml: xml.replace("found a ratio of", "reported a ratio of", 1),
    )
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    assert sentence.replace("found", "reported") in source.read_text(encoding="utf-8")


@needs_pandoc
@pytest.mark.parametrize(
    ("paragraph", "was", "now", "code"),
    [
        pytest.param(
            "Run the tool with `--offline` and the ratio was {{results.ror.point}} overall.",
            "Run the tool",
            "Start the tool",
            "--offline",
            id="dashes-beside-a-binding",
        ),
        pytest.param(
            "A comment is opened with `<!--` in the source files.",
            "is opened",
            "is started",
            "<!--",
            id="comment-marker",
        ),
        pytest.param(
            'Quote it as `"exact"` or `...` in the query string.',
            "Quote it",
            "Write it",
            '"exact"',
            id="quotes-and-dots",
        ),
    ],
)
def test_code_beside_an_edit_is_never_typeset(
    project: Path, tmp_path: Path, paragraph: str, was: str, now: str, code: str
) -> None:
    """Rebuilt from Word's text, the code span came back as prose, and pandoc typeset it:
    `--offline` printed as "–offline" and `<!--` as "<!–", and import exited 0. Whatever
    import does with the edit, the next build prints the code as it was written."""
    from manuscript_guard.cli import main
    from manuscript_guard.roundtrip import paragraph_text

    source = project / "manuscript" / "main.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n\n# Tools\n\n" + paragraph + "\n",
        encoding="utf-8",
    )
    returned = rewrite(
        built(project), tmp_path / "tools.docx", lambda xml: xml.replace(was, now, 1)
    )
    assert now in "".join(paragraph_text(returned).values()), "the edit reached the document"
    main(["import", str(returned), str(project), "--apply"])
    printed = "".join(paragraph_text(built(project)).values())
    assert code in printed, printed[-300:]


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
    when pandoc was missing. The returned document is read first, to know which document to
    rebuild, so it has to be readable and carry one of the paper's identifiers."""
    import manuscript_guard.build.document as document
    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.review import document_digest
    from manuscript_guard.roundtrip import tagged_paragraphs

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    loaded = load_project(project)[0]
    identifier = next(
        name
        for name, (path, _text, _start) in tagged_paragraphs(loaded).items()
        if path.name == "main.md"
    )
    returned = tmp_path / "back.docx"
    with zipfile.ZipFile(returned, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{w}"><w:body><w:p>'
            f'<w:bookmarkStart w:id="0" w:name="{identifier}"/><w:bookmarkEnd w:id="0"/>'
            f"<w:r><w:t>Text.</w:t></w:r></w:p></w:body></w:document>",
        )
    stamp_into(returned, document_digest(loaded))

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
def test_a_comment_opener_typed_in_word_leaves_every_paragraph_identified(
    project: Path, tmp_path: Path
) -> None:
    """End to end. A co-author types `<!--` into a paragraph, and the merge writes it
    escaped, `\\<!--`, which pandoc prints as typed. The next build took it for a comment
    opened there and closed by a `-->` further down, and the paragraphs between went without
    an identifier: a co-author's next edit to them was dropped with "nothing came back"."""
    from manuscript_guard.cli import main
    from manuscript_guard.roundtrip import paragraph_text

    with_paragraphs(
        project, "Alpha comes first.", "Beta sits between.", "Gamma shows an arrow --> here."
    )
    # Written into document.xml, where Word stores a typed `<` as `&lt;`.
    edits = {"Alpha comes first.": "Alpha comes first &lt;!-- as typed."}
    returned = edit_docx(built(project), tmp_path / "back.docx", edits)

    assert main(["import", str(returned), str(project), "--apply"]) == 0
    source = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert f"Alpha comes first {BACKSLASH}<!-- as typed." in source
    # Pandoc prints the `--` of `<!--` as a dash; the words are what is compared.
    printed = list(paragraph_text(built(project)).values())
    assert "Beta sits between." in printed
    assert any(text.startswith("Gamma shows an arrow") for text in printed)
    assert any(text.startswith("Alpha comes first <!") for text in printed)


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

    assert main(["import", str(returned), str(project), "--apply"]) == 0
    assert paragraph.replace("plain.", "clear.") in (project / "manuscript" / "main.md").read_text(
        encoding="utf-8"
    ), "the rewording lands, and the citation is still a citation"


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
    definition and left without an identifier. Where pandoc printed it, or the lines under
    its first, a co-author's edit to it was dropped while `import` said nothing came back;
    where pandoc did not, the paragraph was missing from the document."""
    from manuscript_guard.cli import main

    with_paragraphs(project, paragraph)
    returned = edit_docx(built(project), tmp_path / "back.docx", {was: now})

    assert main(["import", str(returned), str(project), "--apply"]) == 0
    assert now in (project / "manuscript" / "main.md").read_text(encoding="utf-8")


@needs_pandoc
@pytest.mark.parametrize(
    ("definition", "second", "part", "resolved"),
    [
        pytest.param(
            f"[reg]: {REGISTRY}",
            "Omega sees [the registry][reg].",
            "word/_rels/document.xml.rels",
            f'Target="{REGISTRY}"',
            id="link",
        ),
        pytest.param(
            "[^cap]: Capped at forty milligrams.",
            "Omega was capped.[^cap]",
            "word/footnotes.xml",
            "Capped at forty milligrams.",
            id="footnote",
        ),
    ],
)
def test_a_paragraph_moved_across_a_definition_is_moved(
    project: Path, tmp_path: Path, definition: str, second: str, part: str, resolved: str
) -> None:
    """A definition renders nothing in the body, and pandoc reads it wherever it stands.
    As untagged source text between two paragraphs it counted as a section boundary, so a
    co-author's move across it was refused as a move past a heading, a table or a figure.
    The paragraphs now change places around it, and it still resolves."""
    from manuscript_guard.cli import main

    first = "Alpha comes first."
    with_paragraphs(project, first, definition, second)

    def swap(xml: str) -> str:
        paragraphs = tagged_xml(xml)
        alpha = next(p for p in paragraphs if "Alpha comes first" in p)
        omega = next(p for p in paragraphs if "Omega" in p)
        return xml.replace(omega, "", 1).replace(alpha, omega + alpha, 1)

    returned = rewrite(built(project), tmp_path / "moved.docx", swap)
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    text = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert f"{second}\n\n{definition}\n\n{first}\n\n" in text
    assert resolved in _docx_part(built(project), part)


@needs_pandoc
def test_a_definition_beside_a_line_pandoc_prints_leaves_an_edit_merged(
    project: Path, tmp_path: Path
) -> None:
    """Round four: a definition over a line holding only a no-break space still counted as
    a definition between two paragraphs, though `_blocks` leaves it unmarked for that line,
    and pandoc prints the line as a block of its own. So the gap made no new section, the
    section held an untagged block, and an edit to the paragraph above was refused as one
    that reaches Word as more than one paragraph. On #54 alone the edit merges."""
    from manuscript_guard.cli import main

    with_paragraphs(
        project,
        "Alpha comes first.",
        f"[reg]: {REGISTRY}\n{chr(0xA0)}",
        f"[other]: {REGISTRY}/o",
        "Omega sees [the registry][reg] and [o][other].",
    )
    edits = {"Alpha comes first.": "Alpha now comes first."}
    returned = edit_docx(built(project), tmp_path / "back.docx", edits)
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    text = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert "Alpha now comes first.\n\n" in text


def test_only_definitions_between_two_paragraphs_keep_them_in_one_section(
    project: Path,
) -> None:
    """Blank lines and definitions are no boundary; a table or a heading is. A definition
    under a line pandoc does not take for blank is prose to pandoc, not a definition: text
    between two paragraphs that holds one is a boundary, as any untagged text is."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.merge import _sections
    from manuscript_guard.roundtrip import only_definitions_between, tagged_paragraphs

    assert only_definitions_between(f"\n\n[late]: {REGISTRY}/late\n\n")
    assert not only_definitions_between(f"\n\n{chr(0xA0)}\n[late]: {REGISTRY}/late\n\n")
    # Over such a line, or under one with an empty line between, as `_blocks` leaves it.
    for between in (f"\n{chr(0xA0)}\n\n", f"\n\n{chr(0xA0)}\n\n", f"\n\n{chr(0x3000)}\n\n"):
        assert not only_definitions_between(
            f"\n\n[a]: {REGISTRY}/a{between}[b]: {REGISTRY}/b\n\n"
        )
    pieces = [
        "Alpha.",
        f"[reg]: {REGISTRY}",
        "[^cap]: A note.",
        "Beta.",
        "{{table.baseline}}",
        "Gamma.",
        f"[other]: {REGISTRY}/other",
        "# Heading",
        "Delta.",
    ]
    (project / "manuscript" / "sections.md").write_text("\n\n".join(pieces) + "\n", "utf-8")
    loaded, _report = load_project(project)
    known = {
        name: entry
        for name, entry in tagged_paragraphs(loaded).items()
        if entry[0].name == "sections.md"
    }
    section = {known[name][1]: number for name, (_path, number) in _sections(known).items()}
    assert section["Alpha."] == section["Beta."]
    assert section["Gamma."] == section["Beta."] + 1
    assert section["Delta."] == section["Gamma."] + 1


@needs_pandoc
@pytest.mark.parametrize(
    ("paragraph", "was", "now", "expected"),
    [
        pytest.param(
            "As Smith et al. reported, the signal was clear.",
            "the signal was clear.",
            "the signal was plain.",
            "As Smith et al. reported, the signal was plain.",
            id="plain",
        ),
        pytest.param(
            "In such cohorts, e.g. {{results.ror.point}} was the ratio.",
            "In such cohorts",
            "In these cohorts",
            "In these cohorts, e.g. {{results.ror.point}} was the ratio.",
            id="before-a-binding",
        ),
    ],
)
def test_import_writes_pandocs_no_break_space_back_as_a_space(
    project: Path, tmp_path: Path, paragraph: str, was: str, now: str, expected: str
) -> None:
    """End to end: a paragraph with "et al." or "e.g." reworded in Word put pandoc's no-break
    space into the .md as an invisible character. `expected` has plain spaces only."""
    from manuscript_guard.cli import main

    with_paragraphs(project, paragraph)
    returned = edit_docx(built(project), tmp_path / "back.docx", {was: now})

    assert main(["import", str(returned), str(project), "--apply"]) == 0
    assert expected in (project / "manuscript" / "main.md").read_text(encoding="utf-8")


# ------------------------------------ end to end: a write the next build would not identify

SHAPED = "[x]: https://example.org/xyz"
NOTE = "[^cap]: Capped at forty."
#: A block pandoc takes into the note above it: after a blank line, indented four columns,
#: a zero-width space that shows nothing. The note is marked for it, and prints as text.
RUNS_INTO = f"    {chr(0x200B)}\nIt was rare."


def swapped(first: str, second: str):
    """A co-author, simulated: the paragraph holding `second` cut and pasted above the one
    holding `first`."""

    def swap(xml: str) -> str:
        paragraphs = tagged_xml(xml)
        above = next(p for p in paragraphs if first in p)
        below = next(p for p in paragraphs if second in p)
        return xml.replace(below, "", 1).replace(above, below + above, 1)

    return swap


@needs_pandoc
def test_a_move_that_would_make_a_paragraph_a_definition_is_refused(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end. A note is marked where what is below it would run into it, and prints
    as text. Swapped in Word with the paragraph above it, it landed over a plain paragraph,
    where the next build read it as a note again and printed nothing of it in the body -
    while `import --apply` exited 0 and said it had reordered a paragraph."""
    from manuscript_guard.cli import main

    with_paragraphs(project, "Doses were capped.[^cap]", "Alpha comes first.", NOTE, RUNS_INTO)
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")
    document = built(project)
    assert "Capped at forty." in _docx_part(document, "word/document.xml")
    returned = rewrite(document, tmp_path / "moved.docx", swapped("Alpha comes", "Capped at"))

    capsys.readouterr()
    assert main(["import", str(returned), str(project)]) == 1
    dry = capsys.readouterr().out
    assert "without its identifier" in dry
    assert "applies the safe changes" not in dry
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    out = capsys.readouterr().out
    assert "without its identifier" in out
    assert "reordered" not in out
    assert source.read_text(encoding="utf-8") == before
    assert "Capped at forty." in _docx_part(built(project), "word/document.xml")


@needs_pandoc
def test_a_move_that_pushes_a_note_into_a_definitions_place_holds_its_section(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review round one: the co-author moved only the first paragraph, below the note, and
    that pushed the note, which nobody touched, up into a place where it was a definition
    again. Holding back the note alone refused a paragraph nobody moved and put the others
    in an order neither side had. No move in the section is applied now, and each is named
    with the note it would leave behind."""
    from manuscript_guard.cli import main

    with_paragraphs(project, "Doses were capped.[^cap]", "Aaa first.", NOTE, RUNS_INTO)
    source = project / "manuscript" / "main.md"
    before = source.read_text(encoding="utf-8")
    document = built(project)
    once = rewrite(document, tmp_path / "once.docx", swapped("Doses were", "Aaa first"))
    returned = rewrite(once, tmp_path / "moved.docx", swapped("Doses were", "Capped at"))

    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    out = capsys.readouterr().out
    assert "Doses were capped." in out and "it would leave behind: [^cap]" in out
    assert "reordered" not in out
    assert source.read_text(encoding="utf-8") == before


@needs_pandoc
def test_the_other_changes_beside_a_refused_move_are_applied(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Moves are held back in the one section, and a rewording there still lands, in place;
    a move in another section is applied."""
    from manuscript_guard.cli import main

    with_paragraphs(
        project,
        "Doses were capped.[^cap]",
        "Alpha comes first.",
        NOTE,
        RUNS_INTO,
        "## Later",
        "Beta was second.",
        "Gamma was third.",
    )
    source = project / "manuscript" / "main.md"
    document = built(project)
    first = rewrite(document, tmp_path / "one.docx", swapped("Alpha comes", "Capped at"))
    both = rewrite(first, tmp_path / "two.docx", swapped("Beta was", "Gamma was"))
    returned = edit_docx(both, tmp_path / "back.docx", {"Alpha comes first.": "Alpha came first."})

    assert main(["import", str(returned), str(project), "--apply"]) == 1
    text = source.read_text(encoding="utf-8")
    assert f"Alpha came first.\n\n{NOTE}\n\n{RUNS_INTO}" in text
    assert "## Later\n\nGamma was third.\n\nBeta was second." in text
    assert "without its identifier" in capsys.readouterr().out


@needs_pandoc
def test_a_rewording_into_a_definitions_shape_is_escaped_and_kept(
    project: Path, tmp_path: Path
) -> None:
    """The other way a paragraph could take a definition's shape is typed in Word, and that
    one never lost anything: the merge escapes the bracket, so the paragraph prints as it was
    typed and keeps its identifier. Kept here beside the move, which has no such escape."""
    from manuscript_guard.cli import main

    with_paragraphs(project, "The registry is at https://example.org/xyz for anyone.")
    edit = {"The registry is at https://example.org/xyz for anyone.": SHAPED}
    returned = edit_docx(built(project), tmp_path / "back.docx", edit)

    assert main(["import", str(returned), str(project), "--apply"]) == 0
    assert f"\n\n\\{SHAPED}\n\n" in (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert "example.org/xyz" in _docx_part(built(project), "word/document.xml")


def test_a_move_the_next_build_would_lose_is_held_where_it_was(tmp_path: Path) -> None:
    """The plan itself, without pandoc: no move in the section is applied, the move made -
    the note's, by the order diff - is named with the note it would strand, none is listed
    as moved, and applying the plan writes nothing."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    source = tmp_path / "main.md"
    text = f"Alpha.\n\n{NOTE}\n\n{RUNS_INTO}\n"
    source.write_text(text, encoding="utf-8")
    known = {"a": (source, "Alpha.", 0), "n": (source, NOTE, text.index(NOTE))}
    sent = [Block((name,), known[name][1]) for name in known]

    plan = plan_import(known, sent, [sent[1], sent[0]])
    assert plan.held == {"a", "n"}
    assert dict(plan.held_back) == {"n": "n"}
    assert not plan.moved and not plan.refused
    apply_plan(known, plan)
    assert source.read_text(encoding="utf-8") == text


def test_a_write_that_would_cost_another_paragraph_its_identifier_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write can cost a paragraph beside it its identifier - a comment or a fence opened in
    one block runs on into the next - and which write did it cannot be told, so every
    rewording in that file is refused. Simulated: the next build is made to lose `Gamma.`
    once `Alpha.` is reworded."""
    from manuscript_guard import merge
    from manuscript_guard.docxtext import Block

    source = tmp_path / "main.md"
    text = "Alpha.\n\nGamma.\n"
    source.write_text(text, encoding="utf-8")
    known = {"a": (source, "Alpha.", 0), "g": (source, "Gamma.", 8)}
    sent = [Block((name,), known[name][1]) for name in known]
    marked = merge.marked_blocks

    def losing_gamma(raw: str) -> list:
        return [block for block in marked(raw) if "Alpha now." not in raw or block[1] != "Gamma."]

    monkeypatch.setattr(merge, "marked_blocks", losing_gamma)
    plan = merge.plan_import(known, sent, [Block(("a",), "Alpha now."), sent[1]])
    assert not plan.merged
    assert "another paragraph" in plan.refused[0].why[0]
    merge.apply_plan(known, plan)
    assert source.read_text(encoding="utf-8") == text


def _plan_of(tmp_path: Path, text: str, back) -> tuple:
    """A source of paragraphs named by their first word, and the plan for what came back:
    `back` maps those names to the returned blocks, in their returned order."""
    from manuscript_guard import merge
    from manuscript_guard.docxtext import Block
    from manuscript_guard.roundtrip import marked_blocks

    source = tmp_path / "main.md"
    source.write_text(text, encoding="utf-8")
    known = {body.split()[0]: (source, body, start) for _i, body, start in marked_blocks(text)}
    sent = [Block((name,), known[name][1]) for name in known]
    return source, known, merge.plan_import(known, sent, back({b.names[0]: b for b in sent}))


def test_a_rewording_that_strands_a_paragraph_once_its_section_is_held_is_refused(
    tmp_path: Path,
) -> None:
    """Review round two, HIGH: held, a section's moves go back, and a rewording there lands
    in place, where it can do what it did not do where it was moved. Beta, reworded with a
    `-->` and moved above Alpha, closed nothing there; held back under Alpha, it closed
    Alpha's `<!--`, and pandoc read the two as one comment. The check looked at no held
    paragraph again, so the rewording was merged, and the next build lost Beta."""
    from manuscript_guard import merge
    from manuscript_guard.docxtext import Block

    text = f"Alpha opens <!-- here.\n\nBeta plain.\n\nGamma plain.\n\n{NOTE}\n\n{RUNS_INTO}\n"
    source, known, plan = _plan_of(
        tmp_path,
        text,
        lambda by: [Block(("Beta",), "Beta --> plain."), by["Alpha"], by["[^cap]:"], by["Gamma"]],
    )
    assert "Beta" not in plan.merged
    refusal = next(r for r in plan.refused if r.name == "Beta")
    assert refusal.text == "Beta --> plain."
    assert not merge._unidentified(known, plan)
    merge.apply_plan(known, plan)
    assert source.read_text(encoding="utf-8") == text


def test_a_rewording_that_hides_moved_paragraphs_does_not_hold_the_moves(
    tmp_path: Path,
) -> None:
    """Review round two, MEDIUM: Rho's `-->` closed the `<!--` above Alpha and Beta, so the
    two came out without their identifiers, swapped or not. Every lost paragraph was acted
    on in one round: the rewording was refused and the swap held back too, blamed on a
    definition or a heading. A rewording is refused first now, and the plan checked again."""
    from manuscript_guard import merge
    from manuscript_guard.docxtext import Block

    text = "Opens <!-- here.\n\nAlpha plain.\n\nBeta plain.\n\n## Heading\n\nRho plain.\n"
    source, known, plan = _plan_of(
        tmp_path,
        text,
        lambda by: [by["Opens"], by["Beta"], by["Alpha"], Block(("Rho",), "Rho --> plain.")],
    )
    assert "Rho" in {refusal.name for refusal in plan.refused}
    assert not plan.held and not plan.held_back
    assert {entry[0] for entry in plan.moved} & {"Alpha", "Beta"}
    merge.apply_plan(known, plan)
    assert source.read_text(encoding="utf-8") == text.replace(
        "Alpha plain.\n\nBeta plain.", "Beta plain.\n\nAlpha plain."
    )


def test_a_held_section_names_the_moves_made_not_every_paragraph_they_shift(
    tmp_path: Path,
) -> None:
    """Review round two, LOW: one paragraph moved from the top of a section to below a note
    shifts every paragraph between, and each was named as moved - nine for one move."""
    paragraphs = [f"P{number} was written here." for number in range(8)]
    text = "\n\n".join([*paragraphs, NOTE, RUNS_INTO]) + "\n"
    _source, _known, plan = _plan_of(
        tmp_path,
        text,
        lambda by: [block for name, block in by.items() if name != "P0"] + [by["P0"]],
    )
    assert [name for name, _left in plan.held_back] == ["P0"]


# ------------------------------------ end to end: a paragraph cut down to its number stays named


@needs_pandoc
def test_a_paragraph_cut_down_to_its_number_can_be_edited_again(
    project: Path, tmp_path: Path
) -> None:
    """End to end, the way the review found it. A co-author deleted everything but the number;
    it merged as `{{results.ror.point}}` alone and `check` passed. The next build gave that
    paragraph no identifier, so when it was edited again in Word, import skipped the edit and
    said "nothing came back"."""
    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_project
    from manuscript_guard.roundtrip import tagged_paragraphs

    with_paragraphs(project, "The final ratio was {{results.ror.point}} overall.")
    cut = edit_docx(
        built(project), tmp_path / "cut.docx", {"The final ratio was 3.84 overall.": "3.84"}
    )
    assert main(["import", str(cut), str(project), "--apply"]) == 0
    source = project / "manuscript" / "main.md"
    assert "\n\n{{results.ror.point}}\n\n" in source.read_text(encoding="utf-8")

    named = [
        name
        for name, (_path, text, _start) in tagged_paragraphs(load_project(project)[0]).items()
        if text == "{{results.ror.point}}"
    ]
    assert named, "the paragraph has an identifier for its next edit to come back by"

    def reworded(xml: str) -> str:
        (paragraph,) = [p for p in tagged_xml(xml) if f'"{named[0]}"' in p]
        return xml.replace(paragraph, paragraph.replace(">3.84<", ">About 3.84.<"), 1)

    again = rewrite(built(project), tmp_path / "again.docx", reworded)
    assert main(["import", str(again), str(project), "--apply"]) == 0
    assert "\n\nAbout {{results.ror.point}}.\n\n" in source.read_text(encoding="utf-8")


# --------------------------------------------------- a supplement is a document of its own

SUPPLEMENT = Path("manuscript") / "supplementary" / "S1_code_lists.md"


@needs_pandoc
@pytest.mark.parametrize("edited", ["reworded", "untouched"])
def test_a_supplement_that_comes_back_is_compared_with_the_supplement(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], edited: str
) -> None:
    """`build` writes the supplement as its own document, and `import` compared every
    returned document with a fresh build of the paper. An edited supplementary.docx reported
    every paragraph of the paper as deleted in Word, exit 1, and its own edits went nowhere."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    source = project / SUPPLEMENT
    main_md = project / "manuscript" / "main.md"
    before, paper = source.read_text(encoding="utf-8"), main_md.read_text(encoding="utf-8")
    was = "This supplement is referred to from the Methods"
    now = "This supplement is cited from the Methods" if edited == "reworded" else was
    supplement = project / "build" / "supplementary.docx"
    returned = edit_docx(supplement, tmp_path / "back.docx", {was: now})

    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "deleted in Word" not in out
    assert main_md.read_text(encoding="utf-8") == paper
    after = source.read_text(encoding="utf-8")
    if edited == "reworded":
        # A merged paragraph comes back unwrapped, so its line breaks are not compared.
        assert blocks(after) == blocks(before.replace(was, now, 1))
    else:
        assert after == before and "nothing came back" in out


@needs_pandoc
def test_a_document_carrying_paragraphs_of_both_the_paper_and_the_supplement_is_refused(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two paragraphs pasted from the paper into the supplement bring the second one's
    identifier with them; Word drops the first one's, as it drops a single paragraph's.
    Compared with either document alone, the other's paragraphs read as deleted or moved;
    nothing in it is imported, and the refusal says why."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    with zipfile.ZipFile(project / "build" / "manuscript.docx") as archive:
        paper = archive.read("word/document.xml").decode("utf-8")
    first, second = tagged_xml(paper)[1:3]
    first = re.sub(r'<w:bookmark(Start|End) [^>]*/>', "", first)
    pasted = first + second
    returned = rewrite(
        project / "build" / "supplementary.docx",
        tmp_path / "both.docx",
        lambda xml: xml.replace("</w:body>", pasted + "</w:body>", 1)
        if "<w:sectPr" not in xml
        else xml.replace("<w:sectPr", pasted + "<w:sectPr", 1),
    )
    sources = {p: p.read_text(encoding="utf-8") for p in (project / "manuscript").rglob("*.md")}

    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert "paragraphs of both the manuscript and its supplement" in capsys.readouterr().out
    assert {p: p.read_text(encoding="utf-8") for p in sources} == sources


@needs_pandoc
def test_one_paragraph_pasted_from_the_paper_into_the_supplement_is_listed_not_applied(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Word drops the identifier of a single paragraph it pastes, so the supplement comes back
    with new text and nothing of the paper's: it is compared with the supplement, and the
    pasted paragraph is listed as one without an identifier, and not applied."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    with zipfile.ZipFile(project / "build" / "manuscript.docx") as archive:
        paper = archive.read("word/document.xml").decode("utf-8")
    pasted = re.sub(r"<w:bookmark(Start|End) [^>]*/>", "", tagged_xml(paper)[1])
    returned = rewrite(
        project / "build" / "supplementary.docx",
        tmp_path / "pasted.docx",
        lambda xml: xml.replace("</w:body>", pasted + "</w:body>", 1)
        if "<w:sectPr" not in xml
        else xml.replace("<w:sectPr", pasted + "<w:sectPr", 1),
    )
    sources = {p: p.read_text(encoding="utf-8") for p in (project / "manuscript").rglob("*.md")}

    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    out = capsys.readouterr().out
    assert "without an identifier" in out and "deleted in Word" not in out
    assert {p: p.read_text(encoding="utf-8") for p in sources} == sources


@needs_pandoc
@pytest.mark.parametrize("document", ["manuscript", "supplementary"])
def test_a_document_carrying_no_identifier_is_refused_when_there_are_two_it_could_be(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], document: str
) -> None:
    """Which document came back is read from its identifiers, and both carry the same stamp.
    One that lost every identifier (pasted into a fresh file, say) was compared with the
    paper whichever it was, and every paragraph of the paper was reported deleted in Word."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = rewrite(
        project / "build" / f"{document}.docx",
        tmp_path / "bare.docx",
        lambda xml: re.sub(r'<w:bookmarkStart [^>]*w:name="mg-p-[^"]*"\s*/>', "", xml),
    )
    sources = {p: p.read_text(encoding="utf-8") for p in (project / "manuscript").rglob("*.md")}

    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    out = capsys.readouterr().out
    assert "deleted in Word" not in out
    assert "no telling whether it is the manuscript or its supplement" in out
    assert {p: p.read_text(encoding="utf-8") for p in sources} == sources


@needs_pandoc
def test_a_supplement_of_headings_and_tables_only_is_not_compared_with_the_paper(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Whether the project has a supplement was read from the paragraphs carrying an
    identifier, and a supplement of headings and tables has none. Returned untouched, it was
    compared with the paper, and every paragraph of the paper was reported deleted in Word."""
    from manuscript_guard.cli import main

    (project / SUPPLEMENT).write_text(
        "# Supplementary methods\n\n## Table S1. Code lists used to identify the outcome\n\n"
        "{{table.outcome_codes}}\n",
        encoding="utf-8",
        newline="\n",
    )
    assert main(["build", str(project), "--offline"]) == 0
    returned = shutil.copy(project / "build" / "supplementary.docx", tmp_path / "back.docx")
    sources = {p: p.read_text(encoding="utf-8") for p in (project / "manuscript").rglob("*.md")}

    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 1
    out = capsys.readouterr().out
    assert "deleted in Word" not in out
    assert "no telling whether it is the manuscript or its supplement" in out
    assert {p: p.read_text(encoding="utf-8") for p in sources} == sources


@needs_pandoc
def test_a_document_refused_for_carrying_no_identifier_still_reports_its_comments(
    project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The comments were read and then dropped when the document was refused, and with them
    the prompt to record them for G11."""
    from manuscript_guard.cli import main

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    comments = (
        f'<w:comments xmlns:w="{w}"><w:comment w:id="0" w:author="Co-author" '
        f'w:date="2026-09-25T10:00:00Z"><w:p><w:r><w:t>Please cite the 2024 review.</w:t>'
        f"</w:r></w:p></w:comment></w:comments>"
    )
    bare = rewrite(
        built(project),
        tmp_path / "bare.docx",
        lambda xml: re.sub(r'<w:bookmarkStart [^>]*w:name="mg-p-[^"]*"\s*/>', "", xml),
    )
    returned = tmp_path / "commented.docx"
    with zipfile.ZipFile(bare) as zin, zipfile.ZipFile(returned, "w") as zout:
        for item in zin.infolist():
            if item.filename != "word/comments.xml":
                zout.writestr(item, zin.read(item.filename))
        zout.writestr("word/comments.xml", comments)

    capsys.readouterr()
    assert main(["import", str(returned), str(project)]) == 1
    out = capsys.readouterr().out
    assert "no telling whether it is the manuscript or its supplement" in out
    assert "Please cite the 2024 review." in out
    assert "review/round-<n>/" in out
