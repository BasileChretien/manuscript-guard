"""`manuscript-guard set`: one setting of paper.yaml written, every other byte kept.

The file is the author's and most of it is comments, so `set` edits its text and reads the
result back before writing it (DESIGN.md, "One setting is written, and the file kept").
Each refusal leaves the file as it was, byte for byte.
"""

from __future__ import annotations

import json
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
        "manuscript-guard set stage finished",
        "manuscript-guard set target_journal design",
        "manuscript-guard stages && echo set stage design",
    ],
)
def test_moving_the_stage_on_or_setting_anything_else_is_not_asked(
    tmp_path: Path, command: str, monkeypatch, capsys
) -> None:
    (tmp_path / "paper.yaml").write_text("schema: manuscript-guard/paper/1\ntitle: A\n"
                                         "stage: drafting\n", encoding="utf-8")  # fmt: skip
    assert _hook(tmp_path, command, monkeypatch, capsys) is None


def test_a_project_with_no_stage_is_at_drafting(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "paper.yaml").write_text("schema: manuscript-guard/paper/1\ntitle: A\n",
                                         encoding="utf-8")  # fmt: skip
    command = "manuscript-guard set stage analysis"
    assert _decision(_hook(tmp_path, command, monkeypatch, capsys)) == "ask"
    assert _hook(tmp_path, "manuscript-guard set stage submission", monkeypatch, capsys) is None
