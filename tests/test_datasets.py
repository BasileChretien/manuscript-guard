"""The data an analysis read, named by what identifies them: `dataset()` and what reads it.

Many databases have one version, or none a user can name, so what identifies the data a
paper analysed is the date they were extracted and the file. Each test names what it holds:
that the date is pinned to the file and cannot outlive it, that a date is printed as the
date it is, and that G1 and G2 read on disk what the emitter refuses as it runs.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.contracts.values import RESULTS, DisplayError, Value, check_string_value
from manuscript_guard.datasets import dataset_digest, declare
from manuscript_guard.dates import (
    Dated,
    as_dated,
    display_problem,
    parse_iso,
    read_written,
    written,
)
from manuscript_guard.emit import Emitter, input_digest, sha256_of, write_digest
from manuscript_guard.gates.data_dates import data_dates, dates_in_english, is_typed_date
from manuscript_guard.gates.datasets import check_datasets
from manuscript_guard.gates.freshness import check_freshness
from manuscript_guard.gates.numbers import in_sentences
from manuscript_guard.text.placeholders import parse

DATA = "id,received\n1,2023-01-05\n2,2023-12-30\n"


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    (root / "analysis").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "results").mkdir()
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "T"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    (root / "analysis" / "run.py").write_text("# analysis\n", encoding="utf-8")
    (root / "data" / "extract.csv").write_bytes(DATA.encode("utf-8"))
    return root


def emitter(root: Path, script: str = "run.py") -> Emitter:
    return Emitter(root / "analysis" / script, root=root)


def pin(root: Path, *paths: str) -> str:
    entries = [(path, input_digest(root / path)) for path in paths or ("data/extract.csv",)]
    return dataset_digest(entries)[:16]


def declared(root: Path, **given) -> Emitter:
    em = emitter(root)
    call = {"extracted": "2024-03-01", "covers": ("1968", "2023-12-31"),
            "fingerprint": pin(root)} | given  # fmt: skip
    em.dataset("vigibase", "data/extract.csv", **call)
    return em


# ----------------------------------------------------------------------- dates themselves


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("2024-03-01", "2024-03-01"),
        ("1 March 2024", "2024-03-01"),
        ("1st March 2024", "2024-03-01"),
        ("March 1, 2024", "2024-03-01"),
        ("Mar. 1 2024", "2024-03-01"),
        ("1 Sept 2024", "2024-09-01"),
        ("March 2024", "2024-03"),
        ("2024-03", "2024-03"),
        ("2024", "2024"),
        ("1\N{NO-BREAK SPACE}March 2024", "2024-03-01"),
    ],
)
def test_a_date_is_read_in_each_way_it_is_written(text: str, iso: str) -> None:
    found = read_written(text)
    assert found is not None and found.iso == iso


@pytest.mark.parametrize(
    "text",
    ["2024-02-30", "31 April 2024", "1 Marsh 2024", "1 March 2024 onwards", "early 2024",
     "2024-13", "24", "2024\N{ARABIC-INDIC DIGIT ONE}"],
)  # fmt: skip
def test_what_is_no_date_is_read_as_none(text: str) -> None:
    assert read_written(text) is None


def test_a_date_is_printed_in_the_english_the_paper_declares() -> None:
    day = Dated(2024, 3, 1)
    assert written(day, "en-GB") == "1 March 2024"
    assert written(day, "en-US") == "March 1, 2024"
    assert written(Dated(2024, 3), "en-US") == written(Dated(2024, 3), "en-GB") == "March 2024"
    assert written(Dated(1968)) == "1968"


@pytest.mark.parametrize(
    ("value", "display", "says"),
    [
        ("2015-01-01", "1 January 2015", None),
        ("2015-01-01", "January 1, 2015", None),
        ("2015-03-01", "March 2015", None),
        ("2015-03-01", "2015", None),
        ("2015-01-01", "1 January 2016", "is 2016-01-01, and the value is 2015-01-01"),
        ("2015-03", "1 March 2015", "names a day, and the value is the month 2015-03"),
        ("2015-01-01", "early 2015", "is not a date"),
        # Not a date: a period, and the label it always was.
        ("2015-2024", "2015 to 2024", None),
        # A month that is also a period written short, printed as the period: as before.
        ("2010-12", "2010 to 2012", None),
        ("2010-12", "November 2010", "is 2010-11, and the value is 2010-12"),
        ("2015", "2016", "is 2016, and the value is 2015"),
    ],
)
def test_a_date_s_display_is_the_date_or_a_coarser_statement_of_it(
    value: str, display: str, says: str | None
) -> None:
    problem = display_problem(value, display)
    assert (problem is None) if says is None else (says in (problem or "")), problem


def test_value_refuses_a_date_printed_as_another_and_takes_one_printed_as_itself(
    scratch: Path,
) -> None:
    """The hole G2's own hint for a typed date walked into: `display` was not compared with a
    string value, and the call the hint proposed raised for the digits in an ISO date."""
    em = emitter(scratch)
    em.value("period.start", "2015-01-01", display="1 January 2015")
    em.parameter("study.end", "2023-12-31", display="31 December 2023")
    with pytest.raises(DisplayError, match="is 2016-01-01, and the value is 2015-01-01"):
        em.value("period.end", "2015-01-01", display="1 January 2016")


@pytest.mark.parametrize(
    ("item", "iso"),
    [("2023-12-31T08:00:00", "2023-12-31"), ("2023-12", "2023-12"), (2019, "2019"),
     (2019.0, "2019"), (date(2020, 1, 2), "2020-01-02"), (None, None), ("", None),
     (float("nan"), None)],
)  # fmt: skip
def test_an_entry_of_the_data_s_dates_is_read_at_its_precision(item, iso) -> None:
    found = as_dated(item)
    assert (found.iso if found else None) == iso


@pytest.mark.parametrize("item", ["K71.0", True, 2019.5, 12, "31/12/2023"])
def test_an_entry_that_is_no_date_is_refused_naming_it(item) -> None:
    with pytest.raises(ValueError, match="is not a date"):
        as_dated(item)


def test_pandas_and_numpy_dates_are_read_and_their_missing_values_left_out() -> None:
    pd = pytest.importorskip("pandas")
    np = pytest.importorskip("numpy")
    column = pd.Series(pd.to_datetime(["2023-01-05", None, "2023-12-30"]))
    assert [as_dated(item) for item in column] == [Dated(2023, 1, 5), None, Dated(2023, 12, 30)]
    assert as_dated(np.datetime64("2023-04-05")) == Dated(2023, 4, 5)
    assert as_dated(np.int64(2019)) == Dated(2019)
    assert as_dated(pd.NA) is None


# ------------------------------------------------------------------------- the emitter


def test_a_dataset_emits_its_dates_and_version_and_records_its_pin(scratch: Path) -> None:
    em = declared(scratch, version="2024 Q1", dates=["2023-01-05", "2023-12-30", None])
    document = em.document()
    values = document["values"]
    assert values["dataset.vigibase.extracted"] == {
        "value": "2024-03-01", "display": "1 March 2024", "label": True, "role": "dataset",
    }  # fmt: skip
    assert values["dataset.vigibase.covers_from"]["display"] == "1968"
    assert values["dataset.vigibase.covers_to"]["display"] == "31 December 2023"
    assert values["dataset.vigibase.version"]["value"] == "2024 Q1"
    assert document["datasets"]["vigibase"] == {
        "inputs": ["data/extract.csv"],
        "fingerprint": pin(scratch),
        "extracted": "2024-03-01",
        "covers": {"from": "1968", "to": "2023-12-31"},
        "version": "2024 Q1",
        "observed": {"earliest": "2023-01-05", "latest": "2023-12-30", "count": 2},
    }
    assert [i["path"] for i in document["provenance"]["inputs"]] == ["data/extract.csv"]


def test_a_dataset_with_no_version_and_one_end_of_its_period_emits_only_those(
    scratch: Path,
) -> None:
    """Many sources have no version a user can name: then none is emitted, and none is
    asked for. "Covering reports to 31 December 2023" states one end."""
    em = declared(scratch, covers=(None, "2023-12-31"))
    assert sorted(k for k in em.document()["values"]) == [
        "dataset.vigibase.covers_to", "dataset.vigibase.extracted",
    ]  # fmt: skip


def test_a_dataset_is_printed_in_american_english_where_the_paper_is(scratch: Path) -> None:
    paper = scratch / "paper.yaml"
    paper.write_text(paper.read_text(encoding="utf-8").replace("en-GB", "en-US"), encoding="utf-8")
    values = declared(scratch).document()["values"]
    assert values["dataset.vigibase.extracted"]["display"] == "March 1, 2024"


def test_a_dataset_unpinned_is_refused_and_told_its_pin(scratch: Path) -> None:
    with pytest.raises(ValueError, match=re.escape(f'fingerprint="{pin(scratch)}"')):
        declared(scratch, fingerprint=None)


def test_data_extracted_again_cannot_keep_the_old_date(scratch: Path) -> None:
    """The case the pin is for: the extract is replaced, the analysis is run again, and the
    script still says 1 March 2024. It is refused, and told the new digest."""
    old = pin(scratch)
    (scratch / "data" / "extract.csv").write_bytes((DATA + "3,2024-02-27\n").encode("utf-8"))
    with pytest.raises(ValueError, match="is not the data pinned as extracted on 2024-03-01") as e:
        declared(scratch, fingerprint=old)
    assert pin(scratch) in str(e.value)


def test_a_pin_may_be_the_bytes_digest_sha256sum_prints_or_say_so(scratch: Path) -> None:
    raw = sha256_of(scratch / "data" / "extract.csv")
    declared(scratch, fingerprint="SHA256:" + raw[:12].upper())


@pytest.mark.parametrize(
    ("given", "says"),
    [
        ({"fingerprint": "3f9a1c"}, "first twelve or more characters"),
        ({"fingerprint": 12}, "the fingerprint is text"),
        ({"extracted": None}, "give the date the data were extracted"),
        ({"extracted": "01/03/2024"}, "is not a date written as ISO 8601"),
        ({"extracted": "2999-01-01"}, "is after today"),
        ({"covers": ("2023-12-31", "1968")}, "covers runs backwards"),
        ({"covers": ("1968", "2024-06-30")}, "cannot cover a period after they were extracted"),
        ({"covers": "1968/2023"}, "covers is a pair"),
        ({"covers": (None, None)}, "covers states neither end"),
        ({"version": 5.0}, "give the version as text"),
        ({"version": "  "}, "the version is empty"),
        ({"dates": ["2023-01-05", "1967-06-01"]}, "1 of 2 dates lie outside the period"),
        ({"dates": "2023-01-05"}, "a column of them"),
        ({"dates": [None, ""]}, "dates holds no date"),
        ({"dates": ["2023-01-05", "K71.0"]}, "dates[1]: 'K71.0' is not a date"),
    ],
)
def test_what_a_dataset_cannot_be_is_refused(scratch: Path, given: dict, says: str) -> None:
    with pytest.raises(ValueError, match=re.escape(says)):
        declared(scratch, **given)


def test_a_date_after_the_extraction_is_refused_where_the_period_is_not_stated() -> None:
    with pytest.raises(ValueError, match="1 of 2 dates are after the extraction on 2024-03-01"):
        declare("x", extracted="2024-03-01", covers=None, version=None,
                dates=["2023-01-01", "2024-03-02"])  # fmt: skip


def test_a_date_at_a_coarser_precision_is_refused_only_where_it_cannot_lie_within() -> None:
    """A report dated "2023" may lie within data covered to 2023-06-30, so it passes; one
    dated "2024" cannot."""
    declare("x", extracted="2024-03-01", covers=(None, "2023-06-30"), version=None,
            dates=[2023])  # fmt: skip
    with pytest.raises(ValueError, match="lie outside"):
        declare("x", extracted="2024-03-01", covers=(None, "2023-06-30"), version=None,
                dates=[2024])  # fmt: skip


@pytest.mark.parametrize("name", ["VigiBase", "", "-x", "vigi base", 3])
def test_a_dataset_s_name_is_the_record_s_id(scratch: Path, name) -> None:
    with pytest.raises(ValueError, match="a name is lowercase letters"):
        emitter(scratch).dataset(name, "data/extract.csv", extracted="2024-03-01",
                                 fingerprint=pin(scratch))  # fmt: skip


def test_two_names_under_one_set_of_keys_are_refused(scratch: Path) -> None:
    em = emitter(scratch)
    em.dataset("faers-q4", "data/extract.csv", extracted="2024-03-01", fingerprint=pin(scratch))
    with pytest.raises(ValueError, match="'faers-q4' is already declared"):
        em.dataset("faers_q4", "data/extract.csv", extracted="2024-03-01",
                   fingerprint=pin(scratch))  # fmt: skip


def test_several_files_are_one_dataset_whatever_their_order(scratch: Path) -> None:
    (scratch / "data" / "drugs.csv").write_bytes(b"id,drug\n1,a\n")
    whole = pin(scratch, "data/extract.csv", "data/drugs.csv")
    assert whole == pin(scratch, "data/drugs.csv", "data/extract.csv")
    em = emitter(scratch)
    em.dataset("vigibase", ["data/extract.csv", "data/drugs.csv"], extracted="2024-03-01",
               fingerprint=whole, restricted=True)  # fmt: skip
    document = em.document()
    assert document["datasets"]["vigibase"]["inputs"] == ["data/extract.csv", "data/drugs.csv"]
    assert all(i.get("restricted") for i in document["provenance"]["inputs"])
    # A file's own digest is not the pin of several.
    with pytest.raises(ValueError, match="is not the data pinned"):
        emitter(scratch).dataset("vigibase", ["data/extract.csv", "data/drugs.csv"],
                                 extracted="2024-03-01", fingerprint=pin(scratch))  # fmt: skip


def test_a_missing_file_is_refused(scratch: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no file"):
        emitter(scratch).dataset("vigibase", "data/none.csv", extracted="2024-03-01",
                                 fingerprint="0" * 16)  # fmt: skip


# ---------------------------------------------------------------- G1, on what is on disk


def _written(root: Path, em: Emitter) -> tuple:
    em.write()
    project, _report = load_project(root)
    _namespace, results, _literature, _load = load_namespace(project)
    return project, results


def _edit(fragment: Path, change) -> None:
    document = json.loads(fragment.read_text(encoding="utf-8"))
    change(document)
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)


def test_a_dataset_as_the_emitter_wrote_it_passes_g1(scratch: Path) -> None:
    project, results = _written(scratch, declared(scratch))
    report = check_datasets(project, results)
    assert not report.findings and report.counts["datasets_checked"] == 1


def test_a_pin_edited_into_another_is_caught(scratch: Path) -> None:
    declared(scratch).write()
    fragment = scratch / "results" / "run.json"
    _edit(fragment, lambda d: d["datasets"]["vigibase"].update(fingerprint="0" * 16))
    project, _ = load_project(scratch)
    _ns, results, _lit, _load = load_namespace(project)
    found = check_datasets(project, results).failures
    assert [f.code for f in found] == ["dataset-pin-mismatch"]
    assert "pins 0000000000000000" in found[0].message


def test_a_dataset_naming_a_file_the_run_did_not_read_is_caught(scratch: Path) -> None:
    declared(scratch).write()
    fragment = scratch / "results" / "run.json"
    _edit(fragment, lambda d: d["datasets"]["vigibase"].update(inputs=["data/other.csv"]))
    project, _ = load_project(scratch)
    _ns, results, _lit, _load = load_namespace(project)
    assert "did not record reading" in check_datasets(project, results).failures[0].message


def test_another_run_of_other_data_beside_the_dated_extraction_is_caught(scratch: Path) -> None:
    """A model fitted on the new extraction, beside the script that dates the old one: told
    from the records alone, as CI has them where the data are not in the repository."""
    declared(scratch).write()
    (scratch / "data" / "extract.csv").write_bytes((DATA + "3,2023-06-01\n").encode("utf-8"))
    (scratch / "analysis" / "model.py").write_text("# model\n", encoding="utf-8")
    model = emitter(scratch, "model.py")
    model.add_input("data/extract.csv")
    model.value("n", 3)
    model.write()
    (scratch / "data" / "extract.csv").unlink()
    project, _ = load_project(scratch)
    _ns, results, _lit, _load = load_namespace(project)
    found = check_datasets(project, results).failures
    assert [f.code for f in found] == ["dataset-read-differs"]
    assert found[0].message.startswith("model.json read data/extract.csv as other data than")


def test_an_input_changed_names_the_date_it_makes_stale(scratch: Path) -> None:
    project, results = _written(scratch, declared(scratch))
    (scratch / "data" / "extract.csv").write_bytes((DATA + "3,2023-06-01\n").encode("utf-8"))
    found = [f for f in check_freshness(project, results).failures if f.code == "input-changed"]
    assert "dataset.vigibase.extracted dates the data as they were (2024-03-01)" in (
        found[0].message
    )
    assert "with the date of the new extraction and its pin" in found[0].hint


def test_a_date_display_edited_into_another_date_is_refused_when_read(scratch: Path) -> None:
    """A fragment from R, or written by hand, is read with the emitter's rule."""
    declared(scratch).write()
    _edit(scratch / "results" / "run.json",
          lambda d: d["values"]["dataset.vigibase.covers_to"].update(display="31 December 2022"))
    project, _ = load_project(scratch)
    namespace, _results, _lit, load = load_namespace(project)
    assert "results.dataset.vigibase.covers_to" not in namespace
    assert any(f.code == "no-display" and "is 2022-12-31" in f.message for f in load.failures)


