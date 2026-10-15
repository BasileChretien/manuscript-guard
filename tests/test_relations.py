"""Declared arithmetic between results, and flows: the emitter refuses what it can, and G8
holds the results on disk to the rest."""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.contracts import load_results
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import Value
from manuscript_guard.emit import Emitter
from manuscript_guard.findings import FAIL, WARN
from manuscript_guard.gates import check_relations


def _value(key: str, value: object, display: str, unit: str | None = None) -> Value:
    return Value(key=key, value=value, display=display, origin="test", unit=unit)


VALUES = {
    v.key: v
    for v in (
        _value("risk.treated", 2.36, "2.4"),
        _value("risk.control", 1.14, "1.1"),
        _value("risk.difference", 1.22, "1.2"),
        _value("risk.difference_wide", 1.2, "1.20"),
        _value("cohort.n", 1000, "1,000"),
        _value("cohort.n_men", 480, "480"),
        _value("cohort.n_women", 520, "520"),
        _value("cohort.n_women_short", 519, "519"),
        _value("events.n", 12, "12"),
        _value("person_years", 3456.7, "3,456.7"),
        _value("rate.per_1000", 12 / 3456.7 * 1000, "3.5"),
        _value("share.a", 1 / 3, "33.3%"),
        _value("share.b", 1 / 3, "33.3%"),
        _value("share.c", 1 / 3, "33.3%"),
        _value("share.all", 1.0, "100.0%"),
        _value("period.start", "2015-01-01", "1 January 2015"),
        _value("period.end", "2024-12-31", "31 December 2024"),
        _value("p.value", 0.0003, "<0.001"),
        _value("label", "hepatic injury", "hepatic injury"),
    )
}


def _check(*relations: dict, flows: dict | None = None, values: dict | None = None):
    results = Results({**VALUES, **(values or {})}, (), relations=relations, flows=flows or {})
    return check_relations(results)


def _codes(report) -> list[tuple[str, str]]:
    return [(f.code, f.severity) for f in report.findings]


@pytest.mark.parametrize(
    "relation",
    [
        {"kind": "sum", "key": "cohort.n", "of": ["cohort.n_men", "cohort.n_women"]},
        {"kind": "ratio", "key": "rate.per_1000", "of": ["events.n", "person_years"],
         "scale": 1000},
        {"kind": "at_most", "key": "cohort.n_men", "of": ["cohort.n"]},
        {"kind": "in_order", "key": "period.start", "of": ["period.end"]},
        {"kind": "difference", "key": "risk.difference_wide", "of": ["risk.treated",
                                                                    "risk.control"]},
    ],
)  # fmt: skip
def test_a_relation_the_values_hold_is_quiet(relation: dict) -> None:
    if relation["key"] == "risk.difference_wide":
        values = {"risk.treated": _value("risk.treated", 2.35, "2.35"),
                  "risk.control": _value("risk.control", 1.15, "1.15")}  # fmt: skip
        report = _check(relation, values=values)
    else:
        report = _check(relation)
    assert report.findings == (), report.findings
    assert report.counts == {"relations_checked": 1}


def test_a_sum_one_short_fails_exactly() -> None:
    """Counts are whole: 480 and 519 are not 1,000, and no tolerance makes them so."""
    report = _check({"kind": "sum", "key": "cohort.n",
                     "of": ["cohort.n_men", "cohort.n_women_short"]})  # fmt: skip
    assert _codes(report) == [("relation-broken", FAIL)]
    assert "999" in report.findings[0].message


def test_the_order_of_two_dates_and_two_numbers_is_held() -> None:
    late = {"period.start": _value("period.start", "2025-01-01", "1 January 2025")}
    report = _check({"kind": "in_order", "key": "period.start", "of": ["period.end"]},
                    values=late)  # fmt: skip
    assert _codes(report) == [("relation-broken", FAIL)]
    report = _check({"kind": "at_most", "key": "cohort.n", "of": ["cohort.n_men"]})
    assert _codes(report) == [("relation-broken", FAIL)]
    assert "more than" in report.findings[0].message


