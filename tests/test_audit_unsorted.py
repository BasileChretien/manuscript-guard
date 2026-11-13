"""`audit` says a paper's references it could not sort in one note (`auditing.unsorted`).

The corpus run on main at 710326696 audited 52 real preprints and gave 1,405
`reference-not-sorted` notes on 22 papers, one for each entry: 598 on docx-sport-A3, 579 on
docx-socio-B2, 65 on docx-psych-B2, 40 on docx-educ-A2. The author decided on one note per
paper listing the entries (decision 16, 2026-11-14), as the audit says the short forms left
undefined (#640) and the names from the code (#673). The other notes on an entry with no DOI
and no PMID stay one for each entry.
"""

from __future__ import annotations

import json
from pathlib import Path

from manuscript_guard.audit import audit
from manuscript_guard.auditing import by_title, unsorted
from manuscript_guard.auditing.report import REFERENCES, Item
from manuscript_guard.cli import main
from manuscript_guard.findings import INFO

#: The shape docx-educ-A2 and docx-socio-A1 have: a list by author and year with no numbers,
#: in which entries the audit cannot sort stand among articles it can.
UNNUMBERED = (
    "# Results\n\nIt rose (Ross, 2019).\n\n# References\n\n"
    "Adams, J. (2018). Field notes from the archive.\n\n"
    "Ross, K. L. (2019). Ghosts in the classroom: passive disengagement and its implications "
    "for teachers. Teachers and Teaching, 25(3), 312-325.\n\n"
    "Brown, L. (2020). Personal communication.\n\n"
    "Clark, M. (2021). Interview transcripts of the second wave.\n"
)
#: A numbered list with one entry not sorted, and two articles whose titles are too short to
#: look up, each a note of its own.
NUMBERED = (
    "# Results\n\nIt rose [1-3].\n\n# References\n\n"
    "1. Ross KL. Ghosts. Teach Teach. 2019;25(3):312-25.\n"
    "2. Adams J. Field notes from the archive. 2018.\n"
    "3. Clark M. Ghosts. Teach Teach. 2019;25(3):312-25.\n"
)
WHY = ("not sorted: neither an article, a book, a web page nor a legal text by its shape, so "
       "not looked up")  # fmt: skip


def _paper(folder: Path, text: str = UNNUMBERED, name: str = "paper.md") -> Path:
    paper = folder / name
    paper.write_text(text, encoding="utf-8")
    return paper


def _found(capsys, *arguments: str) -> list[dict]:
    assert main(["audit", *arguments, "--json"]) == 0
    return json.loads(capsys.readouterr().out)["findings"]


def _unsorted(found: list[dict]) -> list[dict]:
    return [f for f in found if f["code"] == unsorted.CODE]


def test_a_paper_s_entries_not_sorted_are_one_note_at_the_first(tmp_path: Path, capsys) -> None:
    """One note where there were three: the entries in the list's order, at the first one's
    place, the reason said once in its words, each entry under it with the note it had."""
    paper = _paper(tmp_path)
    (one,) = _unsorted(_found(capsys, str(paper)))
    assert one["message"] == (f"3 entries {WHY}: entries 1, 3 and 4 of the list; check them by "
                              "hand"), one["message"]  # fmt: skip
    assert (one["path"], one["line"]) == (str(paper), 7)
    assert (one["severity"], one["counted"], one["section"]) == (INFO, False, REFERENCES)
    assert [(e["entry"], e["line"]) for e in one["entries"]] == [
        ("entry 1 of the list", 7), ("entry 3 of the list", 11), ("entry 4 of the list", 13)]
    assert one["entries"][0]["message"] == (f"entry 1 of the list: {WHY}: check it by hand")


def test_one_entry_not_sorted_is_still_one_note(tmp_path: Path, capsys) -> None:
    """A paper with a single entry not sorted has one note, said in the singular; the notes
    on the titles too short to look up stay one for each entry."""
    found = _found(capsys, str(_paper(tmp_path, NUMBERED)))
    (one,) = _unsorted(found)
    assert one["message"] == f"1 entry {WHY}: entry 2; check it by hand", one["message"]
    assert one["line"] == 8 and [e["entry"] for e in one["entries"]] == ["entry 2"]
    short = [f for f in found if f["code"] == by_title.CODES[by_title.UNSEARCHED]]
    assert [f["line"] for f in short] == [7, 9], short