# ------------------------------------------------------------------ G2, in the sentences


def _value(key: str, value: object, display: str, role: str | None = None) -> tuple[str, Value]:
    return f"results.{key}", Value(key=key, value=value, display=display, origin=RESULTS,
                                   role=role)  # fmt: skip


NAMESPACE = dict([
    _value("old.extracted", "2024-03-01", "1 March 2024"),
    _value("old.label", "1 March 2024", "1 March 2024"),
    _value("dataset.vb.extracted", "2024-03-01", "1 March 2024", role="dataset"),
    _value("param.start", "2010-01-01", "1 January 2010", role="parameter"),
    _value("cohort.first_year", 2010, "2010"),
    _value("n", 12, "12"),
])  # fmt: skip


def _said(text: str) -> list[str]:
    placeholders, _malformed = parse(text)
    report = data_dates([(Path("main.md"), text, in_sentences(placeholders, text))], NAMESPACE)
    return [f.message.split(" is ")[0] for f in report.findings]


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("Data were extracted on {{results.old.extracted}}.", ["{{results.old.extracted}}"]),
        ("We downloaded the files on {{results.old.label}}.", ["{{results.old.label}}"]),
        ("Reports up to {{results.old.extracted}} were covered.",
         ["{{results.old.extracted}}"]),
        ("Data were extracted on {{results.dataset.vb.extracted}}.", []),
        ("Reports were retrieved from {{results.param.start}}.", []),
        ("Reports from {{results.cohort.first_year}} were extracted.", []),
        ("Ethics approval was given on {{results.old.extracted}}.", []),
        # The key's own words say nothing: "extracted" is in the binding, not the sentence.
        ("Approval came on {{results.old.extracted}}.", []),
        # Nor do the next sentence's, nor a comment's.
        ("Approval came on {{results.old.extracted}}. The data were extracted later.", []),
        ("Approval came on {{results.old.extracted}} <!-- extracted -->.", []),
    ],
)  # fmt: skip
def test_a_date_typed_into_the_script_is_warned_where_the_sentence_dates_the_data(
    text: str, said: list[str]
) -> None:
    assert _said(text) == said


