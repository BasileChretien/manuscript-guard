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
    """Split over properties short enough that Word does not cut them when it saves."""
    import hashlib

    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_project
    from manuscript_guard.roundtrip import paragraphs_of, tagged_paragraphs

    assert main(["build", str(project), "--offline"]) == 0
    document = project / "build" / "manuscript.docx"
    known = tagged_paragraphs(load_project(project)[0])
    assert paragraphs_of(document) == {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        for name, (_path, text, _start) in known.items()
    }
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
    many = {f"mg-p-main-{2 * i}": f"Paragraph {i}." for i in range(60)}
    stamp_into(document, "a" * 64, many)
    stamp_into(document, "b" * 64, {"mg-p-main-2": "Only one."})
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
    index, digest = funding.rpartition("-")[2], _recorded(returned)[funding]
    # The record says the funding identifier named some other text at the build.
    with_record(
        returned,
        lambda found: re.sub(rf"(?<=[:,]){index}\.{digest}(?=[,<])", f"{index}.00000000", found),
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


def test_writing_back_a_no_break_space_is_linear_in_a_long_word() -> None:
    """Looking for a bare `@` in the word before the abbreviation searched the text before it
    with `\\S*\\Z`, which rescans a long run from every place in it: with a URL of 8,000
    characters ahead of a few "e.g.", `align` took 16 seconds. Doubling the input must not
    much more than double the time."""
    import time

    from manuscript_guard.roundtrip import _respaced

    def measure(length: int) -> float:
        text = f"See https://example.org/{'a' * length} and e.g.\u00a0this."
        started = time.perf_counter()
        _respaced(text, ABBREVIATIONS, lead=True, binding_next=False)
        return time.perf_counter() - started

    small = max(min(measure(4000) for _ in range(3)), 1e-4)
    large = min(measure(16000) for _ in range(3))
    assert large / small < 12, f"4x the input took {large / small:.1f}x the time; not linear"


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
