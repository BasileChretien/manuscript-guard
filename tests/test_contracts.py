"""The files read before any gate runs, and what is said of one that cannot be used.

`paper.yaml`, `authors.yaml`, the results fragments and the two ledgers are read before there
is a gate to report on them, so a fault in one of them is not a finding: it is an error,
`ContractError`, whose sentence `check` prints before it exits 2, and which the submission
guard refuses with. Anything else raised there is a traceback for the author and silence from
the hooks, so each shape below is held to that one error, and to a sentence that names the
file and says what is wrong with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.contracts import ContractError, load_namespace, load_project, read_structured
from manuscript_guard.policy import DRAFTING, SUBMISSION, resolve_stage

PAPER = 'schema: manuscript-guard/paper/1\ntitle: "A study"\nenglish_variant: en-GB\n'


def a_project(root: Path, paper: str | bytes = PAPER) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    data = paper if isinstance(paper, bytes) else paper.encode("utf-8")
    (root / "paper.yaml").write_bytes(data)
    return root


def refusal(path: Path) -> str:
    with pytest.raises(ContractError) as raised:
        read_structured(path)
    return str(raised.value)


def refused_project(root: Path) -> str:
    with pytest.raises(ContractError) as raised:
        load_project(root)
    return str(raised.value)


# ---------------------------------------------------------------- a file that is not UTF-8


@pytest.mark.parametrize("name", ["hand.json", "ledger.yaml"])
def test_a_file_in_a_code_page_is_refused_in_a_sentence(name: str, tmp_path: Path) -> None:
    """An accented name saved from an editor that writes the code page, which is the usual way."""
    path = tmp_path / name
    path.write_bytes('{"a": 1,\n "b": 2,\n "who": "Renée"}\n'.encode("cp1252"))

    said = refusal(path)
    assert said.startswith(f"{path}: cannot read as UTF-8: ")
    assert "the byte 0xe9 on line 3" in said, "where to look, in the editor's own terms"
    assert "Save the file as UTF-8" in said


def test_the_line_is_counted_through_a_long_file(tmp_path: Path) -> None:
    """A decoder fed in pieces reports a place within the piece; the line is of the file."""
    path = tmp_path / "ledger.yaml"
    lines = [f"k{n}: {'x' * 60}\n".encode("ascii") for n in range(1, 2001)]
    lines[1499] = b"k1500: caf\xe9\n"
    path.write_bytes(b"".join(lines))

    assert "the byte 0xe9 on line 1500" in refusal(path)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be", "utf-32"])
def test_a_file_with_the_mark_of_another_encoding_is_named_for_it(
    encoding: str, tmp_path: Path
) -> None:
    """Windows PowerShell 5 writes UTF-16 for `>`, with the mark that says so."""
    marks = {"utf-16-be": b"\xfe\xff"}
    path = tmp_path / "hand.json"
    path.write_bytes(marks.get(encoding, b"") + '{"a": 1}'.encode(encoding))

    said = refusal(path)
    assert said.startswith(f"{path}: cannot read as UTF-8: ")
    assert f"the file is {encoding[:6].upper()}" in said
    assert "Save the file as UTF-8" in said


def test_the_bytes_of_the_report_are_utf16_and_are_refused(tmp_path: Path) -> None:
    """The three bytes this was found with: a UTF-16 mark and half of a brace."""
    path = tmp_path / "hand.json"
    path.write_bytes(b"\xff\xfe\x7b")

    assert "the file is UTF-16" in refusal(path)


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"], ids=["LF", "CRLF", "CR"])
def test_the_line_is_counted_as_the_file_ends_its_lines(ending: str, tmp_path: Path) -> None:
    path = tmp_path / "ledger.yaml"
    path.write_bytes(ending.join(["a: 1", "b: 2", "c: caf\xe9", ""]).encode("cp1252"))

    assert "the byte 0xe9 on line 3" in refusal(path)


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"], ids=["LF", "CRLF", "CR"])
@pytest.mark.parametrize("mark", [b"", b"\xef\xbb\xbf"], ids=["plain", "marked"])
def test_utf8_is_still_read_whatever_its_line_endings(
    mark: bytes, ending: str, tmp_path: Path
) -> None:
    """With the mark of UTF-8 in front as well, which YAML has always been read through."""
    path = tmp_path / "ledger.yaml"
    path.write_bytes(mark + ending.join(["who: Renée", "text: |", "  one", "  two", ""]).encode())

    assert read_structured(path) == {"who": "Renée", "text": "one\ntwo\n"}


# ---------------------------------------------------------------- a value the parser will not make


@pytest.mark.parametrize(
    "written",
    ["verified_on: 2026-09-31\n", "verified_on: 2026-13-01\n", "x: &again [*again]\n"],
    ids=["no such day", "no such month", "a list that holds itself"],
)
def test_a_value_the_parser_will_not_make_is_refused_in_a_sentence(
    written: str, tmp_path: Path
) -> None:
    """A date that does not exist, typed without quotes. YAML takes it for a date, and the
    making of it fails with an error that is not one of the parser's own: `ValueError`, which
    went past the two that were caught. What it says is Python's and changes with the version,
    so only the sentence around it is held here."""
    path = tmp_path / "ledger.yaml"
    path.write_text(written, encoding="utf-8")

    assert refusal(path).startswith(f"{path}: cannot parse: ")


def test_a_file_that_cannot_be_opened_is_refused_in_a_sentence(tmp_path: Path) -> None:
    """A folder under the name stands in for a file the system will not hand over."""
    path = tmp_path / "hand.json"
    path.mkdir()

    assert refusal(path).startswith(f"{path}: cannot read: ")


def test_a_fragment_that_is_not_utf8_stops_the_load_with_that_sentence(tmp_path: Path) -> None:
    """The route `check` takes to it, which is where the traceback came from."""
    root = a_project(tmp_path / "paper")
    (root / "results").mkdir()
    (root / "results" / "hand.json").write_bytes(b"\xff\xfe\x7b")
    project, _report = load_project(root)

    with pytest.raises(ContractError, match="hand.json: cannot read as UTF-8"):
        load_namespace(project)


@pytest.mark.parametrize("name", ["paper.yaml", "authors.yaml"])
def test_a_project_file_that_is_not_utf8_stops_the_load(name: str, tmp_path: Path) -> None:
    root = a_project(tmp_path / "paper")
    (root / name).write_bytes(PAPER.encode() + "short_title: Étude\n".encode("cp1252"))

    said = refused_project(root)
    assert said.startswith(f"{root / name}: cannot read as UTF-8: ")
    assert "the byte 0xc9 on line 4" in said


# ---------------------------------------------------------------- a paper.yaml that is not settings


@pytest.mark.parametrize(
    ("written", "held"),
    [
        ("- a\n- b\n", "a list"),
        ("[]\n", "a list"),
        ("title:My paper\nstage:drafting\n", "text"),
        ("42\n", "a number"),
        ("no\n", "a yes or no"),
    ],
)
def test_a_paper_file_that_is_not_settings_is_refused_in_a_sentence(
    written: str, held: str, tmp_path: Path
) -> None:
    root = a_project(tmp_path / "paper", written)

    said = refused_project(root)
    assert said.startswith(f"{root / 'paper.yaml'}: holds {held} where ")
    assert "`key: value`" in said, "what was expected, as it is written"


def test_a_colon_with_no_space_after_it_is_named_as_the_likely_cause(tmp_path: Path) -> None:
    """YAML reads `title:My paper` as text, and a whole file of such lines as one text."""
    root = a_project(tmp_path / "paper", "title:My paper\nstage:drafting\n")

    assert "no space after the colon" in refused_project(root)


def test_an_empty_paper_file_is_still_a_project_with_everything_missing(tmp_path: Path) -> None:
    """Nothing written yet is not a fault of shape: the schema says what to add."""
    project, report = load_project(a_project(tmp_path / "paper", ""))

    assert project.paper == {}
    assert {f.code for f in report.failures} == {"schema-violation"}


# ---------------------------------------------------------------- folders that cannot be found


@pytest.mark.parametrize(
    ("written", "said"),
    [
        ("paths: [results]\n", "`paths` holds a list where "),
        ("paths: results\n", "`paths` holds text where "),
        ("paths:\n", "`paths` holds nothing where "),
        ("paths:\n  results: 5\n", "`paths.results` holds a number where the name of a folder"),
        ("paths:\n  results:\n", "`paths.results` holds nothing where the name of a folder"),
        ("paths:\n  figures: [a]\n", "`paths.figures` holds a list where the name of a folder"),
    ],
)
def test_folders_that_cannot_be_found_are_refused_in_a_sentence(
    written: str, said: str, tmp_path: Path
) -> None:
    """Every command asks the project where its folders are, and none can go on without."""
    root = a_project(tmp_path / "paper", PAPER + written)

    assert refused_project(root).startswith(f"{root / 'paper.yaml'}: {said}")


def test_folders_given_by_name_are_still_found(tmp_path: Path) -> None:
    root = a_project(tmp_path / "paper", PAPER + "paths:\n  results: output\n")
    project, report = load_project(root)

    assert report.ok
    assert project.path("results") == root / "output"
    assert project.path("figures") == root / "figures"


# ---------------------------------------------------------------- a stage that is not one


def test_a_stage_that_is_not_one_is_refused_in_a_sentence(tmp_path: Path) -> None:
    """`draft` for `drafting`. The stage decides which findings fail, so there is no verdict."""
    root = a_project(tmp_path / "paper", PAPER + "stage: draft\n")
    project, report = load_project(root)
    assert not report.ok, "the schema has it too, and that finding was never reached"

    with pytest.raises(ContractError) as raised:
        resolve_stage(project, None, False)
    said = str(raised.value)
    assert said.startswith(f"{root / 'paper.yaml'}: `stage` is 'draft', which is not a stage")
    assert "design, analysis, drafting, internal-review, submission" in said


def test_a_stage_that_is_not_one_is_not_asked_for_where_another_is_given(tmp_path: Path) -> None:
    """`--submission` and `--stage` say which stage, so the check runs and reports the line."""
    project, _report = load_project(a_project(tmp_path / "paper", PAPER + "stage: draft\n"))

    assert resolve_stage(project, None, True) == SUBMISSION
    assert resolve_stage(project, DRAFTING, False) == DRAFTING
