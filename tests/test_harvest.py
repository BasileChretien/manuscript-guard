"""`harvest`: an output a script writes without the emitter, taken in as results; `verify`
re-harvesting it from a run; and a site's receipt of a run where the data are.

The reading of a cell and of an output's shapes is held over generated inputs in
`tests/test_properties.py`; here are the files it writes, what G1 says of them, and the
commands.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.gates import check_freshness
from manuscript_guard.harvest import (
    Entry,
    HarvestError,
    Input,
    append_entry,
    harvest_entry,
    load_entries,
    make_receipt,
)
from manuscript_guard.harvest.read import read_output
from manuscript_guard.verify import verify

ROWS = ["group,n,rate,or", "Women,120,52.1%,1.50", "Men,<5,3.0%,0.95"]
SCRIPT = (
    "from pathlib import Path\n"
    "Path('output').mkdir(exist_ok=True)\n"
    f"Path('output/est.csv').write_text({chr(10).join(ROWS)!r} + '\\n')\n"
)


def _write_script(root: Path, text: str = SCRIPT, name: str = "analysis/02_est.py") -> None:
    (root / name).write_text(text, encoding="utf-8")


def _harvested(project: Path, *, receipt: str | None = None) -> Entry:
    """The example with a script that writes output/est.csv, run, and an entry for it."""
    _write_script(project)
    (project / "output").mkdir(exist_ok=True)
    (project / "output" / "est.csv").write_bytes(("\n".join(ROWS) + "\n").encode("utf-8"))
    entry = Entry("est", "output/est.csv", "analysis/02_est.py",
                  (Input("data/reports.csv", synthetic=True),), row_key="group",
                  receipt=receipt)  # fmt: skip
    append_entry(project, entry)
    return entry


def _g1(root: Path) -> list:
    project, _ = load_project(root)
    _namespace, results, _literature, _report = load_namespace(project)
    return list(check_freshness(project, results).findings)


def _codes(root: Path) -> dict[str, str]:
    return {finding.code: finding.severity for finding in _g1(root)}


# ------------------------------------------------------------------------- the file written


def test_an_output_becomes_a_results_file_with_a_value_for_each_cell(project: Path) -> None:
    entry = _harvested(project)
    path = harvest_entry(project, entry)
    document = json.loads(path.read_text(encoding="utf-8"))
    values = document["values"]
    assert values["est.women.n"] == {"value": 120, "display": "120", "quoted": False}
    assert values["est.men.n"] == {"value": None, "display": "<5", "quoted": False,
                                   "count": True}
    assert values["est.women.rate"]["unit"] == "%"
    assert values["est.women.or"]["display"] == "1.50"
    assert values["est.women.group"]["label"] is True
    assert document["tables"]["est"]["rows"][1] == ["Men", "<5", "3.0%", "0.95"]
    provenance = document["provenance"]
    assert provenance["generated_by"] == "analysis/02_est.py"
    assert provenance["inputs"][0]["path"] == "data/reports.csv"
    assert provenance["inputs"][0]["synthetic"] is True
    assert "session" not in provenance
    harvested = provenance["harvested"]
    assert harvested["attribution"] == "declared"
    assert harvested["spec"] == entry.spec()
    assert path.with_name(path.name + ".sha256").is_file()


def test_a_harvested_file_is_results_like_any_other(project: Path) -> None:
    harvest_entry(project, _harvested(project))
    project_, _ = load_project(project)
    namespace, results, _literature, report = load_namespace(project_)
    assert report.ok, report.render(project)
    assert results.values["est.women.or"].display == "1.50"
    assert "table.est" not in namespace  # tables are not values
    assert results.tables["est"].columns == ("group", "n", "rate", "or")


def test_digits_round_each_number_and_keep_the_unit(tmp_path: Path) -> None:
    entry = Entry("t", "o.csv", "s.py", row_key="g", digits={"rate": 0})
    table = read_output(b"g,rate,n\nA,52.6%,1\n", ".csv", entry)
    assert table.values("t")["t.a.rate"].display == "53%"
    assert table.values("t")["t.a.n"].display == "1"


@pytest.mark.parametrize(("data", "suffix", "row_key", "said"), [
    (b"a,b\n1,2,3\n", ".csv", None, "cells under a header"),
    (b'{"a": {"b": 1}}', ".json", None, "no number, text or null"),
    (b'{"a": true}', ".json", None, "no number, text or null"),
    (b'[{"a": 1}]', ".json", None, "give row_key"),
    (b'[1, 2]', ".json", "a", "neither an object"),
    (b'{"a": NaN}', ".json", None, "no number a paper prints"),
    (b'{"a": 1, "a": 2}', ".json", None, "written twice"),
    (b"g,n\nA,1\na,2\n", ".csv", "g", "both make the key part"),
    (b"g,n\n,1\n", ".csv", "g", "no 'g' to name it"),
    (b"g,n\nA,1\n", ".csv", "h", "no column 'h'"),
    (b"g,n\nA,12.3 (10.1 to 14.5)\n", ".csv", "g", "no gate can trace"),
])  # fmt: skip
def test_what_cannot_be_read_without_a_guess_is_refused(
    tmp_path: Path, data: bytes, suffix: str, row_key: str | None, said: str
) -> None:
    root = tmp_path / "p"
    (root / "output").mkdir(parents=True)
    (root / "s.py").write_text("", encoding="utf-8")
    (root / "output" / f"o{suffix}").write_bytes(data)
    entry = Entry("t", f"output/o{suffix}", "s.py", row_key=row_key)
    with pytest.raises(HarvestError, match=said):
        harvest_entry(root, entry)


def test_a_results_file_an_analysis_wrote_is_not_written_over(project: Path) -> None:
    _harvested(project)
    entry = Entry("01_disproportionality", "output/est.csv", "analysis/02_est.py",
                  row_key="group")  # fmt: skip
    with pytest.raises(HarvestError, match="harvest did not write it"):
        harvest_entry(project, entry)


def test_an_entry_is_added_at_the_end_and_the_comments_kept(tmp_path: Path) -> None:
    (tmp_path / "harvest.yaml").write_text("# mine\nentries:\n  - key: a  # first\n"
                                           "    output: a.csv\n    script: a.py\n"
                                           "    inputs: []\n", encoding="utf-8")  # fmt: skip
    append_entry(tmp_path, Entry("b", "b.csv", "b.py", (Input("d.csv", restricted=True),)))
    text = (tmp_path / "harvest.yaml").read_text(encoding="utf-8")
    assert text.startswith("# mine\nentries:\n  - key: a  # first\n")
    assert [entry.key for entry in load_entries(tmp_path)] == ["a", "b"]
    assert load_entries(tmp_path)[1].inputs == (Input("d.csv", restricted=True),)
    with pytest.raises(HarvestError, match="already has an entry"):
        append_entry(tmp_path, Entry("b", "c.csv", "b.py"))


def test_an_entry_not_at_the_end_of_the_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "harvest.yaml").write_text("entries: []\n", encoding="utf-8")
    with pytest.raises(HarvestError, match="add it there by hand"):
        append_entry(tmp_path, Entry("b", "b.csv", "b.py"))
    assert (tmp_path / "harvest.yaml").read_text(encoding="utf-8") == "entries: []\n"


@pytest.mark.parametrize("output", ["/abs/o.csv", "../o.csv", "o.xlsx"])
def test_a_path_out_of_the_project_or_of_another_kind_breaks_the_schema(
    tmp_path: Path, output: str
) -> None:
    (tmp_path / "harvest.yaml").write_text(yaml.safe_dump({"entries": [
        {"key": "a", "output": output, "script": "a.py", "inputs": []}]}), encoding="utf-8")
    with pytest.raises(HarvestError, match="schema"):
        load_entries(tmp_path)


# ------------------------------------------------------------------------------------- G1


def test_g1_says_a_harvested_file_is_declared_until_verify_reproduces_it(project: Path) -> None:
    harvest_entry(project, _harvested(project))
    assert _codes(project).get("harvest-declared") == "warn"
    result = verify(project_ := load_project(project)[0])
    assert result.ok, [c.error for c in result.comparisons]
    from manuscript_guard.assurance import assurance, record_verified

    record_verified(project_, result)
    assert "harvest-declared" not in _codes(project)
    lines = assurance(check_freshness(project_, load_namespace(project_)[1]), project_)
    assert any("1 reproduced by `verify`" in line for line in lines), lines


def test_the_assurance_says_declared_of_a_harvested_file_nothing_ran(project: Path) -> None:
    from manuscript_guard.assurance import assurance
    from manuscript_guard.findings import Report

    harvest_entry(project, _harvested(project))
    lines = assurance(Report(), load_project(project)[0])
    assert any("harvested from outputs: 1 declared" in line for line in lines), lines


def test_an_output_changed_or_gone_since_the_harvest_fails(project: Path) -> None:
    harvest_entry(project, _harvested(project))
    assert "harvested-output-changed" not in _codes(project)
    output = project / "output" / "est.csv"
    output.write_text(output.read_text(encoding="utf-8").replace("1.50", "1.51"),
                      encoding="utf-8")  # fmt: skip
    assert _codes(project)["harvested-output-changed"] == "fail"
    output.unlink()
    assert _codes(project)["harvested-output-missing"] == "fail"


def test_an_output_whose_line_endings_git_changed_is_the_same_output(project: Path) -> None:
    harvest_entry(project, _harvested(project))
    output = project / "output" / "est.csv"
    assert b"\r" not in output.read_bytes()
    output.write_bytes(output.read_bytes().replace(b"\n", b"\r\n"))
    assert "harvested-output-changed" not in _codes(project)


# ---------------------------------------------------------------------------------- verify


def test_verify_fails_a_harvested_file_the_script_no_longer_writes_the_same(
    project: Path,
) -> None:
    harvest_entry(project, _harvested(project))
    _write_script(project, SCRIPT.replace("1.50", "1.70"))
    result = verify(load_project(project)[0], only=["est"])
    comparison = result.comparisons[0]
    assert comparison.ran
    assert {key for key, *_ in comparison.differed} == {"est.women.or", "<table est rows>"}


def test_verify_says_a_script_that_writes_no_output_failed_to_rerun(project: Path) -> None:
    from manuscript_guard.verify import to_report

    harvest_entry(project, _harvested(project))
    _write_script(project, "print('nothing')\n")
    result = verify(load_project(project)[0], only=["est"])
    assert not result.comparisons[0].ran
    assert "wrote no output/est.csv" in result.comparisons[0].error
    assert {f.code for f in to_report(result).findings} == {"rerun-failed"}


# -------------------------------------------------------------------------------- receipts


def _receipted(project: Path) -> Entry:
    entry = _harvested(project, receipt="site-a")
    make_receipt(load_project(project)[0], "site-a")
    harvest_entry(project, entry)
    return entry


def test_a_receipt_records_the_run_by_digest_and_labels(project: Path) -> None:
    _receipted(project)
    receipt = json.loads((project / "receipts" / "site-a.receipt.json").read_text("utf-8"))
    assert receipt["schema"] == "manuscript-guard/receipt/1"
    run = receipt["runs"][0]
    assert run["script"]["path"] == "analysis/02_est.py"
    assert run["inputs"][0]["label"] == "data/reports.csv"
    assert set(run["inputs"][0]) == {"label", "sha256", "raw_sha256", "bytes"}
    assert run["outputs"][0]["path"] == "output/est.csv"
    assert run["exit_code"] == 0
    assert run["runner"]["version"].startswith("Python")
    assert str(project) not in json.dumps(receipt)
    assert str(project).replace("\\", "/") not in json.dumps(receipt)


def test_a_receipted_file_is_covered_and_verify_does_not_reproduce_it(project: Path) -> None:
    _receipted(project)
    codes = _codes(project)
    assert "harvest-declared" not in codes
    assert not any(severity == "fail" for severity in codes.values()), codes
    result = verify(load_project(project)[0], only=["est"])
    assert result.comparisons == []
    ran = json.loads((project / "receipts" / "site-a.receipt.json").read_text("utf-8"))["ran_at"]
    assert ("est.json", f"data held at site-a; receipt of {ran[:10]}") in result.skipped


def test_inputs_held_at_the_site_are_a_note_at_the_centre(project: Path) -> None:
    _receipted(project)
    (project / "data" / "reports.csv").unlink()
    found = {f.code: f for f in _g1(project) if f.path.name == "est.json"}
    assert found["input-at-site"].severity == "info"
    assert "input-missing" not in found


def test_a_receipt_that_does_not_cover_the_output_is_refused_at_harvest(project: Path) -> None:
    entry = _harvested(project, receipt="site-a")
    make_receipt(load_project(project)[0], "site-a")
    output = project / "output" / "est.csv"
    output.write_text(output.read_text("utf-8").replace("120", "121"), encoding="utf-8")
    with pytest.raises(HarvestError, match="not the output the receipt"):
        harvest_entry(project, entry)


def test_an_output_not_the_receipts_fails(project: Path) -> None:
    _receipted(project)
    receipt = project / "receipts" / "site-a.receipt.json"
    output = project / "output" / "est.csv"
    output.write_text(output.read_text("utf-8").replace("120", "121"), encoding="utf-8")
    codes = _codes(project)
    assert codes["receipt-output-mismatch"] == "fail"
    assert codes["harvested-output-changed"] == "fail"
    assert receipt.is_file()


def test_the_site_refuses_a_receipt_of_a_count_the_custodian_forbids(project: Path) -> None:
    _harvested(project, receipt="site-a")
    paper = project / "paper.yaml"
    paper.write_text(paper.read_text("utf-8") + "\ncustodian:\n  minimum_cell_count: 200\n",
                     encoding="utf-8")  # fmt: skip
    with pytest.raises(HarvestError, match=r"est\.women\.n is 120, a count below"):
        make_receipt(load_project(project)[0], "site-a")
    assert not (project / "receipts").exists()


def test_the_site_refuses_a_run_that_fails(project: Path) -> None:
    _harvested(project, receipt="site-a")
    _write_script(project, "raise SystemExit(3)\n")
    with pytest.raises(HarvestError, match="exited 3"):
        make_receipt(load_project(project)[0], "site-a")
    with pytest.raises(HarvestError, match="no entry of harvest.yaml names the site"):
        make_receipt(load_project(project)[0], "site-b")


# ----------------------------------------------------------------------------- the commands


def test_the_command_adds_an_entry_and_harvests_it(project: Path, capsys) -> None:
    _write_script(project)
    (project / "output").mkdir()
    (project / "output" / "est.csv").write_text("\n".join(ROWS) + "\n", encoding="utf-8")
    code = main(["harvest", "output/est.csv", "--script", "analysis/02_est.py", "--input",
                 "data/reports.csv", "--synthetic", "--key", "est", "--row-key", "group",
                 "--path", str(project)])  # fmt: skip
    said = capsys.readouterr().out
    assert code == 0, said
    assert "output/est.csv -> results/est.json, table.est" in said
    assert "Nothing was run" in said
    assert load_entries(project)[0].inputs == (Input("data/reports.csv", synthetic=True),)
    assert main(["harvest", "--path", str(project)]) == 0
    assert main(["harvest", "x.csv", "--path", str(project)]) == 2


def test_the_command_with_nothing_to_harvest_says_so(project: Path, capsys) -> None:
    assert main(["harvest", "--path", str(project)]) == 2
    assert "names no output to harvest" in capsys.readouterr().err


def test_verify_receipt_writes_the_receipt_and_the_output(project: Path, capsys) -> None:
    _harvested(project, receipt="site-a")
    (project / "output" / "est.csv").unlink()
    assert main(["verify", str(project), "--receipt", "site-a"]) == 0, capsys.readouterr()
    assert (project / "receipts" / "site-a.receipt.json").is_file()
    assert (project / "output" / "est.csv").is_file()
    assert main(["verify", str(project), "--receipt", "site-a", "--only", "est"]) == 2
    assert main(["verify", str(project), "--receipt", "nowhere"]) == 1


def test_a_harvested_value_and_its_table_bind_in_the_manuscript(project: Path) -> None:
    from manuscript_guard.gates import check_numbers

    harvest_entry(project, _harvested(project))
    main_md = project / "manuscript" / "main.md"
    added = ("\n\n# Harvested\n\nThe ratio was {{results.est.women.or}} (Table 3).\n\n"
             "{{table.est}}\n")
    main_md.write_text(main_md.read_text("utf-8") + added, encoding="utf-8")
    project_, _ = load_project(project)
    namespace, results, literature, _report = load_namespace(project_)
    assert namespace["results.est.women.or"].display == "1.50"
    report = check_numbers(project_, namespace, results, literature)
    assert report.ok, report.render(project)


# ------------------------------------------- what a site's receipt refuses, and what it warns


def _minimum(project: Path, minimum: int) -> None:
    paper = project / "paper.yaml"
    paper.write_text(paper.read_text("utf-8") + f"\ncustodian:\n  minimum_cell_count: {minimum}\n",
                     encoding="utf-8")  # fmt: skip


def _site_output(project: Path, rows: list[str], **fields) -> Entry:
    """An entry run at site-a, its script writing `rows` as output/site.csv."""
    text = "\n".join(rows) + "\n"
    _write_script(project, "from pathlib import Path\nPath('output').mkdir(exist_ok=True)\n"
                  f"Path('output/site.csv').write_text({text!r}, encoding='utf-8')\n",
                  "analysis/03_site.py")
    entry = Entry("site", "output/site.csv", "analysis/03_site.py", receipt="site-a",
                  row_key="group", **fields)  # fmt: skip
    append_entry(project, entry)
    return entry


def test_a_total_that_gives_a_held_back_count_away_is_a_warning_and_the_receipt_is_written(
    project: Path, capsys
) -> None:
    """The real check: a "Total" row read from its label may be no sum, so a count it gives
    away is said, as `deposit` says it, and the receipt is written."""
    _minimum(project, 5)
    _site_output(project, ["group,n", "Drug,40", "Placebo,<5", "Total,43"])
    assert main(["verify", str(project), "--receipt", "site-a"]) == 0
    said = capsys.readouterr().out
    assert "[WARN] output/site.csv: table.site" in said and "3" in said, said
    assert (project / "receipts" / "site-a.receipt.json").is_file()


def test_a_declared_sum_that_gives_a_count_away_refuses_the_receipt(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure of the custodian's subtraction check refuses the receipt. A harvested output
    declares no sum, so the check never fails on one; the failure is stood in for."""
    from manuscript_guard.findings import FAIL, WARN, Finding, Report
    from manuscript_guard.gates import custodian

    _minimum(project, 5)
    _site_output(project, ["group,n", "Drug,40", "Placebo,25"])
    said = {"severity": FAIL}
    monkeypatch.setattr(custodian, "recoverable_cells", lambda *_args: Report((Finding(
        gate="G2", code="count-recoverable", severity=said["severity"],
        message="results.site.placebo.n is 3 by subtraction"),)))  # fmt: skip
    with pytest.raises(HarvestError, match="is 3 by subtraction"):
        make_receipt(load_project(project)[0], "site-a")
    assert not (project / "receipts").exists()
    said["severity"] = WARN
    _path, _written, warned = make_receipt(load_project(project)[0], "site-a")
    assert warned == ["output/site.csv: results.site.placebo.n is 3 by subtraction"]


