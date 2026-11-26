"""The draft of the letter returning a paper to its authors before review (`audit --letter`,
`auditing.letter`; Basile, 2026-11-25): what the editor's report would ask the authors and
what it would have the editor look at, each kind once in a sentence written for the
authors, with its places; never a place in the journal's profile, never over a file."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_audit_readers import PAPER as CLEAN
from test_audit_readers import profile

from manuscript_guard.auditing import NOTICE, READER_FLAGS, editor, letter
from manuscript_guard.auditing.report import Item
from manuscript_guard.cli import main
from manuscript_guard.findings import WARN
from manuscript_guard.hooks import _reads_in_confidence

#: A paper with a fault of each part the letter asks: a citation past the end of its list
#: and an entry cited nowhere (the authors'), and an estimate outside its own interval (the
#: editor's); held to `profile`'s 40 words and its Funding statement, it is over the one and
#: lacks the other (the authors').
FLAWED = (
    "# Introduction\n\nThe colour of the urine was recorded in every patient who came to the "
    "clinic during the study [1].\n\n"
    "# Methods\n\nWe counted the patients seen in each month of the year and the share of "
    "them whose urine was dark [3].\n\n"
    "# Results\n\nOf 40 patients, 12 (30%) had dark urine at the first visit, and the odds "
    "ratio was 2.1 (95% CI 2.5 to 3.0).\n\n"
    "# Discussion\n\nDark urine was common among the patients seen at this clinic.\n\n"
    "# References\n\n1. Smith J. Urine colour. J Ex. 2020;1:1-2.\n"
    "2. Jones K. Another study. J Ex. 2021;2:3-4.\n"
)
#: The paper's faults by the kind the editor's report gives them, and the part of each.
EXPECTED = {"beyond-list": editor.ASK, "never-cited": editor.ASK, "over-limit": editor.ASK,
            "required-missing": editor.ASK, "numbers-disagree": editor.LOOK}  # fmt: skip


def _flawed(tmp_path: Path) -> tuple[Path, Path]:
    paper = tmp_path / "paper.md"
    paper.write_text(FLAWED, encoding="utf-8")
    return paper, profile(tmp_path)


def _letter(tmp_path: Path, capsys, *argv: str, name: str = "letter.md") -> tuple[str, str]:
    target = tmp_path / name
    assert main(["audit", *argv, "--letter", str(target)]) == 0
    return target.read_text(encoding="utf-8"), capsys.readouterr().err


# ------------------------------------------------------------------------ the sentences


def test_every_kind_the_letter_asks_has_a_sentence_for_the_authors_and_no_other() -> None:
    """A kind of the two parts the letter asks with no sentence of its own would be asked in
    the one for any finding, and the editor's own words (a sign "there to steer the review")
    are not the authors'; a name that is no such kind is a misspelling."""
    asked = {kind.name for kind in editor.KINDS if kind.part in dict(letter.ASKED)}
    named = set(letter.sentences().kinds)
    assert asked == named, (sorted(asked - named), sorted(named - asked))
    said = {kind.name: kind.says for kind in editor.KINDS}
    assert all(letter.sentences().kinds[name] != said[name] for name in named)


@pytest.mark.parametrize(("text", "said"), [
    ("further: x\n", "needs `kinds`"),
    ("kinds: {total-off: ' '}\nfurther: x\n", "'total-off' is not a name with a sentence"),
    ("kinds: {total-off: x}\n", "'further' is not a name with a sentence"),
])  # fmt: skip
def test_sentences_that_are_wrong_are_refused_with_where(text: str, said: str) -> None:
    with pytest.raises(ValueError, match="letter.yaml") as raised:
        letter.read(text)
    assert said in str(raised.value)


def test_a_finding_no_kind_names_is_asked_in_the_sentence_for_any() -> None:
    assert letter.asked(editor.FURTHER) == letter.sentences().further


def test_a_file_whose_only_sign_is_words_to_a_model_is_not_said_to_hide_text() -> None:
    """Round 1 of #796: the kind `hidden-text` also holds a Word file whose only sign is words
    addressed to a model that a reader sees (`editor._hides` reads `to_a_model`, which counts
    printed ones too), so its sentence names those words as well as text no reader sees."""
    word = Path("paper.docx")
    held = dict.fromkeys(("insertions", "deletions", "moves", "comments", "hidden", "unseen",
                          "zero_width"), [])  # fmt: skip
    facts = SimpleNamespace(path=word, note="", to_a_model=["x"], **held)
    found = Item("Document", "audit", "document-holds", "said", WARN, False, word)
    kind = editor.kind_of(found, SimpleNamespace(documents=[facts]))
    assert kind.name == "hidden-text"
    assert "addressed to" in letter.asked(kind) and "cannot see" in letter.asked(kind)


