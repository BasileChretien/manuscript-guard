"""A table's totals held to their counts, and a count held back that a total gives away.

`stats/margins.py` reads a table as lines, each a total and the counts it totals: `audit`
says a total its counts do not add up to and categories over their column's n, and G2 says
a count held back ("<5") that what the manuscript prints gives away by subtraction
(`count-recoverable`), as `deposit` does of the tables it carries.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.emit import write_digest
from manuscript_guard.findings import FAIL, WARN
from manuscript_guard.gates.custodian import check_recoverable, recoverable
from manuscript_guard.stats.margins import count_in, is_total, over_n, said, sums_off
from manuscript_guard.text.tables import markdown_tables


def table(text: str):
    [found] = markdown_tables(text.strip("\n"))
    return found


def off(text: str) -> list[str]:
    return [wrong for _line, wrong in sums_off(table(text))]


def given_away(text: str, minimum: int | None = 5) -> list[tuple[int, int, bool]]:
    return [(found.member.count.line, found.value, found.line.explicit)
            for found in recoverable(table(text), minimum)]  # fmt: skip


# ---------------------------------------------------------------------------- the reading


@pytest.mark.parametrize("label", ["Total", "TOTAL", "Overall", "All", "**Total**",
                                   "Total (n = 1,200)", "Total, n (%)", "Total^a^", "total:"])
def test_a_total_is_its_word_with_nothing_but_an_n_after_it(label: str) -> None:
    assert is_total(label)


@pytest.mark.parametrize("label", ["Total cholesterol, mmol/L", "Overall survival",
                                   "All-cause death", "All other drugs", "Totals",
                                   "Subtotal", "All patients"])
def test_a_label_that_starts_as_a_total_does_is_none(label: str) -> None:
    assert not is_total(label)


@pytest.mark.parametrize(("text", "low", "high", "held"), [
    ("1,200", 1200, 1200, False), ("<5", 0, 4, True), ("\N{LESS-THAN OR EQUAL TO}4", 0, 4, True),
    ("< 5 (<1.2)", 0, 4, True), ("<10", 0, 9, True), ("12 (30.0%)", 12, 12, False),
])  # fmt: skip
def test_a_count_is_a_whole_number_an_n_or_a_count_held_back(text, low, high, held) -> None:
    found = count_in(text)
    assert (found.low, found.high, found.held) == (low, high, held)


@pytest.mark.parametrize("text", ["<0.001", "12.5", "-", "\N{EM DASH}", "", "NA", "54 (12)"])
def test_a_p_a_decimal_a_dash_and_a_mean_are_no_count(text: str) -> None:
    # "54 (12)" is shaped like an n (%), and a count only where shares reads it as one.
    assert count_in(text, share=False) is None


# ------------------------------------------------------------------------------ sum-off


ROWS = """
| Characteristic | Cases | Controls |
|---|---|---|
| All reports | 4,000 | 3,000 |
| Sex | | |
| Men | 60 | 50 |
| Women | 40 | 47 |
| Total | 100 | 100 |
"""


def test_a_total_row_totals_its_run_and_a_column_off_is_said() -> None:
    """The row of all reports is above the characteristic's label, and no part of its
    total; the column of controls adds up to 97, and its total prints 100."""
    assert off(ROWS) == ["the 'Total' row, column 'Controls', prints 100, and the 2 rows "
                         "above it add up to 97"]  # fmt: skip


def test_a_total_column_totals_the_columns_since_the_labels() -> None:
    text = """
| | Cases | Controls | Total | P |
|---|---|---|---|---|
| Men | 60 | 50 | 110 | 0.04 |
| Women | 40 | 47 | 88 | 1 |
"""
    assert off(text) == ["the 'Total' column, row 'Women', prints 88, and the 2 cells before "
                         "it add up to 87"]  # fmt: skip


def test_a_line_with_a_dash_an_empty_cell_or_a_mean_in_it_is_not_read() -> None:
    text = """
| | Cases | Controls | Total |
|---|---|---|---|
| Men | \N{EM DASH} | 50 | 99 |
| Women | 40 | | 99 |
| Age, mean (SD) | 54 (12) | 55 (11) | 54 (12) |
| Total | 99 | 99 | 198 |
"""
    assert off(text) == []


def test_a_count_held_back_is_every_count_its_bound_allows() -> None:
    text = """
