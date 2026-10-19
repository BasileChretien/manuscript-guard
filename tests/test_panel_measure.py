"""`tools/panel_measure.py`, which measures the review panel against defects we know.

The whole path is run here without a provider: the copies and their requests from the
example in the working tree (CI checks out no history to take the pre-fix version from), a
stand-in for Claude Code that answers each request, the scoring, a filled-in adjudication,
and the report.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "example"


def _tool():
    path = REPO / "tools" / "panel_measure.py"
    spec = importlib.util.spec_from_file_location("panel_measure", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _tool()
RUBRIC = yaml.safe_load((REPO / "tools" / "data" / "panel-rubric.yaml").read_text("utf-8"))
#: Each reviewer's role, as the system text names it.
ROLES = {"pharmacoepidemiologist": "Pharmacoepidemiologist", "biostatistician": "Biostatistician",
         "checklist-auditor": "Reporting-guideline auditor"}  # fmt: skip
STAND_IN = """import hashlib, json, re, sys
args = sys.argv[1:]
system = open(args[args.index("--system-prompt-file") + 1], encoding="utf-8").read()
user = sys.stdin.buffer.read().decode("utf-8")
role = re.search(r"Your role: (.+)", system).group(1).strip()
said = json.load(open({replies!r}, encoding="utf-8"))
reply = said[hashlib.sha256(user.encode("utf-8")).hexdigest() + "|" + role]
print(json.dumps({{"result": reply, "usage": {{"input_tokens": 10, "output_tokens": 5}},
                  "total_cost_usd": 0.01}}))
