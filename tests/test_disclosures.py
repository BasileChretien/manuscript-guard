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


_ANR = "ANR-20-CE17-0001"


def test_an_acknowledgements_section_that_says_none_denies_no_funding() -> None:
    """Round 1 of #653: "Acknowledgements: None." or BMC's "Not applicable." says nothing
    of funding; only a place a funding heading or label opens says none."""
    authors = _authors(ada_funding=[_ANR])
    for said in ("None.", "Not applicable."):
        main = f"## Acknowledgements\n\n{said}\n\n## Funding\n\nSupported by {_ANR}.\n"
        assert _codes(authors, main) == [], said
        assert _codes(authors, f"**Acknowledgements:** {said}\n\n**Funding:** {_ANR}.\n") == []
    assert _codes(authors, "## Funding\n\nNone.\n") == ["funding-denied"]


def test_a_sentence_about_funders_or_one_kind_of_funding_denies_none() -> None:
    """Round 1 of #653: the funders' role, and funding of one kind only (external, from
    industry, commercial), are no denial; a statement that gives the recorded identifier
    denies nothing either. Without the grant, each is a grant left out."""
    authors = _authors(ada_funding=[_ANR])
    for said in ("No funding body had any role in the design.",
                 "No funding source had a role in the analysis.",
                 "No funding agency was involved.",
                 "No external funding was received.",
                 "No financial support from industry was received.",
                 "The study received no industry funding.",
                 "The study was not funded by any commercial entity.",
                 "This work did not receive any commercial funding."):
        assert _codes(authors, f"## Funding\n\nSupported by {_ANR}. {said}\n") == [], said
        assert _codes(authors, f"## Funding\n\n{said}\n") == ["funding-grant-missing"], said
    assert _codes(authors, f"## Funding\n\n{_ANR}. This work received no funding.\n") == []


def test_an_author_with_an_interest_is_named_by_initials_as_the_lancet_writes_them() -> None:
    """Round 1 of #653: "AE reports ... All other authors declare no competing interests."
    names Ada Example, and "all other authors" is no collective none."""
    authors = _authors(ada_competing_interests="Consulting fees from Pharma X.",
                       blaise_competing_interests="None declared.")
    main = ("# Declaration of interests\n\nAE reports consulting fees from Pharma X. All "
            "other authors declare no competing interests.\n")
    assert _codes(authors, main) == []
    assert _codes(authors, main.replace("AE", "A.E.")) == []
    assert _codes(authors, main.replace("AE", "XY")) == ["interests-author-missing"]


def test_a_label_alone_in_its_paragraph_heads_the_paragraphs_after_it() -> None:
    """Round 1 of #653: Word conversions write "**Funding**" alone on its line. What
    follows, to the next label or heading, is the statement."""
    credited = _authors(ada_credit=["Conceptualization"], blaise_credit=["Supervision"])
    for label in ("**Author contributions**", "**Author contributions:**",
                  "Author contributions:"):
        main = f"{label}\n\nAE: Conceptualization.\n\nBS: Supervision.\n\n**Funding**\n\nNone.\n"
        assert _codes(credited, main) == [], label
    funded = _authors(ada_funding=[_ANR])
    for label in ("**Funding**", "Funding:", "*Funding*"):
        assert _codes(funded, f"{label}\n\n{_ANR}.\n\n**Competing interests**\n\nNone.\n") == []
        assert _codes(funded, f"{label}\n\nGrant 12345.\n\n**Competing interests**\n\n"
                      f"{_ANR}.\n") == ["funding-grant-missing"], label
        assert _codes(funded, f"{label}\n\nGrant 12345.\n\n## Results\n\n{_ANR}.\n") == [
            "funding-grant-missing"], label
    # A paragraph of emphasis is no label: a sentence in italics is read as prose.
    kinds = {place.kind for place in places("*Funding was scarce in 2019 for this work.*\n")}
    assert "funding" not in kinds


def test_a_section_holds_only_its_own_statement() -> None:
    """A heading's section ends at a heading or a label inside it that opens a statement of
    another kind, so the initials of the contributions statement under it name no one in the
    competing interests statement, and its "None declared." is the whole statement."""
    authors = _authors(ada_competing_interests="Fees from Pharma X.",
                       blaise_competing_interests="None declared.",
                       ada_credit=["Conceptualization"])
    for after in ("## Author contributions\n\nAE: Conceptualization.",
                  "**Author contributions:** AE: Conceptualization.",
                  "**Author contributions**\n\nAE: Conceptualization."):
        main = f"# Competing interests\n\nNone declared.\n\n{after}\n"
        assert _codes(authors, main) == ["interests-none-contradicted"], after
        main = f"# Competing interests\n\nBlaise Sample: none.\n\n{after}\n"
        assert _codes(authors, main) == ["interests-author-missing"], after


