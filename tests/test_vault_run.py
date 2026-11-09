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
    _without_starter(paper)
    return data


def _without_starter(paper: Path) -> None:
    """These tests run the analysis alone: the profile script `vault init` starts (Task F,
    part 3) is taken out again, and tested with the profile and once below with a run."""
    (paper / "analysis" / "00_profile.py").unlink(missing_ok=True)


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


def test_the_profile_script_vault_init_starts_runs_and_its_profile_waits(
    paper: Path, data: Path, terminal
) -> None:
    """Parts 2 and 3 of Task F together: `vault init` starts analysis/00_profile.py, `vault
    run` runs it on the data with the rest, and the profile waits in the outbox for a
    person's release."""
    assert vault_cli(paper, "init", str(data), "cohort.csv", "--as", "Ada Lovelace") == 0
    assert (paper / "analysis" / "00_profile.py").is_file()
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "run") == 0
    (run,) = [one.name for one in (data / ".runs").iterdir()]
    assert "profiles/data/cohort.csv.profile.json" in _files(data / "outbox" / run)


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
    assert not (vault / ".runs" / run / "copy").exists()
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
    texts = {"analysis/01.R": (work / "analysis" / "01.R").read_text(encoding="utf-8")}
    failed = r_failure(texts, "analysis/01.R", 1, tail)
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
    assert "No script changed since the run released last." in capsys.readouterr().out
    _script(paper, "print('changed')")
    answers.append("n")
    assert vault_cli(paper, "run") == 0
    assert f"analysis/01_model.py: changed since run {run}" in capsys.readouterr().out


def test_a_release_brings_the_run_s_first_reads_into_the_project(
    paper: Path, vault: Path, terminal
) -> None:
    """Round 1 of PR 2b (Basile, 2026-11-09): the run kept its record of first reads in the
    vault's copy, which no release brought back, so held-out data validated in the vault
    read as never read. The release merges it, entries only added."""
    from manuscript_guard.emit import FIRST_READS

    plan = paper / "design" / "plan.md"
    plan.write_text(plan.read_text(encoding="utf-8") + "\n```yaml\nheld_out:\n"
                    "  - input: vault:cohort.csv\n    validated_by: analysis/01_model.py\n```\n",
                    encoding="utf-8")  # fmt: skip
    run = _ran(paper, vault, terminal)
    assert not (paper / FIRST_READS).exists(), "written in the vault's copy, not here"
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    record = json.loads((paper / FIRST_READS).read_text(encoding="utf-8"))
    assert [(read["script"], read["input"]) for read in record["reads"]] == [
        ("analysis/01_model.py", "vault:cohort.csv")]  # fmt: skip
    released = json.loads((paper / "approvals" / "vault-releases" / f"{run}.json")
                          .read_text(encoding="utf-8"))  # fmt: skip
    assert "first reads" in [one["kind"] for one in released["files"]]
    report, *_rest = _run_gates(paper, stage="submission")
    assert not [f for f in report.findings if f.code in ("held-out-unread",
                                                         "held-out-order-unknown") and
                f.severity != "info"]  # fmt: skip


def _held_out_in_the_vault(paper: Path) -> None:
    plan = paper / "design" / "plan.md"
    plan.write_text(plan.read_text(encoding="utf-8") + "\n```yaml\nheld_out:\n"
                    "  - input: vault:cohort.csv\n    validated_by: analysis/01_model.py\n```\n",
                    encoding="utf-8")  # fmt: skip


@pytest.mark.parametrize("since", ["a version's text retyped", "a driver"])
def test_a_record_of_reads_the_emitters_wrote_is_brought_back_whichever_text_or_script(
    paper: Path, vault: Path, terminal, since: str
) -> None:
    """Round 3 of PR 2b: the run's copy keeps the text the project's record holds for the
    plan's digest, which a person may have retyped, and that text is the project's already;
    and a driver that sources the validator runs it under its own name, while the results say
    which script wrote them."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.emit import FIRST_READS, FIRST_READS_SCHEMA, source_digest
    from manuscript_guard.vault.release import open_outbox

    _held_out_in_the_vault(paper)
    if since == "a version's text retyped":
        digest = source_digest(paper / "design" / "plan.md")
        (paper / FIRST_READS).write_text(json.dumps({"schema": FIRST_READS_SCHEMA, "plans": {
            digest: "## Retyped\n"}, "reads": []}), encoding="utf-8")  # fmt: skip
    run = _ran(paper, vault, terminal)
    if since == "a driver":
        manifest = vault / ".runs" / run / "run.json"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        manifest.write_text(json.dumps({**document, "ran": ["analysis/run_all.py"]}),
                            encoding="utf-8")  # fmt: skip
    assert open_outbox(load_project(paper)[0], vault, run).reads == [FIRST_READS.as_posix()]


def test_a_release_that_adds_no_first_read_lists_no_record_of_them(
    paper: Path, vault: Path, terminal
) -> None:
    """Round 2 of PR 2b: a second run of the same script adds no read, and its release said it
    released the project's whole record."""
    from manuscript_guard.emit import FIRST_READS

    _held_out_in_the_vault(paper)
    answers, _asked = terminal
    first = _ran(paper, vault, terminal)
    answers.append("y")
    assert vault_cli(paper, "release", first, "--as", "Lovelace") == 0
    before = (paper / FIRST_READS).read_bytes()
    second = _ran(paper, vault, terminal)
    answers.append("y")
    assert vault_cli(paper, "release", second, "--as", "Lovelace") == 0
    released = json.loads((paper / "approvals" / "vault-releases" / f"{second}.json")
                          .read_text(encoding="utf-8"))  # fmt: skip
    assert "first reads" not in [one["kind"] for one in released["files"]]
    assert (paper / FIRST_READS).read_bytes() == before


