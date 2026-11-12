"""G4's declarations held to authors.yaml (`gates/disclosures.py`), read through `judge`.

The cases in tests/test_corruption.py run the check on the example; these hold the
reading's rules and the limits DESIGN.md writes down under "Known gaps".
"""

from __future__ import annotations

from manuscript_guard.gates.disclosures import (
    entry_named,
    is_none_statement,
    judge,
    names_identifier,
    places,
)

EN_DASH, EM_DASH = "\N{EN DASH}", "\N{EM DASH}"


def _authors(**fields: object) -> dict:
    ada = {"given": "Ada", "family": "Example"}
    blaise = {"given": "Blaise", "family": "Sample"}
    for key, value in fields.items():
        who, field = key.split("_", 1)
        (ada if who == "ada" else blaise)[field] = value
    return {"authors": [ada, blaise]}


def _codes(authors: dict, main: str, supplement: str = "") -> list[str]:
    return sorted(f.code for f in judge(authors, main, supplement).findings)


def test_nothing_is_said_where_authors_yaml_fills_none_of_the_fields() -> None:
    assert _codes({"authors": [{"given": "Ada", "family": "Example"}]},
                  "# Funding\n\nThis work received no funding.\n") == []  # fmt: skip
    assert _codes({}, "# Funding\n\nNone.\n") == []


def test_a_grant_identifier_is_found_however_its_parts_are_joined() -> None:
    """Case and dashes folded, a separator optional between letters and digits, and needed
    between two runs of digits the record writes apart."""
    for written in ("ANR-20-CE17-0001", f"anr{EN_DASH}20{EN_DASH}ce17{EN_DASH}0001",
                    "ANR 20 CE17 0001", "ANR-20-CE-17-0001", "(ANR-20-CE17-0001)."):
        assert names_identifier(f"Funded by {written}", "ANR-20-CE17-0001"), written
    for written in ("ANR-20-CE17-00012", "ANR-2-CE17-0001", "ANR-200-CE17-0001",
                    "ANR20CE170001", "XANR-20-CE17-0001"):
        assert not names_identifier(f"Funded by {written}", "ANR-20-CE17-0001"), written
    # "R01 HL123456" written as one word, and the year of "Horizon 2020" in "H2020".
    assert entry_named("grant 5R01HL123456-03", "NIH R01 HL123456")
    assert entry_named("the EU's H2020 programme (101057015)",
                       "Horizon 2020, grant agreement 101057015")


def test_a_grant_is_found_by_its_identifier_whatever_funder_it_is_given_under() -> None:
    """Known gap: only the identifier of an entry that has one is read, so the right number
    under the wrong funder passes, and a number written apart ("12 345") is not found."""
    assert entry_named("Supported by the NIH (12345).", "Wellcome Trust 12345")
    assert not entry_named("Supported by the Wellcome Trust (12 345).", "Wellcome Trust 12345")


def test_a_funder_in_words_is_found_only_as_the_record_writes_it() -> None:
    """Accents, case, marks and `&` folded; its words in the record's order, every one of
    them, so an abbreviation or a word left out is not found (a Known gap)."""
    entry = "Fondation pour la Recherche M\N{LATIN SMALL LETTER E WITH ACUTE}dicale"
    assert entry_named("the *FONDATION POUR LA\nRECHERCHE MEDICALE*", entry)
    assert entry_named("Bill & Melinda Gates Foundation", "Bill and Melinda Gates Foundation")
    assert not entry_named("the FRM", entry)
    assert not entry_named("Fondation Recherche Medicale", entry)


def test_a_denial_is_read_by_the_listed_phrases_only() -> None:
    authors = _authors(ada_funding=["Wellcome Trust 12345"])
    for said in ("This work received no funding.", "No funding was received.",
                 "This research did not receive any specific grant from funding agencies.",
                 "None.", "Not applicable"):
        assert _codes(authors, f"# Funding\n\n{said}\n") == ["funding-denied"], said
    # Known gap: a denial in other words is not read as one, and is held as a statement
    # that leaves the grant out.
    assert _codes(authors, "# Funding\n\nWe had no money for this study.\n") == [
        "funding-grant-missing"]
    # The funders' role says nothing of whether there were funders.
    assert _codes(authors, "# Role of the funding source\n\nThe Wellcome Trust (12345) had "
                  "no role in the design.\n") == []