"""
#: A stand-in for the adjudicating model: each finding a control is, its known defect, the
#: finding that raises two, both, and every other none, as a JSON list in a fenced block, as
#: models write one.
ADJUDICATOR = """import json, sys
answers = json.loads({answers!r})
batch = json.loads(sys.stdin.buffer.read().decode("utf-8"))
said = [{{"item": i["item"], "defects": answers.get(i["finding"], [])}} for i in batch]
print(json.dumps({{"result": "```json\\n" + json.dumps(said) + "\\n```"}}))
"""

#: One finding that raises two defects, which only an adjudicator can give it.
TWO = "No case definition is given, and duplicate reports are not mentioned."
#: A comment that praises what a defect would lack, in that defect's words.
PRAISE = "The 2 x 2 contingency table lets a reader recompute every estimate."
#: What each reviewer says in the stand-in replies, by copy: the four known defects raised by
#: the reviewers asked about them on the pre-fix copy, two of them in one finding; both
#: planted ones on the minor copy by one reviewer (one rated major); praise in a defect's
#: words on the current copy; and on every copy a finding that names no defect.
SAID = {
    ("pre-fix", "pharmacoepidemiologist"): [("major", "Methods", TWO)],
    ("pre-fix", "biostatistician"): [
        ("major", "Results", "The contingency table is not reported."),
    ],
    ("pre-fix", "checklist-auditor"): [
        ("minor", "Methods, DEMO-OBS item 3", "How records were selected is not described."),
    ],
    ("current", "biostatistician"): [("comment", "Results", PRAISE)],
    ("minor", "biostatistician"): [
        ("minor", "Methods", "ICSR is never spelt out."),
        ("major", "Results", "The caption of Table 1 does not say what its values are."),
    ],
}


def _reply(copy: str, reviewer: str) -> str:
    """The stand-in's reply; the repeat of a copy is answered as the copy is, since its
    requests are the same."""
    copy = copy.removesuffix("-repeat")
    findings = [{"severity": s, "where": w, "finding": f}
                for s, w, f in SAID.get((copy, reviewer), [])]  # fmt: skip
    findings.append({"severity": "comment", "where": "Discussion", "finding": "Well argued."})
    tests = [{"test": "A test.", "holds": False, "evidence": "Methods"}]
    return json.dumps({"verdict": "minor-revision", "summary": "A summary.",
                       "rejection_tests": tests, "findings": findings})  # fmt: skip


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    """The copies from the working tree's example, its pre-fix source told apart by a
    sentence of its own, as the version at `PREFIX` is by its text."""
    folder = tmp_path_factory.mktemp("panel")
    before = folder / "pre-fix"
    shutil.copytree(EXAMPLE, before, ignore=shutil.ignore_patterns("build"))
    main = before / "manuscript" / "main.md"
    said = "\nThis copy stands for the pre-fix version.\n"
    main.write_text(main.read_text(encoding="utf-8") + said, encoding="utf-8")
    work = folder / "work"
    return work, tool.prepare(work, {"pre-fix": before, "current": EXAMPLE}, seed=53)


def test_every_copy_is_asked_by_every_reviewer_three_times(prepared: tuple[Path, dict]) -> None:
    work, key = prepared
    assert len(key) == len(tool.COPIES) * 3 * tool.SAMPLES
    assert {v["reviewer"] for v in key.values()} == {
        "pharmacoepidemiologist", "biostatistician", "checklist-auditor"}  # fmt: skip
    request = json.loads(next((work / "requests").glob("*.json")).read_text(encoding="utf-8"))
    assert set(request) == {"system", "user"} and "# The manuscript" in request["user"]
    with pytest.raises(SystemExit, match="already prepared"):
        tool.prepare(work, {"pre-fix": EXAMPLE, "current": EXAMPLE})


def test_a_folder_prepared_in_part_is_refused(tmp_path: Path) -> None:
    """A run that failed half-way leaves its requests and no key; preparing again in that
    folder is refused with what is there, not a crash. From the command line, any folder
    with something in it is refused before the sources are written into it."""
    (tmp_path / "requests").mkdir()
    with pytest.raises(SystemExit, match=r"already prepared, or in part \(requests\)"):
        tool.prepare(tmp_path, {"pre-fix": EXAMPLE, "current": EXAMPLE})
    with pytest.raises(SystemExit, match="not empty"):
        tool.main(["prepare", "--work", str(tmp_path)])
    assert not (tmp_path / "sources").exists()


def test_the_dry_run_imports_this_tree_s_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The requests are what this tree's `review --run --dry-run` writes, not the installed
    package's, whatever PYTHONPATH already holds."""
    seen = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 1, "", "stopped here")

    monkeypatch.setenv("PYTHONPATH", "elsewhere")
    monkeypatch.setattr(tool.subprocess, "run", run)
    with pytest.raises(SystemExit, match="stopped here"):
        tool.requests_of(tmp_path)
    assert seen["env"]["PYTHONPATH"].split(os.pathsep) == [str(tool.ROOT / "src"), "elsewhere"]


def test_the_blank_copy_is_its_title_and_abstract_and_the_minor_one_is_planted(
    prepared: tuple[Path, dict],
) -> None:
    work, key = prepared
    def user_of(copy: str) -> str:
        ident = next(i for i, v in key.items() if v["copy"] == copy)
        request = (work / "requests" / f"{ident}.json").read_text(encoding="utf-8")
        return json.loads(request)["user"]

    assert "# Abstract" in user_of("blank") and "# Methods" not in user_of("blank")
    assert "ICSR identifier" in user_of("minor") and "ICSR" not in user_of("current")
    assert "Values are n (%) unless stated" in user_of("current")
    assert "Values are n (%) unless stated" not in user_of("minor")


def test_a_finding_is_settled_by_the_words_of_one_defect_alone() -> None:
    assert tool.matched({"where": "Methods", "finding": "Duplicate reports go unmentioned."},
                        RUBRIC) == ["duplicates"]  # fmt: skip
    assert tool.matched({"where": "Discussion", "finding": "Well argued."}, RUBRIC) == []
    both = {"where": "Methods", "finding": "No case definition, and duplicates not removed."}
    assert tool.matched(both, RUBRIC) == ["case-definition", "duplicates"]