# ------------------------------------------------------------- working output, and counts


def test_a_harvested_table_is_placed_unless_its_entry_says_it_is_working_output(
    project: Path,
) -> None:
    from manuscript_guard.gates import check_numbers

    def unplaced() -> list:
        project_, _ = load_project(project)
        namespace, results, literature, _report = load_namespace(project_)
        report = check_numbers(project_, namespace, results, literature)
        return [f for f in report.findings if f.code == "unplaced-table"]

    entry = _harvested(project)
    harvest_entry(project, entry)
    (found,) = unplaced()
    assert "harvest.yaml `quoted: false`" in found.hint
    (project / "harvest.yaml").unlink()
    entry = Entry(**{**entry.__dict__, "quoted": False})
    append_entry(project, entry)
    harvest_entry(project, entry)
    assert load_entries(project)[0].quoted is False
    assert unplaced() == []


def test_only_the_columns_an_entry_counts_are_held_to_the_minimum(project: Path) -> None:
    from manuscript_guard.gates.custodian import check_small_cells

    _minimum(project, 5)
    _write_script(project)
    (project / "output").mkdir()
    (project / "output" / "est.csv").write_bytes(b"group,n,df\nWomen,3,2\n")
    main_md = project / "manuscript" / "main.md"
    main_md.write_text(main_md.read_text("utf-8") + "\n\nWe saw {{results.est.women.n}} "
                       "cases, on {{results.est.women.df}} degrees of freedom.\n",
                       encoding="utf-8")  # fmt: skip

    def small(counts) -> set[str]:
        entry = Entry("est", "output/est.csv", "analysis/02_est.py", row_key="group",
                      counts=counts)  # fmt: skip
        harvest_entry(project, entry)
        project_, _ = load_project(project)
        results = load_namespace(project_)[1]
        return {f.message.split()[0] for f in check_small_cells(project_, results).findings}

    assert small(None) == {"results.est.women.n", "results.est.women.df"}
    assert small(("n",)) == {"results.est.women.n"}
    document = json.loads((project / "results" / "est.json").read_text("utf-8"))
    assert document["values"]["est.women.df"]["count"] is False
    assert "count" not in document["values"]["est.women.n"]
    with pytest.raises(HarvestError, match="no column 'events'"):
        small(("events",))


