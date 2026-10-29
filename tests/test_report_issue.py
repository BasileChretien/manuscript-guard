"""`report-issue`: a report the person reads, edits and posts (`diagnostics.issue`).

Nothing is sent: the browser is never opened here, and no test reaches the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from manuscript_guard import __version__, cli, hooks
from manuscript_guard.diagnostics import crashes, issue

PAGE = "https://github.com/example/manuscript-guard/issues"


@pytest.fixture
def kept(tmp_path, monkeypatch) -> Path:
    """Recording on in this test's folder, a known issue page, and a browser that records."""
    folder = tmp_path / "reports"
    monkeypatch.delenv(crashes.OFF, raising=False)
    monkeypatch.delenv(crashes.DEBUG, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv(crashes.FOLDER, str(folder))
    monkeypatch.setattr(issue, "issues_page", lambda: PAGE)
    monkeypatch.chdir(tmp_path)
    return folder


@pytest.fixture
def opened(monkeypatch) -> list[str]:
    import webbrowser

    pages: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: pages.append(url) or True)
    return pages


def _crash(monkeypatch, message: str = "G7") -> None:
    def broken(_args) -> int:
        raise KeyError(message)

    monkeypatch.setattr(cli, "cmd_stages", broken)
    assert cli.main(["stages"]) == 2


def _link(out: str) -> str:
    return next(line.split(": ", 1)[1] for line in out.splitlines()
                if line.startswith("Read the report above"))  # fmt: skip


def test_the_crash_sentence_points_at_the_report(kept, monkeypatch, capsys) -> None:
    _crash(monkeypatch)
    assert "manuscript-guard report-issue --last" in capsys.readouterr().err


def test_last_prints_the_report_whole_writes_it_and_gives_both_addresses(
    kept, monkeypatch, capsys, opened
) -> None:
    _crash(monkeypatch, "secret-citekey")
    capsys.readouterr()
    assert cli.main(["report-issue", "--last"]) == 0
    out = capsys.readouterr().out
    (record,) = crashes.records()
    fingerprint = record["fingerprint"]
    assert f"`mg-{fingerprint}`" in out and "`KeyError`" in out
    assert f"manuscript-guard {__version__}" in out
    assert "secret-citekey" not in out  # the message is left out unless asked for
    assert "--with-message" in out
    assert (kept / f"{fingerprint}.md").read_text(encoding="utf-8").startswith(issue.HEAD)
    asked = parse_qs(urlsplit(_link(out)).query)
    assert asked["title"][0].startswith(f"[mg-{fingerprint}] stages: KeyError")
    assert asked["labels"] == ["bug"]
    assert asked["body"][0].startswith(issue.HEAD)
    assert f"q=is%3Aissue%20mg-{fingerprint}" in out
    assert "Nothing was sent." in out
    assert opened == []


def test_with_message_adds_it_with_the_project_taken_out(kept, monkeypatch, capsys,
                                                         tmp_path) -> None:
    (tmp_path / "paper.yaml").write_text("schema: manuscript-guard/paper/1\n", encoding="utf-8")
    _crash(monkeypatch, str(tmp_path / "manuscript" / "main.md"))
    capsys.readouterr()
    assert cli.main(["report-issue", "--with-message"]) == 0
    body = capsys.readouterr().out.split("Written to ")[0]
    assert "<PROJECT>" in body and str(tmp_path) not in body
    assert "The error's message** (read it" in body


def test_a_message_with_backticks_stays_inside_its_fence(kept, monkeypatch, capsys) -> None:
    _crash(monkeypatch, "```\n**not bold**")
    capsys.readouterr()
    cli.main(["report-issue", "--with-message"])
    out = capsys.readouterr().out
    assert "````text" in out


def test_open_hands_the_address_to_the_browser(kept, monkeypatch, capsys, opened) -> None:
    _crash(monkeypatch)
    assert cli.main(["report-issue", "--open"]) == 0
    assert len(opened) == 1 and opened[0].startswith(f"{PAGE}/new?")


def test_list_and_a_fingerprint_by_its_first_characters(kept, monkeypatch, capsys) -> None:
    _crash(monkeypatch)
    (record,) = crashes.records()
    capsys.readouterr()
    assert cli.main(["report-issue", "--list"]) == 0
    assert record["fingerprint"] in capsys.readouterr().out
    assert cli.main(["report-issue", record["fingerprint"][:5]]) == 0
    assert f"mg-{record['fingerprint']}" in capsys.readouterr().out


def test_a_fingerprint_no_record_has_is_refused(kept, monkeypatch, capsys) -> None:
    _crash(monkeypatch)
    capsys.readouterr()
    assert cli.main(["report-issue", "zzzz"]) == 2
    assert "no record's fingerprint starts with 'zzzz'" in capsys.readouterr().err
    assert cli.main(["report-issue", "ab"]) == 2


