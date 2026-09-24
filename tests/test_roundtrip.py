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
    moved_xml = xml.replace(tagged[-3], "", 1).replace(tagged[3], tagged[-3] + tagged[3], 1)

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
    was = [p.strip() for p in before.split("\n\n") if p.strip()]
    now = [p.strip() for p in after.split("\n\n") if p.strip()]
    assert sorted(was) == sorted(now), "nothing gained or lost"
    assert was != now, "the order must have changed"
    assert before.count("{{") == after.count("{{"), "every binding survives a move"


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
    "source",
    [
        "See the [agency report](https://example.org/r) for details.",
        "See the agency report.^[Withdrawn in 2019.] It has details.",
    ],
    ids=["link", "footnote"],
)
def test_a_paragraph_whose_markup_word_cannot_carry_is_refused(source: str) -> None:
    """Word's plain text has the link's words but not its address, and a footnote's
    reference mark but not its text. Merging it over the source deleted both."""
    from manuscript_guard.merge import why
    from manuscript_guard.roundtrip import align

    rendered = "See the agency report for details."
    aligned = align(source, rendered, "See the agency report for more details.")
    assert aligned.rebuilt is None
    assert "footnote or a link" in why(aligned)[0]


def test_a_value_is_found_in_its_own_place_not_in_the_prose_before_it() -> None:
    """'Table 1 shows 1 events' - the first '1' is prose. Searching for the rendered value
    from the start of the paragraph moved the binding onto the table number and left the
    value behind as a literal."""
    source = "Table 1 shows {{results.x}} events."
    out = realign(source, "Table 1 shows 1 events.", "Table 1 now shows 1 events.")
    assert out == "Table 1 now shows {{results.x}} events."


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

    def edit(xml: str) -> str:
        tagged = tagged_xml(xml)
        moved = tagged[12]
        assert "Several limitations" in moved
        xml = xml.replace(moved, "", 1).replace(tagged[1], moved + tagged[1], 1)
        # One reworded paragraph before the move's landing point, one inside the span the
        # reorder shifts, one that carries bindings, and the moved paragraph itself.
        xml = xml.replace("has not been examined.", "has not yet been examined.", 1)
        xml = xml.replace("We analysed a synthetic", "We examined a synthetic", 1)
        return xml.replace("Several limitations follow", "Several limitations follow directly", 1)

    returned = rewrite(document, tmp_path / "moved.docx", edit)
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    after = source.read_text(encoding="utf-8")

    expected = (
        before.replace("has not been examined.", "has not yet been examined.")
        .replace("We analysed a synthetic", "We examined a synthetic")
        .replace("Several limitations follow", "Several limitations follow directly")
    )
    assert sorted(blocks(after)) == sorted(blocks(expected)), "every paragraph, edited, once"
    assert after.index("Several limitations") < after.index("Drug-induced hepatic injury remains")
    assert sorted(re.findall(r"\{\{[^}]*\}\}", after)) == sorted(
        re.findall(r"\{\{[^}]*\}\}", before)
    ), "every binding survives, whole"
    assert closed(after)


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
