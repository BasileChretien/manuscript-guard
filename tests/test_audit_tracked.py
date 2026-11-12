"""`audit --tracked`: one copy of the .docx, with each correction G14 is sure of as a Word
tracked change and every other finding as a comment (the author's audit, 2026-11-11)."""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

import pytest
from generated import word_package

from manuscript_guard.cli import main

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DATE = "2026-11-12T00:00:00Z"
STYLES = ("<w:styles xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
          "<w:style w:type='paragraph' w:styleId='Heading1'><w:name w:val='heading 1'/>"
          "</w:style></w:styles>")  # fmt: skip


def heading(text: str) -> str:
    return f"<w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>"


def para(*runs: str) -> str:
    """A paragraph of runs, each plain or, as `**words`, in bold."""
    out = []
    for run in runs:
        bold = run.startswith("**")
        words = run[2:] if bold else run
        out.append("<w:r>" + ("<w:rPr><w:b/></w:rPr>" if bold else "")
                   + f"<w:t xml:space='preserve'>{words}</w:t></w:r>")  # fmt: skip
    return "<w:p>" + "".join(out) + "</w:p>"


def docx(path: Path, body: str) -> Path:
    parts = {**word_package(body), "word/styles.xml": STYLES}
    with zipfile.ZipFile(path, "w") as archive:
        for name, part in parts.items():
            archive.writestr(name, part)
    return path


def read(path: Path, accept: bool | None = None) -> list[str]:
    """The text of each paragraph of the document, with every change in it accepted, or
    rejected, or (None) as it stands."""
    from manuscript_guard.auditing.tracked_copy import resolved_texts
    from manuscript_guard.safexml import parse_xml
    from manuscript_guard.tracked import _chars

    with zipfile.ZipFile(path) as archive:
        root = parse_xml(archive.read("word/document.xml"), what="document")
    if accept is None:
        return [_chars(paragraph)[0] for paragraph in root.iter(W + "p")]
    taken = {node.get(W + "id") for node in root.iter() if node.tag in (W + "ins", W + "del")}
    return resolved_texts(root, taken, accept=accept)


def comments(path: Path) -> list[str]:
    from manuscript_guard.docxtext import word_comments

    return [one.text for one in word_comments(path)]


def tracked(old: str, new: str, before: str = "", after: str = "", *,
            code: str = "spelling-variant", line: int = 1, left_out: str = ""):  # fmt: skip
    from manuscript_guard.auditing.gates import Tracked

    return Tracked((code,), old, new, before, after, line, left_out)


def written(tmp_path: Path, body: str, corrections: list, notes: list | None = None):
    from manuscript_guard.auditing.commented import write

    source = docx(tmp_path / "paper.docx", body)
    target = tmp_path / "tracked.docx"
    result = write(source, target, notes or [], date=DATE, corrections=corrections)
    return source, target, result


# ------------------------------------------------------------------ what as_tracked gives


def _edits(text: str, *changes: tuple[str, str, str]):
    """Edits of `text` as `main.md`: each `old` (found first after `at`) becoming `new`."""
    from manuscript_guard.corrections import Edit
    from manuscript_guard.gates.vocabulary import Passage

    passage = Passage(Path("manuscript/main.md"), text, text,
                      lambda offset: text.count("\n", 0, offset) + 1)  # fmt: skip
    out = []
    for code, old, new in changes:
        start = text.index(old)
        out.append(Edit(code, passage, start, start + len(old), new, (start, start + len(old))))
    return out