def test_a_credit_role_or_a_disclosure_item_as_a_label_ends_no_section() -> None:
    """Round 2 of #653: PLOS writes the roles first ("Funding acquisition: AE."), and
    ICMJE's form its items ("Grants or contracts from any entity: ..."). Neither is a
    statement of its own, nor ends the one it stands in; a label of another statement does."""
    credited = {"authors": [
        {"given": "Ada", "family": "Example", "credit": ["Conceptualization",
                                                        "Funding acquisition"]},
        {"given": "Blaise", "family": "Sample", "credit": ["Writing \N{EN DASH} original draft"]},
    ]}  # fmt: skip
    main = ("## Author contributions\n\nConceptualization: AE.\n\nFunding acquisition: AE.\n\n"
            "Writing \N{EN DASH} original draft: BS.\n")
    assert _codes(credited, main) == []
    interested = _authors(ada_competing_interests="Grants from Pharma X.",
                          blaise_competing_interests="None declared.",
                          ada_funding=[_ANR])
    main = ("## Competing interests\n\nGrants or contracts from any entity: AE received grants "
            f"from Pharma X.\n\n## Funding\n\n{_ANR}.\n")
    assert _codes(interested, main) == []
    # "Grants or contracts from any entity: none" is no funding statement that says none.
    main = ("## Competing interests\n\nAE: grants from Pharma X.\n\nGrants or contracts from "
            "any entity: none.\n\n## Funding\n\nGrant 99.\n")
    assert _codes(interested, main) == ["funding-grant-missing"]
    # A label of another statement still ends the section.
    main = (f"## Competing interests\n\nNone declared.\n\n**Funding:** {_ANR}. AE received "
            "grants from Pharma X.\n")
    assert _codes(interested, main) == ["interests-none-contradicted"]


def test_a_financial_interest_in_one_thing_is_no_collective_none() -> None:
    """Round 2 of #653: "no financial interest in the device" says nothing of competing
    interests; Springer Nature's and Elsevier's sentences still say none."""
    authors = _authors(ada_competing_interests="Consulting fees from Pharma X.",
                       blaise_competing_interests="None declared.")
    main = ("## Competing interests\n\nAE reports consulting fees from Pharma X. The authors "
            "have no financial interest in the device used in this study.\n")
    assert _codes(authors, main) == []
    for said in _NONE_FORMS[:2] + _NONE_FORMS[-1:]:
        assert _codes(authors, f"## Competing interests\n\nAE reports fees. {said}\n") == [
            "interests-none-contradicted"], said


def test_initials_name_an_author_only_as_written_in_capitals() -> None:
    """Round 2 of #653: Ian Smith's initials are "IS", "I.S.", "I. S." or "I-S", never the
    word "is"; alike for competing interests and for contributions."""
    authors = {"authors": [{"given": "Ian", "family": "Smith", "competing_interests":
                            "Grants from Y.", "credit": ["Supervision"]}]}  # fmt: skip
    for written in ("IS", "I.S.", "I. S.", "I-S"):
        main = (f"## Competing interests\n\n{written} reports grants from Y.\n\n"
                f"## Author contributions\n\n{written}: Supervision.\n")
        assert _codes(authors, main) == [], written
    main = ("## Competing interests\n\nAE reports fees from Pharma X and is a member of its "
            "board.\n\n## Author contributions\n\nAE is the guarantor. Supervision.\n")
    assert _codes(authors, main) == ["credit-author-missing", "interests-author-missing"]


def test_every_form_of_a_credit_heading_is_read_and_no_image_credit() -> None:
    """Round 2 of #653: "CRediT statement" and "CRediT roles" are read as 43383b1 read them."""
    authors = _authors(ada_credit=["Supervision"])
    for heading in ("CRediT statement", "CRediT roles", "CRediT role", "CRediT",
                    "CRediT author statement", "CRediT authorship contribution statement"):
        assert _codes(authors, f"## {heading}\n\nBS wrote it.\n") == [
            "credit-author-missing", "credit-role-missing"], heading
    for legend in ("Image credit: the authors.", "Photo credit: the authors.",
                   "Picture credit: the authors.", "## Image credits\n\nThe authors."):
        assert _codes(authors, f"{legend}\n") == [], legend


def test_a_label_alone_stops_at_the_next_label_alone() -> None:
    """Round 2 of #653: "**References**" alone in its paragraph ends the statement above it,
    whatever it names."""
    authors = _authors(ada_competing_interests="Fees from Pharma X.",
                       blaise_competing_interests="None declared.")
    for after in ("**References**", "**Data availability**", "References:"):
        main = (f"**Competing interests**\n\nNone declared.\n\n{after}\n\n1. Example A, "
                "Sample B. A study. J Ex. 2020;1:1-2.\n")
        assert _codes(authors, main) == ["interests-none-contradicted"], after


#: Record values that say none, as journals' forms write them, and what each reads as.
_NONE_FORMS = (
    "The author has no relevant financial or non-financial interests to disclose.",
    "The authors have no relevant financial or non-financial interests to disclose.",
    "No relevant disclosures.", "N/A", "n/a", "Not applicable.",
    "The authors declare that they have no known competing financial interests or personal "
    "relationships that could have appeared to influence the work reported in this paper.",
)  # fmt: skip