def test_nothing_recorded_is_said(kept, capsys) -> None:
    assert cli.main(["report-issue"]) == 1
    assert "No failure of the tool's own is recorded" in capsys.readouterr().err


def test_a_record_from_an_older_version_says_to_run_it_again(kept, monkeypatch,
                                                              capsys) -> None:
    _crash(monkeypatch)
    (path,) = kept.glob("*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**record, "version": "0.0.1"}), encoding="utf-8")
    capsys.readouterr()
    cli.main(["report-issue"])
    said = capsys.readouterr()
    assert "recorded under manuscript-guard 0.0.1" in said.err
    assert "**Note:** recorded under 0.0.1" in said.out


def test_a_report_of_something_else(kept, capsys) -> None:
    assert cli.main(["report-issue", "--title", "G14 calls colour a variant in a quote",
                     "--note", "Mail me at ada@example.org"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    asked = parse_qs(urlsplit(_link(out)).query)
    assert asked["title"] == ["G14 calls colour a variant in a quote"]
    assert "<EMAIL>" in out and "ada@example.org" not in out
    assert "Already reported?" not in out
    assert len(list(kept.glob("report-*.md"))) == 1


def test_title_with_a_fingerprint_is_refused(kept, capsys) -> None:
    assert cli.main(["report-issue", "abcd", "--title", "x"]) == 2


def test_a_report_too_long_for_an_address_goes_by_file(kept, monkeypatch, capsys) -> None:
    _crash(monkeypatch)
    capsys.readouterr()
    cli.main(["report-issue", "--note", "x " * 5000])
    out = capsys.readouterr().out
    link = _link(out)
    assert len(link) <= issue.LONGEST_LINK
    assert parse_qs(urlsplit(link).query)["body"] == [issue.SHORTENED]
    assert "too long for the address" in out


def test_without_an_issue_page_the_report_is_still_printed(kept, monkeypatch, capsys) -> None:
    monkeypatch.setattr(issue, "issues_page", lambda: None)
    cli.main(["report-issue", "--title", "x"])
    out = capsys.readouterr().out
    assert "does not name the project's issue page" in out
    assert "Read the report above" not in out


def test_old_reports_are_tidied_and_nothing_else(kept) -> None:
    kept.mkdir(parents=True)
    mine = kept / "notes.md"
    mine.write_text("mine", encoding="utf-8")
    orphan = kept / "0123456789ab.md"
    orphan.write_text("record gone", encoding="utf-8")
    for second in range(25):
        old = kept / f"report-20260101-0000{second:02d}-{second:06x}.md"
        old.write_text("x", encoding="utf-8")
    latest = "report-20261029-120000-abcdef.md"
    issue.write(issue.Report(title="t", body="b\n", name=latest), kept)
    assert mine.exists() and not orphan.exists()
    assert len(list(kept.glob("report-*.md"))) == 20
    assert (kept / latest).exists()


def test_two_reports_in_one_second_keep_two_files(kept) -> None:
    first = issue.general("a", None, installed=__version__)
    second = issue.general("b", None, installed=__version__)
    assert first.name != second.name
    assert issue._GENERAL_REPORT.match(first.name)


def test_too_long_with_recording_off_points_at_the_printed_report(kept, monkeypatch,
                                                                  capsys) -> None:
    monkeypatch.setenv(crashes.OFF, "1")
    cli.main(["report-issue", "--title", "x", "--note", "y " * 5000])
    out = capsys.readouterr().out
    assert "Written to" not in out
    assert "paste it from the report printed above" in out
    assert "from the file" not in out


def test_a_long_title_is_cut_and_the_address_stays_short(kept) -> None:
    report = issue.Report(title="x" * 8000, body="b\n", name="n")
    found = issue.links(report, PAGE)
    title = parse_qs(urlsplit(found.new).query)["title"][0]
    assert len(title) <= issue.LONGEST_TITLE and title.endswith("…")
    assert len(found.new) <= issue.LONGEST_LINK


def test_a_title_in_another_script_still_opens_whole(kept) -> None:
    report = issue.Report(title="\N{HIRAGANA LETTER A}" * 300, body="b\n", name="n")
    assert len(issue.links(report, PAGE).short) <= issue.LONGEST_OPENED


def test_a_title_with_bytes_that_were_not_utf8_is_printed(kept, capsys) -> None:
    assert cli.main(["report-issue", "--title", "a" + chr(0xDCFF) * 300]) == 0
    assert capsys.readouterr().out.startswith("Title: a?")


def test_a_cut_does_not_part_a_letter_from_its_accent() -> None:
    title = "x" * 198 + "e" + "\N{COMBINING ACUTE ACCENT}" + "y"
    assert issue.cut_title(title) == "x" * 198 + "…"
    # A Devanagari consonant and its vowel sign, a mark of combining class 0.
    ka, aa = chr(0x0915), chr(0x093E)
    assert issue.cut_title("x" * 198 + ka + aa + "y" * 5) == "x" * 198 + "…"


def test_the_title_is_scrubbed_whole_before_it_is_cut(kept, capsys) -> None:
    cli.main(["report-issue", "--title", "x" * 190 + " ada@example.org"])
    out = capsys.readouterr().out
    title_line = out.splitlines()[0]
    assert "ada@" not in title_line and "ada@" not in out


@pytest.mark.parametrize("command", [
    "uv run manuscript-guard report-issue --open",
    'bash -c "manuscript-guard report-issue --open"',
    'powershell -Command "manuscript-guard report-issue --open"',
    "py -m manuscript_guard.cli report-issue --open",
])  # fmt: skip
def test_the_hook_asks_when_the_tool_is_started_another_way(command) -> None:
    assert hooks._opens_report(command) is not None


def test_a_long_report_opens_with_the_title_only(kept, monkeypatch, capsys, opened) -> None:
    _crash(monkeypatch)
    capsys.readouterr()
    cli.main(["report-issue", "--open", "--note", "z " * 1500])
    out = capsys.readouterr().out
    assert "opens with the title only" in out
    (page,) = opened
    assert parse_qs(urlsplit(page).query)["body"] == [issue.SHORTENED]


def test_the_title_is_shown_in_words_before_the_body(kept, monkeypatch, capsys) -> None:
    _crash(monkeypatch)
    capsys.readouterr()
    cli.main(["report-issue"])
    assert capsys.readouterr().out.startswith("Title: [mg-")


def test_the_advice_on_the_message_names_this_record(kept, monkeypatch, capsys) -> None:
    _crash(monkeypatch)
    (record,) = crashes.records()
    capsys.readouterr()
    cli.main(["report-issue", record["fingerprint"][:6]])
    assert f"report-issue {record['fingerprint']} --with-message" in capsys.readouterr().out


def test_an_error_from_the_system_is_reported_as_one(kept, monkeypatch, capsys) -> None:
    def held(_args) -> int:
        raise PermissionError(13, "Permission denied", "x.docx")

    monkeypatch.setattr(cli, "cmd_stages", held)
    cli.main(["stages"])
    capsys.readouterr()
    cli.main(["report-issue"])
    out = capsys.readouterr().out
    assert "stopped on an error from the system it did not expect" in out
    assert "error in manuscript-guard itself" not in out


@pytest.mark.parametrize("argv", [
    ["report-issue", "abcd", "--last"],
    ["report-issue", "--title", "  "],
    ["report-issue", "--list", "--title", "x"],
    ["report-issue", "--list", "abcd"],
])  # fmt: skip
def test_flags_read_two_ways_are_refused(kept, argv, capsys) -> None:
    assert cli.main(argv) == 2


def test_a_gate_errored_finding_names_its_record(kept) -> None:
    def gate():
        raise ValueError("x")

    (finding,) = cli._guarded("G7", gate).findings
    (record,) = crashes.records()
    assert f"report-issue {record['fingerprint']}" in finding.hint


def test_the_hook_asks_before_an_agent_opens_the_page() -> None:
    def asked(command: str) -> str | None:
        return hooks._opens_report(command)

    assert asked("manuscript-guard report-issue --last --open") is not None
    assert asked("mguard report-issue abcd --open") is not None
    assert asked("manuscript-guard report-issue --last") is None
    assert asked("manuscript-guard check --open") is None
    assert asked("manuscript-guard report-issue --last; echo --open") is None
    # A quoted note holding a separator does not hide an --open after it.
    for note in ('"ran check; expected a pass"', '"R&D data"', '"a | b"', '"line one\nline two"'):
        assert asked(f"manuscript-guard report-issue --last --note {note} --open") is not None
    # An --open inside a quoted note opens nothing.
    assert asked('manuscript-guard report-issue --title x --note "tried --open"') is None


def test_the_hook_puts_the_question_to_the_person(monkeypatch, capsys) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(Path.cwd()))
    payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
               "tool_input": {"command": "manuscript-guard report-issue --open"}}  # fmt: skip
    hooks.guard_submission(payload)
    said = json.loads(capsys.readouterr().out)
    decision = said["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask"
    assert "nothing is posted until you click Submit" in decision["permissionDecisionReason"]
