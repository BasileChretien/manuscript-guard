"""The GitHub Actions a paper's repository runs: the action at this repository's root, the
badge's action, the workflow `init --github-actions` writes, and what `ci_report` says of a
report. The CI job `github-action` runs the action itself, on the worked example
(.github/workflows/ci.yml); these hold what it is made of to docs/github-actions.md."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from manuscript_guard import __version__, ci_report
from manuscript_guard.cli import main
from manuscript_guard.github_workflow import (
    WORKFLOW,
    github_workflow,
    repository_root,
    write_github_workflow,
)
from manuscript_guard.policy import STAGES
from manuscript_guard.scaffold import init_project

REPO = Path(__file__).resolve().parent.parent
ACTION = REPO / "action.yml"
BADGE = REPO / "badge" / "action.yml"
CI = REPO / ".github" / "workflows" / "ci.yml"
DOCS = REPO / "docs" / "github-actions.md"
DOCUMENTS = {"manuscript.docx", "supplementary.docx", "manuscript.pdf", "supplementary.pdf"}


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps(path: Path) -> list[dict]:
    return _yaml(path)["runs"]["steps"]


def _step(name: str) -> dict:
    return next(step for step in _steps(ACTION) if step.get("name") == name)


def _repository(folder: Path) -> Path:
    """`folder`, made the root of a repository, so that the workflow is written there and
    never at the root of a repository the test's folder happens to be in."""
    (folder / ".git").mkdir(parents=True, exist_ok=True)
    return folder


def _caller(tmp_path: Path) -> dict:
    """The workflow as `init` writes it. PyYAML reads the key `on` as true, as YAML 1.1 has
    it; GitHub reads it as the triggers."""
    made = write_github_workflow(_repository(tmp_path), __version__)
    read = yaml.safe_load(made.path.read_text(encoding="utf-8"))
    read["on"] = read.pop(True)
    return read


def _uses(tmp_path: Path) -> list[str]:
    caller = _caller(tmp_path)
    steps = [step for job in caller["jobs"].values() for step in job["steps"]]
    return [step["uses"] for step in [*_steps(ACTION), *_steps(BADGE), *steps] if "uses" in step]


# ------------------------------------------------------------------------- the actions


@pytest.mark.parametrize("path", [ACTION, BADGE], ids=["check", "badge"])
def test_each_action_is_composite_and_each_script_runs_in_bash(path: Path) -> None:
    action = _yaml(path)
    assert action["runs"]["using"] == "composite"
    for step in action["runs"]["steps"]:
        if "run" in step:
            assert step.get("shell") == "bash", step.get("name")


@pytest.mark.parametrize("path", [ACTION, BADGE], ids=["check", "badge"])
def test_no_value_is_written_into_a_script(path: Path) -> None:
    """A value reaches a script through `env:`: one written into it as an expression would
    run a path or a stage holding shell as code."""
    for step in _steps(path):
        assert "${{" not in step.get("run", ""), step.get("name")


def test_pandoc_is_the_version_the_suite_runs_with() -> None:
    pinned = _yaml(CI)["env"]["MANUSCRIPT_GUARD_REQUIRE_PANDOC"]
    assert _yaml(ACTION)["inputs"]["pandoc-version"]["default"] == pinned


def test_tex_live_is_the_latex_jobs() -> None:
    """The packages a LaTeX manuscript is compiled with, and pdftotext, are those
    manuscript-guard's own LaTeX tests pass with."""
    latex = next(s["run"] for s in _yaml(CI)["jobs"]["latex"]["steps"]
                 if "apt-get install" in s.get("run", ""))  # fmt: skip
    wanted = set(latex.split("--no-install-recommends", 1)[1].split())
    script = _step("pdftotext, and TeX Live for a LaTeX manuscript")["run"]
    listed = {word for group in re.findall(r"packages\+?=\(([^)]*)\)", script)
              for word in group.split() if not word.startswith('"')}  # fmt: skip
    assert listed == wanted