| | Cases | Controls |
|---|---|---|
| Sex | | |
| Men | <5 | 50 |
| Women | <5 | 47 |
| Total | 9 | 97 |
"""
    # Two held back are 8 at the most.
    assert off(text) == ["the 'Total' row, column 'Cases', prints 9, and the 2 rows above it "
                         "add up to 0 to 8"]  # fmt: skip


# --------------------------------------------------------------------------- the header n


def test_categories_over_their_columns_n_are_said_and_fewer_are_not() -> None:
    text = """
| | Cases (n = 120) | Controls (n = 100) |
|---|---|---|
| Region | | |
| North | 70 (50.0) | 40 (50.0) |
| South | 70 (50.0) | 40 (50.0) |
"""
    found = over_n(table(text))
    assert [(one.line, one.message) for one in found] == [
        (4, "the categories of 'Region' in column 'Cases (n = 120)' add up to 140, more than "
            "its n = 120, and their shares to 100")]  # fmt: skip


# ---------------------------------------------------------------------- given away


def test_a_count_held_back_beside_its_total_is_given_away() -> None:
    text = ROWS.replace("| 40 | 47 |", "| <5 | 47 |").replace("| 100 | 100 |", "| 63 | 97 |")
    assert given_away(text) == [(6, 3, True)]
    [found] = recoverable(table(text), 5)
    assert said(found) == ("<5 in row 'Women', column 'Cases' can only be 3: the 'Total' row, "
                           "column 'Cases', prints 63, and the other row above it leaves 3 "
                           "of it")  # fmt: skip


def test_two_held_back_in_a_line_with_room_between_them_are_not_given_away() -> None:
    text = ROWS.replace("| 60 | 50 |", "| <5 | 50 |").replace("| 40 | 47 |", "| <5 | 47 |")
    assert given_away(text.replace("| 100 | 100 |", "| 5 | 97 |")) == []
    # Unless the total leaves them one count each: 8 is 4 and 4.
    assert given_away(text.replace("| 100 | 100 |", "| 8 | 97 |")) == [(5, 4, True),
                                                                       (6, 4, True)]


def test_a_minimum_says_which_counts_given_away_are_forbidden() -> None:
    text = ROWS.replace("| 40 | 47 |", "| <10 | 47 |").replace("| 100 | 100 |", "| 67 | 97 |")
    assert given_away(text, 5) == []
    assert given_away(text, 10) == given_away(text, None) == [(6, 7, True)]
    # Nought is no small cell.
    assert given_away(text.replace("| 67 |", "| 60 |"), None) == []


def test_only_the_header_n_giving_it_away_is_not_explicit() -> None:
    text = """