def test_what_is_a_typed_date_is_a_string_no_declaration_names() -> None:
    assert [key for key, value in NAMESPACE.items() if is_typed_date(value)] == [
        "results.old.extracted", "results.old.label",
    ]  # fmt: skip


def test_a_dataset_date_printed_in_another_english_is_warned() -> None:
    namespace = dict([_value("dataset.vb.extracted", "2024-03-01", "1 March 2024", "dataset"),
                      # A release named like a month is a name, and printed as it is named.
                      _value("dataset.vb.version", "2024-03", "2024-03", "dataset")])
    assert not dates_in_english(namespace, "en-GB").findings
    (found,) = dates_in_english(namespace, "en-US").findings
    assert found.code == "dataset-date-english" and "'March 1, 2024'" in found.message


# ------------------------------------------------------------------- round 1 of #392


@pytest.mark.parametrize("value", ["1520", "9999", "0042"])
def test_a_string_of_four_digits_is_still_a_number_no_gate_can_trace(value: str) -> None:
    """Round 1 of #392: an ISO year let any four digits through, where main refused them.
    A count read from a CSV as text is not a year."""
    with pytest.raises(DisplayError, match="no gate can trace"):
        check_string_value("cases.n", value, label=False)


@pytest.mark.parametrize("value", ["2015-01-01", "1850-03"])
def test_a_month_or_a_day_is_a_date_and_no_number(value: str) -> None:
    check_string_value("period.start", value, label=False)