def test_printed_parts_that_do_not_give_the_printed_difference_warn() -> None:
    """2.36 less 1.14 is 1.22; printed, 2.4 less 1.1 is 1.3, and the text says 1.2."""
    report = _check({"kind": "difference", "key": "risk.difference",
                     "of": ["risk.treated", "risk.control"]})  # fmt: skip
    assert _codes(report) == [("relation-rounding", WARN)]
    assert "1.3" in report.findings[0].message


def test_shares_printed_as_percentages_that_miss_100_warn() -> None:
    report = _check({"kind": "sum", "key": "share.all", "of": ["share.a", "share.b",
                                                                "share.c"]})  # fmt: skip
    assert _codes(report) == [("relation-rounding", WARN)]


def test_a_rate_printed_to_its_last_place_is_within_its_rounding() -> None:
    """12 over 3,456.7 per 1,000 is 3.4715: printed 3.5, which is that number rounded."""
    report = _check({"kind": "ratio", "key": "rate.per_1000",
                     "of": ["events.n", "person_years"], "scale": 1000})  # fmt: skip
    assert report.findings == ()


def test_a_display_that_is_not_a_rounding_of_its_value_is_left_to_the_values() -> None:
    """"<0.001" is a bound, not a rounding: the printed arithmetic cannot be done with it."""
    small = {"risk.control": _value("risk.control", 0.0003, "<0.001"),
             "risk.treated": _value("risk.treated", 1.2203, "1.22"),
             "risk.difference": _value("risk.difference", 1.22, "1.22")}  # fmt: skip
    report = _check({"kind": "difference", "key": "risk.difference",
                     "of": ["risk.treated", "risk.control"]}, values=small)  # fmt: skip
    assert report.findings == ()


@pytest.mark.parametrize(
    ("relation", "said"),
    [
        ({"kind": "sum", "key": "cohort.n", "of": ["cohort.n_nobody"]}, "cohort.n_nobody"),
        ({"kind": "sum", "key": "cohort.n", "of": ["label"]}, "no number"),
        ({"kind": "in_order", "key": "period.start", "of": ["cohort.n"]}, "not both"),
        ({"kind": "at_most", "key": "period.start", "of": ["period.end"]}, "in_order"),
    ],
)
def test_a_relation_that_cannot_be_checked_fails(relation: dict, said: str) -> None:
    report = _check(relation)
    assert _codes(report) == [("relation-unresolved", FAIL)]
    assert said in report.findings[0].message


def test_a_ratio_over_zero_fails() -> None:
    zero = {"person_years": _value("person_years", 0.0, "0.0")}
    report = _check({"kind": "ratio", "key": "rate.per_1000",
                     "of": ["events.n", "person_years"], "scale": 1000}, values=zero)  # fmt: skip
    assert _codes(report) == [("relation-broken", FAIL)]


# ---------------------------------------------------------------- the emitter


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


def _emitter(scratch: Path) -> Emitter:
    return Emitter(scratch / "analysis" / "run.py", root=scratch)


CONSORT = {
    "stages": {"Assessed for eligibility": 412, "Randomised": 300},
    "exclusions": [{"Not meeting criteria": 87, "Declined": 25}],
    "arms": {"Drug": 151, "Placebo": 149},
}


def test_a_flow_is_written_as_bound_counts_and_g8_reads_it_back(scratch: Path) -> None:
    em = _emitter(scratch)
    em.flow("consort", **CONSORT)
    em.value("cohort.n", 300)
    em.relation("sum", "cohort.n", ["flow.consort.arm.1", "flow.consort.arm.2"])
    em.write()
    results, report = load_results(scratch / "results")
    assert report.ok, report.findings
    assert results.values["flow.consort.stage.1"].value == 412
    assert results.values["flow.consort.excluded.1.2"].display == "25"
    assert results.values["flow.consort.arm.2"].value == 149
    flow = results.flows["consort"]
    assert [s["label"] for s in flow["stages"]] == ["Assessed for eligibility", "Randomised"]
    assert flow["exclusions"][0][1] == {"reason": "Declined", "key": "flow.consort.excluded.1.2"}
    assert flow["source"] == scratch / "results" / "run.json"
    assert check_relations(results).findings == ()


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({"stages": {"Assessed": 412, "Randomised": 301}}, "less its exclusions"),
        ({"arms": {"Drug": 151, "Placebo": 150}}, "the arms sum to 301"),
        ({"stages": {"Assessed": 300, "Randomised": 412}}, "larger than stage 1"),
        ({"exclusions": []}, "need 1 set(s) of exclusions"),
        ({"stages": {"Assessed": 412.0, "Randomised": 300}}, "whole number"),
        ({"stages": {"Assessed": True, "Randomised": 300}}, "whole number"),
    ],
)
def test_the_emitter_refuses_a_flow_whose_arithmetic_fails(
    scratch: Path, change: dict, refusal: str
) -> None:
    with pytest.raises(ValueError, match=refusal.replace("(", r"\(").replace(")", r"\)")):
        _emitter(scratch).flow("consort", **{**CONSORT, **change})


