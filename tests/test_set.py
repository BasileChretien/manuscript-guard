"""`manuscript-guard set`: one setting of paper.yaml written, every other byte kept.

The file is the author's and most of it is comments, so `set` edits its text and reads the
result back before writing it (DESIGN.md, "One setting is written, and the file kept").
Each refusal leaves the file as it was, byte for byte.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest
import yaml

from manuscript_guard import hooks
from manuscript_guard.cli import main
from manuscript_guard.paper_edit import KEYS, Refused, edit

#: A value for each key, and a second one.
VALUES = {
    "stage": ("analysis", "drafting"),
    "target_journal": ("journal-one", "journal-two"),
    "english_variant": ("en-US", "en-GB"),
    "reporting_guideline": (["STROBE", "RECORD"], ["CONSORT"]),
    "study_type": ("cohort", "trial"),
}

#: A paper.yaml with comments everywhere, holding each key in no form yet.
HEAD = """\
schema: manuscript-guard/paper/1
# The title, on one line.
title: "A paper"   # kept as written

# Numbers that are names.
terms: []

"""
TAIL = """\

# The end of the file, kept.
lookup:
  not_indexed:
    # nested, and not the setting
    {key}: invented for this test
"""


def _written(key: str, value) -> str:
    if isinstance(value, list):
        return f"{key}: [{', '.join(value)}]"
    return f"{key}: {value}"


def _paper(key: str, form: str) -> str:
    """The file with `key` absent, commented as `init` comments it, or set."""
    line = {
        "absent": "",
        "commented": f"# The setting, explained.\n# {_written(key, VALUES[key][1])}\n",
        "set": f"# The setting, explained.\n{_written(key, VALUES[key][1])}   # why\n",
    }[form]
    return HEAD + line + TAIL.format(key=key)


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    (root / "profiles" / "journals").mkdir(parents=True)
    for name in ("journal-one", "journal-two"):
        (root / "profiles" / "journals" / f"{name}.yaml").write_text("{}\n", encoding="utf-8")
    return root / "paper.yaml"


def _set(paper: Path, key: str, *words: str) -> int:
    return main(["set", key, *words, "--path", str(paper.parent)])


def _words(value) -> list[str]:
    return list(value) if isinstance(value, list) else [value]


@pytest.mark.parametrize("form", ["absent", "commented", "set"])
@pytest.mark.parametrize("key", KEYS)
def test_each_key_is_set_and_nothing_else_changes(paper: Path, key: str, form: str) -> None:
    before = _paper(key, form)
    paper.write_bytes(before.encode())
    value = VALUES[key][0]
    assert _set(paper, key, *_words(value)) == 0
    after = paper.read_bytes().decode()
    old, new = yaml.safe_load(before), yaml.safe_load(after)
    assert new == {**old, key: value}
    assert new["lookup"]["not_indexed"] == {key: "invented for this test"}
    # Every line but the setting's own is as it was, in its place.
    changed = [
        (was, now)
        for was, now in zip(before.splitlines(), after.splitlines(), strict=False)
        if was != now
    ]
    if form == "absent":
        assert after == before + _written(key, value) + "\n"
    elif form == "commented":
        assert changed == [(f"# {_written(key, VALUES[key][1])}", _written(key, value))]
    else:
        assert changed == [
            (f"{_written(key, VALUES[key][1])}   # why", f"{_written(key, value)}   # why")
        ]
    assert len(after.splitlines()) == len(before.splitlines()) + (form == "absent")


def test_init_s_file_takes_each_setting_where_init_left_it(tmp_path: Path) -> None:
    root = tmp_path / "paper"
    assert main(["init", str(root)]) == 0
    (root / "profiles" / "journals").mkdir(parents=True, exist_ok=True)
    (root / "profiles" / "journals" / "journal-one.yaml").write_text("{}\n", encoding="utf-8")
    before = (root / "paper.yaml").read_bytes().decode()
    for key in KEYS:
        assert _set(root / "paper.yaml", key, *_words(VALUES[key][0])) == 0
    after = (root / "paper.yaml").read_bytes().decode()
    assert len(after.splitlines()) == len(before.splitlines()), "nothing was added at the end"
    assert yaml.safe_load(after) == {
        **yaml.safe_load(before),
        **{key: values[0] for key, values in VALUES.items()},
    }
    # The comments init wrote are all still there, but the examples made settings.
    kept = [line for line in before.splitlines() if line.startswith("#")]
    examples = {f"# {key}:" for key in KEYS}
    assert [line for line in after.splitlines() if line.startswith("#")] == [
        line for line in kept if not any(line.startswith(example) for example in examples)
    ]


def test_a_list_one_entry_to_a_line_keeps_its_layout(paper: Path) -> None:
    paper.write_bytes(
        b"schema: manuscript-guard/paper/1\ntitle: A\n\nreporting_guideline:  # chosen\n"
        b"    - STROBE\n    - RECORD\n\n# after\nterms: []\n"
    )
    assert _set(paper, "reporting_guideline", "CONSORT", "SPIRIT", "TRIPOD") == 0
    assert paper.read_bytes() == (
        b"schema: manuscript-guard/paper/1\ntitle: A\n\nreporting_guideline:  # chosen\n"
        b"    - CONSORT\n    - SPIRIT\n    - TRIPOD\n\n# after\nterms: []\n"
    )
    assert _set(paper, "reporting_guideline") == 0
    assert paper.read_bytes() == (
        b"schema: manuscript-guard/paper/1\ntitle: A\n\nreporting_guideline: []  # chosen\n"
        b"\n# after\nterms: []\n"
    )


def test_line_endings_and_a_byte_order_mark_are_kept(paper: Path) -> None:
    paper.write_bytes(b"\xef\xbb\xbfschema: manuscript-guard/paper/1\r\ntitle: A\r\n# x\r\n")
    assert _set(paper, "stage", "analysis") == 0
    assert _set(paper, "english_variant", "en-GB") == 0
    assert paper.read_bytes() == (
        b"\xef\xbb\xbfschema: manuscript-guard/paper/1\r\ntitle: A\r\n# x\r\n"
        b"stage: analysis\r\nenglish_variant: en-GB\r\n"
    )


def test_a_value_already_set_is_not_written(paper: Path, capsys) -> None:
    text = b"schema: manuscript-guard/paper/1\ntitle: A\nstage:   'analysis'\n"
    paper.write_bytes(text)
    assert _set(paper, "stage", "analysis") == 0
    assert "nothing written" in capsys.readouterr().out
    assert paper.read_bytes() == text


def test_an_empty_value_is_filled_after_its_colon(paper: Path) -> None:
    paper.write_bytes(b"schema: manuscript-guard/paper/1\ntitle: A\nstage:\nstudy_type:  # later\n")
    assert _set(paper, "stage", "design") == 0
    assert _set(paper, "study_type", "trial") == 0
    assert paper.read_bytes() == (
        b"schema: manuscript-guard/paper/1\ntitle: A\nstage: design\nstudy_type: trial  # later\n"
    )


def test_a_commented_example_inside_another_block_is_left_and_the_key_added(paper: Path) -> None:
    """Made a setting there, the line would end `review`'s block."""
    text = (
        "schema: manuscript-guard/paper/1\ntitle: A\nreview:\n# stage: design\n"
        "  rounds_required: 2\n"
    )
    paper.write_bytes(text.encode())
    assert _set(paper, "stage", "analysis") == 0
    assert paper.read_bytes().decode() == text + "stage: analysis\n"