def test_a_correction_is_given_as_the_document_prints_it() -> None:
    """Pandoc's escapes are taken off and its dashes and dots put back: "1--2" is the en
    dash the document prints, "\\<" a "<"; the words around it are its line's, without what
    opens the line as a heading, cut at a word where the line runs on."""
    from manuscript_guard.auditing.gates import as_tracked

    text = ("# The colour\n\nWhat we saw, in a long sentence that runs on and on before it, "
            "was 1-2 \\<5 times and more... than any colour seen before in the whole cohort.\n")
    found = as_tracked(_edits(text, ("spelling-variant", "The colour", "The color"),
                              ("notation-interval", "1-2", "1--2")))  # fmt: skip
    assert [(one.old, one.new, one.before, one.after) for one in found] == [
        ("The colour", "The color", "", ""),
        ("1-2", "1\N{EN DASH}2", "that runs on and on before it, was ",
         " <5 times and more\N{HORIZONTAL ELLIPSIS} than any colour"),
    ]  # fmt: skip
    assert [one.line for one in found] == [1, 3]


@pytest.mark.parametrize(("text", "old", "new", "why"), [
    ("The *colour* of it.\n", "*colour*", "*color*", "a mark the document does not print"),
    ("It was 'colour'd' then.\n", "'colour'd'", "'color'd'", "a quotation mark"),
    ("Its colour\\\nwas red.\n", "colour\\\nwas", "color\\\nwas", "over a line"),
    ("Its colour was red.\n", "colour", "colour", "changes nothing"),
])  # fmt: skip
def test_a_correction_the_document_cannot_be_given_exactly_is_left_out(
    text: str, old: str, new: str, why: str
) -> None:
    """Emphasis, a quotation mark pandoc writes straight for a curly one, a line's end:
    the correction is kept with why, so that its finding stays a comment."""
    from manuscript_guard.auditing.gates import as_tracked

    (found,) = as_tracked(_edits(text, ("spelling-variant", old, new)))
    assert why in found.left_out


def test_the_words_around_a_correction_are_cut_at_a_mark_the_document_does_not_print() -> None:
    from manuscript_guard.auditing.gates import as_tracked

    text = "A *bold* claim on colour, see [the table](#t) for more.\n"
    (found,) = as_tracked(_edits(text, ("spelling-variant", "colour", "color")))
    assert (found.before, found.after) == (" claim on ", ", see ")


# --------------------------------------------------------------------------- the writer


def test_only_the_changed_characters_are_deleted_and_inserted_in_their_own_runs(
    tmp_path: Path,
) -> None:
    """ "beha" + bold "viour": the "u" is deleted from the bold run, and nothing else; the
    space put in after "P", which is in italics, is in italics, and the one after "=" plain."""
    body = ("<w:p><w:r><w:t xml:space='preserve'>Their beha</w:t></w:r><w:r><w:rPr><w:b/>"
            "</w:rPr><w:t xml:space='preserve'>viour was seen (</w:t></w:r><w:r><w:rPr><w:i/>"
            "</w:rPr><w:t>P</w:t></w:r><w:r><w:t xml:space='preserve'>=0.03).</w:t></w:r></w:p>")
    source, target, result = written(tmp_path, body, [
        tracked("behaviour", "behavior", "Their ", " was seen"),
        tracked("P=0.03", "P = 0.03", "seen (", ").", code="notation-sign-spacing"),
    ])  # fmt: skip
    assert result.tracked == 2 and not result.untracked
    assert read(target, accept=True) == ["Their behavior was seen (P = 0.03)."]
    assert read(target, accept=False) == read(source)
    with zipfile.ZipFile(target) as archive:
        document = archive.read("word/document.xml").decode()
    deleted = re.findall(r"<w:del [^>]*>(.*?)</w:del>", document)
    assert len(deleted) == 1 and "<w:b" in deleted[0] and ">u</w:delText>" in deleted[0]
    inserted = re.findall(r"<w:ins [^>]*>(.*?)</w:ins>", document)
    assert len(inserted) == 2 and sum("<w:i" in one for one in inserted) == 1
    assert all('w:author="manuscript-guard"' in one and f'w:date="{DATE}"' in one
               for one in re.findall(r"<w:(?:ins|del) [^>]*>", document))  # fmt: skip
    # No paragraph mark is deleted: Word hangs on Accept All where the last one is (#396).
    assert "<w:pPr><w:rPr><w:del" not in document