def test_a_release_is_refused_before_it_asks_where_the_project_s_record_does_not_read(
    paper: Path, vault: Path, terminal
) -> None:
    """Round 2 of PR 2b: the project's record was checked only after the person said yes,
    and the refusal was a traceback."""
    from manuscript_guard.emit import FIRST_READS

    _held_out_in_the_vault(paper)
    run = _ran(paper, vault, terminal)
    spoiled = '{"schema": "manuscript-guard/first-reads/1", "plans": {}, "reads": [{"script": 1}]}'
    (paper / FIRST_READS).write_text(spoiled, encoding="utf-8")
    answers, asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 2
    assert not [prompt for prompt in asked if "Release these" in prompt]
    assert (paper / FIRST_READS).read_text(encoding="utf-8") == spoiled


@pytest.mark.parametrize(
    "smuggle",
    [
        lambda record: record["reads"][0].update(rows=["P1,1"]),
        lambda record: record["plans"].update({"0" * 64: "P1,1,F"}),
        lambda record: record["reads"][0]["inputs"].append({"path": "P1,1", "sha256": "0" * 64}),
        lambda record: record["reads"][0].update(script="analysis/elsewhere.py"),
    ],
)
def test_a_record_of_first_reads_with_anything_the_emitters_do_not_write_stays_in_the_vault(
    paper: Path, vault: Path, terminal, smuggle
) -> None:
    """Round 2 of PR 2b: the record went out on a check of its shape alone, so a script in the
    vault could carry the data out in it. It goes only as the emitters write it: their keys,
    the run's scripts, the inputs its results declare and the project's plan."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.emit import FIRST_READS
    from manuscript_guard.vault.release import open_outbox

    _held_out_in_the_vault(paper)
    run = _ran(paper, vault, terminal)
    kept = vault / "outbox" / run / FIRST_READS
    record = json.loads(kept.read_text(encoding="utf-8"))
    assert open_outbox(load_project(paper)[0], vault, run).reads == [FIRST_READS.as_posix()]
    smuggle(record)
    kept.write_text(json.dumps(record), encoding="utf-8")
    box = open_outbox(load_project(paper)[0], vault, run)
    assert box.reads == [] and box.withheld == [FIRST_READS.as_posix()]
    assert FIRST_READS.as_posix() not in box.unread, "offered by its path, a copy replaces ours"


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
    assert "results/01_model.json holds a count below" in signed.read_text(encoding="utf-8")
    assert "is 3" not in signed.read_text(encoding="utf-8")
    assert "deaths" not in signed.read_text(encoding="utf-8")
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


# ---------------------------------------------------------------------------- round 1 of #490


def _junction(link: Path, target: Path) -> None:
    """A link to a folder: a junction on Windows, which needs no privilege, else a symlink."""
    import os

    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_a_word_the_run_wrote_into_the_copy_is_no_word_of_the_code(
    paper: Path, vault: Path, terminal
) -> None:
    """The words a name is held to, and the files a frame may name, are the project's as it
    stood before the run: a script that writes a helper named after a row and fails in it
    gets neither the name nor the frame into the summary."""
    extra = ("import pathlib, sys\nname = 'PLANTED' + rows[3]['id']\n"
             "pathlib.Path('analysis/zz_helper.py').write_text("
             "'def ' + name + '():\\n    raise ValueError()\\n')\n"
             "sys.path.insert(0, 'analysis')\nimport zz_helper\ngetattr(zz_helper, name)()")
    answers, _asked = terminal
    _script(paper, extra)
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    text = (paper / ".manuscript-guard" / "vault" / "last-run.json").read_text("utf-8")
    assert "PLANTED" not in text and "zz_helper" not in text
    failed = _summary(paper)["failed"]
    assert [frame["path"] for frame in failed["frames"]] == ["analysis/01_model.py"]


@pytest.mark.parametrize("module", ["builtins", "json"])
def test_a_class_that_says_it_is_of_another_module_is_not_named(
    paper: Path, vault: Path, terminal, module: str
) -> None:
    extra = (f"raise type('PLANTED' + rows[3]['id'], (Exception,), "
             f"{{'__module__': '{module}'}})()")
    answers, _asked = terminal
    _script(paper, extra)
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    text = (paper / ".manuscript-guard" / "vault" / "last-run.json").read_text("utf-8")
    assert "PLANTED" not in text
    failed = _summary(paper)["failed"]
    assert "class" not in failed and failed["exception"] == "not a builtin"


def test_an_r_calls_line_is_held_to_the_code_before_the_run(
    paper: Path, vault: Path, terminal, monkeypatch
) -> None:
    from test_r_emitter import EMIT_R, RSCRIPT

    from manuscript_guard import verify

    if RSCRIPT is None:
        pytest.skip("R is not installed")
    # Rscript may be installed and not on PATH, as on Windows.
    monkeypatch.setitem(verify.RUNNERS, ".r", [RSCRIPT, "--vanilla"])
    script = paper / "analysis" / "01_model.R"
    script.write_text(
        f'source("{EMIT_R.as_posix()}")\n'
        'em <- mg_emitter("analysis/01_model.R")\n'
        'rows <- read.csv(em$vault_input("cohort.csv"))\n'
        'word <- paste0("PLANTED", rows$id[4])\n'
        'writeLines(paste0(word, " <- function() 1"), "analysis/zz.R")\n'
        'message("Calls: ", word)\nquit(status = 1)\n', encoding="utf-8")
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    text = (paper / ".manuscript-guard" / "vault" / "last-run.json").read_text("utf-8")
    assert "PLANTED" not in text
    assert _summary(paper)["failed"]["exit_code"] == 1


def test_the_small_counts_sign_off_binds_the_outputs_and_says_no_count(
    paper: Path, vault: Path, terminal
) -> None:
    from manuscript_guard.contracts import load_project
    from manuscript_guard.vault.release import vault_signables

    run = _ran(paper, vault, terminal, "em.value('cohort.deaths', 3)")
    project, _report = load_project(paper)
    finding = f"VAULT/custodian/small-counts/{run}"
    (signable,), _notes = vault_signables(project, finding)
    said = " ".join(one.message for one in signable.findings)
    assert "deaths" not in said and " 3" not in said
    fragment = vault / "outbox" / run / "results" / "01_model.json"
    fragment.write_bytes(fragment.read_bytes() + b"\n")
    (again,), _notes = vault_signables(project, finding)
    assert again.digest != signable.digest


def test_the_scripts_listed_and_recorded_are_every_one_the_run_can_run(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    run = _ran(paper, vault, terminal)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    (paper / "R").mkdir()
    (paper / "R" / "utils.R").write_text("helper <- function() 1\n", encoding="utf-8")
    (paper / "tools.sh").write_text("echo hi\n", encoding="utf-8")
    (paper / "data" / "make.py").parent.mkdir(exist_ok=True)
    (paper / "data" / "make.py").write_text("# data, not code\n", encoding="utf-8")
    answers.append("y")
    assert vault_cli(paper, "run") == 0
    said = capsys.readouterr().out
    assert "R/utils.R: not in run" in said and "tools.sh: not in run" in said
    assert "data/make.py" not in said
    last = sorted((vault / ".runs").iterdir())[-1]
    record = json.loads((last / "run.json").read_text(encoding="utf-8"))
    assert {"R/utils.R", "tools.sh", "analysis/01_model.py"} <= {
        one["path"] for one in record["scripts"]}


def test_a_release_does_not_write_through_a_link(
    paper: Path, vault: Path, terminal, tmp_path: Path
) -> None:
    run = _ran(paper, vault, terminal)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    shutil.rmtree(paper / "results")
    _junction(paper / "results", elsewhere)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 2
    assert list(elsewhere.iterdir()) == []
    assert not (paper / "approvals" / "vault-releases").exists()


def test_a_link_the_run_makes_into_the_vault_moves_nothing_out_of_it(
    paper: Path, vault: Path, terminal
) -> None:
    extra = ("import os, pathlib\nheld = pathlib.Path(os.environ['MANUSCRIPT_GUARD_VAULT'])\n"
             "if os.name == 'nt':\n    import _winapi\n"
             "    _winapi.CreateJunction(str(held), 'reached')\n"
             "else:\n    os.symlink(held, 'reached', target_is_directory=True)")
    run = _ran(paper, vault, terminal, extra)
    assert (vault / "cohort.csv").is_file()
    assert not (vault / "outbox" / run / "reached").exists()


def test_runs_are_ordered_by_their_time_then_their_number(paper: Path) -> None:
    from manuscript_guard.vault.records import last_release

    folder = paper / "approvals" / "vault-releases"
    folder.mkdir(parents=True)
    for run in ("20261104-120000-9", "20261104-120000-10", "20261104-115959"):
        (folder / f"{run}.json").write_text(json.dumps({
            "schema": "manuscript-guard/vault-release/1", "run": run, "released_by": "Ada",
            "released_at": "2026-11-04T12:00:00+00:00", "ran_at": "2026-11-04T12:00:00+00:00",
            "scripts": [], "ran": [], "inputs": [], "files": [], "warnings": []}),
            encoding="utf-8")  # fmt: skip
    assert last_release(paper)["run"] == "20261104-120000-10"


# ---------------------------------------------------------------------------- round 2 of #490


def _failed(paper: Path) -> tuple[str, dict]:
    text = (paper / ".manuscript-guard" / "vault" / "last-run.json").read_text("utf-8")
    return text, _summary(paper)["failed"]


def test_a_module_the_script_makes_in_the_vault_names_no_class(
    paper: Path, vault: Path, terminal
) -> None:
    """Everything the wrapper writes is the script's to forge: it runs in the same process. A
    module whose file is a file of the vault, holding a class named after a row, is no module
    the tool can import itself (round 2 of #490)."""
    extra = ("import os, sys, types\nname = rows[3]['id']\n"
             "module = types.ModuleType('heldmod')\n"
             "module.__file__ = os.path.join(os.environ['MANUSCRIPT_GUARD_VAULT'], 'cohort.csv')\n"
             "sys.modules['heldmod'] = module\n"
             "kind = type(name, (Exception,), {'__module__': 'heldmod'})\n"
             "setattr(module, name, kind)\nraise kind()")
    answers, _asked = terminal
    _script(paper, extra)
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    text, failed = _failed(paper)
    assert "P0004" not in text
    assert "class" not in failed and failed["exception"] == "not a builtin"


@pytest.mark.parametrize("module", ["builtins", "json", "heldmod"])
def test_a_summary_the_script_writes_itself_names_no_class(
    paper: Path, vault: Path, terminal, module: str
) -> None:
    extra = ("import json, os, pathlib, sys\n"
             "where = pathlib.Path(os.environ['MANUSCRIPT_GUARD_VAULT'], '.runs', "
             "os.environ['MANUSCRIPT_GUARD_VAULT_RUN'], 'summary', '1.json')\n"
             "where.write_text(json.dumps({'class': rows[3]['id'], "
             f"'module': '{module}', 'module_file': str(pathlib.Path("
             "os.environ['MANUSCRIPT_GUARD_VAULT'], 'cohort.csv')), 'frames': [], "
             "'key': None}))\nsys.exit(1)")
    answers, _asked = terminal
    _script(paper, extra)
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    text, failed = _failed(paper)
    assert "P0004" not in text
    assert "class" not in failed


def test_r_calls_are_at_most_twenty(tmp_path: Path) -> None:
    names = [f"step{n}" for n in range(30)]
    texts = {"analysis/01.R": "".join(f"{name} <- function() 1\n" for name in names)}
    tail = ("Calls: " + " -> ".join(names) + "\nExecution halted\n").encode()
    failed = r_failure(texts, "analysis/01.R", 1, tail)
    assert failed["calls"] == names[-20:]


def test_an_edit_of_the_project_while_the_person_reads_refuses_the_run(
    paper: Path, vault: Path, monkeypatch, capsys
) -> None:
    """The copy is made first and listed; at the yes the project is digested again, and a
    script that differs from the copy's refuses the run: the person read the project's file,
    and the copy is what would run (the fix round of #490)."""
    from manuscript_guard.deposit.remote import command

    script = _script(paper, "print('planted')")
    monkeypatch.setattr(person, "_at_terminal", lambda: True)

    def ask(prompt: str) -> str:
        script.write_text(SCRIPT.format(extra=""), encoding="utf-8")
        return "y"

    monkeypatch.setattr(command, "ask_at_terminal", ask)
    assert vault_cli(paper, "run") == 2
    captured = capsys.readouterr()
    assert "planted" not in captured.out
    assert "changed while you read" in captured.err
    # The copy's own path is shown beside the script, to read what would run.
    assert f"{paper.name}/analysis/01_model.py" in captured.out.replace("\\", "/")
    assert not (vault / "outbox").exists()
    assert not (vault / ".runs").exists() or not any((vault / ".runs").iterdir())


@pytest.mark.parametrize(("extra", "kind"), [("raise KeyError('x')", "KeyError"),
                                             ("raise ValueError()", "ValueError"),
                                             ("1 / 0", "ZeroDivisionError"),
                                             ("import json\njson.loads('{')", None)])
def test_only_a_builtin_exception_is_named(paper: Path, vault: Path, terminal, extra: str,
                                           kind: str | None) -> None:  # fmt: skip
    answers, _asked = terminal
    _script(paper, extra)
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    _text, failed = _failed(paper)
    assert failed.get("class") == kind
    assert ("exception" in failed) is (kind is None)
    if kind is None:
        assert failed["exception"] == "not a builtin"


@pytest.mark.parametrize("module", ["test.autotest", "heldmod", "json"])
def test_the_tool_imports_nothing_the_summary_names(
    paper: Path, vault: Path, terminal, monkeypatch, module: str
) -> None:
    """A module the summary names is not imported by the tool, nor looked for: `test.autotest`
    runs CPython's tests when imported, and a module planted in a writable site-packages
    would be found (the fix round of #490)."""
    import importlib
    import importlib.util

    looked: list[str] = []
    real_find, real_import = importlib.util.find_spec, importlib.import_module
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a, **k: looked.append(name) or real_find(name, *a, **k))
    monkeypatch.setattr(importlib, "import_module",
                        lambda name, *a, **k: looked.append(name) or real_import(name, *a, **k))
    extra = ("import json, os, pathlib, sys\n"
             "where = pathlib.Path(os.environ['MANUSCRIPT_GUARD_VAULT'], '.runs', "
             "os.environ['MANUSCRIPT_GUARD_VAULT_RUN'], 'summary', '1.json')\n"
             f"where.write_text(json.dumps({{'class': 'SystemExit', 'module': '{module}', "
             "'frames': [], 'key': None}))\nsys.exit(1)")
    answers, _asked = terminal
    _script(paper, extra)
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    _text, failed = _failed(paper)
    assert "class" not in failed and failed["exception"] == "not a builtin"
    assert module not in looked and module.split(".")[0] not in looked