def test_a_commented_line_inside_a_quoted_value_is_not_a_comment(paper: Path) -> None:
    text = 'schema: manuscript-guard/paper/1\ntitle: "A long\n# stage: design\n  title"\n'
    paper.write_bytes(text.encode())
    assert _set(paper, "stage", "analysis") == 0
    assert paper.read_bytes().decode() == text + "stage: analysis\n"


def test_two_commented_examples_are_both_left(paper: Path) -> None:
    text = "schema: manuscript-guard/paper/1\ntitle: A\n# stage: design\n# stage: analysis\n"
    paper.write_bytes(text.encode())
    assert _set(paper, "stage", "drafting") == 0
    assert paper.read_bytes().decode() == text + "stage: drafting\n"


def test_a_value_that_is_not_a_name_is_quoted(paper: Path) -> None:
    paper.write_bytes(b"schema: manuscript-guard/paper/1\ntitle: A\n")
    assert _set(paper, "reporting_guideline", "yes", "2024", "A guideline", "it's") == 0
    assert yaml.safe_load(paper.read_bytes())["reporting_guideline"] == [
        "yes", "2024", "A guideline", "it's"
    ]  # fmt: skip


#: Each file `set` must refuse, and what the refusal says.
REFUSED = {
    "a flow mapping": ("{schema: manuscript-guard/paper/1, title: A}\n", "between braces"),
    "an anchor": ("schema: manuscript-guard/paper/1\ntitle: &t A\nshort_title: *t\n", "anchor"),
    "a key twice": (
        "schema: manuscript-guard/paper/1\ntitle: A\nstage: design\nstage: analysis\n",
        "written twice",
    ),
    "a key twice inside a block": (
        "schema: manuscript-guard/paper/1\ntitle: A\nreview:\n  models: []\n  models: []\n",
        "written twice",
    ),
    "a folded value": (
        "schema: manuscript-guard/paper/1\ntitle: A\nstage: >\n  design\n",
        "several lines",
    ),  # fmt: skip
    "a value over two lines": (
        "schema: manuscript-guard/paper/1\ntitle: A\nstage: design\n  and more\n",
        "several lines",
    ),
    "a list with a comment among its entries": (
        "schema: manuscript-guard/paper/1\ntitle: A\nreporting_guideline:\n  - STROBE\n"
        "  # and\n  - RECORD\n",
        "comment",
    ),
    "not YAML": ("schema: [\n", "cannot be read"),
    "a list": ("- schema\n", "no settings"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_a_file_set_cannot_edit_safely_is_left_byte_for_byte(
    paper: Path, case: str, capsys
) -> None:
    text, said = REFUSED[case]
    paper.write_bytes(text.encode())
    key = "reporting_guideline" if "list with" in case else "stage"
    assert _set(paper, key, *(["CONSORT"] if key != "stage" else ["drafting"])) == 2
    assert said in capsys.readouterr().err
    assert paper.read_bytes() == text.encode()


@pytest.mark.parametrize(
    ("key", "words", "said"),
    [
        ("stage", ["finished"], "takes one of design"),
        ("stage", ["design", "analysis"], "takes one value"),
        ("stage", [], "takes one value"),
        ("english_variant", ["en-AU"], "en-GB, en-US"),
        ("study_type", ["case-series"], "cohort"),
        ("target_journal", ["journal-three"], "journal --template journal-three"),
        ("reporting_guideline", ["STROBE", "STROBE"], "given twice"),
        ("reporting_guideline", [" STROBE"], "not a name"),
        ("reporting_guideline", ["STR\nOBE"], "not a name"),
    ],
)
def test_a_value_the_key_does_not_take_is_refused_and_nothing_written(
    paper: Path, key: str, words: list[str], said: str, capsys
) -> None:
    text = _paper(key, "set")
    paper.write_bytes(text.encode())
    assert _set(paper, key, *words) == 2
    assert said in capsys.readouterr().err
    assert paper.read_bytes() == text.encode()


def test_the_schema_is_asked_of_the_value_and_of_the_file() -> None:
    with pytest.raises(Refused, match="cannot be"):
        edit("schema: manuscript-guard/paper/1\ntitle: A\n", "study_type", "case-series")
    with pytest.raises(Refused, match="cannot be"):
        edit("schema: manuscript-guard/paper/1\ntitle: A\n", "reporting_guideline", [""])
    # What the schema found before is not the edit's doing, and does not stop it.
    done = edit("title: A\nstage: design\n", "stage", "analysis")
    assert done.text == "title: A\nstage: analysis\n"


def test_a_journal_the_shortlist_names_may_be_set(paper: Path) -> None:
    (paper.parent / "journals").mkdir()
    (paper.parent / "journals" / "shortlist.yaml").write_text(
        "candidates:\n  - journal: Example Journal\n    profile: example-journal\n",
        encoding="utf-8",
    )
    paper.write_bytes(b"schema: manuscript-guard/paper/1\ntitle: A\n")
    assert _set(paper, "target_journal", "example-journal") == 0
    assert yaml.safe_load(paper.read_bytes())["target_journal"] == "example-journal"


def test_no_project_is_said(tmp_path: Path, capsys) -> None:
    assert main(["set", "stage", "design", "--path", str(tmp_path)]) == 2
    assert "no paper.yaml" in capsys.readouterr().err


# ------------------------------------------------------------------ the hook asks


def _hook(cwd: Path, command: str, monkeypatch, capsys, **more) -> dict | None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(cwd))
    payload = {"cwd": str(cwd), "tool_name": "Bash", "tool_input": {"command": command}, **more}
    assert hooks.dispatch("guard-submission", payload) == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


def _decision(result: dict | None) -> str | None:
    return (result or {}).get("hookSpecificOutput", {}).get("permissionDecision")


@pytest.mark.parametrize(
    "command",
    [
        "manuscript-guard set stage design",
        "cd . && mguard set stage 'analysis'",
        'manuscript-guard set --path "{root}" stage design',
        "cd {root} && python -m manuscript_guard.cli set stage design",
        "manuscript-guard set stage \\\n  design",
    ],
)
def test_moving_the_stage_back_is_put_to_the_author(
    tmp_path: Path, command: str, monkeypatch, capsys
) -> None:
    root = tmp_path / "paper"
    root.mkdir()
    (root / "paper.yaml").write_text("schema: manuscript-guard/paper/1\ntitle: A\n"
                                     "stage: drafting\n", encoding="utf-8")  # fmt: skip
    cwd = tmp_path if "{root}" in command else root
    result = _hook(cwd, command.format(root=root), monkeypatch, capsys)
    assert _decision(result) == "ask", result
    assert "author's decision" in result["hookSpecificOutput"]["permissionDecisionReason"]
    # Codex cannot ask: the call is refused, and the author makes it.
    result = _hook(cwd, command.format(root=root), monkeypatch, capsys, turn_id="t")
    assert _decision(result) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "manuscript-guard set stage internal-review",
        "manuscript-guard set stage drafting",
        "manuscript-guard set target_journal design",
        "manuscript-guard set english_variant en-US",
        "manuscript-guard set stage submission 2>&1",
        "manuscript-guard set stage submission > log.txt 2>&1",
        "mguard.exe set stage submission >> log.txt",
        "python -m manuscript_guard.cli set stage submission 2> err.txt",
        "cd . && manuscript-guard set stage submission --path .",
        "manuscript-guard stages && git status",
    ],
)
def test_moving_the_stage_on_or_setting_anything_else_is_not_asked(
    tmp_path: Path, command: str, monkeypatch, capsys
) -> None:
    (tmp_path / "paper.yaml").write_text("schema: manuscript-guard/paper/1\ntitle: A\n"
                                         "stage: drafting\n", encoding="utf-8")  # fmt: skip
    assert _hook(tmp_path, command, monkeypatch, capsys) is None


