"""`report-issue --about`: a report about a gate or a command that got something wrong
(`diagnostics.about`).

The test it writes is run here, in the namespace of the file it names, on the snippet it was
given, and fails or passes as the direction says. Nothing is sent, and no test reaches the
network.
"""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from generated import generated
from hypothesis import given
from hypothesis import strategies as st

from manuscript_guard import cli
from manuscript_guard.diagnostics import about, crashes, issue

PAGE = "https://github.com/example/manuscript-guard/issues"
ARTEFACT = "Certainly! Here is the revised Methods section."
#: A t of 1.20 on 40 degrees of freedom is nowhere near P = 0.001; 3.50 is.
MISFIT = "The difference was significant (t = 1.20, df = 40, P = 0.001)."
FITS = "The difference was significant (t = 3.50, df = 40, P = 0.001)."
ABBREVIATION = ("The ROR was computed for each drug.\n\n"
                "The reporting odds ratio (ROR) compares two groups of reports.\n")  # fmt: skip
UNBOUND = "The cohort grew by 4,817 people."


@pytest.fixture
def kept(tmp_path, monkeypatch) -> Path:
    """Recording on in this test's folder, a known issue page, a working folder of its own."""
    folder = tmp_path / "reports"
    monkeypatch.delenv(crashes.OFF, raising=False)
    monkeypatch.delenv(crashes.DEBUG, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv(crashes.FOLDER, str(folder))
    monkeypatch.setattr(issue, "issues_page", lambda: PAGE)
    monkeypatch.chdir(tmp_path)
    return folder


def _reported(capsys, *argv: str) -> str:
    assert cli.main(["report-issue", *argv]) == 0
    return capsys.readouterr().out


def _test_in(out: str) -> str:
    return out.split("```python\n", 1)[1].split("\n```", 1)[0]


def _run(out: str, module: str, **fixtures) -> None:
    """The test the report holds, run in the namespace of the file it is written for."""
    namespace = dict(vars(importlib.import_module(module)))
    exec(compile(_test_in(out), "<reported>", "exec"), namespace)  # noqa: S102 - our own text
    (name,) = [n for n in namespace if n.startswith("test_reported_")]
    namespace[name](**fixtures)


# ---------------------------------------------------------------- the report


def test_a_report_about_g6_follows_the_template_and_asks_for_the_gate_label(kept,
                                                                             capsys) -> None:
    out = _reported(capsys, "--about", "g6", "--flagged", "model-artefact", "--snippet",
                    ARTEFACT, "--said", "G6 model-artefact", "--note", "It is a quotation.")
    template = (Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE"
                / "gate-got-it-wrong.md").read_text(encoding="utf-8")  # fmt: skip
    for heading in ("Which direction", "The smallest text that shows it",
                    "What manuscript-guard said", "What it should have said, and why"):
        assert f"**{heading}" in template and f"**{heading}" in out
    assert f"- [x] {about.FLAGGED}: `model-artefact`" in out
    assert f"- [ ] {about.MISSED}" in out
    assert f"```markdown\n{ARTEFACT}\n```" in out
    assert "```text\nG6 model-artefact\n```" in out and "It is a quotation." in out
    assert "reproduced: the snippet alone gives `model-artefact`" in out
    asked = parse_qs(urlsplit(next(line for line in out.splitlines()
                                   if line.startswith("Read the report above"))
                              .split(": ", 1)[1]).query)  # fmt: skip
    assert asked["labels"] == ["gate"]
    assert asked["title"] == ["[G6] flagged: model-artefact"]
    name = hashlib.sha256(ARTEFACT.encode("utf-8")).hexdigest()[:12]
    assert f"def test_reported_g6_flagged_model_artefact_{name}(project: Path) -> None:" in out
    assert "Nothing was sent." in out
    assert len(list(kept.glob("report-*.md"))) == 1


def test_with_no_code_the_title_carries_the_first_words(kept, capsys) -> None:
    out = _reported(capsys, "--about", "G2", "--missed", "--snippet",
                    "one two three four five six seven eight nine ten")
    assert out.startswith("Title: [G2] missed: one two three four five six seven eight…")
    assert 'pytest.fail("TODO' in out


def test_the_snippet_is_scrubbed_and_otherwise_kept_as_written(kept, capsys) -> None:
    snippet = "Write to ada@example.org about the  two spaces.\n\nAnd a second paragraph."
    out = _reported(capsys, "--about", "G6", "--flagged", "--snippet", snippet)
    assert "ada@example.org" not in out
    assert "Write to <EMAIL> about the  two spaces.\n\nAnd a second paragraph." in out
    assert '"Write to <EMAIL> about the  two spaces.\\n"' in _test_in(out)


def test_a_snippet_file_is_read(kept, capsys, tmp_path) -> None:
    (tmp_path / "s.md").write_text(ARTEFACT + "\n", encoding="utf-8")
    out = _reported(capsys, "--about", "G6", "--flagged", "model-artefact",
                    "--snippet-file", str(tmp_path / "s.md"))
    assert "reproduced: the snippet alone gives `model-artefact`" in out


@pytest.mark.parametrize("argv", [
    ["--about", "G6", "--flagged", "--snippet", "x", "--last"],
    ["abcd", "--about", "G6", "--flagged", "--snippet", "x"],
    ["--about", "G6", "--flagged", "--snippet", "x", "--with-message"],
    ["--about", "G6", "--flagged", "--snippet", "x", "--title", "t"],
    ["--about", "G6", "--snippet", "x"],
    ["--about", "G6", "--flagged", "--missed", "--snippet", "x"],
    ["--about", "G6", "--flagged"],
    ["--about", "G6", "--flagged", "--snippet", "x", "--snippet-file", "x.md"],
    ["--about", "G6", "--flagged", "--snippet", "  \n"],
    ["--about", "G17", "--flagged", "--snippet", "x"],
    ["--about", "frobnicate", "--flagged", "--snippet", "x"],
    ["--about", "G6", "--flagged", "Some Words", "--snippet", "x"],
    ["--flagged", "--snippet", "x"],
    ["--snippet", "x", "--last"],
    ["--list", "--about", "G6"],
    ["--about", "G6", "--flagged", "--snippet-file", "absent.md"],
])  # fmt: skip
def test_a_report_about_a_gate_that_is_not_one_thing_is_refused(kept, argv, capsys) -> None:
    assert cli.main(["report-issue", *argv]) == 2
    assert capsys.readouterr().out == ""


@generated(300)
@given(st.text(min_size=1))
def test_the_snippet_in_the_test_is_the_snippet(snippet: str) -> None:
    """JSON's string, read as Python's, is the same string: quotes, backslashes, controls,
    line breaks other than a newline, and pieces cut inside a line all come back."""
    lines = about._literal(snippet)
    namespace: dict = {}
    exec("\n".join(lines), namespace)  # noqa: S102 - our own text
    assert namespace["text"] == snippet


def test_a_command_is_named_by_its_name(kept, capsys) -> None:
    out = _reported(capsys, "--about", "Explain", "--flagged", "--snippet", "x 1")
    assert "**About:** `manuscript-guard explain`." in out
    assert "not checked here" in out
    assert 'main(["explain"])  # TODO' in out


# ---------------------------------------------------------------- the check on this machine


@pytest.mark.parametrize(("argv", "said"), [
    (["G6", "--flagged", "model-artefact", ARTEFACT],
     "reproduced: the snippet alone gives `model-artefact`"),
    (["G6", "--missed", "model-artefact", ARTEFACT],
     "not reproduced: the snippet alone gives `model-artefact`; the report says so"),
    (["G14", "--flagged", "abbreviation-used-before-defined", ABBREVIATION],
     "reproduced: the snippet alone gives `abbreviation-used-before-defined`"),
    (["audit", "--flagged", "does-not-fit", MISFIT],
     "reproduced: the snippet alone gives `does-not-fit`"),
    # No list of the codes a gate can give is kept, so a code the snippet does not give is
    # said to be missing from its findings and given no verdict: it may be misspelt.
    (["audit", "--flagged", "does-not-fit", FITS],
     "`does-not-fit` is not found in the snippet's findings"),
    (["audit", "--missed", "does-not-fit", FITS],
     "`does-not-fit` is not found in the snippet's findings"),
    (["G6", "--missed", "model-artifact", ARTEFACT],
     "`model-artifact` is not found in the snippet's findings"),
    (["G6", "--flagged", "model-artifact", ARTEFACT],
     "`model-artifact` is not found in the snippet's findings"),
])  # fmt: skip
def test_the_snippet_alone_is_read_for_audit_g6_and_g14(kept, capsys, argv, said) -> None:
    gate, direction, code, snippet = argv
    out = _reported(capsys, "--about", gate, direction, code, "--snippet", snippet)
    body, after = out.split("```\n\nThe snippet, read again on this machine: ", 1)
    assert said in body and said in after
    if "not found" in said:
        line = body.split("**Does the snippet alone show it?**", 1)[1].split("\n", 1)[0]
        assert "reproduced" not in line


def test_a_gate_not_checked_here_is_said_so_alone(kept, capsys) -> None:
    out = _reported(capsys, "--about", "G2", "--missed", "unclassified-number", "--snippet",
                    UNBOUND)  # fmt: skip
    assert "read again on this machine" not in out
    assert "\n```\n\nnot checked here: " in out


def _literal_in(out: str) -> str:
    """The `text = ...` statement of the test the report holds, as it was printed."""
    lines = [line.strip() for line in _test_in(out).splitlines()]
    start = next(i for i, line in enumerate(lines) if line.startswith("text = "))
    end = start if not lines[start].endswith("(") else lines.index(")", start)
    return "\n".join(lines[start:end + 1])


def test_the_snippet_in_the_printed_test_is_the_snippet(kept, capsys) -> None:
    """The scrub is not run again over the finished report: on the test's literal it read
    `t@example.org` after an escaped tab as an address, and the literal no longer gave the
    snippet. (An escaped newline ends its piece of the literal, so the next piece opens on
    the `@`; a newline is kept in the snippet all the same.)"""
    snippet = "Line one\n\t@example.org two"
    out = _reported(capsys, "--about", "G2", "--flagged", "--snippet", snippet)
    assert f"```markdown\n{snippet}\n```" in out
    namespace: dict = {}
    exec(_literal_in(out), namespace)  # noqa: S102 - our own text
    assert namespace["text"] == snippet


def test_the_test_is_named_by_gate_direction_and_snippet(kept, capsys) -> None:
    out = _reported(capsys, "--about", "sync-bib", "--missed", "--snippet", "x")
    digest = hashlib.sha256(b"x").hexdigest()[:12]
    assert f"def test_reported_sync_bib_missed_{digest}(" in out


def test_the_check_neither_reads_nor_writes_the_project(kept, capsys, project,
                                                        monkeypatch) -> None:
    def files() -> dict[str, bytes]:
        return {p.relative_to(project).as_posix(): p.read_bytes()
                for p in sorted(project.rglob("*")) if p.is_file()}  # fmt: skip

    before = files()
    monkeypatch.chdir(project)
    read: list[Path] = []
    real = about._read_alone

    def watched(gate: str, snippet: str) -> set[str]:
        import manuscript_guard.audit as audit_module

        original = audit_module.audit

        def audit(papers, backing, **kwargs):
            read.extend(papers)
            return original(papers, backing, **kwargs)

        monkeypatch.setattr(audit_module, "audit", audit)
        return real(gate, snippet)

    monkeypatch.setattr(about, "_read_alone", watched)
    out = _reported(capsys, "--about", "audit", "--flagged", "does-not-fit", "--snippet", MISFIT)
    assert "reproduced" in out
    assert files() == before
    (paper,) = read
    assert project.resolve() not in paper.resolve().parents


def test_a_reading_that_stops_is_said_and_recorded(kept, capsys, monkeypatch) -> None:
    def broken(gate: str, snippet: str) -> set[str]:
        raise RuntimeError("x")

    monkeypatch.setattr(about, "_read_alone", broken)
    out = _reported(capsys, "--about", "G6", "--flagged", "--snippet", ARTEFACT)
    (record,) = crashes.records()
    assert (f"not checked: G6 stopped on RuntimeError reading the snippet alone "
            f"(`manuscript-guard report-issue {record['fingerprint']}` reports that)") in out


# ---------------------------------------------------------------- the test it writes, run


def test_the_audit_test_fails_on_a_wrong_flag_and_passes_on_a_fit(kept, capsys,
                                                                  tmp_path) -> None:
    flagged = _reported(capsys, "--about", "audit", "--flagged", "does-not-fit", "--snippet",
                        MISFIT)  # fmt: skip
    assert "tests/test_audit.py" in flagged
    (tmp_path / "a").mkdir()
    with pytest.raises(AssertionError):
        _run(flagged, "test_audit", tmp_path=tmp_path / "a")
    fits = _reported(capsys, "--about", "audit", "--flagged", "does-not-fit", "--snippet", FITS)
    (tmp_path / "b").mkdir()
    _run(fits, "test_audit", tmp_path=tmp_path / "b")
    missed = _reported(capsys, "--about", "audit", "--missed", "does-not-fit", "--snippet",
                       MISFIT)  # fmt: skip
    (tmp_path / "c").mkdir()
    _run(missed, "test_audit", tmp_path=tmp_path / "c")


@pytest.mark.parametrize(("direction", "fails"), [("--flagged", True), ("--missed", False)])
def test_the_g6_test_fails_or_passes_as_the_direction_says(kept, capsys, project, direction,
                                                            fails) -> None:
    out = _reported(capsys, "--about", "G6", direction, "model-artefact", "--snippet", ARTEFACT)
    assert "tests/test_writing.py" in out
    if fails:
        with pytest.raises(AssertionError):
            _run(out, "test_writing", project=project)
    else:
        _run(out, "test_writing", project=project)


def test_the_g14_test_runs_in_its_file(kept, capsys, project) -> None:
    out = _reported(capsys, "--about", "G14", "--flagged", "abbreviation-used-before-defined",
                    "--snippet", ABBREVIATION)
    assert "tests/test_language.py" in out
    with pytest.raises(AssertionError):
        _run(out, "test_language", project=project)


@pytest.mark.parametrize(("direction", "fails"), [("--flagged", True), ("--missed", False)])
def test_another_gates_test_appends_to_the_example(kept, capsys, project, direction,
                                                    fails) -> None:
    out = _reported(capsys, "--about", "G2", direction, "unclassified-number", "--snippet",
                    UNBOUND)  # fmt: skip
    assert "tests/test_corruption.py" in out
    if fails:
        with pytest.raises(AssertionError):
            _run(out, "test_corruption", project=project)
    else:
        _run(out, "test_corruption", project=project)


def test_with_no_code_the_test_stops_at_its_todo(kept, capsys, project) -> None:
    out = _reported(capsys, "--about", "G6", "--flagged", "--snippet", ARTEFACT)
    with pytest.raises(pytest.fail.Exception, match="TODO"):
        _run(out, "test_writing", project=project)


@pytest.mark.parametrize("skill", ["guide", "project-setup"])
def test_the_skills_name_the_fingerprint_after_a_gate_errored_finding(skill) -> None:
    text = (Path(__file__).resolve().parents[1] / "plugin" / "skills" / skill
            / "SKILL.md").read_text(encoding="utf-8")  # fmt: skip
    line = next(line for line in text.splitlines() if "`gate-errored`" in line
                and "report-issue" in line)  # fmt: skip
    assert "`manuscript-guard report-issue <fingerprint>`" in line
    assert line.index("<fingerprint>") < line.index("--last")


def test_two_codes_on_one_snippet_name_two_tests(kept, capsys) -> None:
    names = {_test_in(_reported(capsys, "--about", "G6", "--flagged", code, "--snippet",
                                ARTEFACT)).split("(", 1)[0] for code in ("a-b", "c-d")}
    assert len(names) == 2


@pytest.mark.parametrize(("direction", "code", "fails"), [
    ("--flagged", "unclassified", True), ("--missed", "unclassified", False),
    # The example's numbers are read by a convention already: the snippet adds none.
    ("--missed", "convention", True),
])  # fmt: skip
def test_a_commands_test_counts_what_the_snippet_adds(kept, capsys, project, monkeypatch,
                                                      direction, code, fails) -> None:
    out = _reported(capsys, "--about", "explain", direction, code, "--snippet", UNBOUND)
    # The words the person gave the command, as the TODO asks for them.
    out = out.replace('main(["explain"])', 'main(["explain", "manuscript/main.md"])')
    fixtures = {"project": project, "monkeypatch": monkeypatch, "capsys": capsys}
    if fails:
        with pytest.raises(AssertionError):
            _run(out, "test_corruption", **fixtures)
    else:
        _run(out, "test_corruption", **fixtures)