def test_an_action_of_a_third_party_is_pinned_to_a_commit(tmp_path: Path) -> None:
    """GitHub's own actions by their major tag, as ci.yml has them; manuscript-guard's by the
    version installed; any other by a full commit, which its owner cannot move."""
    for uses in _uses(tmp_path):
        name, ref = uses.split("@", 1)
        if name.startswith("actions/"):
            assert re.fullmatch(r"v\d+", ref), uses
        elif name.startswith("BasileChretien/manuscript-guard"):
            assert ref == f"v{__version__}", uses
        else:
            assert re.fullmatch(r"[0-9a-f]{40}", ref), uses


def test_no_secret_is_read(tmp_path: Path) -> None:
    caller = write_github_workflow(_repository(tmp_path), __version__).path
    for path in (ACTION, BADGE, caller):
        assert "secrets." not in path.read_text(encoding="utf-8"), path.name


def test_verify_runs_before_check_and_build_only_where_check_passed() -> None:
    names = [step.get("name") for step in _steps(ACTION)]
    assert names.index("verify") < names.index("check") < names.index("build")
    assert _step("verify")["if"] == "inputs.verify == 'true'"
    assert _step("build")["if"] == "steps.report.outputs.ok == 'true'"


#: The lines of the action's scripts that may name the artefact's folder: it is emptied and
#: made, the report is written into it, and each document is copied there by its name.
ARTEFACT_LINES = {
    'rm -rf "$RUNNER_TEMP/manuscript-guard"',
    'mkdir -p "$RUNNER_TEMP/manuscript-guard"',
    'manuscript-guard check --json "$PROJECT" > "$RUNNER_TEMP/manuscript-guard/check.json"',
    'python -m manuscript_guard.ci_report report --report '
    '"$RUNNER_TEMP/manuscript-guard/check.json" --exit-code "$CODE" --version "$VERSION"',
    'cp "$BUILD/$name" "$RUNNER_TEMP/manuscript-guard/$name"',
}


def _names_the_artefact(scripts: list[str]) -> list[str]:
    """Each line of `scripts` that names the runner's folder, in any spelling, and is none
    of those: the action's scripts name it for the artefact and for nothing else."""
    lines = [line.strip() for script in scripts for line in script.splitlines()]
    return [line for line in lines if "RUNNER_TEMP" in line and line not in ARTEFACT_LINES]


def test_the_folders_are_asked_of_the_project_before_they_are_used() -> None:
    """TeX Live is installed for a LaTeX manuscript, and the documents copied from the build
    folder, where paper.yaml's `paths:` puts them, never at a folder written into the action."""
    names = [step.get("name") for step in _steps(ACTION)]
    asked = names.index("Where the project keeps its manuscript and its documents")
    tex = "pdftotext, and TeX Live for a LaTeX manuscript"
    assert asked < names.index(tex) < names.index("build")
    assert _step(tex)["env"]["LATEX"] == "${{ steps.folders.outputs.latex }}"
    assert _step("build")["env"]["BUILD"] == "${{ steps.folders.outputs.build }}"
    for step in _steps(ACTION):
        script = step.get("run", "")
        assert "$PROJECT/build" not in script and "$PROJECT/manuscript" not in script


def test_only_the_report_and_the_documents_are_uploaded() -> None:
    """The artefact is one folder of the runner's, outside the project, and nothing is
    written there but the report and the documents: never results/, data, an input, a stored
    source, or what verify printed, which may quote a script's data."""
    upload = _step("The artefact")
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["path"] == "${{ runner.temp }}/manuscript-guard/"
    scripts = [step.get("run", "") for step in _steps(ACTION)]
    assert _names_the_artefact(scripts) == []
    named = re.search(r"documents=\(([^)]*)\)", _step("build")["run"]).group(1).split()
    assert set(named) == DOCUMENTS
    # A copy of anything else into the folder is found, under each spelling of it.
    for planted in ('cp -r "$PROJECT/results" "$RUNNER_TEMP/manuscript-guard/"',
                    'cp -r "$PROJECT/data" "$RUNNER_TEMP/manuscript-guard"',
                    'cp -r "$PROJECT/results" "${RUNNER_TEMP}/manuscript-guard/"',
                    'cp -r "$PROJECT/data" "$RUNNER_TEMP"/manuscript-guard',
                    'cp "$BUILD/manuscript.md" "$RUNNER_TEMP/manuscript-guard/$name"'):  # fmt: skip
        assert _names_the_artefact([*scripts, planted]) == [planted]


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None,
                    reason="the action runs on Ubuntu; a bash on Windows may be WSL's, which "
                    "takes no environment from here")  # fmt: skip