@pytest.mark.parametrize(
    "command",
    [
        # Round 2 of #456: each of these moved the stage back unasked.
        "manuscript-guard set stage design 2>&1",
        "bash -c 'manuscript-guard set stage design'",
        'sh -c "manuscript-guard set stage design"',
        'powershell -Command "manuscript-guard set stage design"',
        "echo design | xargs manuscript-guard set stage",
        "manuscript-guard set stage $('design')",
        "manuscript-guard set stage (Get-Content s.txt)",
        "$s = 'design'; manuscript-guard set stage $s",
        "manuscript-guard set stage @args",
        "env -C elsewhere manuscript-guard set stage submission",
        "uv run --directory elsewhere manuscript-guard set stage submission",
        "manuscript-guard 'set' stage design",
        "manuscript-guard -- set stage design",
        "manuscript-guard set -- stage design",
        "(cd elsewhere && manuscript-guard set stage submission)",
        "cd elsewhere || manuscript-guard set stage submission",
        "{ manuscript-guard set stage submission; }",
        "eval manuscript-guard set stage design",
        "manuscript-guard set stage `echo design`",
        "manuscript-guard set stage finished",
        "manuscript-guard set stage submission | tee log.txt",
        "manuscript-guard set stage submission && git status",
        "manuscript-guard stages && echo set stage design",
    ],
)
def test_a_set_the_guard_does_not_read_exactly_is_asked(
    tmp_path: Path, command: str, monkeypatch, capsys
) -> None:
    """Ask by default: only a plain invocation, after plain `cd` steps and before plain
    redirections, is read and let through."""
    (tmp_path / "paper.yaml").write_text("schema: manuscript-guard/paper/1\ntitle: A\n"
                                         "stage: drafting\n", encoding="utf-8")  # fmt: skip
    assert _decision(_hook(tmp_path, command, monkeypatch, capsys)) == "ask", command


