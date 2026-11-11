"""`init --from`: a Word paper's typed reference list read into `references.bib`, and each
typed citation that names exactly one of its entries made `[@key]`.

The real-paper corpus rebuilt two Word papers as projects (PsyArXiv fyxeq_v2 and d8hkq_v1).
In both, the typed APA citations and reference list were the first wall: every year, volume
and page failed G2, and the rebuild wrote the `.bib` and the keys by hand. These tests quote
the shapes, not the papers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from manuscript_guard import typed_references
from manuscript_guard.cli import main
from manuscript_guard.typed_references.citations import make_citations, renderings
from manuscript_guard.typed_references.entries import Entry, Unread, read_entry

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

ARTICLE = ("Smith, J. A., & Jones, B. (2020). A title of work. *Journal of Things*, *12*(3), "
           "45--67. https://doi.org/10.1000/xyz123")  # fmt: skip


# ----------------------------------------------------------------- an entry, read or not


def _fields(entry: Entry | Unread) -> dict[str, str]:
    assert isinstance(entry, Entry), entry
    return dict(entry.fields)


def test_an_apa_article_is_read_field_by_field() -> None:
    entry = read_entry(ARTICLE, 7)
    assert isinstance(entry, Entry)
    assert (entry.families, entry.initials, entry.year, entry.kind, entry.line) == (
        ("Smith", "Jones"), ("J. A.", "B."), "2020", "article", 7)  # fmt: skip
    assert _fields(entry) == {"title": "A title of work", "journal": "Journal of Things",
                              "volume": "12", "number": "3", "pages": "45--67",
                              "doi": "10.1000/xyz123"}  # fmt: skip


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        # The journal and its volume in one run of italics, as Word users often set them.
        ("Smith, J., Lee, K., & Moe, P. (2019b). Another one? *Journal of Things, 11*, 1--2.",
         {"title": "Another one?", "journal": "Journal of Things", "volume": "11",
          "pages": "1--2"}),
        ("van der Berg, C., & O'Brien, S. (2017). Rates. *J Things*, *4*, e12. "
         "<https://doi.org/10.1000/a_b>", {"title": "Rates", "journal": "J Things", "volume": "4",
                                        "pages": "e12", "doi": "10.1000/a_b"}),
        ("García-López, J.-P. (2016). Costs \\& 50\\% of it. *Health \\& Care*, *2*(1--2), "
         "3--9. [https://x.org/p](https://x.org/p)",
         {"title": "Costs & 50% of it", "journal": "Health & Care", "volume": "2",
          "number": "1--2", "pages": "3--9", "url": "https://x.org/p"}),
        ("Lee, C. (2018). *A book of things*. Publisher.",
         {"title": "A book of things", "publisher": "Publisher"}),
        ("Lee, C. (2018). *Why now?* Big Press. https://doi.org/10.5555/b",
         {"title": "Why now?", "publisher": "Big Press", "doi": "10.5555/b"}),
    ],
    ids=["italics together", "particle and link", "escapes", "book", "book with a question"],
)
def test_each_shape_is_read_as_typed(typed: str, expected: dict[str, str]) -> None:
    assert _fields(read_entry(typed, 1)) == expected


@pytest.mark.parametrize(
    ("typed", "why"),
    [
        ("World Health Organization. (2020). *Report*. WHO.", "family name and initials"),
        ("Smith, John. (2020). *Report*. Press.", "family name and initials"),
        ("Smith, J., Jr., & Lee, K. (2020). *Report*. Press.", "family name and initials"),
        ("Smith, J., Lee, K. (2020). *Report*. Press.", "family name and initials"),
        ("Smith, J. (n.d.). *Report*. Press.", "no year"),
        ("Smith, J. (2020, March 3). *Report*. Press.", "no year"),
        ("Smith, J. (2020). A chapter. In K. Lee (Ed.), *Book* (pp. 1--2). Press.", "shape"),
        ("Smith, J. (2020). *Report* (2nd ed.). Press.", "shape"),
        ("Smith, J. (2020). Effects on *E. coli* growth. *J*, *1*, 1--2.", "shape"),
        ("Smith, J. (2020). The \"best\" way. *J*, *1*, 1--2.", "character"),
        ("Smith, J. (2020). Rates in the U.S. *J*, *1*, 1--2.", "shape"),
        ("Smith, J. (2020). Rates. *J*, *1*, 1--2. https://doi.org/10.1000/x.", "no DOI"),
        ("Smith, J. (2020). Rates. *J*, *1*, 1--2. [see here](https://x.org)", "shape"),
        # Round 1 of #638: a publisher took an edition, or what follows a stop, and a stop
        # an abbreviation ends with was taken for APA's.
        ("Lee, C. (2018). *Why now?* (2nd ed.). Big Press.", "shape"),
        ("Lee, C. (2018). *Title*. Big Press. Retrieved from https://x.org/b.", "shape"),
        ("Lee, C. (2018). *Title*. Press of the U.S.", "shape"),
        ("Smith, J. (2020). Training for the Ph.D. *J*, *1*, 1--2.", "shape"),
    ],
    ids=["group", "full name", "suffix", "no ampersand", "no date", "a day", "chapter",
         "edition", "italics inside", "quotation marks", "abbreviation", "stop after DOI",
         "link with words", "edition after a question", "retrieved from", "publisher's U.S.",
         "Ph.D."],  # fmt: skip
)
def test_an_entry_not_read_exactly_is_not_read_and_says_why(typed: str, why: str) -> None:
    """Nothing is guessed: an entry any of whose fields is not read exactly is not read."""
    entry = read_entry(typed, 4)
    assert isinstance(entry, Unread) and entry.line == 4, entry
    assert why in entry.why, entry.why


# ------------------------------------------------------------------- citations made keys


def _keyed(*typed: str) -> list[tuple[str, Entry]]:
    found = [read_entry(text, at) for at, text in enumerate(typed, start=100)]
    keyed, unkeyed = typed_references._keyed([one for one in found if isinstance(one, Entry)])
    assert not unkeyed
    return keyed


LIST = (
    ARTICLE,
    "Smith, J., Lee, K., & Moe, P. (2019). Another one? *Journal of Things, 11*, 1--2.",
    "Lee, C. (2018). *A book of things*. Publisher.",
    "Brown, A. (2021). One. *J*, *1*, 1--2.",
    "Brown, B. (2021). Two. *J*, *1*, 3--4.",
    "Green, A. (2015a). One. *J*, *1*, 1--2.",
    "Green, A. (2015b). Two. *J*, *1*, 3--4.",
    "van der Berg, C. (2014). Rates. *J*, *4*, 5--6.",
)


@pytest.mark.parametrize(
    ("typed", "made"),
    [
        ("(Smith & Jones, 2020)", "[@smith2020]"),
        ("(Smith and Jones, 2020)", "[@smith2020]"),
        ("(e.g., Smith & Jones, 2020; Lee, 2018)", "[e.g., @smith2020; @lee2018]"),
        ("(Smith et al., 2019)", "[@smith2019]"),
        ("(Smith, Lee, & Moe, 2019)", "[@smith2019]"),
        ("as Smith et al. (2019) said", "as @smith2019 said"),
        ("as Smith and Jones (2020) said", "as @smith2020 said"),
        ("(Green, 2015b; see also Green, 2015a)", "[@green2015b; see also @green2015a]"),
        ("as van der Berg (2014) said", "as @vanderberg2014 said"),
        ("(see van der Berg, 2014)", "[see @vanderberg2014]"),
    ],
)
def test_a_citation_that_names_one_entry_is_made_its_key(typed: str, made: str) -> None:
    text = f"Before. {typed}. After."
    written = make_citations(text, _keyed(*LIST), [], [])
    assert written.text == f"Before. {made}. After.", written
    assert written.left == ()


@pytest.mark.parametrize(
    ("typed", "why"),
    [
        ("(Brown, 2021)", "names 2 entries"),
        ("(Green, 2015)", "names no entry"),
        ("(Jones, 2020)", "names no entry"),
        ("(Smith, 2020)", "names no entry"),
        ("(Smith et al., 2020)", "names no entry"),
        ("(Smith & Jones, 2020; Black, 2001)", "names no entry"),
        ("(Smith & Jones, 2020; Table 2)", "not names and a year alone"),
        ("(Smith & Jones, 2020, p. 4)", "not names and a year alone"),
        ("Brown (2021) said", "names 2 entries"),
        # Round 1 of #638: "Brown and @lee2018" cited the work of Lee alone.
        ("As Brown and Lee (2018) said", "names no entry"),
        ("As Brown, Lee (2018) said", "names no entry"),
        ("Lee's (2018) book", "names no entry"),
        # A page or a second year after a narrative citation's year is listed, not passed.
        ("Lee (2018, p. 4) said", "page or a second year"),
        ("Lee (2018, 2019) said", "page or a second year"),
        # Citeproc prints "van der Berg (2014)", so the typed capital would be lost.
        ("Van der Berg (2014) said", "capital"),
    ],
)
def test_a_citation_that_names_none_or_two_stays_as_typed_and_is_listed(
    typed: str, why: str
) -> None:
    """Two "Brown 2021" with no letter, a year without the list's letter, a name of the
    authors short of all of them, and a group one of whose parts is any of these."""
    text = f"Before.\n{typed}. After."
    written = make_citations(text, _keyed(*LIST), [], [])
    assert written.text == text and written.converted == 0
    assert [(one.line, why in one.why) for one in written.left] == [(2, True)], written.left


def test_a_narrative_citation_names_the_entry_of_all_its_names() -> None:
    """Round 1 of #638: with "Brown & Lee 2018" in the list beside "Lee 2018", "Brown and
    Lee (2018)" was refused as naming two entries; it names one, all its names."""
    keyed = _keyed(*LIST, "Brown, A., & Lee, C. (2018). Two. *J*, *1*, 3--4.")
    written = make_citations("As Brown and Lee (2018) said.", keyed, [], [])
    assert written.text == "As @brown2018 said." and written.left == (), written