@pytest.mark.parametrize(
    ("given", "fails", "said"),
    [({"OK": "true", "BUILT": "0", "DOCUMENTS": "2"}, False, ""),
     ({"WANT_VERIFY": "true", "VERIFIED": "0", "OK": "true", "BUILT": "0", "DOCUMENTS": "2"},
      False, ""),
     ({"OK": "false", "CHECKED": "1"}, True, "check fails at the stage"),
     ({"OK": "", "CHECKED": "2"}, True, "check did not run to the end (exit code 2)"),
     ({"OK": "true", "BUILT": "1"}, True, "build failed (exit code 1)"),
     ({"OK": "true", "BUILT": "0", "DOCUMENTS": "0"}, True, "wrote no document"),
     ({"WANT_VERIFY": "true", "OK": "true", "BUILT": "0", "DOCUMENTS": "2"}, True,
      "verify did not run to the end, or a step before it failed"),
     ({"WANT_VERIFY": "true", "VERIFIED": "1", "OK": "true", "BUILT": "0", "DOCUMENTS": "2"},
      True, "verify did not reproduce")],
    ids=["passes", "passes with verify", "check fails", "check did not run", "build failed",
         "no document",
         "verify did not run", "verify failed"],
)  # fmt: skip
def test_the_verdict_fails_the_job_for_each_reason_and_says_which(
    given: dict, fails: bool, said: str
) -> None:
    step = _step("The verdict")
    env = {**{name: "" for name in step["env"]}, "WANT_VERIFY": "false", **given,
           "PATH": os.environ.get("PATH", "")}  # fmt: skip
    ran = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True,
                         text=True, timeout=60, check=False)  # fmt: skip
    assert ran.returncode == (1 if fails else 0), (ran.stdout, ran.stderr)
    assert said in ran.stdout and ("::error::" in ran.stdout) is fails


def test_the_badge_runs_nothing_of_the_project() -> None:
    for step in _steps(BADGE):
        assert "uses" not in step, step.get("name")
        assert "manuscript-guard " not in step["run"].replace("manuscript-guard-badge", "")


# ------------------------------------------------------------------------- the workflow


def test_the_workflow_reads_only_and_runs_on_pushes_and_pull_requests(tmp_path: Path) -> None:
    caller = _caller(tmp_path)
    assert set(caller["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert caller["permissions"] == {"contents": "read"}
    check = caller["jobs"]["check"]
    checkout, guard = check["steps"]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False
    assert guard["uses"] == f"BasileChretien/manuscript-guard@v{__version__}"
    assert guard["with"]["path"] == "."
    assert "permissions" not in check


def test_the_badge_job_alone_writes_and_only_when_asked(tmp_path: Path) -> None:
    caller = _caller(tmp_path)
    writing = [name for name, job in caller["jobs"].items()
               if "write" in (job.get("permissions") or {}).values()]  # fmt: skip
    assert writing == ["badge"]
    badge = caller["jobs"]["badge"]
    assert badge["permissions"] == {"contents": "write"}
    for said in ("always()", "vars.MANUSCRIPT_GUARD_BADGE == 'true'",
                 "github.event_name == 'push'",
                 "github.ref_name == github.event.repository.default_branch"):  # fmt: skip
        assert said in badge["if"]
    (step,) = badge["steps"]
    assert step["uses"] == f"BasileChretien/manuscript-guard/badge@v{__version__}"


def test_the_docs_give_the_workflow_init_writes() -> None:
    """The page's copy is the file, with the version left for the reader."""
    blocks = re.findall(r"```yaml\n(.*?)```", DOCS.read_text(encoding="utf-8"), re.S)
    written = github_workflow("X.Y.Z", ".")
    assert written in blocks


def test_the_workflow_goes_to_the_repository_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    project = tmp_path / "papers" / "first"
    project.mkdir(parents=True)
    made = write_github_workflow(project, __version__)
    assert made.path == tmp_path / WORKFLOW
    assert made.folder == "papers/first"
    read = yaml.safe_load(made.path.read_text(encoding="utf-8"))
    assert read["jobs"]["check"]["steps"][1]["with"]["path"] == "papers/first"


def test_the_workflow_is_never_written_over(tmp_path: Path) -> None:
    target = _repository(tmp_path) / WORKFLOW
    target.parent.mkdir(parents=True)
    target.write_text("mine\n", encoding="utf-8")
    made = write_github_workflow(tmp_path, __version__)
    assert not made.written
    assert target.read_text(encoding="utf-8") == "mine\n"


# ------------------------------------------------------------------------------- init


def _files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def test_init_writes_no_workflow_unasked(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path / "paper")]) == 0
    assert not (tmp_path / "paper" / ".github").exists()