def test_each_place_a_statement_stands_is_read() -> None:
    """A heading that names it, a label a paragraph opens with, the Acknowledgements, and a
    Declarations section's parts; a sentence that only mentions funding is no label."""
    authors = _authors(ada_funding=["Wellcome Trust 12345"])
    for main in ("## 7. Sources of funding\n\nWellcome Trust 12345.\n",
                 "**Funding:** Wellcome Trust 12345.\n",
                 "Funding: Wellcome Trust 12345.\n",
                 "# Acknowledgements\n\nWe thank the Wellcome Trust (12345).\n",
                 "# Declarations\n\n## Funding\n\nGrant 12345.\n"):
        assert _codes(authors, main) == [], main
    kinds = {place.kind for place in places("Funding was scarce in 2019 for this work.\n")}
    assert "funding" not in kinds


def test_a_statement_under_a_heading_in_another_language_is_not_read() -> None:
    """Known gap: the headings and phrases are English only."""
    authors = _authors(ada_funding=["Wellcome Trust 12345"])
    assert _codes(authors, "# Financement\n\nAucun.\n") == ["funding-not-stated"]


def test_a_record_of_none_is_read_in_the_forms_authors_write_it() -> None:
    for said in ("None declared.", "None", "No competing interests.", "Nothing to declare",
                 "The author declares no competing interests.", "No conflicts of interest"):
        assert is_none_statement(said), said
    for said in ("Consulting fees from Pharma X.", "None other than a grant from X.", ""):
        assert not is_none_statement(said), said


def test_an_author_named_passes_whatever_the_statement_says_of_them() -> None:
    """Known gap: the name is read, not what is said of the person."""
    authors = _authors(ada_competing_interests="Consulting fees from Pharma X.",
                       blaise_competing_interests="None declared.")
    assert _codes(authors, "# Competing interests\n\nAda EXAMPLE declares no competing "
                  "interests.\n") == []


def test_a_collective_none_after_the_named_authors_is_read_by_its_words() -> None:
    """"The other authors" and "no other competing interests" say it of some of them; a
    collective none after a clause of its own is read as one for everyone (a Known gap)."""
    authors = _authors(ada_competing_interests="Consulting fees from Pharma X.",
                       blaise_competing_interests="None declared.")
    head = "# Competing interests\n\nAda Example received consulting fees from Pharma X. "
    assert _codes(authors, head + "The other authors declare no competing interests.\n") == []
    assert _codes(authors, head + "The authors declare no other competing interests.\n") == []
    assert _codes(authors, head + "Apart from this, the authors declare no competing "
                  "interests.\n") == ["interests-none-contradicted"]


def test_an_ethics_denial_is_read_anywhere_in_the_manuscript() -> None:
    """Known gap: a sentence that says no approval was needed is read wherever it stands, a
    sentence about another study among them."""
    authors = {**_authors(), "roles": {"ethics_lead": {"name": "R. Lead",
                                                       "approval": "IRB 2021-0456"}}}  # fmt: skip
    main = ("# Methods\n\nThe IRB approved the study (2021-0456).\n\n# Discussion\n\n"
            "Earlier registry studies did not require ethical approval.\n")
    assert _codes(authors, main) == ["ethics-approval-denied"]


def test_a_role_counts_whoever_the_statement_gives_it_to() -> None:
    """Known gap: which author holds which role is not read, and initials are read as a word
    wherever they stand in the statement."""
    authors = _authors(ada_credit=["Conceptualization"], blaise_credit=["Supervision"])
    main = (f"# Author contributions\n\nBS: Conceptualisation. AE: supervision{EM_DASH}"
            "and nothing else.\n")
    assert _codes(authors, main) == []
    assert _codes(authors, "# Contributors\n\nAE and BS wrote it.\n") == [
        "credit-role-missing", "credit-role-missing"]