@pytest.mark.parametrize(
    ("value", "display", "says"),
    [
        ("2023-12-31", "31/12/2023", None),
        ("2023-12-31", "31.12.2023", None),
        ("2023-12-31", "31-12-2023", None),
        ("2023-12-31", "2023/12/31", None),
        # The day and the month apart, read both ways: either is the date.
        ("2024-03-01", "01/03/2024", None),
        ("2024-01-03", "01/03/2024", None),
        ("2024-03-02", "01/03/2024", "is 2024-03-01, and the value is 2024-03-02"),
        ("2023-12-31", "12/31/2023", None),
        ("2023-12-31", "31/12/23", "is not a date"),
    ],
)
def test_a_date_in_figures_is_read_as_its_date(value: str, display: str, says) -> None:
    """Round 1 of #392: a display in figures, which loaded on main, was no date to the
    reader, and its value was dropped."""
    problem = display_problem(value, display)
    assert (problem is None) if says is None else (says in (problem or "")), problem


def test_a_role_dataset_value_no_record_holds_is_caught(scratch: Path) -> None:
    """Round 1 of #392: G2 does not warn of a dataset's date, so a value that says it is one
    with no record, or another date than the record's, was tied to nothing."""
    declared(scratch, version="2024 Q1").write()
    fragment = scratch / "results" / "run.json"

    def change(document: dict) -> None:
        document["values"]["dataset.vigibase.extracted"]["value"] = "2023-01-01"
        document["values"]["dataset.vigibase.extracted"]["display"] = "1 January 2023"
        document["values"]["dataset.other.extracted"] = {
            "value": "2024-03-01", "display": "1 March 2024", "label": True, "role": "dataset",
        }  # fmt: skip

    _edit(fragment, change)
    project, _ = load_project(scratch)
    _ns, results, _lit, _load = load_namespace(project)
    found = sorted(f.message for f in check_datasets(project, results).failures
                   if f.code == "dataset-value-unrecorded")  # fmt: skip
    assert found == [
        "results.dataset.other.extracted says it identifies a dataset, '2024-03-01', and no "
        "dataset record of its fragment holds it",
        "results.dataset.vigibase.extracted says it identifies a dataset, '2023-01-01', and its "
        "dataset's record holds '2024-03-01'",
    ]