def test_init_writes_the_workflow_into_a_new_project(tmp_path: Path, capsys) -> None:
    root = _repository(tmp_path) / "paper"
    assert main(["init", str(root), "--github-actions"]) == 0
    assert (tmp_path / WORKFLOW).is_file() and (root / "paper.yaml").is_file()
    said = capsys.readouterr().out
    assert f"manuscript-guard@v{__version__}" in said
    assert "The project is the folder paper of the repository" in said


def test_init_says_where_no_repository_holds_the_project(tmp_path: Path, capsys) -> None:
    if repository_root(tmp_path) is not None:
        pytest.skip("the test's folder is in a git repository, whose root the file would go to")
    root = tmp_path / "paper"
    assert main(["init", str(root), "--github-actions"]) == 0
    assert (root / WORKFLOW).is_file()
    assert "No git repository holds this project yet" in capsys.readouterr().out


@pytest.mark.parametrize("latex", [False, True], ids=["markdown", "latex"])
def test_init_adds_only_the_workflow_to_a_project_set_up(tmp_path: Path, latex: bool) -> None:
    """Where a paper.yaml is, the workflow and nothing else: not a file init would otherwise
    add back, and a LaTeX project is not refused for want of --latex."""
    root = _repository(tmp_path / "paper")
    init_project(root, "A study", latex=latex)
    (root / "AGENTS.md").unlink()
    before = _files(root)
    assert main(["init", str(root), "--github-actions"]) == 0
    assert _files(root) - before == {WORKFLOW.as_posix()}


def test_init_refuses_another_flag_beside_it_in_a_project_set_up(tmp_path: Path, capsys) -> None:
    root = tmp_path / "paper"
    init_project(root, "A study")
    before = _files(root)
    assert main(["init", str(root), "--github-actions", "--title", "Another"]) == 2
    assert "--title" in capsys.readouterr().err
    assert _files(root) == before


# --------------------------------------------------------------------- check --json


@pytest.mark.parametrize(
    ("flags", "stage"),
    [([], "design"), (["--stage", "analysis"], "analysis"), (["--submission"], "submission")],
)
def test_check_json_says_its_stage_and_what_no_gate_decides(
    tmp_path: Path, capsys, flags: list[str], stage: str
) -> None:
    root = tmp_path / "paper"
    init_project(root, "A study")
    capsys.readouterr()
    main(["check", str(root), "--json", *flags])
    said = json.loads(capsys.readouterr().out)
    assert said["stage"] == stage
    assert said["assurance"] and all(isinstance(line, str) for line in said["assurance"])
    assert said["assurance"][0].startswith("What was checked, by what")
    assert "version" not in said


# ------------------------------------------------------------------------- ci_report


def test_ci_report_knows_the_stages_the_policy_has() -> None:
    assert ci_report.STAGES == STAGES


def _finding(severity: str = "fail", **given) -> dict:
    found = {"gate": "G2", "code": "unclassified-number", "message": "'4,000' is not bound",
             "severity": severity, "path": None, "line": None, "col": None, "context": None,
             "hint": None}  # fmt: skip
    return {**found, **given}


def test_an_annotation_is_escaped_as_github_reads_it(tmp_path: Path) -> None:
    file = tmp_path / "manuscript" / "main.md"
    found = _finding(path=str(file), line=3, col=4, message="50% of a, b: c\nnext",
                     hint="bind it")  # fmt: skip
    assert ci_report.annotation(found, tmp_path) == (
        "::error file=manuscript/main.md,line=3,col=4,title=G2 unclassified-number"
        "::50%25 of a, b: c%0Anext%0Ahint: bind it"
    )
    title = ci_report.annotation(_finding(code="a,b:c"), tmp_path)
    assert title.startswith("::error title=G2 a%2Cb%3Ac::")