def test_a_project_with_no_stage_is_at_drafting(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "paper.yaml").write_text("schema: manuscript-guard/paper/1\ntitle: A\n",
                                         encoding="utf-8")  # fmt: skip
    command = "manuscript-guard set stage analysis"
    assert _decision(_hook(tmp_path, command, monkeypatch, capsys)) == "ask"
    assert _hook(tmp_path, "manuscript-guard set stage submission", monkeypatch, capsys) is None


def _project(folder: Path, settings: str = "stage: submission\n") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "paper.yaml").write_text(
        "schema: manuscript-guard/paper/1\ntitle: A\n" + settings, encoding="utf-8"
    )
    return folder


@pytest.mark.parametrize(
    "command",
    [
        # Round 1: the `cd` was not followed, `--path` was read from the hook's folder, no
        # project was found there, and the stage moved back unasked.
        "cd papers && manuscript-guard set stage drafting --path paper",
        "Set-Location papers; manuscript-guard set stage drafting --path paper",
        "cd papers/paper && manuscript-guard set stage drafting",
    ],
)
def test_a_folder_changed_before_the_set_is_followed(
    tmp_path: Path, command: str, monkeypatch, capsys
) -> None:
    _project(tmp_path / "papers" / "paper")
    assert _decision(_hook(tmp_path, command, monkeypatch, capsys)) == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "pushd $HOME/papers && manuscript-guard set stage design",
        "popd && manuscript-guard set stage design",
        "cd && manuscript-guard set stage design",
        "git status && (cd elsewhere/x; manuscript-guard set stage design)",
        "x=1 cd papers && manuscript-guard set stage design",
        "manuscript-guard set stage $STAGE",
        "manuscript-guard set stage design --path nowhere-at-all",
        "manuscript-guard set reporting_guideline --path $P",
    ],
)
def test_what_the_guard_cannot_read_is_asked(
    tmp_path: Path, command: str, monkeypatch, capsys
) -> None:
    """Fail closed: a change of folder the guard does not follow, a value through the shell,
    or no project where the command looks."""
    cwd = tmp_path / "here"
    cwd.mkdir()
    assert _decision(_hook(cwd, command, monkeypatch, capsys)) == "ask", command


