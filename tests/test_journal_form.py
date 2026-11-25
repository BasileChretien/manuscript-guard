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
from manuscript_guard.journal_form import STATEMENTS, FormError, as_text, authors_of, profile_of

DATE = "2026-11-25"


def found(statement: str, text: str) -> bool:
    """Whether G4 finds `statement` in `text`, as it searches a profile's pattern."""
    return bool(re.search(journal_form.pattern(STATEMENTS[statement].labels), text,
                          re.IGNORECASE | re.MULTILINE))  # fmt: skip


@pytest.mark.parametrize(("statement", "text"), [
    ("funding", "# Funding\n\nNone."),
    ("funding", "## 5. Funding\n\nNone."),
    ("funding", "Intro.\n\n**Funding:** none."),
    ("funding", "**Funding**: none."),
    ("funding", "*Funding.* None."),
    ("funding", "Funding: none."),
    ("funding", "Sources of funding: the trust."),
    ("competing-interests", "**Conflict of interest statement:** none."),
    ("competing-interests", "Declaration of competing interest: none."),
    ("competing-interests", "# Conflicts of Interest"),
    ("ethics", "# Ethics approval and consent to participate"),
    ("consent", "# Ethics approval and consent to participate"),
    ("ethics", "**Ethical approval.** The committee approved it."),
    ("data-availability", "Data availability statement: on request."),
    ("data-availability", "# Availability of data and materials"),
    ("author-contributions", "# Authors' contributions"),
    ("author-contributions", "# Author’s contributions"),
    ("author-contributions", "**Contributors:** AE wrote it."),
    ("trial-registration", "**Trial registration:** NCT01234567."),
    ("use-of-ai", "# Declaration of generative AI in the writing process"),
    ("use-of-ai", "AI disclosure: none was used."),
    ("use-of-ai", "## Statement on the use of AI"),
])  # fmt: skip
def test_a_statement_is_found_in_a_heading_or_the_label_its_paragraph_opens_with(
    statement: str, text: str
) -> None:
    assert found(statement, text)


@pytest.mark.parametrize(("statement", "text"), [
    # A sentence that mentions the subject is no statement of it.
    ("funding", "The funding of the study was public, and it ended in 2020."),
    ("funding", "We thank the **funding** agency."),
    ("consent", "Written consent was obtained from every patient."),
    ("ethics", "The ethics of the trial are discussed below."),
    # A heading that names another thing.
    ("trial-registration", "# Image registration"),
    ("author-contributions", "# Our contributions"),
    ("use-of-ai", "# AI-based models"),
    ("use-of-ai", "## Training the AI"),
    ("data-availability", "# Data collection"),
])  # fmt: skip
def test_a_sentence_or_another_heading_is_no_statement(statement: str, text: str) -> None:
    assert not found(statement, text)


def test_a_sentence_with_a_colon_after_a_few_words_is_read_as_a_label() -> None:
    """A label in plain type is read by its colon among the paragraph's first words, as the
    disclosures gate reads one: a sentence that opens that way is read as a statement too
    (DESIGN.md, Known gaps)."""
    assert found("consent", "We obtained consent from each patient: written, in their language.")


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
    """What the page's form asks is what the audit checks: the statements stated in a
    heading, a bold label and a plain one are found, the one missing is reported, and in a
    double-blind review an author named in the text is found."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "journal.yaml").write_text(as_text(profile_of({
        "date": DATE, "statements": ["funding", "competing-interests", "ethics", "consent",
                                     "use-of-ai"], "blinding": "double"})), encoding="utf-8")
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