def test_an_annotation_outside_the_repository_names_no_file(tmp_path: Path) -> None:
    found = _finding("warn", path=str(tmp_path.parent / "elsewhere.md"), line=1)
    assert ci_report.annotation(found, tmp_path).startswith("::warning title=")


def test_a_note_is_no_annotation_and_annotations_are_capped(tmp_path: Path) -> None:
    assert ci_report.annotation(_finding("info"), tmp_path) is None
    many = {"ok": False, "findings": [_finding() for _ in range(ci_report.ANNOTATIONS + 3)]}
    lines = ci_report.annotations(many, tmp_path)
    assert len(lines) == ci_report.ANNOTATIONS + 1
    assert lines[-1].startswith("::notice::3 more")


def test_the_summary_says_the_stage_what_is_open_and_what_no_gate_decides(tmp_path: Path) -> None:
    report = {"ok": False, "stage": "drafting", "counts": {},
              "findings": [_finding(message="a <b> & [c](http://x) ![d](y)"), _finding("warn"),
                           _finding("info")],
              "assurance": ["What was checked, by what (no score)", "  the data"]}  # fmt: skip
    said = ci_report.summary(report, 1, "1.2.3", tmp_path)
    assert "manuscript-guard 1.2.3 held the manuscript to the stage **drafting**" in said
    assert "check **fails** there" in said
    assert "### Failing" in said and "### Warnings" in said
    assert "`a <b> & [c](http://x) ![d](y)`" in said
    assert "And 1 note, in check.json." in said
    assert "```text\nWhat was checked, by what (no score)\n  the data\n```" in said
    assert "not evidence that the paper is right" in said


@pytest.mark.parametrize(
    "message", ["see https://example.org and www.example.org", "a `tick`", "``", "`edge`"]
)
def test_a_message_is_shown_as_it_is_and_never_as_markup(message: str) -> None:
    """GitHub renders the summary as GFM, which makes a bare address a link: a message goes
    in a code span, whose backticks outnumber any run of them inside it."""
    shown = ci_report.code(message)
    ticks = len(shown) - len(shown.lstrip("`"))
    assert shown.endswith("`" * ticks)
    inside = shown[ticks:-ticks]
    assert inside.strip() == message
    assert "`" * ticks not in inside


def test_no_line_of_what_was_recorded_closes_its_block() -> None:
    lines = ["  recorded:    read by ```Ada```", "````"]
    fenced = ci_report.fenced(lines)
    fence = fenced[-1]
    assert fenced[0] == f"{fence}text"
    assert all(fence not in line for line in lines)


def test_the_summary_stays_under_the_size_github_keeps(tmp_path: Path) -> None:
    """GitHub drops a step summary larger than 1 MiB whole: at the worst, both kinds of
    finding past the count listed, each message and place long and in four-byte characters,
    and a reviewer's name of two million characters among a thousand lines recorded."""
    long = "\N{GRINNING FACE}" * 5000
    many = [_finding(kind, message=long, path=str(tmp_path / ("p" * 4000)))
            for kind in ("fail", "warn") for _ in range(ci_report.LISTED + 50)]  # fmt: skip
    recorded = ["x" * 2_000_000, *(long for _ in range(1000))]
    report = {"ok": False, "stage": "drafting", "findings": many, "assurance": recorded}
    said = ci_report.summary(report, 1, "1.2.3", tmp_path)
    assert len(said.encode("utf-8")) < 1024 * 1024
    assert said.count(" more, in check.json") == 2
    assert "more lines, in check.json" in said


