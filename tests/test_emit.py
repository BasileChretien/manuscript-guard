"""The emitter, which is the one channel a number may enter the manuscript through.

It had no direct tests, and an adversarial review found what that cost: `display` was
returned verbatim with no relation to its value, and table cells were `str()`-ed and
compared to nothing. "Formatting is fixed where the number is computed" and "tables are
emitted, not written" were both satisfied by *calling* the emitter, while the numbers were
still typed by hand.

Every test here names the escape it closes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuscript_guard.contracts.values import DisplayError
from manuscript_guard.emit import Emitter, read_digest, sha256_of


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    (root / "analysis").mkdir(parents=True)
    (root / "results").mkdir()
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "T"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    (root / "analysis" / "run.py").write_text("# analysis\n", encoding="utf-8")
    return root


def emitter(scratch: Path) -> Emitter:
    return Emitter(scratch / "analysis" / "run.py", root=scratch)


# ---------------------------------------------------------------- display


def test_a_float_must_say_how_it_rounds(scratch: Path) -> None:
    with pytest.raises(DisplayError, match="rounds it identically"):
        emitter(scratch).value("ror", 3.4211)


@pytest.mark.parametrize(
    "display",
    [
        # The attack: one call publishing a fabricated estimate and a fabricated interval.
        "3.84 (95% CI 2.10 to 7.02)",
        "3.84",
        "9.99",
        "1.0",
    ],
)
def test_a_display_must_be_a_rendering_of_its_own_value(scratch: Path, display: str) -> None:
    """The check is on the number, not on prose style.

    A trailing unit is allowed and may be wordy — "per patient-year" is a real unit — so
    what disqualifies a display is the value it reads as, or a second number in it. That is
    enough: an interval and a wrong estimate are both refused, and no legitimate unit is.
    """
    with pytest.raises(DisplayError):
        emitter(scratch).value("ror", 0.9487, display=display)


@pytest.mark.parametrize(
    ("value", "display"),
    [
        (0.9487, "0.95"),
        (3.4211, "3.42"),
        (41200, "41,200"),
        (41200, "41 200"),
        (12.4, "12.4%"),
        (-3.2, "-3.2"),
        (0.0000312, "3.12e-5"),
        ("2015-2024", "2015-2024"),  # a label is its own display
    ],
)
def test_an_honest_display_is_accepted(scratch: Path, value: object, display: str) -> None:
    em = emitter(scratch)
    em.value("k", value, display=display)
    assert em.document()["values"]["k"]["display"] == display


@pytest.mark.parametrize(
    ("value", "display"),
    [(0.0000004, "<0.001"), (0.0000004, "< 0.001"), (1200, ">1000"), (0.04, "≤0.05")],
)
def test_a_comparator_display_is_accepted_when_the_value_is_on_that_side(
    scratch: Path, value: float, display: str
) -> None:
    """A rounded p-value is written "<0.001", and that is the honest rendering of a number
    too small to state. Needed once thresholds stopped being conventions outside Methods:
    a reported p-value must be bound, so it must be emittable."""
    em = emitter(scratch)
    em.value("p", value, display=display)
    assert em.document()["values"]["p"]["display"] == display


@pytest.mark.parametrize(("value", "display"), [(0.4, "<0.001"), (900, ">1000")])
def test_a_comparator_display_is_refused_when_it_is_untrue(
    scratch: Path, value: float, display: str
) -> None:
    with pytest.raises(DisplayError):
        emitter(scratch).value("p", value, display=display)


@pytest.mark.parametrize(
    "value", ["12.34 (95% CI 8.00 to 19.00)", "9999", "ROR 5.12", "42 cases"]
)
def test_a_string_value_may_not_smuggle_a_number(scratch: Path, value: str) -> None:
    """A string value is its own display, and nothing looked inside it.

    So the hole closed on the `display=` route stayed open one line away: one call published
    a fabricated estimate and a fabricated interval, quoted through an ordinary binding,
    with every gate green. `_cell` already refused a numeric string in a table for exactly
    this reason; `value()` did not.
    """
    with pytest.raises(DisplayError, match="no gate can trace"):
        emitter(scratch).value("ror.headline", value)


@pytest.mark.parametrize("value", ["2015-2024", "2019", "CYP2C19", "Cohort A", "no events"])
def test_a_genuine_label_still_passes(scratch: Path, value: str) -> None:
    """Periods, years and names carry digits and are not measurements.

    Accepted without a flag, because making every study period declare itself would teach
    authors to set the flag everywhere, which is the same as not having it.
    """
    em = emitter(scratch)
    em.value("k", value)
    assert em.document()["values"]["k"]["display"] == value


def test_label_is_the_deliberate_escape(scratch: Path) -> None:
    em = emitter(scratch)
    em.value("k", "12.34 (95% CI 8.00 to 19.00)", label=True)
    assert em.document()["values"]["k"]["label"] is True


# ---------------------------------------------------------------- table furniture


def test_a_caption_is_checked_like_a_cell(scratch: Path) -> None:
    """Captions and column headers render with the table and were checked by nothing."""
    em = emitter(scratch)
    em.table(
        "t",
        ["Group", "n"],
        [["Exposed", 77]],
        caption="Underlying the reporting odds ratio of 12.34 (95% CI 8.00 to 19.00).",
    )
    with pytest.raises(DisplayError, match="caption"):
        em.document()


def test_a_column_header_is_checked_like_a_cell(scratch: Path) -> None:
    em = emitter(scratch)
    em.table("t", ["Group", "Hepatic injury (n = 9999)"], [["Exposed", 77]])
    with pytest.raises(DisplayError, match="column 1 header"):
        em.document()


def test_a_caption_built_from_emitted_values_passes(scratch: Path) -> None:
    em = emitter(scratch)
    em.value("ror.point", 3.8439, digits=2)
    em.table("t", ["Group", "n"], [["Exposed", 77]], caption="Reporting odds ratio 3.84.")
    assert em.document()["tables"]["t"]["caption"] == "Reporting odds ratio 3.84."


def test_a_p_value_typed_into_a_cell_is_not_a_threshold(scratch: Path) -> None:
    """Cells were classified with no section, so every methods_only rule applied —
    in the one place a *reported* p-value is most likely to be written."""
    em = emitter(scratch)
    em.table("t", ["Outcome", "p"], [["Hepatic", "p < 0.001"]])
    with pytest.raises(DisplayError, match="not a value this analysis emitted"):
        em.document()


# ---------------------------------------------------------------- same_as


def test_two_keys_declared_the_same_must_agree(scratch: Path) -> None:
    """G8 notices two keys while they still hold the same number, and goes quiet the moment
    they diverge — which is when it matters. Nothing recorded that they were meant to agree.
    """
    from manuscript_guard.contracts import load_results
    from manuscript_guard.gates import check_consistency

    em = emitter(scratch)
    em.value("ror.point", 0.9487, digits=2)
    em.value("ror.abstract", 3.8439, digits=2, same_as="ror.point")
    em.write()

    results, _report = load_results(scratch / "results")
    codes = {f.code for f in check_consistency(results).failures}
    assert "declared-same-but-differs" in codes


def test_two_keys_declared_the_same_and_agreeing_pass(scratch: Path) -> None:
    from manuscript_guard.contracts import load_results
    from manuscript_guard.gates import check_consistency

    em = emitter(scratch)
    em.value("ror.point", 3.8439, digits=2)
    em.value("ror.abstract", 3.8439, digits=2, same_as="ror.point")
    em.write()

    results, _report = load_results(scratch / "results")
    assert check_consistency(results).ok


def test_a_declaration_pointing_at_nothing_is_reported(scratch: Path) -> None:
    """A declaration that resolves to no key checks nothing, and looks like it checks."""
    from manuscript_guard.contracts import load_results
    from manuscript_guard.gates import check_consistency

    em = emitter(scratch)
    em.value("ror.abstract", 3.8439, digits=2, same_as="ror.typo")
    em.write()

    results, _report = load_results(scratch / "results")
    codes = {f.code for f in check_consistency(results).failures}
    assert "same-as-unresolved" in codes


def test_a_key_cannot_declare_itself(scratch: Path) -> None:
    with pytest.raises(ValueError, match="same_as itself"):
        emitter(scratch).value("ror.point", 1.0, digits=2, same_as="ror.point")


# ---------------------------------------------------------------- tables


def test_a_number_typed_into_a_cell_is_refused(scratch: Path) -> None:
    """`str(a)` in an analysis script and a hand-typed "9999" are the same thing here."""
    em = emitter(scratch)
    with pytest.raises(DisplayError, match="number written as text"):
        em.table("t", ["Group", "n"], [["Exposed", "9999"]])


def test_a_number_passed_as_a_number_is_formatted_here(scratch: Path) -> None:
    em = emitter(scratch)
    em.table("t", ["Group", "n", "%"], [["Exposed", 2018, 12.4]], digits={2: 1})
    assert em.document()["tables"]["t"]["rows"] == [["Exposed", "2018", "12.4"]]


def test_a_float_cell_must_say_how_it_rounds(scratch: Path) -> None:
    em = emitter(scratch)
    with pytest.raises(DisplayError, match="digits"):
        em.table("t", ["Group", "%"], [["Exposed", 12.4]])


def test_text_cells_are_untouched(scratch: Path) -> None:
    em = emitter(scratch)
    em.table("t", ["Characteristic", "Value"], [["Age 18-44", "n/a"], ["Grade 3", "Serious"]])
    assert em.document()["tables"]["t"]["rows"][0] == ["Age 18-44", "n/a"]


def test_a_label_containing_digits_is_not_a_claim(scratch: Path) -> None:
    """The classifier decides, exactly as it does for prose.

    "Age 18-44" and "Grade 3" are labels in a table for the same reason they are labels in
    a sentence. A rule that made an author emit `18` as a result would be answered by not
    using tables.
    """
    em = emitter(scratch)
    em.table("t", ["Characteristic", "n"], [["Age 18-44", 12], ["Grade 3", 4]])
    assert em.document()["tables"]["t"]["rows"][0][0] == "Age 18-44"


def test_a_cell_with_a_number_this_analysis_never_emitted_is_refused(scratch: Path) -> None:
    """Caught at `table()` for a bare numeral, at `document()` for one inside a phrase."""
    em = emitter(scratch)
    em.value("ror", 3.8439, digits=2)
    em.table("t", ["Outcome", "ROR"], [["Hepatic", "about 9.99"]])
    with pytest.raises(DisplayError, match="not a value this analysis emitted"):
        em.document()


def test_several_typed_numbers_in_one_cell_are_refused_even_when_all_are_emitted(
    scratch: Path,
) -> None:
    """Set membership says each number came from the analysis, not which is which.

    So `ROR 5.12 (95% CI 3.84 to 2.89)` passed with the point estimate and both bounds
    transposed — every one of them a real emitted value, in the wrong place. That is exactly
    the coincidental-match weakness this design claims not to have.
    """
    em = emitter(scratch)
    em.value("ror.point", 5.12, digits=2)
    em.value("ror.low", 3.84, digits=2)
    em.value("ror.high", 2.89, digits=2)
    em.table("t", ["Outcome", "ROR (95% CI)"], [["Hepatic", "ROR 5.12 (95% CI 3.84 to 2.89)"]])
    with pytest.raises(DisplayError, match="typed rather than composed"):
        em.document()


def test_a_composed_cell_does_not_excuse_a_copy_of_itself(scratch: Path) -> None:
    """`_composed` was a set of rendered *text*, shared across the whole emitter.

    So a stale copy-paste of group A's interval into group B's row passed the
    anti-transposition rule — identical characters, and group B's own values never used.
    Keyed by position now, which is the only thing that distinguishes the cell the emitter
    built from a cell that merely looks like it.
    """
    em = emitter(scratch)
    for key, value in (
        ("a.point", 5.12),
        ("a.low", 3.84),
        ("a.high", 8.02),
        ("b.point", 2.01),
        ("b.low", 1.05),
        ("b.high", 3.60),
    ):
        em.value(key, value, digits=2)

    em.table(
        "t",
        ["Group", "ROR (95% CI)"],
        [
            ["A", em.cell("{} (95% CI {} to {})", (5.12, 2), (3.84, 2), (8.02, 2))],
            ["B", "5.12 (95% CI 3.84 to 8.02)"],
        ],
    )
    with pytest.raises(DisplayError, match="typed rather than composed"):
        em.document()


def test_the_same_interval_composed_is_accepted(scratch: Path) -> None:
    """Identical characters; the difference is that the emitter placed each number."""
    em = emitter(scratch)
    em.value("ror.point", 3.8439, digits=2)
    em.value("ror.low", 2.1043, digits=2)
    em.value("ror.high", 7.0211, digits=2)
    em.table(
        "t",
        ["Outcome", "ROR (95% CI)"],
        [["Hepatic", em.cell("{} ({} to {})", (3.8439, 2), (2.1043, 2), (7.0211, 2))]],
    )
    assert em.document()["tables"]["t"]["rows"][0][1] == "3.84 (2.10 to 7.02)"


def test_one_emitted_number_in_a_cell_still_passes(scratch: Path) -> None:
    """A lone value has nowhere to be transposed to, so demanding em.cell() would be
    friction with nothing behind it."""
    em = emitter(scratch)
    em.value("n.cases", 77)
    em.table("t", ["Group", "n"], [["Exposed", 77]])
    assert em.document()["tables"]["t"]["rows"][0][1] == "77"


def test_a_composed_cell_is_formatted_by_the_emitter(scratch: Path) -> None:
    """An f-string and `em.cell()` produce the same characters, which is the whole problem.

    By the time `table()` sees a string it cannot tell a computed cell from a typed one, so
    the difference is made at the API: hand over the numbers, and the emitter rounds them.
    """
    em = emitter(scratch)
    em.table("t", ["Characteristic", "Exposed"], [["Female", em.cell("{} ({})", 77, (12.34, 1))]])
    assert em.document()["tables"]["t"]["rows"][0][1] == "77 (12.3)"


# ---------------------------------------------------------------- the fragment


def test_the_fragment_carries_a_digest_of_itself(scratch: Path) -> None:
    em = emitter(scratch)
    em.value("n", 4000)
    path = em.write()
    assert read_digest(path) == sha256_of(path)


def test_the_fragment_is_written_with_lf_on_every_platform(scratch: Path) -> None:
    em = emitter(scratch)
    em.value("n", 4000)
    assert b"\r\n" not in em.write().read_bytes()


def test_a_key_cannot_be_emitted_twice(scratch: Path) -> None:
    em = emitter(scratch)
    em.value("n", 4000)
    with pytest.raises(ValueError, match="emitted twice"):
        em.value("n", 4001)


def test_provenance_records_the_inputs_it_read(scratch: Path) -> None:
    data = scratch / "reports.csv"
    data.write_text("a,b\n1,2\n", encoding="utf-8")
    em = Emitter(scratch / "analysis" / "run.py", inputs=[data], root=scratch)
    em.value("n", 1)
    document = json.loads(em.write().read_text(encoding="utf-8"))
    inputs = document["provenance"]["inputs"]
    assert len(inputs) == 1
    assert inputs[0]["sha256"] == sha256_of(data)


# ------------------------------------------------- what an ordinary clinical table needs


def write(em: Emitter) -> None:
    em.write("results/probe.json")


def test_n_over_N_can_be_emitted(scratch: Path) -> None:
    """The commonest cell format in medicine, and it could not be written at all.

    `em.cell("{}/{}", 77, 412)` renders `77/412`, which the tokenizer reads as one atom -
    neither "77" nor "412" - so the composed cell was rejected as a number the analysis
    never produced. A cell the emitter composed is now checked on its template instead.
    """
    em = emitter(scratch)
    em.table("t", ["Group", "n/N"], [["Exposed", em.cell("{}/{}", 77, 412)]])
    write(em)


def test_a_p_value_too_small_to_state_goes_in_a_table(scratch: Path) -> None:
    em = emitter(scratch)
    em.table("t", ["Group", "p"], [["Exposed", em.cell("{}", (3.2e-7, "<0.001"))]])
    write(em)


def test_a_comparator_display_must_be_true_of_its_value(scratch: Path) -> None:
    """The display is checked against the number, so it cannot invent a significance."""
    em = emitter(scratch)
    with pytest.raises(DisplayError, match="below 0.001, but it is 0.4"):
        em.table("t", ["Group", "p"], [["Exposed", em.cell("{}", (0.4, "<0.001"))]])


def test_a_header_can_carry_a_computed_count(scratch: Path) -> None:
    """"Exposed (n = 412)" is where a group size is written, and headers were `list[str]`.

    The only way to put the count there was to type it, which the header check then refused
    - so an ordinary table header could not be written. Passing a `Composed` failed with
    "'Composed' object is not iterable" three frames away.
    """
    em = emitter(scratch)
    em.table("t", ["Group", em.cell("Exposed (n = {})", 412)], [["a", "b"]])
    write(em)


def test_a_typed_count_in_a_header_is_still_refused(scratch: Path) -> None:
    em = emitter(scratch)
    em.table("t", ["Group", "Exposed (n = 412)"], [["a", "b"]])
    with pytest.raises(DisplayError, match="'412' in 'Exposed"):
        write(em)


def test_a_count_typed_into_a_template_is_refused(scratch: Path) -> None:
    """The exemption covers what the emitter formatted, not what the script typed round it."""
    em = emitter(scratch)
    em.table("t", ["Group", "x"], [["Exposed", em.cell("{} (n = 412)", 77)]])
    with pytest.raises(DisplayError, match="'412'"):
        write(em)


def test_a_convention_in_a_template_is_allowed(scratch: Path) -> None:
    """"95% CI" is a conventional level, so the template that carries it passes."""
    em = emitter(scratch)
    em.table(
        "t",
        ["Group", "ROR"],
        [["Exposed", em.cell("{} (95% CI {} to {})", (3.84, 2), (2.10, 2), (7.02, 2))]],
    )
    write(em)


def test_a_transposed_interval_is_still_caught_in_a_typed_cell(scratch: Path) -> None:
    """The guarantee the composed-cell exemption must not weaken."""
    em = emitter(scratch)
    em.value("ror.point", 3.84, digits=2)
    em.value("ror.low", 2.10, digits=2)
    em.value("ror.high", 7.02, digits=2)
    em.table("t", ["Group", "ROR"], [["Exposed", "3.84 (7.02 to 2.10)"]])
    with pytest.raises(DisplayError, match="typed rather than composed"):
        write(em)


# ---------------------------------------------------------- RECORD 6.1 code lists


def test_a_code_list_table_can_be_emitted(scratch: Path) -> None:
    """RECORD 6.1 requires the code lists to be published, and this toolkit forbade it.

    A cell reading "10019663, 10019708" was refused as "a number written as text", and even
    one code per row the numeric codes would not classify: the system that names them is in
    the next column and the check reads one cell at a time. A reporting guideline the
    toolkit ships could not be complied with using the toolkit.
    """
    em = emitter(scratch)
    em.code_list(
        "outcome_codes",
        [
            {"concept": "Hepatic injury", "system": "ICD-10", "codes": ["K71.0", "K71.9"]},
            {"concept": "Hepatic injury", "system": "MedDRA PT", "codes": ["10019663"]},
        ],
        caption="Code lists used to identify the outcome (RECORD 6.1).",
    )
    document = em.document()
    assert document["tables"]["outcome_codes"]["rows"][0][2] == "K71.0, K71.9"
    assert document["code_lists"]["outcome_codes"][1]["codes"] == ["10019663"]
    write(em)


def test_a_code_list_keeps_the_codes_as_data(scratch: Path) -> None:
    """The rendered cell is for the reader; the list is for the next check and the next study."""
    em = emitter(scratch)
    em.code_list("c", [{"concept": "x", "system": "ICD-10", "codes": ["K71.0", "K71.1"]}])
    assert em.document()["code_lists"]["c"] == [
        {"concept": "x", "system": "ICD-10", "codes": ["K71.0", "K71.1"]}
    ]


def test_a_code_list_entry_must_be_complete(scratch: Path) -> None:
    em = emitter(scratch)
    with pytest.raises(DisplayError, match="missing codes"):
        em.code_list("c", [{"concept": "x", "system": "ICD-10"}])


def test_an_empty_code_list_is_refused(scratch: Path) -> None:
    """A concept that matched nothing is a finding, not a formatting choice."""
    em = emitter(scratch)
    with pytest.raises(DisplayError, match="no codes"):
        em.code_list("c", [{"concept": "x", "system": "ICD-10", "codes": []}])


def test_a_typed_numeric_code_list_is_still_refused(scratch: Path) -> None:
    """The exemption belongs to the emitter's own join, not to any string of codes.

    Only numeric codes are caught this way. A typed list of ICD-10 codes passes, because
    `K71.0` classifies as an identifier wherever it appears and nothing that begins with a
    letter is a measurement — `code_list()` earns its place by keeping the list as data the
    analysis can select on, not by being the only way to print one.
    """
    em = emitter(scratch)
    with pytest.raises(DisplayError, match="number written as text"):
        em.table("c", ["Concept", "System", "Codes"], [["x", "MedDRA", "10019663 10019708"]])


def test_an_interval_publishes_three_keys_with_their_roles(scratch: Path) -> None:
    em = emitter(scratch)
    em.interval("ror", 3.8439, 2.1032, 7.0210, digits=2)
    values = em.document()["values"]
    assert values["ror.point"]["display"] == "3.84"
    assert values["ror.ci_low"]["bounds"] == "ror.point"
    assert values["ror.ci_low"]["bound"] == "low"
    assert values["ror.ci_high"]["bound"] == "high"


def test_an_interval_must_bracket_its_estimate(scratch: Path) -> None:
    with pytest.raises(DisplayError, match="does not bracket"):
        emitter(scratch).interval("ror", 3.84, 7.02, 2.10, digits=2)


def test_a_code_list_cell_must_match_its_published_list(scratch: Path) -> None:
    """The abuse of the code-list exemption, which had no test until the inventory asked.

    A code-list cell is exempt from the emitted-value check because it is a join of the
    codes published beside it. Nothing about that is self-evident from the cell, so the
    fragment is what it is checked against - and a cell claiming to be a code list while
    saying something else must be refused.
    """
    import copy

    em = emitter(scratch)
    em.code_list("codes", [{"concept": "x", "system": "ICD-10", "codes": ["K71.0"]}])
    document = em.document()
    published = copy.deepcopy(document["code_lists"])
    # The emitter's own output, then the claim falsified: the cell says something the
    # published list does not.
    document["tables"]["codes"]["rows"][0][2] = "K71.0, and 4281003.55 besides"

    from manuscript_guard.classify import Classifier
    from manuscript_guard.tables import problems_in

    problems = problems_in(
        "codes",
        document["tables"]["codes"],
        set(),
        Classifier.load(),
        document.get("code_lists"),
    )
    assert any(p.code == "code-list-does-not-match" for p in problems), [p.code for p in problems]
    # Checking must not rewrite what it is checking against: a validator that cleared the
    # published codes would make every later cell agree with an empty list.
    assert document["code_lists"] == published