def test_a_receipt_holds_only_the_counted_columns_to_the_minimum(project: Path) -> None:
    _minimum(project, 5)
    _site_output(project, ["group,n,df", "Drug,40,2"])
    with pytest.raises(HarvestError, match=r"site\.drug\.df is 2"):
        make_receipt(load_project(project)[0], "site-a")
    (project / "harvest.yaml").unlink()
    _site_output(project, ["group,n,df", "Drug,40,2"], counts=("n",))
    make_receipt(load_project(project)[0], "site-a")


def test_the_command_takes_working_output_and_the_count_columns(project: Path) -> None:
    _write_script(project)
    (project / "output").mkdir()
    (project / "output" / "est.csv").write_bytes(("\n".join(ROWS) + "\n").encode("utf-8"))
    assert main(["harvest", "output/est.csv", "--script", "analysis/02_est.py", "--key", "est",
                 "--row-key", "group", "--not-quoted", "--counts", "n",
                 "--path", str(project)]) == 0  # fmt: skip
    (entry,) = load_entries(project)
    assert (entry.quoted, entry.counts) == (False, ("n",))
    assert entry.spec()["quoted"] is False and entry.spec()["counts"] == ["n"]


# ------------------------------------------------------------------- review round 1 of #471


def test_a_column_the_entry_does_not_take_in_is_held_to_the_minimum_at_the_site(
    project: Path,
) -> None:
    """The whole output file leaves the site, so a column the entry leaves out is read too,
    as a count column: nothing shows it is none."""
    _minimum(project, 5)
    _site_output(project, ["group,n,rate,deaths", "Drug,40,0.5,2"], columns=("n", "rate"))
    with pytest.raises(HarvestError, match=r"site\.drug\.deaths is 2"):
        make_receipt(load_project(project)[0], "site-a")
    (project / "harvest.yaml").unlink()
    _site_output(project, ["group,n,rate,deaths", "Drug,40,0.5,2"], columns=("n", "rate"),
                 counts=("n",))  # fmt: skip
    with pytest.raises(HarvestError, match=r"site\.drug\.deaths is 2"):
        make_receipt(load_project(project)[0], "site-a")


