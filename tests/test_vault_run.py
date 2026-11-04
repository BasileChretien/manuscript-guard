"""`em.vault_input`, `vault run` and `vault release`: the analysis run on the data held in the
vault, in a copy of the project inside it, and what it wrote released on a person's word;
and what G1 says of results from data unregistered, changed or unreleased.

The vault is a folder beside the project in `tmp_path`, never inside it, as in
`tests/test_vault.py`. A terminal is stood in for by patching `person._at_terminal` and the
deposit's `ask_at_terminal`; without the patch, standard input under pytest is no terminal.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import _run_gates, main
from manuscript_guard.contracts._schema import validate
from manuscript_guard.emit import Emitter, sha256_of
from manuscript_guard.vault import RUN_VARIABLE, VARIABLE, checked_label, person
from manuscript_guard.vault.summary import r_failure

MINIMUM = "\ncustodian:\n  minimum_cell_count: 5\n"
AUTHORS = """schema: manuscript-guard/authors/1
affiliations:
  - id: a1
    text: "Department, Institution, City, Country"
authors:
  - given: Ada
    family: Lovelace
    affiliations: [a1]
    corresponding: true
  - given: Grace
    family: Hopper
    affiliations: [a1]
"""
ROWS = "".join(f"P{n:04d},{30 + n},{'F' if n % 2 else 'M'}\n" for n in range(1, 13))
#: The analysis, read on the vault: what it reads is the file `vault_input` gives.
SCRIPT = """import csv
from manuscript_guard.emit import Emitter
em = Emitter(__file__)
path = em.vault_input("cohort.csv")
rows = list(csv.DictReader(open(path, encoding="utf-8")))
print("read", len(rows), "rows")
em.value("cohort.n", len(rows))
{extra}
em.write()
"""


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-c", "core.fsmonitor=false", *arguments], cwd=root,
                   capture_output=True, text=True, check=False)  # fmt: skip


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    assert main(["init", str(root)]) == 0
    with (root / "paper.yaml").open("a", encoding="utf-8") as file:
        file.write(MINIMUM)
    (root / "authors.yaml").write_text(AUTHORS, encoding="utf-8")
    (root / "analysis").mkdir(exist_ok=True)
    if shutil.which("git"):
        _git(root, "init", "-q")
    return root


@pytest.fixture
def data(tmp_path: Path) -> Path:
    folder = tmp_path / "held"
    folder.mkdir()
    (folder / "cohort.csv").write_text("id,age,sex\n" + ROWS, encoding="utf-8")
    return folder


@pytest.fixture
def vault(paper: Path, data: Path) -> Path:
    assert main(["vault", "init", str(data), "cohort.csv", "--as", "Ada Lovelace",
                 "--path", str(paper)]) == 0  # fmt: skip
    return data


def _script(paper: Path, extra: str = "", name: str = "01_model.py") -> Path:
    path = paper / "analysis" / name
    path.write_text(SCRIPT.format(extra=extra), encoding="utf-8")
    return path


@pytest.fixture
def terminal(monkeypatch):
    """A person at a terminal, answering in turn what `answers` holds."""
    from manuscript_guard.deposit.remote import command

    answers: list[str] = []
    asked: list[str] = []
    monkeypatch.setattr(person, "_at_terminal", lambda: True)

    def ask(prompt: str) -> str | None:
        asked.append(prompt)
        return answers.pop(0) if answers else None

    monkeypatch.setattr(command, "ask_at_terminal", ask)
    return answers, asked


def vault_cli(paper: Path, *words: str) -> int:
    return main(["vault", *words, "--path", str(paper)])


def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()
            and ".git" not in path.relative_to(root).parts}  # fmt: skip


def _ran(paper: Path, vault: Path, terminal, extra: str = "") -> str:
    """A run made and finished; its id."""
    answers, _asked = terminal
    _script(paper, extra)
    answers.append("y")
    assert vault_cli(paper, "run") == 0
    runs = sorted((vault / "outbox").iterdir())
    return runs[-1].name


def _summary(paper: Path) -> dict:
    path = paper / ".manuscript-guard" / "vault" / "last-run.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert validate(document, "vault-run", path).ok
    return document


# ---------------------------------------------------------------------------- vault_input


@pytest.mark.parametrize("label", ["../cohort.csv", "/cohort.csv", "C:/cohort.csv",
                                   "a\\cohort.csv", "", "a//b.csv", "./cohort.csv", "a/"])
def test_a_label_that_leaves_the_vault_or_is_spelt_two_ways_is_refused(label: str) -> None:
    with pytest.raises(ValueError, match="vault_input"):
        checked_label(label)
    assert checked_label("visits/2020.csv") == "visits/2020.csv"


def test_outside_a_run_the_synthetic_copy_is_read_and_declared_synthetic(
    paper: Path, vault: Path, monkeypatch
) -> None:
    monkeypatch.delenv(VARIABLE, raising=False)
    script = _script(paper)
    em = Emitter(script, root=paper)
    with pytest.raises(FileNotFoundError, match="vault synthesize"):
        em.vault_input("cohort.csv")
    copy = paper / "data" / "synthetic" / "cohort.csv"
    copy.parent.mkdir(parents=True)
    copy.write_text("id,age,sex\nS1,40,F\n", encoding="utf-8")
    assert em.vault_input("cohort.csv") == copy
    em.value("cohort.n", 1)
    document = json.loads(em.write().read_text(encoding="utf-8"))
    assert document["provenance"]["inputs"] == [
        {"path": "data/synthetic/cohort.csv", "sha256": document["provenance"]["inputs"][0][
            "sha256"], "raw_sha256": sha256_of(copy), "bytes": copy.stat().st_size,
         "synthetic": True}]  # fmt: skip
    assert "vault" not in document["provenance"]


def test_under_a_run_the_real_file_is_read_and_recorded_by_its_label(
    paper: Path, vault: Path, monkeypatch
) -> None:
    monkeypatch.setenv(VARIABLE, str(vault))
    monkeypatch.setenv(RUN_VARIABLE, "20261104-120000")
    em = Emitter(_script(paper), root=paper)
    assert em.vault_input("cohort.csv") == vault / "cohort.csv"
    with pytest.raises(FileNotFoundError, match="vault:visits.csv"):
        em.vault_input("visits.csv")
    em.value("cohort.n", 12)
    written = em.write()
    document = json.loads(written.read_text(encoding="utf-8"))
    registry = yaml.safe_load((paper / "design" / "vault.yaml").read_text(encoding="utf-8"))
    entry = registry["files"][0]
    assert document["provenance"]["inputs"] == [
        {"path": "vault:cohort.csv", "sha256": entry["sha256"], "raw_sha256": entry["raw_sha256"],
         "bytes": entry["bytes"], "restricted": True, "vault": True}]  # fmt: skip
    assert document["provenance"]["vault"] == {"run": "20261104-120000", "released": False}
    assert validate(document, "results", written).ok
    # Where the data are is in no result.
    assert str(vault) not in written.read_text(encoding="utf-8")
    assert vault.name not in written.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------- run


def test_run_is_refused_without_a_terminal_and_nothing_is_run(paper: Path, vault: Path) -> None:
    _script(paper)
    before = _files(paper)
    assert vault_cli(paper, "run") == 2
    assert not (vault / ".runs").exists() and not (vault / "outbox").exists()
    assert _files(paper) == before


def test_run_is_refused_where_no_vault_is_registered(paper: Path, terminal) -> None:
    _script(paper)
    assert vault_cli(paper, "run") == 2


def test_run_lists_the_scripts_changed_and_runs_nothing_on_a_no(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    answers, asked = terminal
    _script(paper)
    (paper / "analysis" / "helpers").mkdir()
    (paper / "analysis" / "helpers" / "read.py").write_text("X = 1\n", encoding="utf-8")
    answers.append("n")
    assert vault_cli(paper, "run") == 0
    said = capsys.readouterr().out
    assert "analysis/01_model.py: no run on the vault has been released yet" in said
    # A helper is listed as changed, and not run.
    assert "analysis/helpers/read.py: no run on the vault has been released yet" in said
    assert "  analysis/helpers/read.py\n" not in said.split("read each before")[0]
    assert asked == ["Run them on the data held in the vault? [y/N] "]
    assert "nothing run" in said
    assert not (vault / ".runs").exists()


def test_a_run_works_in_the_vault_and_writes_nothing_to_the_project_but_its_summary(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    _script(paper)
    before = _files(paper)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "run") == 0
    said = capsys.readouterr()
    # What the script printed is streamed to the person's terminal, and kept in the vault.
    assert "read 12 rows" in said.out
    (run,) = [one.name for one in (vault / ".runs").iterdir()]
    assert "read 12 rows" in (vault / ".runs" / run / "log.txt").read_text(encoding="utf-8")
    outbox = vault / "outbox" / run
    # The plan frozen at the first results is written by the run too, and waits with them.
    assert sorted(_files(outbox)) == ["design/plan.frozen.yaml", "results/01_model.json",
                                      "results/01_model.json.sha256"]
    fragment = json.loads((outbox / "results" / "01_model.json").read_text(encoding="utf-8"))
    assert fragment["values"]["cohort.n"]["value"] == 12
    assert fragment["provenance"]["vault"] == {"run": run, "released": False}
    # The copy of the project is gone; its log and record stay.
    assert not (vault / ".runs" / run / paper.name).exists()
    assert (vault / ".runs" / run / "run.json").is_file()
    after = _files(paper)
    assert sorted(set(after) - set(before)) == [".manuscript-guard/vault/last-run.json"]
    assert {name: after[name] for name in before} == before
    summary = _summary(paper)
    assert summary["run"] == run and summary["failed"] is None and summary["outbox"] is True
    assert summary["scripts"] == [{"path": "analysis/01_model.py", "exit_code": 0}]


def test_a_failed_run_tells_the_agent_where_and_never_what(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    """The summary holds the class and the frames in the project's code, and no message or
    value: a value of the data planted in the exception's message, in a KeyError's key and
    in the name of a class made while the script ran is in none of it."""
    profile = paper / "profiles" / "data" / "cohort.csv.profile.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps({"columns": [{"name": "age"}]}), encoding="utf-8")
    cases = {
        "message": ("raise ValueError('PLANTED-' + rows[3]['id'])", "ValueError", None),
        "key": ("raise KeyError('PLANTED-' + rows[3]['id'])", "KeyError", None),
        "column": ("raise KeyError('age')", "KeyError", "age"),
        "class": ("raise type('PLANTED' + rows[3]['id'], (Exception,), {})()", None, None),
    }
    answers, _asked = terminal
    for name, (extra, kind, column) in cases.items():
        _script(paper, extra)
        answers.append("y")
        assert vault_cli(paper, "run") == 1, name
        text = (paper / ".manuscript-guard" / "vault" / "last-run.json").read_text("utf-8")
        assert "PLANTED" not in text and "P0004" not in text, name
        failed = _summary(paper)["failed"]
        assert failed["path"] == "analysis/01_model.py" and failed["exit_code"] == 1
        assert failed.get("class") == kind, name
        assert failed.get("column") == column, name
        line = SCRIPT.format(extra=extra).splitlines().index(extra) + 1
        assert failed["frames"] == [{"path": "analysis/01_model.py", "line": line,
                                     "function": "<module>"}], name  # fmt: skip
    # The person saw it all; the vault keeps it; the outbox got nothing.
    assert "PLANTED-P0004" in capsys.readouterr().err
    assert not (vault / "outbox").exists()


def test_r_calls_keep_only_the_names_the_code_holds(tmp_path: Path) -> None:
    work = tmp_path / "copy"
    (work / "analysis").mkdir(parents=True)
    (work / "analysis" / "01.R").write_text("helper <- function(x) stop('no')\nhelper(1)\n",
                                            encoding="utf-8")  # fmt: skip
    tail = (b"Error in helper(1) : PLANTED 1953-04-02\n"
            b"Calls: helper -> Smith1953 -> stop\nExecution halted\n")
    failed = r_failure(None, work, "analysis/01.R", 1, tail)
    # `stop` is a word of the script; the name made of the data is not.
    assert failed == {"path": "analysis/01.R", "exit_code": 1, "calls": ["helper", "stop"]}


# ---------------------------------------------------------------------------- release


def test_release_is_refused_without_a_terminal(paper: Path, vault: Path, terminal,
                                              monkeypatch) -> None:  # fmt: skip
    run = _ran(paper, vault, terminal)
    monkeypatch.setattr(person, "_at_terminal", lambda: False)
    before = _files(paper)
    assert vault_cli(paper, "release", run, "--as", "Ada Lovelace") == 2
    assert _files(paper) == before


def test_release_puts_the_results_in_the_project_and_records_it(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    run = _ran(paper, vault, terminal)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    said = capsys.readouterr().out
    assert said.count("read by the coding agent, and through it by its provider") >= 2
    released = paper / "results" / "01_model.json"
    document = json.loads(released.read_text(encoding="utf-8"))
    assert document["provenance"]["vault"] == {"run": run, "released": True}
    record_path = paper / "approvals" / "vault-releases" / f"{run}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert validate(record, "vault-release", record_path).ok
    assert record["released_by"] == "Ada Lovelace" and record["role"] == "author"
    frozen = paper / "design" / "plan.frozen.yaml"
    assert record["files"] == [
        {"path": "results/01_model.json", "sha256": sha256_of(released),
         "bytes": released.stat().st_size, "kind": "results"},
        # The plan the first results froze holds the project's plan and nothing else.
        {"path": "design/plan.frozen.yaml", "sha256": sha256_of(frozen),
         "bytes": frozen.stat().st_size, "kind": "plan"}]
    registry = yaml.safe_load((paper / "design" / "vault.yaml").read_text(encoding="utf-8"))
    assert record["inputs"] == [{"label": "cohort.csv",
                                 "sha256": registry["files"][0]["sha256"]}]  # fmt: skip
    assert [one["path"] for one in record["scripts"]] == ["analysis/01_model.py"]
    assert record["ran"] == ["analysis/01_model.py"]
    # G1 has nothing to say of it, and the digest beside it is the file's.
    report, *_rest = _run_gates(paper, stage="internal-review")
    assert not [f for f in report.findings if f.code.startswith("vault-")
                or f.code in ("results-edited", "input-missing")]  # fmt: skip
    # A second release of the run is refused.
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 2
    # And the next run lists nothing changed, or the script once it changes.
    answers.append("n")
    assert vault_cli(paper, "run") == 0
    assert "No analysis script changed since the run released last." in capsys.readouterr().out
    _script(paper, "print('changed')")
    answers.append("n")
    assert vault_cli(paper, "run") == 0
    assert f"analysis/01_model.py: changed since run {run}" in capsys.readouterr().out


@pytest.mark.parametrize("run", ["../held", "20261104-120000/..", "x"])
def test_release_names_a_run_by_its_id_and_nothing_else(paper: Path, vault: Path, terminal,
                                                         run: str) -> None:  # fmt: skip
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 2
    finding = f"VAULT/custodian/small-counts/{run}"
    assert main(["sign", str(paper), "--as", "Lovelace", "--finding", finding]) == 2


def test_a_results_file_the_release_cannot_read_refuses_it(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    run = _ran(paper, vault, terminal)
    (vault / "outbox" / run / "results" / "01_model.json").write_text("{", encoding="utf-8")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 1
    assert "not a results file it can read" in capsys.readouterr().err
    assert not (paper / "approvals" / "vault-releases").exists()


def test_release_says_no_on_a_no(paper: Path, vault: Path, terminal) -> None:
    run = _ran(paper, vault, terminal)
    answers, _asked = terminal
    answers.append("")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    assert not (paper / "results" / "01_model.json").exists()
    assert not (paper / "approvals" / "vault-releases").exists()


def test_who_releases_is_the_custodian_where_one_is_named(
    paper: Path, vault: Path, terminal
) -> None:
    run = _ran(paper, vault, terminal)
    answers, _asked = terminal
    assert vault_cli(paper, "release", run, "--as", "Nobody") == 2
    authors = paper / "authors.yaml"
    authors.write_text(AUTHORS + "roles:\n  data_custodian: Hopper\n", encoding="utf-8")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 2
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Grace Hopper") == 0
    record = json.loads((paper / "approvals" / "vault-releases" / f"{run}.json").read_text(
        encoding="utf-8"))  # fmt: skip
    assert (record["released_by"], record["role"]) == ("Grace Hopper", "data_custodian")


def test_a_small_count_refuses_the_release_until_the_custodian_signs_that_list_off(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    run = _ran(paper, vault, terminal, "em.value('cohort.deaths', 3)")
    answers, _asked = terminal
    (paper / "authors.yaml").write_text(AUTHORS + "roles:\n  data_custodian: Hopper\n",
                                        encoding="utf-8")  # fmt: skip
    assert vault_cli(paper, "release", run, "--as", "Hopper") == 1
    # The person at the terminal is shown the count.
    assert "results/01_model.json: cohort.deaths is 3" in capsys.readouterr().err
    assert not (paper / "results" / "01_model.json").exists()
    finding = f"VAULT/custodian/small-counts/{run}"
    assert main(["sign", str(paper), "--as", "Hopper", "--finding", finding]) == 0
    signed = next((paper / "approvals" / "sign-offs").glob("vault-custodian-small-counts*"))
    # The sign-off is kept in the project: it says where the count is, not the count.
    assert "cohort.deaths is below" in signed.read_text(encoding="utf-8")
    assert "is 3" not in signed.read_text(encoding="utf-8")
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Hopper") == 0
    record = json.loads((paper / "approvals" / "vault-releases" / f"{run}.json").read_text(
        encoding="utf-8"))  # fmt: skip
    assert record["signed_off"] == [finding]


def test_where_the_custodian_restricts_sending_the_release_waits_for_their_sign_off(
    paper: Path, vault: Path, terminal
) -> None:
    run = _ran(paper, vault, terminal)
    answers, _asked = terminal
    with (paper / "paper.yaml").open("a", encoding="utf-8") as file:
        file.write("  restricts_sending: true\n")
    (paper / "authors.yaml").write_text(AUTHORS + "roles:\n  data_custodian: Hopper\n",
                                        encoding="utf-8")  # fmt: skip
    assert vault_cli(paper, "release", run, "--as", "Hopper") == 1
    finding = "VAULT/custodian/agent-reads-releases"
    assert main(["sign", str(paper), "--as", "Hopper", "--finding", finding]) == 0
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Hopper") == 0


def test_a_column_of_one_value_per_row_is_warned_of(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    # Text cells hold no digit: the emitter refuses a number typed into a table.
    table = ("letters = lambda text: ''.join(chr(65 + int(c)) for c in text[1:])\n"
             "em.table('ages', ['Row', 'Id'], [['x' + letters(row['id']), letters(row['id'])] "
             "for row in rows], quoted=False)")
    run = _ran(paper, vault, terminal, table)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    said = capsys.readouterr().out
    assert "column 'Id': one value per row, over 12 rows" in said
    record = json.loads((paper / "approvals" / "vault-releases" / f"{run}.json").read_text(
        encoding="utf-8"))  # fmt: skip
    assert any("one value per row" in one for one in record["warnings"])


def test_a_file_no_check_reads_is_released_only_where_its_path_is_typed(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    figure = ("import pathlib\npathlib.Path('figures').mkdir(exist_ok=True)\n"
              "pathlib.Path('figures/scatter.png').write_bytes(b'points')\n"
              "pathlib.Path('figures/other.png').write_bytes(b'more')")
    run = _ran(paper, vault, terminal, figure)
    answers, asked = terminal
    # A "y" is not the file's path, and the release is then declined.
    answers += ["y", "", "n"]
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    said = capsys.readouterr().out
    assert "No check reads these files" in said
    assert "  results/01_model.json\n" in said and "  figures/" not in said.split("into ")[-1]
    assert not (paper / "figures" / "scatter.png").exists()
    assert not (paper / "results" / "01_model.json").exists()
    answers += ["", "figures/scatter.png", "y"]
    asked.clear()
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    assert [one for one in asked if "type its path" in one] == [
        "  figures/other.png: type its path to release it, or press Enter to keep it in the "
        "vault: ",
        "  figures/scatter.png: type its path to release it, or press Enter to keep it in the "
        "vault: "]  # fmt: skip
    assert (paper / "figures" / "scatter.png").read_bytes() == b"points"
    assert not (paper / "figures" / "other.png").exists()
    record = json.loads((paper / "approvals" / "vault-releases" / f"{run}.json").read_text(
        encoding="utf-8"))  # fmt: skip
    assert {(one["path"], one["kind"]) for one in record["files"]} == {
        ("results/01_model.json", "results"), ("design/plan.frozen.yaml", "plan"),
        ("figures/scatter.png", "named")}


def test_a_harvested_output_is_held_to_the_custodian_as_a_receipt_holds_it(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    write = ("import pathlib\npathlib.Path('output').mkdir(exist_ok=True)\n"
             "pathlib.Path('output/est.csv').write_text('group,n\\nwomen,120\\nmen,2\\n')")
    (paper / "harvest.yaml").write_text(
        "entries:\n  - key: est\n    output: output/est.csv\n"
        "    script: analysis/01_model.py\n    inputs: []\n    row_key: group\n", encoding="utf-8")
    run = _ran(paper, vault, terminal, write)
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 1
    assert "output/est.csv: est.men.n is 2" in capsys.readouterr().err
    assert not (paper / "output").exists()
    # A count the custodian allows goes in as a harvested output.
    write = write.replace("men,2", "men,9")
    run = _ran(paper, vault, terminal, write)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    record = json.loads((paper / "approvals" / "vault-releases" / f"{run}.json").read_text(
        encoding="utf-8"))  # fmt: skip
    assert ("output/est.csv", "harvested") in {(f["path"], f["kind"]) for f in record["files"]}


# ---------------------------------------------------------------------------- G1


def _vault_codes(paper: Path, stage: str) -> dict[str, str]:
    report, *_rest = _run_gates(paper, stage=stage)
    return {f.code: f.severity for f in report.findings if f.code.startswith("vault-")}


def test_a_fragment_copied_from_the_outbox_by_hand_is_unreleased(
    paper: Path, vault: Path, terminal
) -> None:
    run = _ran(paper, vault, terminal)
    outbox = vault / "outbox" / run / "results"
    for name in ("01_model.json", "01_model.json.sha256"):
        shutil.copyfile(outbox / name, paper / "results" / name)
    assert _vault_codes(paper, "drafting") == {"vault-result-unreleased": "warn"}
    assert _vault_codes(paper, "internal-review") == {"vault-result-unreleased": "fail"}
    report, *_rest = _run_gates(paper, stage="drafting")
    assert "input-missing" not in {f.code for f in report.findings}


def test_a_released_fragment_edited_afterwards_is_unreleased(
    paper: Path, vault: Path, terminal
) -> None:
    from manuscript_guard.emit import write_digest

    run = _ran(paper, vault, terminal)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    released = paper / "results" / "01_model.json"
    document = json.loads(released.read_text(encoding="utf-8"))
    document["values"]["cohort.n"]["value"] = 13
    released.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    write_digest(released)
    report, *_rest = _run_gates(paper, stage="internal-review")
    found = [f for f in report.findings if f.code == "vault-result-unreleased"]
    assert [f.severity for f in found] == ["fail"]
    assert "changed since" in found[0].message


def test_results_from_an_extract_other_than_the_registered_one_fail(
    paper: Path, vault: Path, terminal
) -> None:
    run = _ran(paper, vault, terminal)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    (vault / "cohort.csv").write_text("id,age,sex\n" + ROWS + "P9999,50,F\n", encoding="utf-8")
    assert vault_cli(paper, "init", "--refresh", "--as", "Ada Lovelace") == 0
    assert _vault_codes(paper, "design") == {"vault-input-changed": "fail"}
    registry = paper / "design" / "vault.yaml"
    document = yaml.safe_load(registry.read_text(encoding="utf-8"))
    document["files"] = []
    registry.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert _vault_codes(paper, "design") == {"vault-input-unregistered": "fail"}


# ---------------------------------------------------------------------------- R


R_SCRIPT = """
if (!requireNamespace("jsonlite", quietly = TRUE) || !requireNamespace("digest", quietly = TRUE)) {
  cat("MISSING_DEPS"); quit(status = 3)
}
source("%(emit)s")
em <- mg_emitter("%(root)s/analysis/01_r.R")
path <- em$vault_input("cohort.csv")
em$value("cohort.n", nrow(read.csv(path)))
refused <- tryCatch({ em$vault_input("../cohort.csv"); "no" }, error = function(e) "yes")
if (refused != "yes") quit(status = 4)
em$write()
"""


@pytest.mark.parametrize("under_a_run", [True, False])
def test_the_r_emitter_reads_the_vault_as_python_does(
    paper: Path, vault: Path, monkeypatch, tmp_path: Path, under_a_run: bool
) -> None:
    from test_r_emitter import EMIT_R, RSCRIPT

    if RSCRIPT is None:
        pytest.skip("R is not installed")
    copy = paper / "data" / "synthetic" / "cohort.csv"
    copy.parent.mkdir(parents=True)
    copy.write_text("id,age,sex\nS1,40,F\n", encoding="utf-8")
    (paper / "analysis" / "01_r.R").write_text("# reads the vault\n", encoding="utf-8")
    (paper / "analysis" / "01_py.py").write_text("# reads the vault\n", encoding="utf-8")
    if under_a_run:
        monkeypatch.setenv(VARIABLE, str(vault))
        monkeypatch.setenv(RUN_VARIABLE, "20261104-120000")
    else:
        monkeypatch.delenv(VARIABLE, raising=False)
        monkeypatch.delenv(RUN_VARIABLE, raising=False)
    script = tmp_path / "run.R"
    script.write_text(R_SCRIPT % {"emit": EMIT_R.as_posix(), "root": paper.as_posix()},
                      encoding="utf-8")  # fmt: skip
    out = subprocess.run([RSCRIPT, "--vanilla", str(script)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", cwd=paper)  # fmt: skip
    if out.returncode == 3:
        pytest.skip("R packages jsonlite and digest are not installed")
    assert out.returncode == 0, out.stdout + out.stderr
    from_r = json.loads((paper / "results" / "01_r.json").read_text(encoding="utf-8"))
    em = Emitter(paper / "analysis" / "01_py.py", root=paper)
    em.vault_input("cohort.csv")
    em.value("cohort.n", 1)
    from_python = json.loads(em.write().read_text(encoding="utf-8"))
    assert from_r["provenance"]["inputs"] == from_python["provenance"]["inputs"]
    assert from_r["provenance"].get("vault") == from_python["provenance"].get("vault")
    assert validate(from_r, "results", paper / "results" / "01_r.json").ok
