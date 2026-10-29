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
    assert values["est.men.n"] == {"value": None, "display": "<5", "quoted": False}
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