def test_the_none_forms_of_springer_and_elsevier_are_read_as_none() -> None:
    """Round 1 of #653: each form is a record of none, and, as the manuscript's whole
    statement or a sentence of it, a collective none."""
    for said in _NONE_FORMS:
        assert is_none_statement(said), said
    for said in _NONE_FORMS:
        both_none = _authors(ada_competing_interests=said, blaise_competing_interests=said)
        assert _codes(both_none, f"## Competing interests\n\n{said}\n") == [], said
        one_has = _authors(ada_competing_interests="Fees from Pharma X.",
                           blaise_competing_interests=said)
        if said.lower().startswith(("the author", "the authors")):
            assert _codes(one_has, f"## Competing interests\n\n{said}\n") == [
                "interests-none-contradicted"], said


def test_a_numbered_heading_is_read_by_its_words() -> None:
    """Round 1 of #653: the heading's number is taken off, Arabic or Roman, for every kind."""
    lead = {"name": "R. Lead", "approval": "IRB 2021-0456"}
    authors = {**_authors(ada_funding=[_ANR],
                          ada_competing_interests="Fees from Pharma X.",
                          blaise_competing_interests="None declared.",
                          ada_credit=["Conceptualization"]),
               "roles": {"ethics_lead": lead}}  # fmt: skip
    for number in ("6.", "6.1", "6.1.", "VI.", "7", "IV"):
        main = (f"## {number} Declarations\n\nThe IRB approved it (2021-0456).\n\n"
                f"## {number} Funding\n\n{_ANR}.\n\n"
                f"## {number} Competing interests\n\nAE: fees from Pharma X.\n\n"
                f"## {number} Author contributions\n\nAE: Conceptualization.\n")
        assert _codes(authors, main) == [], number
        ethics = main.replace("Declarations", "Ethics")
        assert _codes(authors, ethics) == [], number


def test_an_image_credit_is_no_contributions_statement() -> None:
    """Round 1 of #653: "Image credit:" in a legend is no CRediT statement."""
    authors = _authors(ada_credit=["Conceptualization"])
    for legend in ("Image credit: Wellcome Collection.", "Photo credit: the authors.",
                   "**Image credit:** Wellcome Collection.", "## Credits\n\nWellcome."):
        assert _codes(authors, f"Figure 1. A map.\n\n{legend}\n") == [], legend
    for heading in ("CRediT author statement", "CRediT authorship contribution statement",
                    "CRediT", "Authorship"):
        assert _codes(authors, f"## {heading}\n\nAE: Conceptualization.\n") == [], heading
        assert _codes(authors, f"## {heading}\n\nBS wrote it.\n") == [
            "credit-author-missing", "credit-role-missing"], heading


def test_an_authors_yaml_of_the_wrong_shapes_is_read_without_raising() -> None:
    """Round 1 of #653: the schema reports a malformed file; the check reads what it can."""
    main = "## Funding\n\nNone.\n\n## Author contributions\n\nAE: Conceptualization.\n"
    for authors in (
        {"authors": [{"given": "Ada", "family": "Example"}], "roles": "Sample"},
        {"authors": [{"given": "Ada", "family": "Example"}], "roles": ["Sample"]},
        {"authors": [{"given": "Ada", "family": "Example"}],
         "roles": {"ethics_lead": ["x"]}},
        {"authors": "Ada Example"},
        {"authors": ["Ada Example", None, 3]},
        {"authors": [{"given": "Ada", "family": "Example", "funding": [12345, None, {"a": 1}]}]},
        {"authors": [{"given": "Ada", "family": "Example", "funding": "ANR"}]},
        {"authors": [{"given": "Ada", "family": "Example", "credit": "Conceptualization"}]},
        {"authors": [{"given": "Ada", "family": "Example", "credit": [None, 3]}]},
        {"authors": [{"given": None, "family": 7, "competing_interests": ["x"]}]},
        {"authors": [{"given": "", "family": "", "credit": ["Conceptualization"]}]},
        ["not", "a", "mapping"],
    ):  # fmt: skip
        judge(authors, main)
    # A string `credit` is one role, as a string `funding` is one entry.
    one = {"authors": [{"given": "Ada", "family": "Example", "credit": "Supervision"}]}
    assert _codes(one, main) == ["credit-role-missing"]


def test_two_authors_of_one_family_name_are_named_together() -> None:
    """Known gap: a family name names every author who has it, so naming one passes both,
    for competing interests and for contributions."""
    authors = {"authors": [
        {"given": "Ada", "family": "Example", "competing_interests": "Fees from Pharma X.",
         "credit": ["Conceptualization"]},
        {"given": "Bea", "family": "Example", "competing_interests": "Fees from Pharma Y.",
         "credit": ["Supervision"]},
    ]}  # fmt: skip
    main = ("## Competing interests\n\nAda Example received fees from Pharma X.\n\n"
            "## Author contributions\n\nAda Example: Conceptualization, Supervision.\n")
    assert _codes(authors, main) == []


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