def test_the_whole_path_answers_scores_adjudicates_and_reports(
    prepared: tuple[Path, dict], tmp_path: Path
) -> None:
    work, key = prepared
    # A stand-in for `claude -p`: it reads the request on stdin and answers as the copy's
    # reviewer would, with the JSON Claude Code prints. Replies are found by the digest of
    # the request and the reviewer its system text names.
    said = {}
    for ident, where in key.items():
        user = json.loads((work / "requests" / f"{ident}.json").read_text(encoding="utf-8"))["user"]
        digest = hashlib.sha256(user.encode("utf-8")).hexdigest()
        said[f"{digest}|{ROLES[where['reviewer']]}"] = _reply(where["copy"], where["reviewer"])
    replies = tmp_path / "said.json"
    replies.write_text(json.dumps(said), encoding="utf-8")
    stand_in = tmp_path / "claude.py"
    stand_in.write_text(STAND_IN.format(replies=str(replies)), encoding="utf-8")
    answered = tool.answer_with_claude_code(work, "opus", [sys.executable, str(stand_in)])
    assert answered["answered"] == len(key)
    # The system text as the panel wrote it, its line ends LF on every system.
    assert b"\r\n" not in (work / "system.txt").read_bytes()

    scored = tool.score(work, RUBRIC, seed=1)
    adjudicate = yaml.safe_load((work / "adjudicate.yaml").read_text(encoding="utf-8"))
    # Every reply's "Well argued.", the praise in a defect's words, the finding that raises
    # two defects and the controls go to the adjudicator; nothing says where an item came
    # from, not even its `where`.
    blind = [item["finding"] for item in adjudicate["items"]]
    assert scored["to_adjudicate"] == len(key) + 3 + 6 + len(RUBRIC["controls"])
    assert blind.count(PRAISE) == 3 and blind.count(TWO) == 6
    assert set(adjudicate["items"][0]) == {"item", "finding", "defects"}
    with pytest.raises(SystemExit, match="already scored"):
        tool.score(work, RUBRIC, seed=1)
    answers = {c["finding"]: c["defect"] for c in RUBRIC["controls"]}
    answers[TWO] = "duplicates, case-definition"
    for item in adjudicate["items"]:
        item["defects"] = answers.get(item["finding"], "none")
    (work / "adjudicate.yaml").write_text(yaml.safe_dump(adjudicate, allow_unicode=True),
                                          encoding="utf-8")  # fmt: skip

    text = tool.report(work, RUBRIC)
    counted = tool.tally(tool._adjudicated(work, RUBRIC)[0], key, RUBRIC)
    assert counted["defects"]["pre-fix"]["case-definition"] == [3, 3, 3]
    assert counted["defects"]["pre-fix"]["duplicates"] == [3, 3, 3]
    assert counted["defects"]["pre-fix"]["record-selection"] == [3, 3, 0]
    assert counted["defects"]["current"]["duplicates"] == [3, 0, 0]
    assert counted["defects"]["current"]["contingency-table"] == [3, 0, 0]
    # Of the three biostatistician replies on the minor copy, each raised both planted
    # defects and rated the caption major: over-escalation. The other two remits, asked
    # about both, raised neither, and the report gives each reviewer's count.
    by_reviewer = counted["by_reviewer"]["minor"]["caption-incomplete"]
    assert by_reviewer["biostatistician"] == [3, 3, 3]
    assert by_reviewer["pharmacoepidemiologist"] == by_reviewer["checklist-auditor"] == [3, 0, 0]
    assert counted["defects"]["minor"]["undefined-acronym"] == [9, 3, 0]
    assert "| caption-incomplete: biostatistician | 3 | 3 | 3 |" in text
    assert "adjudicated by a person; agreement with the controls: 100%" in text
    assert (work / "report.md").read_text(encoding="utf-8") == text

    # The same blind findings adjudicated by a model, as Basile chose, a person checking a
    # sample of its answers and the controls (2026-10-19).
    by_model = work.parent / "by-model"
    shutil.copytree(work, by_model)
    lists = {finding: [] if said == "none" else sorted(said.replace(" ", "").split(","))
             for finding, said in answers.items()}  # fmt: skip
    stand_in = tmp_path / "adjudicator.py"
    stand_in.write_text(ADJUDICATOR.format(answers=json.dumps(lists)), encoding="utf-8")
    done = tool.adjudicate_with_model(by_model, RUBRIC, "opus", [sys.executable, str(stand_in)],
                                      seed=2)  # fmt: skip
    assert done["adjudicated"] == len(adjudicate["items"])
    assert b"\r\n" not in (by_model / "adjudicator.txt").read_bytes()
    assert tool.tally(tool._adjudicated(by_model, RUBRIC)[0], key, RUBRIC) == counted
    check = yaml.safe_load((by_model / "check.yaml").read_text(encoding="utf-8"))
    assert len(check["items"]) == tool.CHECKED + len(RUBRIC["controls"])
    assert all(item["defects"] == "" for item in check["items"])
    # Unchecked, the report says so (Basile scored none, 2026-10-19).
    assert "No person checked the model's adjudications" in tool.report(by_model, RUBRIC)
    for item in check["items"]:
        item["defects"] = answers.get(item["finding"], "none")
    (by_model / "check.yaml").write_text(yaml.safe_dump(check, allow_unicode=True),
                                         encoding="utf-8")  # fmt: skip
    text = tool.report(by_model, RUBRIC)
    assert "adjudicated by a model; agreement with the controls: 100%" in text
    assert f"A person checked {tool.CHECKED} of the model's adjudications and " \
        f"agreed with {tool.CHECKED}" in text  # fmt: skip


