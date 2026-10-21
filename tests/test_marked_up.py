"""The marked-up copy: the revision, with every change since the document sent shown.

Each test plants one kind of change between two documents pandoc built, writes the copy and
reads its XML: where the change shows, as what, by whom and when, and that the rest shows
none. The copy reads as the revision with every change accepted and as the document sent
with every one rejected, by `readings.read_plainly`, which owes nothing to the package; the
writer checks the same with the package's own reading before it keeps a copy
(`markedup.verify`). `tests/test_properties.py` holds both over generated revisions, and
`test_word_reads_the_copy_as_the_package_does` holds the package's reading of accepted and
rejected to what Word 16 made of one copy.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from readings import document_of, plain_of, read_plainly, shown

from manuscript_guard.markedup import (
    AUTHOR,
    MARKED_UP_PROPERTY,
    MarkedUpError,
    marked_up_of,
    write,
)
from manuscript_guard.markedup.verify import _readable, resolved

PANDOC = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(PANDOC is None, reason="pandoc is not installed")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DAY = "2026-10-21"
PILCROW = "\N{PILCROW SIGN}"
_REFERENCES = """@article{a2020, author={Alpha, Ann}, title={First work}, journal={J One}, year={2020}}
@article{b2021, author={Beta, Ben}, title={Second work}, journal={J Two}, year={2021}}
"""  # noqa: E501 - two entries, one a line


def _built(folder: Path, name: str, markdown: str, *extra: str) -> Path:
    source = folder / f"{name}.md"
    source.write_text(markdown, encoding="utf-8")
    target = folder / f"{name}.docx"
    subprocess.run(
        [PANDOC, str(source), "-o", str(target), *extra], check=True, capture_output=True,
        cwd=folder,
    )  # fmt: skip
    return target


def _pair(folder: Path, before: str, after: str, *extra: str) -> tuple[Path, Path]:
    return _built(folder, "before", before, *extra), _built(folder, "after", after, *extra)


def _marked(folder: Path, before: str, after: str, *extra: str, form: str = "tracked"):
    old, new = _pair(folder, before, after, *extra)
    made = write(old, new, folder / "marked.docx", date=DAY, form=form)
    return made, old, new


def _xml(document: Path, part: str = "word/document.xml") -> str:
    with zipfile.ZipFile(document) as archive:
        return archive.read(part).decode("utf-8")


def _changes(document: Path) -> list[tuple[str, str, str]]:
    from xml.etree import ElementTree as ET

    root = ET.fromstring(_xml(document))
    return [
        (node.tag.removeprefix(W), node.get(W + "author", ""), node.get(W + "date", ""))
        for node in root.iter()
        if node.tag in (W + "ins", W + "del", W + "rPrChange", W + "pPrChange")
    ]


def _line(lines: list[str], word: str) -> str:
    found = [line for line in lines if word in line]
    assert len(found) == 1, (word, lines)
    return found[0]


@needs_pandoc
def test_a_number_re_run_and_a_word_reworded_are_shown_word_by_word(tmp_path: Path) -> None:
    """The numbers a re-run printed anew are changes like any word typed: each deleted and
    its successor inserted where it stands, the words around them left alone. Every change
    is by "Revision", dated the day the copy was made."""
    made, old, new = _marked(
        tmp_path,
        "The ratio was 3.84 (95% CI 2.89 to 5.12) in the main analysis.\n\nKept as it was.\n",
        "The ratio was 3.91 (95% CI 2.95 to 5.20) in the primary analysis.\n\nKept as it was.\n",
    )
    lines = shown(made.path)
    assert lines[0] == (
        "The ratio was [-3.84-]{+3.91+} (95% CI [-2.89-]{+2.95+} to [-5.12-]{+5.20+}) in the "
        "[-main-]{+primary+} analysis."
    )
    assert lines[1] == "Kept as it was."
    assert {(author, date) for _kind, author, date in _changes(made.path)} == {
        (AUTHOR, f"{DAY}T00:00:00Z")
    }
    assert read_plainly(made.path, accept=True) == read_plainly(new, accept=True)
    assert read_plainly(made.path, accept=False) == read_plainly(old, accept=True)
    assert made.counts["words inserted"] == made.counts["words deleted"] == 4


@needs_pandoc
def test_a_moved_paragraph_is_deleted_where_it_was_and_inserted_where_it_is(
    tmp_path: Path,
) -> None:
    made, _old, _new = _marked(
        tmp_path,
        "First.\n\nThe paragraph that moves.\n\nSecond.\n\nThird.\n\nLast.\n",
        "First.\n\nSecond.\n\nThird.\n\nThe paragraph that moves.\n\nLast.\n",
    )
    assert shown(made.path) == [
        "First.",
        f"{PILCROW}- [-The paragraph that moves.-]",
        "Second.",
        "Third.",
        f"{PILCROW}+ {{+The paragraph that moves.+}}",
        "Last.",
    ]


@needs_pandoc
@pytest.mark.parametrize("was_last", [True, False])
def test_the_last_paragraph_keeps_its_mark_untracked_whatever_became_of_it(
    tmp_path: Path, was_last: bool
) -> None:
    """Word cannot take away a document's last paragraph mark, and given one tracked as
    deleted its Accept All never returns (Word 16 over COM, 2026-10-21). So the last
    paragraph's words are tracked and its mark is not, deleted there or inserted there."""
    kept = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    last = "\nThe last paragraph.\n"
    before, after = (kept + last, kept) if was_last else (kept, kept + last)
    made, old, new = _marked(tmp_path, before, after)
    lines = shown(made.path)
    assert lines[-1] == ("[-The last paragraph.-]" if was_last else "{+The last paragraph.+}")
    assert read_plainly(made.path, accept=True) == read_plainly(new, accept=True)
    assert read_plainly(made.path, accept=False) == read_plainly(old, accept=True)