@pytest.mark.parametrize(("cell", "said"), [("<2", "a bound tighter than"),
                                            ("\N{LESS-THAN OR EQUAL TO}3", "a bound tighter than"),
                                            ("3.0", "a count below")])  # fmt: skip
def test_a_count_held_back_or_written_with_a_point_is_a_count(
    project: Path, cell: str, said: str
) -> None:
    """In G2 and in the receipt: "<2" is held by its bound as the emitter's `display="<2"`
    is, and "3.0" in a count column, as pandas writes one with a missing value, is 3."""
    from manuscript_guard.gates.custodian import check_small_cells

    _minimum(project, 5)
    _site_output(project, ["group,n", f"Drug,{cell}"], counts=("n",))
    with pytest.raises(HarvestError, match=said):
        make_receipt(load_project(project)[0], "site-a")
    _write_script(project)
    (project / "output").mkdir(exist_ok=True)
    (project / "output" / "est.csv").write_bytes(f"group,n\nWomen,{cell}\n".encode())
    harvest_entry(project, Entry("est", "output/est.csv", "analysis/02_est.py",
                                 row_key="group", counts=("n",)))  # fmt: skip
    main_md = project / "manuscript" / "main.md"
    main_md.write_text(main_md.read_text("utf-8") + "\n\nWe saw {{results.est.women.n}}.\n",
                       encoding="utf-8")  # fmt: skip
    project_, _ = load_project(project)
    found = check_small_cells(project_, load_namespace(project_)[1]).findings
    assert [f.code for f in found] == ["count-below-minimum"] and said in found[0].message


