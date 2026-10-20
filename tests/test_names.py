"""An author list read into people and groups, and two lists compared by family name.

`literature/names` reads a `.bib` entry's `author` field and each registry's way of writing
a name; `gates/authors` compares them by Basile's rules of 2026-10-20 (DESIGN.md, "A
reference is looked up once, and the answer is kept"). The generated cases are in
`tests/test_properties.py`; these are the forms each rule is about, one at a time.
"""

from __future__ import annotations

import pytest

from manuscript_guard.gates import authors
from manuscript_guard.literature import names
from manuscript_guard.literature.names import Authors, Name


@pytest.mark.parametrize(
    ("field", "read", "truncated"),
    [
        ("Naranjo, C. A. and Busto, U.", [("Naranjo", "C. A."), ("Busto", "U.")], False),
        ("Anna van der Berg and Smith Jr., John", [("van der Berg", "Anna"), ("Smith Jr.", "John")],
         False),
        ("van der Berg, Anna", [("van der Berg", "Anna")], False),
        # As PubMed prints a name, which BibTeX reads as given "Naranjo", family "CA".
        ("Naranjo CA and Busto U", [("Naranjo", "CA"), ("Busto", "U")], False),
        ("family=Berg, given=Anna, prefix=van der", [("van der Berg", "Anna")], False),
        ("Naranjo, C. A. and others", [("Naranjo", "C. A.")], True),
        ("Naranjo, C. A. et al.", [("Naranjo", "C. A.")], True),
        ("M{\\\"u}ller, Hans", [("M\\\"uller", "Hans")], False),
    ],
)  # fmt: skip
def test_a_bib_author_field_is_read_in_bibtex_s_forms(field, read, truncated) -> None:
    found = names.cited(field)
    assert [(n.family, n.given) for n in found.names] == read
    assert found.truncated is truncated


@pytest.mark.parametrize(
    "field",
    [
        "{World Health Organization} and Fictional, Anne",
        "RECOVERY Collaborative Group and Fictional, Anne",
        "{The Fictional Consortium, Inc.} and Fictional, Anne",
    ],
)
def test_a_group_is_kept_apart(field: str) -> None:
    found = names.cited(field)
    assert found.names[0].group and not found.names[0].family
    assert found.names[1] == Name(family="Fictional", given="Anne")


def test_each_registry_s_way_of_writing_a_name_is_read() -> None:
    assert names.pubmed("Walker-Smith JA") == Name(family="Walker-Smith", given="JA")
    assert names.pubmed("van der Berg A") == Name(family="van der Berg", given="A")
    assert names.pubmed("RECOVERY Collaborative Group", collective=True).group
    assert names.displayed("C. A. Naranjo") == Name(family="Naranjo", given="C. A.")
    assert names.displayed("Edward M. Sellers Jr.") == Name(family="Sellers", given="Edward M.")
    assert names.crossref({"given": "Anne", "family": "Fictional"}) == Name("Fictional", "Anne")
    assert names.crossref({"name": "The RECOVERY Collaborative Group"}).group
    assert names.crossref({"given": "Sukarno"}) == Name(family="Sukarno")


@pytest.mark.parametrize(
    ("cited", "registered", "same"),
    [
        ("van der Berg", "Berg", True),
        ("van der Berg", "Van Der Berg", True),
        ("Garc\N{LATIN SMALL LETTER I WITH ACUTE}a M\N{LATIN SMALL LETTER A WITH ACUTE}rquez",
         "Garcia", True),
        ("Garc\N{LATIN SMALL LETTER I WITH ACUTE}a-M\N{LATIN SMALL LETTER A WITH ACUTE}rquez",
         "Marquez", True),
        ("O'Brien", "OBrien", True),
        ("O\N{RIGHT SINGLE QUOTATION MARK}Brien", "O'Brien", True),
        ("M{\\\"u}ller", "Mueller", True),
        ("M\N{LATIN SMALL LETTER U WITH DIAERESIS}ller", "Muller", True),
        ("Rei\N{LATIN SMALL LETTER SHARP S}", "Reiss", True),
        ("J{\\o}rgensen", "J\N{LATIN SMALL LETTER O WITH STROKE}rgensen", True),
        ("Smith Jr.", "Smith", True),
        ("Lee", "Le", False),
        ("Chen", "Cheng", False),
        ("van Dijk", "van der Berg", False),
        # A particle alone is nobody's name.
        ("de", "de Vries", False),
        ("Smith", "Smyth", False),
    ],
)  # fmt: skip
def test_two_family_names_are_one_person_s_by_the_lenient_folding(cited, registered, same):
    assert authors.same(cited, registered) is same
    assert authors.same(registered, cited) is same


def _people(*families: str) -> list[Name]:
    return [Name(family=f) for f in families]


def test_every_cited_person_must_be_listed_and_the_first_first() -> None:
    cited = Authors(tuple(_people("Naranjo", "Busto")))
    assert authors.compare(cited, [_people("Naranjo", "Busto", "Sellers")]) == authors.Compared(
        compared=True, listed=("Naranjo", "Busto", "Sellers"))  # fmt: skip
    said = authors.compare(cited, [_people("Busto", "Naranjo")])
    assert said.compared and not said.disjoint and not said.first and not said.missing
    said = authors.compare(Authors(tuple(_people("Naranjo", "Dupont"))), [_people("Naranjo")])
    assert said.first and said.missing == ("Dupont",)
    said = authors.compare(Authors(tuple(_people("Dupont", "Leclerc"))), [_people("Naranjo")])
    assert said.disjoint and not said.first


def test_a_name_listed_by_any_record_is_listed() -> None:
    cited = Authors(tuple(_people("Naranjo", "Busto")))
    said = authors.compare(cited, [_people("Naranjo"), _people("Naranjo", "Busto")])
    assert said.first and not said.missing


def test_one_listed_person_answers_for_one_cited() -> None:
    said = authors.compare(Authors(tuple(_people("Wang", "Wang"))), [_people("Wang", "Li")])
    assert said.missing == ("Wang",)


def test_a_group_is_never_compared() -> None:
    group = Name(group="The RECOVERY Collaborative Group")
    assert not authors.compare(Authors(tuple(_people("Horby"))), [[group]]).compared
    assert not authors.compare(Authors((group,)), [_people("Horby")]).compared
    # A group ahead of the people is skipped on either side.
    said = authors.compare(Authors((group, *_people("Horby"))), [[group, *_people("Horby")]])
    assert said.first and not said.missing


def test_a_list_filed_the_other_way_round_is_read_once_more() -> None:
    """Some records file "Li Wang" as family name "Li", given name "Wang"."""
    swapped = [Name(family="Li", given="Wang"), Name(family="Mei", given="Zhang")]
    said = authors.compare(Authors(tuple(_people("Wang", "Zhang"))), [swapped])
    assert not said.disjoint and said.first and not said.missing
    # Initials are not a family name.
    said = authors.compare(Authors(tuple(_people("Wang"))), [[Name(family="Li", given="W.")]])
    assert said.disjoint
