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

from manuscript_guard.contracts import (
    ContractError,
    Unreadable,
    load_namespace,
    load_project,
    read_structured,
    read_text,
)
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


# ---------------------------------------------------------------- the text of a manuscript file

#: What `Path.read_text` folds and what it leaves: both line endings, alone and mixed, and a
#: mark at the top, which stays in the text.
AS_WRITTEN = {
    "unix": b"one\ntwo\n",
    "windows": b"one\r\ntwo\r\n",
    "old mac": b"one\rtwo\r",
    "mixed": b"one\r\ntwo\rthree\n\r\nfour",
    "a return before a return and a feed": b"one\r\r\ntwo",
    "marked": b"\xef\xbb\xbf# Title\r\n",
    "accented": "Café society.\r\n".encode(),
    "empty": b"",
}


@pytest.mark.parametrize("case", list(AS_WRITTEN))
def test_a_manuscript_file_is_read_as_it_always_was(case: str, tmp_path: Path) -> None:
    """Every position a gate reports is an offset into this text, so a file that is UTF-8
    reads exactly as `Path.read_text` gave it."""
    path = tmp_path / "main.md"
    path.write_bytes(AS_WRITTEN[case])

    assert read_text(path) == path.read_text(encoding="utf-8")


def test_a_manuscript_file_in_a_code_page_is_refused_with_where_to_look(tmp_path: Path) -> None:
    """Saved as "ANSI", with one accented letter. The error is the one `check` prints and the
    hooks pass on, and it carries the file and the line for a finding to be placed at."""
    path = tmp_path / "main.md"
    path.write_bytes(b"# Title\n\nCaf\xe9 society.\n")

    with pytest.raises(Unreadable) as raised:
        read_text(path)
    error = raised.value
    reason = "cannot read as UTF-8: the byte 0xe9 on line 3 is not UTF-8. Save the file as UTF-8."
    assert isinstance(error, ContractError)
    assert str(error) == f"{path}: {reason}"
    assert (error.path, error.reason, error.line) == (path, reason, 3)


def test_a_manuscript_file_in_utf16_has_no_line_to_point_at(tmp_path: Path) -> None:
    path = tmp_path / "main.md"
    path.write_bytes("# Title\n\nText.\n".encode("utf-16"))

    with pytest.raises(Unreadable, match="cannot read as UTF-8: the file is UTF-16") as raised:
        read_text(path)
    assert raised.value.line is None


@pytest.mark.parametrize("there", [True, False], ids=["a folder", "nothing"])
def test_a_manuscript_file_that_cannot_be_opened_is_refused_in_a_sentence(
    there: bool, tmp_path: Path
) -> None:
    path = tmp_path / "main.md"
    if there:
        path.mkdir()

    with pytest.raises(Unreadable) as raised:
        read_text(path)
    assert str(raised.value).startswith(f"{path}: cannot read: ")
    assert raised.value.line is None


def test_a_structured_file_is_refused_with_the_same_error(tmp_path: Path) -> None:
    """One reader under both, so a ledger and a manuscript file are refused in one sentence."""
    path = tmp_path / "ledger.yaml"
    path.write_bytes(b"who: Ren\xe9e\n")

    with pytest.raises(Unreadable) as raised:
        read_structured(path)
    assert (raised.value.path, raised.value.line) == (path, 1)


# ---------------------------------------------------------------- a setting only a gate reads

#: A key of `paper.yaml` that no command needs before the gates run, in a shape the schema
#: refuses. The schema's finding names the key. The gate that read the value raised on it,
#: `TypeError: 'int' object is not iterable`, which was reported as a fault of the tool.
NOT_THE_SHAPE = {
    "terms, a number": ("terms: 5\n", "terms"),
    "terms, one word": ("terms: CYP3A4\n", "terms"),
    "conventions, a word": ("conventions: abc\n", "conventions"),
    "conventions, a number": ("conventions: 5\n", "conventions"),
    "conventions, a list of words": ("conventions:\n  - abc\n", "conventions/0"),
    "conventions, no reason": ("conventions:\n  - pattern: abc\n", "conventions/0"),
    "conventions, a pattern that is a number": (
        "conventions:\n  - pattern: 5\n    why: because\n",
        "conventions/0/pattern",
    ),
    "guideline, a number": ("reporting_guideline: 5\n", "reporting_guideline"),
    "guideline, one word": ("reporting_guideline: STROBE\n", "reporting_guideline"),
    "review, a list": ("review: [1]\n", "review"),
    "review, a number": ("review: 5\n", "review"),
    "review, rounds in words": ("review:\n  rounds_required: two\n", "review/rounds_required"),
    "review, no rounds": ("review:\n  rounds_required: 0\n", "review/rounds_required"),
}