def test_one_work_typed_in_two_lists_is_one_entry() -> None:
    """Round 1 of #638: a work in the main list and in the supplement's had two keys, and its
    every citation was refused as naming two entries."""
    text = (f"# Introduction\n\nAs said (Lee, 2018).\n\n# References\n\n{LIST[2]}\n\n"
            f"# Appendix\n\nMore.\n\n## Bibliography\n\n{LIST[2]}\n")
    typed = typed_references.read(text)
    assert [key for key, _entry in typed.entries] == ["lee2018"], typed.entries
    assert "As said [@lee2018]." in typed.text and typed.left == (), typed


def test_a_note_after_the_list_is_no_entry_of_it() -> None:
    """Round 1 of #638: pandoc puts a Word paper's notes after the reference list, and each
    was listed as an entry not read."""
    text = f"# Introduction\n\nAs noted.[^1]\n\n# References\n\n{LIST[2]}\n\n[^1]: Of 2019.\n"
    assert typed_references.read(text).unread == ()


def test_a_year_in_brackets_that_is_no_citation_is_not_listed() -> None:
    text = "Data from (March 2020) and (n = 2018) and (in 2019) and Table 2 (2020)."
    assert make_citations(text, _keyed(*LIST), [], []) == (
        typed_references.citations.Made(text, 0, ())
    )


