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


def test_a_typed_interval_in_a_cell_is_refused(scratch: Path) -> None:
    em = emitter(scratch)
    em.value("ror", 3.8439, digits=2)
    em.table("t", ["Outcome", "ROR (95% CI)"], [["Hepatic", "3.84 (2.10 to 7.02)"]])
    with pytest.raises(DisplayError, match="not a value this analysis emitted"):
        em.document()


def test_an_interval_composed_from_emitted_values_is_accepted(scratch: Path) -> None:
    """The cell stays a string; the numbers in it have to be numbers this analysis published."""
    em = emitter(scratch)
    em.value("ror.point", 3.8439, digits=2)
    em.value("ror.low", 2.1043, digits=2)
    em.value("ror.high", 7.0211, digits=2)
    em.table("t", ["Outcome", "ROR (95% CI)"], [["Hepatic", "3.84 (2.10 to 7.02)"]])
    assert em.document()["tables"]["t"]["rows"][0][1] == "3.84 (2.10 to 7.02)"


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