def test_each_paper_audited_has_a_note_of_its_own(tmp_path: Path, capsys) -> None:
    """Two papers audited at once: a note for each, at its own first entry."""
    first = _paper(tmp_path, UNNUMBERED, "first.md")
    second = _paper(tmp_path, NUMBERED, "second.md")
    found = _unsorted(_found(capsys, str(first), str(second)))
    assert [(f["path"], f["line"], len(f["entries"])) for f in found] == [
        (str(first), 7, 3), (str(second), 8, 1)], found


def test_the_summary_and_the_tile_still_count_the_entries(tmp_path: Path, capsys) -> None:
    """The References line counts the entries to check by hand, not the one note, and the
    tile is still "to look at"."""
    from manuscript_guard.auditing.summary import LOOK, standings

    paper = _paper(tmp_path)
    assert main(["audit", str(paper)]) == 0
    assert "3 entries to check by hand (not sorted): see below" in capsys.readouterr().out
    assert standings(audit([paper], None))["References"] == LOOK


def test_the_commented_copy_and_the_draft_say_it_once(tmp_path: Path, capsys) -> None:
    """The copy with comments lists one note for the entries, and the referee draft's
    further findings one bullet."""
    from manuscript_guard.auditing.commented import notes_of

    paper = _paper(tmp_path)
    notes = [note for note in notes_of(audit([paper], None), paper) if note.code == unsorted.CODE]
    assert len(notes) == 1 and "entries 1, 3 and 4 of the list" in notes[0].comment, notes
    target = tmp_path / "draft.md"
    assert main(["audit", str(paper), "--report-draft", str(target)]) == 0
    capsys.readouterr()
    further = target.read_text(encoding="utf-8").split("## Further findings")[1]
    assert further.count("not sorted: neither") == 1, further


def _note(label: str, why: str, line: int) -> Item:
    return Item(REFERENCES, "G7", unsorted.CODE, f"{label}: {why}: check it by hand", INFO,
                False, Path("paper.md"), line)  # fmt: skip


def test_each_reason_is_said_once_with_its_entries() -> None:
    """Entries left unsorted for two reasons: each reason once, with its entries, in the
    order each is first met; the note stands at the first entry. Any other item is left as
    it was."""
    other = Item(REFERENCES, "G7", "would-ask", "entry 9: would ask Crossref", INFO, False,
                 Path("paper.md"), 2)  # fmt: skip
    found = [other, _note("entry 3", WHY, 5), _note("\\bibitem{a}", "not sorted: another way",
                                                    6), _note("entry 7", WHY, 9)]  # fmt: skip
    audited = unsorted.one_finding(found)
    assert audited[0] is other and len(audited) == 2
    one = audited[1]
    assert one.message == (f"3 entries {WHY}: entries 3 and 7; not sorted: another way: "
                           "\\bibitem{a}; check them by hand"), one.message  # fmt: skip
    assert (one.path, one.line, one.severity, one.counted) == (Path("paper.md"), 5, INFO, False)
    assert unsorted.one_finding([other]) == [other]


def test_entries_of_each_kind_are_named_in_runs() -> None:
    """A LaTeX list's entries are named by their keys; where a list is read in part as
    numbered and in part as not, as docx-psych-B2's was, each run of one kind is said once,
    in the list's order."""
    labels = ["\\bibitem{a}", "\\bibitem{b}", "entry 3", "entry 1 of the list",
              "entry 2 of the list", "entry 34", "entry 38"]  # fmt: skip
    (one,) = unsorted.one_finding([_note(label, WHY, at) for at, label in enumerate(labels, 3)])
    assert one.message.endswith(
        ": \\bibitem{a} and \\bibitem{b}, then entry 3, then entries 1 and 2 of the list, then "
        "entries 34 and 38; check them by hand"), one.message  # fmt: skip
    assert one.message.startswith("7 entries not sorted") and one.line == 3