def test_a_held_back_count_whose_bound_hides_it_and_a_held_back_p_pass(project: Path) -> None:
    _minimum(project, 5)
    _site_output(project, ["group,n,p", "Drug,<5,<0.001"])
    make_receipt(load_project(project)[0], "site-a")


def test_a_receipt_checked_out_with_other_line_endings_is_the_same_receipt(
    project: Path,
) -> None:
    _receipted(project)
    receipt = project / "receipts" / "site-a.receipt.json"
    receipt.write_bytes(receipt.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert "receipt-changed" not in _codes(project)


def test_what_only_the_site_can_answer_goes_to_no_command() -> None:
    from manuscript_guard.findings import Finding
    from manuscript_guard.gates.harvested import RECEIPT_CONTEXT
    from manuscript_guard.guide.routes import route_for

    site = route_for(Finding(gate="G1", code="script-newer", message="m",
                             context=f"{RECEIPT_CONTEXT} site-a"))  # fmt: skip
    assert (site.argv, site.who) == (None, "author")
    assert route_for(Finding(gate="G1", code="script-newer", message="m")).argv == ("verify",)
    noted = route_for(Finding(gate="G1", code="input-at-site", message="m"))
    assert (noted.argv, noted.who) == (None, "author")


def test_a_receipted_script_changed_is_routed_to_the_site(project: Path) -> None:
    from manuscript_guard.guide.routes import route_for

    _receipted(project)
    _write_script(project, SCRIPT.replace("1.50", "1.70"))
    (found,) = [f for f in _g1(project) if f.code == "script-newer"]
    assert route_for(found).argv is None


def test_deposit_counts_no_harvested_whole_number_outside_counts() -> None:
    from manuscript_guard.deposit.counts import _values

    document = {"values": {"t.a.df": {"value": 3, "display": "3", "count": False},
                           "t.a.n": {"value": 3.0, "display": "3.0", "count": True},
                           "t.a.held": {"value": None, "display": "<2", "count": True}}}
    assert _values(document) == [("t.a.n", 3)]


def test_digits_keep_a_space_that_groups_thousands() -> None:
    entry = Entry("t", "o.csv", "s.py", digits=2)
    table = read_output(b"n\n1 234.5\n", ".csv", entry)
    assert table.values("t")["t.1.n"].display == "1 234.50"


def test_a_number_too_large_to_be_finite_is_refused(tmp_path: Path) -> None:
    with pytest.raises(HarvestError, match="no finite number"):
        read_output(b"n\n1e400\n", ".csv", Entry("t", "o.csv", "s.py"))


def test_records_named_name_and_value_are_read_by_their_row_key() -> None:
    entry = Entry("t", "o.json", "s.py", row_key="value")
    table = read_output(b'[{"name": "a", "value": "x"}]', ".json", entry)
    assert set(table.values("t")) == {"t.x.name", "t.x.value"}


def test_entries_yaml_wrote_without_indent_take_another(tmp_path: Path) -> None:
    (tmp_path / "harvest.yaml").write_text(yaml.safe_dump({"entries": [
        {"key": "a", "output": "a.csv", "script": "a.py", "inputs": []}]}), encoding="utf-8")
    append_entry(tmp_path, Entry("b", "b.csv", "b.py"))
    assert [entry.key for entry in load_entries(tmp_path)] == ["a", "b"]


def test_an_output_that_cannot_be_read_leaves_no_entry_behind(project: Path, capsys) -> None:
    _write_script(project)
    (project / "output").mkdir()
    (project / "output" / "est.csv").write_bytes(b"group,n\nA,1,2\n")
    assert main(["harvest", "output/est.csv", "--script", "analysis/02_est.py", "--key", "est",
                 "--path", str(project)]) == 2  # fmt: skip
    assert "cells under a header" in capsys.readouterr().err
    assert not (project / "harvest.yaml").exists()


def test_an_output_swallowed_by_a_flag_of_several_values_is_said(project: Path, capsys) -> None:
    _write_script(project)
    assert main(["harvest", "--input", "data/reports.csv", "output/est.csv", "--script",
                 "analysis/02_est.py", "--key", "est", "--path", str(project)]) == 2  # fmt: skip
    assert "name it first" in capsys.readouterr().err
    assert not (project / "harvest.yaml").exists()


# ------------------------------------------------------------------- review round 2 of #471


@pytest.mark.parametrize(("cell", "counts", "said"), [
    ("2 (1.5%)", None, "a count below"), ("2/40", ("n",), "a count below"),
    ("n=2", ("n",), "a cell no count can be read from"),
    ("2 patients", ("n",), "a count below"),
])  # fmt: skip
def test_a_count_written_as_text_refuses_the_receipt(
    project: Path, cell: str, counts, said: str
) -> None:
    """The review's case: under a minimum of 5, a count column holding "2 (1.5%)" is held
    to `deposit`'s `count_in_cell`, and one it cannot read is refused."""
    _minimum(project, 5)
    _site_output(project, ["group,n", f'A,"{cell}"'], counts=counts)
    with pytest.raises(HarvestError, match=said):
        make_receipt(load_project(project)[0], "site-a")


def test_a_count_written_as_text_that_is_large_enough_passes(project: Path) -> None:
    _minimum(project, 5)
    _site_output(project, ["group,n", 'A,"40 (12.5%)"'], counts=("n",))
    make_receipt(load_project(project)[0], "site-a")


def test_a_bound_count_with_a_unit_in_a_count_column_is_held_by_g2(project: Path) -> None:
    from manuscript_guard.gates.custodian import check_small_cells

    _minimum(project, 5)
    _write_script(project)
    (project / "output").mkdir()
    (project / "output" / "est.csv").write_bytes(b"group,n\nWomen,2 patients\n")
    harvest_entry(project, Entry("est", "output/est.csv", "analysis/02_est.py",
                                 row_key="group", counts=("n",)))  # fmt: skip
    main_md = project / "manuscript" / "main.md"
    main_md.write_text(main_md.read_text("utf-8") + "\n\nWe saw {{results.est.women.n}}.\n",
                       encoding="utf-8")  # fmt: skip
    project_, _ = load_project(project)
    found = check_small_cells(project_, load_namespace(project_)[1]).findings
    assert [f.code for f in found] == ["count-below-minimum"]


def test_an_emitted_results_file_of_the_key_leaves_no_entry_behind(project: Path) -> None:
    _write_script(project)
    (project / "output").mkdir()
    (project / "output" / "est.csv").write_bytes(("\n".join(ROWS) + "\n").encode("utf-8"))
    assert main(["harvest", "output/est.csv", "--script", "analysis/02_est.py", "--key",
                 "01_disproportionality", "--row-key", "group",
                 "--path", str(project)]) == 2  # fmt: skip
    assert not (project / "harvest.yaml").exists()


def test_a_flag_that_describes_an_entry_with_no_output_is_refused(project: Path, capsys) -> None:
    harvest_entry(project, _harvested(project))
    assert main(["harvest", "--counts", "n", "output/est.csv", "--path", str(project)]) == 2
    assert "--counts describes an entry to add" in capsys.readouterr().err


def test_an_integer_too_long_to_read_is_refused() -> None:
    with pytest.raises(HarvestError, match="too long a number"):
        read_output(b"n\n" + b"9" * 5000 + b"\n", ".csv", Entry("t", "o.csv", "s.py"))


def test_deposit_counts_only_the_cells_of_count_columns_of_a_harvested_table() -> None:
    from manuscript_guard.deposit.counts import _cells

    document = {"provenance": {"harvested": {"spec": {"counts": ["n"]}}},
                "tables": {"t": {"columns": ["group", "n", "df"], "rows": [["A", "3", "2"]]}}}
    assert _cells(document) == [("table t, row 1, column 2", 3)]
    del document["provenance"]
    assert len(_cells(document)) == 2