def test_an_adjudication_is_a_list_of_defect_ids_or_none() -> None:
    known = {d["id"] for d in RUBRIC["defects"]}
    assert tool.defects_of("none", known, "x") == tool.defects_of([], known, "x") == []
    assert tool.defects_of("duplicates, case-definition", known, "x") == [
        "case-definition", "duplicates"]  # fmt: skip
    assert tool.defects_of(["duplicates"], known, "x") == ["duplicates"]
    for wrong in ("", "case definition", "none, duplicates", None):
        with pytest.raises(SystemExit, match="is no defect id or none"):
            tool.defects_of(wrong, known, "x")


@pytest.mark.parametrize(("code", "out", "says"), [
    (1, "", "claude -p failed"),
    (0, '{"result": "[', "claude -p failed"),
    (0, json.dumps({"is_error": True, "result": "Overloaded"}), "claude -p failed"),
    (0, json.dumps({"result": "I could not decide."}), "no list of them"),
    (0, json.dumps({"result": '[{"item": 99, "defects": []}]'}), "no list of them"),
    (0, json.dumps({"result": '[{"item": 1, "defects": ["case defn"]}]'}), "no defect id"),
])  # fmt: skip
def test_an_adjudicating_call_that_failed_or_answered_otherwise_is_refused(
    code: int, out: str, says: str
) -> None:
    run = subprocess.CompletedProcess([], code, out.encode("utf-8"), b"")
    known = {d["id"] for d in RUBRIC["defects"]}
    with pytest.raises(SystemExit, match=says):
        tool._model_said(run, [{"item": 1, "finding": "f"}, {"item": 2, "finding": "g"}], known)


def test_an_answer_that_is_no_defect_id_is_refused(prepared: tuple[Path, dict]) -> None:
    work, _key = prepared
    if not (work / "adjudicate.yaml").exists():
        pytest.skip("the whole path has not run")
    adjudicate = yaml.safe_load((work / "adjudicate.yaml").read_text(encoding="utf-8"))
    adjudicate["items"][0]["defects"] = "case definition"
    broken = work.parent / "broken"
    if not broken.exists():
        import shutil

        shutil.copytree(work, broken)
    (broken / "adjudicate.yaml").write_text(yaml.safe_dump(adjudicate), encoding="utf-8")
    with pytest.raises(SystemExit, match="no defect id"):
        tool.report(broken, RUBRIC)