def test_an_unreadable_paper_yaml_is_asked(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "paper.yaml").write_text("stage: [\n", encoding="utf-8")
    command = "manuscript-guard set stage submission"
    assert _decision(_hook(tmp_path, command, monkeypatch, capsys)) == "ask"


@pytest.mark.parametrize("stage", ["dr''afting", "draf\\ting", '"drafting"'])
def test_a_stage_a_posix_shell_unquotes_is_read_as_the_shell_reads_it(
    tmp_path: Path, stage: str, monkeypatch, capsys
) -> None:
    _project(tmp_path)
    command = f"manuscript-guard set stage {stage}"
    assert _decision(_hook(tmp_path, command, monkeypatch, capsys)) == "ask", stage


def test_only_the_set_s_own_project_is_read(tmp_path: Path, monkeypatch, capsys) -> None:
    """Round 1: a forward move for one project was asked because the line named another at
    a later stage."""
    _project(tmp_path / "a", "stage: design\n")
    _project(tmp_path / "b", "stage: submission\n")
    command = "manuscript-guard set stage analysis --path a"
    assert _hook(tmp_path, command, monkeypatch, capsys) is None
    command = "cd a && manuscript-guard set stage analysis > ../b/log.txt"
    assert _hook(tmp_path, command, monkeypatch, capsys) is None
    # Round 2 of #456: `sl` inside an earlier word was taken for a change of folder.
    command = "cd docs/sl && manuscript-guard set stage analysis --path ../../a"
    (tmp_path / "docs" / "sl").mkdir(parents=True)
    assert _hook(tmp_path, command, monkeypatch, capsys) is None