def test_a_note_all_of_whose_corrections_are_written_is_no_comment(tmp_path: Path) -> None:
    from manuscript_guard.auditing.commented import Note

    body = para("The behaviour was odd.") + para("The colour was odd.")
    notes = [Note("behaviour", "The behaviour was odd.", "spelt British", code="spelling-variant",
                  line=1),
             Note("colour", "The colour was odd.", "colour too", code="spelling-variant", line=3),
             Note("odd", "The behaviour was odd.", "another kind", code="ai-phrasing", line=1)]
    _source, target, result = written(tmp_path, body, [
        tracked("behaviour", "behavior", "The ", " was", line=1),
        tracked("colour", "color", "The ", " was", line=3),
    ], notes)  # fmt: skip
    assert result.tracked == 2
    assert comments(target) == ["another kind"]


def test_a_correction_found_in_two_places_is_left_out_and_its_finding_stays_a_comment(
    tmp_path: Path,
) -> None:
    from manuscript_guard.auditing.commented import Note

    body = para("The colour was odd.") * 2 + para("The behaviour was odd.")
    notes = [Note("colour", "The colour was odd.", "colour stays", code="spelling-variant",
                  line=1),
             Note("behaviour", "The behaviour was odd.", "behaviour goes", code="spelling-variant",
                  line=5)]
    source, target, result = written(tmp_path, body, [
        tracked("colour", "color", "The ", " was", line=1),
        tracked("behaviour", "behavior", "The ", " was", line=5),
    ], notes)  # fmt: skip
    assert result.tracked == 1
    assert [why for _one, why in result.untracked] == ["its words are in 2 places in the document"]
    assert comments(target) == ["colour stays"]
    assert read(target, accept=True) == ["The colour was odd."] * 2 + ["The behavior was odd."]


def test_a_correction_inside_a_link_is_left_out(tmp_path: Path) -> None:
    body = ("<w:p><w:r><w:t xml:space='preserve'>See </w:t></w:r><w:hyperlink r:id='rId9'><w:r>"
            "<w:t>colour</w:t></w:r></w:hyperlink><w:r><w:t xml:space='preserve'> here."
            "</w:t></w:r></w:p>")
    source, target, result = written(tmp_path, body, [tracked("colour", "color", "See ", " here")])
    assert result.tracked == 0
    assert "field, a link" in result.untracked[0][1]
    assert read(target, accept=True) == read(source)


def test_a_document_s_own_tracked_changes_are_left_as_they_stand(tmp_path: Path) -> None:
    """The check reads only this copy's changes accepted and rejected: an author's own
    insertion stays an insertion, by its author."""
    body = (para("The colour was odd.")
            + "<w:p><w:ins w:id='7' w:author='Ada' w:date='2026-01-01T00:00:00Z'><w:r><w:t>"
            "Hers.</w:t></w:r></w:ins></w:p>")  # fmt: skip
    _source, target, result = written(tmp_path, body, [tracked("colour", "color", "The ", " was")])
    assert result.tracked == 1
    with zipfile.ZipFile(target) as archive:
        document = archive.read("word/document.xml").decode()
    assert re.findall(r"<w:(ins|del) [^>]*w:author=\"([^\"]+)\"", document) == [
        ("del", "manuscript-guard"), ("ins", "Ada")]
    assert read(target) == ["The color was odd.", "Hers."]