def test_every_value_a_dataset_writes_is_its_record_s(scratch: Path) -> None:
    project, results = _written(scratch, declared(scratch, version="2024 Q1"))
    assert not check_datasets(project, results).findings


def test_a_file_named_twice_is_one_file_of_the_data(scratch: Path) -> None:
    em = emitter(scratch)
    em.dataset("vigibase", ["data/extract.csv", "data/extract.csv"], extracted="2024-03-01",
               fingerprint=pin(scratch))  # fmt: skip
    document = em.document()
    assert document["datasets"]["vigibase"]["inputs"] == ["data/extract.csv"]
    assert [i["path"] for i in document["provenance"]["inputs"]] == ["data/extract.csv"]


@pytest.mark.parametrize("role", ["software", "dictionary"])
def test_a_release_named_by_a_year_is_no_date_typed(role: str) -> None:
    """Round 1 of #392: ICD-10's release is "2019", and declared with `dictionary()` it is no
    date the analysis typed."""
    _key, value = _value(f"{role}.icd_10", "2019", "2019", role=role)
    assert not is_typed_date(value)


@pytest.mark.parametrize(
    "text",
    [
        "Approval came on {{results.old.extracted}} ({{method.extraction}}).",
        "Approval came on {{results.old.extracted}} [@extracted2020].",
        "Approval came on {{results.old.extracted}}, as @extracted2020 did.",
        "Approval came on {{results.old.extracted}} (see {{table.extracted_cases}}).",
    ],
)
def test_the_words_of_another_binding_or_a_citation_say_nothing(text: str) -> None:
    assert _said(text) == []


@pytest.mark.parametrize(
    "word", ["queries run", "obtaining", "accessing", "retrieving", "retrieves", "cut-offs",
             "locking", "freezing"],
)  # fmt: skip
def test_each_form_of_the_words_that_date_the_data_is_read(word: str) -> None:
    assert _said(f"With {word} the data, {{{{results.old.extracted}}}} was the date.") == [
        "{{results.old.extracted}}"
    ]


def test_iso_dates_are_dates_at_their_precision() -> None:
    assert parse_iso("2023") == Dated(2023)
    assert parse_iso("2023-02-29") is None
    assert parse_iso(2023) is None