@needs_pandoc
def test_a_table_is_merged_cell_by_cell_and_a_row_added_is_a_row(tmp_path: Path) -> None:
    table = "| Group | n |\n|---|--:|\n| A | 426 |\n| B | 3574 |\n"
    made, _old, _new = _marked(tmp_path, table, table.replace("426", "430") + "| C | 1 |\n")
    assert shown(made.path) == [
        "Group | n",
        "A | [-426-]{+430+}",
        "B | 3574",
        "row+ {+C+} | {+1+}",
    ]


@needs_pandoc
def test_a_table_of_other_columns_is_replaced_and_kept_apart_from_it(tmp_path: Path) -> None:
    """Word runs two tables that touch into one, so the one deleted and the one inserted
    in its place have an empty paragraph between them, tracked as deleted."""
    made, old, new = _marked(
        tmp_path,
        "Above.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nBelow.\n",
        "Above.\n\n| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |\n\nBelow.\n",
    )
    lines = shown(made.path)
    assert lines == [
        "Above.",
        "row- [-A-] | [-B-]",
        "row- [-1-] | [-2-]",
        f"{PILCROW}- ",
        "row+ {+A+} | {+B+} | {+C+}",
        "row+ {+1+} | {+2+} | {+3+}",
        "Below.",
    ]
    assert read_plainly(made.path, accept=True) == read_plainly(new, accept=True)
    assert read_plainly(made.path, accept=False) == read_plainly(old, accept=True)


@needs_pandoc
def test_a_reference_added_is_inserted_in_the_text_and_in_the_list(tmp_path: Path) -> None:
    (tmp_path / "refs.bib").write_text(_REFERENCES, encoding="utf-8")
    made, _old, _new = _marked(
        tmp_path,
        "As shown before [@a2020].\n",
        "As shown before [@a2020; @b2021].\n",
        "--citeproc", "--bibliography=refs.bib",
    )  # fmt: skip
    lines = shown(made.path)
    assert lines[0] == "As shown before (Alpha 2020{+; Beta 2021+})."
    assert lines[1].startswith("Alpha, Ann. 2020.")
    # The list's last entry: its words inserted, its mark not (see the test above).
    assert lines[2].startswith("{+Beta, Ben. 2021.")


@needs_pandoc
def test_a_replaced_figure_is_removed_and_added_and_its_picture_is_carried(
    tmp_path: Path,
) -> None:
    """The picture deleted is the one sent, carried into the copy's package under a name
    of its own; the caption is merged as text."""
    from readings import _png

    (tmp_path / "red.png").write_bytes(_png((255, 0, 0)))
    (tmp_path / "blue.png").write_bytes(_png((0, 0, 255)))
    made, old, new = _marked(
        tmp_path, "![The caption.](red.png)\n", "![The caption, revised.](blue.png)\n"
    )
    lines = shown(made.path)
    assert lines[:3] == [
        f"{PILCROW}- [-(picture red)-]",
        f"{PILCROW}+ {{+(picture blue)+}}",
        "The caption{+, revised+}.",
    ]
    with zipfile.ZipFile(made.path) as archive:
        carried = [name for name in archive.namelist() if "marked-up-" in name]
        assert len(carried) == 1
        assert archive.read(carried[0]) == _png((255, 0, 0))
        # The parts it was declared in keep their namespace as their default, as every
        # reader of a package expects them: `ns0:` is read by Word, not by all.
        assert b"<Relationships xmlns=" in archive.read("word/_rels/document.xml.rels")
        assert b"<Types xmlns=" in archive.read("[Content_Types].xml")
    assert read_plainly(made.path, accept=False) == read_plainly(old, accept=True)