@pytest.mark.skipif(os.name != "nt", reason="a backslash separates folders on Windows only")
def test_a_windows_folder_with_backslashes_is_read_as_one(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Round 2 of #456: `cd papers\\a; …` was read as `papersa` too, found no project, and
    asked for a forward move."""
    _project(tmp_path / "papers" / "a", "stage: design\n")
    for command in (
        "cd papers\\a; manuscript-guard set stage analysis",
        "manuscript-guard set stage analysis --path papers\\a",
    ):
        assert _hook(tmp_path, command, monkeypatch, capsys) is None, command
    command = "cd papers\\a; manuscript-guard set stage design --path ."
    _project(tmp_path / "papers" / "a", "stage: drafting\n")
    assert _decision(_hook(tmp_path, command, monkeypatch, capsys)) == "ask"


@pytest.mark.parametrize(
    ("settings", "command", "asked"),
    [
        ("reporting_guideline: [STROBE, RECORD]\n",
         "manuscript-guard set reporting_guideline RECORD", True),
        ("reporting_guideline: [STROBE]\n", "manuscript-guard set reporting_guideline", True),
        ("reporting_guideline: [STROBE]\n",
         "manuscript-guard set reporting_guideline STROBE RECORD", False),
        ("reporting_guideline: []\n", "manuscript-guard set reporting_guideline STROBE", False),
        ("", "manuscript-guard set reporting_guideline STROBE", False),
        ("target_journal: journal-one\n", "manuscript-guard set target_journal journal-two",
         True),
        ("target_journal: journal-one\n", "manuscript-guard set target_journal journal-one",
         False),
        ("", "manuscript-guard set target_journal journal-one", False),
        ("stage: design\n", "manuscript-guard set english_variant en-US", False),
    ],
)  # fmt: skip
def test_taking_a_guideline_away_or_replacing_the_journal_is_asked(
    tmp_path: Path, settings: str, command: str, asked: bool, monkeypatch, capsys
) -> None:
    _project(tmp_path, settings)
    result = _hook(tmp_path, command, monkeypatch, capsys)
    assert (_decision(result) == "ask") is asked, result


# ------------------------------------------------------------------ the file it writes


def test_a_note_after_the_commented_example_stays(paper: Path) -> None:
    paper.write_bytes(
        b"schema: manuscript-guard/paper/1\ntitle: A\n# stage: design  # until the plan is frozen\n"
    )
    assert _set(paper, "stage", "analysis") == 0
    assert paper.read_bytes() == (
        b"schema: manuscript-guard/paper/1\ntitle: A\nstage: analysis  # until the plan is frozen\n"
    )


@pytest.mark.parametrize("code", [0x85, 0x2028, 0x2029])
@pytest.mark.parametrize("where", ["comment", "quoted"])
def test_a_line_break_only_yaml_reads_is_refused(
    paper: Path, code: int, where: str, capsys
) -> None:
    held = f"# a note{chr(code)}more\n" if where == "comment" else f'short_title: "A{chr(code)}B"\n'
    text = f"schema: manuscript-guard/paper/1\ntitle: A\n{held}stage: design\n".encode()
    paper.write_bytes(text)
    assert _set(paper, "stage", "analysis") == 2
    assert f"U+{code:04X}" in capsys.readouterr().err
    assert paper.read_bytes() == text


@pytest.mark.parametrize(
    "name", ["1e3", "0o17", "0x1F", ".inf", "-.Inf", ".nan", "1_000", "+1", "1.5", "null",
             "True", "yes", "2024-01-01", "~", "y", "Y", "n", "N", "On", "oFF", "nO"],
)  # fmt: skip
def test_a_name_any_yaml_reader_types_is_quoted(name: str) -> None:
    from manuscript_guard.paper_edit import written

    assert written(name).startswith("'"), name
    assert yaml.safe_load(f"k: {written(name)}") == {"k": name}
    assert written("RECORD-PE") == "RECORD-PE" and written("journal.one") == "journal.one"


def test_the_value_is_checked_before_the_file_is_read(paper: Path, capsys) -> None:
    paper.write_bytes(b"\xff not even UTF-8\n")
    assert _set(paper, "stage", "finished") == 2
    assert "takes one of" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_file_keeps_its_mode(paper: Path) -> None:
    paper.write_bytes(b"schema: manuscript-guard/paper/1\ntitle: A\n")
    paper.chmod(0o664)
    assert _set(paper, "stage", "analysis") == 0
    assert stat.S_IMODE(paper.stat().st_mode) == 0o664


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root writes anyway")
def test_a_read_only_paper_yaml_is_refused_and_nothing_left(paper: Path, capsys) -> None:
    """Round 2 of #456: on Windows the copied mode left the new file read-only, the rename
    and the clean-up both failed, and a read-only `.paper.*.tmp` stayed in the project; on
    a POSIX system the file was replaced anyway."""
    text = b"schema: manuscript-guard/paper/1\ntitle: A\n"
    paper.write_bytes(text)
    paper.chmod(stat.S_IREAD)
    try:
        assert _set(paper, "stage", "analysis") == 2
        assert "read-only" in capsys.readouterr().err
        assert paper.read_bytes() == text
        assert [p.name for p in paper.parent.iterdir() if p.name.startswith(".paper.")] == []
    finally:
        paper.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_a_temporary_file_marked_read_only_is_cleaned_up(paper: Path, monkeypatch) -> None:
    """The clean-up unmarks the file before deleting it."""
    from manuscript_guard import paper_edit

    paper.write_bytes(b"schema: manuscript-guard/paper/1\ntitle: A\n")

    def read_only_then_fail(source, target) -> None:
        os.chmod(target, stat.S_IREAD)
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(shutil, "copymode", read_only_then_fail)
    with pytest.raises(PermissionError):
        paper_edit.write(paper, "stage: analysis\n")
    assert [p.name for p in paper.parent.iterdir() if p.name.startswith(".paper.")] == []


def test_a_file_that_cannot_be_replaced_is_said(paper: Path, monkeypatch, capsys) -> None:
    text = b"schema: manuscript-guard/paper/1\ntitle: A\n"
    paper.write_bytes(text)

    def refused(*_args) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", refused)
    assert _set(paper, "stage", "analysis") == 2
    assert "could not be written: Permission denied" in capsys.readouterr().err
    monkeypatch.undo()
    assert paper.read_bytes() == text
    assert [p.name for p in paper.parent.iterdir() if p.name.startswith(".paper.")] == []


def test_a_linked_paper_yaml_is_refused(paper: Path, capsys) -> None:
    text = b"schema: manuscript-guard/paper/1\ntitle: A\n"
    target = paper.parent / "real.yaml"
    target.write_bytes(text)
    os.link(target, paper)
    assert _set(paper, "stage", "analysis") == 2
    assert "hard link" in capsys.readouterr().err
    paper.unlink()
    try:
        paper.symlink_to(target)
    except OSError:
        pytest.skip("this system makes no symbolic link here")
    assert _set(paper, "stage", "analysis") == 2
    assert "symbolic link" in capsys.readouterr().err
    assert target.read_bytes() == text


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root writes anyway")
def test_a_read_only_paper_yaml_that_holds_the_value_already_is_no_failure(paper: Path) -> None:
    paper.write_bytes(b"schema: manuscript-guard/paper/1\ntitle: A\nstage: analysis\n")
    paper.chmod(stat.S_IREAD)
    try:
        assert _set(paper, "stage", "analysis") == 0
    finally:
        paper.chmod(stat.S_IREAD | stat.S_IWRITE)


# --------------------------------------------- the fix-only round of #456: what the guard reads


@pytest.mark.parametrize(
    "command",
    [
        # `cd -` goes back to the folder before: here, to a project at a later stage.
        "cd {late} && cd {early} && cd - && manuscript-guard set stage drafting",
        "cd -P {early} && manuscript-guard set stage drafting",
        "cd -- {early} && manuscript-guard set stage drafting",
        "pushd +1 && manuscript-guard set stage drafting",
        "Set-Location - ; manuscript-guard set stage drafting",
        "cd && manuscript-guard set stage drafting",
        # A backslash in a value, and one before a space anywhere, is the guard's to refuse
        # on every system: Git Bash reads `X\ RECORD` as one word.
        "manuscript-guard set reporting_guideline STROBE X\\ RECORD --path {early}",
        "manuscript-guard set reporting_guideline STROBE RECORD\\x --path {early}",
        "cd {early}\\ x && manuscript-guard set stage drafting",
        # Output written over a file the tool reads.
        "manuscript-guard set stage submission --path {early} > {early}/paper.yaml",
        "manuscript-guard set stage submission --path {early} 2> authors.yaml",
        "manuscript-guard set stage drafting --path {late} 3>log.txt",
    ],
)
def test_what_the_fix_only_round_found_is_asked(
    tmp_path: Path, command: str, monkeypatch, capsys
) -> None:
    """Each a forward move for `early` or an added guideline, which the guard let through,
    where the shell moves `late` back or reads the words otherwise."""
    early = _project(tmp_path / "early", "stage: design\nreporting_guideline: [STROBE]\n")
    late = _project(tmp_path / "late", "stage: submission\n")
    command = command.format(early=early.as_posix(), late=late.as_posix())
    assert _decision(_hook(tmp_path, command, monkeypatch, capsys)) == "ask", command


@pytest.mark.parametrize(
    "command",
    [
        "manuscript-guard set stage submission --path {early} 3>log.txt",
        "manuscript-guard set stage submission --path {early} 10>>log.txt 2>&1",
        "cd {early} && manuscript-guard set reporting_guideline STROBE RECORD > out.txt",
    ],
)
def test_a_redirection_by_any_descriptor_is_read(
    tmp_path: Path, command: str, monkeypatch, capsys
) -> None:
    early = _project(tmp_path / "early", "stage: analysis\nreporting_guideline: [STROBE]\n")
    command = command.format(early=early.as_posix())
    assert _hook(tmp_path, command, monkeypatch, capsys) is None, command


def test_a_folder_that_cannot_be_had_is_asked(tmp_path: Path, monkeypatch, capsys) -> None:
    from manuscript_guard.set_guard import asks

    assert "cannot be read" in asks("manuscript-guard set stage submission", None)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    payload = {"cwd": "a" + chr(0) + "b", "tool_name": "Bash",
               "tool_input": {"command": "manuscript-guard set stage submission"}}  # fmt: skip
    assert hooks.dispatch("guard-submission", payload) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "ask"


#: Typographic quotation marks, which PowerShell reads as `'` and `"`.
_LEFT, _RIGHT, _LOW = chr(0x2018), chr(0x2019), chr(0x201E)


@pytest.mark.parametrize(
    "command",
    [
        "manuscript-guard set st''age drafting",
        'manuscript-guard s""et stage drafting',
        "mgu''ard set stage drafting",
        "manuscript-guard set st\\age drafting",
        f"manuscript-guard set st{_LEFT}{_RIGHT}age drafting",
        f"manuscript-guard set stage {_LOW}drafting{chr(0x201C)}",
        f"m{chr(0x201C)}{chr(0x201D)}guard set stage drafting",
    ],
)
def test_words_the_shell_puts_together_are_read_together(
    tmp_path: Path, command: str, monkeypatch, capsys
) -> None:
    """Each moves a project at submission back to drafting once the shell has taken the
    quotation marks out; the raw text names no watched key or no tool."""
    _project(tmp_path)
    assert _decision(_hook(tmp_path, command, monkeypatch, capsys)) == "ask", command