def test_overlapping_reasons_waive_their_sum_and_keep_the_total(scratch: Path) -> None:
    overlapping = {**CONSORT, "exclusions": [{"Not meeting criteria": 87, "Declined": 40}]}
    with pytest.raises(ValueError, match="less its exclusions"):
        _emitter(scratch).flow("consort", **overlapping)
    _emitter(scratch).flow("consort", **overlapping, overlapping=True)
    too_few = {**CONSORT, "exclusions": [{"Not meeting criteria": 60, "Declined": 40}]}
    with pytest.raises(ValueError, match="cannot account for the 112 excluded"):
        _emitter(scratch).flow("consort", **too_few, overlapping=True)
    one_too_many = {**CONSORT, "exclusions": [{"Not meeting criteria": 113}]}
    with pytest.raises(ValueError, match="cannot account"):
        _emitter(scratch).flow("consort", **one_too_many, overlapping=True)


@pytest.mark.parametrize(
    ("args", "kwargs", "refusal"),
    [
        (("mean", "a", ["b"]), {}, "the kinds are"),
        (("difference", "a", ["b"]), {}, "is of 2 key"),
        (("sum", "a", []), {}, "at least one key"),
        (("sum", "a", ["b"]), {"scale": 1000}, "only a ratio"),
        (("ratio", "a", ["b", "c"]), {"scale": 0}, "positive number"),
        (("ratio", "a", ["b", "c"]), {"scale": float("nan")}, "positive number"),
    ],
)
def test_the_emitter_refuses_a_relation_it_cannot_write(
    scratch: Path, args: tuple, kwargs: dict, refusal: str
) -> None:
    with pytest.raises(ValueError, match=refusal):
        _emitter(scratch).relation(*args, **kwargs)


def test_a_relation_may_name_another_script_s_keys(scratch: Path) -> None:
    """G8 reads every fragment together, so the total and its parts can be two scripts'."""
    (scratch / "analysis" / "other.py").write_text("# other\n", encoding="utf-8")
    first = _emitter(scratch)
    first.value("cohort.n_men", 480)
    first.value("cohort.n_women", 519)
    first.write()
    second = Emitter(scratch / "analysis" / "other.py", root=scratch)
    second.value("cohort.n", 1000)
    second.relation("sum", "cohort.n", ["cohort.n_men", "cohort.n_women"])
    second.write()
    results, report = load_results(scratch / "results")
    assert report.ok, report.findings
    findings = check_relations(results).findings
    assert [f.code for f in findings] == ["relation-broken"]
    assert findings[0].path == scratch / "results" / "other.json"


def test_a_flow_edited_on_disk_is_caught(scratch: Path) -> None:
    """The emitter refuses a broken flow; a fragment edited and re-signed is G8's."""
    import json

    from manuscript_guard.emit import write_digest

    em = _emitter(scratch)
    em.flow("consort", **CONSORT)
    em.write()
    fragment = scratch / "results" / "run.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["flow.consort.arm.1"].update(value=152, display="152")
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    results, _report = load_results(scratch / "results")
    findings = check_relations(results).findings
    assert [(f.code, f.severity) for f in findings] == [("flow-broken", FAIL)]
    assert "the arms sum to 301" in findings[0].message
    del document["flows"]["consort"]["exclusions"][0]
    document["values"]["flow.consort.arm.1"].update(value=151, display="151")
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    results, _report = load_results(scratch / "results")
    assert "where each step has one" in check_relations(results).findings[0].message