@needs_pandoc
def test_a_footnote_is_merged_word_by_word(tmp_path: Path) -> None:
    made, old, new = _marked(
        tmp_path,
        "Text.^[A note that says one thing.]\n",
        "Text.^[A note that says another thing.]\n",
    )
    assert shown(made.path)[-1] == "note: A note that says [-one-]{+another+} thing."
    assert read_plainly(made.path, accept=True) == read_plainly(new, accept=True)
    assert read_plainly(made.path, accept=False) == read_plainly(old, accept=True)


@needs_pandoc
def test_a_change_of_formatting_or_of_style_records_what_it_was(tmp_path: Path) -> None:
    """A word set in italics keeps its text and records the run's old properties; a
    paragraph made a heading records its old style. Rejected, both are as they were."""
    made, old, _new = _marked(
        tmp_path, "A word in plain.\n\nA paragraph.\n", "A *word* in plain.\n\n# A paragraph.\n"
    )
    assert shown(made.path) == ["A ~word~ in plain.", "style A paragraph."]
    kinds = [kind for kind, _author, _date in _changes(made.path)]
    assert kinds.count("rPrChange") == 1 and kinds.count("pPrChange") == 1
    with_reject = resolved(made.path, accept=False, target=tmp_path / "rejected.docx")
    assert _readable(with_reject) == _readable(old)
    assert made.counts == {"paragraphs edited": 2, "words reformatted": 1,
                           "paragraphs restyled": 1}  # fmt: skip


@needs_pandoc
def test_a_deleted_list_item_keeps_a_numbering_of_its_own(tmp_path: Path) -> None:
    """A deleted item is the document sent's, numbered by a copy of its list, so that it
    joins none of the revision's lists."""
    made, old, _new = _marked(
        tmp_path, "1. one\n2. two\n3. three\n", "1. one\n2. three\n"
    )
    assert shown(made.path) == ["one", f"{PILCROW}- [-two-]", "three"]
    numbering = _xml(made.path, "word/numbering.xml")
    assert numbering.count("<w:num ") == _xml(old, "word/numbering.xml").count("<w:num ") + 1


@needs_pandoc
def test_two_documents_alike_make_a_copy_with_no_change(tmp_path: Path) -> None:
    text = "# A heading\n\nA paragraph with *emphasis* and 3.84.\n\n| A |\n|---|\n| 1 |\n"
    made, _old, _new = _marked(tmp_path, text, text)
    assert made.counts == {} and not made.changed
    assert _changes(made.path) == []


@needs_pandoc
def test_the_copy_says_what_it_is_and_carries_none_of_the_build_s_stamps(
    tmp_path: Path,
) -> None:
    from manuscript_guard.roundtrip import PRINTED_PROPERTY, stamp_into, stamp_of

    old, new = _pair(tmp_path, "One.\n", "Two.\n")
    stamp_into(new, "0" * 64, {"mg-p-main-1": "abc"}, "1" * 64, "offline")
    made = write(old, new, tmp_path / "copy.docx", date=DAY, round_number=2)
    said = marked_up_of(made.path)
    assert said is not None and said["form"] == "tracked" and said["round"] == 2
    assert len(said["since"]) == 64
    assert stamp_of(made.path) is None
    custom = _xml(made.path, "docProps/custom.xml")
    assert MARKED_UP_PROPERTY in custom and PRINTED_PROPERTY not in custom
    assert "manuscript-guard-paragraphs" not in custom
    assert marked_up_of(new) is None


@needs_pandoc
def test_a_copy_is_not_compared_and_a_document_with_changes_pending_is_refused(
    tmp_path: Path,
) -> None:
    made, old, new = _marked(tmp_path, "One.\n", "Two.\n")
    with pytest.raises(MarkedUpError, match="itself a marked-up copy"):
        write(made.path, new, tmp_path / "again.docx", date=DAY)
    with pytest.raises(MarkedUpError, match="tracked change"):
        write(old, _pending(made.path), tmp_path / "again.docx", date=DAY)
    assert not (tmp_path / "again.docx").exists()