# ------------------------------------------------------------------------ the letter


def test_the_letter_asks_the_authors_kinds_then_the_editors_each_once_with_its_places(
    tmp_path: Path, capsys
) -> None:
    paper, journal = _flawed(tmp_path)
    text, err = _letter(tmp_path, capsys, str(paper), "--journal", str(journal))
    assert NOTICE in err and "the draft of the letter to the authors is in" in err
    lines = text.splitlines()
    assert lines[0] == letter.FIRST and letter.GREETING in lines and letter.OPENING in lines
    assert lines[-len(letter.SIGNED):] == list(letter.SIGNED)
    (ask, ask_title), (look, look_title) = letter.ASKED
    first, second = text.index(f"## {ask_title}"), text.index(f"## {look_title}")
    assert first < second < text.index(letter.CLOSING)
    assert text.index(letter.CHECK_SAID) > second
    for name, part in EXPECTED.items():
        sentence = letter.sentences().kinds[name]
        assert text.count(sentence) == 1, name
        assert (text.index(sentence) > second) is (part == look), name
    assert "\n   - paper.md:7: [3] cites entry 3, which the reference list does not hold" in text
    assert "\n     > odds ratio was 2.1 (95% CI 2.5 to 3.0" in text
    assert "\n   - the journal requires a funding statement\n" in text
    # The journal's profile is the editor's file, not the authors': no place names it.
    assert journal.name not in text
    # Copyediting and what the check read are the report's, not the letter's.
    assert editor.title(editor.COPYEDIT) not in text and editor.title(editor.READ) not in text


def test_the_letter_is_the_same_each_time_and_never_written_over_a_file(
    tmp_path: Path, capsys
) -> None:
    paper, journal = _flawed(tmp_path)
    one, _ = _letter(tmp_path, capsys, str(paper), "--journal", str(journal), name="one.md")
    two, _ = _letter(tmp_path, capsys, str(paper), "--journal", str(journal), name="two.md")
    assert one == two
    target = tmp_path / "one.md"
    target.write_text("my own words", encoding="utf-8")
    assert main(["audit", str(paper), "--letter", str(target)]) == 2
    assert f"--letter {target}: the file is there already" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "my own words"


@pytest.mark.parametrize("case", ["text", "draft", "paper", "package"])
def test_the_letter_is_refused_where_it_cannot_be_written(tmp_path: Path, capsys,
                                                          case: str) -> None:  # fmt: skip
    paper, _journal = _flawed(tmp_path)
    target = tmp_path / ("letter.txt" if case == "text" else "letter.md")
    argv = {"text": [str(paper), "--letter", str(target)],
            "draft": [str(paper), "--letter", str(target), "--report-draft", str(target)],
            "paper": [str(paper), "--letter", str(paper)],
            "package": ["--package", str(tmp_path / "package.zip"), "--letter", str(target)]}
    assert main(["audit", *argv[case]]) == 2
    said = {"text": "--letter writes Markdown", "draft": "that is a file the command reads",
            "paper": f"--letter {paper}: the file is there already",
            "package": "--letter reads a paper"}[case]
    assert said in capsys.readouterr().err
    assert not target.exists() or case == "paper"
    assert paper.read_text(encoding="utf-8") == FLAWED


def test_with_nothing_to_ask_the_letter_says_so_and_asks_nothing(tmp_path: Path,
                                                                capsys) -> None:  # fmt: skip
    paper = tmp_path / "paper.md"
    paper.write_text(CLEAN, encoding="utf-8")
    text, _ = _letter(tmp_path, capsys, str(paper))
    assert letter.NOTHING in text
    assert letter.OPENING not in text and "## " not in text


def test_a_letter_is_a_reading_in_confidence() -> None:
    """The letter quotes the manuscript, so an agent running the audit for it is put to the
    person, as for the report draft (`hooks._reads_in_confidence`)."""
    assert "--letter" in READER_FLAGS
    assert _reads_in_confidence("manuscript-guard audit paper.docx --letter letter.md")
