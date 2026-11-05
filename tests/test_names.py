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
        # An accent on a dotless i, as Better BibTeX writes it, before a t: with the braces
        # gone the accent's `\i` ran on into the letters after it and was read as `\it`.
        ("Sal{\\'\\i}tez", "Sal\N{LATIN SMALL LETTER I WITH ACUTE}tez", True),
        ("Sal{\\'\\i}tez", "Salez", False),
        ("Dam{\\^\\i}tre", "Dam\N{LATIN SMALL LETTER I WITH CIRCUMFLEX}tre", True),
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


#: An accent's argument is one letter or one command for a letter: after an accent, `\i`
#: and `\j` end where the letter does, whatever letters follow and however the braces
#: stood. `B` is the `\` of TeX, `t` the letter after the accented one.
_ON_A_DOTLESS_LETTER = [
    ("{B'Bi}t", "\N{LATIN SMALL LETTER I WITH ACUTE}t"),
    ("B'{Bi}t", "\N{LATIN SMALL LETTER I WITH ACUTE}t"),
    ("B'Bi{}t", "\N{LATIN SMALL LETTER I WITH ACUTE}t"),
    ("{B'{Bi}}t", "\N{LATIN SMALL LETTER I WITH ACUTE}t"),
    ("{B\"Bi}t", "\N{LATIN SMALL LETTER I WITH DIAERESIS}t"),
    ("{B^Bi}t", "\N{LATIN SMALL LETTER I WITH CIRCUMFLEX}t"),
    ("{B`Bi}t", "\N{LATIN SMALL LETTER I WITH GRAVE}t"),
    ("{B~Bi}t", "\N{LATIN SMALL LETTER I WITH TILDE}t"),
    ("{B=Bi}t", "\N{LATIN SMALL LETTER I WITH MACRON}t"),
    ("{Bu Bi}t", "\N{LATIN SMALL LETTER I WITH BREVE}t"),
    ("{Bv Bi}t", "\N{LATIN SMALL LETTER I WITH CARON}t"),
    ("Bv{Bi}t", "\N{LATIN SMALL LETTER I WITH CARON}t"),
    ("{B'Bi}ota", "\N{LATIN SMALL LETTER I WITH ACUTE}ota"),
    ("{Bv Bj}t", "\N{LATIN SMALL LETTER J WITH CARON}t"),
    # A letter command no accent is on, and an accent on a letter.
    ("{Bi}n", "\N{LATIN SMALL LETTER DOTLESS I}n"),
    ("{Bc c}a", "\N{LATIN SMALL LETTER C WITH CEDILLA}a"),
    ("Bc{c}a", "\N{LATIN SMALL LETTER C WITH CEDILLA}a"),
    ("{Bv S}a", "\N{LATIN CAPITAL LETTER S WITH CARON}a"),
    ("Bv{S}a", "\N{LATIN CAPITAL LETTER S WITH CARON}a"),
]


@pytest.mark.parametrize(("written", "printed"), _ON_A_DOTLESS_LETTER)
def test_a_tex_letter_is_the_letter_it_prints(written: str, printed: str) -> None:
    """Better BibTeX writes \N{LATIN SMALL LETTER I WITH ACUTE} as `{\\'\\i}`. The .bib's
    braces are gone before the TeX is read, so "Sal{\\'\\i}tez" reached the reader as
    `Sal\\'\\itez`, whose `\\itez` began with `\\it`, the command of italics: the name was
    "Salez", and G7 said a work by Salitez was by somebody else."""
    tex = written.replace("B", "\\")
    assert authors.name_words(f"Sal{tex}ez") == authors.name_words(f"Sal{printed}ez")
    assert authors.name_words(f"Sal{tex}ez") != authors.name_words("Salez")


def test_a_dotless_i_no_accent_is_on_before_a_t_is_pinned() -> None:
    """Known gaps: the braces are gone before the TeX is read, and `{\\i}t` is then `\\it`,
    as `\\it{...}` is. No accent says the `\\i` ends there, and the longer command is read,
    so a name written "\\c{C}{\\i}tan" is "Can"."""
    assert authors.name_words("\\c{C}{\\i}tan") == ("can",)
    assert authors.name_words("{\\c C}{\\i}tan") == ("can",)
    # Before any other letter, the `\i` is the letter.
    assert authors.name_words("\\c{C}{\\i}nar") == ("cinar",)


def _people(*families: str) -> list[Name]:
    return [Name(family=f) for f in families]


