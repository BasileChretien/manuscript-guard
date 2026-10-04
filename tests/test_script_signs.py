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


#: An unbound atom, and the name its hint says to declare; None where the hint says nothing
#: of terms: a count, and a name with no sign in it, which is declared as it is written.
DECLARED_AS = {
    "CO~2": "`terms: [CO2]`",
    "N~2~O": "`terms: [N2O]`",
    "t~1/2": "`terms: [t1/2]`",
    "Ca^2+^": "`terms: [Ca2+]`",
    "IL~1,2": '`terms: ["IL1,2"]`',
    "x~[2]": '`terms: ["x[2]"]`',
    "412~patients": None,
    "^412^": None,
    "5~mg": None,
    "SF6": None,
    "10^6^": None,
}


@pytest.mark.parametrize("atom", list(DECLARED_AS))
def test_how_a_name_with_the_signs_is_told_to_be_declared(atom: str) -> None:
    from manuscript_guard.gates.numbers import _how_to_declare

    said = _how_to_declare(atom)
    name = DECLARED_AS[atom]
    if name is None:
        assert said == ""
    else:
        assert name in said
        assert said.endswith("; otherwise ")


def test_the_hint_for_a_number_with_the_signs_says_nothing_of_terms(
    project: Path, capsys
) -> None:
    """`412~patients~` is no name: told to declare it, an author would have exempted a
    count."""
    add_to_results(project, "There were 412~patients~ in all, and ^412^ again.")

    _code, loose = checked(project, capsys)

    assert [finding["message"].split()[0] for finding in loose] == ["'412~patients'", "'^412^'"]
    assert all("terms:" not in finding["hint"] for finding in loose)