def _pending(copy: Path) -> Path:
    """`copy` with its marked-up property gone: a document with changes nobody decided."""
    pending = copy.with_name("pending.docx")
    with zipfile.ZipFile(copy) as source, zipfile.ZipFile(pending, "w") as out:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "docProps/custom.xml":
                data = data.replace(MARKED_UP_PROPERTY.encode(), b"something-else")
            out.writestr(item, data)
    return pending


@needs_pandoc
def test_the_highlighted_copy_tracks_nothing_and_strikes_what_was_deleted(
    tmp_path: Path,
) -> None:
    """New text highlighted yellow, deleted text struck through and still there, a deleted
    picture left out; no change tracked, and nothing Word would refuse to open: each run's
    properties in the order Word reads them."""
    from readings import _png

    (tmp_path / "red.png").write_bytes(_png((255, 0, 0)))
    (tmp_path / "blue.png").write_bytes(_png((0, 0, 255)))
    made, _old, _new = _marked(
        tmp_path,
        "The *ratio* was 3.84.\n\n![Caption.](red.png)\n",
        "The *ratio* was 3.91.\n\n![Caption.](blue.png)\n",
        form="highlighted",
    )
    xml = _xml(made.path)
    assert _changes(made.path) == []
    assert '<w:highlight w:val="yellow" />' in xml and "<w:strike />" in xml
    assert "<w:delText" not in xml and "3.84" in xml and "3.91" in xml
    assert xml.count("<w:drawing>") == 1
    assert marked_up_of(made.path)["form"] == "highlighted"


def test_a_generated_document_reads_as_written(tmp_path: Path) -> None:
    """The documents the property is drawn over are read by `read_plainly` as `plain_of`
    says they hold, with no copy made: the test's two readings agree before they judge."""
    blocks = [
        {"kind": "p", "runs": [["A ", ""], ["word", "i"], [" here.", ""]], "style": "Heading1"},
        {"kind": "p", "runs": [["Noted.", ""]], "note": [["One note.", ""]]},
        {"kind": "table", "rows": [["a", "1"], ["b", "2"]]},
        {"kind": "figure", "picture": "red"},
        {"kind": "p", "runs": [["An item.", ""]], "list": True},
    ]
    document = document_of(blocks, tmp_path / "made.docx")
    assert read_plainly(document, accept=True) == plain_of(blocks)
    assert read_plainly(document, accept=False) == plain_of(blocks)
    assert [b[0] for b in _readable(document)] == [
        "heading", "", "table", "figure", "list", "note",
    ]  # fmt: skip


# --------------------------------------------------------------- the round and the commands


def _source(project: Path) -> Path:
    return project / "manuscript" / "main.md"


def _reword(project: Path, was: str, now: str) -> None:
    source = _source(project)
    text = source.read_text(encoding="utf-8")
    assert was in text, was
    source.write_text(text.replace(was, now, 1), encoding="utf-8")


_WAS = "Whether the signal extends to example-drug specifically has not been examined."
_NOW = "Whether the signal extends to example-drug specifically has not yet been examined."