def test_an_entry_not_read_that_may_be_the_work_keeps_its_citation_typed() -> None:
    """A second "Lee 2018" the list could not read may be the one cited."""
    unread = Unread(50, "Lee, Carol. (2018). *Another book*. Press.", "names")
    written = make_citations("As said (Lee, 2018).", _keyed(*LIST), [unread], [])
    assert written.converted == 0 and "line 50" in written.left[0].why


def test_text_set_apart_is_not_changed() -> None:
    text = "(Lee, 2018)\n(Lee, 2018)\n"
    written = make_citations(text, _keyed(*LIST), [], [(0, 12)])
    assert written.text == "(Lee, 2018)\n[@lee2018]\n"


def test_renderings_name_every_author_or_the_first_with_et_al() -> None:
    assert renderings(("Lee",)) == ("Lee",)
    assert renderings(("Smith", "Jones")) == ("Smith & Jones", "Smith and Jones")
    assert "Smith et al." in renderings(("Smith", "Jones", "Moe"))
    assert "Smith, Jones, & Moe" in renderings(("Smith", "Jones", "Moe"))
    assert renderings(("van der Berg",)) == ("van der Berg",)


def test_keys_are_better_bibtex_author_year_with_a_letter_for_a_second() -> None:
    keys = [key for key, _entry in _keyed(*LIST)]
    assert keys == ["smith2020", "smith2019", "lee2018", "brown2021", "brown2021a",
                    "green2015a", "green2015b", "vanderberg2014"]  # fmt: skip


