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


def test_terms_all_near_nought_are_not_equal_by_being_small() -> None:
    """Round 1 of #293: the tolerance was absolute, so 1e-12 passed as the sum of 1e-12 and
    2e-12. It is relative to the largest number in the relation, which still lets a
    difference near nought be as near as its terms allow."""
    tiny = {"t.a": _value("t.a", 1e-12, "0"), "t.b": _value("t.b", 2e-12, "0"),
            "t.sum": _value("t.sum", 1e-12, "0")}  # fmt: skip
    report = _check({"kind": "sum", "key": "t.sum", "of": ["t.a", "t.b"]}, values=tiny)
    assert _codes(report) == [("relation-broken", FAIL)]
    cancel = {"t.a": _value("t.a", 0.3, "0.3"), "t.b": _value("t.b", 0.1 + 0.2, "0.3"),
              "t.diff": _value("t.diff", 0.0, "0.0")}  # fmt: skip
    report = _check({"kind": "difference", "key": "t.diff", "of": ["t.a", "t.b"]}, values=cancel)
    assert report.findings == ()


def test_a_ratio_is_held_to_its_result_not_to_its_denominator() -> None:
    """Round 1 of #340: a tolerance of 1e-9 of the largest number made 2e-3 of a
    denominator of 2,000,000, and a rate of 0.0007 passed for 700 over it, which is
    0.00035."""
    rate = {"r.rate": _value("r.rate", 0.0007, "0.0007"),
            "r.events": _value("r.events", 700, "700"),
            "r.py": _value("r.py", 2_000_000, "2,000,000")}  # fmt: skip
    report = _check({"kind": "ratio", "key": "r.rate", "of": ["r.events", "r.py"]}, values=rate)
    assert ("relation-broken", FAIL) in _codes(report)
    rate["r.rate"] = _value("r.rate", 700 / 2_000_000, "0.00035")
    report = _check({"kind": "ratio", "key": "r.rate", "of": ["r.events", "r.py"]}, values=rate)
    assert report.findings == ()


def test_a_bound_is_no_rounding_even_within_half_a_unit() -> None:
    """Round 1 of #293: "<0.001" over 0.0009 was read as 0.001 rounded, and the printed
    arithmetic warned."""
    near = {"risk.control": _value("risk.control", 0.0009, "<0.001"),
            "risk.treated": _value("risk.treated", 0.5009, "0.5009"),
            "risk.difference": _value("risk.difference", 0.5, "0.5000")}  # fmt: skip
    report = _check({"kind": "difference", "key": "risk.difference",
                     "of": ["risk.treated", "risk.control"]}, values=near)  # fmt: skip
    assert report.findings == ()


def test_the_last_digits_of_decimal_arithmetic_are_no_rounding() -> None:
    """Round 1 of #293: 100 over 3, times 3, is 99.99...9 to 28 digits, and a whole 100
    printed as itself was warned of."""
    whole = {"w.key": _value("w.key", 100, "100"), "w.a": _value("w.a", 100, "100"),
             "w.b": _value("w.b", 3, "3")}  # fmt: skip
    report = _check({"kind": "ratio", "key": "w.key", "of": ["w.a", "w.b"], "scale": 3},
                    values=whole)  # fmt: skip
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
        # Round 1 of #293: one key as a string was read as its letters, and a key that is
        # no results key was refused only at `write`.
        (("at_most", "a", "cohort.n"), {}, r"a list of keys, \['cohort.n'\] for one"),
        (("sum", "a", ["Cohort N"]), {}, "'Cohort N' is no results key"),
        (("sum", "a b", ["b"]), {}, "'a b' is no results key"),
    ],
)
def test_the_emitter_refuses_a_relation_it_cannot_write(
    scratch: Path, args: tuple, kwargs: dict, refusal: str
) -> None:
    with pytest.raises(ValueError, match=refusal):
        _emitter(scratch).relation(*args, **kwargs)


PRISMA = {
    "stages": {"Records": 1200, "Screened": 1000, "Sought": 300, "Assessed": 250},
    "exclusions": [{"Duplicates": 150, "Automation": 80}, {"Excluded": 700},
                   {"Not retrieved": 50}],
}  # fmt: skip


def test_overlap_named_for_one_step_leaves_the_others_exact(scratch: Path) -> None:
    """Round 1 of #293: one flag waived every step, so the first step's reasons, 230 for
    the 200 removed before screening, passed because the reports step overlapped."""
    with pytest.raises(ValueError, match="stage 1 .1200. less its exclusions .230."):
        _emitter(scratch).flow("prisma", **PRISMA, overlapping=[3])
    _emitter(scratch).flow("prisma", **PRISMA, overlapping=[1])
    em = _emitter(scratch)
    em.flow("prisma", **PRISMA, overlapping=(1, 1))
    assert em._flows["prisma"]["overlapping"] == [1]