@pytest.mark.parametrize(
    ("settings", "latex", "build", "manuscript"),
    [("", False, "build", "manuscript"),
     ("paths:\n  build: out\n  manuscript: paper\n", False, "out", "paper"),
     ("", True, "build", "manuscript")],
    ids=["by default", "moved by paths", "latex"],
)  # fmt: skip
def test_the_folders_are_those_paper_yaml_gives(
    tmp_path: Path, monkeypatch, settings: str, latex: bool, build: str, manuscript: str
) -> None:
    """The action installs TeX Live for a LaTeX manuscript and copies the documents from the
    build folder, wherever `paths:` puts either."""
    root = tmp_path / "paper"
    init_project(root, "A study", latex=latex)
    if settings:
        with (root / "paper.yaml").open("a", encoding="utf-8", newline="\n") as paper:
            paper.write(settings)
        (root / "manuscript").rename(root / manuscript)
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert ci_report.main(["folders", "--path", str(root)]) == 0
    said = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert Path(said["build"]).resolve() == (root / build).resolve()
    assert Path(said["manuscript"]).resolve() == (root / manuscript).resolve()
    assert said["latex"] == ("true" if latex else "false")


@pytest.mark.parametrize(("report", "code"), [(None, 1), ({"ok": True}, 2)])
def test_the_summary_of_a_check_that_did_not_run(tmp_path: Path, report, code: int) -> None:
    said = ci_report.summary(report, code, "1.2.3", tmp_path)
    assert f"did not run to the end (exit code {code})" in said
    assert ci_report.outcome(report, code) == "did not run"


@pytest.mark.parametrize(
    ("written", "code", "outputs"),
    [
        ({"ok": True, "stage": "analysis", "findings": []}, 0, "ok=true\nstage=analysis\n"),
        ({"ok": False, "stage": "drafting", "findings": [_finding()]}, 1,
         "ok=false\nstage=drafting\n"),
        (None, 2, "ok=\nstage=\n"),
        ({"ok": True, "stage": "drafting\nok=false", "findings": []}, 0, "ok=true\nstage=\n"),
    ],
    ids=["passes", "fails", "did not run", "a stage that is none"],
)
def test_the_step_says_ok_and_stage(tmp_path: Path, monkeypatch, capsys, written, code,
                                    outputs: str) -> None:  # fmt: skip
    report = tmp_path / "check.json"
    report.write_text("not json" if written is None else json.dumps(written), encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    assert ci_report.main(["report", "--report", str(report), "--exit-code", str(code),
                           "--version", "1.2.3", "--workspace", str(tmp_path)]) == 0  # fmt: skip
    assert (tmp_path / "output").read_text(encoding="utf-8") == outputs
    assert "## manuscript-guard check" in (tmp_path / "summary").read_text(encoding="utf-8")
    printed = capsys.readouterr().out
    assert ("::error" in printed) == (code == 1)


@pytest.mark.parametrize("stage", STAGES)
def test_the_badge_says_passes_or_fails_at_the_stage_and_nothing_more(stage: str) -> None:
    passes, fails = ci_report.badge("true", stage), ci_report.badge("false", stage)
    assert passes == {"schemaVersion": 1, "label": "manuscript-guard check",
                      "message": f"passes at stage {stage}", "color": "blue"}  # fmt: skip
    assert fails["message"] == f"fails at stage {stage}" and fails["color"] == "red"
    for words in (passes, fails, ci_report.badge("", "")):
        said = f"{words['label']} {words['message']}".lower()
        assert not re.search(r"\d", said)
        assert not any(word in said for word in ("verified", "clean", "valid", "correct"))


def test_a_badge_with_no_run_says_so() -> None:
    assert ci_report.badge("", "") == {"schemaVersion": 1, "label": "manuscript-guard check",
                                       "message": "did not run", "color": "lightgrey"}  # fmt: skip


@pytest.mark.parametrize(("ok", "stage"), [("yes", "drafting"), ("true", "final"), ("true", "")])
def test_a_badge_no_report_said_is_refused(ok: str, stage: str) -> None:
    with pytest.raises(ValueError):
        ci_report.badge(ok, stage)


def test_the_badge_runs_from_its_file_with_nothing_installed(tmp_path: Path) -> None:
    """The badge's action runs the module by its path, with no package installed: `-I`
    keeps the environment's variables and this checkout off the path, and `-S` the
    site-packages that hold the installed package, as on a runner that installed none."""
    out = tmp_path / "badge.json"
    module = REPO / "src" / "manuscript_guard" / "ci_report.py"
    ran = subprocess.run(
        [sys.executable, "-I", "-S", str(module), "badge", "--ok", "true", "--stage",
         "drafting", "--out", str(out)],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert ran.returncode == 0, ran.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["message"] == "passes at stage drafting"