# ------------------------------------------------------------------ a whole paper's text

PAPER = """\
<!-- Title page (Smith & Jones, 2020). -->

# Introduction

Recovery matters (Smith & Jones, 2020; Lee, 2018). Brown (2021) disagreed.

# References

{entries}

Table 1. Counts (Lee, 2018).
"""


def test_a_paper_s_list_is_read_and_its_citations_made_keys() -> None:
    entries = "\n\n".join([*LIST, "World Health Organization. (2020). *Report*. WHO."])
    typed = typed_references.read(PAPER.format(entries=entries))
    assert [key for key, _entry in typed.entries][:3] == ["smith2020", "smith2019", "lee2018"]
    assert len(typed.unread) == 1 and typed.unread[0].line == 25
    assert typed.converted == 3
    # The title page's comment and the reference list are left as typed; the caption after
    # the list is the paper's.
    assert "<!-- Title page (Smith & Jones, 2020). -->" in typed.text
    assert "matters [@smith2020; @lee2018]. Brown (2021)" in typed.text
    assert "Table 1. Counts [@lee2018]." in typed.text
    assert ARTICLE in typed.text
    assert [(one.line, one.shown) for one in typed.left] == [(5, "Brown (2021)")]


@pytest.mark.parametrize("entry", ["1. Smith, J. (2020). *Report*. Press.",
                                   "[1] Smith, J. (2020). *Report*. Press."])
def test_a_numbered_list_is_left_as_typed(entry: str) -> None:
    text = PAPER.format(entries=entry)
    typed = typed_references.read(text)
    assert typed.text == text and not typed.entries and "numbers its entries" in typed.said


def test_no_list_and_a_bib_already_there_change_nothing() -> None:
    text = "# Introduction\n\nAs said (Lee, 2018).\n"
    assert "no reference list" in typed_references.read(text).said
    listed = PAPER.format(entries=LIST[2])
    there = typed_references.read(listed, bib_there=True)
    assert there.text == listed and "already there" in there.said


# ----------------------------------------------------------- the .bib, as pandoc reads it

TYPED = (
    ARTICLE,
    "García-López, J.-P., van der Berg, C., & O'Brien, S. (2016). Costs \\& 50\\% of #1 in "
    "Japan: A new approach -- x_y. *Health \\& Care*, *2*(1--2), 3--9. "
    "https://doi.org/10.1000/a_b%c",
    "Lee, C. (2018). *Why now? Japan's 2nd wave*. Big Press.",
)


@needs_pandoc
def test_every_field_written_is_what_pandoc_reads_from_the_typed_entry(tmp_path: Path) -> None:
    """A `.bib` field is read by pandoc as TeX and a title as title case: unbraced, "Japan"
    became "japan" and `%` began a comment. Each field written is read by pandoc as the
    typed entry prints it, the authors with their particles."""
    keyed = _keyed(*TYPED)
    typed = typed_references.TypedReferences("", tuple(keyed))
    bib = tmp_path / "references.bib"
    bib.write_text(typed_references.bib(typed, "paper.docx"), encoding="utf-8")
    read = {item["id"]: item for item in json.loads(subprocess.run(
        ["pandoc", "-f", "biblatex", "-t", "csljson", str(bib)], capture_output=True,
        check=True, encoding="utf-8").stdout)}  # fmt: skip

    def printed(markdown: str) -> str:
        return subprocess.run(["pandoc", "-f", "markdown", "-t", "plain", "--wrap=none"],
                              input=markdown, capture_output=True, check=True,
                              encoding="utf-8").stdout.strip()  # fmt: skip

    names = {"title": "title", "journal": "container-title", "publisher": "publisher",
             "volume": "volume", "number": "issue", "doi": "DOI"}  # fmt: skip
    for key, entry in keyed:
        item = read[key]
        for name, value in entry.fields:
            if name in names:
                assert item[names[name]] == printed(value.replace("*", "")), (name, item)
        assert item["issued"]["date-parts"] == [[int(entry.year[:4])]]
        people = [" ".join(filter(None, (one.get("non-dropping-particle"), one["family"])))
                  for one in item["author"]]  # fmt: skip
        assert people == [printed(family) for family in entry.families], item


