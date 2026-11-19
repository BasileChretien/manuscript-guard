"""`tools/corpus.py`, which measures judged findings over runs of a corpus and gates a change.

Everything here is a made-up mini corpus written in `tmp_path`: a few papers' reports, the
packets the findings were judged from, the verdicts and a ledger. No real paper's text is in
the repository, and `run` is tried with its install and its steps faked.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "corpus.py"
RUNNER = REPO / "tools" / "corpus_run.py"


def _tool():
    spec = importlib.util.spec_from_file_location("corpus_tool", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["corpus_tool"] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


tool = _tool()


def finding(gate: str, code: str, message: str, severity: str = "warn", line: int | None = 10,
            path: str = "paper.docx", **extra) -> dict:  # fmt: skip
    return {"gate": gate, "code": code, "message": message, "severity": severity,
            "line": line, "path": path, "context": extra.pop("context", None), **extra}  # fmt: skip


#: The judged findings of the mini corpus, by paper and report, in packet order, each with
#: its verdict. The names say what the new run does with each.
JUDGED = {
    ("paper-a", "audit"): [
        (finding("G6", "vague-attribution", "'Studies show' with no citation nearby", line=5),
         "true"),  # kept, reported
        (finding("G14", "abbreviation-undefined", "XYZ is used 3 times in the main text and "
                 "not defined there", line=20), "true"),  # now in a question: asked
        (finding("G2", "unclassified-number", "42 is typed", line=30), "true"),  # elsewhere
        (finding("G14", "abbreviation-undefined", "QRS is used once in the main text and not "
                 "defined there", line=40), "true"),  # G14 form, other code: elsewhere
        (finding("G6", "model-artefact", "'[INSERT FIGURE 1]' — Unfilled placeholder text",
                 line=50), "true"),  # gone, but the ledger re-judges it false
        (finding("G14", "spelling-variant", "'color' is the American spelling of 'colour'",
                 line=60), "true"),  # gone: lost
        (finding("audit", "not-audited", "paper.docx: Limitations, read as the reference list",
                 severity="info", line=None), "true"),  # a notice, gone
        (finding("G6", "ai-phrasing", "'delve into' is a phrase models favour", line=70),
         "false"),  # gone before, loud now
    ],
    ("paper-b", "audit"): [
        (finding("audit", "abstract-not-compared", "not compared: no file has a heading that "
                 "names the Abstract", severity="info", line=None), "true"),  # successor
        (finding("G6", "vague-attribution", "'It is known' with no citation nearby", line=8),
         "unclear"),  # not counted
    ],
}

BASE = {
    ("paper-a", "audit"): [
        finding("G6", "vague-attribution", "'Studies show' with no citation nearby", line=5),
        finding("G14", "abbreviation-undefined", "XYZ is used 3 times in the main text and not "
                "defined there", line=20),
        finding("G2", "unclassified-number", "42 is typed", line=30),
        finding("G14", "abbreviation-undefined", "QRS is used once in the main text and not "
                "defined there", line=40),
        finding("G6", "model-artefact", "'[INSERT FIGURE 1]' — Unfilled placeholder text",
                line=50),
        finding("G14", "spelling-variant", "'color' is the American spelling of 'colour'",
                line=60),
        finding("audit", "not-audited", "paper.docx: Limitations, read as the reference list",
                severity="info", line=None),
    ],
    ("paper-b", "audit"): [
        finding("audit", "abstract-not-compared", "not compared: no file has a heading that "
                "names the Abstract", severity="info", line=None),
    ],
}

NEW = {
    ("paper-a", "audit"): [
        # reported: the same message, with the folder of another run in it
        finding("G6", "vague-attribution", "'Studies show' with no citation nearby", line=5),
        # asked: the same code, now one question that names the form
        finding("G14", "abbreviation-undefined", "2 short forms are used and never defined: "
                "'XYZ' here, then ABC. Do any of them need defining?", severity="info",
                line=20, question=True, forms=[{"form": "XYZ"}, {"form": "ABC"}]),
        # elsewhere: another code's warning at the same line of the same file
        finding("G2", "typed-number", "42 is typed and not bound", line=30),
        # elsewhere: the same short form under another G14 code, at another line
        finding("G14", "abbreviation-used-before-defined", "QRS is used here, and defined later "
                "at Methods, paragraph 2", line=44),
        # the same line as the lost spelling finding, in another file: not its place
        finding("G12", "plan-section-empty", "the plan's question section is empty", line=60,
                path="design/plan.md"),
        # a notice still there, worded otherwise
        finding("audit", "not-audited", "paper.docx: References, read as the reference list",
                severity="info", line=None),
        # the false finding, loud now
        finding("G6", "ai-phrasing", "'delve into' is a phrase models favour", line=70),
        # matches no judged finding
        finding("G14", "notation-percent", "'%' stands against its number", line=80),
    ],
    ("paper-b", "audit"): [
        finding("audit", "question-no-abstract", "No Abstract was found. Where is it?",
                severity="info", line=None, question=True),
    ],
}

LEDGER = {"decisions": [
    {"id": "marker", "date": "2026-11-11", "by": "the author", "what": "a placement marker",
     "source": "DESIGN.md, \"A placement marker is no slot\"",
     "rejudge": {"verdict": False, "match": [
         {"gate": "G6", "code": "model-artefact", "message": r"\[INSERT FIGURE \d+\]"}]}},
    {"id": "abstract-questions", "date": "2026-11-16", "by": "the author",
     "what": "the audit asks where no Abstract is found", "source": "#697",
     "successor": {"from": "audit/abstract-not-compared",
                   "to": ["audit/question-no-abstract", "audit/question-no-results"],
                   "scope": "paper"}},
]}  # fmt: skip


def write_run(root: Path, name: str, reports: dict) -> None:
    for (slug, report), found in reports.items():
        folder = root / "runs" / name / slug
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{report}.json").write_text(json.dumps({"findings": found}), "utf-8")


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus-root"
    packets, verdicts = {}, []
    for (slug, report), items in JUDGED.items():
        paper = packets.setdefault(slug, {"slug": slug, "text": "made up", "reports": {}})
        paper["reports"][report] = {"findings": [f for f, _ in items]}
        verdicts += [{"slug": slug, "report": report, "index": i, "verdict": v,
                      "gate": f["gate"], "code": f["code"]} for i, (f, v) in enumerate(items)]
    (root / "report" / "packets").mkdir(parents=True)
    (root / "report" / "judged").mkdir()
    (root / "report" / "packets" / "field.json").write_text(json.dumps(list(packets.values())))
    (root / "report" / "judged" / "field.json").write_text(json.dumps(verdicts))
    write_run(root, "base", BASE)
    write_run(root, "new", NEW)
    return root


def with_ledger(root: Path, ledger: dict = LEDGER) -> Path:
    (root / "report" / "ledger.yaml").write_text(yaml.safe_dump(ledger), "utf-8")
    return root


def states(result: dict) -> dict[tuple[str, int], str]:
    return {(r["slug"], r["index"]): r["state"] for r in result["findings"]}


def test_each_judged_finding_is_put_in_one_of_four_states(corpus: Path) -> None:
    result = tool.measure(corpus, "new", ledger=False)
    assert states(result) == {
        ("paper-a", 0): "reported", ("paper-a", 1): "asked", ("paper-a", 2): "elsewhere",
        ("paper-a", 3): "elsewhere", ("paper-a", 4): "gone", ("paper-a", 5): "gone",
        ("paper-a", 6): "gone", ("paper-a", 7): "reported", ("paper-b", 0): "gone",
    }  # fmt: skip
    assert result["skipped"] == {"verdict unclear": 1}
    assert result["totals"]["true"] == {"reported": 1, "asked": 1, "elsewhere": 2, "gone": 4}


def test_a_finding_is_found_in_the_run_it_was_judged_from(corpus: Path) -> None:
    result = tool.measure(corpus, "base", ledger=False)
    assert "gone" not in {r["state"] for r in result["findings"] if r["slug"] == "paper-a"
                          and r["index"] < 7}  # fmt: skip


def test_a_note_of_the_same_finding_is_asked_and_a_warning_reported() -> None:
    old = finding("G7", "doi-unresolved", "10.1/abc does not resolve")
    assert tool.state(old, [{**old, "severity": "info"}])[0] == "asked"
    assert tool.state(old, [{**old, "severity": "fail"}])[0] == "reported"
    assert tool.state(old, [{**old, "message": "other", "code": "question-doi",
                             "severity": "info"}])[0] == "asked"  # fmt: skip


def test_a_folder_of_the_machine_in_a_message_does_not_tell_two_findings_apart() -> None:
    old = finding("G7", "x", r"C:\Users\someone\scratch\runs\one\paper\project\main.md: read")
    new = finding("G7", "x", "/home/other/runs/two/paper/project/main.md: read")
    assert tool.state(old, [new])[0] == "reported"


def test_the_same_line_of_another_file_is_not_the_same_place() -> None:
    old = finding("G14", "spelling-variant", "'color'", line=60, path="manuscript/main.md")
    other = finding("G12", "plan-section-empty", "empty", line=60, path="design/plan.md")
    assert tool.state(old, [other])[0] == "gone"
    assert tool.state(old, [{**other, "path": "/elsewhere/manuscript/main.md"}])[0] == "elsewhere"


def test_a_finding_said_under_another_code_at_another_line_is_gone() -> None:
    old = finding("compare", "fact-gone", "'0.48' is gone: it stood on line 19 of v1", "info",
                  line=19, path="v2.tex")  # fmt: skip
    now = finding("compare", "table-changed", "Table 6: the row '0.089 B & 0.48 M' is gone",
                  "info", line=40, path="v2.tex")  # fmt: skip
    assert tool.state(old, [now])[0] == "gone"


def test_the_reading_notices_are_counted_apart(corpus: Path) -> None:
    result = tool.measure(corpus, "new", ledger=False)
    assert result["notices"]["true"]["gone"] == 2  # not-audited, abstract-not-compared
    assert result["paper"]["true"]["gone"] == 2
    text = tool.render_measure(result)
    paper_part = text.split("## True findings gone, about the paper")[1].split("## True")[0]
    assert "spelling-variant" in paper_part and "not-audited" not in paper_part


def test_a_rejudge_by_matcher_changes_the_verdict_and_a_successor_asks(corpus: Path) -> None:
    result = tool.measure(with_ledger(corpus), "new")
    rows = {(r["slug"], r["index"]): r for r in result["findings"]}
    marker = rows[("paper-a", 4)]
    assert (marker["judged"], marker["verdict"], marker["rejudged_by"]) == ("true", "false",
                                                                           "marker")  # fmt: skip
    assert rows[("paper-b", 0)]["state"] == "asked"
    assert rows[("paper-b", 0)]["successor_by"] == "abstract-questions"
    assert result["decisions"] == [
        {"id": "marker", "matched": 1, "changed": 1, "successor": 0},
        {"id": "abstract-questions", "matched": 0, "changed": 0, "successor": 1}]
    assert "2 decisions, 1 findings re-judged, 1 asked by a successor" in tool.render_measure(
        result)


def test_a_rejudge_by_key_names_one_finding(corpus: Path) -> None:
    ledger = {"decisions": [{"id": "k", "date": "2026-11-19", "by": "the author",
                             "what": "one finding", "source": "#1", "rejudge": {
                                 "verdict": "false",
                                 "findings": [{"slug": "paper-a", "report": "audit",
                                               "index": 5}]}}]}  # fmt: skip
    rows = tool.measure(with_ledger(corpus, ledger), "new")["findings"]
    assert [r["index"] for r in rows if r["rejudged_by"] == "k"] == [5]


def test_a_successor_needs_its_code_in_the_same_report_of_the_same_paper(corpus: Path) -> None:
    write_run(corpus, "other", {("paper-b", "audit"): [], ("paper-a", "audit"): [
        finding("audit", "question-no-abstract", "Where?", severity="info")]})
    assert states(tool.measure(with_ledger(corpus), "other"))[("paper-b", 0)] == "gone"


@pytest.mark.parametrize(("broken", "says"), [
    ({"decisions": {"id": "x"}}, "a list under `decisions`"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w", "source": "s"}]},
     "one of rejudge or successor"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w",
                     "rejudge": {"verdict": "false", "findings": []}}]}, "`source` is missing"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w", "source": "s",
                     "rejudge": {"verdict": "maybe", "match": [{"code": "c"}]}}]},
     "true or false"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w", "source": "s",
                     "rejudge": {"verdict": "false"}}]}, "names no finding"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w", "source": "s",
                     "rejudge": {"verdict": "false", "match": [{"message": "("}]}}]},
     "no regular expression"),
    ({"decisions": [{"id": "x", "date": "d", "by": "b", "what": "w", "source": "s",
                     "successor": {"from": "a/b", "to": ["c/d"], "scope": "sentence"}}]},
     "scope"),
])  # fmt: skip
def test_a_ledger_that_is_not_as_written_down_is_refused(corpus: Path, broken: dict,
                                                         says: str) -> None:  # fmt: skip
    with pytest.raises(tool.CorpusError, match=re.escape(says)):
        tool.measure(with_ledger(corpus, broken), "new")


def test_the_gate_fails_on_a_true_finding_kept_at_base_and_gone_now(corpus: Path) -> None:
    result = tool.gate(with_ledger(corpus), "base", "new")
    assert not result["ok"]
    assert [(r["code"], r["base"], r["state"]) for r in result["lost"]] == [
        ("G14/spelling-variant", "reported", "gone")]
    assert tool.main(["--corpus", str(corpus), "gate", "base", "new"]) == 1


def test_the_gate_passes_where_the_author_s_decision_covers_the_loss(corpus: Path) -> None:
    ledger = {"decisions": [*LEDGER["decisions"], {
        "id": "spelling", "date": "2026-11-19", "by": "the author", "what": "w",
        "source": "#2", "rejudge": {"verdict": "false", "match": [
            {"code": "spelling-variant", "slug": "paper-a"}]}}]}  # fmt: skip
    out = corpus / "gate.md"
    assert tool.main(["--corpus", str(with_ledger(corpus, ledger)), "gate", "base", "new",
                      "--out", str(out), "--json", str(corpus / "gate.json")]) == 0  # fmt: skip
    text = out.read_text("utf-8")
    assert "**Passes**" in text
    data = json.loads((corpus / "gate.json").read_text("utf-8"))
    # Without the ledger the marker would be lost too; re-judged false, it is not true.
    assert data["lost"] == []
    assert [r["code"] for r in data["false_loud"]] == ["G6/ai-phrasing"]
    assert [r["code"] for r in data["quieter"]] == ["G14/abbreviation-undefined"]
    # The successor's question stands where the base had the note itself: asked at both.
    assert [r["code"] for r in data["notices"]] == ["audit/not-audited"]
    assert data["unjudged"]["G14/notation-percent"] == {"base": 0, "new": 1}


def test_a_notice_lost_does_not_fail_the_gate(corpus: Path) -> None:
    ledger = {"decisions": [{"id": "all", "date": "d", "by": "the author", "what": "w",
                             "source": "s", "rejudge": {"verdict": "false", "match": [
                                 {"code": "spelling-variant"}, {"code": "model-artefact"}]}}]}
    result = tool.gate(with_ledger(corpus, ledger), "base", "new")
    assert result["ok"]
    assert any(r["code"] == "audit/not-audited" and r["state"] == "gone"
               for r in result["notices"])  # fmt: skip


def test_the_command_says_what_it_needs_in_one_line(tmp_path: Path, capsys,
                                                    monkeypatch) -> None:  # fmt: skip
    monkeypatch.delenv(tool.ENV, raising=False)
    assert tool.main(["measure", "x"]) == 2
    assert tool.ENV in capsys.readouterr().err
    assert tool.main(["--corpus", str(tmp_path), "measure", "x"]) == 2
    assert "not a corpus" in capsys.readouterr().err


def test_the_reading_notices_are_the_ones_the_page_lists_and_the_package_writes() -> None:
    page = (REPO / "docs" / "corpus.md").read_text("utf-8")
    table = page.split("### Reading notices")[1].split("\n## ")[0]
    listed = set(re.findall(r"^\| `([a-z-]+)` \|", table, flags=re.M))
    assert listed == set(tool.NOTICES)
    source = "\n".join(p.read_text("utf-8") for p in (REPO / "src").rglob("*.py"))
    unwritten = [code for code in tool.NOTICES if f'"{code}"' not in source]
    assert not unwritten, f"no code of the package writes {unwritten}"


def test_every_command_the_tool_runs_has_a_time_limit() -> None:
    text = TOOL.read_text("utf-8") + RUNNER.read_text("utf-8")
    tree = ast.parse(text)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("run", "communicate", "check_output", "call")
             and isinstance(n.func.value, ast.Name)
             and n.func.value.id in ("subprocess", "proc")]  # fmt: skip
    assert calls
    for call in calls:
        assert "timeout" in {k.arg for k in call.keywords}, ast.unparse(call)
    assert not re.search(r"subprocess\.(check_call|check_output|getoutput|call)\(", text)


# --- run, with the install and the steps faked ------------------------------------------


def _archive() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        data = b"[project]\nname = 'stand-in'\n"
        info = tarfile.TarInfo("pyproject.toml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_run_installs_the_commit_and_runs_each_report_outside_the_papers(
        corpus: Path, monkeypatch) -> None:  # fmt: skip
    for slug, meta in {
        "doc-1": {"format": "docx", "main": "paper.docx"},
        "tex-1": {"format": "latex", "main": "latest/paper.tex", "v1": "v1/paper.tex",
                  "pdf": "paper.pdf"},
        "pdf-1": {"format": "pdf", "main": "paper.pdf"},
    }.items():  # fmt: skip
        folder = corpus / "corpus" / slug
        (folder / "files" / "latest").mkdir(parents=True)
        (folder / "files" / "latest" / "paper.tex").write_text("\\section{A}\n")
        (folder / "files" / "latest" / "refs.bib").write_text("@article{a,title={A}}\n")
        (folder / "meta.json").write_text(json.dumps({"slug": slug, **meta}))
    quiet_calls, steps = [], []
    sha = "0123456789abcdef0123456789abcdef01234567"

    def fake_quiet(cmd, cwd=None):
        quiet_calls.append([str(c) for c in cmd])
        if "rev-parse" in cmd:
            return (sha + "\n").encode()
        if "archive" in cmd:
            return _archive()
        if "-c" in cmd:
            return b"0.2.999\n"
        if "venv" in cmd:
            python = tool.corpus_run.venv_python(Path(cmd[-1]))
            python.parent.mkdir(parents=True)
            python.write_text("")
        return b""

    def fake_call(cmd, cwd, out, env):
        steps.append((list(cmd), Path(cwd), Path(out), env))
        if "init" in cmd and "--latex" in cmd:
            (Path(cmd[-1]) / "manuscript").mkdir(parents=True)
        out.write_text(json.dumps({"findings": []}))
        return {"cmd": cmd, "exit": 0, "seconds": 0.0, "stderr": ""}

    runner = tool.corpus_run
    monkeypatch.setattr(runner, "quiet", fake_quiet)
    monkeypatch.setattr(runner, "call", fake_call)
    monkeypatch.setenv("MANUSCRIPT_GUARD_DEBUG", "1")
    record = runner.run(corpus, "main", "pr-1", REPO, jobs=2, only=None)
    assert record == {"commit": "main", "sha": sha, "version": "0.2.999", "papers": 3}
    assert any("archive" in c and sha in c for c in quiet_calls)
    assert (corpus / "builds" / sha[:9] / "installed.txt").read_text("utf-8") == sha
    assert (corpus / "builds" / f"src-{sha[:9]}" / "pyproject.toml").is_file()
    papers = (corpus / "corpus").resolve()
    for cmd, cwd, out, env in steps:
        assert cmd[1:5] == ["-I", "-X", "utf8", "-c"], cmd
        assert papers not in cwd.resolve().parents and cwd.resolve() != papers
        assert out.resolve().is_relative_to((corpus / "runs" / "pr-1").resolve())
        assert "MANUSCRIPT_GUARD_DEBUG" not in env
        assert env["MANUSCRIPT_GUARD_NO_REPORTS"] == "1"
    names = {(out.parent.name, out.name) for _, _, out, _ in steps}
    assert names == {
        ("doc-1", "audit.json"), ("doc-1", "init.out"), ("doc-1", "check.json"),
        ("tex-1", "audit.json"), ("tex-1", "audit-pdf.json"), ("tex-1", "compare.json"),
        ("tex-1", "init.out"), ("tex-1", "check.json"), ("pdf-1", "audit.json")}
    project = corpus / "runs" / "pr-1" / "tex-1" / "project"
    assert (project / "manuscript" / "main.tex").is_file()
    assert (project / "literature" / "references.bib").is_file()
    # A second run of the same build runs no step again and installs nothing.
    steps.clear()
    quiet_calls.clear()
    runner.run(corpus, "main", "pr-1", REPO, jobs=1, only=["doc-1"])
    assert steps == []
    assert not any("archive" in c for c in quiet_calls)