@pytest.mark.parametrize("overlapping", [[0], [4], ["1"], [True], [], 1, "yes"])
def test_an_overlap_that_names_no_step_is_refused(scratch: Path, overlapping: object) -> None:
    with pytest.raises(ValueError, match="numbers of the steps whose reasons overlap, from 1 to 3"):
        _emitter(scratch).flow("prisma", **PRISMA, overlapping=overlapping)


def test_numpy_s_whole_numbers_and_truth_values_are_taken(scratch: Path) -> None:
    """Round 2 of #293: a count or a step number from NumPy, and NumPy's True, were
    refused, where R takes any whole numeric; they are written as Python's."""
    numpy = pytest.importorskip("numpy")
    em = _emitter(scratch)
    counts = {"stages": {label: numpy.int64(n) for label, n in PRISMA["stages"].items()},
              "exclusions": [{reason: numpy.int64(n) for reason, n in step.items()}
                             for step in PRISMA["exclusions"]]}  # fmt: skip
    em.flow("prisma", **counts, overlapping=[numpy.int64(1)])
    em.flow("again", **counts, overlapping=numpy.True_)
    assert em._flows["prisma"]["overlapping"] == [1] and em._flows["again"]["overlapping"] is True
    em.write()
    results, report = load_results(scratch / "results")
    assert report.ok, report.findings
    assert type(results.values["flow.prisma.stage.1"].value) is int
    # An array of step numbers is taken, as R takes c(1, 3); an array of truth values is
    # no truth value, and is refused with the emitter's words (round 1 of #340).
    em.flow("steps", **counts, overlapping=numpy.array([1]))
    assert em._flows["steps"]["overlapping"] == [1]
    for given in (numpy.array([True, False]), numpy.array([True])):
        with pytest.raises(ValueError, match="overlapping is True, False"):
            em.flow("refused", **counts, overlapping=given)


def test_a_flow_two_fragments_record_is_the_first_s(scratch: Path) -> None:
    """Round 1 of #293: the second record was checked against the first's counts, which
    are the ones kept; `duplicate-key` says so of the second's."""
    (scratch / "analysis" / "other.py").write_text("# other\n", encoding="utf-8")
    first = _emitter(scratch)
    first.flow("consort", **CONSORT)
    first.write()
    second = Emitter(scratch / "analysis" / "other.py", root=scratch)
    second.flow("consort", stages={"A": 500, "B": 400, "C": 300},
                exclusions=[{"x": 100}, {"y": 100}])  # fmt: skip
    second.write()
    results, report = load_results(scratch / "results")
    assert "duplicate-key" in {f.code for f in report.findings}
    # The record kept is the one whose counts were kept, whichever fragment was read first.
    kept = "other.json" if results.values["flow.consort.stage.1"].value == 500 else "run.json"
    assert results.flows["consort"]["source"] == scratch / "results" / kept
    assert check_relations(results).findings == ()


def test_an_overlapping_step_with_no_reasons_accounts_for_nothing(scratch: Path) -> None:
    unexplained = {"stages": {"A": 412, "B": 300}, "exclusions": [{}]}
    with pytest.raises(ValueError, match="cannot account for the 112 excluded"):
        _emitter(scratch).flow("consort", **unexplained, overlapping=True)


def test_a_flow_on_disk_is_held_to_the_steps_it_names(scratch: Path) -> None:
    import json

    from manuscript_guard.emit import write_digest

    em = _emitter(scratch)
    em.flow("prisma", **PRISMA, overlapping=[1])
    em.write()
    fragment = scratch / "results" / "run.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    assert document["flows"]["prisma"]["overlapping"] == [1]
    document["flows"]["prisma"]["overlapping"] = [3]
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    results, report = load_results(scratch / "results")
    assert report.ok, report.findings
    assert [f.code for f in check_relations(results).findings] == ["flow-broken"]


@pytest.mark.parametrize(
    "relation",
    [
        {"kind": "difference", "key": "risk.difference", "of": ["risk.treated"]},
        {"kind": "ratio", "key": "rate.per_1000", "of": ["events.n"]},
        {"kind": "at_most", "key": "cohort.n_men", "of": ["cohort.n", "cohort.n_women"]},
    ],
)
def test_a_relation_with_the_wrong_number_of_keys_is_refused_not_a_crash(relation: dict) -> None:
    """Round 1 of #293: the schema let a difference of one key through, and the gate raised.
    The schema refuses it now; a gate given one anyway says so."""
    from manuscript_guard.contracts import validate

    report = _check(relation)
    assert _codes(report) == [("relation-unresolved", FAIL)]
    document = {"schema": "manuscript-guard/results/1", "values": {}, "relations": [relation]}
    assert not validate(document, "results", Path("r.json")).ok


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