# ------------------------------------------------------------------- G2 and the audit


@pytest.mark.parametrize("title", ["# References", "**References**"])
def test_the_audit_reads_no_number_of_a_typed_list_and_reads_one_after_it(
    tmp_path: Path, title: str
) -> None:
    """Decision 5: what `check` no longer fails in a typed reference list, the audit does not
    report either, and a number before the list is read as the paper's. (The audit's cut of
    a Markdown list runs on to the next heading: `audit.bibliography_spans`.)"""
    from manuscript_guard.audit import audit

    outputs = tmp_path / "out.json"
    outputs.write_text('{"n": 77}', encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text(f"# Results\n\nWe saw 4321 cases.\n\n{title}\n\n{ARTICLE}\n\n"
                     "# Appendix\n\nWe saw 8765 more.\n", encoding="utf-8")  # fmt: skip
    unmatched = {found.text for found in audit([paper], [outputs]).unmatched}
    assert {"4321", "8765"} <= unmatched, unmatched
    assert not unmatched & {"2020", "12", "45--67", "45–67", "3"}, unmatched


# ------------------------------------------------------------------------- init --from

BODY = """\
# Introduction

Recovery matters (Smith & Jones, 2020; Lee, 2018). Brown (2021) disagreed.

# References

{entries}
"""


def _word(folder: Path, markdown: str) -> Path:
    source, docx = folder / "paper.md", folder / "paper.docx"
    source.write_text(markdown, encoding="utf-8")
    subprocess.run(["pandoc", str(source), "-o", str(docx)], check=True)
    return docx


@needs_pandoc
def test_init_from_writes_the_bib_makes_keys_and_lists_the_rest(tmp_path: Path, capsys) -> None:
    entries = "\n\n".join([*LIST, "World Health Organization. (2020). *Report*. WHO."])
    docx = _word(tmp_path, BODY.format(entries=entries))
    root = tmp_path / "project"
    assert main(["init", str(root), "--from", str(docx)]) == 0
    said = capsys.readouterr().out
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert "Recovery matters [@smith2020; @lee2018]. Brown (2021) disagreed." in text
    bib = (root / "literature" / "references.bib").read_text(encoding="utf-8")
    assert "@article{smith2020," in bib and "@book{lee2018," in bib and "WHO" not in bib
    assert "8 entries of the typed reference list written" in said, said
    assert "2 citations typed as text made [@key]" in said, said
    lines = text.split("\n")
    unread = next(line for line in said.splitlines() if "family name and initials" in line)
    number = int(unread.split("main.md:")[1].split(":")[0])
    assert lines[number - 1].startswith("World Health Organization."), unread
    left = next(line for line in said.splitlines() if "Brown (2021)" in line)
    number = int(left.split("main.md:")[1].split(":")[0])
    assert "Brown (2021) disagreed" in lines[number - 1] and "names 2 entries" in left


@needs_pandoc
def test_init_from_keeps_a_bib_that_is_there(tmp_path: Path, capsys) -> None:
    docx = _word(tmp_path, BODY.format(entries=LIST[2]))
    root = tmp_path / "project"
    (root / "literature").mkdir(parents=True)
    (root / "literature" / "references.bib").write_text("% mine\n", encoding="utf-8")
    assert main(["init", str(root), "--from", str(docx)]) == 0
    assert "already there" in capsys.readouterr().out
    assert (root / "literature" / "references.bib").read_text(encoding="utf-8") == "% mine\n"
    assert "(Smith & Jones, 2020; Lee, 2018)" in (root / "manuscript" / "main.md").read_text(
        encoding="utf-8")