def test_a_journal_s_abbreviation_is_its_name_and_its_plural_is_another() -> None:
    """Round 2 of #379: "Cell" and "Cells" are two journals, as are "Cancer" and "Cancers"."""
    from manuscript_guard.gates.searched import same_journal

    assert same_journal("J Clin Epidemiol", "Journal of Clinical Epidemiology")
    assert same_journal("BMJ", "BMJ (Clinical research ed.)")
    assert same_journal("N. Engl. J. Med.", "The New England journal of medicine")
    for one, other in (("Cell", "Cells"), ("Cancer", "Cancers (Basel)"), ("Vaccine", "Vaccines"),
                       ("Lancet", "Lancet Oncol"), ("J Clin Epidemiol", "J Clin Endocrinol")):
        assert not same_journal(one, other), (one, other)


def test_records_are_one_work_only_where_no_two_of_them_differ() -> None:
    """Every two records that share no identifier are compared, not each with the first
    (the round after the budget of #379)."""
    from manuscript_guard.gates.searched import Work, _one

    def work(doi: str | None, *journals: str) -> Work:
        return Work("Crossref", "t", ("t",), (2021,), (), doi, None, {}, journals=journals)

    first = Work("PubMed", "t", ("t",), (2021,), (), None, "1", {},
                 journals=("Journal of Alpha", "J Beta"))  # fmt: skip
    # The first holds a name of each other, which differ, and share no identifier.
    assert not _one([first, work("10.5/a", "Journal of Alpha"), work(None, "J Beta")])
    # Two that share a DOI are one work however each registry writes the journal.
    assert _one([work("10.5/a", "Pharmacotherapy"),
                 work("10.5/a", "Pharmacotherapy: The Journal of Human Pharmacology")])  # fmt: skip


def test_a_double_surname_filed_among_the_given_names_is_one_person_s() -> None:
    """Crossref files George Davey Smith as given "George Davey", family "Smith"; a paper of
    the measurement of 2026-10-20 cites him as "Davey, SG"."""
    assert authors.same("Davey", "Smith", "George Davey")
    assert authors.same("Davey Smith", "Smith", "George Davey")
    assert not authors.same("Davey", "Smith", "G. D.")
    assert not authors.same("Davey", "Smith", "George")
    cited = Authors((Name(family="Davey", given="SG"),))
    said = authors.compare(cited, [[Name(family="Smith", given="George Davey")]])
    assert said.first and not said.disjoint


def test_every_cited_person_must_be_listed_and_the_first_first() -> None:
    cited = Authors(tuple(_people("Naranjo", "Busto")))
    assert authors.compare(cited, [_people("Naranjo", "Busto", "Sellers")]) == authors.Compared(
        compared=True, listed=("Naranjo", "Busto", "Sellers"))  # fmt: skip
    said = authors.compare(cited, [_people("Busto", "Naranjo")])
    assert said.compared and not said.disjoint and not said.first and not said.missing
    said = authors.compare(Authors(tuple(_people("Naranjo", "Dupont"))),
                           [_people("Naranjo", "Busto")])  # fmt: skip
    assert said.first and said.missing == ("Dupont",)
    said = authors.compare(Authors(tuple(_people("Dupont", "Leclerc"))), [_people("Naranjo")])
    assert said.disjoint and not said.first


def test_a_name_listed_by_any_record_is_listed() -> None:
    cited = Authors(tuple(_people("Naranjo", "Busto")))
    said = authors.compare(cited, [_people("Naranjo"), _people("Naranjo", "Busto")])
    assert said.first and not said.missing


def test_a_list_that_stops_short_says_nothing_of_the_names_after_it() -> None:
    """Crossref lists one author of a paper the entry cites with three (the measurement of
    2026-10-20); PubMed's list, which is complete, says who is missing."""
    cited = Authors(tuple(_people("Hossain", "Mannan", "Mostafa")))
    said = authors.compare(cited, [_people("Hossain")], [False])
    assert said.first and not said.missing
    said = authors.compare(cited, [_people("Hossain")], [True])
    assert said.missing == ("Mannan", "Mostafa")
    # A list as long as the entry's is no list cut short.
    said = authors.compare(cited, [_people("Hossain", "Rahman", "Akter")], [False])
    assert said.missing == ("Mannan", "Mostafa")


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
    # Round 1 of #379: a family name of two letters is one (Xu, Li, Wu, Ma).
    said = authors.compare(Authors((Name(family="Xu", given="Jun"),)),
                           [[Name(family="Jun", given="Xu")]])  # fmt: skip
    assert not said.disjoint and said.first