def test_a_results_folder_holding_compiled_files_runs_and_leaves_no_copy(
    paper: Path, vault: Path, terminal
) -> None:
    cache = paper / "results" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "a.pyc").write_bytes(b"compiled")
    answers, _asked = terminal
    _script(paper)
    answers.append("y")
    assert vault_cli(paper, "run") == 0
    (run,) = [one.name for one in (vault / ".runs").iterdir()]
    assert not (vault / ".runs" / run / "copy").exists()


def test_compiled_code_is_not_copied_nor_written_and_is_listed(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    cache = paper / "analysis" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "01_model.cpython-312.pyc").write_bytes(b"planted")
    (paper / "analysis" / "helper.pyc").write_bytes(b"sourceless")
    (paper / "lib.so").write_bytes(b"native")
    (paper / ".Renviron").write_text("X=1\n", encoding="utf-8")
    (paper / "_extensions" / "mine").mkdir(parents=True)
    (paper / "_extensions" / "mine" / "filter.lua").write_text("--\n", encoding="utf-8")
    answers, _asked = terminal
    _script(paper, "import os, sys\nprint('cache', os.path.exists('analysis/__pycache__'), "
                   "sys.dont_write_bytecode)")
    answers.append("y")
    assert vault_cli(paper, "run") == 0
    said = capsys.readouterr().out
    assert "cache False True" in said
    for path in ("analysis/helper.pyc", "lib.so", ".Renviron", "_extensions/mine/filter.lua"):
        assert f"{path}: no run on the vault has been released yet" in said, path
    assert "__pycache__" not in said