def test_a_wrong_placement_is_refused_and_no_copy_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check reads the copy back: with a correction written one character off, it does
    not read as the document with the correction made, and nothing is written."""
    from manuscript_guard.auditing import tracked_copy
    from manuscript_guard.auditing.commented import CommentedError

    real = tracked_copy.write_changes

    def off_by_one(paragraphs, placed, ids, date):
        moved = [tracked_copy.Placed(one.index, one.start + 1, one.end + 1, one.tracked)
                 for one in placed]  # fmt: skip
        return real(paragraphs, moved, ids, date)

    monkeypatch.setattr(tracked_copy, "write_changes", off_by_one)
    with pytest.raises(CommentedError, match="with every change accepted"):
        written(tmp_path, para("The colour was odd."), [tracked("colour", "color", "The ", " was")])
    assert not (tmp_path / "tracked.docx").exists()


def test_a_change_that_leaves_the_document_altered_when_rejected_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuscript_guard.auditing import tracked_copy
    from manuscript_guard.auditing.commented import CommentedError

    def nothing_kept(paragraph, lo, hi, inserted, revisions, *, opens):
        from manuscript_guard.tracked import _chars

        _text, where = _chars(paragraph)
        where[lo].text.text = where[lo].text.text.replace("u", "")

    monkeypatch.setattr(tracked_copy, "_change", nothing_kept)
    with pytest.raises(CommentedError, match="with every change rejected"):
        written(tmp_path, para("The colour was odd."), [tracked("colour", "color", "The ", " was")])
    assert not (tmp_path / "tracked.docx").exists()


# ------------------------------------------------------------------------ the command line


@needs_pandoc
def test_the_audit_writes_one_copy_with_corrections_tracked_and_findings_commented(
    tmp_path: Path, capsys
) -> None:
    """In American English: "behaviour" and "colour" respelt, "P=0.03" spaced as the rest
    are, the reporting odds ratio written out where ROR is not used again; each a tracked
    change, and none of their findings a comment."""
    body = (heading("Methods")
            + para("The behaviour of the cohort was studied, and its colour was noted.")
            + para("We used the reporting odds ratio (ROR) throughout the work.")
            + heading("Results")
            + para("We found P = 0.01 and P = 0.02 and P = 0.04 among the patients.")
            + para("The change was seen (P=0.03) in the last of them."))  # fmt: skip
    paper = docx(tmp_path / "paper.docx", body)
    given = paper.read_bytes()
    target = tmp_path / "tracked.docx"
    assert main(["audit", str(paper), "--english", "american", "--tracked", str(target)]) == 0
    err = capsys.readouterr().err
    assert "4 corrections as tracked changes" in err, err
    assert read(target, accept=True) == [
        "Methods", "The behavior of the cohort was studied, and its color was noted.",
        "We used the reporting odds ratio throughout the work.", "Results",
        "We found P = 0.01 and P = 0.02 and P = 0.04 among the patients.",
        "The change was seen (P = 0.03) in the last of them.",
    ]  # fmt: skip
    assert read(target, accept=False) == read(paper)
    said = "\n".join(comments(target))
    assert "behaviour" not in said and "'colour'" not in said and "P=0.03" not in said
    assert paper.read_bytes() == given


@pytest.mark.parametrize(("target", "paper", "extra", "said"), [
    ("there.docx", "paper.docx", [], "the file is there already"),
    ("tracked.md", "paper.docx", [], "writes a Word document (.docx)"),
    ("tracked.docx", "paper.md", [], "and paper.md is not one"),
    ("paper.docx", "paper.docx", [], "the file is there already"),
    ("missing/tracked.docx", "paper.docx", [], "its folder does not exist"),
    ("tracked.docx", "paper.docx", ["--commented", "tracked.docx"],
     "that is the file --commented writes"),
])  # fmt: skip
def test_a_tracked_copy_is_refused_where_it_cannot_be_written(
    tmp_path: Path, capsys, target: str, paper: str, extra: list[str], said: str
) -> None:
    docx(tmp_path / "paper.docx", para("Of 40 patients, 12 improved."))
    (tmp_path / "paper.md").write_text("# Results\n\nOf 40 patients, 12 improved.\n",
                                       encoding="utf-8")  # fmt: skip
    (tmp_path / "there.docx").write_bytes(b"theirs")
    extra = [str(tmp_path / one) if one.endswith(".docx") else one for one in extra]
    code = main(["audit", str(tmp_path / paper), "--tracked", str(tmp_path / target), *extra])
    assert code == 2
    assert said in capsys.readouterr().err
    assert (tmp_path / "there.docx").read_bytes() == b"theirs"
    assert not (tmp_path / "tracked.docx").exists()