| | Cases (n = 120) | Controls |
|---|---|---|
| Region | | |
| North | 60 | 40 |
| South | <5 | 40 |
| East | 57 | 40 |
"""
    assert given_away(text) == [(5, 3, False)]
    # A total row beside it is printed, and says it first.
    printed = text + "| Total | 120 | 120 |\n"
    assert given_away(printed) == [(5, 3, True)]


# --------------------------------------------------------------------------- G2 in check


def _custodian(root: Path, minimum: int) -> None:
    paper = root / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["custodian"] = {"minimum_cell_count": minimum}
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _edit(root: Path, change) -> None:
    fragment = root / "results" / "01_disproportionality.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    change(document)
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)


def _given_away(root: Path) -> list[tuple[str, str, str]]:
    project, _ = load_project(root)
    _, results, _, _ = load_namespace(project)
    return [(f.code, f.severity, f.message) for f in check_recoverable(project, results).findings]


def _total_row(document: dict) -> None:
    document["tables"]["two_by_two"]["rows"] = [
        ["example-drug", "<5", "349"], ["All other drugs", "194", "3380"],
        ["Total", "197", "3729"]]  # fmt: skip


def test_g2_says_a_count_a_bound_tables_total_gives_away(project: Path) -> None:
    _edit(project, _total_row)
    assert _given_away(project) == []  # no minimum declared
    _custodian(project, 5)
    assert _given_away(project) == [(
        "count-recoverable", FAIL, "table.two_by_two: <5 in row 'example-drug', column "
        "'Hepatic injury' can only be 3: the 'Total' row, column 'Hepatic injury', prints "
        "197, and the other row above it leaves 3 of it")]  # fmt: skip
    # A table the manuscript does not bind prints nothing.
    text = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    (project / "manuscript" / "main.md").write_text(text.replace("{{table.two_by_two}}", ""),
                                                    encoding="utf-8")  # fmt: skip
    assert _given_away(project) == []


def test_g2_only_warns_where_the_header_n_alone_gives_it_away(project: Path) -> None:
    def by_n(document: dict) -> None:
        document["tables"]["two_by_two"]["columns"] = ["", "Cases (n = 197)", "Controls"]
        document["tables"]["two_by_two"]["rows"] = [
            ["Sex", "", ""], ["Men", "<5", "349"], ["Women", "194", "3380"]]  # fmt: skip

    _custodian(project, 5)
    _edit(project, by_n)
    [(code, severity, message)] = _given_away(project)
    assert (code, severity) == ("count-recoverable", WARN)
    assert message.endswith("if every one of the column has one of the categories")


def _bind(root: Path, sentence: str) -> None:
    main = root / "manuscript" / "main.md"
    main.write_text(main.read_text(encoding="utf-8") + f"\n{sentence}\n", encoding="utf-8")


def test_g2_says_a_count_a_declared_sum_gives_away(project: Path) -> None:
    def summed(document: dict) -> None:
        document["values"]["cohort.n_men"] = {"value": 3, "display": "<5"}
        document["values"]["cohort.n_women"] = {"value": 423, "display": "423"}
        document["relations"].append({"kind": "sum", "key": "cohort.n_drug_reports",
                                      "of": ["cohort.n_men", "cohort.n_women"]})

    _custodian(project, 5)
    _edit(project, summed)
    assert _given_away(project) == []  # the men are bound nowhere
    _bind(project, "Men {{results.cohort.n_men}}, women {{results.cohort.n_women}}.")
    assert [(c, s) for c, s, _m in _given_away(project)] == [("count-recoverable", FAIL)]
    assert "<5 in results.cohort.n_men can only be 3" in _given_away(project)[0][2]


def test_g2_says_a_count_a_flows_step_gives_away_unless_its_reasons_overlap(
    project: Path,
) -> None:
    def flowed(overlapping: bool):
        def change(document: dict) -> None:
            for key, value, display in (("flow.f.stage.1", 50, "50"),
                                        ("flow.f.stage.2", 46, "46"),
                                        ("flow.f.excluded.1.1", 3, "<5"),
                                        ("flow.f.excluded.1.2", 1, "<5")):  # fmt: skip
                document["values"][key] = {"value": value, "display": display}
            document["flows"]["f"] = {
                "stages": [{"label": "Assessed", "key": "flow.f.stage.1"},
                           {"label": "Included", "key": "flow.f.stage.2"}],
                "exclusions": [[{"reason": "Declined", "key": "flow.f.excluded.1.1"},
                                {"reason": "Moved", "key": "flow.f.excluded.1.2"}]],
                "overlapping": overlapping}  # fmt: skip
        return change

    _custodian(project, 5)
    _bind(project, "Of {{results.flow.f.stage.1}}, {{results.flow.f.excluded.1.1}} declined "
          "and {{results.flow.f.excluded.1.2}} moved; {{results.flow.f.stage.2}} took part.")
    _edit(project, flowed(False))
    # Two held back, which 4 leaves as 3 and 1, or 2 and 2, or 1 and 3, or 4 and 0.
    assert _given_away(project) == []
    _edit(project, lambda document: document["values"]["flow.f.excluded.1.2"].update(
        display="1"))  # fmt: skip
    assert [(c, s) for c, s, _m in _given_away(project)] == [("count-recoverable", FAIL)]
    _edit(project, flowed(True))
    _edit(project, lambda document: document["values"]["flow.f.excluded.1.2"].update(
        display="1"))  # fmt: skip
    assert _given_away(project) == []
