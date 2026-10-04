"""Names and units written with pandoc's subscript and superscript signs, as G2 reads them.

`HbA~1c~` is how pandoc is told to print a subscript, and `kg/m^2^` a superscript. G2 cut
`CO~2~` to the atom `CO~2`, which no term matched: `HbA1c` is a built-in term and `HbA~1c~`
was an unbound number, a declared `CO2` did not cover `CO~2~`, and every square metre
written `m^2^` was reported where `m²` never was. An author had to declare `CO~2`, with
the sign in it, or type the character.

A name is now matched against the terms with its signs taken out, and an exponent on a
unit is read as the superscript character is: as typography. A number is still a number:
`10^6^` is reported, and so is one typed between the signs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.cli import main
from manuscript_guard.text.masking import mask
from manuscript_guard.text.tokens import find_atoms

N = chr(10)


def atoms(text: str) -> list[str]:
    return [atom.text for atom in find_atoms(text, mask(text))]


def unbound(text: str, terms: tuple[str, ...] = ()) -> list[str]:
    """The atoms of `text` that nothing classifies, with `terms` declared by the project."""
    classifier = Classifier.load(extra_terms=terms)
    return [
        atom.text
        for atom in find_atoms(text, mask(text))
        if classifier.classify(atom).kind == UNCLASSIFIED
    ]


# ------------------------------------------------------------------------------------- names

#: A name with a subscript or a superscript, and the terms the project declares.
NAMES = {
    "a built-in name": ("HbA~1c~ was measured at baseline.", ()),
    "three more": ("PaCO~2~ and SpO~2~ fell, and FEV~1~ with them.", ()),
    "a built-in name with a superscript after it": ("CD4^+^ cells were counted.", ()),
    "a declared name": ("End-tidal CO~2~ was recorded.", ("CO2",)),
    "a declared name, in brackets and before a comma": (
        "Nitrous oxide (N~2~O), CO~2~, and air.",
        ("N2O", "CO2"),
    ),
    "a declared name with a slash in its subscript": (
        "A half-life t~1/2~ was estimated.",
        ("t1/2",),
    ),
    "a declared ion": ("Ca^2+^ was measured.", ("Ca2+",)),
    "a declared isotope": ("^99m^Tc was the tracer.", ("99mTc",)),
    "a name declared with its sign, as it had to be": (
        "End-tidal CO~2~ was recorded.",
        ("CO~2",),
    ),
    "a name declared without signs and written without": (
        "End-tidal CO2 was recorded.",
        ("CO2",),
    ),
    "two built-in names with a slash between": ("A PaO~2~/FiO~2~ ratio was taken.", ()),
    "a built-in name before a slash, a sign, a hyphen": (
        "FEV~1~/FVC, SpO~2~% and HbA~1c~-guided care.",
        (),
    ),
    "a built-in name in emphasis and in brackets": ("**HbA~1c~** (*HbA~1c~*) was used.", ()),
    "a symbol with a subscript that is a term": ("Vitamin B~12~ was given.", ()),
}


@pytest.mark.parametrize("case", list(NAMES))
def test_a_name_is_matched_against_the_terms_with_its_signs_taken_out(case: str) -> None:
    text, terms = NAMES[case]
    assert unbound(text, terms) == []


#: A name nobody declared, and a number beside a name: each is still reported.
NOT_NAMES = {
    "a name that is not declared": ("End-tidal CO~2~ was recorded.", (), ["CO~2"]),
    "another": ("Nitrous oxide, N~2~O, was given.", ("CO2",), ["N~2~O"]),
    "a number after a declared name": ("A CO~2~7.2 reading.", ("CO2",), ["CO~2~7.2"]),
    "a number after a built-in name": ("An HbA~1c~7.2 reading.", (), ["HbA~1c~7.2"]),
    "a number with a subscript": ("There were 412~patients~ in all.", (), ["412~patients"]),
    "a number with a unit in a subscript": ("A dose of 5~mg~ was given.", (), ["5~mg"]),
    "a number between the signs": ("There were ^412^ patients.", (), ["^412^"]),
    "a range written with a tilde": ("Between 5~10 mg were given.", (), ["5~10"]),
    # A tilde nothing closes is no subscript, and pandoc prints it: it stands for "about"
    # or for a range. With every sign taken out, the number after it joined the letters
    # before it, and `pH~2` was `ph2`, which holds the built-in term `h2`.
    "a number after a tilde, and a word a term ends": (
        "An effect of about HR~2 at pH~2 was sought.",
        (),
        ["HR~2", "pH~2"],
    ),
    "the same in brackets": ("A median of 3 (IQR~2) and an OR~2.", (), ["3", "IQR~2", "OR~2"]),
    "a deviation": ("With an SD~3 overall.", (), ["SD~3"]),
    "a fold change and a share": (
        "Reporting increased~2-fold, to around~3% of reports.",
        (),
        ["increased~2-fold", "around~3%"],
    ),
    "the upper end of a range": (
        "From 1 week~2 weeks and 1 h~2 h.",
        (),
        ["1", "week~2", "1", "h~2"],
    ),
    "a letter and a number that make a term": (
        "The slope was b~1 with d~2 and k~2 clusters.",
        (),
        ["b~1", "d~2", "k~2"],
    ),
    "a declared name whose tilde nothing closes": ("A CO~2 reading.", ("CO2",), ["CO~2"]),
    # A closed sign is one, and a term still has to open a word: the 1 of `risk^1^` is a
    # citation's number, and `risk1` holds the term `k1`.
    "a citation's number after a word a term ends": (
        "As for risk^1^, cancer^2^ and death^1^ before.",
        (),
        ["risk^1^", "cancer^2^", "death^1^"],
    ),
    "the same after a drug's name": (
        "With nivolumab^6^ or pembrolizumab^12^.",
        (),
        ["nivolumab^6^", "pembrolizumab^12^"],
    ),
    "a subscript after a word a term ends": ("At week~2~ and month~2~.", (), ["week~2", "month~2"]),
    "a declared name inside a longer word": ("A preCO~2~ reading.", ("CO2",), ["preCO~2"]),
}


@pytest.mark.parametrize("case", list(NOT_NAMES))
def test_what_no_term_covers_is_still_reported(case: str) -> None:
    text, terms, reported = NOT_NAMES[case]
    assert unbound(text, terms) == reported


def test_a_name_matched_without_its_signs_is_counted_as_the_projects_own() -> None:
    """A run says how much of its clean bill it owes to the project's own allowlist, and a
    name matched with its signs taken out is on that list like any other."""
    classifier = Classifier.load(extra_terms=("CO2",))
    text = "End-tidal CO~2~ was recorded."
    [atom] = find_atoms(text, mask(text))

    verdict = classifier.classify(atom)

    assert verdict.kind == "term"
    assert classifier.is_project_exemption(verdict)


def test_a_declared_name_that_holds_a_comma_is_counted_as_the_projects_own() -> None:
    """The hint for `IL~1,2~` says `terms: ["IL1,2"]`. What the verdict used was told from
    a list joined by commas, so that name was a term and was counted for nobody."""
    classifier = Classifier.load(extra_terms=("IL1,2", "1,3-BDG"))
    for text in ("Then IL~1,2~ rose.", "Then 1,3-BDG rose."):
        [atom] = find_atoms(text, mask(text))
        verdict = classifier.classify(atom)
        assert verdict.kind == "term", text
        assert classifier.is_project_exemption(verdict), text


# ------------------------------------------------------------------------------------- units

#: An exponent on a unit, or on the letter of a statistic: no number, as `m²` is none.
EXPONENTS = [
    "A body mass index in kg/m^2^, as usual.",
    "In (kg/m^2^).",
    "Cells per mm^3^ were counted.",
    "A rate in s^-1^ was fitted.",
    "Given in mg·kg^-1^·day^-1^.",
    "Per µL^-1^ of blood.",
    "In mol^-1^ and in mL^+1^.",
    "The fit was good (R^2^ and I^2^).",
    "A χ^2^ test was used.",
    "An area in m^2^.",
    # A statistic's letter in italics, as journals set it.
    "A fit of *R*^2^ and heterogeneity of *I*^2^.",
    "With _R_^2^ and **R**^2^ and *χ*^2^.",
    "With a minus sign of its own, s^−1^.",
]


@pytest.mark.parametrize("text", EXPONENTS)
def test_an_exponent_on_a_unit_is_no_number(text: str) -> None:
    assert atoms(text) == []


def test_it_is_read_as_the_superscript_character_is() -> None:
    assert atoms("In kg/m², as usual.") == atoms("In kg/m^2^, as usual.") == []


#: What is still a number: a power of ten, an exponent that is no single digit, one on a
#: word, one that is not closed, and the number beside the unit.
NUMBERS = {
    "a power of ten": ("A count of 10^6^ cells.", ["10^6^"]),
    "a power of ten with a sign": ("About 1.5 × 10^-3^ of them.", ["1.5", "10^-3^"]),
    "a number of two digits on a unit": ("An area of m^25^.", ["m^25^"]),
    "a number of three digits on a letter": ("Of n^412^ patients.", ["n^412^"]),
    "a citation's number typed after a word": ("As shown^2^ before.", ["shown^2^"]),
    "the same in two digits": ("As shown^12^ before.", ["shown^12^"]),
    "an exponent on a word of four letters": ("A rate in year^-1^.", ["year^-1^"]),
    "an exponent that is not closed": ("An area in m^2 was given.", ["m^2"]),
    "a digit and a sign in the wrong order": ("A charge of Ca^2+^.", ["Ca^2+^"]),
    "the number before the unit": ("Over 30 kg/m^2^ was an exclusion.", ["30"]),
    "a number hard against the unit": ("Over 30kg/m^2^ was an exclusion.", ["30kg/m^2^"]),
    "a value after the statistic": ("With R^2^=0.85 overall.", ["R^2^=0.85"]),
}


@pytest.mark.parametrize("case", list(NUMBERS))
def test_a_number_written_with_the_signs_is_still_one(case: str) -> None:
    text, found = NUMBERS[case]
    assert atoms(text) == found
    assert unbound(text) == found


def test_many_exponents_on_one_line_take_time_in_proportion(assert_linear) -> None:
    assert_linear(lambda n: "kg/m^2^ " * n, atoms, 2000, "exponents on units")
    assert_linear(lambda n: "m^2" * n + " 1", atoms, 2000, "carets that close nothing")


# ----------------------------------------------------------------------- through `check`


def checked(project: Path, capsys) -> tuple[int, list[dict]]:
    """`check --json`: its exit code and the findings of an unbound number."""
    capsys.readouterr()
    code = main(["check", str(project), "--json"])
    report = json.loads(capsys.readouterr().out)
    return code, [f for f in report["findings"] if f["code"] == "unclassified-number"]


def set_title(project: Path, title: str, *more: str) -> None:
    paper = project / "paper.yaml"
    lines = paper.read_bytes().decode("utf-8").split(N)
    [at] = [index for index, line in enumerate(lines) if line.startswith("title:")]
    lines[at] = "title: " + json.dumps(title)
    paper.write_bytes(N.join([*lines, *more]).encode("utf-8"))


def add_to_results(project: Path, sentence: str) -> None:
    source = project / "manuscript" / "main.md"
    text = source.read_bytes().decode("utf-8")
    held = "The database contained {{results.cohort.n_reports}} reports, of which"
    assert text.count(held) == 1
    source.write_bytes(text.replace(held, sentence + N + N + held).encode("utf-8"))


TITLE = "Hepatic injury, HbA~1c~ and end-tidal CO~2~ by body mass index in kg/m^2^"
SENTENCE = (
    "Neither HbA~1c~ nor PaCO~2~ was reported, nor end-tidal CO~2~, nor a body mass index "
    "in kg/m^2^."
)


def test_the_example_with_such_names_in_its_title_and_its_text_passes_check(
    project: Path, capsys
) -> None:
    """`HbA1c` and `PaCO2` are built in, `CO2` is declared, and `m^2^` is `m²`."""
    paper = project / "paper.yaml"
    written = paper.read_bytes().decode("utf-8")
    assert written.count(N + "terms:" + N) == 1
    declared = written.replace(N + "terms:" + N, N + "terms:" + N + "  - CO2" + N)
    paper.write_bytes(declared.encode("utf-8"))
    set_title(project, TITLE)
    add_to_results(project, SENTENCE)

    code, loose = checked(project, capsys)

    assert loose == []
    assert code == 0


def test_an_undeclared_name_is_reported_and_the_hint_says_how_to_declare_it(
    project: Path, capsys
) -> None:
    set_title(project, TITLE)
    add_to_results(project, SENTENCE)

    code, loose = checked(project, capsys)

    assert code == 1
    in_text, in_title = sorted(loose, key=lambda finding: finding["path"])
    assert in_text["message"] == "'CO~2' is not bound to any source"
    assert Path(in_text["path"]).name == "main.md"
    assert in_title["message"] == "'CO~2' in paper.yaml `title` is not bound to any source"
    for finding in (in_text, in_title):
        assert "`terms: [CO2]`" in finding["hint"], finding["hint"]
        assert "without its subscript and superscript signs" in finding["hint"]


#: A sentence with one unbound atom, and the name its hint says to declare; None where the
#: hint says nothing of terms. That is a count, a name with no sign in it, which is
#: declared as it is written, and an atom with a number beside its name or after a sign
#: nothing closes: told how to declare it, an author would have exempted the number.
DECLARED_AS = {
    "End-tidal CO~2~ was recorded.": "`terms: [CO2]`",
    "Nitrous oxide, N~2~O, was given.": "`terms: [N2O]`",
    "A half-life t~1/2~ was estimated.": "`terms: [t1/2]`",
    "A level of Ca^2+^ was measured.": "`terms: [Ca2+]`",
    "Then IL~1,2~ rose.": '`terms: ["IL1,2"]`',
    "A ratio A~1:2~ was used.": '`terms: ["A1:2"]`',
    "There were 412~patients~ in all.": None,
    "There were ^412^ patients.": None,
    "A dose of 5~mg~ was given.": None,
    "A tracer, SF6, was used.": None,
    "A count of 10^6^ cells.": None,
    "With R^2^=0.85 overall.": None,
    "An HbA~1c~7.2 reading.": None,
    "Of n~412 patients.": None,
    "As shown^12^ before.": None,
    "A rate in year^-1^.": None,
    "Dissolution at pH~2 was tested.": None,
}


@pytest.mark.parametrize("sentence", list(DECLARED_AS))
def test_how_a_name_with_the_signs_is_told_to_be_declared(sentence: str) -> None:
    from manuscript_guard.gates.numbers import _how_to_declare

    [atom] = find_atoms(sentence, mask(sentence))
    said = _how_to_declare(atom)
    name = DECLARED_AS[sentence]
    if name is None:
        assert said == ""
    else:
        assert name in said
        assert said.endswith("; otherwise ")


def test_the_hint_of_a_duration_is_still_the_one_about_a_design_parameter() -> None:
    """`week~12` beside "follow-up" was told how to declare a term, where it had been told
    that a follow-up window is a design parameter."""
    from manuscript_guard.gates.numbers import _hint_for

    sentence = "A follow-up of week~12 was planned."
    [atom] = find_atoms(sentence, mask(sentence))

    assert "design parameter" in _hint_for(atom)
    assert "terms:" not in _hint_for(atom)


def test_a_string_value_with_a_number_after_a_tilde_is_still_refused() -> None:
    """The emitter judges a string value with the same classifier."""
    from manuscript_guard.contracts.values import DisplayError, check_string_value

    with pytest.raises(DisplayError):
        check_string_value("buffer", "a buffer at pH~2", label=False)


def test_a_number_after_a_tilde_is_reported_by_check(project: Path, capsys) -> None:
    """`The study could detect an effect of about HR~2, and dissolution was tested at
    pH~2.` passed `check` and the build with the first version of this change, and the
    document printed both."""
    add_to_results(
        project,
        "The study could detect an effect of about HR~2, and dissolution was tested at pH~2.",
    )

    code, loose = checked(project, capsys)

    assert code == 1
    assert [finding["message"].split()[0] for finding in loose] == ["'HR~2'", "'pH~2'"]


def test_the_hint_for_a_number_with_the_signs_says_nothing_of_terms(
    project: Path, capsys
) -> None:
    """`412~patients~` is no name: told to declare it, an author would have exempted a
    count."""
    add_to_results(project, "There were 412~patients~ in all, and ^412^ again.")

    _code, loose = checked(project, capsys)

    assert [finding["message"].split()[0] for finding in loose] == ["'412~patients'", "'^412^'"]
    assert all("terms:" not in finding["hint"] for finding in loose)
