"""The journal's profile and the authors' names the audit page's form makes
(`manuscript_guard.journal_form`): the files `audit --journal` and `--authors` read, each
statement found where a paper states it and not where a sentence only mentions it."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from manuscript_guard import journal_form
from manuscript_guard.auditing.journal import read_authors, read_profile
from manuscript_guard.cli import main
from manuscript_guard.journal_form import (
    STATEMENTS,
    FormError,
    as_text,
    authors_of,
    headings_of,
    profile_of,
)

DATE = "2026-11-25"


def found(heading: str, text: str) -> bool:
    """Whether G4 finds a statement the journal asks for under `heading`, as typed in the
    form, in `text`, as it searches a profile's pattern."""
    return bool(re.search(journal_form.pattern(headings_of(heading)), text,
                          re.IGNORECASE | re.MULTILINE))  # fmt: skip


@pytest.mark.parametrize(("heading", "text"), [
    ("Funding", "# Funding\n\nNone."),
    ("Funding", "## 5. Funding\n\nNone."),
    ("Funding", "## IV. Funding"),
    ("Funding", "# **Funding**"),
    ("Funding", "# FUNDING {#sec-funding}"),
    ("Funding", "Intro.\n\n**Funding:** none."),
    ("Funding", "**Funding**: none."),
    ("Funding", "**Funding** This work was supported by the trust."),
    ("Funding", "*Funding.* None."),
    ("Funding", "***Funding:*** none."),
    ("Funding", "Funding: none."),
    ("Funding", "[]{#_Hlk1 .anchor}**Funding:** none."),
    ("Funding", "**[]{#_Hlk1 .anchor}Funding:** none."),
    ("Funding", "[]{#_Hlk1 .anchor}Funding: none."),
    ("Funding/Support", "**Funding/Support:** the trust."),
    ("Funding (if any)", "# Funding (if any)"),
    ("Competing interests or Conflicts of interest", "Conflicts of interest: none."),
    ("Competing interests or Conflicts of interest", "# Competing interests"),
    ("Ethics approval and consent to participate",
     "# Ethics  approval and consent to participate"),
    ("Authors' contributions", "# Authors\u2019 contributions"),
    ("Author\u2019s contributions", "# Author's contributions"),
    # The end of a heading in any order (the redesign's review): a colon after the marks, a
    # closing sequence of hashes, a Word bookmark after the title.
    ("Funding", "# **Funding**:"),
    ("Funding", "# *Funding*."),
    ("Funding", "## Funding ##"),
    ("Funding", "# Funding[]{#_GoBack .anchor}"),
])  # fmt: skip
def test_a_statement_is_found_under_the_heading_the_journal_asks_for(
    heading: str, text: str
) -> None:
    assert found(heading, text)


@pytest.mark.parametrize(("heading", "text"), [
    # Another heading, or one that only opens with the journal's: the journal's own check
    # asks for its heading (Basile, 2026-11-25).
    ("Funding", "# Financial support"),
    ("Funding", "# Funding sources"),
    ("Funding", "## Funding of mental health services"),
    ("Funding", "# Acknowledgements and funding"),
    ("Funding", "**Funding sources:** NIH."),
    # A sentence, a bullet or a bold title that holds the word.
    ("Funding", "The funding of the study was public."),
    ("Funding", "Funding was provided by the trust."),
    ("Funding", "We thank the **funding** agency."),
    ("Informed consent", "* Patients who withdrew informed consent were excluded."),
    ("Funding", "**Table 2. Funding of the included trials**"),
    ("Funding", "| Funding: | the trust |"),
    ("Declaration of generative AI", "## The use of AI in radiology"),
])  # fmt: skip
def test_another_heading_a_sentence_or_a_title_is_no_statement(heading: str, text: str) -> None:
    assert not found(heading, text)


@pytest.mark.parametrize("opening", ["# Funding", "**Funding"])
def test_a_line_of_spaces_after_a_title_is_read_in_linear_time(assert_linear, opening) -> None:
    """A line that does not end where its title does is refused in time that grows with the
    spaces after the title as they grow (the redesign's review: three runs of spaces back to
    back took cubic time, and 3000 of them stalled the search). The line is timed 64 times
    over, each a line of its own the search starts on: once, a linear search of 819,200
    spaces took under the 20 ms `assert_linear` needs to time it on CI's runner."""
    assert not found("Funding", opening + " " * 3000 + "x")
    searched = re.compile(journal_form.pattern(["Funding"]), re.IGNORECASE | re.MULTILINE)
    assert_linear(lambda n: (opening + " " * n + "x\n") * 64, searched.search, 200,
                  "a statement's pattern, by the spaces after its title")  # fmt: skip


def test_a_statement_ticked_takes_its_usual_heading_or_the_journal_s(tmp_path: Path) -> None:
    """Each statement ticked is held to the heading the reader typed, alternatives joined by
    " or ", or to its usual one where nothing is typed, and the report's hint names them."""
    profile = profile_of({"date": DATE, "statements": ["competing-interests", "funding"],
                          "headings": {"funding": "  Funding   or Financial support ",
                                       "competing-interests": " "}})  # fmt: skip
    funding, interests = profile["required_statements"]
    assert funding["id"] == "funding" and interests["id"] == "competing-interests"
    assert funding["why"].endswith('under the heading "Funding" or "Financial support".')
    assert interests["why"].endswith('under the heading "Competing interests".')
    for text in ("# Funding", "# Financial support"):
        assert re.search(funding["pattern"], text, re.IGNORECASE | re.MULTILINE)
    assert headings_of("A or b OR c") == ["A", "b", "c"]
    assert headings_of("  ") == []
    assert all(statement.heading for statement in STATEMENTS.values())