@needs_pandoc
def test_a_round_keeps_the_document_sent_and_the_build_marks_up_what_changed_since(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`respond --open` keeps the document the journal received, the paper and its
    supplement, where it was built from the manuscript as it stands. `build --marked-up`
    then writes the revision with its changes shown into build/marked-up/, which `check`
    does not hold to the source as it holds a build."""
    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.freshness import _check_built_document

    assert main(["build", str(project), "--offline"]) == 0
    sent = (project / "build" / "manuscript.docx").read_bytes()
    capsys.readouterr()
    assert main(["respond", str(project), "--open"]) == 0
    said = capsys.readouterr().out
    kept = project / "revision" / "round-1" / "submitted" / "manuscript.docx"
    assert kept.read_bytes() == sent
    assert (kept.parent / "supplementary.docx").is_file()
    assert "revision/round-1/submitted/manuscript.docx is the document the journal" in said

    _reword(project, _WAS, _NOW)
    assert main(["build", str(project), "--offline", "--skip-checks", "--marked-up"]) == 0
    said = capsys.readouterr().out
    marked = next((project / "build" / "marked-up").glob("manuscript*.docx"))
    assert "against revision/round-1/submitted/manuscript.docx: 1 words inserted" in said
    assert _line(shown(marked), "example-drug specifically").endswith(
        "has not {+yet +}been examined."
    )
    assert marked_up_of(marked)["round"] == 1
    projekt, _ = load_project(project)
    assert not [f for f in _check_built_document(projekt).findings if "marked" in str(f.path)]


@needs_pandoc
def test_a_round_built_from_other_text_keeps_nothing_and_says_where_the_file_goes(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    _reword(project, _WAS, _NOW)
    capsys.readouterr()
    assert main(["respond", str(project), "--open"]) == 0
    said = capsys.readouterr().out
    assert "no document in build/ was built from the manuscript as it stands" in said
    assert "revision/round-1/submitted/manuscript.docx" in said
    assert not (project / "revision" / "round-1" / "submitted" / "manuscript.docx").exists()
    assert main(["build", str(project), "--offline", "--skip-checks", "--marked-up"]) == 1
    assert "round 1 kept no copy of the document the journal received" in capsys.readouterr().err
    sent = project / "sent.docx"
    shutil.copy2(project / "build" / "manuscript.docx", sent)
    assert main(["build", str(project), "--offline", "--skip-checks", "--marked-up",
                 "--since", str(sent), "--highlight"]) == 0  # fmt: skip
    marked = next((project / "build" / "marked-up").glob("manuscript*.highlighted.docx"))
    assert marked_up_of(marked)["form"] == "highlighted"


@needs_pandoc
def test_at_a_revision_the_pack_holds_the_marked_up_copy_beside_the_manuscript(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import yaml

    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    assert main(["respond", str(project), "--open"]) == 0
    _reword(project, _WAS, _NOW)
    capsys.readouterr()
    assert main(["submit", str(project), "--offline", "--skip-checks"]) == 0
    pack = project / "build" / "submission"
    marked = pack / "manuscript-marked-up.docx"
    assert marked_up_of(marked)["form"] == "tracked"
    assert marked_up_of(pack / "manuscript.docx") is None
    assert (pack / "supplementary-marked-up.docx").is_file()
    listed = yaml.safe_load((pack / "MANIFEST.yaml").read_text(encoding="utf-8"))
    assert {"manuscript-marked-up.docx", "supplementary-marked-up.docx"} <= {
        entry["file"] for entry in listed["files"]
    }


# ----------------------------------------------------------------------------- Word itself

_WORD = Path(__file__).parent / "data" / "word"


def test_word_reads_the_copy_as_the_package_does(tmp_path: Path) -> None:
    """`marked-up.docx` is a copy this writer made on 2026-10-21 of two pandoc documents
    holding a re-run, a word reworded, a paragraph moved, a word set in italics, a paragraph
    made a heading and one made text, a link's address changed, an inline and a display
    equation changed, a footnote reworded, one added and one removed, a list item deleted,
    a cell re-run and a row
    added, a figure replaced, a paragraph deleted before a table, a table of other columns,
    a reference added, and the document's last two paragraphs deleted. The two others are
    what Word 16 saved after Accept All and after Reject All on every story range, its
    author fields renamed. The package reads its own acceptance and rejection of the copy
    as it reads Word's, block by block and note by note."""
    copy = _WORD / "marked-up.docx"
    accepted = resolved(copy, accept=True, target=tmp_path / "accepted.docx")
    rejected = resolved(copy, accept=False, target=tmp_path / "rejected.docx")
    assert _readable(accepted) == _readable(_WORD / "marked-up-accepted-in-word.docx")
    assert _readable(rejected) == _readable(_WORD / "marked-up-rejected-in-word.docx")
    assert read_plainly(copy, accept=True) == read_plainly(
        _WORD / "marked-up-accepted-in-word.docx", accept=True
    )


def test_the_marked_up_options_go_with_marked_up_and_not_with_annotated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given without `--marked-up`, `--since`, `--round` and `--highlight` would be read by
    nothing and the build would look as if it had made a copy; and the annotated copy is
    made in place of the build, so the two are not made at once."""
    from manuscript_guard.cli import main

    for given in (["--since", "sent.docx"], ["--round", "2"], ["--highlight"]):
        assert main(["build", str(tmp_path), *given]) == 2
        assert "go with --marked-up" in capsys.readouterr().err
    assert main(["build", str(tmp_path), "--marked-up", "--annotated"]) == 2
    assert "one at a time" in capsys.readouterr().err