def test_a_stop_at_the_question_leaves_no_copy(paper: Path, vault: Path, monkeypatch) -> None:
    from manuscript_guard.deposit.remote import command

    _script(paper)
    monkeypatch.setattr(person, "_at_terminal", lambda: True)

    def stopped(prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(command, "ask_at_terminal", stopped)
    with pytest.raises(KeyboardInterrupt):
        vault_cli(paper, "run")
    assert not (vault / ".runs").exists() or not any((vault / ".runs").iterdir())


def test_a_no_leaves_no_copy_in_the_vault(paper: Path, vault: Path, terminal) -> None:
    answers, _asked = terminal
    _script(paper)
    answers.append("n")
    assert vault_cli(paper, "run") == 0
    assert not (vault / ".runs").exists() or not any((vault / ".runs").iterdir())


def test_a_script_named_or_read_by_a_runner_is_listed_wherever_it_is(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    (paper / "data").mkdir(exist_ok=True)
    named = paper / "data" / "run_me.py"
    named.write_text(SCRIPT.format(extra=""), encoding="utf-8")
    (paper / ".Rprofile").write_text("options(digits = 3)\n", encoding="utf-8")
    (paper / "_quarto.yml").write_text("project: {}\n", encoding="utf-8")
    answers, _asked = terminal
    answers.append("n")
    assert vault_cli(paper, "run", "data/run_me.py") == 0
    said = capsys.readouterr().out
    for path in ("data/run_me.py", ".Rprofile", "_quarto.yml"):
        assert f"{path}: no run on the vault has been released yet" in said, path


def test_an_outbox_holding_a_link_is_refused(
    paper: Path, vault: Path, terminal, tmp_path: Path
) -> None:
    run = _ran(paper, vault, terminal)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "rows.csv").write_text("P0001,31\n", encoding="utf-8")
    _junction(vault / "outbox" / run / "linked", elsewhere)
    answers, _asked = terminal
    answers += ["linked/rows.csv", "y"]
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 2
    assert not (paper / "linked").exists()
    assert not (paper / "approvals" / "vault-releases").exists()


def test_a_run_refuses_a_results_folder_that_is_a_link(
    paper: Path, vault: Path, terminal, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "kept.json").write_text("{}", encoding="utf-8")
    shutil.rmtree(paper / "results")
    _junction(paper / "results", elsewhere)
    answers, _asked = terminal
    _script(paper)
    answers.append("y")
    assert vault_cli(paper, "run") == 2
    assert (elsewhere / "kept.json").read_text(encoding="utf-8") == "{}"
    assert not (vault / ".runs").exists() or not any((vault / ".runs").iterdir())


# ---------------------------------------------------------------------------- fix round 2 of #490


def _forged(record: str) -> str:
    """A script that writes its own summary, `record` being its JSON, and exits 1."""
    return ("import json, os, pathlib, sys\n"
            "where = pathlib.Path(os.environ['MANUSCRIPT_GUARD_VAULT'], '.runs', "
            "os.environ['MANUSCRIPT_GUARD_VAULT_RUN'], 'summary', '1.json')\n"
            f"where.write_text({record!r}.replace('\"__FILE__\"', json.dumps(__file__)))\n"
            "sys.exit(1)")


@pytest.mark.parametrize("record", [
    '{"class": [], "module": "builtins", "frames": [], "key": null}',
    '{"class": {}, "module": "builtins", "frames": [], "key": null}',
    '{"class": null, "module": "builtins", "frames": [], "key": null}',
    '{"class": 3, "module": "builtins", "frames": [], "key": null}',
    '{"class": "' + "A" * 100000 + '", "module": "builtins", "frames": [], "key": null}',
    '{"class": "KeyError", "module": [], "frames": 5, "key": []}',
    '{"class": "KeyError", "module": "builtins", "frames": [5, "x", null, [[], 1, "f"], '
    '["a.py", [], []], ["__FILE__", 1, {}], ["__FILE__", 1, []]], "key": {}}',
    '[1, 2]',
    "[" * 200000,
    '{"class": "KeyError", "module": "builtins", "frames": [], "key": null, "pad": "'
    + "x" * 200000 + '"}',
    "[" * 60000,
], ids=["list", "dict", "null", "number", "long", "module-frames-key", "frames", "list-whole",
        "deep", "oversized", "deep-within-the-cap"])
def test_a_summary_of_the_wrong_shape_still_gives_the_agent_its_summary(
    paper: Path, vault: Path, terminal, record: str
) -> None:
    """What the script wrote is read by type before use: a field of another type is no name,
    never an error that leaves no summary and the copy behind (fix round 2 of #490)."""
    answers, _asked = terminal
    _script(paper, _forged(record))
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    _text, failed = _failed(paper)
    assert failed.get("class") in (None, "KeyError") and "column" not in failed
    if record.startswith("[[") or len(record) > 100000:
        # Too large or too deep to be read: the path and the exit code alone, as a script
        # that raised nothing (fix rounds 3 and 4 of #490).
        assert set(failed) == {"path", "exit_code"}
    (run,) = [one.name for one in (vault / ".runs").iterdir()]
    assert not (vault / ".runs" / run / "copy").exists()


@pytest.mark.parametrize("where", ["analysis/sub/build/helper.py", "analysis/cpp/build/model.so",
                                   "_extensions/x/build/f.lua"])
def test_what_the_copy_leaves_out_is_no_change_at_the_yes(
    paper: Path, vault: Path, terminal, where: str
) -> None:
    path = paper.joinpath(*where.split("/"))
    path.parent.mkdir(parents=True)
    path.write_text("x = 1\n", encoding="utf-8")
    answers, _asked = terminal
    _script(paper)
    answers.append("y")
    assert vault_cli(paper, "run") == 0


def test_an_extensions_folder_that_is_a_link_is_no_change_at_the_yes(
    paper: Path, vault: Path, terminal, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "f.lua").write_text("--\n", encoding="utf-8")
    _junction(paper / "_extensions", elsewhere)
    answers, _asked = terminal
    _script(paper)
    answers.append("y")
    assert vault_cli(paper, "run") == 0


def test_a_run_stopped_after_it_started_leaves_its_log_and_no_copy(
    paper: Path, vault: Path, terminal, monkeypatch
) -> None:
    from manuscript_guard.vault import run as running

    def stopped(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(running, "execute", stopped)
    answers, _asked = terminal
    _script(paper)
    answers.append("y")
    with pytest.raises(KeyboardInterrupt):
        vault_cli(paper, "run")
    (run,) = [one.name for one in (vault / ".runs").iterdir()]
    assert not (vault / ".runs" / run / "copy").exists()
    assert (vault / ".runs" / run / "log.txt").is_file()
    record = json.loads((vault / ".runs" / run / "run.json").read_text(encoding="utf-8"))
    assert record["finished"] is False
    # The agent reads this run's summary, not the one before (fix round 3 of #490).
    summary = _summary(paper)
    assert summary["run"] == run and summary["stopped"] is True
    assert summary["scripts"] == [{"path": "analysis/01_model.py", "exit_code": None}]


def test_a_copy_stopped_while_it_is_made_is_removed(
    paper: Path, vault: Path, terminal, monkeypatch
) -> None:
    from manuscript_guard.vault import run as running

    def stopped(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(running, "stage", stopped)
    _script(paper)
    with pytest.raises(KeyboardInterrupt):
        vault_cli(paper, "run")
    assert not (vault / ".runs").exists() or not any((vault / ".runs").iterdir())


def test_a_changed_script_is_shown_against_the_version_released(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    _script(paper)
    _git(paper, "add", "-A")
    _git(paper, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    run = _ran(paper, vault, terminal)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    _script(paper, "print('changed')")
    answers.append("y")
    capsys.readouterr()
    assert vault_cli(paper, "run") == 0
    said = capsys.readouterr().out
    line = next(one for one in said.splitlines() if one.startswith("  analysis/01_model.py:"))
    assert "git diff --no-index" in line
    before = line.split("git diff --no-index ", 1)[1].split(" ", 1)[0]
    assert Path(before).read_text(encoding="utf-8") == SCRIPT.format(extra="")


def test_a_lua_filter_and_a_metadata_file_are_listed(
    paper: Path, vault: Path, terminal, capsys
) -> None:
    (paper / "filters").mkdir()
    (paper / "filters" / "own.lua").write_text("--\n", encoding="utf-8")
    (paper / "chapters").mkdir()
    (paper / "chapters" / "_metadata.yml").write_text("x: 1\n", encoding="utf-8")
    answers, _asked = terminal
    _script(paper)
    answers.append("n")
    assert vault_cli(paper, "run") == 0
    said = capsys.readouterr().out
    assert "filters/own.lua: no run" in said and "chapters/_metadata.yml: no run" in said


def test_a_link_inside_the_results_compiled_folder_refuses_the_run(
    paper: Path, vault: Path, terminal, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "kept.txt").write_text("kept", encoding="utf-8")
    (paper / "results" / "__pycache__").mkdir(parents=True)
    _junction(paper / "results" / "__pycache__" / "linked", elsewhere)
    answers, _asked = terminal
    _script(paper)
    answers.append("y")
    assert vault_cli(paper, "run") == 2
    assert (elsewhere / "kept.txt").read_text(encoding="utf-8") == "kept"
    assert not (vault / ".runs").exists() or not any((vault / ".runs").iterdir())


# ---------------------------------------------------------------------------- fix round 3 of #490


def test_a_released_version_is_read_from_the_project_in_a_larger_repository(
    tmp_path: Path, data: Path, terminal, capsys
) -> None:
    """Where the project is a folder of a larger repository, the released version of a script
    is the project's at that commit, not the file at the same path from the repository's top
    (fix round 3 of #490)."""
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    top = tmp_path / "repository"
    (top / "analysis").mkdir(parents=True)
    (top / "analysis" / "01_model.py").write_text("print('the top one')\n", encoding="utf-8")
    paper = top / "sub"
    assert main(["init", str(paper)]) == 0
    with (paper / "paper.yaml").open("a", encoding="utf-8") as file:
        file.write(MINIMUM)
    (paper / "authors.yaml").write_text(AUTHORS, encoding="utf-8")
    (paper / "analysis").mkdir(exist_ok=True)
    _script(paper)
    _git(top, "init", "-q")
    _git(top, "add", "-A")
    _git(top, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-qm", "x")
    assert vault_cli(paper, "init", str(data), "cohort.csv", "--as", "Ada Lovelace") == 0
    _without_starter(paper)
    run = _ran(paper, data, terminal)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    _script(paper, "print('changed')")
    answers.append("y")
    capsys.readouterr()
    assert vault_cli(paper, "run") == 0
    said = capsys.readouterr().out
    line = next(one for one in said.splitlines() if one.startswith("  analysis/01_model.py:"))
    assert "git diff --no-index" in line, line
    before = line.split("git diff --no-index ", 1)[1].split(" ", 1)[0]
    assert Path(before).read_text(encoding="utf-8") == SCRIPT.format(extra="")


@pytest.mark.parametrize("commit", ["HEAD", "--output=x", "a" * 39, "zz" * 20])
def test_a_commit_that_is_no_commit_id_is_not_asked_of_git(
    paper: Path, vault: Path, terminal, capsys, commit: str
) -> None:
    from manuscript_guard.vault.records import release_file

    if not shutil.which("git"):
        pytest.skip("git is not installed")
    _script(paper)
    _committed(paper)
    run = _ran(paper, vault, terminal)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    record_path = release_file(paper, run)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["commit"] = commit
    record_path.write_text(json.dumps(record), encoding="utf-8")
    _script(paper, "print('changed')")
    answers.append("n")
    capsys.readouterr()
    assert vault_cli(paper, "run") == 0
    line = next(one for one in capsys.readouterr().out.splitlines()
                if one.startswith("  analysis/01_model.py:"))  # fmt: skip
    assert "read " in line and "whole" in line and "git diff --no-index" not in line
    assert not (paper / "x").exists()


def _committed(paper: Path) -> None:
    _git(paper, "add", "-A")
    _git(paper, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-qm", "x")


@pytest.mark.parametrize("name", ["before", "released", "copy"])
def test_a_project_folder_named_as_the_run_s_own_folders_keeps_its_copy_apart(
    tmp_path: Path, data: Path, terminal, capsys, name: str
) -> None:
    """The released versions are written beside the copy, never into it, whatever the
    project's folder is called (fix round 3 of #490)."""
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    paper = tmp_path / name
    assert main(["init", str(paper)]) == 0
    with (paper / "paper.yaml").open("a", encoding="utf-8") as file:
        file.write(MINIMUM)
    (paper / "authors.yaml").write_text(AUTHORS, encoding="utf-8")
    (paper / "analysis").mkdir(exist_ok=True)
    _git(paper, "init", "-q")
    _script(paper)
    _committed(paper)
    assert vault_cli(paper, "init", str(data), "cohort.csv", "--as", "Ada Lovelace") == 0
    _without_starter(paper)
    run = _ran(paper, data, terminal)
    answers, _asked = terminal
    answers.append("y")
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 0
    _script(paper, "print('the-edited-script-ran')")
    answers.append("y")
    capsys.readouterr()
    assert vault_cli(paper, "run") == 0
    assert "the-edited-script-ran" in capsys.readouterr().out


# ---------------------------------------------------------------------------- fix round 4 of #490


def test_a_recursion_error_is_named_with_its_last_frames(
    paper: Path, vault: Path, terminal
) -> None:
    """A real RecursionError has some thousand frames: the wrapper writes the last 20 only,
    so that what it writes fits what the tool reads (fix round 4 of #490)."""
    answers, _asked = terminal
    _script(paper, "def walk(n):\n    return walk(n + 1)\nwalk(0)")
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    _text, failed = _failed(paper)
    assert failed["class"] == "RecursionError"
    assert len(failed["frames"]) == 20
    assert {frame["function"] for frame in failed["frames"]} == {"walk"}


def test_a_fault_while_the_outputs_are_moved_says_what_waits(
    paper: Path, vault: Path, terminal, monkeypatch, capsys
) -> None:
    from manuscript_guard.vault import run as running

    real = running.shutil.move
    calls: list[str] = []

    def moved(source: str, target: str):
        calls.append(source)
        if len(calls) == 2:
            raise OSError("the disk is full")
        return real(source, target)

    monkeypatch.setattr(running.shutil, "move", moved)
    answers, _asked = terminal
    _script(paper, "import pathlib\npathlib.Path('figures').mkdir(exist_ok=True)\n"
                   "pathlib.Path('figures/a.png').write_bytes(b'a')")
    answers.append("y")
    with pytest.raises(OSError, match="the disk is full"):
        vault_cli(paper, "run")
    (run,) = [one.name for one in (vault / ".runs").iterdir()]
    outbox = str(vault / "outbox" / run)
    # The person is told at the terminal what waits, before the fault itself (fix round 5).
    said = capsys.readouterr().err
    assert outbox in said and "cannot be released" in said
    record = json.loads((vault / ".runs" / run / "run.json").read_text(encoding="utf-8"))
    assert record["finished"] is False and len(record["outbox"]) == 1
    assert (vault / "outbox" / run / record["outbox"][0]).is_file()
    summary = _summary(paper)
    assert summary["stopped"] is True and summary["outbox"] is True
    assert vault_cli(paper, "release", run, "--as", "Lovelace") == 2
    said = capsys.readouterr().err
    assert "nothing it wrote waits" not in said and outbox in said


def test_a_finished_run_whose_summary_fails_is_not_said_unreleasable(
    paper: Path, vault: Path, terminal, monkeypatch, capsys
) -> None:
    """Fix round 6 of #490: the run finished, its outputs wait to be released, and only the
    agent's summary could not be written; the person is not told it cannot be released."""
    from manuscript_guard.vault import summary

    real = summary.write_summary

    def failing(*args, **kwargs):
        if kwargs.get("stopped"):
            return real(*args, **kwargs)
        raise OSError("last-run.json is a folder")

    monkeypatch.setattr(summary, "write_summary", failing)
    answers, _asked = terminal
    _script(paper, "import pathlib\npathlib.Path('figures').mkdir(exist_ok=True)\n"
                   "pathlib.Path('figures/a.png').write_bytes(b'a')")
    answers.append("y")
    with pytest.raises(OSError, match="is a folder"):
        vault_cli(paper, "run")
    assert "cannot be released" not in capsys.readouterr().err
    (run,) = [one.name for one in (vault / ".runs").iterdir()]
    record = json.loads((vault / ".runs" / run / "run.json").read_text(encoding="utf-8"))
    assert record["finished"] is True


def test_a_run_whose_record_cannot_be_written_is_said_unreleasable(
    paper: Path, vault: Path, terminal, monkeypatch, capsys
) -> None:
    """Fix round 7 of #490: with no record of the run (a full disk), the run is not one to
    release, and the person is told what waits in the outbox. Every script finished, and the
    person is told so, not that it stopped; the copy is removed, and the agent's summary is
    this run's, saying its record could not be written (the last round of #490)."""
    real = Path.write_text

    def full(self, *args, **kwargs):
        if self.name == "run.json":
            raise OSError("the disk is full")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", full)
    answers, _asked = terminal
    _script(paper, "import pathlib\npathlib.Path('figures').mkdir(exist_ok=True)\n"
                   "pathlib.Path('figures/a.png').write_bytes(b'a')")
    answers.append("y")
    with pytest.raises(OSError, match="the disk is full"):
        vault_cli(paper, "run")
    said = capsys.readouterr().err
    (run,) = [one.name for one in (vault / ".runs").iterdir()]
    assert "cannot be released" in said and "every script finished" in said
    assert "stopped" not in said and str(vault / "outbox" / run) in said
    assert not (vault / ".runs" / run / "copy").exists()
    summary = _summary(paper)
    assert summary["run"] == run and summary["unrecorded"] is True
    assert summary["failed"] is None and summary["outbox"] is True and "stopped" not in summary


def test_a_ctrl_c_during_the_run_s_record_leaves_no_copy_and_this_run_s_summary(
    paper: Path, vault: Path, terminal, monkeypatch
) -> None:
    """Round 1 of #498: a Ctrl-C is no OSError, so it skipped the clean-up; the copy went and
    the agent kept the run before's summary as this one's."""
    real = Path.write_text

    def stopped(self, *args, **kwargs):
        if self.name == "run.json" and "copy" not in self.parts:
            raise KeyboardInterrupt
        return real(self, *args, **kwargs)

    answers, _asked = terminal
    _script(paper)
    answers.append("y")
    monkeypatch.setattr(Path, "write_text", stopped)
    with pytest.raises(KeyboardInterrupt):
        vault_cli(paper, "run")
    (run,) = [one.name for one in (vault / ".runs").iterdir()]
    assert not (vault / ".runs" / run / "copy").exists()
    assert _summary(paper)["run"] == run


def test_an_outbox_that_cannot_be_listed_is_said_so(
    paper: Path, vault: Path, terminal, monkeypatch, capsys
) -> None:
    """A run stopped while its outputs were moved, whose outbox cannot then be listed, is not
    said to have left anything waiting there (the last round of #490)."""
    from manuscript_guard.vault import run as running

    def moved(_source: str, _target: str):
        raise OSError("the disk is full")

    real = Path.iterdir

    def unlisted(self):
        if self.parent.name == "outbox":
            raise PermissionError("access is denied")
        return real(self)

    monkeypatch.setattr(running.shutil, "move", moved)
    monkeypatch.setattr(Path, "iterdir", unlisted)
    answers, _asked = terminal
    _script(paper, "import pathlib\npathlib.Path('figures').mkdir(exist_ok=True)\n"
                   "pathlib.Path('figures/a.png').write_bytes(b'a')")
    answers.append("y")
    with pytest.raises(OSError, match="the disk is full"):
        vault_cli(paper, "run")
    said = capsys.readouterr().err
    assert "could not be listed" in said and "cannot be released" in said
    assert "waits in" not in said


def test_a_lone_surrogate_in_the_summary_is_kept_readable(
    paper: Path, vault: Path, terminal
) -> None:
    """Fix round 6 of #490: a key decoded with surrogateescape no longer truncates the
    wrapper's record, so the class is still named."""
    answers, _asked = terminal
    _script(paper, 'raise KeyError("\\udcff")')
    answers.append("y")
    vault_cli(paper, "run")
    _text, failed = _failed(paper)
    assert failed.get("class") == "KeyError"


# ---------------------------------------------------------------------------- fix round 5 of #490


def _wrapper_record(vault: Path) -> str:
    (run,) = [one.name for one in (vault / ".runs").iterdir()]
    return (vault / ".runs" / run / "summary" / "1.json").read_text(encoding="utf-8")


def test_a_failure_deep_in_a_library_keeps_the_script_s_frame(
    paper: Path, vault: Path, terminal
) -> None:
    """The frames are held to the copy before the last 20 are taken: a fault raised some
    thirty frames down in the standard library keeps the line of the script that called it
    (fix round 5 of #490)."""
    extra = ("import copy, threading\nx = threading.Lock()\nfor _ in range(15):\n"
             "    x = [x]\ncopy.deepcopy(x)")
    answers, _asked = terminal
    _script(paper, extra)
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    _text, failed = _failed(paper)
    line = SCRIPT.format(extra=extra).splitlines().index("copy.deepcopy(x)") + 1
    assert failed["frames"] == [{"path": "analysis/01_model.py", "line": line,
                                 "function": "<module>"}]  # fmt: skip


def test_a_name_too_long_to_write_is_left_out_not_cut(
    paper: Path, vault: Path, terminal
) -> None:
    name = "f" + "x" * 300
    answers, _asked = terminal
    _script(paper, f"def {name}():\n    raise ValueError()\n{name}()")
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    written = json.loads(_wrapper_record(vault))
    assert [frame[2] for frame in written["frames"]] == ["<module>"]


def test_the_wrapper_writes_its_record_as_utf8(paper: Path, vault: Path, terminal) -> None:
    answers, _asked = terminal
    _script(paper, "def mesuré():\n    raise ValueError()\nmesuré()")
    answers.append("y")
    assert vault_cli(paper, "run") == 1
    assert "mesuré" in _wrapper_record(vault)