def test_the_form_makes_a_profile_the_command_line_reads(tmp_path: Path) -> None:
    form = {"name": "Journal of Tests", "url": "https://example.org/authors", "date": DATE,
            "limits": {"abstract_words": "250", "figures": "0", "tables": "", "keywords": " 6 "},
            "sections": ["Introduction", " ", "Methods"],
            "abstract_headings": ["Background", "Conclusions"],
            "statements": ["use-of-ai", "funding"], "blinding": "double"}  # fmt: skip
    path = tmp_path / "journal.yaml"
    path.write_text(as_text(profile_of(form)), encoding="utf-8")
    profile, errors = read_profile(path)
    assert errors == []
    assert profile["name"] == "Journal of Tests" and profile["retrieved_on"] == DATE
    # A limit left empty is not in the profile, and is not checked; 0 figures is a limit.
    assert profile["limits"] == {"abstract_words": 250, "figures": 0, "keywords": 6}
    assert profile["structure"] == {"required_sections": ["Introduction", "Methods"],
                                    "abstract_structured": True,
                                    "abstract_headings": ["Background", "Conclusions"]}
    # In the order the page lists them, whatever the order ticked.
    assert [one["id"] for one in profile["required_statements"]] == ["funding", "use-of-ai"]
    assert profile["blinding"] == "double"
    bare = profile_of({"date": DATE})
    assert bare["name"] == journal_form.UNNAMED
    assert not {"limits", "structure", "required_statements", "blinding"} & set(bare)


@pytest.mark.parametrize(("form", "said"), [
    ({"date": DATE, "limits": {"abstract_words": "250 words"}}, "the words in the abstract"),
    ({"date": DATE, "limits": {"abstract_words": "0"}}, "a whole number from 1"),
    ({"date": DATE, "limits": {"tables": "-1"}}, "the tables is a whole number from 0"),
    ({"date": DATE, "statements": ["plagiarism"]}, "no statement 'plagiarism'"),
    ({"date": DATE, "blinding": "quadruple"}, "single, double, triple or open"),
    ({"date": "25/11/2026"}, "is no date"),
])  # fmt: skip
def test_a_form_the_profile_cannot_hold_is_refused(form: dict, said: str) -> None:
    with pytest.raises(FormError, match=re.escape(said)):
        profile_of(form)


def test_the_form_makes_the_authors_file_the_command_line_reads(tmp_path: Path) -> None:
    form = {"authors": [{"given": "Ada", "family": "Example", "orcid": "0000-0002-1825-0097",
                         "email": " ada@example.org "}, {"given": "", "family": ""},
                        {"given": "Grace", "family": "Hopper"}],
            "affiliations": ["Department of Examples, University of Nowhere", ""]}  # fmt: skip
    path = tmp_path / "authors.yaml"
    path.write_text(as_text(authors_of(form)), encoding="utf-8")
    document, why = read_authors(path)
    assert why == ""
    assert document == {
        "authors": [{"given": "Ada", "family": "Example", "orcid": "0000-0002-1825-0097",
                     "email": "ada@example.org"}, {"given": "Grace", "family": "Hopper"}],
        "affiliations": [{"text": "Department of Examples, University of Nowhere"}]}
    with pytest.raises(FormError, match="author 1 needs a given name and a family name"):
        authors_of({"authors": [{"given": "Ada"}]})
    with pytest.raises(FormError, match="no author is named"):
        authors_of({"authors": [{}], "affiliations": ["Somewhere"]})


def test_the_audit_holds_a_paper_to_the_profile_the_form_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """What the page's form asks is what the audit checks: the statements stated under the
    headings the journal asks for, in a heading, a bold label and a plain one, are found, the
    one missing is reported, and in a double-blind review an author named in the text is
    found."""
    monkeypatch.chdir(tmp_path)
    both = "Ethics approval and consent to participate"
    (tmp_path / "journal.yaml").write_text(as_text(profile_of({
        "date": DATE, "statements": ["funding", "competing-interests", "ethics", "consent",
                                     "use-of-ai"], "blinding": "double",
        "headings": {"competing-interests": "Competing interests or Conflicts of interest",
                     "ethics": both, "consent": both}})), encoding="utf-8")
    (tmp_path / "authors.yaml").write_text(as_text(authors_of({
        "authors": [{"given": "Ada", "family": "Lovelace"}]})), encoding="utf-8")
    (tmp_path / "paper.md").write_text(
        "# Methods\n\nAda Lovelace did it.\n\n**Funding:** none.\n\n"
        "Conflicts of interest: none.\n\n# Ethics approval and consent to participate\n\n"
        "Approved.\n", encoding="utf-8")  # fmt: skip
    main(["audit", "paper.md", "--journal", "journal.yaml", "--authors", "authors.yaml"])
    out = capsys.readouterr().out
    missing = re.findall(r"the journal requires a (\S+) statement", out)
    assert missing == ["use-of-ai"], out
    assert "'Ada Lovelace' is in the text of paper.md" in out