@pytest.mark.parametrize("case", list(NOT_THE_SHAPE))
def test_a_setting_in_the_wrong_shape_is_the_schemas_to_report_and_is_not_read(
    case: str, tmp_path: Path
) -> None:
    """The gates run as if the key were not set, and the schema's finding is what is said."""
    from manuscript_guard.classify import Classifier
    from manuscript_guard.gates.review import DEFAULT_ROUNDS_REQUIRED, rounds_required

    written, where = NOT_THE_SHAPE[case]
    project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    assert [f.code for f in report.failures] == ["schema-violation"]
    assert report.failures[0].message.startswith(f"{where}: ")
    assert project.extra_terms == ()
    assert project.extra_conventions == ()
    assert project.reporting_guidelines == ()
    assert rounds_required(project) == DEFAULT_ROUNDS_REQUIRED
    Classifier.load(project.extra_conventions, project.extra_terms)


def test_a_list_keeps_the_entries_the_schema_accepts(tmp_path: Path) -> None:
    """One entry in the wrong shape does not take the others with it: dropping a convention
    that was written correctly would report every number it accounts for."""
    written = (
        "terms: [CYP3A4, 5]\n"
        "reporting_guideline: [STROBE, 5]\n"
        "conventions:\n"
        "  - pattern: half-normal\n"
        "    why: a name\n"
        "  - abc\n"
        "review:\n"
        "  rounds_required: 3\n"
    )
    from manuscript_guard.gates.review import rounds_required

    project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    assert len(report.failures) == 3
    assert project.extra_terms == ("CYP3A4",)
    assert project.reporting_guidelines == ("STROBE",)
    assert project.extra_conventions == ({"pattern": "half-normal", "why": "a name"},)
    assert rounds_required(project) == 3


#: A pattern that does not compile, and what the compiler says of it. The second is not the
#: compiler's own error but a `ValueError`: the check for one let it past, and since it is
#: made where the project is loaded, every command ended in a traceback and the hooks in
#: silence, where the gate had at least reported it.
NO_PATTERN = {
    "[0-9": "unterminated character set",
    "(?a)(?u)x": "ASCII and UNICODE flags are incompatible",
}


@pytest.mark.parametrize("pattern", list(NO_PATTERN))
def test_a_pattern_that_is_no_regular_expression_is_a_finding_that_names_it(
    pattern: str, tmp_path: Path
) -> None:
    """The schema can only say that a pattern is text. Compiling it raised in the gate, "G2
    could not run: error: unterminated character set at position 0", and nothing named the
    entry; `explain` and `bind` ended in a traceback. The entry is not read, like one the
    schema refuses, and the one beside it is."""
    from manuscript_guard.classify import Classifier

    written = (
        "conventions:\n"
        "  - pattern: half-normal\n"
        "    why: a name\n"
        f"  - pattern: '{pattern}'\n"
        "    why: a count\n"
    )
    project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    (failure,) = report.failures
    assert (failure.gate, failure.code) == ("G0", "schema-violation")
    assert failure.path == tmp_path / "paper" / "paper.yaml"
    assert failure.message.startswith(
        f"conventions/1/pattern: {pattern!r} is not a regular expression: {NO_PATTERN[pattern]}"
    )
    assert project.extra_conventions == ({"pattern": "half-normal", "why": "a name"},)
    Classifier.load(project.extra_conventions, project.extra_terms)


def test_rounds_required_is_read_beside_an_entry_the_schema_refuses(tmp_path: Path) -> None:
    """Of settings, as of a list, the entries the schema accepts are read. Dropping the
    whole of `review:` for one mistyped key beside it asked for two rounds where the paper
    asks for five, and `review --submission` answered 0 where it had answered 1."""
    from manuscript_guard.gates.review import rounds_required

    written = "review:\n  rounds_required: 5\n  round_required: 1\n"
    project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    assert [f.code for f in report.failures] == ["schema-violation"]
    assert project.setting("review") == {"rounds_required": 5}
    assert rounds_required(project) == 5


def test_a_convention_can_be_named_and_the_classifier_cites_that_name(tmp_path: Path) -> None:
    """`id` names a convention. The classifier has always named the rule by it, and the
    schema refused it, so a project that named one failed with nothing else wrong; from
    #135 the entry was not read at all. The schema allows it now (Basile, 2026-10-03)."""
    from manuscript_guard.classify import Classifier

    written = (
        "conventions:\n"
        "  - id: half-normal\n"
        "    pattern: half-normal\n"
        "    why: a name\n"
        "  - pattern: half-life\n"
        "    why: a name\n"
    )
    project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    assert report.failures == ()
    assert project.extra_conventions[0] == {
        "id": "half-normal",
        "pattern": "half-normal",
        "why": "a name",
    }
    named = Classifier.load(project.extra_conventions, project.extra_terms).conventions
    ids = {rule.id for rule in named if rule.id.startswith("project:")}
    assert ids == {"project:half-normal", "project:half-life"}, "without a name, its pattern"


@pytest.mark.parametrize("name", ["5", "''", "[half-normal]", "'   '", '"first\\nsecond"'])
def test_a_name_that_is_not_text_is_the_schemas_to_report(name: str, tmp_path: Path) -> None:
    """A name the schema refuses is its finding, at the entry, and the entry is not read: a
    convention with a name in the wrong shape exempts nothing until it is put right."""
    written = f"conventions:\n  - id: {name}\n    pattern: half-normal\n    why: a name\n"
    project, report = load_project(a_project(tmp_path / "paper", PAPER + written))

    assert [f.code for f in report.failures] == ["schema-violation"]
    assert report.failures[0].message.startswith("conventions/0/id: ")
    assert project.extra_conventions == ()


#: Each written between double quotation marks, as YAML reads them: `\a` is U+0007, `\e`
#: U+001B. The place `check` names and the character it names there.
CONTROL = {
    "title": ('title: "Effects of \\alpha-blockers"\n', "title", "U+0007"),
    "short title": ('short_title: "\\alpha-blockers"\n', "short_title", "U+0007"),
    "keyword": ('keywords:\n  - plain\n  - "\\escape"\n', "keywords/1", "U+001B"),
    "one keyword": ('keywords: "\\alpha"\n', "keywords", "U+0007"),
}


@pytest.mark.parametrize("case", list(CONTROL))
def test_a_control_character_in_what_the_document_prints_is_a_finding(
    case: str, tmp_path: Path
) -> None:
    """A document cannot carry it, and `check` passed it: the build wrote a .docx Word will
    not open. A line break is not one: the build folds lines into one."""
    written, where, character = CONTROL[case]
    paper = PAPER if case != "title" else PAPER.replace('title: "A study"\n', "")
    project, report = load_project(a_project(tmp_path / "paper", paper + written))

    # One keyword where a list is expected is also the schema's finding for its shape.
    found = [f for f in report.failures if "control character" in f.message]
    assert [(f.code, f.message.split(",")[0]) for f in found] == [
        ("schema-violation", f"{where}: holds the control character {character}")
    ]


def test_a_title_over_several_lines_is_no_finding(tmp_path: Path) -> None:
    written = 'short_title: "First\nsecond"\nkeywords: ["a\tb"]\n'
    _project, report = load_project(a_project(tmp_path / "paper", PAPER + written))
    assert report.failures == ()


@pytest.mark.parametrize(
    ("keywords", "printed"),
    [
        (5, None),
        (2.5, None),
        (True, None),
        # One word typed where a list is expected, which YAML reads as text.
        ("pharmacovigilance", ["pharmacovigilance"]),
        ("R", ["R"]),
        # Text with nothing in it is no keyword: "**Keywords.**" with nothing after it.
        ("", None),
        ("   ", None),
        ([5, "signal"], ["5", "signal"]),
        (["pharmacovigilance", 2019], ["pharmacovigilance", "2019"]),
        ([False, "cGMP"], ["False", "cGMP"]),
        # Colons typed where the dashes belong: settings whose names are the keywords.
        (
            {"pharmacovigilance": None, "hepatotoxicity": None},
            ["pharmacovigilance", "hepatotoxicity"],
        ),
    ],
)
def test_keywords_in_the_wrong_shape_do_not_stop_a_build_and_none_is_dropped_from_a_list(
    keywords: object, printed: list[str] | None, project: Path
) -> None:
    """`keywords: 5` ended a build with `--skip-checks`, and the title page of the pack, in
    `TypeError: 'int' object is not iterable`: the one key the build reads as a list. A
    number is not printed now. One word where a list is expected was printed letter by
    letter, then for a while not at all, which lost it from the document; it is printed
    whole, as the one keyword it is (Basile, 2026-10-03).

    An entry of a list that is not text is printed as it was: `2019`, which YAML reads as a
    number, reached an unchecked document and must not leave it without a word."""
    import yaml

    from manuscript_guard.build.document import _front_matter
    from manuscript_guard.build.submission import title_page

    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["keywords"] = keywords
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    loaded, report = load_project(project)
    assert "schema-violation" in {f.code for f in report.failures}

    header, page = _front_matter(loaded), title_page(loaded)
    if printed:
        assert "keywords: [" + ", ".join(f'"{word}"' for word in printed) + "]\n" in header
        assert "**Keywords.** " + "; ".join(printed) + "\n" in page
    else:
        assert "keywords:" not in header
        assert "**Keywords.**" not in page
